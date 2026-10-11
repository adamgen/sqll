from sqll_harness.paths import SQLFLUFF_ROOT
from sqll_harness.suites import dialects


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
