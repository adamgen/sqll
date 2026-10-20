"""The benchmark report and its schema check (harness/README.md)."""

import copy
import json
import re
import sys
from pathlib import Path

import pytest

from sqll_harness.bench import report, timer
from sqll_harness.bench.timer import (
    ERROR,
    INVALID,
    TIMED,
    UNSUPPORTED,
    VALID,
    WARMUP,
    Job,
    Measurement,
    Sample,
    measure,
)
from sqll_harness.paths import REPO_ROOT

DOUBLE = Path(__file__).parent / "fixtures" / "bench" / "double.py"
SHA = "0" * 64
BENCHMARKS = {
    "start/ansi": {
        "id": "start/ansi",
        "command": "start",
        "dialect": "ansi",
        "size": None,
        "input": "start",
    },
    "parse/ansi/small": {
        "id": "parse/ansi/small",
        "command": "parse",
        "dialect": "ansi",
        "size": "small",
        "input": "ansi/small",
    },
}


def sample(kind=TIMED, wall=1.0, cpu=0.5, code=0, timed_out=False) -> Sample:
    return Sample(kind, wall, cpu, 0.0, 1000, code, timed_out)


def valid(*walls: float, code=0) -> Measurement:
    samples = [sample(WARMUP, 9.0, code=code)] + [
        sample(wall=w, cpu=w / 2, code=code) for w in walls
    ]
    return Measurement(VALID, None, samples, timer.sample_stats(samples))


def invalid(*walls: float) -> Measurement:
    """A result with a timed run that has a bad exit code. Its samples stay."""
    samples = [sample(WARMUP, 9.0)] + [sample(wall=w, cpu=w) for w in walls]
    samples.append(sample(wall=100.0, cpu=100.0, code=1))
    return Measurement(INVALID, "timed run: exit code 1", samples, None)


def make(results: dict[tuple[str, str], Measurement], profile="full") -> dict:
    tools = sorted({t for _, t in results})
    return report.build(
        sqlfluff_ref="abc",
        profile=profile,
        machine=report.machine(),
        harness=report.harness(),
        timer=timer.timer_entry([sample(wall=0.002, cpu=0.001)] * 3),
        scope=report.scope(tools, ["ansi"], ["start", "parse"], ["small"]),
        tools={t: {"version": "1.0", "settings": {"dialect": "ansi"}} for t in tools},
        inputs={
            "start": {"bytes": 10, "lines": 1, "sha256": SHA},
            "ansi/small": {"bytes": 1019, "lines": 46, "sha256": SHA},
        },
        results=[
            report.result_entry(BENCHMARKS[bid], tool, m)
            for (bid, tool), m in results.items()
        ],
    )


@pytest.fixture
def good() -> dict:
    return make(
        {
            ("start/ansi", "a"): valid(1.0, 2.0, 3.0),
            ("start/ansi", "b"): valid(0.5, 0.5, 0.5),
            ("parse/ansi/small", "a"): valid(4.0, 4.0, 5.0, code=1),
            ("parse/ansi/small", "b"): invalid(0.1, 0.1),
        }
    )


def result(rep: dict, bid: str, tool: str) -> dict:
    (r,) = [r for r in rep["results"] if r["id"] == bid and r["tool"] == tool]
    return r


# Build and write.


def test_a_built_report_has_no_schema_error(good, tmp_path):
    assert report.check(good) == []
    path = tmp_path / "out" / "bench.json"
    report.write(good, path)
    loaded = report.load(path)
    assert loaded == good
    assert report.check(loaded) == []


def test_a_report_of_real_runs_has_no_schema_error(tmp_path):
    ok = Job([sys.executable, str(DOUBLE), "exit", "0"])
    bad = Job([sys.executable, str(DOUBLE), "exit", "2"])
    policy = timer.PROFILES["smoke"]
    rep = make(
        {
            ("start/ansi", "a"): measure(ok, policy, tmp_path / "1"),
            ("start/ansi", "b"): measure(bad, policy, tmp_path / "2"),
            ("parse/ansi/small", "a"): measure(
                Job([str(tmp_path / "none")]), policy, tmp_path / "3"
            ),
        },
        profile="smoke",
    )
    rep["timer"] = timer.overhead(tmp_path / "o")
    assert report.check(rep) == []
    statuses = [(r["id"], r["tool"], r["status"]) for r in rep["results"]]
    assert statuses == [
        ("parse/ansi/small", "a", ERROR),
        ("start/ansi", "a", VALID),
        ("start/ansi", "b", INVALID),
    ]


