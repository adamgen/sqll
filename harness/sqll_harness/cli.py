"""Command line: sqll-harness run | merge | tools | known-failures | summarize |
bench (inputs | reference | run | merge | check | compare).

See harness/README.md.
"""

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import known_failures, merge, report, shard, summary, tools
from .adapters import ADAPTERS, Adapter
from .adapters.base import Unsupported
from .bench import baseline as bench_baseline
from .bench import compare as bench_compare
from .bench import definitions as bench_definitions
from .bench import inputs as bench_inputs
from .bench import reference as bench_reference
from .bench import registry as bench_registry
from .bench import report as bench_report
from .bench import run as bench_run
from .bench.adapter import ConfigAbove
from .bench.inputs import SIZES as BENCH_SIZES
from .bench.timer import PROFILES as BENCH_PROFILES
from .cases import ERROR, FAIL, UNSUPPORTED, CaseResult
from .known_failures import Outcome
from .paths import (
    DEFAULT_REPORT,
    DEFAULT_SUMMARY,
    KNOWN_FAILURES_DIR,
    SQLFLUFF_ROOT,
    sqlfluff_ref,
)
from .suites import SUITES, runs_for


def _shard(text: str) -> shard.Shard:
    try:
        return shard.parse(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sqll-harness")
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run test suites through tool binaries.")
    run.add_argument(
        "--tool",
        action="append",
        choices=sorted(ADAPTERS),
        help="Tool to run. Repeat for more tools. Default: all tools.",
    )
    run.add_argument(
        "--suite",
        action="append",
        choices=sorted(SUITES),
        help="Suite to run. Repeat for more suites. Default: all suites.",
    )
    run.add_argument(
        "--jobs",
        type=int,
        default=os.process_cpu_count() or 1,
        help="Number of cases to run in parallel. Default: CPUs this process can use.",
    )
    run.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    run.add_argument(
        "--filter",
        help="Run only the cases whose id starts with this text.",
    )
    run.add_argument(
        "--shard",
        type=_shard,
        metavar="K/N",
        help="Run only shard K of N. The shard of a case depends on its id.",
    )
    run.add_argument("--known-failures", type=Path, default=KNOWN_FAILURES_DIR)
    run.add_argument("--sqlfluff-root", type=Path, default=SQLFLUFF_ROOT)

    mrg = sub.add_parser(
        "merge",
        help="Merge shard reports into one report and check known failures.",
    )
    mrg.add_argument("reports", nargs="+", type=Path, help="Reports of shard runs.")
    mrg.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    mrg.add_argument("--known-failures", type=Path, default=KNOWN_FAILURES_DIR)
    mrg.add_argument(
        "--expect",
        type=Path,
        help='JSON list of {"suite", "tool", "shards"}. Each must be in the reports.',
    )

    kfs = sub.add_parser(
        "known-failures",
        help="Print the known-failures file of a tool from a report.",
    )
    kfs.add_argument("report", type=Path)
    kfs.add_argument("--tool", required=True)
    kfs.add_argument(
        "--counts",
        action="store_true",
        help="Print the number of failures for each reason prefix and suite.",
    )

    smr = sub.add_parser(
        "summarize",
        help="Write the summary of a full-run report. Optionally compare it "
        "with a recorded summary.",
    )
    smr.add_argument("report", type=Path)
    smr.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_SUMMARY,
        help="File for the new summary. Default: out/summary.json.",
    )
    smr.add_argument(
        "--check",
        type=Path,
        metavar="SUMMARY",
        help="Fail if this file is not equal to the new summary. It must not "
        "be the --out file.",
    )

    tls = sub.add_parser(
        "tools",
        help="Print the installed tools as JSON. Fail if a tool is not as pinned.",
    )
    tls.add_argument(
        "--tool",
        action="append",
        choices=sorted(tools.CHECKS),
        help="Tool to check. Repeat for more tools. Default: all tools.",
    )
    bench = sub.add_parser("bench", help="S2 benchmarks. See harness/bench.md.")
    bench_sub = bench.add_subparsers(dest="bench_command", required=True)
    binp = bench_sub.add_parser(
        "inputs",
        help="Build the benchmark inputs and a manifest. Fail if an input is "
        "not as in the definitions.",
    )
    binp.add_argument(
        "--out",
        type=Path,
        default=bench_inputs.DEFAULT_OUT,
        help="Folder for the inputs. Not in the repository, except below out/. "
        "Default: out/bench/inputs.",
    )
    binp.add_argument("--sqlfluff-root", type=Path, default=SQLFLUFF_ROOT)
    binp.add_argument("--definitions", type=Path, default=bench_definitions.DEFINITIONS)
    binp.add_argument(
        "--write-definitions",
        action="store_true",
        help="Write the definitions of this build to the --definitions file "
        "instead of a check. The sqlfluff reference stays.",
    )
    bref = bench_sub.add_parser(
        "reference",
        help="Make the sqlfluff reference of the inputs (lint rule codes, and "
        "if fix changes the file). Fail if it is not the reference of the "
        "definitions.",
    )
    bref.add_argument("--sqlfluff-root", type=Path, default=SQLFLUFF_ROOT)
    bref.add_argument("--definitions", type=Path, default=bench_definitions.DEFINITIONS)
    bref.add_argument(
        "--jobs",
        type=int,
        default=os.process_cpu_count() or 1,
        help="Number of inputs to do in parallel. Default: CPUs this process can use.",
    )
    bref.add_argument(
        "--write",
        action="store_true",
        help="Write the new reference to the --definitions file instead of a check.",
    )
    brun = bench_sub.add_parser(
        "run",
        help="Run the benchmarks and write the report. Fail if a tool check "
        "fails or the report is not complete.",
    )
    brun.add_argument(
        "--tool",
        action="append",
        choices=bench_registry.names(),
        help="Tool to run. Repeat for more tools. Default: all tools.",
    )
    brun.add_argument(
        "--dialect",
        action="append",
        help="Dialect to run. Repeat for more dialects. Default: all dialects.",
    )
    brun.add_argument(
        "--command",
        action="append",
        dest="bench_commands",
        choices=bench_report.ALL_COMMANDS,
        help="Command to run. Repeat for more commands. Default: all commands.",
    )
    brun.add_argument(
        "--size",
        action="append",
        choices=list(BENCH_SIZES),
        help="Input size to run. Repeat for more sizes. Default: the sizes of "
        "the profile.",
    )
    brun.add_argument(
        "--profile",
        choices=sorted(BENCH_PROFILES),
        default="full",
        help="smoke: start and small, 1 timed run. full (default): all sizes, "
        "3 to 20 timed runs.",
    )
    brun.add_argument(
        "--shard",
        type=_bench_shard,
        metavar="K/N",
        help="Run only shard K of N. The dialects go to the shards in turn.",
    )
    brun.add_argument("--out", type=Path, default=bench_report.DEFAULT_REPORT)
    brun.add_argument("--sqlfluff-root", type=Path, default=SQLFLUFF_ROOT)
    brun.add_argument("--definitions", type=Path, default=bench_definitions.DEFINITIONS)
    bmrg = bench_sub.add_parser(
        "merge",
        help="Merge the reports of the shards of one benchmark run.",
    )
    bmrg.add_argument("reports", nargs="+", type=Path)
    bmrg.add_argument(
        "--expect",
        type=Path,
        metavar="MATRIX_JSON",
        help="Fail if the reports do not have the shard count of this file "
        '({"shards": N}, as ci/bench-matrix.json).',
    )
    bmrg.add_argument("--out", type=Path, default=bench_report.DEFAULT_REPORT)
    bchk = bench_sub.add_parser(
        "check",
        help="Check the schema and the completeness of a benchmark report.",
    )
    bchk.add_argument("report", type=Path)
    bchk.add_argument("--definitions", type=Path, default=bench_definitions.DEFINITIONS)
    bchk.add_argument(
        "--baseline",
        type=Path,
        metavar="BASELINE_JSON",
        help="Also fail if this file is not a full baseline, or if the stable "
        "data of the report (sqlfluff ref, tool versions and settings, inputs, "
        "and the status of each result) is not that of it. Timings are not "
        "compared.",
    )
    bcmp = bench_sub.add_parser(
        "compare",
        help="Compare 2 benchmark reports: flag each benchmark that is slower "
        "than the noise limit, and each status change. Also compare the tools "
        "of NEW. With one report, only compare its tools.",
    )
    bcmp.add_argument(
        "reports",
        nargs="+",
        type=Path,
        metavar="REPORT",
        help="BASE NEW, or only NEW.",
    )
    bcmp.add_argument(
        "--tool",
        action="append",
        help="Tool to compare. Repeat for more tools. Default: all tools.",
    )
    bcmp.add_argument("--out", type=Path, default=bench_compare.DEFAULT_OUT)
    return p


