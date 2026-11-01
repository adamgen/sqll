"""S3 T17: parse speed, part 4 (close the gap, round 1).

results/s3/speed/T17.json is the output of scripts/s3/speed_profile.py
(the T14 method, --task T17) on the committed T17 sessions and profile,
with the target of T14. results/s3/speed/T17-compare.json is the output of
"sqll-harness bench compare" of 2 sessions of sqll and sqruff: BEFORE (main
before T17) and AFTER (session 1 of the T17 sessions), for the tool sqll
(G3.6). results/s3/speed/T17-soql.json is one session of sqll and sqlfluff
on the soql benchmarks (no sqruff pair). The tests make the report and the
compare again and check the main values and the status."""

import hashlib
import importlib.util
import json

import pytest

from sqll_harness.bench import compare as bench_compare
from sqll_harness.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "speed_profile", REPO_ROOT / "scripts" / "s3" / "speed_profile.py"
)
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)

SPEED = REPO_ROOT / "results" / "s3" / "speed"
SESSIONS_FILE, PROFILE_FILE, OUT_FILE = sp.task_files("T17")
BEFORE_FILE = SPEED / "T17-before.json"
AFTER_FILE = SPEED / "T17-after.json"
COMPARE_FILE = SPEED / "T17-compare.json"
SOQL_FILE = SPEED / "T17-soql.json"
OUT = json.loads(OUT_FILE.read_text("utf8"))
T14 = json.loads(sp.OUT_FILE.read_text("utf8"))
SESSIONS = json.loads(SESSIONS_FILE.read_text("utf8"))
T16B_SESSIONS = json.loads(sp.task_files("T16b")[0].read_text("utf8"))
PROFILE = json.loads(PROFILE_FILE.read_text("utf8"))
COMPARE = json.loads(COMPARE_FILE.read_text("utf8"))
SOQL = json.loads(SOQL_FILE.read_text("utf8"))
PAIRED = [r for r in OUT["benchmarks"] if r["needed_factor"] is not None]
STATUS = (REPO_ROOT / "status" / "S3.md").read_text("utf8")


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def words(text):
    return " ".join(text.split())


# The record.


def test_the_committed_report_is_the_report_of_the_committed_inputs():
    assert sp.main(["report", "--task", "T17", "--check"]) == 0


def test_the_inputs_are_the_committed_files():
    assert OUT["task"] == "T17"
    assert OUT["inputs"] == {
        "results/s3/speed/T17-sessions.json": sha256_file(SESSIONS_FILE),
        "results/s3/speed/T17-callgrind.json": sha256_file(PROFILE_FILE),
        "results/s3/speed-by-base.json": sha256_file(sp.SPEED_BY_BASE_FILE),
        "results/s3/speed-profile.json": sha256_file(sp.OUT_FILE),
    }


def test_the_sessions_are_5_new_sessions_of_one_clean_commit():
    sessions = SESSIONS["sessions"]
    assert [s["role"] for s in sessions] == ["controlled"] + ["noise"] * 4
    assert len({s["report"]["harness"]["commit"] for s in sessions}) == 1
    for s in sessions:
        assert s["report"]["harness"]["clean"] is True
        assert sorted(s["report"]["tools"]) == ["sqll", "sqruff"]
    assert sessions[0]["started"] > T16B_SESSIONS["sessions"][-1]["finished"]
    assert SESSIONS["sqll"]["source_sha256"] != T16B_SESSIONS["sqll"]["source_sha256"]


def test_the_profile_is_of_the_source_of_the_sessions():
    assert PROFILE["sqll_source_sha256"] == SESSIONS["sqll"]["source_sha256"]
    assert len(PROFILE["benchmarks"]) == 112
    # Since T17 the toggles are the phase functions of crates/sqll/src/parse.rs
    # (link-time optimization inlines the functions of T14 to T16b).
    assert PROFILE["phases"] == sp.PROFILE_PHASES
    for b in PROFILE["benchmarks"]:
        for phase in sp.PROFILE_PHASES:
            assert b[phase]["ir"] > 0, (b["id"], phase)


def test_the_target_is_that_of_t14():
    assert OUT["target"]["margin"] == T14["target"]["margin"] == 0.26
    assert OUT["target"]["ratio_below"] == T14["target"]["ratio_below"]
    assert OUT["target"]["benchmarks"] == len(PAIRED) == 108
    for r in PAIRED:
        assert r["needed_factor"] == pytest.approx(
            max(1.0, r["sqll_s"] / r["sqruff_s"] * 1.26), abs=1e-4
        )


