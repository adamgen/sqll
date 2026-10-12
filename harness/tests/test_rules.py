import dataclasses
import tempfile
import tomllib
from pathlib import Path

import pytest
from conftest import needs_sqlfluff

from sqll_harness.adapters.base import EmptyHome, FixResult, LintResult
from sqll_harness.adapters.sqlfluff import SqlfluffAdapter, sqlfluff_toml
from sqll_harness.cases import FAIL, PASS, SKIP
from sqll_harness.paths import SQLFLUFF_ROOT
from sqll_harness.suites import rules

FIXTURES = Path(__file__).parent / "fixtures" / "rules"
CASES = {c.id: c for c in rules.discover(SQLFLUFF_ROOT)}


def _toml_round_trip(config):
    data = tomllib.loads(sqlfluff_toml(config))
    return data["tool"]["sqlfluff"]


# Discovery


def test_discovery_count():
    cases = rules.discover(SQLFLUFF_ROOT)
    assert len(cases) == 2527
    assert len(CASES) == len(cases)


def test_case_fields():
    case = CASES["rules/AL02/test_fail_explicit_column_explicit"]
    assert case.rule == "AL02"
    assert case.fail_str == "select 1 bar from table1 b"
    assert case.fix_str == "select 1 AS bar from table1 b"
    assert case.configs == {"rules": {"aliasing.column": {"aliasing": "explicit"}}}
    assert case.line_numbers == []
    assert case.pass_str is None
    case = CASES["rules/AL02_LT01/test_alias_expression_align_4515_1"]
    assert case.rule == "AL02, LT01"
    assert rules.rule_codes(case.rule) == ["AL02", "LT01"]
    assert case.fix_str == "select\n    test AS a\nfrom example_table\n"


def test_file_level_configs_apply_to_cases_with_no_configs():
    enabled = {"rules": {"convention.last_select_star": {"force_enable": True}}}
    cv13 = {k: c for k, c in CASES.items() if k.startswith("rules/CV13/")}
    assert cv13["rules/CV13/test_pass_cte_select_star"].configs == enabled
    own = cv13["rules/CV13/test_pass_disabled_by_default"].configs
    assert own == {"rules": {"convention.last_select_star": {"force_enable": False}}}
    assert sum(c.configs == enabled for c in cv13.values()) == len(cv13) - 1


def test_global_config_fixture_of_sqlfluff():
    # The same assertions as test__rule_test_global_config in sqlfluff.
    path = SQLFLUFF_ROOT / "test" / "fixtures" / "rules" / "R001_global_config_test.yml"
    cases = rules.load_file(path)
    assert len(cases) == 2
    assert cases[0].configs["core"]["dialect"] == "ansi"
    assert cases[1].configs["core"]["dialect"] == "exasol"
    assert [c.id for c in cases] == [
        "rules/R001_global_config_test/tc1",
        "rules/R001_global_config_test/tc2",
    ]


def test_unknown_key_is_an_error(tmp_path):
    path = tmp_path / "X.yml"
    path.write_text("rule: LT01\ncase:\n  pass_str: x\n  fixed_str: y\n")
    with pytest.raises(ValueError, match="fixed_str"):
        rules.load_file(path)


def test_missing_rule_is_an_error(tmp_path):
    path = tmp_path / "X.yml"
    path.write_text("case:\n  pass_str: x\n")
    with pytest.raises(ValueError, match="rule"):
        rules.load_file(path)


def test_rule_codes():
    assert rules.rule_codes("LT01") == ["LT01"]
    assert rules.rule_codes("AL05,CV12") == ["AL05", "CV12"]
    assert rules.rule_codes(" CP02 ,  LT01 ") == ["CP02", "LT01"]


