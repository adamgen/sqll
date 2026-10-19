"""Run locally each check that CI (.github/workflows/ci.yml) runs.

scripts/verify runs this module with the Python of the harness venv. Each
check is a shell command, run with "sh -ec" from the repository root. Each
command is a copy of a CI step. harness/tests/test_verify.py fails (drift())
if a CI step is not in checks() or in CI_ONLY, or if a command line of a CI
step, with its env, is not the same as the local command lines.

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


# CI steps that have no local check: CI mechanics only.
CI_ONLY = {
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
}

# Workflow, job, or step env that the local commands do not need.
CI_ONLY_ENV = {"IMAGE_REPO": "image registry name; only the image job uses it"}

# Shell words and text that can hide a failure or skip a part of a check.
# No local command can have them (test_verify.py).
WEAK_WORDS = {"||", "true", ":", "--filter", "-k", "--deselect", "--lf", "exit"}
WEAK_TEXT = ("||", "set +e")

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
UV = "uv run --frozen --project harness"
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


def weak_parts(command: str) -> list[str]:
    """Return the parts of a command that can hide a failure (WEAK_*)."""
    found = {t for t in WEAK_TEXT if t in command}
    found |= {w for line in lines(command) for w in line} & WEAK_WORDS
    return sorted(found)


def drift(selected: list[Check], data: dict | None = None) -> list[str]:
    """Return each difference between the CI file and the local checks.

    For each CI step that is not in CI_ONLY, the command lines of all its
    matrix entries, in order, must be the same as the command lines of its
    local checks, in order. A word cannot move between commands.
    """
    data = load_ci() if data is None else data
    steps = ci_steps(data)
    problems = []
    for key, step, job in steps:
        local = [c for c in selected if key in c.ci]
        if key in CI_ONLY:
            if local:
                problems.append(f"{key}: in CI_ONLY and in a check")
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
    problems += [
        f"{c.name}: no CI step {k!r}" for c in selected for k in c.ci if k not in keys
    ]
    problems += [
        f"{c.name}: {w!r} can hide a failure"
        for c in selected
        for w in weak_parts(c.command)
    ]
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
