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
    did not complete. critical holds the first line of each CRITICAL log
    message of the tool. The sqlfluff test fails for these messages (a rule
    exception, or conflicting fixes), but the CLI only logs them.
    """

    fixed: str | None
    errors: list[str] = field(default_factory=list)
    critical: list[str] = field(default_factory=list)
    rc: int = 0
    stderr: str = ""


@dataclass
class FileFixResult:
    """The result of one fix of a SQL file with the config files of the user.

    violations: the violations that the tool found in fix mode, with no
    ignored or noqa-masked ones. Each is a dict with the keys code,
    start_line_no, start_line_pos, and warning. None if the run does not
    show them.
    linted: True if the tool linted the file, None if the run does not show
    it.
    unparsable_gate: the tool did not apply fixes because the file has a
    templating or parse error. The tool counts also ignored and noqa-masked
    errors for this.
    critical: as for FixResult.
    errors: why the run gave no usable result. Then the other fields are not
    known.
    """

    violations: list[dict[str, Any]] | None = None
    linted: bool | None = None
    unparsable_gate: bool = False
    critical: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ToolNotInstalled(Exception):
    """The tool binary is not installed."""


class Unsupported(Exception):
    """The case uses an item that the tool does not support: a setting, a
    rule, a dialect, a templater, or an output field that a check reads.

    The case status is "fail" with the reason "unsupported: <item>". It is
    never "pass".
    """

    def __init__(self, item: str) -> None:
        super().__init__(item)
        self.item = item


class Adapter(ABC):
    """Runs one tool through its binary. Never through function calls.

    config_layer is the config that the adapter adds to each case, in the
    sqlfluff config structure. The report shows it.
    An adapter raises Unsupported for an item that the tool does not support.
    """

    name: str
    config_layer: dict[str, Any] | None = None
    # The violation keys that lint() gives. None: all keys of
    # "sqlfluff lint -f json".
    lint_fields: frozenset[str] | None = None

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

    @abstractmethod
    def parse_file(
        self,
        sql_path: Path,
        dialect: str | None,
        cwd: Path,
        code_only: bool = False,
        include_meta: bool = False,
    ) -> ParseResult:
        """Parse one SQL file, as a user runs the tool in cwd.

        The tool reads the config files of the user, as for fix_file(). If
        dialect is None, the config files set it. tree is None if the tool
        parsed the file but has no tree for it. errors is not empty if the
        tool gave no usable output. With include_meta, the tree has the meta
        segments, and can have the position of each segment.
        """

    @abstractmethod
    def fix_file(
        self,
        sql_path: Path,
        rules: list[str] | None,
        dialect: str,
        cwd: Path,
        show_violations: bool = False,
    ) -> FileFixResult:
        """Fix one SQL file in place, as a user runs the tool in cwd.

        The tool reads the config files of the user: those near the file and
        in cwd. rules None means the rules of the config. With
        show_violations, the result has the violations and the linted flag.
        """


def isolated_env(home: Path) -> dict[str, str]:
    """Return an environment that does not leak user config into a tool.

    The tool must not write bytecode files: a jinja library_path imports
    Python modules from the fixture folders in the sqlfluff submodule.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSTARTUP"}
    }
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class EmptyHome:
    """An empty temporary directory to use as HOME for tool processes."""

    _dir: tempfile.TemporaryDirectory | None = None

    @classmethod
    def path(cls) -> Path:
        if cls._dir is None:
            cls._dir = tempfile.TemporaryDirectory(prefix="sqll-home-")
        return Path(cls._dir.name)
