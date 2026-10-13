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
    FileFixResult,
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

    def parse_file(
        self,
        sql_path: Path,
        dialect: str | None,
        cwd: Path,
        code_only: bool = False,
        include_meta: bool = False,
    ) -> ParseResult:
        # With -m the JSON output also has the source position of each
        # segment (include_position=include_meta in the parse command).
        self._check()
        cmd = [str(self.binary), "parse", "-f", "json"]
        if code_only:
            cmd.append("-c")
        if include_meta:
            cmd.append("-m")
        if dialect is not None:
            cmd += ["--dialect", dialect]
        cmd.append(str(sql_path))
        proc = self._run(cmd, cwd)
        return _parse_file_output(proc.stdout, proc.returncode, proc.stderr)

    def fix_file(
        self,
        sql_path: Path,
        rules: list[str] | None,
        dialect: str,
        cwd: Path,
        show_violations: bool = False,
    ) -> FileFixResult:
        # No --ignore-local-config and no --config: the tool reads the config
        # files near the file and in cwd. --nocolor only removes colors.
        self._check()
        cmd = [str(self.binary), "fix", "--nocolor", "--dialect", dialect]
        if rules is not None:
            cmd += ["--rules", ",".join(rules)]
        if show_violations:
            cmd.append("--show-lint-violations")
        cmd.append(str(sql_path))
        proc = self._run(cmd, cwd)
        stdout = _ANSI.sub("", proc.stdout)
        stderr = _ANSI.sub("", proc.stderr)
        result = FileFixResult(
            unparsable_gate=bool(_UNPARSABLE_GATE.search(stderr)),
            critical=_critical_logs(stdout + "\n" + stderr),
        )
        # Exit code 1 means that violations or parse errors remain.
        if proc.returncode not in (0, 1):
            result.errors.append(_exit_reason(proc.returncode, proc.stderr))
        if _TRACEBACK in proc.stderr or _TRACEBACK in proc.stdout:
            result.errors.append("the tool crashed")
        if show_violations and not result.errors:
            try:
                result.violations, result.linted = fix_output_violations(
                    stdout, str(sql_path)
                )
            except ValueError as exc:
                result.errors.append(f"fix output: {exc}")
        return result

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
# "sqlfluff fix" prints this on stderr if it does not apply fixes to a file
# with a templating or parse error (also an ignored one), because
# fix_even_unparsable is not set (_handle_unparsable).
_UNPARSABLE_GATE = re.compile(r"^\s*\[\d+ templating/parsing errors found\]", re.M)
# The text output of a violation (OutputStreamFormatter.format_violation):
# "L:  <line> | P:  <pos> | <code> | <description>". A long description
# continues on lines that start with 23 spaces and "| ".
_VIOLATION = re.compile(r"^L:\s*(\d+|-) \| P:\s*(\d+|-) \| +(\S+) \| (.*)$")
_CONTINUATION = re.compile(r"^ {23}\| ")
_WARNING_PREFIX = "WARNING: "
_FIX_START = "==== finding fixable violations ===="
_UNFIXABLE_START = "==== lint for unfixable violations ===="


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


def fix_output_violations(stdout: str, path: str) -> tuple[list[dict[str, Any]], bool]:
    """Read the output of "sqlfluff fix --show-lint-violations --nocolor".

    Return the violations of the file at path and True if the tool linted
    the file. stdout must have no ANSI codes.

    The first section has, for each file with violations, a line
    "== [<path>] PASS|FAIL" and one line for each violation that is not
    ignored or masked by noqa (get_violations with warnings). PASS means that
    all of them are warnings. A line "== [<path>] FIXED|FAIL" with no
    violation lines after it is the result of the fix. The last section has
    a line "== [<path>] ..." for each file that the tool linted.
    """
    lines = stdout.splitlines()
    if lines.count(_FIX_START) != 1 or lines.count(_UNFIXABLE_START) != 1:
        raise ValueError("the fix output does not have the 2 sections")
    split = lines.index(_UNFIXABLE_START)
    if lines.index(_FIX_START) > split:
        raise ValueError("the fix output sections are not in order")
    header = re.compile(r"^== \[" + re.escape(path) + r"\] (\S+)$")
    linted = any(header.match(line) for line in lines[split + 1 :])
    violations: list[dict[str, Any]] = []
    blocks = 0
    i = 0
    first = lines[:split]
    while i < len(first):
        m = header.match(first[i])
        if not m or i + 1 >= len(first) or not _VIOLATION.match(first[i + 1]):
            if _VIOLATION.match(first[i]):
                raise ValueError(f"a violation line has no file line: {first[i]!r}")
            i += 1
            continue
        blocks += 1
        status = m.group(1)
        block = []
        i += 1
        while i < len(first) and (
            _VIOLATION.match(first[i]) or _CONTINUATION.match(first[i])
        ):
            v = _VIOLATION.match(first[i])
            if v:
                line_no, line_pos, code, desc = v.groups()
                block.append(
                    {
                        "code": code,
                        "start_line_no": None if line_no == "-" else int(line_no),
                        "start_line_pos": None if line_pos == "-" else int(line_pos),
                        "warning": desc.startswith(_WARNING_PREFIX),
                    }
                )
            i += 1
        fails = any(not v["warning"] for v in block)
        if status != ("FAIL" if fails else "PASS"):
            raise ValueError(
                f"the file line says {status}, but the file has "
                f"{sum(not v['warning'] for v in block)} violations that are "
                "not warnings"
            )
        violations += block
    if blocks > 1:
        raise ValueError("the fix output has the violations of the file 2 times")
    if violations and not linted:
        raise ValueError("the fix output has violations but the file is not linted")
    return violations, linted


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


def _parse_file_output(stdout: str, rc: int, stderr: str) -> ParseResult:
    """Read "parse -f json" output for one file.

    "segments" is null if the root variant has no tree: the file did not
    template or did not parse. A TMP, LXR, or PRS violation sets exit code 1.
    """
    errors: list[str] = []
    tree = None
    try:
        records = json.loads(stdout)
        if len(records) != 1:
            raise ValueError(f"{len(records)} records")
        tree = records[0]["segments"]
    except (ValueError, IndexError, KeyError, TypeError):
        errors.append("no JSON parse output for the file")
    if rc not in (0, 1):
        errors.append(_exit_reason(rc, stderr))
    if _TRACEBACK in stderr or _TRACEBACK in stdout:
        errors.append("the tool crashed")
    return ParseResult(
        tree=tree,
        has_unparsable=has_node(tree, "unparsable"),
        errors=errors,
        rc=rc,
        stderr=stderr,
    )


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
