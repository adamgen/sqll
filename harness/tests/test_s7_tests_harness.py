"""The harness hooks of the S7 suites (T4: the harness core runs the 3 S7
suites s7_rules, s7_config, and s7_cli; S7: CLI and config parity, the
sqlfluff CLI, config, and Python rule tests as black-box cases).

"sqll-harness s7 run" runs each S7 suite for sqlfluff, sqlfluff-rs, and
sqruff, and writes the S7 report of its suites. It fails closed before a
tool runs if an assert of a converted source test has no citing check and no
row in the not-reproduced record. The S1 suites do not change.
"""

import copy
import dataclasses
import json
import os
import re
import subprocess

import pytest
from conftest import needs_all_tools

from sqll_harness import cli
from sqll_harness.cases import ERROR, FAIL, PASS
from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT
from sqll_harness.s7_tests import caseformat, command, oracle, report, suites
from sqll_harness.s7_tests.report import ReportError
from sqll_harness.s7_tests.runner import CaseOutcome, NodeOutcome
from sqll_harness.suites import SUITES as S1_SUITES

RECORDED_FILE = REPO_ROOT / "results" / "S7-tests" / "report.json"
RECORDED = json.loads(RECORDED_FILE.read_text("utf8"))
SCOPE = caseformat.load_scope()
CASES = caseformat.load()
HARNESS_RECORD = REPO_ROOT / "harness" / "not-reproduced.md"
DIRECTED = "test/cli/commands_test.py::test__cli__command_directed"


# The suites.


def test_the_s7_suites_are_apart_from_the_s1_suites():
    # "sqll-harness run" runs the S1 suites only, so the S1 report, the
    # summary, and the CI matrix do not change.
    assert set(S1_SUITES) == {"dialects", "rules", "autofix", "templater", "code_only"}
    assert not set(S1_SUITES) & set(suites.SUITES)
    assert cli._parser().parse_args(["run"]).suite is None


def test_each_group_is_in_one_suite():
    found = [g for gs in suites.SUITES.values() for g in gs]
    assert sorted(found) == sorted(report.GROUPS) == sorted(set(found))
    assert set(SCOPE["counts"]) - {"total"} == set(found)
    assert suites.suite_of("config_fixtures") == "s7_config"
    with pytest.raises(ValueError, match="unknown S7 suites"):
        suites.groups(["rules"])


def test_cli_parses_s7_run():
    args = cli._parser().parse_args(
        ["s7", "run", "--suite", "s7_cli", "--tool", "sqruff", "--jobs", "2"]
    )
    assert (args.command, args.s7_command) == ("s7", "run")
    assert args.suite == ["s7_cli"] and args.tool == ["sqruff"] and args.jobs == 2
    assert args.out == command.DEFAULT_OUT
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["s7", "run", "--suite", "rules"])
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["s7", "run", "--tool", "sqll"])


def test_require_pass_needs_the_tool(capsys):
    argv = ["s7", "run", "--tool", "sqlfluff", "--require-pass", "sqruff"]
    assert cli.main(argv) == 2
    assert "--require-pass ['sqruff'] needs --tool" in capsys.readouterr().err


# The S7 report of the suites.


def test_recorded_report_has_each_suite():
    assert RECORDED["suites"] == sorted(suites.SUITES)
    assert RECORDED["format"] == report.FORMAT == 2
    report.check(RECORDED, SCOPE)


def test_the_suite_reports_add_up_to_the_recorded_report():
    parts = [report.select_suites(RECORDED, [s], SCOPE) for s in suites.SUITES]
    for part in parts:
        report.check(part, SCOPE)
    for key in ("in_scope", "converted", "excluded", "not_yet_converted"):
        assert sum(p["counts"][key] for p in parts) == RECORDED["counts"][key], key
    for tool, parity in RECORDED["parity"].items():
        for key in ("nodes", "passed", "failed", "error"):
            assert sum(p["parity"][tool][key] for p in parts) == parity[key]
    # The pilot results of T2 (status/S7-tests.md, "Pilot (T2)").
    passed = {t: p["passed"] for t, p in RECORDED["parity"].items()}
    assert passed == {"sqlfluff": 14, "sqlfluff-rs": 13, "sqruff": 1}
    assert {t: p["nodes"] for t, p in RECORDED["parity"].items()} == {
        "sqlfluff": 14,
        "sqlfluff-rs": 14,
        "sqruff": 14,
    }


