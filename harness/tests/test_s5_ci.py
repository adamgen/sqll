"""The CI gate of S5 (rule parity: sqll passes 100% of the rule fixtures, lint
and fix; cases that need the Jinja templater move to the Jinja templater
stone).

Task T4 (goal of the task: CI fails on a sqll pass that the oracle does not
pass, and on a changed class count) of S5. Design record:
docs/decisions/s5-rules.md, sections 3 and 4. The CI report job runs
scripts/s5/parity after the rule oracle and the autofix oracle, and
scripts/verify runs the same command (the check "s5-parity"). The tests run
the arguments of the CI step on the small repository of test_s5_parity.py:
the step fails on a sqll pass that the oracle does not pass, on a changed
class count, and on a missing input.
"""

import json
import re
import shlex
import subprocess
import sys

import pytest
import yaml
from test_s5_parity import (
    AUTOFIX_DIR,
    AUTOFIX_ORACLE,
    FIXTURES,
    ORACLE,
    RECORDED,
    REPORT,
    RULE_DIR,
    SCRIPT,
    Repo,
)

from sqll_harness import verify
from sqll_harness.paths import REPO_ROOT

CI = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
JOB = CI["jobs"]["report"]
RULE_ORACLE_STEP = "Compare the rule results with the sqlfluff test"
AUTOFIX_ORACLE_STEP = "Compare the autofix results with the sqlfluff test"
STEP = "Check the S5 rule parity"
OUT = "out/s5-parity.json"
STATUS = REPO_ROOT / "status" / "S5.md"
STONE = (
    "S5 (rule parity: sqll passes 100% of the rule fixtures, lint and fix;"
    " cases that need the Jinja templater move to the Jinja templater stone)"
)
GOAL = (
    "CI fails on a sqll pass that the oracle does not pass, and on a changed"
    " class count"
)


def _names(job: dict) -> list[str]:
    return [s.get("name") or s.get("uses", "").split("@")[0] for s in job["steps"]]


def _step(job: dict, name: str) -> dict:
    return next(s for s in job["steps"] if s.get("name") == name)


def _ci_args() -> list[str]:
    """The arguments of scripts/s5/parity in the CI step."""
    words = shlex.split(_step(JOB, STEP)["run"])
    return words[words.index("scripts/s5/parity") + 1 :]


def _oracle_out(step: str) -> str:
    words = shlex.split(" ".join(_step(JOB, step)["run"].replace("\\\n", " ").split()))
    return words[words.index("--out") + 1]


# The CI step.


def test_the_step_comes_after_the_2_oracle_steps():
    names = _names(JOB)
    assert names.index(AUTOFIX_ORACLE_STEP) == names.index(RULE_ORACLE_STEP) + 1
    assert names.index(STEP) == names.index(AUTOFIX_ORACLE_STEP) + 1
    # The upload of the outputs and the check of the test jobs stay last.
    assert names[-2:] == ["actions/upload-artifact", "Check test jobs"]


def test_the_step_runs_only_if_the_steps_before_it_pass():
    # No "if": GitHub runs the step only if each step before it passes, and
    # a failure of the step fails the job. No other key (for example
    # continue-on-error) can hide a failure.
    step = _step(JOB, STEP)
    assert set(step) == {"name", "run"}
    commands = verify.ci_commands(step, JOB, CI.get("env"))
    assert len(commands) == 1
    assert verify.ci_weak_parts(step["run"]) == []


