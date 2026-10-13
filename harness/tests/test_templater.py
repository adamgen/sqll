import ast
import hashlib
import re
import shutil
from pathlib import Path

import pytest
from conftest import needs_sqlfluff

from sqll_harness import cli
from sqll_harness.adapters.base import ParseResult, isolated_env
from sqll_harness.adapters.sqlfluff import SqlfluffAdapter
from sqll_harness.cases import ERROR, FAIL, PASS
from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT
from sqll_harness.suites import templater

FIXTURES = Path(__file__).parent / "fixtures" / "templater"
CASES = {c.id: c for c in templater.discover(SQLFLUFF_ROOT)}
HARNESS_CASES = {c.id: c for c in templater.discover(FIXTURES)}
REAL_TEST = SQLFLUFF_ROOT / templater.TEST_FILE


# The case table


def test_suite_has_the_43_cases_of_the_table():
    table = templater.read_table(REAL_TEST)
    assert len(table) == 43
    assert len(CASES) == 43
    assert [(c.subpath, c.code_only, c.include_meta) for c in CASES.values()] == table
    assert list(CASES) == [f"templater/{row[0]}" for row in table]


def test_table_flags():
    flags = [(c.code_only, c.include_meta) for c in CASES.values()]
    assert flags.count((True, False)) == 31
    assert flags.count((False, False)) == 1
    assert flags.count((False, True)) == 11
    meta = [c.id for c in CASES.values() if c.include_meta]
    assert meta == [f"templater/jinja_l_metas/{i:03d}" for i in range(1, 12)]
    case = CASES["templater/jinja_b/jinja"]
    assert not case.code_only and not case.include_meta
    assert str(case.sql) == "test/fixtures/templater/jinja_b/jinja.sql"
    assert str(case.yml) == "test/fixtures/templater/jinja_b/jinja.yml"


def test_table_is_read_from_the_submodule(tmp_path):
    text = REAL_TEST.read_text(encoding="utf8")
    row = '("jinja_a/jinja", True, False),'
    assert text.count(row) == 1
    new_rows = '("jinja_a/jinja", False, True),\n("new/case", True, True),'
    text = text.replace(row, new_rows)
    test_file = tmp_path / templater.TEST_FILE
    test_file.parent.mkdir(parents=True)
    test_file.write_text(text, encoding="utf8")
    cases = templater.discover(tmp_path)
    assert len(cases) == 44
    assert (cases[0].id, cases[0].code_only, cases[0].include_meta) == (
        "templater/jinja_a/jinja",
        False,
        True,
    )
    assert cases[1].id == "templater/new/case"


def test_harness_code_has_no_copy_of_the_table():
    sources = [p.read_text(encoding="utf8") for p in templater_sources()]
    for subpath, _, _ in templater.read_table(REAL_TEST):
        for text in sources:
            assert subpath not in text


def templater_sources():
    yield from (REPO_ROOT / "harness" / "sqll_harness").rglob("*.py")
    yield REPO_ROOT / "scripts" / "sqlfluff-templater-oracle"
    yield REPO_ROOT / "scripts" / "sqlfluff_oracle.py"


def _table_file(tmp_path, body: str) -> Path:
    path = tmp_path / "jinja_test.py"
    path.write_text("import pytest\n\nSUBPATH = 'a/b'\n\n" + body, encoding="utf8")
    return path


GOOD_DECORATOR = (
    '@pytest.mark.parametrize(\n    "subpath,code_only,include_meta",\n    [ROWS],\n)\n'
)
FUNC = "def test__templater_full(subpath, code_only, include_meta):\n    pass\n"


def test_read_table_of_a_small_file(tmp_path):
    rows = '("a/b", True, False), ("c", False, True)'
    path = _table_file(tmp_path, GOOD_DECORATOR.replace("ROWS", rows) + FUNC)
    assert templater.read_table(path) == [("a/b", True, False), ("c", False, True)]


