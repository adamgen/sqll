"""sqll-harness bench run, merge, and check (harness/README.md, "Benchmark
runs"), with test-double tools. The real tools are in the last test."""

import json
import os
import sys
from pathlib import Path

import pytest
from conftest import needs_all_tools
from test_bench_adapters import DoubleBench

from sqll_harness import cli
from sqll_harness import tools as s1_tools
from sqll_harness.bench import definitions, registry, report
from sqll_harness.bench import run as bench_run
from sqll_harness.bench.timer import INVALID, UNSUPPORTED, VALID
from sqll_harness.tools import ToolInfo

DEFS = definitions.load()
DIALECTS = sorted({b["dialect"] for b in DEFS["benchmarks"]})


class BaseDouble(DoubleBench):
    """A test double in the place of sqlfluff, the base tool of the ratios."""

    name = "sqlfluff"


class OtherDouble(DoubleBench):
    """A second test double: soql is unsupported, and mysql gets no rules
    setting, so the tool stops with exit code 2 (invalid)."""

    name = "double-b"

    def __init__(self) -> None:
        super().__init__(no={"soql"})

    def layer(self, config):
        if config.get("core", {}).get("dialect") == "mysql":
            config["core"].pop("rules")
        return config


def _ok(name):
    def check(root, specs):
        return ToolInfo(name, "binary", "1.0", "1.0")

    return check


def _bad(name):
    def check(root, specs):
        return ToolInfo(name, "binary", "1.0", "0.9", errors=["version 0.9"])

    return check


def _use_doubles(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(
        registry,
        "REGISTRY",
        {BaseDouble.name: BaseDouble, OtherDouble.name: OtherDouble},
    )
    mp.setattr(
        s1_tools,
        "CHECKS",
        {BaseDouble.name: _ok(BaseDouble.name), OtherDouble.name: _ok("double-b")},
    )


@pytest.fixture
def doubles(monkeypatch):
    _use_doubles(monkeypatch)


def bench(*args: str) -> int:
    return cli.main(["bench", *[str(a) for a in args]])


def statuses(rep: dict) -> dict[tuple[str, str], str]:
    return {(r["id"], r["tool"]): r["status"] for r in rep["results"]}


@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    """An unsharded smoke run, the 3 shards of a sharded smoke run, and
    their merge. Also records the series of each run_in_turn call."""
    out = tmp_path_factory.mktemp("smoke")
    calls = []
    real = bench_run.run_in_turn

    def record(series):
        calls.append([s.folder for s in series])
        return real(series)

    codes = {}
    with pytest.MonkeyPatch.context() as mp:
        _use_doubles(mp)
        mp.setattr(bench_run, "run_in_turn", record)
        codes["all"] = bench("run", "--profile", "smoke", "--out", out / "all.json")
        n_calls = len(calls)
        for k in (1, 2, 3):
            shard = ("--shard", f"{k}/3", "--out", out / f"{k}.json")
            codes[k] = bench("run", "--profile", "smoke", *shard)
        codes["merge"] = bench(
            "merge", *(out / f"{k}.json" for k in (1, 2, 3)), "--out", out / "m.json"
        )
    return {
        "codes": codes,
        "all": report.load(out / "all.json"),
        "shards": [report.load(out / f"{k}.json") for k in (1, 2, 3)],
        "merged": report.load(out / "m.json"),
        "calls": calls[:n_calls],
        "out": out,
    }


# The plan.


def test_the_profiles_give_the_benchmarks_of_bench_md():
    tools = ["sqlfluff"]
    scope, smoke = bench_run.plan(DEFS, tools=tools, profile="smoke")
    assert scope["sizes"] == ["small"] and scope["commands"] == [
        "start",
        "parse",
        "lint",
        "fix",
    ]
    assert len(smoke) == len(DIALECTS) * 4 == 112
    assert {b["size"] for b in smoke} == {None, "small"}
    _, full = bench_run.plan(DEFS, tools=tools, profile="full")
    assert full == DEFS["benchmarks"]
    _, some = bench_run.plan(
        DEFS,
        tools=tools,
        profile="full",
        dialects=["tsql", "ansi", "tsql"],
        commands=["lint"],
        sizes=["large", "small"],
    )
    assert [b["id"] for b in some] == [
        "lint/ansi/small",
        "lint/ansi/large",
        "lint/tsql/small",
        "lint/tsql/large",
    ]


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"profile": "smoke", "sizes": ["large"]}, "not in the smoke profile"),
        ({"profile": "full", "dialects": ["nosuch"]}, "no dialect nosuch"),
        ({"profile": "full", "commands": ["format"]}, "unknown command format"),
    ],
)
def test_a_bad_scope_is_refused(kwargs, error):
    with pytest.raises(bench_run.RunError, match=error):
        bench_run.plan(DEFS, tools=["sqlfluff"], **kwargs)


