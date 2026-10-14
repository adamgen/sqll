import json
import subprocess
from pathlib import Path

import pytest
from conftest import needs

from sqll_harness import cli
from sqll_harness.adapters import ADAPTERS
from sqll_harness.adapters import config_files as sfc
from sqll_harness.adapters.base import Unsupported
from sqll_harness.adapters.sqruff import (
    LINT_FIELDS,
    SqruffAdapter,
    check_inline_config,
    lint_output,
    parse_output,
    to_violation,
)
from sqll_harness.adapters.sqruff_config import SQLFLUFF_DEFAULTS
from sqll_harness.cases import ERROR, FAIL
from sqll_harness.paths import SQLFLUFF_ROOT
from sqll_harness.suites import autofix, dialects, rules, templater

needs_sqruff = needs("sqruff/bin/sqruff", "sqruff/python/bin/python3")
FIXTURES = Path(__file__).parent / "fixtures"


def _proc(rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["sqruff"], rc, stdout, stderr)


def test_adapter_is_registered():
    assert ADAPTERS["sqruff"] is SqruffAdapter
    assert SqruffAdapter.config_layer == SQLFLUFF_DEFAULTS
    assert SqruffAdapter.lint_fields == LINT_FIELDS


# Output reading (no tool)


def test_to_violation():
    item = {
        "range": {"start": {"line": 2, "character": 5}, "end": {}},
        "message": "Bad.",
        "severity": "Warning",
        "source": "sqruff",
        "code": "LT01",
    }
    assert to_violation(item) == {
        "code": "LT01",
        "description": "Bad.",
        "start_line_no": 2,
        "start_line_pos": 5,
    }
    # sqruff gives no code for a parse error.
    assert to_violation({**item, "code": None})["code"] == "PRS"


def test_lint_output(tmp_path):
    a, b = tmp_path / "a.sql", tmp_path / "b.sql"
    item = {
        "range": {"start": {"line": 1, "character": 1}},
        "message": "m",
        "code": "X",
    }
    out = lint_output(
        _proc(1, json.dumps({"a.sql": [item], "b.sql": []})), {"a.sql": a, "b.sql": b}
    )
    assert out.errors == []
    assert out.violations == {a: [to_violation(item)], b: []}
    missing = lint_output(_proc(0, json.dumps({"a.sql": []})), {"a.sql": a, "b.sql": b})
    assert missing.violations is None and missing.errors == ["no lint output for b.sql"]
    # A config error: exit code 1 and no JSON.
    bad = lint_output(_proc(1, "", "Error loading config"), {"a.sql": a})
    assert bad.violations is None and bad.errors == ["no JSON lint output"]
    crash = lint_output(_proc(101, "{}", "thread 'main' panicked at x"), {})
    assert crash.errors and crash.errors[0].startswith("exit code 101")


def test_parse_output():
    tree = {
        "file": [
            {"keyword": "select"},
            {"whitespace": " "},
            {"unparsable": [{"word": "x"}]},
        ]
    }
    full = parse_output(
        _proc(1, json.dumps(tree), "\nParse violations:\n  PRS: x"), False
    )
    assert full.tree == {
        "file": {"keyword": "select", "whitespace": " ", "unparsable": {"word": "x"}}
    }
    assert full.has_unparsable and full.errors == [] and full.rc == 1
    code = parse_output(_proc(0, json.dumps(tree)), True)
    assert code.tree == {"file": {"keyword": "select", "unparsable": {"word": "x"}}}
    # Position keys (--include-meta) are removed.
    meta = {
        "start_line_no": 1,
        "start_line_pos": 1,
        "start_file_pos": 0,
        "end_line_no": 1,
        "end_line_pos": 1,
        "end_file_pos": 0,
        "file": [{"indent": ""}],
    }
    assert parse_output(_proc(0, json.dumps(meta)), False).tree == {
        "file": {"indent": ""}
    }


@pytest.mark.parametrize(
    "stderr",
    [
        "Error: Failed to parse a.sql\nParse violations:\n  PRS: x\n",
        "Error parsing a.sql: Failed to template file a.sql with error X\n",
    ],
)
def test_parse_output_no_tree(stderr):
    got = parse_output(_proc(1, "", stderr), False)
    assert got.tree is None and got.errors == []


