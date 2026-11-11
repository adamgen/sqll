"""sqll-harness s7 (run | merge | summarize | known-failures): the commands of
the S7 suites (docs/decisions/s7-tests-design.md, "Case runner", "Report",
"Known failures", and "CI").

s7 run: run the S7 suites through the tool binaries and write the S7 report.

It loads each case file and the exclusion list, and checks that a check
cites each assert of each converted source test or that a row of the
not-reproduced record has it (exit code 2 on an error). It checks the tools
(exit code 2 if a tool is not the pin), runs each case of each node of the
suites for each tool, writes the report (default out/s7-tests/report.json),
and runs scripts/check-submodule. Exit code 1 if the submodule changed, if
a --require-pass tool did not pass a node, or if the report is not the
--check file (only its suites and tools). With --known-failures DIR, exit
code 1 if the results are not the known failures of DIR (sqll_harness.s7_tests.
known).

s7 merge: merge the reports of the CI jobs (one for each suite and tool) into
one report, and check the known failures and the --expect matrix again.
s7 summarize: write the summary of a report of all suites and tools, and
compare it with the recorded summary (--check).
s7 known-failures: print the known-failures list of a tool from a report.

The heavy imports are in run(), so that the other harness commands do not
load the S7 modules.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..paths import REPO_ROOT, SQLFLUFF_ROOT
from .suites import SUITES, TOOLS, groups

DEFAULT_OUT = REPO_ROOT / "out" / "s7-tests" / "report.json"
DEFAULT_SUMMARY = REPO_ROOT / "out" / "s7-tests" / "summary.json"


def add_parser(sub: Any) -> None:
    """Add the s7 command to the subparsers of the harness CLI."""
    s7 = sub.add_parser(
        "s7",
        help="S7 suites: the sqlfluff CLI, config, and Python rule tests as "
        "black-box cases. See docs/decisions/s7-tests-design.md.",
    )
    s7_sub = s7.add_subparsers(dest="s7_command", required=True)
    run = s7_sub.add_parser(
        "run",
        help="Run the S7 suites through the tool binaries and write the S7 report.",
    )
    run.add_argument(
        "--suite",
        action="append",
        choices=list(SUITES),
        help="Suite to run. Repeat for more suites. Default: all S7 suites.",
    )
    run.add_argument(
        "--tool",
        action="append",
        choices=list(TOOLS),
        help="Tool to run. Repeat for more tools. Default: all S7 tools.",
    )
    run.add_argument("--jobs", type=int, default=4)
    run.add_argument("--out", type=Path, default=DEFAULT_OUT)
    run.add_argument(
        "--require-pass",
        action="append",
        default=[],
        choices=list(TOOLS),
        help="Exit code 1 if this tool does not pass each node.",
    )
    run.add_argument(
        "--check",
        type=Path,
        metavar="REPORT",
        help="Exit code 1 if the report is not this report, for the suites and "
        "tools of the run.",
    )
    run.add_argument(
        "--known-failures",
        type=Path,
        metavar="DIR",
        help="Exit code 1 if a node fails and is not in DIR/<tool>.txt, or if a "
        "listed node of a suite of the run passes or did not run.",
    )

    mrg = s7_sub.add_parser(
        "merge",
        help="Merge the S7 reports of the CI jobs into one report.",
    )
    mrg.add_argument("reports", nargs="+", type=Path)
    mrg.add_argument("--out", type=Path, default=DEFAULT_OUT)
    mrg.add_argument(
        "--expect",
        type=Path,
        metavar="MATRIX",
        help="The CI matrix (ci/matrix.d): each S7 suite and tool of it must "
        "be in the reports, and no other.",
    )
    mrg.add_argument(
        "--known-failures",
        type=Path,
        metavar="DIR",
        help="Exit code 1 if the merged results are not the known failures of DIR.",
    )

    summ = s7_sub.add_parser(
        "summarize",
        help="Write the summary of an S7 report of all suites and tools.",
    )
    summ.add_argument("report", type=Path)
    summ.add_argument("--out", type=Path, default=DEFAULT_SUMMARY)
    summ.add_argument(
        "--check",
        type=Path,
        metavar="SUMMARY",
        help="Exit code 1 if the summary is not this file.",
    )

    kf = s7_sub.add_parser(
        "known-failures",
        help="Print the known-failures list of a tool from an S7 report.",
    )
    kf.add_argument("report", type=Path)
    kf.add_argument("--tool", required=True, choices=list(TOOLS))


def main(args: argparse.Namespace) -> int:
    commands = {
        "run": run,
        "merge": merge,
        "summarize": summarize,
        "known-failures": show_known_failures,
    }
    return commands[args.s7_command](args)


def _known_failures(
    data: dict[str, Any], directory: Path, scope: dict[str, Any]
) -> int:
    """Print the differences from the known failures. 0: none; 1: some; 2: a
    list is not valid."""
    from . import known

    try:
        lines = known.check(data, directory, scope)
    except known.KnownFailuresError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    if lines:
        print(f"FAIL: the results are not the known failures of {directory}.")
        return 1
    print(f"The results are the known failures of {directory}.")
    return 0


def summary_lines(data: dict[str, Any]) -> list[str]:
    """The counts and the parity of a report, as text."""
    c = data["counts"]
    classes = ", ".join(f"{k} {v}" for k, v in c["excluded_by_class"].items())
    lines = [
        f"S7 suites: {' '.join(data['suites'])}",
        f"in scope {c['in_scope']}, converted {c['converted']}, excluded "
        f"{c['excluded']}, not yet converted {c['not_yet_converted']}, needs "
        f"Jinja (S11) {c['needs_jinja']}",
        f"excluded by class: {classes}",
    ]
    for tool, p in data["parity"].items():
        lines.append(
            f"{tool}: {p['passed']} of {p['nodes']} nodes passed, {p['failed']} "
            f"failed, {p['error']} error ({p['percent_of_converted']}% of "
            f"converted, {p['percent_of_in_scope']}% of in scope)"
        )
    return lines


def run(args: argparse.Namespace) -> int:
    from .. import tools as tool_checks
    from ..adapters import ADAPTERS
    from . import caseformat, oracle, report, runner

    tools = list(dict.fromkeys(args.tool or TOOLS))
    suites = sorted(set(args.suite or SUITES))
    missing = sorted(set(args.require_pass) - set(tools))
    if missing:
        print(
            f"error: --require-pass {missing} needs --tool {missing}", file=sys.stderr
        )
        return 2

    try:
        cases = caseformat.load()
    except caseformat.CaseFormatError as exc:
        for line in exc.errors:
            print(f"error: {line}", file=sys.stderr)
        return 2
    errors = oracle.coverage_errors(
        cases.nodes, SQLFLUFF_ROOT, oracle.load_not_reproduced()
    )
    for line in errors:
        print(f"error: {line}", file=sys.stderr)
    if errors:
        return 2

    bad = [i for i in tool_checks.check(tools) if not i.ok]
    for info in bad:
        for err in info.errors:
            print(f"error: {info.name}: {err}", file=sys.stderr)
    if bad:
        return 2
    adapters = {t: ADAPTERS[t]() for t in tools}
    versions = {t: a.version() for t, a in adapters.items()}

    keep = groups(suites)
    nodes = [n for n in cases.nodes if n.group in keep]
    results = runner.run_nodes(nodes, tools, args.jobs, adapters)
    data = report.build(cases, results, versions, suites)
    report.write(data, args.out)
    for line in summary_lines(data):
        print(line)
    print(f"report: {args.out}")

    status = 0
    check = subprocess.run(
        [str(REPO_ROOT / "scripts" / "check-submodule"), "after the S7 cases"],
        check=False,
    )
    if check.returncode != 0:
        status = 1
    if args.known_failures is not None:
        code = _known_failures(data, args.known_failures, cases.scope)
        if code == 2:
            return 2
        status = max(status, code)
    for tool in args.require_pass:
        bad_nodes = [
            n["id"] for n in data["nodes"] if n["results"][tool]["status"] != "pass"
        ]
        for node_id in bad_nodes:
            print(f"error: {tool} does not pass {node_id}", file=sys.stderr)
        if bad_nodes:
            status = 1
    if args.check is not None:
        try:
            recorded = json.loads(args.check.read_text(encoding="utf8"))
            report.check(recorded, cases.scope)
            want = report.select_suites(
                report.select_tools(recorded, tools), suites, cases.scope
            )
        except (OSError, ValueError, KeyError, report.ReportError) as exc:
            print(f"error: {args.check}: {exc}", file=sys.stderr)
            return 1
        if want != data:
            print(
                f"error: the report is not {args.check} for the suites {suites} "
                f"and the tools {tools}; compare it with {args.out}",
                file=sys.stderr,
            )
            status = 1
        else:
            print(f"The report is {args.check} for its suites and tools.")
    return status


def _expected(path: Path) -> set[tuple[str, str]]:
    """The S7 suites and tools of the CI matrix (ci/matrix.d). Each must have
    1 shard: the S7 runner has no shards."""
    from ..merge import MergeError, load_expected

    try:
        entries = load_expected(path, s7=True)
    except MergeError as exc:
        raise ValueError(str(exc)) from None
    bad = [f"{s}/{t}" for s, t, n in entries if n != 1]
    if bad:
        raise ValueError(f"{path}: an S7 entry must have 1 shard: {bad}")
    return {(s, t) for s, t, _ in entries}


def merge(args: argparse.Namespace) -> int:
    from . import caseformat, report

    try:
        cases = caseformat.load()
    except caseformat.CaseFormatError as exc:
        for line in exc.errors:
            print(f"error: {line}", file=sys.stderr)
        return 2
    try:
        parts = [
            (str(p), json.loads(p.read_text(encoding="utf8"))) for p in args.reports
        ]
        data = report.merge(parts, cases)
        if args.expect is not None:
            want = _expected(args.expect)
            got = {(s, t) for s in data["suites"] for t in data["tools"]}
            if got != want:
                raise ValueError(
                    f"the reports have the suites and tools {sorted(got)}, not "
                    f"those of {args.expect}: {sorted(want)}"
                )
    except (OSError, ValueError, KeyError, TypeError, report.ReportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report.write(data, args.out)
    print(f"merged {len(parts)} reports")
    for line in summary_lines(data):
        print(line)
    print(f"report: {args.out}")
    if args.known_failures is not None:
        return _known_failures(data, args.known_failures, cases.scope)
    return 0


def summarize(args: argparse.Namespace) -> int:
    from . import caseformat
    from . import summary as s7_summary

    try:
        data = json.loads(args.report.read_text(encoding="utf8"))
        result = s7_summary.summarize(data, caseformat.load_scope())
    except (OSError, ValueError, KeyError, TypeError, s7_summary.SummaryError) as exc:
        print(f"error: {args.report}: {exc}", file=sys.stderr)
        return 2
    if args.check is not None and args.check.resolve() == args.out.resolve():
        print(
            f"error: --out and --check are the same file ({args.check}).",
            file=sys.stderr,
        )
        return 2
    # Compare before the write, so that the check never reads the new file.
    lines = None if args.check is None else s7_summary.diff(result, args.check)
    s7_summary.write(result, args.out)
    print(s7_summary.text(result), end="")
    print(f"summary: {args.out}")
    if lines is None:
        return 0
    if lines:
        sys.stdout.writelines(lines)
        print(f"\nFAIL: {args.check} is not the summary of {args.report}.")
        return 1
    print(f"{args.check} is equal to the summary.")
    return 0


def show_known_failures(args: argparse.Namespace) -> int:
    from . import caseformat, known, report

    try:
        data = json.loads(args.report.read_text(encoding="utf8"))
        report.check(data, caseformat.load_scope())
    except (OSError, ValueError, KeyError, TypeError, report.ReportError) as exc:
        print(f"error: {args.report}: {exc}", file=sys.stderr)
        return 2
    if args.tool not in data["tools"]:
        print(f"error: {args.report} has no {args.tool} results", file=sys.stderr)
        return 2
    sys.stdout.write(known.render(data, args.tool))
    return 0
