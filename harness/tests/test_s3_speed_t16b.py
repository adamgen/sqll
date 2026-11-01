"""S3 T16b: the speed checkpoint after T15 and T16.

results/s3/speed/T16b.json is the output of scripts/s3/speed_profile.py
(the T14 method, --task T16b) on the committed T16b sessions and profile,
with the target of T14. T16b has no engine change. The tests make the
report again, compute the go result again, and check that status/S3.md
gives the T14 and the T16b values side by side."""

import hashlib
import importlib.util
import json

import pytest

from sqll_harness.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "speed_profile", REPO_ROOT / "scripts" / "s3" / "speed_profile.py"
)
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)

SESSIONS_FILE, PROFILE_FILE, OUT_FILE = sp.task_files("T16b")
OUT = json.loads(OUT_FILE.read_text("utf8"))
T14 = json.loads(sp.OUT_FILE.read_text("utf8"))
SESSIONS = json.loads(SESSIONS_FILE.read_text("utf8"))
T16_SESSIONS = json.loads(sp.task_files("T16")[0].read_text("utf8"))
PROFILE = json.loads(PROFILE_FILE.read_text("utf8"))
PAIRED = [r for r in OUT["benchmarks"] if r["needed_factor"] is not None]
STATUS = (REPO_ROOT / "status" / "S3.md").read_text("utf8")
INDEX = (REPO_ROOT / "STATUS.md").read_text("utf8")


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def words(text):
    return " ".join(text.split())


def checkpoint():
    return STATUS.split("\n## Speed checkpoint (T16b)\n", 1)[1].split("\n## ", 1)[0]


def worst(report):
    return max(
        (r for r in report["benchmarks"] if r["needed_factor"] is not None),
        key=lambda r: (r["needed_factor"], r["id"]),
    )


# The record.


def test_the_committed_report_is_the_report_of_the_committed_inputs():
    assert sp.main(["report", "--task", "T16b", "--check"]) == 0


def test_the_check_fails_on_a_change(tmp_path, monkeypatch):
    out = tmp_path / "T16b.json"
    text = OUT_FILE.read_text("utf8")
    assert text.count('"task": "T16b"') == 1
    out.write_text(text.replace('"task": "T16b"', '"task": "T17"'), "utf8")
    monkeypatch.setattr(
        sp, "task_files", lambda task: (SESSIONS_FILE, PROFILE_FILE, out)
    )
    assert sp.main(["report", "--task", "T16b", "--check"]) == 1


def test_the_inputs_are_the_committed_files():
    assert OUT["task"] == "T16b"
    assert OUT["inputs"] == {
        "results/s3/speed/T16b-sessions.json": sha256_file(SESSIONS_FILE),
        "results/s3/speed/T16b-callgrind.json": sha256_file(PROFILE_FILE),
        "results/s3/speed-by-base.json": sha256_file(sp.SPEED_BY_BASE_FILE),
        "results/s3/speed-profile.json": sha256_file(sp.OUT_FILE),
    }


def test_no_engine_change_since_t16():
    # The sessions ran the sqll source of the T16 sessions.
    assert SESSIONS["sqll"]["source_sha256"] == T16_SESSIONS["sqll"]["source_sha256"]
    assert SESSIONS["sqll"]["version"] == T16_SESSIONS["sqll"]["version"]
    assert PROFILE["sqll_source_sha256"] == SESSIONS["sqll"]["source_sha256"]


def test_the_sessions_are_5_new_sessions_of_one_clean_commit():
    sessions = SESSIONS["sessions"]
    assert [s["role"] for s in sessions] == ["controlled"] + ["noise"] * 4
    assert len({s["report"]["harness"]["commit"] for s in sessions}) == 1
    for s in sessions:
        assert s["report"]["harness"]["clean"] is True
        assert sorted(s["report"]["tools"]) == ["sqll", "sqruff"]
    assert sessions[0]["started"] > T16_SESSIONS["sessions"][-1]["finished"]
    assert SESSIONS["method"] == T16_SESSIONS["method"] | {
        "host": SESSIONS["method"]["host"]
    }


