"""The Markdown tables of a corpus report for status/S9.md (T6).

markdown() gives 4 tables: the status counts of each tool; the totals over
the files where each tool is ok, with the ratios to sqlfluff; one row for
each file with a cell for each tool; and the reason of each result that is
not ok or unparsable (the cell of an unparsable result has its count and
bytes). A report with pairs (report.py) also gives 2 tables: the totals of
each pair, and the slow files of each pair. "python -m sqll_harness.corpus
tables REPORT" prints them.
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
_T = report.PAIR_TOOL
PAIRS_HEADER = (
    "| Pair | Goal | Files | Bytes "
    f"| Wall time of {_T} (s) | Wall time of the other tool (s) | Wall time ratio "
    f"| CPU time of {_T} (s) | CPU time of the other tool (s) | CPU time ratio "
    "| Slow files |"
)
SLOW_HEADER = (
    "| Pair | File | Bytes "
    f"| Wall time of {_T} (s) | Wall time of the other tool (s) "
    f"| CPU time of {_T} (s) | CPU time of the other tool (s) |"
)
GOAL_TEXT = {
    report.FASTER: f"{_T} is faster",
    report.NOT_SLOWER: f"{_T} is not slower",
}


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
    """Return the tables of a report with no schema error."""
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
    if report.PAIRS in rep:
        blocks += pair_tables(rep[report.PAIRS])
    return "\n\n".join("\n".join(b) for b in blocks) + "\n"


def pair_tables(pairs: list[Mapping[str, Any]]) -> list[list[str]]:
    """Return the table of the pair totals and the table of the slow files."""
    totals, slow = [], []
    for p in pairs:
        me, other = p["tool"], p["other"]
        name = f"{me} to {other}"
        wall, cpu = p["wall_s"], p["cpu_s"]
        totals.append(
            [
                name,
                GOAL_TEXT[p["goal"]],
                str(p["files"]),
                str(p["bytes"]),
                f"{wall[me]:.3f}",
                f"{wall[other]:.3f}",
                _num(p["wall_ratio"], 3),
                f"{cpu[me]:.3f}",
                f"{cpu[other]:.3f}",
                _num(p["cpu_ratio"], 3),
                str(len(p["slow_files"])),
            ]
        )
        slow += [
            [
                name,
                f"`{s['file']}`",
                str(s["bytes"]),
                f"{s['wall_s'][me]:.3f}",
                f"{s['wall_s'][other]:.3f}",
                f"{s['cpu_s'][me]:.3f}",
                f"{s['cpu_s'][other]:.3f}",
            ]
            for s in p["slow_files"]
        ]
    return [_table(PAIRS_HEADER, totals), _table(SLOW_HEADER, slow)]
