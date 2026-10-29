"""S3 T9: the data of the decision record.

results/s3/decision-data.json is the output of scripts/s3/decision_data.py
on the S1 summary and the T2 to T8 outputs. The tests read each copied value
again from its file and key, compute the derived values again, and check
that docs/decisions/s3-base.md has the tables of the file and no number
that is not a value of the file."""

import copy
import importlib.util
import json
import re

import pytest

from sqll_harness.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "decision_data", REPO_ROOT / "scripts" / "s3" / "decision_data.py"
)
dd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dd)

OUT = json.loads(dd.OUT_FILE.read_text("utf8"))
VALUES = OUT["values"]
RECORD = (REPO_ROOT / "docs" / "decisions" / "s3-base.md").read_text("utf8")
INPUTS = {
    rel: json.loads((REPO_ROOT / rel).read_text("utf8")) for rel in dd.INPUTS.values()
}


def v(vid):
    return VALUES[vid]["value"]


def section(title: str) -> str:
    return RECORD.split(f"\n## {title}\n", 1)[1].split("\n## ", 1)[0]


# The drift test and the inputs.


def test_the_committed_output_is_the_output_of_the_committed_inputs():
    assert dd.main(["--check"]) == 0


def test_the_check_fails_on_a_change(tmp_path, monkeypatch):
    out = tmp_path / "out.json"
    out.write_text(dd.OUT_FILE.read_text("utf8").replace('"T9"', '"T8"'), "utf8")
    monkeypatch.setattr(dd, "OUT_FILE", out)
    assert dd.main(["--check"]) == 1


def test_the_inputs_are_the_committed_files():
    assert OUT["inputs"] == {
        rel: dd.sha256_file(REPO_ROOT / rel) for rel in dd.INPUTS.values()
    }


def _paths(tmp_path, name, change):
    paths = {k: REPO_ROOT / rel for k, rel in dd.INPUTS.items()}
    doc = copy.deepcopy(INPUTS[dd.INPUTS[name]])
    change(doc)
    paths[name] = tmp_path / f"{name}.json"
    paths[name].write_text(json.dumps(doc), "utf8")
    return paths


def test_a_missing_key_fails(tmp_path):
    paths = _paths(tmp_path, "t3", lambda d: d["groups"].pop("cases_with_a_unique_fix"))
    with pytest.raises(dd.DataError, match="no key 'groups.cases_with_a_unique_fix'"):
        dd.make_report(paths)


def test_another_native_tree_count_than_s1_fails(tmp_path):
    def change(d):
        d["fixtures"]["total"]["cases"] -= 1

    with pytest.raises(dd.DataError, match="T5: another dialect case count"):
        dd.make_report(_paths(tmp_path, "t5", change))


def test_another_rule_failure_count_than_t2_fails(tmp_path):
    def change(d):
        d["scope"]["failures"]["rules"] += 1

    with pytest.raises(dd.DataError, match="T4"):
        dd.make_report(_paths(tmp_path, "t4", change))


def test_another_sqruff_rule_count_in_t7_fails(tmp_path):
    def change(d):
        d["bases"]["sqruff"]["structure"]["values"]["rule_files"] += 1

    with pytest.raises(dd.DataError, match="another sqruff rule count"):
        dd.make_report(_paths(tmp_path, "t7", change))


def test_a_dependency_that_is_not_permissive_fails(tmp_path):
    def change(d):
        by = d["bases"]["sqlfluffrs"]["dependencies"]["standalone"]["by_class"]
        by["permissive"] -= 1
        by["weak_copyleft"] += 1

    with pytest.raises(dd.DataError, match="not permissive"):
        dd.make_report(_paths(tmp_path, "t7", change))


# Each value names its source; the tests read it again.


def test_each_value_has_a_kind_and_a_source():
    for vid, entry in VALUES.items():
        assert entry["kind"] in ("copied", "derived", "estimate"), vid
        assert isinstance(entry["text"], str) and entry["text"], vid
        if entry["kind"] == "copied":
            assert entry["from"] in dd.INPUTS.values(), vid
            assert entry["key"], vid
        else:
            assert entry["formula"], vid
        if entry["kind"] == "estimate":
            assert entry["reason"], vid


def test_each_copied_value_is_the_value_of_its_key():
    for vid, entry in VALUES.items():
        if entry["kind"] == "copied":
            assert dd.get(INPUTS[entry["from"]], entry["key"]) == entry["value"], vid


def test_the_text_of_each_ratio_and_share():
    for vid, entry in VALUES.items():
        if vid.endswith(".total") and vid.startswith("t6."):
            assert entry["text"] == f"{entry['value']:.3f}", vid
        if vid.endswith(".share") and vid.startswith("t3."):
            assert entry["text"] == f"{100 * entry['value']:.1f}%", vid


