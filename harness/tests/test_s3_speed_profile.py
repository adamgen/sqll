"""S3 T14: parse speed, part 1 (scripts/s3/speed_profile.py).

results/s3/speed-profile.json is the output of the script on the committed
session data (results/s3/speed-profile-sessions.json), the committed profile
(results/s3/speed-profile-callgrind.json), and the T6 record. The drift test
makes it again and fails on a difference. The other tests compute the main
values again from the inputs."""

import hashlib
import importlib.util
import json
import math
import statistics

import pytest

from sqll_harness.bench import definitions as bench_definitions
from sqll_harness.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "speed_profile", REPO_ROOT / "scripts" / "s3" / "speed_profile.py"
)
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


OUT = json.loads(sp.OUT_FILE.read_text("utf8"))
SESSIONS = json.loads(sp.SESSIONS_FILE.read_text("utf8"))
PROFILE = json.loads(sp.PROFILE_FILE.read_text("utf8"))
ROWS = {r["id"]: r for r in OUT["benchmarks"]}
PAIRED = [r for r in OUT["benchmarks"] if r["needed_factor"] is not None]
M = OUT["target"]["margin"]


# The drift test.


def test_the_committed_output_is_the_output_of_the_committed_inputs():
    assert sp.main(["report", "--check"]) == 0


def test_the_check_fails_on_a_change(tmp_path, monkeypatch):
    out = tmp_path / "out.json"
    out.write_text(sp.OUT_FILE.read_text("utf8").replace('"T14"', '"T15"'), "utf8")
    monkeypatch.setattr(sp, "OUT_FILE", out)
    assert sp.main(["report", "--check"]) == 1


def test_a_changed_session_changes_the_report(tmp_path):
    sessions = json.loads(json.dumps(SESSIONS))
    result = next(
        r
        for r in sessions["sessions"][0]["report"]["results"]
        if r["id"] == "parse/ansi/large" and r["tool"] == "sqll"
    )
    result["stats"]["wall_s"]["median"] *= 2
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps(sessions), "utf8")
    new = sp.make_report(sessions_path=path)
    row = next(r for r in new["benchmarks"] if r["id"] == "parse/ansi/large")
    assert row["ratio"] == pytest.approx(2 * ROWS["parse/ansi/large"]["ratio"], 1e-3)


def test_the_inputs_are_the_committed_files():
    assert OUT["inputs"] == {
        "results/s3/speed-profile-sessions.json": sha256_file(sp.SESSIONS_FILE),
        "results/s3/speed-profile-callgrind.json": sha256_file(sp.PROFILE_FILE),
        "results/s3/speed-by-base.json": sha256_file(sp.SPEED_BY_BASE_FILE),
    }


def test_a_session_on_a_changed_worktree_fails(tmp_path):
    sessions = json.loads(json.dumps(SESSIONS))
    sessions["sessions"][2]["report"]["harness"]["clean"] = False
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps(sessions), "utf8")
    with pytest.raises(sp.DataError, match="changed worktree"):
        sp.make_report(sessions_path=path)


def test_a_profile_of_another_source_fails(tmp_path):
    prof = json.loads(json.dumps(PROFILE))
    prof["sqll_source_sha256"] = "0" * 64
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(prof), "utf8")
    with pytest.raises(sp.DataError, match="sqll source"):
        sp.make_report(profile_path=path)


# The session data.


def test_the_sessions_are_the_controlled_session_and_4_noise_sessions():
    sessions = SESSIONS["sessions"]
    assert [s["session"] for s in sessions] == [1, 2, 3, 4, 5]
    assert [s["role"] for s in sessions] == ["controlled"] + ["noise"] * 4
    commits = {s["report"]["harness"]["commit"] for s in sessions}
    assert len(commits) == 1
    for s in sessions:
        rep = s["report"]
        assert rep["profile"] == "full"
        assert rep["scope"]["commands"] == ["start", "parse"]
        assert sorted(rep["tools"]) == ["sqll", "sqruff"]
        assert s["load"]["before"][0] < 0.3
        assert s["load"]["after"][1] <= 1.5