def test_the_report_lists_each_excluded_node_with_its_class():
    # Decision 2: each excluded node by node id with its class, apart from
    # parity; a reason of one line for needs-python-runtime and environment.
    want = [(e.id, e.cls) for e in CASES.exclusions]
    assert [(e["id"], e["class"]) for e in RECORDED["excluded"]] == want
    for entry in RECORDED["excluded"]:
        if entry["class"] in caseformat.NEEDS_REASON:
            assert entry["reason"].strip() and "\n" not in entry["reason"]
    excluded = {e["id"] for e in RECORDED["excluded"]}
    assert not excluded & {n["id"] for n in RECORDED["nodes"]}
    counts = RECORDED["counts"]
    assert (counts["in_scope"], counts["converted"], counts["excluded"]) == (
        643,
        15,
        3,
    )


def _outcomes(nodes, tool, status=PASS):
    reason = "" if status == PASS else "a reason"
    return [NodeOutcome(n.id, tool, [CaseOutcome("c", status, reason)]) for n in nodes]


def _cli_nodes():
    return [n for n in CASES.nodes if n.group == "cli"]


def test_build_with_one_suite():
    nodes = _cli_nodes()
    results = {
        "sqlfluff": _outcomes(nodes, "sqlfluff"),
        "sqruff": _outcomes(nodes, "sqruff", FAIL),
    }
    data = report.build(
        CASES, results, {"sqlfluff": "4.4.0", "sqruff": "0.41.0"}, ["s7_cli"]
    )
    report.check(data, SCOPE)
    assert data["suites"] == ["s7_cli"]
    counts = data["counts"]
    assert counts["in_scope"] == SCOPE["counts"]["cli"] == 295
    assert counts["converted"] == len(nodes) == 8
    assert counts["excluded"] == 2
    assert counts["groups"]["rules"]["in_scope"] == 0
    assert data["parity"]["sqruff"]["failed"] == 8
    assert data["parity"]["sqruff"]["percent_of_in_scope"] == 0.0
    assert data["parity"]["sqlfluff"]["percent_of_in_scope"] == 2.71


def test_build_refuses_a_wrong_number_of_results():
    nodes = _cli_nodes()
    with pytest.raises(ReportError, match="no result 7"):
        report.build(
            CASES,
            {"sqlfluff": _outcomes(nodes[:7], "sqlfluff")},
            {"sqlfluff": "4.4.0"},
            ["s7_cli"],
        )
    extra = _outcomes(nodes, "sqlfluff") + [NodeOutcome("x", "sqlfluff", [])]
    with pytest.raises(ReportError, match="9 results, not 8"):
        report.build(CASES, {"sqlfluff": extra}, {"sqlfluff": "4.4.0"}, ["s7_cli"])


@pytest.mark.parametrize(
    ("value", "error"),
    [
        (["s7_rules", "s7_cli"], "not a sorted list"),
        ([], "not a sorted list"),
        ("s7_cli", "not a sorted list"),
        (["s7_cli", "s7_cli"], "not a sorted list"),
        (["rules"], "not a sorted list"),
        (["s7_cli", "s7_rules"], "the group is not of the suites"),
        (["s7_config"], "the group is not of the suites"),
    ],
)
def test_check_refuses_wrong_suites(value, error):
    bad = copy.deepcopy(RECORDED)
    bad["suites"] = value
    with pytest.raises(ReportError) as info:
        report.check(bad, SCOPE)
    assert any(error in e for e in info.value.errors), info.value.errors