def test_the_derived_rule_codes():
    t2, t4 = (
        INPUTS["results/s3/s1-by-base.json"],
        INPUTS["results/s3/sqruff-rule-diffs.json"],
    )
    codes = set()
    for key in t2["bases"]["sqruff"]["rules"]:
        codes.update(key.split(","))
    sqruff = {r["code"] for r in t4["coupling"]["rules"]}
    assert v("t2.rule_codes") == len(codes)
    assert v("sqruff.rules_missing_names") == sorted(codes - sqruff)
    assert v("sqruff.rules_missing") == len(codes) - len(sqruff)
    rs = INPUTS["results/s3/license-size.json"]["bases"]["sqlfluffrs"]["structure"]
    assert v("sqlfluffrs.rules_in_python") == len(codes) - len(
        rs["values"]["rule_modules"]
    )


def test_the_derived_sqruff_dialect_values():
    dialects = INPUTS["results/s3/s1-by-base.json"]["bases"]["sqruff"]["dialects"]
    full = [
        k for k, d in dialects.items() if d["checks"]["exact"]["pass"] == d["total"]
    ]
    assert v("t2.sqruff.dialects_all_exact") == len(full)
    worst = dialects[v("t2.sqruff.worst.name")]
    share = worst["checks"]["exact"]["pass"] / worst["total"]
    assert all(
        d["checks"]["exact"]["pass"] / d["total"] >= share for d in dialects.values()
    )


def test_the_derived_cli_values():
    s7 = INPUTS["results/s3/capabilities.json"]["S7"]
    shared = [
        c["command"]
        for c in s7["commands"]
        if c["sqlfluff"]["value"] and c["sqruff"]["value"]
    ]
    assert v("t8.commands.sqruff") == len(shared)
    assert v("t8.options.sqlfluff") == sum(
        s7["options"][c]["value"]["sqlfluff"] for c in shared
    )
    assert v("t8.options.sqruff") == sum(
        len(s7["options"][c]["value"]["both"]) for c in shared
    )
    assert v("t8.keys.missing") == v("t8.keys.sqlfluff") - v("t8.keys.sqruff")


def test_the_rule_layer_estimate():
    lib = INPUTS["results/s3/license-size.json"]["bases"]["sqruff"]["size"]["crates"][
        "sqruff-lib"
    ]
    assert VALUES["sqruff.rule_layer_lines"]["kind"] == "estimate"
    assert v("sqruff.rule_layer_lines") == (
        lib["hand_written"]["lines"] - lib["hand_written_src_by_dir"]["src/templaters"]
    )


# The decision record.


def test_the_record_has_each_table_of_the_data_file():
    lines = RECORD.splitlines()
    for name, table in OUT["tables"].items():
        assert table["markdown"] == dd.render(table), name
        start = lines.index(table["markdown"][0])
        assert lines[start : start + len(table["markdown"])] == table["markdown"], name


def numbers(text: str) -> list[str]:
    """Return the numbers of the text outside code, link targets, list
    markers, versions, dates, and ids such as G3.5, T5, or CP01."""
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"(?m)^\s*\d+\. ", " ", text)
    text = re.sub(r"CONSTITUTION \d+\.\d+", " ", text)
    text = re.sub(r"\b\d+\.\d+\.\d+\b", " ", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)
    text = re.sub(r"\b[A-Z][A-Za-z]*\d+(?:\.\d+)*\b", " ", text)
    text = re.sub(r"\bApache-2\.0\b", " ", text)
    return re.findall(r"(?<![\w.-])\d+(?:\.\d+)?%?", text)


def test_numbers():
    assert numbers("a `x 5` [b](c/9) G3.5 T5 CP01 4.4.0 Apache-2.0 7 and 1.25") == [
        "7",
        "1.25",
    ]
    assert numbers("1. item 3\n2. item") == ["3"]
    assert numbers("on 2026-10-29 and 2026 and 10-29") == ["2026", "10"]


def test_each_number_of_the_record_is_a_value_of_the_data_file():
    texts = {e["text"] for e in VALUES.values()}
    found = numbers(RECORD)
    assert len(found) > 200
    assert sorted({n for n in found if n not in texts}) == []


def test_the_record_names_the_data_file_and_the_c8_source():
    assert "[`results/s3/decision-data.json`](../../results/s3/decision-data.json)" in (
        RECORD
    )
    row = next(
        r for r in RECORD.splitlines() if r.startswith("| C8 |") and "| T9 |" in r
    )
    assert "`results/s3/decision-data.json`" in row
    assert "`scripts/s3/decision_data.py`" in row
    assert "estimates" in row
    assert "T9 adds" not in RECORD