def test_the_benchmarks_above_the_target():
    limit = 1 / (1 + OUT["target"]["margin"])
    above = sorted(r["id"] for r in PAIRED if not r["ratio"] < limit)
    assert OUT["target"]["above"] == above
    assert OUT["groups"]["all"]["below_target"] == len(PAIRED) - len(above)
    worst = max(PAIRED, key=lambda r: (r["ratio"], r["id"]))
    assert OUT["target"]["worst"] == {"id": worst["id"], "ratio": worst["ratio"]}


def test_the_change_from_t14():
    change = OUT["change"]
    t14 = {r["id"]: r for r in T14["benchmarks"]}
    for row in change["benchmarks"]:
        assert row["ratio"]["t14"] == t14[row["id"]]["ratio"]
    for group, g in change["groups"].items():
        assert g["below_target"]["t14"] == T14["groups"][group]["below_target"]
        assert g["below_target"]["now"] == OUT["groups"][group]["below_target"]


# The bench compare (G3.6).


def test_after_is_session_1_of_the_t17_sessions():
    after = json.loads(AFTER_FILE.read_text("utf8"))
    controlled = SESSIONS["sessions"][0]["report"]
    assert after["harness"] == controlled["harness"]
    medians = {
        (r["id"], r["tool"]): r["stats"]["wall_s"]["median"]
        for r in controlled["results"]
        if r["stats"]
    }
    for r in after["results"]:
        if r["stats"]:
            assert r["stats"]["wall_s"]["median"] == medians[(r["id"], r["tool"])]


def test_before_is_main_before_t17():
    before = json.loads(BEFORE_FILE.read_text("utf8"))
    after = json.loads(AFTER_FILE.read_text("utf8"))
    assert before["harness"]["clean"] is True
    assert before["harness"]["commit"] != after["harness"]["commit"]
    assert before["profile"] == after["profile"] == "full"
    assert before["machine"] == after["machine"]


def test_the_compare_is_the_output_of_the_committed_reports():
    before = json.loads(BEFORE_FILE.read_text("utf8"))
    after = json.loads(AFTER_FILE.read_text("utf8"))
    got = bench_compare.compare(
        ("results/s3/speed/T17-after.json", after),
        ("results/s3/speed/T17-before.json", before),
        tools=["sqll"],
    )
    assert json.loads(json.dumps(got)) == COMPARE
    assert COMPARE["ok"] is True


def test_no_sqll_benchmark_is_slower():
    rows = [b for b in COMPARE["benchmarks"] if b["tool"] == "sqll"]
    assert len(rows) == 112
    assert not [b["id"] for b in rows if b["change"] in ("slower", "failure")]


# The soql benchmarks (no sqruff pair): faster than sqlfluff (G3.4).


def test_the_soql_session_is_of_the_source_of_the_sessions():
    assert SOQL["harness"]["clean"] is True
    assert (
        SOQL["harness"]["commit"]
        == SESSIONS["sessions"][0]["report"]["harness"]["commit"]
    )
    assert sorted(SOQL["tools"]) == ["sqlfluff", "sqll"]


def test_sqll_is_faster_than_sqlfluff_on_each_soql_benchmark():
    medians = {
        (r["id"], r["tool"]): r["stats"]["wall_s"]["median"]
        for r in SOQL["results"]
        if r["stats"]
    }
    ids = ["start/soql", "parse/soql/small", "parse/soql/medium", "parse/soql/large"]
    assert sorted({i for i, _ in medians}) == sorted(ids)
    for bid in ids:
        assert medians[(bid, "sqll")] < medians[(bid, "sqlfluff")], bid
    assert set(OUT["target"]["no_sqruff_pair"]) == set(ids)


# The status.


def test_the_status_gives_the_count_below_the_target():
    below = OUT["groups"]["all"]["below_target"]
    assert f"{below} of 108 start and parse benchmarks" in words(STATUS)


def test_the_status_gives_the_worst_ratio_and_the_list_above_the_target():
    text = words(STATUS)
    worst = OUT["target"]["worst"]
    assert f"at most {worst['ratio']:.3f} ({worst['id']})" in text
    if OUT["target"]["above"]:
        assert "Above the target: " + ", ".join(OUT["target"]["above"]) in text
    else:
        assert "Above the target: none." in text
