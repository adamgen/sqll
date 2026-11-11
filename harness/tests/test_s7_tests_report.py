"""The S7 report (sqll_harness/s7_tests/report.py) and the recorded pilot
report results/S7-tests/report.json.

The recorded report must agree with the case files and the exclusion list,
and with a new run of "sqll-harness s7 run". Each fail-closed check of
report.check() has a mutation test.
"""

import copy
import json
import os
import subprocess

import pytest
from conftest import needs_all_tools

from sqll_harness.cases import ERROR, FAIL, PASS
from sqll_harness.paths import REPO_ROOT
from sqll_harness.s7_tests import caseformat, report
from sqll_harness.s7_tests.report import ReportError
from sqll_harness.s7_tests.runner import CaseOutcome, NodeOutcome

RECORDED_FILE = REPO_ROOT / "results" / "S7-tests" / "report.json"
RECORDED = json.loads(RECORDED_FILE.read_text("utf8"))
SCOPE = caseformat.load_scope()
CASES = caseformat.load()
STATUS = (REPO_ROOT / "status" / "S7-tests.md").read_text("utf8")


# The recorded report.


def test_recorded_report_passes_the_check():
    report.check(RECORDED, SCOPE)


def test_recorded_report_has_the_case_files_and_the_exclusions():
    assert [n["id"] for n in RECORDED["nodes"]] == [n.id for n in CASES.nodes]
    assert [n["cases"] for n in RECORDED["nodes"]] == [
        len(n.cases) for n in CASES.nodes
    ]
    assert [n["case_file"] for n in RECORDED["nodes"]] == [
        n.case_file for n in CASES.nodes
    ]
    assert RECORDED["excluded"] == [
        {"id": e.id, "group": e.group, "class": e.cls, "reason": e.reason}
        for e in CASES.exclusions
    ]
    assert list(RECORDED["tools"]) == ["sqlfluff", "sqlfluff-rs", "sqruff"]


def test_recorded_counts():
    counts = RECORDED["counts"]
    assert counts["in_scope"] == SCOPE["counts"]["total"] == 643
    assert counts["converted"] + counts["excluded"] + counts["not_yet_converted"] == 643
    # The pilot: nodes of each group of the 3 suites.
    for group in ("cli", "rules", "config"):
        assert counts["groups"][group]["converted"] > 0, group
    assert sum(counts["excluded_by_class"].values()) == counts["excluded"]


def test_sqlfluff_passes_each_pilot_node():
    for node in RECORDED["nodes"]:
        assert node["results"]["sqlfluff"] == {"status": PASS, "failed_cases": []}
    parity = RECORDED["parity"]["sqlfluff"]
    assert parity["percent_of_converted"] == 100.0
    assert RECORDED["s11_jinja"]["sqlfluff"]["percent_of_converted"] == 100.0


def test_each_failure_has_a_reason():
    # A sqruff case that uses an item that sqruff does not support fails
    # with "unsupported: <item>". Each other failure has a reason too.
    for node in RECORDED["nodes"]:
        for tool, result in node["results"].items():
            for case in result["failed_cases"]:
                assert case["reason"], (node["id"], tool)
    reasons = [
        c["reason"]
        for n in RECORDED["nodes"]
        for c in n["results"]["sqruff"]["failed_cases"]
    ]
    assert any(r.startswith("unsupported: ") for r in reasons)


def test_status_file_gives_the_recorded_counts():
    words = " ".join(STATUS.split())
    counts = RECORDED["counts"]
    assert (
        f"in scope {counts['in_scope']}, converted {counts['converted']}, "
        f"excluded {counts['excluded']}, not yet converted "
        f"{counts['not_yet_converted']}" in words
    )
    groups = counts["groups"]
    assert (
        f"`cli` {groups['cli']['converted']}, `rules` {groups['rules']['converted']}, "
        f"`config` {groups['config']['converted']}." in words
    )
    s7 = [n for n in RECORDED["nodes"] if not n["needs_jinja"]]
    unsupported = [
        n
        for n in s7
        if n["results"]["sqruff"]["failed_cases"]
        and all(
            c["reason"].startswith("unsupported: ")
            for c in n["results"]["sqruff"]["failed_cases"]
        )
    ]
    assert f"sqruff: {len(unsupported)} nodes fail with `unsupported: <item>`" in words
    for tool, parity in RECORDED["parity"].items():
        assert (
            f"| {tool} | {parity['nodes']} | {parity['passed']} | "
            f"{parity['failed']} | {parity['error']} |" in STATUS
        ), tool


