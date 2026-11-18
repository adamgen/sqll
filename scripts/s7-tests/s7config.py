"""The config model of the S7 trace oracle (docs/decisions/s7-tests-design.md,
"Trace oracle", "Config model").

trace-nodes uses it with the Python of a pinned oracle. A Linter string call
(Linter.lint_string, lint_string_wrapped) uses the config of its Linter and
no config file. The oracle maps the call to a CLI case that reads stdin in a
temporary folder with a .sqlfluff file. This module gives the text of that
file from the config of the Linter:

- snapshot(): the values of a config as JSON data. An object is
  {"<object>": "<module>.<class>"} (and "name" if it has a text name).
- config_text(): each value of the config that is not the value of the
  default config, as an ini text. It fails closed (ConfigMapError) on a key
  that the default config does not have and that is not an extra key
  (EXTRA_KEYS), on a value that is not a scalar, on a path key, and on a
  value that does not load again as the same value.
- differences(): the keys with different values in 2 snapshots. The trace
  loads the text as the CLI does and records these differences (the proof);
  the oracle accepts the map only if there is none.
- templater_text(): the .sqlfluff text of a templater process() call (the
  templater map of S6, templater parity; docs/decisions/s6-templaters.md,
  "Black-box form"): the config of the call with core.templater, and the
  override_context of the templater in the section of its context. The
  trace proves it for each call: the templater result of the CLI run with
  this file must be the result of the call.
"""

import ast
import copy
import math
import re
from typing import Any

OBJECT = "<object>"
CONFIG_FILE = ".sqlfluff"
# The keys that FluffConfig.__init__ derives from other keys. The file gives
# the source keys; the CLI derives these again (the proof compares them).
DERIVED = frozenset(
    {
        ("core", "color"),
        ("core", "rule_allowlist"),
        ("core", "rule_denylist"),
        ("core", "dialect_obj"),
        ("core", "templater_obj"),
    }
)
# sqlfluff resolves a key with one of these suffixes as a path relative to
# the config file (sqlfluff.core.config.file.RESOLVE_PATH_SUFFIXES).
PATH_SUFFIXES = ("_path", "_dir")
# The keys that the default config does not have and that the map knows
# (T18): a key matches a pattern of the same length, and "*" matches each
# name. sqlfluff reads them only with get_section, so a config file gives
# them as the same value (the proof checks each one):
# - the Jinja context (JinjaTemplater.get_context);
# - the Jinja delimiters (JinjaTemplater._get_jinja_env_kwargs);
# - the keys of a layout type that a config file can give
#   (sqlfluff.core.config.validate.ALLOWABLE_LAYOUT_CONFIG_KEYS; the reflow
#   config reads them), for example align_scope.
JINJA_DELIMITERS = (
    "variable_start_string",
    "variable_end_string",
    "block_start_string",
    "block_end_string",
    "comment_start_string",
    "comment_end_string",
)
LAYOUT_KEYS = (
    "spacing_before",
    "spacing_after",
    "spacing_within",
    "line_position",
    "align_within",
    "align_scope",
    "keyword_line_position",
    "keyword_line_position_exclusions",
    "alignment_coordinate_space",
)
EXTRA_KEYS = (
    ("templater", "jinja", "context", "*"),
    *(("templater", "jinja", key) for key in JINJA_DELIMITERS),
    *(("layout", "type", "*", key) for key in LAYOUT_KEYS),
)
_KEY = re.compile(r"^[A-Za-z0-9_]+$")
_SECTION = re.compile(r"^[A-Za-z0-9_.]+$")


class ConfigMapError(Exception):
    """The config has a value that the map does not know."""


def snapshot(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): snapshot(v) for k, v in value.items()}
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, list | tuple):
        return [snapshot(v) for v in value]
    kind = type(value)
    out = {OBJECT: f"{kind.__module__}.{kind.__qualname__}"}
    name = getattr(value, "name", None)
    if isinstance(name, str):
        out["name"] = name
    return out


def leaves(data: dict[str, Any], prefix: tuple[str, ...] = ()):
    for key, value in data.items():
        path = (*prefix, key)
        if isinstance(value, dict) and OBJECT not in value:
            yield from leaves(value, path)
        else:
            yield path, value


def is_extra(path: tuple[str, ...]) -> bool:
    """True if the key matches a pattern of EXTRA_KEYS."""
    return any(
        len(pattern) == len(path)
        and all(p in ("*", k) for p, k in zip(pattern, path, strict=True))
        for pattern in EXTRA_KEYS
    )


def same(a: Any, b: Any) -> bool:
    return a == b and type(a) is type(b)


def differences(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """The paths (keys joined with ":") that have different values."""
    left, right = dict(leaves(a)), dict(leaves(b))
    return sorted(
        ":".join(path)
        for path in set(left) | set(right)
        if path not in left or path not in right or not same(left[path], right[path])
    )


def value_text(path: tuple[str, ...], value: Any) -> str:
    """The ini text of a value. It must load again as the same value."""
    from sqlfluff.core.config.ini import coerce_value

    where = ":".join(path)
    if isinstance(value, bool):
        text = "True" if value else "False"
    elif value is None:
        text = "None"
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, float) and math.isfinite(value):
        text = repr(value)
    elif isinstance(value, str):
        if "\n" in value or "\r" in value or value != value.strip():
            raise ConfigMapError(f"{where}: the text {value!r} is not one ini line")
        text = value
    else:
        raise ConfigMapError(f"{where}: the value {value!r} is not a scalar")
    if not same(coerce_value(text), value):
        raise ConfigMapError(f"{where}: the text {text!r} loads as another value")
    return text


