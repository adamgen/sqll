from pathlib import Path

import pytest
from conftest import needs

from sqll_harness.adapters.sqlfluff import SqlfluffAdapter
from sqll_harness.adapters.sqlfluff_rs import SqlfluffRsAdapter
from sqll_harness.cases import FAIL, PASS
from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT
from sqll_harness.suites import dialects
from sqll_harness.suites.rules import has_inline_config


def test_discovery_count():
    cases = dialects.discover(SQLFLUFF_ROOT)
    assert len(cases) == 2306
    assert len({c.id for c in cases}) == len(cases)


def test_case_fields():
    cases = {c.id: c for c in dialects.discover(SQLFLUFF_ROOT)}
    case = cases["dialects/ansi/select_simple_a"]
    assert case.dialect == "ansi"
    assert case.code_only
    assert str(case.sql) == "test/fixtures/dialects/ansi/select_simple_a.sql"
    assert case.extra_config is None


def test_depth_override():
    cases = {c.id: c for c in dialects.discover(SQLFLUFF_ROOT)}
    case = cases["dialects/ansi/expression_recursion"]
    assert case.extra_config == {"core": {"max_parse_depth": 2000}}


def test_in_file_config_lines_are_recorded():
    # The CLI applies in-file config lines and the sqlfluff test does not.
    # harness/not-reproduced.md records the only pinned file with one; this
    # test fails if the pinned fixtures change.
    found = {}
    for case in dialects.discover(SQLFLUFF_ROOT):
        sql = (SQLFLUFF_ROOT / case.sql).read_text(encoding="utf-8")
        if has_inline_config(sql):
            lines = [line for line in sql.splitlines() if has_inline_config(line)]
            found[f"{case.dialect}/{case.sql.name}"] = lines
    assert found == {"clickhouse/create_user.sql": ["-- sqlfluff:dialect:clickhouse"]}
    record = (REPO_ROOT / "harness" / "not-reproduced.md").read_text(encoding="utf-8")
    assert "`clickhouse/create_user.sql`" in record


def test_nc_yml_gives_full_tree_case(tmp_path):
    d = tmp_path / "test" / "fixtures" / "dialects" / "ansi"
    d.mkdir(parents=True)
    for name in ("a.sql", "a.yml", "a_nc.yml", "b.sql", "c.sql", "c_nc.yml"):
        (d / name).write_text("")
    (d.parent / "README.md").write_text("")
    got = [(c.id, c.code_only) for c in dialects.discover(tmp_path)]
    assert got == [
        ("dialects/ansi/a", True),
        ("dialects/ansi/a_nc", False),
        ("dialects/ansi/c_nc", False),
    ]


# The harness result of each harness fixture, with each sqlfluff tool. The
# key prefix is the result of the sqlfluff tests
# (scripts/sqlfluff-dialect-oracle --check-prefixes, also with --rust).
FIXTURES = Path(__file__).parent / "fixtures" / "dialects"
HARNESS_CASES = {c.id: c for c in dialects.discover(FIXTURES)}
HARNESS_STATUS = {
    "dialects/ansi/expect_fail_tree": FAIL,
    "dialects/ansi/expect_fail_unparsable": FAIL,
    "dialects/ansi/expect_pass_comment_nc": PASS,
    "dialects/ansi/expect_pass_select": PASS,
}
TOOLS = {
    "sqlfluff": (SqlfluffAdapter, needs("sqlfluff/bin/sqlfluff")),
    "sqlfluff-rs": (SqlfluffRsAdapter, needs("sqlfluff-rs/bin/sqlfluff")),
}


def test_harness_fixture_list():
    assert list(HARNESS_CASES) == list(HARNESS_STATUS)
    for case_id, status in HARNESS_STATUS.items():
        key = case_id.rsplit("/", 1)[-1]
        assert key.startswith(("expect_pass_", "expect_fail_"))
        assert status == (PASS if key.startswith("expect_pass_") else FAIL)


@pytest.mark.parametrize(
    "tool, case_id",
    [
        pytest.param(tool, case_id, marks=mark)
        for tool, (_, mark) in TOOLS.items()
        for case_id in HARNESS_STATUS
    ],
)
def test_harness_fixtures(tool, case_id):
    result = dialects.run(TOOLS[tool][0](), HARNESS_CASES[case_id], FIXTURES)
    assert result.status == HARNESS_STATUS[case_id], result.reason
