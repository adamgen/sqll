"""S3 T2: results/s3/s1-by-base.json is the output of scripts/s3/s1_by_base.py
on the committed inputs, and the sqruff per-case run agrees with the S1
summary and known_failures/sqruff.txt."""

import copy
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter

import pytest

from sqll_harness import known_failures
from sqll_harness.paths import KNOWN_FAILURES_DIR, RECORDED_SUMMARY, REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "s1_by_base", REPO_ROOT / "scripts" / "s3" / "s1_by_base.py"
)
s1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s1)

SUMMARY = json.loads(RECORDED_SUMMARY.read_text("utf8"))
CASES = json.loads(s1.CASES_FILE.read_text("utf8"))
OUT = json.loads(s1.OUT_FILE.read_text("utf8"))
KNOWN = known_failures.load(KNOWN_FAILURES_DIR, "sqruff")
TOOLS = {"sqruff": "sqruff", "sqlfluffrs": "sqlfluff-rs"}


def write_cases(tmp_path, record) -> str:
    path = tmp_path / "cases.json"
    path.write_text(s1.text(record), "utf8")
    return path


def rows(record, prefix):
    return [r for r in record["cases"] if r[0].startswith(prefix)]


# Drift.


def test_the_committed_output_is_the_build_of_the_committed_inputs():
    assert s1.text(s1.build()) == s1.OUT_FILE.read_text("utf8")
    assert s1.main(["build", "--check"]) == 0


def test_the_check_fails_on_a_change(tmp_path):
    changed = copy.deepcopy(OUT)
    changed["bases"]["sqruff"]["dialects"]["ansi"]["pass"] += 1
    out = tmp_path / "s1-by-base.json"
    out.write_text(s1.text(changed), "utf8")
    assert s1.main(["build", "--check", "--out", str(out)]) == 1
    out.write_text(s1.OUT_FILE.read_text("utf8") + " ", "utf8")
    assert s1.main(["build", "--check", "--out", str(out)]) == 1
    assert s1.main(["build", "--check", "--out", str(tmp_path / "none")]) == 1


def test_a_changed_input_changes_the_output(tmp_path):
    record = copy.deepcopy(CASES)
    record["harness"]["commit"] = "0" * 40
    path = write_cases(tmp_path, record)
    assert s1.text(s1.build(path)) != s1.OUT_FILE.read_text("utf8")
    assert s1.main(["build", "--check", "--cases", str(path)]) == 1


# The sqruff per-case run.


def test_the_sqruff_dialect_run_agrees_with_the_summary():
    dialects = rows(CASES, "dialects/")
    want = SUMMARY["results"]["sqruff"]["suites"]["dialects"]
    assert len(dialects) == want["total"] == 2306
    assert sum(r[2][0] == 1 for r in dialects) == want["checks"]["exact"] == 1548
    assert (
        sum(r[2][1] == 1 for r in dialects) == want["checks"]["no_unparsable"] == 2164
    )
    failed = {r[0] for r in dialects if r[1] != "pass"}
    assert failed == {i for i in KNOWN if i.startswith("dialects/")}
    assert len(failed) == 758


def test_the_failed_cases_of_each_suite_are_the_known_failures():
    failed = {r[0] for r in CASES["cases"] if r[1] in ("fail", "error")}
    assert failed == set(KNOWN)
    assert Counter(r[1] for r in CASES["cases"]) == {
        "pass": 3806,
        "fail": 1124,
        "error": 7,
    }


def _shift(record, case_id, status, values):
    for r in record["cases"]:
        if r[0] == case_id:
            r[1], r[2] = status, values
            return
    raise AssertionError(case_id)


def _first(record, prefix, status):
    return next(r for r in rows(record, prefix) if r[1] == status)


