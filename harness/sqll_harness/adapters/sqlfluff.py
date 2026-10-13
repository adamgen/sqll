"""Adapter for the sqlfluff binary."""

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import tomli_w

from ..compare import has_node
from ..paths import tools_dir
from .base import (
    Adapter,
    EmptyHome,
    FixResult,
    LintResult,
    ParseResult,
    ToolNotInstalled,
    isolated_env,
)

TIMEOUT_S = 600
# sqlfluff reads a config file as TOML only if its name is pyproject.toml.
# Other names are read as INI. TOML keeps the types of the values.
CONFIG_NAME = "pyproject.toml"


def sqlfluff_toml(config: dict[str, Any]) -> str:
    """Return a sqlfluff config dict as the text of a pyproject.toml file.

    The values keep their types: bools, ints, strings with new lines, and
    nested lists. Each dict becomes a [tool.sqlfluff.<section>] table. A key
    with a dot, for example the rule name "aliasing.column", is quoted.
    """
    _check_toml(config, "tool.sqlfluff")
    return tomli_w.dumps({"tool": {"sqlfluff": config}})


def _check_toml(value: Any, where: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"config key {key!r} in {where} is not a string")
            _check_toml(item, f"{where}.{key}")
    elif isinstance(value, list):
        for item in value:
            _check_toml(item, where)
    elif value is None:
        raise ValueError(f"config value {where} is null; TOML has no null")
    elif not isinstance(value, (str, int, float)):
        raise ValueError(f"config value {where} has type {type(value).__name__}")


class SqlfluffAdapter(Adapter):
    name = "sqlfluff"

    def __init__(self, venv: Path | None = None) -> None:
        self.venv = venv or tools_dir() / "sqlfluff"
        self.binary = self.venv / "bin" / "sqlfluff"
        self._version: str | None = None

    def _check(self) -> None:
        if not self.binary.exists():
            raise ToolNotInstalled(
                f"{self.binary} does not exist. Run scripts/setup to install it."
            )

    def version(self) -> str:
        if self._version is None:
            self._version = self._read_version()
        return self._version

    def _read_version(self) -> str:
        self._check()
        out = subprocess.run(
            [str(self.binary), "--version"],
            capture_output=True,
            text=True,
            check=True,
            env=isolated_env(EmptyHome.path()),
        ).stdout
        # Output is "sqlfluff, version X.Y.Z".
        return out.strip().rsplit(" ", 1)[-1]

    def parse(
        self,
        sql_path: Path,
        dialect: str,
        code_only: bool,
        include_meta: bool,
        cwd: Path,
        extra_config: dict[str, Any] | None = None,
    ) -> ParseResult:
        self._check()
        cmd = [str(self.binary), "parse", "-f", "json"]
        if code_only:
            cmd.append("-c")
        if include_meta:
            cmd.append("-m")
        cmd += ["--templater", "raw", "--dialect", dialect]
        # The sqlfluff test reads no config file. Without this flag the CLI
        # reads .sqlfluff files from cwd and from the folder of the SQL file.
        cmd.append("--ignore-local-config")
        with tempfile.TemporaryDirectory(prefix="sqll-case-") as tmp:
            if extra_config:
                cfg = Path(tmp) / CONFIG_NAME
                cfg.write_text(sqlfluff_toml(extra_config), encoding="utf8")
                cmd += ["--config", str(cfg)]
            cmd.append(str(sql_path))
            proc = self._run(cmd, cwd)
        return _parse_output(proc.stdout, proc.returncode, proc.stderr)

    def lint(
        self,
        sql_paths: list[Path],
        rules: list[str],
        dialect: str | None,
        config: dict[str, Any] | None,
        workdir: Path,
    ) -> LintResult:
        self._check()
        names = {str(p.relative_to(workdir)): p for p in sql_paths}
        cmd = [str(self.binary), "lint", "-f", "json", "--nofail"]
        cmd += _rule_args(rules, dialect, config, workdir) + list(names)
        proc = self._run(cmd, workdir)
        return _lint_output(proc.stdout, proc.returncode, proc.stderr, names)

    def fix(
        self,
        sql_path: Path,
        rules: list[str],
        dialect: str | None,
        config: dict[str, Any] | None,
        workdir: Path,
    ) -> FixResult:
        # "sqlfluff fix" does not write a file with a TMP or PRS violation,
        # also a hidden one, unless fix_even_unparsable is set. The rule suite
        # finds this case (rules.fix_not_shown).
        self._check()
        cmd = [str(self.binary), "fix"]
        cmd += _rule_args(rules, dialect, config, workdir)
        cmd.append(str(sql_path.relative_to(workdir)))
        proc = self._run(cmd, workdir)
        errors = []
        # Exit code 1 means that violations or parse errors remain.
        if proc.returncode not in (0, 1):
            errors.append(_exit_reason(proc.returncode, proc.stderr))
        if _TRACEBACK in proc.stderr or _TRACEBACK in proc.stdout:
            errors.append("the tool crashed")
        fixed = None if errors else sql_path.read_bytes().decode("utf8")
        critical = _critical_logs(proc.stdout + "\n" + proc.stderr)
        return FixResult(
            fixed, errors, critical=critical, rc=proc.returncode, stderr=proc.stderr
        )

    def _run(self, cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=isolated_env(EmptyHome.path()),
            timeout=TIMEOUT_S,
        )


