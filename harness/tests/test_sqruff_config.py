import configparser

import pytest

from sqll_harness.adapters.base import Unsupported
from sqll_harness.adapters.sqruff_config import (
    SQLFLUFF_DEFAULTS,
    NotRepresentable,
    check,
    is_supported,
    nested_combine,
    translate,
    unsupported_settings,
)


def _read(text: str) -> dict:
    parser = configparser.ConfigParser(delimiters=("=", ":"), interpolation=None)
    parser.read_string(text)
    return {s: dict(parser.items(s)) for s in parser.sections()}


def test_sections_and_values():
    config = {
        "core": {"dialect": "tsql", "max_line_length": 40, "fix_even_unparsable": True},
        "indentation": {"tab_space_size": 2, "indented_joins": False},
        "layout": {"type": {"comma": {"line_position": "leading"}}},
        "rules": {
            "allow_scalar": False,
            "capitalisation.keywords": {"capitalisation_policy": "lower"},
        },
        "templater": {
            "unwrap_wrapped_queries": True,
            "jinja": {"apply_dbt_builtins": False, "context": {"a": "x", "n": 3}},
            "placeholder": {"param_style": "colon", "my_name": "'john'"},
        },
    }
    text = translate(config)
    assert _read(text) == {
        "sqruff": {
            "dialect": "tsql",
            "max_line_length": "40",
            "fix_even_unparsable": "True",
        },
        "sqruff:indentation": {"tab_space_size": "2", "indented_joins": "False"},
        "sqruff:layout:type:comma": {"line_position": "leading"},
        "sqruff:rules": {"allow_scalar": "False"},
        "sqruff:rules:capitalisation.keywords": {"capitalisation_policy": "lower"},
        "sqruff:templater": {"unwrap_wrapped_queries": "True"},
        "sqruff:templater:jinja": {"apply_dbt_builtins": "False"},
        "sqruff:templater:jinja:context": {"a": "x", "n": "3"},
        "sqruff:templater:placeholder": {"param_style": "colon", "my_name": "'john'"},
    }


def test_template_variables_can_be_nested_and_lists():
    config = {
        "templater": {
            "jinja": {
                "context": {
                    "params": {"project_id": "p1"},
                    "tables": ["a", "b"],
                    "none": None,
                }
            },
            "python": {"context": {"my_table": "t"}},
        }
    }
    assert _read(translate(config)) == {
        "sqruff:templater:jinja:context": {
            "params.project_id": "p1",
            "tables": "['a', 'b']",
            "none": "None",
        },
        "sqruff:templater:python:context": {"my_table": "t"},
    }


@pytest.mark.parametrize(
    "config, item",
    [
        # Not in the sqruff documentation.
        ({"rules": {"indent_unit": "tab"}}, "rules.indent_unit"),
        (
            {
                "rules": {
                    "layout.newlines": {"minimum_empty_lines_between_statements": 1}
                }
            },
            "rules.layout.newlines.minimum_empty_lines_between_statements",
        ),
        (
            {"layout": {"type": {"alias_expression": {"align_within": "x"}}}},
            "layout.type.alias_expression.align_within",
        ),
        ({"templater": {"jinja": {"macros": {"m": "x"}}}}, "templater.jinja.macros.m"),
        ({"rules": {"AL03": {"allow_scalar": False}}}, "rules.AL03.allow_scalar"),
        ({"core": {"use_rust_parser": True}}, "core.use_rust_parser"),
        (
            {"indentation": {"allow_implicit_indents": True}},
            "indentation.allow_implicit_indents",
        ),
        (
            {"templater": {"placeholder": {"a": {"b": "c"}}}},
            "templater.placeholder.a.b",
        ),
        ({"other": {"x": 1}}, "other.x"),
        ({"x": 1}, "x"),
        # In the sqruff documentation, but the sqruff source does not read it.
        (
            {"indentation": {"template_blocks_indent": True}},
            "indentation.template_blocks_indent",
        ),
        (
            {"rules": {"capitalisation.types": {"ignore_words": "int"}}},
            "rules.capitalisation.types.ignore_words",
        ),
        (
            {"rules": {"capitalisation.types": {"ignore_words_regex": "^i"}}},
            "rules.capitalisation.types.ignore_words_regex",
        ),
        ({"core": {"output_line_length": 80}}, "core.output_line_length"),
        (
            {"templater": {"jinja": {"library_path": "x"}}},
            "templater.jinja.library_path",
        ),
        ({"templater": {"dbt": {"profile": "p"}}}, "templater.dbt.profile"),
    ],
)
def test_an_unsupported_setting_is_named(config, item):
    assert unsupported_settings(config) == [item]
    with pytest.raises(Unsupported, match=f"^setting {item}$"):
        translate(config)


