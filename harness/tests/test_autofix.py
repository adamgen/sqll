import dataclasses
import json
import shutil
import tempfile
from pathlib import Path

import pytest
from conftest import needs_sqlfluff

from sqll_harness.adapters.base import EmptyHome, FileFixResult, ParseResult
from sqll_harness.adapters.sqlfluff import (
    SqlfluffAdapter,
    _parse_file_output,
    fix_output_violations,
)
from sqll_harness.cases import ERROR, FAIL, PASS
from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT
from sqll_harness.suites import autofix

FIXTURES = Path(__file__).parent / "fixtures" / "autofix"
CASES = {c.id: c for c in autofix.discover(SQLFLUFF_ROOT)}
HARNESS_CASES = {c.id: c for c in autofix.discover_dir(FIXTURES)}


def _v(code, line, pos, warning=False):
    return {
        "code": code,
        "start_line_no": line,
        "start_line_pos": pos,
        "warning": warning,
    }


def _case(tmp_path, files, dialect="ansi", name="c"):
    folder = tmp_path / "cases" / dialect / name
    folder.mkdir(parents=True)
    defaults = {
        "test-config.yml": "test-config:\n  rules:\n    - LT01\n",
        "before.sql": "SELECT a  +  b\n",
        "after.sql": "SELECT a + b\n",
    }
    for name_, text in {**defaults, **files}.items():
        if text is not None:
            (folder / name_).write_bytes(text.encode("utf8"))
    return autofix.AutofixCase(f"autofix/{dialect}/{name}", dialect, folder)


# Discovery


def test_discovery_count():
    cases = autofix.discover(SQLFLUFF_ROOT)
    assert len(cases) == 61
    assert len(CASES) == len(cases)


def test_case_fields():
    case = CASES["autofix/ansi/001_long_line"]
    assert case.dialect == "ansi"
    assert case.folder == (
        SQLFLUFF_ROOT / "test/fixtures/linter/autofix/ansi/001_long_line"
    )
    dialects = {c.dialect for c in CASES.values()}
    assert dialects == {
        "ansi",
        "bigquery",
        "clickhouse",
        "oracle",
        "snowflake",
        "sparksql",
        "sqlite",
        "tsql",
    }


def test_discovery_is_as_in_the_test(tmp_path):
    # Each entry of a dialect folder is a case, also a file. Only the
    # top-level entries that end with ".md" are not dialects.
    (tmp_path / "README.md").write_text("x")
    (tmp_path / "ansi" / "b").mkdir(parents=True)
    (tmp_path / "ansi" / "a.md").write_text("x")
    (tmp_path / "tsql" / "z").mkdir(parents=True)
    ids = [c.id for c in autofix.discover_dir(tmp_path)]
    assert ids == ["autofix/ansi/a.md", "autofix/ansi/b", "autofix/tsql/z"]


# test-config.yml


@pytest.mark.parametrize(
    "rules, want",
    [
        ("[LT02, LT05]", "LT02,LT05"),
        ("[lt02, cp01]", "LT02,CP01"),
        ("[ALL]", None),
        ("[lt01, all]", None),
        ("['layout.call_spacing']", None),
        ("[]", None),
    ],
)
def test_load_test_config_rules(tmp_path, rules, want):
    path = tmp_path / "test-config.yml"
    path.write_text(f"test-config:\n  dialect: tsql\n  rules: {rules}\n")
    config = autofix.load_test_config(path)
    assert config.rules == want
    assert config.raise_on_non_linting_violations is True


def test_load_test_config_raise_flag(tmp_path):
    path = tmp_path / "test-config.yml"
    path.write_text(
        "test-config:\n  rules: [LT01]\n  raise_on_non_linting_violations: false\n"
    )
    assert autofix.load_test_config(path).raise_on_non_linting_violations is False


def test_load_test_config_with_no_rules_fails(tmp_path):
    path = tmp_path / "test-config.yml"
    path.write_text("test-config:\n  dialect: ansi\n")
    with pytest.raises(TypeError):
        autofix.load_test_config(path)


