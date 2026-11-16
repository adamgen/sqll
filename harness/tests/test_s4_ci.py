"""The CI gate of S4 (parser parity: sqll passes 100% of the dialect parse
fixtures with an exact tree match).

Task T3 (CI fails on each gap of this stone) of S4. Design record:
docs/decisions/s4-parity.md, section 3. The job "dialect-oracle (sqlfluff)"
runs scripts/s4/parity after the oracle step, scripts/verify runs the same
command (the check "s4-parity"), and the lint job runs ruff on each S4
script. The tests run the arguments of the CI step on the small repository
of test_s4_parity.py: the step fails closed on a gap and on a missing input.
"""

import json
import re
import shlex
import subprocess
import sys

import pytest
import yaml
from test_s4_parity import (
    CASES,
    KNOWN,
    KNOWN_TEXT,
    ORACLE,
    REPORT,
    SCRIPT,
    Repo,
    oracle_text,
)

from sqll_harness import verify
from sqll_harness.paths import REPO_ROOT

CI = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
JOB = CI["jobs"]["dialect-oracle"]
ORACLE_STEP = "Compare the dialect results with the sqlfluff tests"
STEP = "Check the S4 parser parity"
STATUS = REPO_ROOT / "status" / "S4.md"
STONE = (
    "S4 (parser parity: sqll passes 100% of the dialect parse fixtures with an"
    " exact tree match)"
)


def _names(job: dict) -> list[str]:
    return [s.get("name") or s.get("uses", "").split("@")[0] for s in job["steps"]]


def _step(job: dict, name: str) -> dict:
    return next(s for s in job["steps"] if s.get("name") == name)


def _ci_args() -> list[str]:
    """The arguments of scripts/s4/parity in the CI step."""
    words = shlex.split(_step(JOB, STEP)["run"])
    return words[words.index("scripts/s4/parity") + 1 :]


# The CI step.


def test_the_step_comes_after_the_oracle_step():
    names = _names(JOB)
    assert names.index(STEP) == names.index(ORACLE_STEP) + 1
    # The upload of the oracle output stays last (if: always()).
    assert names[-1] == "actions/upload-artifact"


def test_the_step_runs_only_for_the_oracle_of_the_sqll_passes():
    step = _step(JOB, STEP)
    assert step["if"] == "matrix.tool == 'sqlfluff'"
    assert set(step) == {"name", "if", "run"}
    # The drift test of verify.py gives the step one command: the sqlfluff
    # entry.
    commands = verify.ci_commands(step, JOB, CI.get("env"))
    assert len(commands) == 1
    tools = [e["tool"] for e in JOB["strategy"]["matrix"]["include"]]
    assert tools.count("sqlfluff") == 1


def test_the_step_reads_the_merged_report_and_the_sqlfluff_oracle_output():
    entry = next(
        e for e in JOB["strategy"]["matrix"]["include"] if e["tool"] == "sqlfluff"
    )
    assert entry["args"] == "--passes-of sqll"
    run = _step(JOB, STEP)["run"]
    assert run.startswith("uv run --frozen --project harness python scripts/s4/parity")
    assert _ci_args() == [
        "--report",
        "out/report.json",
        "--oracle",
        "out/dialect-oracle-sqlfluff.jsonl",
        "--out",
        "out/s4-parity.json",
    ]
    # The oracle step writes the file that the step reads.
    oracle = _step(JOB, ORACLE_STEP)["run"].replace("${{ matrix.tool }}", "sqlfluff")
    assert "--out out/dialect-oracle-sqlfluff.jsonl" in " ".join(oracle.split())
    # The download step gives out/report.json (the artifact "report").
    download = next(
        s for s in JOB["steps"] if s.get("uses", "").startswith("actions/download")
    )
    assert download["with"] == {"name": "report", "path": "out"}


def test_the_job_runs_on_each_change_of_the_parse_path():
    # The job has no "if": it runs on each pull request that is not only
    # documents (the report job), and on each push to main.
    assert "if" not in JOB
    assert JOB["needs"] == ["image", "report"]


# The local check of scripts/verify.


def test_verify_runs_the_same_command_after_the_oracle():
    names = [c.name for c in verify.checks()]
    assert names.index("s4-parity") == names.index("dialect-oracle-sqlfluff") + 1
    check = next(c for c in verify.checks() if c.name == "s4-parity")
    assert check.ci == (f"dialect-oracle: {STEP}",)
    assert verify.lines(check.command) == [
        tuple(shlex.split(" ".join(_step(JOB, STEP)["run"].split())))
    ]
    assert check.needs == (verify.SETUP, verify.REPORT_FILE)
    assert check.removes == ("out/s4-parity.json",)
    assert check.report == "out/s4-parity.json"
    assert not check.quick and not check.full_bench and not check.s7


def test_verify_deletes_an_old_oracle_output_before_the_oracle():
    # An old oracle output must not give a pass if the oracle check fails.
    oracle = next(c for c in verify.checks() if c.name == "dialect-oracle-sqlfluff")
    assert oracle.removes == ("out/dialect-oracle-sqlfluff.jsonl",)


def test_verify_lists_the_check(capsys):
    assert verify.main(["--list"]) == 0
    assert any(
        line.startswith("s4-parity") for line in capsys.readouterr().out.splitlines()
    )


