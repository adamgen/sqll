"""The schema check of the S9 corpus report (docs/decisions/s9-corpus.md,
"Report"). The reports are built from synthetic samples."""

import copy

import pytest

from sqll_harness.bench.timer import Measurement, Sample, sample_stats
from sqll_harness.corpus import report
from sqll_harness.corpus import run as corpus_run

SHA = "a" * 64
POLICY = corpus_run.PROFILES["full"].as_dict()
MACHINE = {
    "cpu_model": "test",
    "cpu_count": 4,
    "memory_kib": 1024,
    "os": "test",
    "kernel": "1",
    "arch": "x86_64",
    "python": "3.13",
}
OVERHEAD = [Sample("timed", 0.001, 0.0, 0.0, 1000, 0, False)]
TIMER = {
    "clock": "time.perf_counter_ns",
    "rusage": "os.wait4",
    "overhead": {
        "argv": ["/bin/true"],
        "samples": [s.as_dict() for s in OVERHEAD],
        "stats": sample_stats(OVERHEAD),
    },
}
SETTINGS = {"raw": {"core": {"templater": "raw"}}, "jinja": {"core": {}}}


def inp(name: str, size: int, templater: str = "raw", ref=None) -> dict:
    source, path = name.split("/", 1)
    return {
        "source": source,
        "path": path,
        "dialect": "ansi",
        "templater": templater,
        "bytes": size,
        "lines": 10,
        "sha256": SHA,
        "reference": ref,
    }


INPUTS = {
    "s/a.sql": inp("s/a.sql", 20000),
    "s/b.sql": inp("s/b.sql", 30000),
    "s/m.sql": inp("s/m.sql", 9000, "jinja", report.reference_record(SHA, None)),
    "s/n.sql": inp("s/n.sql", 9000, "jinja", report.reference_record(None, "bad")),
}


def samples(wall: float, code: int = 0, timed: int = 2) -> list[Sample]:
    out = [Sample("warmup", wall, wall / 2, 0.01, 5000, code, False)]
    return out + [
        Sample("timed", wall + i / 10, wall / 2, 0.01, 6000 + i, code, False)
        for i in range(timed)
    ]


def entry(file, tool, status, reason=None, s=None, unparsable=None) -> dict:
    s = s or []
    timed = [x for x in s if x.kind == "timed"]
    m = Measurement(status, reason, s, sample_stats(timed) if timed else None)
    return report.result_entry(
        file, INPUTS[file]["bytes"], tool, status, reason, m, unparsable
    )


OK0 = {"count": 0, "bytes": 0}


def results() -> list[dict]:
    return [
        entry("s/a.sql", "sqlfluff", "ok", s=samples(2.0), unparsable=OK0),
        entry("s/a.sql", "sqruff", "ok", s=samples(0.5), unparsable=OK0),
        entry("s/b.sql", "sqlfluff", "ok", s=samples(3.0), unparsable=OK0),
        entry(
            "s/b.sql",
            "sqruff",
            "unparsable",
            "1 unparsable segments (8 bytes)",
            samples(0.4, 1),
            {"count": 1, "bytes": 8},
        ),
        entry("s/m.sql", "sqlfluff", "ok", s=samples(1.0), unparsable=OK0),
        entry(
            "s/m.sql",
            "sqruff",
            "invalid",
            "warmup run: timeout",
            [Sample("warmup", 9.0, 9.0, 0.0, 100, -9, True)],
        ),
        entry(
            "s/n.sql",
            "sqlfluff",
            "no_reference",
            "no reference: bad",
            samples(1.0, 1),
            {"count": 3, "bytes": 30},
        ),
        entry("s/n.sql", "sqruff", "unsupported", "unsupported: dialect ansi"),
    ]


def build(**changes) -> dict:
    args = {
        "sqlfluff_ref": "0" * 40,
        "profile": "full",
        "policy": POLICY,
        "machine": MACHINE,
        "harness": {"commit": "c" * 40, "clean": True},
        "timer": TIMER,
        "manifest_sha256": SHA,
        "scope": {"tools": ["sqlfluff", "sqruff"], "shard": None},
        "tools": {
            "sqlfluff": {"version": "4.4.0", "settings": SETTINGS},
            "sqruff": {"version": "0.41.0", "settings": SETTINGS},
        },
        "inputs": INPUTS,
        "results": results(),
    }
    args.update(changes)
    return report.build(**args)