def _bench_shard(text: str) -> tuple[int, int]:
    try:
        return bench_run.parse_shard(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _run_one(suite, adapter: Adapter, case, root: Path) -> CaseResult:
    t0 = time.monotonic()
    try:
        result = suite.run(adapter, case, root)
    except Unsupported as exc:
        result = CaseResult(
            id=case.id,
            suite=suite.NAME,
            tool=adapter.name,
            status=FAIL,
            reason=f"{UNSUPPORTED}{exc.item}",
        )
    except Exception as exc:  # noqa: BLE001 - one bad case must not stop the run.
        result = CaseResult(
            id=case.id,
            suite=suite.NAME,
            tool=adapter.name,
            status=ERROR,
            reason=f"{type(exc).__name__}: {exc}",
        )
        if os.environ.get("SQLL_HARNESS_DEBUG"):
            traceback.print_exc()
    result.duration_ms = int((time.monotonic() - t0) * 1000)
    result.tags = list(getattr(case, "tags", ()))
    return result


def _finish(rep: dict, out: Path, outcomes: dict[str, Outcome]) -> int:
    report.write(rep, out)
    for line in report.summary_lines(rep):
        print(line)
    failed = False
    for tool, outcome in outcomes.items():
        for msg in outcome.messages(tool):
            print(msg)
        failed |= not outcome.ok
    print(f"report: {out}")
    if failed:
        print("FAIL: results differ from known_failures/.")
        return 1
    return 0


def run(args: argparse.Namespace) -> int:
    root: Path = args.sqlfluff_root.resolve()
    if not (root / "test" / "fixtures").is_dir():
        print(
            f"error: {root} has no fixtures. Run: git submodule update --init",
            file=sys.stderr,
        )
        return 2
    tool_names = args.tool or sorted(ADAPTERS)
    suites = args.suite or sorted(SUITES)
    checked = {i.name: i for i in tools.check(tool_names)}
    bad = [i for i in checked.values() if not i.ok]
    for info in bad:
        for err in info.errors:
            print(f"error: {info.name}: {err}", file=sys.stderr)
    if bad:
        return 2
    adapters = {name: ADAPTERS[name]() for name in tool_names}
    tool_infos = {
        name: report.tool_entry(a.version(), a.config_layer, checked[name].details)
        for name, a in adapters.items()
    }

    jobs = []
    for suite_name in suites:
        suite = SUITES[suite_name]
        cases = suite.discover(root)
        if args.filter:
            cases = [c for c in cases if c.id.startswith(args.filter)]
        cases = [c for c in cases if shard.contains(args.shard, c.id)]
        for adapter in adapters.values():
            if runs_for(suite, adapter.name):
                jobs += [(suite, adapter, c) for c in cases]

    print(f"running {len(jobs)} cases with {args.jobs} jobs", file=sys.stderr)
    results: list[CaseResult] = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(_run_one, s, a, c, root) for s, a, c in jobs]
        for i, f in enumerate(futures, 1):
            results.append(f.result())
            if i % 500 == 0:
                print(f"  {i}/{len(jobs)}", file=sys.stderr)

    complete = set() if args.filter else set(suites)
    # With no --suite and no --filter every case ran, so a listed id with an
    # unknown suite is also not found.
    every_case_ran = not args.suite and not args.filter
    outcomes = {}
    for tool in tool_names:
        known = known_failures.load(args.known_failures, tool)
        outcomes[tool] = known_failures.evaluate(
            [r for r in results if r.tool == tool],
            known,
            complete,
            every_case_ran=every_case_ran,
            shard=args.shard,
        )

    scope = report.scope(suites, tool_names, args.filter, args.shard)
    rep = report.build(sqlfluff_ref(root), tool_infos, results, outcomes, scope)
    return _finish(rep, args.out, outcomes)


