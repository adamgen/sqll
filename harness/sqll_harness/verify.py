"""Run locally each check that CI (.github/workflows/ci.yml) runs.

scripts/verify runs this module with the Python of the harness venv. Each
check is a shell command, run with "sh -ec" from the repository root. Each
command is a copy of a CI step. harness/tests/test_verify.py fails (drift())
if a CI step is not in checks() or in CI_ONLY, if a command line of a CI
step, with its env, is not the same as the local command lines, if the
run text of a CI_ONLY step is not the text in CI_ONLY_RUN, if a job or
step "if" is not the text in JOB_IF or STEP_IF, if job needs, job outputs,
or step ids are not JOB_NEEDS, JOB_OUTPUTS, or STEP_IDS, if the workflow
"on" or "concurrency" is not WORKFLOW_ON or WORKFLOW_CONCURRENCY, or if a
workflow, job, or step key is not known.

Output: one line for each check, a log for each check in out/verify/, and
out/verify.json. With --quick: out/verify-quick/ and out/verify-quick.json,
so a quick run does not delete the result of a full run.
"""

import argparse
import fcntl
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import preflight
from .paths import REPO_ROOT

CI_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"
OUT_DIR = REPO_ROOT / "out"
REPORT = OUT_DIR / "report.json"
LOCK = OUT_DIR / "verify.lock"


def result_paths(quick: bool) -> tuple[Path, Path]:
    """Return the result file and the log folder of a mode."""
    name = "verify-quick" if quick else "verify"
    return OUT_DIR / f"{name}.json", OUT_DIR / name


UV = "uv run --frozen --project harness"

# CI steps that have no local check: CI mechanics only, and the full
# benchmark (its local copy is scripts/bench; see BENCH_LOCAL).
CI_ONLY = {
    "changes: actions/checkout": "checkout",
    "changes: Changed files": "documents-only test; locally all checks run",
    "image: actions/checkout": "checkout",
    "image: tag": "image tag and shard matrix",
    "image: docker/login-action": "registry login",
    "image: find": "image lookup in the registry",
    "image: docker/setup-buildx-action": "image build; locally scripts/setup",
    "image: docker/build-push-action": "image build; locally scripts/setup",
    "lint: actions/checkout": "checkout",
    "lint: git config --global --add safe.directory '*'": "container user",
    "test: actions/checkout": "checkout",
    "test: git config --global --add safe.directory '*'": "container user",
    "test: actions/upload-artifact": "artifact upload",
    "report: actions/checkout": "checkout",
    "report: git config --global --add safe.directory '*'": "container user",
    "report: actions/download-artifact": "artifact download",
    "report: Merge": "merge of shards; the unsharded run does the known-failure"
    " check on all cases",
    "report: actions/upload-artifact": "artifact upload",
    "report: Check test jobs": "result of the shard jobs; locally the run check",
    "dialect-oracle: actions/checkout": "checkout",
    "dialect-oracle: git config --global --add safe.directory '*'": "container user",
    "dialect-oracle: actions/download-artifact": "artifact download",
    "dialect-oracle: actions/upload-artifact": "artifact upload",
    "bench-smoke: actions/checkout": "checkout",
    "bench-smoke: git config --global --add safe.directory '*'": "container user",
    "bench-smoke: actions/upload-artifact": "artifact upload",
    "bench-full: actions/checkout": "checkout",
    "bench-full: git config --global --add safe.directory '*'": "container user",
    "bench-full: Run the benchmark shard": "full benchmark shard; locally"
    " scripts/bench (BENCH_LOCAL, no shard)",
    "bench-full: actions/upload-artifact": "artifact upload",
    "bench-merge: actions/checkout": "checkout",
    "bench-merge: actions/download-artifact": "artifact download",
    "bench-merge: Merge": "merge of the full benchmark shards; locally"
    " scripts/bench writes one report",
    "bench-merge: Check the merged report": "check of the merged full report;"
    " locally bench run checks its report",
    "bench-merge: actions/upload-artifact": "artifact upload",
}

_SAFE_DIRECTORY = "git config --global --add safe.directory '*'"

