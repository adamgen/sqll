"""S3 T6: speed by base and the distance to the G3 targets.

results/s3/speed-by-base.json is the output of scripts/s3/speed_by_base.py on
the committed S2 baseline and the T5 probe report. Each time is copied from
one of them, or it is an estimate with its formula; the test computes each
estimate again from the inputs."""

import importlib.util
import json
import re
from collections import Counter

import pytest

from sqll_harness.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "speed_by_base", REPO_ROOT / "scripts" / "s3" / "speed_by_base.py"
)
sb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sb)

OUT = json.loads(sb.OUT_FILE.read_text("utf8"))
BASELINE = json.loads(sb.BASELINE_FILE.read_text("utf8"))
PROBE = json.loads(sb.PROBE_FILE.read_text("utf8"))
BASE = {(r["id"], r["tool"]): r for r in BASELINE["results"]}
SESSION = {r["id"]: r for r in PROBE["speed"]["benchmarks"]}
ROWS = OUT["benchmarks"]
ESTIMATES = ("sqlfluffrs", "new-parser-low", "new-parser-high")


def median(bid, tool):
    r = BASE[(bid, tool)]
    return r["stats"]["wall_s"]["median"] if r["status"] == "valid" else None


def entries(base, command=None):
    return [
        (r, r["bases"][base])
        for r in ROWS
        if command is None or r["command"] == command
    ]


# The drift test.


def test_the_committed_output_is_the_output_of_the_committed_inputs():
    assert sb.main(["--check"]) == 0


def test_the_check_fails_on_a_change(tmp_path, monkeypatch):
    out = tmp_path / "out.json"
    out.write_text(sb.OUT_FILE.read_text("utf8").replace('"T6"', '"T7"'), "utf8")
    monkeypatch.setattr(sb, "OUT_FILE", out)
    assert sb.main(["--check"]) == 1


def test_the_inputs_are_the_committed_files():
    assert OUT["inputs"] == {
        "results/s2/baseline.json": sb.sha256_file(sb.BASELINE_FILE),
        "results/s3/sqlfluffrs-probe.json": sb.sha256_file(sb.PROBE_FILE),
    }


def test_a_probe_report_of_another_baseline_fails(tmp_path):
    probe = json.loads(json.dumps(PROBE))
    probe["inputs"]["results/s2/baseline.json"] = "0" * 64
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(probe), "utf8")
    with pytest.raises(sb.DataError, match="committed baseline"):
        sb.make_report(probe_path=path)


def test_another_tool_version_fails(tmp_path):
    probe = json.loads(json.dumps(PROBE))
    probe["speed"]["session"]["tools"]["sqruff"] = "0.42.0"
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(probe), "utf8")
    with pytest.raises(sb.DataError, match="sqruff version"):
        sb.make_report(probe_path=path)


def test_a_missing_probe_benchmark_fails(tmp_path):
    probe = json.loads(json.dumps(PROBE))
    probe["speed"]["benchmarks"] = probe["speed"]["benchmarks"][1:]
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(probe), "utf8")
    with pytest.raises(sb.DataError, match="start and parse benchmarks"):
        sb.make_report(probe_path=path)


def write_json(path, value):
    path.write_text(json.dumps(value), "utf8")
    return path


def copy_probe():
    return json.loads(json.dumps(PROBE))


def probe_row(probe, bid):
    return next(r for r in probe["speed"]["benchmarks"] if r["id"] == bid)


def test_another_sqlfluff_commit_fails(tmp_path):
    probe = copy_probe()
    probe["sqlfluffrs"]["commit"] = "0" * 40
    path = write_json(tmp_path / "probe.json", probe)
    with pytest.raises(sb.DataError, match="pinned sqlfluff commit"):
        sb.make_report(probe_path=path)


def test_a_baseline_that_is_not_correct_fails(tmp_path):
    baseline = json.loads(json.dumps(BASELINE))
    baseline["kind"] = "another-report"
    base_path = write_json(tmp_path / "baseline.json", baseline)
    probe = copy_probe()
    probe["inputs"]["results/s2/baseline.json"] = sb.sha256_file(base_path)
    path = write_json(tmp_path / "probe.json", probe)
    with pytest.raises(sb.DataError, match="baseline is not correct"):
        sb.make_report(baseline_path=base_path, probe_path=path)


