"""S3 T11: the provenance of the code that sqll ports from sqlfluffrs.

crates/ported.json maps each ported file to its source file in the pinned
sqlfluff submodule, with the sha256 of the source. Each ported file has the
attribution header and is equal to its source after the header, or the
record gives the reason of the change. Each file of the 4 source crates is
ported or excluded with a reason, and each file in crates/ is in the record.
"""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT

PORTED = REPO_ROOT / "crates" / "ported.json"
RECORD = json.loads(PORTED.read_text("utf8"))
COMMIT = "0348222a3bcdb0226563f7349c5a39beb0641955"
COPYRIGHT = "Copyright (c) 2018-2026 Alan Cruickshank"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(SQLFLUFF_ROOT), *args],
        input=data,
        capture_output=True,
        check=True,
    ).stdout


def source_files(record: dict) -> dict[str, bytes]:
    """The content of each file of the source crates, of the license file, and
    of each other source file of the record, at the pinned commit."""
    commit = record["source"]["commit"]
    names = set(
        git("ls-tree", "-r", "--name-only", commit, "--", *record["crates"])
        .decode()
        .split("\n")
    ) - {""}
    names |= {f["source"] for f in record["files"]}
    names.add(record["license_copy"]["source"])
    names = sorted(names)
    batch = "".join(f"{commit}:{n}\n" for n in names).encode()
    out = git("cat-file", "--batch", data=batch)
    files, pos = {}, 0
    for name in names:
        head_end = out.index(b"\n", pos)
        head = out[pos:head_end].split()
        assert head[1] == b"blob", (name, head)
        size = int(head[2])
        files[name] = out[head_end + 1 : head_end + 1 + size]
        pos = head_end + 1 + size + 1
    return files


SOURCES = source_files(RECORD)


def header(record: dict, source: str, path: str, changed: bool) -> bytes:
    mark = "#" if path.endswith(".toml") else "//"
    commit = record["source"]["commit"]
    lines = [h.format(source=source, commit=commit) for h in record["header"]]
    if changed:
        lines.append(record["changed_line"])
    return ("".join(f"{mark} {line}\n" for line in lines) + "\n").encode()


def problems(root: Path, record: dict, sources: dict[str, bytes]) -> list[str]:
    """Return each difference between the record, the files under root, and
    the source files."""
    found = []
    source = record["source"]
    if source["commit"] != COMMIT or source["tag"] != "4.4.0":
        found.append(f"source: not the pinned sqlfluff: {source}")
    expected_header = [
        "This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):",
        "{source}",
        "Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,",
        "commit {commit}.",
        f"{COPYRIGHT}. MIT License: see",
        "crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.",
    ]
    if record["header"] != expected_header:
        found.append("header: not the attribution header")
    covered: list[str] = []
    for f in record["files"]:
        src, path, changed = f["source"], f["path"], f["changed"]
        covered.append(src)
        if src not in sources:
            found.append(f"{path}: no source file {src}")
            continue
        if sha256(sources[src]) != f["source_sha256"]:
            found.append(f"{path}: the source sha256 is not that of {src}")
        if changed is not None and not (isinstance(changed, str) and changed.strip()):
            found.append(f"{path}: a changed file needs a reason")
        target = root / path
        if not target.is_file():
            found.append(f"{path}: the file does not exist")
            continue
        data = target.read_bytes()
        head = header(record, src, path, changed is not None)
        if not data.startswith(head):
            found.append(f"{path}: no attribution header for {src}")
            continue
        body = data[len(head) :]
        if changed is None and body != sources[src]:
            found.append(f"{path}: differs from {src} after the header")
        if changed is not None and body == sources[src]:
            found.append(f"{path}: listed as changed, but equal to {src}")
    for e in record["excluded"]:
        covered.append(e["source"])
        if e["source"] not in sources:
            found.append(f"excluded {e['source']}: no such source file")
        elif sha256(sources[e["source"]]) != e["source_sha256"]:
            found.append(f"excluded {e['source']}: the sha256 is not that of the file")
        if not e["reason"].strip():
            found.append(f"excluded {e['source']}: no reason")
    crate_files = sorted(
        s for s in sources if any(s.startswith(c + "/") for c in record["crates"])
    )
    for src in crate_files:
        if covered.count(src) != 1:
            found.append(f"{src}: ported or excluded {covered.count(src)} times")
    lic = record["license_copy"]
    copy = root / lic["path"]
    if sha256(sources[lic["source"]]) != lic["source_sha256"]:
        found.append(f"{lic['path']}: the sha256 is not that of {lic['source']}")
    if not copy.is_file() or copy.read_bytes() != sources[lic["source"]]:
        found.append(f"{lic['path']}: not a copy of {lic['source']}")
    listed = {f["path"] for f in record["files"]} | {n["path"] for n in record["new"]}
    listed.add(lic["path"])
    for n in record["new"]:
        if not (root / n["path"]).is_file() or not n["reason"].strip():
            found.append(f"{n['path']}: a new file must exist and have a reason")
    for path in sorted((root / "crates").rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and rel not in listed:
            found.append(f"{rel}: not in crates/ported.json")
    return found


def copy_tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "crates", root / "crates")
    shutil.copy2(REPO_ROOT / "Cargo.toml", root / "Cargo.toml")
    return root


def entry(record: dict, path: str) -> dict:
    return next(f for f in record["files"] if f["path"] == path)