@pytest.mark.parametrize(
    "configs, dialect",
    [
        (None, "ansi"),
        ({}, "ansi"),
        ({"rules": {}}, "ansi"),
        ({"core": {"max_line_length": 10}}, "ansi"),
        ({"core": "x"}, "ansi"),
        ({"core": {"dialect": "tsql"}}, None),
    ],
)
def test_default_dialect(configs, dialect):
    assert rules.default_dialect(configs) == dialect


# TOML config


def test_toml_nested_layout_section():
    config = CASES["rules/LT04/leading_commas_allowed"].configs
    assert config == {"layout": {"type": {"comma": {"line_position": "leading"}}}}
    text = sqlfluff_toml(config)
    assert "[tool.sqlfluff.layout.type.comma]" in text
    assert _toml_round_trip(config) == config


def test_toml_rule_name_with_dot_is_one_key():
    config = CASES["rules/AL02/test_fail_explicit_column_explicit"].configs
    text = sqlfluff_toml(config)
    assert '[tool.sqlfluff.rules."aliasing.column"]' in text
    assert _toml_round_trip(config) == config


def test_toml_bools_and_ints_keep_their_type():
    config = {
        **CASES["rules/AL07/test_pass_allow_self_join_alias"].configs,
        **CASES["rules/LT02-indent/test_pass_indented_joins_false"].configs,
        "core": {"max_line_length": 40},
    }
    got = _toml_round_trip(config)
    assert got == config
    assert got["rules"]["aliasing.forbid"]["force_enable"] is True
    assert got["indentation"]["indented_joins"] is False
    assert type(got["core"]["max_line_length"]) is int


def test_toml_multi_line_macro():
    config = CASES["rules/LT15/test_pass_macros_with_embedded_newlines"].configs
    macro = config["templater"]["jinja"]["macros"]["a_macro_def"]
    assert macro.count("\n") > 5
    assert _toml_round_trip(config) == config


def test_toml_lists_in_jinja_context():
    config = CASES["rules/LT02-indent/test_jinja_value_error_6378"].configs
    context = config["templater"]["jinja"]["context"]
    assert context["each_table_cols"][0] == ["aa", "ab", "ac"]
    assert _toml_round_trip(config) == config


def test_toml_round_trip_of_all_case_configs():
    for case in CASES.values():
        if case.configs is not None:
            assert _toml_round_trip(case.configs) == case.configs, case.id


@pytest.mark.parametrize(
    "config", [{"core": {"x": None}}, {"core": {1: "x"}}, {"core": {"x": [None]}}]
)
def test_toml_rejects_values_it_cannot_write(config):
    with pytest.raises(ValueError):
        sqlfluff_toml(config)


# Checks


def _v(code, line, pos, **extra):
    return {"code": code, "start_line_no": line, "start_line_pos": pos, **extra}


def test_pass_problems():
    assert rules.pass_problems([], ["LT01"]) == []
    assert rules.pass_problems([_v("AL01", 1, 1)], ["LT01"]) == []
    assert rules.pass_problems([_v("LT01", 2, 1)], ["LT01"]) == [
        "1 violations of LT01 (lines [2])"
    ]
    # A lexer error also makes a pass_str fail. A warning is a violation.
    assert rules.pass_problems([_v("LXR", 1, 1, description="x")], ["LT01"])
    assert rules.pass_problems([_v("LT01", 1, 1, warning=True)], ["LT01"])


def test_fail_problems():
    ok = [_v("LT01", 1, 5), _v("LT01", 3, 1)]
    assert rules.fail_problems(ok, ["LT01"], [], None, "LT01") == []
    assert rules.fail_problems(ok, ["LT01"], [1, 3], None, "LT01") == []
    assert rules.fail_problems(ok, ["LT01"], [1, 2], None, "LT01") == [
        "line numbers [1, 3], expected [1, 2]"
    ]
    assert rules.fail_problems([], ["LT01"], [], None, "LT01") == [
        "no violation of LT01"
    ]
    # A warning does not count, and an LXR error does not fail a fail_str.
    warn = [_v("LT01", 1, 1, warning=True), _v("LXR", 1, 1)]
    assert rules.fail_problems(warn, ["LT01"], [], None, "LT01") == [
        "no violation of LT01"
    ]
    prs = [_v("PRS", 1, 1, description="bad"), *ok]
    assert rules.fail_problems(prs, ["LT01"], [], None, "LT01") == ["PRS: bad"]
    crash = [_v("LT01", 1, 1, description="Unexpected exception: boom;\nmore")]
    assert rules.fail_problems(crash, ["LT01"], [], None, "LT01") == [
        "rule crash: Unexpected exception: boom;"
    ]


