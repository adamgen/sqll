"""Adapter for sqlfluff with the Rust parser and rules (sqlfluff[rs]).

It is the sqlfluff adapter with the tools/sqlfluff-rs venv and one more
config layer: RUST_CONFIG. The default of use_rust_parser is "auto", which
uses the Python parser with no message when sqlfluffrs does not import. The
layer sets True: then sqlfluff logs a warning if it cannot use the Rust
parser, and the adapter stops the case with an error.

The layer adds only the RUST_CONFIG keys. If the config of a case sets one of
these keys, the case does not run (RustConfigConflict): the layer must not
change a setting of the case. See harness/sqlfluff-rs.md.
"""

import re
import tempfile
from pathlib import Path
from typing import Any

from .base import EmptyHome
from .sqlfluff import CONFIG_NAME, SqlfluffAdapter, sqlfluff_toml

RUST_CONFIG: dict[str, dict[str, Any]] = {
    "core": {"use_rust_parser": True, "use_rust_rules": True}
}
# Linter.parse_rendered logs this warning when use_rust_parser is True and
# the Rust parser cannot load.
FALLBACK_WARNING = "sqlfluffrs not available"
# RustParser.parse logs this warning when it cannot build the Rust parse
# arena. Then the Rust rules do not run.
ARENA_WARNING = "falling back to Python"
# The config file names that sqlfluff reads in a folder (load_config_at_path).
CONFIG_FILES = ("setup.cfg", "tox.ini", "pep8.ini", ".sqlfluff", "pyproject.toml")
# An in-file config line starts with one of these (process_raw_file_for_config).
INLINE_PREFIXES = ("-- sqlfluff", "--sqlfluff")
_RUST_KEY = re.compile("|".join(RUST_CONFIG["core"]), re.IGNORECASE)


class RustConfigConflict(Exception):
    """The case sets a key of RUST_CONFIG. The layer would change it."""


class RustParserNotUsed(Exception):
    """sqlfluff did not use the Rust parser or the Rust rules."""


def with_rust_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return config with the RUST_CONFIG keys added. config does not change."""
    config = dict(config or {})
    core = config.get("core", {})
    if not isinstance(core, dict):
        raise RustConfigConflict(f"the case config 'core' is a {type(core).__name__}")
    for key in RUST_CONFIG["core"]:
        if key in core:
            raise RustConfigConflict(
                f"the case config sets core.{key}; the sqlfluff-rs layer sets it too"
            )
    config["core"] = {**core, **RUST_CONFIG["core"]}
    return config


def check_inline_config(sql_path: Path) -> None:
    """Fail if an in-file config line of the file can set a RUST_CONFIG key.

    The check is on the text, so it can also find a line that does not set
    the key. That gives an error, never a false pass.
    """
    text = sql_path.read_bytes().decode("utf8", errors="replace")
    for line in text.splitlines():
        if line.startswith(INLINE_PREFIXES) and _RUST_KEY.search(line):
            raise RustConfigConflict(
                f"{sql_path.name}: an in-file config line has a sqlfluff-rs "
                f"layer key: {line.strip()!r}"
            )


def user_config_folders(sql_path: Path, cwd: Path, home: Path) -> list[Path]:
    """Return each folder where sqlfluff can read a config file for sql_path.

    This is more than sqlfluff reads (load_config_up_to_path): each parent
    of cwd and of the folder of sql_path, home, and the user appdir.
    """
    folders = [home, home / "sqlfluff", home / ".config" / "sqlfluff"]
    for start in (cwd.resolve(), (cwd / sql_path).resolve().parent):
        folders += [start, *start.parents]
    return list(dict.fromkeys(folders))


def check_user_config(sql_path: Path, cwd: Path, home: Path) -> None:
    """Fail if a config file that sqlfluff can read has a RUST_CONFIG key.

    The check is on the text of each file in user_config_folders, so it can
    find more than sqlfluff reads. That gives an error, never a false pass.
    """
    for folder in user_config_folders(sql_path, cwd, home):
        for name in CONFIG_FILES:
            path = folder / name
            if not path.is_file():
                continue
            text = path.read_bytes().decode("utf8", errors="replace")
            if _RUST_KEY.search(text):
                raise RustConfigConflict(f"{path} has a sqlfluff-rs layer key")
    check_inline_config(cwd / sql_path)


class SqlfluffRsAdapter(SqlfluffAdapter):
    name = "sqlfluff-rs"
    config_layer = RUST_CONFIG

    def __init__(self, venv: Path | None = None) -> None:
        super().__init__(venv)
        # Not in a folder of a case: sqlfluff must not read it as a config
        # file of the user.
        self._layer_dir = tempfile.TemporaryDirectory(prefix="sqll-rs-layer-")
        self._layer_file = Path(self._layer_dir.name) / CONFIG_NAME
        self._layer_file.write_text(sqlfluff_toml(RUST_CONFIG), encoding="utf8")

    def case_config(
        self, config: dict[str, Any] | None, sql_paths: list[Path]
    ) -> dict[str, Any]:
        for path in sql_paths:
            check_inline_config(path)
        return with_rust_config(config)

    def user_config_file(self, sql_path: Path, cwd: Path) -> Path:
        check_user_config(sql_path, cwd, EmptyHome.path())
        return self._layer_file

    def _run(self, cmd, cwd):
        proc = super()._run(cmd, cwd)
        output = proc.stdout + proc.stderr
        if FALLBACK_WARNING in output:
            raise RustParserNotUsed(
                f"sqlfluff used the Python parser: '{FALLBACK_WARNING}'"
            )
        if ARENA_WARNING in output:
            raise RustParserNotUsed(
                f"sqlfluff has no Rust parse arena, so the Rust rules did not "
                f"run: '{ARENA_WARNING}'"
            )
        return proc
