"""sqll-harness bench compare (harness/bench.md, "Slowdowns"), with synthetic
reports."""

import copy
import json
import re
from pathlib import Path

import pytest
from test_bench_report import SHA, invalid, make, sample, valid

from sqll_harness import cli
from sqll_harness.bench import compare, report, timer
from sqll_harness.bench import run as bench_run
from sqll_harness.bench.timer import ERROR, INVALID, UNSUPPORTED, Measurement
from sqll_harness.paths import REPO_ROOT

NOISE = {"wall_pct": 0.25, "cpu_pct": 0.1, "k": 3.0, "min_diff_s": 0.005}
START = "start/ansi"
PARSE = "parse/ansi/small"


def same(*walls: float) -> dict:
    """The same valid result for each benchmark of tool a."""
    return {(START, "a"): valid(*walls), (PARSE, "a"): valid(*walls)}


def run(tmp_path: Path, base: dict | None, new: dict, *args: str):
    """Run the command. Return (exit code, compare output or None)."""
    paths = []
    for name, rep in (("base", base), ("new", new)):
        if rep is not None:
            path = tmp_path / f"{name}.json"
            path.write_text(json.dumps(rep), encoding="utf8")
            paths.append(str(path))
    out = tmp_path / "compare.json"
    # An old output must not stay after a refusal.
    out.write_text("old")
    code = cli.main(["bench", "compare", *paths, "--out", str(out), *args])
    return code, json.loads(out.read_text()) if out.exists() else None


def entry(result: dict, bid: str, tool: str) -> dict:
    (e,) = [e for e in result["benchmarks"] if e["id"] == bid and e["tool"] == tool]
    return e


# Slowdowns and the noise limit.


def test_a_slowdown_above_the_noise_limit_is_flagged(tmp_path, capsys):
    base = make(same(1.0, 1.0, 1.0))
    new = make({(START, "a"): valid(1.5, 1.5, 1.5), (PARSE, "a"): valid(1.0, 1.0, 1.0)})
    code, result = run(tmp_path, base, new)
    assert code == 1
    e = entry(result, START, "a")
    assert e["change"] == compare.SLOWER
    assert e["wall"] == {
        "base": 1.0,
        "new": 1.5,
        "ratio": 1.5,
        "limit": 0.25,
        "change": compare.SLOWER,
    }
    assert e["cpu"]["ratio"] == 1.5 and e["cpu"]["change"] == compare.SLOWER
    assert entry(result, PARSE, "a")["change"] == compare.SAME
    assert result["counts"][compare.SLOWER] == 1
    assert result["ok"] is False
    out = capsys.readouterr().out
    assert "slower: a start/ansi: wall 1.000 -> 1.500 s (1.500, limit 1.250)" in out
    assert "FAIL: 1 slower, 0 valid to not valid." in out
    assert "(PROCESS.md)" in out


def test_a_change_inside_the_noise_limit_is_not_flagged(tmp_path, capsys):
    base = make(same(1.0, 1.0, 1.0))
    # Wall time 1.09, CPU time 0.5 -> 0.545.
    new = make(same(1.09, 1.09, 1.09))
    code, result = run(tmp_path, base, new)
    assert code == 0, capsys.readouterr()
    assert {e["change"] for e in result["benchmarks"]} == {compare.SAME}
    assert result["ok"] is True
    assert result["counts"] == {
        "compared": 2,
        "slower": 0,
        "faster": 0,
        "same": 2,
        "failure": 0,
        "status": 0,
        "not_valid": 0,
    }


def test_a_faster_result_is_reported_and_does_not_fail(tmp_path):
    code, result = run(tmp_path, make(same(1.0, 1.0, 1.0)), make(same(0.5, 0.5, 0.5)))
    assert code == 0
    assert {e["change"] for e in result["benchmarks"]} == {compare.FASTER}


def test_a_slower_cpu_time_alone_is_flagged():
    base = {"n": 3, "median": 1.0, "min": 1.0, "max": 1.0, "mad": 0.0}
    m = compare.metric("cpu", base, {**base, "median": 1.2})
    assert m["change"] == compare.SLOWER
    b = make(same(1.0, 1.0, 1.0))
    n = copy.deepcopy(b)
    r = [r for r in n["results"] if r["id"] == START][0]
    r["stats"]["cpu_s"]["median"] = 0.6  # wall the same, cpu 0.5 -> 0.6
    e = compare.benchmark_entry([r for r in b["results"] if r["id"] == START][0], r)
    assert e["wall"]["change"] == compare.SAME
    assert e["cpu"]["change"] == compare.SLOWER and e["change"] == compare.SLOWER


