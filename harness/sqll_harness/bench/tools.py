"""The benchmark adapters of sqlfluff, sqlfluff[rs], and sqruff.

They use the S1 adapters for the binary, the version, and the config
translation: sqlfluff_toml, the sqlfluff-rs RUST_CONFIG layer, and the
sqruff layer (SQLFLUFF_DEFAULTS) and .sqruff translation. Commands:
harness/README.md, "Benchmark adapters".
"""

import json
import re
import subprocess
import tempfile
from functools import cached_property
from pathlib import Path
from typing import Any

from ..adapters.base import EmptyHome, Unsupported, isolated_env
from ..adapters.sqlfluff import CONFIG_NAME as SQLFLUFF_CONFIG
from ..adapters.sqlfluff import SqlfluffAdapter, sqlfluff_toml
from ..adapters.sqlfluff_rs import ARENA_WARNING, FALLBACK_WARNING, with_rust_config
from ..adapters.sqruff import CONFIG_NAME as SQRUFF_CONFIG
from ..adapters.sqruff import SqruffAdapter, sqruff_env, to_violation
from ..adapters.sqruff_config import SQLFLUFF_DEFAULTS, nested_combine, translate
from ..compare import strip_positions
from ..paths import tools_dir
from .adapter import FIX, LINT, PARSE, BenchAdapter
from .inputs import START

TIMEOUT_S = 120
# Prints the dialect names (labels) of the package argv[1] in the venv, as
# tools._IMPORT_CHECK does. The output of "sqlfluff dialects" wraps a long
# name, so the adapter does not read it.
_LIST_DIALECTS = (
    "import importlib, sys;"
    "m = importlib.import_module(sys.argv[1]);"
    "print(' '.join(d.label for d in m.list_dialects()))"
)


