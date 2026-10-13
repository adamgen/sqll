"""Each file with ported sqlfluff code has a header and a THIRD_PARTY.md row."""

import re

from sqll_harness.paths import REPO_ROOT

COPYRIGHT = "Copyright (c) 2018-2026 Alan Cruickshank"
SEARCH_DIRS = ("harness/sqll_harness", "scripts", "ci", "tools")


def _ported_rows() -> set[str]:
    text = (REPO_ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    section = text.split("Ported code", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| `([^`]+)` \|", section, re.MULTILINE))


def _header(path) -> str:
    """Return the comment lines at the start of the file, without a shebang."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            break
        if not line.startswith("#!"):
            lines.append(line.lstrip("# "))
    return " ".join(lines)


def _files_with_copyright() -> set[str]:
    found = set()
    for top in SEARCH_DIRS:
        for path in (REPO_ROOT / top).rglob("*"):
            if not path.is_file() or ".venv" in path.parts or path.suffix == ".pyc":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "Alan Cruickshank" in text:
                found.add(str(path.relative_to(REPO_ROOT)))
    return found


def test_each_ported_file_has_a_header():
    rows = _ported_rows()
    assert rows
    for name in rows:
        header = _header(REPO_ROOT / name)
        assert "port" in header and "sqlfluff 4.4.0" in header, name
        assert COPYRIGHT in header, name
        assert "MIT License" in header, name
        assert "THIRD_PARTY.md" in header, name


def test_each_file_with_sqlfluff_copyright_has_a_row():
    assert _files_with_copyright() <= _ported_rows()
