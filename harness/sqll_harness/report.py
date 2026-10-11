"""The machine-readable report: out/report.json. See harness/README.md."""

import json
from dataclasses import asdict
from pathlib import Path

from .cases import CaseResult
from .known_failures import Outcome


def summarize(results: list[CaseResult]) -> dict[str, dict[str, dict[str, int]]]:
    """Return {suite: {tool: {total, passed, failed, <check>...}}}."""
    summary: dict[str, dict[str, dict[str, int]]] = {}
    for r in results:
        s = summary.setdefault(r.suite, {}).setdefault(
            r.tool, {"total": 0, "passed": 0, "failed": 0}
        )
        s["total"] += 1
        s["passed" if r.passed else "failed"] += 1
        for name, ok in r.checks.items():
            s[name] = s.get(name, 0) + int(ok)
    return summary


def build(
    sqlfluff_ref: str,
    versions: dict[str, str],
    results: list[CaseResult],
    outcomes: dict[str, Outcome],
) -> dict:
    ordered = sorted(results, key=lambda r: (r.suite, r.tool, r.id))
    return {
        "sqlfluff_ref": sqlfluff_ref,
        "tools": {name: {"version": v} for name, v in sorted(versions.items())},
        "summary": summarize(ordered),
        "known_failures": {
            tool: {
                "new_failures": [r.id for r in o.new_failures],
                "unexpected_passes": o.unexpected_passes + o.not_found,
            }
            for tool, o in sorted(outcomes.items())
        },
        "cases": [asdict(r) for r in ordered],
    }


def write(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1) + "\n", encoding="utf8")


def summary_lines(report: dict) -> list[str]:
    lines = []
    for suite, tools in report["summary"].items():
        for tool, s in tools.items():
            extra = " ".join(
                f"{k}={v}"
                for k, v in s.items()
                if k not in {"total", "passed", "failed"}
            )
            pct = 100.0 * s["passed"] / s["total"] if s["total"] else 0.0
            lines.append(
                f"{suite}/{tool}: total={s['total']} passed={s['passed']} "
                f"failed={s['failed']} {extra} ({pct:.2f}% pass)".rstrip()
            )
    return lines
