"""The CI jobs and the recorded results of the S7 suites (T5: CI jobs, oracle
step, and local verify for the S7 suites; CI and scripts/verify run the S7
suites and record the results; S7: CLI and config parity, the sqlfluff CLI,
config, and Python rule tests as black-box cases).

The known failures (results/S7-tests/known_failures/<tool>.txt), the merge of
the reports of the s7 jobs, and the recorded summary
(results/S7-tests/summary.json).
"""

import copy
import json

import pytest
from conftest import needs_all_tools

from sqll_harness import cli
from sqll_harness.cases import FAIL, PASS
from sqll_harness.paths import REPO_ROOT
from sqll_harness.s7_tests import caseformat, known, report, suites
from sqll_harness.s7_tests import summary as s7_summary

RESULTS = REPO_ROOT / "results" / "S7-tests"
KNOWN = RESULTS / "known_failures"
RECORDED = json.loads((RESULTS / "report.json").read_text("utf8"))
SUMMARY_FILE = RESULTS / "summary.json"
SCOPE = caseformat.load_scope()
CASES = caseformat.load()
DIRECTED = "test/cli/commands_test.py::test__cli__command_directed"
DIALECT = "test/cli/commands_test.py::test__cli__command_dialect"
CV02 = "test/rules/std_CV02_test.py::test__rules__std_CV02_raised"


def _parts(data=RECORDED):
    """The report of each suite and tool, as the s7 jobs write them."""
    parts = [
        (
            f"{s}-{t}",
            report.select_suites(report.select_tools(data, [t]), [s], SCOPE),
        )
        for s in data["suites"]
        for t in data["tools"]
    ]
    # Each part has its own data, as a file of a job.
    return json.loads(json.dumps(parts))


# The known failures.


def test_the_known_failures_are_the_failures_of_the_recorded_report():
    for tool in suites.TOOLS:
        listed = known.load(KNOWN, tool, SCOPE)
        failed = {
            n["id"] for n in RECORDED["nodes"] if n["results"][tool]["status"] != PASS
        }
        assert set(listed) == failed, tool
        assert all(listed.values()), tool
    assert known.check(RECORDED, KNOWN, SCOPE) == []


def test_sqlfluff_has_no_known_failure():
    # sqlfluff passes 100% of the converted nodes.
    assert (KNOWN / "sqlfluff.txt").exists()
    assert known.load(KNOWN, "sqlfluff", SCOPE) == {}
    assert RECORDED["parity"]["sqlfluff"]["failed"] == 0
    assert RECORDED["parity"]["sqlfluff"]["error"] == 0


def test_the_other_tools_have_their_failures_with_a_reason():
    assert set(known.load(KNOWN, "sqlfluff-rs", SCOPE)) == {DIRECTED}
    sqruff = known.load(KNOWN, "sqruff", SCOPE)
    assert len(sqruff) == 14 and DIALECT in sqruff
    assert (
        "Keywords must be consistent."
        in known.load(KNOWN, "sqlfluff-rs", SCOPE)[DIRECTED]
    )


def test_no_node_id_has_the_comment_mark():
    # The list format cuts each line at "#".
    assert not [n["id"] for n in SCOPE["nodes"] if "#" in n["id"]]
    assert not [n["id"] for n in SCOPE["nodes"] if n["id"] != n["id"].strip()]


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (f"{DIRECTED}  # b\n{DIALECT}  # a\n", "not sorted"),
        (f"{DIALECT}  # a\n{DIALECT}  # a\n", "duplicate"),
        ("test/cli/x_test.py::test_x  # a\n", "not a node of scope.json"),
        (f"{DIALECT}\n", "no reason"),
        (f"{DIALECT}  #   \n", "no reason"),
    ],
)
def test_a_bad_list_is_an_error(text, error):
    with pytest.raises(known.KnownFailuresError, match=error):
        known.parse(text, "x.txt", SCOPE)


def test_comment_lines_are_not_ids():
    assert known.parse("# a comment\n\n", "x.txt", SCOPE) == {}


def test_render_gives_the_list_of_a_report():
    text = known.render(RECORDED, "sqruff")
    assert list(known.parse(text, "x", SCOPE)) == list(
        known.load(KNOWN, "sqruff", SCOPE)
    )
    assert known.render(RECORDED, "sqlfluff") == ""


def test_a_long_reason_is_cut():
    result = {"failed_cases": [{"name": "c", "reason": "x" * 1000}]}
    assert len(known.reason(result)) == known.REASON_LIMIT


