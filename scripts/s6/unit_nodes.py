#!/usr/bin/env python3
"""Collect and classify the pytest nodes of the sqlfluff placeholder and
Python templater tests (docs/decisions/s6-templaters.md, "Set").

scripts/s6/inventory.py runs this script with the Python of the sqlfluff
oracle tools (scripts/setup):

  .tools/sqlfluff-oracle/bin/python scripts/s6/unit_nodes.py ROOT

ROOT is a sqlfluff checkout. The script runs "pytest --collect-only" on
TEST_FILES in place, with no bytecode and no cache. It runs no test. The
pytest output goes to stderr. It writes one JSON list to stdout: each node
with its kind, the templater methods that it calls, its templater inputs
(each override_context and each FluffConfig argument, evaluated from the
test source and the pytest parameters), and why it needs a Python runtime
(an empty list if it does not).

Kind: "black_box" if the test function calls process() (the templater
output or error), else "internal" (it calls only internal functions).

The exit code is 1 if a node has no test function, or if an input is not
a literal, a parameter, a local name with a literal value, or dict(...).
"""

import ast
import contextlib
import json
import os
import sys
from pathlib import Path

# Python and pytest must not write a bytecode file or a cache in the
# submodule.
sys.dont_write_bytecode = True

import pytest  # noqa: E402
from s6common import ADDRESS, runtime_needs  # noqa: E402
from sqlfluff.core.templaters import PlaceholderTemplater, PythonTemplater  # noqa: E402
from sqlfluff.core.templaters.python import IntermediateFileSlice  # noqa: E402

TEST_FILES = {
    "test/core/templaters/placeholder_test.py": "placeholder",
    "test/core/templaters/python_test.py": "python",
}
TEMPLATERS = {"PlaceholderTemplater", "PythonTemplater"}
# The methods of these classes are the templater functions that a test can
# call.
METHODS = {
    name
    for cls in (PlaceholderTemplater, PythonTemplater, IntermediateFileSlice)
    for name in dir(cls)
    if not name.startswith("__")
}


class Unknown(Exception):
    """An input that the script cannot evaluate."""


class Collector:
    def __init__(self) -> None:
        self.items: list = []
        self.errors: list[str] = []

    def pytest_collectreport(self, report) -> None:
        if report.failed:
            self.errors.append(report.nodeid)

    def pytest_collection_finish(self, session) -> None:
        self.items = list(session.items)


def evaluate(node: ast.expr, env: dict):
    """The value of a literal, a name in env, or dict(...) with keywords."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Dict):
        out = {}
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                out.update(evaluate(value, env))
            else:
                out[evaluate(key, env)] = evaluate(value, env)
        return out
    if isinstance(node, (ast.List, ast.Tuple)):
        items = [evaluate(e, env) for e in node.elts]
        return items if isinstance(node, ast.List) else tuple(items)
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "dict"
        and not node.args
    ):
        out = {}
        for kw in node.keywords:
            if kw.arg is None:
                out.update(evaluate(kw.value, env))
            else:
                out[kw.arg] = evaluate(kw.value, env)
        return out
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -evaluate(node.operand, env)
    raise Unknown(ast.unparse(node))


def local_names(func: ast.FunctionDef, params: dict) -> dict:
    """The parameters, and each top-level "name = <literal>" of the body."""
    env = dict(params)
    for stmt in func.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            with contextlib.suppress(Unknown):
                env[stmt.targets[0].id] = evaluate(stmt.value, env)
    return env


def deep_texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from deep_texts(k)
            yield from deep_texts(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from deep_texts(v)


def classify(func: ast.FunctionDef, params: dict) -> dict:
    env = local_names(func, params)
    calls: set[str] = set()
    contexts, configs, needs, raises = [], [], [], []
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in METHODS:
                calls.add(f.attr)
            if isinstance(f, ast.Name) and f.id in TEMPLATERS:
                if node.args:
                    raise Unknown(f"positional argument of {f.id}")
                kws = {kw.arg: kw.value for kw in node.keywords}
                if set(kws) - {"override_context"}:
                    raise Unknown(f"argument of {f.id}: {sorted(kws)}")
                ctx = kws.get("override_context")
                contexts.append(None if ctx is None else evaluate(ctx, env))
            if isinstance(f, ast.Name) and f.id == "FluffConfig":
                if node.args or any(kw.arg is None for kw in node.keywords):
                    raise Unknown("FluffConfig argument")
                configs.append(
                    {kw.arg: evaluate(kw.value, env) for kw in node.keywords}
                )
            if ast.unparse(f) == "pytest.raises" and node.args:
                raises.append(ast.unparse(node.args[0]))
        if isinstance(node, ast.Lambda):
            body = node.body
            constant = isinstance(body, ast.Constant) or (
                isinstance(body, ast.Name) and body.id in params
            )
            if not constant:
                needs.append(f"python code: lambda at line {node.lineno}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if ADDRESS.search(node.value):
                needs.append(f"object address: line {node.lineno}")
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "id":
            needs.append(f"object address: id() at line {node.lineno}")
    for name, value in params.items():
        if any(ADDRESS.search(t) for t in deep_texts(value)):
            needs.append(f"object address: parameter {name}")
    needs += runtime_needs(contexts + configs)
    return {
        "kind": "black_box" if "process" in calls else "internal",
        "calls": sorted(calls),
        "context": contexts,
        "config": configs,
        "raises": sorted(set(raises)),
        "needs_python_runtime": needs,
    }


def python_object(value) -> dict:
    """The JSON form of an input that is not JSON data: its type only (a
    repr can have an object address that changes on each run)."""
    return {"python_object": type(value).__qualname__}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: unit_nodes.py SQLFLUFF_ROOT", file=sys.stderr)
        return 2
    root = Path(argv[0]).resolve()
    funcs = {}
    for rel in TEST_FILES:
        tree = ast.parse((root / rel).read_text("utf8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                funcs[(rel, node.name)] = node
    collector = Collector()
    os.chdir(root)
    with contextlib.redirect_stdout(sys.stderr):
        code = pytest.main(
            ["--collect-only", "-q", "-p", "no:cacheprovider", *TEST_FILES],
            plugins=[collector],
        )
    if code != 0 or collector.errors:
        print(f"error: pytest collection: {code} {collector.errors}", file=sys.stderr)
        return 1
    nodes, problems = [], []
    for item in collector.items:
        rel = item.nodeid.split("::", 1)[0]
        name = item.originalname
        func = funcs.get((rel, name))
        if rel not in TEST_FILES or func is None:
            problems.append(f"{item.nodeid}: no test function in {rel}")
            continue
        params = dict(item.callspec.params) if hasattr(item, "callspec") else {}
        try:
            info = classify(func, params)
        except Unknown as exc:
            problems.append(f"{item.nodeid}: cannot evaluate {exc}")
            continue
        nodes.append(
            {
                "id": item.nodeid,
                "file": rel,
                "function": name,
                "templater": TEST_FILES[rel],
                **info,
            }
        )
    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    if problems:
        return 1
    text = json.dumps(nodes, ensure_ascii=False, indent=1, default=python_object)
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
