"""The recorded S1 results agree with the known failures and with status/S1.md.

CI compares results/s1/summary.json with the summary of each full run. These
tests make sure that the other records say the same.
"""

import json
import re
import subprocess

import pytest
from test_case_counts import COUNTS

from sqll_harness import known_failures, summary
from sqll_harness.adapters import sqll
from sqll_harness.paths import KNOWN_FAILURES_DIR, RECORDED_SUMMARY, REPO_ROOT

TOOLS = ("sqlfluff", "sqlfluff-rs", "sqruff", "sqll")
# The sqll version is the crate version and the table manifest hash, so it is
# the same for each commit with the same tables.
VERSIONS = {
    "sqlfluff": "4.4.0",
    "sqlfluff-rs": "4.4.0",
    "sqruff": "0.41.0",
    "sqll": sqll.expected_version(),
}
RECORDED = json.loads(RECORDED_SUMMARY.read_text(encoding="utf8"))
RESULTS = RECORDED["results"]


def _known(tool: str) -> dict[str, str]:
    return known_failures.load(KNOWN_FAILURES_DIR, tool)


def test_summary_is_of_the_pinned_sqlfluff_and_tools():
    pin = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD:third_party/sqlfluff"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert RECORDED["format"] == summary.FORMAT
    assert RECORDED["sqlfluff_ref"] == pin
    assert sorted(RECORDED["tools"]) == sorted(TOOLS) == sorted(RESULTS)
    for tool, version in VERSIONS.items():
        assert RECORDED["tools"][tool]["version"] == version


@pytest.mark.parametrize("tool", TOOLS)
def test_each_tool_ran_each_case(tool):
    suites = RESULTS[tool]["suites"]
    assert {s: suites[s]["total"] for s in COUNTS} == COUNTS
    assert RESULTS[tool]["parity"]["total"] == sum(COUNTS.values()) == 4937
    for entry in suites.values():
        assert entry["skipped"] == 0
    assert RESULTS[tool]["known_failures_check"] == {
        "new_failures": 0,
        "unexpected_passes": 0,
    }


@pytest.mark.parametrize("tool", ["sqlfluff", "sqlfluff-rs"])
def test_sqlfluff_passes_each_case(tool):
    # S1 exit: sqlfluff passes 100% of the cases. sqlfluff-rs does too.
    assert RESULTS[tool]["parity"]["passed"] == 4937
    for entry in RESULTS[tool]["suites"].values():
        assert entry["passed"] == entry["total"]
    assert _known(tool) == {}
    text = (KNOWN_FAILURES_DIR / f"{tool}.txt").read_text(encoding="utf8")
    assert text == ""


def test_code_only_check_passes():
    assert RESULTS["sqlfluff"]["suites"]["code_only"]["passed"] == 2306
    assert "code_only" not in RESULTS["sqruff"]["suites"]
    assert "code_only" not in RESULTS["sqll"]["suites"]


def test_sqll_passes_each_dialect_case_and_supports_no_other_case():
    # S3: sqll has only the parse command. Each rule, autofix, and templater
    # case fails with the reason "unsupported: <item>".
    suites = RESULTS["sqll"]["suites"]
    assert suites["dialects"]["passed"] == 2306
    assert suites["dialects"]["checks"] == {"exact": 2306, "no_unparsable": 2306}
    known = _known("sqll")
    for name in ("rules", "autofix", "templater"):
        assert suites[name]["passed"] == 0
        assert suites[name]["failed"] == suites[name]["total"]
        listed = {i: r for i, r in known.items() if i.startswith(f"{name}/")}
        assert len(listed) == suites[name]["total"]
        assert all(r.startswith("unsupported: ") for r in listed.values())
    assert not [i for i in known if i.startswith("dialects/")]
    assert RECORDED["tools"]["sqll"]["preflight"] == {
        "fresh_build": True,
        "needs_libpython": False,
        "parse": True,
    }


@pytest.mark.parametrize("tool", TOOLS)
def test_known_failures_are_the_failed_cases(tool):
    suites = RESULTS[tool]["suites"]
    known = _known(tool)
    for name, entry in suites.items():
        listed = [i for i in known if i.startswith(f"{name}/")]
        assert len(listed) == entry["failed"] + entry["error"], name
    assert len(known) == sum(e["failed"] + e["error"] for e in suites.values())


def test_needs_python_counts():
    for tool in TOOLS:
        tags = RESULTS[tool]["suites"]["templater"]["tags"]
        assert tags["needs_python"]["total"] == 3
        for name, entry in RESULTS[tool]["suites"].items():
            if name != "templater":
                assert entry["tags"]["needs_python"]["total"] == 0


# status/S1.md

S1_STATUS = REPO_ROOT / "status" / "S1.md"


def _status_rows(header: str) -> list[list[str]]:
    """Return the cells of each row of the status/S1.md table with this header."""
    text = S1_STATUS.read_text(encoding="utf8")
    lines = text.splitlines()
    start = lines.index(header)
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def _checks(entry: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in entry["checks"].items())


def test_status_parity_table_is_the_summary():
    rows = _status_rows("| Tool | Parity cases | Passed | Percent |")
    want = []
    for tool in TOOLS:
        p = RESULTS[tool]["parity"]
        version = RECORDED["tools"][tool]["version"]
        pct = f"{100 * p['passed'] / p['total']:.2f}"
        want.append([f"{tool} {version}", str(p["total"]), str(p["passed"]), pct])
    assert rows == want


def test_status_suite_table_is_the_summary():
    rows = _status_rows(
        "| Suite | Tool | Total | Passed | Failed | Error | Skipped | Checks |"
    )
    want = []
    for tool in TOOLS:
        version = RECORDED["tools"][tool]["version"]
        for suite in summary.PARITY_SUITES:
            e = RESULTS[tool]["suites"][suite]
            counts = [e[k] for k in ("total", "passed", "failed", "error", "skipped")]
            want.append([suite, f"{tool} {version}", *map(str, counts), _checks(e)])
    assert rows == want


def test_status_known_failure_counts_are_the_summary():
    text = S1_STATUS.read_text(encoding="utf8")
    for tool in TOOLS:
        known = _known(tool)
        m = re.search(rf"^- {re.escape(tool)}: (\d+) ", text, re.MULTILINE)
        assert m, tool
        assert int(m.group(1)) == len(known), tool
