import json
import subprocess
import tomllib

import pytest
from conftest import needs, needs_all_tools, needs_sqlfluff

from sqll_harness import cli, tools
from sqll_harness.paths import REPO_ROOT, TOOL_SPECS_DIR, tools_dir


def test_pins_in_lock_files():
    assert tools.lock_version(TOOL_SPECS_DIR / "sqlfluff", "sqlfluff") == "4.4.0"
    rs = TOOL_SPECS_DIR / "sqlfluff-rs"
    assert tools.lock_version(rs, "sqlfluff") == "4.4.0"
    assert tools.lock_version(rs, "sqlfluffrs") == "4.4.0"
    assert tools.lock_version(TOOL_SPECS_DIR / "sqruff", "sqruff") == "0.41.0"


def _lock(tool):
    text = (TOOL_SPECS_DIR / tool / "uv.lock").read_text()
    return {p["name"]: p["version"] for p in tomllib.loads(text)["package"]}


def test_sqlfluff_and_sqlfluff_rs_have_the_same_dependencies():
    # Then a difference in results comes from sqlfluffrs only.
    plain, rs = _lock("sqlfluff"), _lock("sqlfluff-rs")
    plain.pop("sqll-tool-sqlfluff")
    rs.pop("sqll-tool-sqlfluff-rs")
    assert rs.pop("sqlfluffrs") == "4.4.0"
    assert plain == rs


def test_oracle_has_the_same_sqlfluff_packages():
    # scripts/sqlfluff-rule-oracle must run the sqlfluff of the harness.
    plain, oracle = _lock("sqlfluff"), _lock("sqlfluff-oracle")
    plain.pop("sqll-tool-sqlfluff")
    oracle.pop("sqll-sqlfluff-oracle")
    assert {k: oracle.get(k) for k in plain} == plain
    assert oracle["pytest"] == "9.1.1"


def test_rust_oracle_has_the_sqlfluff_rs_and_oracle_packages():
    # The oracle scripts with --rust must run the sqlfluff-rs of the harness.
    rs, oracle, rs_oracle = (
        _lock("sqlfluff-rs"),
        _lock("sqlfluff-oracle"),
        _lock("sqlfluff-rs-oracle"),
    )
    rs.pop("sqll-tool-sqlfluff-rs")
    oracle.pop("sqll-sqlfluff-oracle")
    rs_oracle.pop("sqll-sqlfluff-rs-oracle")
    assert rs_oracle == {**oracle, **rs}
    assert rs_oracle["sqlfluffrs"] == "4.4.0"


@needs("sqlfluff-rs-oracle/bin/python")
def test_setup_installs_the_rust_oracle():
    python = tools_dir() / "sqlfluff-rs-oracle" / "bin" / "python"
    code = (
        "import sqlfluff, sqlfluffrs, pytest;"
        "from sqlfluff.core.parser.rust_parser import RustParser;"
        "assert RustParser is not None;"
        "print(sqlfluff.__version__, pytest.__version__)"
    )
    out = subprocess.run(
        [str(python), "-I", "-c", code], capture_output=True, text=True, check=True
    ).stdout.split()
    assert out == ["4.4.0", "9.1.1"]


@needs("sqlfluff-oracle/bin/python")
def test_setup_installs_the_oracle():
    # CI runs scripts/sqlfluff-rule-oracle with this venv and no network.
    python = tools_dir() / "sqlfluff-oracle" / "bin" / "python"
    code = "import sqlfluff, pytest; print(sqlfluff.__version__, pytest.__version__)"
    out = subprocess.run(
        [str(python), "-I", "-c", code], capture_output=True, text=True, check=True
    ).stdout.split()
    assert out == [_lock("sqlfluff-oracle")["sqlfluff"], "9.1.1"]


