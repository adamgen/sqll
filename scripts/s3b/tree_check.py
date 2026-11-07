"""S3b task C7: the S2 parse inputs and the cost of the conversion from the
parser tree to the SyntaxTree (docs/interfaces/tree.md).

Run it with the harness Python from the repository root:

    uv run --frozen --project harness python scripts/s3b/tree_check.py check
    uv run --frozen --project harness python scripts/s3b/tree_check.py measure [--runs N]
    uv run --frozen --project harness python scripts/s3b/tree_check.py summary

check (CI job build, scripts/verify): build the 84 S2 parse inputs
(harness/bench.md, "Inputs") into out/s3b/c7/inputs, then run the ignored
test TEST of crates/sqll_interfaces/tests/tree.rs on them (cargo test
--locked). The test converts the parser tree of each input and checks the
lossless rule and that each node equals the parser node. The check fails
unless cargo exits with 0, the test passes, and the output has PASS_LINE.

measure: with the machine lock (PROCESS.md, "Tracks", rule 7), build the
tool scripts/s3b/convert-cost (release, --locked, --offline) and run it on
the 28 large inputs. Write MEASURE_FILE: for each input, the median times of
the lex, the parse, and the conversion, and the heap counts of each step.
The times change from run to run; the heap counts do not.

summary: print the lines of the C7 numbers that status/S3b.md cites
(harness/tests/test_s3b_tree_check.py checks them).

Exit code: 0 pass, 1 a failure.
"""

import argparse
import fcntl
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))
from sqll_harness.bench import definitions  # noqa: E402
from sqll_harness.bench import inputs as bench_inputs  # noqa: E402
from sqll_harness.paths import SQLFLUFF_ROOT  # noqa: E402

MEASURE_FILE = ROOT / "results" / "S3b" / "C7-conversion.json"
KIND = "sqll-s3b-c7-conversion"
COMMAND = "uv run --frozen --project harness python scripts/s3b/tree_check.py"
TOOL_DIR = ROOT / "scripts" / "s3b" / "convert-cost"
TOOL = "sqll-s3b-convert-cost"
WORK = ROOT / "out" / "s3b" / "c7"
LOCK = Path("/tmp/sqll-machine.lock")
SIZES = ("small", "medium", "large")
PARSE_INPUTS = 84
LARGE_INPUTS = 28
RUNS = 21
TEST = "each_s2_parse_input_converts_lossless_and_node_for_node"
INPUTS_ENV = "SQLL_S2_PARSE_INPUTS"
PASS_LINE = (
    f"tree: {PARSE_INPUTS} of {PARSE_INPUTS} S2 parse inputs:"
    " lossless and node for node equal"
)
STEPS = ("lex", "parse", "convert")
MEMORY_KEYS = ("blocks", "bytes", "peak_bytes", "kept_bytes")


class DataError(Exception):
    """A step failed, or the data does not agree."""


def run(argv: list[str], **kw) -> subprocess.CompletedProcess:
    print("tree_check: $ " + " ".join(argv), file=sys.stderr, flush=True)
    out = subprocess.run(argv, text=True, capture_output=True, **kw)
    if out.returncode != 0:
        raise DataError(
            f"{argv[0]}: exit code {out.returncode}\n{out.stdout[-4000:]}{out.stderr[-4000:]}"
        )
    return out


def build_inputs() -> tuple[Path, dict]:
    """Build the S2 inputs into WORK/inputs. Return the folder and the
    parse inputs of definitions.json ("<dialect>/<size>": entry)."""
    result = bench_inputs.build(SQLFLUFF_ROOT)
    defs = definitions.load()
    problems = definitions.check(defs, result)
    if problems:
        raise DataError(
            "the inputs are not as in definitions.json:\n" + "\n".join(problems)
        )
    out = WORK / "inputs"
    why = bench_inputs.check_out_dir(out, SQLFLUFF_ROOT)
    if why:
        raise DataError(why)
    bench_inputs.write(result, out)
    parse = {
        name: entry
        for name, entry in defs["inputs"].items()
        if name.split("/")[-1] in SIZES
    }
    if len(parse) != PARSE_INPUTS:
        raise DataError(f"{len(parse)} parse inputs, not {PARSE_INPUTS}")
    for name, entry in parse.items():
        data = (out / f"{name}.sql").read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise DataError(f"{name}: the sha256 is not as in definitions.json")
    return out, parse


