import pytest

from sqll_harness.compare import (
    has_node,
    load_yaml,
    process_struct,
    record_to_test_tuple,
    record_to_tuple,
    strip_positions,
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


def test_safe_loader_gives_the_same_data_as_sqlfluff_loader():
    # sqlfluff loads the fixtures with yaml.CLoader. See compare.py.
    import yaml

    from sqll_harness.compare import _Loader
    from sqll_harness.suites import dialects, templater

    assert _Loader is yaml.CSafeLoader
    paths = {SQLFLUFF_ROOT / c.yml for c in dialects.discover(SQLFLUFF_ROOT)}
    paths |= {SQLFLUFF_ROOT / c.yml for c in templater.discover(SQLFLUFF_ROOT)}
    assert len(paths) == 2306 + 43
    for path in sorted(paths):
        text = path.read_text(encoding="utf8")
        assert yaml.load(text, Loader=_Loader) == yaml.load(text, Loader=yaml.CLoader)


POS = {
    "start_line_no": 1,
    "start_line_pos": 1,
    "start_file_pos": 0,
    "end_line_no": 2,
    "end_line_pos": 1,
    "end_file_pos": 9,
}


def test_strip_positions_of_each_record_form():
    # Many children: a list of dicts. One child: its keys are in the dict of
    # the parent. The root record also has the keys.
    record = {
        **POS,
        "file": [
            {**POS, "statement": {**POS, "keyword": "SELECT"}},
            {**POS, "newline": "\n"},
            {**POS, "statement": None},
        ],
    }
    assert strip_positions(record) == {
        "file": [
            {"statement": {"keyword": "SELECT"}},
            {"newline": "\n"},
            {"statement": None},
        ]
    }


def test_strip_positions_keeps_a_segment_with_a_position_name():
    for value in ("x", None, {"a": "b"}, ["c"], True, 1.5):
        with pytest.raises(ValueError, match="position key 'end_file_pos'"):
            strip_positions({"file": {"end_file_pos": value}})


def test_record_to_test_tuple_makes_null_an_empty_tuple():
    assert record_to_test_tuple({"file": None}) == ("file", ())
    assert record_to_test_tuple({"file": {"statement": None, "x": ""}}) == (
        "file",
        (("statement", ()), ("x", "")),
    )
    assert record_to_test_tuple({"file": [{"a": None}, {"a": "1"}]}) == (
        "file",
        (("a", ()), ("a", "1")),
    )


@pytest.mark.parametrize("record", [{}, {"a": "1", "b": "2"}, None, []])
def test_record_to_test_tuple_needs_one_root(record):
    with pytest.raises(ValueError):
        record_to_test_tuple(record)


def test_test_tuple_and_yaml_null(tmp_path):
    p = tmp_path / "x.yml"
    p.write_text("file:\n")
    assert load_yaml(p)[1] == ("file", None)
    assert load_yaml(p)[1] != record_to_test_tuple({"file": None})
    p.write_text("file: []\n")
    assert load_yaml(p)[1] == record_to_test_tuple({"file": None})