def test_a_changed_count_fails(tmp_path):
    record = copy.deepcopy(CASES)
    case = _first(record, "dialects/", "pass")
    _shift(record, case[0], "fail", [0, 1])
    with pytest.raises(s1.DataError, match="known_failures"):
        s1.build(write_cases(tmp_path, record))
    assert s1.main(["build", "--cases", str(tmp_path / "cases.json")]) == 1


def test_a_swap_of_two_cases_fails(tmp_path):
    # The counts do not change; only the failed set does.
    record = copy.deepcopy(CASES)
    good = _first(record, "dialects/", "pass")
    bad = next(
        r for r in rows(record, "dialects/") if r[1] == "fail" and r[2] == [0, 1]
    )
    _shift(record, good[0], "fail", [0, 1])
    _shift(record, bad[0], "pass", [1, 1])
    with pytest.raises(s1.DataError, match="dialects: the failed cases"):
        s1.build(write_cases(tmp_path, record))


def test_a_missing_case_fails(tmp_path):
    record = copy.deepcopy(CASES)
    record["cases"] = [
        r for r in record["cases"] if r[1] == "fail" or "ansi" not in r[0]
    ]
    with pytest.raises(s1.DataError, match="not those of the fixtures"):
        s1.build(write_cases(tmp_path, record))


def test_a_check_that_does_not_apply_fails(tmp_path):
    record = copy.deepcopy(CASES)
    case = next(r for r in rows(record, "rules/") if r[1] == "pass" and r[2][0] is None)
    _shift(record, case[0], "pass", [1, *case[2][1:]])
    with pytest.raises(s1.DataError, match="do not apply"):
        s1.build(write_cases(tmp_path, record))


def test_a_status_that_does_not_agree_with_the_checks_fails(tmp_path):
    record = copy.deepcopy(CASES)
    case = next(r for r in rows(record, "dialects/") if r[1] == "fail")
    _shift(record, case[0], "fail", [1, 1])
    with pytest.raises(s1.DataError, match="does not agree"):
        s1.build(write_cases(tmp_path, record))


@pytest.mark.parametrize(
    "values", [[2, 1], [True, True], [1, True], ["1", 1], [1.0, 1]]
)
def test_a_check_value_that_is_not_0_1_or_null_fails(tmp_path, values):
    record = copy.deepcopy(CASES)
    case = _first(record, "dialects/", "pass")
    _shift(record, case[0], "pass", values)
    with pytest.raises(s1.DataError, match="bad row"):
        s1.build(write_cases(tmp_path, record))


@pytest.mark.parametrize("clean", [False, None, 1])
def test_a_run_in_a_checkout_with_changes_fails(tmp_path, clean):
    record = copy.deepcopy(CASES)
    record["harness"]["clean"] = clean
    with pytest.raises(s1.DataError, match="has changes"):
        s1.build(write_cases(tmp_path, record))


def test_the_note_on_failure_reasons_is_true(monkeypatch):
    # The build does not compare the reasons with another file: it copies
    # them from known_failures/sqruff.txt. The note must say that, and only
    # the drift check finds a changed reason.
    note = " ".join(OUT["bases"]["sqruff"]["note"].split())
    assert "checks the suite totals and the failed cases against" in note
    assert "failure reasons are the text of known_failures/sqruff.txt" in note
    assert "extract checks that the run gives this text" in note
    load = known_failures.load

    def changed(directory, tool):
        found = load(directory, tool)
        if tool == "sqruff":
            case = next(i for i, r in found.items() if i.startswith("dialects/"))
            found[case] = "fix mismatch: changed"
        return found

    monkeypatch.setattr(s1.known_failures, "load", changed)
    assert s1.text(s1.build()) != s1.OUT_FILE.read_text("utf8")
    assert s1.main(["build", "--check"]) == 1


def test_another_tool_record_fails(tmp_path):
    record = copy.deepcopy(CASES)
    record["record"]["version"] = "0.40.0"
    with pytest.raises(s1.DataError, match="sqruff record"):
        s1.build(write_cases(tmp_path, record))