def test_a_new_failure_and_an_unexpected_pass_are_found():
    data = copy.deepcopy(RECORDED)
    for node in data["nodes"]:
        if node["id"] == CV02:
            node["results"]["sqlfluff"] = {
                "status": FAIL,
                "failed_cases": [{"name": "raised", "status": FAIL, "reason": "r"}],
            }
        if node["id"] == DIRECTED:
            node["results"]["sqlfluff-rs"] = {"status": PASS, "failed_cases": []}
    lines = known.check(data, KNOWN, SCOPE)
    assert lines == [
        f"sqlfluff: new failure: {CV02}: raised: r",
        f"sqlfluff-rs: unexpected pass: {DIRECTED}",
    ]


def test_a_listed_node_that_did_not_run_is_found():
    data = report.select_suites(RECORDED, ["s7_cli"], SCOPE)
    data["nodes"] = [n for n in data["nodes"] if n["id"] != DIALECT]
    lines = known.evaluate(data, "sqruff", known.load(KNOWN, "sqruff", SCOPE), SCOPE)
    assert lines == [
        f"sqruff: unexpected pass: {DIALECT} (not a converted node of the report;"
        " remove it from the list)"
    ]


def test_a_listed_node_of_another_suite_is_not_checked():
    part = report.select_suites(RECORDED, ["s7_config"], SCOPE)
    assert known.check(part, KNOWN, SCOPE) == []


# The merge of the reports of the s7 jobs.


def test_the_merge_of_the_job_reports_is_the_recorded_report():
    parts = _parts()
    assert len(parts) == 9
    assert report.merge(parts, CASES) == RECORDED
    assert report.merge(list(reversed(parts)), CASES) == RECORDED


def test_a_merge_of_some_suites_is_their_report():
    parts = [p for p in _parts() if not p[0].startswith("s7_cli")]
    want = report.select_suites(RECORDED, ["s7_config", "s7_rules"], SCOPE)
    assert report.merge(parts, CASES) == want


def _merge_error(parts) -> str:
    with pytest.raises(report.ReportError) as exc:
        report.merge(parts, CASES)
    return str(exc.value)


def test_a_bad_merge_is_an_error():
    parts = _parts()
    assert "no reports" in _merge_error([])
    assert "is also in" in _merge_error(parts + parts[:1])
    assert "no report of the tools ['sqruff']" in _merge_error(
        [p for p in parts if p[0] != "s7_cli-sqruff"]
    )
    other = copy.deepcopy(parts)
    other[0][1]["tools"]["sqlfluff"]["version"] = "0.0.0"
    assert "sqlfluff has the version 4.4.0, not the version 0.0.0" in _merge_error(
        other
    )
    other = copy.deepcopy(parts)
    other[1][1]["nodes"] = other[1][1]["nodes"][1:]
    assert "the counts are not those" in _merge_error(other)


def test_a_part_with_other_nodes_is_an_error():
    parts = copy.deepcopy(_parts())
    name, part = parts[1]
    part["nodes"][0]["cases"] += 1
    assert f"{name}: the nodes of" in _merge_error(parts)


# The summary.


def test_the_recorded_summary_is_the_summary_of_the_recorded_report():
    result = s7_summary.summarize(RECORDED, SCOPE)
    assert s7_summary.text(result) == SUMMARY_FILE.read_text("utf8")
    assert s7_summary.diff(result, SUMMARY_FILE) == []
    assert result["known_failures"] == {
        t: len(known.load(KNOWN, t, SCOPE)) for t in suites.TOOLS
    }
    by_suite = result["suite_results"]
    assert set(by_suite) == set(suites.SUITES)
    assert sum(s["in_scope"] for s in by_suite.values()) == 643
    assert (
        sum(s["parity"]["sqlfluff"]["nodes"] for s in by_suite.values())
        == (result["parity"]["sqlfluff"]["nodes"])
    )


def test_a_summary_needs_all_suites_and_tools():
    with pytest.raises(s7_summary.SummaryError, match="suites"):
        s7_summary.summarize(report.select_suites(RECORDED, ["s7_cli"], SCOPE), SCOPE)
    with pytest.raises(s7_summary.SummaryError, match="tools"):
        s7_summary.summarize(report.select_tools(RECORDED, ["sqlfluff"]), SCOPE)
    bad = copy.deepcopy(RECORDED)
    bad["counts"]["converted"] += 1
    with pytest.raises(s7_summary.SummaryError, match="counts"):
        s7_summary.summarize(bad, SCOPE)


# The commands.


def _write_parts(tmp_path, parts):
    paths = []
    for name, part in parts:
        path = tmp_path / "shards" / f"{name}.json"
        report.write(part, path)
        paths.append(str(path))
    return paths