@pytest.mark.parametrize(
    "body, message",
    [
        (
            GOOD_DECORATOR.replace("ROWS", "(SUBPATH, True, False)") + FUNC,
            "entry is not a literal: (SUBPATH, True, False)",
        ),
        (
            GOOD_DECORATOR.replace("ROWS", '("a" + "b", True, False)') + FUNC,
            "entry is not a literal",
        ),
        (
            GOOD_DECORATOR.replace("ROWS", '("a", 1, False)') + FUNC,
            "entry is not (str, bool, bool)",
        ),
        (
            GOOD_DECORATOR.replace("ROWS", '("a", True)') + FUNC,
            "entry is not (str, bool, bool)",
        ),
        (
            GOOD_DECORATOR.replace("[ROWS]", "ROWS_LIST") + FUNC,
            "the values are not a list",
        ),
        (
            GOOD_DECORATOR.replace("ROWS", '("a", True, False)').replace(
                "],\n", "], ids=['x'],\n"
            )
            + FUNC,
            "parametrize has other arguments",
        ),
        (
            GOOD_DECORATOR.replace("ROWS", '("a", True, False)').replace(
                "subpath,code_only", "subpath, code_only"
            )
            + FUNC,
            "argnames are not",
        ),
        (
            "@pytest.mark.skip\n"
            + GOOD_DECORATOR.replace("ROWS", '("a", True, False)')
            + FUNC,
            "must have only one parametrize",
        ),
        (FUNC, "must have only one parametrize"),
        ("", "0 functions named test__templater_full"),
        (
            GOOD_DECORATOR.replace("ROWS", '("a", True, False)') + FUNC + FUNC,
            "2 functions named test__templater_full",
        ),
    ],
)
def test_read_table_fails_loudly(tmp_path, body, message):
    with pytest.raises(templater.TableError, match=re.escape(message)):
        templater.read_table(_table_file(tmp_path, body))


def test_two_rows_with_one_id_fail(tmp_path):
    path = tmp_path / templater.TEST_FILE
    path.parent.mkdir(parents=True)
    rows = '("a", True, False), ("a", False, True)'
    path.write_text(
        "import pytest\n\n" + GOOD_DECORATOR.replace("ROWS", rows) + FUNC,
        encoding="utf8",
    )
    with pytest.raises(templater.TableError, match="two rows give one case id"):
        templater.discover(tmp_path)


def _logic_digest() -> str:
    """Hash the sqlfluff code that suites/templater.py and compare.py port."""

    def functions(path: Path, names: set[str]) -> list[str]:
        out = []
        for node in ast.parse(path.read_text(encoding="utf8")).body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                node.decorator_list = []
                out.append(ast.dump(node))
        assert len(out) == len(names)
        return out

    parts = functions(
        REAL_TEST, {"get_parsed", "assert_structure", "test__templater_full"}
    )
    parts += functions(
        SQLFLUFF_ROOT / "test" / "conftest.py", {"load_yaml", "process_struct"}
    )
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def test_sqlfluff_test_logic_is_the_ported_logic():
    # If this fails, the sqlfluff test changed. Compare it with
    # suites/templater.py and harness/templater.md, then update the digest.
    assert _logic_digest() == (
        "83b357ada3cffc66c21715e6fd89ad621e43d56f99bff23bd4177db561066b42"
    )


# Python runtime


def test_needs_python_cases():
    tagged = sorted(c.id for c in CASES.values() if c.tags)
    assert tagged == [
        "templater/jinja_j_libraries/jinja",
        "templater/jinja_m_libraries_module/jinja",
        "templater/jinja_s_filters_in_library/jinja",
    ]
    for case_id in tagged:
        assert CASES[case_id].tags == (templater.NEEDS_PYTHON,)


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")


SQL = Path("test/fixtures/templater/d/sub/x.sql")