# check


def check_output(code: int, output: str) -> list[str]:
    """Return each problem of the cargo test run. No problem only if cargo
    gave exit code 0, the test passed, and the output has PASS_LINE."""
    problems = []
    if code != 0:
        problems.append(f"cargo test: exit code {code}")
    if f"test {TEST} ... ok" not in output:
        problems.append(f"the test {TEST} did not pass")
    if "test result: ok. 1 passed;" not in output:
        problems.append("cargo did not run exactly 1 passing test")
    if PASS_LINE not in output:
        problems.append(f"no line {PASS_LINE!r}")
    return problems


def check() -> int:
    folder, _ = build_inputs()
    env = {
        k: v for k, v in os.environ.items() if k not in ("RUST_LOG", "CARGO_TERM_COLOR")
    }
    env["CARGO_TERM_COLOR"] = "never"
    env[INPUTS_ENV] = str(folder)
    argv = ["cargo", "test", "--locked", "--test", "tree", "--", "--ignored", "--exact"]
    argv += [TEST, "--nocapture"]
    print("tree_check: $ " + " ".join(argv), flush=True)
    proc = subprocess.run(
        argv,
        cwd=ROOT,
        env=env,
        text=True,
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    sys.stdout.write(proc.stdout)
    problems = check_output(proc.returncode, proc.stdout)
    for p in problems:
        print(f"tree check: {p}")
    if problems:
        print(f"tree check: FAIL: {len(problems)} problems")
        return 1
    print(f"tree check: PASS: {PASS_LINE}")
    return 0


# measure


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


def git(*args: str) -> str:
    return run(["git", "-C", str(ROOT), *args]).stdout.strip()


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text("utf8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def ratio(a: float, b: float) -> float:
    return round(a / b, 4)


def derive(items: list[dict]) -> dict:
    """The totals and the ratios of the measured items."""
    totals = {
        "bytes": sum(i["bytes"] for i in items),
        "nodes": sum(i["nodes"] for i in items),
        "tree_heap_bytes": sum(i["tree_heap_bytes"] for i in items),
        "median_ns": {s: sum(i["median_ns"][s] for i in items) for s in STEPS},
        "memory": {
            s: {k: sum(i["memory"][s][k] for i in items) for k in MEMORY_KEYS}
            for s in STEPS
        },
    }
    t, m = totals["median_ns"], totals["memory"]
    per_input = [i["median_ns"]["convert"] / i["median_ns"]["parse"] for i in items]
    ratios = {
        "convert_over_parse_time": ratio(t["convert"], t["parse"]),
        "convert_over_lex_and_parse_time": ratio(t["convert"], t["lex"] + t["parse"]),
        "convert_over_parse_time_per_input": {
            "min": round(min(per_input), 4),
            "median": round(statistics.median(per_input), 4),
            "max": round(max(per_input), 4),
        },
        "convert_ns_per_node": round(t["convert"] / totals["nodes"], 1),
        "convert_over_parse_asked_bytes": ratio(
            m["convert"]["bytes"], m["parse"]["bytes"]
        ),
        "convert_over_parse_peak_bytes": ratio(
            m["convert"]["peak_bytes"], m["parse"]["peak_bytes"]
        ),
        "convert_over_parse_blocks": ratio(
            m["convert"]["blocks"], m["parse"]["blocks"]
        ),
        "tree_over_node_tree_bytes": ratio(
            totals["tree_heap_bytes"], m["parse"]["kept_bytes"]
        ),
    }
    return {"inputs": len(items), "totals": totals, "ratios": ratios}


def measure(runs: int) -> dict:
    folder, parse = build_inputs()
    large = sorted(n for n in parse if n.endswith("/large"))
    if len(large) != LARGE_INPUTS:
        raise DataError(f"{len(large)} large inputs, not {LARGE_INPUTS}")
    tool = build_tool()
    lines = "".join(f"{n.split('/')[0]}\t{folder / n}.sql\n" for n in large)
    LOCK.touch(exist_ok=True)
    with LOCK.open() as lock:
        print(
            f"tree_check: wait for the machine lock {LOCK}", file=sys.stderr, flush=True
        )
        fcntl.flock(lock, fcntl.LOCK_EX)
        out = run([str(tool), str(runs)], input=lines).stdout.splitlines()
    items = []
    for name, line in zip(large, out, strict=True):
        raw = json.loads(line)
        item = {"input": name, "sha256": parse[name]["sha256"]}
        for key in (
            "bytes",
            "nodes",
            "tree_heap_bytes",
            "median_ns",
            "min_ns",
            "memory",
        ):
            item[key] = raw[key]
        items.append(item)
    data = derive(items)
    data["items"] = items
    status = git(
        "status",
        "--porcelain",
        "--",
        "crates",
        "scripts/s3b/convert-cost",
        "Cargo.lock",
    )
    return {
        "kind": KIND,
        "about": (
            "The cost of the conversion from the parser tree (Node) to the SyntaxTree"
            " (sqll_syntax::from_node) on the 28 large S2 parse inputs, relative to the"
            " parse. Tool scripts/s3b/convert-cost: the sqll allocator and the sqll"
            " release profile; times are the medians of the runs of each step (ns);"
            " memory: the heap blocks, the asked bytes, the peak of the live bytes, and"
            " the kept bytes of one run of each step. parse kept_bytes is the Node tree."
            " convert includes the copy of the text."
        ),
        "command": f"{COMMAND} measure --runs {runs}",
        "commit": git("rev-parse", "HEAD"),
        "crates_clean": status == "",
        "rustc": run(["rustc", "-V"]).stdout.strip(),
        "machine": {"cpu": cpu_model(), "cpus": os.cpu_count(), "lock": str(LOCK)},
        "runs": runs,
        "data": data,
    }


# summary


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def summary_lines(doc: dict) -> list[str]:
    """The lines of status/S3b.md for the C7 conversion cost."""
    d = doc["data"]
    r, t = d["ratios"], d["totals"]
    p = r["convert_over_parse_time_per_input"]
    return [
        f"| Inputs | {d['inputs']} large S2 parse inputs, {t['bytes']} bytes, {t['nodes']} nodes |",
        f"| Conversion time / parse time | {pct(r['convert_over_parse_time'])}"
        f" (for each input: min {pct(p['min'])}, median {pct(p['median'])},"
        f" max {pct(p['max'])}) |",
        f"| Conversion time / (lex + parse) time | {pct(r['convert_over_lex_and_parse_time'])} |",
        f"| Conversion time for each node | {r['convert_ns_per_node']} ns |",
        f"| Conversion heap bytes / parse heap bytes | {pct(r['convert_over_parse_asked_bytes'])} |",
        f"| Conversion peak / parse peak | {pct(r['convert_over_parse_peak_bytes'])} |",
        f"| SyntaxTree bytes / Node tree bytes | {pct(r['tree_over_node_tree_bytes'])} |",
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="check the S2 parse inputs (cargo test)")
    m = sub.add_parser("measure", help="measure the conversion cost")
    m.add_argument("--runs", type=int, default=RUNS)
    sub.add_parser("summary", help="print the status lines of MEASURE_FILE")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "check":
            return check()
        if args.cmd == "measure":
            if args.runs < 1:
                raise DataError("--runs must be 1 or more")
            doc = measure(args.runs)
            MEASURE_FILE.write_text(json.dumps(doc, indent=1) + "\n", "utf8")
            print(f"wrote {MEASURE_FILE.relative_to(ROOT)}")
            print("\n".join(summary_lines(doc)))
            return 0
        doc = json.loads(MEASURE_FILE.read_text("utf8"))
        print("\n".join(summary_lines(doc)))
        return 0
    except DataError as exc:
        print(f"tree_check: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
