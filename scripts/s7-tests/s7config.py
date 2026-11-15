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
  that the default config does not have, on a value that is not a scalar, on
  a path key, and on a value that does not load again as the same value.
- differences(): the keys with different values in 2 snapshots. The trace
  loads the text as the CLI does and records these differences (the proof);
  the oracle accepts the map only if there is none.
"""

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


def config_text(effective: dict[str, Any], reference: dict[str, Any]) -> str:
    """The .sqlfluff text that gives the effective config over the reference
    (the default config). Empty if they are the same."""
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
        if path not in ref:
            raise ConfigMapError(
                f"{where}: the map knows only the keys of the default config"
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
    order = sorted(sections, key=lambda s: (s != "sqlfluff", s))
    return "\n".join(f"[{s}]\n" + "".join(sections[s]) for s in order)