@pytest.mark.parametrize(
    "name, base_walls, new_walls, limit, change",
    [
        # No spread: the fixed part, 25% for wall time, 10% for CPU time.
        ("wall", (1.0, 1.0, 1.0), (1.3, 1.3, 1.3), 0.25, compare.SLOWER),
        ("wall", (1.0, 1.0, 1.0), (1.2, 1.2, 1.2), 0.25, compare.SAME),
        ("cpu", (1.0, 1.0, 1.0), (1.12, 1.12, 1.12), 0.1, compare.SLOWER),
        ("cpu", (1.0, 1.0, 1.0), (1.08, 1.08, 1.08), 0.1, compare.SAME),
        ("cpu", (1.0, 1.0, 1.0), (0.9, 0.9, 0.9), 0.1, compare.FASTER),
        # The spread of the 2 results: 3 x (0.2 / 1.0 + 0.2 / 1.3).
        ("cpu", (0.8, 1.0, 1.2), (1.1, 1.3, 1.5), 1.061538, compare.SAME),
        ("cpu", (0.8, 1.0, 1.2), (2.1, 2.3, 2.5), 0.86087, compare.SLOWER),
        # Short runs: 5 ms / 0.02 s.
        ("cpu", (0.02, 0.02, 0.02), (0.024, 0.024, 0.024), 0.25, compare.SAME),
        ("cpu", (0.02, 0.02, 0.02), (0.03, 0.03, 0.03), 0.25, compare.SLOWER),
        # 1 timed run (smoke): no spread.
        ("cpu", (1.0,), (1.11,), 0.1, compare.SLOWER),
        ("wall", (1.0,), (1.11,), 0.25, compare.SAME),
    ],
)
def test_the_noise_limit(name, base_walls, new_walls, limit, change):
    b = valid(*base_walls).stats["wall_s"]
    n = valid(*new_walls).stats["wall_s"]
    m = compare.metric(name, b, n)
    assert m["limit"] == limit
    assert m["change"] == change


def test_a_zero_base_median_uses_only_the_absolute_limit():
    zero = {"n": 1, "median": 0.0, "min": 0.0, "max": 0.0, "mad": 0.0}
    small = {**zero, "median": 0.004}
    big = {**zero, "median": 0.006}
    assert compare.metric("wall", zero, small)["change"] == compare.SAME
    m = compare.metric("wall", zero, big)
    assert m["change"] == compare.SLOWER and m["ratio"] is None and m["limit"] is None


# Refusals: exit code 2 and no output.


def test_different_input_hashes_are_refused(tmp_path, capsys):
    base, new = make(same(1.0, 1.0, 1.0)), make(same(1.0, 1.0, 1.0))
    new["inputs"]["ansi/small"]["sha256"] = "1" * 64
    code, result = run(tmp_path, base, new)
    assert (code, result) == (2, None)
    err = capsys.readouterr().err
    assert "different inputs or settings: input ansi/small: sha256" in err


def test_different_settings_are_refused(tmp_path, capsys):
    base, new = make(same(1.0, 1.0, 1.0)), make(same(1.0, 1.0, 1.0))
    new["tools"]["a"]["settings"] = {"dialect": "ansi", "rules": "LT01"}
    code, result = run(tmp_path, base, new)
    assert (code, result) == (2, None)
    assert "tool a: settings" in capsys.readouterr().err


def test_settings_of_a_tool_that_is_not_compared_are_not_refused(tmp_path):
    two = {
        **same(1.0, 1.0, 1.0),
        (START, "b"): valid(1.0, 1.0, 1.0),
        (PARSE, "b"): valid(1.0, 1.0, 1.0),
    }
    base, new = make(two), make(two)
    new["tools"]["b"]["settings"] = {"dialect": "tsql"}
    assert run(tmp_path, base, new)[0] == 2
    assert run(tmp_path, base, new, "--tool", "a")[0] == 0


