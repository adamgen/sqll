"""S3b task C4: the data of the core design record
(docs/decisions/s3b-core.md).

Run it with the harness Python:

    uv run --frozen --project harness python scripts/s3b/core_design.py measure [--check]
    uv run --frozen --project harness python scripts/s3b/core_design.py record [--check]

measure: the heap cost of the parser tree (MEASURE_FILE).
1. Build the 84 S2 parse inputs (harness/bench.md, "Inputs") into
   out/s3b/c4/inputs. Stop if they are not as in definitions.json.
2. Generate and check the dialect tables (scripts/build-sqll --tables-only).
3. Build the tool scripts/s3b/tree-cost (cargo, --locked, --offline). It
   links the sqll crates by path and counts each heap block.
4. Run it on each input and on the tables of the 28 dialects.
Each value is a count: two runs on the same code give the same file. The
flat tree is an estimate (FLAT): no flat tree exists before task C7.

record: each number of the record (RECORD_FILE), with its source: a key of
a committed file, or a formula over other values. It reads only committed
files and runs no tool. A changed source value fails the check. The
"claims" are the sentences of the record (CLAIMS) with these values. Each
claim must be in the record, and each number of the record must be in a
claim (doc_problems). Note: the value "unsupported_exit_code" reads
crates/sqll/src/main.rs. If task C13 moves EXIT_ERROR to sqll_cli, change
the path here (the check fails closed until then).

With --check, the command writes nothing and fails if the file is not the
new text (measure: the "data" part; the commit can differ). record --check
also fails if the record does not agree with the claims.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))
from sqll_harness.bench import definitions  # noqa: E402
from sqll_harness.bench import inputs as bench_inputs  # noqa: E402
from sqll_harness.paths import SQLFLUFF_ROOT  # noqa: E402

MEASURE_FILE = ROOT / "results" / "S3b" / "C4-tree-cost.json"
RECORD_FILE = ROOT / "results" / "S3b" / "C4-record.json"
RECORD_DOC = "docs/decisions/s3b-core.md"
COMMAND = "uv run --frozen --project harness python scripts/s3b/core_design.py"
TOOL_DIR = ROOT / "scripts" / "s3b" / "tree-cost"
TOOL = "sqll-s3b-tree-cost"
WORK = ROOT / "out" / "s3b" / "c4"
SIZES = ("small", "medium", "large")
TREE_KEYS = ("parse", "node_tree", "arena")
COUNT_KEYS = (
    "bytes",
    "lines",
    "tokens",
    "nodes",
    "raw",
    "segment",
    "meta",
    "unparsable",
    "raw_with_kwargs",
    "template_meta",
)

# The flat tree of the plan (C7): one Vec of node records, one Vec of child
# ids, one text buffer, and one Vec of line starts.
FLAT = {
    "node_record_bytes": 24,
    "node_record": "kind u16, flags u16, text start u32, text end u32, parent u32, "
    "children start u32, children end u32",
    "child_id_bytes": 4,
    "line_start_bytes": 4,
    "blocks": 4,
    "formula": "nodes * node_record_bytes + (nodes - 1) * child_id_bytes + bytes"
    " + (lines + 1) * line_start_bytes",
}


class DataError(Exception):
    """A step failed, or the data does not agree."""


def flat_bytes(item: dict) -> int:
    return (
        item["nodes"] * FLAT["node_record_bytes"]
        + (item["nodes"] - 1) * FLAT["child_id_bytes"]
        + item["bytes"]
        + (item["lines"] + 1) * FLAT["line_start_bytes"]
    )


def run(argv: list[str], **kw) -> subprocess.CompletedProcess:
    print("core_design: $ " + " ".join(argv), file=sys.stderr, flush=True)
    out = subprocess.run(argv, text=True, capture_output=True, **kw)
    if out.returncode != 0:
        raise DataError(f"{argv[0]}: exit code {out.returncode}\n{out.stderr[-4000:]}")
    return out


def git(*args: str) -> str:
    return run(["git", "-C", str(ROOT), *args]).stdout.strip()


def build_inputs() -> tuple[Path, dict]:
    result = bench_inputs.build(SQLFLUFF_ROOT)
    problems = definitions.check(definitions.load(), result)
    if problems:
        raise DataError(
            "the inputs are not as in definitions.json:\n" + "\n".join(problems)
        )
    out = WORK / "inputs"
    why = bench_inputs.check_out_dir(out, SQLFLUFF_ROOT)
    if why:
        raise DataError(why)
    bench_inputs.write(result, out)
    return out, definitions.load()["inputs"]


def build_tool() -> Path:
    run([sys.executable, str(ROOT / "scripts" / "build-sqll"), "--tables-only"])
    env = dict(os.environ, CARGO_TARGET_DIR=str(WORK / "target"))
    env.pop("RUSTFLAGS", None)
    manifest = str(TOOL_DIR / "Cargo.toml")
    run(
        [
            "cargo",
            "build",
            "--release",
            "--locked",
            "--offline",
            "--manifest-path",
            manifest,
        ],
        env=env,
    )
    return WORK / "target" / "release" / TOOL


def measure() -> dict:
    folder, recorded = build_inputs()
    tool = build_tool()
    names = [n for n in recorded if n != bench_inputs.START]
    dialects = sorted({n.split("/")[0] for n in names})
    order = [f"{d}/{s}" for d in dialects for s in SIZES]
    if sorted(order) != sorted(names):
        raise DataError(f"the inputs are not each dialect in each size: {names}")
    lines = "".join(f"{n.split('/')[0]}\t{folder / n}.sql\n" for n in order)
    out = run([str(tool), "parse"], input=lines).stdout.splitlines()
    tables = json.loads(run([str(tool), "tables", *dialects]).stdout)
    items, observed, kinds = [], set(), set()
    for name, line in zip(order, out, strict=True):
        raw = json.loads(line)
        data = (folder / f"{name}.sql").read_bytes()
        if hashlib.sha256(data).hexdigest() != recorded[name]["sha256"]:
            raise DataError(f"{name}: the sha256 is not as in definitions.json")
        if not raw["lossless"] or raw["unparsable"] or raw["empty"]:
            raise DataError(f"{name}: not a full lossless tree")
        observed.update(raw["types"])
        kinds.update(json.dumps(k) for k in raw["kinds"])
        item = {"input": name, "sha256": recorded[name]["sha256"]}
        item.update({k: raw[k] for k in COUNT_KEYS})
        item["max_depth"] = raw["max_depth"]
        item.update({k: raw[k] for k in TREE_KEYS})
        item["flat_estimate"] = {"blocks": FLAT["blocks"], "bytes": flat_bytes(item)}
        items.append(item)
    totals = {k: sum(i[k] for i in items) for k in COUNT_KEYS}
    for key in (*TREE_KEYS, "flat_estimate"):
        totals[key] = {
            f: sum(i[key][f] for i in items)
            for f in ("blocks", "bytes")
            if f in items[0][key]
        }
    strings = set(tables.pop("all_strings"))
    return {
        "kinds": kind_counts([json.loads(k) for k in kinds]),
        "inputs": len(items),
        "dialects": len(dialects),
        "flat": FLAT,
        "totals": totals,
        "types": {
            "observed": len(observed),
            "observed_not_in_tables_or_lexers": sorted(observed - strings),
            "table_strings_and_lexer_names": len(strings),
            "tables": tables,
        },
        "items": items,
    }


def kind_counts(kinds: list[list]) -> dict:
    """Count the kinds: the distinct static data of the nodes (the node
    variant, the class, the type, the instance types, the class types, and
    the segment kwargs of a leaf). The tool gives each kind as a JSON array
    that starts with the node variant."""
    by_variant: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for k in kinds:
        by_variant[k[0]] = by_variant.get(k[0], 0) + 1
        if k[0] in ("raw", "segment") and k[2] is not None:
            by_type[k[2]] = by_type.get(k[2], 0) + 1
    return {
        "distinct": len(kinds),
        "by_variant": dict(sorted(by_variant.items())),
        "type_names": len(by_type),
        "type_names_with_more_than_one_kind": sum(n > 1 for n in by_type.values()),
        "u16_limit": 2**16,
    }


def measure_doc(data: dict) -> dict:
    rustc = run(["rustc", "-V"], cwd=TOOL_DIR).stdout.strip()
    return {
        "kind": "sqll-s3b-c4-tree-cost",
        "about": (
            "The heap cost of the parser tree (Node) and of the Arena for the 84 S2 parse"
            " inputs, and a flat tree estimate. Counts of scripts/s3b/tree-cost: blocks"
            " and asked bytes. parse: the allocations of Parser::root_parse. node_tree:"
            " what a clone of the tree keeps (a clone has no spare Vec capacity, thus a"
            " lower bound of the tree that the parser keeps). arena: what"
            " Arena::from_node keeps. kinds: the distinct static data of the nodes"
            " (variant, class, type, instance types, class types, segment kwargs)."
        ),
        "command": f"{COMMAND} measure",
        "commit": git("rev-parse", "HEAD"),
        "crates_clean": git("status", "--porcelain", "--", "crates", "Cargo.lock")
        == "",
        "rustc": rustc,
        "data": data,
    }


def mb(value: int) -> str:
    """Bytes as megabytes (10**6 bytes), with 1 decimal."""
    return f"{value / 1e6:.1f}"


# The record values. Each is copied (file and key) or derived (formula).
def _key(doc, key: str):
    value = doc
    for part in key.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _sha256(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def record() -> dict:
    files = {
        "tree": "results/S3b/C4-tree-cost.json",
        "native": "results/s3/base-native-tests.json",
        "s1": "results/s1/summary.json",
        "tables": "crates/sqll_dialects/generated.json",
    }
    docs = {k: json.loads((ROOT / v).read_text("utf8")) for k, v in files.items()}
    values: dict[str, dict] = {}

    def copied(vid, name, key, text=None):
        value = _key(docs[name], key)
        values[vid] = {
            "kind": "copied",
            "from": files[name],
            "key": key,
            "value": value,
            "text": str(value) if text is None else text(value),
        }

    def matched(vid, rel, pattern):
        found = re.findall(pattern, (ROOT / rel).read_text("utf8"), re.MULTILINE)
        if len(found) != 1:
            raise DataError(f"{rel}: {len(found)} lines match {pattern}")
        values[vid] = {
            "kind": "copied",
            "from": rel,
            "key": f"the line that matches {pattern}",
            "value": int(found[0]),
            "text": found[0],
        }

    def derived(vid, formula, value, text):
        values[vid] = {
            "kind": "derived",
            "formula": formula,
            "value": value,
            "text": text,
        }

    tot = "data.totals"
    copied("inputs", "tree", "data.inputs")
    copied("nodes", "tree", f"{tot}.nodes")
    copied("input_bytes", "tree", f"{tot}.bytes")
    copied("node_blocks", "tree", f"{tot}.node_tree.blocks")
    copied("node_bytes", "tree", f"{tot}.node_tree.bytes", text=mb)
    copied("arena_blocks", "tree", f"{tot}.arena.blocks")
    copied("arena_bytes", "tree", f"{tot}.arena.bytes", text=mb)
    copied("parse_blocks", "tree", f"{tot}.parse.blocks")
    copied("flat_bytes", "tree", f"{tot}.flat_estimate.bytes", text=mb)
    copied("flat_blocks", "tree", "data.flat.blocks")
    copied("record_bytes", "tree", "data.flat.node_record_bytes")
    copied("kinds", "tree", "data.kinds.distinct")
    copied("kinds_raw", "tree", "data.kinds.by_variant.raw")
    copied("kinds_segment", "tree", "data.kinds.by_variant.segment")
    copied("kinds_meta", "tree", "data.kinds.by_variant.meta")
    copied("type_names_multi", "tree", "data.kinds.type_names_with_more_than_one_kind")
    copied("raw_with_kwargs", "tree", f"{tot}.raw_with_kwargs")
    copied("template_meta", "tree", f"{tot}.template_meta")
    v = {k: x["value"] for k, x in values.items()}
    derived(
        "node_bytes_per_node",
        "node_bytes / nodes",
        v["node_bytes"] / v["nodes"],
        f"{v['node_bytes'] / v['nodes']:.0f}",
    )
    derived(
        "node_blocks_per_node",
        "node_blocks / nodes",
        v["node_blocks"] / v["nodes"],
        f"{v['node_blocks'] / v['nodes']:.1f}",
    )
    derived(
        "node_bytes_per_input_byte",
        "node_bytes / input_bytes",
        v["node_bytes"] / v["input_bytes"],
        f"{v['node_bytes'] / v['input_bytes']:.0f}",
    )
    derived(
        "node_over_flat",
        "node_bytes / flat_bytes",
        v["node_bytes"] / v["flat_bytes"],
        f"{v['node_bytes'] / v['flat_bytes']:.0f}",
    )
    derived(
        "tree_share_of_parse_blocks",
        "node_blocks / parse_blocks, in percent",
        100 * v["node_blocks"] / v["parse_blocks"],
        f"{100 * v['node_blocks'] / v['parse_blocks']:.0f}%",
    )
    derived("u16_kinds", "2 ** 16", 2**16, str(2**16))
    copied("native_tests", "native", "totals.tests")
    arena = [
        t
        for t in docs["native"]["tests"]
        if t["name"].startswith("parser::arena::tests::")
    ]
    derived(
        "arena_tests",
        'count of tests whose name starts with "parser::arena::tests::" in '
        + files["native"],
        len(arena),
        str(len(arena)),
    )
    copied("s1_exact", "s1", "results.sqll.suites.dialects.checks.exact")
    copied("s1_total", "s1", "results.sqll.suites.dialects.total")
    copied("table_files", "tables", "files", text=lambda x: str(len(x)))
    values["table_files"]["value"] = len(values["table_files"]["value"])
    derived(
        "table_sha256",
        f"sha256 of {files['tables']} (the tables part of the sqll version)",
        _sha256(files["tables"]),
        _sha256(files["tables"])[:12],
    )
    matched(
        "runaway_limit",
        "third_party/sqlfluff/src/sqlfluff/core/default_config.cfg",
        r"^runaway_limit = (\d+)$",
    )
    matched(
        "unsupported_exit_code",
        "crates/sqll/src/main.rs",
        r"^const EXIT_ERROR: u8 = (\d+);$",
    )
    texts = {k: x["text"] for k, x in values.items()}
    return {
        "kind": "sqll-s3b-c4-record",
        "about": f"Each number of {RECORD_DOC} and its source, and the sentences"
        " (claims) of the record with these numbers.",
        "command": f"{COMMAND} record",
        "inputs": files,
        "values": values,
        "claims": [c.format(**texts) for c in CLAIMS],
    }


# The sentences of the record that have a number, with the value ids. The
# record must have each sentence (whitespace can differ).
CLAIMS = (
    "parses the {inputs} S2 parse inputs as `sqll parse` does",
    "The {inputs} inputs have {input_bytes} bytes of SQL and {nodes} tree nodes:",
    "| `Node` tree of the parser (a clone, a lower bound) | {node_blocks}"
    " | {node_bytes} |",
    "| `Arena`, made from the `Node` tree | {arena_blocks} | {arena_bytes} |",
    "| Flat tree, estimate with a {record_bytes}-byte node record"
    " | {flat_blocks} for each tree | {flat_bytes} |",
    "The `Node` tree uses {node_bytes_per_node} bytes and {node_blocks_per_node}"
    " heap blocks for each node ({node_bytes_per_input_byte} bytes for each byte"
    " of SQL)",
    "The flat tree is {node_over_flat} times smaller (an estimate; C7 measures it).",
    "The tree has {tree_share_of_parse_blocks} of the {parse_blocks} heap blocks"
    " that the parse asks for.",
    "The {inputs} trees have {kinds} kinds: {kinds_raw} leaf, {kinds_segment}"
    " segment, and {kinds_meta} meta kinds.",
    "{type_names_multi} type names have more than one kind (for example"
    " `quoted_literal`), and {raw_with_kwargs} leaves have segment kwargs.",
    "`Node` and `Arena` stay: {arena_tests} of the {native_tests} native base"
    " tests test the `Arena`.",
    "The leaves of each of the {inputs} trees give their input again (the tool"
    " checks this)",
    "the inputs use the raw templater ({template_meta} template meta nodes)",
    "up to the sqlfluff `runaway_limit` ({runaway_limit} loops).",
    'gives "unsupported" and exit code {unsupported_exit_code}.',
    "the sha256 of the manifest of the {table_files} generated files"
    " (`generated.json`, `{table_sha256}`) is part of the sqll version.",
    "The trees have {kinds} kinds; a `u16` holds {u16_kinds} kinds.",
    "S1 dialect suite of sqll: {s1_exact} of {s1_total} exact,",
    "Native base tests: {native_tests} of {native_tests}.",
)


def flat_text(text: str) -> str:
    return " ".join(text.split())


def numbers(text: str) -> list[str]:
    """Return the numbers of the text outside code, link targets, list
    numbers, versions, dates, and ids (G3.6, C4, Q1, CP01)."""
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"(?m)^\s*\d+\. ", " ", text)
    text = re.sub(r"\b\d+\.\d+\.\d+\b", " ", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)
    text = re.sub(r"\b[A-Z][A-Za-z]*\d+[a-z]?(?:\.\d+)*\b", " ", text)
    return re.findall(r"(?<![\w.-])\d+(?:\.\d+)?%?", text)


def doc_problems(text: str, claims: list[str]) -> list[str]:
    """Each claim must be in the record text, and each number of the record
    must be in a claim. Thus a number cannot move to another sentence, and
    the words around it cannot change."""
    problems, rest = [], flat_text(text)
    for claim in claims:
        if flat_text(claim) not in rest:
            problems.append(f"the record does not have the claim: {claim}")
    for claim in sorted(claims, key=len, reverse=True):
        rest = rest.replace(flat_text(claim), " ")
    for number in numbers(rest):
        problems.append(f"the record has a number that is not in a claim: {number}")
    return problems


def shown(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def text_of(doc: dict) -> str:
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("what", choices=("measure", "record"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    path = MEASURE_FILE if args.what == "measure" else RECORD_FILE
    try:
        if args.what == "measure":
            doc = measure_doc(measure())
        else:
            doc = record()
    except (DataError, KeyError, OSError, ValueError) as exc:
        print(f"core_design: {exc}", file=sys.stderr)
        return 1
    if args.check:
        try:
            old = json.loads(path.read_text("utf8"))
        except (OSError, ValueError) as exc:
            print(f"core_design: {exc}", file=sys.stderr)
            return 1
        same = old.get("data") == doc["data"] if args.what == "measure" else old == doc
        if not same:
            print(f"core_design: {shown(path)} is not the new data", file=sys.stderr)
            return 1
        if args.what == "record":
            problems = doc_problems(
                (ROOT / RECORD_DOC).read_text("utf8"), doc["claims"]
            )
            for problem in problems:
                print(f"core_design: {RECORD_DOC}: {problem}", file=sys.stderr)
            if problems:
                return 1
        print(f"core_design: {shown(path)} is the new data")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf8"
    ) as f:
        f.write(text_of(doc))
    os.replace(f.name, path)
    print(f"core_design: wrote {shown(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