def test_the_records_of_the_run(good):
    m = good["machine"]
    assert m["cpu_count"] >= 1 and m["python"].startswith("3.13")
    assert m["kernel"] and m["os"] and m["cpu_model"]
    h = good["harness"]
    assert re.fullmatch(r"[0-9a-f]{40}", h["commit"]) and isinstance(h["clean"], bool)
    assert good["policy"] == {
        "warmup_runs": 1,
        "min_runs": 3,
        "max_runs": 20,
        "budget_s": 2.0,
        "timeout_s": 120.0,
    }


def test_write_refuses_a_bad_report(good, tmp_path):
    del good["machine"]
    path = tmp_path / "bench.json"
    with pytest.raises(report.ReportError, match="missing field 'machine'"):
        report.write(good, path)
    assert not path.exists()


# Invalid results keep their samples, and no total uses them.


def test_an_invalid_result_keeps_its_samples_and_has_no_stats(good):
    r = result(good, "parse/ansi/small", "b")
    assert r["status"] == INVALID and r["reason"] == "timed run: exit code 1"
    assert [s["wall_s"] for s in r["samples"]] == [9.0, 0.1, 0.1, 100.0]
    assert r["runs"] == {"warmup": 1, "timed": 3}
    assert r["stats"] is None


def test_no_total_or_pair_uses_an_invalid_result(good):
    assert good["totals"] == {
        "a": {
            "valid": 2,
            "invalid": 0,
            "unsupported": 0,
            "error": 0,
            "wall_s": 2.0 + 4.0,
            "cpu_s": 1.0 + 2.0,
        },
        "b": {
            "valid": 1,
            "invalid": 1,
            "unsupported": 0,
            "error": 0,
            "wall_s": 0.5,
            "cpu_s": 0.25,
        },
    }
    # The pair uses only start/ansi, where both tools are valid.
    assert good["pairs"] == [
        {
            "tools": ["a", "b"],
            "benchmarks": 1,
            "skipped": 1,
            "wall_s": [2.0, 0.5],
            "cpu_s": [1.0, 0.25],
            "wall_ratio": 4.0,
        }
    ]


def test_a_total_that_uses_an_invalid_result_is_refused(good):
    good["totals"]["b"]["wall_s"] = 0.5 + 100.0
    assert any(e.startswith("totals: ") for e in report.check(good))
    good = make({("start/ansi", "a"): invalid(1.0)})
    good["totals"]["a"]["wall_s"] = 100.0
    assert any(e.startswith("totals: ") for e in report.check(good))


def test_a_pair_that_uses_an_invalid_result_is_refused(good):
    good["pairs"][0]["benchmarks"] = 2
    good["pairs"][0]["wall_s"][1] += 100.0
    assert any(e.startswith("pairs: ") for e in report.check(good))


def test_stats_on_an_invalid_result_are_refused(good):
    r = result(good, "parse/ansi/small", "b")
    r["stats"] = timer.sample_stats([Sample(**s) for s in r["samples"][1:]])
    assert report.check(good) == [
        "result parse/ansi/small (b): status invalid must have no stats",
        "totals: not checked: the results or the tools have an error",
    ]


# Ratios to sqlfluff: only valid results of the same report.


@pytest.fixture
def with_base() -> dict:
    return make(
        {
            ("start/ansi", "sqlfluff"): valid(2.0, 4.0, 4.0),
            ("start/ansi", "b"): valid(1.0, 1.0, 1.0),
            ("start/ansi", "c"): invalid(0.1, 0.1),
            ("parse/ansi/small", "sqlfluff"): invalid(1.0, 1.0),
            ("parse/ansi/small", "b"): valid(0.5, 0.5, 0.5),
        }
    )


def test_a_ratio_uses_only_valid_results(with_base):
    assert report.check(with_base) == []
    ratio = {(r["id"], r["tool"]): r["ratio"] for r in with_base["results"]}
    assert ratio == {
        # Median 1.0 / 4.0; CPU time is half the wall time in valid().
        ("start/ansi", "b"): {"wall": 0.25, "cpu": 0.25},
        # The tool result is not valid.
        ("start/ansi", "c"): None,
        # The base result is not valid.
        ("parse/ansi/small", "b"): None,
        # No ratio of the base to itself.
        ("start/ansi", "sqlfluff"): None,
        ("parse/ansi/small", "sqlfluff"): None,
    }


def test_a_ratio_with_no_base_result_is_null():
    rep = make({("start/ansi", "b"): valid(1.0, 1.0, 1.0)})
    assert report.check(rep) == []
    assert rep["results"][0]["ratio"] is None


