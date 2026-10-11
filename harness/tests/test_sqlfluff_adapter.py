import pytest

from sqll_harness.adapters.sqlfluff import SqlfluffAdapter, _parse_output
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
