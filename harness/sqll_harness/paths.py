"""Paths in the sqll repository."""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SQLFLUFF_ROOT = REPO_ROOT / "third_party" / "sqlfluff"
TOOL_SPECS_DIR = REPO_ROOT / "tools"
KNOWN_FAILURES_DIR = REPO_ROOT / "known_failures"
DEFAULT_REPORT = REPO_ROOT / "out" / "report.json"
DEFAULT_SUMMARY = REPO_ROOT / "out" / "summary.json"
RECORDED_SUMMARY = REPO_ROOT / "results" / "s1" / "summary.json"
OUT_DIR = REPO_ROOT / "out"


def sqlfluff_ref(root: Path) -> str:
    """Return the commit of the sqlfluff checkout at root, or "unknown"."""
    try:
        return subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def tools_dir() -> Path:
    """Return the folder of the installed tools.

    SQLL_TOOLS_DIR sets it. scripts/setup and scripts/test use the same
    setting. The default is .tools/ in the repository.
    """
    value = os.environ.get("SQLL_TOOLS_DIR")
    return Path(value).resolve() if value else REPO_ROOT / ".tools"
