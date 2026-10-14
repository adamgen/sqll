import json

import pytest

from sqll_harness import cli, merge, report, shard, summary
from sqll_harness.cases import ERROR, FAIL, PASS, SKIP, CaseResult
from sqll_harness.known_failures import Outcome
from sqll_harness.paths import DEFAULT_SUMMARY, REPO_ROOT

PAIRS = {("dialects", "t"), ("templater", "t"), ("code_only", "t")}


def _results():
    def r(i, suite, status, checks, tags=()):
        return CaseResult(i, suite, "t", status, checks, tags=list(tags))

    ok = {"exact": True, "no_unparsable": True}
    return [
        r("dialects/a", "dialects", PASS, ok),
        r("dialects/b", "dialects", FAIL, {"exact": False, "no_unparsable": True}),
        r("dialects/c", "dialects", ERROR, {}),
        r("dialects/d", "dialects", SKIP, {}),
        r("templater/a", "templater", PASS, ok, ["needs_python"]),
        r("templater/b", "templater", FAIL, {"exact": False}, ["needs_python"]),
        r("templater/c", "templater", PASS, ok),
        r("code_only/a", "code_only", PASS, {"filter": True}),
    ]


def _report(results=None, flt=None, k=None, n=None, outcome=None):
    results = _results() if results is None else results
    suites = sorted({r.suite for r in results})
    scope = report.scope(suites, ["t"], flt, (k, n) if k else None)
    tools = {"t": report.tool_entry("1.0", None, {"x": "1.0"})}
    return report.build("ref", tools, results, {"t": outcome or Outcome()}, scope)


def test_counts_of_each_suite():
    got = summary.summarize(_report(), PAIRS)
    assert got["format"] == 1
    assert got["sqlfluff_ref"] == "ref"
    assert got["tools"] == {"t": {"version": "1.0", "preflight": {"x": "1.0"}}}
    t = got["results"]["t"]
    assert t["suites"]["dialects"] == {
        "total": 4,
        "passed": 1,
        "failed": 1,
        "error": 1,
        "skipped": 1,
        "checks": {"exact": 1, "no_unparsable": 2},
        "tags": {"needs_python": {"total": 0, "passed": 0}},
    }
    assert t["suites"]["templater"]["tags"] == {
        "needs_python": {"total": 2, "passed": 1}
    }
    assert t["known_failures_check"] == {"new_failures": 0, "unexpected_passes": 0}


def test_parity_is_only_of_the_parity_suites():
    t = summary.summarize(_report(), PAIRS)["results"]["t"]
    assert t["parity"] == {"suites": ["dialects", "templater"], "total": 7, "passed": 3}
    assert "code_only" in t["suites"]


def test_statuses_add_up_to_total():
    t = summary.summarize(_report(), PAIRS)["results"]["t"]
    for entry in t["suites"].values():
        n = entry["passed"] + entry["failed"] + entry["error"] + entry["skipped"]
        assert n == entry["total"]


def test_case_order_does_not_change_the_summary():
    a = summary.render(summary.summarize(_report(), PAIRS))
    b = summary.render(summary.summarize(_report(_results()[::-1]), PAIRS))
    assert a == b


def test_known_failure_check_results_are_counted():
    results = _results()
    outcome = Outcome(new_failures=results[1:3], unexpected_passes=["x"])
    t = summary.summarize(_report(outcome=outcome), PAIRS)["results"]["t"]
    assert t["known_failures_check"] == {"new_failures": 2, "unexpected_passes": 1}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"flt": "dialects/"}, "filter"),
        ({"k": 1, "n": 2}, "shard 1/2"),
    ],
)
def test_partial_run_is_refused(kwargs, message):
    with pytest.raises(summary.SummaryError, match=message):
        summary.summarize(_report(**kwargs), PAIRS)


def test_missing_or_extra_suite_is_refused():
    with pytest.raises(summary.SummaryError, match="missing code_only/t"):
        summary.summarize(_report(_results()[:-1]), PAIRS)
    with pytest.raises(summary.SummaryError, match="not expected rules/t"):
        extra = [*_results(), CaseResult("rules/x", "rules", "t", PASS)]
        summary.summarize(_report(extra), PAIRS)


def test_default_pairs_are_each_suite_for_each_tool():
    pairs = summary.full_run_pairs()
    assert ("code_only", "sqlfluff") in pairs
    assert ("code_only", "sqruff") not in pairs
    for suite in summary.PARITY_SUITES:
        for tool in ("sqlfluff", "sqlfluff-rs", "sqruff"):
            assert (suite, tool) in pairs
    with pytest.raises(summary.SummaryError, match="not a full run"):
        summary.summarize(_report())


