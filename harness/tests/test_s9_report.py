"""The schema check of the S9 corpus report (docs/decisions/s9-corpus.md,
"Report"). The reports are built from synthetic samples."""

import copy

import pytest

from sqll_harness.bench.timer import Measurement, Sample, sample_stats
from sqll_harness.corpus import report, tables
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


# The pairs of sqll (docs/decisions/s9-corpus.md, "sqll results", decision
# 4: the speed tables of G3). A test-double sqll has results with known
# median times.


def times(wall: float, cpu: float, code: int = 0) -> list[Sample]:
    """A warmup and 2 timed runs: the medians are wall and cpu."""
    return [
        Sample(kind, wall, cpu, 0.0, 7000, code, False)
        for kind in ("warmup", "timed", "timed")
    ]


SQLL_SETTINGS = {
    "raw": {"core": {"rust_parser_max_iterations": 10**12}},
    "jinja": {"core": {"rust_parser_max_iterations": 10**12}},
}
TOOLS3 = {
    "sqlfluff": {"version": "4.4.0", "settings": SETTINGS},
    "sqll": {"version": "0.1.0", "settings": SQLL_SETTINGS},
    "sqruff": {"version": "0.41.0", "settings": SETTINGS},
}


def sqll_results() -> list[dict]:
    """The other tools have the medians (wall, CPU): sqlfluff a (2.05,
    1.01), b (3.05, 1.51), m (1.05, 0.51); sqruff a (0.55, 0.26). sqruff
    is not ok on b and m, and sqlfluff is not ok on n."""
    return [
        # Faster than sqlfluff; slower than sqruff on CPU only.
        entry("s/a.sql", "sqll", "ok", s=times(0.35, 0.3), unparsable=OK0),
        # Slower than sqlfluff on wall time only.
        entry("s/b.sql", "sqll", "ok", s=times(3.55, 1.0), unparsable=OK0),
        # The same times as sqlfluff: not faster.
        entry("s/m.sql", "sqll", "ok", s=times(1.05, 0.51), unparsable=OK0),
        entry("s/n.sql", "sqll", "unsupported", "unsupported: templater jinja"),
    ]


def build3(tools=TOOLS3, rows=None) -> dict:
    if rows is None:
        rows = [r for r in results() + sqll_results() if r["tool"] in tools]
    return build(
        results=rows,
        scope={"tools": sorted(tools), "shard": None},
        tools=dict(tools),
    )


PAIR_FLUFF = {
    "tool": "sqll",
    "other": "sqlfluff",
    "goal": "faster",
    "files": 3,
    "bytes": 59000,
    "wall_s": {"sqll": 4.95, "sqlfluff": 6.15},
    "cpu_s": {"sqll": 1.81, "sqlfluff": 3.03},
    "wall_ratio": round(4.95 / 6.15, 6),
    "cpu_ratio": round(1.81 / 3.03, 6),
    "slow_files": [
        {
            "file": "s/b.sql",
            "bytes": 30000,
            "wall_s": {"sqll": 3.55, "sqlfluff": 3.05},
            "cpu_s": {"sqll": 1.0, "sqlfluff": 1.51},
        },
        {
            "file": "s/m.sql",
            "bytes": 9000,
            "wall_s": {"sqll": 1.05, "sqlfluff": 1.05},
            "cpu_s": {"sqll": 0.51, "sqlfluff": 0.51},
        },
    ],
}
PAIR_SQRUFF = {
    "tool": "sqll",
    "other": "sqruff",
    "goal": "not_slower",
    "files": 1,
    "bytes": 20000,
    "wall_s": {"sqll": 0.35, "sqruff": 0.55},
    "cpu_s": {"sqll": 0.3, "sqruff": 0.26},
    "wall_ratio": round(0.35 / 0.55, 6),
    "cpu_ratio": round(0.3 / 0.26, 6),
    "slow_files": [
        {
            "file": "s/a.sql",
            "bytes": 20000,
            "wall_s": {"sqll": 0.35, "sqruff": 0.55},
            "cpu_s": {"sqll": 0.3, "sqruff": 0.26},
        }
    ],
}