@pytest.mark.parametrize("n", [1, 2, 3, 4, 28, 30])
def test_the_shards_divide_the_benchmarks_by_dialect(n):
    _, everything = bench_run.plan(DEFS, tools=["x"], profile="full")
    seen = []
    for k in range(1, n + 1):
        _, part = bench_run.plan(DEFS, tools=["x"], profile="full", shard=(k, n))
        dialects = {b["dialect"] for b in part}
        # Each dialect has all its benchmarks in one shard.
        assert part == [b for b in everything if b["dialect"] in dialects]
        assert len(dialects) in (len(DIALECTS) // n, -(-len(DIALECTS) // n))
        seen += part
    assert sorted(b["id"] for b in seen) == sorted(b["id"] for b in everything)


# The run, with test-double tools.


def test_a_smoke_run_writes_a_complete_report(smoke):
    assert smoke["codes"] == {"all": 0, 1: 0, 2: 0, 3: 0, "merge": 0}
    rep = smoke["all"]
    assert report.check(rep) == []
    assert bench_run.incomplete(rep, DEFS) == []
    assert rep["profile"] == "smoke" and rep["parts"] is None
    assert rep["scope"]["dialects"] == DIALECTS and rep["scope"]["shard"] is None
    assert rep["tools"]["double-b"] == {
        "version": "1.0",
        "settings": OtherDouble().config(None),
    }
    assert len(rep["results"]) == 2 * 112
    found = statuses(rep)
    assert found[("lint/mysql/small", "double-b")] == INVALID
    assert found[("start/soql", "double-b")] == UNSUPPORTED
    other = [v for (i, t), v in found.items() if t == "double-b"]
    assert other.count(VALID) == 112 - 4 - 4
    assert all(v == VALID for (i, t), v in found.items() if t == "sqlfluff")
    for r in rep["results"]:
        assert (
            rep["inputs"][r["input"]]["sha256"]
            == (DEFS["inputs"][r["input"]]["sha256"])
        )


def test_the_tools_of_a_benchmark_run_in_turn(smoke):
    """run_in_turn gets the series of all tools of one benchmark, so the
    tools do their timed runs in turn (test_bench_timer.py)."""
    calls = smoke["calls"]
    assert len(calls) == 112
    for folders in calls:
        # <tmp>/sqll-bench-*/runs/<tool>/<id>/runs
        named = []
        for f in folders:
            i = max(j for j, p in enumerate(f.parts) if p.startswith("sqll-bench-"))
            named.append((f.parts[i + 2], "/".join(f.parts[i + 3 : -1])))
        tools = [t for t, _ in named]
        ((bid,),) = [{b for _, b in named}]
        if "/soql" in bid:
            assert tools == ["sqlfluff"]
        else:
            assert tools == ["double-b", "sqlfluff"]


def test_ratios_use_only_valid_results_of_the_same_run(smoke):
    """test_bench_report.py has the case of a base result that is not valid."""
    rep = smoke["all"]
    by = {(r["id"], r["tool"]): r for r in rep["results"]}
    for r in rep["results"]:
        base = by[(r["id"], "sqlfluff")]
        both_valid = r["status"] == base["status"] == VALID
        if r["tool"] == "sqlfluff" or not both_valid:
            assert r["ratio"] is None, r["id"]
            continue
        for key in ("wall", "cpu"):
            a, b = (x["stats"][f"{key}_s"]["median"] for x in (r, base))
            assert r["ratio"][key] == round(a / b, 6)
    assert by[("lint/mysql/small", "double-b")]["ratio"] is None
    assert by[("start/soql", "double-b")]["ratio"] is None
    assert by[("start/ansi", "double-b")]["ratio"] is not None
    # A merged report keeps the ratios of its shard reports: the tools of a
    # benchmark run in the same shard run.
    in_shards = {
        (r["id"], r["tool"]): r["ratio"] for s in smoke["shards"] for r in s["results"]
    }
    merged = {(r["id"], r["tool"]): r["ratio"] for r in smoke["merged"]["results"]}
    assert merged == in_shards


def test_the_merged_shards_are_the_unsharded_run(smoke):
    full, merged, shards = smoke["all"], smoke["merged"], smoke["shards"]
    assert report.check(merged) == []
    assert bench_run.incomplete(merged, DEFS) == []
    assert [r["id"] for r in merged["results"]] == [r["id"] for r in full["results"]]
    assert statuses(merged) == statuses(full)
    assert merged["inputs"] == full["inputs"]
    assert merged["scope"] == full["scope"]
    assert merged["tools"] == full["tools"]
    assert [p["shard"] for p in merged["parts"]] == ["1/3", "2/3", "3/3"]
    assert merged["machine"] == shards[0]["machine"]
    # The shards have no common dialect. Thus only the start input is in
    # more than one shard (harness/README.md, "Benchmark runs").
    dialects = [{r["dialect"] for r in s["results"]} for s in shards]
    assert sum(len(d) for d in dialects) == len(set().union(*dialects)) == 28
    assert all("start" in s["inputs"] for s in shards)
    others = [name for s in shards for name in s["inputs"] if name != "start"]
    assert len(others) == len(set(others)) == len(full["inputs"]) - 1


# Exit codes.


def test_a_failed_tool_check_stops_the_run(doubles, monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(s1_tools.CHECKS, "double-b", _bad("double-b"))
    out = tmp_path / "b.json"
    assert bench("run", "--dialect", "ansi", "--out", out) == 2
    assert "error: double-b: version 0.9" in capsys.readouterr().err
    assert not out.exists()
    monkeypatch.delitem(s1_tools.CHECKS, "double-b")
    assert bench("run", "--dialect", "ansi", "--out", out) == 2
    assert "error: double-b: no tool check" in capsys.readouterr().err
    assert not out.exists()


def test_an_incomplete_report_fails(doubles, monkeypatch, tmp_path, capsys):
    real = bench_run.run_benchmarks

    def drop_last(*args, **kwargs):
        return real(*args, **kwargs)[:-1]

    monkeypatch.setattr(bench_run, "run_benchmarks", drop_last)
    out = tmp_path / "b.json"
    assert bench("run", "--dialect", "ansi", "--command", "start", "--out", out) == 1
    text = capsys.readouterr().out
    assert "sqlfluff: no result for 1: start/ansi" in text
    assert "FAIL: the report is not complete" in text
    # The report is written, with no schema error.
    assert report.check(report.load(out)) == []
    assert bench("check", out) == 1


def test_a_report_with_a_schema_error_is_not_written(
    doubles, monkeypatch, tmp_path, capsys
):
    real = bench_run.run

    def bad_status(**kwargs):
        rep = real(**kwargs)
        rep["results"][0]["status"] = "passed"
        return rep

    monkeypatch.setattr(bench_run, "run", bad_status)
    out = tmp_path / "b.json"
    assert bench("run", "--dialect", "ansi", "--command", "start", "--out", out) == 1
    assert "the report has a schema error" in capsys.readouterr().err
    assert not out.exists()


def test_a_closed_pipe_does_not_change_the_exit_code(parts, tmp_path, monkeypatch):
    """The reader of the summary closes the pipe early, as "| head" does."""
    read_end, write_end = os.pipe()
    os.close(read_end)
    with os.fdopen(write_end, "w") as closed:
        monkeypatch.setattr(sys, "stdout", closed)
        assert bench("merge", *parts, "--out", tmp_path / "m.json") == 0
        monkeypatch.undo()
    assert bench("check", tmp_path / "m.json") == 0


def test_inputs_that_are_not_those_of_the_definitions_stop_the_run(
    doubles, tmp_path, capsys
):
    defs = json.loads(definitions.DEFINITIONS.read_text())
    defs["inputs"]["ansi/small"]["sha256"] = "0" * 64
    path = tmp_path / "defs.json"
    path.write_text(json.dumps(defs))
    out = tmp_path / "b.json"
    code = bench("run", "--dialect", "ansi", "--definitions", path, "--out", out)
    assert code == 2
    assert "the inputs are not those of the definitions" in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize(
    "args, error",
    [
        (["--profile", "smoke", "--size", "large"], "not in the smoke profile"),
        (["--dialect", "nosuch"], "no dialect nosuch"),
    ],
)
def test_a_bad_scope_stops_the_run(doubles, tmp_path, capsys, args, error):
    assert bench("run", *args, "--out", tmp_path / "b.json") == 2
    assert error in capsys.readouterr().err
    assert not (tmp_path / "b.json").exists()


def test_a_bad_shard_is_refused(capsys):
    with pytest.raises(SystemExit) as exc:
        bench("run", "--shard", "3/2")
    assert exc.value.code == 2
    assert "1 <= K <= N" in capsys.readouterr().err


# Merge.


@pytest.fixture(scope="module")
def short_shards(tmp_path_factory):
    """The texts of the 2 shard reports of a short run."""
    out = tmp_path_factory.mktemp("short")
    texts = []
    with pytest.MonkeyPatch.context() as mp:
        _use_doubles(mp)
        for k in (1, 2):
            path = out / f"{k}.json"
            args = ["--dialect", "ansi", "--dialect", "soql", "--command", "start"]
            assert bench("run", *args, "--shard", f"{k}/2", "--out", path) == 0
            texts.append(path.read_text())
    return texts


@pytest.fixture
def parts(short_shards, tmp_path):
    """Copies of the 2 shard reports of a short run."""
    paths = []
    for k, text in enumerate(short_shards, 1):
        path = tmp_path / f"{k}.json"
        path.write_text(text)
        paths.append(path)
    return paths


def _merge_error(reports: list[dict], match: str) -> None:
    with pytest.raises(bench_run.MergeError, match=match):
        bench_run.merge([(f"r{i}", r) for i, r in enumerate(reports)])


def test_merge_refuses_a_missing_or_repeated_shard(parts, tmp_path, capsys):
    one, two = (report.load(p) for p in parts)
    _merge_error([one], r"no report for shard 2/2")
    _merge_error([one, one], r"shard 1/2 is in r0 and r1")
    assert bench("merge", parts[0], "--out", tmp_path / "m.json") == 2
    assert "no report for shard 2/2" in capsys.readouterr().err
    assert not (tmp_path / "m.json").exists()
    merged = bench_run.merge([("a", two), ("b", one)])
    assert [p["shard"] for p in merged["parts"]] == ["1/2", "2/2"]
    _merge_error([merged], "a merged report cannot be merged again")


@pytest.mark.parametrize(
    "change, match",
    [
        (lambda r: r["tools"]["double-b"].update(version="2.0"), "tool double-b"),
        (lambda r: r["tools"]["sqlfluff"]["settings"].update(x=1), "tool sqlfluff"),
        (lambda r: r.update(sqlfluff_ref="x"), "sqlfluff_ref differs"),
        (lambda r: r["harness"].update(commit="x"), "harness differs"),
        (lambda r: r["scope"]["sizes"].remove("large"), "the scope differs"),
    ],
)
def test_merge_refuses_reports_with_another_record(parts, change, match):
    one, two = (report.load(p) for p in parts)
    change(two)
    _merge_error([one, two], match)


def test_merge_refuses_a_bad_or_incomplete_report(parts):
    one, two = (report.load(p) for p in parts)
    bad = json.loads(json.dumps(two))
    bad["results"][0]["status"] = "passed"
    _merge_error([one, bad], "r1: schema error")
    short = dict(two)
    short["results"] = two["results"][1:]
    short["totals"] = report.totals(short["results"], short["tools"])
    short["pairs"] = report.pairs(short["results"], short["tools"])
    assert report.check(short) == []
    _merge_error([one, short], "r1: not complete")


def test_the_parts_of_a_merged_report_are_checked(parts):
    merged = bench_run.merge([(str(p), report.load(p)) for p in parts])
    assert report.check(merged) == []
    bad = json.loads(json.dumps(merged))
    bad["scope"]["shard"] = "1/2"
    assert any("scope.shard null" in e for e in report.check(bad))
    bad = json.loads(json.dumps(merged))
    bad["parts"].reverse()
    assert any("not 1/2 to 2/2" in e for e in report.check(bad))
    bad = json.loads(json.dumps(merged))
    bad["machine"] = bad["parts"][1]["machine"] | {"cpu_model": "other"}
    assert any("not those of part 1" in e for e in report.check(bad))
    bad = json.loads(json.dumps(merged))
    bad["parts"][0]["shard"] = "x"
    assert any("bad shard" in e for e in report.check(bad))


def test_the_summary_lists_each_result_that_is_not_valid(parts):
    rep = bench_run.merge([(str(p), report.load(p)) for p in parts])
    by = {(r["id"], r["tool"]): r for r in rep["results"]}
    assert by[("start/soql", "double-b")]["reason"] == "unsupported: dialect soql"
    by[("start/ansi", "double-b")].update(
        status=INVALID, reason="line one\n" + "x" * 300, stats=None, ratio=None
    )
    lines = bench_run.summary_lines(rep)
    start = lines.index("not valid: 2")
    assert lines[start + 1 :] == [
        "  double-b start/ansi: "
        + ("invalid: line one " + "x" * 300)[: bench_run.REASON_TEXT - 3]
        + "...",
        "  double-b start/soql: unsupported: dialect soql",
    ]


def test_check_finds_inputs_that_are_not_those_of_the_definitions(parts, capsys):
    path = parts[0]
    assert bench("check", path) == 0
    rep = report.load(path)
    rep["inputs"]["start"]["bytes"] += 1
    path.write_text(json.dumps(rep))
    assert bench("check", path) == 1
    assert "input start: not that of the definitions" in capsys.readouterr().out


# The real tools.


@needs_all_tools
def test_a_smoke_run_of_the_real_tools(tmp_path, capsys):
    out = tmp_path / "bench.json"
    assert bench("run", "--profile", "smoke", "--dialect", "ansi", "--out", out) == 0
    rep = report.load(out)
    assert report.check(rep) == [] and bench_run.incomplete(rep, DEFS) == []
    assert sorted(rep["tools"]) == ["sqlfluff", "sqlfluff-rs", "sqruff"]
    assert statuses(rep) == {
        (b, t): VALID
        for b in ("start/ansi", "parse/ansi/small", "lint/ansi/small", "fix/ansi/small")
        for t in ("sqlfluff", "sqlfluff-rs", "sqruff")
    }
    for r in rep["results"]:
        assert (r["ratio"] is None) == (r["tool"] == "sqlfluff")
    text = capsys.readouterr().out
    assert "profile smoke: 4 benchmarks, 3 tools, 1 dialects" in text
    assert f"report: {out}" in text


def test_the_test_doubles_are_not_in_the_registry():
    assert registry.names() == ["sqlfluff", "sqlfluff-rs", "sqruff"]
    assert Path(registry.__file__).is_file()