def test_a_new_tool_version_is_a_warning_not_a_refusal(tmp_path):
    base, new = make(same(1.0, 1.0, 1.0)), make(same(1.0, 1.0, 1.0))
    new["tools"]["a"]["version"] = "1.1"
    code, result = run(tmp_path, base, new)
    assert code == 0
    assert result["tools"] == {"a": {"base": "1.0", "new": "1.1"}}
    assert "tool a: version 1.0 in BASE, 1.1 in NEW" in result["warnings"]


def drop_last(rep: dict) -> None:
    """Remove the last result. The report has no schema error."""
    rep["results"].pop()
    rep["totals"] = report.totals(rep["results"], rep["tools"])
    rep["pairs"] = report.pairs(rep["results"], rep["tools"])
    assert report.check(rep) == []


@pytest.mark.parametrize(
    "change, error",
    [
        (lambda r: r["results"][0].update(status="passed"), "NEW: result"),
        (drop_last, "NEW: a: no result for 1: start/ansi"),
        (lambda r: r.update(kind="x"), "NEW: kind"),
    ],
)
def test_a_report_with_a_schema_error_or_not_complete_is_refused(
    tmp_path, capsys, change, error
):
    base, new = make(same(1.0, 1.0, 1.0)), make(same(1.0, 1.0, 1.0))
    change(new)
    assert run(tmp_path, base, new) == (2, None)
    assert error in capsys.readouterr().err
    assert run(tmp_path, new, base) == (2, None)
    assert error.replace("NEW", "BASE") in capsys.readouterr().err


def test_bad_arguments_are_refused(tmp_path, capsys):
    rep = make(same(1.0, 1.0, 1.0))
    assert run(tmp_path, rep, rep, "--tool", "x") == (2, None)
    assert "no report has the tool x" in capsys.readouterr().err
    path = tmp_path / "r.json"
    path.write_text(json.dumps(rep))
    out = tmp_path / "c.json"
    argv = ["bench", "compare", str(path), str(path), str(path), "--out", str(out)]
    assert cli.main(argv) == 2
    assert not out.exists()
    path.write_text("{")
    assert cli.main(["bench", "compare", str(path), "--out", str(out)]) == 2
    assert not out.exists()


# Status changes.


@pytest.mark.parametrize("status", [INVALID, UNSUPPORTED, ERROR])
def test_a_status_change_from_valid_is_a_failure(tmp_path, capsys, status):
    new = same(1.0, 1.0, 1.0)
    new[(PARSE, "a")] = Measurement(status, f"{status}: why", [], None)
    code, result = run(tmp_path, make(same(1.0, 1.0, 1.0)), make(new))
    assert code == 1
    e = entry(result, PARSE, "a")
    assert e["change"] == compare.FAILURE
    assert (e["base_status"], e["new_status"]) == ("valid", status)
    assert e["reason"] == f"{status}: why"
    assert e["wall"] is None and e["cpu"] is None
    assert result["counts"][compare.FAILURE] == 1 and result["ok"] is False
    out = capsys.readouterr().out
    assert f"failure: a parse/ansi/small: valid -> {status}: {status}: why" in out
    assert "FAIL: 0 slower, 1 valid to not valid." in out


def test_other_status_changes_are_listed_and_do_not_fail(tmp_path):
    base = {(START, "a"): invalid(1.0, 1.0, 1.0), (PARSE, "a"): invalid(1.0)}
    new = {
        (START, "a"): valid(1.0, 1.0, 1.0),
        (PARSE, "a"): Measurement(ERROR, "error: x", [], None),
    }
    code, result = run(tmp_path, make(base), make(new))
    assert code == 0
    assert entry(result, START, "a")["change"] == compare.STATUS
    assert entry(result, PARSE, "a")["change"] == compare.STATUS
    code, result = run(tmp_path, make(base), make(base))
    assert code == 0
    assert {e["change"] for e in result["benchmarks"]} == {compare.NOT_VALID}


