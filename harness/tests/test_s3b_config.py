"""Tests of scripts/s3b/config_oracle.py (S3b task C11): the record of the
sqlfluff config data and the names that the Rust tests use. The CI job
build runs "check", which makes the data again."""

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "s3b" / "config_oracle.py"
TESTS = (
    REPO_ROOT / "crates" / "sqll_interfaces" / "tests" / "config.rs",
    REPO_ROOT / "crates" / "sqll" / "tests" / "cli_config.rs",
)


def load():
    spec = importlib.util.spec_from_file_location("config_oracle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["config_oracle"] = module
    spec.loader.exec_module(module)
    return module


co = load()
RECORD = json.loads(co.RECORD_FILE.read_text("utf8"))


def test_the_record_has_each_case_of_the_script_in_order():
    assert [c["name"] for c in RECORD["ini"]] == [n for n, _ in co.INI]
    assert [c["name"] for c in RECORD["toml"]] == [n for n, _ in co.TOML]
    assert [c[0] for c in RECORD["coerce"]] == list(co.COERCE)
    assert [s["name"] for s in RECORD["load"]] == [s["name"] for s in co.LOAD]
    assert [s["name"] for s in RECORD["cli"]] == [c[0] for c in co.CLI]
    for scenario, case in zip(RECORD["load"], co.LOAD, strict=True):
        for key in ("files", "cwd", "home", "xdg", "path", "extra", "sqll"):
            assert scenario[key] == case[key], (case["name"], key)


def test_the_counts_are_those_of_the_record_and_of_the_script():
    assert co.counts(RECORD | {"jinja_as_raw": RECORD["jinja_as_raw"]}) == co.COUNTS
    assert RECORD["counts"] == co.COUNTS
    assert RECORD["kind"] == co.KIND
    assert RECORD["sqlfluff"]["version"] == "4.4.0"


def test_the_writer_gives_the_record_again():
    assert co.dumps(RECORD) == co.RECORD_FILE.read_text("utf8")


def test_each_scenario_has_a_result_and_a_known_sqll_mark():
    for s in RECORD["load"]:
        assert ("config" in s) != ("error" in s), s["name"]
        assert s["sqll"] in (None, "unsupported", "exit2"), s["name"]
    for s in RECORD["cli"]:
        assert ("stdout" in s) != ("tree" in s), s["name"]
        assert s["sqll"] in (None, "unsupported", "exit2"), s["name"]
    # Each path of the record is relative to the scenario folder.
    assert str(REPO_ROOT) not in co.RECORD_FILE.read_text("utf8")


def test_the_rust_tests_read_the_record():
    for test in TESTS:
        text = test.read_text("utf8")
        assert "results/S3b/C11-config.json" in text, test


def test_the_problems_include_a_count_change():
    data = {**RECORD, "jinja_as_raw": {**RECORD["jinja_as_raw"], "problems": []}}
    assert co.problems_of(data) == []
    data["cli"] = RECORD["cli"][:1]
    assert co.problems_of(data)
