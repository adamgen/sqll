# fail_on_parse_error_after_fix is a port of sqlfluff 4.4.0 code:
# test/conftest.py. Copyright (c) 2018-2026 Alan Cruickshank. MIT License.
# See THIRD_PARTY.md.
"""Shared code of the oracle scripts (scripts/sqlfluff-*-oracle).

An oracle runs a sqlfluff test through Python and compares the status of
each case with a harness report. Only the oracles import sqlfluff; the
harness must never do this. Run them with the Python of tools/sqlfluff-oracle.
"""

import json
from collections import Counter
from pathlib import Path

from sqlfluff.core import Linter
from sqlfluff.core.parser.segments.base import BaseSegment

ROOT = Path(__file__).resolve().parents[1]
SQLFLUFF_ROOT = ROOT / "third_party" / "sqlfluff"

# {case id: (status, reason)}
Results = dict[str, tuple[str, str]]

PREFIXES = {"expect_pass_": "pass", "expect_fail_": "fail"}


def fail_on_parse_error_after_fix() -> None:
    """Make 2 log functions raise ValueError, as sqlfluff test/conftest.py does.

    The autouse fixture of the same name sets this for each sqlfluff test.
    """

    def raise_error_apply_fixes_check_issue(message, *args):
        raise ValueError(message % args)

    def raise_error_conflicting_fixes_same_anchor(message: str):
        raise ValueError(message)

    BaseSegment._log_apply_fixes_check_issue = staticmethod(
        raise_error_apply_fixes_check_issue
    )
    Linter._report_conflicting_fixes_same_anchor = staticmethod(
        raise_error_conflicting_fixes_same_anchor
    )


def failure_reason(exc: BaseException) -> str:
    """Return the exception type and the first line of its message."""
    lines = str(exc).splitlines()
    return f"{type(exc).__name__}: {lines[0] if lines else ''}"


def write_results(oracle: Results, out: Path) -> None:
    """Write one JSON line for each case: {"id", "status", "reason"}."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(
            json.dumps({"id": case_id, "status": status, "reason": reason}) + "\n"
            for case_id, (status, reason) in oracle.items()
        ),
        encoding="utf8",
    )


def check_prefixes(oracle: Results) -> int:
    """Check the status of each case with a key prefix. Return the exit code.

    The key is the last part of the case id. The exit code is 1 if a status
    is different or no key has a prefix.
    """
    checked = 0
    wrong = []
    for case_id, (status, reason) in oracle.items():
        key = case_id.rsplit("/", 1)[-1]
        for prefix, want in PREFIXES.items():
            if key.startswith(prefix):
                checked += 1
                if status != want:
                    wrong.append(f"  {case_id}: {status}, expected {want} ({reason})")
    print(f"cases with a key prefix: {checked}, different status: {len(wrong)}")
    print("\n".join(wrong), end="\n" if wrong else "")
    return 1 if wrong or not checked else 0


def compare_with_report(oracle: Results, report: Path, suite: str, tool: str) -> int:
    """Compare the oracle with the results of one suite and tool in a report.

    Print the totals and each difference. Return 1 if a status is different
    or a case is only in one of the two, else 0.
    """
    data = json.loads(report.read_text(encoding="utf8"))
    harness = {
        c["id"]: c["status"]
        for c in data["cases"]
        if c["suite"] == suite and c["tool"] == tool
    }
    print(f"oracle cases: {len(oracle)}, harness cases: {len(harness)}")
    print(f"oracle: {dict(Counter(s for s, _ in oracle.values()))}")
    print(f"harness: {dict(Counter(harness.values()))}")
    only_oracle = sorted(set(oracle) - set(harness))
    only_harness = sorted(set(harness) - set(oracle))
    differ = sorted(i for i in set(oracle) & set(harness) if oracle[i][0] != harness[i])
    print(f"only in oracle: {len(only_oracle)} {only_oracle[:10]}")
    print(f"only in harness: {len(only_harness)} {only_harness[:10]}")
    print(f"different status: {len(differ)}")
    for i in differ:
        print(f"  {i}: oracle {oracle[i][0]} ({oracle[i][1]}), harness {harness[i]}")
    return 1 if only_oracle or only_harness or differ else 0
