# Parts of this file are ported from sqlfluff 4.4.0, test/conftest.py
# (process_struct, load_yaml) and test/dialects/dialects_test.py
# (test__dialect__base_parse_struct).
# Source: https://github.com/sqlfluff/sqlfluff
# Copyright (c) 2018-2026 Alan Cruickshank. MIT License.
# See THIRD_PARTY.md for the full attribution.
"""Compare parse trees as sqlfluff does in its own test suite."""

from pathlib import Path
from typing import Any

import yaml

_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

Struct = tuple | str | None


def process_struct(obj: Any) -> Struct:
    """Process a nested dict or dict-like into a check tuple."""
    if isinstance(obj, dict):
        return tuple((k, process_struct(obj[k])) for k in obj)
    elif isinstance(obj, list):
        if not len(obj):
            return tuple()
        if isinstance(obj[0], dict):
            buff = [process_struct(elem) for elem in obj]
            if any(len(elem) > 1 for elem in buff):
                raise ValueError(f"Not sure how to deal with multi key dict: {buff!r}")
            return tuple(elem[0] for elem in buff)
        else:
            raise TypeError(f"Did not expect a list of {type(obj[0])}: {obj[0]!r}")
    elif isinstance(obj, (str, int, float)):
        return str(obj)
    elif obj is None:
        return None
    else:
        raise TypeError(f"Not sure how to deal with type {type(obj)}: {obj!r}")


def record_to_tuple(record: Any) -> tuple | None:
    """Return the root (name, children) tuple of a parse record, or None."""
    processed = process_struct(record)
    if processed:
        return processed[0]
    return None


def load_yaml(path: Path) -> tuple[str | None, tuple | None]:
    """Load a YAML parse fixture. Return (hash, root tuple)."""
    obj = yaml.load(path.read_text(encoding="utf8"), Loader=_Loader)
    _hash = None
    if obj:
        _hash = obj.pop("_hash", None)
    processed = process_struct(obj)
    if processed:
        return _hash, processed[0]
    return None, None


def trees_match(expected: tuple | None, actual: tuple | None) -> bool:
    """Return True if the parse trees are equal.

    As in sqlfluff, two trees with no children are equal. Thus `file: null`
    and `file: []` are equal. If the tool gave no tree, the result is equal
    only if the fixture also has no tree.
    """
    if actual is None or expected is None:
        return actual == expected
    if actual[1] or expected[1]:
        return actual == expected
    return True


def has_node(record: Any, name: str) -> bool:
    """Return True if a node with this name is in the parse record."""
    stack = [record]
    while stack:
        obj = stack.pop()
        if isinstance(obj, dict):
            if name in obj:
                return True
            stack.extend(obj.values())
        elif isinstance(obj, list):
            stack.extend(obj)
    return False
