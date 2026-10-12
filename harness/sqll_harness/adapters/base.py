"""The interface that each tool adapter implements."""

import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParseResult:
    """The result of one parse through a tool binary.

    tree is the parse record as the tool gives it, for example
    {"file": {...}}. It is None if the tool gave no tree.
    errors holds the error codes or messages that the tool gave.
    """

    tree: Any | None
    has_unparsable: bool
    errors: list[str] = field(default_factory=list)
    rc: int = 0
    stderr: str = ""


@dataclass
class LintResult:
    """The result of one lint through a tool binary.

    violations maps each linted file, as given to lint(), to its violations.
    It is None if the tool gave no usable output. Each violation is a dict
    with the keys of "sqlfluff lint -f json": code, description, name,
    warning, start_line_no, start_line_pos, start_file_pos, end_line_no,
    end_line_pos, end_file_pos, and fixes.
    """

    violations: dict[Path, list[dict[str, Any]]] | None
    errors: list[str] = field(default_factory=list)
    rc: int = 0
    stderr: str = ""


@dataclass
class FixResult:
    """The result of one fix through a tool binary.

    fixed is the content of the file after the fix. It is None if the tool
    did not complete.
    """

    fixed: str | None
    errors: list[str] = field(default_factory=list)
    rc: int = 0
    stderr: str = ""


class ToolNotInstalled(Exception):
    """The tool binary is not installed."""


class Adapter(ABC):
    """Runs one tool through its binary. Never through function calls."""

    name: str

    @abstractmethod
    def version(self) -> str:
        """Return the version of the tool."""

    @abstractmethod
    def parse(
        self,
        sql_path: Path,
        dialect: str,
        code_only: bool,
        include_meta: bool,
        cwd: Path,
        extra_config: dict[str, Any] | None = None,
    ) -> ParseResult:
        """Parse one SQL file.

        extra_config uses the sqlfluff config structure, for example
        {"core": {"max_parse_depth": 2000}}.
        """

    @abstractmethod
    def lint(
        self,
        sql_paths: list[Path],
        rules: list[str],
        dialect: str | None,
        config: dict[str, Any] | None,
        workdir: Path,
    ) -> LintResult:
        """Lint SQL files in workdir with only these rules.

        config uses the sqlfluff config structure. The adapter can write its
        config files in workdir. If dialect is None, the config sets it.
        """

    @abstractmethod
    def fix(
        self,
        sql_path: Path,
        rules: list[str],
        dialect: str | None,
        config: dict[str, Any] | None,
        workdir: Path,
    ) -> FixResult:
        """Fix one SQL file in workdir with only these rules.

        The arguments are as for lint(). The tool can change the file.
        """


def isolated_env(home: Path) -> dict[str, str]:
    """Return an environment that does not leak user config into a tool."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSTARTUP"}
    }
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home)
    return env


class EmptyHome:
    """An empty temporary directory to use as HOME for tool processes."""

    _dir: tempfile.TemporaryDirectory | None = None

    @classmethod
    def path(cls) -> Path:
        if cls._dir is None:
            cls._dir = tempfile.TemporaryDirectory(prefix="sqll-home-")
        return Path(cls._dir.name)
