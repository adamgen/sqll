# Parts of this file are a port of sqlfluff 4.4.0 code: test/conftest.py
# (process_struct, load_yaml) and test/dialects/dialects_test.py
# (test__dialect__base_parse_struct).
# Source: https://github.com/sqlfluff/sqlfluff
# Copyright (c) 2018-2026 Alan Cruickshank. MIT License.
# See THIRD_PARTY.md for the full attribution.
"""Compare parse trees as sqlfluff does in its own test suite."""

from pathlib import Path
from typing import Any

import yaml

# sqlfluff uses yaml.CLoader. CSafeLoader has the same parser and the same
# scalar resolvers, so it gives the same data for plain YAML. It does not
# construct Python objects from tags such as !!python/object. A fixture with
# such a tag gives an error, not a different tree. tests/test_compare.py
# proves that both loaders give equal data for all dialect fixtures.
# SafeLoader is the pure-Python fallback when libyaml is not available.
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


# The keys of the source position that "sqlfluff parse -m" adds to each
# segment record (TemplatedFile.source_position_dict_from_slice).
POSITION_KEYS = frozenset(
    {
        "start_line_no",
        "start_line_pos",
        "start_file_pos",
        "end_line_no",
        "end_line_pos",
        "end_file_pos",
    }
)


def strip_positions(record: Any) -> Any:
    """Return a parse record with no position keys.

    With -m, "sqlfluff parse" adds the source position of each segment to
    its record, and to the record of its parent if it is the only child.
    The value of a position key is an int. The value of a segment is a
    string, a dict, a list, or null. A position key with another value is
    an error, because the harness cannot know if it is a segment.
    """
    if isinstance(record, dict):
        out = {}
        for key, value in record.items():
            if key in POSITION_KEYS:
                if type(value) is not int:
                    raise ValueError(f"position key {key!r} has the value {value!r}")
                continue
            out[key] = strip_positions(value)
        return out
    if isinstance(record, list):
        return [strip_positions(item) for item in record]
    return record


def record_to_test_tuple(record: Any) -> tuple:
    """Return the root tuple of a parse record, as BaseSegment.to_tuple gives it.

    The parse record of the CLI (as_record) has null for a segment with no
    children to show. to_tuple has an empty tuple for it, and never None.
    Thus null becomes an empty tuple. A raw segment has a string, also an
    empty string.
    """
    if not isinstance(record, dict) or len(record) != 1:
        raise ValueError("the root record does not have exactly one segment")
    return process_struct(_nulls_to_lists(record))[0]


def _nulls_to_lists(record: Any) -> Any:
    if isinstance(record, dict):
        return {k: [] if v is None else _nulls_to_lists(v) for k, v in record.items()}
    if isinstance(record, list):
        return [_nulls_to_lists(item) for item in record]
    return record


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
