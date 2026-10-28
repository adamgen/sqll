"""The names that the Jinja code of a templated corpus file reads
(docs/decisions/s9-corpus.md, "Templated files").

The selection takes a templated file only if scan() finds no problem: the
file has a Jinja tag, each tag is complete, each statement is one of
STATEMENTS, and each name that the code reads is a dbt builtin of the pinned
sqlfluff, a Jinja global (GLOBALS), or a name that the file sets before in
the same block or an outer block (set, for, macro, with). Then the render
needs no input other than the file and the jinja settings: no template
variable, macro file, or library.

The scan uses only the file text, not a tool result. It does not use a Jinja
library: the harness does not depend on one. Text outside the tags is not
read. A name is not a read if it is an attribute (after "."), a filter
(after "|" or "filter"), a test (after "is" or "is not"), or a keyword
argument of a call.
"""

import ast
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from ..paths import SQLFLUFF_ROOT

_DBT_FILE = (
    SQLFLUFF_ROOT / "src" / "sqlfluff" / "core" / "templaters" / "builtins" / "dbt.py"
)
# The globals of a default Jinja environment, and the names that Jinja gives
# in a for loop (loop) and in a macro (varargs, kwargs).
GLOBALS = frozenset(
    {"range", "dict", "lipsum", "cycler", "joiner", "namespace"}
    | {"loop", "varargs", "kwargs"}
)
KEYWORDS = frozenset(
    {"and", "or", "not", "in", "is", "if", "else", "recursive"}
    | {"true", "false", "none", "True", "False", "None"}
)
# The statements that the rule accepts, and their end statements. Others
# (import, from, include, extends, call, block, ...) need another template
# or have their own scopes, so the rule refuses them.
STATEMENTS = frozenset(
    {"if", "elif", "else", "endif", "for", "endfor", "set", "endset"}
    | {"macro", "endmacro", "with", "endwith", "filter", "endfilter"}
    | {"do", "break", "continue", "raw"}
)

_TAG = re.compile(r"\{\{|\{%|\{#")
_END_RAW = re.compile(r"\{%[-+]?\s*endraw\s*[-+]?%\}")
_TOKEN = re.compile(
    r"""
    (?P<space>\s+)
  | (?P<string>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<number>\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\*\*|//|==|!=|>=|<=|[-+*/%~<>=.,:|()\[\]{}])
    """,
    re.VERBOSE | re.DOTALL,
)
_CLOSE = {")": "(", "]": "[", "}": "{"}


class ScanError(ValueError):
    """The text is not Jinja code that the rule can read."""


