"""Tests of scripts/s3b/cli_oracle.py (S3b task C13): the record of the
sqlfluff runs that crates/sqll/tests/cli.rs compares sqll with. The CI job
build runs "check", which makes the data again."""

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "s3b" / "cli_oracle.py"
TEST = REPO_ROOT / "crates" / "sqll" / "tests" / "cli.rs"


def load():
    spec = importlib.util.spec_from_file_location("cli_oracle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cli_oracle"] = module
    spec.loader.exec_module(module)
    return module


co = load()
RECORD = json.loads(co.RECORD_FILE.read_text("utf8"))


def test_the_record_has_each_scenario_of_the_script_in_order():
    assert RECORD["count"] == len(co.SCENARIOS) == len(RECORD["scenarios"])
    for got, want in zip(RECORD["scenarios"], co.SCENARIOS, strict=True):
        for key in ("name", "files", "cwd", "args", "stdin", "tty", "sqll"):
            assert got[key] == want[key], (want["name"], key)
    assert RECORD["kind"] == co.KIND
    assert RECORD["sqlfluff"]["version"] == "4.4.0"


def test_the_writer_gives_the_record_again():
    assert co.dumps(RECORD) == co.RECORD_FILE.read_text("utf8")


def test_each_scenario_has_a_known_mark_and_its_data():
    for s in RECORD["scenarios"]:
        assert s["sqll"] in (None, "unsupported", "usage", "rules_subset"), s["name"]
        assert isinstance(s["exit_code"], int), s["name"]
        if s["sqll"] == "unsupported":
            # sqll fails closed where sqlfluff runs.
            assert s["exit_code"] != 2, s["name"]
            assert "stdout" not in s, s["name"]
        else:
            assert {"stdout", "stderr", "after"} <= set(s), s["name"]
    assert co.problems_of(RECORD["scenarios"]) == []


def test_each_command_and_format_has_a_scenario():
    args = [s["args"] for s in RECORD["scenarios"] if s["sqll"] is None]
    commands = {a[0] for a in args}
    assert commands == {"lint", "fix", "rules", "dialects"}
    formats = set()
    for a in args:
        if a[0] == "lint":
            fmt = "human"
            for i, x in enumerate(a):
                if x in ("-f", "--format"):
                    fmt = a[i + 1]
            formats.add(fmt)
    assert formats == {
        "human",
        "json",
        "yaml",
        "github-annotation",
        "github-annotation-native",
        "none",
    }
    codes = {s["exit_code"] for s in RECORD["scenarios"] if s["sqll"] is None}
    assert codes == {0, 1, 2}
    assert any(s["tty"] for s in RECORD["scenarios"])
    assert any(s["stdin"] for s in RECORD["scenarios"] if s["args"][0] == "fix")


def test_the_timings_are_masked():
    text = (
        '{"timings": {"templating": 1.5e-05, "CP01": 0.25}}\n'
        "  timings:\n    lexing: 0.001\n"
    )
    assert co.mask_timings(text) == (
        '{"timings": {"templating": 0.0, "CP01": 0.0}}\n  timings:\n    lexing: 0.0\n'
    )
    assert "each_c13_scenario_gives_the_sqlfluff_result" in TEST.read_text("utf8")