def merge_reports(args: argparse.Namespace) -> int:
    try:
        expected = merge.load_expected(args.expect) if args.expect else None
        reports = [(str(p), merge.load(p)) for p in args.reports]
        rep, outcomes = merge.merge(
            reports, args.known_failures, sorted(SUITES), expected
        )
    except (merge.MergeError, known_failures.KnownFailuresError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"merged {len(reports)} reports")
    return _finish(rep, args.out, outcomes)


def show_known_failures(args: argparse.Namespace) -> int:
    rep = json.loads(args.report.read_text(encoding="utf8"))
    results = [CaseResult(**c) for c in rep["cases"] if c["tool"] == args.tool]
    if not args.counts:
        sys.stdout.write(known_failures.render(results))
        return 0
    counts = known_failures.prefix_counts(results)
    suites = sorted({s for by_suite in counts.values() for s in by_suite})
    print("| Reason prefix | " + " | ".join(suites) + " |")
    print("|---|" + "---|" * len(suites))
    for prefix, by_suite in counts.items():
        cells = " | ".join(str(by_suite.get(s, 0)) for s in suites)
        print(f"| {prefix} | {cells} |")
    return 0


def _same_file(a: Path, b: Path) -> bool:
    if a.resolve() == b.resolve():
        return True
    return a.exists() and b.exists() and os.path.samefile(a, b)