def test_parse_output_errors():
    assert parse_output(
        _proc(1, "", "The specified config file 'x' does not exist."), False
    ).errors
    assert parse_output(_proc(0, "not json"), False).errors == ["no JSON parse output"]
    assert parse_output(_proc(101, '{"file": []}', "panicked at x"), False).errors


# In-file config lines


@pytest.mark.parametrize(
    "line",
    [
        "--sqlfluff:dialect:ansi",  # sqlfluff reads it, sqruff does not.
        "  -- sqlfluff:dialect:ansi",  # sqruff reads it, sqlfluff does not.
        "-- sqruff:dialect:ansi",
    ],
)
def test_inline_config_read_by_one_tool_is_unsupported(tmp_path, line):
    sql = tmp_path / "a.sql"
    sql.write_text(f"select 1\n{line}\n")
    with pytest.raises(Unsupported, match="in-file config line"):
        check_inline_config(sql)


def test_inline_config_with_an_unsupported_setting(tmp_path):
    sql = tmp_path / "a.sql"
    sql.write_text("-- sqlfluff:rules:tab_space_size:2\nselect 1\n")
    with pytest.raises(Unsupported, match="setting rules.tab_space_size"):
        check_inline_config(sql)
    sql.write_text("-- sqlfluff: indentation: template_blocks_indent: force\n")
    with pytest.raises(Unsupported, match="indentation.template_blocks_indent"):
        check_inline_config(sql)
    sql.write_text("-- sqlfluff: indentation: tab_space_size: 2\n-- noqa\n")
    check_inline_config(sql)


def test_inline_config_with_warnings(tmp_path):
    # sqruff gives no warning field, so the violation is counted.
    sql = tmp_path / "a.sql"
    sql.write_text("-- sqlfluff:warnings:LT01\nselect a  from b\n")
    with pytest.raises(Unsupported, match="^output field warning"):
        check_inline_config(sql)


# sqlfluff config files (no tool)


def test_read_ini_keeps_case_and_splits_dots(tmp_path):
    got = sfc.read_ini(
        "[sqlfluff]\ndialect = ansi\n[sqlfluff:templater:jinja:context]\n"
        "NUM = 2\nnum = 4\na.b = x\n[other]\nk = v\n"
    )
    assert got == {
        "core": {"dialect": "ansi"},
        "templater": {"jinja": {"context": {"NUM": "2", "num": "4", "a": {"b": "x"}}}},
    }


def test_resolve_paths(tmp_path):
    (tmp_path / "macros").mkdir()
    (tmp_path / "libs").mkdir()
    cfg = tmp_path / ".sqlfluff"
    cfg.write_text(
        "[sqlfluff:templater:jinja]\nload_macros_from_path = macros,missing\n"
        "library_path = libs\n[sqlfluff:templater:jinja:context]\nx_path = libs\n"
        "[sqlfluff:templater:placeholder]\nparam_style = colon\n"
    )
    got = sfc.read_file(cfg)
    jinja = got["templater"]["jinja"]
    assert jinja["load_macros_from_path"] == str(tmp_path / "macros")
    assert jinja["library_path"] == str(tmp_path / "libs")
    # The context is user data.
    assert jinja["context"]["x_path"] == "libs"
    other = tmp_path / "o"
    other.mkdir()
    (other / ".sqlfluff").write_text(
        "[sqlfluff:templater:jinja]\nlibrary_path = nope\n"
    )
    assert (
        sfc.read_file(other / ".sqlfluff")["templater"]["jinja"]["library_path"]
        == "nope"
    )


def test_pyproject_with_sqlfluff_is_not_ported(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.black]\nx = 1\n")
    assert sfc.read_folder(tmp_path) == {}
    (tmp_path / "pyproject.toml").write_text("[tool.sqlfluff.core]\ndialect = 'ansi'\n")
    with pytest.raises(sfc.NotPorted):
        sfc.read_folder(tmp_path)


def test_file_order_in_a_folder(tmp_path):
    (tmp_path / "setup.cfg").write_text("[sqlfluff]\na = 1\nb = 1\n")
    (tmp_path / ".sqlfluff").write_text("[sqlfluff]\nb = 2\n")
    assert sfc.read_folder(tmp_path) == {"core": {"a": "1", "b": "2"}}


