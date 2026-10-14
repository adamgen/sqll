# The setting names in this file are from the sqruff 0.41.0 documentation:
# crates/lib/src/core/default_config.cfg (the full list of settings),
# docs/usage/configuration.md, and docs/reference/templaters.md.
# Source: https://github.com/quarylabs/sqruff. Apache License 2.0.
# See THIRD_PARTY.md.
"""Translate a sqlfluff config into a sqruff config file (.sqruff, INI).

The input is a config in the sqlfluff structure, for example
{"core": {"dialect": "ansi"}, "rules": {"capitalisation.keywords": {...}}}.
A setting is supported only if the sqruff documentation has it and the
sqruff 0.41.0 source reads it (NOT_READ). For another setting, translate()
raises Unsupported, and the case fails with a reason that starts with
"unsupported:". sqruff can read some settings that its documentation does
not have; the harness does not use them.
"""

import ast
from typing import Any

from .base import Unsupported

# [sqruff] in default_config.cfg, and library_path (the --library-path option
# and templaters.md).
CORE = frozenset(
    {
        "max_parse_depth",
        "max_parse_nodes",
        "verbose",
        "nocolor",
        "dialect",
        "templater",
        "rules",
        "exclude_rules",
        "output_line_length",
        "runaway_limit",
        "ignore",
        "warnings",
        "warn_unused_ignores",
        "ignore_templated_areas",
        "encoding",
        "disable_noqa",
        "disable_noqa_except",
        "sql_file_exts",
        "fix_even_unparsable",
        "large_file_skip_char_limit",
        "large_file_skip_byte_limit",
        "large_file_skip_fail",
        "max_line_length",
        "render_variant_limit",
        "library_path",
    }
)
INDENTATION = frozenset(
    {
        "indent_unit",
        "tab_space_size",
        "indented_joins",
        "indented_ctes",
        "indented_using_on",
        "indented_on_contents",
        "indented_then",
        "indented_then_contents",
        "implicit_indents",
        "template_blocks_indent",
        "skip_indentation_in",
        "skip_implicit_indents_in",
        "trailing_comments",
        "ignore_comment_lines",
    }
)
# [sqruff:layout:type:<type>] for each segment type.
LAYOUT = frozenset(
    {
        "spacing_before",
        "spacing_after",
        "spacing_within",
        "line_position",
        "keyword_line_position",
        "keyword_line_position_exclusions",
    }
)
RULES_ROOT = frozenset(
    {"allow_scalar", "single_table_references", "unquoted_identifiers_policy"}
)
_IGNORE_WORDS = ("ignore_words", "ignore_words_regex")
RULES: dict[str, frozenset[str]] = {
    name: frozenset(keys)
    for name, keys in {
        "capitalisation.keywords": ("capitalisation_policy", *_IGNORE_WORDS),
        "capitalisation.identifiers": (
            "extended_capitalisation_policy",
            *_IGNORE_WORDS,
        ),
        "capitalisation.functions": ("extended_capitalisation_policy", *_IGNORE_WORDS),
        "capitalisation.literals": ("capitalisation_policy", *_IGNORE_WORDS),
        "capitalisation.types": ("extended_capitalisation_policy", *_IGNORE_WORDS),
        "ambiguous.join": ("fully_qualify_join_types",),
        "ambiguous.column_references": ("group_by_and_order_by_style",),
        "aliasing.table": ("aliasing",),
        "aliasing.column": ("aliasing",),
        "aliasing.unused": ("alias_case_check",),
        "aliasing.length": ("min_alias_length", "max_alias_length"),
        "aliasing.forbid": ("force_enable",),
        "convention.select_trailing_comma": ("select_clause_trailing_comma",),
        "convention.count_rows": ("prefer_count_1", "prefer_count_0"),
        "convention.terminator": ("multiline_newline", "require_final_semicolon"),
        "convention.blocked_words": ("blocked_words", "blocked_regex", "match_source"),
        "convention.quoted_literals": (
            "preferred_quoted_literal_style",
            "force_enable",
        ),
        "convention.casting_style": ("preferred_type_casting_style",),
        "postgres.excessive_locks": ("force_enable",),
        "postgres.not_valid_foreign_key": ("force_enable",),
        "tsql.prefer_as_alias": ("force_enable",),
        "convention.not_equal": ("preferred_not_equal_style",),
        "references.from": ("force_enable",),
        "references.qualification": (
            *_IGNORE_WORDS,
            "subqueries_ignore_external_references",
        ),
        "references.consistent": ("force_enable",),
        "references.keywords": (
            "unquoted_identifiers_policy",
            "quoted_identifiers_policy",
            *_IGNORE_WORDS,
        ),
        "references.special_chars": (
            "unquoted_identifiers_policy",
            "quoted_identifiers_policy",
            "allow_space_in_identifier",
            "additional_allowed_characters",
            *_IGNORE_WORDS,
        ),
        "references.quoting": (
            "prefer_quoted_identifiers",
            "prefer_quoted_keywords",
            "prefer_quoted_keyword_style",
            *_IGNORE_WORDS,
            "case_sensitive",
        ),
        "references.window_alias": ("force_enable",),
        "layout.long_lines": ("ignore_comment_lines", "ignore_comment_clauses"),
        "layout.select_targets": ("wildcard_policy", "single_target_policy"),
        "layout.newlines": (
            "maximum_empty_lines_between_statements",
            "maximum_empty_lines_inside_statements",
            "maximum_empty_lines_between_batches",
        ),
        "structure.subquery": ("forbid_subquery_in",),
        "structure.join_condition_order": ("preferred_first_table_in_join_clause",),
    }.items()
}
TEMPLATER_ROOT = frozenset({"unwrap_wrapped_queries"})
# Documented settings that the sqruff 0.41.0 source does not read. sqruff
# reads templater.jinja.library_paths, not library_path.
NOT_READ = frozenset(
    {
        ("core", "output_line_length"),
        ("indentation", "template_blocks_indent"),
        ("rules", "capitalisation.types", "ignore_words"),
        ("rules", "capitalisation.types", "ignore_words_regex"),
        ("templater", "jinja", "library_path"),
        ("templater", "dbt", "profile"),
    }
)
# configparser (Ini::new) cuts an INI line at the first of these characters.
INI_COMMENT_CHARS = "#;"
# templaters.md. A section in OPEN_SECTIONS takes any key: template variables
# or placeholder parameters.
TEMPLATERS: dict[str, frozenset[str]] = {
    "jinja": frozenset(
        {
            "apply_dbt_builtins",
            "load_macros_from_path",
            "exclude_macros_from_path",
            "loader_search_path",
            "library_path",
            "ignore_templating",
        }
    ),
    "placeholder": frozenset({"param_style", "param_regex"}),
    "python": frozenset(),
    "dbt": frozenset(
        {
            "project_dir",
            "profiles_dir",
            "profile",
            "target",
            "dbt_skip_compilation_error",
        }
    ),
    "sqlmesh": frozenset({"project_dir", "config", "gateway"}),
}
CONTEXT_SECTIONS = (
    ("templater", "jinja", "context"),
    ("templater", "python", "context"),
    ("templater", "dbt", "context"),
)
OPEN_SECTIONS = (*CONTEXT_SECTIONS, ("templater", "placeholder"))