def test_results_in_only_one_report_are_listed(tmp_path):
    base = make(same(1.0, 1.0, 1.0))
    new = make(
        {
            **same(1.0, 1.0, 1.0),
            (START, "b"): valid(1.0, 1.0, 1.0),
            (PARSE, "b"): valid(1.0, 1.0, 1.0),
        }
    )
    code, result = run(tmp_path, base, new)
    assert code == 0
    assert result["only_new"] == [
        {"id": PARSE, "tool": "b"},
        {"id": START, "tool": "b"},
    ]
    assert result["only_base"] == []
    assert result["tools"]["b"] == {"base": None, "new": "1.0"}
    assert list(result["totals"]) == ["a"]
    code, result = run(tmp_path, new, base)
    assert code == 0
    assert result["only_base"] == [
        {"id": PARSE, "tool": "b"},
        {"id": START, "tool": "b"},
    ]
    # A tool that NEW does not have: no tool totals.
    code, result = run(tmp_path, new, base, "--tool", "b")
    assert code == 0
    assert result["benchmarks"] == [] and len(result["only_base"]) == 2
    assert result["tool_totals"]["tools"] == []
    assert result["tool_totals"]["benchmarks"] == 0


# Totals use only valid results.


def test_totals_use_only_benchmarks_that_are_valid_in_both_reports(tmp_path):
    base = {
        (START, "a"): valid(1.0, 1.0, 1.0),
        (PARSE, "a"): valid(2.0, 2.0, 2.0),
        (START, "b"): invalid(5.0),
        (PARSE, "b"): valid(3.0, 3.0, 3.0),
    }
    new = {
        (START, "a"): valid(1.0, 1.0, 1.0),
        (PARSE, "a"): invalid(100.0),
        (START, "b"): valid(5.0, 5.0, 5.0),
        (PARSE, "b"): valid(3.0, 3.0, 3.0),
    }
    code, result = run(tmp_path, make(base), make(new))
    assert code == 1  # parse of a: valid to invalid.
    assert result["totals"] == {
        "a": {
            "benchmarks": 1,
            "wall_s": [1.0, 1.0],
            "cpu_s": [0.5, 0.5],
            "wall_ratio": 1.0,
            "cpu_ratio": 1.0,
        },
        "b": {
            "benchmarks": 1,
            "wall_s": [3.0, 3.0],
            "cpu_s": [1.5, 1.5],
            "wall_ratio": 1.0,
            "cpu_ratio": 1.0,
        },
    }


@pytest.fixture
def three() -> dict:
    """start: valid for a, b, and c. parse: c is not valid."""
    return make(
        {
            (START, "a"): valid(4.0, 4.0, 4.0),
            (START, "b"): valid(2.0, 2.0, 2.0),
            (START, "c"): valid(1.0, 1.0, 1.0),
            (PARSE, "a"): valid(10.0, 10.0, 10.0),
            (PARSE, "b"): valid(20.0, 20.0, 20.0),
            (PARSE, "c"): invalid(0.1),
        }
    )


def test_tool_totals_use_only_benchmarks_that_are_valid_for_all_tools(tmp_path, three):
    code, result = run(tmp_path, None, three)
    assert code == 0
    assert result["base"] is None and result["benchmarks"] == []
    assert result["tool_totals"] == {
        "tools": ["a", "b", "c"],
        "benchmarks": 1,
        "excluded": [
            {"id": PARSE, "statuses": {"a": "valid", "b": "valid", "c": "invalid"}}
        ],
        "wall_s": {"a": 4.0, "b": 2.0, "c": 1.0},
        "cpu_s": {"a": 2.0, "b": 1.0, "c": 0.5},
        "pairs": [
            {
                "tools": ["a", "b"],
                "wall_ratio": 2.0,
                "cpu_ratio": 2.0,
                "first_slower": 1,
                "first_faster": 0,
            },
            {
                "tools": ["a", "c"],
                "wall_ratio": 4.0,
                "cpu_ratio": 4.0,
                "first_slower": 1,
                "first_faster": 0,
            },
            {
                "tools": ["b", "c"],
                "wall_ratio": 2.0,
                "cpu_ratio": 2.0,
                "first_slower": 1,
                "first_faster": 0,
            },
        ],
    }
    # The same totals of a and b in the pairs of the report use parse too.
    assert three["pairs"][0]["benchmarks"] == 2
    # With only a and b, parse is valid for all compared tools.
    code, result = run(tmp_path, None, three, "--tool", "a", "--tool", "b")
    tt = result["tool_totals"]
    assert tt["benchmarks"] == 2 and tt["excluded"] == []
    assert tt["wall_s"] == {"a": 14.0, "b": 22.0}
    assert tt["pairs"][0]["first_slower"] == 1 and tt["pairs"][0]["first_faster"] == 1