def test_violations_match_adds_missing_code():
    actual = [_v("LT05", 4, 9, description="d")]
    expected = [{"start_line_no": 4, "start_line_pos": 9, "description": "d"}]
    assert rules.violations_match(actual, expected, "LT05")
    assert not rules.violations_match(actual, expected, "LT01")
    assert not rules.violations_match(actual, [], "LT05")


def test_violations_match_order():
    a, b = _v("AL01", 1, 1), _v("LT01", 1, 1)
    c = _v("LT01", 2, 1)
    # The tool output is sorted by line, position, and code.
    assert rules.violations_match([a, b, c], [b, a, c], "x")
    assert rules.violations_match([a, b, c], [a, b, c], "x")
    # The expected list must be in line and position order, as in sqlfluff.
    assert not rules.violations_match([a, b, c], [c, a, b], "x")


def test_fail_problems_compare_all_violations():
    found = [_v("LT01", 1, 1), _v("LT01", 2, 1, warning=True)]
    assert rules.fail_problems(found, ["LT01"], [], found, "LT01") == []
    assert rules.fail_problems(found, ["LT01"], [], found[:1], "LT01") == [
        "violations differ"
    ]


class FakeAdapter:
    """An adapter that gives fixed results and records its calls."""

    name = "fake"

    def __init__(self, lint=None, fixed=None):
        self.lint_violations = lint or {}
        self.fixed = fixed
        self.calls = []

    def lint(self, sql_paths, rules_, dialect, config, workdir):
        self.calls.append(("lint", [p.name for p in sql_paths], rules_, dialect))
        return LintResult({p: self.lint_violations.get(p.name, []) for p in sql_paths})

    def fix(self, sql_path, rules_, dialect, config, workdir):
        self.calls.append(("fix", sql_path.name, rules_, dialect))
        text = sql_path.read_text()
        return FixResult(self.fixed if self.fixed is not None else text)


def test_skip_runs_no_tool():
    case = rules.RuleCase(id="rules/x/y", rule="LT01", skip="why", pass_str="x")
    adapter = FakeAdapter()
    result = rules.run(adapter, case, SQLFLUFF_ROOT)
    assert result.status == SKIP
    assert result.reason == "why"
    assert adapter.calls == []


def test_run_calls_and_checks():
    case = rules.RuleCase(
        id="rules/x/y",
        rule="AL02, LT01",
        pass_str="p",
        fail_str="f",
        fix_str="g",
        configs={"core": {"dialect": "tsql"}},
    )
    adapter = FakeAdapter(lint={"fail.sql": [_v("LT01", 1, 1)]}, fixed="g")
    result = rules.run(adapter, case, SQLFLUFF_ROOT)
    assert result.status == PASS, result.reason
    assert result.checks == {
        "pass_str": True,
        "fail_str": True,
        "fix": True,
        "after_fix": True,
    }
    codes = ["AL02", "LT01"]
    assert adapter.calls == [
        ("lint", ["pass.sql", "fail.sql", "fixed.sql"], codes, None),
        ("fix", "fix.sql", codes, None),
    ]


