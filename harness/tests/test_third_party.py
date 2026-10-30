"""Each file with ported sqlfluff code has a header and a THIRD_PARTY.md row.

The ported sqlfluffrs crates in crates/ have one THIRD_PARTY.md section; the
record crates/ported.json lists each of their files
(harness/tests/test_sqll_ported.py checks it).
"""

import hashlib
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


CPYTHON_LICENSE = "crates/LICENSE-cpython.txt"
CPYTHON_LICENSE_SHA256 = (
    "78b12c3a81360b357002334f0e70ea0e92eebf7a9b358805c03c48484945f3bb"
)
CPYTHON_TAG = "v3.13.16"
CPYTHON_COMMIT = "cbc944f4bc59639a444dd971c737788ba2283a91"
PSF_NOTICE = "Copyright (c) 2001-2024 Python Software Foundation; All Rights Reserved"


def _cpython_section() -> str:
    text = (REPO_ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    return text.split("\n## CPython\n", 1)[1].split("\n## ", 1)[0]


def test_the_cpython_port_keeps_the_psf_license_and_notice():
    """PSF-2.0 clause 2: the License Agreement and the PSF notice stay with a
    derivative version. Clause 3: a summary of the changes."""
    license_path = REPO_ROOT / CPYTHON_LICENSE
    data = license_path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == CPYTHON_LICENSE_SHA256
    text = data.decode("utf-8")
    assert "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2" in text
    assert f'i.e., "{PSF_NOTICE}"' in text

    section = " ".join(_cpython_section().split())
    for word in (
        f"tag `{CPYTHON_TAG}`",
        f"commit `{CPYTHON_COMMIT}`",
        PSF_NOTICE,
        f"`{CPYTHON_LICENSE}`",
        "Changes:",
    ):
        assert word in section, word

    main = (REPO_ROOT / "crates/sqll/src/main.rs").read_text(encoding="utf-8")
    comment = " ".join(
        line.strip().removeprefix("///").strip()
        for line in main.split("fn normpath", 1)[0].splitlines()[-12:]
        if line.strip().startswith("///")
    )
    for word in (
        "Lib/posixpath.py",
        f"tag {CPYTHON_TAG}",
        CPYTHON_COMMIT,
        PSF_NOTICE,
        CPYTHON_LICENSE,
        "Changes:",
    ):
        assert word in comment, word

    new = {n["path"]: n["reason"] for n in _ported_record()["new"]}
    assert CPYTHON_LICENSE_SHA256 in new[CPYTHON_LICENSE]
    assert CPYTHON_LICENSE in new["crates/sqll/src/main.rs"]


def test_only_the_cpython_records_name_the_psf():
    """Each file with the PSF notice is the license copy, its record, or the
    port; a new port must add its own record."""
    found = set()
    for top in SEARCH_DIRS:
        for path in (REPO_ROOT / top).rglob("*"):
            if not path.is_file() or ".venv" in path.parts or path.suffix == ".pyc":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "Python Software Foundation" in text:
                found.add(str(path.relative_to(REPO_ROOT)))
    assert found <= {CPYTHON_LICENSE, PORTED_RECORD, "crates/sqll/src/main.rs"}, found