@pytest.mark.parametrize(
    "files, want",
    [
        ({}, []),
        ({"test/fixtures/templater/d/.sqlfluff": "[sqlfluff]\ndialect=ansi\n"}, []),
        (
            {"test/fixtures/templater/d/.sqlfluff": "[sqlfluff]\nlibrary_path=libs\n"},
            ["library_path"],
        ),
        (
            {
                "test/.sqlfluff": "[sqlfluff:templater:jinja]\nlibrary_path = libs\n",
            },
            ["library_path"],
        ),
        (
            {
                "test/.sqlfluff": "[sqlfluff:templater:jinja]\nlibrary_path=libs\n",
                "test/fixtures/templater/d/sub/.sqlfluff": (
                    "[sqlfluff:templater:jinja]\nlibrary_path=none\n"
                ),
            },
            [],
        ),
        (
            {
                "test/fixtures/templater/d/.sqlfluff": (
                    "[sqlfluff:templater:jinja:context]\nlibrary_path=foo\n"
                ),
            },
            [],
        ),
        (
            {"test/fixtures/templater/d/.sqlfluff": "[sqlfluff]\ntemplater=python\n"},
            ["templater python"],
        ),
        (
            {
                "tox.ini": "[sqlfluff]\ntemplater = dbt\n",
                "pyproject.toml": "[tool.sqlfluff.templater.jinja]\nlibrary_path='x'\n",
            },
            ["library_path", "templater dbt"],
        ),
        (
            {
                ".sqlfluff": "[sqlfluff]\ntemplater = python\n",
                "test/fixtures/templater/d/pyproject.toml": (
                    "[tool.sqlfluff.core]\ntemplater = 'jinja'\n"
                ),
            },
            [],
        ),
        (
            {"test/fixtures/templater/d/sub/setup.cfg": "[other]\ntemplater=python\n"},
            [],
        ),
        (
            {str(SQL): "-- sqlfluff:templater:python\nSELECT 1\n"},
            ["templater python"],
        ),
        (
            {str(SQL): "--sqlfluff:templater:jinja:library_path:libs\nSELECT 1\n"},
            ["library_path"],
        ),
        (
            {
                "test/.sqlfluff": "[sqlfluff]\ntemplater=python\n",
                str(SQL): "SELECT 1 -- sqlfluff:templater:jinja\n",
            },
            ["templater python"],
        ),
        (
            {
                "test/.sqlfluff": "[sqlfluff]\ntemplater=python\n",
                str(SQL): "  -- sqlfluff:templater:jinja\nSELECT 1\n",
            },
            ["templater python"],
        ),
        (
            {
                "test/.sqlfluff": "[sqlfluff]\ntemplater=python\n",
                str(SQL): "-- sqlfluff:templater:jinja\nSELECT 1\n",
            },
            [],
        ),
    ],
)
def test_python_needs(tmp_path, files, want):
    for rel, text in files.items():
        _write(tmp_path, rel, text)
    assert templater.python_needs(tmp_path, SQL) == want


def test_python_needs_reads_parent_folders_and_home(tmp_path):
    root, home = tmp_path / "a" / "root", tmp_path / "home"
    root.mkdir(parents=True)
    home.mkdir()
    _write(tmp_path, "a/.sqlfluff", "[sqlfluff]\nlibrary_path=libs\n")
    assert templater.python_needs(root, SQL, home) == ["library_path"]
    _write(home, ".sqlfluff", "[sqlfluff]\ntemplater=python\n")
    assert templater.python_needs(root, SQL, home) == [
        "library_path",
        "templater python",
    ]


# The templater of the CLI. sqlfluff reads the config of the user (appdir and
# home), then the folders after the common path of home and the current
# folder, to the current folder.


@pytest.mark.parametrize(
    "root, home, want",
    [
        ("h/a/b", "h", ["h/.config/sqlfluff", "h", "h/a", "h/a/b"]),
        ("x/a", "h", ["h/.config/sqlfluff", "h", "x", "x/a"]),
        ("h", "h", ["h/.config/sqlfluff", "h", "h"]),
        ("x", "x/h", ["x/h/.config/sqlfluff", "x/h", "x"]),
    ],
)
def test_root_config_folders(tmp_path, root, home, want):
    (tmp_path / home / ".config" / "sqlfluff").mkdir(parents=True)
    folders = templater.root_config_folders(tmp_path / root, tmp_path / home)
    assert folders == [tmp_path.resolve() / f for f in want]


