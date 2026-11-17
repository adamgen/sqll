"""The exit check of S4 (parser parity: sqll passes 100% of the dialect parse
fixtures with an exact tree match).

Task T5 (the exit record gives the CI proof that sqll passes 100% of the
dialect parse fixtures with an exact tree match, and the orchestrator can
approve this stone) of this stone. Design record: docs/decisions/s4-parity.md. Exit
record: docs/decisions/s4-exit.md.

One command. Run it from the root of the repository with the harness Python:

    uv run --frozen --project harness python scripts/s4/exit.py [--check]

The inputs. A default path is relative to --root (default: the root of this
repository):

  --ci              the CI proof (default: results/S4/exit-ci.json): a push
                    run on main with conclusion success, the job
                    "dialect-oracle (sqlfluff)", and the log lines of its
                    steps "Compare the dialect results with the sqlfluff
                    tests" and "Check the S4 parser parity" (copied from the
                    GitHub job log).
  --parity          the record of the local parity run of T2 (each dialect
                    fixture of the pinned sqlfluff is one harness case, and
                    the check fails closed on each gap) of this stone
                    (default: results/S4/parity.json).
  --gate            the record of the CI gate of T3 (CI fails on each gap of
                    this stone) of this stone, with the injected gaps
                    (default: results/S4/gate.json).
  --corpus          the corpus information of T4 (the parse status of sqll
                    and sqlfluff on each corpus file is recorded, and each
                    difference has a row) of this stone
                    (default: results/S4/corpus-diff.json).
  --s1              the recorded summary of the harness
                    (default: results/s1/summary.json).
  --known-failures  the known failures of sqll
                    (default: known_failures/sqll.txt).
  git               in --root: the pinned commit (git rev-parse
                    HEAD:third_party/sqlfluff), the HEAD of the submodule,
                    scripts/check-submodule, and git diff --name-only from the
                    start of this stone (START) to the head of the CI run and
                    to HEAD. The git history must have START and the head of
                    the CI run (a shallow clone does not have them).

It writes the exit record (default: results/S4/exit.json; --out). With
--check it writes nothing, and exit code 1 if the file is not the new text.
It runs no benchmark, no harness run, and no CI job.

The exit items:

  a  2306 of 2306 dialect cases in 28 dialects pass with exact and
     no_unparsable through the shared syntax tree and the sqll adapter (design record
     section 1), in a push run on main with conclusion success.
  b  known_failures/sqll.txt has 0 dialects lines.
  c  Each sqll pass also passes in the sqlfluff dialect oracle.
  d  The pinned sqlfluff commit is PINNED, and the submodule is clean.
  e  The CI gate fails closed (the injected-gap proofs of T3).
  f  The corpus information of T4, as information only (it does not change
     the parity number).
  g  The speed rule of G3 (the text of G3 is in the constant G3): no
     parse-path change from START (design record section 5). A parse-path
     change needs the speed-check record of its task; this check then
     fails, and the exit record must give that record.

Exit code 0 if each item is met, 1 if an item is not met, and 2 if an input
is missing or not valid (no record is written).
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from sqll_harness import known_failures
from sqll_harness.paths import REPO_ROOT

FORMAT = 1
STONE = (
    "S4 (parser parity: sqll passes 100% of the dialect parse fixtures with an"
    " exact tree match)"
)
TASK = (
    "T5 (the exit record gives the CI proof that sqll passes 100% of the dialect"
    " parse fixtures with an exact tree match, and the orchestrator can approve"
    f" this stone) of {STONE}"
)
G3 = (
    "G3 (speed: each command, start time included, is as fast as reasonably"
    " possible and has a benchmark that measures sqlfluff, sqruff, and sqll on"
    " the same input. sqll is faster than sqlfluff on each benchmark, not slower"
    " than sqruff on any benchmark, and faster than sqruff on the total of all"
    " benchmarks. A change that makes a benchmark slower gives the reason."
    " Correctness is more important than speed: do not make a result wrong to"
    " make it fast)"
)
COMMAND = "uv run --frozen --project harness python scripts/s4/exit.py"
# The state when each exit item is met. Before the approval of this stone
# (2026-11-17) it was "Awaiting approval"; status/S4.md, "Approval", records
# the approval.
STATE = "Exit met"
NOT_MET = "Exit not met"

# The start of this stone (status/S4.md, "Start data"): main after the merge
# of PR #84.
START = "0fb9cdb61a4febb6d9f08b9a149c42bf3d9fdf6e"
# The pinned sqlfluff (tag 4.4.0). Only the human owner changes it.
PINNED = "0348222a3bcdb0226563f7349c5a39beb0641955"
SUBMODULE = "third_party/sqlfluff"
CHECK_SUBMODULE = "scripts/check-submodule"
CASES = 2306
DIALECTS = 28
SUITE = "dialects"
TOOL = "sqll"

WORKFLOW = "CI"
JOB = "dialect-oracle (sqlfluff)"
STEP = "Check the S4 parser parity"
ORACLE_STEP = "Compare the dialect results with the sqlfluff tests"
SUMMARY = (
    f"S4 parity: pass: sqll dialects {CASES} of {CASES} discovered cases pass in"
    f" {DIALECTS} dialects (exact {CASES}, no_unparsable {CASES}, {CASES} pass in"
    " the oracle); gaps 0"
)
ORACLE_LINE = (
    f"sqll dialects: {CASES} cases, {CASES} pass, {CASES} of them pass in the oracle"
)
# The counts of a parity output with no gap (scripts/s4/parity, "counts").
# known_failures_lines is the size of the list, not a gap; it is not here.
COUNTS = {
    "discovered_cases": CASES,
    "discovered_dialects": DIALECTS,
    "report_cases": CASES,
    "report_dialects": DIALECTS,
    "passed": CASES,
    "failed": 0,
    "skipped": 0,
    "exact": CASES,
    "no_unparsable": CASES,
    "oracle_cases": CASES,
    "oracle_passed": CASES,
    "passed_in_oracle": CASES,
    "known_failures_dialects_lines": 0,
    "gaps": 0,
}
# The parity items of design record section 3 (scripts/s4/parity, "items").
PARITY_ITEMS = (1, 2, 3, 4, 5)

# The injected-gap proofs of T3 (results/S4/gate.json): the name of each run,
# its exit code, and the gap that it must find.
GATE_RUNS = {
    "control": (0, None),
    "known-failures-dialects-line": (1, "known_failures_dialects"),
    "report-case-removed": (1, "missing"),
    "no-oracle-output": (2, None),
}

# The parse path (design record section 5): each file that `sqll parse` runs
# or that changes how it is built: the Rust packages, the workspace files, the
# build script, and the pinned grammar (the tables are made from it).
PARSE_PATH_FILES = (
    "Cargo.toml",
    "Cargo.lock",
    "rust-toolchain.toml",
    "scripts/build-sqll",
    SUBMODULE,
)
PARSE_PATH_DIRS = ("crates/", ".cargo/")

# The tree path of design record section 1.
TREE_PATH = [
    "harness/sqll_harness/suites/dialects.py: each SQL file of"
    " test/fixtures/dialects/<dialect>/ of the pinned sqlfluff with a .yml file"
    " is one case",
    "harness/sqll_harness/adapters/sqll.py: sqll parse -f json -c --templater"
    " raw --dialect D --ignore-local-config PATH",
    "crates/sqll_cli/src/parse/steps.rs: the raw templater, then"
    " sqll_syntax::parse (the frozen parse interface of the shared core) to the"
    " SyntaxTree",
    "crates/sqll_cli/src/parse/output.rs: the record of sqlfluff parse -f json"
    " from the SyntaxTree",
    "harness/sqll_harness/compare.py: process_struct of the sqlfluff test, and"
    " an exact tree match; no unparsable segment, no error, exit code 0",
    "scripts/sqlfluff-dialect-oracle --passes-of sqll: each sqll pass passes"
    " in the sqlfluff dialect tests",
]

INPUTS = {
    "ci": Path("results/S4/exit-ci.json"),
    "parity": Path("results/S4/parity.json"),
    "gate": Path("results/S4/gate.json"),
    "corpus": Path("results/S4/corpus-diff.json"),
    "s1": Path("results/s1/summary.json"),
    "known_failures": Path("known_failures/sqll.txt"),
}
OUT = Path("results/S4/exit.json")
COMMIT = re.compile(r"[0-9a-f]{40}")


class InputError(Exception):
    """An input is missing or not valid (exit code 2)."""


# The inputs.


def read_text(path: Path, name: str) -> str:
    if not path.is_file():
        raise InputError(f"{name}: {path}: no such file")
    try:
        return path.read_text(encoding="utf8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"{name}: {path}: cannot read: {exc}") from exc


def read_json(path: Path, name: str) -> dict:
    try:
        data = json.loads(read_text(path, name))
    except json.JSONDecodeError as exc:
        raise InputError(f"{name}: {path}: not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError(f"{name}: {path}: not a JSON object")
    return data


def need(doc, keys: str, kind, name: str):
    """Return the value of a dotted key, or raise InputError if a key is
    missing or the value is not of the kind."""
    value = doc
    for key in keys.split("."):
        if not isinstance(value, dict) or key not in value:
            raise InputError(f"{name}: no key {keys!r}")
        value = value[key]
    if isinstance(value, bool) and kind is not bool:
        raise InputError(f"{name}: {keys!r} is not {kind.__name__}")
    if not isinstance(value, kind):
        raise InputError(f"{name}: {keys!r} is not {kind.__name__}")
    return value


def load_inputs(paths: dict[str, Path]) -> dict:
    data = {
        name: read_json(paths[name], name)
        for name in INPUTS
        if name != "known_failures"
    }
    try:
        data["known_failures"] = known_failures.parse(
            read_text(paths["known_failures"], "known_failures"),
            str(paths["known_failures"]),
        )
    except known_failures.KnownFailuresError as exc:
        raise InputError(f"known_failures: {exc}") from exc
    ci = data["ci"]
    for key, kind in (
        ("workflow", str),
        ("run_id", int),
        ("url", str),
        ("event", str),
        ("branch", str),
        ("head_sha", str),
        ("conclusion", str),
        ("jobs_total", int),
        ("jobs_by_conclusion", dict),
        ("job.name", str),
        ("job.id", int),
        ("job.conclusion", str),
        ("steps", list),
    ):
        need(ci, key, kind, "ci")
    if not COMMIT.fullmatch(ci["head_sha"]):
        raise InputError(f"ci: head_sha {ci['head_sha']!r} is not a commit")
    for n, step in enumerate(ci["steps"]):
        for key, kind in (("name", str), ("conclusion", str), ("lines", list)):
            need(step, key, kind, f"ci: step {n}")
        if not all(isinstance(x, str) for x in step["lines"]):
            raise InputError(f"ci: step {n}: a line is not text")
    need(data["parity"], "exit_code", int, "parity")
    need(data["parity"], "output", dict, "parity")
    need(data["parity"], "output.counts", dict, "parity")
    need(data["gate"], "injected_gaps.runs", list, "gate")
    need(data["gate"], "ci", dict, "gate")
    need(data["corpus"], "status", str, "corpus")
    need(data["corpus"], "counts", dict, "corpus")
    need(data["corpus"], "counts.by_class", dict, "corpus")
    need(data["s1"], "sqlfluff_ref", str, "s1")
    need(data["s1"], f"results.{TOOL}.suites.{SUITE}", dict, "s1")
    return data


# The git facts.


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    except OSError as exc:
        raise InputError(f"git: cannot run {argv[0]}: {exc}") from exc


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return _run(["git", "-C", str(root), *args], root)


def _lines(done: subprocess.CompletedProcess) -> list[str]:
    return [x for x in (done.stdout + done.stderr).splitlines() if x.strip()]


def is_parse_path(path: str) -> bool:
    return path in PARSE_PATH_FILES or path.startswith(PARSE_PATH_DIRS)


def git_facts(root: Path, ci_head: str) -> dict:
    """Run the git commands of items d and g in root. Raise InputError if a
    commit is not in the history or a command cannot give its value."""
    for commit in (START, ci_head):
        if _git(root, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
            raise InputError(
                f"git: the commit {commit} is not in the history of {root}"
                " (a shallow clone does not have it; fetch it first)"
            )
    spec = f"HEAD:{SUBMODULE}"
    pinned = _git(root, "rev-parse", "--verify", "--quiet", spec)
    if pinned.returncode != 0 or not COMMIT.fullmatch(pinned.stdout.strip()):
        raise InputError(f"git: git rev-parse {spec} gives no commit")
    # Without a checkout, "git -C" finds the parent repository instead.
    if (root / SUBMODULE / ".git").exists():
        sub = _run(["git", "-C", str(root / SUBMODULE), "rev-parse", "HEAD"], root)
        sub_head = {
            "exit_code": sub.returncode,
            "output": sub.stdout.strip() if sub.returncode == 0 else _lines(sub),
        }
    else:
        sub_head = {"exit_code": None, "output": f"{SUBMODULE} is not checked out"}
    script = root / CHECK_SUBMODULE
    if not script.is_file():
        raise InputError(f"git: {script}: no such file")
    check = _run(["sh", str(script), "in the S4 exit check"], root)

    def ancestor(a: str, b: str, text: str) -> dict:
        done = _git(root, "merge-base", "--is-ancestor", a, b)
        if done.returncode not in (0, 1):
            raise InputError(
                f"git: git merge-base --is-ancestor {a} {b}: {_lines(done)}"
            )
        return {
            "command": f"git merge-base --is-ancestor {text}",
            "exit_code": done.returncode,
        }

    def diff(b: str) -> list[str]:
        done = _git(root, "diff", "--name-only", START, b)
        if done.returncode != 0:
            raise InputError(f"git: git diff --name-only {START} {b}: {_lines(done)}")
        return [x for x in done.stdout.splitlines() if x]

    ci_files = diff(ci_head)
    head_files = diff("HEAD")
    return {
        "pinned": {
            "command": f"git rev-parse {spec}",
            "exit_code": pinned.returncode,
            "output": pinned.stdout.strip(),
        },
        "submodule_head": {
            "command": f"git -C {SUBMODULE} rev-parse HEAD",
            **sub_head,
        },
        "check_submodule": {
            "command": f'{CHECK_SUBMODULE} "in the S4 exit check"',
            "exit_code": check.returncode,
            "output": _lines(check),
        },
        "start_in_ci_head": ancestor(START, ci_head, f"{START[:7]} {ci_head[:7]}"),
        "ci_head_in_head": ancestor(ci_head, "HEAD", f"{ci_head[:7]} HEAD"),
        "diff_ci": {
            "command": f"git diff --name-only {START[:7]} {ci_head[:7]}",
            "files": ci_files,
        },
        "diff_head_parse_path": {
            "command": f"git diff --name-only {START[:7]} HEAD (parse-path files only)",
            "files": [x for x in head_files if is_parse_path(x)],
        },
    }


# The items.


def find_step(ci: dict, name: str) -> dict | None:
    found = [s for s in ci["steps"] if s["name"] == name]
    return found[0] if len(found) == 1 else None


def step_output(step: dict | None) -> dict | None:
    """The JSON object that scripts/s4/parity writes on stdout: the lines from
    the line "{" to the end of the step."""
    if step is None or "{" not in step["lines"]:
        return None
    start = step["lines"].index("{")
    try:
        value = json.loads("\n".join(step["lines"][start:]))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def item(key: str, rule: str, checks: dict[str, bool], values: dict) -> dict:
    failed = [name for name, ok in checks.items() if not ok]
    return {
        "item": key,
        "rule": rule,
        "met": not failed,
        "checks": checks,
        "failed": failed,
        "values": values,
    }


def counts_ok(counts) -> bool:
    return isinstance(counts, dict) and all(
        counts.get(k) == v for k, v in COUNTS.items()
    )


def items_ok(output: dict | None) -> bool:
    items = (output or {}).get("items")
    return (
        isinstance(items, list)
        and sorted(i.get("item") for i in items if isinstance(i, dict))
        == list(PARITY_ITEMS)
        and all(isinstance(i, dict) and i.get("ok") is True for i in items)
    )


def item_a(data: dict, git: dict) -> dict:
    ci = data["ci"]
    step = find_step(ci, STEP)
    out = step_output(step)
    lines = step["lines"] if step else []
    s1 = data["s1"]["results"][TOOL]["suites"][SUITE]
    s1_checks = s1.get("checks") or {}
    preflight = (data["s1"].get("tools") or {}).get(TOOL, {}).get("preflight") or {}
    parity = data["parity"]
    jobs = ci["jobs_by_conclusion"]
    checks = {
        "ci_workflow": ci["workflow"] == WORKFLOW,
        "ci_push_on_main": ci["event"] == "push" and ci["branch"] == "main",
        "ci_run_success": ci["conclusion"] == "success",
        "ci_jobs_ok": sum(n for c, n in jobs.items() if c in ("success", "skipped"))
        == ci["jobs_total"]
        and sum(jobs.values()) == ci["jobs_total"],
        "ci_job_success": ci["job"]["name"] == JOB
        and ci["job"]["conclusion"] == "success",
        "ci_step_success": step is not None and step["conclusion"] == "success",
        "ci_summary_line": lines.count(SUMMARY) == 1,
        "ci_output_pass": out is not None
        and out.get("status") == "pass"
        and out.get("exit_code") == 0
        and out.get("errors") == [],
        "ci_output_commit": out is not None and out.get("commit") == ci["head_sha"],
        "ci_output_counts": counts_ok((out or {}).get("counts")),
        "ci_output_items": items_ok(out),
        "ci_head_in_head": git["ci_head_in_head"]["exit_code"] == 0,
        "s1_summary": s1.get("total") == CASES
        and s1.get("passed") == CASES
        and s1.get("failed") == 0
        and s1.get("error") == 0
        and s1.get("skipped") == 0
        and s1_checks.get("exact") == CASES
        and s1_checks.get("no_unparsable") == CASES,
        "s1_sqll_adapter_parse": preflight.get("parse") is True,
        "parity_record": parity["exit_code"] == 0
        and parity["output"].get("status") == "pass"
        and counts_ok(parity["output"]["counts"])
        and items_ok(parity["output"]),
    }
    counts = (out or {}).get("counts") or {}
    return item(
        "a",
        f"{CASES} of {CASES} dialect cases in {DIALECTS} dialects pass with exact"
        " and no_unparsable through the shared syntax tree and the sqll adapter"
        " (design record section 1), in a push run on main with conclusion"
        " success",
        checks,
        {
            "ci_run": ci["run_id"],
            "ci_url": ci["url"],
            "ci_head": ci["head_sha"],
            "ci_job": ci["job"]["id"],
            "ci_step": STEP,
            "ci_summary_line": SUMMARY if checks["ci_summary_line"] else None,
            "ci_counts": {k: counts.get(k) for k in COUNTS},
            "s1": {
                "total": s1.get("total"),
                "passed": s1.get("passed"),
                "exact": s1_checks.get("exact"),
                "no_unparsable": s1_checks.get("no_unparsable"),
            },
            "parity_record": {
                "commit": parity["output"].get("commit"),
                "exit_code": parity["exit_code"],
            },
            "tree_path": TREE_PATH,
        },
    )


def item_b(data: dict) -> dict:
    known = list(data["known_failures"])
    lines = sorted(i for i in known if i.split("/", 1)[0] == SUITE)
    out = step_output(find_step(data["ci"], STEP)) or {}
    ci_count = (out.get("counts") or {}).get("known_failures_dialects_lines")
    parity_count = data["parity"]["output"]["counts"].get(
        "known_failures_dialects_lines"
    )
    checks = {
        "no_dialects_line": not lines,
        "ci_output": ci_count == 0,
        "parity_record": parity_count == 0,
    }
    return item(
        "b",
        "known_failures/sqll.txt has 0 dialects lines (design record section 2)",
        checks,
        {
            "command": "the known failures parser of the harness"
            " (sqll_harness.known_failures.parse) on known_failures/sqll.txt",
            "lines": len(known),
            "dialects_lines": len(lines),
            "dialects_ids": lines,
            "ci_known_failures_dialects_lines": ci_count,
        },
    )


def item_c(data: dict) -> dict:
    step = find_step(data["ci"], ORACLE_STEP)
    out = step_output(find_step(data["ci"], STEP)) or {}
    counts = out.get("counts") or {}
    items = {i.get("item"): i for i in out.get("items") or [] if isinstance(i, dict)}
    item4 = items.get(4) or {}
    gaps = item4.get("gaps") or {}
    parity = data["parity"]["output"]["counts"]
    checks = {
        "ci_oracle_step_success": step is not None and step["conclusion"] == "success",
        "ci_oracle_line": step is not None and step["lines"].count(ORACLE_LINE) == 1,
        "ci_passed_in_oracle": counts.get("passed") == CASES
        and counts.get("passed_in_oracle") == counts.get("passed")
        and counts.get("oracle_cases") == CASES
        and counts.get("oracle_passed") == CASES,
        "ci_item_4": item4.get("ok") is True
        and bool(gaps)
        and all(v == 0 for v in gaps.values()),
        "parity_record": parity.get("passed_in_oracle")
        == parity.get("passed")
        == CASES,
    }
    return item(
        "c",
        "Each sqll pass also passes in the sqlfluff dialect oracle"
        " (scripts/sqlfluff-dialect-oracle --passes-of sqll)",
        checks,
        {
            "ci_step": ORACLE_STEP,
            "ci_oracle_line": ORACLE_LINE if checks["ci_oracle_line"] else None,
            "ci_passed": counts.get("passed"),
            "ci_passed_in_oracle": counts.get("passed_in_oracle"),
            "ci_oracle_cases": counts.get("oracle_cases"),
            "ci_oracle_passed": counts.get("oracle_passed"),
        },
    )


def item_d(data: dict, git: dict) -> dict:
    out = step_output(find_step(data["ci"], STEP)) or {}
    parity = data["parity"]["output"]
    checks = {
        "pinned_commit": git["pinned"]["output"] == PINNED,
        "submodule_head": git["submodule_head"]["exit_code"] == 0
        and git["submodule_head"]["output"] == PINNED,
        "check_submodule": git["check_submodule"]["exit_code"] == 0,
        "s1_sqlfluff_ref": data["s1"]["sqlfluff_ref"] == PINNED,
        "ci_output": out.get("pinned_commit") == PINNED
        and out.get("report_sqlfluff_ref") == PINNED,
        "parity_record": parity.get("pinned_commit") == PINNED
        and parity.get("report_sqlfluff_ref") == PINNED,
    }
    return item(
        "d",
        f"The pinned sqlfluff commit is {PINNED} (tag 4.4.0), and the submodule"
        " is clean",
        checks,
        {
            "pinned": PINNED,
            "git_pinned": git["pinned"],
            "git_submodule_head": git["submodule_head"],
            "check_submodule": git["check_submodule"],
            "s1_sqlfluff_ref": data["s1"]["sqlfluff_ref"],
            "ci_pinned_commit": out.get("pinned_commit"),
            "ci_report_sqlfluff_ref": out.get("report_sqlfluff_ref"),
        },
    )


def item_e(data: dict) -> dict:
    gate = data["gate"]
    runs = {
        r.get("name"): r for r in gate["injected_gaps"]["runs"] if isinstance(r, dict)
    }
    checks = {}
    found = {}
    for name, (code, gap) in GATE_RUNS.items():
        run = runs.get(name) or {}
        gaps = run.get("gaps") if isinstance(run.get("gaps"), dict) else {}
        ok = run.get("exit_code") == code
        if gap is None:
            ok = ok and not any(gaps.values())
        else:
            ok = ok and bool(gaps.get(gap)) and set(gaps) == {gap}
        if code == 2:
            ok = ok and bool(run.get("errors"))
        checks[f"run_{name}"] = ok
        found[name] = {"exit_code": run.get("exit_code"), "gaps": sorted(gaps)}
    ci = gate["ci"]
    checks["ci_gate_step"] = (
        ci.get("conclusion") == "success"
        and ci.get("job") == JOB
        and ci.get("step") == STEP
        and ci.get("step_conclusion") == "success"
        and ci.get("log") == SUMMARY
        and ci.get("log_exit_code") == 0
    )
    return item(
        "e",
        "The CI gate fails closed: exit code 1 on an injected gap and exit code"
        " 2 on a missing input (the injected-gap proofs of T3 (CI fails on each"
        f" gap of this stone) of {STONE})",
        checks,
        {
            "record": "results/S4/gate.json",
            "runs": found,
            "gate_ci_run": ci.get("run"),
            "gate_ci_pull_request": ci.get("pull_request"),
        },
    )


def item_f(data: dict) -> dict:
    corpus = data["corpus"]
    counts = corpus["counts"]
    by_class = counts["by_class"]
    checks = {
        "record_pass": corpus["status"] == "pass" and corpus.get("exit_code") == 0,
        "rows_classified": isinstance(counts.get("rows"), int)
        and sum(v for v in by_class.values() if isinstance(v, int)) == counts["rows"],
    }
    return item(
        "f",
        "The corpus information of T4 (the parse status of sqll and sqlfluff on"
        f" each corpus file is recorded, and each difference has a row) of {STONE},"
        " as information only: it does not change the parity number of this stone"
        " and does not block its exit (design record section 4)",
        checks,
        {
            "record": "results/S4/corpus-diff.json",
            "information_only": True,
            "changes_parity_number": False,
            "files": counts.get("files"),
            "same": counts.get("same"),
            "rows": counts.get("rows"),
            "by_class": by_class,
            "by_tool": counts.get("by_tool"),
            "report_commit": (corpus.get("report") or {})
            .get("harness", {})
            .get("commit"),
        },
    )


def item_g(git: dict) -> dict:
    ci_files = git["diff_ci"]["files"]
    parse = [x for x in ci_files if is_parse_path(x)]
    head = git["diff_head_parse_path"]["files"]
    checks = {
        "start_in_ci_head": git["start_in_ci_head"]["exit_code"] == 0,
        "no_parse_path_change_to_ci_head": not parse,
        "no_parse_path_change_to_head": not head,
    }
    return item(
        "g",
        f"{G3}: no parse-path change from the start of this stone"
        f" ({START[:7]}); a parse-path change needs the speed-check record of its"
        " task (design record section 5), and this check then fails",
        checks,
        {
            "start": START,
            "parse_path": {
                "files": list(PARSE_PATH_FILES),
                "dirs": list(PARSE_PATH_DIRS),
            },
            "command": git["diff_ci"]["command"],
            "files": len(ci_files),
            "changed_files": ci_files,
            "parse_path_files": parse,
            "head_command": git["diff_head_parse_path"]["command"],
            "head_parse_path_files": head,
            "speed_checks": [],
        },
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_report(root: Path, paths: dict[str, Path]) -> dict:
    data = load_inputs(paths)
    git = git_facts(root, data["ci"]["head_sha"])
    items = [
        item_a(data, git),
        item_b(data),
        item_c(data),
        item_d(data, git),
        item_e(data),
        item_f(data),
        item_g(git),
    ]
    met = all(i["met"] for i in items)
    ci = data["ci"]
    return {
        "format": FORMAT,
        "kind": "sqll-s4-exit",
        "stone": STONE,
        "task": TASK,
        "command": COMMAND,
        "inputs": {shown(path, root): sha256(path) for path in paths.values()},
        "ci": {
            "run_id": ci["run_id"],
            "url": ci["url"],
            "event": ci["event"],
            "branch": ci["branch"],
            "head_sha": ci["head_sha"],
            "conclusion": ci["conclusion"],
            "job": ci["job"],
            "summary_line": SUMMARY,
        },
        "git": git,
        "items": items,
        "result": {
            "met": met,
            "failed_items": [i["item"] for i in items if not i["met"]],
            "state": STATE if met else NOT_MET,
        },
    }


def shown(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def text(report: dict) -> str:
    return json.dumps(report, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="exit.py",
        description=f"The exit check of {STONE}.",
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    for name in INPUTS:
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, dest=name)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    paths = {
        name: getattr(args, name) or root / default for name, default in INPUTS.items()
    }
    out = args.out or root / OUT
    try:
        report = make_report(root, paths)
    except InputError as exc:
        print(f"S4 exit: error: {exc}", file=sys.stderr)
        return 2
    result = report["result"]
    failed = ", ".join(result["failed_items"]) or "none"
    line = (
        f"S4 exit: {'pass' if result['met'] else 'fail'}: items met"
        f" {len(report['items']) - len(result['failed_items'])} of"
        f" {len(report['items'])}; failed items: {failed}; state: {result['state']}"
    )
    new = text(report)
    if args.check:
        if not out.is_file() or out.read_text(encoding="utf8") != new:
            print(f"S4 exit: error: {shown(out, root)} is not the output of the inputs")
            return 1
        print(f"{line}; {shown(out, root)}: no change")
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(new, encoding="utf8")
        print(f"{line}; wrote {shown(out, root)}")
    for i in report["items"]:
        if not i["met"]:
            print(f"  item {i['item']}: failed checks: {', '.join(i['failed'])}")
    return 0 if result["met"] else 1


if __name__ == "__main__":
    sys.exit(main())
