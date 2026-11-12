"""Shared rules of the S6 inventory (docs/decisions/s6-templaters.md).

scripts/s6/inventory.py (the harness Python) and scripts/s6/unit_nodes.py
(the Python of the sqlfluff oracle tools) both use this module. It uses only
the standard library.
"""

import ast
import re

# A text that shows a Python object address, for example
# "<object at 0x7f...>" or "0x7f3a".
ADDRESS = re.compile(r"\b0x[0-9a-fA-F]{4,}\b|\bobject at\b")
# Config keys that load Python code.
CODE_KEYS = ("library_path",)


def literal_ok(value) -> bool:
    """True if a config value can make value: ast.literal_eval of its repr
    gives an equal value of the same type, and so does each part of it."""
    if isinstance(value, dict):
        return all(isinstance(k, str) and literal_ok(v) for k, v in value.items())
    if isinstance(value, (list, tuple, set)) and not all(literal_ok(v) for v in value):
        return False
    if value is None or isinstance(
        value, (bool, int, float, complex, str, bytes, list, tuple, set)
    ):
        try:
            back = ast.literal_eval(repr(value))
        except (ValueError, SyntaxError):
            return False
        return type(back) is type(value) and back == value
    return False


def runtime_needs(inputs) -> list[str]:
    """Why a templater input (a context or config value) needs a Python
    runtime, or an empty list. inputs is a list of values (dicts or None).

    Rules (docs/decisions/s6-templaters.md, "Needs a Python runtime"):
    "python code": a callable value or a key of CODE_KEYS; "object address":
    a text with an object address; "not a literal: <path>": a value that
    ast.literal_eval of a config value cannot make.
    """
    out: list[str] = []

    def walk(value, path: str) -> None:
        if callable(value):
            out.append(f"python code: {path}")
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if key in CODE_KEYS and item not in (None, "", "none"):
                    out.append(f"python code: {path}.{key}")
                walk(item, f"{path}.{key}")
            return
        if isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                walk(item, f"{path}[{i}]")
            return
        if isinstance(value, str) and ADDRESS.search(value):
            out.append(f"object address: {path}")
        elif not literal_ok(value):
            out.append(f"not a literal: {path}")

    for i, value in enumerate(inputs):
        if value is not None:
            walk(value, f"input{i}")
    return out
