"""The S7 case format and the exclusion list (sqll_harness/s7_tests/
caseformat.py). Each fail-closed check of the loader has a mutation test: a
valid case file or exclusion list with one change that the loader must
refuse."""

import copy
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT
from sqll_harness.s7_tests import caseformat
from sqll_harness.s7_tests.caseformat import CaseFormatError

SCOPE = caseformat.load_scope()
SCOPE_IDS = {n["id"] for n in SCOPE["nodes"]}
DESIGN = (REPO_ROOT / "docs" / "decisions" / "s7-tests-design.md").read_text("utf8")

FILE = "test/rules/std_CV02_test.py"
NODE = f"{FILE}::test__rules__std_CV02_raised"
CLI_FILE = "test/cli/commands_test.py"
CLI_NODE = f"{CLI_FILE}::test__cli__command_dialect"
VALID = {
    "source": {
        "project": "sqlfluff",
        "version": "4.4.0",
        "commit": "0348222a3bcdb0226563f7349c5a39beb0641955",
        "file": FILE,
    },
    "license": "MIT",
    "nodes": [
        {
            "node": NODE,
            "cases": [
                {
                    "name": "raised",
                    "run": "api",
                    "function": "lint",
                    "sql": "SELECT 1",
                    "rules": ["CV02"],
                    "checks": {"violations": [{"count": 0}]},
                }
            ],
        }
    ],
}
VALID_CLI = {
    **VALID,
    "source": {**VALID["source"], "file": CLI_FILE},
    "nodes": [
        {
            "node": CLI_NODE,
            "cases": [
                {
                    "name": "dialect",
                    "run": "cli",
                    "argv": ["lint", "--dialect", "x", "a.sql"],
                    "cwd": "tmp",
                    "files": {"a.sql": "select 1\n"},
                    "checks": {
                        "exit_code": 2,
                        "stdout": {"contains": ["x"]},
                        "files": {"a.sql": "select 1\n"},
                        "violations": [{"file": "a.sql", "count": 0}],
                    },
                }
            ],
        }
    ],
}
VALID_EXCLUSIONS = {
    "excluded": [
        {
            "node": f"{CLI_FILE}::test___main___help",
            "class": "needs-python-runtime",
            "reason": "It runs python -m sqlfluff.",
        },
        {
            "node": f"{CLI_FILE}::test__cli__command_versioning",
            "class": "python-internal",
        },
    ]
}


def write_set(root: Path, files: dict[str, object], exclusions=VALID_EXCLUSIONS):
    cases = root / "cases"
    cases.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        path = cases / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else yaml.safe_dump(data))
    excl = root / "exclusions.yml"
    excl.write_text(
        exclusions if isinstance(exclusions, str) else yaml.safe_dump(exclusions)
    )
    return cases, excl


def load_set(root: Path, files: dict[str, object], exclusions=VALID_EXCLUSIONS):
    cases, excl = write_set(root, files, exclusions)
    return caseformat.load(cases, excl, SCOPE)


def errors_of(root: Path, files: dict[str, object], exclusions=VALID_EXCLUSIONS):
    with pytest.raises(CaseFormatError) as info:
        load_set(root, files, exclusions)
    return info.value.errors


RULES_PATH = "rules/std_CV02_test.yml"
CLI_PATH = "cli/commands_test.yml"


# The recorded case files and exclusion list.


def test_recorded_cases_load():
    cases = caseformat.load()
    groups = {n.group for n in cases.nodes}
    # The pilot has nodes of each group of the 3 suites.
    assert {"rules", "config", "cli"} <= groups
    assert all(n.cases for n in cases.nodes)
    assert {e.cls for e in cases.exclusions} <= set(caseformat.CLASSES)
    runs = {c.run for n in cases.nodes for c in n.cases}
    assert runs == {"cli", "api"}
    assert any(n.needs_jinja for n in cases.nodes)


def _raw_case_files():
    for path in sorted(caseformat.CASES_DIR.rglob("*.yml")):
        yield path, yaml.safe_load(path.read_text("utf8"))


def test_each_node_id_is_in_scope():
    # Read without the loader: each node id of a case file and of the
    # exclusion list is a node of results/S7-tests/scope.json.
    ids = []
    for _, data in _raw_case_files():
        ids += [n["node"] for n in data["nodes"]]
    excluded = yaml.safe_load(caseformat.EXCLUSIONS_FILE.read_text("utf8"))
    ids += [e["node"] for e in excluded["excluded"]]
    assert ids
    assert [i for i in ids if i not in SCOPE_IDS] == []
    assert len(ids) == len(set(ids))