# extract: the committed per-case list is that of a report.


def _report(record):
    """A report of the run that gives the committed per-case list."""
    cases = []
    for r in record["cases"]:
        suite = r[0].split("/", 1)[0]
        checks = {
            c: bool(v)
            for c, v in zip(s1.CHECKS[suite], r[2], strict=True)
            if v is not None
        }
        cases.append(
            {
                "id": r[0],
                "suite": suite,
                "tool": "sqruff",
                "status": r[1],
                "checks": checks,
                "reason": KNOWN.get(r[0], ""),
                "duration_ms": 0,
                "tags": r[3] if len(r) > 3 else [],
            }
        )
    return {
        "sqlfluff_ref": record["sqlfluff_ref"],
        "scope": {
            "suites": sorted(s1.PARITY_SUITES),
            "tools": ["sqruff"],
            "filter": None,
            "shard": None,
        },
        "tools": {"sqruff": record["record"]},
        "known_failures": {"sqruff": {"new_failures": [], "unexpected_passes": []}},
        "cases": cases,
    }


def test_extract_gives_the_committed_cases():
    harness = CASES["harness"]
    got = s1.extract(_report(CASES), harness["commit"], harness["clean"])
    assert s1.text(got) == s1.CASES_FILE.read_text("utf8")


@pytest.mark.parametrize(
    "change, match",
    [
        (lambda r: r["scope"].update(filter="dialects/"), "scope"),
        (lambda r: r["scope"].update(shard="1/2"), "scope"),
        (lambda r: r["scope"].update(tools=["sqruff", "sqlfluff"]), "scope"),
        (lambda r: r.update(parts=[{}]), "merge of shards"),
        (
            lambda r: r["known_failures"]["sqruff"].update(new_failures=["x"]),
            "known-failure check",
        ),
        (lambda r: r.update(sqlfluff_ref="0" * 40), "sqlfluff ref"),
        (
            lambda r: next(c for c in r["cases"] if c["reason"]).update(reason="x"),
            "reasons are not known_failures",
        ),
    ],
)
def test_extract_refuses_a_report_that_does_not_agree(change, match):
    report = _report(CASES)
    change(report)
    with pytest.raises(s1.DataError, match=match):
        s1.extract(report, CASES["harness"]["commit"], True)


def test_extract_refuses_a_checkout_with_changes():
    with pytest.raises(s1.DataError, match="has changes"):
        s1.extract(_report(CASES), CASES["harness"]["commit"], False)


# The tables.


@pytest.mark.parametrize("base", sorted(TOOLS))
def test_the_groups_add_up_to_the_suite_totals_of_the_summary(base):
    tables = OUT["bases"][base]
    want = SUMMARY["results"][TOOLS[base]]["suites"]
    for suite in s1.PARITY_SUITES:
        groups = tables[suite].values()
        assert sum(g["total"] for g in groups) == want[suite]["total"]
        assert sum(g["pass"] for g in groups) == want[suite]["passed"]
        assert sum(g["fail"] for g in groups) == want[suite]["failed"]
        assert sum(g["error"] for g in groups) == want[suite]["error"]
        assert tables["suites"][suite]["total"] == want[suite]["total"]
    for check, n in want["dialects"]["checks"].items():
        assert sum(g["checks"][check]["pass"] for g in tables["dialects"].values()) == n
    assert len(tables["dialects"]) == 28


def test_the_rule_tables_of_sqlfluff_rs_agree_with_the_summary():
    rs = OUT["bases"]["sqlfluffrs"]
    want = SUMMARY["results"]["sqlfluff-rs"]["suites"]["rules"]["checks"]
    for check, n in want.items():
        assert (
            sum(r["checks"].get(check, {}).get("pass", 0) for r in rs["rules"].values())
            == n
        )
    for r in rs["rules"].values():
        assert r["pass"] == r["total"]
        assert all(v["fail"] == v["no_result"] == 0 for v in r["checks"].values())