# The sqlfluff 4.4.0 defaults that differ from the sqruff 0.41.0 defaults, for
# documented sqruff settings. The fixtures expect the sqlfluff defaults, so
# the adapter adds this layer under the config of each case. sqruff stops on
# the layout types alias_column_list and semantic_view, so their sqlfluff
# defaults are not in the layer.
SQLFLUFF_DEFAULTS: dict[str, Any] = {
    "core": {"templater": "jinja", "rules": "all"},
    "layout": {"type": {"match_condition": {"spacing_within": "touch:inline"}}},
}


class NotRepresentable(ValueError):
    """The value cannot be written in a sqruff INI file. This is a limit of
    the harness, not of sqruff: the case status is "error"."""


def flatten(config: dict[str, Any], prefix: tuple[str, ...] = ()):
    """Yield (path, value) for each setting. A value is not a dict."""
    for key, value in config.items():
        if isinstance(value, dict):
            yield from flatten(value, prefix + (key,))
        else:
            yield prefix + (key,), value


def nested_combine(*configs: dict[str, Any] | None) -> dict[str, Any]:
    """Merge configs. A later config overrides an earlier one, key by key."""
    out: dict[str, Any] = {}
    for config in configs:
        for key, value in (config or {}).items():
            if isinstance(value, dict) and isinstance(out.get(key), dict):
                out[key] = nested_combine(out[key], value)
            elif isinstance(value, dict):
                out[key] = nested_combine(value)
            else:
                out[key] = value
    return out


def _open_section(path: tuple[str, ...]) -> tuple[str, ...] | None:
    for section in OPEN_SECTIONS:
        if path[: len(section)] == section and len(path) > len(section):
            return section
    return None


