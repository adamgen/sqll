"""S3 T15: parse speed, part 2 (start and fixed costs).

results/s3/speed/T15.json is the output of scripts/s3/speed_profile.py
(the T14 method, --task T15) on the committed T15 sessions and profile,
with the target of T14. results/s3/speed/T15-compare.json is the output of
"sqll-harness bench compare" of 2 sessions of sqll and sqruff: BEFORE (main
before T15) and AFTER (session 1 of the T15 sessions), for the tool sqll
(G3.6). The tests make both again and check the main values."""

import hashlib
import importlib.util
import json

import pytest
from conftest import s3_record

from sqll_harness.bench import compare as bench_compare
from sqll_harness.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "speed_profile", REPO_ROOT / "scripts" / "s3" / "speed_profile.py"
)
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)

SPEED = REPO_ROOT / "results" / "s3" / "speed"
SESSIONS_FILE, PROFILE_FILE, OUT_FILE = sp.task_files("T15")
BEFORE_FILE = SPEED / "T15-before.json"
AFTER_FILE = SPEED / "T15-after.json"
COMPARE_FILE = SPEED / "T15-compare.json"
OUT = json.loads(OUT_FILE.read_text("utf8"))
T14 = json.loads(sp.OUT_FILE.read_text("utf8"))
SESSIONS = json.loads(SESSIONS_FILE.read_text("utf8"))
COMPARE = json.loads(COMPARE_FILE.read_text("utf8"))
STATUS = s3_record()


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_committed_report_is_the_report_of_the_committed_inputs():
    assert sp.main(["report", "--task", "T15", "--check"]) == 0


def test_the_inputs_are_the_committed_files():
    assert OUT["task"] == "T15"
    assert OUT["inputs"] == {
        "results/s3/speed/T15-sessions.json": sha256_file(SESSIONS_FILE),
        "results/s3/speed/T15-callgrind.json": sha256_file(PROFILE_FILE),
        "results/s3/speed-by-base.json": sha256_file(sp.SPEED_BY_BASE_FILE),
        "results/s3/speed-profile.json": sha256_file(sp.OUT_FILE),
    }


def test_the_target_is_that_of_t14():
    assert OUT["target"]["margin"] == T14["target"]["margin"] == 0.26
    assert OUT["target"]["ratio_below"] == T14["target"]["ratio_below"]
    for r in OUT["benchmarks"]:
        if r["sqruff_s"] is not None:
            assert r["needed_factor"] == pytest.approx(
                max(1.0, r["sqll_s"] / r["sqruff_s"] * 1.26), abs=1e-4
            )


def test_the_change_from_t14():
    change = OUT["change"]
    t14 = {r["id"]: r for r in T14["benchmarks"]}
    for row in change["benchmarks"]:
        assert row["ratio"]["t14"] == t14[row["id"]]["ratio"]
    for group, g in change["groups"].items():
        assert g["below_target"]["t14"] == T14["groups"][group]["below_target"]
        assert g["below_target"]["now"] == OUT["groups"][group]["below_target"]


def test_the_sessions_are_5_sessions_of_one_clean_commit():
    sessions = SESSIONS["sessions"]
    assert [s["role"] for s in sessions] == ["controlled"] + ["noise"] * 4
    assert len({s["report"]["harness"]["commit"] for s in sessions}) == 1
    for s in sessions:
        assert s["report"]["harness"]["clean"] is True
        assert sorted(s["report"]["tools"]) == ["sqll", "sqruff"]


def test_the_profile_is_of_the_source_of_the_sessions():
    prof = json.loads(PROFILE_FILE.read_text("utf8"))
    assert prof["sqll_source_sha256"] == SESSIONS["sqll"]["source_sha256"]
    assert len(prof["benchmarks"]) == 112


# The bench compare (G3.6).


def test_after_is_session_1_of_the_t15_sessions():
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


def test_before_is_main_before_t15():
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
        ("results/s3/speed/T15-after.json", after),
        ("results/s3/speed/T15-before.json", before),
        tools=["sqll"],
    )
    assert json.loads(json.dumps(got)) == COMPARE
    assert COMPARE["ok"] is True


def test_no_sqll_benchmark_is_slower():
    rows = [b for b in COMPARE["benchmarks"] if b["tool"] == "sqll"]
    assert len(rows) == 112
    assert not [b["id"] for b in rows if b["change"] in ("slower", "failure")]


def test_the_status_gives_the_count_below_the_target():
    below = OUT["groups"]["all"]["below_target"]
    total = OUT["groups"]["all"]["benchmarks"]
    assert f"{below} of {total}" in " ".join(STATUS.split())