def test_check_refuses_counts_of_other_suites():
    # A report of one suite with the counts of all suites.
    part = report.select_suites(RECORDED, ["s7_cli"], SCOPE)
    bad = dict(part, counts=RECORDED["counts"])
    with pytest.raises(ReportError, match="the counts are not"):
        report.check(bad, SCOPE)
    bad = dict(part, parity=RECORDED["parity"])
    with pytest.raises(ReportError, match="the parity is not"):
        report.check(bad, SCOPE)


def test_select_suites_refuses_a_suite_that_the_report_does_not_have():
    part = report.select_suites(RECORDED, ["s7_cli"], SCOPE)
    with pytest.raises(ReportError, match="the report has no suites"):
        report.select_suites(part, ["s7_rules"], SCOPE)


def test_summary_lines_give_the_counts_apart_from_parity():
    lines = command.summary_lines(RECORDED)
    assert lines[1] == (
        "in scope 643, converted 15, excluded 3, not yet converted 625, "
        "needs Jinja (S11) 1"
    )
    assert lines[2] == (
        "excluded by class: python-internal 1, needs-python-runtime 1, "
        "engine-comparison 1, environment 0"
    )
    assert lines[3].startswith("sqlfluff: 14 of 14 nodes passed, 0 failed, 0 error")


# Each assert of a converted test: a check cites it, or a row has it.


def _uncite(node_id, assert_id):
    """The case set with no citation of one assert of one node."""
    nodes = []
    for node in CASES.nodes:
        if node.id == node_id:
            asserts = {k: v for k, v in node.asserts.items() if k != assert_id}
            assert len(asserts) == len(node.asserts) - 1
            node = dataclasses.replace(node, asserts=asserts)
        nodes.append(node)
    return caseformat.CaseSet(CASES.scope, nodes, CASES.exclusions)


def test_each_assert_of_the_case_files_has_a_citation_or_a_row():
    records = oracle.load_not_reproduced()
    assert records.pointer
    assert oracle.coverage_errors(CASES.nodes, SQLFLUFF_ROOT, records) == []


def test_an_assert_with_no_citation_needs_a_row():
    nodes = _uncite(DIRECTED, "L108").nodes
    none = oracle.NotReproduced([], True)
    errors = oracle.coverage_errors(nodes, SQLFLUFF_ROOT, none)
    assert errors == [
        f"{DIRECTED}: assert L108: no check cites it and no record has it"
    ]
    row = oracle.Record(DIRECTED, "L108", "a reason")
    assert (
        oracle.coverage_errors(nodes, SQLFLUFF_ROOT, oracle.NotReproduced([row], True))
        == []
    )
    # Without the pointer section, no case may use a row (decision 4).
    errors = oracle.coverage_errors(
        nodes, SQLFLUFF_ROOT, oracle.NotReproduced([row], False)
    )
    assert any("no pointer section" in e for e in errors), errors
    # A row of an assert that a check cites, and a row of a node that is
    # not converted.
    other = oracle.Record("test/cli/commands_test.py::test___main___help", "L1", "x")
    errors = oracle.coverage_errors(
        CASES.nodes, SQLFLUFF_ROOT, oracle.NotReproduced([row, other], True)
    )
    assert f"{DIRECTED}: assert L108: a check cites it and a record has it" in errors
    assert f"a not-reproduced record of {other.node}, not a converted node" in errors