def test_all_real_test_configs():
    configs = {
        i: autofix.load_test_config(c.folder / "test-config.yml")
        for i, c in CASES.items()
    }
    assert configs["autofix/ansi/023_LT05_confuses_LT10"].rules == "LT02,LT05,LT10"
    no_rules = sorted(i for i, c in configs.items() if c.rules is None)
    assert no_rules == [
        "autofix/ansi/032_LT07_cte_bracket_not_idempotent",
        "autofix/ansi/033_LT07_cte_bracket_multi_cte_idempotent",
        "autofix/ansi/034_LT07_cte_bracket_multiline_unchanged",
    ]
    assert all(c.raise_on_non_linting_violations is True for c in configs.values())


# violations.json


def test_expected_violations():
    path = CASES["autofix/ansi/001_long_line"].folder / "violations.json"
    data = json.loads(path.read_text())
    assert autofix.expected_violations(data) == {("LT05", 3, 9)}
    data = {"violations": {"linting": {"LT01": [[1, 2], [3, 4]], "CP01": []}}}
    assert autofix.expected_violations(data) == {("LT01", 1, 2), ("LT01", 3, 4)}


def test_check_tuples_has_only_lint_errors():
    found = [_v("LT01", 1, 2), _v("PRS", 3, 1), _v("TMP", 1, 1), _v("CP01", 4, 5)]
    assert autofix.check_tuples(found) == {("LT01", 1, 2), ("CP01", 4, 5)}


def test_only_one_real_case_has_violations_json():
    with_json = sorted(
        i for i, c in CASES.items() if (c.folder / "violations.json").exists()
    )
    assert with_json == ["autofix/ansi/001_long_line"]


# The output of "sqlfluff fix --show-lint-violations --nocolor"

PATH = "/tmp/x/testing.sql"


def _fix_output(first: list[str], linted=True):
    last = [f"== [{PATH}] PASS"] if linted else []
    return "\n".join(
        ["==== finding fixable violations ===="]
        + first
        + ["==== lint for unfixable violations ===="]
        + last
    )


def test_fix_output_violations():
    out = _fix_output(
        [
            f"== [{PATH}] FAIL",
            "L:   3 | P:   9 | LT05 | Line is too long (198 > 80).",
            "                       | [layout.long_lines]",
            "L:  12 | P:  10 |  PRS | Couldn't find closing bracket.",
            "L:  13 | P:   1 | CP01 | WARNING: Keywords must be upper case.",
            "L:   - | P:   - |  TMP | Undefined jinja template variable.",
            f"== [{PATH}] FIXED",
            "WARNING    Loop limit on fixes reached [10].",
            "1 fixable linting violations found",
        ]
    )
    violations, linted = fix_output_violations(out, PATH)
    assert linted is True
    assert violations == [
        _v("LT05", 3, 9),
        _v("PRS", 12, 10),
        _v("CP01", 13, 1, warning=True),
        _v("TMP", None, None),
    ]


def test_fix_output_with_no_violations():
    out = _fix_output(
        ["==== no fixable linting violations found ====", "All Finished!"]
    )
    assert fix_output_violations(out, PATH) == ([], True)
    assert fix_output_violations(_fix_output([], linted=False), PATH) == ([], False)
    # A line of another file is not a line of this file.
    other = _fix_output([], linted=False) + "\n== [/tmp/x/testing.sql.bak] PASS"
    assert fix_output_violations(other, PATH) == ([], False)


def test_fix_output_only_warnings_is_pass():
    out = _fix_output(
        [f"== [{PATH}] PASS", "L:   1 | P:   9 | LT01 | WARNING: Unexpected space."]
    )
    assert fix_output_violations(out, PATH) == ([_v("LT01", 1, 9, True)], True)


@pytest.mark.parametrize(
    "first, linted, message",
    [
        ([f"== [{PATH}] PASS", "L:   1 | P:   9 | LT01 | x"], True, "says PASS"),
        ([f"== [{PATH}] FAIL", "L:   1 | P:   9 | LT01 | WARNING: x"], True, "FAIL"),
        (["L:   1 | P:   9 | LT01 | x"], True, "no file line"),
        (
            [f"== [{PATH}] FAIL", "L:   1 | P:   9 | LT01 | x"] * 2,
            True,
            "2 times",
        ),
        ([f"== [{PATH}] FAIL", "L:   1 | P:   9 | LT01 | x"], False, "not linted"),
    ],
)
def test_fix_output_that_is_not_consistent_is_an_error(first, linted, message):
    with pytest.raises(ValueError, match=message):
        fix_output_violations(_fix_output(first, linted), PATH)


