"""Adapter for the sqll binary (out/sqll/bin/sqll; scripts/build-sqll).

sqll has only the parse command (S3). Since S3b C11 it reads the sqlfluff
config: parse() runs it as the sqlfluff adapter runs sqlfluff (the raw
templater, --ignore-local-config, and the extra config of the case as a
--config file). sqll fails closed on a setting that it cannot do: exit
code 2 and "unsupported: <item>", which the adapter raises as Unsupported
(harness/sqll.md lists the differences from "sqlfluff parse"). The adapter
raises Unsupported for each other item: lint, fix, and a parse as a user
(the templater suites need the templater of the config, default jinja).

This module also has the facts of the worktree that the tool check compares
with the binary (tools.check_sqll): the expected version and the source
hash. crates/sqll/build.rs computes the same source hash at build time.
"""

import hashlib
import os
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from ..paths import REPO_ROOT
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
from .sqlfluff import CONFIG_NAME, _parse_output, sqlfluff_toml

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


class SqllAdapter(Adapter):
    name = "sqll"
    lints = False

    def __init__(self, binary: Path | None = None) -> None:
        self.binary = binary or binary_path()
        self._version: str | None = None

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

    def lint(self, sql_paths, rules, dialect, config, workdir) -> LintResult:
        raise Unsupported("lint")

    def fix(self, sql_path, rules, dialect, config, workdir) -> FixResult:
        raise Unsupported("fix")

    def parse_file(
        self, sql_path, dialect, cwd, code_only=False, include_meta=False
    ) -> ParseResult:
        # A parse as a user reads the config files and uses the templater of
        # the config (default: jinja), and the in-file config lines. sqll
        # has only the raw templater (S6, S11) and reads no in-file config
        # line.
        raise Unsupported("templater")

    def fix_file(
        self, sql_path, rules, dialect, cwd, show_violations=False
    ) -> FileFixResult:
        raise Unsupported("fix")

    def _run(self, cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=isolated_env(EmptyHome.path()),
            timeout=TIMEOUT_S,
        )


def raise_unsupported(rc: int, stderr: str) -> None:
    """Raise Unsupported for a run that sqll stopped as unsupported: exit
    code 2 and the line "Error: unsupported: <item>. <why>."."""
    if rc != 2:
        return
    for line in stderr.splitlines():
        if line.startswith(UNSUPPORTED_PREFIX):
            item = line[len(UNSUPPORTED_PREFIX) :].split(". ", 1)[0].rstrip(".")
            raise Unsupported(item)
