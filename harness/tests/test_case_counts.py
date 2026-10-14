"""The harness finds the same cases as the sqlfluff tests collect.

scripts/sqlfluff-case-ids runs "pytest --collect-only" on the pinned
sqlfluff tests and prints the parameter id of each case. This test makes the
same id from each case that the harness finds. The 2 lists must be equal, as
lists with repeats. See "Case counts" in harness/README.md.
"""

import functools
import json
import os
import subprocess
from collections import Counter

import pytest
from conftest import needs

from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT, tools_dir
from sqll_harness.suites import SUITES, autofix, dialects, rules, templater

SCRIPT = REPO_ROOT / "scripts" / "sqlfluff-case-ids"

# The number of cases of each suite in sqlfluff 4.4.0.
COUNTS = {"dialects": 2306, "rules": 2527, "autofix": 61, "templater": 43}


def pytest_id(case) -> str:
    """Return the pytest parameter id of a harness case.

    pytest joins the parameter values with "-". A str value is the text and a
    bool value is "True" or "False". The rule test gives its own ids
    (load_test_cases): the rule with "_" for ",", then "_", then the key.
    pytest writes a character that is not ASCII as an escape sequence.
    """
    return _pytest_text(case).encode("unicode_escape").decode("ascii")


def _pytest_text(case) -> str:
    if isinstance(case, dialects.DialectCase):
        return f"{case.dialect}-{case.sql.name}-{case.code_only}-{case.yml.name}"
    if isinstance(case, rules.RuleCase):
        key = case.id.split("/", 2)[2]
        return f"{case.rule.replace(',', '_')}_{key}"
    if isinstance(case, autofix.AutofixCase):
        return f"{case.dialect}-{case.folder.name}"
    if isinstance(case, templater.TemplaterCase):
        return f"{case.subpath}-{case.code_only}-{case.include_meta}"
    raise TypeError(type(case))


def unique_ids(ids: list[str]) -> list[str]:
    """Make repeated ids unique, as pytest does when it collects.

    pytest adds a counter to each id that is in the list more than one time:
    0 for the first, 1 for the next, and so on. If the id ends with a digit,
    "_" comes before the counter. If a new id is also an other id, this
    function stops with an error and the test fails.
    """
    counts = Counter(ids)
    next_number: Counter = Counter()
    out = []
    for i in ids:
        if counts[i] > 1:
            sep = "_" if i[-1:].isdigit() else ""
            new = f"{i}{sep}{next_number[i]}"
            next_number[i] += 1
            if new in counts:
                raise ValueError(f"the unique id {new} is also an id")
            i = new
        out.append(i)
    return out


@functools.cache
def harness_ids() -> dict[str, list[str]]:
    """The pytest ids of the harness cases of each suite."""
    return {
        name: unique_ids([pytest_id(c) for c in SUITES[name].discover(SQLFLUFF_ROOT)])
        for name in COUNTS
    }


def differences(want: list[str], got: list[str]) -> tuple[list[str], list[str]]:
    """Return the ids only in want and the ids only in got, with repeats."""
    a, b = Counter(want), Counter(got)
    return sorted((a - b).elements()), sorted((b - a).elements())


@pytest.fixture(scope="module")
def sqlfluff_ids() -> dict:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [str(tools_dir() / "sqlfluff-oracle" / "bin" / "python"), str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout)


def test_harness_counts():
    got = {name: len(ids) for name, ids in harness_ids().items()}
    assert got == COUNTS
    assert sum(got.values()) == 4937


@needs("sqlfluff-oracle/bin/python")
def test_counts_are_the_counts_of_the_sqlfluff_tests(sqlfluff_ids):
    assert sqlfluff_ids["sqlfluff"] == "4.4.0"
    suites = sqlfluff_ids["suites"]
    assert {name: len(s["ids"]) for name, s in suites.items()} == COUNTS


