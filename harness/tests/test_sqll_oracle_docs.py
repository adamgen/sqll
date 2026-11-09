"""The usage text of each sqlfluff oracle names the CI job that runs it with
--passes-of sqll (S3b C14). A false job name is a false claim (PROCESS.md)."""

import re

import pytest

from sqll_harness.paths import REPO_ROOT

CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
ORACLES = ("dialect", "rule", "autofix", "templater")


def _jobs():
    body = CI.read_text().split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([a-z][a-z0-9_-]*):\n", body)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def _steps(job):
    return job.split("\n      - ")


def _claim(name):
    text = " ".join((REPO_ROOT / "scripts" / name).read_text().split())
    match = re.search(r"The CI (.+?) (?:uses|use) it for sqll", text)
    assert match, name
    return match.group(1)


def _runs_passes_of_sqll(job, name, tool=None):
    """True if a step of the job runs the script with --passes-of sqll."""
    for step in _steps(job):
        if f"scripts/{name}" not in step:
            continue
        if "--passes-of sqll" in step:
            return True
        if "${{ matrix.args }}" in step and tool is not None:
            entry = re.search(
                rf"- tool: {re.escape(tool)}\n(?:\s+\w+: .*\n)*?\s+args: (.*)\n",
                job,
            )
            if entry and "--passes-of sqll" in entry.group(1):
                return True
    return False


@pytest.mark.parametrize("kind", ORACLES)
def test_oracle_usage_names_the_ci_job_that_runs_it(kind):
    name = f"sqlfluff-{kind}-oracle"
    claim = _claim(name)
    jobs = _jobs()
    if claim == "report job":
        assert _runs_passes_of_sqll(jobs["report"], name), claim
        return
    match = re.fullmatch(r"job `([a-z-]+) \(([a-z-]+)\)`.*", claim)
    assert match, claim
    job, tool = match.groups()
    assert _runs_passes_of_sqll(jobs[job], name, tool), claim
    if "scripts/verify" in claim:
        verify = (REPO_ROOT / "harness" / "sqll_harness" / "verify.py").read_text()
        check = re.search(rf'"{name}",\s*"(.*)"', verify)
        assert check and "--passes-of sqll" in check.group(1), claim


def test_report_job_does_not_run_the_dialect_oracle():
    assert "sqlfluff-dialect-oracle" not in _jobs()["report"]
