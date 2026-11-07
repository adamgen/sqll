"""S3b task C10: the sqlfluff answers for the crawl of the typed view
(docs/interfaces/typed-view.md).

Run it with the harness Python from the repository root:

    uv run --frozen --project harness python scripts/s3b/crawl_oracle.py record
    uv run --frozen --project harness python scripts/s3b/crawl_oracle.py check

Both run the pinned sqlfluff of the tool venv (tools/sqlfluff, pure Python)
on the dialect fixtures FIXTURES. The parse is that of the sqlfluff dialect
test (test/conftest.py, parse_example_file: the dialect of the folder, the
lexer and the parser, no templater). For each fixture and each case of
CASES, the data are the segments that BaseSegment.recursive_crawl gives
(type and raw, in order), or null if the fixture has no start node. For
the Jinja templater fixture TEMPLATED_FIXTURE, the data are the block type
and the source text of each placeholder.

A case is a start node, the types, recurse_into, no_recursive_seg_type, and
allow_self. The start node is the root, or the n-th segment (from 0) of a
type, in pre-order, of the code segments with that type (get_type).

The data also come from the fixture YAML (the sqlfluff parse tree of the
fixture, code only). The YAML has the type (get_type) of each segment, but
not its class types. Thus a case is a YAML case ("yaml": true) if no
segment of the tree has one of the types or no_recursive types as a class
type only (is_type true, get_type another type). For each YAML case, the
same crawl on the YAML tree (a match is a key of the types) must give the
code segments of the sqlfluff crawl (type and the raw of the code leaves),
in the same order.

record: write RECORD_FILE.
check (CI job build): make the data again; it must be the text of
RECORD_FILE. The YAML crawl must agree for each YAML case, and the counts
must be those of COUNTS. The interface test
crates/sqll_interfaces/tests/typed_view.rs reads RECORD_FILE and the
fixture YAML (cargo test).

Exit code: 0 pass, 1 a failure.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQLFLUFF_ROOT = ROOT / "third_party" / "sqlfluff"
RECORD_FILE = ROOT / "results" / "S3b" / "C10-crawl.json"
KIND = "sqll-s3b-c10-crawl"
FORMAT = 1
COMMAND = "uv run --frozen --project harness python scripts/s3b/crawl_oracle.py"
FIXTURE_DIR = "test/fixtures/dialects"
# dialect/file of the dialect fixtures.
FIXTURES = (
    "ansi/select_a.sql",
    "ansi/select_j.sql",
    "ansi/select_many_join.sql",
    "ansi/select_simple_e.sql",
    "bigquery/select_example.sql",
    "tsql/multi_statement.sql",
)
# A templater fixture with placeholders (its slices are in the record of
# C8, results/S3b/C8-source-map.json).
TEMPLATED_FIXTURE = "test/fixtures/templater/jinja_b/jinja.sql"
# [start, types, recurse_into, no_recursive, allow_self]; start is null
# (the root) or [type, n].
CASES = (
    [None, ["statement"], True, [], True],
    [None, ["statement"], False, [], True],
    [None, ["select_statement"], True, [], True],
    [None, ["select_statement"], False, [], True],
    [None, ["column_reference"], True, [], True],
    [None, ["column_reference", "table_reference"], True, [], True],
    [None, ["from_expression_element"], False, [], True],
    [None, ["alias_expression"], True, [], True],
    [None, ["keyword"], True, [], True],
    [None, ["identifier"], True, [], True],
    [None, ["literal"], True, [], True],
    [None, ["comment"], True, [], True],
    [None, ["end_of_file", "indent", "dedent"], True, [], True],
    [None, ["indent"], True, [], True],
    [["select_statement", 0], ["column_reference"], True, ["select_statement"], True],
    [["select_statement", 0], ["keyword"], True, ["select_clause", "bracketed"], True],
    [["select_statement", 0], ["select_statement"], True, [], False],
    [["select_statement", 0], ["select_statement"], False, [], False],
    [["select_statement", 0], ["select_statement"], False, [], True],
    [["select_statement", 0], ["select_statement"], True, ["select_statement"], True],
    [
        ["select_statement", 1],
        ["select_clause_element"],
        True,
        ["select_statement"],
        True,
    ],
    [["from_expression", 0], ["from_expression_element"], False, [], True],
    [["from_expression", 0], ["table_reference"], True, ["bracketed"], True],
)
# The counts of the record (docs/interfaces/typed-view.md, "Proof"):
# cases with a start node, YAML cases, and segments of the crawls.
COUNTS = {"cases": 135, "yaml_cases": 111, "segments": 1182}


class DataError(Exception):
    """A step failed, or the data do not agree."""


# The data, made with the sqlfluff Python (the "dump" command).


def parse_fixture(rel: str):
    """The parse tree of the sqlfluff dialect test (parse_example_file)."""
    from sqlfluff.core import FluffConfig
    from sqlfluff.core.parser import Lexer, Parser

    dialect, name = rel.split("/")
    config = FluffConfig(overrides={"dialect": dialect})
    raw = (SQLFLUFF_ROOT / FIXTURE_DIR / rel).read_text(encoding="utf8")
    tokens, _ = Lexer(config=config).lex(raw)
    tree = Parser(config=config).parse(tokens, fname=rel)
    if tree is None or tree.raw != raw:
        raise DataError(f"{rel}: no lossless sqlfluff parse tree")
    return tree


def code_raw(seg) -> str:
    """The raw of the code leaves of a segment (as the YAML shows them)."""
    return "".join(r.raw for r in seg.raw_segments if r.is_code and not r.is_meta)


def start_node(tree, start):
    if start is None:
        return tree
    ty, n = start
    found = [s for s in tree.recursive_crawl_all() if s.is_code and s.get_type() == ty]
    return found[n] if n < len(found) else None


def class_only(tree, types) -> bool:
    """True if a segment has one of the types only as a class type."""
    return any(
        s.is_type(t) and s.get_type() != t
        for s in tree.recursive_crawl_all()
        for t in types
    )


# The YAML tree: (type, raw) for a leaf, (type, [children]) for a segment.


def yaml_tree(rel: str):
    import yaml

    path = (SQLFLUFF_ROOT / FIXTURE_DIR / rel).with_suffix(".yml")
    obj = yaml.safe_load(path.read_text(encoding="utf8"))
    obj.pop("_hash", None)
    (item,) = obj.items()
    return to_node(*item)


def to_node(key: str, value):
    if isinstance(value, str):
        return (key, value)
    if value is None:
        return (key, [])
    if isinstance(value, dict):
        return (key, [to_node(k, v) for k, v in value.items()])
    if isinstance(value, list):
        children = []
        for elem in value:
            ((k, v),) = elem.items()
            children.append(to_node(k, v))
        return (key, children)
    raise DataError(f"a YAML value of the type {type(value).__name__}")


def yaml_raw(node) -> str:
    key, value = node
    return value if isinstance(value, str) else "".join(yaml_raw(c) for c in value)


def yaml_preorder(node):
    yield node
    if not isinstance(node[1], str):
        for c in node[1]:
            yield from yaml_preorder(c)


def yaml_crawl(node, types, recurse_into, no_recursive, allow_self=True):
    """BaseSegment.recursive_crawl on the YAML tree: the key is the type."""
    key, value = node
    match = allow_self and key in types
    if match:
        yield node
    if isinstance(value, str) or (match and not recurse_into):
        return
    for child in value:
        if child[0] not in no_recursive:
            yield from yaml_crawl(child, types, recurse_into, no_recursive)


def yaml_start(node, start):
    if start is None:
        return node
    ty, n = start
    found = [s for s in yaml_preorder(node) if s[0] == ty]
    return found[n] if n < len(found) else None


def case_data(rel: str, tree, ytree, case) -> tuple[dict, list[str]]:
    start, types, recurse_into, no_recursive, allow_self = case
    node = start_node(tree, start)
    out = {
        "start": start,
        "types": types,
        "recurse_into": recurse_into,
        "no_recursive": no_recursive,
        "allow_self": allow_self,
        "yaml": not class_only(tree, types + no_recursive),
        "crawl": None,
    }
    if node is None:
        return out, []
    crawl = list(
        node.recursive_crawl(
            *types,
            recurse_into=recurse_into,
            no_recursive_seg_type=no_recursive,
            allow_self=allow_self,
        )
    )
    out["crawl"] = [[s.get_type(), s.raw] for s in crawl]
    problems = []
    if out["yaml"]:
        want = [
            [s.get_type(), code_raw(s)] for s in crawl if s.is_code and not s.is_meta
        ]
        ynode = yaml_start(ytree, start)
        got = (
            None
            if ynode is None
            else [
                [k, yaml_raw((k, v))]
                for k, v in yaml_crawl(
                    ynode, types, recurse_into, no_recursive, allow_self
                )
            ]
        )
        if got != want:
            problems.append(f"{rel} {case}: the YAML crawl is {got}, not {want}")
    return out, problems


def placeholder_data(rel: str) -> dict:
    """block_type and source_str of each placeholder of a templater fixture
    (the parse of source_map_oracle.py: the config of the fixture folder)."""
    from sqlfluff.core import FluffConfig, Linter

    path = SQLFLUFF_ROOT / rel
    config = FluffConfig.from_path(str(path.parent))
    source = path.read_text(encoding="utf8")
    parsed = Linter(config=config).parse_string(source, fname=str(path))
    tree = parsed.parsed_variants[0].tree
    if tree is None or parsed.violations:
        raise DataError(f"{rel}: no sqlfluff parse tree with no violation")
    return {
        "path": rel,
        "templater": config.get("templater"),
        "dialect": config.get("dialect"),
        "placeholders": [
            [s.block_type, s.source_str] for s in tree.recursive_crawl("placeholder")
        ],
    }


def dump() -> dict:
    import sqlfluff

    fixtures, problems = [], []
    for rel in FIXTURES:
        tree = parse_fixture(rel)
        ytree = yaml_tree(rel)
        cases = []
        for case in CASES:
            data, p = case_data(rel, tree, ytree, case)
            cases.append(data)
            problems += p
        fixtures.append({"path": f"{FIXTURE_DIR}/{rel}", "cases": cases})
    return {
        "sqlfluff": sqlfluff.__version__,
        "fixtures": fixtures,
        "templated": placeholder_data(TEMPLATED_FIXTURE),
        "problems": problems,
    }


# The commands of the harness Python.


def run_dump() -> dict:
    sys.path.insert(0, str(ROOT / "harness"))
    from sqll_harness.paths import tools_dir

    python = tools_dir() / "sqlfluff" / "bin" / "python"
    if not python.is_file():
        raise DataError(f"no sqlfluff Python at {python} (scripts/setup)")
    argv = [str(python), "-I", "-B", str(Path(__file__).resolve()), "dump"]
    print(f"crawl_oracle: $ {' '.join(argv)}", flush=True)
    out = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=False)
    if out.returncode != 0:
        raise DataError(f"dump: exit code {out.returncode}\n{out.stderr[-4000:]}")
    return json.loads(out.stdout)


def submodule_commit() -> str:
    out = subprocess.run(
        ["git", "-C", str(SQLFLUFF_ROOT), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    return out.stdout.strip()


def counts(fixtures: list[dict]) -> dict:
    cases = [c for f in fixtures for c in f["cases"] if c["crawl"] is not None]
    return {
        "cases": len(cases),
        "yaml_cases": sum(1 for c in cases if c["yaml"]),
        "segments": sum(len(c["crawl"]) for c in cases),
    }


def record_data(data: dict) -> dict:
    return {
        "kind": KIND,
        "format": FORMAT,
        "about": (
            "S3b C10: the segments of the sqlfluff recursive_crawl on dialect "
            "fixtures of the pinned sqlfluff (scripts/s3b/crawl_oracle.py; "
            "docs/interfaces/typed-view.md). A case: start (null for the root, or "
            "[type, n]: the n-th code segment of the type in pre-order), types, "
            "recurse_into, no_recursive (no_recursive_seg_type), allow_self. "
            "crawl: [type, raw] of each segment in order, or null if the fixture "
            "has no start node. yaml: the fixture YAML shows the types of the case "
            "(no segment has one only as a class type), and its crawl agrees. "
            "templated: [block_type, source_str] of each placeholder of a Jinja "
            "templater fixture, in order."
        ),
        "command": f"{COMMAND} record",
        "sqlfluff": {"version": data["sqlfluff"], "commit": submodule_commit()},
        "counts": counts(data["fixtures"]),
        "templated": data["templated"],
        "fixtures": data["fixtures"],
    }


def dumps(record: dict) -> str:
    """JSON with one line for each case."""
    lines = ["{"]
    keys = list(record)
    for k, key in enumerate(keys):
        end = "," if k < len(keys) - 1 else ""
        if key != "fixtures":
            lines.append(f" {json.dumps(key)}: {json.dumps(record[key])}{end}")
            continue
        lines.append(' "fixtures": [')
        for f, fixture in enumerate(record["fixtures"]):
            lines.append(f'  {{"path": {json.dumps(fixture["path"])}, "cases": [')
            cases = fixture["cases"]
            for c, case in enumerate(cases):
                lines.append(
                    f"   {json.dumps(case)}" + ("," if c < len(cases) - 1 else "")
                )
            lines.append("  ]}" + ("," if f < len(record["fixtures"]) - 1 else ""))
        lines.append(" ]" + end)
    lines.append("}")
    return "\n".join(lines) + "\n"


def problems_of(data: dict) -> list[str]:
    problems = list(data["problems"])
    got = counts(data["fixtures"])
    if got != COUNTS:
        problems.append(f"the counts are {got}, not {COUNTS}")
    return problems


def record() -> int:
    data = run_dump()
    RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECORD_FILE.write_text(dumps(record_data(data)), encoding="utf8")
    print(f"crawl_oracle: wrote {RECORD_FILE.relative_to(ROOT)}")
    for p in problems_of(data):
        print(f"crawl_oracle: {p}")
    return 1 if problems_of(data) else 0


def check() -> int:
    data = run_dump()
    problems = problems_of(data)
    want = dumps(record_data(data))
    if not RECORD_FILE.is_file() or RECORD_FILE.read_text(encoding="utf8") != want:
        problems.append(
            f"{RECORD_FILE.relative_to(ROOT)} is not the sqlfluff data ({COMMAND} record)"
        )
    clean = subprocess.run(
        [str(ROOT / "scripts" / "check-submodule"), "after the crawl data"],
        check=False,
    )
    if clean.returncode != 0:
        problems.append("the sqlfluff run changed the submodule")
    for p in problems:
        print(f"crawl check: {p}")
    if problems:
        print(f"crawl check: FAIL: {len(problems)} problems")
        return 1
    c = counts(data["fixtures"])
    print(
        f"crawl check: PASS: {len(FIXTURES)} fixtures, {c['cases']} cases "
        f"({c['yaml_cases']} YAML cases), {c['segments']} segments"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("record", help="write the record file")
    sub.add_parser("check", help="check the record and the YAML crawls")
    sub.add_parser("dump", help="(sqlfluff Python) print the data as JSON")
    args = parser.parse_args(argv)
    try:
        if args.command == "dump":
            json.dump(dump(), sys.stdout)
            return 0
        if args.command == "record":
            return record()
        return check()
    except DataError as e:
        print(f"crawl_oracle: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
