import json
import subprocess
import tomllib

import pytest
from conftest import needs, needs_all_tools

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


def _fake_sqlfluff(root, name, version, python_body):
    _script(root / name / "bin" / "sqlfluff", f'echo "sqlfluff, version {version}"\n')
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
    assert info.details == {"sqlfluffrs": "4.4.0"}
    _fake_sqlfluff(tmp_path, "sqlfluff-rs", "4.4.0", "echo 4.3.9\n")
    info = tools.check_sqlfluff_rs(tmp_path, TOOL_SPECS_DIR)
    assert info.errors == ["sqlfluffrs 4.3.9 is not the pin 4.4.0"]


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
    assert out["sqlfluff-rs"]["details"] == {"sqlfluffrs": "4.4.0"}
    sqruff = out["sqruff"]["details"]
    assert sqruff["sqruff"] == "0.41.0"
    assert sqruff["parse"] is True
    assert sqruff["jinja"] is True
    assert {"raw", "placeholder", "jinja", "python"} <= set(sqruff["templaters"])
