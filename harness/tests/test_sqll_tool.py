"""S3 T12: the sqll adapter and the sqll tool check.

The tool check must fail closed: a missing binary, another version, a stale
binary (its source hash is not that of the worktree), a binary that needs
libpython, and a binary that does not parse. The tests use fake binaries,
so they need no build. The adapter must give "unsupported: <item>" for each
rule, autofix, and templater case of the pinned fixtures.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from sqll_harness import cli, tools
from sqll_harness.adapters import ADAPTERS
from sqll_harness.adapters import sqll as sqll_adapter
from sqll_harness.adapters.base import Unsupported
from sqll_harness.cases import FAIL, UNSUPPORTED
from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT, TOOL_SPECS_DIR
from sqll_harness.suites import SUITES

TABLES = b'{"files": []}\n'


def _script(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def _worktree(tmp_path: Path) -> Path:
    """A small worktree with the inputs of the version and the source hash."""
    root = tmp_path / "worktree"
    (root / "crates" / "sqll_dialects").mkdir(parents=True)
    (root / "Cargo.toml").write_text('[workspace.package]\nversion = "0.1.0"\n')
    (root / "Cargo.lock").write_text("lock\n")
    (root / "rust-toolchain.toml").write_text("toolchain\n")
    (root / "crates" / "sqll_dialects" / "generated.json").write_bytes(TABLES)
    (root / "crates" / "sqll" / "src").mkdir(parents=True)
    (root / "crates" / "sqll" / "src" / "main.rs").write_text("fn main() {}\n")
    return root


def _fake_sqll(tmp_path: Path, version: str, source: str, tree: bool = True) -> Path:
    build = json.dumps({"version": version, "source_sha256": source})
    out = '[{"filepath": "check.sql", "segments": {"file": {}}}]' if tree else ""
    body = (
        f'[ "$1" = --version ] && {{ echo "sqll, version {version}"; exit 0; }}\n'
        f"[ \"$1\" = version ] && {{ echo '{build}'; exit 0; }}\n"
        f"[ \"$1\" = parse ] && {{ echo '{out}'; exit 0; }}\n"
        "exit 2\n"
    )
    return _script(tmp_path / "bin" / "sqll", body)


def _fake_readelf(tmp_path: Path, monkeypatch, libs: list[str]) -> None:
    lines = "".join(
        f"echo ' 0x0000000000000001 (NEEDED)             Shared library: [{lib}]'\n"
        for lib in libs
    )
    _script(tmp_path / "path" / "readelf", lines)
    monkeypatch.setenv("PATH", f"{tmp_path / 'path'}{os.pathsep}{os.environ['PATH']}")


LIBC = ["libc.so.6", "libgcc_s.so.1"]


def _check(tmp_path, root, binary):
    return tools.check_sqll(tmp_path, TOOL_SPECS_DIR, binary=binary, worktree=root)


def test_the_version_is_the_crate_version_and_the_manifest_hash(tmp_path):
    root = _worktree(tmp_path)
    tables = hashlib.sha256(TABLES).hexdigest()
    assert sqll_adapter.expected_version(root) == f"0.1.0+tables.{tables}"


def test_the_source_hash_covers_each_source_file(tmp_path):
    root = _worktree(tmp_path)
    first, count = sqll_adapter.source_hash(root)
    assert count == 5
    # The hash of the sorted files: path, NUL, size, NUL, bytes.
    want = hashlib.sha256()
    for rel in sorted(
        [
            "Cargo.lock",
            "Cargo.toml",
            "crates/sqll/src/main.rs",
            "crates/sqll_dialects/generated.json",
            "rust-toolchain.toml",
        ]
    ):
        data = (root / rel).read_bytes()
        want.update(rel.encode() + b"\0" + str(len(data)).encode() + b"\0" + data)
    assert first == want.hexdigest()
    (root / "crates" / "sqll" / "src" / "main.rs").write_text("fn main() { }\n")
    second, _ = sqll_adapter.source_hash(root)
    (root / "crates" / "sqll" / "new.rs").write_text("")
    third, count = sqll_adapter.source_hash(root)
    (root / "Cargo.lock").write_text("lock 2\n")
    fourth, _ = sqll_adapter.source_hash(root)
    assert len({first, second, third, fourth}) == 4
    assert count == 6
    # Files outside the source set do not count.
    (root / "README.md").write_text("x")
    assert sqll_adapter.source_hash(root)[0] == fourth


def test_the_source_hash_has_the_inputs_of_build_rs():
    build_rs = (REPO_ROOT / "crates" / "sqll" / "build.rs").read_text("utf8")
    files = ", ".join(f'"{f}"' for f in sqll_adapter.SOURCE_FILES)
    dirs = ", ".join(f'"{d}"' for d in sqll_adapter.SOURCE_DIRS)
    assert f"const SOURCE_FILES: &[&str] = &[{files}];" in build_rs
    assert f"const SOURCE_DIRS: &[&str] = &[{dirs}];" in build_rs
    assert f'const MANIFEST: &str = "{sqll_adapter.TABLE_MANIFEST}";' in build_rs
    assert 'hasher.update(b"\\0");' in build_rs


def test_a_fresh_binary_passes(tmp_path, monkeypatch):
    root = _worktree(tmp_path)
    _fake_readelf(tmp_path, monkeypatch, LIBC)
    version = sqll_adapter.expected_version(root)
    binary = _fake_sqll(tmp_path, version, sqll_adapter.source_hash(root)[0])
    info = _check(tmp_path, root, binary)
    assert info.ok, info.errors
    assert info.version == info.pinned == version
    assert info.details == {
        "fresh_build": True,
        "needs_libpython": False,
        "parse": True,
    }


def test_a_stale_binary_fails(tmp_path, monkeypatch):
    root = _worktree(tmp_path)
    _fake_readelf(tmp_path, monkeypatch, LIBC)
    version = sqll_adapter.expected_version(root)
    old, _ = sqll_adapter.source_hash(root)
    binary = _fake_sqll(tmp_path, version, old)
    (root / "crates" / "sqll" / "src" / "main.rs").write_text("fn main() { }\n")
    new, _ = sqll_adapter.source_hash(root)
    info = _check(tmp_path, root, binary)
    assert info.details["fresh_build"] is False
    assert info.errors == [
        f"stale binary: its source hash {old} is not the hash {new} of the "
        "worktree. Run scripts/build-sqll."
    ]


def test_a_binary_with_no_build_record_fails(tmp_path, monkeypatch):
    root = _worktree(tmp_path)
    _fake_readelf(tmp_path, monkeypatch, LIBC)
    version = sqll_adapter.expected_version(root)
    binary = _fake_sqll(tmp_path, version, "x")
    binary.write_text(binary.read_text().replace('[ "$1" = version ]', "false"))
    info = _check(tmp_path, root, binary)
    assert info.details["fresh_build"] is False
    assert info.errors[0].startswith("stale binary: its source hash None ")


def test_a_binary_that_needs_libpython_fails(tmp_path, monkeypatch):
    root = _worktree(tmp_path)
    _fake_readelf(tmp_path, monkeypatch, [*LIBC, "libpython3.13.so.1.0"])
    version = sqll_adapter.expected_version(root)
    binary = _fake_sqll(tmp_path, version, sqll_adapter.source_hash(root)[0])
    info = _check(tmp_path, root, binary)
    assert info.details["needs_libpython"] is True
    assert info.errors == [
        "the binary needs libpython: libc.so.6, libgcc_s.so.1, libpython3.13.so.1.0"
    ]


def test_a_binary_that_readelf_cannot_read_fails(tmp_path, monkeypatch):
    root = _worktree(tmp_path)
    _script(tmp_path / "path" / "readelf", "echo 'Not an ELF file' >&2\nexit 1\n")
    monkeypatch.setenv("PATH", f"{tmp_path / 'path'}{os.pathsep}{os.environ['PATH']}")
    version = sqll_adapter.expected_version(root)
    binary = _fake_sqll(tmp_path, version, sqll_adapter.source_hash(root)[0])
    info = _check(tmp_path, root, binary)
    assert info.details["needs_libpython"] is True
    assert info.errors == ["readelf failed: Not an ELF file"]


def test_readelf_of_a_real_binary():
    libs = tools.needed_libraries(Path("/bin/sh"))
    assert isinstance(libs, list) and any(lib.startswith("libc.") for lib in libs)


def test_another_version_and_no_tree_fail(tmp_path, monkeypatch):
    root = _worktree(tmp_path)
    _fake_readelf(tmp_path, monkeypatch, LIBC)
    binary = _fake_sqll(
        tmp_path, "0.0.9+tables.x", sqll_adapter.source_hash(root)[0], tree=False
    )
    info = _check(tmp_path, root, binary)
    want = sqll_adapter.expected_version(root)
    assert info.errors == [
        f"version 0.0.9+tables.x is not the pin {want}",
        "parse does not work: exit code 0",
    ]


def test_a_missing_binary_fails(tmp_path):
    info = _check(tmp_path, _worktree(tmp_path), tmp_path / "no" / "sqll")
    assert info.errors == [
        f"{tmp_path}/no/sqll does not exist. Run scripts/build-sqll."
    ]


def test_run_stops_before_the_cases_for_a_stale_binary(tmp_path, monkeypatch, capsys):
    _fake_readelf(tmp_path, monkeypatch, LIBC)
    binary = _fake_sqll(tmp_path, sqll_adapter.expected_version(), "0" * 64)
    monkeypatch.setenv("SQLL_BIN", str(binary))
    out = tmp_path / "report.json"
    args = ["run", "--tool=sqll", "--suite=dialects", f"--out={out}"]
    assert cli.main(args) == 2
    err = capsys.readouterr().err
    assert f"error: sqll: stale binary: its source hash {'0' * 64} " in err
    assert "running" not in err
    assert not out.exists()


def test_the_binary_path_setting(monkeypatch, tmp_path):
    monkeypatch.delenv("SQLL_BIN", raising=False)
    assert sqll_adapter.binary_path() == REPO_ROOT / "out" / "sqll" / "bin" / "sqll"
    monkeypatch.setenv("SQLL_BIN", str(tmp_path / "x"))
    assert sqll_adapter.binary_path() == tmp_path / "x"
    assert ADAPTERS["sqll"]().binary == tmp_path / "x"


# The adapter.


def test_parse_options():
    assert sqll_adapter.parse_options(None) == []
    assert sqll_adapter.parse_options({"core": {"max_parse_depth": 2000}}) == [
        "--max-parse-depth",
        "2000",
    ]
    for config, item in [
        ({"core": {"max_parse_depth": "2000"}}, "setting core.max_parse_depth"),
        ({"core": {"dialect": "ansi"}}, "setting core.dialect"),
        (
            {"rules": {"capitalisation.keywords": {"x": 1}}},
            "setting rules.capitalisation.keywords",
        ),
        ({"core": 1}, "setting core"),
    ]:
        with pytest.raises(Unsupported) as exc:
            sqll_adapter.parse_options(config)
        assert exc.value.item == item


def test_the_parse_command(tmp_path):
    log = tmp_path / "args"
    tree = '[{"filepath": "x.sql", "segments": {"file": {"keyword": "select"}}}]'
    binary = _script(tmp_path / "sqll", f"echo \"$@\" > {log}\necho '{tree}'\n")
    adapter = sqll_adapter.SqllAdapter(binary)
    result = adapter.parse(
        Path("x.sql"), "tsql", True, False, tmp_path, {"core": {"max_parse_depth": 9}}
    )
    assert log.read_text().split() == [
        "parse",
        "-f",
        "json",
        "--dialect",
        "tsql",
        "-c",
        "--max-parse-depth",
        "9",
        "x.sql",
    ]
    assert result.tree == {"file": {"keyword": "select"}}
    assert result.errors == [] and result.rc == 0
    binary = _script(
        tmp_path / "sqll", 'echo \'[{"segments": {"unparsable": []}}]\'\nexit 1\n'
    )
    result = sqll_adapter.SqllAdapter(binary).parse(
        Path("x.sql"), "ansi", False, True, tmp_path
    )
    assert result.has_unparsable and result.errors == ["exit code 1"]


@pytest.mark.parametrize("suite", ["rules", "autofix", "templater"])
def test_each_pinned_case_of_the_other_suites_is_unsupported(suite, tmp_path):
    # No binary: these items fail before a run of the binary.
    adapter = sqll_adapter.SqllAdapter(tmp_path / "no-binary")
    module = SUITES[suite]
    cases = module.discover(SQLFLUFF_ROOT)
    item = "lint" if suite == "rules" else "templater"
    counts = {"rules": 2527, "autofix": 61, "templater": 43}
    assert len(cases) == counts[suite]
    for case in cases:
        result = cli._run_one(module, adapter, case, SQLFLUFF_ROOT)
        assert result.status == FAIL, case.id
        assert result.reason == f"{UNSUPPORTED}{item}", case.id


def test_lint_and_fix_are_unsupported(tmp_path):
    adapter = sqll_adapter.SqllAdapter(tmp_path / "no-binary")
    calls = [
        (lambda: adapter.lint([], ["CP01"], "ansi", None, tmp_path), "lint"),
        (
            lambda: adapter.fix(tmp_path / "x.sql", ["CP01"], "ansi", None, tmp_path),
            "fix",
        ),
        (lambda: adapter.fix_file(tmp_path / "x.sql", None, "ansi", tmp_path), "fix"),
        (lambda: adapter.parse_file(tmp_path / "x.sql", None, tmp_path), "templater"),
    ]
    for call, item in calls:
        with pytest.raises(Unsupported) as exc:
            call()
        assert exc.value.item == item
    assert adapter.lints is False
    assert all(a.lints for name, a in ADAPTERS.items() if name != "sqll")
