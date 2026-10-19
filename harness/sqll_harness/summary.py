"""The recorded summary of a full run: results/s1/summary.json.

summarize() makes it from out/report.json. CI makes it from the merged report
and compares it with the committed file, so the recorded results cannot
drift. See "Summary" in harness/README.md.
"""

import difflib
import json
from pathlib import Path

from .adapters import ADAPTERS
from .cases import ERROR, FAIL, PASS, SKIP
from .suites import SUITES, runs_for

FORMAT = 1
# The suites that give the parity number. code_only is a check of the harness.
PARITY_SUITES = ("dialects", "rules", "autofix", "templater")
# Tags that each suite entry has, also with the count 0.
TAGS = ("needs_python",)
STATUS_KEYS = {PASS: "passed", FAIL: "failed", ERROR: "error", SKIP: "skipped"}
KNOWN_FAILURE_KEYS = ("new_failures", "unexpected_passes")


class SummaryError(Exception):
    """The report cannot give a correct summary."""


def _check_full_run(report: dict) -> None:
    """Raise SummaryError if the report is not of a full run.

    A run report must have no filter and no shard. A merged report has no
    scope; each of its parts must have no filter. merge makes sure that each
    shard is there one time.
    """
    scope = report.get("scope")
    if scope is None:
        parts = report.get("parts")
        if not parts:
            raise SummaryError("the report has no scope and no parts")
        if any(p.get("filter") for p in parts):
            raise SummaryError("a part of the merged report used a filter")
        return
    if scope.get("filter"):
        raise SummaryError(f"the run used the filter {scope['filter']!r}")
    if scope.get("shard"):
        raise SummaryError(f"the report is of shard {scope['shard']} only")


def _suite_entry(cases: list[dict]) -> dict:
    entry: dict = {"total": len(cases)}
    entry.update({key: 0 for key in STATUS_KEYS.values()})
    checks: dict[str, int] = {}
    tags: dict[str, dict[str, int]] = {t: {"total": 0, "passed": 0} for t in TAGS}
    for case in cases:
        status = case["status"]
        if status not in STATUS_KEYS:
            raise SummaryError(f"{case['id']}: unknown status {status!r}")
        entry[STATUS_KEYS[status]] += 1
        for name, ok in case.get("checks", {}).items():
            checks[name] = checks.get(name, 0) + int(bool(ok))
        for tag in case.get("tags", []):
            counts = tags.setdefault(tag, {"total": 0, "passed": 0})
            counts["total"] += 1
            counts["passed"] += int(status == PASS)
    entry["checks"] = dict(sorted(checks.items()))
    entry["tags"] = dict(sorted(tags.items()))
    return entry


def _known_failures_outcome(report: dict, tool: str) -> dict:
    """Return the known-failure check result of a tool in the report.

    Raise SummaryError if the result or one of its lists is missing: then the
    report does not show that the check ran.
    """
    outcome = report.get("known_failures", {}).get(tool)
    if not isinstance(outcome, dict):
        raise SummaryError(f"the report has no known-failure check result for {tool}")
    for key in KNOWN_FAILURE_KEYS:
        if not isinstance(outcome.get(key), list):
            raise SummaryError(f"known-failure check result of {tool}: no {key} list")
    return outcome


def full_run_pairs() -> set[tuple[str, str]]:
    """Return each (suite, tool) pair of a full run."""
    return {
        (name, tool)
        for name, suite in SUITES.items()
        for tool in ADAPTERS
        if runs_for(suite, tool)
    }


def summarize(report: dict, pairs: set[tuple[str, str]] | None = None) -> dict:
    """Return the summary of a full-run report.

    The report must have cases for each (suite, tool) pair in pairs (default:
    full_run_pairs()) and for no other pair, and each case one time.

    For each tool and suite: total and the number of cases with each status
    (passed, failed, error, skipped; their sum is total), the number of
    cases where each check is true, and for each tag the number of cases and
    of passed cases. parity is the sum of total and passed over
    PARITY_SUITES.
    """
    _check_full_run(report)
    by_tool: dict[str, dict[str, list[dict]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for case in report["cases"]:
        key = (case["suite"], case["tool"], case["id"])
        if key in seen:
            raise SummaryError(
                f"case {case['tool']} {case['id']} is in the report 2 times"
            )
        seen.add(key)
        by_tool.setdefault(case["tool"], {}).setdefault(case["suite"], []).append(case)
    want = full_run_pairs() if pairs is None else pairs
    got = {(suite, tool) for suite, tool, _ in seen}
    if got != want:
        missing = ", ".join(f"{s}/{t}" for s, t in sorted(want - got)) or "none"
        extra = ", ".join(f"{s}/{t}" for s, t in sorted(got - want)) or "none"
        raise SummaryError(f"not a full run: missing {missing}; not expected {extra}")
    if set(by_tool) != set(report["tools"]):
        raise SummaryError(
            f"tools with cases {sorted(by_tool)} are not the report tools "
            f"{sorted(report['tools'])}"
        )
    results = {}
    for tool in sorted(by_tool):
        suites = {s: _suite_entry(c) for s, c in sorted(by_tool[tool].items())}
        parity = [suites[s] for s in PARITY_SUITES if s in suites]
        outcome = _known_failures_outcome(report, tool)
        results[tool] = {
            "parity": {
                "suites": [s for s in PARITY_SUITES if s in suites],
                "total": sum(e["total"] for e in parity),
                "passed": sum(e["passed"] for e in parity),
            },
            "known_failures_check": {
                key: len(outcome[key]) for key in KNOWN_FAILURE_KEYS
            },
            "suites": suites,
        }
    return {
        "format": FORMAT,
        "sqlfluff_ref": report["sqlfluff_ref"],
        "tools": {t: report["tools"][t] for t in sorted(report["tools"])},
        "results": results,
    }


def render(summary: dict) -> str:
    return json.dumps(summary, indent=1, ensure_ascii=False) + "\n"


def write(summary: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(summary), encoding="utf8")


def diff(summary: dict, path: Path) -> list[str]:
    """Return the unified diff from the file at path to the summary.

    The list is empty if the file has the same text.
    """
    try:
        old = path.read_text(encoding="utf8")
    except OSError as exc:
        return [f"cannot read {path}: {exc}"]
    new = render(summary)
    return list(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=str(path),
            tofile="summary of the report",
        )
    )
