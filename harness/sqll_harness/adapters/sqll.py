"""Adapter for the sqll binary (out/sqll/bin/sqll; scripts/build-sqll).

sqll has only the parse command (S3). It reads no config file and uses
only the raw templater (harness/sqll.md lists the differences from
"sqlfluff parse"). The adapter raises Unsupported for each other item:
lint, fix, a parse as a user (it needs the config files and the templater
of the config), and each extra setting other than core.max_parse_depth.

This module also has the facts of the worktree that the tool check compares
with the binary (tools.check_sqll): the expected version and the source
hash. crates/sqll/build.rs computes the same source hash at build time.
"""

import hashlib
import os
import subprocess
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
from .sqlfluff import _parse_output

TIMEOUT_S = 600
# SQLL_BIN sets another binary.
DEFAULT_BINARY = REPO_ROOT / "out" / "sqll" / "bin" / "sqll"
# The inputs of the source hash: these files, and each file under these
# folders. They must be those of crates/sqll/build.rs.
SOURCE_FILES = ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml")
SOURCE_DIRS = ("crates",)
TABLE_MANIFEST = "crates/sqll_dialects/generated.json"
BUILD_HELP = "Run scripts/build-sqll."


def binary_path() -> Path:
    value = os.environ.get("SQLL_BIN")
    return Path(value) if value else DEFAULT_BINARY


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
        cmd = [str(self.binary), "parse", "-f", "json", "--dialect", dialect]
        if code_only:
            cmd.append("-c")
        if include_meta:
            cmd.append("-m")
        cmd += parse_options(extra_config)
        cmd.append(str(sql_path))
        proc = self._run(cmd, cwd)
        return _parse_output(proc.stdout, proc.returncode, proc.stderr)

    def lint(self, sql_paths, rules, dialect, config, workdir) -> LintResult:
        raise Unsupported("lint")

    def fix(self, sql_path, rules, dialect, config, workdir) -> FixResult:
        raise Unsupported("fix")

    def parse_file(
        self, sql_path, dialect, cwd, code_only=False, include_meta=False
    ) -> ParseResult:
        # A parse as a user reads the config files and uses the templater of
        # the config (default: jinja). sqll has no config reader and only
        # the raw templater.
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


def parse_options(extra_config: dict[str, Any] | None) -> list[str]:
    """Return the parse options for the extra config of a case.

    sqll has an option only for core.max_parse_depth. Another setting raises
    Unsupported("setting <section>.<key>").
    """
    args: list[str] = []
    for section, values in (extra_config or {}).items():
        if not isinstance(values, dict):
            raise Unsupported(f"setting {section}")
        for key, value in values.items():
            if section == "core" and key == "max_parse_depth" and type(value) is int:
                args += ["--max-parse-depth", str(value)]
            else:
                raise Unsupported(f"setting {section}.{key}")
    return args