def test_a_built_report_has_no_schema_error():
    rep = build()
    assert report.check(rep) == []
    assert rep["kind"] == "sqll-corpus-report" and rep["format"] == 1


def test_the_derived_fields_of_a_result():
    rows = {(r["file"], r["tool"]): r for r in build()["results"]}
    a = rows[("s/a.sql", "sqlfluff")]
    assert a["exit_code"] == 0 and a["max_rss_kib"] == 6001
    assert a["runs"] == {"warmup": 1, "timed": 2}
    assert a["bytes_per_s"] == round(20000 / a["stats"]["wall_s"]["median"], 6)
    t = rows[("s/m.sql", "sqruff")]
    assert t["exit_code"] == -9 and t["stats"] is None and t["bytes_per_s"] is None
    u = rows[("s/n.sql", "sqruff")]
    assert u["exit_code"] is None and u["max_rss_kib"] is None


def test_the_totals_count_each_status():
    totals = build()["totals"]
    assert totals["sqruff"] == {
        "ok": 1,
        "unparsable": 1,
        "no_reference": 0,
        "invalid": 1,
        "unsupported": 1,
        "error": 0,
    }
    assert totals["sqlfluff"]["ok"] == 3 and totals["sqlfluff"]["no_reference"] == 1


def test_the_compared_totals_use_the_files_where_each_tool_is_ok():
    c = build()["compared"]
    assert c["tools"] == ["sqlfluff", "sqruff"]
    assert c["files"] == 1 and c["bytes"] == 20000
    fluff, sq = c["results"]["sqlfluff"], c["results"]["sqruff"]
    assert fluff["wall_s"] == 2.05 and sq["wall_s"] == 0.55
    assert sq["wall_ratio"] == round(0.55 / 2.05, 6) and fluff["wall_ratio"] == 1.0
    assert sq["bytes_per_s"] == round(20000 / 0.55, 6)


def test_with_no_sqlfluff_the_ratios_are_null():
    rows = [r for r in results() if r["tool"] == "sqruff"]
    rep = build(
        results=rows,
        scope={"tools": ["sqruff"], "shard": None},
        tools={"sqruff": {"version": "0.41.0", "settings": SETTINGS}},
    )
    assert report.check(rep) == []
    assert rep["compared"]["results"]["sqruff"]["wall_ratio"] is None


def _one(rep: dict, text: str) -> None:
    errors = report.check(rep)
    assert any(text in e for e in errors), errors


def _result(rep: dict, file: str, tool: str) -> dict:
    return next(r for r in rep["results"] if (r["file"], r["tool"]) == (file, tool))


@pytest.mark.parametrize(
    "edit, text",
    [
        (lambda r: r.update(kind="x"), "kind: not"),
        (lambda r: r.update(format=2), "format: not 1"),
        (lambda r: r.pop("compared"), "missing field 'compared'"),
        (lambda r: r.update(extra=1), "unknown field 'extra'"),
        (lambda r: r.update(profile="huge"), "unknown profile"),
        (lambda r: r["policy"].update(max_runs=9), "policy: not the full policy"),
        (lambda r: r.update(manifest_sha256="x"), "manifest_sha256: not a sha256"),
        (lambda r: r["scope"].update(shard="3/2"), "scope: bad shard"),
        (lambda r: r["scope"].update(tools=["sqruff"]), "the tools of the scope"),
        (lambda r: r["tools"]["sqruff"].update(settings={}), "settings must have"),
        (lambda r: r["inputs"]["s/a.sql"].update(sha256="x"), "input s/a.sql: bad"),
        (lambda r: r["inputs"]["s/a.sql"].update(path="z"), "input s/a.sql: bad"),
        (
            lambda r: r["inputs"]["s/a.sql"].update(reference={}),
            "has no reference",
        ),
        (
            lambda r: r["inputs"]["s/m.sql"]["reference"].update(sha256=None),
            "input s/m.sql reference: bad value",
        ),
        (lambda r: r["results"].reverse(), "not sorted by file and tool"),
        (lambda r: r["results"].append(r["results"][0]), "are repeated"),
        (lambda r: r["totals"]["sqruff"].update(ok=5), "totals: not"),
        (lambda r: r["compared"].update(files=2), "compared: not"),
    ],
)
def test_a_report_error_is_found(edit, text):
    rep = copy.deepcopy(build())
    edit(rep)
    _one(rep, text)


