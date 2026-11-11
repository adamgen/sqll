"""The asserts of a sqlfluff test function (docs/decisions/s7-tests-design.md,
"Trace oracle").

The trace oracle needs each assert of the source test of a converted node: a
check of a case must cite it, or the not-reproduced record must have it.
This module reads the source with the ast module. It does not import or run
the test.

An assert has an id:

- "L<line>": an assert statement at that line of the source file.
- "L<line>:<arg>": a check of a known assert helper at the line of its call
  (KNOWN_HELPERS). invoke_assert_code always checks ret_code, and checks
  assert_stdout_contains and assert_stderr_contains if the call gives them.
- "L<line>:raises", "L<line>:warns", "L<line>:fail": pytest.raises,
  pytest.warns, and pytest.fail.

The finder reads the test function and, by name, each function of the same
module that the test calls (and so on). It fails closed (AssertSourceError)
on a call of a function whose name has "assert" and that is not a known
helper (for example mock.assert_called_once or self.assertEqual), and on a
call of a function that the module imports from a test helper module
(sqlfluff.utils.testing or the test package) and that is not a known
helper.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

# The known assert helpers: the arguments that each one checks, in the order
# of its parameters, with the arguments that it always checks.
KNOWN_HELPERS = {
    "invoke_assert_code": {
        "params": (
            "ret_code",
            "args",
            "kwargs",
            "cli_input",
            "assert_stdout_contains",
            "assert_stderr_contains",
            "raise_exceptions",
        ),
        "always": ("ret_code",),
        "if_given": ("assert_stdout_contains", "assert_stderr_contains"),
    },
}
PYTEST_CHECKS = {"raises": "raises", "warns": "warns", "fail": "fail"}
# The modules of test helpers. A call of a name that the test module imports
# from one of them must be a known helper.
HELPER_MODULES = re.compile(r"^(sqlfluff\.utils\.testing(\.|$)|test(\.|$))")
ASSERT_NAME = re.compile(r"assert", re.IGNORECASE)


class AssertSourceError(Exception):
    """The finder cannot list the asserts of a test."""


@dataclass(frozen=True)
class Assert:
    id: str
    function: str  # the function that has the assert
    text: str  # the source text of the statement or call (first line)


def _callee(call: ast.Call) -> tuple[str, str | None]:
    """(name, base) of a call: f() gives ("f", None), a.b.f() gives ("f", "a.b")."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id, None
    if isinstance(func, ast.Attribute):
        return func.attr, ast.unparse(func.value)
    return "", None


def _first_line(source_lines: list[str], node: ast.AST) -> str:
    return source_lines[node.lineno - 1].strip()


class _Module:
    def __init__(self, path: Path) -> None:
        self.path = path
        text = path.read_text(encoding="utf8")
        self.lines = text.splitlines()
        self.tree = ast.parse(text, filename=str(path))
        self.functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self.classes: dict[str, ast.ClassDef] = {}
        self.helper_imports: dict[str, str] = {}
        for item in self.tree.body:
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                self.functions[item.name] = item
            elif isinstance(item, ast.ClassDef):
                self.classes[item.name] = item
            elif isinstance(item, ast.ImportFrom):
                module = "." * item.level + (item.module or "")
                if item.level or HELPER_MODULES.match(module):
                    for alias in item.names:
                        self.helper_imports[alias.asname or alias.name] = module

    def test_function(self, node_id: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
        parts = node_id.split("::")[1:]
        if not parts:
            raise AssertSourceError(f"{node_id}: not a pytest node id")
        name = parts[-1].split("[", 1)[0]
        if len(parts) == 1:
            found = self.functions.get(name)
        elif len(parts) == 2 and parts[0] in self.classes:
            found = next(
                (
                    f
                    for f in self.classes[parts[0]].body
                    if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef)
                    and f.name == name
                ),
                None,
            )
        else:
            found = None
        if found is None:
            raise AssertSourceError(f"{node_id}: no test function in {self.path.name}")
        return found


def _helper_asserts(name: str, call: ast.Call) -> list[str]:
    helper = KNOWN_HELPERS[name]
    given = {kw.arg for kw in call.keywords if kw.arg is not None}
    given |= set(helper["params"][: len(call.args)])
    if any(kw.arg is None for kw in call.keywords) or any(
        isinstance(a, ast.Starred) for a in call.args
    ):
        raise AssertSourceError(
            f"line {call.lineno}: {name} with *args or **kwargs; the finder"
            " cannot see which checks it makes"
        )
    out = list(helper["always"])
    for arg in helper["if_given"]:
        value = next((kw.value for kw in call.keywords if kw.arg == arg), None)
        if value is None and arg in helper["params"][: len(call.args)]:
            value = call.args[helper["params"].index(arg)]
        empty = isinstance(value, ast.Constant) and value.value == ""
        if arg in given and not empty:
            out.append(arg)
    return out


def find_asserts(source_root: Path, node_id: str) -> list[Assert]:
    """The asserts of the test function of a node, in source order.

    source_root is the root of the sqlfluff checkout; the node id starts with
    the path of the test file relative to it.
    """
    file = node_id.split("::", 1)[0]
    module = _Module(source_root / file)
    start = module.test_function(node_id)
    found: dict[str, Assert] = {}
    seen: set[str] = set()
    todo = [start]
    while todo:
        function = todo.pop()
        if function.name in seen:
            continue
        seen.add(function.name)
        for node in ast.walk(function):
            if isinstance(node, ast.Assert):
                aid = f"L{node.lineno}"
                found[aid] = Assert(aid, function.name, _first_line(module.lines, node))
                continue
            if not isinstance(node, ast.Call):
                continue
            name, base = _callee(node)
            text = _first_line(module.lines, node)
            if base is None and name in KNOWN_HELPERS:
                for arg in _helper_asserts(name, node):
                    aid = f"L{node.lineno}:{arg}"
                    found[aid] = Assert(aid, function.name, text)
            elif base == "pytest" and name in PYTEST_CHECKS:
                aid = f"L{node.lineno}:{PYTEST_CHECKS[name]}"
                found[aid] = Assert(aid, function.name, text)
            elif ASSERT_NAME.search(name):
                raise AssertSourceError(
                    f"{node_id}: line {node.lineno}: {name} is an assert helper"
                    " that the finder does not know"
                )
            elif base is None and name in module.helper_imports:
                raise AssertSourceError(
                    f"{node_id}: line {node.lineno}: {name} comes from the test"
                    f" helper module {module.helper_imports[name]}; the finder"
                    " does not read it"
                )
            elif base is None and name in module.functions:
                todo.append(module.functions[name])
    return sorted(found.values(), key=_order)


def _order(item: Assert) -> tuple[int, str]:
    line, _, arg = item.id[1:].partition(":")
    return int(line), arg