def test_s7_merge_command(tmp_path, capsys):
    paths = _write_parts(tmp_path, _parts())
    out = tmp_path / "report.json"
    matrix = str(REPO_ROOT / "ci" / "matrix.d")
    argv = ["s7", "merge", "--expect", matrix, *paths, "--out", str(out)]
    assert cli.main([*argv, "--known-failures", str(KNOWN)]) == 0
    assert json.loads(out.read_text()) == RECORDED
    assert "The results are the known failures" in capsys.readouterr().out
    # A missing job report.
    assert cli.main(["s7", "merge", "--expect", matrix, *paths[:-1]]) == 2
    assert "no report of the tools ['sqruff']" in capsys.readouterr().err
    # A missing suite.
    assert cli.main(["s7", "merge", "--expect", matrix, *paths[3:]]) == 2
    assert "not those of" in capsys.readouterr().err
    # A list that is not the results.
    lists = tmp_path / "known"
    lists.mkdir()
    for tool in ("sqlfluff", "sqlfluff-rs"):
        (lists / f"{tool}.txt").write_text((KNOWN / f"{tool}.txt").read_text())
    assert cli.main([*argv, "--known-failures", str(lists)]) == 1
    text = capsys.readouterr().out
    assert f"sqruff: new failure: {DIALECT}" in text
    assert "FAIL: the results are not the known failures" in text
    # A list that is not valid.
    (lists / "sqruff.txt").write_text(f"{DIALECT}\n")
    assert cli.main([*argv, "--known-failures", str(lists)]) == 2
    assert "no reason" in capsys.readouterr().err


def test_s7_merge_expects_1_shard(tmp_path, capsys):
    folder = tmp_path / "matrix.d"
    folder.mkdir()
    (folder / "a.json").write_text(
        json.dumps([{"suite": "s7_cli", "tool": "sqlfluff", "shards": 2}])
    )
    paths = _write_parts(tmp_path, _parts())
    assert cli.main(["s7", "merge", "--expect", str(folder), *paths]) == 2
    assert "1 shard" in capsys.readouterr().err


def test_s7_summarize_command(tmp_path, capsys):
    src = tmp_path / "report.json"
    report.write(RECORDED, src)
    out = tmp_path / "summary.json"
    argv = ["s7", "summarize", str(src), "--out", str(out)]
    assert cli.main([*argv, "--check", str(SUMMARY_FILE)]) == 0
    assert out.read_text() == SUMMARY_FILE.read_text()
    assert "is equal to the summary" in capsys.readouterr().out
    other = tmp_path / "other.json"
    other.write_text(SUMMARY_FILE.read_text().replace('"known_failures"', '"x"'))
    assert cli.main([*argv, "--check", str(other)]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert cli.main([*argv, "--check", str(out)]) == 2
    report.write(report.select_tools(RECORDED, ["sqruff"]), src)
    assert cli.main(argv) == 2


def test_s7_known_failures_command(tmp_path, capsys):
    src = tmp_path / "report.json"
    report.write(RECORDED, src)
    assert cli.main(["s7", "known-failures", str(src), "--tool", "sqruff"]) == 0
    assert capsys.readouterr().out == known.render(RECORDED, "sqruff")
    report.write(report.select_tools(RECORDED, ["sqlfluff"]), src)
    assert cli.main(["s7", "known-failures", str(src), "--tool", "sqruff"]) == 2


@needs_all_tools
def test_s7_run_checks_the_known_failures(tmp_path, capsys):
    out = tmp_path / "report.json"
    argv = ["s7", "run", "--suite", "s7_config", "--tool", "sqruff", "--out", str(out)]
    assert cli.main([*argv, "--known-failures", str(KNOWN)]) == 0
    assert "The results are the known failures" in capsys.readouterr().out
    lists = tmp_path / "known"
    lists.mkdir()
    lines = (KNOWN / "sqruff.txt").read_text().splitlines(keepends=True)
    glob = "test/core/config/fluffconfig_test.py::test__config__glob_include"
    # A new failure: a failed node is not in the list.
    (lists / "sqruff.txt").write_text(
        "".join(x for x in lines if not x.startswith(glob))
    )
    assert cli.main([*argv, "--known-failures", str(lists)]) == 1
    assert f"sqruff: new failure: {glob}" in capsys.readouterr().out
    # An unexpected pass: a listed node of the suite is not a failed node.
    unconverted = next(
        n["id"]
        for n in SCOPE["nodes"]
        if n["group"] == "config"
        and n["id"] not in {x["id"] for x in RECORDED["nodes"]}
    )
    (lists / "sqruff.txt").write_text(
        "".join(sorted([*lines, f"{unconverted}  # x\n"]))
    )
    assert cli.main([*argv, "--known-failures", str(lists)]) == 1
    assert f"sqruff: unexpected pass: {unconverted}" in capsys.readouterr().out


def test_status_file_gives_the_known_failures():
    status = (REPO_ROOT / "status" / "S7-tests.md").read_text("utf8")
    section = status[status.index("\n## CI and recorded results (T5)\n") :]
    counts = json.loads(SUMMARY_FILE.read_text("utf8"))["known_failures"]
    for tool, count in counts.items():
        assert f"\n| {tool} | {count} | " in section, tool
