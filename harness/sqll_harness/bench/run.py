"""Run the benchmarks and merge shard reports (harness/bench.md; the
commands are in harness/README.md, "Benchmark runs").

plan() gives the benchmarks of a scope, in the order of the definitions.
run() runs them one at a time. For each benchmark, the tools run in turn
for each repeat (timer.run_in_turn), so that drift has the same effect on
each tool. All benchmarks of a dialect are in the same shard, so the
validity checks of one input are done in one run.
"""

import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from statistics import median
from typing import Any

from .. import paths
from .. import tools as s1_tools
from . import definitions as bench_definitions
from . import inputs as bench_inputs
from . import report
from .adapter import BenchAdapter, BenchJob, Context
from .inputs import SIZES
from .timer import (
    ERROR,
    PROFILES,
    STATUSES,
    VALID,
    Measurement,
    overhead,
    run_in_turn,
)

PROFILE_SIZES = {"smoke": ("small",), "full": tuple(SIZES)}
REASON_TEXT = 160


class RunError(Exception):
    """The run cannot start: a bad scope, or inputs that are not those of
    the definitions."""


class MergeError(Exception):
    """The reports cannot be merged into a correct report."""


def parse_shard(text: str | None) -> tuple[int, int] | None:
    if text is None:
        return None
    m = report.SHARD.fullmatch(text)
    if m is None or not 1 <= int(m[1]) <= int(m[2]):
        raise ValueError(f"shard must be K/N with 1 <= K <= N: {text!r}")
    return int(m[1]), int(m[2])


def in_shard(dialect: str, dialects: list[str], shard: tuple[int, int] | None) -> bool:
    """The dialects of the scope, in sorted order, go to the shards in turn:
    dialect i (from 0) is in shard i % N + 1."""
    if shard is None:
        return True
    k, n = shard
    return sorted(dialects).index(dialect) % n + 1 == k


def expected(scope: Mapping[str, Any]) -> list[dict]:
    """Return the benchmarks of a report scope (and its shard), in the order
    of the definitions."""
    dialects = sorted(set(scope["dialects"]))
    shard = parse_shard(scope["shard"])
    commands, sizes = set(scope["commands"]), set(scope["sizes"])
    return [
        b
        for b in bench_definitions.benchmarks(dialects)
        if b["command"] in commands
        and (b["size"] is None or b["size"] in sizes)
        and in_shard(b["dialect"], dialects, shard)
    ]


def plan(
    defs: Mapping[str, Any],
    *,
    tools: list[str],
    profile: str,
    dialects: list[str] | None = None,
    commands: list[str] | None = None,
    sizes: list[str] | None = None,
    shard: tuple[int, int] | None = None,
) -> tuple[dict, list[dict]]:
    """Return the report scope and its benchmarks. RunError for a dialect,
    command, or size that the definitions or the profile do not have."""
    known = sorted({b["dialect"] for b in defs["benchmarks"]})
    unknown = sorted(set(dialects or []) - set(known))
    if unknown:
        raise RunError(f"the definitions have no dialect {', '.join(unknown)}")
    unknown = sorted(set(commands or []) - set(report.ALL_COMMANDS))
    if unknown:
        raise RunError(f"unknown command {', '.join(unknown)}")
    allowed = PROFILE_SIZES[profile]
    outside = sorted(set(sizes or []) - set(allowed))
    if outside:
        raise RunError(
            f"size {', '.join(outside)} is not in the {profile} profile "
            f"(sizes: {', '.join(allowed)})"
        )
    if not tools:
        raise RunError("no tool")
    scope = report.scope(
        tools,
        sorted(set(dialects or known)),
        commands or report.ALL_COMMANDS,
        sizes or allowed,
        shard,
    )
    benchmarks = expected(scope)
    in_defs = {b["id"]: b for b in defs["benchmarks"]}
    missing = [b["id"] for b in benchmarks if in_defs.get(b["id"]) != b]
    if missing:
        raise RunError(f"not in the definitions: {', '.join(missing)}")
    return scope, benchmarks