_TRACEBACK = "Traceback (most recent call last)"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# The log format of the CLI is "%(levelname)-10s %(message)s".
_CRITICAL = re.compile(r"^CRITICAL\s+(.*)$", re.MULTILINE)


def _exit_reason(rc: int, stderr: str) -> str:
    """Return "exit code N" and the first line of stderr, if there is one.

    For a Python traceback, the line is the last one: the exception.
    """
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return f"exit code {rc}"
    line = lines[-1] if lines[0].startswith(_TRACEBACK) else lines[0]
    return f"exit code {rc}: {line}"


def _critical_logs(output: str) -> list[str]:
    """Return the first line of each CRITICAL log message in output."""
    return [m.strip() for m in _CRITICAL.findall(_ANSI.sub("", output))]


def _rule_args(
    rules: list[str], dialect: str | None, config: dict[str, Any] | None, workdir: Path
) -> list[str]:
    """Return the lint and fix options of a rule case.

    --ignore-local-config: the sqlfluff test reads no config file.
    --encoding utf-8: the sqlfluff test gives the SQL as a string, and the
    harness writes it as UTF-8. Without this option sqlfluff guesses.
    """
    args = ["--ignore-local-config", "--encoding", "utf-8"]
    args += ["--rules", ",".join(rules)]
    if dialect is not None:
        args += ["--dialect", dialect]
    if config is not None:
        cfg = workdir / CONFIG_NAME
        cfg.write_text(sqlfluff_toml(config), encoding="utf8")
        args += ["--config", str(cfg)]
    return args


def _lint_output(
    stdout: str, rc: int, stderr: str, names: dict[str, Path]
) -> LintResult:
    """Read "lint -f json" output. names maps each file name in the command
    to its path."""
    errors: list[str] = []
    violations: dict[Path, list[dict[str, Any]]] | None = None
    try:
        records = {r["filepath"]: r["violations"] for r in json.loads(stdout)}
    except (ValueError, KeyError, TypeError):
        errors.append("no JSON lint output")
    else:
        missing = [name for name in names if name not in records]
        if missing:
            # For example, a file larger than large_file_skip_byte_limit.
            errors.append(f"no lint output for {', '.join(missing)}")
        else:
            violations = {path: records[name] for name, path in names.items()}
    # With --nofail the exit code is 0 unless the tool fails.
    if rc != 0:
        errors.append(_exit_reason(rc, stderr))
    return LintResult(violations, errors, rc, stderr)


def _parse_output(stdout: str, rc: int, stderr: str) -> ParseResult:
    errors: list[str] = []
    tree = None
    try:
        payload = json.loads(stdout)
        tree = payload[0]["segments"]
    except (ValueError, IndexError, KeyError, TypeError):
        errors.append("no JSON parse output")
    # The JSON output of "sqlfluff parse" has no violation codes. A PRS, LXR,
    # or TMP violation sets exit code 1.
    if rc != 0:
        errors.append(f"exit code {rc}")
    return ParseResult(
        tree=tree,
        has_unparsable=has_node(tree, "unparsable"),
        errors=errors,
        rc=rc,
        stderr=stderr,
    )