def summarize(args: argparse.Namespace) -> int:
    try:
        rep = json.loads(args.report.read_text(encoding="utf8"))
        result = summary.summarize(rep)
    except (OSError, ValueError, KeyError, TypeError, summary.SummaryError) as exc:
        print(f"error: {args.report}: {exc!r}", file=sys.stderr)
        return 2
    if args.check is not None and _same_file(args.out, args.check):
        print(
            f"error: --out and --check are the same file ({args.check}). "
            "Write the summary to a different file.",
            file=sys.stderr,
        )
        return 2
    # Compare before the write, so that the check never reads the new file.
    lines = None if args.check is None else summary.diff(result, args.check)
    summary.write(result, args.out)
    print(f"summary: {args.out}")
    if lines is None:
        return 0
    if lines:
        sys.stdout.writelines(lines)
        print(f"\nFAIL: {args.check} is not the summary of {args.report}.")
        return 1
    print(f"{args.check} is equal to the summary.")
    return 0


def show_tools(args: argparse.Namespace) -> int:
    infos = tools.check(args.tool)
    out = {
        "tools_dir": str(tools.tools_dir()),
        "tools": [i.to_json() for i in infos],
    }
    print(json.dumps(out, indent=1))
    return 0 if all(i.ok for i in infos) else 1


