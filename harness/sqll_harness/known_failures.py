"""Known failures: known_failures/<tool>.txt.

Format: one case id on each line, sorted, with no duplicates. Text after
"#" is the reason. Blank lines are ignored.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import shard as shards
from .cases import UNSUPPORTED, CaseResult


class KnownFailuresError(Exception):
    """The known-failures file is not valid."""


def parse(text: str, source: str = "<string>") -> dict[str, str]:
    """Return {case id: reason}."""
    entries: dict[str, str] = {}
    order: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        case_id, _, reason = line.partition("#")
        case_id = case_id.strip()
        if not case_id:
            continue
        if case_id in entries:
            raise KnownFailuresError(f"{source}:{lineno}: duplicate id {case_id}")
        entries[case_id] = reason.strip()
        order.append(case_id)
    if order != sorted(order):
        raise KnownFailuresError(f"{source}: ids are not sorted")
    return entries


def load(directory: Path, tool: str) -> dict[str, str]:
    path = directory / f"{tool}.txt"
    if not path.exists():
        return {}
    return parse(path.read_text(encoding="utf8"), str(path))


@dataclass
class Outcome:
    """Differences between the results and the known failures of one tool."""

    new_failures: list[CaseResult] = field(default_factory=list)
    unexpected_passes: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.new_failures or self.unexpected_passes or self.not_found)

    def messages(self, tool: str) -> list[str]:
        out = [f"{tool}: new failure: {r.id}: {r.reason}" for r in self.new_failures]
        out += [f"{tool}: unexpected pass: {i}" for i in self.unexpected_passes]
        out += [
            f"{tool}: unexpected pass: {i} (no such case; remove it from the list)"
            for i in self.not_found
        ]
        return out


def evaluate(
    results: list[CaseResult],
    known: dict[str, str],
    complete_suites: set[str],
    every_case_ran: bool = False,
    shard: shards.Shard | None = None,
) -> Outcome:
    """Compare the results of one tool with its known failures.

    complete_suites are the suites that ran with no filter. A listed id in
    one of these suites that did not run is reported as not found. If
    every_case_ran is true, each listed id that did not run is reported as
    not found, also when its suite is not known. With a shard, only the
    listed ids in that shard can be not found.
    """
    outcome = Outcome()
    seen = set()
    for r in results:
        seen.add(r.id)
        listed = r.id in known
        # A skipped case did not fail, so it must not be in the list.
        if (r.passed or r.skipped) and listed:
            outcome.unexpected_passes.append(r.id)
        elif not (r.passed or r.skipped) and not listed:
            outcome.new_failures.append(r)
    for case_id in known:
        if case_id in seen or not shards.contains(shard, case_id):
            continue
        if every_case_ran or case_id.split("/", 1)[0] in complete_suites:
            outcome.not_found.append(case_id)
    return outcome


# The kinds of unsupported items (adapters.base.Unsupported), longest first.
_UNSUPPORTED_KINDS = (
    "in-file config line",
    "comment character",
    "multi-line value",
    "upper-case key",
    "output field",
    "layout type",
    "templater",
    "dialect",
    "setting",
    "rule",
)
_REASON_LIMIT = 300
# Text of a Rust panic message that changes between runs and machines: the
# thread id, and the folder of the cargo registry.
_VOLATILE = (
    (re.compile(r"(thread '[^']*') \(\d+\)"), r"\1"),
    (re.compile(r"\S*/registry/src/[^/\s]+/"), ""),
)


def reason_prefix(reason: str) -> str:
    """Return the group of a failure reason.

    "unsupported: <kind>" for an item that the tool does not support. Else
    the text of the first reason before ":" or ";", for example
    "tree differs", "fail_str", or "fix mismatch".
    """
    if reason.startswith(UNSUPPORTED):
        rest = reason[len(UNSUPPORTED) :]
        for kind in _UNSUPPORTED_KINDS:
            if rest.startswith(kind):
                return UNSUPPORTED + kind
        return UNSUPPORTED.rstrip()
    first = reason.split(";", 1)[0].split(":", 1)[0]
    return " ".join(first.split()) or "no reason"


def render(results: list[CaseResult]) -> str:
    """Return the known-failures file of the failed results of one tool:
    sorted ids, each with its reason on one line."""
    lines = []
    for r in sorted(results, key=lambda r: r.id):
        if r.passed or r.skipped:
            continue
        reason = " ".join(r.reason.split())
        for pattern, repl in _VOLATILE:
            reason = pattern.sub(repl, reason)
        if len(reason) > _REASON_LIMIT:
            reason = reason[: _REASON_LIMIT - 3] + "..."
        lines.append(f"{r.id}  # {reason}" if reason else r.id)
    return "".join(line + "\n" for line in lines)


def prefix_counts(results: list[CaseResult]) -> dict[str, dict[str, int]]:
    """Return {reason prefix: {suite: count}} of the failed results."""
    out: dict[str, dict[str, int]] = {}
    for r in results:
        if r.passed or r.skipped:
            continue
        by_suite = out.setdefault(reason_prefix(r.reason), {})
        by_suite[r.suite] = by_suite.get(r.suite, 0) + 1
    return dict(sorted(out.items()))