def test_config_folders(tmp_path):
    home, root = tmp_path / "home", tmp_path / "root"
    (root / "a" / "b").mkdir(parents=True)
    home.mkdir()
    sql = Path("a/b/x.sql")
    assert sfc.config_folders(sql, root, home) == [
        home / "sqlfluff",
        home,
        root,
        root / "a",
        root,
        root / "a",
        root / "a" / "b",
    ]
    # A file outside the current folder.
    other = tmp_path / "tmp" / "case"
    other.mkdir(parents=True)
    got = sfc.config_folders(other / "x.sql", root, home)
    assert got[-3:] == [tmp_path, tmp_path / "tmp", other]


def test_config_for_file(tmp_path):
    home, root = tmp_path / "home", tmp_path / "root"
    (root / "a").mkdir(parents=True)
    home.mkdir()
    (root / ".sqlfluff").write_text(
        "[sqlfluff]\ndialect = ansi\nmax_line_length = 10\n"
    )
    (root / "a" / ".sqlfluff").write_text("[sqlfluff]\ndialect = tsql\n")
    (home / ".sqlfluff").write_text("[sqlfluff]\nrules = LT01\n")
    got = sfc.config_for_file(Path("a/x.sql"), root, home)
    assert got == {
        "core": {"rules": "LT01", "dialect": "tsql", "max_line_length": "10"}
    }


def test_inline_config():
    sql = (
        "-- sqlfluff:dialect:tsql\n--sqlfluff:rules:x:y:1\n"
        "  -- sqlfluff:a:b\n-- sqlfluff x\n"
    )
    assert sfc.inline_config(sql) == {
        "core": {"dialect": "tsql"},
        "rules": {"x": {"y": "1"}},
    }


# The real tool


@needs_sqruff
def test_info():
    info = SqruffAdapter().info
    assert info["version"] == "0.41.0"
    assert info["rules"]["LT01"] == "layout.spacing"
    assert "CV13" not in info["rules"]
    assert "ansi" in info["dialects"] and "soql" not in info["dialects"]
    assert {"raw", "jinja", "placeholder", "python"} <= info["templaters"]


@needs_sqruff
def test_parse_and_code_only(tmp_path):
    sql = tmp_path / "a.sql"
    sql.write_text("select a -- c\nfrom t;\n")
    adapter = SqruffAdapter()
    full = adapter.parse(sql, "ansi", False, False, tmp_path)
    code = adapter.parse(sql, "ansi", True, False, tmp_path)
    assert full.errors == [] and code.errors == []
    assert (
        full.tree["file"]["statement"]["select_statement"]["inline_comment"] == "-- c"
    )
    assert code.tree == {
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
                        "from_expression": {
                            "from_expression_element": {
                                "table_expression": {
                                    "table_reference": {"naked_identifier": "t"}
                                }
                            }
                        },
                    },
                }
            },
            "statement_terminator": ";",
        }
    }


def _run_case(suite, case, root):
    return cli._run_one(suite, SqruffAdapter(), case, root)