def test_root_config_folders_xdg_appdir(tmp_path):
    folders = templater.root_config_folders(tmp_path, tmp_path)
    assert folders[0] == tmp_path.resolve() / "sqlfluff"


@pytest.mark.parametrize(
    "files, want",
    [
        ({}, "jinja"),
        ({"r/.sqlfluff": "[sqlfluff]\ndialect = ansi\n"}, "jinja"),
        ({"r/.sqlfluff": "[sqlfluff]\ntemplater = placeholder\n"}, "placeholder"),
        ({"r/pyproject.toml": "[tool.sqlfluff.core]\ntemplater = 'raw'\n"}, "raw"),
        # sqlfluff does not read the common path of home and the current folder.
        ({".sqlfluff": "[sqlfluff]\ntemplater = python\n"}, "jinja"),
        ({"h/.sqlfluff": "[sqlfluff]\ntemplater = raw\n"}, "raw"),
        ({"h/.config/sqlfluff/.sqlfluff": "[sqlfluff]\ntemplater = raw\n"}, "raw"),
        (
            {
                "h/.sqlfluff": "[sqlfluff]\ntemplater = python\n",
                "r/tox.ini": "[sqlfluff]\ntemplater = jinja\n",
            },
            "jinja",
        ),
        ({"r/sub/.sqlfluff": "[sqlfluff]\ntemplater = raw\n"}, "jinja"),
    ],
)
def test_cli_templater(tmp_path, files, want):
    (tmp_path / "r").mkdir()
    (tmp_path / "h").mkdir()
    for rel, text in files.items():
        _write(tmp_path, rel, text)
    assert templater.cli_templater(tmp_path / "r", tmp_path / "h") == want


def test_run_one_keeps_the_tags_of_the_case():
    class Boom:
        NAME = "templater"

        @staticmethod
        def run(adapter, case, root):
            raise RuntimeError("boom")

    case = templater.TemplaterCase("templater/a", "a", True, False, ("needs_python",))
    result = cli._run_one(Boom, FakeAdapter([]), case, SQLFLUFF_ROOT)
    assert result.status == ERROR
    assert result.tags == ["needs_python"]


# run() with a fake adapter


class FakeAdapter:
    name = "fake"

    def __init__(self, results: list[ParseResult]) -> None:
        self.results = list(results)
        self.calls: list[tuple] = []

    def parse_file(self, sql_path, dialect, cwd, code_only=False, include_meta=False):
        self.calls.append((sql_path, dialect, cwd, code_only, include_meta))
        return self.results.pop(0)


def _tree(tree, rc=0, errors=None):
    from sqll_harness.compare import has_node

    return ParseResult(tree, has_node(tree, "unparsable"), errors or [], rc)


SELECT = {"file": {"statement": {"keyword": "SELECT"}}}
SELECT_YML = "file:\n  statement:\n    keyword: SELECT\n"


def _case(tmp_path, yml=SELECT_YML, code_only=True, include_meta=False, sql=True):
    if sql:
        _write(tmp_path, "test/fixtures/templater/d/x.sql", "SELECT\n")
    if yml is not None:
        _write(tmp_path, "test/fixtures/templater/d/x.yml", yml)
    return templater.TemplaterCase("templater/d/x", "d/x", code_only, include_meta)


def test_run_code_only_parses_2_times(tmp_path):
    case = _case(tmp_path)
    adapter = FakeAdapter([_tree(SELECT), _tree(SELECT)])
    result = templater.run(adapter, case, tmp_path)
    assert result.status == PASS, result.reason
    assert result.checks == {"exact": True, "no_unparsable": True}
    assert adapter.calls == [
        (case.sql, None, tmp_path, True, False),
        (case.sql, None, tmp_path, False, False),
    ]


def test_run_full_tree_parses_1_time(tmp_path):
    case = _case(tmp_path, code_only=False, include_meta=True)
    adapter = FakeAdapter([_tree(SELECT)])
    assert templater.run(adapter, case, tmp_path).status == PASS
    assert adapter.calls == [(case.sql, None, tmp_path, False, True)]