def test_the_step_reads_the_report_and_the_outputs_of_the_2_oracle_steps():
    run = _step(JOB, STEP)["run"]
    assert run.startswith("uv run --frozen --project harness python scripts/s5/parity")
    assert _ci_args() == [
        "--report",
        "out/report.json",
        "--oracle",
        "out/oracle.jsonl",
        "--autofix-oracle",
        "out/autofix-oracle.jsonl",
        "--out",
        OUT,
    ]
    # The oracle steps write the files that the step reads, with the oracle
    # of the sqll passes (--passes-of sqll).
    assert _oracle_out(RULE_ORACLE_STEP) == "out/oracle.jsonl"
    assert _oracle_out(AUTOFIX_ORACLE_STEP) == "out/autofix-oracle.jsonl"
    for name in (RULE_ORACLE_STEP, AUTOFIX_ORACLE_STEP):
        assert "--passes-of sqll" in " ".join(_step(JOB, name)["run"].split())
    # The merge step writes out/report.json.
    assert "sqll-harness merge" in _step(JOB, "Merge")["run"]


def test_the_step_uses_the_recorded_counts_and_does_not_fail_on_a_gap():
    # No --recorded: the counts of the design record (RECORDED of the
    # script). No --exit: a gap of this stone is not a failure before the
    # exit of this stone.
    assert "--recorded" not in _ci_args()
    assert "--exit" not in _ci_args()


def test_the_upload_has_the_output_of_the_step():
    upload = next(
        s for s in JOB["steps"] if s.get("uses", "").startswith("actions/upload")
    )
    assert upload["if"] == "always()"
    assert OUT in upload["with"]["path"].split()


def test_the_job_runs_on_each_change_that_is_not_only_documents():
    assert JOB["if"] == verify.JOB_IF["report"]
    assert JOB["needs"] == ["changes", "image", "test"]


# The local check of scripts/verify.


def test_verify_runs_the_same_command_after_the_2_oracles():
    names = [c.name for c in verify.checks()]
    assert names.index("oracle-autofix") == names.index("oracle-rules") + 1
    assert names.index("s5-parity") == names.index("oracle-autofix") + 1
    check = next(c for c in verify.checks() if c.name == "s5-parity")
    assert check.ci == (f"report: {STEP}",)
    assert verify.lines(check.command) == [
        tuple(shlex.split(" ".join(_step(JOB, STEP)["run"].split())))
    ]
    assert check.needs == (verify.SETUP, verify.REPORT_FILE)
    assert check.removes == (OUT,)
    assert check.report == OUT
    assert not check.quick and not check.full_bench and not check.s7


def test_verify_deletes_an_old_oracle_output_before_each_oracle():
    # An old oracle output must not give a pass if an oracle check fails.
    checks = {c.name: c for c in verify.checks()}
    assert checks["oracle-rules"].removes == ("out/oracle.jsonl",)
    assert checks["oracle-autofix"].removes == ("out/autofix-oracle.jsonl",)


def test_verify_lists_the_check(capsys):
    assert verify.main(["--list"]) == 0
    assert any(
        line.startswith("s5-parity") for line in capsys.readouterr().out.splitlines()
    )


def test_drift_finds_no_difference():
    assert verify.drift(verify.checks(), CI) == []


# The CI step on a small repository: the arguments of the CI step, run in the
# root of the repository, as CI does.


def _run_ci_step(repo: Repo, *extra: str) -> tuple[int, dict, str]:
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(repo.root), *_ci_args(), *extra],
        cwd=repo.root,
        capture_output=True,
        text=True,
        check=False,
    )
    result = json.loads(done.stdout)
    assert result["exit_code"] == done.returncode
    return done.returncode, result, done.stderr


def _recorded(repo: Repo) -> tuple[str, str]:
    """The recorded counts of the small repository (only for the tests)."""
    return ("--recorded", str(repo.root / RECORDED))


@pytest.fixture
def repo(tmp_path) -> Repo:
    repo = Repo(tmp_path)
    repo.write_inputs()
    return repo


def test_the_ci_step_passes_with_the_counts_of_the_small_repository(repo):
    rc, result, err = _run_ci_step(repo, *_recorded(repo))
    assert rc == 0, err
    assert result["status"] == "pass"
    assert err.startswith("S5 parity: pass")
    assert json.loads((repo.root / OUT).read_text("utf8")) == result


