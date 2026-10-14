"""Adapter for the sqruff binary (<tools>/sqruff/bin/sqruff).

The adapter gives sqruff each config through one --config file: a .sqruff
INI file that sqruff_config.translate makes from the config in the sqlfluff
structure. With --config, sqruff reads no other config file. If a case uses
a setting, rule, dialect, or templater that sqruff does not support, or a
check reads an output field that sqruff does not give, the adapter raises
Unsupported. See harness/sqruff.md.
"""

import json
import re
import subprocess
import tempfile
from functools import cached_property
from pathlib import Path
from typing import Any

from ..code_only import code_only_record, sqlfluff_record
from ..compare import has_node, strip_positions
from ..paths import tools_dir
from . import config_files
from .base import (
    Adapter,
    EmptyHome,
    FileFixResult,
    FixResult,
    LintResult,
    ParseResult,
    ToolNotInstalled,
    Unsupported,
    isolated_env,
)
from .sqruff_config import SQLFLUFF_DEFAULTS, check, nested_combine, translate

TIMEOUT_S = 600
CONFIG_NAME = ".sqruff"
# The violation fields that "sqruff lint -f json" gives (as sqlfluff keys).
LINT_FIELDS = frozenset({"code", "description", "start_line_no", "start_line_pos"})
# sqruff gives no code (null) for a parse error. "sqruff parse" calls it PRS.
NO_CODE = "PRS"
# The codes of the errors that stop "fix" if fix_even_unparsable is not set.
FIX_GATE_CODES = frozenset({"TMP", "PRS"})
_RULE_LINE = re.compile(r"^([A-Z]{2}\d{2}):\s*\[([^\]]+)\]", re.M)
# sqruff stops with this message for a layout type in the config that it does
# not have (ReflowConfig::from_fluff_config).
_UNKNOWN_LAYOUT_TYPE = re.compile(
    r"src/utils/reflow/config\.rs:\d+:\d+:\nnot implemented: (\S+)"
)
# "sqruff parse" writes one of these on stderr when it has no tree for the
# file: parse errors, or a templater error.
_NO_TREE = re.compile(r"^Error: Failed to parse |: Failed to template file ", re.M)
# sqruff reads an in-file config line that starts with one of these, after
# it removes the spaces around the line (process_raw_file_for_config).
SQRUFF_INLINE_PREFIXES = ("-- sqlfluff:", "-- sqruff:")


def sqruff_env(root: Path | None = None) -> dict[str, str]:
    """Return the environment to run the sqruff binary in.

    The Python interpreter in sqruff finds its venv through the first
    python3 on PATH. The venv holds the Python templaters (jinja, python).
    """
    env = isolated_env(EmptyHome.path())
    python_bin = (root or tools_dir()) / "sqruff" / "python" / "bin"
    env["PATH"] = f"{python_bin}:{env.get('PATH', '')}"
    return env


def check_inline_config(sql_path: Path) -> None:
    """Fail if sqruff and sqlfluff can read the in-file config lines of the
    file in different ways, or if a line sets an unsupported setting.

    sqlfluff reads a line that starts with "-- sqlfluff" or "--sqlfluff".
    sqruff reads a line that starts with "-- sqlfluff:" or "-- sqruff:"
    after it removes the spaces around it, and splits it on each ":".
    """
    sql = sql_path.read_bytes().decode("utf8", errors="replace")
    for line in sql.splitlines():
        sqlfluff_reads = line.startswith(config_files.INLINE_PREFIXES) and line[
            2:
        ].strip().startswith("sqlfluff:")
        sqruff_reads = line.strip().startswith(SQRUFF_INLINE_PREFIXES)
        if sqlfluff_reads != sqruff_reads:
            raise Unsupported(f"the in-file config line {line.strip()!r}")
        if sqlfluff_reads and any(c in line for c in "{[\\"):
            # sqlfluff does not split some values with ":" (paths, JSON).
            raise ValueError(f"in-file config line with a complex value: {line!r}")
    check_settings(config_files.inline_config(sql))


def check_settings(config: dict[str, Any]) -> None:
    """Raise Unsupported for a setting that sqruff does not support, or for
    "warnings" (the lint output of sqruff has no warning field)."""
    if "warnings" in _core(config):
        raise Unsupported(
            "output field warning (the config sets warnings; sqruff lint "
            "gives no warning field)"
        )
    check(config)