# The run text (and step env) of each CI_ONLY step that has "run". drift()
# fails if CI changes it, because these commands can also check something
# (for example the shard merge).
CI_ONLY_RUN = {
    "changes: Changed files": 'python3 ci/changes.py "$EVENT"',
    "image: tag": (
        'echo "image=$IMAGE_REPO:$(python3 ci/image_tag.py)" >> "$GITHUB_OUTPUT"\n'
        'echo "matrix=$(python3 ci/matrix.py)" >> "$GITHUB_OUTPUT"\n'
        'echo "bench_matrix=$(python3 ci/bench_matrix.py)" >> "$GITHUB_OUTPUT"'
    ),
    "image: find": (
        'if docker buildx imagetools inspect "$IMAGE" > /dev/null 2>&1; then\n'
        'echo "Image $IMAGE exists. The build is not necessary."\n'
        'echo "exists=true" >> "$GITHUB_OUTPUT"\n'
        "else\n"
        'echo "Image $IMAGE does not exist. Build and push it."\n'
        'echo "exists=false" >> "$GITHUB_OUTPUT"\n'
        "fi"
    ),
    **{
        f"{job}: {_SAFE_DIRECTORY}": _SAFE_DIRECTORY
        for job in (
            "lint",
            "test",
            "report",
            "dialect-oracle",
            "bench-smoke",
            "bench-full",
        )
    },
    "report: Merge": (
        "uv run --frozen --project harness sqll-harness merge"
        " --expect ci/matrix.json out/shards/*.json"
    ),
    "report: Check test jobs": (
        'echo "A test job did not succeed: ${{ needs.test.result }}"\nexit 1'
    ),
    "bench-full: Run the benchmark shard": (
        f"{UV} sqll-harness bench run --profile full"
        " --shard ${{ matrix.shard }} --out out/bench-shards/${{ matrix.name }}.json"
    ),
    "bench-merge: Merge": (
        f"{UV} sqll-harness bench merge --expect ci/bench-matrix.json"
        " out/bench-shards/*.json --out out/bench.json"
    ),
    "bench-merge: Check the merged report": (
        f"{UV} sqll-harness bench check out/bench.json"
    ),
}
CI_ONLY_RUN_ENV = {
    "changes: Changed files": {"EVENT": "${{ github.event_name }}"},
    "image: find": {"IMAGE": "${{ steps.tag.outputs.image }}"},
}

# The "if" of each CI job that has one. A job "if" can skip all checks of a
# job, thus drift() fails if a job "if" is not this text. The lint job has
# no "if": its unit tests read documents (for example STATUS.md). The test
# and report jobs run unless "full" is 'false', so an empty output (for
# example a broken outputs map) gives a full run.
_FULL = "needs.changes.outputs.full != 'false'"
_NOT_PR = "github.event_name != 'pull_request'"
JOB_IF = {
    "test": _FULL,
    "report": f"always() && {_FULL} && needs.image.result == 'success'",
    "bench-smoke": _FULL,
    "bench-full": _NOT_PR,
    "bench-merge": _NOT_PR,
}

# The needs of each CI job that has needs. A job "if" and the order of
# jobs use them, thus drift() fails if they change.
JOB_NEEDS = {
    "lint": ["image"],
    "test": ["changes", "image"],
    "report": ["changes", "image", "test"],
    "dialect-oracle": ["image", "report"],
    "bench-smoke": ["changes", "image"],
    "bench-full": ["image"],
    "bench-merge": ["image", "bench-full"],
}

# The outputs of each CI job that has outputs, and the id of each CI step
# that has an id. The job "if" text uses them, thus drift() fails if they
# change.
JOB_OUTPUTS = {
    "changes": {"full": "${{ steps.changes.outputs.full }}"},
    "image": {
        "image": "${{ steps.tag.outputs.image }}",
        "matrix": "${{ steps.tag.outputs.matrix }}",
        "bench_matrix": "${{ steps.tag.outputs.bench_matrix }}",
    },
}
STEP_IDS = {
    "changes: Changed files": "changes",
    "image: tag": "tag",
    "image: find": "find",
}

# The "if" of each CI step that has one. A step "if" can skip a check, thus
# drift() fails if a step "if" is not this text.
_NO_IMAGE = "steps.find.outputs.exists == 'false'"
STEP_IF = {
    "image: docker/setup-buildx-action": _NO_IMAGE,
    "image: docker/build-push-action": _NO_IMAGE,
    "test: actions/upload-artifact": "always()",
    "report: actions/upload-artifact": "always()",
    "report: Check test jobs": "needs.test.result != 'success'",
    "dialect-oracle: actions/upload-artifact": "always()",
    "bench-smoke: actions/upload-artifact": "always()",
    "bench-full: actions/upload-artifact": "always()",
    "bench-merge: actions/upload-artifact": "always()",
}

# The events and the concurrency of the workflow. An event filter (for
# example paths-ignore) can skip all jobs, and cancel-in-progress on a push
# to main can stop a full run. Thus drift() fails if they change. PyYAML
# reads the key "on" as True.
WORKFLOW_ON = {
    "pull_request": None,
    "push": {"branches": ["main"]},
    "workflow_dispatch": None,
}
WORKFLOW_CONCURRENCY = {
    "group": "${{ github.workflow }}-${{ github.ref }}",
    "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
}

# The workflow keys that drift() knows.
WORKFLOW_KEYS = {"name", "on", True, "permissions", "concurrency", "env", "jobs"}

