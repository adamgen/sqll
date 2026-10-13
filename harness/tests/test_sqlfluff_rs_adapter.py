import json
import tomllib
from pathlib import Path

import pytest
from conftest import needs, needs_sqlfluff

from sqll_harness import cli
from sqll_harness.adapters import ADAPTERS
from sqll_harness.adapters.sqlfluff import SqlfluffAdapter
from sqll_harness.adapters.sqlfluff_rs import (
    RUST_CONFIG,
    RustConfigConflict,
    RustParserNotUsed,
    SqlfluffRsAdapter,
    check_inline_config,
    check_user_config,
    user_config_folders,
    with_rust_config,
)
from sqll_harness.cases import ERROR, PASS
from sqll_harness.paths import SQLFLUFF_ROOT, tools_dir
from sqll_harness.suites import autofix, dialects, rules, templater

needs_sqlfluff_rs = needs("sqlfluff-rs/bin/sqlfluff")
RUST_KEYS = {"use_rust_parser": True, "use_rust_rules": True}


def test_adapter_is_registered():
    assert ADAPTERS["sqlfluff-rs"] is SqlfluffRsAdapter
    assert SqlfluffRsAdapter.config_layer == {"core": RUST_KEYS}
    assert SqlfluffAdapter.config_layer is None


def test_with_rust_config_adds_only_the_layer_keys():
    case = {"core": {"dialect": "tsql", "max_line_length": 40}, "rules": {"x": 1}}
    before = json.loads(json.dumps(case))
    got = with_rust_config(case)
    assert got == {
        "core": {"dialect": "tsql", "max_line_length": 40, **RUST_KEYS},
        "rules": {"x": 1},
    }
    assert case == before
    assert with_rust_config(None) == RUST_CONFIG
    assert with_rust_config({"layout": {"a": "b"}}) == {
        "layout": {"a": "b"},
        "core": RUST_KEYS,
    }


@pytest.mark.parametrize(
    "case",
    [
        {"core": {"use_rust_parser": False}},
        {"core": {"use_rust_parser": True}},
        {"core": {"use_rust_rules": "auto"}},
        {"core": "x"},
    ],
)
def test_with_rust_config_does_not_change_a_case_setting(case):
    with pytest.raises(RustConfigConflict):
        with_rust_config(case)


@pytest.mark.parametrize(
    "line",
    [
        "-- sqlfluff:use_rust_parser:False",
        "--sqlfluff:USE_RUST_RULES:false",
        "-- sqlfluff:core:use_rust_parser:False",
    ],
)
def test_inline_config_with_a_layer_key_is_a_conflict(tmp_path, line):
    sql = tmp_path / "a.sql"
    sql.write_text(f"select 1\n{line}\n")
    with pytest.raises(RustConfigConflict, match="in-file config line"):
        check_inline_config(sql)


def test_other_lines_are_not_a_conflict(tmp_path):
    sql = tmp_path / "a.sql"
    sql.write_text(
        "-- sqlfluff:dialect:ansi\n select 1 -- sqlfluff:use_rust_parser:False\n"
    )
    check_inline_config(sql)


def test_user_config_folders(tmp_path):
    cwd = tmp_path / "root"
    home = tmp_path / "home"
    folders = user_config_folders(Path("a/b/x.sql"), cwd, home)
    for folder in (
        home,
        home / "sqlfluff",
        home / ".config" / "sqlfluff",
        cwd,
        tmp_path,
        Path("/"),
        cwd / "a",
        cwd / "a" / "b",
    ):
        assert folder.resolve() in folders or folder in folders
    assert len(folders) == len(set(folders))


@pytest.mark.parametrize(
    "where,name",
    [
        ("root/a/b", ".sqlfluff"),
        ("root/a", "setup.cfg"),
        ("root", "tox.ini"),
        (".", "pep8.ini"),
        ("home", "pyproject.toml"),
        ("home/sqlfluff", ".sqlfluff"),
        ("home/.config/sqlfluff", ".sqlfluff"),
    ],
)
def test_user_config_file_with_a_layer_key_is_a_conflict(tmp_path, where, name):
    cwd, home = tmp_path / "root", tmp_path / "home"
    (cwd / "a" / "b").mkdir(parents=True)
    (cwd / "a" / "b" / "x.sql").write_text("select 1\n")
    check_user_config(Path("a/b/x.sql"), cwd, home)
    (tmp_path / where).mkdir(parents=True, exist_ok=True)
    (tmp_path / where / name).write_text("[sqlfluff]\nuse_rust_parser = False\n")
    with pytest.raises(RustConfigConflict, match="has a sqlfluff-rs layer key"):
        check_user_config(Path("a/b/x.sql"), cwd, home)