def test_a_tool_with_no_result_excludes_the_benchmark():
    rep = make(
        {
            (START, "a"): valid(1.0, 1.0, 1.0),
            (START, "b"): valid(1.0, 1.0, 1.0),
            (PARSE, "a"): valid(1.0, 1.0, 1.0),
        }
    )
    tt = compare.tool_totals(rep, ["a", "b"])
    assert tt["benchmarks"] == 1
    assert tt["excluded"] == [{"id": PARSE, "statuses": {"a": "valid"}}]


# The table of the tools of one report.


def wide(results: dict[tuple[str, str], Measurement]) -> dict:
    """A report of start and parse (small, medium) for ansi and tsql."""
    tools = sorted({t for _, t in results})
    scope = report.scope(
        tools, ["ansi", "tsql"], ["start", "parse"], ["small", "medium"]
    )
    benchmarks = {b["id"]: b for b in bench_run.expected(scope)}
    return report.build(
        sqlfluff_ref="abc",
        profile="full",
        machine=report.machine(),
        harness=report.harness(),
        timer=timer.timer_entry([sample(wall=0.002, cpu=0.001)] * 3),
        scope=scope,
        tools={t: {"version": "1.0", "settings": {}} for t in tools},
        inputs={
            b["input"]: {"bytes": 10, "lines": 1, "sha256": SHA}
            for b in benchmarks.values()
        },
        results=[
            report.result_entry(benchmarks[bid], tool, m)
            for (bid, tool), m in results.items()
        ],
    )


# Median wall times. b is the reference. a/b: 4, 2, 3, 0.5, 1 (a tie).
# b is not valid on parse/tsql/medium.
WALLS = {
    "start/ansi": (0.5, 2.0),
    "start/tsql": (1.0, 2.0),
    "parse/ansi/small": (1.0, 3.0),
    "parse/tsql/small": (2.0, 1.0),
    "parse/ansi/medium": (4.0, 4.0),
    "parse/tsql/medium": (None, 5.0),
}


@pytest.fixture
def table_report() -> dict:
    results = {}
    for bid, (b, a) in WALLS.items():
        results[(bid, "b")] = invalid(1.0) if b is None else valid(b, b, b)
        results[(bid, "a")] = valid(a, a, a)
    return wide(results)


def test_the_table_has_each_benchmark_valid_for_all_tools(tmp_path, table_report):
    code, result = run(tmp_path, None, table_report, "--tool", "b", "--tool", "a")
    assert code == 0
    table = result["table"]
    assert tuple(table) == compare.TABLE
    assert table["tools"] == ["b", "a"]
    assert table["benchmarks"] == [
        {
            "id": "start/ansi",
            "group": "start",
            "wall_s": {"b": 0.5, "a": 2.0},
            "ratio": {"a": 4.0},
            "faster": "b",
        },
        {
            "id": "start/tsql",
            "group": "start",
            "wall_s": {"b": 1.0, "a": 2.0},
            "ratio": {"a": 2.0},
            "faster": "b",
        },
        {
            "id": "parse/ansi/small",
            "group": "parse/small",
            "wall_s": {"b": 1.0, "a": 3.0},
            "ratio": {"a": 3.0},
            "faster": "b",
        },
        {
            "id": "parse/tsql/small",
            "group": "parse/small",
            "wall_s": {"b": 2.0, "a": 1.0},
            "ratio": {"a": 0.5},
            "faster": "a",
        },
        {
            "id": "parse/ansi/medium",
            "group": "parse/medium",
            "wall_s": {"b": 4.0, "a": 4.0},
            "ratio": {"a": 1.0},
            "faster": None,
        },
    ]
    # The tool that is not valid is left out, with its status.
    assert table["left_out"] == [
        {"id": "parse/tsql/medium", "tool": "b", "status": "invalid"}
    ]