@cache
def dbt_builtins(path: Path = _DBT_FILE) -> frozenset[str]:
    """Return the names of DBT_BUILTINS in the dbt builtins file of the
    pinned sqlfluff. The file is read as text, not imported."""
    tree = ast.parse(path.read_text(encoding="utf8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and [getattr(t, "id", None) for t in node.targets] == ["DBT_BUILTINS"]
            and isinstance(node.value, ast.Dict)
        ):
            names = [getattr(k, "value", None) for k in node.value.keys]
            if names and all(isinstance(n, str) for n in names):
                return frozenset(names)
    raise ScanError(f"no DBT_BUILTINS dict in {path}")


def allowed() -> frozenset[str]:
    """Return the names that a file can read with no other render input."""
    return dbt_builtins() | GLOBALS


@dataclass
class Scan:
    """The result of scan(). reads: each allowed name that the file reads
    and does not set. unknown: each other name that it reads before it sets
    it. problems: why the rule cannot read the file."""

    tags: int = 0
    reads: set[str] = field(default_factory=set)
    unknown: set[str] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.tags > 0 and not self.unknown and not self.problems

    def reason(self) -> str:
        """Return why the file is not taken (empty if ok)."""
        parts = list(self.problems)
        if self.unknown:
            parts.append("it reads " + ", ".join(sorted(self.unknown)))
        if self.tags == 0 and not parts:
            parts.append("no Jinja tag")
        return "; ".join(parts)


def _tokens(text: str, pos: int, end: str) -> tuple[list, int]:
    """Return the tokens (kind, value, bracket depth) of the code of a tag
    from pos to its end marker (end: "}}" or "%}", with an optional "-" or
    "+" before it), and the position after the marker. The marker ends the
    tag only outside of brackets."""
    tokens: list[tuple[str, str, int]] = []
    stack: list[str] = []
    while True:
        if pos >= len(text):
            raise ScanError(f"a tag has no {end!r}")
        if not stack:
            for marker in (end, "-" + end, "+" + end):
                if text.startswith(marker, pos):
                    return tokens, pos + len(marker)
        m = _TOKEN.match(text, pos)
        if m is None and text[pos] in "'\"":
            raise ScanError("a string in a tag has no end")
        if m is None:
            raise ScanError(f"unknown character {text[pos]!r} in a tag")
        kind = m.lastgroup
        value = m.group()
        pos = m.end()
        if kind == "space":
            continue
        if kind == "op" and value in "([{":
            stack.append(value)
        elif kind == "op" and value in _CLOSE:
            if not stack or stack.pop() != _CLOSE[value]:
                raise ScanError(f"unbalanced {value!r} in a tag")
        tokens.append((kind, value, len(stack)))


def _is_read(tokens: list, i: int) -> bool:
    """Return True if the name token i is a read of a variable."""
    value = tokens[i][1]
    if value in KEYWORDS:
        return False
    prev = tokens[i - 1][1] if i > 0 else None
    if prev in (".", "|"):
        return False
    if prev == "is" or (prev == "not" and i > 1 and tokens[i - 2][1] == "is"):
        return False
    nxt = tokens[i + 1][1] if i + 1 < len(tokens) else None
    # A keyword argument: "name=" in a call (depth > 0). "==" is one token.
    return not (nxt == "=" and tokens[i][2] > 0)


# The block statements and their end statements. A name that a block sets
# is set only in the block (as Jinja finds the undeclared names of a
# template): a branch of an if block can be false, and a for or macro block
# has its own scope.
BLOCKS = {
    "if": "endif",
    "for": "endfor",
    "macro": "endmacro",
    "with": "endwith",
    "filter": "endfilter",
    "set": "endset",
}
ENDS = {end: start for start, end in BLOCKS.items()}


@dataclass
class _Block:
    word: str
    names: set[str] = field(default_factory=set)
    # A set block ("{% set x %}...{% endset %}") sets x after its end.
    sets: list[str] = field(default_factory=list)


class _Scanner:
    def __init__(self, allowed_names: frozenset[str]) -> None:
        self.allowed = allowed_names
        self.blocks = [_Block("file")]
        self.result = Scan()

    def bound(self, name: str) -> bool:
        return any(name in b.names for b in self.blocks)

    def bind(self, names) -> None:
        self.blocks[-1].names.update(names)

    def push(self, word: str) -> _Block:
        self.blocks.append(_Block(word))
        return self.blocks[-1]

    def pop(self, end: str) -> _Block:
        if len(self.blocks) == 1 or self.blocks[-1].word != ENDS[end]:
            raise ScanError(f"{end!r} does not end the open block")
        return self.blocks.pop()

    def read(self, tokens: list) -> None:
        for i, (kind, value, _) in enumerate(tokens):
            if kind == "name" and _is_read(tokens, i):
                self.use(value)

    def use(self, name: str) -> None:
        if self.bound(name):
            return
        if name in self.allowed:
            self.result.reads.add(name)
        else:
            self.result.unknown.add(name)

    def statement(self, tokens: list) -> None:
        if not tokens or tokens[0][0] != "name":
            raise ScanError("a statement tag has no statement name")
        word = tokens[0][1]
        rest = tokens[1:]
        if word not in STATEMENTS:
            self.result.problems.append(f"statement {word!r}")
            return
        if word in ENDS:
            block = self.pop(word)
            self.bind(block.sets)
        elif word in ("elif", "else"):
            # A new branch of an if block (or the else of a for block).
            opened = self.blocks[-1].word
            if opened not in ("if", "for") or (word == "elif" and opened != "if"):
                raise ScanError(f"{word!r} is not in an if or for block")
            self.blocks.pop()
            self.read(rest)
            self.push(opened)
        elif word == "set":
            self.set_(rest)
        elif word == "for":
            self.for_(rest)
        elif word == "macro":
            self.macro(rest)
        elif word == "with":
            self.with_(rest)
        elif word == "filter":
            # The first name is the filter; then its arguments.
            self.read(rest[1:] if rest and rest[0][0] == "name" else rest)
            self.push(word)
        elif word == "if":
            self.read(rest)
            self.push(word)
        else:
            self.read(rest)

    def set_(self, rest: list) -> None:
        split = next((i for i, t in enumerate(rest) if t[1] == "=" and t[2] == 0), None)
        targets = rest if split is None else rest[:split]
        if split is not None:
            self.read(rest[split + 1 :])
        names = []
        for i, (kind, value, _) in enumerate(targets):
            if kind != "name" or (i > 0 and targets[i - 1][1] == "."):
                continue
            if i + 1 < len(targets) and targets[i + 1][1] == ".":
                self.use(value)  # A namespace attribute: the namespace is read.
            else:
                names.append(value)
        if split is None:
            self.push("set").sets.extend(names)
        else:
            self.bind(names)

    def for_(self, rest: list) -> None:
        split = next(
            (i for i, t in enumerate(rest) if t[1] == "in" and t[2] == 0), None
        )
        if split is None:
            raise ScanError("a for statement has no 'in'")
        tail = rest[split + 1 :]
        # "for x in items if test": the test reads the loop names.
        cut = next(
            (i for i, t in enumerate(tail) if t[1] == "if" and t[2] == 0), len(tail)
        )
        self.read(tail[:cut])
        self.push("for")
        self.bind(v for k, v, _ in rest[:split] if k == "name")
        self.read(tail[cut:])

    def macro(self, rest: list) -> None:
        if not rest or rest[0][0] != "name":
            raise ScanError("a macro has no name")
        self.bind([rest[0][1]])
        params = rest[1:]
        names = []
        defaults = []
        for i, (kind, value, depth) in enumerate(params):
            prev = params[i - 1][1] if i > 0 else None
            if kind == "name" and depth == 1 and prev in ("(", ","):
                names.append(value)
            else:
                defaults.append(params[i])
        self.read(defaults)
        self.push("macro")
        self.bind(names)

    def with_(self, rest: list) -> None:
        """Read "a = expr, b = expr": each expr, then set each name in the
        block."""
        names = []
        expr: list = []
        for i, token in enumerate(rest):
            kind, value, depth = token
            nxt = rest[i + 1][1] if i + 1 < len(rest) else None
            start = i == 0 or (rest[i - 1][1] == "," and rest[i - 1][2] == 0)
            if kind == "name" and depth == 0 and start and nxt == "=":
                names.append(value)
            elif value == "=" and depth == 0:
                continue
            else:
                expr.append(token)
        self.read(expr)
        self.push("with")
        self.bind(names)

    def finish(self) -> None:
        if len(self.blocks) > 1:
            raise ScanError(f"the {self.blocks[-1].word!r} block has no end")


def scan(text: str, allowed_names: frozenset[str] | None = None) -> Scan:
    """Return the names that the Jinja code of text reads, and each problem."""
    s = _Scanner(allowed() if allowed_names is None else allowed_names)
    pos = 0
    try:
        while True:
            m = _TAG.search(text, pos)
            if m is None:
                break
            opener = m.group()
            pos = m.end()
            if opener == "{#":
                close = text.find("#}", pos)
                if close < 0:
                    raise ScanError("a comment has no '#}'")
                pos = close + 2
                continue
            s.result.tags += 1
            if text.startswith(("-", "+"), pos):
                pos += 1
            if opener == "{{":
                tokens, pos = _tokens(text, pos, "}}")
                s.read(tokens)
                continue
            tokens, pos = _tokens(text, pos, "%}")
            if tokens and tokens[0][1] == "raw":
                end = _END_RAW.search(text, pos)
                if end is None:
                    raise ScanError("a raw block has no endraw")
                pos = end.end()
                continue
            s.statement(tokens)
        s.finish()
    except ScanError as exc:
        s.result.problems.append(str(exc))
    return s.result
