"""sqll-harness s7 run: run the S7 suites through the tool binaries and write
the S7 report (docs/decisions/s7-tests-design.md, "Case runner" and
"Report").

It loads each case file and the exclusion list, and checks that a check
cites each assert of each converted source test or that a row of the
not-reproduced record has it (exit code 2 on an error). It checks the tools
(exit code 2 if a tool is not the pin), runs each case of each node of the
suites for each tool, writes the report (default out/s7-tests/report.json),
and runs scripts/check-submodule. Exit code 1 if the submodule changed, if
a --require-pass tool did not pass a node, or if the report is not the
--check file (only its suites and tools).

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