def test_the_subtotals_by_command_and_size(tmp_path, table_report):
    code, result = run(tmp_path, None, table_report, "--tool", "b", "--tool", "a")
    assert code == 0
    table = result["table"]
    assert table["groups"] == [
        {
            "group": "start",
            "benchmarks": 2,
            "wall_s": {"b": 1.5, "a": 4.0},
            # 4.0 / 1.5; the median of 4 and 2.
            "ratio": {"a": {"total": 2.666667, "min": 2.0, "median": 3.0, "max": 4.0}},
            "faster": {"b": 2, "a": 0},
        },
        {
            "group": "parse/small",
            "benchmarks": 2,
            "wall_s": {"b": 3.0, "a": 4.0},
            # 4.0 / 3.0; the median of 3 and 0.5.
            "ratio": {"a": {"total": 1.333333, "min": 0.5, "median": 1.75, "max": 3.0}},
            "faster": {"b": 1, "a": 1},
        },
        {
            "group": "parse/medium",
            "benchmarks": 1,
            "wall_s": {"b": 4.0, "a": 4.0},
            "ratio": {"a": {"total": 1.0, "min": 1.0, "median": 1.0, "max": 1.0}},
            "faster": {"b": 0, "a": 0},
        },
    ]
    for g in [*table["groups"], table["total"]]:
        assert tuple(g) == compare.TABLE_GROUP
        assert tuple(g["ratio"]["a"]) == compare.GROUP_RATIO
    assert table["total"] == {
        "group": "total",
        "benchmarks": 5,
        "wall_s": {"b": 8.5, "a": 12.0},
        # 12.0 / 8.5; the median of 4, 2, 3, 0.5, and 1.
        "ratio": {"a": {"total": 1.411765, "min": 0.5, "median": 2.0, "max": 4.0}},
        "faster": {"b": 3, "a": 1},
    }
    # The total ratio is that of the tool totals: a / b.
    tt = result["tool_totals"]
    assert tt["benchmarks"] == 5
    assert tt["pairs"][0]["tools"] == ["a", "b"]
    assert tt["pairs"][0]["wall_ratio"] == table["total"]["ratio"]["a"]["total"]


def test_the_table_text(tmp_path, capsys, table_report):
    code, _ = run(tmp_path, None, table_report, "--tool", "b", "--tool", "a")
    assert code == 0
    out = capsys.readouterr().out.splitlines()
    start = out.index(
        "table of the tools of NEW: the median wall time (s) of each benchmark "
        "valid for all of b, a; ratio: tool / b"
    )
    assert out[start + 1 : start + 15] == [
        "  benchmark               b       a    a/b  faster",
        "  start/ansi         0.5000  2.0000  4.000  b",
        "  start/tsql         1.0000  2.0000  2.000  b",
        "  parse/ansi/small   1.0000  3.0000  3.000  b",
        "  parse/tsql/small   2.0000  1.0000  0.500  a",
        "  parse/ansi/medium  4.0000  4.0000  1.000  -",
        "subtotals: the sums of the medians (s), the ratio of the sums, and the "
        "min, median, and max of the ratios",
        "  group         n       b        a    a/b    min  median    max  faster",
        "  start         2  1.5000   4.0000  2.667  2.000   3.000  4.000  b 2",
        "  parse/small   2  3.0000   4.0000  1.333  0.500   1.750  3.000  b 1, a 1",
        "  parse/medium  1  4.0000   4.0000  1.000  1.000   1.000  1.000  -",
        "  total         5  8.5000  12.0000  1.412  0.500   2.000  4.000  b 3, a 1",
        "note: 1 benchmarks left out, a tool is not valid: b: invalid on 1",
        f"compare: {tmp_path / 'compare.json'}",
    ]


def test_the_first_tool_is_the_reference(tmp_path, table_report):
    # With no --tool: all tools, sorted. a is the reference.
    code, result = run(tmp_path, None, table_report)
    assert code == 0
    table = result["table"]
    assert table["tools"] == ["a", "b"]
    assert [r["ratio"]["b"] for r in table["benchmarks"]] == [
        0.25,
        0.5,
        0.333333,
        2.0,
        1.0,
    ]
    assert table["total"]["ratio"]["b"]["total"] == 0.708333  # 8.5 / 12.0
    assert table["total"]["faster"] == {"a": 1, "b": 3}
    # The tool totals are the same in each order.
    _, other = run(tmp_path, None, table_report, "--tool", "b", "--tool", "a")
    assert other["tool_totals"] == result["tool_totals"]


