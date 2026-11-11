"""The S6 fixture set (docs/decisions/s6-templaters.md, "Set").

S6: templater parity (sqll passes 100% of the placeholder and Python
format-string templater fixtures that do not need a Python runtime).

results/S6/scope.json must be the output of scripts/s6/inventory.py on the
pinned submodule, and the counts in the design record and in status/S6.md
must be its counts.
"""

import ast
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path

import pytest
from conftest import ci_module, needs

from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT, tools_dir

SCRIPTS = REPO_ROOT / "scripts" / "s6"
INVENTORY = SCRIPTS / "inventory.py"
UNIT_NODES = SCRIPTS / "unit_nodes.py"
SCOPE_FILE = REPO_ROOT / "results" / "S6" / "scope.json"
SCOPE = json.loads(SCOPE_FILE.read_text("utf8"))
DESIGN_FILE = REPO_ROOT / "docs" / "decisions" / "s6-templaters.md"
STATUS_FILE = REPO_ROOT / "status" / "S6.md"
SUMMARY = json.loads((REPO_ROOT / "results" / "s1" / "summary.json").read_text("utf8"))
oracle = needs("sqlfluff-oracle/bin/python")


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inventory = load_script("s6_inventory", INVENTORY)
s6common = load_script("s6common", SCRIPTS / "s6common.py")

# The S6 set of sqlfluff 4.4.0.
COUNTS = {
    "templater_suite": {
        "total": 43,
        "jinja": 43,
        "placeholder": 0,
        "python": 0,
        "needs_python": 3,
    },
    "placeholder_nodes": {
        "total": 26,
        "black_box": 26,
        "internal": 0,
        "needs_python_runtime": 0,
    },
    "python_nodes": {
        "total": 53,
        "black_box": 28,
        "internal": 25,
        "needs_python_runtime": 0,
    },
    "rule_cases": {"total": 13, "placeholder": 12, "python": 1},
    "fixtures_not_in_set": 1,
    "fixture_configs": 9,
    "other_tests": 7,
    "s6_black_box": 54,
    "s6_internal": 25,
}


def flat(counts: dict, prefix: str = "") -> dict[str, int]:
    out = {}
    for key, value in counts.items():
        if isinstance(value, dict):
            out |= flat(value, f"{prefix}{key}.")
        else:
            out[f"{prefix}{key}"] = value
    return out


def section(text: str, title: str) -> str:
    """The text of the section "## <title>" or "### <title>"."""
    match = re.search(rf"^#+ {re.escape(title)}\n(.*?)(?=^#+ |\Z)", text, re.M | re.S)
    assert match, title
    return match.group(1)


def doc_counts(text: str) -> dict[str, int]:
    """The rows "| `key` | value |" of the section "Set"."""
    rows = re.findall(r"^\| `([\w.]+)` \| (\d+) \|$", section(text, "Set"), re.M)
    keys = [k for k, _ in rows]
    assert len(keys) == len(set(keys)), "a count is twice in the table"
    return {k: int(v) for k, v in rows}


def differences(recorded: str, output: str) -> list[str]:
    """What is different between the recorded scope and a new output."""
    if recorded == output:
        return []
    a, b = json.loads(recorded), json.loads(output)
    out = [f"key {k}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    ids_a = Counter(n["id"] for n in a.get("nodes", []))
    ids_b = Counter(n["id"] for n in b.get("nodes", []))
    out += [f"only recorded: {i}" for i in sorted((ids_a - ids_b).elements())]
    out += [f"only output: {i}" for i in sorted((ids_b - ids_a).elements())]
    return out or ["the text is different"]


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        list(args), capture_output=True, text=True, env=env, cwd=cwd, check=False
    )


ORACLE_PYTHON = str(tools_dir() / "sqlfluff-oracle" / "bin" / "python")


# The recorded scope is the inventory output.


