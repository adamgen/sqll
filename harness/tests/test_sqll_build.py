"""S3 T11: the Rust workspace of sqll and scripts/build-sqll.

The manifest of the generated dialect tables must be the T5 generation, the
comparison must fail closed, and the build must have no Python: no pyo3 in
Cargo.lock, Python calls during cargo fail the build, and a binary that needs
libpython fails it.
"""

import importlib.machinery
import importlib.util
import json
import re
import subprocess
import tomllib

import pytest

from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT

_loader = importlib.machinery.SourceFileLoader(
    "build_sqll", str(REPO_ROOT / "scripts" / "build-sqll")
)
_spec = importlib.util.spec_from_loader("build_sqll", _loader)
build_sqll = importlib.util.module_from_spec(_spec)
_loader.exec_module(build_sqll)

MANIFEST = json.loads(build_sqll.MANIFEST.read_text("utf8"))
T5 = json.loads(
    (REPO_ROOT / "results" / "s3" / "sqlfluffrs-probe-build.json").read_text("utf8")
)
CRATES = ["sqll_types", "sqll_lexer", "sqll_parser", "sqll_dialects"]


def test_the_manifest_is_the_t5_generation():
    files = MANIFEST["files"]
    assert len(files) == 85
    assert sum(f["lines"] for f in files) == 414352
    t5 = {f["path"]: f for f in T5["generation"]["files"]}
    assert [f["path"] for f in files] == sorted(t5)
    for f in files:
        want = {k: t5[f["path"]][k] for k in ("bytes", "lines", "sha256")}
        assert {k: f[k] for k in ("bytes", "lines", "sha256")} == want, f["path"]
    assert MANIFEST["prefix"] == build_sqll.PREFIX
    assert all(f["path"].startswith(build_sqll.GENERATED) for f in files)


