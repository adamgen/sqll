import json

import pytest
from conftest import needs_sqlfluff

from sqll_harness import cli, merge, report, shard
from sqll_harness.cases import FAIL, PASS, CaseResult
from sqll_harness.known_failures import Outcome

SUITES = ["dialects"]
IDS = [f"dialects/ansi/case_{i}" for i in range(40)]


def _report(
    ids, status=PASS, k=None, n=None, tool="t", suite="dialects", flt=None, ref="r1"
):
    results = [
        CaseResult(id=i, suite=suite, tool=tool, status=status, checks={"exact": True})
        for i in ids
    ]
    run_shard = (k, n) if k else None
    scope = report.scope([suite], [tool], flt, run_shard)
    return report.build(
        ref, {tool: report.tool_entry("1.0")}, results, {tool: Outcome()}, scope
    )


def _shards(n, ids=IDS, **kw):
    return [
        (f"s{k}", _report([i for i in ids if shard.index(i, n) == k], k=k, n=n, **kw))
        for k in range(1, n + 1)
    ]


def _known(tmp_path, *ids, tool="t"):
    (tmp_path / f"{tool}.txt").write_text("".join(i + "\n" for i in sorted(ids)))
    return tmp_path


def test_merged_shards_equal_unsharded_run(tmp_path):
    rep, outcomes = merge.merge(_shards(4), tmp_path, SUITES)
    single = _report(IDS)
    assert rep["cases"] == single["cases"]
    assert rep["summary"] == single["summary"]
    assert rep["tools"] == single["tools"]
    assert rep["scope"] is None
    assert len(rep["parts"]) == 4
    assert all(o.ok for o in outcomes.values())


def test_listed_id_that_no_shard_ran_is_reported(tmp_path):
    # Each shard run passes alone; only the merge sees all shards.
    missing = "dialects/ansi/no_such_case"
    known = _known(tmp_path, missing)
    _, outcomes = merge.merge(_shards(3), known, SUITES)
    assert outcomes["t"].not_found == [missing]
    assert not outcomes["t"].ok


def test_listed_id_with_unknown_suite_is_reported_when_all_suites_ran(tmp_path):
    known = _known(tmp_path, "fake_case")
    _, outcomes = merge.merge(_shards(2), known, SUITES)
    assert outcomes["t"].not_found == ["fake_case"]
    # If a suite of the harness did not run, the id can be in it.
    _, outcomes = merge.merge(_shards(2), known, SUITES + ["rules"])
    assert outcomes["t"].ok


def test_a_suite_that_does_not_run_for_the_tool_is_not_needed(tmp_path):
    # code_only runs only for sqlfluff (suites.runs_for). Thus all suites
    # ran for the tool "t" with only dialects.
    known = _known(tmp_path, "fake_case")
    _, outcomes = merge.merge(_shards(2), known, SUITES + ["code_only"])
    assert outcomes["t"].not_found == ["fake_case"]
    known = _known(tmp_path, "fake_case", tool="sqlfluff")
    _, outcomes = merge.merge(
        _shards(2, tool="sqlfluff"), known, SUITES + ["code_only"]
    )
    assert outcomes["sqlfluff"].ok


def test_case_outside_the_scope_is_an_error(tmp_path):
    a, b = _shards(2)
    b[1]["cases"][0]["tool"] = "other"
    with pytest.raises(merge.MergeError, match="not in the scope"):
        merge.merge([a, b], tmp_path, SUITES)


def test_new_failure_and_listed_failure_in_shards(tmp_path):
    reports = []
    for k in (1, 2):
        ids = [i for i in IDS if shard.index(i, 2) == k]
        results = [
            CaseResult(
                id=i, suite="dialects", tool="t", status=FAIL if i in IDS[:2] else PASS
            )
            for i in ids
        ]
        scope = report.scope(SUITES, ["t"], None, (k, 2))
        reports.append(
            (
                f"s{k}",
                report.build(
                    "r1",
                    {"t": report.tool_entry("1.0")},
                    results,
                    {"t": Outcome()},
                    scope,
                ),
            )
        )
    known = _known(tmp_path, IDS[0])
    rep, outcomes = merge.merge(reports, known, SUITES)
    assert [r.id for r in outcomes["t"].new_failures] == [IDS[1]]
    assert rep["known_failures"]["t"]["new_failures"] == [IDS[1]]
    assert rep["summary"]["dialects"]["t"]["failed"] == 2


def test_missing_shard_is_an_error(tmp_path):
    reports = _shards(3)
    del reports[1]
    with pytest.raises(merge.MergeError, match="no report for shard 2/3"):
        merge.merge(reports, tmp_path, SUITES)


def test_duplicate_shard_is_an_error(tmp_path):
    reports = _shards(2)
    with pytest.raises(merge.MergeError, match="two reports"):
        merge.merge(reports + reports[:1], tmp_path, SUITES)


def test_different_shard_counts_are_an_error(tmp_path):
    with pytest.raises(merge.MergeError, match="shard counts"):
        merge.merge(_shards(2) + _shards(3), tmp_path, SUITES)


def test_different_refs_and_versions_are_errors(tmp_path):
    a, b = _shards(2)
    b[1]["sqlfluff_ref"] = "other"
    with pytest.raises(merge.MergeError, match="sqlfluff refs"):
        merge.merge([a, b], tmp_path, SUITES)
    a, b = _shards(2)
    b[1]["tools"]["t"]["version"] = "2.0"
    with pytest.raises(merge.MergeError, match="version 2.0 differs"):
        merge.merge([a, b], tmp_path, SUITES)