def test_a_duplicate_probe_benchmark_fails(tmp_path):
    probe = copy_probe()
    rows = probe["speed"]["benchmarks"]
    rows.append(json.loads(json.dumps(rows[0])))
    path = write_json(tmp_path / "probe.json", probe)
    with pytest.raises(sb.DataError, match="start and parse benchmarks"):
        sb.make_report(probe_path=path)


@pytest.mark.parametrize("setup_s", [0, 10])
def test_a_setup_phase_outside_the_probe_time_fails(tmp_path, setup_s):
    probe = copy_probe()
    probe_row(probe, "parse/ansi/large")["probe_phases"]["setup_s"] = setup_s
    path = write_json(tmp_path / "probe.json", probe)
    with pytest.raises(sb.DataError, match="setup phase"):
        sb.make_report(probe_path=path)


@pytest.mark.parametrize("other", ["sqruff", "sqlfluff"])
def test_a_ratio_that_is_not_the_ratio_of_the_medians_fails(tmp_path, other):
    probe = copy_probe()
    probe_row(probe, "parse/ansi/large")[f"probe_over_{other}"] = 0.5
    path = write_json(tmp_path / "probe.json", probe)
    with pytest.raises(sb.DataError, match=f"probe_over_{other}"):
        sb.make_report(probe_path=path)


def test_a_probe_result_that_is_not_valid_fails_its_comparisons(tmp_path):
    probe = copy_probe()
    for bid in ("parse/ansi/large", "start/ansi"):
        row = probe_row(probe, bid)
        row["status"][sb.PROBE] = "invalid"
        row[sb.PROBE] = row["probe_over_sqruff"] = row["probe_over_sqlfluff"] = None
    path = write_json(tmp_path / "probe.json", probe)
    out = sb.make_report(probe_path=path)
    by = {r["id"]: r["bases"] for r in out["benchmarks"]}
    # fix/ansi/large: sqruff is not valid, thus G3.5 has no pair.
    want = {
        "start/ansi": ("not_met", "not_met"),
        "parse/ansi/large": ("not_met", "not_met"),
        "lint/ansi/large": ("not_met", "not_met"),
        "fix/ansi/large": ("not_met", "skipped"),
    }
    for name in ESTIMATES:
        for bid, outcomes in want.items():
            e = by[bid][name]
            assert e["kind"] == "not_valid" and e["from"] == "session", (bid, name)
            assert e["status"] == "invalid" and e["time_s"] is None
            assert (e["g3_4"], e["g3_5"]) == outcomes, (bid, name)
        assert by["lint/ansi/medium"][name]["kind"] == "estimate"
        sp = out["bases"][name]["lex_parse_speedup"]
        assert sp["start"]["not_valid"] == ["start/ansi"]
        assert sp["parse"]["not_valid"] == ["parse/ansi/large"]
        s = out["bases"][name]["summary"]["all"]
        assert s["kinds"]["not_valid"] == 4


def test_a_reason_with_no_class_fails():
    with pytest.raises(sb.DataError, match="no class"):
        sb.reason_class("invalid", "warmup run: a new failure")
    assert sb.reason_class("unsupported", "unsupported: dialect soql") == "unsupported"
    assert sb.reason_class("invalid", "x: the tool crashed (panic): y") == "panic"


# Each number is copied from a committed file or is an estimate.


def test_each_value_names_its_source_or_its_formula():
    for row in ROWS:
        assert set(row["bases"]) == set(sb.BASES)
        for name, e in row["bases"].items():
            assert e["ref_from"] in sb.SOURCES, (row["id"], name)
            if e["kind"] in ("measured", "not_valid"):
                assert e["from"] in sb.SOURCES and "formula" not in e
            else:
                assert e["kind"] in ("estimate", "no_estimate")
                assert e["formula"] in sb.FORMULAS and "from" not in e
            if e["kind"] in ("not_valid", "no_estimate"):
                assert e["time_s"] is None and e["over_sqruff"] is None
    for source in sb.SOURCES.values():
        assert (REPO_ROOT / source["path"]).is_file()