def test_option_3_and_the_work_cells_are_labelled_as_estimates():
    license_row = next(r for r in OUT["tables"]["license"]["rows"] if r[0][0] == "3")
    assert "(estimate)" in license_row[2] and "(estimate)" in license_row[3]
    cap = OUT["tables"]["capabilities"]
    col = cap["columns"].index("3 new parser")
    for row in cap["rows"]:
        # A cell with no capability states a fact: option 3 has no code.
        if row[col] not in ("no CLI", "no config reader", "no"):
            assert "(estimate)" in row[col], row
    work = section("Work estimates (C8)")
    assert work.lstrip().startswith("All cells are estimates.")
    speed = {r[0]: r[-1] for r in OUT["tables"]["speed"]["rows"]}
    assert speed["1 sqruff"] == "measured"
    assert "estimate" in speed["2 sqlfluffrs"]
    assert speed["3 low"] == speed["3 high"] == "estimate"


def test_the_record_has_one_recommendation_and_its_risks():
    rec = section("Recommendation")
    assert re.findall(r"\*\*Option (\d)", rec) == ["2"]
    for title in ("Reasons", "Main risks", "Data that would change the recommendation"):
        assert section(title).strip(), title


def test_the_record_has_the_decision_of_the_human_owner():
    assert (
        "\nStatus: decided. The human owner chose option 2 (sqlfluffrs) on"
        " 2026-10-29.\n"
    ) in RECORD
    decision = section("Decision")
    assert "The human owner chose option 2, sqlfluffrs, on 2026-10-29." in decision
    start = "The S3 track starts phase B (the sqll binary) with the parse speed work"
    assert start in decision
    assert '"Data that would change the recommendation"' in decision
    assert "human owner decides" in decision
    assert "chooses the base" not in RECORD


def test_the_premises_of_the_reasons_hold_in_the_data():
    # Option 2 has all trees natively; option 1 does not, and its mismatches
    # are not systematic: the top 50 groups cover less than half of the cases.
    assert v("t5.native.exact") == v("t5.native.cases") == v("s1.sqlfluff.exact")
    assert v("t2.sqruff.exact") < v("t5.native.cases")
    assert v("t3.top50.share") < 0.5
    # Most sqruff rules see a changed tree (estimate).
    assert v("t4.rules_changed") / v("t4.rules") > 0.9
    # The option 3 low bound is faster than option 2, the high bound is equal.
    for c in dd.COMMANDS:
        low, two = v(f"t6.new-parser-low.{c}.total"), v(f"t6.sqlfluffrs.{c}.total")
        assert low <= two
        assert v(f"t6.new-parser-high.{c}.total") == two
    limits = INPUTS["results/s3/speed-by-base.json"]["limits"]
    assert "The low bound of option 3 needs a change that option 2 can also make." in (
        limits
    )
    # No base meets G3.5 on the total yet.
    assert all(v(f"t6.{b}.all.total") >= 1 for b in dd.SPEED_BASES)
    assert v("t7.sqlfluffrs.hand") < v("t7.sqruff.hand")


def test_the_record_is_short():
    prose = [line for line in RECORD.splitlines() if not line.startswith("|")]
    words = len(" ".join(prose).split())
    assert 1000 <= words <= 1800, words


# The status files.


def test_status_says_the_human_owner_chose_sqlfluffrs():
    # The phase B state (test_s3_status.py) keeps the decision and its record.
    index = (REPO_ROOT / "STATUS.md").read_text("utf8")
    (row,) = [line for line in index.splitlines() if line.startswith("| S3 |")]
    assert "the base is sqlfluffrs (human owner, 2026-10-29)" in row
    record = "[docs/decisions/s3-base.md](docs/decisions/s3-base.md)"
    assert f"Decision record: {record}" in row
    status = (REPO_ROOT / "status" / "S3.md").read_text("utf8")
    assert "the base is sqlfluffrs (human owner, 2026-10-29)" in status
    assert "[docs/decisions/s3-base.md](../docs/decisions/s3-base.md)" in status
    assert "awaiting" not in status
    assert "in work" not in status
    tasks = status.split("## S3 phase A tasks", 1)[1].split("\n## ", 1)[0]
    rows = {
        line.split("|")[1].strip(): line.split("|")[3].strip()
        for line in tasks.splitlines()
        if re.match(r"\| T\d \|", line)
    }
    assert sorted(rows) == [f"T{i}" for i in range(1, 10)]
    for task, state in rows.items():
        assert re.fullmatch(r"Merged \(PR #\d+\)", state), (task, state)
    assert rows["T9"] == "Merged (PR #42)"
    assert "results/s3/decision-data.json" in status
    assert "scripts/s3/decision_data.py" in status