def test_user_config_checks_the_inline_config(tmp_path):
    (tmp_path / "x.sql").write_text("-- sqlfluff:use_rust_rules:False\nselect 1\n")
    with pytest.raises(RustConfigConflict):
        check_user_config(Path("x.sql"), tmp_path, tmp_path / "home")


def test_layer_file_is_not_in_a_case_folder():
    adapter = SqlfluffRsAdapter()
    sql = templater.FIXTURE_DIR / "jinja_a" / "jinja.sql"
    layer = adapter.user_config_file(sql, SQLFLUFF_ROOT)
    assert layer.name == "pyproject.toml"
    assert tomllib.loads(layer.read_text()) == {"tool": {"sqlfluff": RUST_CONFIG}}
    assert SQLFLUFF_ROOT not in layer.parents


class _Recorder(SqlfluffRsAdapter):
    """Records the config file of each command. With verbose, adds -vvv
    and records if sqlfluff logs that it uses the Rust parser."""

    def __init__(self, verbose=False):
        super().__init__()
        self.verbose = verbose
        self.configs = []
        self.rust_logs = []

    def _run(self, cmd, cwd):
        assert cmd.count("--config") == 1, cmd
        path = Path(cmd[cmd.index("--config") + 1])
        self.configs.append(tomllib.loads(path.read_text())["tool"]["sqlfluff"])
        if self.verbose:
            cmd = cmd[:2] + ["-vvv"] + cmd[2:]
        proc = super()._run(cmd, cwd)
        self.rust_logs.append("Using Rust parser" in proc.stdout + proc.stderr)
        return proc


def _rule_case(tmp_path, configs):
    path = tmp_path / "CP01.yml"
    path.write_text(
        "rule: CP01\n"
        "test_fail:\n"
        "  fail_str: SELECT a from b\n"
        "  fix_str: SELECT a FROM b\n" + (f"  configs: {json.dumps(configs)}\n")
    )
    return rules.load_file(path)[0]


def _autofix_case(tmp_path, config):
    folder = tmp_path / "ansi" / "case"
    folder.mkdir(parents=True)
    (folder / "test-config.yml").write_text("test-config:\n  rules:\n    - CP01\n")
    (folder / "before.sql").write_text("SELECT a from b\n")
    (folder / "after.sql").write_text("SELECT a FROM b\n")
    (folder / ".sqlfluff").write_text(config)
    return autofix.AutofixCase("autofix/ansi/case", "ansi", folder)


@needs_sqlfluff_rs
@pytest.mark.parametrize("verbose", [False, True])
def test_each_command_gets_the_layer(tmp_path, verbose):
    adapter = _Recorder(verbose)
    dialect = next(
        c for c in dialects.discover(SQLFLUFF_ROOT) if c.id == "dialects/ansi/select_a"
    )
    rule = _rule_case(tmp_path, {"core": {"max_line_length": 40}})
    fix = _autofix_case(tmp_path, "[sqlfluff]\nmax_line_length = 40\n")
    tmpl = next(
        c
        for c in templater.discover(SQLFLUFF_ROOT)
        if c.id == "templater/jinja_a/jinja"
    )
    results = [
        cli._run_one(dialects, adapter, dialect, SQLFLUFF_ROOT),
        cli._run_one(rules, adapter, rule, SQLFLUFF_ROOT),
        cli._run_one(autofix, adapter, fix, SQLFLUFF_ROOT),
        cli._run_one(templater, adapter, tmpl, SQLFLUFF_ROOT),
    ]
    # parse; lint, fix; parse_file, 2 x fix_file; 2 x parse_file (code_only).
    assert len(adapter.configs) == 8
    rule_config = {"core": {"max_line_length": 40, **RUST_KEYS}}
    assert adapter.configs[1:3] == [rule_config, rule_config]
    assert all(
        c == RUST_CONFIG for i, c in enumerate(adapter.configs) if i not in (1, 2)
    )
    if verbose:
        # Proof from the log of sqlfluff: each command used the Rust parser.
        assert adapter.rust_logs == [True] * 8
    else:
        assert [r.status for r in results] == [PASS] * 4, [r.reason for r in results]
        assert adapter.rust_logs == [False] * 8