@needs_all_tools
def test_recorded_report_is_the_runner_output(tmp_path):
    # A new run of all tools gives the recorded report, sqlfluff passes each
    # node, and the run does not change the submodule (G4.5).
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--quiet",
            "--frozen",
            "--project",
            str(REPO_ROOT / "harness"),
            "sqll-harness",
            "s7",
            "run",
            "--out",
            str(out),
            "--require-pass",
            "sqlfluff",
            "--check",
            str(RECORDED_FILE),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert json.loads(out.read_text("utf8")) == RECORDED
    check = subprocess.run(
        [str(REPO_ROOT / "scripts" / "check-submodule"), "after the S7 cases"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stderr


# report.build and report.check with a small case set.


def small_set():
    """3 cli nodes of scope.json with 1 case each, and the recorded
    exclusions (one node of each class but environment)."""
    case = caseformat.Case("c0", "cli", {"exit_code": 0}, argv=["version"])
    ids = [n["id"] for n in SCOPE["nodes"] if n["group"] == "cli"]
    excluded = {e.id for e in CASES.exclusions}
    ids = [i for i in ids if i not in excluded][:3]
    nodes = [caseformat.Node(i, "cli", "cli/commands_test.yml", [case]) for i in ids]
    return caseformat.CaseSet(SCOPE, nodes, CASES.exclusions)


def outcomes(cases, tool: str, statuses: list[list[str]]) -> list[NodeOutcome]:
    out = []
    for node, node_statuses in zip(cases.nodes, statuses, strict=True):
        out.append(
            NodeOutcome(
                node.id,
                tool,
                [
                    CaseOutcome(f"c{i}", s, "" if s == PASS else f"reason {i}")
                    for i, s in enumerate(node_statuses)
                ],
            )
        )
    return out


def built() -> dict:
    cases = small_set()
    results = {
        "sqlfluff": outcomes(cases, "sqlfluff", [[PASS], [PASS], [PASS]]),
        "sqruff": outcomes(cases, "sqruff", [[PASS], [FAIL], [ERROR]]),
    }
    return report.build(cases, results, {"sqlfluff": "4.4.0", "sqruff": "0.41.0"})


def test_build():
    data = built()
    assert data["counts"]["in_scope"] == 643
    assert data["counts"]["converted"] == 3
    assert data["counts"]["excluded"] == len(CASES.exclusions)
    assert data["counts"]["not_yet_converted"] == 643 - 3 - len(CASES.exclusions)
    statuses = [n["results"]["sqruff"]["status"] for n in data["nodes"]]
    assert statuses == [PASS, FAIL, ERROR]
    assert data["nodes"][1]["results"]["sqruff"]["failed_cases"] == [
        {"name": "c0", "status": FAIL, "reason": "reason 0"}
    ]
    parity = data["parity"]["sqruff"]
    assert parity == {
        "nodes": 3,
        "passed": 1,
        "failed": 1,
        "error": 1,
        "percent_of_converted": 33.33,
        "percent_of_in_scope": 0.16,
    }
    # The excluded nodes are apart from parity.
    assert data["excluded"][0]["class"] in caseformat.CLASSES
    assert report.select_tools(data, ["sqlfluff"])["tools"] == {
        "sqlfluff": {"version": "4.4.0"}
    }


def test_build_refuses_results_out_of_order():
    cases = small_set()
    results = {"sqlfluff": outcomes(cases, "sqlfluff", [[PASS]] * 3)[::-1]}
    with pytest.raises(ReportError, match="result 0 is"):
        report.build(cases, results, {"sqlfluff": "4.4.0"})


def _excluded_index(data: dict, cls: str) -> int:
    return next(i for i, e in enumerate(data["excluded"]) if e["class"] == cls)


def _mutations():
    """(name, function that changes a report, expected error)."""

    def setter(path, value):
        def change(data):
            target = data
            keys = path.split(".")
            for key in keys[:-1]:
                target = target[int(key)] if key.isdigit() else target[key]
            target[keys[-1]] = value

        return change

    def reason_of(cls, value):
        def change(data):
            data["excluded"][_excluded_index(data, cls)]["reason"] = value

        return change

    def add_excluded(entry):
        return lambda data: data["excluded"].append(entry)

    def environment_without_reason(data):
        entry = data["excluded"][_excluded_index(data, "python-internal")]
        entry["class"] = "environment"
        entry["reason"] = None

    return [
        # A missing reason of a needs-python-runtime or environment node.
        (
            "no reason, needs-python-runtime",
            reason_of("needs-python-runtime", None),
            "class needs-python-runtime needs a reason",
        ),
        (
            "no reason, environment",
            environment_without_reason,
            "class environment needs a reason",
        ),
        (
            "reason of 2 lines",
            reason_of("needs-python-runtime", "a\nb"),
            "the reason is not one line",
        ),
        ("empty reason", reason_of("engine-comparison", " "), "not one line"),
        # An unknown class.
        ("unknown class", setter("excluded.0.class", "slow"), "unknown class 'slow'"),
        # Counts that are not those of the lists.
        ("in-scope total", setter("counts.in_scope", 600), "the counts are not"),
        ("converted count", setter("counts.converted", 2), "the counts are not"),
        ("excluded count", setter("counts.excluded", 0), "the counts are not"),
        (
            "not yet converted",
            setter("counts.not_yet_converted", 0),
            "the counts are not",
        ),
        (
            "class count",
            setter("counts.excluded_by_class.environment", 1),
            "the counts are not",
        ),
        (
            "group count",
            setter("counts.groups.cli.converted", 0),
            "the counts are not",
        ),
        # Parity that is not that of the nodes.
        ("parity", setter("parity.sqruff.passed", 3), "the parity is not"),
        ("percent", setter("parity.sqruff.percent_of_converted", 100.0), "parity"),
        ("s11", setter("s11_jinja.sqruff.nodes", 1), "the s11_jinja result is not"),
        # Node lists.
        (
            "node not in scope",
            setter("nodes.0.id", "test/cli/x_test.py::test_x"),
            "not in scope.json",
        ),
        ("wrong group", setter("nodes.0.group", "rules"), "the group is not"),
        (
            "node also excluded",
            lambda d: d["excluded"].append(
                {
                    "id": d["nodes"][0]["id"],
                    "group": d["nodes"][0]["group"],
                    "class": "python-internal",
                    "reason": None,
                }
            ),
            "in the report 2 times",
        ),
        (
            "excluded node not in scope",
            add_excluded(
                {
                    "id": "x::y",
                    "group": "cli",
                    "class": "python-internal",
                    "reason": None,
                }
            ),
            "x::y: not in scope.json",
        ),
        (
            "excluded extra key",
            setter("excluded.0.note", "x"),
            "an excluded node has other keys",
        ),
        # Statuses that are not those of the cases.
        ("status", setter("nodes.1.results.sqruff.status", PASS), "but its cases give"),
        ("error status", setter("nodes.2.results.sqruff.status", FAIL), "cases give"),
        (
            "case status",
            setter("nodes.1.results.sqruff.failed_cases.0.status", PASS),
            "a failed case has the status",
        ),
        (
            "case reason",
            setter("nodes.1.results.sqruff.failed_cases.0.reason", ""),
            "a failed case has no reason",
        ),
        (
            "node status",
            setter("nodes.0.results.sqruff.status", "skip"),
            "unknown status",
        ),
        ("missing tool", lambda d: d["nodes"][0]["results"].pop("sqruff"), "the tools"),
        ("unknown tool", setter("tools.sqll", {"version": "0"}), "are not a part of"),
        ("kind", setter("kind", "other"), "not a sqll-s7-tests-report"),
        ("pin", setter("sqlfluff.commit", "0348222a"), "not the pin"),
        ("extra key", setter("note", 1), "the report keys are not"),
    ]


@pytest.mark.parametrize(
    ("change", "error"),
    [(m[1], m[2]) for m in _mutations()],
    ids=[m[0] for m in _mutations()],
)
def test_report_mutation_is_refused(change, error):
    data = built()
    report.check(data, SCOPE)
    bad = copy.deepcopy(data)
    change(bad)
    with pytest.raises(ReportError) as info:
        report.check(bad, SCOPE)
    assert any(error in e for e in info.value.errors), info.value.errors


def test_check_refuses_a_scope_with_a_wrong_total():
    data = built()
    scope = dict(SCOPE, counts=dict(SCOPE["counts"], total=642))
    with pytest.raises(ReportError, match="the node list is not the total count"):
        report.check(data, scope)


def test_check_refuses_more_nodes_than_scope():
    data = built()
    scope = dict(SCOPE, nodes=SCOPE["nodes"][:5])
    scope["counts"] = dict(SCOPE["counts"], total=5)
    with pytest.raises(ReportError):
        report.check(data, scope)
