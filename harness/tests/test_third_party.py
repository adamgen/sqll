"""Each file with ported sqlfluff code has a header and a THIRD_PARTY.md row.

The ported sqlfluffrs crates in crates/ have one THIRD_PARTY.md section; the
record crates/ported.json lists each of their files
(harness/tests/test_sqll_ported.py checks it).
"""

import hashlib
import json
import re
import tomllib

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


def test_the_new_files_with_ported_parts_are_named():
    """THIRD_PARTY.md says that the new sqll files in crates/ have no
    sqlfluff code, except the files it names. Those are the new files with
    a "Parts of this file are a port" header."""
    text = (REPO_ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    start = text.index("The new sqll files in `crates/`")
    sentence = text[start : text.index("have ported parts", start)]
    named = set(re.findall(r"`(crates/[^`]+)`", sentence)) - {PORTED_RECORD}
    headers = {
        n["path"]
        for n in _ported_record()["new"]
        if (REPO_ROOT / n["path"]).is_file()
        and "Parts of this file are a port" in _header(REPO_ROOT / n["path"])
    }
    # 5 since S3b C9: the ported parse calls moved from crates/sqll/src/parse.rs
    # and crates/sqll_interfaces/src/parse.rs to crates/sqll_syntax/src/parse.rs.
    # 6 since S3b C11: crates/sqll_config/src/value.rs (coerce_value).
    assert len(headers) == 6
    assert named == headers


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
    ports = {"crates/sqll/src/main.rs", "crates/sqll_config/src/ini.rs"}
    assert found <= {CPYTHON_LICENSE, PORTED_RECORD, *ports}, found


def test_the_configparser_port_keeps_the_psf_license_and_notice():
    """S3b C11: the INI reader of sqll_config is a port of configparser."""
    head = (REPO_ROOT / "crates/sqll_config/src/ini.rs").read_text("utf-8")
    head = " ".join(
        line.removeprefix("//").strip() for line in head.split("\n\n")[0].splitlines()
    )
    for word in (
        "Lib/configparser.py",
        f"tag {CPYTHON_TAG}",
        CPYTHON_COMMIT,
        PSF_NOTICE,
        CPYTHON_LICENSE,
        "Changes:",
    ):
        assert word in head, word
    section = " ".join(_cpython_section().split())
    assert "`crates/sqll_config/src/ini.rs`" in section
    new = {n["path"]: n["reason"] for n in _ported_record()["new"]}
    assert CPYTHON_LICENSE in new["crates/sqll_config/src/ini.rs"]


TOMLI_LICENSE = "crates/LICENSE-tomli.txt"
TOMLI_LICENSE_SHA256 = (
    "b80816b0d530b8accb4c2211783790984a6e3b61922c2b5ee92f3372ab2742fe"
)


def test_the_tomllib_port_keeps_the_mit_license_and_notice():
    """S3b C11: the TOML reader of sqll_config is a port of tomllib (MIT)."""
    data = (REPO_ROOT / TOMLI_LICENSE).read_bytes()
    assert hashlib.sha256(data).hexdigest() == TOMLI_LICENSE_SHA256
    assert data.startswith(b"MIT License\n\nCopyright (c) 2021 Taneli Hukkinen\n")
    head = (REPO_ROOT / "crates/sqll_config/src/toml.rs").read_text("utf-8")
    for word in (
        "Lib/tomllib",
        "SPDX-License-Identifier: MIT",
        "Taneli",
        TOMLI_LICENSE,
    ):
        assert word in head, word
    section = _section("tomllib")
    for word in (
        f"`{TOMLI_LICENSE}`",
        "Taneli Hukkinen",
        "`crates/sqll_config/src/toml.rs`",
    ):
        assert word in section, word
    new = {n["path"]: n["reason"] for n in _ported_record()["new"]}
    assert TOMLI_LICENSE_SHA256 in new[TOMLI_LICENSE]


# The license of sqll and the notices of the binary (S3 T19).

SQLL_COPYRIGHT = "Copyright (c) 2026 The sqll authors"
RUST_LICENSE = "crates/LICENSE-rust-MIT.txt"
RUST_LICENSE_SHA256 = "b71bd43a069ca0641a9ecfe585ca7b3c53b5cc1608f8b68321168698e28b5ea1"
RUST_TAG = "1.97.0"
RUST_COMMIT = "2d8144b7880597b6e6d3dfd63a9a9efae3f533d3"
NOTICES = "crates/sqll/build/notices.rs"


def _section(title: str) -> str:
    text = (REPO_ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    return " ".join(text.split(f"\n## {title}\n", 1)[1].split("\n## ", 1)[0].split())


def test_sqll_is_under_the_mit_license():
    """The MIT text of the pinned sqlfluff, with the sqll copyright line."""
    sqlfluff = (REPO_ROOT / "third_party/sqlfluff/LICENSE.md").read_text("utf-8")
    assert COPYRIGHT in sqlfluff
    text = (REPO_ROOT / "LICENSE").read_text("utf-8")
    assert text == sqlfluff.replace(COPYRIGHT, SQLL_COPYRIGHT)
    assert text.startswith(f"MIT License\n\n{SQLL_COPYRIGHT}\n")
    section = _section("sqll")
    for word in ("`LICENSE`", SQLL_COPYRIGHT, 'license = "MIT"', "`sqll --license`"):
        assert word in section, word


def test_each_crate_of_the_workspace_has_the_mit_license():
    workspace = tomllib.loads((REPO_ROOT / "Cargo.toml").read_text("utf-8"))
    members = workspace["workspace"]["members"]
    assert len(members) == 13
    for member in members:
        manifest = tomllib.loads((REPO_ROOT / member / "Cargo.toml").read_text("utf-8"))
        assert manifest["package"]["license"] == "MIT", member


def test_the_rust_notice_is_a_copy_of_the_pinned_toolchain_tag():
    data = (REPO_ROOT / RUST_LICENSE).read_bytes()
    assert hashlib.sha256(data).hexdigest() == RUST_LICENSE_SHA256
    assert data.startswith(b"Copyright (c) The Rust Project Contributors\n")
    toolchain = tomllib.loads((REPO_ROOT / "rust-toolchain.toml").read_text("utf-8"))
    assert toolchain["toolchain"]["channel"] == RUST_TAG
    license_rs = (REPO_ROOT / "crates/sqll/src/license.rs").read_text("utf-8")
    assert f'pub const RUST_TAG: &str = "{RUST_TAG}";' in license_rs
    section = _section("Rust")
    for word in (f"tag `{RUST_TAG}`", f"commit `{RUST_COMMIT}`", f"`{RUST_LICENSE}`"):
        assert word in section, word
    new = {n["path"]: n["reason"] for n in _ported_record()["new"]}
    assert RUST_LICENSE_SHA256 in new[RUST_LICENSE]
    assert RUST_COMMIT in new[RUST_LICENSE]


def test_third_party_gives_the_allow_list_of_the_build():
    text = (REPO_ROOT / NOTICES).read_text("utf-8")
    block = text.split("pub const ALLOWED: &[&str] = &[", 1)[1].split("];", 1)[0]
    allowed = re.findall(r'"([^"]+)"', block)
    assert allowed[0] == "MIT" and len(allowed) == 8
    section = _section("Rust")
    assert f"The allow list, in the order of choice: {', '.join(allowed)}." in section
    for word in ("`cargo metadata`", NOTICES, "crates/sqll/tests/license.rs"):
        assert word in section, word