@pytest.mark.parametrize(
    "bid, tool, ratio",
    [
        ("start/ansi", "c", {"wall": 0.1, "cpu": 0.1}),
        ("parse/ansi/small", "b", {"wall": 0.5, "cpu": 0.5}),
        ("start/ansi", "sqlfluff", {"wall": 1.0, "cpu": 1.0}),
        ("start/ansi", "b", {"wall": 0.5, "cpu": 0.25}),
        ("start/ansi", "b", None),
    ],
)
def test_a_ratio_that_is_not_that_of_the_valid_results_is_refused(
    with_base, bid, tool, ratio
):
    result(with_base, bid, tool)["ratio"] = ratio
    errors = report.check(with_base)
    assert f"result {bid} ({tool}): ratio {ratio!r} is not" in " ".join(errors)


def test_a_bad_ratio_value_is_refused(with_base):
    result(with_base, "start/ansi", "b")["ratio"] = {"wall": -1, "cpu": 0.25}
    assert any("bad ratio" in e for e in report.check(with_base))
    result(with_base, "start/ansi", "b")["ratio"] = {"wall": 0.25}
    assert any("missing field 'cpu'" in e for e in report.check(with_base))


# The schema check refuses bad reports.


def _paths(obj, prefix=()):
    """Yield the path of each field of each object in obj."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if prefix[-1:] in (("tools",), ("inputs",)) and prefix[:1] != ("scope",):
                yield from _paths(v, (*prefix, k))
                continue
            yield (*prefix, k)
            yield from _paths(v, (*prefix, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:2]):
            yield from _paths(v, (*prefix, i))


def _get(obj, path):
    for p in path:
        obj = obj[p]
    return obj


def test_each_missing_field_is_refused(good):
    # Not the fields of free objects: settings, work, and the overhead argv.
    free = {"settings", "work"}
    paths = [
        p
        for p in _paths(good)
        if not free & set(map(str, p[:-1])) and isinstance(_get(good, p[:-1]), dict)
    ]
    assert len(paths) > 100
    for path in paths:
        bad = copy.deepcopy(good)
        del _get(bad, path[:-1])[path[-1]]
        errors = report.check(bad)
        assert errors, f"no error without {path}"


def test_a_value_of_any_type_gives_errors_not_an_exception(good):
    paths = list(_paths(good))
    assert len(paths) > 100
    for path in paths:
        for value in (None, "x", "", [], {}, -1, True, 1.5, [[]], [{}], {"a": []}):
            bad = copy.deepcopy(good)
            _get(bad, path[:-1])[path[-1]] = value
            errors = report.check(bad)
            assert not [e for e in errors if "cannot check" in e], (path, value)


@pytest.mark.parametrize(
    "where",
    [
        (),
        ("machine",),
        ("timer", "overhead"),
        ("results", 0),
        ("results", 0, "samples", 0),
    ],
)
def test_an_unknown_field_is_refused(good, where):
    _get(good, where)["extra"] = 1
    assert any("unknown field 'extra'" in e for e in report.check(good))


@pytest.mark.parametrize("status", ["passed", "Valid", "", None, "skip"])
def test_an_unknown_status_is_refused(good, status):
    result(good, "start/ansi", "b")["status"] = status
    assert f"result start/ansi (b): unknown status {status!r}" in report.check(good)


def test_a_valid_result_with_no_stats_is_refused(good):
    result(good, "start/ansi", "a")["stats"] = None
    assert "result start/ansi (a): a valid result needs stats" in report.check(good)


def test_a_valid_result_with_no_timed_run_is_refused(good):
    r = result(good, "start/ansi", "a")
    r["samples"] = r["samples"][:1]
    r["runs"]["timed"] = 0
    errors = report.check(good)
    assert "result start/ansi (a): 0 timed runs, the policy needs 3 to 20" in errors
    assert "result start/ansi (a): no timed sample" in errors


@pytest.mark.parametrize(
    "change, error",
    [
        (
            lambda r: r["stats"]["wall_s"].update(median=0.1),
            "are not those of the samples",
        ),
        (lambda r: r.update(reason="slow"), "a valid result must have no reason"),
        (lambda r: r["samples"][2].update(exit_code=1), "other exit codes"),
        (lambda r: r["samples"][1].update(timed_out=True), "a run has a timeout"),
        (lambda r: r["samples"].pop(0), "runs {'warmup': 1, 'timed': 3} are not"),
        (
            lambda r: r["samples"].append(dict(r["samples"][0])),
            "the warmup sample must be the first and only one",
        ),
        (lambda r: r["samples"][1].update(kind="cold"), "bad value"),
        (lambda r: r["samples"][1].update(wall_s=-1.0), "bad value"),
        (lambda r: r["samples"][1].update(exit_code=True), "bad value"),
        (lambda r: r["runs"].update(timed=3.0), "runs {'warmup': 1, 'timed': 3.0}"),
        (lambda r: r["stats"]["wall_s"].update(n=3.0), "not those of the samples"),
        (lambda r: r.update(input="ansi/small"), "do not agree"),
        (lambda r: r.update(id="start/tsql"), "do not agree"),
        (
            lambda r: r.update(dialect="tsql", id="start/tsql"),
            "dialect not in the scope",
        ),
        (lambda r: r.update(tool="c"), "tool not in tools"),
        (lambda r: r.update(work=[]), "bad work"),
    ],
)
def test_a_bad_valid_result_is_refused(good, change, error):
    change(result(good, "start/ansi", "a"))
    assert any(error in e for e in report.check(good)), report.check(good)


@pytest.mark.parametrize("status", [INVALID, UNSUPPORTED, ERROR])
def test_a_result_that_is_not_valid_needs_a_reason(good, status):
    r = result(good, "parse/ansi/small", "b")
    r["status"] = status
    good["totals"] = report.totals(good["results"], good["tools"])
    assert report.check(good) == []
    r["reason"] = None
    assert f"result parse/ansi/small (b): status {status} needs a reason" in (
        report.check(good)
    )


@pytest.mark.parametrize(
    "change, error",
    [
        (lambda r: r.update(kind="sqll-harness-report"), "kind: "),
        (lambda r: r.update(format=1), "format: "),
        (lambda r: r.update(parts=[]), "parts: not null or a list"),
        (lambda r: r.update(format=True), "format: "),
        (lambda r: r["policy"].update(min_runs=3.0), "not the full policy"),
        (lambda r: r.update(profile="quick"), "unknown profile"),
        (lambda r: r["policy"].update(min_runs=1), "not the full policy"),
        (lambda r: r.update(profile="smoke"), "not the smoke policy"),
        (lambda r: r["inputs"]["start"].update(sha256="x"), "input start: bad value"),
        (lambda r: r["inputs"].pop("start"), "input not in inputs"),
        (lambda r: r["tools"]["a"].update(version=""), "empty version"),
        (lambda r: r["scope"]["tools"].append("c"), "the tools of the scope"),
        (lambda r: r["scope"]["commands"].append("format"), "unknown commands"),
        (lambda r: r["scope"].update(shard="2"), "bad shard"),
        (lambda r: r["scope"].update(shard="3/2"), "bad shard"),
        (lambda r: r["scope"].update(shard="0/2"), "bad shard"),
        (lambda r: r["results"].reverse(), "not sorted by id and tool"),
        (lambda r: r["results"].append(r["results"][0]), "an id and tool are repeated"),
        (lambda r: r["timer"]["overhead"]["stats"]["wall_s"].update(n=5), "timer"),
        (lambda r: r["harness"].update(clean="yes"), "clean is not a bool"),
        (lambda r: r.update(results={}), "results: not a list"),
    ],
)
def test_a_bad_report_is_refused(good, change, error):
    change(good)
    assert any(error in e for e in report.check(good)), report.check(good)


def test_a_report_that_is_not_an_object_is_refused():
    assert report.check([]) == ["report: not an object: []"]


# The schema in harness/README.md.


def _readme_schema() -> dict:
    text = (REPO_ROOT / "harness" / "README.md").read_text(encoding="utf8")
    section = text.split("## Benchmark report: `out/bench.json`", 1)[1]
    block = re.search(r"```json\n(.*?)```", section, re.DOTALL).group(1)
    return json.loads(block)


def test_the_readme_has_each_field_of_the_schema():
    doc = _readme_schema()
    assert tuple(doc) == report.TOP
    assert tuple(doc["harness"]) == report.HARNESS
    assert tuple(doc["machine"]) == report.MACHINE
    assert tuple(doc["timer"]) == report.TIMER
    assert tuple(doc["timer"]["overhead"]) == report.OVERHEAD
    assert tuple(doc["scope"]) == report.SCOPE
    assert tuple(doc["policy"]) == tuple(timer.PROFILES["full"].as_dict())
    ((_, tool),) = doc["tools"].items()
    assert tuple(tool) == report.TOOL
    ((_, inp),) = doc["inputs"].items()
    assert tuple(inp) == report.INPUT
    (res,) = doc["results"]
    assert tuple(res) == report.RESULT
    assert tuple(res["runs"]) == report.RUNS
    (smp,) = res["samples"]
    assert tuple(smp) == report.SAMPLE
    assert tuple(res["stats"]) == ("wall_s", "cpu_s")
    assert tuple(res["stats"]["wall_s"]) == ("n", "median", "min", "max", "mad")
    ((_, total),) = doc["totals"].items()
    assert tuple(total) == report.TOTAL
    (pair,) = doc["pairs"]
    assert tuple(pair) == report.PAIR
    assert tuple(res["ratio"]) == report.RATIO
    (part,) = doc["parts"]
    assert tuple(part) == report.PART
    assert doc["format"] == report.FORMAT
    assert res["status"] == "|".join(timer.STATUSES)
