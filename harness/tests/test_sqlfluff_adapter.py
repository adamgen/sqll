import json
from pathlib import Path

import pytest

from sqll_harness.adapters.sqlfluff import (
    SqlfluffAdapter,
    _critical_logs,
    _exit_reason,
    _lint_output,
    _parse_output,
)
from sqll_harness.paths import SQLFLUFF_ROOT


def test_parse_output_with_tree():
    out = '[{"filepath": "x.sql", "segments": {"file": {"keyword": "select"}}}]'
    r = _parse_output(out, 0, "")
    assert r.tree == {"file": {"keyword": "select"}}
    assert not r.errors
    assert not r.has_unparsable


def test_parse_output_with_unparsable_and_error():
    out = '[{"filepath": "x.sql", "segments": {"file": {"unparsable": "x"}}}]'
    r = _parse_output(out, 1, "")
    assert r.has_unparsable
    assert r.errors == ["exit code 1"]


def test_parse_output_with_no_json():
    r = _parse_output("Traceback ...", 2, "boom")
    assert r.tree is None
    assert r.errors == ["no JSON parse output", "exit code 2"]


def test_lint_output():
    names = {"a.sql": Path("/w/a.sql"), "b.sql": Path("/w/b.sql")}
    out = json.dumps(
        [
            {"filepath": "a.sql", "violations": []},
            {"filepath": "b.sql", "violations": [{"code": "LT01"}]},
        ]
    )
    r = _lint_output(out, 0, "", names)
    assert not r.errors
    assert r.violations == {Path("/w/a.sql"): [], Path("/w/b.sql"): [{"code": "LT01"}]}
    # The tool skips a file, for example over large_file_skip_byte_limit.
    r = _lint_output('[{"filepath": "a.sql", "violations": []}]', 0, "", names)
    assert r.violations is None
    assert r.errors == ["no lint output for b.sql"]
    r = _lint_output("", 2, "\nUser Error: bad config\nmore\n", names)
    assert r.violations is None
    assert r.errors == ["no JSON lint output", "exit code 2: User Error: bad config"]


def test_exit_reason():
    assert _exit_reason(2, "") == "exit code 2"
    assert _exit_reason(2, "  \nUser Error: x\ny\n") == "exit code 2: User Error: x"
    traceback = "Traceback (most recent call last):\n  File \"x\"\nKeyError: 'd'\n"
    assert _exit_reason(1, traceback) == "exit code 1: KeyError: 'd'"


def test_critical_logs():
    out = (
        "==== finding fixable violations ====\n"
        "\x1b[0mWARNING    \x1b[31mOne fix for LT01 not applied\x1b[0m \n"
        "\x1b[0mCRITICAL   \x1b[31mRule LT01 returned conflicting fixes with the "
        "same anchor.\n0x1:\n    fix\x1b[0m \n"
        "CRITICAL   Applying rule AL01 to 'x.sql' threw an Exception: boom\n"
    )
    assert _critical_logs(out) == [
        "Rule LT01 returned conflicting fixes with the same anchor.",
        "Applying rule AL01 to 'x.sql' threw an Exception: boom",
    ]
    assert _critical_logs("WARNING    x\nFIXED\n") == []


adapter = SqlfluffAdapter()
needs_sqlfluff = pytest.mark.skipif(
    not adapter.binary.exists(),
    reason="sqlfluff tool venv is not installed; run scripts/test",
)


@needs_sqlfluff
def test_version_is_pinned():
    assert adapter.version() == "4.4.0"


@needs_sqlfluff
def test_parse_error_is_detected(tmp_path):
    sql = tmp_path / "bad.sql"
    sql.write_text('select "\n')
    r = adapter.parse(sql, "ansi", True, False, SQLFLUFF_ROOT)
    assert r.rc != 0
    assert r.has_unparsable


@needs_sqlfluff
def test_extra_config_is_applied(tmp_path):
    sql = SQLFLUFF_ROOT / "test/fixtures/dialects/ansi/expression_recursion.sql"
    low = adapter.parse(
        sql, "ansi", True, False, SQLFLUFF_ROOT, {"core": {"max_parse_depth": 5}}
    )
    assert low.tree is None
    high = adapter.parse(
        sql, "ansi", True, False, SQLFLUFF_ROOT, {"core": {"max_parse_depth": 2000}}
    )
    assert high.tree is not None
    assert high.rc == 0


@needs_sqlfluff
def test_local_config_file_is_ignored(tmp_path):
    src = SQLFLUFF_ROOT / "test/fixtures/dialects/ansi/expression_recursion.sql"
    sql = tmp_path / src.name
    sql.write_text(src.read_text())
    # This config makes the parse fail if sqlfluff reads it.
    (tmp_path / ".sqlfluff").write_text("[sqlfluff]\nmax_parse_depth = 5\n")
    r = adapter.parse(sql, "ansi", True, False, tmp_path)
    assert r.tree is not None
    assert r.rc == 0
