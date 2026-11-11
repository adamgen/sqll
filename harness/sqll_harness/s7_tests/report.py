"""The S7 report (docs/decisions/s7-tests-design.md, "Report").

The report gives the status of each converted node for each tool, the
excluded nodes apart from parity, and the counts. check() fails closed: it
computes each count again from the lists and refuses a report where a count,
a class, a reason, or a status does not agree.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

from ..cases import ERROR, FAIL, PASS
from .caseformat import (
    CLASSES,
    NEEDS_REASON,
    SQLFLUFF_COMMIT,
    SQLFLUFF_VERSION,
    CaseSet,
)
from .runner import TOOLS, NodeOutcome

KIND = "sqll-s7-tests-report"
FORMAT = 1
GROUPS = ("cli", "rules", "config", "config_fixtures")
NODE_STATUSES = (PASS, FAIL, ERROR)


class ReportError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__(errors)
        self.errors = errors

    def __str__(self) -> str:
        return "\n".join(self.errors)


def _percent(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 2) if whole else None


def parity(nodes: list[dict[str, Any]], tool: str, in_scope: int) -> dict[str, Any]:
    """The parity of a tool over the nodes. Excluded nodes are not in it.
    percent_of_in_scope also counts each excluded and each node that is not
    converted yet as not passed, so an exclusion cannot hide (G1.4)."""
    statuses = Counter(n["results"][tool]["status"] for n in nodes)
    return {
        "nodes": len(nodes),
        "passed": statuses[PASS],
        "failed": statuses[FAIL],
        "error": statuses[ERROR],
        "percent_of_converted": _percent(statuses[PASS], len(nodes)),
        "percent_of_in_scope": _percent(statuses[PASS], in_scope),
    }


def counts(
    scope: dict[str, Any], nodes: list[dict[str, Any]], excluded: list[dict[str, Any]]
) -> dict[str, Any]:
    in_scope = Counter(n["group"] for n in scope["nodes"])
    converted = Counter(n["group"] for n in nodes)
    out = Counter(e["group"] for e in excluded)
    groups = {
        g: {
            "in_scope": in_scope[g],
            "converted": converted[g],
            "excluded": out[g],
            "not_yet_converted": in_scope[g] - converted[g] - out[g],
        }
        for g in GROUPS
    }
    classes = Counter(e["class"] for e in excluded)
    return {
        "in_scope": len(scope["nodes"]),
        "converted": len(nodes),
        "excluded": len(excluded),
        "not_yet_converted": len(scope["nodes"]) - len(nodes) - len(excluded),
        "needs_jinja": sum(n["needs_jinja"] for n in nodes),
        "groups": groups,
        "excluded_by_class": {c: classes[c] for c in CLASSES},
    }


def summaries(
    tools: list[str], nodes: list[dict[str, Any]], in_scope: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The parity of each tool (nodes that S7 keeps) and the result of the
    nodes that move to S11 (they need the Jinja templater)."""
    s7 = [n for n in nodes if not n["needs_jinja"]]
    s11 = [n for n in nodes if n["needs_jinja"]]
    return (
        {t: parity(s7, t, in_scope) for t in tools},
        {t: parity(s11, t, in_scope) for t in tools},
    )


def build(
    cases: CaseSet,
    results: dict[str, list[NodeOutcome]],
    versions: dict[str, str],
) -> dict[str, Any]:
    tools = list(results)
    nodes = []
    for i, node in enumerate(cases.nodes):
        entry = {
            "id": node.id,
            "group": node.group,
            "case_file": node.case_file,
            "cases": len(node.cases),
            "needs_jinja": node.needs_jinja,
            "results": {},
        }
        for tool in tools:
            outcome = results[tool][i]
            if outcome.id != node.id:
                raise ReportError(
                    [f"{tool}: result {i} is {outcome.id}, not {node.id}"]
                )
            entry["results"][tool] = {
                "status": outcome.status,
                "failed_cases": [
                    {"name": c.name, "status": c.status, "reason": c.reason}
                    for c in outcome.cases
                    if c.status != PASS
                ],
            }
        nodes.append(entry)
    excluded = [
        {"id": e.id, "group": e.group, "class": e.cls, "reason": e.reason}
        for e in cases.exclusions
    ]
    in_scope = len(cases.scope["nodes"])
    s7, s11 = summaries(tools, nodes, in_scope)
    report = {
        "kind": KIND,
        "format": FORMAT,
        "sqlfluff": {"version": SQLFLUFF_VERSION, "commit": SQLFLUFF_COMMIT},
        "tools": {t: {"version": versions[t]} for t in tools},
        "counts": counts(cases.scope, nodes, excluded),
        "parity": s7,
        "s11_jinja": s11,
        "nodes": nodes,
        "excluded": excluded,
    }
    check(report, cases.scope)
    return report