def _path_keys_absolute(config: dict[str, Any], cwd: Path, prefix=()) -> None:
    """Make each relative path value absolute from cwd.

    sqlfluff keeps a path that it cannot find near the config file, and the
    templater uses it from the current folder. sqruff makes a relative path
    relative to the folder of its config file.
    """
    for key, value in config.items():
        path = prefix + (key.lower(),)
        if isinstance(value, dict):
            if path != config_files.OPAQUE_SECTION:
                _path_keys_absolute(value, cwd, path)
            continue
        if not isinstance(value, str) or value.strip().lower() == "none":
            continue
        if key.lower() in config_files.COMMA_SEPARATED_PATH_KEYS:
            parts = [p.strip() for p in value.split(",") if p.strip()]
            config[key] = ",".join(str(cwd / p) for p in parts)
        elif key.lower().endswith(config_files.RESOLVE_PATH_SUFFIXES):
            config[key] = str(cwd / value.strip())


def _core(config: dict[str, Any]) -> dict[str, Any]:
    core = config.get("core", {})
    return core if isinstance(core, dict) else {}


def _is_true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def to_violation(item: dict[str, Any]) -> dict[str, Any]:
    """Return a sqruff JSON diagnostic with the sqlfluff violation keys that
    it has (LINT_FIELDS)."""
    start = item["range"]["start"]
    return {
        "code": item["code"] if item["code"] is not None else NO_CODE,
        "description": item["message"],
        "start_line_no": start["line"],
        "start_line_pos": start["character"],
    }


