"""Paths in the sqll repository."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SQLFLUFF_ROOT = REPO_ROOT / "third_party" / "sqlfluff"
TOOL_SPECS_DIR = REPO_ROOT / "tools"
KNOWN_FAILURES_DIR = REPO_ROOT / "known_failures"
DEFAULT_REPORT = REPO_ROOT / "out" / "report.json"
DEFAULT_SUMMARY = REPO_ROOT / "out" / "summary.json"
RECORDED_SUMMARY = REPO_ROOT / "results" / "s1" / "summary.json"


def tools_dir() -> Path:
    """Return the folder of the installed tools.

    SQLL_TOOLS_DIR sets it. scripts/setup and scripts/test use the same
    setting. The default is .tools/ in the repository.
    """
    value = os.environ.get("SQLL_TOOLS_DIR")
    return Path(value).resolve() if value else REPO_ROOT / ".tools"