# The job keys that drift() knows. Another key (for example continue-on-error
# or services) can change the result of a job, so drift() fails on it.
JOB_KEYS = {
    "needs",
    "if",
    "name",
    "runs-on",
    "timeout-minutes",
    "permissions",
    "outputs",
    "strategy",
    "container",
    "steps",
    "env",
}

# The step keys that drift() knows. Another key (for example shell or
# working-directory) can change what a command does, so drift() fails on it.
STEP_KEYS = {"name", "id", "uses", "with", "run", "env", "if"}

# Workflow, job, or step env that the local commands do not need.
CI_ONLY_ENV = {"IMAGE_REPO": "image registry name; only the image job uses it"}

# Shell words and text that can hide a failure or skip a part of a check.
# No local command can have them (test_verify.py). No CI run text can have
# WEAK_TEXT or CI_WEAK_WORDS.
WEAK_WORDS = {"||", "true", ":", "--filter", "-k", "--deselect", "--lf", "exit"}
WEAK_TEXT = ("||", "set +e")
CI_WEAK_WORDS = {"||", "true", ":"}
SHELL_OPERATORS = {"||", "&&", ";", "|", "&", ";;", "(", ")"}

# The local copy of the full benchmark of CI is scripts/bench with no
# argument: its "bench run" line, without --quiet and "$@", followed by
# BENCH_SHARD_ARGS, must be the command of the CI shard step (drift()).
# "bench run" with no --profile runs the full profile (test_verify.py).
BENCH_LOCAL = "scripts/bench"
BENCH_SHARD_STEP = "bench-full: Run the benchmark shard"
BENCH_SHARD_ARGS = (
    "--profile",
    "full",
    "--shard",
    "{}",
    "--out",
    "out/bench-shards/{}.json",
)

SETUP = "setup"
REPORT_FILE = "report"


@dataclass(frozen=True)
class Check:
    name: str
    command: str
    # CI steps ("job: step") that this check does. Empty: a local check only.
    ci: tuple[str, ...] = ()
    quick: bool = False
    # SETUP: skip if the setup check failed. REPORT_FILE: skip if the run did
    # not write out/report.json.
    needs: tuple[str, ...] = ()
    # Files to delete before the command runs.
    removes: tuple[str, ...] = ()
    # (CI text, local text) replacements in the CI command before the drift
    # test compares it with the local command. Each CI text must occur.
    ci_diff: tuple[tuple[str, str], ...] = field(default=(), compare=False)


ORACLES = (
    "scripts/sqlfluff_oracle.py scripts/sqlfluff-rule-oracle"
    " scripts/sqlfluff-autofix-oracle scripts/sqlfluff-templater-oracle"
    " scripts/sqlfluff-dialect-oracle scripts/sqlfluff-case-ids"
)
ORACLE_PY = '"$SQLL_TOOLS_DIR/sqlfluff-oracle/bin/python"'
RS_PY = '"$SQLL_TOOLS_DIR/sqlfluff-rs-oracle/bin/python"'
LINT_SUBMODULE = "lint: Check that the sqlfluff submodule is clean"
AFTER = 'scripts/check-submodule "after the comparison"'


def _oracle(script: str, args: str, py: str = ORACLE_PY) -> str:
    return f"{py} scripts/{script} {args}\n{AFTER}"