@needs("sqlfluff-oracle/bin/python")
@pytest.mark.parametrize("suite", sorted(COUNTS))
def test_ids_are_the_ids_of_the_sqlfluff_tests(sqlfluff_ids, suite):
    want = sqlfluff_ids["suites"][suite]["ids"]
    only_sqlfluff, only_harness = differences(want, harness_ids()[suite])
    assert only_sqlfluff == []
    assert only_harness == []


def test_each_harness_case_has_its_own_id():
    for name, ids in harness_ids().items():
        assert len(set(ids)) == len(ids), name
        cases = SUITES[name].discover(SQLFLUFF_ROOT)
        assert len({c.id for c in cases}) == len(cases), name


def test_repeated_rule_test_ids_are_recorded():
    # The sqlfluff rule test gives these ids to 2 cases each, one in
    # LT01-literals.yml and one in LT01-operators.yml. pytest adds 0 and 1.
    # The harness ids have the file stem, so they are unique.
    ids = [pytest_id(c) for c in rules.discover(SQLFLUFF_ROOT)]
    repeated = sorted(i for i, n in Counter(ids).items() if n > 1)
    assert repeated == [
        "LT01_test_fail_expression",
        "LT01_test_pass_expression",
        "LT01_test_pass_sparksql_multi_units_interval_minus",
    ]
    assert all(Counter(ids)[i] == 2 for i in repeated)
    unique = harness_ids()["rules"]
    for i in repeated:
        assert [x for x in unique if x in (f"{i}0", f"{i}1")] == [f"{i}0", f"{i}1"]


@pytest.mark.parametrize(
    ("ids", "result"),
    [
        (["a", "b"], ["a", "b"]),
        (["a", "b", "a"], ["a0", "b", "a1"]),
        (["x1", "x1"], ["x1_0", "x1_1"]),
    ],
)
def test_unique_ids(ids, result):
    assert unique_ids(ids) == result


def test_unique_ids_stops_on_a_clash():
    with pytest.raises(ValueError):
        unique_ids(["a", "a", "a0"])


@pytest.mark.parametrize(
    ("want", "got", "result"),
    [
        (["a", "b"], ["b", "a"], ([], [])),
        (["a", "b"], ["a"], (["b"], [])),
        (["a"], ["a", "a"], ([], ["a"])),
        (["a", "a"], ["a"], (["a"], [])),
    ],
)
def test_differences_count_repeats(want, got, result):
    assert differences(want, got) == result


def test_a_missing_or_extra_harness_case_is_found(tmp_path):
    # Mutated fixtures: the harness finds one dialect case less, and one more.
    d = tmp_path / "test" / "fixtures" / "dialects" / "ansi"
    d.mkdir(parents=True)
    for name in ("a.sql", "a.yml", "b.sql", "b_nc.yml", "c.sql"):
        (d / name).write_text("")
    got = [pytest_id(c) for c in dialects.discover(tmp_path)]
    want = ["ansi-a.sql-True-a.yml", "ansi-b.sql-False-b_nc.yml"]
    assert differences(want, got) == ([], [])
    assert differences(want + ["ansi-c.sql-True-c.yml"], got) == (
        ["ansi-c.sql-True-c.yml"],
        [],
    )
    (d / "x.sql").write_text("")
    (d / "x.yml").write_text("")
    got = [pytest_id(c) for c in dialects.discover(tmp_path)]
    assert differences(want, got) == ([], ["ansi-x.sql-True-x.yml"])


def test_rule_ids_keep_the_space_after_the_comma():
    case = next(
        c
        for c in rules.discover(SQLFLUFF_ROOT)
        if c.id == "rules/AL02_LT01/test_alias_expression_align_4515_1"
    )
    assert pytest_id(case) == "AL02_ LT01_test_alias_expression_align_4515_1"


def test_rule_ids_escape_characters_that_are_not_ascii():
    case = next(
        c
        for c in rules.discover(SQLFLUFF_ROOT)
        if c.id == "rules/LT01-operators/test_pass_newline_\N{POUND SIGN}"
    )
    assert pytest_id(case) == "LT01_test_pass_newline_\\xa3"
