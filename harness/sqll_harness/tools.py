"""The installed tools: binary paths, pinned versions, and preflight checks.

The pins are the versions in tools/<tool>/uv.lock. scripts/setup installs
the tools in tools_dir() (SQLL_TOOLS_DIR):

- <tools_dir>/sqlfluff: venv with sqlfluff.
- <tools_dir>/sqlfluff-rs: venv with sqlfluff and sqlfluffrs.
- <tools_dir>/sqruff/bin/sqruff: sqruff built by tools/sqruff/install.sh.
- <tools_dir>/sqruff/python: venv with the Python templaters of sqruff.

The checks start each tool as a subprocess. The harness never imports a tool.
"""

import json
import subprocess
import tempfile
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .adapters.base import EmptyHome, isolated_env
from .paths import TOOL_SPECS_DIR, tools_dir

TIMEOUT_S = 120

# Prints the version of the distribution argv[1] after it imports argv[2].
_IMPORT_CHECK = (
    "import importlib, importlib.metadata, sys;"
    "importlib.import_module(sys.argv[2]);"
    "print(importlib.metadata.version(sys.argv[1]))"
)


@dataclass
class ToolInfo:
    name: str
    binary: str
    pinned: str
    version: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "ok": self.ok}


def lock_version(project: Path, package: str) -> str:
    """Return the version of a package in <project>/uv.lock."""
    data = tomllib.loads((project / "uv.lock").read_text(encoding="utf8"))
    found = {p["version"] for p in data.get("package", []) if p["name"] == package}
    if len(found) != 1:
        raise ValueError(f"{project}/uv.lock: {len(found)} versions of {package}")
    return found.pop()


def sqruff_env(root: Path | None = None) -> dict[str, str]:
    """Return the environment to run the sqruff binary in.

    The Python interpreter in sqruff finds its venv through the first
    python3 on PATH. The venv holds the Python templaters (jinja, python).
    """
    env = isolated_env(EmptyHome.path())
    python_bin = (root or tools_dir()) / "sqruff" / "python" / "bin"
    env["PATH"] = f"{python_bin}:{env.get('PATH', '')}"
    return env


def _run(cmd: list[str | Path], env: dict[str, str] | None = None, **kwargs):
    """Run a command. An OS error or a timeout gives exit code 127."""
    args = [str(c) for c in cmd]
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env=env or isolated_env(EmptyHome.path()),
            **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(
            args, 127, "", f"{type(exc).__name__}: {exc}"
        )


def _last_line(proc: subprocess.CompletedProcess) -> str:
    text = (proc.stderr or proc.stdout).strip()
    return text.splitlines()[-1] if text else f"exit code {proc.returncode}"


def _version_of(info: ToolInfo, cmd: list[str | Path], env=None) -> None:
    """Set info.version from the last word of the "--version" output."""
    proc = _run(cmd, env)
    if proc.returncode != 0:
        info.errors.append(f"{cmd[-1]} failed: {_last_line(proc)}")
        return
    info.version = proc.stdout.strip().rsplit(" ", 1)[-1]
    if info.version != info.pinned:
        info.errors.append(f"version {info.version} is not the pin {info.pinned}")


def _python_package(
    info: ToolInfo, venv: Path, dist: str, module: str, pinned: str
) -> None:
    """Check through the venv python that a package imports and is pinned."""
    proc = _run([venv / "bin" / "python3", "-I", "-c", _IMPORT_CHECK, dist, module])
    if proc.returncode != 0:
        info.errors.append(f"{module} is not importable: {_last_line(proc)}")
        return
    version = proc.stdout.strip()
    info.details[dist] = version
    if version != pinned:
        info.errors.append(f"{dist} {version} is not the pin {pinned}")


def _missing(info: ToolInfo, *paths: Path) -> bool:
    for path in paths:
        if not path.exists():
            info.errors.append(f"{path} does not exist. Run scripts/setup.")
    return not info.ok


def check_sqlfluff(root: Path, specs: Path, name: str = "sqlfluff") -> ToolInfo:
    venv = root / name
    info = ToolInfo(name, str(venv / "bin" / "sqlfluff"), "")
    info.pinned = lock_version(specs / name, "sqlfluff")
    if not _missing(info, venv / "bin" / "sqlfluff"):
        _version_of(info, [info.binary, "--version"])
    return info


def check_sqlfluff_rs(root: Path, specs: Path) -> ToolInfo:
    info = check_sqlfluff(root, specs, "sqlfluff-rs")
    if info.version is not None:
        pinned = lock_version(specs / "sqlfluff-rs", "sqlfluffrs")
        _python_package(info, root / "sqlfluff-rs", "sqlfluffrs", "sqlfluffrs", pinned)
    return info


def _sqruff_parse(binary: Path, env, sql: str, config: str | None) -> dict | str:
    """Parse sql with sqruff. Return the JSON tree, or an error message."""
    with tempfile.TemporaryDirectory(prefix="sqll-check-") as tmp:
        (Path(tmp) / "check.sql").write_text(sql)
        cmd: list[str | Path] = [binary, "parse", "-f", "json", "--dialect", "ansi"]
        if config is not None:
            (Path(tmp) / "check.cfg").write_text(config)
            cmd += ["--config", "check.cfg"]
        proc = _run([*cmd, "check.sql"], env, cwd=tmp)
    if proc.returncode != 0:
        return _last_line(proc)
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return "no JSON parse output"


def check_sqruff(root: Path, specs: Path) -> ToolInfo:
    binary = root / "sqruff" / "bin" / "sqruff"
    venv = root / "sqruff" / "python"
    info = ToolInfo("sqruff", str(binary), lock_version(specs / "sqruff", "sqruff"))
    if _missing(info, binary, venv / "bin" / "python3"):
        return info
    env = sqruff_env(root)
    _version_of(info, [binary, "--version"], env)
    if not info.ok:
        return info
    _python_package(
        info, venv, "sqruff", "sqruff.templaters.jinja_templater", info.pinned
    )

    proc = _run([binary, "templaters"], env)
    info.details["templaters"] = proc.stdout.split()
    if proc.returncode != 0 or "jinja" not in info.details["templaters"]:
        info.errors.append("no jinja templater: build with the python feature")

    tree = _sqruff_parse(binary, env, "select 1\n", None)
    info.details["parse"] = isinstance(tree, dict) and "file" in tree
    if not info.details["parse"]:
        info.errors.append(f"parse does not work: {tree}")

    config = "[sqruff]\ntemplater = jinja\n[sqruff:templater:jinja:context]\nc = x1\n"
    tree = _sqruff_parse(binary, env, "select {{ c }}\n", config)
    rendered = json.dumps(tree)
    info.details["jinja"] = '"naked_identifier": "x1"' in rendered
    if not info.details["jinja"]:
        info.errors.append(f"jinja templater does not work: {tree}")
    return info


CHECKS = {
    "sqlfluff": check_sqlfluff,
    "sqlfluff-rs": check_sqlfluff_rs,
    "sqruff": check_sqruff,
}


def check(
    names: list[str] | None = None,
    root: Path | None = None,
    specs: Path = TOOL_SPECS_DIR,
) -> list[ToolInfo]:
    """Check the installed tools. Default: all tools."""
    root = root or tools_dir()
    return [CHECKS[name](root, specs) for name in names or CHECKS]