def checks(jobs: int | None = None) -> list[Check]:
    jobs_arg = f" --jobs {jobs}" if jobs else ""
    rs_fixtures = "\n".join(
        [
            'py="$SQLL_TOOLS_DIR/sqlfluff-rs-oracle/bin/python"',
            '"$py" scripts/sqlfluff-dialect-oracle --rust'
            " --root harness/tests/fixtures/dialects --check-prefixes",
            '"$py" scripts/sqlfluff-rule-oracle --rust'
            " --cases 'harness/tests/fixtures/rules/*.yml' --check-prefixes",
            '"$py" scripts/sqlfluff-autofix-oracle --rust'
            " --root harness/tests/fixtures/autofix --check-prefixes",
            '"$py" scripts/sqlfluff-templater-oracle --rust'
            " --root harness/tests/fixtures/templater --check-prefixes",
        ]
    )
    rs_report = "\n".join(
        [
            'py="$SQLL_TOOLS_DIR/sqlfluff-rs-oracle/bin/python"',
            '"$py" scripts/sqlfluff-rule-oracle --rust'
            " --report out/report.json --out out/rs-oracle.jsonl",
            '"$py" scripts/sqlfluff-autofix-oracle --rust'
            " --report out/report.json --out out/rs-autofix-oracle.jsonl",
            '"$py" scripts/sqlfluff-templater-oracle --rust'
            " --report out/report.json --out out/rs-templater-oracle.jsonl",
            AFTER,
        ]
    )
    rep = (SETUP, REPORT_FILE)
    return [
        Check("setup", "scripts/setup", quick=True),
        Check(
            "submodule-before",
            'scripts/check-submodule "before the tests"',
            quick=True,
        ),
        Check(
            "tools",
            f'{UV} sqll-harness tools\n"$SQLL_TOOLS_DIR/sqruff/bin/sqruff" templaters',
            ("lint: Tools",),
            quick=True,
            needs=(SETUP,),
        ),
        Check(
            "ruff-check",
            f"{UV} ruff check harness ci {ORACLES}",
            ("lint: Lint",),
            quick=True,
        ),
        Check(
            "ruff-format",
            f"{UV} ruff format --check harness ci {ORACLES}",
            ("lint: Lint",),
            quick=True,
        ),
        Check(
            "unit-tests",
            f"SQLL_REQUIRE_TOOLS=1 {UV} pytest -q harness/tests",
            ("lint: Unit tests",),
            quick=True,
            needs=(SETUP,),
        ),
        Check(
            "fixtures-rules",
            f"{ORACLE_PY} scripts/sqlfluff-rule-oracle"
            " --cases 'harness/tests/fixtures/rules/*.yml' --check-prefixes",
            ("lint: Check the harness rule fixtures with the sqlfluff test",),
            quick=True,
            needs=(SETUP,),
        ),
        Check(
            "fixtures-autofix",
            f"{ORACLE_PY} scripts/sqlfluff-autofix-oracle"
            " --root harness/tests/fixtures/autofix --check-prefixes",
            ("lint: Check the harness autofix fixtures with the sqlfluff test",),
            quick=True,
            needs=(SETUP,),
        ),
        Check(
            "fixtures-templater",
            f"{ORACLE_PY} scripts/sqlfluff-templater-oracle"
            " --root harness/tests/fixtures/templater --check-prefixes",
            ("lint: Check the harness templater fixtures with the sqlfluff test",),
            quick=True,
            needs=(SETUP,),
        ),
        Check(
            "fixtures-dialects",
            f"{ORACLE_PY} scripts/sqlfluff-dialect-oracle"
            " --root harness/tests/fixtures/dialects --check-prefixes",
            ("lint: Check the harness dialect fixtures with the sqlfluff tests",),
            quick=True,
            needs=(SETUP,),
        ),
        Check(
            "fixtures-rust",
            rs_fixtures,
            ("lint: Check the harness fixtures with the sqlfluff test and --rust",),
            quick=True,
            needs=(SETUP,),
        ),
        Check(
            "submodule-after-tests",
            'scripts/check-submodule "after the tests"',
            (LINT_SUBMODULE,),
            quick=True,
        ),
        # One unsharded run of all suites and tools, as all shards of CI.
        Check(
            "run",
            f"{UV} sqll-harness run{jobs_arg} --out out/report.json",
            ("test: Run shard",),
            needs=(SETUP,),
            removes=("out/report.json",),
            ci_diff=(
                (
                    " --suite {} --tool {} --shard {} --out out/shards/{}.json",
                    " --out out/report.json",
                ),
            ),
        ),
        Check(
            "submodule-after-run",
            'scripts/check-submodule "after the run"',
            ("test: Check that the sqlfluff submodule is clean",),
        ),
        Check(
            "report-commit",
            "want=$(git rev-parse HEAD:third_party/sqlfluff)\n"
            "got=$(python3 -c 'import json;"
            ' print(json.load(open("out/report.json"))["sqlfluff_ref"])\')\n'
            'echo "submodule: $want, report: $got"\n'
            'test "$want" = "$got"',
            ("report: Check sqlfluff commit in the report",),
            needs=rep,
        ),
        Check(
            "summary",
            f"{UV} sqll-harness summarize out/report.json --out out/summary.json\n"
            "cat out/summary.json",
            ("report: Summary",),
            needs=rep,
        ),
        Check(
            "oracle-rules",
            _oracle(
                "sqlfluff-rule-oracle",
                "--report out/report.json --out out/oracle.jsonl",
            ),
            ("report: Compare the rule results with the sqlfluff test",),
            needs=rep,
        ),
        Check(
            "oracle-autofix",
            _oracle(
                "sqlfluff-autofix-oracle",
                "--report out/report.json --out out/autofix-oracle.jsonl",
            ),
            ("report: Compare the autofix results with the sqlfluff test",),
            needs=rep,
        ),
        Check(
            "oracle-templater",
            _oracle(
                "sqlfluff-templater-oracle",
                "--report out/report.json --out out/templater-oracle.jsonl",
            ),
            ("report: Compare the templater results with the sqlfluff test",),
            needs=rep,
        ),
        Check(
            "oracle-sqlfluff-rs",
            rs_report,
            ("report: Compare the sqlfluff-rs results with the sqlfluff tests",),
            needs=rep,
        ),
        Check(
            "recorded-summary",
            f"{UV} sqll-harness summarize out/report.json --out out/summary.json"
            " --check results/s1/summary.json",
            ("report: Check the recorded summary",),
            needs=rep,
        ),
        Check(
            "dialect-oracle-sqlfluff",
            _oracle(
                "sqlfluff-dialect-oracle",
                "--report out/report.json --out out/dialect-oracle-sqlfluff.jsonl",
            ),
            ("dialect-oracle: Compare the dialect results with the sqlfluff tests",),
            needs=rep,
        ),
        Check(
            "dialect-oracle-sqlfluff-rs",
            _oracle(
                "sqlfluff-dialect-oracle",
                "--rust --report out/report.json"
                " --out out/dialect-oracle-sqlfluff-rs.jsonl",
                RS_PY,
            ),
            ("dialect-oracle: Compare the dialect results with the sqlfluff tests",),
            needs=rep,
        ),
        # The smoke benchmark. The full benchmark is BENCH_LOCAL.
        Check(
            "bench-smoke",
            f"{UV} sqll-harness bench run --profile smoke --out out/bench.json",
            ("bench-smoke: Run the smoke benchmark",),
            needs=(SETUP,),
            removes=("out/bench.json",),
        ),
        Check(
            "submodule-after-bench",
            'scripts/check-submodule "after the benchmarks"',
            (
                "bench-smoke: Check that the sqlfluff submodule is clean",
                "bench-full: Check that the sqlfluff submodule is clean",
            ),
        ),
    ]