def test_repeated_case_is_refused():
    rep = _report()
    rep["cases"].append(rep["cases"][0])
    with pytest.raises(summary.SummaryError, match="2 times"):
        summary.summarize(rep, PAIRS)


def test_unknown_status_is_refused():
    rep = _report()
    rep["cases"][0]["status"] = "flaky"
    with pytest.raises(summary.SummaryError, match="unknown status"):
        summary.summarize(rep, PAIRS)


def test_tool_with_no_cases_is_refused():
    rep = _report()
    rep["tools"]["u"] = {"version": "2"}
    with pytest.raises(summary.SummaryError, match="not the report tools"):
        summary.summarize(rep, PAIRS)


def _shards(n):
    results = _results()
    out = []
    for k in range(1, n + 1):
        part = [r for r in results if shard.index(r.id, n) == k]
        out.append((f"s{k}", _report(part, k=k, n=n)))
    return out


def test_merged_report_gives_the_summary_of_the_single_run(tmp_path):
    # The shard parts must each have all suites in their scope, as in CI.
    parts = []
    for name, rep in _shards(3):
        rep["scope"]["suites"] = sorted({s for s, _ in PAIRS})
        parts.append((name, rep))
    failing = sorted(r.id for r in _results() if r.status in (FAIL, ERROR))
    (tmp_path / "t.txt").write_text("".join(i + "\n" for i in failing))
    merged, outcomes = merge.merge(parts, tmp_path, sorted({s for s, _ in PAIRS}))
    assert outcomes["t"].ok
    assert summary.summarize(merged, PAIRS) == summary.summarize(_report(), PAIRS)


def test_merged_report_with_a_filter_is_refused():
    rep = _report()
    rep["scope"] = None
    rep["parts"] = [{"suites": ["dialects"], "tools": ["t"], "filter": "x"}]
    with pytest.raises(summary.SummaryError, match="filter"):
        summary.summarize(rep, PAIRS)
    rep["parts"] = []
    with pytest.raises(summary.SummaryError, match="no scope"):
        summary.summarize(rep, PAIRS)


def test_diff(tmp_path):
    s = summary.summarize(_report(), PAIRS)
    path = tmp_path / "summary.json"
    summary.write(s, path)
    assert summary.diff(s, path) == []
    # A mutated record: one passed case more.
    data = json.loads(path.read_text())
    data["results"]["t"]["suites"]["dialects"]["passed"] += 1
    path.write_text(json.dumps(data, indent=1) + "\n")
    lines = summary.diff(s, path)
    assert any(line.startswith("-") and '"passed": 2' in line for line in lines)
    assert any(line.startswith("+") and '"passed": 1' in line for line in lines)
    # Only the format is different: this is also a difference.
    path.write_text(json.dumps(s, indent=2) + "\n")
    assert summary.diff(s, path) != []
    assert summary.diff(s, tmp_path / "missing.json")[0].startswith("cannot read")


def _write_report(tmp_path, rep):
    path = tmp_path / "report.json"
    report.write(rep, path)
    return path


def test_cli_writes_and_checks(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(summary, "full_run_pairs", lambda: PAIRS)
    rep = _write_report(tmp_path, _report())
    out = tmp_path / "out" / "summary.json"
    assert cli.main(["summarize", str(rep), "--out", str(out)]) == 0
    recorded = tmp_path / "recorded.json"
    recorded.write_text(out.read_text())
    args = ["summarize", str(rep), "--out", str(out), "--check", str(recorded)]
    assert cli.main(args) == 0
    assert "is equal to the summary" in capsys.readouterr().out
    recorded.write_text(out.read_text().replace('"passed": 1', '"passed": 9', 1))
    assert cli.main(args) == 1
    assert "FAIL" in capsys.readouterr().out


def test_cli_refuses_a_partial_report(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(summary, "full_run_pairs", lambda: PAIRS)
    rep = _write_report(tmp_path, _report(flt="dialects/"))
    out = tmp_path / "summary.json"
    assert cli.main(["summarize", str(rep), "--out", str(out)]) == 2
    assert not out.exists()
    assert "filter" in capsys.readouterr().err


def test_default_out_is_the_recorded_s1_summary():
    assert DEFAULT_SUMMARY == REPO_ROOT / "results" / "s1" / "summary.json"