@oracle
def test_recorded_scope_is_the_inventory_output():
    proc = run(sys.executable, str(INVENTORY))
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert differences(SCOPE_FILE.read_text("utf8"), proc.stdout) == []
    check = run(str(REPO_ROOT / "scripts" / "check-submodule"), "after the inventory")
    assert check.returncode == 0, check.stderr


def test_write_needs_the_pinned_submodule(tmp_path):
    proc = run(sys.executable, str(INVENTORY), "--write", "--root", str(tmp_path))
    assert proc.returncode == 2
    assert "--write needs the pinned submodule" in proc.stderr


def test_a_changed_scope_is_not_the_inventory_output():
    text = SCOPE_FILE.read_text("utf8")
    assert differences(text, text) == []
    data = json.loads(text)
    dropped = dict(data, nodes=data["nodes"][1:])
    assert differences(
        text, json.dumps(dropped, ensure_ascii=False, indent=1) + "\n"
    ) == [
        "key nodes",
        f"only recorded: {data['nodes'][0]['id']}",
    ]
    changed = json.loads(text)
    changed["counts"]["s6_black_box"] = 53
    assert differences(
        text, json.dumps(changed, ensure_ascii=False, indent=1) + "\n"
    ) == ["key counts"]
    assert differences(text, text.replace("\n", "\n ", 1)) == ["the text is different"]


# The counts.


def test_counts():
    assert SCOPE["counts"] == COUNTS
    assert inventory.counts(SCOPE) == SCOPE["counts"]
    assert SCOPE["sqlfluff"] == "4.4.0"
    assert SCOPE["commit"] == "0348222a3bcdb0226563f7349c5a39beb0641955"
    assert len({n["id"] for n in SCOPE["nodes"]}) == len(SCOPE["nodes"])
    for node in SCOPE["nodes"]:
        assert node["id"].split("::")[0] == node["file"]
        assert node["id"].split("::")[1].split("[")[0] == node["function"]
    functions = Counter(f"{n['file']}::{n['function']}" for n in SCOPE["nodes"])
    assert {k: v["nodes"] for k, v in SCOPE["functions"].items()} == dict(functions)


@pytest.mark.parametrize("path", [DESIGN_FILE, STATUS_FILE], ids=["design", "status"])
def test_documents_give_the_counts(path):
    assert doc_counts(path.read_text("utf8")) == flat(SCOPE["counts"])


def test_a_changed_count_in_a_document_is_found():
    text = STATUS_FILE.read_text("utf8")
    changed = text.replace("| `s6_black_box` | 54 |", "| `s6_black_box` | 55 |")
    assert changed != text
    assert doc_counts(changed) != flat(SCOPE["counts"])
    dropped = text.replace("| `s6_internal` | 25 |\n", "")
    assert dropped != text
    assert doc_counts(dropped) != flat(SCOPE["counts"])


# The parts of the set.


def test_templater_suite_is_jinja_and_s11():
    suite = SCOPE["templater_suite"]
    summary = SUMMARY["results"]["sqll"]["suites"]["templater"]
    assert len(suite) == summary["total"] == 43
    assert {c["templater"] for c in suite} == {"jinja"}
    assert {c["known_failure"] for c in suite} == {inventory.JINJA_REASON}
    needs_python = sorted(c["id"] for c in suite if c["needs_python"])
    assert {tuple(c["needs_python"]) for c in suite if c["needs_python"]} == {
        ("library_path",)
    }
    status = STATUS_FILE.read_text("utf8")
    known = section(status, "Known failures")
    assert sorted(re.findall(r"`(templater/[\w/]+)`", known)) == needs_python
    assert f"`{inventory.JINJA_REASON}`" in known
    parity = " ".join(section(status, "Parity now").split())
    assert f"sqll {summary['passed']} of {summary['total']}" in parity
    sqlfluff = SUMMARY["results"]["sqlfluff"]["suites"]["templater"]
    assert f"sqlfluff {sqlfluff['passed']} of {sqlfluff['total']}" in parity
    counts = SCOPE["counts"]
    assert f"0 of {counts['s6_black_box']} converted" in parity
    assert f"0 of {counts['s6_internal']}" in parity
    assert f"each of the {counts['rule_cases']['total']}" in parity