# --- CI file -----------------------------------------------------------------


def load_ci(path: Path = CI_FILE) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf8"))


def step_label(step: dict) -> str:
    """Return the name of a CI step: name, id, action, or first command line."""
    if "name" in step:
        return step["name"]
    if "id" in step:
        return step["id"]
    if "uses" in step:
        return step["uses"].split("@", 1)[0]
    return step["run"].strip().splitlines()[0]


def ci_steps(data: dict | None = None) -> list[tuple[str, dict, dict]]:
    """Return (key, step, job) for each step of each CI job."""
    data = load_ci() if data is None else data
    return [
        (f"{job_id}: {step_label(step)}", step, job)
        for job_id, job in data["jobs"].items()
        for step in job["steps"]
    ]


_EXPR = re.compile(r"\$\{\{\s*([^}]*?)\s*\}\}")


def step_env(step: dict, job: dict, workflow_env: dict | None = None) -> dict:
    """Return the env of a CI step: workflow, job, container, then step env,
    without CI_ONLY_ENV."""
    container = job.get("container")
    env = {
        **(workflow_env or {}),
        **(job.get("env") or {}),
        **((container.get("env") or {}) if isinstance(container, dict) else {}),
        **(step.get("env") or {}),
    }
    return {k: str(v) for k, v in env.items() if k not in CI_ONLY_ENV}


def ci_commands(step: dict, job: dict, workflow_env: dict | None = None) -> list[str]:
    """Return the shell text of a CI step, one for each static matrix entry.

    An env value replaces $NAME. An env name that the text does not use
    becomes "NAME=value " before each command line. A ${{ matrix.X }} of a
    static matrix becomes its value; another expression becomes "{}".
    """
    text = step.get("run", "").replace("\\\n", " ")
    unused = []
    for name, value in step_env(step, job, workflow_env).items():
        pattern = re.compile(rf"\$(?:{name}\b|\{{{name}\}})")
        if pattern.search(text):
            text = pattern.sub(lambda _, v=value: v, text)
        else:
            unused.append(f"{name}={shlex.quote(value)} ")
    if unused:
        prefix = "".join(unused)
        text = "\n".join(prefix + line for line in text.splitlines() if line.strip())
    include = (job.get("strategy") or {}).get("matrix") or {}
    entries = include.get("include") if isinstance(include, dict) else None
    out = []
    for entry in entries or [{}]:

        def value(m: re.Match, entry: dict = entry) -> str:
            expr = m.group(1)
            if expr.startswith("matrix.") and expr[7:] in entry:
                return str(entry[expr[7:]])
            return "{}"

        out.append(_EXPR.sub(value, text))
    return out


def lines(text: str) -> list[tuple[str, ...]]:
    """Return the shell words of each command line of a text."""
    text = text.replace("\\\n", " ")
    return [tuple(shlex.split(line)) for line in text.splitlines() if line.strip()]