def test_run_with_no_fix_str_needs_no_change():
    case = rules.RuleCase(id="rules/x/y", rule="LT01", fail_str="f")
    adapter = FakeAdapter(lint={"fail.sql": [_v("LT01", 1, 1)]}, fixed="changed")
    result = rules.run(adapter, case, SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.checks == {"fail_str": True, "fix": False}
    assert result.reason == "fix mismatch"
    assert adapter.calls[0] == ("lint", ["fail.sql"], ["LT01"], "ansi")


def test_run_violations_after_fix():
    after = [_v("LT01", 2, 1)]
    case = rules.RuleCase(
        id="rules/x/y",
        rule="LT01",
        fail_str="f",
        fix_str="g",
        violations_after_fix=after,
    )
    lint = {"fail.sql": [_v("LT01", 1, 1)], "fixed.sql": after}
    result = rules.run(FakeAdapter(lint=lint, fixed="g"), case, SQLFLUFF_ROOT)
    assert result.status == PASS, result.reason
    # With no violations_after_fix, the fixed SQL must have no violation.
    case = rules.RuleCase(id="rules/x/y", rule="LT01", fail_str="f", fix_str="g")
    result = rules.run(FakeAdapter(lint=lint, fixed="g"), case, SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.checks["after_fix"] is False


def test_run_with_empty_strings_checks_nothing():
    # sqlfluff tests the strings for truth, so an empty string is no string.
    case = rules.RuleCase(id="rules/x/y", rule="LT01", pass_str="", fail_str="")
    adapter = FakeAdapter()
    result = rules.run(adapter, case, SQLFLUFF_ROOT)
    assert result.status == PASS
    assert result.checks == {}
    assert adapter.calls == []


# Runs through the sqlfluff binary.


@needs_sqlfluff
def test_wrong_fix_str_gives_fix_mismatch():
    cases = {c.id: c for c in rules.load_file(FIXTURES / "LT01_harness.yml")}
    adapter = SqlfluffAdapter()
    wrong = rules.run(
        adapter, cases["rules/LT01_harness/test_wrong_fix_str"], SQLFLUFF_ROOT
    )
    assert wrong.status == FAIL
    assert wrong.reason == "fix mismatch"
    assert wrong.checks == {"fail_str": True, "fix": False, "after_fix": True}
    right = rules.run(
        adapter, cases["rules/LT01_harness/test_right_fix_str"], SQLFLUFF_ROOT
    )
    assert right.status == PASS, right.reason
    skip = rules.run(adapter, cases["rules/LT01_harness/test_skip"], SQLFLUFF_ROOT)
    assert skip.status == SKIP


@needs_sqlfluff
@pytest.mark.parametrize(
    "case_id",
    [
        "rules/LT04/leading_commas_allowed",
        "rules/LT04/leading_comma_violations",
        "rules/AL07/test_violation_locations",
        "rules/CV03/test_fail_templated",
        "rules/LT05/test_trailing_semicolon_moves",
        "rules/RF01/test_trino_unknown_reference_in_union_join",
        "rules/AL02/test_fail_explicit_column_explicit",
        "rules/AL02_LT01/test_alias_expression_align_4515_1",
        "rules/AL07/test_pass_allow_self_join_alias",
        "rules/LT02-indent/test_pass_indented_joins_false",
        "rules/LT15/test_fail_macros_with_newlines",
        "rules/LT15/test_pass_macros_with_embedded_newlines",
        "rules/LT02-indent/test_jinja_value_error_6378",
        "rules/CV13/test_pass_cte_select_star",
        "rules/CV13/test_fail_cte_explicit_columns",
        "rules/CV13/test_pass_disabled_by_default",
        "rules/AL07/test_fail_avoid_aliases_1",
    ],
)
def test_real_cases_pass(case_id):
    result = rules.run(SqlfluffAdapter(), CASES[case_id], SQLFLUFF_ROOT)
    assert result.status == PASS, result.reason


@needs_sqlfluff
def test_config_changes_the_result():
    # The same SQL passes or fails only by the config. Thus the harness
    # gives the config to sqlfluff.
    case = CASES["rules/CV13/test_fail_cte_explicit_columns"]
    off = {"rules": {"convention.last_select_star": {"force_enable": False}}}
    changed = rules.RuleCase(id=case.id, rule=case.rule, fail_str=case.fail_str)
    result = rules.run(SqlfluffAdapter(), changed, SQLFLUFF_ROOT)
    assert result.checks["fail_str"] is False
    changed = rules.RuleCase(
        id=case.id, rule=case.rule, pass_str=case.fail_str, configs=off
    )
    assert rules.run(SqlfluffAdapter(), changed, SQLFLUFF_ROOT).status == PASS


@needs_sqlfluff
def test_temp_dirs_are_removed(tmp_path, monkeypatch):
    EmptyHome.path()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    case = CASES["rules/LT15/test_fail_macros_with_newlines"]
    assert rules.run(SqlfluffAdapter(), case, SQLFLUFF_ROOT).status == PASS
    assert list(tmp_path.iterdir()) == []


@needs_sqlfluff
def test_lint_ignores_local_config(tmp_path):
    sql = tmp_path / "a.sql"
    sql.write_text("SELECT a  +  b FROM t\n")
    # sqlfluff must not read these files: they exclude all rules.
    (tmp_path / ".sqlfluff").write_text("[sqlfluff]\nexclude_rules = LT01\n")
    (tmp_path / "setup.cfg").write_text("[sqlfluff]\nexclude_rules = LT01\n")
    adapter = SqlfluffAdapter()
    result = adapter.lint([sql], ["LT01"], "ansi", None, tmp_path)
    assert not result.errors
    assert [v["code"] for v in result.violations[sql]] == ["LT01", "LT01"]
    fix = adapter.fix(sql, ["LT01"], "ansi", None, tmp_path)
    assert not fix.errors
    assert fix.fixed == "SELECT a + b FROM t\n"


@needs_sqlfluff
def test_lint_reads_the_toml_config(tmp_path):
    sql = tmp_path / "a.sql"
    sql.write_text("select a from t\n")
    adapter = SqlfluffAdapter()
    config = {"rules": {"capitalisation.keywords": {"capitalisation_policy": "upper"}}}
    result = adapter.lint([sql], ["CP01"], "ansi", config, tmp_path)
    assert [v["code"] for v in result.violations[sql]] == ["CP01", "CP01"]
    config = {"rules": {"capitalisation.keywords": {"capitalisation_policy": "lower"}}}
    result = adapter.lint([sql], ["CP01"], "ansi", config, tmp_path)
    assert result.violations[sql] == []


@needs_sqlfluff
def test_wrong_expected_violations_fail():
    case = CASES["rules/AL07/test_violation_locations"]
    assert rules.run(SqlfluffAdapter(), case, SQLFLUFF_ROOT).status == PASS
    moved = [{**v, "start_line_pos": v["start_line_pos"] + 1} for v in case.violations]
    wrong = dataclasses.replace(case, violations=moved)
    result = rules.run(SqlfluffAdapter(), wrong, SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.reason == "fail_str: violations differ"

    case = CASES["rules/RF01/test_trino_unknown_reference_in_union_join"]
    lines = [n + 1 for n in case.line_numbers]
    wrong = dataclasses.replace(case, line_numbers=lines)
    result = rules.run(SqlfluffAdapter(), wrong, SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.reason.startswith("fail_str: line numbers ")


@needs_sqlfluff
def test_pass_str_with_a_violation_fails():
    wrong = rules.RuleCase(id="rules/x/y", rule="LT01", pass_str="SELECT a  +  b\n")
    result = rules.run(SqlfluffAdapter(), wrong, SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.reason == "pass_str: 2 violations of LT01 (lines [1])"
    wrong = rules.RuleCase(id="rules/x/y", rule="LT01", pass_str="SELECT (\n")
    result = rules.run(SqlfluffAdapter(), wrong, SQLFLUFF_ROOT)
    assert result.reason.startswith("pass_str: PRS: ")
