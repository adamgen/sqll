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
    "running 2 tests\n"
    f"{so.random_pass_line(20000)} (211080 ranges)\n"
    f"test {so.RANDOM_TEST} ... ok\n"
    f"{so.pass_line(54)} (776608 ranges)\n"
    f"test {so.TEST} ... ok\n\n"
    "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 5 filtered out\n"
)


def test_a_passing_run_has_no_problem():
    assert so.check_output(0, GOOD, 54, 20000) == []


@pytest.mark.parametrize(
    "code, output, fixtures, files",
    [
        (101, GOOD, 54, 20000),
        (0, GOOD.replace(f"{so.TEST} ... ok", f"{so.TEST} ... ignored"), 54, 20000),
        (0, GOOD.replace(f"{so.RANDOM_TEST} ... ok", "x"), 54, 20000),
        (0, GOOD.replace("2 passed", "1 passed"), 54, 20000),
        (0, GOOD.replace("54 of 54", "53 of 54"), 54, 20000),
        (0, GOOD.replace("20000 of 20000", "19999 of 20000"), 54, 20000),
        (0, GOOD, 55, 20000),
        (0, GOOD, 54, 20001),
        (0, "", 54, 20000),
    ],
)
def test_the_check_fails_closed(code, output, fixtures, files):
    assert so.check_output(code, output, fixtures, files)


def test_the_pass_line_and_names_are_those_of_the_rust_test():
    text = (
        REPO_ROOT / "crates" / "sqll_interfaces" / "tests" / "source_map.rs"
    ).read_text("utf8")
    assert '"source map: {} of {total} {what}: as sqlfluff (' in text
    assert 'report(total, "templater fixtures", &counts, &problems);' in text
    assert '"source map: {} of {total} random files: as sqlfluff (' in text
    assert f"fn {so.TEST}()" in text
    assert f"fn {so.RANDOM_TEST}()" in text
    assert f'const ORACLE_ENV: &str = "{so.ORACLE_ENV}";' in text
    assert f'const RANDOM_ENV: &str = "{so.RANDOM_ENV}";' in text
    assert f'assert_eq!(json["kind"], "{so.RANDOM_KIND}");' in text
    assert f'const RECORD: &str = "{so.RECORD_FILE.relative_to(REPO_ROOT)}";' in text
    assert f'const JINJA_A: &str = "{so.RECORD_FIXTURES[0]}";' in text
    # A fixture with no sqlfluff parse tree fails.
    assert 'return Err("sqlfluff gave no parse tree".into());' in text


def test_the_random_generator_is_that_of_the_unit_test():
    """The characters and the raw slice types of the random files are those
    of the generator of the unit test of crates/sqll_source/src/map.rs."""
    text = (REPO_ROOT / "crates" / "sqll_source" / "src" / "map.rs").read_text("utf8")
    rust = text.split("const CHARS: [char; 8] = [", 1)[1].split("];", 1)[0]
    want = list(so.RANDOM_CHARS)
    got = [c.strip()[1:-1] for c in rust.split(",")]
    got = [{"\\r": "\r", "\\n": "\n"}.get(c, c) for c in got]
    assert got == want
    types = ", ".join(f'"{t}"' for t in so.RAW_TYPES)
    assert f"[{types}][rng.below(4)]" in text


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


def test_the_record_is_the_data_of_the_fixtures_of_the_pinned_sqlfluff():
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


@pytest.mark.parametrize("index", [0, 1, 2])
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


def test_the_fixtures_are_those_of_the_folders_and_of_the_jinja_test_table():
    fixtures = so.all_fixtures()
    assert len(fixtures) == so.FIXTURES == len(set(fixtures))
    nested = "test/fixtures/templater/jinja_exclude_macro_path/model_directory/"
    assert nested + "jinja_sub_directory.sql" in fixtures
    assert all(f.startswith(so.FIXTURE_DIR + "/") for f in fixtures)
    # Only the table fixture in a subfolder; no macro or loader file.
    deep = [f for f in fixtures if f.count("/") > so.FIXTURE_DIR.count("/") + 2]
    assert deep == [nested + "jinja_sub_directory.sql"]
