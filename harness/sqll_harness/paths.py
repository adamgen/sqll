"""Paths in the sqll repository."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SQLFLUFF_ROOT = REPO_ROOT / "third_party" / "sqlfluff"
TOOLS_DIR = REPO_ROOT / ".tools"
KNOWN_FAILURES_DIR = REPO_ROOT / "known_failures"
DEFAULT_REPORT = REPO_ROOT / "out" / "report.json"