def test_the_ci_step_fails_on_a_changed_class_count(repo):
    repo.recorded["rules"]["jinja"] += 1
    repo.write_inputs()
    rc, result, err = _run_ci_step(repo, *_recorded(repo))
    assert rc == 1, err
    assert "failed items: 3" in err
    assert result["failures"]["count"] == ["rules jinja: 7, the recorded count is 8"]


def test_the_ci_step_fails_on_a_new_case_of_the_jinja_class(tmp_path):
    fixtures = dict(FIXTURES)
    fixtures[AUTOFIX_DIR / "ansi" / "005_new" / "before.sql"] = "SELECT {{ y }}\n"
    repo = Repo(tmp_path, fixtures)
    repo.statuses["autofix/ansi/005_new"] = "fail"
    repo.oracle["autofix"]["autofix/ansi/005_new"] = "pass"
    repo.known.add("autofix/ansi/005_new")
    repo.write_inputs()
    rc, result, err = _run_ci_step(repo, *_recorded(repo))
    assert rc == 1, err
    assert "failed items: 3" in err
    assert result["failures"]["count"] == [
        "autofix cases: 8, the recorded count is 7",
        "autofix jinja: 4, the recorded count is 3",
    ]


def test_the_ci_step_fails_on_a_case_that_leaves_the_templater_class(tmp_path):
    # The case moves from the templater class to the gap class: the count
    # of the cases does not change, but the count of a class does.
    fixtures = dict(FIXTURES)
    fixtures[RULE_DIR / "AA02.yml"] = FIXTURES[RULE_DIR / "AA02.yml"].replace(
        "placeholder", "raw"
    )
    repo = Repo(tmp_path, fixtures)
    repo.write_inputs()
    rc, result, err = _run_ci_step(repo, *_recorded(repo))
    assert rc == 1, err
    assert result["failures"]["count"] == [
        "rules templater: 2, the recorded count is 3"
    ]


def test_the_ci_step_as_it_is_uses_the_counts_of_the_design_record(repo):
    # With the arguments of CI only, the counts of the small repository are
    # not the recorded counts: the step fails (item 3).
    rc, result, err = _run_ci_step(repo)
    assert rc == 1, err
    assert "failed items: 3" in err
    assert result["recorded"] == {
        "rules": {"cases": 2527, "jinja": 169, "templater": 13},
        "autofix": {"cases": 61, "jinja": 21, "templater": 0},
    }
    assert len(result["failures"]["count"]) == 6


@pytest.mark.parametrize(
    "suite,case_id",
    [
        ("rules", "rules/AA01/test_pass_jinja_as_raw"),
        ("autofix", "autofix/ansi/001_plain"),
    ],
)
def test_the_ci_step_fails_on_a_sqll_pass_that_the_oracle_does_not_pass(
    repo, suite, case_id
):
    repo.oracle[suite][case_id] = "fail"
    repo.write_inputs()
    rc, result, err = _run_ci_step(repo, *_recorded(repo))
    assert rc == 1, err
    assert "failed items: 2" in err
    assert result["failures"]["oracle_mismatch"] == [
        f"{case_id}: sqll passes the case, but the oracle gives fail"
    ]


@pytest.mark.parametrize("path", [REPORT, ORACLE, AUTOFIX_ORACLE])
def test_the_ci_step_fails_with_a_missing_input(repo, path):
    (repo.root / path).unlink()
    rc, result, err = _run_ci_step(repo, *_recorded(repo))
    assert rc == 2, err
    assert result["status"] == "error"
    assert "S5 parity: error" in err


# The status file.


def test_status_row_of_t4():
    row = next(
        line
        for line in STATUS.read_text("utf8").splitlines()
        if line.startswith("| T4 |")
    )
    assert "CI report job" in row
    assert "`scripts/verify`" in row
    assert GOAL in row
    assert re.search(r"\| (In review|Done) \(PR #\d+\) \|$", row), row
    text = " ".join(STATUS.read_text("utf8").split())
    assert f"T4 (goal of the task: {GOAL}) of {STONE}" in text
