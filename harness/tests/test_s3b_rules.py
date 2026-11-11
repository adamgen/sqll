"""Tests of scripts/s3b/rules_oracle.py (S3b task C12): the record of the
sqlfluff rule data and the Rust table of sqll_lint. The CI job build runs
"check", which makes the data again."""

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "s3b" / "rules_oracle.py"


def load():
    spec = importlib.util.spec_from_file_location("rules_oracle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["rules_oracle"] = module
    spec.loader.exec_module(module)
    return module


ro = load()
RECORD = json.loads(ro.RECORD_FILE.read_text("utf8"))


def test_the_counts_are_those_of_the_record_and_of_the_script():
    assert ro.counts(RECORD) == ro.COUNTS
    assert RECORD["counts"] == ro.COUNTS
    assert RECORD["kind"] == ro.KIND
    assert RECORD["sqlfluff"]["version"] == "4.4.0"
    assert RECORD["fixtures"] == list(ro.RULE_FIXTURES)


def test_the_writer_gives_the_record_again():
    assert ro.dumps(RECORD) == ro.RECORD_FILE.read_text("utf8")


def test_the_rust_table_is_the_table_of_the_record():
    assert ro.table(RECORD) == ro.RULES_RS.read_text("utf8")


def test_the_cases_are_those_of_the_fixtures_in_order():
    import yaml

    names = []
    for rel in ro.RULE_FIXTURES:
        y = yaml.safe_load((ro.SQLFLUFF_ROOT / rel).read_text("utf8"))
        rule = y.pop("rule")
        y.pop("configs", None)
        names += [[rule, name] for name in y]
    assert [[c["rule"], c["name"]] for c in RECORD["cases"]] == names


def test_the_problems_include_a_count_change():
    data = {"rules": RECORD["rules"][:1], "config_info": {}, "cases": []}
    assert ro.problems_of(data)
    assert ro.problems_of(RECORD) == []