def test_the_sqruff_base_is_copied_from_the_baseline():
    for row, e in entries("sqruff"):
        res = BASE[(row["id"], "sqruff")]
        assert e["from"] == e["ref_from"] == "baseline"
        assert e["sqlfluff_s"] == median(row["id"], "sqlfluff")
        if res["status"] == "valid":
            assert e["kind"] == "measured"
            assert e["time_s"] == e["sqruff_s"] == median(row["id"], "sqruff")
            assert e["over_sqlfluff"] == res["ratio"]["wall"]
            assert e["over_sqruff"] == 1.0
        else:
            assert e["kind"] == "not_valid" and e["status"] == res["status"]
            assert (e["g3_4"], e["g3_5"]) == ("not_met", "skipped")


def test_start_and_parse_of_sqlfluffrs_are_copied_from_the_probe_report():
    for command in sb.MEASURED_BY_PROBE:
        for row, e in entries("sqlfluffrs", command):
            s = SESSION[row["id"]]
            assert e["kind"] == "measured" and e["from"] == "session"
            assert e["time_s"] == s[sb.PROBE]["median_s"]
            assert e["sqlfluff_s"] == s["sqlfluff"]["median_s"]
            assert e["sqruff_s"] == (s["sqruff"] or {}).get("median_s")
            assert e["over_sqlfluff"] == s["probe_over_sqlfluff"]
            assert e["over_sqruff"] == s["probe_over_sqruff"]


def test_the_option_3_bounds_of_start_and_parse():
    for command in sb.MEASURED_BY_PROBE:
        for row, e in entries("new-parser-high", command):
            assert e["formula"] == "option3_high"
            assert e["time_s"] == SESSION[row["id"]][sb.PROBE]["median_s"]
        for row, e in entries("new-parser-low", command):
            s = SESSION[row["id"]]
            want = s[sb.PROBE]["median_s"] - s["probe_phases"]["setup_s"]
            assert e["formula"] == "option3_low"
            assert e["time_s"] == pytest.approx(want, abs=1e-6)
            assert 0 < e["time_s"] < s[sb.PROBE]["median_s"]


@pytest.mark.parametrize("name", ESTIMATES)
def test_each_lint_and_fix_estimate_is_its_formula(name):
    n = 0
    for command in ("lint", "fix"):
        for row, e in entries(name, command):
            rest = row["id"].split("/", 1)[1]
            tq, pq = median(row["id"], "sqruff"), median(f"parse/{rest}", "sqruff")
            assert e["sqlfluff_s"] == median(row["id"], "sqlfluff")
            assert e["sqruff_s"] == tq and e["ref_from"] == "baseline"
            assert e["formula"] == "rule_time"
            if tq is None or pq is None:
                assert e["kind"] == "no_estimate"
                continue
            parse = row_of(f"parse/{rest}")["bases"][name]
            pq_session = SESSION[f"parse/{rest}"]["sqruff"]["median_s"]
            want = tq + pq * (parse["time_s"] / pq_session - 1)
            assert e["kind"] == "estimate"
            assert e["time_s"] == pytest.approx(want, abs=2e-6)
            assert e["over_sqruff"] == pytest.approx(want / tq, abs=1e-4)
            assert e["over_sqlfluff"] == pytest.approx(want / e["sqlfluff_s"], abs=1e-4)
            n += 1
    assert n == 55 + 53


def row_of(bid):
    return next(r for r in ROWS if r["id"] == bid)


# The G3 outcomes and the pairs.


def test_the_outcome_of_each_entry():
    for row in ROWS:
        for e in row["bases"].values():
            if e["sqlfluff_s"] is None:
                assert e["g3_4"] == "skipped"
            elif e["kind"] == "not_valid":
                assert e["g3_4"] == "not_met"
            elif e["over_sqlfluff"] is None:
                assert e["g3_4"] == "unknown"
            else:
                assert e["g3_4"] == ("met" if e["over_sqlfluff"] < 1 else "not_met")
            # A pair only if the other tool is valid (harness/bench.md).
            if e["sqruff_s"] is None:
                assert e["g3_5"] == "skipped"
            elif e["kind"] == "not_valid":
                assert e["g3_5"] == "not_met"
            else:
                assert e["over_sqruff"] is not None
                assert e["g3_5"] == ("met" if e["over_sqruff"] <= 1 else "not_met")