def test_install_script_reads_the_same_sqruff_version():
    script = TOOL_SPECS_DIR / "sqruff" / "install.sh"
    out = subprocess.run(
        [str(script), "--print-version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out == tools.lock_version(TOOL_SPECS_DIR / "sqruff", "sqruff")


def test_lock_version_needs_exactly_one_version(tmp_path):
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "a"\nversion = "1"\n'
        '[[package]]\nname = "a"\nversion = "2"\n'
    )
    with pytest.raises(ValueError):
        tools.lock_version(tmp_path, "a")
    with pytest.raises(ValueError):
        tools.lock_version(tmp_path, "b")


def test_tools_dir_setting(monkeypatch, tmp_path):
    monkeypatch.delenv("SQLL_TOOLS_DIR", raising=False)
    assert tools_dir() == REPO_ROOT / ".tools"
    monkeypatch.setenv("SQLL_TOOLS_DIR", str(tmp_path))
    assert tools_dir() == tmp_path
    assert tools.sqruff_env()["PATH"].startswith(f"{tmp_path}/sqruff/python/bin:")


def _script(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


# A fake parse as sqlfluff[rs] does it. With use_rust_parser true in the
# config file, it logs the Rust parser, and stops at the iteration limit.
RUST_PARSE = """\
if grep -q 'use_rust_parser = true' pyproject.toml; then
  grep -q 'rust_parser_max_iterations = 1' pyproject.toml && {
    echo 'PanicException: Parser exceeded maximum iteration limit (1).' >&2
    exit 1
  }
  echo 'INFO       Using Rust parser (experimental)' >&2
fi
"""
TREE = '[{"filepath": "check.sql", "segments": {"file": {}}}]'


def _fake_sqlfluff(root, name, version, python_body, parse_body=RUST_PARSE):
    body = f"[ \"$1\" = parse ] && {{\n{parse_body}echo '{TREE}'\nexit 0\n}}\n"
    body += f'echo "sqlfluff, version {version}"\n'
    _script(root / name / "bin" / "sqlfluff", body)
    _script(root / name / "bin" / "python3", python_body)


def test_missing_tools(tmp_path):
    infos = {i.name: i for i in tools.check(root=tmp_path)}
    assert set(infos) == {"sqlfluff", "sqlfluff-rs", "sqruff"}
    for info in infos.values():
        assert not info.ok
        assert "does not exist. Run scripts/setup." in info.errors[0]
        assert info.version is None


def test_version_must_match_the_pin(tmp_path):
    _fake_sqlfluff(tmp_path, "sqlfluff", "4.3.0", "")
    info = tools.check_sqlfluff(tmp_path, TOOL_SPECS_DIR)
    assert info.version == "4.3.0"
    assert info.errors == ["version 4.3.0 is not the pin 4.4.0"]
    _fake_sqlfluff(tmp_path, "sqlfluff", "4.4.0", "")
    assert tools.check_sqlfluff(tmp_path, TOOL_SPECS_DIR).ok


def test_sqlfluff_rs_needs_importable_sqlfluffrs(tmp_path):
    fail = "echo 'ModuleNotFoundError: no sqlfluffrs' >&2\nexit 1\n"
    _fake_sqlfluff(tmp_path, "sqlfluff-rs", "4.4.0", fail)
    info = tools.check_sqlfluff_rs(tmp_path, TOOL_SPECS_DIR)
    assert info.errors == [
        "sqlfluffrs is not importable: ModuleNotFoundError: no sqlfluffrs"
    ]
    # The check runs in the venv python, with the names as arguments.
    ok = '[ "$1" = -I ] && [ "$4$5" = sqlfluffrssqlfluffrs ] && echo 4.4.0\n'
    _fake_sqlfluff(tmp_path, "sqlfluff-rs", "4.4.0", ok)
    info = tools.check_sqlfluff_rs(tmp_path, TOOL_SPECS_DIR)
    assert info.ok, info.errors
    assert info.details == {
        "sqlfluffrs": "4.4.0",
        "rust_parser": True,
        "rust_iteration_limit": True,
    }
    _fake_sqlfluff(tmp_path, "sqlfluff-rs", "4.4.0", "echo 4.3.9\n")
    info = tools.check_sqlfluff_rs(tmp_path, TOOL_SPECS_DIR)
    assert info.errors == ["sqlfluffrs 4.3.9 is not the pin 4.4.0"]


LIMIT_ERROR = (
    "the Rust parser does not run: a parse with rust_parser_max_iterations = 1 "
    "does not stop with 'maximum iteration limit'"
)


def test_sqlfluff_rs_must_use_the_rust_parser(tmp_path):
    ok = "echo 4.4.0\n"
    fallback = (
        "echo 'WARNING    use_rust_parser=True but sqlfluffrs not available.' >&2\n"
    )
    _fake_sqlfluff(tmp_path, "sqlfluff-rs", "4.4.0", ok, fallback)
    info = tools.check_sqlfluff_rs(tmp_path, TOOL_SPECS_DIR)
    assert info.details["rust_parser"] is False
    assert info.details["rust_iteration_limit"] is False
    assert info.errors == [
        "the Rust parser does not run: sqlfluff logs 'sqlfluffrs not available'",
        LIMIT_ERROR,
    ]
    _fake_sqlfluff(tmp_path, "sqlfluff-rs", "4.4.0", ok, "")
    info = tools.check_sqlfluff_rs(tmp_path, TOOL_SPECS_DIR)
    assert info.errors == [
        "the Rust parser does not run: no 'Using Rust parser' log, exit code 0",
        LIMIT_ERROR,
    ]
    # The controls: the Python parser (use_rust_parser false) must not log
    # the Rust parser, and must not stop at the limit.
    always = (
        "echo 'INFO       Using Rust parser (experimental)' >&2\n"
        "grep -q 'rust_parser_max_iterations = 1' pyproject.toml && {\n"
        "  echo 'maximum iteration limit' >&2\n  exit 1\n}\n"
    )
    _fake_sqlfluff(tmp_path, "sqlfluff-rs", "4.4.0", ok, always)
    info = tools.check_sqlfluff_rs(tmp_path, TOOL_SPECS_DIR)
    assert info.details["rust_parser"] is True
    assert info.details["rust_iteration_limit"] is True
    assert info.errors == [
        "the Rust parser check is not valid: the 'Using Rust parser' log is "
        "also there with use_rust_parser False",
        "the Rust parser check is not valid: the Python parser gives no tree "
        "with rust_parser_max_iterations = 1",
    ]


def _no_sqlfluffrs(tmp_path):
    """Return a tools folder where sqlfluff-rs is the sqlfluff venv. It has
    sqlfluff 4.4.0 but no sqlfluffrs."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "sqlfluff-rs").symlink_to(tools_dir() / "sqlfluff")
    return tmp_path


@needs_sqlfluff
def test_real_sqlfluff_without_sqlfluffrs(tmp_path):
    info = tools.check_sqlfluff_rs(_no_sqlfluffrs(tmp_path), TOOL_SPECS_DIR)
    assert info.version == "4.4.0"
    assert info.details["rust_parser"] is False
    assert info.details["rust_iteration_limit"] is False
    assert info.errors == [
        "sqlfluffrs is not importable: "
        "ModuleNotFoundError: No module named 'sqlfluffrs'",
        "the Rust parser does not run: sqlfluff logs 'sqlfluffrs not available'",
        LIMIT_ERROR,
    ]


@needs_sqlfluff
def test_run_stops_when_sqlfluffrs_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SQLL_TOOLS_DIR", str(_no_sqlfluffrs(tmp_path / "tools")))
    out = tmp_path / "report.json"
    args = ["run", "--tool=sqlfluff-rs", "--suite=dialects", f"--out={out}"]
    assert cli.main([*args, "--filter=dialects/ansi/select_a"]) == 2
    err = capsys.readouterr().err
    assert (
        "error: sqlfluff-rs: sqlfluffrs is not importable: "
        "ModuleNotFoundError: No module named 'sqlfluffrs'"
    ) in err
    assert "error: sqlfluff-rs: the Rust parser does not run" in err
    assert "running" not in err
    assert not out.exists()


def test_sqruff_version_must_match_the_pin(tmp_path):
    _script(tmp_path / "sqruff" / "bin" / "sqruff", "echo sqruff 0.40.0\n")
    _script(tmp_path / "sqruff" / "python" / "bin" / "python3", "")
    info = tools.check_sqruff(tmp_path, TOOL_SPECS_DIR)
    assert info.errors == ["version 0.40.0 is not the pin 0.41.0"]


def test_cli_tools_fails_when_not_installed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SQLL_TOOLS_DIR", str(tmp_path))
    assert cli.main(["tools", "--tool=sqlfluff"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["tools_dir"] == str(tmp_path)
    assert [t["ok"] for t in out["tools"]] == [False]


def test_run_fails_before_cases_when_a_tool_is_not_pinned(tmp_path, monkeypatch):
    _fake_sqlfluff(tmp_path, "sqlfluff", "4.3.0", "")
    monkeypatch.setenv("SQLL_TOOLS_DIR", str(tmp_path))
    out = tmp_path / "report.json"
    assert cli.main(["run", "--tool=sqlfluff", f"--out={out}"]) == 2
    assert not out.exists()


@needs_all_tools
def test_installed_tools(capsys):
    assert cli.main(["tools"]) == 0
    out = {t["name"]: t for t in json.loads(capsys.readouterr().out)["tools"]}
    assert {n: t["version"] for n, t in out.items()} == {
        "sqlfluff": "4.4.0",
        "sqlfluff-rs": "4.4.0",
        "sqruff": "0.41.0",
    }
    assert all(t["ok"] for t in out.values())
    assert out["sqlfluff-rs"]["details"] == {
        "sqlfluffrs": "4.4.0",
        "rust_parser": True,
        "rust_iteration_limit": True,
    }
    sqruff = out["sqruff"]["details"]
    assert sqruff["sqruff"] == "0.41.0"
    assert sqruff["parse"] is True
    assert sqruff["jinja"] is True
    assert {"raw", "placeholder", "jinja", "python"} <= set(sqruff["templaters"])
