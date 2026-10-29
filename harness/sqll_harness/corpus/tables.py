"""The Markdown tables of a corpus report for status/S9.md (T6).

markdown() gives 4 tables: the status counts of each tool; the totals over
the files where each tool is ok, with the ratios to sqlfluff; one row for
each file with a cell for each tool; and the reason of each result that is
not ok or unparsable (the cell of an unparsable result has its count and
bytes). "python -m sqll_harness.corpus tables REPORT" prints them.
"""

from collections.abc import Mapping
from typing import Any

from . import report

REASON_TEXT = 200
TOTALS_HEADER = "| Tool | Version | " + " | ".join(report.STATUSES) + " |"
COMPARED_HEADER = (
    "| Tool | Files | Bytes | Wall time (s) | CPU time (s) | Bytes per second "
    f"| Wall time ratio to {report.RATIO_BASE} "
    f"| CPU time ratio to {report.RATIO_BASE} |"
)
REASONS_HEADER = "| Tool | File | Status | Reason |"


def files_header(tools: list[str]) -> str:
    return "| File | Dialect | Bytes | " + " | ".join(tools) + " |"


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _table(header: str, rows: list[list[str]]) -> list[str]:
    rule = "|" + "---|" * (header.count("|") - 1)
    return [header, rule, *(_row(r) for r in rows)]


def _num(value: float | None, digits: int) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def cell(result: Mapping[str, Any]) -> str:
    """Return the file table cell of one result: the status (and the count
    and bytes of the unparsable segments, if any), the median wall time, and
    the bytes per second. Only a timed status has the numbers."""
    status = result["status"]
    if status not in report.TIMED_STATUSES:
        return status
    u = result["unparsable"]
    head = f"{status} {u['count']} ({u['bytes']} B)" if u["count"] else status
    wall = result["stats"]["wall_s"]["median"]
    return f"{head}, {wall:.3f} s, {_num(result['bytes_per_s'], 0)} B/s"


def reason_text(reason: str) -> str:
    """Return the reason as one table cell: one line, at most REASON_TEXT
    characters, in a code span."""
    text = " ".join(reason.split()).replace("`", "'")
    if len(text) > REASON_TEXT:
        text = text[: REASON_TEXT - 3] + "..."
    return "`" + text.replace("|", "\\|") + "`"


def markdown(rep: Mapping[str, Any]) -> str:
    """Return the 4 tables of a report with no schema error."""
    tools = list(rep["tools"])
    totals = [
        [tool, rep["tools"][tool]["version"]]
        + [str(rep["totals"][tool][s]) for s in report.STATUSES]
        for tool in tools
    ]
    c = rep["compared"]
    compared = [
        [
            tool,
            str(c["files"]),
            str(c["bytes"]),
            f"{t['wall_s']:.3f}",
            f"{t['cpu_s']:.3f}",
            _num(t["bytes_per_s"], 0),
            _num(t["wall_ratio"], 3),
            _num(t["cpu_ratio"], 3),
        ]
        for tool, t in c["results"].items()
    ]
    by_key = {(r["file"], r["tool"]): r for r in rep["results"]}
    files = [
        [f"`{name}`", record["dialect"], str(record["bytes"])]
        + [cell(by_key[(name, tool)]) for tool in tools]
        for name, record in rep["inputs"].items()
    ]
    reasons = [
        [r["tool"], f"`{r['file']}`", r["status"], reason_text(r["reason"])]
        for r in sorted(rep["results"], key=lambda r: (r["tool"], r["file"]))
        if r["status"] not in (report.OK, report.UNPARSABLE)
    ]
    blocks = [
        _table(TOTALS_HEADER, totals),
        _table(COMPARED_HEADER, compared),
        _table(files_header(tools), files),
        _table(REASONS_HEADER, reasons),
    ]
    return "\n\n".join("\n".join(b) for b in blocks) + "\n"