def test_the_test_double_has_the_medians_of_the_pair_data():
    rows = {(r["file"], r["tool"]): r["stats"] for r in build3()["results"]}
    medians = {
        k: (v["wall_s"]["median"], v["cpu_s"]["median"])
        for k, v in rows.items()
        if v is not None
    }
    assert medians[("s/a.sql", "sqlfluff")] == (2.05, 1.01)
    assert medians[("s/b.sql", "sqlfluff")] == (3.05, 1.51)
    assert medians[("s/m.sql", "sqlfluff")] == (1.05, 0.51)
    assert medians[("s/a.sql", "sqruff")] == (0.55, 0.26)
    assert medians[("s/a.sql", "sqll")] == (0.35, 0.3)


def test_a_report_with_sqll_has_a_pair_with_sqlfluff_and_with_sqruff():
    rep = build3()
    assert report.check(rep) == []
    assert rep["pairs"] == [PAIR_FLUFF, PAIR_SQRUFF]
    assert list(rep).index("pairs") == list(rep).index("compared") + 1


def test_a_pair_needs_both_of_its_tools():
    two = {k: TOOLS3[k] for k in ("sqll", "sqruff")}
    rep = build3(two)
    assert report.check(rep) == []
    assert rep["pairs"] == [PAIR_SQRUFF]
    rep = build3({"sqll": TOOLS3["sqll"]})
    assert report.check(rep) == [] and "pairs" not in rep


def test_a_report_with_no_sqll_has_no_pairs_field():
    rep = build()
    assert "pairs" not in rep and report.pairs(rep["results"], rep["tools"], {}) == []
    rep["pairs"] = []
    _one(rep, "pairs: a report with no pair has no pairs field")


def test_the_goal_of_each_pair_lists_each_slow_file():
    assert report.PAIR_GOALS == (("sqlfluff", "faster"), ("sqruff", "not_slower"))
    assert report.is_slow("faster", 1.0, 1.0) and report.is_slow("faster", 1.1, 1.0)
    assert not report.is_slow("faster", 0.9, 1.0)
    assert not report.is_slow("not_slower", 1.0, 1.0)
    assert report.is_slow("not_slower", 1.000001, 1.0)


def test_a_pair_with_no_file_has_no_ratio():
    rows = [r for r in results() + sqll_results() if r["tool"] != "sqll"]
    rows.append(entry("s/a.sql", "sqll", "invalid", "warmup run: no parse tree"))
    rows += [r for r in sqll_results() if r["file"] != "s/a.sql"]
    rep = build3(rows=rows)
    assert report.check(rep) == []
    sq = rep["pairs"][1]
    assert sq["files"] == 0 and sq["bytes"] == 0 and sq["slow_files"] == []
    assert sq["wall_ratio"] is None and sq["cpu_ratio"] is None


def _pair(rep: dict, other: str) -> dict:
    return next(p for p in rep["pairs"] if p["other"] == other)


@pytest.mark.parametrize(
    "edit, text",
    [
        (lambda r: r.pop("pairs"), "report: missing field 'pairs'"),
        (lambda r: r["pairs"].pop(), "pairs: not a list of 2 pairs"),
        (lambda r: r["pairs"].reverse(), "pair sqll to sqlfluff: other is not"),
        (lambda r: _pair(r, "sqruff").update(files=2), "sqruff: files is not 1"),
        (lambda r: _pair(r, "sqruff").update(bytes=1), "sqruff: bytes is not 20000"),
        (lambda r: _pair(r, "sqruff").update(goal="faster"), "goal is not"),
        (lambda r: _pair(r, "sqruff").pop("goal"), "missing field 'goal'"),
        (lambda r: _pair(r, "sqruff").update(x=1), "unknown field 'x'"),
        (
            lambda r: _pair(r, "sqlfluff")["wall_s"].update(sqll=4.9),
            "pair sqll to sqlfluff: wall_s is not",
        ),
        (
            lambda r: _pair(r, "sqlfluff")["cpu_s"].update(sqlfluff=3.0),
            "pair sqll to sqlfluff: cpu_s is not",
        ),
        (
            lambda r: _pair(r, "sqlfluff").update(wall_ratio=0.5),
            "pair sqll to sqlfluff: wall_ratio is not",
        ),
        (
            lambda r: _pair(r, "sqruff").update(cpu_ratio=1.0),
            "pair sqll to sqruff: cpu_ratio is not",
        ),
        (
            lambda r: _pair(r, "sqlfluff")["slow_files"].pop(),
            "pair sqll to sqlfluff: slow_files is not",
        ),
        (
            lambda r: _pair(r, "sqruff").update(slow_files=[]),
            "pair sqll to sqruff: slow_files is not",
        ),
        (
            lambda r: _pair(r, "sqruff")["slow_files"][0]["cpu_s"].update(sqll=0.2),
            "pair sqll to sqruff: slow_files is not",
        ),
    ],
)
def test_a_changed_pair_number_is_found(edit, text):
    rep = copy.deepcopy(build3())
    edit(rep)
    _one(rep, text)