def test_fix_output_with_no_sections_is_an_error():
    with pytest.raises(ValueError, match="2 sections"):
        fix_output_violations("==== finding fixable violations ====\n", PATH)


def test_parse_file_output():
    out = json.dumps([{"filepath": PATH, "segments": None}])
    r = _parse_file_output(out, 1, "")
    assert r.tree is None
    assert r.errors == []
    out = json.dumps([{"filepath": PATH, "segments": {"file": {"x": "y"}}}])
    assert _parse_file_output(out, 0, "").tree == {"file": {"x": "y"}}
    assert _parse_file_output("", 0, "").errors == ["no JSON parse output for the file"]
    assert _parse_file_output("[]", 0, "").errors
    assert _parse_file_output(out, 2, "User Error: x").errors == [
        "exit code 2: User Error: x"
    ]


# run() with a fake adapter


class FakeAdapter:
    """Gives fixed results, writes `fixed` to the file, and records calls."""

    name = "fake"

    def __init__(self, fixed="SELECT a + b\n", violations=(), **kw):
        self.fixed = fixed
        self.violations = list(violations)
        self.tree = kw.pop("tree", {"file": {}})
        self.result = kw
        self.calls = []
        self.files = []
        self.paths = []

    def parse_file(self, sql_path, dialect, cwd):
        self.calls.append(("parse", sql_path.name, dialect, cwd))
        self.paths.append(sql_path)
        return ParseResult(tree=self.tree, has_unparsable=False)

    def fix_file(self, sql_path, rules, dialect, cwd, show_violations=False):
        self.calls.append(("fix", sql_path.name, rules, dialect, cwd, show_violations))
        self.paths.append(sql_path)
        self.files.append(
            {p.name: p.read_bytes() for p in sorted(sql_path.parent.iterdir())}
        )
        fixed = (
            self.fixed[show_violations] if isinstance(self.fixed, tuple) else self.fixed
        )
        sql_path.write_text(fixed)
        result = FileFixResult(**self.result)
        if show_violations:
            result.violations = self.violations
            result.linted = self.result.get("linted", True)
        return result


def test_run_calls_and_checks(tmp_path):
    case = _case(tmp_path, {".sqlfluff": "[sqlfluff]\nmax_line_length = 70\n"})
    adapter = FakeAdapter()
    result = autofix.run(adapter, case, SQLFLUFF_ROOT)
    assert result.status == PASS, result.reason
    assert result.checks == {"tree": True, "non_linting": True, "fix": True}
    assert adapter.calls == [
        ("parse", "testing.sql", "ansi", SQLFLUFF_ROOT),
        ("fix", "testing.sql", ["LT01"], "ansi", SQLFLUFF_ROOT, False),
        ("fix", "testing.sql", ["LT01"], "ansi", SQLFLUFF_ROOT, True),
    ]
    want = {
        ".sqlfluff": b"[sqlfluff]\nmax_line_length = 70\n",
        "testing.sql": b"SELECT a  +  b\n",
    }
    assert adapter.files == [want, want]


def test_run_uses_2_copies_as_autofix_md_says(tmp_path):
    # harness/autofix.md: parse and fix in <tmp>/fix/, and
    # fix --show-lint-violations in <tmp>/show/.
    adapter = FakeAdapter()
    autofix.run(adapter, _case(tmp_path, {}), SQLFLUFF_ROOT)
    parse, fix, show = adapter.paths
    assert parse == fix
    assert fix.parent.name == "fix"
    assert show.parent.name == "show"
    assert show.parent.parent == fix.parent.parent
    doc = (REPO_ROOT / "harness" / "autofix.md").read_text()
    assert "3 commands on 2 copies" in doc
    assert "each on a new copy" not in doc


def test_file_fix_result_docstring_describes_each_field():
    for f in dataclasses.fields(FileFixResult):
        assert f"{f.name}:" in FileFixResult.__doc__, f.name


def test_run_with_all_rules_gives_no_rules(tmp_path):
    case = _case(tmp_path, {"test-config.yml": "test-config:\n  rules: [CP01, all]\n"})
    adapter = FakeAdapter()
    assert autofix.run(adapter, case, SQLFLUFF_ROOT).status == PASS
    assert {c[2] for c in adapter.calls if c[0] == "fix"} == {None}


