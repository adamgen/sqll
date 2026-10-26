"""S3 phase A, task T3: the classes of the sqruff parse tree mismatches.

Commands. Run them with the harness Python:

    uv run --frozen --project harness python scripts/s3/sqruff_trees.py collect
    uv run --frozen --project harness python scripts/s3/sqruff_trees.py show ID...
    uv run --frozen --project harness python scripts/s3/sqruff_trees.py build [--check]

"collect" runs sqruff through the harness adapter on each case of
tree_cases() (the sqruff dialect failures and the templater "tree differs"
failures of known_failures/sqruff.txt), compares the tree with the fixture
tree, and writes the differences of each case to HUNKS_FILE. "show" prints
the changes of the leaves of a case (leaf_changes), for the hand check. The
hand check is in HANDCHECK_FILE; select_sample gives its cases. "build"
reads only committed files (HUNKS_FILE, HANDCHECK_FILE, the T2 files, and
known_failures/sqruff.txt) and writes OUT_FILE. With --check it writes
nothing and fails if OUT_FILE is not the new text.

Each command stops with exit code 1 if the data do not agree (DataError).

The comparison. The leaves of the 2 trees give the same text, or nearly the
same text. The script puts each node of the sqruff tree on the character
positions of the fixture tree (difflib alignment of the leaf texts). Then it
compares leaves by their span, and nodes by their code span (the span from
the first to the last code leaf). Each difference is a hunk with one class
(CLASSES) and one group key. The group key names the segment type and its
parent type in the tree that has the node, thus the grammar rule that makes
the difference. A sqruff "unparsable" node absorbs the other hunks in its
region (CLASSES): they follow from the parse failure.
"""

import argparse
import concurrent.futures
import difflib
import hashlib
import json
import sys
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqll_harness import known_failures
from sqll_harness.adapters.base import Unsupported
from sqll_harness.adapters.sqruff import SqruffAdapter
from sqll_harness.code_only import META_TYPES, NON_CODE_TYPES
from sqll_harness.compare import (
    load_yaml,
    record_to_test_tuple,
    record_to_tuple,
    strip_positions,
    trees_match,
)
from sqll_harness.paths import SQLFLUFF_ROOT, sqlfluff_ref
from sqll_harness.suites import dialects, templater

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "s3"
HUNKS_FILE = RESULTS / "sqruff-tree-hunks.json"
HANDCHECK_FILE = RESULTS / "sqruff-tree-handcheck.json"
OUT_FILE = RESULTS / "sqruff-tree-diffs.json"
CASES_FILE = RESULTS / "sqruff-cases.json"
S1_BY_BASE = RESULTS / "s1-by-base.json"
KNOWN_FAILURES = ROOT / "known_failures"

SQRUFF_VERSION = "0.41.0"
TREE_DIFFERS = "tree differs"
UNSUPPORTED_DIALECT = "unsupported: dialect"
DIALECT_FAILURES = 758
TEMPLATER_TREE_FAILURES = 5
NO_UNPARSABLE_FAILURES = 142
TOP = (10, 20, 50)
SAMPLE_SIZE = 60
SAMPLE_PER_CLASS = 3

COLLECT_COMMAND = (
    "uv run --frozen --project harness python scripts/s3/sqruff_trees.py collect"
)
BUILD_COMMAND = (
    "uv run --frozen --project harness python scripts/s3/sqruff_trees.py build"
)

# The classes of a hunk. The order is the precedence of the primary class of
# a case: a class earlier in the list is more general.
CLASSES = {
    "unsupported_dialect": "sqruff does not have the dialect, thus it gives no tree.",
    "unparsable": (
        "sqruff gives an unparsable node. Its region is its span and the "
        "statement of sqlfluff where it starts. The other hunks in the region "
        "are not counted: they follow from the parse failure. A node that "
        "holds the region, or that sqruff ends in it, is compared without "
        "the region."
    ),
    "leaf_text": (
        "The text of the leaves is different: a text is in a leaf of one tree "
        "and not in the other tree (for example a newline that one tool puts "
        "in a code leaf)."
    ),
    "token_split": (
        "The text is the same, but the leaf boundaries are different (the "
        "lexers make different tokens)."
    ),
    "nesting": (
        "A node of one tree crosses a node of the other tree: different "
        "nesting of the same leaves."
    ),
    "missing_wrapper": (
        "A sqlfluff node that sqruff does not have. It does not cross a sqruff "
        "node, thus sqruff can add it as a wrapper."
    ),
    "extra_wrapper": (
        "A sqruff node that sqlfluff does not have. It does not cross a sqlfluff node."
    ),
    "renamed": "A node with the same code span has another segment type.",
    "keyword_vs_identifier": (
        "A leaf with the same span is a keyword in one tree and an identifier "
        "in the other tree."
    ),
    "leaf_type": "A leaf with the same span has another type.",
    "non_code_placement": (
        "The same node, but a whitespace, newline, or comment leaf at its edge "
        "is in another node."
    ),
    "meta": (
        "The leaves with no text (indent, dedent, and other meta leaves) at a "
        "position are different."
    ),
    "other": "The trees are different, but no other class applies.",
}
NON_CODE = NON_CODE_TYPES | META_TYPES
GROUP_KEY_TYPES = 6


class DataError(Exception):
    """The inputs do not agree."""


# The cases.


