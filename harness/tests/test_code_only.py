from pathlib import Path

import pytest
from conftest import needs_sqlfluff

from sqll_harness.adapters.sqlfluff import SqlfluffAdapter
from sqll_harness.cases import PASS
from sqll_harness.code_only import (
    META_TYPES,
    NON_CODE_TYPES,
    code_only_record,
    simplify,
    sqlfluff_record,
    to_node,
)
from sqll_harness.compare import record_to_tuple
from sqll_harness.paths import SQLFLUFF_ROOT
from sqll_harness.suites import SUITES, code_only, dialects, runs_for

# "select a -- c\nfrom t;\n" as sqruff gives it: lists of one-key dicts.
SQRUFF_FULL = {
    "file": [
        {
            "statement": [
                {
                    "select_statement": [
                        {
                            "select_clause": [
                                {"keyword": "select"},
                                {"whitespace": " "},
                                {
                                    "select_clause_element": [
                                        {
                                            "column_reference": [
                                                {"naked_identifier": "a"}
                                            ]
                                        }
                                    ]
                                },
                            ]
                        },
                        {"whitespace": " "},
                        {"inline_comment": "-- c"},
                        {"newline": "\n"},
                        {
                            "from_clause": [
                                {"keyword": "from"},
                                {"whitespace": " "},
                                {"table_reference": [{"naked_identifier": "t"}]},
                            ]
                        },
                    ]
                }
            ]
        },
        {"statement_terminator": ";"},
        {"newline": "\n"},
    ]
}
# The same tree as "sqlfluff parse -c" gives it.
SQLFLUFF_CODE_ONLY = {
    "file": {
        "statement": {
            "select_statement": {
                "select_clause": {
                    "keyword": "select",
                    "select_clause_element": {
                        "column_reference": {"naked_identifier": "a"}
                    },
                },
                "from_clause": {
                    "keyword": "from",
                    "table_reference": {"naked_identifier": "t"},
                },
            }
        },
        "statement_terminator": ";",
    }
}


def test_sqruff_list_form_gives_the_sqlfluff_code_only_record():
    got = code_only_record(SQRUFF_FULL)
    assert got == SQLFLUFF_CODE_ONLY
    assert record_to_tuple(got) == record_to_tuple(SQLFLUFF_CODE_ONLY)


def test_sqlfluff_record_keeps_the_tree():
    got = sqlfluff_record(SQRUFF_FULL)
    assert record_to_tuple(got) == record_to_tuple(SQRUFF_FULL)
    # Children with different types become a dict, as in sqlfluff.
    assert got["file"]["statement_terminator"] == ";"


def test_duplicate_types_give_a_list():
    node = ("x", (("a", "1"), ("b", "2"), ("a", "3")))
    assert simplify(node) == {"x": [{"a": "1"}, {"b": "2"}, {"a": "3"}]}
    assert simplify(("x", ())) == {"x": None}


@pytest.mark.parametrize("value", [None, []])
def test_no_children(value):
    assert to_node({"file": value}) == ("file", ())
    assert code_only_record({"file": value}) == {"file": None}


def test_a_segment_with_only_non_code_children_is_removed():
    record = {
        "file": [
            {"statement": [{"keyword": "select"}]},
            {"bracketed": [{"whitespace": " "}, {"block_comment": "/* x */"}]},
            {"empty": None},
            {"also_empty": []},
        ]
    }
    assert code_only_record(record) == {"file": {"statement": {"keyword": "select"}}}


def test_meta_segments_are_removed():
    record = {"file": [{"indent": ""}, {"keyword": "a"}, {"end_of_file": ""}]}
    for meta in META_TYPES:
        record["file"].append({meta: ""})
    assert code_only_record(record) == {"file": {"keyword": "a"}}


def test_each_non_code_type_is_removed():
    for name in NON_CODE_TYPES:
        record = {"file": [{name: "x"}, {"keyword": "a"}]}
        assert code_only_record(record) == {"file": {"keyword": "a"}}, name


def test_postgres_meta_command():
    # The "meta_command" lexer (a comment) and MetaCommandQueryBufferSegment
    # (code) give the same type.
    record = {
        "file": [
            {"meta_command": "\\d my_table"},
            {"statement": [{"meta_command": "\\gset"}]},
            {"statement": [{"meta_command": "\\gexec"}]},
        ]
    }
    assert code_only_record(record) == {
        "file": [
            {"statement": {"meta_command": "\\gset"}},
            {"statement": {"meta_command": "\\gexec"}},
        ]
    }


@pytest.mark.parametrize(
    "record",
    [
        {"a": "x", "b": "y"},
        {},
        {"file": 3},
        {"file": [{"a": "x", "b": "y"}]},
        ["file"],
    ],
)
def test_bad_records(record):
    with pytest.raises(ValueError):
        code_only_record(record)


def test_suite_runs_only_for_sqlfluff():
    assert code_only.TOOLS == ("sqlfluff",)
    assert runs_for(SUITES["code_only"], "sqlfluff")
    assert not runs_for(SUITES["code_only"], "sqruff")
    assert not runs_for(SUITES["code_only"], "sqlfluff-rs")
    assert runs_for(SUITES["dialects"], "sqruff")


def test_discovery_is_the_dialect_cases():
    cases = code_only.discover(SQLFLUFF_ROOT)
    assert len(cases) == 2306
    assert [c.id.split("/", 1)[1] for c in cases] == [
        c.id.split("/", 1)[1] for c in dialects.discover(SQLFLUFF_ROOT)
    ]


FIXTURES = Path(__file__).parent / "fixtures" / "dialects"


@needs_sqlfluff
@pytest.mark.parametrize("case", code_only.discover(FIXTURES), ids=lambda c: c.id)
def test_filter_agrees_with_sqlfluff_on_the_harness_fixtures(case):
    # Also the fixtures that fail the dialect test: the filter check only
    # compares 2 sqlfluff outputs.
    result = code_only.run(SqlfluffAdapter(), case, FIXTURES)
    assert result.status == PASS, result.reason
