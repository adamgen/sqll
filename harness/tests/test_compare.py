import pytest

from sqll_harness.compare import (
    has_node,
    load_yaml,
    process_struct,
    record_to_tuple,
    trees_match,
)
from sqll_harness.paths import SQLFLUFF_ROOT


def test_dict_and_list_forms_are_equal():
    as_dict = {"file": {"keyword": "select", "numeric_literal": "1"}}
    as_list = {"file": [{"keyword": "select"}, {"numeric_literal": "1"}]}
    assert record_to_tuple(as_dict) == record_to_tuple(as_list)
    assert record_to_tuple(as_dict) == (
        "file",
        (("keyword", "select"), ("numeric_literal", "1")),
    )


def test_order_is_significant():
    a = record_to_tuple({"file": [{"a": "1"}, {"b": "2"}]})
    b = record_to_tuple({"file": [{"b": "2"}, {"a": "1"}]})
    assert not trees_match(a, b)


def test_null_and_empty_list_files_are_equal():
    assert trees_match(record_to_tuple({"file": None}), record_to_tuple({"file": []}))
    assert trees_match(record_to_tuple({"file": []}), record_to_tuple({"file": None}))


def test_empty_file_and_non_empty_file_differ():
    full = record_to_tuple({"file": {"keyword": "select"}})
    assert not trees_match(record_to_tuple({"file": None}), full)
    assert not trees_match(full, record_to_tuple({"file": []}))


def test_no_tree_from_tool_is_not_a_match():
    assert not trees_match(record_to_tuple({"file": None}), None)


def test_scalars_become_strings():
    assert process_struct({"numeric_literal": 1}) == (("numeric_literal", "1"),)


def test_multi_key_dict_in_list_is_rejected():
    with pytest.raises(ValueError):
        process_struct([{"a": "1", "b": "2"}])


def test_list_of_scalars_is_rejected():
    with pytest.raises(TypeError):
        process_struct(["a"])


def test_load_yaml_drops_hash(tmp_path):
    p = tmp_path / "x.yml"
    p.write_text("_hash: abc\nfile:\n  keyword: select\n")
    assert load_yaml(p) == ("abc", ("file", (("keyword", "select"),)))


def test_load_yaml_of_real_empty_fixture():
    p = SQLFLUFF_ROOT / "test/fixtures/dialects/ansi/empty_file.yml"
    _hash, tree = load_yaml(p)
    assert tree == ("file", None)


def test_has_node():
    rec = {"file": [{"statement": {"unparsable": [{"word": "x"}]}}]}
    assert has_node(rec, "unparsable")
    assert not has_node(rec, "keyword")
    assert not has_node(None, "unparsable")
