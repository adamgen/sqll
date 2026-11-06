"""S3b C4: the core design record docs/decisions/s3b-core.md and its data.

results/S3b/C4-record.json is the output of scripts/s3b/core_design.py
record: each number of the record and its source. The tests make it again
from the committed files, check the tree measurement
results/S3b/C4-tree-cost.json against the S2 input definitions and its own
sums, and check that each number of the record is a value of the data
file. The measurement itself needs cargo: "core_design.py measure --check"
makes it again (the command is in the record)."""

import copy
import importlib.util
import json
import re

import pytest
from conftest import ci_module

from sqll_harness.bench import definitions
from sqll_harness.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "s3b_core_design", REPO_ROOT / "scripts" / "s3b" / "core_design.py"
)
cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cd)

RECORD = (REPO_ROOT / "docs" / "decisions" / "s3b-core.md").read_text("utf8")
DATA = json.loads(cd.RECORD_FILE.read_text("utf8"))
VALUES = DATA["values"]
TREE = json.loads(cd.MEASURE_FILE.read_text("utf8"))
STATUS = (REPO_ROOT / "status" / "S3b.md").read_text("utf8")
QUESTIONS = {
    "Q1": "Tree type",
    "Q2": "Source map",
    "Q3": "Lexer to parser to tree",
    "Q4": "Rule and fix interface",
    "Q5": "Ownership",
    "Q6": "CLI and config",
    "Q7": "Table format",
}
# The packages of the S3b plan and their owner tracks.
PACKAGES = {
    "sqll_types": "core",
    "sqll_lexer": "core",
    "sqll_tree": "core",
    "sqll_source": "core",
    "sqll_syntax": "core",
    "sqll_config": "core",
    "sqll_lint": "core",
    "sqll_schema": "core",
    "sqll_interfaces": "core",
    "sqll": "core",
    "sqll_base_tests": "core",
    "sqll_parser": "S4",
    "sqll_dialects": "S4",
    "sqll_rules": "S5",
    "sqll_templater": "S6",
    "sqll_cli": "S7-sqll",
    "sqll_codegen": "S8",
    "sqll_plpgsql": "S10",
}


def section(title: str) -> str:
    return RECORD.split(f"\n### {title}\n", 1)[1].split("\n#", 1)[0]


def numbers(text: str) -> list[str]:
    """Return the numbers of the text outside code, link targets, list
    numbers, versions, dates, and ids (G3.6, C4, Q1, CP01)."""
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"(?m)^\s*\d+\. ", " ", text)
    text = re.sub(r"\b\d+\.\d+\.\d+\b", " ", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)
    text = re.sub(r"\b[A-Z][A-Za-z]*\d+[a-z]?(?:\.\d+)*\b", " ", text)
    return re.findall(r"(?<![\w.-])\d+(?:\.\d+)?%?", text)


# The record data.


def test_the_record_data_is_the_output_of_the_committed_files():
    assert cd.main(["record", "--check"]) == 0


def test_a_changed_value_fails_the_check(tmp_path, monkeypatch):
    changed = copy.deepcopy(DATA)
    changed["values"]["arena_tests"]["value"] = 7
    path = tmp_path / "record.json"
    path.write_text(json.dumps(changed), encoding="utf8")
    monkeypatch.setattr(cd, "RECORD_FILE", path)
    assert cd.main(["record", "--check"]) == 1


def test_each_value_has_a_source():
    assert VALUES
    for vid, value in VALUES.items():
        assert value["kind"] in ("copied", "derived"), vid
        if value["kind"] == "copied":
            assert (REPO_ROOT / value["from"]).is_file(), vid
            assert value["key"], vid
        else:
            assert value["formula"], vid
        assert isinstance(value["text"], str) and value["text"], vid


def test_the_table_sha256_is_the_one_in_the_sqll_version():
    summary = json.loads(
        (REPO_ROOT / "results" / "s1" / "summary.json").read_text("utf8")
    )
    version = summary["tools"]["sqll"]["version"]
    assert version.endswith("+tables." + VALUES["table_sha256"]["value"])


def test_the_arena_tests_are_tests_of_the_native_base_record():
    assert VALUES["arena_tests"]["value"] == 8
    assert VALUES["native_tests"]["value"] == 162


