# The filter and the record format in this file are a port of sqlfluff 4.4.0
# code: src/sqlfluff/core/parser/segments/base.py (BaseSegment.to_tuple,
# BaseSegment.structural_simplify, BaseSegment.is_code) and the is_code and
# is_meta values of the segment classes in src/sqlfluff/core/parser/segments/
# and src/sqlfluff/dialects/. Copyright (c) 2018-2026 Alan Cruickshank.
# MIT License. See THIRD_PARTY.md.
"""Make the code-only parse record ("parse -c") from a full parse record.

sqruff has no code-only output. The harness applies this filter to its full
tree. The "code_only" suite checks the filter with sqlfluff on all dialect
cases. See harness/sqruff.md.

A record is a segment as "parse -f json" gives it: {type: value}. value is a
string (a segment with no children), null or [] (no children to show), a
dict (children with different types), or a list of one-key dicts. sqruff
always gives a list. The filter does not accept position keys: remove them
first (compare.strip_positions).
"""

import re
from typing import Any

# The types of the raw segments that are not code (_is_code = False) in
# sqlfluff 4.4.0: CommentSegment, WhitespaceSegment, and NewlineSegment, with
# the type that each lexer and parser of each dialect gives them.
NON_CODE_TYPES = frozenset(
    {
        "accept_command",
        "bare_magic_sql",
        "block_comment",
        "comment",
        "inline_comment",
        "newline",
        "notebook_start",
        "notebook_start_bare_magic_sql",
        "obevo_annotation",
        "prompt_command",
        "remark_command",
        "whitespace",
    }
)
# The types of the meta segments (is_meta = True, not code). "parse" shows
# them only with -m.
META_TYPES = frozenset(
    {"meta", "end_of_file", "template_loop", "indent", "dedent", "placeholder"}
)
# The postgres type "meta_command" is not code if the "meta_command" lexer
# (CommentSegment) made it, and is code if MetaCommandQueryBufferSegment
# (SymbolSegment) made it. The first lexer matches each text that starts with
# this pattern, so only the second one gives the other texts.
_META_COMMAND = "meta_command"
_COMMENT_META_COMMAND = re.compile(r"\\(?!gset|gexec|crosstabview\b|copy\b|set\b)")

# A node is (type, value). value is a str for a segment with no children,
# else a tuple of nodes.
Node = tuple[str, "str | tuple[Node, ...]"]


def to_node(record: Any) -> Node:
    """Return the node of a record with exactly one segment."""
    if not isinstance(record, dict) or len(record) != 1:
        raise ValueError(f"a segment record must have one key: {record!r}")
    ((key, value),) = record.items()
    if not isinstance(key, str):
        raise ValueError(f"segment type {key!r} is not a string")
    if isinstance(value, str):
        return (key, value)
    if value is None:
        return (key, ())
    if isinstance(value, dict):
        return (key, tuple(to_node({k: v}) for k, v in value.items()))
    if isinstance(value, list):
        return (key, tuple(to_node(item) for item in value))
    raise ValueError(f"segment {key!r} has a value of type {type(value).__name__}")


def simplify(node: Node) -> dict[str, Any]:
    """Return the record of a node as "sqlfluff parse" gives it
    (structural_simplify): null for no children, a dict if the types of the
    children are all different, else a list of one-key dicts."""
    key, value = node
    if isinstance(value, str):
        return {key: value}
    if not value:
        return {key: None}
    contents = [simplify(child) for child in value]
    keys = [k for item in contents for k in item]
    if len(set(keys)) != len(keys):
        return {key: contents}
    return {key: {k: v for item in contents for k, v in item.items()}}


def is_meta(node: Node) -> bool:
    return isinstance(node[1], str) and node[0] in META_TYPES


def is_code(node: Node) -> bool:
    """BaseSegment.is_code: a raw segment is code if its class is code; any
    other segment is code if one of its children is code."""
    key, value = node
    if isinstance(value, str):
        if key in NON_CODE_TYPES or key in META_TYPES:
            return False
        if key == _META_COMMAND:
            return not _COMMENT_META_COMMAND.match(value)
        return True
    return any(is_code(child) for child in value)


def code_only_node(node: Node) -> Node:
    """to_tuple(code_only=True, show_raw=True): keep only the children that
    are code and not meta, at each level."""
    key, value = node
    if isinstance(value, str):
        return node
    return (
        key,
        tuple(
            code_only_node(child)
            for child in value
            if is_code(child) and not is_meta(child)
        ),
    )


def code_only_record(record: Any) -> dict[str, Any]:
    """Return the "parse -c" record of a full parse record."""
    return simplify(code_only_node(to_node(record)))


def sqlfluff_record(record: Any) -> dict[str, Any]:
    """Return a record in the form of "sqlfluff parse": the same tree."""
    return simplify(to_node(record))