def test_the_manifest_names_the_pinned_generator():
    gen = MANIFEST["generator"]
    commit = subprocess.run(
        ["git", "-C", str(SQLFLUFF_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert gen["submodule_commit"] == commit == T5["sqlfluffrs"]["commit"]
    assert (
        gen["sqlfluff"]
        == "4.4.0"
        == T5["generation"]["python"]["installed"]["sqlfluff_version"]
    )
    assert gen["command"] == "utils/rustify.py build"
    lock = (REPO_ROOT / "tools" / "sqlfluff" / "uv.lock").read_text("utf8")
    assert re.search(r'name = "sqlfluff"\nversion = "4\.4\.0"', lock)


def _files():
    return [dict(f) for f in MANIFEST["files"]]


def test_compare_accepts_equal_files():
    assert build_sqll.compare(_files(), MANIFEST) == []


def test_compare_fails_closed():
    want = MANIFEST["files"]
    files = _files()
    files[3]["sha256"] = "0" * 64
    files[4]["bytes"] += 1
    files[5]["lines"] -= 1
    extra = dict(files[1], path=build_sqll.GENERATED + "extra/mod.rs")
    files = files[1:] + [extra]
    assert build_sqll.compare(files, MANIFEST) == sorted(
        [
            f"{want[0]['path']}: not generated",
            f"{want[3]['path']}: sha256 {'0' * 64}, manifest {want[3]['sha256']}",
            f"{want[4]['path']}: bytes {want[4]['bytes'] + 1}, manifest"
            f" {want[4]['bytes']}",
            f"{want[5]['path']}: lines {want[5]['lines'] - 1}, manifest"
            f" {want[5]['lines']}",
            f"{extra['path']}: generated, but not in the manifest",
        ]
    )
    assert build_sqll.compare([], dict(MANIFEST, files=[])) == [
        "the manifest has no file"
    ]


def test_a_generated_file_outside_the_table_folder_fails(tmp_path):
    (tmp_path / "utils").mkdir()
    (tmp_path / "utils" / "rustify.py").write_text("x")
    table = tmp_path / build_sqll.GENERATED / "mod.rs"
    table.parent.mkdir(parents=True)
    table.write_bytes(b"pub mod ansi;\n")
    files = build_sqll.generated_files(tmp_path, {"utils/rustify.py"})
    assert files == [
        {
            "path": build_sqll.GENERATED + "mod.rs",
            "bytes": 14,
            "lines": 1,
            "sha256": build_sqll.sha256(b"pub mod ansi;\n"),
        }
    ]
    (tmp_path / "utils" / "new.py").write_text("x")
    with pytest.raises(build_sqll.BuildError, match="outside"):
        build_sqll.generated_files(tmp_path, {"utils/rustify.py"})


def test_install_writes_the_tables_without_the_prefix(tmp_path):
    scratch = tmp_path / "scratch"
    table = scratch / build_sqll.GENERATED / "ansi" / "mod.rs"
    table.parent.mkdir(parents=True)
    table.write_bytes(b"x\n")
    files = [{"path": build_sqll.GENERATED + "ansi/mod.rs"}]
    dest = tmp_path / "tables"
    (dest / "old").mkdir(parents=True)
    build_sqll.install(scratch, files, dest)
    assert [p.relative_to(dest).as_posix() for p in dest.rglob("*")] == [
        "dialect",
        "dialect/ansi",
        "dialect/ansi/mod.rs",
    ]


def test_the_sqlfluff_of_the_tool_venv_must_be_the_pin(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    python = tools / "sqlfluff" / "bin" / "python"
    python.parent.mkdir(parents=True)
    info = {
        "sqlfluff_version": "4.3.0",
        "sqlfluff_file": str(tools / "sqlfluff" / "x.py"),
        "python": "3.13.16",
    }
    python.write_text(f"#!/bin/sh\necho '{json.dumps(info)}'\n")
    python.chmod(0o755)
    monkeypatch.setenv("SQLL_TOOLS_DIR", str(tools))
    with pytest.raises(build_sqll.BuildError, match="sqlfluff 4.3.0, not 4.4.0"):
        build_sqll.check_python(python, "4.4.0")
    assert build_sqll.check_python(python, None) == info
    info.update(sqlfluff_version="4.4.0", sqlfluff_file="/src/sqlfluff/x.py")
    python.write_text(f"#!/bin/sh\necho '{json.dumps(info)}'\n")
    with pytest.raises(build_sqll.BuildError, match="not from the tool venv"):
        build_sqll.check_python(python, "4.4.0")
    with pytest.raises(build_sqll.BuildError, match="Run scripts/setup"):
        build_sqll.check_python(tools / "none", "4.4.0")


def test_python_in_the_build_fails():
    assert (
        build_sqll.python_problems([], ["serde", "sha2"], {"sqll": ["libc.so.6"]}) == []
    )
    assert build_sqll.python_problems(["python3 x.py"], [], {}) == [
        "a Python call during cargo: python3 x.py"
    ]
    assert build_sqll.python_problems([], ["pyo3", "sqlfluffrs_python"], {}) == [
        "cargo tree has pyo3",
        "cargo tree has sqlfluffrs_python",
    ]
    assert build_sqll.python_problems([], [], {"sqll": ["libpython3.13.so.1.0"]}) == [
        "sqll needs libpython3.13.so.1.0"
    ]


def test_the_shims_record_a_call_and_fail(tmp_path):
    log = tmp_path / "calls.log"
    build_sqll.write_shims(tmp_path / "bin", log)
    for name in ("python", "python3", "python3.13"):
        result = subprocess.run([tmp_path / "bin" / name, "-c", "1"])
        assert result.returncode == build_sqll.SHIM_EXIT
    assert len(log.read_text().splitlines()) == 3


def test_tree_packages():
    text = (
        "sqll_types v0.1.0 (/x)\nregex v1.12.3\n\n[build-dependencies]\nsha2 v0.10.9\n"
    )
    assert build_sqll.tree_packages(text) == ["regex", "sha2", "sqll_types"]


def test_the_workspace_has_the_4_crates_the_binary_and_no_python():
    cargo = tomllib.loads((REPO_ROOT / "Cargo.toml").read_text("utf8"))
    members = [f"crates/{c}" for c in CRATES] + ["crates/sqll"]
    assert cargo["workspace"]["members"] == members
    lock = tomllib.loads((REPO_ROOT / "Cargo.lock").read_text("utf8"))
    names = {p["name"] for p in lock["package"]}
    assert {*CRATES, "sqll"} <= names
    assert not names & {"pyo3", "pyo3-ffi", "sqlfluffrs_python"}
    for crate in [*CRATES, "sqll"]:
        text = (REPO_ROOT / "crates" / crate / "Cargo.toml").read_text("utf8")
        assert "pyo3" not in text and "python" not in text, crate


def test_the_toolchain_is_the_rust_of_the_ci_image():
    pin = tomllib.loads((REPO_ROOT / "rust-toolchain.toml").read_text("utf8"))
    dockerfile = (REPO_ROOT / "ci" / "Dockerfile").read_text("utf8")
    image = re.search(r"^ARG RUST_IMAGE=\S+/rust:([0-9.]+)-slim", dockerfile, re.M)
    assert pin["toolchain"]["channel"] == image[1] == "1.97.0"
    final = dockerfile.rsplit("\nFROM ", 1)[1]
    assert "COPY --from=rust /usr/local/rustup /usr/local/rustup" in final
    assert "COPY --from=rust /usr/local/cargo /usr/local/cargo" in final


def test_the_generated_tables_are_not_committed():
    files = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "crates", "target"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "crates/sqll_dialects/generated.json" in files
    assert not [f for f in files if "/dialect/" in f or f.startswith("target/")]
    assert "/target/" in (REPO_ROOT / ".gitignore").read_text("utf8").splitlines()
    lib = (REPO_ROOT / "crates" / "sqll_dialects" / "src" / "lib.rs").read_text()
    assert 'include!(concat!(env!("OUT_DIR"), "/dialect.rs"));' in lib