@dataclass(frozen=True)
class Case:
    id: str
    suite: str
    sql: Path
    yml: Path
    dialect: str | None
    code_only: bool
    include_meta: bool
    extra_config: dict | None = None


def tree_cases() -> list[Case]:
    """Return the cases of T3: the dialect failures and the templater cases
    with "tree differs" of known_failures/sqruff.txt. Raise DataError if the
    counts are not those of the T3 scope."""
    known = known_failures.load(KNOWN_FAILURES, "sqruff")
    out = []
    for c in dialects.discover(SQLFLUFF_ROOT):
        if c.id in known:
            out.append(
                Case(
                    c.id,
                    "dialects",
                    c.sql,
                    c.yml,
                    c.dialect,
                    c.code_only,
                    False,
                    c.extra_config,
                )
            )
    for c in templater.discover(SQLFLUFF_ROOT):
        if known.get(c.id) == TREE_DIFFERS:
            out.append(
                Case(c.id, "templater", c.sql, c.yml, None, c.code_only, c.include_meta)
            )
    errors = []
    in_suite = Counter(c.suite for c in out)
    if in_suite["dialects"] != DIALECT_FAILURES:
        errors.append(
            f"{in_suite['dialects']} dialect failures, not {DIALECT_FAILURES}"
        )
    if in_suite["templater"] != TEMPLATER_TREE_FAILURES:
        errors.append(
            f"{in_suite['templater']} templater tree failures, "
            f"not {TEMPLATER_TREE_FAILURES}"
        )
    for case_id, reason in known.items():
        suite = case_id.split("/", 1)[0]
        prefix = known_failures.reason_prefix(reason)
        if suite == "dialects" and prefix not in (TREE_DIFFERS, UNSUPPORTED_DIALECT):
            errors.append(f"{case_id}: reason {reason!r}")
    if errors:
        raise DataError("; ".join(errors))
    return out


# Trees. A tree is (type, value): value is a str (a leaf), or a tuple of
# trees, or None (no children).


@dataclass
class Flat:
    """The leaves and nodes of a tree, with character spans."""

    text: str = ""
    # Each element: [start, end, type, parent index or -1, is leaf].
    items: list[list] = field(default_factory=list)
    # The code span of each node that has a code leaf.
    code: dict[int, tuple[int, int]] = field(default_factory=dict)

    def path(self, i: int) -> list[str]:
        out = []
        while i >= 0:
            out.append(self.items[i][2])
            i = self.items[i][3]
        return out[::-1]

    def parent_type(self, i: int) -> str:
        p = self.items[i][3]
        return self.items[p][2] if p >= 0 else "-"


def flatten(tree: tuple) -> Flat:
    flat = Flat()
    parts: list[str] = []
    pos = 0

    def walk(node: tuple, parent: int) -> tuple[int, int] | None:
        nonlocal pos
        name, value = node
        index = len(flat.items)
        if isinstance(value, str):
            flat.items.append([pos, pos + len(value), name, parent, True])
            parts.append(value)
            start = pos
            pos += len(value)
            if name in NON_CODE or not value:
                return None
            return (start, pos)
        flat.items.append([pos, pos, name, parent, False])
        span = None
        for child in value or ():
            got = walk(child, index)
            if got:
                span = got if span is None else (span[0], got[1])
        flat.items[index][1] = pos
        if span:
            flat.code[index] = span
        return span

    walk(tree, -1)
    flat.text = "".join(parts)
    return flat


def first_path(expected: tuple, actual: tuple) -> list[str]:
    """Return the path of the first node, in pre-order, where the trees are
    different: another type, another leaf text, or another child count."""
    path: list[str] = []
    e, a = expected, actual
    while True:
        if e[0] != a[0]:
            return path + [e[0]]
        path.append(e[0])
        ev, av = e[1], a[1]
        if isinstance(ev, str) or isinstance(av, str):
            return path
        ev, av = ev or (), av or ()
        nxt = next(((x, y) for x, y in zip(ev, av, strict=False) if x != y), None)
        if nxt is None:
            return path
        e, a = nxt


class _PositionMap:
    """Map a position in the text of the sqruff tree to the fixture text.
    Where the fixture has text that the sqruff tree does not have, a start
    goes after that text and an end goes before it."""

    def __init__(self, expected: str, actual: str) -> None:
        sm = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
        self.ops = sm.get_opcodes()
        self.j1 = [op[3] for op in self.ops]
        self.j2 = [op[4] for op in self.ops]

    def start(self, b: int) -> int:
        tag, i1, i2, j1, _ = self.ops[max(0, bisect_right(self.j1, b) - 1)]
        if tag == "equal":
            return i1 + (b - j1)
        return i1 if b == j1 else i2

    def end(self, b: int) -> int:
        tag, i1, i2, j1, j2 = self.ops[min(len(self.ops) - 1, bisect_left(self.j2, b))]
        if tag == "equal":
            return i1 + (b - j1)
        return i2 if b == j2 else i1

    def regions(self):
        for tag, i1, i2, j1, j2 in self.ops:
            if tag != "equal":
                yield i1, i2, j1, j2


def _types(flat: Flat, idx: list[int]) -> str:
    names = [flat.items[i][2] for i in idx]
    if len(names) > GROUP_KEY_TYPES:
        names = names[:GROUP_KEY_TYPES] + ["..."]
    return " ".join(names) or "-"