class SqlfluffBench(BenchAdapter):
    name = "sqlfluff"
    venv_name = "sqlfluff"
    problems = (
        # Linter.load_raw_file_and_config (byte limit) and the char limit of
        # the templater. Exit code 0.
        (
            re.compile(r"over the limit of \d+|Skipping to avoid parser lock"),
            "the tool skipped the file (size limit)",
        ),
        # BaseRule (allowlist and denylist); then the rule does not run.
        (re.compile(r"unknown rules? references", re.IGNORECASE), "unknown rule"),
        # "sqlfluff fix" does not fix a file with parse errors.
        (
            re.compile(r"templating/parsing errors found"),
            "the tool did not fix the file (parse errors)",
        ),
    )
    commands = {
        START: ["parse", "-f", "json"],
        PARSE: ["parse", "-f", "json"],
        LINT: ["lint", "-f", "json"],
        FIX: ["fix"],
    }

    def __init__(self, root: Path | None = None) -> None:
        super().__init__()
        self.s1 = SqlfluffAdapter((root or tools_dir()) / self.venv_name)

    def version(self) -> str:
        return self.s1.version()

    @cached_property
    def dialects(self) -> frozenset[str]:
        self.s1._check()
        python = self.s1.venv / "bin" / "python"
        with tempfile.TemporaryDirectory(prefix="sqll-bench-") as tmp:
            proc = subprocess.run(
                [str(python), "-I", "-c", _LIST_DIALECTS, "sqlfluff"],
                cwd=tmp,
                capture_output=True,
                text=True,
                env=self.env(),
                timeout=TIMEOUT_S,
            )
        names = frozenset(proc.stdout.split())
        if proc.returncode != 0 or not names:
            raise RuntimeError(
                f"{self.name}: no dialect list: exit code {proc.returncode}: "
                f"{proc.stderr[-300:]}"
            )
        return names

    def unsupported(self, config: dict[str, Any]) -> str | None:
        dialect = config["core"].get("dialect")
        if dialect is not None and dialect not in self.dialects:
            return f"dialect {dialect}"
        return None

    def write_config(self, config: dict[str, Any], folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / SQLFLUFF_CONFIG
        path.write_text(sqlfluff_toml(config), encoding="utf8")
        return path

    def argv(self, command: str, config_file: Path, sql: str) -> list[str]:
        # --ignore-local-config: sqlfluff reads only the --config file (and
        # no file in a folder of the run), as in the S1 dialects suite.
        return [
            str(self.s1.binary),
            *self.commands[command],
            "--ignore-local-config",
            "--config",
            str(config_file),
            sql,
        ]

    def env(self) -> dict[str, str]:
        return isolated_env(EmptyHome.path())

    def read_tree(self, stdout: bytes, sql: str) -> Any:
        records = json.loads(stdout)
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError(f"not 1 parse record: {str(records)[:100]}")
        if records[0]["filepath"] != sql:
            raise ValueError(f"the record is for {records[0]['filepath']!r}")
        return records[0]["segments"]

    def read_violations(self, stdout: bytes, sql: str) -> list[dict] | None:
        records = json.loads(stdout)
        if not isinstance(records, list):
            raise ValueError("the lint output is not a list")
        found = [r["violations"] for r in records if r["filepath"] == sql]
        if len(found) > 1:
            raise ValueError(f"{len(found)} lint records for {sql}")
        return found[0] if found else None


class SqlfluffRsBench(SqlfluffBench):
    """sqlfluff with the Rust parser and rules (harness/sqlfluff-rs.md)."""

    name = "sqlfluff-rs"
    venv_name = "sqlfluff-rs"
    problems = (
        *SqlfluffBench.problems,
        (re.compile(re.escape(FALLBACK_WARNING)), "sqlfluff used the Python parser"),
        (
            re.compile(re.escape(ARENA_WARNING)),
            "sqlfluff has no Rust parse arena, so the Rust rules did not run",
        ),
    )

    def layer(self, config: dict[str, Any]) -> dict[str, Any]:
        return with_rust_config(config)


class SqruffBench(BenchAdapter):
    name = "sqruff"
    problems = (
        # Linter::skip_large_file. "lint -f json" gives "{}" and no message.
        (
            re.compile(r"exceeding large_file_skip_(byte|char)_limit|\] SKIP:"),
            "the tool skipped the file (size limit)",
        ),
        (re.compile(r"Unknown rule\(s\)"), "unknown rule"),
    )
    commands = {
        START: ["parse", "-f", "json"],
        PARSE: ["parse", "-f", "json"],
        # As the S1 adapter: without --parsing-errors, an unparsable file
        # gives exit code 0 and no violation.
        LINT: ["lint", "-f", "json", "--parsing-errors"],
        # The default format of sqruff is github-annotation-native if
        # GITHUB_ACTIONS is set (CI); that format prints no size-limit skip.
        FIX: ["fix", "-f", "human"],
    }

    def __init__(self, root: Path | None = None) -> None:
        super().__init__()
        self.s1 = SqruffAdapter(root)

    def version(self) -> str:
        return self.s1.version()

    def layer(self, config: dict[str, Any]) -> dict[str, Any]:
        # The sqlfluff defaults that differ from the sqruff defaults.
        return nested_combine(SQLFLUFF_DEFAULTS, config)

    def unsupported(self, config: dict[str, Any]) -> str | None:
        try:
            self.s1.check_config(config, None)
        except Unsupported as exc:
            return exc.item
        return None

    def write_config(self, config: dict[str, Any], folder: Path) -> Path:
        # With --config, sqruff reads no other config file.
        text = translate(config)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / SQRUFF_CONFIG
        path.write_text(text, encoding="utf8")
        return path

    def argv(self, command: str, config_file: Path, sql: str) -> list[str]:
        return [
            str(self.s1.binary),
            *self.commands[command],
            "--config",
            str(config_file),
            sql,
        ]

    def env(self) -> dict[str, str]:
        return sqruff_env(self.s1.root)

    def read_tree(self, stdout: bytes, sql: str) -> Any:
        if not stdout.strip():
            return None
        return strip_positions(json.loads(stdout))

    def read_violations(self, stdout: bytes, sql: str) -> list[dict] | None:
        data = json.loads(stdout)
        if not isinstance(data, dict):
            raise ValueError("the lint output is not an object")
        if sql not in data:
            return None
        return [to_violation(v) for v in data[sql]]
