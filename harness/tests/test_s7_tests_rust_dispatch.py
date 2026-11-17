"""The Rust dispatch nodes (cp01, cp03, cp04_rust_dispatch_test.py) and
decision 3 (docs/decisions/s7-tests-design.md, "Decisions"; status/S7-tests.md,
"Rust dispatch tests (T8)").

The trace oracle checks the converted node and the python-internal nodes.
It does not check the class engine-comparison. This test reads the source of
each Rust dispatch test and gives each node its class by the rule of decision
3: a node that patches with unittest.mock is python-internal; a node whose
each assert compares 2 calls that are the same but for "True" and "False" (the
use_rust_rules value) is engine-comparison; each other node is converted. The
exclusion list and the case files must agree with it.
"""

import ast
import re

import yaml

from sqll_harness.paths import SQLFLUFF_ROOT
from sqll_harness.s7_tests import caseformat

CASES = caseformat.load()
FILES = {
    "test/rules/cp01_rust_dispatch_test.py": "CP01",
    "test/rules/cp03_rust_dispatch_test.py": "CP03",
    "test/rules/cp04_rust_dispatch_test.py": "CP04",
}
NODES = [n["id"] for n in CASES.scope["nodes"] if n["file"] in FILES]
EXCLUDED = {e.id: e for e in CASES.exclusions}
CONVERTED = {n.id for n in CASES.nodes}
RULE_FILES = {
    "CP01": ["CP01.yml"],
    "CP02": ["CP02.yml"],
    "CP03": ["CP03.yml"],
    "CP04": ["CP04.yml"],
    "LT01": [
        f"LT01-{part}.yml"
        for part in (
            "alignment",
            "brackets",
            "commas",
            "excessive",
            "functions",
            "literals",
            "missing",
            "operators",
            "trailing",
        )
    ],
}


def _function(node_id: str) -> ast.FunctionDef:
    path, name = node_id.split("::")
    name = name.split("[")[0]
    tree = ast.parse((SQLFLUFF_ROOT / path).read_text("utf8"))
    return next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name
    )


def _patches(func: ast.FunctionDef) -> bool:
    """True if the test calls mock.patch (or patch.object)."""
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            text = ast.unparse(node.func)
            if text in ("mock.patch", "mock.patch.object", "patch", "patch.object"):
                return True
    return False


def _engine_comparison(func: ast.FunctionDef) -> bool:
    """True if the test has asserts and each one is "call == call", where the
    2 calls are the same but for the constants "True" and "False"."""

    def mark(node: ast.AST, value: str) -> str:
        text = ast.dump(node)
        return text.replace(f"Constant(value='{value}')", "Constant(value='X')")

    asserts = [n for n in ast.walk(func) if isinstance(n, ast.Assert)]
    if not asserts:
        return False
    for item in asserts:
        test = item.test
        if not (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and isinstance(test.left, ast.Call)
            and isinstance(test.comparators[0], ast.Call)
        ):
            return False
        left, right = test.left, test.comparators[0]
        if ast.dump(left) == ast.dump(right):
            return False
        if mark(left, "True") != mark(right, "False"):
            return False
    return True


def _class(node_id: str) -> str:
    func = _function(node_id)
    if _patches(func):
        return "python-internal"
    if _engine_comparison(func):
        return "engine-comparison"
    return "converted"


def _rule_cases(rule: str) -> tuple[int, int]:
    """The S1 data cases of a rule, and the cases with a fix_str."""
    folder = SQLFLUFF_ROOT / "test" / "fixtures" / "rules" / "std_rule_cases"
    cases = []
    for name in RULE_FILES[rule]:
        data = yaml.safe_load((folder / name).read_text("utf8"))
        cases += [v for k, v in data.items() if k != "rule"]
    return len(cases), sum("fix_str" in case for case in cases)


def test_each_rust_dispatch_node_has_the_class_of_decision_3():
    assert len(NODES) == 102
    got = {}
    for node in NODES:
        if node in CONVERTED:
            got[node] = "converted"
        else:
            assert node in EXCLUDED, f"{node}: not converted and not excluded"
            got[node] = EXCLUDED[node].cls
    want = {node: _class(node) for node in NODES}
    assert got == want
    counts = {c: list(want.values()).count(c) for c in set(want.values())}
    assert counts == {"engine-comparison": 92, "python-internal": 9, "converted": 1}
    fix_parity = [n for n in NODES if "_dispatch__fix_parity[" in n]
    assert len(fix_parity) == 87
    assert {want[n] for n in fix_parity} == {"engine-comparison"}


def _rule_of(node_id: str) -> str:
    """The rule that a Rust dispatch test lints: CP02 and LT01 for the 2 tests
    of a rule with no Rust path of its own, else the rule of the file."""
    path, name = node_id.split("::")
    if name == "test__dispatch__rule_without_rust_path_falls_back":
        return "LT01"
    if name == "test__dispatch__cp02_inherits_eval_rust_and_falls_back":
        return "CP02"
    return FILES[path]


def test_each_rust_dispatch_exclusion_gives_its_reason():
    for node in NODES:
        entry = EXCLUDED.get(node)
        if entry is None:
            continue
        reason = entry.reason or ""
        assert reason.strip() and "\n" not in reason, node
        assert reason.endswith("(decision 3).") or "(decision 3);" in reason, node
        if entry.cls != "engine-comparison":
            assert re.search(r"mock\.patch of sqlfluffrs\.cp0[134]_violations", reason)
            continue
        # The S1 data cases that cover the same rule, with their counts.
        rule = re.search(r"the S1 data cases cover (\w+):", reason)[1]
        n, fixes = _rule_cases(rule)
        files = RULE_FILES[rule]
        if len(files) == 1:
            where = f"{files[0]} has"
        else:
            where = f"the {len(files)} LT01-*.yml files have"
        assert f"cover {rule}: {where} {n} cases, {fixes} with fix_str." in reason, node
        compared = re.search(r"True and False for (\w+)", reason)[1]
        assert compared == rule == _rule_of(node), node


def test_the_converted_rust_dispatch_node_runs_without_sqlfluffrs():
    # The converted node has no skipif: sqlfluff runs it with no Rust parser.
    (node,) = [n for n in NODES if n in CONVERTED]
    func = _function(node)
    assert not func.decorator_list
    for other in NODES:
        if other not in CONVERTED:
            text = ast.unparse(_function(other).decorator_list[0])
            assert "Rust parser not available" in text, other