def shell_tokens(line: str) -> list[str]:
    """Return the words and the operators (for example "||" or ";") of one
    command line."""
    lex = shlex.shlex(line, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    return list(lex)


def weak_parts(command: str) -> list[str]:
    """Return the parts of a command that can hide a failure (WEAK_*)."""
    found = {t for t in WEAK_TEXT if t in command}
    for line in command.replace("\\\n", " ").splitlines():
        found |= set(shell_tokens(line)) & WEAK_WORDS
    return sorted(found)


def _ci_only_run_drift(key: str, step: dict) -> list[str]:
    """Return the differences of a CI_ONLY step from CI_ONLY_RUN."""
    if "run" not in step:
        if key in CI_ONLY_RUN:
            return [f"{key}: CI_ONLY_RUN has a run text, but the step has none"]
        return []
    if key not in CI_ONLY_RUN:
        return [f"{key}: add its run text to CI_ONLY_RUN"]
    problems = []
    want, got = lines(CI_ONLY_RUN[key]), lines(step["run"])
    if want != got:
        problems.append(f"{key}:\n  CI:          {got}\n  CI_ONLY_RUN: {want}")
    env = {k: str(v) for k, v in (step.get("env") or {}).items()}
    if env != CI_ONLY_RUN_ENV.get(key, {}):
        problems.append(f"{key}: step env {env} is not CI_ONLY_RUN_ENV")
    return problems


def ci_weak_parts(run: str) -> list[str]:
    """Return the parts of a CI run text that can hide a failure."""
    text = run.replace("\\\n", " ")
    found = {t for t in WEAK_TEXT if t in run}
    for line in text.splitlines():
        found |= set(shell_tokens(line)) & CI_WEAK_WORDS
    return sorted(found)


def bench_local_words(script: str) -> tuple[str, ...] | None:
    """Return the words of the "sqll-harness bench run" command of
    scripts/bench, without --quiet and "$@". None if there is not exactly one
    such command, or if its last word is not "$@" (all arguments go to bench
    run, and no other word)."""
    text = script.replace("\\\n", " ")
    run = ["sqll-harness", "bench", "run"]
    found = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        command: list[str] = []
        for token in shell_tokens(line) + [";"]:
            if token not in SHELL_OPERATORS:
                command.append(token)
                continue
            if any(command[i : i + 3] == run for i in range(len(command))):
                found.append(command)
            command = []
    if len(found) != 1 or found[0][-1] != "$@":
        return None
    return tuple(w for w in found[0][:-1] if w != "--quiet")


def bench_local_drift(data: dict, script: str | None = None) -> list[str]:
    """Return the differences between the CI shard command of the full
    benchmark and BENCH_LOCAL (see BENCH_SHARD_ARGS)."""
    if script is None:
        script = (REPO_ROOT / BENCH_LOCAL).read_text(encoding="utf8")
    local = bench_local_words(script)
    if local is None:
        return [f'{BENCH_LOCAL}: no single "sqll-harness bench run ... "$@"" line']
    steps = [(s, j) for k, s, j in ci_steps(data) if k == BENCH_SHARD_STEP]
    if len(steps) != 1:
        return [f"{BENCH_SHARD_STEP}: no such CI step"]
    step, job = steps[0]
    got = lines("\n".join(ci_commands(step, job, data.get("env"))))
    want = [local + BENCH_SHARD_ARGS]
    if got != want:
        return [f"{BENCH_SHARD_STEP}:\n  CI:    {got}\n  {BENCH_LOCAL}: {want}"]
    return []


def drift(
    selected: list[Check], data: dict | None = None, bench_script: str | None = None
) -> list[str]:
    """Return each difference between the CI file and the local checks.

    For each CI step that is not in CI_ONLY, the command lines of all its
    matrix entries, in order, must be the same as the command lines of its
    local checks, in order. A word cannot move between commands. The run
    text of each CI_ONLY step must be the text in CI_ONLY_RUN. A job key
    that is not in JOB_KEYS, a step key that is not in STEP_KEYS, a
    workflow key that is not in WORKFLOW_KEYS, "defaults", a job or step
    "if" that is not in JOB_IF or STEP_IF, job needs or outputs that are not
    in JOB_NEEDS or JOB_OUTPUTS, a step id that is not in STEP_IDS, or a
    workflow "on" or "concurrency" that is not WORKFLOW_ON or
    WORKFLOW_CONCURRENCY, is a difference. A CI run text that can hide a
    failure (ci_weak_parts), and a CI shard command of the full benchmark
    that is not BENCH_LOCAL with BENCH_SHARD_ARGS (bench_script: the text of
    scripts/bench), are differences too.
    """
    data = load_ci() if data is None else data
    steps = ci_steps(data)
    problems = []
    events = data.get(True, data.get("on"))
    if events != WORKFLOW_ON or (True in data and "on" in data):
        problems.append(f"workflow: on {events!r} is not WORKFLOW_ON")
    if data.get("concurrency") != WORKFLOW_CONCURRENCY:
        problems.append(
            f"workflow: concurrency {data.get('concurrency')!r}"
            " is not WORKFLOW_CONCURRENCY"
        )
    problems += [
        f"workflow: key {k!r} is not supported by drift()"
        for k in sorted(map(str, set(data) - WORKFLOW_KEYS - {"defaults"}))
    ]
    for where, block in [("workflow", data), *data["jobs"].items()]:
        if "defaults" in block:
            problems.append(f"{where}: 'defaults' is not supported by drift()")
    for job_id, job in data["jobs"].items():
        got_if = " ".join(str(job.get("if", "")).split()) or None
        if got_if != JOB_IF.get(job_id):
            problems.append(f"{job_id}: job if {got_if!r} is not JOB_IF")
        needs = job.get("needs")
        needs = [needs] if isinstance(needs, str) else needs
        if needs != JOB_NEEDS.get(job_id):
            problems.append(f"{job_id}: job needs {needs!r} are not JOB_NEEDS")
        outputs = job.get("outputs")
        if outputs != JOB_OUTPUTS.get(job_id):
            problems.append(f"{job_id}: job outputs {outputs!r} are not JOB_OUTPUTS")
        problems += [
            f"{job_id}: job key {k!r} is not supported by drift()"
            for k in sorted(set(job) - JOB_KEYS - {"defaults"})
        ]
    for key, step, job in steps:
        problems += [
            f"{key}: step key {k!r} is not supported by drift()"
            for k in sorted(set(step) - STEP_KEYS)
        ]
        problems += [
            f"{key}: {w!r} in the CI run text can hide a failure"
            for w in ci_weak_parts(str(step.get("run", "")))
        ]
        if step.get("id") != STEP_IDS.get(key):
            problems.append(f"{key}: step id {step.get('id')!r} is not STEP_IDS")
        step_if = " ".join(str(step.get("if", "")).split()) or None
        if step_if != STEP_IF.get(key):
            problems.append(f"{key}: step if {step_if!r} is not STEP_IF")
        local = [c for c in selected if key in c.ci]
        if key in CI_ONLY:
            if local:
                problems.append(f"{key}: in CI_ONLY and in a check")
            problems += _ci_only_run_drift(key, step)
            continue
        if not local:
            problems.append(f"{key}: add a check to checks() or the step to CI_ONLY")
            continue
        text = "\n".join(ci_commands(step, job, data.get("env")))
        for check in local:
            for old, new in check.ci_diff:
                if old not in text:
                    problems.append(f"{key}: ci_diff of {check.name}: no {old!r}")
                text = text.replace(old, new)
        want = lines(text)
        got = [line for c in local for line in lines(c.command)]
        if want != got:
            problems.append(f"{key}:\n  CI:    {want}\n  local: {got}")
    keys = {key for key, _, _ in steps}
    problems += [f"CI_ONLY {k!r}: no such CI step" for k in set(CI_ONLY) - keys]
    problems += [f"STEP_IDS {k!r}: no such CI step" for k in set(STEP_IDS) - keys]
    problems += [f"STEP_IF {k!r}: no such CI step" for k in set(STEP_IF) - keys]
    problems += [
        f"CI_ONLY_RUN {k!r}: not a CI_ONLY step"
        for k in sorted(set(CI_ONLY_RUN) | set(CI_ONLY_RUN_ENV))
        if k not in CI_ONLY
    ]
    problems += [
        f"{c.name}: no CI step {k!r}" for c in selected for k in c.ci if k not in keys
    ]
    problems += [
        f"{c.name}: {w!r} can hide a failure"
        for c in selected
        for w in weak_parts(c.command)
    ]
    problems += bench_local_drift(data, bench_script)
    return problems


# --- Runner ------------------------------------------------------------------


def _git(*args: str) -> str | None:
    """Return the output of a git command, or None if it fails."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True
        )
    except OSError:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def worktree_state() -> tuple[str | None, bool | None]:
    """Return the HEAD commit and True if the worktree has no change.

    None: git failed.
    """
    status = _git("status", "--porcelain")
    return _git("rev-parse", "HEAD"), (None if status is None else status == "")


def _warn_worktree(commit: str | None, clean: bool | None) -> None:
    if commit is None or clean is None:
        print(
            "WARNING: git failed, or HEAD changed in the run."
            " This result is not for a known commit."
        )
    elif not clean:
        print(
            f"WARNING: the worktree has changes (git status). This result is"
            f" not the result of commit {commit[:12]}, and CI can differ."
        )


def _tail(path: Path, n: int = 15) -> str:
    text = path.read_text(encoding="utf8", errors="replace").splitlines()
    return "\n".join("    " + line for line in text[-n:])


def _run(command: str, log) -> int:
    """Run a command in its own process group. Stop the group on an interrupt."""
    proc = subprocess.Popen(
        ["sh", "-ec", command],
        cwd=REPO_ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        return proc.wait()
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait()


def run_checks(selected: list[Check], quick: bool) -> dict:
    _, log_dir = result_paths(quick)
    log_dir.mkdir(parents=True, exist_ok=True)
    for old in log_dir.glob("*.log"):
        old.unlink()
    failed: set[str] = set()
    results = []
    start = time.monotonic()
    width = max(len(c.name) for c in selected)
    tty = sys.stdout.isatty()
    commit, clean = worktree_state()
    _warn_worktree(commit, clean)
    for i, check in enumerate(selected, 1):
        entry = {
            "name": check.name,
            "command": check.command,
            "ci_steps": list(check.ci),
            "status": None,
            "exit_code": None,
            "seconds": 0.0,
            "reason": None,
            "log": None,
        }
        head = f"[{i:2}/{len(selected)}] {check.name:<{width}}"
        reason = None
        if SETUP in check.needs and SETUP in failed:
            reason = "the setup check failed"
        elif REPORT_FILE in check.needs and not REPORT.exists():
            reason = "the run check wrote no out/report.json"
        if reason:
            entry.update(status="skip", reason=reason)
            print(f"{head} SKIP  ({reason})", flush=True)
            results.append(entry)
            failed.add(check.name)
            continue
        if tty:
            print(f"{head} ...", end="\r", flush=True)
        for name in check.removes:
            (REPO_ROOT / name).unlink(missing_ok=True)
        log = log_dir / f"{check.name}.log"
        t0 = time.monotonic()
        with log.open("w", encoding="utf8") as fh:
            fh.write(f"$ {check.command}\n")
            fh.flush()
            code = _run(check.command, fh)
        seconds = round(time.monotonic() - t0, 1)
        status = "pass" if code == 0 else "fail"
        entry.update(
            status=status,
            exit_code=code,
            seconds=seconds,
            log=str(log.relative_to(REPO_ROOT)),
        )
        print(f"{head} {status.upper()}  {seconds:8.1f} s", flush=True)
        if code != 0:
            failed.add(check.name)
            print(f"    exit code {code}, log: {entry['log']}")
            print(_tail(log))
        results.append(entry)
    end_commit, end_clean = worktree_state()
    if commit is None or end_commit != commit:
        commit, clean = None, None
    elif clean is None or end_clean is None:
        clean = None
    else:
        clean = clean and end_clean
    ok = all(r["status"] == "pass" for r in results)
    return {
        "mode": "quick" if quick else "full",
        "full_verification": not quick,
        "result": "pass" if ok else "fail",
        "commit": commit,
        "worktree_clean": clean,
        "seconds": round(time.monotonic() - start, 1),
        "passed": sum(r["status"] == "pass" for r in results),
        "failed": sum(r["status"] == "fail" for r in results),
        "skipped": sum(r["status"] == "skip" for r in results),
        "checks": results,
    }


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="scripts/verify",
        description="Run locally each check that CI runs. Writes out/verify.json"
        " and out/verify/*.log (--quick: out/verify-quick.json and"
        " out/verify-quick/*.log).",
    )
    p.add_argument("--jobs", type=_positive, help="Jobs for the harness run.")
    p.add_argument(
        "--quick",
        action="store_true",
        help="Run only the fast checks. This is not the full verification.",
    )
    p.add_argument("--list", action="store_true", help="Print the checks and stop.")
    args = p.parse_args(argv)

    selected = [c for c in checks(args.jobs) if c.quick or not args.quick]
    if args.list:
        for c in selected:
            print(f"{c.name}: {', '.join(c.ci) or '(local only)'}")
        return 0
    if preflight.check():
        return 2
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    if "SQLL_TOOLS_DIR" not in os.environ:
        os.environ["SQLL_TOOLS_DIR"] = str(REPO_ROOT / ".tools")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(
                "error: another scripts/verify runs in this checkout.",
                file=sys.stderr,
            )
            return 2
        return _main(selected, args.quick)


def _main(selected: list[Check], quick: bool) -> int:
    quick_note = "QUICK: only the fast checks. This is NOT the full verification."
    if quick:
        print(quick_note)
    result = run_checks(selected, quick)
    path, _ = result_paths(quick)
    path.write_text(json.dumps(result, indent=1) + "\n", encoding="utf8")
    print(
        f"{result['result'].upper()}: {result['passed']} passed,"
        f" {result['failed']} failed, {result['skipped']} skipped"
        f" in {result['seconds']:.0f} s. Details: {path.relative_to(REPO_ROOT)}"
    )
    _warn_worktree(result["commit"], result["worktree_clean"])
    if quick:
        print(quick_note)
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