def test_run_unparsable_hidden_by_code_only_fails(tmp_path):
    case = _case(tmp_path)
    full = {"file": [{"statement": {"keyword": "SELECT"}}, {"unparsable": " "}]}
    result = templater.run(FakeAdapter([_tree(SELECT), _tree(full)]), case, tmp_path)
    assert result.status == FAIL
    assert result.checks == {"exact": True, "no_unparsable": False}
    assert result.reason == "unparsable segment"


def test_run_templating_violation_is_not_a_failure(tmp_path):
    # The test does not check the violations. Exit code 1 is a TMP, LXR, or
    # PRS violation; only an unparsable segment fails.
    case = _case(tmp_path)
    adapter = FakeAdapter([_tree(SELECT, rc=1), _tree(SELECT, rc=1)])
    assert templater.run(adapter, case, tmp_path).status == PASS


def test_run_tree_differs(tmp_path):
    case = _case(tmp_path, yml="file:\n  statement:\n    keyword: select\n")
    result = templater.run(FakeAdapter([_tree(SELECT)] * 2), case, tmp_path)
    assert result.status == FAIL
    assert result.checks == {"exact": False, "no_unparsable": True}
    assert result.reason == "tree differs"


def test_run_with_no_tree_fails(tmp_path):
    for yml in (SELECT_YML, ""):
        case = _case(tmp_path, yml=yml)
        result = templater.run(FakeAdapter([_tree(None)] * 2), case, tmp_path)
        assert result.status == FAIL
        assert result.checks == {"exact": False, "no_unparsable": False}


@pytest.mark.parametrize(
    "rel, text, status",
    [
        ("root/.sqlfluff", "[sqlfluff]\ntemplater = placeholder\n", ERROR),
        (".sqlfluff", "[sqlfluff]\ntemplater = raw\n", ERROR),
        ("root/setup.cfg", "[sqlfluff]\ntemplater = jinja\n", PASS),
        ("root/test/.sqlfluff", "[sqlfluff]\ntemplater = placeholder\n", PASS),
        ("root/.sqlfluff", "[sqlfluff\n", ERROR),
    ],
)
def test_run_root_templater(tmp_path, rel, text, status):
    # The test always uses jinja. A templater in a config file of a sub
    # folder only gives a warning, in the test and in the CLI.
    root = tmp_path / "root"
    case = _case(root)
    _write(tmp_path, rel, text)
    adapter = FakeAdapter([_tree(SELECT)] * 2)
    result = templater.run(adapter, case, root)
    assert result.status == status, result.reason
    assert bool(adapter.calls) == (status == PASS)


def test_run_with_one_tree_is_an_error(tmp_path):
    case = _case(tmp_path)
    result = templater.run(FakeAdapter([_tree(SELECT), _tree(None)]), case, tmp_path)
    assert result.status == ERROR


def test_run_tool_errors_give_error(tmp_path):
    case = _case(tmp_path)
    bad = _tree(None, rc=2, errors=["exit code 2"])
    result = templater.run(FakeAdapter([_tree(SELECT), bad]), case, tmp_path)
    assert result.status == ERROR
    assert result.reason == "parse with no -c: exit code 2"


@pytest.mark.parametrize(
    "yml, sql",
    [
        (None, True),
        ("file: [a]\n", True),
        ("file: {a: 1, b\n", True),
        ("abc\n", True),
        ("- {}\n", True),
        ("file: [{}]\n", True),
        (None, False),
    ],
)
def test_run_missing_or_bad_files_fail(tmp_path, yml, sql):
    case = _case(tmp_path, yml=yml, sql=sql)
    adapter = FakeAdapter([_tree(SELECT)] * 2)
    result = templater.run(adapter, case, tmp_path)
    assert result.status == FAIL
    assert result.reason.startswith("the test fails")
    assert bool(adapter.calls) == sql


# The empty-tree rule. The test compares to_tuple with the YAML tree with ==.
# to_tuple gives an empty tuple for a segment with no children to show; the
# CLI gives null. A YAML null is not equal to it.


