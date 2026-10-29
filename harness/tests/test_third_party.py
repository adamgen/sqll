"""Each file with ported sqlfluff code has a header and a THIRD_PARTY.md row.

The ported sqlfluffrs crates in crates/ have one THIRD_PARTY.md section; the
record crates/ported.json lists each of their files
(harness/tests/test_sqll_ported.py checks it).
"""

import json
import re

from sqll_harness.paths import REPO_ROOT

COPYRIGHT = "Copyright (c) 2018-2026 Alan Cruickshank"
SEARCH_DIRS = ("harness/sqll_harness", "scripts", "ci", "tools", "crates")
PORTED_RECORD = "crates/ported.json"


def _ported_rows() -> set[str]:
    text = (REPO_ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    section = text.split("Ported code", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| `([^`]+)` \|", section, re.MULTILINE))


def _ported_record() -> dict:
    return json.loads((REPO_ROOT / PORTED_RECORD).read_text(encoding="utf-8"))


def _record_files() -> set[str]:
    """The ported files of crates/ported.json, its copy of the license, and the
    record itself (it names the copyright holder)."""
    record = _ported_record()
    files = {f["path"] for f in record["files"]}
    return files | {record["license_copy"]["path"], PORTED_RECORD}


def _header(path) -> str:
    """Return the comment lines at the start of the file, without a shebang.
    A comment line starts with "#" (Python, shell) or "//" (Rust)."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("//"):
            lines.append(line.lstrip("/ "))
            continue
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
    files = {f["path"] for f in _ported_record()["files"]}
    assert files
    for name in rows | files:
        header = _header(REPO_ROOT / name)
        assert "port" in header and "sqlfluff 4.4.0" in header, name
        assert COPYRIGHT in header, name
        assert "MIT License" in header, name
        assert "THIRD_PARTY.md" in header, name


def test_each_file_with_sqlfluff_copyright_has_a_row():
    assert _files_with_copyright() <= _ported_rows() | _record_files()


def test_third_party_names_the_ported_crates_and_the_generated_tables():
    text = (REPO_ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    section = text.split("\n## sqlfluffrs in crates/\n", 1)[1].split("\n## ", 1)[0]
    record = _ported_record()
    source = record["source"]
    for word in (
        source["repository"],
        f"tag `{source['tag']}`",
        f"commit `{source['commit']}`",
        "MIT",
        source["copyright"],
        PORTED_RECORD,
        record["license_copy"]["path"],
        "crates/sqll_dialects/generated.json",
        "scripts/build-sqll",
        "utils/rustify.py",
    ):
        assert word in section, word
    for source_crate, crate in record["crates"].items():
        assert f"| `{crate}` | `{source_crate}` |" in section, crate