def bench_inputs_command(args: argparse.Namespace) -> int:
    root: Path = args.sqlfluff_root.resolve()
    problem = bench_inputs.check_out_dir(args.out, root)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2
    try:
        result = bench_inputs.build(root)
    except bench_inputs.BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    bench_inputs.write(result, args.out)
    sel = bench_inputs.manifest(result)["selection"]
    print(
        f"{len(result.inputs)} inputs in {args.out} "
        f"({sel['used']} of {sel['files']} fixture files)"
    )
    try:
        recorded = bench_definitions.load(args.definitions)
    except (OSError, ValueError) as exc:
        if not args.write_definitions:
            print(f"error: {args.definitions}: {exc}", file=sys.stderr)
            return 2
        recorded = {}
    if args.write_definitions:
        new = bench_definitions.make(result, recorded.get("reference"))
        args.definitions.write_text(bench_definitions.render(new), encoding="utf8")
        print(f"definitions: {args.definitions}")
        for line in bench_definitions.check_reference(new):
            print(f"warning: {line}")
        return 0
    errors = bench_definitions.check(recorded, result)
    errors += bench_definitions.check_reference(recorded)
    for line in errors:
        print(line)
    if errors:
        print(f"FAIL: the inputs are not as in {args.definitions}.")
        return 1
    print(f"The inputs are as in {args.definitions}.")
    return 0


def bench_reference_command(args: argparse.Namespace) -> int:
    root: Path = args.sqlfluff_root.resolve()
    try:
        defs = bench_definitions.load(args.definitions)
        result = bench_inputs.build(root)
    except (OSError, ValueError, bench_inputs.BuildError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    errors = bench_definitions.check(defs, result)
    if errors:
        for line in errors:
            print(line, file=sys.stderr)
        print(
            "error: the inputs are not those of the definitions. Run: "
            "sqll-harness bench inputs --write-definitions",
            file=sys.stderr,
        )
        return 2
    adapter = bench_registry.get(bench_definitions.REFERENCE_TOOL)
    with tempfile.TemporaryDirectory(prefix="sqll-bench-reference-") as tmp:
        bench_inputs.write(result, Path(tmp) / "inputs")
        try:
            new, failed = bench_reference.make(
                adapter, defs, Path(tmp) / "inputs", Path(tmp) / "work", args.jobs
            )
        except ConfigAbove as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    for line in failed:
        print(f"invalid: {line}")
    if failed:
        print(f"FAIL: {len(failed)} inputs have no valid {adapter.name} run.")
        return 1
    diffs = bench_reference.differences(defs.get("reference"), new)
    if args.write:
        defs["reference"] = new
        args.definitions.write_text(bench_definitions.render(defs), encoding="utf8")
        print(f"reference of {len(new['inputs'])} inputs: {args.definitions}")
        return 0
    for line in diffs:
        print(line)
    if diffs:
        print(f"FAIL: the reference is not that of {args.definitions}.")
        return 1
    print(f"The reference is that of {args.definitions}.")
    return 0


def _print_out(lines: list[str]) -> None:
    """Print lines on stdout. If the reader closes the pipe early (for
    example "| head"), discard the rest; the exit code does not change."""
    try:
        for line in lines:
            print(line)
        sys.stdout.flush()
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)


def _bench_summary(rep: dict, out: Path) -> list[str]:
    return [*bench_run.summary_lines(rep), f"report: {out}"]


