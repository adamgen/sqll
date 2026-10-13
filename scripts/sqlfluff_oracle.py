# fail_on_parse_error_after_fix is a port of sqlfluff 4.4.0 code:
# test/conftest.py. Copyright (c) 2018-2026 Alan Cruickshank. MIT License.
# See THIRD_PARTY.md.
"""Shared code of the oracle scripts (scripts/sqlfluff-*-oracle).

An oracle runs a sqlfluff test through Python and compares the status of
each case with a harness report. Only the oracles import sqlfluff; the
harness must never do this. Run them with the Python of tools/sqlfluff-oracle,
or with --rust and the Python of tools/sqlfluff-rs-oracle.
"""

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

from sqlfluff.core import Linter
from sqlfluff.core.parser.segments.base import BaseSegment

ROOT = Path(__file__).resolve().parents[1]
SQLFLUFF_ROOT = ROOT / "third_party" / "sqlfluff"

# {case id: (status, reason)}
Results = dict[str, tuple[str, str]]

PREFIXES = {"expect_pass_": "pass", "expect_fail_": "fail"}

# The config layer of the sqlfluff-rs adapter
# (harness/sqll_harness/adapters/sqlfluff_rs.py).
RUST_CORE = {"use_rust_parser": True, "use_rust_rules": True}


def add_tool_arguments(parser: argparse.ArgumentParser) -> None:
    """Add --tool and --rust. The default tool is sqlfluff-rs with --rust."""
    parser.add_argument("--tool", help="Tool in the report. Default: see --rust.")
    parser.add_argument(
        "--rust",
        action="store_true",
        help="Use the Rust parser and rules, as the sqlfluff-rs adapter does.",
    )


def setup_tool(args: argparse.Namespace) -> Counter | None:
    """Set args.tool. With --rust, call force_rust and return its counter."""
    if args.tool is None:
        args.tool = "sqlfluff-rs" if args.rust else "sqlfluff"
    return force_rust() if args.rust else None


def force_rust() -> Counter:
    """Make sqlfluff use the Rust parser and rules for each test.

    Each FluffConfig gets RUST_CORE under the configs that the test gives, so
    a setting of the test does not change. The harness gives "error" for a
    case that sets one of these keys. Return a counter of the parse runs of
    each parser class: "RustParser" and "Parser" (Python).
    """
    try:
        import sqlfluffrs  # noqa: F401
    except ImportError as exc:
        sys.exit(f"error: --rust needs sqlfluffrs: {exc}")
    from sqlfluff.core.config import FluffConfig
    from sqlfluff.core.helpers.dict import nested_combine
    from sqlfluff.core.parser import Parser
    from sqlfluff.core.parser.rust_parser import RustParser

    if RustParser is None:
        sys.exit("error: --rust: the Rust parser of sqlfluff does not load")
    init = FluffConfig.__init__

    def rust_init(self, configs=None, *args, **kwargs):
        configs = nested_combine({"core": dict(RUST_CORE)}, configs or {})
        init(self, configs, *args, **kwargs)

    FluffConfig.__init__ = rust_init
    runs: Counter = Counter()
    for cls in (Parser, RustParser):

        def parse(self, *args, _parse=cls.parse, _name=cls.__name__, **kwargs):
            runs[_name] += 1
            return _parse(self, *args, **kwargs)

        cls.parse = parse
    return runs


def check_rust_runs(runs: Counter | None) -> int:
    """Print the parse runs of each parser. Return 1 if the Python parser ran
    or the Rust parser did not run, else 0. None (no --rust) gives 0."""
    if runs is None:
        return 0
    print(
        f"parse runs: RustParser {runs['RustParser']}, Parser {runs['Parser']}",
        file=sys.stderr,
    )
    if runs["Parser"] or not runs["RustParser"]:
        print(
            "error: --rust: the Python parser ran, or the Rust parser did not",
            file=sys.stderr,
        )
        return 1
    return 0


class CapLog:
    """The part of the pytest caplog fixture that the sqlfluff tests use."""

    def __init__(self) -> None:
        self._levels: dict[str, int] = {}

    def set_level(self, level: int, logger: str | None = None) -> None:
        log = logging.getLogger(logger)
        self._levels.setdefault(logger or "", log.level)
        log.setLevel(level)

    def restore(self) -> None:
        for name, level in self._levels.items():
            logging.getLogger(name or None).setLevel(level)
        self._levels.clear()


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