@pytest.mark.parametrize(
    "file, tool, edit, text",
    [
        ("s/a.sql", "sqlfluff", {"status": "great"}, "unknown status"),
        ("s/a.sql", "sqlfluff", {"reason": "x"}, "an ok result must have no reason"),
        ("s/b.sql", "sqruff", {"reason": None}, "status unparsable needs a reason"),
        ("s/a.sql", "sqlfluff", {"bytes_per_s": 1.0}, "bytes_per_s is not"),
        ("s/a.sql", "sqlfluff", {"max_rss_kib": 1}, "max_rss_kib is not"),
        ("s/a.sql", "sqlfluff", {"exit_code": 1}, "exit_code is not 0"),
        ("s/a.sql", "sqlfluff", {"runs": {"warmup": 1, "timed": 1}}, "runs"),
        ("s/a.sql", "sqlfluff", {"file": "s/z.sql"}, "file not in inputs"),
        ("s/a.sql", "sqlfluff", {"tool": "sqll"}, "tool not in tools"),
        (
            "s/a.sql",
            "sqlfluff",
            {"unparsable": {"count": 1, "bytes": 2}},
            "an ok result has no unparsable",
        ),
        (
            "s/b.sql",
            "sqruff",
            {"unparsable": {"count": 0, "bytes": 0}},
            "needs a count > 0",
        ),
        ("s/m.sql", "sqruff", {"unparsable": OK0}, "must have no unparsable"),
        ("s/m.sql", "sqruff", {"stats": {}}, "must have no stats"),
        (
            "s/a.sql",
            "sqlfluff",
            {"status": "no_reference", "reason": "x"},
            "does not agree with the reference record",
        ),
        (
            "s/n.sql",
            "sqlfluff",
            {"status": "unparsable", "reason": "x"},
            "does not agree with the reference record",
        ),
        (
            "s/n.sql",
            "sqruff",
            {"samples": [Sample("warmup", 1, 1, 0, 1, 0, False).as_dict()]},
            "an unsupported result must have no samples",
        ),
    ],
)
def test_a_result_error_is_found(file, tool, edit, text):
    rep = copy.deepcopy(build())
    _result(rep, file, tool).update(edit)
    _one(rep, text)


def test_stats_must_be_those_of_the_samples():
    rep = copy.deepcopy(build())
    r = _result(rep, "s/a.sql", "sqlfluff")
    r["samples"][1]["wall_s"] = 99.0
    _one(rep, "stats")


def test_an_ok_result_needs_exit_code_0():
    rows = results()
    rows[0] = entry("s/a.sql", "sqlfluff", "ok", s=samples(2.0, 1), unparsable=OK0)
    _one(build(results=rows), "an ok result needs exit code 0")


def test_a_timed_result_needs_the_runs_of_the_policy():
    rep = copy.deepcopy(build())
    r = _result(rep, "s/a.sql", "sqlfluff")
    r["samples"] = r["samples"][:1]
    r["runs"] = {"warmup": 1, "timed": 0}
    r["max_rss_kib"] = 5000
    _one(rep, "0 timed runs, the policy needs 1 to 5")


def test_a_timed_result_needs_one_exit_code():
    s = samples(2.0)
    s[2] = Sample("timed", 2.0, 1.0, 0.0, 1, 1, False)
    rows = results()
    rows[0] = entry("s/a.sql", "sqlfluff", "ok", s=s, unparsable=OK0)
    _one(build(results=rows), "the runs must have one exit code")


def test_a_merged_report_needs_each_part():
    part = {"shard": "1/2", "machine": MACHINE, "timer": TIMER}
    _one(build(parts=[part]), "the shards are not 1/1 to 1/1")
    rep = build(parts=[{**part, "shard": "1/1"}])
    assert report.check(rep) == []


def test_write_refuses_a_report_with_an_error(tmp_path):
    rep = copy.deepcopy(build())
    rep["kind"] = "x"
    with pytest.raises(report.ReportError):
        report.write(rep, tmp_path / "r.json")
    assert not (tmp_path / "r.json").exists()
    report.write(build(), tmp_path / "r.json")
    assert report.load(tmp_path / "r.json") == build()


def test_check_does_not_stop_on_a_value_of_another_type():
    rep = copy.deepcopy(build())
    rep["results"][0]["samples"] = "x"
    assert report.check(rep)
    rep = copy.deepcopy(build())
    rep["inputs"] = []
    assert report.check(rep) == ["inputs: not an object"]
    assert report.check(None)
