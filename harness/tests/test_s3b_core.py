"""S3b C4: the core design record docs/decisions/s3b-core.md and its data.

results/S3b/C4-record.json is the output of scripts/s3b/core_design.py
record: each number of the record and its source. The tests make it again
from the committed files, check the tree measurement
results/S3b/C4-tree-cost.json against the S2 input definitions and its own
sums, and check that each number of the record is in a claim (a sentence
of the data file) and each claim is in the record. The measurement itself
needs cargo: "core_design.py measure --check" makes it again (the command
is in the record)."""

import copy
import importlib.util
import json
import re
import string

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


def test_the_kinds_are_the_sum_of_the_variants_and_fit_in_a_u16():
    kinds = TREE["data"]["kinds"]
    assert kinds["distinct"] == sum(kinds["by_variant"].values())
    assert kinds["distinct"] < kinds["u16_limit"] == 2**16
    assert 0 < kinds["type_names_with_more_than_one_kind"] < kinds["type_names"]
    assert kinds["type_names"] < kinds["distinct"]


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
    text = "a `x 5` [b](c/9) G3.6 C4 Q1 CP01 4.4.0 7 and 1.25 12%"
    assert cd.numbers(text) == ["7", "1.25", "12%"]


def test_each_claim_is_in_the_record_and_each_number_is_in_a_claim():
    assert cd.numbers(RECORD)
    assert cd.doc_problems(RECORD, DATA["claims"]) == []


def test_each_value_is_in_a_claim():
    used = {
        field
        for claim in cd.CLAIMS
        for _, field, _, _ in string.Formatter().parse(claim)
        if field
    }
    assert used == set(VALUES)


# Changed copies of the record (false claims) that the check must find.
# (old, new, swap): with swap, old and new change places.
CHANGES = [
    ("1806330", "1989881", True),
    ("100.7", "196.3", True),
    ("8 of the 162", "162 of the 8", False),
    ("(10 loops)", "(12 loops)", False),
    ("12 times smaller", "12 times larger", False),
    ("359 bytes", "360 bytes", False),
    ("790 kinds:", "761 kinds:", False),
    ("177 leaf, 609 segment", "609 leaf, 177 segment", False),
    ("12% of the", "88% of the", False),
    ("exit code 2", "exit code 1", False),
    ("holds 65536 kinds", "holds 65535 kinds", False),
    ("(a clone, a lower bound)", "(the full tree)", False),
]


@pytest.mark.parametrize(("old", "new", "swap"), CHANGES)
def test_a_false_claim_fails_the_check(old, new, swap):
    text = cd.flat_text(RECORD)
    assert text.count(old) == 1, old
    if swap:
        assert text.count(new) == 1, new
        changed = text.replace(old, "\0").replace(new, old).replace("\0", new)
    else:
        changed = text.replace(old, new)
    assert cd.doc_problems(text, DATA["claims"]) == []
    assert cd.doc_problems(changed, DATA["claims"]) != []


def test_a_new_number_outside_a_claim_fails_the_check():
    changed = RECORD.replace(
        "## Proof for each task", "## Proof for each task\n\n3 more."
    )
    problems = cd.doc_problems(changed, DATA["claims"])
    assert problems == ["the record has a number that is not in a claim: 3"]


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


def test_tracks_yml_gives_each_package_to_its_owner_in_the_table():
    # S3b C16: the owner track owns src/** and tests/** of the package; Core
    # keeps its Cargo.toml.
    ownership = ci_module("ownership")
    tracks = ownership.load()
    for package, track in package_rows().items():
        for path in (f"crates/{package}/src/lib.rs", f"crates/{package}/tests/x.rs"):
            assert ownership.owner(path, tracks) == track, path
        assert ownership.owner(f"crates/{package}/Cargo.toml", tracks) == "core"


def test_each_package_of_the_workspace_is_in_the_table():
    cargo = (REPO_ROOT / "Cargo.toml").read_text("utf8")
    members = re.findall(r'"crates/(\w+)"', cargo)
    assert members
    assert set(members) <= set(package_rows())


@pytest.mark.parametrize(
    "word",
    [
        "[docs/decisions/s3b-core.md](../docs/decisions/s3b-core.md)",
        # The plan changes of the record (task list).
        "the build fails if the kinds do not fit in a `u16`",
        # C13 moved EXIT_ERROR (the status names the new place).
        "`scripts/s3b/core_design.py` reads it there",
        "`docs/decisions/s3b-*.md` to the Core paths",
    ],
)
def test_the_s3b_status_links_the_record(word):
    assert word in STATUS