@pytest.mark.parametrize(
    "yml, status",
    [
        ("file: []\n", PASS),
        ("file:\n", FAIL),
        ("file: null\n", FAIL),
        ("", FAIL),
        ("file: ''\n", FAIL),
    ],
)
def test_run_empty_tree(tmp_path, yml, status):
    case = _case(tmp_path, yml=yml)
    empty = {"file": None}
    result = templater.run(FakeAdapter([_tree(empty)] * 2), case, tmp_path)
    assert result.status == status


def test_run_empty_child(tmp_path):
    tree = {"file": {"statement": None}}
    for yml, status in (("file:\n  statement: []\n", PASS), (SELECT_YML, FAIL)):
        case = _case(tmp_path, yml=yml)
        result = templater.run(FakeAdapter([_tree(tree)] * 2), case, tmp_path)
        assert result.status == status
    case = _case(tmp_path, yml="file:\n  statement:\n")
    result = templater.run(FakeAdapter([_tree(tree)] * 2), case, tmp_path)
    assert result.status == FAIL


# Position keys (include_meta)

POS = {
    "start_line_no": 1,
    "start_line_pos": 1,
    "start_file_pos": 0,
    "end_line_no": 1,
    "end_line_pos": 7,
    "end_file_pos": 6,
}
META_TREE = {
    **POS,
    "file": [
        {**POS, "indent": ""},
        {**POS, "statement": {**POS, "keyword": "SELECT"}},
    ],
}
META_YML = "file:\n- indent: ''\n- statement:\n    keyword: SELECT\n"


def test_run_include_meta_removes_positions(tmp_path):
    case = _case(tmp_path, yml=META_YML, code_only=False, include_meta=True)
    result = templater.run(FakeAdapter([_tree(META_TREE)]), case, tmp_path)
    assert result.status == PASS, result.reason


def test_run_without_include_meta_keeps_positions(tmp_path):
    # Only "parse -m" adds positions. Without it, a position key is a
    # segment and the tree is different.
    case = _case(tmp_path, yml=META_YML, code_only=False)
    result = templater.run(FakeAdapter([_tree(META_TREE)]), case, tmp_path)
    assert result.status == ERROR


def test_run_position_key_with_other_value_is_an_error(tmp_path):
    case = _case(tmp_path, yml=META_YML, code_only=False, include_meta=True)
    tree = {"file": [{"start_line_no": "x", "indent": ""}]}
    result = templater.run(FakeAdapter([_tree(tree)]), case, tmp_path)
    assert result.status == ERROR
    assert "position key 'start_line_no'" in result.reason


def test_run_yml_with_positions_fails(tmp_path):
    yml = "start_line_no: 1\nfile:\n- indent: ''\n- statement:\n    keyword: SELECT\n"
    case = _case(tmp_path, yml=yml, code_only=False, include_meta=True)
    result = templater.run(FakeAdapter([_tree(META_TREE)]), case, tmp_path)
    assert result.status == FAIL


# The adapter command


def test_parse_file_command(monkeypatch, tmp_path):
    adapter = SqlfluffAdapter(venv=tmp_path)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "sqlfluff").write_text("")
    calls = []

    class Proc:
        stdout = '[{"filepath": "x.sql", "segments": {"file": null}}]'
        stderr = ""
        returncode = 0

    def fake_run(cmd, cwd):
        calls.append((cmd, cwd))
        return Proc()

    monkeypatch.setattr(adapter, "_run", fake_run)
    sql = Path("test/fixtures/templater/d/x.sql")
    adapter.parse_file(sql, None, tmp_path, code_only=True, include_meta=True)
    adapter.parse_file(sql, "ansi", tmp_path)
    binary = str(tmp_path / "bin" / "sqlfluff")
    assert calls == [
        ([binary, "parse", "-f", "json", "-c", "-m", str(sql)], tmp_path),
        ([binary, "parse", "-f", "json", "--dialect", "ansi", str(sql)], tmp_path),
    ]