def test_each_case_file_has_the_header_and_the_license():
    for path, data in _raw_case_files():
        assert data["license"] == "MIT", path
        assert data["source"] == {
            "project": "sqlfluff",
            "version": "4.4.0",
            "commit": caseformat.SQLFLUFF_COMMIT,
            "file": data["source"]["file"],
        }, path
        text = path.read_text("utf8")
        assert "copyright (c) 2018-2026 Alan\n# Cruickshank, MIT License." in text


def test_the_pinned_commit_is_the_submodule():
    head = subprocess.run(
        ["git", "-C", str(SQLFLUFF_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert head == caseformat.SQLFLUFF_COMMIT
    assert f"commit `{head}`" in (REPO_ROOT / "STATUS.md").read_text("utf8")
    assert SCOPE["sqlfluff"] == caseformat.SQLFLUFF_VERSION


def test_case_file_path():
    assert str(caseformat.case_file_path(CLI_FILE)) == CLI_PATH
    assert (
        str(caseformat.case_file_path("test/core/config/loader_test.py"))
        == "core/config/loader_test.yml"
    )


def test_valid_sets_load(tmp_path):
    out = load_set(tmp_path, {RULES_PATH: VALID, CLI_PATH: VALID_CLI})
    assert [n.id for n in out.nodes] == [CLI_NODE, NODE]
    assert out.nodes[0].cases[0].files == {"a.sql": "select 1\n"}
    # The order of scope.json.
    assert [(e.cls, e.reason) for e in out.exclusions] == [
        ("python-internal", None),
        ("needs-python-runtime", "It runs python -m sqlfluff."),
    ]


# Mutations of a case file. Each one must stop the load.


def mutate(data: dict, path: str, value=None, delete: bool = False) -> dict:
    """Return a copy of data with the value at a dotted path changed."""
    out = copy.deepcopy(data)
    keys = [int(k) if k.isdigit() else k for k in path.split(".")]
    target = out
    for key in keys[:-1]:
        target = target[key]
    if delete:
        del target[keys[-1]]
    else:
        target[keys[-1]] = value
    return out


CASE = "nodes.0.cases.0"


@pytest.mark.parametrize(
    ("base", "path", "value", "delete", "error"),
    [
        # The header: the source and the license.
        (VALID, "source", None, True, "header: has no source"),
        (VALID, "license", None, True, "header: has no license"),
        (VALID, "license", "Apache-2.0", False, "license: must be MIT"),
        (VALID, "source.file", None, True, "source: has no file"),
        (VALID, "source.commit", None, True, "source: has no commit"),
        (VALID, "source.version", "4.3.0", False, "source.version: '4.3.0' is not"),
        (VALID, "source.commit", "0348222a", False, "source.commit: '0348222a' is"),
        (VALID, "source.project", "sqruff", False, "source.project: 'sqruff' is"),
        (VALID, "source.license", "MIT", False, "source: unknown keys ['license']"),
        (VALID, "extra", 1, False, "header: unknown keys ['extra']"),
        (
            VALID,
            "source.file",
            "test/core/plugin_test.py",
            False,
            "source.file: 'test/core/plugin_test.py' has no node in scope.json",
        ),
        (
            VALID,
            "source.file",
            "test/rules/std_AL04_test.py",
            False,
            "source.file: the case file of test/rules/std_AL04_test.py is",
        ),
        # The nodes.
        (VALID, "nodes", [], False, "nodes: must be a list with one or more nodes"),
        (VALID, "nodes.0.node", f"{CLI_NODE}", False, "is not a node of"),
        (VALID, "nodes.0.cases", [], False, "cases must be a list with one or more"),
        (VALID, "nodes.0.extra", 1, False, "unknown keys ['extra']"),
        # The cases.
        (VALID, f"{CASE}.run", "python", False, ".run: must be one of"),
        (VALID, f"{CASE}.name", "", False, ".name: '' is not a new"),
        (VALID, f"{CASE}.argv", ["lint"], False, "unknown keys ['argv']"),
        (VALID, f"{CASE}.function", "parse", False, ".function: must be one of"),
        (VALID, f"{CASE}.sql", None, True, ".sql: must be a string"),
        (VALID, f"{CASE}.rules", "CV02", False, ".rules: must be a list"),
        (VALID, f"{CASE}.needs_jinja", "yes", False, ".needs_jinja: must be a bool"),
        (VALID, f"{CASE}.checks", {}, False, ".checks: needs violations"),
        (VALID, f"{CASE}.checks.fixed", "x", False, "unknown keys ['fixed']"),
        (VALID, f"{CASE}.checks.violations", [], False, "one or more checks"),
        (VALID, f"{CASE}.checks.violations.0", {}, False, "needs count, min_count"),
        (
            VALID,
            f"{CASE}.checks.violations.0.min_count",
            1,
            False,
            "has count and min_count",
        ),
        (VALID, f"{CASE}.checks.violations.0.count", -1, False, "integer >= 0"),
        (VALID, f"{CASE}.checks.violations.0.count", True, False, "integer >= 0"),
        (
            VALID,
            f"{CASE}.checks.violations.0.select",
            {"line": 1},
            False,
            "select: unknown keys ['line']",
        ),
        (
            VALID,
            f"{CASE}.checks.violations.0.select",
            {"code": {"regex": "x"}},
            False,
            "a mapping value must be {contains: <string>}",
        ),
        (
            VALID,
            f"{CASE}.checks.violations.0.records",
            [{"code": "CV02"}],
            False,
            "count is not the number of records",
        ),
        (
            VALID,
            f"{CASE}.checks.violations.0.exact",
            True,
            False,
            "exact: is a bool, and only with records",
        ),
        (
            VALID,
            f"{CASE}.checks.violations.0.file",
            "a.sql",
            False,
            "file: is a string, and only in a cli case",
        ),
        # cli cases.
        (VALID_CLI, f"{CASE}.argv", [], False, ".argv: must be a list of strings"),
        (VALID_CLI, f"{CASE}.argv", ["lint", 1], False, ".argv: must be a list"),
        (VALID_CLI, f"{CASE}.sql", "x", False, "unknown keys ['sql']"),
        (VALID_CLI, f"{CASE}.cwd", "home", False, ".cwd: must be one of"),
        (VALID_CLI, f"{CASE}.stdin", 1, False, ".stdin: must be a string"),
        (VALID_CLI, f"{CASE}.sqruff", "lint", False, ".sqruff: must be a list"),
        # The cases never write into the submodule (G4.5).
        (VALID_CLI, f"{CASE}.cwd", "sqlfluff", False, ".files: needs cwd: tmp"),
        (
            VALID_CLI,
            f"{CASE}.files",
            {"../x.sql": ""},
            False,
            "'../x.sql' is not a relative path",
        ),
        (
            VALID_CLI,
            f"{CASE}.files",
            {"/tmp/x.sql": ""},
            False,
            "'/tmp/x.sql' is not a relative path",
        ),
        (
            VALID_CLI,
            f"{CASE}.checks.exit_code",
            None,
            True,
            "exit_code: must be an integer (each cli case checks it)",
        ),
        (VALID_CLI, f"{CASE}.checks.stdout", {}, False, "stdout: has no matcher"),
        (
            VALID_CLI,
            f"{CASE}.checks.stdout",
            {"regex": "x"},
            False,
            "stdout: unknown keys ['regex']",
        ),
        (
            VALID_CLI,
            f"{CASE}.checks.stderr",
            {"contains": []},
            False,
            "stderr.contains: must be a list of strings with one or more",
        ),
        (VALID_CLI, f"{CASE}.checks.stdout.equals", 1, False, "must be a string"),
        (
            VALID_CLI,
            f"{CASE}.checks.files",
            {"a.sql": 1},
            False,
            "checks.files: must map each path to a string",
        ),
        (VALID_CLI, f"{CASE}.checks.fixed", "x", False, "unknown keys ['fixed']"),
    ],
)
def test_case_file_mutation_is_refused(tmp_path, base, path, value, delete, error):
    name = RULES_PATH if base is VALID else CLI_PATH
    errors = errors_of(tmp_path, {name: mutate(base, path, value, delete)})
    assert any(error in e for e in errors), errors
    # Without the mutation the same set loads.
    load_set(tmp_path / "good", {name: base})


def test_case_file_text_errors(tmp_path):
    text = yaml.safe_dump(VALID)
    errors = errors_of(tmp_path / "a", {RULES_PATH: text + "license: MIT\n"})
    assert any("repeated key 'license'" in e for e in errors), errors
    errors = errors_of(tmp_path / "b", {RULES_PATH: "[1, 2]\n"})
    assert errors == [f"{RULES_PATH}: file: must be a mapping"]
    errors = errors_of(tmp_path / "c", {RULES_PATH: VALID, "rules/x.yaml": "{}"})
    assert errors == ["rules/x.yaml: a file in the case folder that is not a .yml file"]
    # A repeated case name in a node.
    case = VALID["nodes"][0]["cases"][0]
    data = mutate(VALID, "nodes.0.cases", [case, case])
    errors = errors_of(tmp_path / "d", {RULES_PATH: data})
    assert any(".name: 'raised' is not a new" in e for e in errors), errors


def test_node_not_in_scope_is_refused(tmp_path):
    node = f"{FILE}::test_not_there"
    errors = errors_of(tmp_path, {RULES_PATH: mutate(VALID, "nodes.0.node", node)})
    assert errors == [f"{RULES_PATH}: {node}: not in scope.json"]


def test_node_in_two_places_is_refused(tmp_path):
    data = mutate(VALID, "nodes", VALID["nodes"] * 2)
    errors = errors_of(tmp_path / "a", {RULES_PATH: data})
    assert errors == [f"{RULES_PATH}: {NODE}: also in {RULES_PATH}"]
    excluded = {"excluded": [{"node": CLI_NODE, "class": "python-internal"}]}
    errors = errors_of(tmp_path / "b", {CLI_PATH: VALID_CLI}, excluded)
    assert errors == [f"{CLI_NODE}: excluded, but {CLI_PATH} converts it"]


# Mutations of the exclusion list.


EXCLUDED = "excluded.0"


@pytest.mark.parametrize(
    ("path", "value", "delete", "error"),
    [
        # A needs-python-runtime or environment node needs a reason of one
        # line.
        (f"{EXCLUDED}.reason", None, True, "class needs-python-runtime needs a reason"),
        (f"{EXCLUDED}.reason", "", False, "the reason must be one line of text"),
        (f"{EXCLUDED}.reason", "   ", False, "the reason must be one line of text"),
        (f"{EXCLUDED}.reason", "a\nb", False, "the reason must be one line of text"),
        (f"{EXCLUDED}.reason", 3, False, "the reason must be one line of text"),
        (f"{EXCLUDED}.class", "environment", False, None),
        # An unknown class.
        (f"{EXCLUDED}.class", "slow", False, "unknown class 'slow'"),
        (f"{EXCLUDED}.class", None, True, "unknown class None"),
        (
            f"{EXCLUDED}.node",
            f"{CLI_FILE}::test_not_there",
            False,
            "is not in scope.json",
        ),
        (f"{EXCLUDED}.why", "x", False, "unknown keys ['why']"),
        ("excluded.1", VALID_EXCLUSIONS["excluded"][0], False, "in the list 2 times"),
        ("excluded", {}, False, "excluded: must be a list"),
        ("other", [], False, "must be a mapping with only the key 'excluded'"),
    ],
)
def test_exclusion_mutation_is_refused(tmp_path, path, value, delete, error):
    data = mutate(VALID_EXCLUSIONS, path, value, delete)
    if error is None:
        # environment needs a reason too; this one has a reason, so it loads.
        load_set(tmp_path, {RULES_PATH: VALID}, data)
        data = mutate(data, f"{EXCLUDED}.reason", None, True)
        error = "class environment needs a reason"
    errors = errors_of(tmp_path / "bad", {RULES_PATH: VALID}, data)
    assert any(error in e for e in errors), errors


def test_exclusion_list_must_exist(tmp_path):
    cases, excl = write_set(tmp_path, {RULES_PATH: VALID})
    excl.unlink()
    with pytest.raises(CaseFormatError) as info:
        caseformat.load(cases, excl, SCOPE)
    assert info.value.errors == ["exclusions.yml: the exclusion list does not exist"]


def test_each_class_is_in_the_design_record():
    words = " ".join(DESIGN.split())
    for cls in caseformat.CLASSES:
        assert re.search(rf"- `{cls}`: ", DESIGN), cls
    assert "`needs-python-runtime` and `environment` node needs a reason" in words


def test_design_record_gives_each_key_of_the_format():
    start = DESIGN.index("\n## Case format\n")
    section = DESIGN[start : DESIGN.index("\n## Case runner\n")]
    keys = (
        caseformat._HEADER_KEYS
        | caseformat._SOURCE_KEYS
        | caseformat._NODE_KEYS
        | caseformat._CLI_KEYS
        | caseformat._API_KEYS
        | caseformat._CLI_CHECKS
        | {k for v in caseformat._API_CHECKS.values() for k in v}
        | caseformat._VIOLATION_CHECK_KEYS
        | caseformat._EXCLUSION_KEYS
        | set(caseformat.MATCHERS)
        | set(caseformat.RUNS)
        | set(caseformat.CWDS)
        | set(caseformat.API_FUNCTIONS)
    )
    missing = [
        k for k in sorted(keys) if not re.search(rf"[`\s]{re.escape(k)}[`:\s]", section)
    ]
    assert missing == []


def test_scope_counts_of_the_loader():
    assert len(SCOPE["nodes"]) == SCOPE["counts"]["total"] == 643
    assert json.loads(caseformat.SCOPE_FILE.read_text("utf8")) == SCOPE
