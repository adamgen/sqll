"""Command line: sqll-harness run [--tool T] [--suite S] [--jobs N] [--out PATH]."""

import argparse
import os
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import known_failures, report
from .adapters import ADAPTERS, Adapter
from .cases import ERROR, CaseResult
from .paths import DEFAULT_REPORT, KNOWN_FAILURES_DIR, SQLFLUFF_ROOT
from .suites import SUITES


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
        default=os.cpu_count() or 1,
        help="Number of cases to run in parallel. Default: number of CPUs.",
    )
    run.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    run.add_argument(
        "--filter",
        help="Run only the cases whose id starts with this text.",
    )
    run.add_argument("--known-failures", type=Path, default=KNOWN_FAILURES_DIR)
    run.add_argument("--sqlfluff-root", type=Path, default=SQLFLUFF_ROOT)
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
    return result


def run(args: argparse.Namespace) -> int:
    root: Path = args.sqlfluff_root.resolve()
    if not (root / "test" / "fixtures").is_dir():
        print(
            f"error: {root} has no fixtures. Run: git submodule update --init",
            file=sys.stderr,
        )
        return 2
    tools = args.tool or sorted(ADAPTERS)
    suites = args.suite or sorted(SUITES)
    adapters = {name: ADAPTERS[name]() for name in tools}
    versions = {name: a.version() for name, a in adapters.items()}

    jobs = []
    for suite_name in suites:
        suite = SUITES[suite_name]
        cases = suite.discover(root)
        if args.filter:
            cases = [c for c in cases if c.id.startswith(args.filter)]
        for adapter in adapters.values():
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
    outcomes = {}
    for tool in tools:
        known = known_failures.load(args.known_failures, tool)
        known = {k: v for k, v in known.items() if k.split("/", 1)[0] in suites}
        outcomes[tool] = known_failures.evaluate(
            [r for r in results if r.tool == tool], known, complete
        )

    rep = report.build(_sqlfluff_ref(root), versions, results, outcomes)
    report.write(rep, args.out)
    for line in report.summary_lines(rep):
        print(line)
    failed = False
    for tool, outcome in outcomes.items():
        for msg in outcome.messages(tool):
            print(msg)
        failed |= not outcome.ok
    print(f"report: {args.out}")
    if failed:
        print("FAIL: results differ from known_failures/.")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        return run(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