def test_each_median_is_the_median_of_the_timed_runs():
    for s in SESSIONS["sessions"]:
        for r in s["report"]["results"]:
            if r["status"] != "valid":
                assert r["stats"] is None
                continue
            walls = r["samples"]["wall_s"]
            assert len(walls) == r["runs"]["timed"] >= 3
            assert r["stats"]["wall_s"]["median"] == pytest.approx(
                statistics.median(walls), abs=1e-6
            )
            assert set(r["samples"]["exit_code"]) == {0}


def test_the_inputs_of_the_sessions_are_those_of_the_definitions():
    defs = bench_definitions.load()
    for s in SESSIONS["sessions"]:
        for name, entry in s["report"]["inputs"].items():
            assert entry["sha256"] == defs["inputs"][name]["sha256"]


def test_sqll_is_valid_on_each_of_the_112_benchmarks():
    assert len(OUT["benchmarks"]) == 112
    assert sum(r["id"].startswith("start/") for r in OUT["benchmarks"]) == 28
    assert all(r["sqll_s"] > 0 for r in OUT["benchmarks"])
    assert OUT["target"]["no_sqruff_pair"] == [
        "start/soql",
        "parse/soql/small",
        "parse/soql/medium",
        "parse/soql/large",
    ]
    assert len(PAIRED) == OUT["target"]["benchmarks"] == 108


def test_the_phase_samples_are_5_runs_of_each_benchmark():
    samples = SESSIONS["phases"]["samples"]
    assert sorted(samples) == sorted(ROWS)
    for runs in samples.values():
        assert len(runs) == sp.PHASE_RUNS == 5
        for run in runs:
            assert set(run) == {f"{p}_s" for p in sp.PHASES} | {"total_s", "tokens"}


# The values of the report, computed again.


def test_the_ratio_and_the_needed_factor():
    for r in PAIRED:
        assert r["ratio"] == pytest.approx(r["sqll_s"] / r["sqruff_s"], abs=1e-4)
        assert r["needed_factor"] == pytest.approx(
            max(1.0, r["sqll_s"] / r["sqruff_s"] * (1 + M)), abs=1e-4
        )


def test_the_margin_is_the_largest_spread_rounded_up():
    spreads = [max(r["session_ratios"]) / min(r["session_ratios"]) - 1 for r in PAIRED]
    largest = max(spreads)
    assert M == math.ceil(largest * 100) / 100
    assert M >= largest
    assert OUT["target"]["ratio_below"] == pytest.approx(1 / (1 + M), abs=1e-4)


def test_the_phase_times_add_up_to_the_wall_time():
    for r in OUT["benchmarks"]:
        total = sum(r["phase_time"].values())
        assert total == pytest.approx(r["sqll_s"], rel=1e-3), r["id"]


def test_each_gain_and_estimate():
    classes = {c["id"]: c for c in OUT["classes"]}
    for r in OUT["benchmarks"]:
        est = r["estimate"]
        central = upper = 0.0
        for cid, g in est["gains"].items():
            assert g["central_s"] == pytest.approx(
                classes[cid]["r"] * g["removable_s"], abs=2e-6
            )
            assert 0 <= g["removable_s"]
            central += g["central_s"]
            upper += g["removable_s"]
        t = r["sqll_s"]
        assert est["central"]["time_s"] == pytest.approx(t - central, abs=1e-5)
        assert est["upper"]["time_s"] == pytest.approx(t - upper, abs=1e-5)
        assert est["upper"]["time_s"] > 0
        if r["needed_factor"] is not None:
            assert r["in_reach"]["central"] == (
                est["central"]["factor"] >= r["needed_factor"]
            )