def test_functions_in_the_design_record():
    design = DESIGN_FILE.read_text("utf8")
    rows = re.findall(
        r"^\| `(\w+_test\.py::\w+)` \| (\d+) \| (black_box|internal) \| (yes|no) \|$",
        section(design, "Needs a Python runtime"),
        re.M,
    )
    needs_by_function = Counter()
    for n in SCOPE["nodes"]:
        needs_by_function[f"{n['file']}::{n['function']}"] += bool(
            n["needs_python_runtime"]
        )
    want = [
        (
            key.removeprefix("test/core/templaters/"),
            str(v["nodes"]),
            v["kind"],
            "yes" if needs_by_function[key] else "no",
        )
        for key, v in SCOPE["functions"].items()
    ]
    assert sorted(rows) == sorted(want)
    internal = {k for k, v in SCOPE["functions"].items() if v["kind"] == "internal"}
    calls = sorted(c for k in internal for c in SCOPE["functions"][k]["calls"])
    text = section(design, "Internal nodes")
    assert sorted(set(re.findall(r"`(\w+)`", text.split("\n\n")[0]))) == calls


def test_black_box_nodes_call_process_and_internal_nodes_do_not():
    for node in SCOPE["nodes"]:
        assert ("process" in node["calls"]) == (node["kind"] == "black_box"), node["id"]
        if node["kind"] == "black_box":
            assert node["context"], node["id"]
    assert all(not n["needs_python_runtime"] for n in SCOPE["nodes"])


def test_rule_cases():
    rules = Counter(
        (c["rule"], c["templater"]) for c in SCOPE["rule_cases"] if c["owner"] == "S5"
    )
    assert rules == {
        ("AM04", "placeholder"): 3,
        ("AM07", "placeholder"): 1,
        ("CP02", "placeholder"): 4,
        ("CP02,LT01", "placeholder"): 1,
        ("RF03", "placeholder"): 1,
        ("ST10", "placeholder"): 1,
        ("ST11", "placeholder"): 1,
        ("JJ01", "python"): 1,
    }
    python = [c["id"] for c in SCOPE["rule_cases"] if c["templater"] == "python"]
    assert python == ["rules/JJ01/test_pass_python_templater"]
    design = section(DESIGN_FILE.read_text("utf8"), "Set")
    for (rule, name), n in rules.items():
        if name == "placeholder":
            assert f"{rule.replace(',', '_')} {n}" in design, rule


def test_flyway_fixture_is_not_in_the_set():
    assert SCOPE["fixtures"] == [
        {
            "path": "test/fixtures/templater/placeholder_flyway_var/"
            "placeholder_flyway_var_a.sql",
            "in_suite": False,
            "expected_output": False,
            "users": [],
            "reason": (
                "no test of sqlfluff 4.4.0 uses it, and it has no expected output"
            ),
        }
    ]
    for path in (DESIGN_FILE, STATUS_FILE):
        assert "placeholder_flyway_var_a.sql" in path.read_text("utf8")


def test_other_tests_in_the_design_record():
    rows = re.findall(
        r"^\| `(test/[\w/.]+)` \| ([\w ]+) \| ",
        section(DESIGN_FILE.read_text("utf8"), "Other test files"),
        re.M,
    )
    assert sorted(rows) == sorted((e["file"], e["owner"]) for e in SCOPE["other_tests"])
    assert {e["owner"] for e in SCOPE["other_tests"]} == {
        "S7 test conversion",
        "out of scope",
    }


def test_known_styles_of_the_design_record():
    path = SQLFLUFF_ROOT / "src" / "sqlfluff" / "core" / "templaters" / "placeholder.py"
    tree = ast.parse(path.read_text("utf8"))
    styles = [
        n.value
        for n in tree.body
        if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "KNOWN_STYLES"
    ]
    assert len(styles) == 1 and isinstance(styles[0], ast.Dict)
    n = len(styles[0].keys)
    design = " ".join(DESIGN_FILE.read_text("utf8").split())
    assert f"the {n} `KNOWN_STYLES` patterns" in design