def config_sections(
    effective: dict[str, Any], reference: dict[str, Any]
) -> dict[str, list[str]]:
    """The ini lines of each section that give the effective config over the
    reference (the default config)."""
    ref = dict(leaves(reference))
    eff = dict(leaves(effective))
    missing = sorted(":".join(p) for p in set(ref) - set(eff) if p not in DERIVED)
    if missing:
        raise ConfigMapError(f"the config has no value for the default keys {missing}")
    sections: dict[str, list[str]] = {}
    for path in sorted(eff):
        value = eff[path]
        if path in DERIVED or (path in ref and same(ref[path], value)):
            continue
        where = ":".join(path)
        if path not in ref and not is_extra(path):
            raise ConfigMapError(
                f"{where}: the map knows only the keys of the default config"
                " and the extra keys"
            )
        if len(path) < 2 or (path[0] == "core" and len(path) != 2):
            raise ConfigMapError(f"{where}: not a key of a config section")
        key = path[-1]
        if key.lower().endswith(PATH_SUFFIXES):
            raise ConfigMapError(f"{where}: a path key (resolved relative to a file)")
        if not _KEY.match(key) or not all(_SECTION.match(p) for p in path[:-1]):
            raise ConfigMapError(f"{where}: a name that an ini file cannot give")
        section = "sqlfluff" if path[0] == "core" else "sqlfluff:" + ":".join(path[:-1])
        sections.setdefault(section, []).append(f"{key} = {value_text(path, value)}\n")
    return sections


def sections_text(sections: dict[str, list[str]]) -> str:
    order = sorted(sections, key=lambda s: (s != "sqlfluff", s))
    return "\n".join(f"[{s}]\n" + "".join(sections[s]) for s in order)


def config_text(effective: dict[str, Any], reference: dict[str, Any]) -> str:
    """The .sqlfluff text that gives the effective config over the reference
    (the default config). Empty if they are the same."""
    return sections_text(config_sections(effective, reference))


# The templater map of S6 (templater parity; docs/decisions/s6-templaters.md,
# "Black-box form"): the section of the context of each templater that the
# map knows. A PlaceholderTemplater reads its context from
# [sqlfluff:templater:placeholder], a PythonTemplater from
# [sqlfluff:templater:python:context].
TEMPLATER_SECTIONS = {
    "placeholder": "sqlfluff:templater:placeholder",
    "python": "sqlfluff:templater:python:context",
}
# A context key: the ini delimiter is "=", so a key can have ":" and "."
# (for example "flyway:database" of the flyway_var style).
_CONTEXT_KEY = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:]*$")
# The core keys that FluffConfig splits into a list of texts at the commas
# (FluffConfig._handle_comma_separated_values). The file gives the texts
# with commas.
COMMA_KEYS = ("ignore", "warnings")


def context_text(where: str, value: Any) -> str:
    """The ini text of a context value of a templater: a scalar as
    value_text gives it (with no check of the type that the loader gives:
    the trace proves the templater output), or a list or a dict as its
    Python literal on one line (the python templater evaluates it with
    ast.literal_eval). Fail closed on each other value."""
    if value is None or isinstance(value, bool | int):
        return value_text((where,), value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigMapError(f"{where}: the value {value!r} is not finite")
        return repr(value)
    if isinstance(value, str):
        if "\n" in value or "\r" in value or value != value.strip():
            raise ConfigMapError(f"{where}: the text {value!r} is not one ini line")
        return value
    if isinstance(value, list | dict):
        text = repr(value)
        try:
            same_value = ast.literal_eval(text) == value
        except (SyntaxError, ValueError):
            same_value = False
        if "\n" in text or "\r" in text or not same_value:
            raise ConfigMapError(
                f"{where}: the value {value!r} is not one literal line"
            )
        return text
    raise ConfigMapError(f"{where}: the value {value!r} is not a literal")


def templater_text(
    name: str,
    context: dict[str, Any],
    effective: dict[str, Any],
    reference: dict[str, Any],
) -> str:
    """The .sqlfluff text of a templater call (S6 map): the effective config
    of the call with core.templater = name, and the context of the templater
    in the section of its context."""
    if name not in TEMPLATER_SECTIONS:
        raise ConfigMapError(
            f"the templater {name!r}; the map knows only {list(TEMPLATER_SECTIONS)}"
        )
    core = effective.get("core", {})
    if not same(core.get("templater"), reference["core"]["templater"]):
        raise ConfigMapError(f"the config sets the templater {core.get('templater')!r}")
    eff = copy.deepcopy(effective)
    eff["core"]["templater"] = name
    for key in COMMA_KEYS:
        value = eff["core"].get(key)
        if isinstance(value, list) and value:
            if not all(isinstance(v, str) and v and "," not in v for v in value):
                raise ConfigMapError(f"core:{key}: the value {value!r} is not texts")
            eff["core"][key] = ",".join(value)
    sections = config_sections(eff, reference)
    section = TEMPLATER_SECTIONS[name]
    if section in sections:
        raise ConfigMapError(
            f"the config sets keys of [{section}]; the map gives that section from"
            " the context of the templater"
        )
    lines = []
    for key, value in context.items():
        where = f"{section}:{key}"
        if not isinstance(key, str) or not _CONTEXT_KEY.match(key):
            raise ConfigMapError(f"{where}: a name that an ini file cannot give")
        lines.append(f"{key} = {context_text(where, value)}\n")
    if lines:
        sections[section] = lines
    return sections_text(sections)