@pytest.mark.parametrize("name", list(sb.BASES))
def test_the_summary_counts_and_totals_use_only_pairs(name):
    summary = OUT["bases"][name]["summary"]
    for command in (*sb.COMMANDS, "all"):
        sel = [e for _, e in entries(name, None if command == "all" else command)]
        s = summary[command]
        assert s["benchmarks"] == len(sel)
        for key, field in (("g3_4", "g3_4"), ("g3_5_each", "g3_5")):
            n = Counter(e[field] for e in sel)
            assert {o: s[key][o] for o in sb.OUTCOMES} == {o: n[o] for o in sb.OUTCOMES}
            assert s[key]["all_met"] == (n["not_met"] == 0 and n["unknown"] == 0)
        pairs = [e for e in sel if e["over_sqruff"] is not None]
        assert all(e["sqruff_s"] is not None and e["time_s"] for e in pairs)
        total = s["g3_5_total"]
        assert total["pairs"] == len(pairs)
        if command == "all":
            tq = {r["id"]: r["bases"]["sqruff"]["time_s"] for r in ROWS}
            ids = [r["id"] for r, e in entries(name) if e["over_sqruff"] is not None]
            want_q = sum(tq[i] for i in ids)
            want_b = sum(row_of(i)["bases"][name]["over_sqruff"] * tq[i] for i in ids)
        else:
            want_q = sum(e["sqruff_s"] for e in pairs)
            want_b = sum(e["time_s"] for e in pairs)
        assert total["sum_sqruff_s"] == pytest.approx(want_q, abs=1e-5)
        assert total["sum_base_s"] == pytest.approx(want_b, abs=1e-5)
        assert total["met"] == (total["ratio"] < 1)


def test_the_g3_counts():
    sq = OUT["bases"]["sqruff"]["summary"]["all"]
    assert sq["g3_4"]["not_met"] == OUT["bases"]["sqruff"]["not_valid"]["count"] == 64
    assert sq["g3_5_total"]["ratio"] == 1.0 and sq["g3_5_total"]["met"] is False
    for name in ESTIMATES:
        s = OUT["bases"][name]["summary"]
        assert s["all"]["g3_4"]["not_met"] == 0
        assert s["all"]["g3_4"]["unknown"] == 29 + 31
        assert s["all"]["g3_5_each"]["skipped"] == 1 + 3 + 29 + 31


@pytest.mark.parametrize("name", ESTIMATES)
def test_g3_5_of_lint_and_fix_follows_parse_on_the_same_input(name):
    for command in ("lint", "fix"):
        for row, e in entries(name, command):
            if e["kind"] != "estimate":
                continue
            parse = row_of("parse/" + row["id"].split("/", 1)[1])["bases"][name]
            assert e["g3_5"] == parse["g3_5"], row["id"]


def test_the_sqruff_results_that_are_not_valid_are_listed():
    nv = OUT["bases"]["sqruff"]["not_valid"]
    want = sorted(
        (r["id"], r["status"])
        for r in BASELINE["results"]
        if r["tool"] == "sqruff" and r["status"] != "valid"
    )
    assert [(i["id"], i["status"]) for i in nv["results"]] == want
    classes = Counter(i["class"] for i in nv["results"])
    assert classes == {"rule_codes": 46, "unsupported": 10, "panic": 7, "timeout": 1}
    by = {c: sum(v.values()) for c, v in nv["by_class"].items()}
    assert by == dict(classes)


@pytest.mark.parametrize("name", ESTIMATES)
@pytest.mark.parametrize("command", sb.MEASURED_BY_PROBE)
def test_the_speedup_of_each_benchmark_that_is_slower(name, command):
    sp = OUT["bases"][name]["lex_parse_speedup"][command]
    factors, unreachable, slower = [], [], 0
    for row, e in entries(name, command):
        if e["g3_5"] != "not_met":
            continue
        slower += 1
        s = SESSION[row["id"]]
        ph = s["probe_phases"]
        lp = ph["lex_s"] + ph["parse_s"]
        t = s[sb.PROBE]["median_s"]
        if name == "new-parser-low":
            t -= ph["setup_s"]
        room = s["sqruff"]["median_s"] - (t - lp)
        if room <= 0:
            unreachable.append(row["id"])
        else:
            factors.append(lp / room)
    assert sp["needed"] == slower
    assert sp["unreachable"] == unreachable and sp["not_valid"] == []
    if factors:
        assert sp["max_factor"] == pytest.approx(max(factors), abs=1e-4)
        assert sp["median_factor"] == pytest.approx(median_of(factors), abs=1e-4)
    else:
        assert sp["max_factor"] is sp["median_factor"] is None