def test_run_writes_an_empty_config_and_new_lines_as_the_test(tmp_path):
    # The test opens .sqlfluff for writing also if the case has no config. It
    # copies the files in text mode, thus "\r\n" becomes "\n".
    case = _case(tmp_path, {"before.sql": "SELECT a\r\nFROM t\r"})
    adapter = FakeAdapter(fixed="SELECT a + b\r\n")
    result = autofix.run(adapter, case, SQLFLUFF_ROOT)
    assert adapter.files[0] == {".sqlfluff": b"", "testing.sql": b"SELECT a\nFROM t\n"}
    # The test reads the fixed file in text mode too.
    assert result.status == PASS, result.reason


def test_run_wrong_fix_fails(tmp_path):
    result = autofix.run(FakeAdapter(fixed="x\n"), _case(tmp_path, {}), SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.checks["fix"] is False
    assert result.reason == "fix mismatch"


def test_run_violations_check(tmp_path):
    data = {"violations": {"linting": {"LT01": [[1, 9], [1, 12]]}}}
    case = _case(tmp_path, {"violations.json": json.dumps(data)})
    found = [_v("LT01", 1, 9), _v("LT01", 1, 12)]
    result = autofix.run(FakeAdapter(violations=found), case, SQLFLUFF_ROOT)
    assert result.status == PASS, result.reason
    assert result.checks["violations"] is True
    # A warning is not in the list of the test.
    found = [_v("LT01", 1, 9), _v("LT01", 1, 12, warning=True)]
    result = autofix.run(FakeAdapter(violations=found), case, SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.reason == "violations: missing [('LT01', 1, 12)], extra []"
    # The test compares sets: the order and duplicates do not count.
    found = [_v("LT01", 1, 12), _v("LT01", 1, 9), _v("LT01", 1, 9)]
    result = autofix.run(FakeAdapter(violations=found), case, SQLFLUFF_ROOT)
    assert result.status == PASS


def test_run_empty_violations_json_is_no_check(tmp_path):
    case = _case(tmp_path, {"violations.json": "{}"})
    result = autofix.run(
        FakeAdapter(violations=[_v("LT01", 1, 9)]), case, SQLFLUFF_ROOT
    )
    assert result.status == PASS
    assert "violations" not in result.checks


def test_run_bad_violations_json_fails(tmp_path):
    case = _case(tmp_path, {"violations.json": '{"violations": {}}'})
    result = autofix.run(FakeAdapter(), case, SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.checks["violations"] is False
    case = _case(tmp_path, {"violations.json": "{"}, name="d")
    adapter = FakeAdapter()
    result = autofix.run(adapter, case, SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.reason.startswith("the test fails: JSONDecodeError")
    assert adapter.calls == []


@pytest.mark.parametrize("missing", ["test-config.yml", "before.sql", "after.sql"])
def test_run_with_a_missing_file_fails(tmp_path, missing):
    adapter = FakeAdapter()
    result = autofix.run(adapter, _case(tmp_path, {missing: None}), SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.reason.startswith("the test fails: FileNotFoundError")
    assert adapter.calls == []


def test_run_non_linting_violation_fails(tmp_path):
    found = [_v("PRS", 2, 1), _v("TMP", 1, 1, warning=True)]
    result = autofix.run(
        FakeAdapter(violations=found), _case(tmp_path, {}), SQLFLUFF_ROOT
    )
    assert result.status == FAIL
    assert result.checks["non_linting"] is False
    assert result.reason == "non_linting: PRS at line 2, position 1"
    # A warning does not make the test fail.
    found = [_v("TMP", 1, 1, warning=True)]
    result = autofix.run(
        FakeAdapter(violations=found), _case(tmp_path, {}, name="d"), SQLFLUFF_ROOT
    )
    assert result.status == PASS


def test_run_raise_off_has_no_non_linting_check(tmp_path):
    config = "test-config:\n  rules: [LT01]\n  raise_on_non_linting_violations: false\n"
    case = _case(tmp_path, {"test-config.yml": config})
    result = autofix.run(FakeAdapter(violations=[_v("PRS", 2, 1)]), case, SQLFLUFF_ROOT)
    assert result.status == PASS
    assert "non_linting" not in result.checks


def test_run_unparsable_gate_gives_error(tmp_path):
    adapter = FakeAdapter(fixed="SELECT a  +  b\n", unparsable_gate=True)
    result = autofix.run(adapter, _case(tmp_path, {}), SQLFLUFF_ROOT)
    assert result.status == ERROR
    assert result.reason == autofix.GATE_REASON
    assert "fix" not in result.checks
    # If the test fails before the fix, the result is known.
    adapter = FakeAdapter(violations=[_v("PRS", 2, 1)], unparsable_gate=True)
    result = autofix.run(adapter, _case(tmp_path, {}, name="d"), SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.reason == "non_linting: PRS at line 2, position 1"


class ShowGateAdapter(FakeAdapter):
    """Finds the gate only in the run that shows the violations."""

    def fix_file(self, sql_path, rules, dialect, cwd, show_violations=False):
        result = super().fix_file(sql_path, rules, dialect, cwd, show_violations)
        result.unparsable_gate = show_violations
        return result


def test_run_gate_of_one_fix_run_gives_error(tmp_path):
    # The tool does not change the file. The test applies the fixes.
    adapter = ShowGateAdapter(fixed="SELECT a  +  b\n")
    config = "test-config:\n  rules: [LT01]\n  raise_on_non_linting_violations: false\n"
    case = _case(tmp_path, {"test-config.yml": config, "after.sql": "SELECT a  +  b\n"})
    result = autofix.run(adapter, case, SQLFLUFF_ROOT)
    assert result.status == ERROR
    assert result.reason == autofix.GATE_REASON


def test_run_with_no_tree_fails(tmp_path):
    result = autofix.run(FakeAdapter(tree=None), _case(tmp_path, {}), SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.checks == {"tree": False}
    assert result.reason == autofix.NO_TREE_REASON


def test_run_not_linted_fails(tmp_path):
    result = autofix.run(FakeAdapter(linted=False), _case(tmp_path, {}), SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.reason == autofix.NOT_LINTED_REASON


def test_run_critical_log_gives_error(tmp_path):
    adapter = FakeAdapter(critical=["Rule LT01 returned conflicting fixes"])
    result = autofix.run(adapter, _case(tmp_path, {}), SQLFLUFF_ROOT)
    assert result.status == ERROR
    assert result.reason == (
        "fix: the tool logged CRITICAL 'Rule LT01 returned conflicting fixes'; "
        "the test can fail there"
    )


def test_run_tool_errors_give_error(tmp_path):
    result = autofix.run(
        FakeAdapter(errors=["exit code 2"]), _case(tmp_path, {}), SQLFLUFF_ROOT
    )
    assert result.status == ERROR
    assert result.reason == "fix: exit code 2; fix: exit code 2"


def test_run_different_fix_runs_give_error(tmp_path):
    adapter = FakeAdapter(fixed=("SELECT a + b\n", "SELECT a +  b\n"))
    result = autofix.run(adapter, _case(tmp_path, {}), SQLFLUFF_ROOT)
    assert result.status == ERROR
    assert result.reason == "fix: the 2 fix runs gave different files"


# The real tool

adapter = SqlfluffAdapter()

# The harness result of each harness fixture. The key prefix is the result
# of the sqlfluff test (scripts/sqlfluff-autofix-oracle --check-prefixes).
# "error": the harness cannot know the result of the test.
HARNESS_STATUS = {
    "autofix/ansi/expect_fail_ignored_parse_error": ERROR,
    "autofix/ansi/expect_fail_no_rules": FAIL,
    "autofix/ansi/expect_fail_no_tree_ignored": FAIL,
    "autofix/ansi/expect_fail_noqa_masked_gate": ERROR,
    "autofix/ansi/expect_fail_parse_error": FAIL,
    "autofix/ansi/expect_fail_raise_off_gate": ERROR,
    "autofix/ansi/expect_fail_warning_violations": FAIL,
    "autofix/ansi/expect_fail_wrong_after": FAIL,
    "autofix/ansi/expect_pass_empty_violations": PASS,
    "autofix/ansi/expect_pass_ignored_parse_error": ERROR,
    "autofix/ansi/expect_pass_noqa_masked_violation": PASS,
    "autofix/ansi/expect_pass_raise_off_parse_error": ERROR,
    "autofix/ansi/expect_pass_rules_all": PASS,
    "autofix/tsql/expect_fail_lint_mode_violations": FAIL,
    "autofix/tsql/expect_pass_fix_mode_violations": PASS,
}


def test_harness_fixture_list():
    assert sorted(HARNESS_CASES) == sorted(HARNESS_STATUS)
    for case_id, status in HARNESS_STATUS.items():
        key = case_id.rsplit("/", 1)[-1]
        assert key.startswith(("expect_pass_", "expect_fail_"))
        # Never "pass" where the test fails.
        if key.startswith("expect_fail_"):
            assert status != PASS
        else:
            assert status != FAIL


@needs_sqlfluff
@pytest.mark.parametrize("case_id", sorted(HARNESS_STATUS))
def test_harness_fixtures(case_id):
    result = autofix.run(adapter, HARNESS_CASES[case_id], SQLFLUFF_ROOT)
    assert result.status == HARNESS_STATUS[case_id], result.reason
    if result.status == ERROR:
        assert result.reason == autofix.GATE_REASON


@needs_sqlfluff
def test_long_line_case_checks_the_violations():
    result = autofix.run(adapter, CASES["autofix/ansi/001_long_line"], SQLFLUFF_ROOT)
    assert result.status == PASS, result.reason
    assert result.checks == {
        "tree": True,
        "non_linting": True,
        "violations": True,
        "fix": True,
    }


@needs_sqlfluff
def test_mutated_long_line_case_fails(tmp_path):
    src = CASES["autofix/ansi/001_long_line"].folder
    folder = tmp_path / "ansi" / "001_long_line"
    shutil.copytree(src, folder)
    data = {"violations": {"linting": {"LT05": [[3, 10]]}}}
    (folder / "violations.json").write_text(json.dumps(data))
    case = autofix.AutofixCase("autofix/ansi/001_long_line", "ansi", folder)
    result = autofix.run(adapter, case, SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert (
        result.reason == "violations: missing [('LT05', 3, 10)], extra [('LT05', 3, 9)]"
    )
    (folder / "violations.json").unlink()
    (folder / "after.sql").write_text((folder / "before.sql").read_text())
    result = autofix.run(adapter, case, SQLFLUFF_ROOT)
    assert result.status == FAIL
    assert result.reason == "fix mismatch"


@needs_sqlfluff
def test_macro_path_is_relative_to_the_sqlfluff_root():
    # The case config loads macros from a path relative to the sqlfluff
    # root. From another folder the case fails.
    case = CASES["autofix/ansi/macro_file_jinja_include_undefined_variable"]
    assert autofix.run(adapter, case, SQLFLUFF_ROOT).status == PASS
    with tempfile.TemporaryDirectory() as other:
        assert autofix.run(adapter, case, Path(other)).status != PASS


@needs_sqlfluff
def test_fix_file_shows_violations_and_the_gate(tmp_path):
    sql = tmp_path / "testing.sql"
    sql.write_text("SELECT a  +  b FROM t\n\nWHERE c = 1 FROM\n")
    result = adapter.fix_file(sql, ["LT01"], "ansi", SQLFLUFF_ROOT, True)
    assert not result.errors
    assert result.linted is True
    assert result.unparsable_gate is False
    assert result.violations == [
        _v("LT01", 1, 9),
        _v("LT01", 1, 12),
        _v("PRS", 3, 13),
    ]
    sql.write_text("SELECT a  +  b FROM t\n\nWHERE c = 1 FROM\n")
    result = adapter.fix_file(sql, ["LT01"], "ansi", SQLFLUFF_ROOT, False)
    assert result.unparsable_gate is True
    assert result.violations is None
    assert sql.read_text() == "SELECT a  +  b FROM t\n\nWHERE c = 1 FROM\n"


@needs_sqlfluff
def test_parse_file_reads_the_local_config(tmp_path):
    sql = tmp_path / "testing.sql"
    sql.write_text("SELECT (;\n")
    assert adapter.parse_file(sql, "ansi", SQLFLUFF_ROOT).tree is None
    sql.write_text("SELECT a FROM t\n")
    assert adapter.parse_file(sql, "ansi", SQLFLUFF_ROOT).tree is not None
    # This config makes the parse fail if sqlfluff reads it.
    (tmp_path / ".sqlfluff").write_text("[sqlfluff]\nmax_parse_depth = 2\n")
    assert adapter.parse_file(sql, "ansi", SQLFLUFF_ROOT).tree is None


@needs_sqlfluff
def test_temp_dirs_are_removed(tmp_path, monkeypatch):
    EmptyHome.path()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    case = CASES["autofix/ansi/001_long_line"]
    assert autofix.run(adapter, case, SQLFLUFF_ROOT).status == PASS
    assert list(tmp_path.iterdir()) == []