def test_s7_run_fails_closed_on_a_missing_row(monkeypatch, tmp_path, capsys):
    # A case set that relies on a row that the record does not have. The
    # run stops with exit code 2 before it checks or runs a tool.
    monkeypatch.setattr(caseformat, "load", lambda: _uncite(DIRECTED, "L108"))

    def no_tools(names):
        raise AssertionError("the tools must not run")

    monkeypatch.setattr("sqll_harness.tools.check", no_tools)
    out = tmp_path / "report.json"
    assert cli.main(["s7", "run", "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert f"error: {DIRECTED}: assert L108: no check cites it" in err
    assert not out.exists()


def test_s7_run_fails_closed_on_a_case_format_error(monkeypatch, tmp_path, capsys):
    def bad_load():
        raise caseformat.CaseFormatError(["cli/x.yml: a bad case"])

    monkeypatch.setattr(caseformat, "load", bad_load)
    assert cli.main(["s7", "run", "--out", str(tmp_path / "r.json")]) == 2
    assert "error: cli/x.yml: a bad case" in capsys.readouterr().err


# The pointer section (decision 4).


def test_harness_record_has_the_pointer_section():
    text = HARNESS_RECORD.read_text("utf8")
    assert oracle.POINTER_SECTION in text.splitlines()
    section = text.split(oracle.POINTER_SECTION, 1)[1].split("\n## ", 1)[0]
    targets = re.findall(r"\]\(([^)]+)\)", section)
    record = [t for t in targets if t.endswith(oracle.NOT_REPRODUCED.name)]
    assert record, targets
    for target in targets:
        assert (HARNESS_RECORD.parent / target).resolve().is_file(), target
    assert (HARNESS_RECORD.parent / record[0]).resolve() == oracle.NOT_REPRODUCED
    assert "PROCESS.md, rule 7" in " ".join(section.split())
    words = " ".join(oracle.NOT_REPRODUCED.read_text("utf8").split())
    assert "This record is a part of the not-reproduced record of PROCESS.md" in words


# THIRD_PARTY.md (G4.3: the source and license of all external test data).


def test_third_party_names_the_s7_cases_and_the_files_they_read():
    text = (REPO_ROOT / "THIRD_PARTY.md").read_text("utf8")
    found = [
        p for p in text.split("\n\n") if p.startswith("`harness/sqll_harness/s7_tests/")
    ]
    assert len(found) == 1
    paragraph = found[0]
    folders = {f.rsplit("/", 1)[0] for f in SCOPE["files"]}
    for folder in folders:
        assert f"`{folder}/`" in paragraph, folder
    for name in ("MIT", "exclusions.yml", "scope.json", "sqll-harness s7 run"):
        assert name in paragraph, name
    assert "`test/fixtures/`" in paragraph
    for node in CASES.nodes:
        for case in node.cases:
            for arg in [*(case.argv or []), *(case.sqruff or [])]:
                if arg.startswith("test/"):
                    assert arg.startswith("test/fixtures/"), arg
                    assert (SQLFLUFF_ROOT / arg).exists(), arg


# A run of each suite (the acceptance of T4).


@needs_all_tools
@pytest.mark.parametrize("suite", list(suites.SUITES))
def test_each_suite_run_is_the_recorded_report(suite, tmp_path):
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
            "--suite",
            suite,
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
    data = json.loads(out.read_text("utf8"))
    assert data == report.select_suites(RECORDED, [suite], SCOPE)
    assert data["suites"] == [suite]
    assert list(data["tools"]) == list(suites.TOOLS)
    statuses = {n["results"]["sqlfluff"]["status"] for n in data["nodes"]}
    assert statuses == {PASS}
    assert ERROR not in {
        n["results"][t]["status"] for n in data["nodes"] for t in suites.TOOLS
    }


def test_status_file_gives_the_result_of_each_suite():
    status = (REPO_ROOT / "status" / "S7-tests.md").read_text("utf8")
    for suite in suites.SUITES:
        part = report.select_suites(RECORDED, [suite], SCOPE)
        c = part["counts"]
        cells = [f"`{suite}`", c["in_scope"], c["converted"], c["excluded"]]
        cells += [
            f"{part['parity'][t]['passed']}/{part['parity'][t]['nodes']}"
            for t in suites.TOOLS
        ]
        row = "| " + " | ".join(str(x) for x in cells) + " |"
        assert row in status.splitlines(), row
