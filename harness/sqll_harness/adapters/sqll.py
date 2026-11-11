"""Adapter for the sqll binary (out/sqll/bin/sqll; scripts/build-sqll).

parse() runs "sqll parse" as the sqlfluff adapter runs sqlfluff parse (the
raw templater, --ignore-local-config, and the extra config of the case as a
--config file). Since S3b C14, lint(), fix(), parse_file(), and fix_file()
run "sqll lint", "sqll fix", and "sqll parse" as the sqlfluff adapter runs
sqlfluff, but only if:

- each rule of the case is in the sqll registry (read from "sqll rules");
- the templater is raw, or it is jinja (the sqlfluff default) with no
  templater setting and each SQL file is a text of the jinja as raw record
  (results/S3b/C14-jinja-raw.json, scripts/s3b/jinja_raw_oracle.py): for
  that text the pinned sqlfluff gives the file of the raw templater;
- no line of a SQL file is an in-file config line.

Else the adapter raises Unsupported with the reason, before a run. sqll
checks each setting itself: it fails closed on a setting, an option, or an
input that it cannot do (exit code 2 and "unsupported: <item>"), and the
adapter raises Unsupported(<item>). "fix --show-lint-violations" is not in
sqll: fix_file with show_violations raises Unsupported. See harness/sqll.md.

This module also has the facts of the worktree that the tool check compares
with the binary (tools.check_sqll): the expected version and the source
hash. crates/sqll/build.rs computes the same source hash at build time.
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import tomllib
from functools import cache
from pathlib import Path
from typing import Any

from ..paths import REPO_ROOT
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
from .sqlfluff import (
    _ANSI,
    _UNPARSABLE_GATE,
    CONFIG_NAME,
    _critical_logs,
    _exit_reason,
    _lint_output,
    _parse_file_output,
    _parse_output,
    _rule_args,
    sqlfluff_toml,
)

TIMEOUT_S = 600
# SQLL_BIN sets another binary, and SQLL_SOURCE_DIR the source folder that
# its tool check compares with (default: the worktree).
DEFAULT_BINARY = REPO_ROOT / "out" / "sqll" / "bin" / "sqll"
SOURCE_ENV = "SQLL_SOURCE_DIR"
# The base binary of a speed check (scripts/speed-check; tool "sqll-base").
BASE_BINARY_ENV = "SQLL_BASE_BIN"
BASE_SOURCE_ENV = "SQLL_BASE_SOURCE_DIR"
DEFAULT_BASE_BINARY = REPO_ROOT / "out" / "sqll-base" / "bin" / "sqll"
# The inputs of the source hash: these files, and each file under these
# folders. They must be those of crates/sqll/build.rs.
SOURCE_FILES = ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "LICENSE")
SOURCE_DIRS = ("crates",)
TABLE_MANIFEST = "crates/sqll_dialects/generated.json"
BUILD_HELP = "Run scripts/build-sqll."
# sqll prints "Error: unsupported: <item>. <why>." and exits with code 2
# for a setting or an input that it cannot do yet (fail closed).
UNSUPPORTED_PREFIX = "Error: unsupported: "
# The jinja as raw record (scripts/s3b/jinja_raw_oracle.py): the sha256 of
# each text for which the pinned sqlfluff gives the file of the raw
# templater with the jinja templater.
JINJA_RAW_RECORD = REPO_ROOT / "results" / "S3b" / "C14-jinja-raw.json"
JINJA_RAW_KIND = "sqll-s3b-c14-jinja-raw"
# The templater of sqlfluff when the config sets none.
DEFAULT_TEMPLATER = "jinja"
# A rule line of "sqll rules" (and "sqlfluff rules"): "CP01: [name] ...".
_RULE_LINE = re.compile(r"^([A-Z]{2}\d{2}):", re.M)
# The fail-closed message of a rule selection: "rules AL01, AL02: why".
_MISSING_RULES = re.compile(r"^rules ([A-Z]{2}\d{2}(?:, [A-Z]{2}\d{2})*): ")


def binary_path() -> Path:
    value = os.environ.get("SQLL_BIN")
    return Path(value) if value else DEFAULT_BINARY


def source_root() -> Path:
    value = os.environ.get(SOURCE_ENV)
    return Path(value) if value else REPO_ROOT


def base_binary_path() -> Path:
    value = os.environ.get(BASE_BINARY_ENV)
    return Path(value) if value else DEFAULT_BASE_BINARY


def source_hash(root: Path = REPO_ROOT) -> tuple[str, int]:
    """Return the sha256 of the source files and their count.

    Each file, sorted by its path relative to root (with "/"), adds its path,
    a NUL byte, its size in bytes (decimal text), a NUL byte, and its bytes.
    """
    files = {name: root / name for name in SOURCE_FILES}
    for top in SOURCE_DIRS:
        for path in (root / top).rglob("*"):
            if path.is_file():
                files[path.relative_to(root).as_posix()] = path
    digest = hashlib.sha256()
    for rel in sorted(files, key=lambda r: r.encode("utf8")):
        data = files[rel].read_bytes()
        digest.update(rel.encode("utf8") + b"\0" + str(len(data)).encode() + b"\0")
        digest.update(data)
    return digest.hexdigest(), len(files)


def expected_version(root: Path = REPO_ROOT) -> str:
    """The version of a sqll binary built from root: the workspace version
    and the sha256 of the table manifest. It is the same for each commit
    with the same version and tables."""
    cargo = tomllib.loads((root / "Cargo.toml").read_text("utf8"))
    version = cargo["workspace"]["package"]["version"]
    tables = hashlib.sha256((root / TABLE_MANIFEST).read_bytes()).hexdigest()
    return f"{version}+tables.{tables}"


@cache
def jinja_raw_texts(record: Path = JINJA_RAW_RECORD) -> frozenset[str]:
    """The sha256 of each text of the jinja as raw record. A missing or
    other record gives no text: then each jinja case is unsupported."""
    try:
        data = json.loads(record.read_text(encoding="utf8"))
    except (OSError, ValueError):
        return frozenset()
    if not isinstance(data, dict) or data.get("kind") != JINJA_RAW_KIND:
        return frozenset()
    texts = data.get("equal")
    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        return frozenset()
    return frozenset(texts)


def text_sha256(path: Path) -> str:
    """The sha256 of the bytes of a SQL file, which must be UTF-8 (the
    record has the sha256 of the UTF-8 bytes of each text)."""
    data = path.read_bytes()
    try:
        data.decode("utf8")
    except UnicodeDecodeError:
        raise Unsupported(f"templater jinja: {path.name} is not UTF-8") from None
    return hashlib.sha256(data).hexdigest()


def _core(config: dict[str, Any] | None) -> dict[str, Any]:
    core = config.get("core") if isinstance(config, dict) else None
    return core if isinstance(core, dict) else {}


def check_inline_config(path: Path) -> None:
    """Raise Unsupported for an in-file config line. "sqll parse" does not
    read one (sqlfluff applies it); "sqll lint" and "sqll fix" fail closed
    on one."""
    text = path.read_bytes().decode("utf8", errors="replace")
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith(config_files.INLINE_PREFIXES):
            raise Unsupported(f"in-file config line {number} of {path.name}")


class SqllAdapter(Adapter):
    name = "sqll"

    def __init__(
        self, binary: Path | None = None, jinja_record: Path | None = None
    ) -> None:
        self.binary = binary or binary_path()
        self.jinja_record = jinja_record or JINJA_RAW_RECORD
        self._version: str | None = None
        self._rules: tuple[frozenset[str], frozenset[str]] | None = None

    def _check(self) -> None:
        if not self.binary.exists():
            raise ToolNotInstalled(f"{self.binary} does not exist. {BUILD_HELP}")

    def version(self) -> str:
        if self._version is None:
            self._check()
            out = self._run([str(self.binary), "--version"], REPO_ROOT)
            if out.returncode != 0:
                raise RuntimeError(f"sqll --version: exit code {out.returncode}")
            # Output is "sqll, version X".
            self._version = out.stdout.strip().rsplit(" ", 1)[-1]
        return self._version

    def rules(self) -> tuple[frozenset[str], frozenset[str]]:
        """The codes of the rules that sqll has (its registry) and of all
        the rules of sqlfluff, from the output of "sqll rules".

        With no config, "sqll rules" selects each sqlfluff rule. If sqll does
        not have one, it fails closed and names them. Then a second run
        excludes those, and its table has the rules that sqll has."""
        if self._rules is None:
            self._check()
            argv = [str(self.binary), "rules", "--nocolor"]
            with tempfile.TemporaryDirectory(prefix="sqll-rules-") as tmp:
                folder = Path(tmp)
                proc = self._run(argv, folder)
                missing: set[str] = set()
                if proc.returncode != 0:
                    missing = _missing_rules(proc)
                    exclude = ",".join(sorted(missing))
                    (folder / ".sqlfluff").write_text(
                        f"[sqlfluff]\nexclude_rules = {exclude}\n", encoding="utf8"
                    )
                    proc = self._run(argv, folder)
                    if proc.returncode != 0:
                        raise RuntimeError(
                            f"sqll rules: {_exit_reason(proc.returncode, proc.stderr)}"
                        )
                have = set(_RULE_LINE.findall(proc.stdout))
            if not have and not missing:
                raise RuntimeError("sqll rules: no rule in the output")
            if have & missing:
                raise RuntimeError("sqll rules: a rule is in both runs")
            self._rules = (frozenset(have), frozenset(have | missing))
        return self._rules

    def check_rules(self, codes: list[str]) -> None:
        """Raise Unsupported for each rule of the case that sqll does not
        have."""
        have, _ = self.rules()
        missing = [c for c in codes if c not in have]
        if missing:
            raise Unsupported("rule " + ", ".join(missing))

    def check_case_rules(self, codes: list[str]) -> None:
        # Fail closed also for a case that runs no lint (an empty pass_str).
        self.check_rules(codes)

    def check_templater(
        self, templater: Any, config: dict[str, Any] | None, paths: list[Path]
    ) -> None:
        """Raise Unsupported if the templated file of a SQL file can be
        another one than the file of the raw templater, which sqll uses.

        raw: the same file. jinja: only with no templater setting, and for a
        text of the jinja as raw record. Each other templater: unsupported.
        """
        name = str(templater).strip()
        if name == "raw":
            return
        if name != DEFAULT_TEMPLATER:
            raise Unsupported(f"templater {name}")
        if isinstance(config, dict) and (
            "templater" in config or "library_path" in _core(config)
        ):
            raise Unsupported(
                "templater jinja with settings (the jinja as raw record has "
                "only the default settings)"
            )
        texts = jinja_raw_texts(self.jinja_record)
        for path in paths:
            if text_sha256(path) not in texts:
                raise Unsupported(
                    f"templater jinja: {path.name} is not a text of the jinja as "
                    "raw record (results/S3b/C14-jinja-raw.json)"
                )

    def user_config(self, sql_path: Path, cwd: Path) -> tuple[str, dict[str, Any]]:
        """The templater and the config of a run as a user runs sqlfluff in
        cwd. sqlfluff uses the templater of the config of cwd, with the
        settings of the config of the file."""
        home = EmptyHome.path()
        try:
            root = config_files.config_for_file(Path("."), cwd, home)
            files = config_files.config_for_file(sql_path, cwd, home)
        except (config_files.NotPorted, ValueError) as exc:
            raise Unsupported(f"setting: {exc}") from None
        templater = str(_core(root).get("templater", DEFAULT_TEMPLATER)).strip()
        own = str(_core(files).get("templater", templater)).strip()
        if own != templater:
            raise Unsupported(
                f"templater {own} in the config of the file (sqlfluff uses "
                f"{templater}, the templater of the working folder)"
            )
        return templater, files

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
        # As the sqlfluff adapter: the raw templater, and no config file but
        # the config of the case.
        cmd += ["--templater", "raw", "--dialect", dialect, "--ignore-local-config"]
        with tempfile.TemporaryDirectory(prefix="sqll-case-") as tmp:
            if extra_config:
                cfg = Path(tmp) / CONFIG_NAME
                cfg.write_text(sqlfluff_toml(extra_config), encoding="utf8")
                cmd += ["--config", str(cfg)]
            cmd.append(str(sql_path))
            proc = self._run(cmd, cwd)
        raise_unsupported(proc.returncode, proc.stderr)
        return _parse_output(proc.stdout, proc.returncode, proc.stderr)

    def _case_checks(
        self, paths: list[Path], rules: list[str], config: dict[str, Any] | None
    ) -> None:
        self.check_rules(rules)
        templater = _core(config).get("templater", DEFAULT_TEMPLATER)
        self.check_templater(templater, config, paths)
        for path in paths:
            check_inline_config(path)

    def lint(
        self,
        sql_paths: list[Path],
        rules: list[str],
        dialect: str | None,
        config: dict[str, Any] | None,
        workdir: Path,
    ) -> LintResult:
        self._case_checks(sql_paths, rules, config)
        # As the sqlfluff adapter: --ignore-local-config, --encoding utf-8,
        # --rules, --dialect, and the config of the case as a --config file.
        names = {str(p.relative_to(workdir)): p for p in sql_paths}
        cmd = [str(self.binary), "lint", "-f", "json", "--nofail"]
        cmd += _rule_args(rules, dialect, config, workdir) + list(names)
        proc = self._run(cmd, workdir)
        raise_unsupported(proc.returncode, proc.stderr)
        return _lint_output(proc.stdout, proc.returncode, proc.stderr, names)

    def fix(
        self,
        sql_path: Path,
        rules: list[str],
        dialect: str | None,
        config: dict[str, Any] | None,
        workdir: Path,
    ) -> FixResult:
        self._case_checks([sql_path], rules, config)
        cmd = [str(self.binary), "fix"]
        cmd += _rule_args(rules, dialect, config, workdir)
        cmd.append(str(sql_path.relative_to(workdir)))
        proc = self._run(cmd, workdir)
        raise_unsupported(proc.returncode, proc.stderr)
        errors = []
        # Exit code 1 means that violations or parse errors remain.
        if proc.returncode not in (0, 1):
            errors.append(_exit_reason(proc.returncode, proc.stderr))
        fixed = None if errors else sql_path.read_bytes().decode("utf8")
        critical = _critical_logs(proc.stdout + "\n" + proc.stderr)
        return FixResult(
            fixed, errors, critical=critical, rc=proc.returncode, stderr=proc.stderr
        )

    def _user_checks(self, sql_path: Path, cwd: Path) -> None:
        templater, config = self.user_config(sql_path, cwd)
        self.check_templater(templater, config, [cwd / sql_path])
        check_inline_config(cwd / sql_path)

    def parse_file(
        self,
        sql_path: Path,
        dialect: str | None,
        cwd: Path,
        code_only: bool = False,
        include_meta: bool = False,
    ) -> ParseResult:
        self._check()
        self._user_checks(sql_path, cwd)
        if include_meta:
            # "sqlfluff parse -m" also gives the source position of each
            # segment, and thus another record shape (harness/sqll.md).
            raise Unsupported(
                "output field source positions (sqll parse -m gives none)"
            )
        cmd = [str(self.binary), "parse", "-f", "json"]
        if code_only:
            cmd.append("-c")
        if dialect is not None:
            cmd += ["--dialect", dialect]
        cmd.append(str(sql_path))
        proc = self._run(cmd, cwd)
        raise_unsupported(proc.returncode, proc.stderr)
        return _parse_file_output(proc.stdout, proc.returncode, proc.stderr)

    def fix_file(
        self,
        sql_path: Path,
        rules: list[str] | None,
        dialect: str,
        cwd: Path,
        show_violations: bool = False,
    ) -> FileFixResult:
        self._check()
        if rules is not None:
            self.check_rules(rules)
        self._user_checks(sql_path, cwd)
        if show_violations:
            raise Unsupported(
                "output field violations of a fix (sqll fix has no "
                "--show-lint-violations)"
            )
        # As the sqlfluff adapter: the config files of the user, and only
        # --dialect and --rules.
        cmd = [str(self.binary), "fix", "--nocolor", "--dialect", dialect]
        if rules is not None:
            cmd += ["--rules", ",".join(rules)]
        cmd.append(str(sql_path))
        proc = self._run(cmd, cwd)
        raise_unsupported(proc.returncode, proc.stderr)
        stdout = _ANSI.sub("", proc.stdout)
        stderr = _ANSI.sub("", proc.stderr)
        result = FileFixResult(
            unparsable_gate=bool(_UNPARSABLE_GATE.search(stderr)),
            critical=_critical_logs(stdout + "\n" + stderr),
        )
        # Exit code 1 means that violations or parse errors remain.
        if proc.returncode not in (0, 1):
            result.errors.append(_exit_reason(proc.returncode, proc.stderr))
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


def _missing_rules(proc: subprocess.CompletedProcess) -> set[str]:
    """The rules that a failed "sqll rules" names as unsupported."""
    for line in proc.stderr.splitlines():
        if line.startswith(UNSUPPORTED_PREFIX):
            m = _MISSING_RULES.match(line[len(UNSUPPORTED_PREFIX) :])
            if m:
                return set(m.group(1).split(", "))
    raise RuntimeError(f"sqll rules: {_exit_reason(proc.returncode, proc.stderr)}")


def raise_unsupported(rc: int, stderr: str) -> None:
    """Raise Unsupported for a run that sqll stopped as unsupported: exit
    code 2 and the line "Error: unsupported: <item>. <why>."."""
    if rc != 2:
        return
    for line in stderr.splitlines():
        if line.startswith(UNSUPPORTED_PREFIX):
            item = line[len(UNSUPPORTED_PREFIX) :].split(". ", 1)[0].rstrip(".")
            raise Unsupported(item)