def is_supported(path: tuple[str, ...]) -> bool:
    """Return True if the sqruff documentation has this setting and sqruff
    reads it."""
    if path in NOT_READ:
        return False
    match path:
        case ("core", key):
            return key in CORE
        case ("indentation", key):
            return key in INDENTATION
        case ("layout", "type", _, key):
            return key in LAYOUT
        case ("rules", key):
            return key in RULES_ROOT
        case ("rules", name, key):
            return key in RULES.get(name, ())
        case ("templater", key):
            return key in TEMPLATER_ROOT
        case ("templater", name, key) if key in TEMPLATERS.get(name, ()):
            return True
    section = _open_section(path)
    if section is None:
        return False
    # A placeholder parameter is one key; a template variable can be nested.
    return section in CONTEXT_SECTIONS or len(path) == len(section) + 1


def unsupported_settings(config: dict[str, Any] | None) -> list[str]:
    """Return the settings of config that sqruff does not support, sorted."""
    return sorted(
        ".".join(path) for path, _ in flatten(config or {}) if not is_supported(path)
    )


def check(config: dict[str, Any] | None) -> None:
    """Raise Unsupported if config has a setting that sqruff does not
    support."""
    bad = unsupported_settings(config)
    if bad:
        raise Unsupported("setting " + ", ".join(bad))


def _ini_value(path: tuple[str, ...], value: Any) -> str:
    """Return the INI text of a value.

    sqruff reads an INI value as an int, a float, a bool ("true", "false"),
    None ("none"), or else a string, as sqlfluff does. A list is only a
    template variable: the templater reads the text with ast.literal_eval.
    """
    text = _ini_text(path, value)
    _no_comment_char(".".join(path), text)
    return text


def _ini_text(path: tuple[str, ...], value: Any) -> str:
    where = ".".join(path)
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        text = repr(value)
        if _open_section(path) in CONTEXT_SECTIONS and ast.literal_eval(text) == value:
            return text
        raise NotRepresentable(f"{where}: a list value")
    if not isinstance(value, str):
        raise NotRepresentable(f"{where}: a value of type {type(value).__name__}")
    if "\n" in value or "\r" in value:
        raise Unsupported(
            f"multi-line value of {where} (sqruff reads INI values on one line)"
        )
    if value != value.strip():
        raise NotRepresentable(f"{where}: INI removes the spaces around a value")
    return value


def _no_comment_char(where: str, text: str) -> None:
    found = [c for c in INI_COMMENT_CHARS if c in text]
    if found:
        raise Unsupported(
            f"comment character {found[0]!r} in {where} (sqruff reads the rest "
            "of an INI line as a comment)"
        )


def _ini_key(path: tuple[str, ...], key: str) -> str:
    where = ".".join(path)
    if key != key.lower():
        raise Unsupported(f"upper-case key {where} (sqruff makes INI keys lower case)")
    if any(c in key for c in "=:[]") or not key:
        raise NotRepresentable(f"{where}: the key cannot be an INI key")
    _no_comment_char(where, key)
    return key


def translate(config: dict[str, Any] | None) -> str:
    """Return the text of a .sqruff file for a config in the sqlfluff
    structure. Raise Unsupported for a setting that sqruff does not
    support, or for a key or value that sqruff reads in another way."""
    config = config or {}
    check(config)
    sections: dict[str, list[str]] = {}
    for path, value in flatten(config):
        open_section = _open_section(path)
        if open_section is not None:
            # sqruff (as sqlfluff) splits a key on "." into nested keys.
            section_path, key_parts = open_section, path[len(open_section) :]
            for part in key_parts:
                _ini_key(path, part)
                if "." in part:
                    raise NotRepresentable(f"{'.'.join(path)}: a key with '.'")
            key = ".".join(key_parts)
        else:
            section_path, key = path[:-1], _ini_key(path, path[-1])
        for part in section_path:
            _no_comment_char(".".join(path), part)
        name = (
            "sqruff"
            if section_path == ("core",)
            else "sqruff:" + ":".join(section_path)
        )
        if name != name.lower():
            raise Unsupported(
                f"upper-case key {'.'.join(path)} (sqruff makes INI section "
                "names lower case)"
            )
        sections.setdefault(name, []).append(f"{key} = {_ini_value(path, value)}")
    return "".join(
        f"[{name}]\n" + "".join(line + "\n" for line in lines) + "\n"
        for name, lines in sections.items()
    )
