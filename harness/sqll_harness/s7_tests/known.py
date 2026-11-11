"""The known failures of the S7 suites: results/S7-tests/known_failures/<tool>.txt
(docs/decisions/s7-tests-design.md, "Known failures").

The format is that of the S1 lists (sqll_harness.known_failures): one pytest
node id on each line, sorted, with no duplicates; the text after "#" is the
reason. Here each id must also be a node of scope.json and have a reason.

A node of a report fails for a tool if its status is not "pass". The check
of a report compares, for each tool of the report, the nodes that do not
pass with the list of the tool:
- new failure: a node does not pass and is not in the list;
- unexpected pass: a listed node passes;
- not found: a listed node of a suite of the report is not a converted node
  of the report (for example an excluded node, or a node that is not
  converted yet).
A listed node of a suite that is not in the report is not checked.
"""

import re
from pathlib import Path
from typing import Any

from .. import known_failures
from ..cases import PASS
from ..paths import REPO_ROOT
from .suites import groups

DIRECTORY = REPO_ROOT / "results" / "S7-tests" / "known_failures"
REASON_LIMIT = 300
# Text of a Rust panic message that changes between runs and machines: the
# thread id, and the folder of the cargo registry (as in the S1 lists).
_VOLATILE = (
    (re.compile(r"(thread '[^']*') \(\d+\)"), r"\1"),
    (re.compile(r"\S*/registry/src/[^/\s]+/"), ""),
)


class KnownFailuresError(Exception):
    """A list of known failures is not valid."""


def parse(text: str, source: str, scope: dict[str, Any]) -> dict[str, str]:
    """Return {node id: reason}. Fail closed on a format error, on an id that
    is not a node of scope.json, and on an id with no reason."""
    try:
        entries = known_failures.parse(text, source)
    except known_failures.KnownFailuresError as exc:
        raise KnownFailuresError(str(exc)) from None
    ids = {n["id"] for n in scope["nodes"]}
    errors = [
        f"{source}: {i}: not a node of scope.json" for i in entries if i not in ids
    ]
    errors += [
        f"{source}: {i}: no reason after '#'" for i, r in entries.items() if not r
    ]
    if errors:
        raise KnownFailuresError("\n".join(errors))
    return entries


def load(directory: Path, tool: str, scope: dict[str, Any]) -> dict[str, str]:
    """The list of a tool; a missing file is an empty list."""
    path = directory / f"{tool}.txt"
    if not path.exists():
        return {}
    return parse(path.read_text(encoding="utf8"), str(path), scope)


def reason(result: dict[str, Any]) -> str:
    """The reason of a node that does not pass: each failed case with its
    reason, on one line."""
    text = "; ".join(f"{c['name']}: {c['reason']}" for c in result["failed_cases"])
    text = " ".join(text.split())
    for pattern, repl in _VOLATILE:
        text = pattern.sub(repl, text)
    if len(text) > REASON_LIMIT:
        text = text[: REASON_LIMIT - 3] + "..."
    return text


def render(report: dict[str, Any], tool: str) -> str:
    """The list of a tool from a report: each node that does not pass, sorted,
    with its reason."""
    lines = [
        f"{n['id']}  # {reason(n['results'][tool])}"
        for n in report["nodes"]
        if n["results"][tool]["status"] != PASS
    ]
    return "".join(line + "\n" for line in sorted(lines))


def evaluate(
    report: dict[str, Any], tool: str, known: dict[str, str], scope: dict[str, Any]
) -> list[str]:
    """The differences between the results of a tool in the report and its
    list, as messages. No message: the results agree with the list."""
    keep = groups(report["suites"])
    group_of = {n["id"]: n["group"] for n in scope["nodes"]}
    seen = set()
    out = []
    for node in report["nodes"]:
        seen.add(node["id"])
        result = node["results"][tool]
        listed = node["id"] in known
        if result["status"] == PASS and listed:
            out.append(f"{tool}: unexpected pass: {node['id']}")
        elif result["status"] != PASS and not listed:
            out.append(f"{tool}: new failure: {node['id']}: {reason(result)}")
    for node_id in known:
        if node_id not in seen and group_of.get(node_id) in keep:
            out.append(
                f"{tool}: unexpected pass: {node_id} (not a converted node of the "
                "report; remove it from the list)"
            )
    return out


def check(report: dict[str, Any], directory: Path, scope: dict[str, Any]) -> list[str]:
    """evaluate() for each tool of the report. KnownFailuresError if a list
    is not valid."""
    return [
        line
        for tool in report["tools"]
        for line in evaluate(report, tool, load(directory, tool, scope), scope)
    ]
