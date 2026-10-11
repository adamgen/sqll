"""Known failures: known_failures/<tool>.txt.

Format: one case id on each line, sorted, with no duplicates. Text after
"#" is the reason. Blank lines are ignored.
"""

from dataclasses import dataclass, field
from pathlib import Path

from .cases import CaseResult


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
) -> Outcome:
    """Compare the results of one tool with its known failures.

    complete_suites are the suites that ran with no filter. A listed id in
    one of these suites that did not run is reported as not found.
    """
    outcome = Outcome()
    seen = set()
    for r in results:
        seen.add(r.id)
        listed = r.id in known
        if r.passed and listed:
            outcome.unexpected_passes.append(r.id)
        elif not r.passed and not listed:
            outcome.new_failures.append(r)
    for case_id in known:
        if case_id not in seen and case_id.split("/", 1)[0] in complete_suites:
            outcome.not_found.append(case_id)
    return outcome