def test_a_changed_median_changes_the_pairs():
    """The pairs come from the samples: a report with other samples and the
    old pairs has an error."""
    old = build3()
    rows = [r for r in results() + sqll_results() if r["file"] != "s/a.sql"]
    rows += [r for r in results() if r["file"] == "s/a.sql"]
    rows.append(entry("s/a.sql", "sqll", "ok", s=times(0.35, 0.2), unparsable=OK0))
    rep = build3(rows=rows)
    assert report.check(rep) == []
    assert _pair(rep, "sqruff")["slow_files"] == []
    assert _pair(rep, "sqruff")["cpu_s"] == {"sqll": 0.2, "sqruff": 0.26}
    rep["pairs"] = old["pairs"]
    _one(rep, "pair sqll to sqruff: cpu_s is not")


def test_the_tables_of_a_report_with_pairs():
    blocks = tables.markdown(build3()).strip("\n").split("\n\n")
    assert len(blocks) == 6
    assert blocks[:4] == tables.markdown(
        {k: v for k, v in build3().items() if k != "pairs"}
    ).strip("\n").split("\n\n")
    assert blocks[4].splitlines() == [
        tables.PAIRS_HEADER,
        "|" + "---|" * 11,
        "| sqll to sqlfluff | sqll is faster | 3 | 59000 | 4.950 | 6.150 | "
        f"{4.95 / 6.15:.3f} | 1.810 | 3.030 | {1.81 / 3.03:.3f} | 2 |",
        "| sqll to sqruff | sqll is not slower | 1 | 20000 | 0.350 | 0.550 | "
        f"{0.35 / 0.55:.3f} | 0.300 | 0.260 | {0.3 / 0.26:.3f} | 1 |",
    ]
    assert blocks[5].splitlines() == [
        tables.SLOW_HEADER,
        "|" + "---|" * 7,
        "| sqll to sqlfluff | `s/b.sql` | 30000 | 3.550 | 3.050 | 1.000 | 1.510 |",
        "| sqll to sqlfluff | `s/m.sql` | 9000 | 1.050 | 1.050 | 0.510 | 0.510 |",
        "| sqll to sqruff | `s/a.sql` | 20000 | 0.350 | 0.550 | 0.300 | 0.260 |",
    ]


def test_a_report_with_no_pairs_has_the_4_tables():
    assert len(tables.markdown(build()).strip("\n").split("\n\n")) == 4


def test_the_summary_gives_each_pair_and_its_slow_files():
    lines = corpus_run.summary_lines(build3())
    start = next(i for i, x in enumerate(lines) if x.startswith("pair "))
    assert lines[start : start + 5] == [
        "pair sqll to sqlfluff (goal: faster): 3 files where both are ok, "
        f"59000 bytes, wall ratio {4.95 / 6.15:.3f}, cpu ratio {1.81 / 3.03:.3f}, "
        "2 slow files",
        "  slow: s/b.sql: wall 3.550 s to 3.050 s, cpu 1.000 s to 1.510 s",
        "  slow: s/m.sql: wall 1.050 s to 1.050 s, cpu 0.510 s to 0.510 s",
        "pair sqll to sqruff (goal: not_slower): 1 files where both are ok, "
        f"20000 bytes, wall ratio {0.35 / 0.55:.3f}, cpu ratio {0.3 / 0.26:.3f}, "
        "1 slow files",
        "  slow: s/a.sql: wall 0.350 s to 0.550 s, cpu 0.300 s to 0.260 s",
    ]
    assert not any(x.startswith("pair ") for x in corpus_run.summary_lines(build()))