def test_the_failure_reasons_are_those_of_the_known_failures():
    reasons = OUT["bases"]["sqruff"]["failure_reasons"]
    want: dict[str, Counter] = {}
    for case_id, reason in KNOWN.items():
        prefix = known_failures.reason_prefix(reason)
        want.setdefault(prefix, Counter())[case_id.split("/", 1)[0]] += 1
    assert reasons == {p: dict(c) for p, c in want.items()}
    assert sum(sum(v.values()) for v in reasons.values()) == len(KNOWN) == 1131
    assert OUT["bases"]["sqlfluffrs"]["failure_reasons"] == {}


def test_the_record_has_the_ref_versions_commit_and_commands():
    pin = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD:third_party/sqlfluff"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert OUT["sqlfluff_ref"] == CASES["sqlfluff_ref"] == pin
    assert OUT["bases"]["sqruff"]["version"] == "0.41.0"
    assert OUT["bases"]["sqlfluffrs"]["version"] == "4.4.0"
    assert OUT["bases"]["sqlfluffrs"]["record"]["preflight"]["sqlfluffrs"] == "4.4.0"
    assert re.fullmatch(r"[0-9a-f]{40}", OUT["harness"]["commit"])
    assert OUT["harness"]["clean"] is True
    assert set(OUT["commands"]) == {"run", "extract", "build"}
    assert OUT["bases"]["new-parser"]["data"] is None


def test_the_s3_status_file_has_the_t2_numbers():
    # The S3 track writes only status/S3.md (PROCESS.md, "Tracks").
    status = (REPO_ROOT / "status" / "S3.md").read_text("utf8")
    assert (
        "| T2 | S1 results by base, per suite and per dialect | Merged (PR #23) |"
        in status
    )
    status = " ".join(status.split())
    sq = OUT["bases"]["sqruff"]
    exact = {
        d: (r["checks"]["exact"]["pass"], r["total"]) for d, r in sq["dialects"].items()
    }
    assert exact["oracle"] == (0, 103) and exact["soql"] == (0, 3)
    assert exact["flink"] == (17, 17)
    assert (
        "from 0 of 103 (oracle) and 0 of 3 (soql: no dialect) to 17 of 17 (flink)"
        in status
    )
    full = sum(r["pass"] == r["total"] for r in sq["rules"].values())
    assert f"{full} of {len(sq['rules'])} rule groups pass all their cases" in status
    assert f"harness commit `{OUT['harness']['commit'][:7]}`" in status


def test_the_decision_record_gives_the_true_source_of_the_c1_data():
    record = (REPO_ROOT / "docs" / "decisions" / "s3-base.md").read_text("utf8")
    out = f"`{s1.OUT_FILE.relative_to(REPO_ROOT)}`"
    # The C1 row of the Method table (the Criteria table also has a C1 row).
    row = next(r for r in record.splitlines() if r.startswith("| C1 |") and out in r)
    cells = [c.strip() for c in row.strip("|").split("|")]
    data, file, task, kind = cells[1:]
    assert file == out and task == "T2"
    assert f"`{s1.CASES_FILE.relative_to(REPO_ROOT)}`" in data
    assert "`results/s1/summary.json`" in data and "pinned fixtures" in data
    assert "run reports" not in data
    assert OUT["bases"]["new-parser"]["data"] is None
    assert (
        kind == "Measurement (options 1, 2); no data (option 3; T9 gives the estimate)"
    )


# Lint. CI and scripts/verify run ruff only on the Core paths; the S3 track
# owns scripts/s3, so this test runs the same ruff commands on it.


@pytest.mark.parametrize("command", [["check"], ["format", "--check"]])
def test_ruff_passes_on_scripts_s3(command):
    result = subprocess.run(
        [sys.executable, "-m", "ruff", *command, "scripts/s3"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