def test_the_submodule_is_the_pinned_commit():
    assert git("rev-parse", "HEAD").decode().strip() == COMMIT
    status = (REPO_ROOT / "STATUS.md").read_text("utf8")
    assert f"commit `{COMMIT}`" in status


def test_the_ported_files_agree_with_the_record():
    assert problems(REPO_ROOT, RECORD, SOURCES) == []


def test_the_record_covers_the_4_crates_without_python():
    assert RECORD["crates"] == {
        "sqlfluffrs/sqlfluffrs_types": "crates/sqll_types",
        "sqlfluffrs/sqlfluffrs_lexer": "crates/sqll_lexer",
        "sqlfluffrs/sqlfluffrs_parser": "crates/sqll_parser",
        "sqlfluffrs/sqlfluffrs_dialects": "crates/sqll_dialects",
    }
    for f in RECORD["files"]:
        src = f["source"]
        crate = next((c for c in RECORD["crates"] if src.startswith(c + "/")), None)
        if crate is None:
            assert (f["path"], src) == ("Cargo.toml", "sqlfluffrs/Cargo.toml")
        else:
            assert f["path"] == RECORD["crates"][crate] + src[len(crate) :]
    excluded = {e["source"] for e in RECORD["excluded"]}
    assert "sqlfluffrs/sqlfluffrs_parser/src/parser/python.rs" in excluded
    assert "sqlfluffrs/sqlfluffrs_parser/src/parser/arena_py.rs" in excluded
    assert "sqlfluffrs/sqlfluffrs_dialects/build.rs" in excluded
    for f in RECORD["files"]:
        text = (REPO_ROOT / f["path"]).read_text("utf8")
        assert "pyo3" not in text, f["path"]
        assert 'feature = "python"' not in text, f["path"]


def test_each_file_of_the_source_crates_is_ported_or_excluded():
    crate_files = [
        s for s in SOURCES if any(s.startswith(c + "/") for c in RECORD["crates"])
    ]
    assert len(crate_files) == 60
    assert len(RECORD["files"]) + len(RECORD["excluded"]) == 61  # with Cargo.toml
    changed = [f["path"] for f in RECORD["files"] if f["changed"]]
    assert sorted(changed) == [
        "Cargo.toml",
        "crates/sqll_dialects/Cargo.toml",
        "crates/sqll_dialects/src/lib.rs",
        "crates/sqll_lexer/Cargo.toml",
        "crates/sqll_lexer/src/lexer.rs",
        "crates/sqll_lexer/src/lib.rs",
        "crates/sqll_parser/Cargo.toml",
        "crates/sqll_parser/src/lib.rs",
        "crates/sqll_parser/src/parser/mod.rs",
        "crates/sqll_types/Cargo.toml",
    ]


def _append_byte(root, record):
    path = root / "crates/sqll_types/src/lib.rs"
    path.write_bytes(path.read_bytes() + b"\n")


def _change_header(root, record):
    path = root / "crates/sqll_types/src/slice.rs"
    path.write_bytes(path.read_bytes().replace(b"tag 4.4.0", b"tag 4.3.0", 1))


def _changed_but_equal(root, record):
    f = entry(record, "crates/sqll_lexer/src/lib.rs")
    data = header(record, f["source"], f["path"], True) + SOURCES[f["source"]]
    (root / f["path"]).write_bytes(data)


def _equal_but_changed_body(root, record):
    path = root / "crates/sqll_parser/src/parser/core.rs"
    path.write_bytes(path.read_bytes().replace(b"fn ", b"fn  ", 1))


def _wrong_source_sha(root, record):
    entry(record, "crates/sqll_types/src/lib.rs")["source_sha256"] = "0" * 64


def _wrong_source_path(root, record):
    entry(record, "crates/sqll_types/src/lib.rs")["source"] = (
        "sqlfluffrs/sqlfluffrs_types/src/slice.rs"
    )


def _unlisted_file(root, record):
    (root / "crates/sqll_types/src/extra.rs").write_text("pub fn x() {}\n")


def _source_not_covered(root, record):
    record["excluded"] = [
        e for e in record["excluded"] if "python.rs" not in e["source"]
    ]


def _empty_reason(root, record):
    entry(record, "crates/sqll_lexer/src/lexer.rs")["changed"] = " "


def _license_changed(root, record):
    path = root / record["license_copy"]["path"]
    path.write_bytes(path.read_bytes() + b"x")


def _missing_new_file(root, record):
    (root / "crates/sqll_dialects/build.rs").unlink()


def _other_commit(root, record):
    record["source"]["commit"] = "1" * 40


MUTATIONS = {
    "a byte added to an equal file": _append_byte,
    "a changed header": _change_header,
    "a changed file that is equal to its source": _changed_but_equal,
    "a changed body of an equal file": _equal_but_changed_body,
    "a wrong source sha256": _wrong_source_sha,
    "a wrong source path": _wrong_source_path,
    "a file that is not in the record": _unlisted_file,
    "a source file that is not ported or excluded": _source_not_covered,
    "a change with no reason": _empty_reason,
    "a changed license copy": _license_changed,
    "a missing new file": _missing_new_file,
    "another source commit": _other_commit,
}


@pytest.mark.parametrize("name", MUTATIONS)
def test_a_mutated_copy_fails(tmp_path, name):
    root = copy_tree(tmp_path)
    record = json.loads(PORTED.read_text("utf8"))
    assert problems(root, record, SOURCES) == []
    MUTATIONS[name](root, record)
    assert problems(root, record, SOURCES), name