def check_tools(names: list[str]) -> list[str]:
    """Return the errors of the S1 tool check ("sqll-harness tools") of these
    tools. A tool with no check is an error."""
    errors = [f"{n}: no tool check" for n in names if n not in s1_tools.CHECKS]
    known = [n for n in names if n in s1_tools.CHECKS]
    for info in s1_tools.check(known) if known else []:
        errors += [f"{info.name}: {e}" for e in info.errors]
    return errors


def build_inputs(sqlfluff_root: Path, defs: Mapping[str, Any], out: Path) -> None:
    """Build the inputs into out. RunError if they are not those of the
    definitions, or if the definitions have no complete sqlfluff reference."""
    try:
        built = bench_inputs.build(sqlfluff_root)
    except bench_inputs.BuildError as exc:
        raise RunError(str(exc)) from None
    errors = bench_definitions.check(defs, built)
    errors += bench_definitions.check_reference(defs)
    if errors:
        raise RunError(
            "the inputs are not those of the definitions: " + "; ".join(errors[:5])
        )
    bench_inputs.write(built, out)


def _one(
    benchmark: dict, adapters: list[BenchAdapter], ctx: Context, policy
) -> list[dict]:
    jobs: list[BenchJob] = [a.job(benchmark, ctx) for a in adapters]
    runnable = [bj for bj in jobs if bj.job is not None]
    measured = run_in_turn([bj.series(policy) for bj in runnable])
    by_tool: dict[str, Measurement] = {}
    for bj, m in zip(runnable, measured, strict=True):
        bj.finish(m)
        by_tool[bj.tool] = m
    return [
        report.result_entry(
            benchmark, bj.tool, by_tool.get(bj.tool) or bj.not_run(), bj.work
        )
        for bj in jobs
    ]


