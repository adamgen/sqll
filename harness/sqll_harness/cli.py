"""Command line: sqll-harness run | merge | tools | known-failures.

See harness/README.md.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import known_failures, merge, report, shard, tools
from .adapters import ADAPTERS, Adapter
from .adapters.base import Unsupported
from .cases import ERROR, FAIL, UNSUPPORTED, CaseResult
from .known_failures import Outcome
from .paths import DEFAULT_REPORT, KNOWN_FAILURES_DIR, SQLFLUFF_ROOT
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
    return p


def _sqlfluff_ref(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


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
    rep = report.build(_sqlfluff_ref(root), tool_infos, results, outcomes, scope)
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


def show_tools(args: argparse.Namespace) -> int:
    infos = tools.check(args.tool)
    out = {
        "tools_dir": str(tools.tools_dir()),
        "tools": [i.to_json() for i in infos],
    }
    print(json.dumps(out, indent=1))
    return 0 if all(i.ok for i in infos) else 1


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
    return 2


if __name__ == "__main__":
    sys.exit(main())