def test_a_tool_with_no_result_is_left_out_with_a_note(tmp_path, capsys):
    rep = make(
        {
            (START, "a"): valid(1.0, 1.0, 1.0),
            (START, "b"): valid(3.0, 3.0, 3.0),
            (PARSE, "a"): valid(1.0, 1.0, 1.0),
        }
    )
    table = compare.tool_table(rep, ["a", "b"])
    assert [r["id"] for r in table["benchmarks"]] == [START]
    assert table["left_out"] == [{"id": PARSE, "tool": "b", "status": None}]
    assert compare.table_lines(table)[-1] == (
        "note: 1 benchmarks left out, a tool is not valid: b: no result on 1"
    )


def test_a_tool_that_is_not_valid_on_each_benchmark_gives_an_empty_table(tmp_path):
    rep = make(
        {
            (START, "a"): valid(1.0, 1.0, 1.0),
            (START, "b"): Measurement(UNSUPPORTED, "unsupported: x", [], None),
            (PARSE, "a"): valid(1.0, 1.0, 1.0),
            (PARSE, "b"): Measurement(UNSUPPORTED, "unsupported: x", [], None),
        }
    )
    code, result = run(tmp_path, None, rep)
    assert code == 0
    table = result["table"]
    assert table["benchmarks"] == [] and table["groups"] == []
    assert table["total"] == {
        "group": "total",
        "benchmarks": 0,
        "wall_s": {"a": 0.0, "b": 0.0},
        "ratio": {"b": {"total": None, "min": None, "median": None, "max": None}},
        "faster": {"a": 0, "b": 0},
    }
    assert [e["status"] for e in table["left_out"]] == [UNSUPPORTED, UNSUPPORTED]


def test_one_tool_gives_no_table(tmp_path, capsys):
    code, result = run(tmp_path, None, make(same(1.0, 1.0, 1.0)))
    assert code == 0
    assert result["table"] is None
    assert "table of the tools" not in capsys.readouterr().out


def test_the_table_of_the_s2_baseline():
    """bench compare results/s2/baseline.json --tool sqll --tool sqlfluff."""
    path = REPO_ROOT / "results" / "s2" / "baseline.json"
    rep = json.loads(path.read_text(encoding="utf8"))
    result = compare.compare((str(path), rep), tools=["sqll", "sqlfluff"])
    table = result["table"]
    assert table["tools"] == ["sqll", "sqlfluff"]
    assert len(table["benchmarks"]) == 112
    assert [(g["group"], g["benchmarks"]) for g in table["groups"]] == [
        ("start", 28),
        ("parse/small", 28),
        ("parse/medium", 28),
        ("parse/large", 28),
    ]
    tt = result["tool_totals"]
    (pair,) = tt["pairs"]
    assert pair["tools"] == ["sqlfluff", "sqll"] and tt["benchmarks"] == 112
    total = table["total"]
    assert total["ratio"]["sqlfluff"]["total"] == pair["wall_ratio"]
    assert total["wall_s"] == tt["wall_s"]
    assert total["faster"]["sqll"] == pair["first_slower"]
    assert len({e["id"] for e in table["left_out"]}) == len(tt["excluded"])


# The output and its schema.


def test_the_output_is_written_for_exit_codes_0_and_1(tmp_path):
    base = make(same(1.0, 1.0, 1.0))
    for walls, code in (((1.0, 1.0, 1.0), 0), ((2.0, 2.0, 2.0), 1)):
        got, result = run(tmp_path, base, make(same(*walls)))
        assert got == code
        assert tuple(result) == compare.TOP
        assert result["kind"] == compare.KIND and result["format"] == compare.FORMAT
        assert result["noise"] == NOISE
        assert tuple(result["base"]) == compare.REPORT_REF
        assert result["new"]["path"] == str(tmp_path / "new.json")
        for e in result["benchmarks"]:
            assert tuple(e) == compare.BENCHMARK
            assert tuple(e["wall"]) == compare.METRIC
        for t in result["totals"].values():
            assert tuple(t) == compare.TOTAL
        assert tuple(result["tool_totals"]) == compare.TOOL_TOTALS
        assert result["table"] is None  # 1 tool