def run_benchmarks(
    benchmarks: list[dict],
    adapters: list[BenchAdapter],
    ctx: Context,
    profile: str,
    progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Run the benchmarks one at a time. Return one result entry for each
    benchmark and tool. A harness error in one benchmark gives the status
    error for each tool of it; the run continues."""
    policy = PROFILES[profile]
    adapters = sorted(adapters, key=lambda a: a.name)
    results = []
    for i, b in enumerate(benchmarks, 1):
        try:
            entries = _one(b, adapters, ctx, policy)
        except Exception as exc:  # noqa: BLE001 - one benchmark must not stop the run.
            m = Measurement(ERROR, f"harness error: {exc!r}", [], None)
            entries = [report.result_entry(b, a.name, m) for a in adapters]
        results += entries
        if progress:
            progress(f"[{i}/{len(benchmarks)}] {b['id']}: " + _brief(entries))
    return results


def _brief(entries: list[dict]) -> str:
    parts = []
    for r in entries:
        if r["status"] == VALID:
            parts.append(f"{r['tool']} {r['stats']['wall_s']['median']:.3f} s")
        else:
            parts.append(f"{r['tool']} {r['status']}")
    return ", ".join(parts)


def run(
    *,
    defs: Mapping[str, Any],
    adapters: list[BenchAdapter],
    profile: str,
    scope: dict,
    benchmarks: list[dict],
    sqlfluff_root: Path,
    work: Path,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Build the inputs in work, run the benchmarks, and return the report.
    RunError if the inputs are not those of the definitions; ConfigAbove if
    a tool can read a config file above work."""
    inputs_dir = work / "inputs"
    build_inputs(sqlfluff_root, defs, inputs_dir)
    ctx = Context(defs, inputs_dir, work / "runs", PROFILES[profile].timeout_s)
    timer_entry = overhead(work / "overhead")
    results = run_benchmarks(benchmarks, adapters, ctx, profile, progress)
    used = sorted({b["input"] for b in benchmarks})
    return report.build(
        sqlfluff_ref=paths.sqlfluff_ref(sqlfluff_root),
        profile=profile,
        machine=report.machine(),
        harness=report.harness(),
        timer=timer_entry,
        scope=scope,
        tools={
            a.name: {"version": a.version(), "settings": a.config(None)}
            for a in adapters
        },
        inputs={n: _input_record(defs["inputs"][n]) for n in used},
        results=results,
    )


def _input_record(entry: Mapping[str, Any]) -> dict:
    return {k: entry[k] for k in report.INPUT}


# Completeness.


def incomplete(rep: Mapping[str, Any], defs: Mapping[str, Any] | None = None):
    """Return each error of completeness: the report must have exactly one
    result for each benchmark of its scope and each tool, and exactly the
    inputs of these benchmarks. With defs, each input record must be that of
    the definitions. Call it on a report with no schema error."""
    scope = rep["scope"]
    want = expected(scope)
    errors = []
    ids = [b["id"] for b in want]
    for tool in scope["tools"]:
        have = [r["id"] for r in rep["results"] if r["tool"] == tool]
        missing = sorted(set(ids) - set(have))
        extra = sorted(set(have) - set(ids))
        if missing:
            errors.append(f"{tool}: no result for {len(missing)}: {_few(missing)}")
        if extra:
            errors.append(f"{tool}: results not in the scope: {_few(extra)}")
    used = {b["input"] for b in want}
    if set(rep["inputs"]) != used:
        errors.append(
            f"inputs: missing {_few(sorted(used - set(rep['inputs'])))}, "
            f"extra {_few(sorted(set(rep['inputs']) - used))}"
        )
    if defs is not None:
        for name, entry in sorted(rep["inputs"].items()):
            want_entry = defs["inputs"].get(name)
            if want_entry is None or _input_record(want_entry) != entry:
                errors.append(f"input {name}: not that of the definitions")
    return errors


def _few(items: list[str], n: int = 5) -> str:
    text = ", ".join(items[:n])
    return text + (f" and {len(items) - n} more" if len(items) > n else "")


# Merge.


def _scope_without_shard(scope: Mapping[str, Any]) -> dict:
    return {**scope, "shard": None}


def merge(reports: list[tuple[str, dict]]) -> dict:
    """Merge (name, report) pairs of the shard runs of one scope. MergeError
    if a report has a schema error or is not complete, if a shard is missing
    or repeated, or if 2 reports have a different run record (sqlfluff ref,
    harness, profile, scope, a tool, or an input)."""
    if not reports:
        raise MergeError("no reports to merge")
    for name, rep in reports:
        errors = report.check(rep)
        if errors:
            raise MergeError(f"{name}: schema error: {'; '.join(errors[:3])}")
        if rep["parts"] is not None:
            raise MergeError(f"{name}: a merged report cannot be merged again")
        errors = incomplete(rep)
        if errors:
            raise MergeError(f"{name}: not complete: {'; '.join(errors[:3])}")
    first_name, first = reports[0]
    for name, rep in reports[1:]:
        for key in ("sqlfluff_ref", "harness", "profile"):
            if rep[key] != first[key]:
                raise MergeError(f"{name}: {key} differs from {first_name}")
        if _scope_without_shard(rep["scope"]) != _scope_without_shard(first["scope"]):
            raise MergeError(f"{name}: the scope differs from {first_name}")
        if set(rep["tools"]) != set(first["tools"]):
            raise MergeError(f"{name}: the tools differ from {first_name}")
        for tool, record in rep["tools"].items():
            if record != first["tools"][tool]:
                raise MergeError(f"{name}: the record of tool {tool} differs")

    shards: dict[int, tuple[str, dict]] = {}
    counts = set()
    for name, rep in reports:
        k, n = parse_shard(rep["scope"]["shard"]) or (1, 1)
        counts.add(n)
        if k in shards:
            raise MergeError(f"shard {k}/{n} is in {shards[k][0]} and {name}")
        shards[k] = (name, rep)
    if len(counts) != 1:
        raise MergeError(f"the reports have different shard counts: {sorted(counts)}")
    n = counts.pop()
    missing = [f"{k}/{n}" for k in range(1, n + 1) if k not in shards]
    if missing:
        raise MergeError(f"no report for shard {', '.join(missing)}")

    inputs: dict[str, dict] = {}
    results: list[dict] = []
    parts = []
    for k in range(1, n + 1):
        name, rep = shards[k]
        for input_name, record in rep["inputs"].items():
            if inputs.setdefault(input_name, record) != record:
                raise MergeError(f"{name}: the record of input {input_name} differs")
        results += rep["results"]
        parts.append(
            {"shard": f"{k}/{n}", "machine": rep["machine"], "timer": rep["timer"]}
        )
    merged = report.build(
        sqlfluff_ref=first["sqlfluff_ref"],
        profile=first["profile"],
        machine=parts[0]["machine"],
        harness=first["harness"],
        timer=parts[0]["timer"],
        scope=_scope_without_shard(first["scope"]),
        tools=first["tools"],
        inputs=inputs,
        results=results,
        parts=parts,
    )
    errors = report.check(merged) or incomplete(merged)
    if errors:
        raise MergeError(f"the merged report is not correct: {'; '.join(errors[:3])}")
    return merged


# Text summary.


def summary_lines(rep: Mapping[str, Any]) -> list[str]:
    """Return a short text summary of a report."""
    scope = rep["scope"]
    tools = list(rep["tools"])
    ids = {r["id"] for r in rep["results"]}
    shard = f", shard {scope['shard']}" if scope["shard"] else ""
    parts = f", {len(rep['parts'])} parts" if rep["parts"] else ""
    lines = [
        f"profile {rep['profile']}: {len(ids)} benchmarks, {len(tools)} tools, "
        f"{len(scope['dialects'])} dialects{shard}{parts}"
    ]
    width = max(len(t) for t in tools) if tools else 4
    lines.append(
        f"{'tool':<{width}}  {'version':<10}"
        + "".join(f"{s:>12}" for s in STATUSES)
        + f"{'wall_s':>12}"
    )
    for tool in tools:
        t = rep["totals"][tool]
        lines.append(
            f"{tool:<{width}}  {rep['tools'][tool]['version']:<10}"
            + "".join(f"{t[s]:>12}" for s in STATUSES)
            + f"{t['wall_s']:>12.3f}"
        )
    others = [t for t in tools if t != report.RATIO_BASE]
    if report.RATIO_BASE in tools and others:
        lines.append(
            f"wall time ratio to {report.RATIO_BASE}: median of the valid "
            "benchmarks (count)"
        )
        for command in scope["commands"]:
            cells = []
            for tool in others:
                values = [
                    r["ratio"]["wall"]
                    for r in rep["results"]
                    if r["tool"] == tool
                    and r["command"] == command
                    and r["ratio"] is not None
                    and r["ratio"]["wall"] is not None
                ]
                cell = f"{median(values):.3f} ({len(values)})" if values else "-"
                cells.append(f"{tool} {cell}")
            lines.append(f"  {command:<6} " + ", ".join(cells))
    for p in rep["pairs"]:
        a, b = p["tools"]
        ratio = "-" if p["wall_ratio"] is None else f"{p['wall_ratio']:.3f}"
        lines.append(
            f"pair {a} / {b}: wall {ratio} on {p['benchmarks']} benchmarks "
            f"({p['skipped']} skipped)"
        )
    bad = [r for r in rep["results"] if r["status"] != VALID]
    if bad:
        lines.append(f"not valid: {len(bad)}")
        for r in bad:
            reason = (r["reason"] or "").replace("\n", " ")
            if not reason.startswith(f"{r['status']}: "):
                reason = f"{r['status']}: {reason}"
            if len(reason) > REASON_TEXT:
                reason = reason[: REASON_TEXT - 3] + "..."
            lines.append(f"  {r['tool']} {r['id']}: {reason}")
    return lines


def progress_to_stderr(line: str) -> None:
    print(line, file=sys.stderr, flush=True)