def test_different_tool_config_is_an_error(tmp_path):
    a, b = _shards(2)
    b[1]["tools"]["t"]["config"] = {"core": {"use_rust_parser": True}}
    with pytest.raises(merge.MergeError, match="t config or preflight differs"):
        merge.merge([a, b], tmp_path, SUITES)


def test_tool_config_and_preflight_are_kept(tmp_path):
    entry = report.tool_entry("1.0", {"core": {"x": True}}, {"check": True})
    assert entry == {
        "version": "1.0",
        "config": {"core": {"x": True}},
        "preflight": {"check": True},
    }
    assert report.tool_entry("1.0", None, {}) == {"version": "1.0"}
    a, b = _shards(2)
    a[1]["tools"]["t"] = b[1]["tools"]["t"] = entry
    rep, _ = merge.merge([a, b], tmp_path, SUITES)
    assert rep["tools"] == {"t": entry}


def test_duplicate_case_is_an_error(tmp_path):
    a, b = _shards(2)
    b[1]["cases"].append(a[1]["cases"][0])
    with pytest.raises(merge.MergeError, match="in two reports"):
        merge.merge([a, b], tmp_path, SUITES)


def test_report_with_no_scope_is_an_error(tmp_path):
    rep, _ = merge.merge(_shards(2), tmp_path, SUITES)
    with pytest.raises(merge.MergeError, match="no run scope"):
        merge.merge([("merged", rep)], tmp_path, SUITES)


def test_expected_groups(tmp_path):
    reports = _shards(2)
    merge.merge(reports, tmp_path, SUITES, [("dialects", "t", 2)])
    with pytest.raises(merge.MergeError, match="2 shards, expected 3"):
        merge.merge(reports, tmp_path, SUITES, [("dialects", "t", 3)])
    with pytest.raises(merge.MergeError, match="rules/t: no report"):
        merge.merge(reports, tmp_path, SUITES, [("rules", "t", 1)])


def test_filtered_runs_are_not_complete(tmp_path):
    known = _known(tmp_path, "dialects/ansi/no_such_case")
    reports = _shards(2, flt="dialects/ansi/")
    _, outcomes = merge.merge(reports, known, SUITES)
    assert outcomes["t"].ok


def test_two_groups_merge(tmp_path):
    reports = _shards(2) + _shards(3, tool="u")
    rep, outcomes = merge.merge(reports, tmp_path, SUITES)
    assert set(outcomes) == {"t", "u"}
    assert rep["summary"]["dialects"]["t"]["total"] == len(IDS)
    assert rep["summary"]["dialects"]["u"]["total"] == len(IDS)


def _write(tmp_path, reports):
    paths = []
    for name, rep in reports:
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(rep))
        paths.append(str(path))
    return paths


def test_cli_merge_fails_on_listed_id_that_no_shard_ran(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "SUITES", {"dialects": None})
    known = tmp_path / "known"
    known.mkdir()
    _known(known, "dialects/ansi/no_such_case")
    out = tmp_path / "report.json"
    paths = _write(tmp_path, _shards(2))
    argv = ["merge", f"--known-failures={known}", f"--out={out}", *paths]
    assert cli.main(argv) == 1
    text = capsys.readouterr().out
    assert "t: unexpected pass: dialects/ansi/no_such_case (no such case" in text
    rep = json.loads(out.read_text())
    assert rep["known_failures"]["t"]["unexpected_passes"] == [
        "dialects/ansi/no_such_case"
    ]
    (known / "t.txt").write_text("")
    assert cli.main(argv) == 0


def test_cli_merge_errors(tmp_path, capsys):
    paths = _write(tmp_path, _shards(2))
    expect = tmp_path / "matrix.json"
    expect.write_text(json.dumps([{"suite": "dialects", "tool": "t", "shards": 3}]))
    out = tmp_path / "r.json"
    assert cli.main(["merge", f"--expect={expect}", f"--out={out}", *paths]) == 2
    assert "expected 3" in capsys.readouterr().err
    assert cli.main(["merge", f"--out={out}", str(tmp_path / "missing.json")]) == 2
    assert not out.exists()


@needs_sqlfluff
def test_cli_shards_merge_to_the_unsharded_run(tmp_path):
    flt = "--filter=dialects/ansi/select_simple_"
    base = ["run", "--tool=sqlfluff", "--suite=dialects", flt]
    known = f"--known-failures={tmp_path}"
    assert cli.main([*base, known, f"--out={tmp_path / 'all.json'}"]) == 0
    paths = []
    for k in (1, 2, 3):
        path = tmp_path / f"shard{k}.json"
        assert cli.main([*base, known, f"--shard={k}/3", f"--out={path}"]) == 0
        paths.append(str(path))
    merged = tmp_path / "merged.json"
    assert cli.main(["merge", known, f"--out={merged}", *paths]) == 0

    def statuses(path):
        cases = json.loads(path.read_text())["cases"]
        return [(c["id"], c["status"], c["checks"]) for c in cases]

    assert statuses(merged) == statuses(tmp_path / "all.json")
    assert len(statuses(merged)) > 3
    sizes = [len(json.loads(open(p).read())["cases"]) for p in paths]
    assert sum(1 for s in sizes if s) >= 2
    assert sum(sizes) == len(statuses(merged))
