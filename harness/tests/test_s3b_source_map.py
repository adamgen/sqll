"""Tests of scripts/s3b/source_map_oracle.py (S3b task C8): the check of the
cargo test output, the JSON writer, and the record of the sqlfluff data.
The CI job build runs "check", which makes the data again."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "s3b" / "source_map_oracle.py"


def load():
    spec = importlib.util.spec_from_file_location("source_map_oracle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["source_map_oracle"] = module
    spec.loader.exec_module(module)
    return module


so = load()

GOOD = (
    "running 1 test\n"
    f"{so.pass_line(53)} (775828 ranges)\n"
    f"test {so.TEST} ... ok\n\n"
    "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 4 filtered out\n"
)


def test_a_passing_run_has_no_problem():
    assert so.check_output(0, GOOD, 53) == []


@pytest.mark.parametrize(
    "code, output, fixtures",
    [
        (101, GOOD, 53),
        (0, GOOD.replace(f"{so.TEST} ... ok", f"{so.TEST} ... ignored"), 53),
        (0, GOOD.replace("1 passed", "0 passed"), 53),
        (0, GOOD.replace("53 of 53", "52 of 53"), 53),
        (0, GOOD, 54),
        (0, "", 53),
    ],
)
def test_the_check_fails_closed(code, output, fixtures):
    assert so.check_output(code, output, fixtures)


def test_the_pass_line_and_names_are_those_of_the_rust_test():
    text = (
        REPO_ROOT / "crates" / "sqll_interfaces" / "tests" / "source_map.rs"
    ).read_text("utf8")
    assert '"source map: {} of {total} templater fixtures: as sqlfluff (' in text
    assert f"fn {so.TEST}()" in text
    assert f'const ORACLE_ENV: &str = "{so.ORACLE_ENV}";' in text
    assert f'const RECORD: &str = "{so.RECORD_FILE.relative_to(REPO_ROOT)}";' in text
    assert f'const JINJA_A: &str = "{so.RECORD_FIXTURES[0]}";' in text


def test_the_ci_job_and_verify_run_the_check():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text("utf8")
    command = f"{so.COMMAND} check"
    assert f"run: {command}" in ci
    verify = (REPO_ROOT / "harness" / "sqll_harness" / "verify.py").read_text("utf8")
    assert "scripts/s3b/source_map_oracle.py check" in verify


def test_the_writer_gives_the_data_again():
    data = {
        "kind": so.KIND,
        "fixtures": [
            {"path": "a", "ranges": [[0, 0], [0, 1, 0, 3, 1]], "segments": None},
            {"path": "b", "violations": [], "x": {"y": 1}},
        ],
        "last": [1, 2],
    }
    text = so.dumps(data)
    assert json.loads(text) == data
    assert "    [0, 1, 0, 3, 1]\n" in text


DOC = json.loads(so.RECORD_FILE.read_text("utf8"))


def test_the_record_is_the_data_of_the_two_fixtures_of_the_pinned_sqlfluff():
    commit = (REPO_ROOT / "crates" / "sqll_dialects" / "generated.json").read_text(
        "utf8"
    )
    assert DOC["kind"] == so.KIND and DOC["format"] == so.FORMAT
    assert DOC["command"] == f"{so.COMMAND} record"
    assert DOC["sqlfluff"]["version"] == "4.4.0"
    assert DOC["sqlfluff"]["commit"] == "0348222a3bcdb0226563f7349c5a39beb0641955"
    assert DOC["sqlfluff"]["commit"] in commit
    assert so.RECORD_FILE.read_text("utf8") == so.dumps(DOC)
    paths = [f["path"] for f in DOC["fixtures"]]
    assert paths == list(so.RECORD_FIXTURES)


@pytest.mark.parametrize("index", [0, 1])
def test_each_recorded_fixture_has_all_ranges_and_offsets(index):
    fx = DOC["fixtures"][index]
    source = (so.SQLFLUFF_ROOT / fx["path"]).read_text("utf8")
    assert fx["source_chars"] == len(source)
    n = len(fx["templated_str"])
    pairs = [(r[0], r[1]) for r in fx["ranges"]]
    assert pairs == [(i, j) for i in range(n + 1) for j in range(i, n + 1)]
    assert len(fx["source_points"]) == len(source) + 1
    assert fx["violations"] == [] and fx["segments"]
    assert fx["dialect"] == so.DEFAULT_DIALECT and fx["templater"] == "jinja"
    # The literal slices give the templated text from the source text.
    for ty, s0, s1, t0, t1 in fx["sliced_file"]:
        if ty == "literal" and t1 > t0:
            assert source[s0:s1] == fx["templated_str"][t0:t1]