# The lint job.


def _lint() -> dict:
    return _step(CI["jobs"]["lint"], "Lint")


def test_the_lint_job_checks_each_s4_script():
    files = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "scripts/s4"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "scripts/s4/parity" in files
    paths = _lint()["env"]["S4_SCRIPTS"].split()
    assert "scripts/s4" in paths
    for path in files:
        if path.endswith(".py"):
            continue
        first = (REPO_ROOT / path).read_text("utf8", errors="replace").splitlines()
        if first and first[0].startswith("#!") and "python" in first[0]:
            assert path in paths, f"{path}: add it to S4_SCRIPTS of the lint job"
    for path in paths:
        assert (REPO_ROOT / path).exists(), path
    assert paths == verify.S4_SCRIPTS.split()


def test_ruff_check_and_format_use_the_s4_scripts():
    lines = [line for line in _lint()["run"].splitlines() if line.strip()]
    assert len(lines) == 2
    assert re.search(r"ruff check .* \$S4_SCRIPTS$", lines[0]), lines[0]
    assert re.search(r"ruff format --check .* \$S4_SCRIPTS$", lines[1]), lines[1]


# The CI step fails closed: the arguments of the CI step on a small repository.


def _run_ci_step(repo: Repo) -> tuple[int, str]:
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(repo.root), *_ci_args()],
        cwd=repo.root,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stderr


@pytest.fixture
def repo(tmp_path) -> Repo:
    repo = Repo(tmp_path)
    repo.write(REPORT, json.dumps(repo.report))
    repo.write(ORACLE, oracle_text(repo.oracle))
    return repo


def test_the_ci_step_passes_with_no_gap(repo):
    rc, err = _run_ci_step(repo)
    assert rc == 0, err
    assert "S4 parity: pass" in err
    assert (repo.root / "out" / "s4-parity.json").is_file()


def test_the_ci_step_fails_on_a_dialects_line_in_the_known_failures(repo):
    # The ids of the list are sorted: "dialects/" comes before "rules/".
    repo.write(KNOWN, f"{CASES[0]}  # an injected gap\n" + KNOWN_TEXT)
    rc, err = _run_ci_step(repo)
    assert rc == 1, err
    assert "failed items: 3" in err


def test_the_ci_step_fails_on_a_removed_case_in_the_report(repo):
    data = json.loads((repo.root / REPORT).read_text("utf8"))
    data["cases"] = [c for c in data["cases"] if c["id"] != CASES[1]]
    repo.write(REPORT, json.dumps(data))
    rc, err = _run_ci_step(repo)
    assert rc == 1, err
    assert "failed items: 1" in err


def test_the_ci_step_fails_with_no_oracle_output(repo):
    (repo.root / ORACLE).unlink()
    rc, err = _run_ci_step(repo)
    assert rc == 2, err
    assert "oracle" in err


# The status file.


def test_status_row_of_t3():
    row = next(
        line
        for line in STATUS.read_text("utf8").splitlines()
        if line.startswith("| T3 |")
    )
    assert "`dialect-oracle (sqlfluff)`" in row
    assert "`scripts/verify`" in row
    assert STONE in row
    assert "CI fails on each gap of this stone" in row
    assert re.search(r"\| (In review|Done) \(PR #\d+\) \|$", row), row


# The record of the proof: results/S4/gate.json.

GATE = REPO_ROOT / "results" / "S4" / "gate.json"


def test_the_record_gives_a_real_pass_and_each_injected_gap_fails():
    record = json.loads(GATE.read_text("utf8"))
    assert record["design_record"] == "docs/decisions/s4-parity.md, section 3"
    verify_run = record["verify"]
    assert verify_run["command"].startswith(
        "flock /tmp/sqll-machine.lock scripts/verify"
    )
    assert verify_run["exit_code"] == 0 and verify_run["result"] == "pass"
    assert verify_run["worktree_clean"] is True and verify_run["failed"] == 0
    assert verify_run["s4_parity_check"]["exit_code"] == 0
    assert verify_run["s4_parity_check"]["command"] == next(
        c.command for c in verify.checks() if c.name == "s4-parity"
    )
    assert any("s4-parity" in line and "PASS" in line for line in verify_run["output"])
    counts = verify_run["s4_parity_counts"]
    assert counts["passed"] == counts["discovered_cases"] == 2306
    assert counts["gaps"] == 0
    runs = {r["name"]: r for r in record["injected_gaps"]["runs"]}
    assert {name: r["exit_code"] for name, r in runs.items()} == {
        "control": 0,
        "known-failures-dialects-line": 1,
        "report-case-removed": 1,
        "no-oracle-output": 2,
    }
    assert runs["control"]["gaps"] == {}
    assert runs["known-failures-dialects-line"]["gaps"] == {
        "known_failures_dialects": ["dialects/ansi/select_a"]
    }
    assert runs["report-case-removed"]["gaps"] == {
        "missing": ["dialects/ansi/select_a"]
    }
    assert runs["no-oracle-output"]["errors"]
    ci = record["ci"]
    assert ci["conclusion"] == ci["step_conclusion"] == "success"
    assert ci["job"] == "dialect-oracle (sqlfluff)" and ci["step"] == STEP
    assert "2306 of 2306" in ci["log"] and ci["log_exit_code"] == 0