@needs_sqlfluff_rs
def test_rule_case_that_sets_a_layer_key_is_an_error(tmp_path):
    case = _rule_case(tmp_path, {"core": {"use_rust_parser": False}})
    r = cli._run_one(rules, SqlfluffRsAdapter(), case, SQLFLUFF_ROOT)
    assert r.status == ERROR
    assert r.reason.startswith("RustConfigConflict: the case config sets core.")


@needs_sqlfluff_rs
def test_autofix_case_that_sets_a_layer_key_is_an_error(tmp_path):
    case = _autofix_case(tmp_path, "[sqlfluff]\nuse_rust_rules = False\n")
    r = cli._run_one(autofix, SqlfluffRsAdapter(), case, SQLFLUFF_ROOT)
    assert r.status == ERROR
    assert r.reason.startswith("RustConfigConflict: ")
    assert "has a sqlfluff-rs layer key" in r.reason


@needs_sqlfluff_rs
def test_dialect_case_that_sets_a_layer_key_is_an_error(tmp_path):
    sql = tmp_path / "a.sql"
    sql.write_text("-- sqlfluff:use_rust_parser:False\nselect 1\n")
    yml = tmp_path / "a.yml"
    yml.write_text("file: {}\n")
    case = dialects.DialectCase("dialects/ansi/a", "ansi", sql, yml, True, None)
    r = cli._run_one(dialects, SqlfluffRsAdapter(), case, tmp_path)
    assert r.status == ERROR
    assert "in-file config line" in r.reason
    case = dialects.DialectCase(
        "dialects/ansi/a", "ansi", sql, yml, True, {"core": {"use_rust_rules": True}}
    )
    sql.write_text("select 1\n")
    r = cli._run_one(dialects, SqlfluffRsAdapter(), case, tmp_path)
    assert r.status == ERROR
    assert "sets core.use_rust_rules" in r.reason


@needs_sqlfluff
def test_python_parser_fallback_is_an_error(tmp_path):
    # The sqlfluff venv has no sqlfluffrs. With use_rust_parser True,
    # sqlfluff warns and uses the Python parser.
    adapter = SqlfluffRsAdapter(venv=tools_dir() / "sqlfluff")
    sql = tmp_path / "a.sql"
    sql.write_text("select 1\n")
    with pytest.raises(RustParserNotUsed, match="used the Python parser"):
        adapter.parse(sql, "ansi", True, False, tmp_path)
    case = _rule_case(tmp_path, {"core": {"max_line_length": 40}})
    r = cli._run_one(rules, adapter, case, SQLFLUFF_ROOT)
    assert r.status == ERROR
    assert r.reason.startswith("RustParserNotUsed: ")


@needs_sqlfluff_rs
def test_report_shows_the_version_and_the_rust_config(tmp_path):
    out = tmp_path / "report.json"
    args = ["run", "--tool=sqlfluff-rs", "--suite=dialects", f"--out={out}"]
    assert cli.main([*args, "--filter=dialects/ansi/select_a"]) == 0
    rep = json.loads(out.read_text())
    assert rep["tools"] == {
        "sqlfluff-rs": {
            "version": "4.4.0",
            "config": {"core": RUST_KEYS},
            "preflight": {
                "sqlfluffrs": "4.4.0",
                "rust_parser": True,
                "rust_iteration_limit": True,
            },
        }
    }
    assert rep["summary"]["dialects"]["sqlfluff-rs"]["passed"] >= 1


@pytest.mark.parametrize(
    "warning,reason",
    [
        ("WARNING    use_rust_parser=True but sqlfluffrs not available.", "Python"),
        (
            "WARNING    Unable to apply match result in parse tree for x.sql, "
            "falling back to Python.",
            "no Rust parse arena",
        ),
    ],
)
def test_fallback_warnings_are_errors(tmp_path, warning, reason):
    # A fake sqlfluff that gives a tree and logs the warning.
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    tree = '[{"filepath": "a.sql", "segments": {"file": {}}}]'
    script = venv / "bin" / "sqlfluff"
    script.write_text(f"#!/bin/sh\necho '{warning}' >&2\necho '{tree}'\n")
    script.chmod(0o755)
    sql = tmp_path / "a.sql"
    sql.write_text("select 1\n")
    with pytest.raises(RustParserNotUsed, match=reason):
        SqlfluffRsAdapter(venv=venv).parse(sql, "ansi", True, False, tmp_path)
    plain = SqlfluffAdapter(venv=venv).parse(sql, "ansi", True, False, tmp_path)
    assert plain.tree == {"file": {}}