def test_the_classes_are_labelled_estimates_with_a_basis():
    for c in OUT["classes"]:
        assert c["task"] in ("T15", "T16")
        assert c["removable"] and c["basis"]
        assert 0 < c["r"] <= 1
        if c["r"] < 1:
            assert "assumption" in c["basis"]


def test_the_go_result_follows_from_the_benchmarks():
    go = OUT["go"]
    out = [r["id"] for r in PAIRED if not r["in_reach"]["central"]]
    assert go["not_in_reach_central"] == out
    assert go["result"] == ("go" if not out else "no-go")
    if out:
        assert "Human decision needed" in go["reason"]


def test_the_t6_numbers_are_copied():
    t6 = json.loads(sp.SPEED_BY_BASE_FILE.read_text("utf8"))
    want = t6["bases"]["sqlfluffrs"]["lex_parse_speedup"]["parse"]
    got = OUT["t6_comparison"]["t6"]
    assert (got["needed"], got["median_factor"], got["max_factor"]) == (
        44,
        1.7518,
        3.824,
    )
    assert got["median_factor"] == want["median_factor"]


# The profile.


def test_the_profile_has_each_benchmark_and_phase():
    assert len(PROFILE["benchmarks"]) == 112
    for b in PROFILE["benchmarks"]:
        for phase in ("all", *sp.PROFILE_PHASES):
            shares = b[phase]["classes"]
            assert sum(shares.values()) == pytest.approx(1.0, abs=2e-3), b["id"]
            assert b[phase]["ir"] > 0
        assert b["parse"]["ir"] < b["all"]["ir"]
    assert len(PROFILE["worst"]) == 6
    for bid in PROFILE["worst"]:
        top = OUT["profile"]["top"][bid]["all"]["self_top"]
        assert len(top) == sp.PROFILE_TOP


ANNOTATE = """\
--------------------------------------------------------------------------------
Ir
--------------------------------------------------------------------------------
1,000 (100.0%)  PROGRAM TOTALS

--------------------------------------------------------------------------------
Ir                    file:function
--------------------------------------------------------------------------------
600 (60.00%)  ./string/memmove.S:__memcpy_avx_unaligned_erms [/lib/libc.so.6]
300 (30.00%)  /a/core.rs:<sqll_parser::parser::core::Parser>::step'2 [/bin/sqll]
 60 ( 6.00%)  /a/other.rs:<sqll_parser::parser::core::Parser>::step [/bin/sqll]
 40 ( 4.00%)  ./malloc/malloc.c:_int_free [/lib/libc.so.6]
  .           ./x/clone.S:clone [/lib/libc.so.6]
"""


def test_the_annotate_output_is_read_by_function():
    total, costs = sp.annotate_text(ANNOTATE)
    assert total == 1000
    costs = sp.self_by_function(costs)
    assert costs == {
        "__memcpy_avx_unaligned_erms": 600,
        "<sqll_parser::parser::core::Parser>::step": 360,
        "_int_free": 40,
    }
    classes = sp.classes_of(total, costs)
    assert (classes["copy"], classes["parser"], classes["allocator"]) == (
        0.6,
        0.36,
        0.04,
    )


def test_the_cost_classes_of_some_functions():
    cases = {
        "__memcpy_avx_unaligned_erms": "copy",
        "<alloc::string::String as core::clone::Clone>::clone": "copy",
        "malloc": "allocator",
        "_int_free_merge_chunk": "allocator",
        "__rustc::__rdl_alloc": "allocator",
        "core::ptr::drop_glue::<sqll_parser::parser::types::Node>": "drop",
        "<core::hash::sip::Hasher<core::hash::sip::Sip13Rounds> as "
        "core::hash::Hasher>::write": "hashing",
        "<regex_automata::meta::regex::Builder>::build": "regex",
        "<sqll_parser::parser::core::Parser>::handle_initial": "parser",
        "_dl_relocate_object": "loader",
        "strcmp": "other",
    }
    for function, want in cases.items():
        assert sp.cost_class(function) == want, function