def _is_identifier(t: str) -> bool:
    return t.endswith("identifier")


def _crosses(span: tuple[int, int], others: list[tuple[int, int]]) -> bool:
    s, e = span
    return any(o[0] < s < o[1] < e or s < o[0] < e < o[1] for o in others)


def diff(expected: tuple, actual: tuple) -> dict:
    """Return {first_path, hunks} for 2 trees that are not equal. hunks: see
    merge_hunks. A sqlfluff path is the types from the root to the fixture
    node of the hunk: the node itself, or the deepest node that holds it."""
    ef, af = flatten(expected), flatten(actual)
    pmap = _PositionMap(ef.text, af.text)
    # Spans of the sqruff tree on the fixture positions.
    a_raw = [it[:2] for it in af.items]
    a_items = [[pmap.start(s), pmap.end(e), *rest] for (s, e, *rest) in af.items]
    a_code = {i: (pmap.start(s), pmap.end(e)) for i, (s, e) in af.code.items()}
    hunks: list[list] = []

    def anchor(span: tuple[int, int]) -> int:
        """The deepest fixture node whose code span holds span."""
        best, depth = 0, -1
        for i, (s, e) in ef.code.items():
            if s <= span[0] and span[1] <= e:
                d = len(ef.path(i))
                if d > depth:
                    best, depth = i, d
        return best

    def add(cls: str, key: str, span: tuple[int, int], e_index: int | None = None):
        if e_index is None:
            e_index = anchor(span)
        hunks.append(
            [cls, f"{cls}: {key}", span[0], span[1], "/".join(ef.path(e_index))]
        )

    # Unparsable nodes of sqruff. Each one absorbs the hunks in its region.
    absorbed: list[tuple[int, int]] = []
    for i, it in enumerate(a_items):
        if it[2] == "unparsable" and not it[4]:
            span = a_code.get(i, (it[0], it[1]))
            name, region = _unparsable_anchor(ef, span)
            absorbed.append(region)
            add("unparsable", f"in {name}", span)

    def in_unparsable(span: tuple[int, int]) -> bool:
        """True if span is in a region, or crosses its edge."""
        s, e = span
        for rs, re in absorbed:
            if rs <= s and e <= re or s < re and rs < e and not (s <= rs and re <= e):
                return True
        return False

    def clip(p: int) -> int:
        """Move a position in a region to the start of the region. Thus a
        node that holds a region and a node that sqruff ends in it have the
        same span."""
        for rs, re in absorbed:
            if rs < p <= re:
                return rs
        return p

    # Text.
    text_regions = []
    for i1, i2, j1, j2 in pmap.regions():
        text_regions.append((i1, i2))
        if in_unparsable((i1, i2)):
            continue
        e_idx = [
            i for i, it in enumerate(ef.items) if it[4] and it[0] <= i2 and i1 <= it[1]
        ]
        a_idx = [
            i for i, (s, e) in enumerate(a_raw) if a_items[i][4] and s <= j2 and j1 <= e
        ]
        e_idx = [i for i in e_idx if ef.items[i][1] > ef.items[i][0]] or e_idx
        a_idx = [i for i in a_idx if a_raw[i][1] > a_raw[i][0]] or a_idx
        add("leaf_text", f"{_types(ef, e_idx)} -> {_types(af, a_idx)}", (i1, i2))

    def in_text(span):
        s, e = span
        return any(
            s < te and ts < e or ts == te and s <= ts <= e for ts, te in text_regions
        )

    # Leaves with text.
    e_leaves = {
        (it[0], it[1]): i for i, it in enumerate(ef.items) if it[4] and it[1] > it[0]
    }
    a_leaves = {
        (it[0], it[1]): i for i, it in enumerate(a_items) if it[4] and it[1] > it[0]
    }
    split = []
    for span in sorted(set(e_leaves) | set(a_leaves)):
        if in_unparsable(span) or in_text(span):
            continue
        if span in e_leaves and span in a_leaves:
            et = ef.items[e_leaves[span]][2]
            at = a_items[a_leaves[span]][2]
            if et != at:
                kw = "keyword" in (et, at) and (
                    _is_identifier(et) or _is_identifier(at)
                )
                cls = "keyword_vs_identifier" if kw else "leaf_type"
                i = e_leaves[span]
                add(cls, f"{et} -> {at} in {ef.parent_type(i)}", span, i)
        else:
            split.append(span)
    # Merge the split leaves into regions.
    split_regions: list[list[int]] = []
    for s, e in sorted(split):
        if split_regions and s < split_regions[-1][1]:
            split_regions[-1][1] = max(split_regions[-1][1], e)
        else:
            split_regions.append([s, e])
    for s, e in split_regions:
        e_idx = [i for sp, i in sorted(e_leaves.items()) if s <= sp[0] and sp[1] <= e]
        a_idx = [i for sp, i in sorted(a_leaves.items()) if s <= sp[0] and sp[1] <= e]
        add("token_split", f"{_types(ef, e_idx)} -> {_types(af, a_idx)}", (s, e))

    # Leaves with no text (meta leaves), by position.
    e_meta: dict[int, list[str]] = {}
    a_meta: dict[int, list[str]] = {}
    e_at: dict[int, int] = {}
    for items, meta in ((ef.items, e_meta), (a_items, a_meta)):
        for i, it in enumerate(items):
            if it[4] and it[0] == it[1]:
                meta.setdefault(it[0], []).append(it[2])
                if items is ef.items:
                    e_at.setdefault(it[0], i)
    for p in sorted(set(e_meta) | set(a_meta)):
        et, at = sorted(e_meta.get(p, [])), sorted(a_meta.get(p, []))
        if et != at and not in_unparsable((p, p)):
            key = f"{' '.join(et) or '-'} -> {' '.join(at) or '-'}"
            add("meta", key, (p, p), e_at.get(p))

    # Nodes, by code span. Nodes with no code leaf: by span. A node in an
    # unparsable region is not compared. The other spans are clipped.
    def chains(items, code):
        out: dict[tuple, list[int]] = {}
        for i, it in enumerate(items):
            if it[4]:
                continue
            span = code.get(i) or (it[0], it[1])
            if any(rs <= span[0] and span[1] <= re for rs, re in absorbed):
                continue
            key = (clip(span[0]), clip(span[1]))
            if i not in code:
                key = ("nc", *key)
            out.setdefault(key, []).append(i)
        return out

    e_ch = chains(ef.items, ef.code)
    a_ch = chains(a_items, a_code)
    e_spans = [k for k in e_ch if k[0] != "nc"]
    a_spans = [k for k in a_ch if k[0] != "nc"]

    def a_parent_type(i: int) -> str:
        p = a_items[i][3]
        return a_items[p][2] if p >= 0 else "-"

    for key in sorted(set(e_ch) | set(a_ch), key=str):
        span = key[1:] if key[0] == "nc" else key
        ei, ai = e_ch.get(key, []), a_ch.get(key, [])
        et = [ef.items[i][2] for i in ei]
        at = [a_items[i][2] for i in ai]
        if et == at:
            for x, y in zip(ei, ai, strict=True):
                full = tuple(ef.items[x][:2])
                near = any(full[0] <= re and rs <= full[1] for rs, re in absorbed)
                if full != tuple(a_items[y][:2]) and not in_text(span) and not near:
                    add("non_code_placement", ef.items[x][2], span, x)
            continue
        sm = difflib.SequenceMatcher(None, et, at, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            ge, ga = ei[i1:i2], ai[j1:j2]
            n = min(len(ge), len(ga))
            # Pair from the outer end: the outer node is the segment of the
            # grammar rule; the inner ones are wrappers.
            for x, y in zip(ge[:n], ga[:n], strict=True):
                add("renamed", f"{ef.items[x][2]} -> {a_items[y][2]}", span, x)
            for x in ge[n:]:
                cross = key[0] != "nc" and _crosses(key, a_spans)
                cls = "nesting" if cross else "missing_wrapper"
                side = "sqlfluff " if cross else ""
                add(cls, f"{side}{ef.items[x][2]} in {ef.parent_type(x)}", span, x)
            for y in ga[n:]:
                cross = key[0] != "nc" and _crosses(key, e_spans)
                cls = "nesting" if cross else "extra_wrapper"
                side = "sqruff " if cross else ""
                add(cls, f"{side}{a_items[y][2]} in {a_parent_type(y)}", span)

    if not hunks:
        add("other", "no hunk", (0, len(ef.text)), 0)
    return {
        "first_path": "/".join(first_path(expected, actual)),
        "hunks": merge_hunks(hunks),
    }


def merge_hunks(hunks: list[list]) -> list[list]:
    """Return one row for each class, group key, and path: [class, group key,
    sqlfluff path, count, first start]."""
    rows: dict[tuple, list] = {}
    for cls, key, start, _end, path in sorted(hunks, key=lambda h: (h[2], h[3], h[:2])):
        row = rows.setdefault((cls, key, path), [cls, key, path, 0, start])
        row[3] += 1
    return sorted(rows.values(), key=lambda r: (r[4], r[:3]))


def _unparsable_anchor(ef: Flat, span: tuple[int, int]) -> tuple[str, tuple[int, int]]:
    """Return the sqlfluff segment where sqruff fails, and the region of the
    unparsable node.

    The segment is the child of the nearest "statement" node above the first
    fixture code leaf in the span. The region is the span of the node and the
    code span of that segment: sqruff did not parse the statement. With no
    such segment: the deepest fixture node that holds the span, and the span.
    """
    for i, it in enumerate(ef.items):
        if it[4] and it[0] >= span[0] and it[1] > it[0] and it[2] not in NON_CODE:
            if it[1] > span[1]:
                break
            chain = []
            j = it[3]
            while j >= 0:
                chain.append(j)
                j = ef.items[j][3]
            for below, node in zip(chain, chain[1:], strict=False):
                if ef.items[node][2] == "statement" and below in ef.code:
                    cs = ef.code[below]
                    return ef.items[below][2], (
                        min(cs[0], span[0]),
                        max(cs[1], span[1]),
                    )
            break
    best, depth = "file", -1
    for i, (s, e) in ef.code.items():
        if s <= span[0] and span[1] <= e and len(ef.path(i)) > depth:
            best, depth = ef.items[i][2], len(ef.path(i))
    return best, span


# collect: sqruff runs -> HUNKS_FILE


def _trees(adapter: SqruffAdapter, case: Case) -> tuple[tuple | None, tuple | None]:
    """Return (fixture tree, sqruff tree) as the suite of the case compares
    them."""
    _, expected = load_yaml(SQLFLUFF_ROOT / case.yml)
    if case.suite == "dialects":
        result = adapter.parse(
            case.sql,
            case.dialect,
            code_only=case.code_only,
            include_meta=False,
            cwd=SQLFLUFF_ROOT,
            extra_config=case.extra_config,
        )
        actual = record_to_tuple(result.tree) if result.tree is not None else None
        if trees_match(expected, actual):
            raise DataError(f"{case.id}: the trees are equal")
        return expected, actual
    result = adapter.parse_file(
        case.sql,
        None,
        SQLFLUFF_ROOT,
        code_only=case.code_only,
        include_meta=case.include_meta,
    )
    if result.tree is None or result.errors:
        raise DataError(f"{case.id}: no tree: {result.errors}")
    record = strip_positions(result.tree) if case.include_meta else result.tree
    actual = record_to_test_tuple(record)
    if actual == expected:
        raise DataError(f"{case.id}: the trees are equal")
    return expected, actual


def case_dialect(adapter: SqruffAdapter, case: Case) -> str:
    if case.dialect:
        return case.dialect
    config = adapter.user_config(case.sql, None, SQLFLUFF_ROOT, None)
    return config["core"]["dialect"]


def collect_case(adapter: SqruffAdapter, case: Case) -> dict:
    dialect = case_dialect(adapter, case)
    try:
        expected, actual = _trees(adapter, case)
    except Unsupported as exc:
        if str(exc) != f"dialect {dialect}":
            raise DataError(f"{case.id}: unsupported: {exc}") from exc
        return {
            "id": case.id,
            "dialect": dialect,
            "first_path": "file",
            "hunks": [
                ["unsupported_dialect", f"unsupported_dialect: {dialect}", "file", 1, 0]
            ],
        }
    if actual is None:
        raise DataError(f"{case.id}: sqruff gives no tree")
    return {"id": case.id, "dialect": dialect, **diff(expected, actual)}


def collect(jobs: int = 4) -> dict:
    adapter = SqruffAdapter()
    if adapter.version() != SQRUFF_VERSION:
        raise DataError(f"sqruff {adapter.version()}, not {SQRUFF_VERSION}")
    cases = tree_cases()
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        rows = list(pool.map(lambda c: collect_case(adapter, c), cases))
    return {
        "kind": "sqll-s3-sqruff-tree-hunks",
        "format": 1,
        "sqlfluff_ref": sqlfluff_ref(SQLFLUFF_ROOT),
        "sqruff": SQRUFF_VERSION,
        "commands": {"collect": COLLECT_COMMAND},
        "hunk": (
            "[class, group key, sqlfluff path, count, first start]: the hunks "
            "with this class, key, and path. start is a character offset in the "
            "text of the leaves of the fixture tree"
        ),
        "cases": {r.pop("id"): r for r in sorted(rows, key=lambda r: r["id"])},
    }


# build: committed files -> OUT_FILE


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def case_rows(hunks: dict) -> list[dict]:
    return [{"id": k, **v} for k, v in hunks["cases"].items()]


def classes_of(row: dict) -> list[str]:
    found = {h[0] for h in row["hunks"]}
    return [c for c in CLASSES if c in found]


def keys_of(row: dict) -> list[str]:
    return sorted({h[1] for h in row["hunks"]})


def select_sample(rows: list[dict]) -> tuple[list[str], str]:
    """Return the ids of the hand-check sample and the selection rule."""
    rule = (
        "Order the cases by the sha256 of the case id. Take the first case of "
        "each dialect. Then, for each class, take the next cases that have "
        f"the class until the sample has {SAMPLE_PER_CLASS} cases with it (or "
        f"no case is left). Then take the next cases until the sample has "
        f"{SAMPLE_SIZE} cases."
    )
    order = sorted(rows, key=lambda r: hashlib.sha256(r["id"].encode()).hexdigest())
    picked: list[dict] = []
    ids: set[str] = set()

    def take(r):
        if r["id"] not in ids:
            ids.add(r["id"])
            picked.append(r)

    for d in sorted({r["dialect"] for r in rows}):
        take(next(r for r in order if r["dialect"] == d))
    for c in CLASSES:
        for r in order:
            if sum(c in classes_of(p) for p in picked) >= SAMPLE_PER_CLASS:
                break
            if c in classes_of(r):
                take(r)
    for r in order:
        if len(picked) >= SAMPLE_SIZE:
            break
        take(r)
    return sorted(ids), rule


def check_inputs(hunks: dict, cases_record: dict, by_base: dict) -> list[str]:
    """Return the differences between the hunks file and the T2 data and
    known_failures/sqruff.txt."""
    errors = []
    known = known_failures.load(KNOWN_FAILURES, "sqruff")
    rows = case_rows(hunks)
    ids = [r["id"] for r in rows]
    want = {
        i
        for i, reason in known.items()
        if i.startswith("dialects/")
        or (i.startswith("templater/") and reason == TREE_DIFFERS)
    }
    if set(ids) != want:
        errors.append(
            f"the cases are not the dialect and templater tree failures of "
            f"known_failures/sqruff.txt ({len(set(ids) - want)} more, "
            f"{len(want - set(ids))} fewer)"
        )
    if len(ids) != DIALECT_FAILURES + TEMPLATER_TREE_FAILURES:
        errors.append(
            f"{len(ids)} cases, not {DIALECT_FAILURES + TEMPLATER_TREE_FAILURES}"
        )
    if hunks["sqlfluff_ref"] != sqlfluff_ref(SQLFLUFF_ROOT):
        errors.append("the sqlfluff ref of the hunks is not the pinned one")
    if hunks["sqlfluff_ref"] != cases_record["sqlfluff_ref"]:
        errors.append("the sqlfluff ref of the hunks is not that of the T2 cases")
    if hunks["sqruff"] != cases_record["record"]["version"]:
        errors.append("the sqruff version is not that of the T2 run")
    # T2 per-case rows: status and the no_unparsable check.
    t2 = {r[0]: r for r in cases_record["cases"]}
    for r in rows:
        row = t2.get(r["id"])
        if row is None:
            errors.append(f"{r['id']}: not in the T2 cases")
            continue
        exact, no_unparsable = row[2][0], row[2][1]
        if row[1] != "fail" or exact == 1:
            errors.append(f"{r['id']}: T2 gives {row[1]} {row[2]}")
        cls = classes_of(r)
        if not cls or any(c not in CLASSES for c in {h[0] for h in r["hunks"]}):
            errors.append(f"{r['id']}: no class or an unknown class")
        bad = "unparsable" in cls or "unsupported_dialect" in cls
        if bad != (no_unparsable != 1):
            errors.append(
                f"{r['id']}: classes {cls} do not agree with no_unparsable "
                f"{no_unparsable} of T2"
            )
        if r["id"].startswith("dialects/") and r["dialect"] != r["id"].split("/")[1]:
            errors.append(f"{r['id']}: dialect {r['dialect']}")
        unsupported = (
            known_failures.reason_prefix(known.get(r["id"], "")) == UNSUPPORTED_DIALECT
        )
        if ("unsupported_dialect" in cls) != unsupported:
            errors.append(f"{r['id']}: classes {cls}, reason {known.get(r['id'])!r}")
    # T2 tables: the dialect failures of each dialect.
    table = by_base["bases"]["sqruff"]["dialects"]
    got = Counter(r["dialect"] for r in rows if r["id"].startswith("dialects/"))
    for d, t in table.items():
        if got.get(d, 0) != t["fail"] + t["error"]:
            errors.append(
                f"{d}: {got.get(d, 0)} cases, T2 gives {t['fail'] + t['error']}"
            )
    no_unp = sum(
        1 for r in t2.values() if r[0].startswith("dialects/") and r[2][1] != 1
    )
    dialect_rows = by_base["bases"]["sqruff"]["suites"]["dialects"]
    if (
        no_unp
        != dialect_rows["total"] - dialect_rows["checks"]["no_unparsable"]["pass"]
    ):
        errors.append("the no_unparsable count is not that of T2")
    if no_unp != NO_UNPARSABLE_FAILURES:
        errors.append(f"{no_unp} dialect cases without no_unparsable, not 142")
    return errors


def coverage(rows: list[dict], key_fn) -> dict:
    """Group the cases by group key. Return the table of the groups and the
    share of the cases that the top groups cover. A case is covered by a set
    of groups if each of its keys is in the set."""
    groups: dict[str, set[str]] = {}
    case_keys = {}
    for r in rows:
        keys = key_fn(r)
        case_keys[r["id"]] = keys
        for k in keys:
            groups.setdefault(k, set()).add(r["id"])
    ranked = sorted(groups, key=lambda k: (-len(groups[k]), k))
    rank = {k: i for i, k in enumerate(ranked)}
    # The number of top groups that a case needs: the max rank of its keys.
    need = Counter(max(rank[k] for k in keys) + 1 for keys in case_keys.values())
    total = len(rows)

    def covered(n: int) -> int:
        return sum(v for k, v in need.items() if k <= n)

    singles = {k for k, v in groups.items() if len(v) == 1}
    return {
        "groups": len(groups),
        "top": {
            str(n): {
                "cases": covered(n),
                "share": round(covered(n) / total, 4),
                "touched": len(set().union(*(groups[k] for k in ranked[:n]))),
            }
            for n in TOP
        },
        "all": {"groups": len(groups), "cases": covered(len(groups))},
        "groups_with_one_case": len(singles),
        "cases_with_a_unique_fix": sum(
            1 for ks in case_keys.values() if set(ks) & singles
        ),
        "cases_with_only_unique_fixes": sum(
            1 for ks in case_keys.values() if ks and set(ks) <= singles
        ),
        "ranked": ranked,
        "members": groups,
    }


def build(
    hunks_file: Path = HUNKS_FILE,
    handcheck_file: Path = HANDCHECK_FILE,
) -> dict:
    hunks = json.loads(hunks_file.read_text("utf8"))
    cases_record = json.loads(CASES_FILE.read_text("utf8"))
    by_base = json.loads(S1_BY_BASE.read_text("utf8"))
    errors = check_inputs(hunks, cases_record, by_base)
    rows = case_rows(hunks)
    by_id = {r["id"]: r for r in rows}

    # Hand check.
    hand = json.loads(handcheck_file.read_text("utf8"))
    sample, rule = select_sample(rows)
    hand_ids = [c["id"] for c in hand["cases"]]
    if hand_ids != sample:
        errors.append(
            "the hand-check cases are not the sample "
            f"({len(set(hand_ids) - set(sample))} more, "
            f"{len(set(sample) - set(hand_ids))} fewer)"
        )
    if errors:
        raise DataError("; ".join(errors))
    checked = []
    for c in hand["cases"]:
        if set(c) != {"id", "classes", "note"} or not c["classes"]:
            raise DataError(f"{c.get('id')}: a hand-check row needs id, classes, note")
        if any(x not in CLASSES for x in c["classes"]):
            raise DataError(f"{c['id']}: unknown hand class")
        auto = classes_of(by_id[c["id"]])
        hand_cls = [x for x in CLASSES if x in c["classes"]]
        checked.append(
            {
                "id": c["id"],
                "dialect": by_id[c["id"]]["dialect"],
                "auto": auto,
                "hand": hand_cls,
                "agree": auto == hand_cls,
                "note": c["note"],
            }
        )
    agree = sum(c["agree"] for c in checked)
    per_class = {}
    for x in CLASSES:
        tp = sum(x in c["auto"] and x in c["hand"] for c in checked)
        fp = sum(x in c["auto"] and x not in c["hand"] for c in checked)
        fn = sum(x not in c["auto"] and x in c["hand"] for c in checked)
        if tp + fp + fn:
            per_class[x] = {"both": tp, "auto_only": fp, "hand_only": fn}
    sample_dialects = {c["dialect"] for c in checked}
    if sample_dialects != {r["dialect"] for r in rows}:
        raise DataError("the sample does not have each dialect")

    # Classes.
    total = len(rows)
    case_classes = {r["id"]: classes_of(r) for r in rows}
    class_table = {}
    for x in CLASSES:
        with_x = [i for i, cl in case_classes.items() if x in cl]
        class_table[x] = {
            "cases": len(with_x),
            "only": sum(1 for i in with_x if case_classes[i] == [x]),
            "primary": sum(1 for cl in case_classes.values() if cl[0] == x),
            "dialects": len({by_id[i]["dialect"] for i in with_x}),
            "hunks": sum(h[3] for r in rows for h in r["hunks"] if h[0] == x),
            "description": CLASSES[x],
        }
    if sum(v["primary"] for v in class_table.values()) != total:
        raise DataError("the primary classes do not add up to the cases")

    # Groups.
    cov = coverage(rows, keys_of)
    cov_dialect = coverage(
        rows, lambda r: [f"{k} @ {r['dialect']}" for k in keys_of(r)]
    )
    top_groups = []
    for k in cov["ranked"][:50]:
        members = cov["members"][k]
        top_groups.append(
            [
                k,
                len(members),
                len({by_id[i]["dialect"] for i in members}),
                sum(h[3] for i in members for h in by_id[i]["hunks"] if h[1] == k),
            ]
        )

    def strip(c):
        return {k: v for k, v in c.items() if k not in ("ranked", "members")}

    no_unparsable = [
        [
            r["id"],
            r["dialect"],
            case_classes[r["id"]],
            [
                k
                for k in keys_of(r)
                if k.startswith(("unparsable", "unsupported_dialect"))
            ],
        ]
        for r in rows
        if set(case_classes[r["id"]]) & {"unparsable", "unsupported_dialect"}
        and r["id"].startswith("dialects/")
    ]
    if len(no_unparsable) != NO_UNPARSABLE_FAILURES:
        raise DataError(f"{len(no_unparsable)} cases without no_unparsable, not 142")

    inputs = [
        hunks_file,
        handcheck_file,
        CASES_FILE,
        S1_BY_BASE,
        KNOWN_FAILURES / "sqruff.txt",
    ]
    per_case = []
    for r in rows:
        per_case.append(
            [
                r["id"],
                r["dialect"],
                case_classes[r["id"]],
                keys_of(r),
                r["first_path"],
                sum(h[3] for h in r["hunks"]),
            ]
        )
    return {
        "kind": "sqll-s3-sqruff-tree-diffs",
        "format": 1,
        "sqlfluff_ref": hunks["sqlfluff_ref"],
        "sqruff": hunks["sqruff"],
        "commands": {**hunks["commands"], "build": BUILD_COMMAND},
        "inputs": {
            str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else p.name: _sha256(p)
            for p in inputs
        },
        "scope": {
            "cases": total,
            "dialects": DIALECT_FAILURES,
            "templater": TEMPLATER_TREE_FAILURES,
            "note": (
                "The sqruff dialect failures (755 'tree differs', 3 "
                "'unsupported: dialect' soql) and the 5 templater 'tree "
                "differs' cases of known_failures/sqruff.txt. The build checks "
                "the case list against that file, and the dialect counts and the "
                "no_unparsable values against the T2 files."
            ),
        },
        "method": (
            "collect parses each case with sqruff through the harness adapter "
            "and compares the tree with the fixture tree (scripts/s3/"
            "sqruff_trees.py, diff). Leaves are compared by span, nodes by code "
            "span. Each difference is a hunk with one class and one group key. "
            "The group key is the class, the segment types, and the parent type "
            "in the tree that has the node. A case has the classes and the keys "
            "of its hunks. Primary class: the first class of the case in the "
            "order of 'classes'."
        ),
        "classes": class_table,
        "groups": {
            "key": "class and segment types, with no dialect",
            **strip(cov),
            "by_dialect": {"key": "group key and dialect", **strip(cov_dialect)},
            "coverage_rule": (
                "A case is covered by the top N groups if each of its group "
                "keys is in the top N. Groups are ranked by their count of "
                "cases. 'touched': the cases with at least one key in the top N. "
                "A unique fix: a group with only one case."
            ),
            "top_50": top_groups,
            "top_50_row": "[group key, cases, dialects, hunks]",
        },
        "hand_check": {
            "size": len(checked),
            "rule": rule,
            "method": hand["method"],
            "agree": agree,
            "rate": round(agree / len(checked), 4),
            "per_class": per_class,
            "cases": checked,
        },
        "no_unparsable": {
            "count": len(no_unparsable),
            "row": "[id, dialect, classes, unparsable or unsupported keys]",
            "cases": no_unparsable,
        },
        "row": "[id, dialect, classes, group keys, first differing path, hunks]",
        "cases": per_case,
    }


# Output.


def dumps(value, indent: int = 0) -> str:
    """JSON with one line for each item of a list of rows, and for each short
    object."""
    pad = " " * (indent + 1)
    if isinstance(value, dict) and value and len(json.dumps(value)) > 100:
        items = [
            f"{pad}{json.dumps(k)}: {dumps(v, indent + 1)}" for k, v in value.items()
        ]
        return "{\n" + ",\n".join(items) + "\n" + " " * indent + "}"
    if isinstance(value, list) and any(isinstance(v, dict | list) for v in value):
        items = [pad + json.dumps(v, ensure_ascii=False) for v in value]
        return "[\n" + ",\n".join(items) + "\n" + " " * indent + "]"
    return json.dumps(value, ensure_ascii=False)


def text(value: dict) -> str:
    return dumps(value) + "\n"


def leaves(tree: tuple) -> list[tuple[tuple[str, ...], str, str]]:
    """(ancestor types, type, text) of each leaf, and of each node with no
    children (text None)."""
    out: list = []

    def walk(node: tuple, path: tuple[str, ...]) -> None:
        name, value = node
        if isinstance(value, str) or not value:
            out.append((path, name, value if isinstance(value, str) else None))
            return
        for child in value:
            walk(child, path + (name,))

    walk(tree, ())
    return out


def leaf_changes(expected: tuple, actual: tuple) -> list[tuple[str, int]]:
    """Return the changes of the leaves and their counts, in the order of the
    first change. Another view than the diff, for the hand check: a leaf
    with the same text in both trees shows the changed part of its ancestor
    types and its type, after the last common ancestor. Other leaves show as
    removed (-) or added (+)."""
    e, a = leaves(expected), leaves(actual)
    sm = difflib.SequenceMatcher(
        None, [(x[2]) for x in e], [(y[2]) for y in a], autojunk=False
    )
    changes: Counter = Counter()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for x, y in zip(e[i1:i2], a[j1:j2], strict=True):
                if x[:2] != y[:2]:
                    changes[_path_change(x, y)] += 1
            continue
        for x in e[i1:i2]:
            changes[f"- {'/'.join(x[0][-2:])} | {x[1]} {x[2]!r}"] += 1
        for y in a[j1:j2]:
            changes[f"+ {'/'.join(y[0][-2:])} | {y[1]} {y[2]!r}"] += 1
    return list(changes.items())


def _path_change(x: tuple, y: tuple) -> str:
    pe, pa = list(x[0]) + [x[1]], list(y[0]) + [y[1]]
    k = 0
    while k < min(len(pe), len(pa)) - 1 and pe[k] == pa[k]:
        k += 1
    m = 0
    while m < min(len(pe), len(pa)) - k and pe[-1 - m] == pa[-1 - m]:
        m += 1
    ctx = pe[k - 1] if k else "-"
    mid_e = "/".join(pe[k : len(pe) - m]) or "()"
    mid_a = "/".join(pa[k : len(pa) - m]) or "()"
    return f"~ {ctx}: {mid_e} -> {mid_a}"


def show(ids: list[str]) -> None:
    adapter = SqruffAdapter()
    cases = {c.id: c for c in tree_cases()}
    for i in ids:
        print(f"===== {i}")
        try:
            expected, actual = _trees(adapter, cases[i])
        except Unsupported as exc:
            print(f"unsupported: {exc}")
            continue
        for change, n in leaf_changes(expected, actual):
            print(f"{n:4} {change}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sqruff_trees.py")
    sub = p.add_subparsers(dest="command", required=True)
    co = sub.add_parser("collect", help="Write HUNKS_FILE from sqruff runs.")
    co.add_argument("--jobs", type=int, default=4)
    co.add_argument("--out", type=Path, default=HUNKS_FILE)
    sh = sub.add_parser("show", help="Print the leaf changes of cases.")
    sh.add_argument("ids", nargs="+")
    bd = sub.add_parser("build", help="Write OUT_FILE from the committed inputs.")
    bd.add_argument("--hunks", type=Path, default=HUNKS_FILE)
    bd.add_argument("--handcheck", type=Path, default=HANDCHECK_FILE)
    bd.add_argument("--out", type=Path, default=OUT_FILE)
    bd.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.command == "collect":
            args.out.write_text(text(collect(args.jobs)), "utf8")
            print(f"wrote {args.out}")
            return 0
        if args.command == "show":
            show(args.ids)
            return 0
        new = text(build(args.hunks, args.handcheck))
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.check:
        if not args.out.exists() or args.out.read_text("utf8") != new:
            print(f"error: {args.out} is not the output of the build", file=sys.stderr)
            return 1
        print(f"{args.out}: no change")
        return 0
    args.out.write_text(new, "utf8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
