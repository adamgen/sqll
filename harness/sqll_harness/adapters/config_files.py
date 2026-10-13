# The file search and the file reading in this file are a port of sqlfluff
# 4.4.0 code: src/sqlfluff/core/config/loader.py (load_config_up_to_path,
# load_config_at_path, _get_user_config_dir_path), file.py
# (_resolve_paths_in_config), ini.py (load_ini_string), and
# src/sqlfluff/core/helpers/file.py (iter_intermediate_paths).
# Copyright (c) 2018-2026 Alan Cruickshank. MIT License. See THIRD_PARTY.md.
"""The config that sqlfluff reads for one SQL file, from the files of the user.

A tool that does not read sqlfluff config files the same way (sqruff) gets
this config through its own config file. The values stay as the INI text
(sqlfluff and sqruff convert them in the same way). A pyproject.toml file
with a [tool.sqlfluff] table is not ported: config_for_file raises
NotPorted.
"""

import configparser
import glob
import os
import tomllib
from pathlib import Path
from typing import Any

from .sqruff_config import nested_combine

# The files that sqlfluff reads in a folder. A later one overrides.
CONFIG_FILES = ("setup.cfg", "tox.ini", "pep8.ini", ".sqlfluff", "pyproject.toml")
COMMA_SEPARATED_PATH_KEYS = (
    "load_macros_from_path",
    "loader_search_path",
    "exclude_macros_from_path",
)
RESOLVE_PATH_SUFFIXES = ("_path", "_dir")
OPAQUE_SECTION = ("templater", "jinja", "context")
# In-file config lines: sqlfluff reads a line that starts with one of these
# (process_raw_file_for_config).
INLINE_PREFIXES = ("-- sqlfluff", "--sqlfluff")


class NotPorted(ValueError):
    """The config has a form that the harness does not read."""


def read_ini(text: str) -> dict[str, Any]:
    """Read a sqlfluff INI config (load_ini_string), with the values as text.

    [sqlfluff] is "core", [sqlfluff:a:b] is ("a", "b"), and a key is split
    on ".". Keys keep their case.
    """
    parser = configparser.ConfigParser(delimiters="=", interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read_string(text)
    records = []
    for section in parser.sections():
        if section == "sqlfluff":
            prefix: tuple[str, ...] = ("core",)
        elif section.startswith("sqlfluff:"):
            prefix = tuple(section[len("sqlfluff:") :].split(":"))
        else:
            continue
        for name, value in parser.items(section):
            records.append((prefix + tuple(name.split(".")), value))
    out: dict[str, Any] = {}
    for path, value in records:
        node = out
        for key in path[:-1]:
            node = node.setdefault(key, {})
            if not isinstance(node, dict):
                raise NotPorted(f"a value and a section have the name {key!r}")
        node[path[-1]] = value
    return out


def _resolve_path(config_file: Path, value: str) -> list[str]:
    return glob.glob(os.path.join(os.path.dirname(config_file), value))


def resolve_paths(config: dict[str, Any], config_file: Path, prefix=()) -> None:
    """Make the path values relative to the folder of the config file, as
    sqlfluff does (_resolve_paths_in_config). A path that does not exist
    stays as it is."""
    for key, value in config.items():
        path = prefix + (key.lower(),)
        if isinstance(value, dict):
            if path != OPAQUE_SECTION:
                resolve_paths(value, config_file, path)
        elif key.lower() in COMMA_SEPARATED_PATH_KEYS:
            parts = [p.strip() for p in str(value).split(",") if p.strip()]
            found = [r for p in parts for r in _resolve_path(config_file, p)]
            config[key] = ",".join(found) if found else value
        elif key.lower().endswith(RESOLVE_PATH_SUFFIXES):
            found = _resolve_path(config_file, str(value))
            config[key] = found[0] if found else value


def read_file(path: Path) -> dict[str, Any]:
    """Read one config file (load_config_file_as_dict)."""
    text = path.read_bytes().decode("utf8")
    if path.name == "pyproject.toml":
        if "sqlfluff" in tomllib.loads(text).get("tool", {}):
            raise NotPorted(f"{path}: the harness does not read [tool.sqlfluff]")
        return {}
    config = read_ini(text)
    resolve_paths(config, path)
    return config


def read_folder(folder: Path) -> dict[str, Any]:
    """Read the config files of a folder (load_config_at_path)."""
    return nested_combine(
        *(read_file(folder / n) for n in CONFIG_FILES if (folder / n).is_file())
    )


def intermediate_paths(inner: Path, outer: Path) -> list[Path]:
    """Port of iter_intermediate_paths: the common path of inner and outer,
    then each folder down to inner. inner is a file or a folder."""
    inner, outer = inner.absolute(), outer.absolute()
    if not inner.is_dir():
        inner = inner.parent
    common = Path(os.path.commonpath([inner, outer]))
    out = []
    folder = common
    while folder != inner:
        out.append(folder.resolve())
        folder = folder / inner.relative_to(folder).parts[0]
    out.append(inner.resolve())
    return out


def appdir(home: Path) -> Path:
    """The user config folder of sqlfluff on Linux, with XDG_CONFIG_HOME set
    to home (adapters.base.isolated_env)."""
    legacy = home / ".config" / "sqlfluff"
    return legacy if legacy.exists() else home / "sqlfluff"


def config_folders(sql_path: Path, cwd: Path, home: Path) -> list[Path]:
    """The folders of load_config_up_to_path for a file, in load order:
    the appdir, home, the folders between home and the file, then the
    folders from the common path of cwd and the file down to the file."""
    path = cwd / sql_path
    between = intermediate_paths(path, home)[1:-1]
    return [appdir(home), home, *between, *intermediate_paths(path, cwd)]


def config_for_file(sql_path: Path, cwd: Path, home: Path) -> dict[str, Any]:
    """The config that sqlfluff reads for the file from the files of the
    user, before the CLI options and the in-file config lines."""
    return nested_combine(
        *(read_folder(f) for f in config_folders(sql_path, cwd, home) if f.is_dir())
    )


def inline_config(sql: str) -> dict[str, Any]:
    """The in-file config lines that sqlfluff reads, as a config.

    As in sqlfluff (process_raw_file_for_config and process_inline_config),
    the line starts with "-- sqlfluff" or "--sqlfluff", with no space before
    it. The text after "sqlfluff:" is split on ":". One key is in "core".
    """
    out: dict[str, Any] = {}
    for line in sql.splitlines():
        if not line.startswith(INLINE_PREFIXES):
            continue
        text = line[2:].strip()
        if not text.startswith("sqlfluff:"):
            continue
        *keys, value = (p.strip() for p in text[len("sqlfluff:") :].split(":"))
        if not keys:
            continue
        path = ("core", *keys) if len(keys) == 1 else tuple(keys)
        node = out
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = value
    return out