def test_warnings_for_other_machines_profiles_and_worktrees(tmp_path):
    base, new = make(same(1.0, 1.0, 1.0)), make(same(1.0, 1.0, 1.0))
    new["machine"] = {**new["machine"], "cpu_count": 99}
    new["harness"] = {**new["harness"], "clean": False}
    base["harness"] = {**base["harness"], "clean": True}
    code, result = run(tmp_path, base, new)
    assert code == 0
    assert result["warnings"] == [
        "the machine of BASE and NEW differ",
        "NEW is of a worktree with changes",
    ]
    smoke = make(same(1.0), profile="smoke")
    smoke["harness"] = {**smoke["harness"], "clean": True}
    code, result = run(tmp_path, base, smoke)
    assert code == 0
    assert result["warnings"] == [
        "the profile of BASE and NEW differ",
        "NEW has 1 timed run for each benchmark (profile smoke): expect false "
        "slowdowns",
    ]


def _readme_schema() -> dict:
    text = (REPO_ROOT / "harness" / "README.md").read_text(encoding="utf8")
    section = text.split("## Benchmark compare", 1)[1]
    block = re.search(r"```json\n(.*?)```", section, re.DOTALL).group(1)
    return json.loads(block)


def test_the_readme_has_each_field_of_the_output():
    doc = _readme_schema()
    assert tuple(doc) == compare.TOP
    assert doc["kind"] == compare.KIND and doc["format"] == compare.FORMAT
    assert tuple(doc["base"]) == compare.REPORT_REF
    assert tuple(doc["new"]) == compare.REPORT_REF
    assert doc["noise"] == NOISE
    ((_, tool),) = doc["tools"].items()
    assert tuple(tool) == ("base", "new")
    (e,) = doc["benchmarks"]
    assert tuple(e) == compare.BENCHMARK
    assert e["change"] == "|".join(compare.CHANGES)
    assert tuple(e["wall"]) == compare.METRIC
    assert e["wall"]["change"] == "|".join(compare.CHANGES[:3])
    ((_, total),) = doc["totals"].items()
    assert tuple(total) == compare.TOTAL
    assert tuple(doc["tool_totals"]) == compare.TOOL_TOTALS
    (pair,) = doc["tool_totals"]["pairs"]
    assert tuple(pair) == compare.PAIR
    table = doc["table"]
    assert tuple(table) == compare.TABLE
    (row,) = table["benchmarks"]
    assert tuple(row) == compare.TABLE_ROW
    (group,) = table["groups"]
    for g in (group, table["total"]):
        assert tuple(g) == compare.TABLE_GROUP
        ((_, ratio),) = g["ratio"].items()
        assert tuple(ratio) == compare.GROUP_RATIO
    (left,) = table["left_out"]
    assert tuple(left) == compare.LEFT_OUT
    assert tuple(doc["counts"]) == ("compared", *compare.CHANGES)


def test_the_noise_limit_is_that_of_bench_md():
    assert compare.NOISE == compare.Noise(
        wall_pct=0.25, cpu_pct=0.10, k=3.0, min_diff_s=0.005
    )
    text = (REPO_ROOT / "harness" / "bench.md").read_text(encoding="utf8")
    flat = " ".join(text.split())
    assert "25% for wall time and 10% for CPU time" in flat
    assert "3 times the sum of the relative MADs" in flat
    assert "5 ms divided by the BASE median" in flat


def test_process_md_has_the_change_record_rule():
    text = (REPO_ROOT / "PROCESS.md").read_text(encoding="utf8")
    flat = " ".join(text.split())
    assert "`sqll-harness bench compare`" in flat
    assert "the pull request body must give the reason" in flat


def test_the_s3b_status_has_the_table_of_the_s2_baseline():
    path = REPO_ROOT / "results" / "s2" / "baseline.json"
    rep = json.loads(path.read_text(encoding="utf8"))
    table = compare.tool_table(rep, ["sqll", "sqlfluff"])
    want = []
    for g in [*table["groups"], table["total"]]:
        r = g["ratio"]["sqlfluff"]
        cells = [
            g["group"],
            str(g["benchmarks"]),
            f"{g['wall_s']['sqll']:.4f}",
            f"{g['wall_s']['sqlfluff']:.4f}",
            *(f"{r[k]:.3f}" for k in compare.GROUP_RATIO),
            str(g["faster"]["sqll"]),
        ]
        want.append("| " + " | ".join(cells) + " |")
    text = (REPO_ROOT / "status" / "S3b.md").read_text(encoding="utf8")
    got = [
        line for line in text.splitlines() if re.match(r"\| (start|parse|total)", line)
    ]
    assert got == want
