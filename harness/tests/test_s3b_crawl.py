"""Tests of scripts/s3b/crawl_oracle.py (S3b task C10): the record of the
sqlfluff crawl data and the names that the Rust interface test uses. The CI
job build runs "check", which makes the data again."""

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "s3b" / "crawl_oracle.py"
TEST = REPO_ROOT / "crates" / "sqll_interfaces" / "tests" / "typed_view.rs"


def load():
    spec = importlib.util.spec_from_file_location("crawl_oracle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["crawl_oracle"] = module
    spec.loader.exec_module(module)
    return module


co = load()
RECORD = json.loads(co.RECORD_FILE.read_text("utf8"))


def test_the_record_has_each_fixture_and_case_in_order():
    paths = [f["path"] for f in RECORD["fixtures"]]
    assert paths == [f"{co.FIXTURE_DIR}/{rel}" for rel in co.FIXTURES]
    for fixture in RECORD["fixtures"]:
        cases = [
            [
                c["start"],
                c["types"],
                c["recurse_into"],
                c["no_recursive"],
                c["allow_self"],
            ]
            for c in fixture["cases"]
        ]
        assert cases == [list(c) for c in co.CASES]


def test_the_counts_are_those_of_the_record_and_of_the_script():
    assert co.counts(RECORD["fixtures"]) == co.COUNTS
    assert RECORD["counts"] == co.COUNTS
    assert RECORD["kind"] == co.KIND
    assert RECORD["sqlfluff"]["version"] == "4.4.0"


def test_the_writer_gives_the_record_again():
    assert co.dumps(RECORD) == co.RECORD_FILE.read_text("utf8")


def test_the_problems_include_a_count_change():
    data = {"problems": [], "fixtures": RECORD["fixtures"][:1]}
    assert co.problems_of(data)
    data = {"problems": ["x"], "fixtures": RECORD["fixtures"]}
    assert co.problems_of(data) == ["x"]


def test_the_yaml_crawl_has_the_options_of_recursive_crawl():
    tree = co.to_node(
        "file",
        [
            {"statement": {"keyword": "a", "statement": {"keyword": "b"}}},
        ],
    )

    def crawl(node, types, recurse_into=True, stops=(), allow_self=True):
        found = co.yaml_crawl(node, types, recurse_into, list(stops), allow_self)
        return [co.yaml_raw(n) for n in found]

    assert crawl(tree, ["statement"]) == ["ab", "b"]
    assert crawl(tree, ["statement"], recurse_into=False) == ["ab"]
    assert crawl(tree, ["keyword"], stops=["statement"]) == []
    outer = tree[1][0]
    assert crawl(outer, ["keyword"], stops=["statement"]) == ["a"]
    assert crawl(outer, ["statement"], allow_self=False) == ["b"]


def test_the_names_are_those_of_the_rust_test():
    text = TEST.read_text("utf8")
    assert f'const RECORD: &str = "{co.RECORD_FILE.relative_to(REPO_ROOT)}";' in text
    assert f'const KIND: &str = "{co.KIND}";' in text
    assert f'const JINJA_B: &str = "{co.TEMPLATED_FIXTURE}";' in text