def _check_node(errors: list[str], node: dict[str, Any], tools: list[str]) -> None:
    keys = {"id", "group", "case_file", "cases", "needs_jinja", "results"}
    if set(node) != keys:
        errors.append(f"{node.get('id')}: the keys are not {sorted(keys)}")
        return
    if set(node["results"]) != set(tools):
        errors.append(f"{node['id']}: the tools are not {tools}")
        return
    for tool, result in node["results"].items():
        at = f"{node['id']}: {tool}"
        status = result.get("status")
        failed = result.get("failed_cases")
        if status not in NODE_STATUSES or not isinstance(failed, list):
            errors.append(f"{at}: unknown status {status!r} or no failed_cases list")
            continue
        case_statuses = {c.get("status") for c in failed}
        if case_statuses - {FAIL, ERROR}:
            errors.append(f"{at}: a failed case has the status {case_statuses}")
        if any(not c.get("reason") for c in failed):
            errors.append(f"{at}: a failed case has no reason")
        want = PASS if not failed else ERROR if ERROR in case_statuses else FAIL
        if status != want:
            errors.append(f"{at}: the status is {status}, but its cases give {want}")
        if len(failed) > node["cases"]:
            errors.append(f"{at}: more failed cases than cases")


def check(report: dict[str, Any], scope: dict[str, Any]) -> None:
    """Fail closed if the report does not agree with itself and with scope."""
    errors: list[str] = []
    want_keys = {
        "kind",
        "format",
        "sqlfluff",
        "tools",
        "counts",
        "parity",
        "s11_jinja",
        "nodes",
        "excluded",
    }
    if set(report) != want_keys:
        raise ReportError([f"the report keys are not {sorted(want_keys)}"])
    if report["kind"] != KIND or report["format"] != FORMAT:
        errors.append(f"not a {KIND} report of format {FORMAT}")
    if report["sqlfluff"] != {"version": SQLFLUFF_VERSION, "commit": SQLFLUFF_COMMIT}:
        errors.append("the sqlfluff version or commit is not the pin")
    if len(scope["nodes"]) != scope["counts"]["total"]:
        errors.append("scope.json: the node list is not the total count")
    tools = list(report["tools"])
    if not tools or set(tools) - set(TOOLS):
        errors.append(f"the tools {tools} are not a part of {list(TOOLS)}")
    groups = {n["id"]: n["group"] for n in scope["nodes"]}
    seen: set[str] = set()
    for entry in report["nodes"] + report["excluded"]:
        node_id = entry.get("id")
        if node_id not in groups:
            errors.append(f"{node_id}: not in scope.json")
        elif entry.get("group") != groups[node_id]:
            errors.append(f"{node_id}: the group is not {groups[node_id]}")
        if node_id in seen:
            errors.append(f"{node_id}: in the report 2 times")
        seen.add(node_id)
    for node in report["nodes"]:
        _check_node(errors, node, tools)
    for entry in report["excluded"]:
        at = entry.get("id")
        if set(entry) != {"id", "group", "class", "reason"}:
            errors.append(
                f"{at}: an excluded node has other keys than id, group, "
                "class, and reason"
            )
            continue
        if entry["class"] not in CLASSES:
            errors.append(f"{at}: unknown class {entry['class']!r}")
        reason = entry["reason"]
        if reason is not None and (
            not isinstance(reason, str) or not reason.strip() or "\n" in reason
        ):
            errors.append(f"{at}: the reason is not one line of text")
        elif reason is None and entry["class"] in NEEDS_REASON:
            errors.append(f"{at}: class {entry['class']} needs a reason")
    if errors:
        raise ReportError(errors)
    in_scope = len(scope["nodes"])
    want = counts(scope, report["nodes"], report["excluded"])
    if report["counts"] != want:
        errors.append(f"the counts are not those of the lists: {want}")
    if want["not_yet_converted"] < 0 or any(
        g["not_yet_converted"] < 0 for g in want["groups"].values()
    ):
        errors.append("more converted and excluded nodes than nodes in scope")
    s7, s11 = summaries(tools, report["nodes"], in_scope)
    if report["parity"] != s7:
        errors.append(f"the parity is not that of the nodes: {s7}")
    if report["s11_jinja"] != s11:
        errors.append(f"the s11_jinja result is not that of the nodes: {s11}")
    if errors:
        raise ReportError(errors)


def select_tools(report: dict[str, Any], tools: list[str]) -> dict[str, Any]:
    """The report with only the results of these tools."""

    def keep(mapping: dict[str, Any]) -> dict[str, Any]:
        return {t: v for t, v in mapping.items() if t in tools}

    nodes = [dict(n, results=keep(n["results"])) for n in report["nodes"]]
    return {
        **report,
        "tools": keep(report["tools"]),
        "parity": keep(report["parity"]),
        "s11_jinja": keep(report["s11_jinja"]),
        "nodes": nodes,
    }


def write(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1) + "\n", encoding="utf8")