def _exit_reason(rc: int, stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return f"exit code {rc}: {lines[0]}" if lines else f"exit code {rc}"


def _violation_reason(rc: int, stderr: str) -> str:
    """Return "exit code N" and the first parse violation on stderr."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    found = [
        line[:200]
        for line in lines
        if line != "Parse violations:" and not line.startswith("Error: Failed")
    ]
    return f"exit code {rc}: {found[0]}" if found else _exit_reason(rc, stderr)


def _panicked(proc: subprocess.CompletedProcess) -> bool:
    return "panicked at" in proc.stderr


class SqruffAdapter(Adapter):
    name = "sqruff"
    config_layer = SQLFLUFF_DEFAULTS
    lint_fields = LINT_FIELDS

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or tools_dir()
        self.binary = self.root / "sqruff" / "bin" / "sqruff"

    def _check(self) -> None:
        if not self.binary.exists():
            raise ToolNotInstalled(
                f"{self.binary} does not exist. Run scripts/setup to install it."
            )

    def _run(self, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
        self._check()
        proc = subprocess.run(
            [str(self.binary), *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            env=sqruff_env(self.root),
            timeout=TIMEOUT_S,
        )
        unknown = _UNKNOWN_LAYOUT_TYPE.search(proc.stderr)
        if unknown and _panicked(proc):
            raise Unsupported(f"layout type {unknown.group(1)} (sqruff stops on it)")
        return proc

    def _list(self, command: str) -> str:
        with tempfile.TemporaryDirectory(prefix="sqll-sqruff-") as tmp:
            proc = self._run([command], Path(tmp))
        if proc.returncode != 0:
            raise RuntimeError(
                f"sqruff {command}: {_exit_reason(proc.returncode, proc.stderr)}"
            )
        return proc.stdout

    def version(self) -> str:
        # Output is "sqruff X.Y.Z".
        return self.info["version"]

    @cached_property
    def info(self) -> dict[str, Any]:
        """The version, rules ({code: name}), dialects, and templaters of the
        binary, from its commands."""
        with tempfile.TemporaryDirectory(prefix="sqll-sqruff-") as tmp:
            proc = self._run(["--version"], Path(tmp))
        return {
            "version": proc.stdout.strip().rsplit(" ", 1)[-1],
            "rules": dict(_RULE_LINE.findall(self._list("rules"))),
            "dialects": set(self._list("dialects").split()),
            "templaters": set(self._list("templaters").split()),
        }

    def check_rules(self, codes: list[str]) -> None:
        missing = [c for c in codes if c not in self.info["rules"]]
        if missing:
            raise Unsupported("rule " + ", ".join(missing))

    def check_config(self, config: dict[str, Any], dialect: str | None) -> None:
        """Raise Unsupported for the dialect, the templater, or a setting."""
        core = _core(config)
        dialect = dialect or core.get("dialect")
        if isinstance(dialect, str) and dialect.strip() not in self.info["dialects"]:
            raise Unsupported(f"dialect {dialect.strip()}")
        templater = str(core.get("templater", "raw")).strip()
        if templater not in self.info["templaters"]:
            raise Unsupported(f"templater {templater}")
        check_settings(config)

    def _config_args(
        self, config: dict[str, Any], dialect: str | None, tmp: Path
    ) -> list[str]:
        self.check_config(config, dialect)
        path = tmp / CONFIG_NAME
        path.write_text(translate(config), encoding="utf8")
        args = ["--config", str(path)]
        if dialect is not None:
            args += ["--dialect", dialect]
        return args

    def parse(
        self,
        sql_path: Path,
        dialect: str,
        code_only: bool,
        include_meta: bool,
        cwd: Path,
        extra_config: dict[str, Any] | None = None,
    ) -> ParseResult:
        # As the sqlfluff adapter: the raw templater and no config file of
        # the user.
        config = nested_combine(
            self.config_layer, extra_config, {"core": {"templater": "raw"}}
        )
        self.check_config(config, dialect)
        check_inline_config(cwd / sql_path)
        result = self._parse(sql_path, dialect, config, cwd, code_only, include_meta)
        # As "sqlfluff parse": exit code 1 means a parse error. The dialects
        # suite reads it as an error.
        if result.rc != 0 and not result.errors:
            result.errors.append(_violation_reason(result.rc, result.stderr))
        return result

    def _parse(
        self,
        sql_path: Path,
        dialect: str | None,
        config: dict[str, Any],
        cwd: Path,
        code_only: bool,
        include_meta: bool,
    ) -> ParseResult:
        with tempfile.TemporaryDirectory(prefix="sqll-sqruff-") as tmp:
            args = ["parse", "-f", "json"]
            if include_meta:
                args.append("--include-meta")
            args += self._config_args(config, dialect, Path(tmp))
            proc = self._run([*args, str(sql_path)], cwd)
        return parse_output(proc, code_only)

    def lint(
        self,
        sql_paths: list[Path],
        rules: list[str],
        dialect: str | None,
        config: dict[str, Any] | None,
        workdir: Path,
    ) -> LintResult:
        self.check_rules(rules)
        config = self._rule_config(config, rules)
        self.check_config(config, dialect)
        for path in sql_paths:
            check_inline_config(path)
        names = {str(p.relative_to(workdir)): p for p in sql_paths}
        with tempfile.TemporaryDirectory(prefix="sqll-sqruff-") as tmp:
            args = ["lint", "-f", "json", "--parsing-errors"]
            args += self._config_args(config, dialect, Path(tmp))
            proc = self._run([*args, *names], workdir)
        return lint_output(proc, names)

    def _rule_config(
        self, config: dict[str, Any] | None, rules: list[str]
    ) -> dict[str, Any]:
        # As the sqlfluff adapter (--rules, --encoding utf-8): the rules of
        # the case and the encoding of the files that the harness writes.
        return nested_combine(
            self.config_layer,
            config,
            {"core": {"rules": ",".join(rules), "encoding": "utf-8"}},
        )

    def fix(
        self,
        sql_path: Path,
        rules: list[str],
        dialect: str | None,
        config: dict[str, Any] | None,
        workdir: Path,
    ) -> FixResult:
        self.check_rules(rules)
        config = self._rule_config(config, rules)
        self.check_config(config, dialect)
        check_inline_config(sql_path)
        with tempfile.TemporaryDirectory(prefix="sqll-sqruff-") as tmp:
            args = ["fix"]
            args += self._config_args(config, dialect, Path(tmp))
            proc = self._run([*args, str(sql_path.relative_to(workdir))], workdir)
        errors = []
        # Exit code 1 means that violations that it cannot fix remain.
        if proc.returncode not in (0, 1) or _panicked(proc):
            errors.append(_exit_reason(proc.returncode, proc.stderr))
        fixed = None if errors else sql_path.read_bytes().decode("utf8")
        return FixResult(fixed, errors, rc=proc.returncode, stderr=proc.stderr)

    def user_config(
        self, sql_path: Path, dialect: str | None, cwd: Path, rules: list[str] | None
    ) -> dict[str, Any]:
        """The config of a run as a user runs sqlfluff in cwd: the config
        files that sqlfluff reads for the file, and the CLI options.

        sqlfluff uses the templater of the config of cwd (its Linter), not
        of the file. The harness checks the in-file config lines separately.
        """
        home = EmptyHome.path()
        root = config_files.config_for_file(Path("."), cwd, home)
        files = config_files.config_for_file(sql_path, cwd, home)
        _path_keys_absolute(files, cwd)
        templater = _core(root).get("templater", SQLFLUFF_DEFAULTS["core"]["templater"])
        overrides: dict[str, Any] = {"core": {"templater": templater}}
        if dialect is not None:
            overrides["core"]["dialect"] = dialect
        if rules is not None:
            overrides["core"]["rules"] = ",".join(rules)
        config = nested_combine(self.config_layer, files, overrides)
        self.check_config(config, dialect)
        check_inline_config(cwd / sql_path)
        return config

    def parse_file(
        self,
        sql_path: Path,
        dialect: str | None,
        cwd: Path,
        code_only: bool = False,
        include_meta: bool = False,
    ) -> ParseResult:
        config = self.user_config(sql_path, dialect, cwd, None)
        return self._parse(sql_path, dialect, config, cwd, code_only, include_meta)

    def fix_file(
        self,
        sql_path: Path,
        rules: list[str] | None,
        dialect: str,
        cwd: Path,
        show_violations: bool = False,
    ) -> FileFixResult:
        if rules is not None:
            self.check_rules(rules)
        config = self.user_config(sql_path, dialect, cwd, rules)
        with tempfile.TemporaryDirectory(prefix="sqll-sqruff-") as tmp:
            args = ["fix", "-f", "json"] if show_violations else ["fix"]
            args += self._config_args(config, dialect, Path(tmp))
            proc = self._run([*args, str(sql_path)], cwd)
        result = FileFixResult()
        # Exit code 1 means that violations that it cannot fix remain.
        if proc.returncode not in (0, 1) or _panicked(proc):
            result.errors.append(_exit_reason(proc.returncode, proc.stderr))
            return result
        if not show_violations:
            return result
        lint = lint_output(proc, {str(sql_path): sql_path})
        if lint.violations is None:
            result.linted = str(sql_path) in _json_keys(proc.stdout)
            if result.linted:
                result.errors += lint.errors
            else:
                result.violations = []
            return result
        result.linted = True
        result.violations = lint.violations[sql_path]
        # sqruff fix does not write a file with a TMP or PRS violation if
        # fix_even_unparsable is not set (run_fix).
        even = _is_true(_core(config).get("fix_even_unparsable"))
        result.unparsable_gate = not even and any(
            v["code"] in FIX_GATE_CODES for v in result.violations
        )
        return result


def _json_keys(stdout: str) -> set[str]:
    try:
        data = json.loads(stdout)
    except ValueError:
        return set()
    return set(data) if isinstance(data, dict) else set()


def lint_output(
    proc: subprocess.CompletedProcess, names: dict[str, Path]
) -> LintResult:
    """Read "sqruff lint -f json" output: {file: [diagnostic, ...]}. names
    maps each file name in the command to its path."""
    errors: list[str] = []
    violations: dict[Path, list[dict[str, Any]]] | None = None
    try:
        data = json.loads(proc.stdout)
        records = {
            name: [to_violation(v) for v in items] for name, items in data.items()
        }
    except (ValueError, KeyError, TypeError, AttributeError):
        errors.append("no JSON lint output")
    else:
        missing = [name for name in names if name not in records]
        if missing:
            errors.append(f"no lint output for {', '.join(missing)}")
        else:
            violations = {path: records[name] for name, path in names.items()}
    # Exit code 1 means that there are violations.
    if proc.returncode not in (0, 1) or _panicked(proc):
        errors.append(_exit_reason(proc.returncode, proc.stderr))
    return LintResult(violations, errors, proc.returncode, proc.stderr)


def parse_output(proc: subprocess.CompletedProcess, code_only: bool) -> ParseResult:
    """Read "sqruff parse -f json" output for one file.

    sqruff writes the full tree, also with parse errors, and exit code 1 if
    the file has a parse error. With no tree (parse or templater errors) it
    writes _NO_TREE on stderr and exit code 1.
    The tree goes into the form of "sqlfluff parse", with no position keys.
    With code_only, it is the code-only tree (code_only.code_only_record).
    """
    errors: list[str] = []
    tree = None
    has_unparsable = False
    if proc.stdout.strip():
        try:
            record = strip_positions(json.loads(proc.stdout))
            has_unparsable = has_node(record, "unparsable")
            tree = code_only_record(record) if code_only else sqlfluff_record(record)
        except (ValueError, TypeError):
            errors.append("no JSON parse output")
    elif proc.returncode != 0 and not _NO_TREE.search(proc.stderr):
        errors.append(_exit_reason(proc.returncode, proc.stderr))
    if proc.returncode not in (0, 1) or _panicked(proc):
        errors.append(_exit_reason(proc.returncode, proc.stderr))
    return ParseResult(
        tree=tree,
        has_unparsable=has_unparsable,
        errors=errors,
        rc=proc.returncode,
        stderr=proc.stderr,
    )