# The tree measurement.


def test_the_measurement_has_each_s2_parse_input_once():
    defs = definitions.load()
    parse = [b["input"] for b in defs["benchmarks"] if b["command"] == "parse"]
    items = TREE["data"]["items"]
    assert [i["input"] for i in items] == parse
    assert TREE["data"]["inputs"] == len(parse) == 84
    for item in items:
        recorded = defs["inputs"][item["input"]]
        for key in ("sha256", "bytes", "lines"):
            assert item[key] == recorded[key], (item["input"], key)


def test_the_measurement_is_of_clean_committed_crates():
    assert re.fullmatch(r"[0-9a-f]{40}", TREE["commit"])
    assert TREE["crates_clean"] is True
    assert TREE["command"] == f"{cd.COMMAND} measure"


def test_each_tree_is_full_and_typed_from_the_tables():
    data = TREE["data"]
    for item in data["items"]:
        assert item["unparsable"] == 0, item["input"]
        assert item["nodes"] == item["raw"] + item["segment"] + item["meta"]
    assert data["types"]["observed_not_in_tables_or_lexers"] == []
    assert data["types"]["table_strings_and_lexer_names"] < 2**16


def test_the_totals_are_the_sums_of_the_inputs():
    data = TREE["data"]
    items, totals = data["items"], data["totals"]
    for key in cd.COUNT_KEYS:
        assert totals[key] == sum(i[key] for i in items), key
    for key in (*cd.TREE_KEYS, "flat_estimate"):
        for field, total in totals[key].items():
            assert total == sum(i[key][field] for i in items), (key, field)


def test_the_flat_estimate_is_the_formula():
    assert TREE["data"]["flat"] == cd.FLAT
    for item in TREE["data"]["items"]:
        assert item["flat_estimate"] == {
            "blocks": cd.FLAT["blocks"],
            "bytes": cd.flat_bytes(item),
        }


# The record document.


def test_numbers():
    assert numbers("a `x 5` [b](c/9) G3.6 C4 Q1 CP01 4.4.0 7 and 1.25 12%") == [
        "7",
        "1.25",
        "12%",
    ]


def test_each_number_of_the_record_is_a_value_of_the_data_file():
    texts = {v["text"] for v in VALUES.values()}
    found = numbers(RECORD)
    assert found
    assert sorted(set(found) - texts) == []


def test_each_value_is_in_the_record():
    for vid, value in VALUES.items():
        assert value["text"] in RECORD, vid


def test_the_record_is_a_5_minute_read():
    assert len(RECORD.split()) < 1250


def test_the_record_names_its_data_and_commands():
    for word in (
        "results/S3b/C4-record.json",
        "results/S3b/C4-tree-cost.json",
        "scripts/s3b/core_design.py record",
        "scripts/s3b/core_design.py measure",
        "harness/tests/test_s3b_core.py",
    ):
        assert word in RECORD, word


def test_each_question_has_a_decision_and_a_reason():
    headings = re.findall(r"(?m)^### (Q\d)\. (.*)$", RECORD)
    assert headings == list(QUESTIONS.items())
    for qid, title in QUESTIONS.items():
        text = section(f"{qid}. {title}")
        assert "Decision:" in text, qid
        assert "Reason:" in text, qid


def package_rows() -> dict[str, str]:
    rows = re.findall(
        r"(?m)^\| `(sqll\w*)` \| ([\w-]+) \| .+ \|$", section("Q5. Ownership")
    )
    found = dict(rows)
    assert len(found) == len(rows), "a package has two rows"
    return found


def test_the_package_table_gives_an_owner_track_for_each_package():
    tracks = ci_module("ownership").load()
    rows = package_rows()
    assert rows == PACKAGES
    assert set(rows.values()) <= set(tracks)


def test_each_package_of_the_workspace_is_in_the_table():
    cargo = (REPO_ROOT / "Cargo.toml").read_text("utf8")
    members = re.findall(r'"crates/(\w+)"', cargo)
    assert members
    assert set(members) <= set(package_rows())


@pytest.mark.parametrize(
    "word",
    [
        "[docs/decisions/s3b-core.md](../docs/decisions/s3b-core.md)",
    ],
)
def test_the_s3b_status_links_the_record(word):
    assert word in STATUS