def bench_run_command(args: argparse.Namespace) -> int:
    root: Path = args.sqlfluff_root.resolve()
    names = sorted(set(args.tool or bench_registry.names()))
    try:
        defs = bench_definitions.load(args.definitions)
        scope, benchmarks = bench_run.plan(
            defs,
            tools=names,
            profile=args.profile,
            dialects=args.dialect,
            commands=args.bench_commands,
            sizes=args.size,
            shard=args.shard,
        )
    except (OSError, ValueError, bench_run.RunError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    errors = bench_run.check_tools(names)
    for line in errors:
        print(f"error: {line}", file=sys.stderr)
    if errors:
        print("error: the tool check failed. Run: scripts/setup", file=sys.stderr)
        return 2
    adapters = [bench_registry.get(n) for n in names]
    print(
        f"running {len(benchmarks)} benchmarks for {len(names)} tools "
        f"({args.profile} profile)",
        file=sys.stderr,
    )
    with tempfile.TemporaryDirectory(prefix="sqll-bench-") as tmp:
        try:
            rep = bench_run.run(
                defs=defs,
                adapters=adapters,
                profile=args.profile,
                scope=scope,
                benchmarks=benchmarks,
                sqlfluff_root=root,
                work=Path(tmp),
                progress=bench_run.progress_to_stderr,
            )
        except (bench_run.RunError, ConfigAbove) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    try:
        bench_report.write(rep, args.out)
    except bench_report.ReportError as exc:
        print(f"error: the report has a schema error: {exc}", file=sys.stderr)
        return 1
    errors = bench_run.incomplete(rep, defs)
    fail = ["FAIL: the report is not complete for the scope of the run."]
    _print_out(_bench_summary(rep, args.out) + errors + (fail if errors else []))
    return 1 if errors else 0


def bench_merge_command(args: argparse.Namespace) -> int:
    try:
        shards = bench_run.expected_shards(args.expect) if args.expect else None
        reports = [(str(p), bench_report.load(p)) for p in args.reports]
        rep = bench_run.merge(reports, shards)
    except (OSError, ValueError, bench_run.MergeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    bench_report.write(rep, args.out)
    _print_out([f"merged {len(reports)} reports", *_bench_summary(rep, args.out)])
    return 0


def bench_check_command(args: argparse.Namespace) -> int:
    try:
        rep = bench_report.load(args.report)
        defs = bench_definitions.load(args.definitions)
        base = bench_report.load(args.baseline) if args.baseline else None
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    errors = bench_report.check(rep)
    if not errors:
        errors = bench_run.incomplete(rep, defs)
    if base is not None and not errors:
        errors = [f"baseline: {e}" for e in bench_baseline.recorded(base, defs)]
        if not errors:
            errors = bench_baseline.drift(rep, base)
    for line in errors:
        print(line)
    if errors:
        print(f"FAIL: {args.report} has {len(errors)} errors.")
        return 1
    print(f"{args.report}: no schema error; complete for its scope.")
    if base is not None:
        print(
            f"The stable data of {len(rep['results'])} results is that of the "
            f"baseline {args.baseline}."
        )
    return 0


def bench_compare_command(args: argparse.Namespace) -> int:
    if len(args.reports) > 2:
        print("error: give BASE NEW, or only NEW", file=sys.stderr)
        args.out.unlink(missing_ok=True)
        return 2
    try:
        loaded = [(str(p), bench_report.load(p)) for p in args.reports]
        result = bench_compare.compare(
            loaded[-1], loaded[0] if len(loaded) == 2 else None, args.tool
        )
    except (OSError, ValueError, bench_compare.CompareError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        # No old output must look like the result of this run.
        args.out.unlink(missing_ok=True)
        return 2
    bench_compare.write(result, args.out)
    lines = [*bench_compare.summary_lines(result), f"compare: {args.out}"]
    if not result["ok"]:
        c = result["counts"]
        lines.append(
            f"FAIL: {c[bench_compare.SLOWER]} slower, {c[bench_compare.FAILURE]} "
            "valid to not valid. Give the reason of each slowdown in the pull "
            "request body (PROCESS.md)."
        )
    _print_out(lines)
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        return run(args)
    if args.command == "merge":
        return merge_reports(args)
    if args.command == "tools":
        return show_tools(args)
    if args.command == "known-failures":
        return show_known_failures(args)
    if args.command == "summarize":
        return summarize(args)
    if args.command == "bench" and args.bench_command == "inputs":
        return bench_inputs_command(args)
    if args.command == "bench" and args.bench_command == "reference":
        return bench_reference_command(args)
    if args.command == "bench" and args.bench_command == "run":
        return bench_run_command(args)
    if args.command == "bench" and args.bench_command == "merge":
        return bench_merge_command(args)
    if args.command == "bench" and args.bench_command == "check":
        return bench_check_command(args)
    if args.command == "bench" and args.bench_command == "compare":
        return bench_compare_command(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