def median_of(values):
    v = sorted(values)
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2


# The status file and the decision record.


def test_the_s3_status_file_has_t6_and_its_numbers():
    status = (REPO_ROOT / "status" / "S3.md").read_text("utf8")
    row = next(line for line in status.splitlines() if line.startswith("| T6 |"))
    assert "Not started" not in row
    assert "results/s3/speed-by-base.json" in status
    assert "scripts/s3/speed_by_base.py" in status
    labels = {
        "sqruff": "1 sqruff",
        "sqlfluffrs": "2 sqlfluffrs",
        "new-parser-low": "3 low",
        "new-parser-high": "3 high",
    }
    for name, label in labels.items():
        s = OUT["bases"][name]["summary"]
        a = s["all"]
        cells = (
            f"| {label} | {a['g3_4']['met']} | {a['g3_4']['not_met']} | "
            f"{a['g3_4']['unknown']} | {a['g3_5_each']['not_met']} of "
            f"{a['g3_5_each']['met'] + a['g3_5_each']['not_met']} |"
        )
        assert cells in status.splitlines(), name
        ratios = " | ".join(
            f"{s[c]['g3_5_total']['ratio']:.3f}" for c in (*sb.COMMANDS, "all")
        )
        assert re.search(rf"\| {re.escape(label)} \| {re.escape(ratios)} \|", status)


def test_the_decision_record_gives_the_c5_source():
    record = (REPO_ROOT / "docs" / "decisions" / "s3-base.md").read_text("utf8")
    row = next(
        r for r in record.splitlines() if r.startswith("| C5 |") and "| T6 |" in r
    )
    assert "`results/s3/speed-by-base.json`" in row
    assert "scripts/s3/speed_by_base.py" in row
    assert "`results/s2/baseline.json`" in row
    assert "`results/s3/sqlfluffrs-probe.json`" in row
    method = " ".join(record.split("## Method", 1)[1].split("| Criterion")[0].split())
    # Only the estimates take ratios inside each session; unscaled does not.
    assert "(formulas `rule_time` and `total_all`) take only ratios inside" in method
    assert "(formula `unscaled`) does not" in method


def test_the_status_text_numbers_are_those_of_the_output():
    status = " ".join((REPO_ROOT / "status" / "S3.md").read_text("utf8").split())
    nv = OUT["bases"]["sqruff"]["not_valid"]["results"]
    n = Counter(i["class"] for i in nv)
    assert (
        f"{len(nv)} results are not valid, thus they fail G3.4: rule codes that are "
        f"not those of sqlfluff {n['rule_codes']}, unsupported (soql) "
        f"{n['unsupported']}, panic {n['panic']}, timeout {n['timeout']}." in status
    )
    sens = {
        name: [
            OUT["bases"][name]["sensitivity"][c]["g3_5_total"]["ratio"]
            for c in ("lint", "fix")
        ]
        for name in ("sqlfluffrs", "new-parser-low")
    }
    two, low = sens["sqlfluffrs"], sens["new-parser-low"]
    assert (
        f"totals of {two[0]:.4f} and {two[1]:.4f} (option 2), {low[0]:.4f} and "
        f"{low[1]:.4f} (option 3 low)." in status
    )
    sp = {
        name: OUT["bases"][name]["lex_parse_speedup"]["parse"]
        for name in ("sqlfluffrs", "new-parser-low")
    }
    two, low = sp["sqlfluffrs"], sp["new-parser-low"]
    assert two["unreachable"] == low["unreachable"] == []
    assert (
        f"a median factor of {two['median_factor']:.2f} and at most "
        f"{two['max_factor']:.2f} (option 2), or {low['median_factor']:.2f} and "
        f"{low['max_factor']:.2f} (option 3 low)." in status
    )