# The track paths (tracks.yml).


def test_s6_owns_its_paths():
    ownership = ci_module("ownership")
    tracks = ownership.load()
    for path in (
        "status/S6.md",
        "results/S6/scope.json",
        "docs/decisions/s6-templaters.md",
        "scripts/s6/inventory.py",
        "harness/sqll_harness/s6/cases/x.yml",
        "harness/tests/test_s6_scope.py",
        "harness/tests/fixtures/s6/x.sql",
        "crates/sqll_templater/src/lib.rs",
    ):
        assert ownership.owner(path, tracks) == "S6", path
    for path in ("tracks.yml", "scripts/verify", "harness/sqll_harness/cli.py"):
        assert ownership.owner(path, tracks) == "core", path
    design = DESIGN_FILE.read_text("utf8")
    for pattern in tracks["S6"]["paths"]:
        assert f"`{pattern}`" in section(design, "Paths"), pattern


# The rule "needs a Python runtime".


def test_literal_ok():
    for value in (
        "a",
        "",
        0,
        -3,
        1.5,
        True,
        False,
        None,
        [1, "a"],
        {"a": {"b": 2}},
        (1,),
    ):
        assert s6common.literal_ok(value), value
    for value in (
        datetime.date(2020, 1, 1),
        object(),
        {1: "a"},
        [object()],
        float("nan"),
    ):
        assert not s6common.literal_ok(value), value


def test_runtime_needs():
    assert s6common.runtime_needs([None, {"a": "1", "b": 2}]) == []
    assert s6common.runtime_needs([{"f": len}]) == ["python code: input0.f"]
    assert s6common.runtime_needs([{"core": {"library_path": "libs"}}]) == [
        "python code: input0.core.library_path"
    ]
    assert s6common.runtime_needs([{"core": {"library_path": "none"}}]) == []
    assert s6common.runtime_needs([{"x": "<object at 0x7f3a12345678>"}]) == [
        "object address: input0.x"
    ]
    assert s6common.runtime_needs([{}, {"d": datetime.date(2020, 1, 1)}]) == [
        "not a literal: input1.d"
    ]


def line_of(source: str, text: str) -> int:
    lines = textwrap.dedent(source).splitlines()
    return next(i for i, line in enumerate(lines, 1) if text in line)


def write_root(root: Path, placeholder: str, python: str) -> Path:
    folder = root / "test" / "core" / "templaters"
    folder.mkdir(parents=True)
    (folder / "placeholder_test.py").write_text(textwrap.dedent(placeholder), "utf8")
    (folder / "python_test.py").write_text(textwrap.dedent(python), "utf8")
    return root


PLACEHOLDER_TESTS = """\
    import datetime

    import pytest
    from sqlfluff.core import FluffConfig
    from sqlfluff.core.templaters import PlaceholderTemplater


    def test_ok():
        t = PlaceholderTemplater(override_context=dict(param_style="colon", a="1"))
        config = FluffConfig(overrides={"dialect": "ansi"})
        t.process(in_str="SELECT :a", fname="x", config=config)


    @pytest.mark.parametrize("value", [datetime.date(2020, 1, 1)])
    def test_object(value):
        context = {"param_style": "colon", "a": value}
        PlaceholderTemplater(override_context=context).process(in_str="x", fname="x")


    def test_address():
        PlaceholderTemplater().process(in_str="<object at 0x7f3a12345678>", fname="x")
"""
PYTHON_TESTS = """\
    from sqlfluff.core.templaters import PythonTemplater


    def test_internal():
        PythonTemplater._substring_occurrences("a", ["a"])


    def test_code():
        PythonTemplater().slice_file("a", (lambda x: x.upper()), config=None)
"""