@pytest.mark.parametrize(
    "value, bad",
    [
        ("templating", []),
        (None, []),
        ("None", []),
        ("parsing", ["core.ignore=parsing"]),
        ("parsing, templating", ["core.ignore=parsing"]),
        (
            ["lexing", "templating", "linting"],
            ["core.ignore=lexing", "core.ignore=linting"],
        ),
    ],
)
def test_ignore_values_that_sqruff_does_not_read(value, bad):
    # sqruff reads only "templating"; "ignore = parsing" has no effect.
    config = {"core": {"ignore": value}}
    assert unsupported_settings(config) == bad
    if bad:
        with pytest.raises(Unsupported) as exc:
            translate(config)
        assert exc.value.item == "setting " + ", ".join(bad)
    else:
        translate(config)


def test_all_unsupported_settings_are_named_sorted():
    config = {"rules": {"tab_space_size": 2, "indent_unit": "tab"}, "core": {"x": 1}}
    with pytest.raises(Unsupported) as exc:
        check(config)
    assert exc.value.item == "setting core.x, rules.indent_unit, rules.tab_space_size"


@pytest.mark.parametrize(
    "path",
    [
        ("core", "templater"),
        ("core", "library_path"),
        ("indentation", "implicit_indents"),
        ("layout", "type", "any_type", "keyword_line_position_exclusions"),
        ("rules", "references.quoting", "case_sensitive"),
        ("rules", "capitalisation.keywords", "ignore_words"),
        ("templater", "jinja", "context", "a", "b", "c"),
        ("templater", "placeholder", "any_param"),
    ],
)
def test_supported(path):
    assert is_supported(path)


def test_upper_case_key_is_unsupported():
    # sqruff makes INI keys lower case; sqlfluff keeps the case.
    config = {"templater": {"placeholder": {"param_style": "colon", "CATALOG": "c"}}}
    with pytest.raises(
        Unsupported, match="upper-case key templater.placeholder.CATALOG"
    ):
        translate(config)


def test_multi_line_value_is_unsupported():
    config = {"templater": {"jinja": {"context": {"a": "x\ny"}}}}
    with pytest.raises(Unsupported, match="multi-line value of templater.jinja"):
        translate(config)


@pytest.mark.parametrize(
    "config, where",
    [
        (
            {"rules": {"references.special_chars": {"ignore_words_regex": "hash#$"}}},
            "rules.references.special_chars.ignore_words_regex",
        ),
        ({"core": {"dialect": "ansi;x"}}, "core.dialect"),
        ({"templater": {"jinja": {"context": {"a": ["x#y"]}}}}, "templater.jinja"),
        ({"templater": {"jinja": {"context": {"a#b": "x"}}}}, "templater.jinja"),
        ({"templater": {"placeholder": {"a;b": "x"}}}, "templater.placeholder"),
        ({"layout": {"type": {"a#b": {"spacing_before": "touch"}}}}, "layout.type"),
    ],
)
def test_ini_comment_character_is_unsupported(config, where):
    # sqruff (configparser Ini::new) cuts an INI line at "#" or ";".
    with pytest.raises(Unsupported, match=f"^comment character '[#;]' in {where}"):
        translate(config)


@pytest.mark.parametrize(
    "config",
    [
        {"core": {"rules": ["LT01"]}},
        {"core": {"dialect": " ansi"}},
        {"templater": {"jinja": {"context": {"a.b": "x"}}}},
        {"templater": {"jinja": {"context": {"a=b": "x"}}}},
    ],
)
def test_not_representable(config):
    with pytest.raises(NotRepresentable):
        translate(config)


def test_nested_combine():
    a = {"core": {"a": 1, "b": 2}, "rules": {"x": {"y": 1}}}
    b = {"core": {"b": 3}, "rules": {"x": {"z": 2}}, "new": {"k": "v"}}
    assert nested_combine(a, None, b) == {
        "core": {"a": 1, "b": 3},
        "rules": {"x": {"y": 1, "z": 2}},
        "new": {"k": "v"},
    }
    assert a == {"core": {"a": 1, "b": 2}, "rules": {"x": {"y": 1}}}


def test_sqlfluff_defaults_layer_is_supported():
    check(SQLFLUFF_DEFAULTS)
    assert SQLFLUFF_DEFAULTS["core"] == {"templater": "jinja", "rules": "all"}
