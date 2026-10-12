"""Adapter for the sqlfluff binary."""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import tomli_w

from ..compare import has_node
from ..paths import tools_dir
from .base import Adapter, EmptyHome, ParseResult, ToolNotInstalled, isolated_env

TIMEOUT_S = 600


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
                # sqlfluff reads a config file as TOML only if its name is
                # pyproject.toml. Other names are read as INI.
                cfg = Path(tmp) / "pyproject.toml"
                cfg.write_text(tomli_w.dumps({"tool": {"sqlfluff": extra_config}}))
                cmd += ["--config", str(cfg)]
            cmd.append(str(sql_path))
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                env=isolated_env(EmptyHome.path()),
                timeout=TIMEOUT_S,
            )
        return _parse_output(proc.stdout, proc.returncode, proc.stderr)


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