@oracle
def test_unit_nodes_classifies_each_node(tmp_path):
    root = write_root(tmp_path / "sqlfluff", PLACEHOLDER_TESTS, PYTHON_TESTS)
    proc = run(ORACLE_PYTHON, str(UNIT_NODES), str(root))
    assert proc.returncode == 0, proc.stderr[-3000:]
    nodes = {n["id"].split("::")[1]: n for n in json.loads(proc.stdout)}
    assert sorted(nodes) == [
        "test_address",
        "test_code",
        "test_internal",
        "test_object[value0]",
        "test_ok",
    ]
    ok = nodes["test_ok"]
    assert (ok["kind"], ok["calls"], ok["needs_python_runtime"]) == (
        "black_box",
        ["process"],
        [],
    )
    assert ok["context"] == [{"param_style": "colon", "a": "1"}]
    assert ok["config"] == [{"overrides": {"dialect": "ansi"}}]
    obj = nodes["test_object[value0]"]
    assert obj["needs_python_runtime"] == ["not a literal: input0.a"]
    assert obj["context"] == [{"param_style": "colon", "a": {"python_object": "date"}}]
    line = line_of(PLACEHOLDER_TESTS, "0x7f3a")
    assert nodes["test_address"]["needs_python_runtime"] == [
        f"object address: line {line}"
    ]
    internal = nodes["test_internal"]
    assert (internal["kind"], internal["calls"]) == (
        "internal",
        ["_substring_occurrences"],
    )
    line = line_of(PYTHON_TESTS, "lambda")
    assert nodes["test_code"]["needs_python_runtime"] == [
        f"python code: lambda at line {line}"
    ]
    assert nodes["test_code"]["kind"] == "internal"


@oracle
def test_unit_nodes_fails_closed_on_an_input_it_cannot_evaluate(tmp_path):
    placeholder = """\
        from sqlfluff.core.templaters import PlaceholderTemplater


        def make():
            return {}


        def test_call():
            PlaceholderTemplater(override_context=make()).process(in_str="x", fname="x")
    """
    root = write_root(tmp_path / "sqlfluff", placeholder, "")
    proc = run(ORACLE_PYTHON, str(UNIT_NODES), str(root))
    assert proc.returncode == 1
    assert "test_call: cannot evaluate make()" in proc.stderr


# The fail-closed checks of the inventory.


def test_inventory_fails_closed_on_a_test_with_no_owner(tmp_path):
    (tmp_path / "test" / "core").mkdir(parents=True)
    (tmp_path / "test" / "core" / "new_test.py").write_text(
        "from sqlfluff.core.templaters import PythonTemplater\n", "utf8"
    )
    found, problems = inventory.other_tests(tmp_path)
    assert found == []
    assert (
        "test/core/new_test.py: names the templaters ['class'] and has no owner"
        in problems
    )
    for name in inventory.OTHER_TESTS:
        assert f"{name}: has an owner and does not name the templaters" in problems


def test_inventory_fails_closed_on_a_fixture_with_no_owner(tmp_path):
    folder = tmp_path / "test" / "fixtures" / "linter" / "x"
    folder.mkdir(parents=True)
    (folder / ".sqlfluff").write_text("[sqlfluff]\ntemplater = python\n", "utf8")
    found, problems = inventory.fixture_configs(tmp_path)
    assert found == []
    assert problems == [
        "test/fixtures/linter/x/.sqlfluff: sets the templater ['python']"
        " and has no owner"
    ]


def test_inventory_fails_closed_on_a_used_fixture(tmp_path):
    folder = tmp_path / "test" / "fixtures" / "templater" / "placeholder_x"
    folder.mkdir(parents=True)
    (folder / "a.sql").write_text("SELECT :a\n", "utf8")
    (tmp_path / "test" / "x_test.py").write_text(
        'PATH = "placeholder_x/a.sql"\n', "utf8"
    )
    found, problems = inventory.fixtures(tmp_path, set())
    assert found[0]["users"] == ["test/x_test.py"]
    assert problems == [
        "test/fixtures/templater/placeholder_x/a.sql: a fixture with a user;"
        " give it an owner"
    ]