def test_the_target_is_that_of_t14():
    assert OUT["target"]["margin"] == T14["target"]["margin"] == 0.26
    assert OUT["target"]["ratio_below"] == T14["target"]["ratio_below"]
    assert OUT["target"]["benchmarks"] == len(PAIRED) == 108
    for r in PAIRED:
        assert r["needed_factor"] == pytest.approx(
            max(1.0, r["sqll_s"] / r["sqruff_s"] * 1.26), abs=1e-4
        )


def test_the_noise_is_measured_as_in_t14():
    largest = max(
        max(r["session_ratios"]) / min(r["session_ratios"]) - 1 for r in PAIRED
    )
    assert OUT["noise"]["largest_spread"]["spread"] == pytest.approx(largest, abs=1e-3)
    assert OUT["noise"]["margin"] == sp.ceil2(OUT["noise"]["largest_spread"]["spread"])
    assert OUT["noise"]["sessions"] == 5


def test_each_value_is_measured_or_has_a_formula():
    for r in OUT["benchmarks"]:
        assert r["estimate"]["formula"] in OUT["formulas"]
    assert OUT["noise"]["formula"] in OUT["formulas"]
    assert OUT["target"]["formula"] in OUT["formulas"]
    assert OUT["go"]["formula"] in OUT["formulas"]
    assert OUT["go"]["sensitivity"]["formula"] in OUT["formulas"]
    for c in OUT["classes"]:
        assert c["removable"] and c["basis"]
        if c["r"] < 1:
            assert "assumption" in c["basis"]


def test_the_go_result_follows_from_the_benchmarks():
    go = OUT["go"]
    out = [r["id"] for r in PAIRED if not r["in_reach"]["central"]]
    for r in PAIRED:
        assert r["in_reach"]["central"] == (
            r["estimate"]["central"]["factor"] >= r["needed_factor"]
        )
    assert go["not_in_reach_central"] == out
    assert go["result"] == ("go" if not out else "no-go")
    if out:
        assert go["reason"].endswith("Human decision needed (status/S3.md, Stop rule).")


def test_the_profile_has_the_top_functions_of_the_worst_parse_benchmarks():
    parse = [b for b in PROFILE["worst"] if b.startswith("parse/")]
    assert len(parse) == 5
    assert len(PROFILE["benchmarks"]) == 112
    by_id = {b["id"]: b for b in PROFILE["benchmarks"]}
    for bid in parse:
        for phase in ("all", "lex", "parse"):
            assert by_id[bid][phase]["self_top"], (bid, phase)


def test_the_change_from_t14():
    change = OUT["change"]
    t14 = {r["id"]: r for r in T14["benchmarks"]}
    for row in change["benchmarks"]:
        assert row["ratio"]["t14"] == t14[row["id"]]["ratio"]
    for group, g in change["groups"].items():
        assert g["below_target"]["t14"] == T14["groups"][group]["below_target"]
        assert g["below_target"]["now"] == OUT["groups"][group]["below_target"]


# The status.


def test_the_status_gives_t14_and_t16b_side_by_side():
    section = checkpoint().strip()
    assert len(section.splitlines()) <= 5
    text = words(section)
    m14, m16b = T14["noise"]["margin"], OUT["noise"]["margin"]
    assert f"m: T14 {m14}, T16b {m16b}" in text
    below = [r["groups"]["all"]["below_target"] for r in (T14, OUT)]
    assert f"T14 {below[0]} of 108, T16b {below[1]} of 108" in text
    w14, w16b = worst(T14), worst(OUT)
    assert (
        f"T14 {w14['needed_factor']:.2f} ({w14['id']}), "
        f"T16b {w16b['needed_factor']:.2f} ({w16b['id']})"
    ) in text
    reach = [r["groups"]["all"]["in_reach"]["central"] for r in (T14, OUT)]
    assert f"T14 {reach[0]} of 108, T16b {reach[1]} of 108" in text


def test_the_status_and_the_index_give_the_go_result():
    text = words(checkpoint())
    (row,) = [line for line in INDEX.splitlines() if line.startswith("| S3 |")]
    if OUT["go"]["result"] == "no-go":
        assert "**No-go: human decision needed.**" in text
        assert "the S3 track stops" in text
        assert "T16b: the speed target is still not in reach on the estimate" in row
        assert "human decision needed" in row
    else:
        assert "**Go.**" in text
        assert "No-go" not in text
        assert "human decision needed" not in row
