"""The recorded summary of the S7 suites: results/S7-tests/summary.json
(docs/decisions/s7-tests-design.md, "Summary").

summarize() makes it from a report of all S7 suites and tools: the merged
report of the CI jobs, or the report of one run of all suites (scripts/verify).
CI and scripts/verify compare it with the recorded file, so the recorded
results cannot drift.
"""

import difflib
import json
from pathlib import Path
from typing import Any

from ..cases import PASS
from . import report as s7_report
from .suites import SUITES, TOOLS

KIND = "sqll-s7-tests-summary"
FORMAT = 1


class SummaryError(Exception):
    """The report cannot give a correct summary."""


def summarize(data: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    """The summary of a report of all S7 suites and tools."""
    try:
        s7_report.check(data, scope)
    except s7_report.ReportError as exc:
        raise SummaryError(str(exc)) from None
    if data["suites"] != sorted(SUITES):
        raise SummaryError(f"the report has the suites {data['suites']}, not all")
    if list(data["tools"]) != list(TOOLS):
        raise SummaryError(f"the report has the tools {list(data['tools'])}, not all")
    by_suite = {}
    for suite in data["suites"]:
        part = s7_report.select_suites(data, [suite], scope)
        c = part["counts"]
        by_suite[suite] = {
            "in_scope": c["in_scope"],
            "converted": c["converted"],
            "excluded": c["excluded"],
            "not_yet_converted": c["not_yet_converted"],
            "needs_jinja": c["needs_jinja"],
            "parity": part["parity"],
        }
    return {
        "kind": KIND,
        "format": FORMAT,
        "sqlfluff": data["sqlfluff"],
        "suites": data["suites"],
        "tools": data["tools"],
        "counts": data["counts"],
        "parity": data["parity"],
        "s11_jinja": data["s11_jinja"],
        "suite_results": by_suite,
        "known_failures": {
            t: sum(n["results"][t]["status"] != PASS for n in data["nodes"])
            for t in data["tools"]
        },
    }


def text(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=1) + "\n"


def write(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text(summary), encoding="utf8")


def diff(summary: dict[str, Any], recorded: Path) -> list[str]:
    """The lines of a unified diff from the recorded file to the summary.
    No line: they are equal. A missing file is an empty file."""
    try:
        old = recorded.read_text(encoding="utf8")
    except OSError:
        old = ""
    return list(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            text(summary).splitlines(keepends=True),
            str(recorded),
            "summary",
        )
    )