def test_tool_env_writes_no_bytecode(tmp_path):
    assert isolated_env(tmp_path)["PYTHONDONTWRITEBYTECODE"] == "1"


# The real tool

adapter = SqlfluffAdapter()

# The harness result of each harness fixture. The key prefix is the result
# of the sqlfluff test (scripts/sqlfluff-templater-oracle --check-prefixes).
HARNESS_STATUS = {
    "templater/cases/expect_pass_basic": PASS,
    "templater/cases/expect_pass_empty_code_only": PASS,
    "templater/cases/expect_fail_empty_null": FAIL,
    "templater/cases/expect_pass_meta": PASS,
    "templater/cases/expect_fail_meta_missing": FAIL,
    "templater/cases/expect_fail_meta_positions": FAIL,
    "templater/cases/expect_pass_tmp_violation": PASS,
    "templater/cases/expect_fail_unparsable": FAIL,
    "templater/cases/expect_fail_no_yml": FAIL,
}


def test_harness_fixture_list():
    assert list(HARNESS_CASES) == list(HARNESS_STATUS)
    for case_id, status in HARNESS_STATUS.items():
        key = case_id.rsplit("/", 1)[-1]
        assert key.startswith(("expect_pass_", "expect_fail_"))
        assert status == (PASS if key.startswith("expect_pass_") else FAIL)


@needs_sqlfluff
@pytest.mark.parametrize("case_id", list(HARNESS_STATUS))
def test_harness_fixtures(case_id):
    result = templater.run(adapter, HARNESS_CASES[case_id], FIXTURES)
    assert result.status == HARNESS_STATUS[case_id], result.reason


@needs_sqlfluff
def test_real_meta_case():
    result = templater.run(adapter, CASES["templater/jinja_l_metas/001"], SQLFLUFF_ROOT)
    assert result.status == PASS, result.reason
    assert result.checks == {"exact": True, "no_unparsable": True}


@needs_sqlfluff
def test_mutated_real_meta_case_fails(tmp_path):
    src = SQLFLUFF_ROOT / "test" / "fixtures"
    folder = tmp_path / "test" / "fixtures" / "templater" / "jinja_l_metas"
    shutil.copytree(src / "templater" / "jinja_l_metas", folder)
    shutil.copy(src / ".sqlfluff", tmp_path / "test" / "fixtures" / ".sqlfluff")
    case = CASES["templater/jinja_l_metas/001"]
    assert templater.run(adapter, case, tmp_path).status == PASS
    yml = folder / "001.yml"
    text = yml.read_text(encoding="utf8")
    first = "  - placeholder: '{% set some_condition %}'\n"
    assert text.count(first + "  - indent: ''\n") == 1
    yml.write_text(text.replace(first + "  - indent: ''\n", first), encoding="utf8")
    result = templater.run(adapter, case, tmp_path)
    assert result.status == FAIL
    assert result.reason == "tree differs"


@needs_sqlfluff
def test_real_case_with_a_templating_violation():
    # sqlfluff gives 3 TMP violations and exit code 1. The test passes.
    case = CASES["templater/jinja_t_loader_search_path/jinja"]
    result = templater.run(adapter, case, SQLFLUFF_ROOT)
    assert result.status == PASS, result.reason


@needs_sqlfluff
def test_real_root_templater_is_an_error(tmp_path):
    # The tool uses the placeholder templater and the tree agrees. The test
    # uses jinja and fails.
    _write(
        tmp_path,
        ".sqlfluff",
        "[sqlfluff]\ndialect = ansi\ntemplater = placeholder\n"
        "[sqlfluff:templater:placeholder]\n"
        "param_regex = (?P<param_name>xyz)\nxyz = 1\n",
    )
    case = _case(tmp_path)
    (tmp_path / case.sql).write_text("SELECT xyz AS a\n", encoding="utf8")
    parsed = adapter.parse_file(case.sql, None, tmp_path)
    assert not parsed.errors
    assert parsed.tree is not None
    result = templater.run(adapter, case, tmp_path)
    assert result.status == ERROR
    assert "'placeholder' templater" in result.reason