@needs_sqruff
def test_unsupported_dialect_fails():
    case = dialects.DialectCase(
        "dialects/soql/x", "soql", Path("x.sql"), Path("x.yml"), True, None
    )
    result = _run_case(dialects, case, SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.reason == "unsupported: dialect soql"


@needs_sqruff
def test_unsupported_rule_fails():
    case = rules.RuleCase(id="rules/CV13/x", rule="CV13", pass_str="select 1\n")
    result = _run_case(rules, case, SQLFLUFF_ROOT)
    assert (result.status, result.reason) == (FAIL, "unsupported: rule CV13")


@needs_sqruff
@pytest.mark.parametrize(
    "configs, reason",
    [
        ({"rules": {"indent_unit": "tab"}}, "unsupported: setting rules.indent_unit"),
        ({"core": {"warnings": "LT01"}}, "unsupported: output field warning"),
        ({"core": {"dialect": "soql"}}, "unsupported: dialect soql"),
        ({"core": {"templater": "nope"}}, "unsupported: templater nope"),
    ],
)
def test_unsupported_config_fails(configs, reason):
    case = rules.RuleCase(
        id="rules/LT01/x", rule="LT01", pass_str="select 1\n", configs=configs
    )
    result = _run_case(rules, case, SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.reason.startswith(reason)


@needs_sqruff
def test_violation_fields_that_sqruff_does_not_give_fail():
    # sqruff gives the code, the description, and the start position.
    case = rules.RuleCase(
        id="rules/LT01/x",
        rule="LT01",
        fail_str="select a  from t\n",
        violations=[
            {"code": "LT01", "start_line_no": 1, "start_line_pos": 9, "end_line_no": 1}
        ],
    )
    result = _run_case(rules, case, SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.reason.startswith("unsupported: output field end_line_no, ")
    # The test compares each violation with to_dict(), which always has
    # "name" and "warning". Thus a dict with only the fields of sqruff never
    # passes the test.
    partial = rules.RuleCase(
        id="rules/LT01/y",
        rule="LT01",
        fail_str="select a  from t\n",
        fix_str="select a from t\n",
        violations=[
            {
                "start_line_no": 1,
                "start_line_pos": 9,
                "description": 'Expected only single space before "from". Found "  ".',
            }
        ],
    )
    result = _run_case(rules, partial, SQLFLUFF_ROOT)
    assert (result.status, result.reason) == (
        FAIL,
        "unsupported: output field name, warning (the case compares "
        "'violations'; the lint output has no such field)",
    )


@needs_sqruff
def test_unknown_layout_type_is_unsupported():
    case = rules.RuleCase(
        id="rules/LT01/x",
        rule="LT01",
        pass_str="select 1\n",
        configs={"layout": {"type": {"semantic_view": {"spacing_within": "touch"}}}},
    )
    result = _run_case(rules, case, SQLFLUFF_ROOT)
    assert (result.status, result.reason) == (
        FAIL,
        "unsupported: layout type semantic_view (sqruff stops on it)",
    )


@needs_sqruff
def test_user_config(tmp_path):
    root = tmp_path / "root"
    (root / "case" / "macros").mkdir(parents=True)
    (root / ".sqlfluff").write_text("[sqlfluff]\ndialect = ansi\n")
    (root / "case" / ".sqlfluff").write_text(
        "[sqlfluff]\ntemplater = placeholder\nlibrary_path = other\n"
        "[sqlfluff:templater:jinja]\nload_macros_from_path = macros\n"
    )
    (root / "case" / "a.sql").write_text("select 1\n")
    got = SqruffAdapter().user_config(Path("case/a.sql"), "tsql", root, ["LT01"])
    # sqlfluff keeps a path that it does not find; the templater uses it
    # from the current folder.
    assert got["core"] == {
        "templater": "jinja",
        "library_path": str(root / "other"),
        "rules": "LT01",
        "dialect": "tsql",
    }
    jinja = got["templater"]["jinja"]
    assert jinja["load_macros_from_path"] == str(root / "case" / "macros")


# Never "pass" for a harness fixture where the sqlfluff test fails.


def _expect_fail(case_id: str) -> bool:
    return case_id.rsplit("/", 1)[-1].startswith("expect_fail_")


def _harness_cases():
    out = []
    root = FIXTURES / "dialects"
    out += [(dialects, c, root) for c in dialects.discover(root)]
    for path in sorted((FIXTURES / "rules").glob("*.yml")):
        out += [(rules, c, SQLFLUFF_ROOT) for c in rules.load_file(path)]
    out += [
        (autofix, c, SQLFLUFF_ROOT) for c in autofix.discover_dir(FIXTURES / "autofix")
    ]
    root = FIXTURES / "templater"
    out += [(templater, c, root) for c in templater.discover(root)]
    return [(s, c, r) for s, c, r in out if _expect_fail(c.id)]


@needs_sqruff
@pytest.mark.parametrize(
    "suite, case, root", _harness_cases(), ids=lambda x: getattr(x, "id", "")
)
def test_expect_fail_fixture_never_passes(suite, case, root):
    result = _run_case(suite, case, root)
    assert result.status in (FAIL, ERROR), result.reason


@pytest.mark.parametrize(
    "violations, missing",
    [
        ([{"code": "LT01", "start_line_no": 1, "start_line_pos": 9}], "name, warning"),
        (
            [{"start_line_no": 1, "start_line_pos": 9, "end_line_no": 1}],
            "end_line_no, name, warning",
        ),
    ],
)
def test_check_fields_needs_all_to_dict_keys(violations, missing):
    adapter = SqruffAdapter(Path("/nonexistent"))
    for name in ("violations", "violations_after_fix"):
        case = rules.RuleCase(
            id="rules/LT01/x", rule="LT01", fail_str="x\n", **{name: violations}
        )
        with pytest.raises(Unsupported, match=f"^output field {missing} "):
            rules.check_fields(adapter, case)
    # An empty list compares nothing.
    rules.check_fields(adapter, rules.RuleCase(id="r", rule="LT01", violations=[]))
