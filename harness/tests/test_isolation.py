"""The harness must run tools only through their binaries (G1.5)."""

import importlib.util
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "sqll_harness"


def test_sqlfluff_is_not_importable():
    assert importlib.util.find_spec("sqlfluff") is None
    with pytest.raises(ImportError):
        import sqlfluff  # noqa: F401


def test_harness_code_does_not_import_sqlfluff():
    for path in PACKAGE.rglob("*.py"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            assert not stripped.startswith("import sqlfluff"), path
            assert not stripped.startswith("from sqlfluff"), path
