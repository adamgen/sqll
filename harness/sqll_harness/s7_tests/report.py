"""The S7 report (docs/decisions/s7-tests-design.md, "Report").

The report gives the status of each converted node for each tool, the
excluded nodes apart from parity, and the counts, for the nodes of its
suites. check() fails closed: it computes each count again from the lists
and refuses a report where a count, a class, a reason, or a status does not
agree.
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
from .runner import NodeOutcome
from .suites import SUITES, TOOLS, groups

KIND = "sqll-s7-tests-report"
FORMAT = 2
ALL_SUITES = sorted(SUITES)
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
    by_group = {
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
        "groups": by_group,
        "excluded_by_class": {c: classes[c] for c in CLASSES},
    }


def suite_scope(scope: dict[str, Any], suites: list[str]) -> dict[str, Any]:
    """scope.json with only the nodes of the groups of the suites."""
    keep = groups(suites)
    return dict(scope, nodes=[n for n in scope["nodes"] if n["group"] in keep])


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
    suites: list[str] | None = None,
) -> dict[str, Any]:
    """The report of the suites (default: all). results has, for each tool,
    the outcome of each node of the suites, in the order of cases.nodes."""
    suites = sorted(suites or ALL_SUITES)
    keep = groups(suites)
    tools = list(results)
    nodes = []
    for i, node in enumerate(n for n in cases.nodes if n.group in keep):
        entry = {
            "id": node.id,
            "group": node.group,
            "case_file": node.case_file,
            "cases": len(node.cases),
            "needs_jinja": node.needs_jinja,
            "results": {},
        }
        for tool in tools:
            if i >= len(results[tool]):
                raise ReportError([f"{tool}: no result {i} ({node.id})"])
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
    for tool in tools:
        if len(results[tool]) != len(nodes):
            raise ReportError(
                [f"{tool}: {len(results[tool])} results, not {len(nodes)}"]
            )
    excluded = [
        {"id": e.id, "group": e.group, "class": e.cls, "reason": e.reason}
        for e in cases.exclusions
        if e.group in keep
    ]
    return assemble(
        suites, {t: versions[t] for t in tools}, nodes, excluded, cases.scope
    )


def assemble(
    suites: list[str],
    versions: dict[str, str],
    nodes: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    scope: dict[str, Any],
) -> dict[str, Any]:
    """The checked report of the suites, from its node and excluded lists.
    versions gives the tools in their order. scope is all of scope.json."""
    suites = sorted(suites)
    tools = list(versions)
    in_scope = len(suite_scope(scope, suites)["nodes"])
    s7, s11 = summaries(tools, nodes, in_scope)
    report = {
        "kind": KIND,
        "format": FORMAT,
        "suites": suites,
        "sqlfluff": {"version": SQLFLUFF_VERSION, "commit": SQLFLUFF_COMMIT},
        "tools": {t: {"version": versions[t]} for t in tools},
        "counts": counts(suite_scope(scope, suites), nodes, excluded),
        "parity": s7,
        "s11_jinja": s11,
        "nodes": nodes,
        "excluded": excluded,
    }
    check(report, scope)
    return report


def merge(parts: list[tuple[str, dict[str, Any]]], cases: CaseSet) -> dict[str, Any]:
    """Merge the (name, report) parts of a CI run (one suite and one tool or
    more in each part) into the report of all their suites and tools.

    Fail closed (ReportError) if a part is not a correct report of the case
    files, if a suite and tool is in 2 parts, if a suite does not have each
    tool of the merge (each node must have a result for each tool), if 2
    parts give a tool 2 versions, or if 2 parts of a suite do not have the
    same nodes and excluded nodes. The order of the nodes and of the tools is
    that of a run of all suites and tools.
    """
    if not parts:
        raise ReportError(["no reports to merge"])
    errors: list[str] = []
    versions: dict[str, str] = {}
    pairs: dict[tuple[str, str], str] = {}
    by_suite: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for name, part in parts:
        try:
            check(part, cases.scope)
        except ReportError as exc:
            errors += [f"{name}: {e}" for e in exc.errors]
            continue
        for tool, info in part["tools"].items():
            first = versions.setdefault(tool, info["version"])
            if first != info["version"]:
                errors.append(
                    f"{name}: {tool} has the version {info['version']}, not the"
                    f" version {first} of an earlier report"
                )
        for suite in part["suites"]:
            for tool in part["tools"]:
                if (suite, tool) in pairs:
                    errors.append(
                        f"{name}: {suite}/{tool} is also in {pairs[(suite, tool)]}"
                    )
                pairs[(suite, tool)] = name
            by_suite.setdefault(suite, []).append(
                (name, select_suites(part, [suite], cases.scope))
            )
    if errors:
        raise ReportError(errors)
    tools = [t for t in TOOLS if t in versions]
    for suite in sorted(by_suite):
        missing = [t for t in tools if (suite, t) not in pairs]
        if missing:
            errors.append(f"{suite}: no report of the tools {missing}")
    if errors:
        raise ReportError(errors)

    node_order = {n.id: i for i, n in enumerate(cases.nodes)}
    excluded_order = {e.id: i for i, e in enumerate(cases.exclusions)}
    nodes: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for suite, suite_parts in sorted(by_suite.items()):
        first_name, first = suite_parts[0]
        shape = [{k: v for k, v in n.items() if k != "results"} for n in first["nodes"]]
        merged = {n["id"]: dict(n, results={}) for n in first["nodes"]}
        for name, part in suite_parts:
            if [
                {k: v for k, v in n.items() if k != "results"} for n in part["nodes"]
            ] != shape or part["excluded"] != first["excluded"]:
                errors.append(
                    f"{name}: the nodes of {suite} are not those of {first_name}"
                )
                continue
            for node in part["nodes"]:
                merged[node["id"]]["results"].update(node["results"])
        nodes += merged.values()
        excluded += first["excluded"]
    if errors:
        raise ReportError(errors)
    for node in nodes:
        node["results"] = {t: node["results"][t] for t in tools}
    errors += [
        f"{n['id']}: not a converted node of the case files"
        for n in nodes
        if n["id"] not in node_order
    ]
    errors += [
        f"{e['id']}: not a node of the exclusion list"
        for e in excluded
        if e["id"] not in excluded_order
    ]
    if errors:
        raise ReportError(errors)
    nodes.sort(key=lambda n: node_order[n["id"]])
    excluded.sort(key=lambda e: excluded_order[e["id"]])
    return assemble(
        sorted(by_suite), {t: versions[t] for t in tools}, nodes, excluded, cases.scope
    )


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
    """Fail closed if the report does not agree with itself and with scope
    (all of scope.json; check() keeps the nodes of the report suites)."""
    errors: list[str] = []
    want_keys = {
        "kind",
        "format",
        "suites",
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
    suites = report["suites"]
    if (
        not isinstance(suites, list)
        or not suites
        or suites != sorted(set(suites))
        or set(suites) - set(SUITES)
    ):
        raise ReportError(
            errors + [f"the suites {suites!r} are not a sorted list of {ALL_SUITES}"]
        )
    keep = groups(suites)
    all_groups = {n["id"]: n["group"] for n in scope["nodes"]}
    scope = suite_scope(scope, suites)
    tools = list(report["tools"])
    if not tools or set(tools) - set(TOOLS):
        errors.append(f"the tools {tools} are not a part of {list(TOOLS)}")
    seen: set[str] = set()
    for entry in report["nodes"] + report["excluded"]:
        node_id = entry.get("id")
        if node_id not in all_groups:
            errors.append(f"{node_id}: not in scope.json")
        elif entry.get("group") != all_groups[node_id]:
            errors.append(f"{node_id}: the group is not {all_groups[node_id]}")
        elif all_groups[node_id] not in keep:
            errors.append(f"{node_id}: the group is not of the suites {suites}")
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


def select_suites(
    report: dict[str, Any], suites: list[str], scope: dict[str, Any]
) -> dict[str, Any]:
    """The report with only the nodes of these suites (a part of the report
    suites), with the counts and parity of these nodes."""
    suites = sorted(suites)
    if set(suites) - set(report["suites"]):
        raise ReportError([f"the report has no suites {suites}"])
    keep = groups(suites)
    part = suite_scope(scope, suites)
    nodes = [n for n in report["nodes"] if n["group"] in keep]
    excluded = [e for e in report["excluded"] if e["group"] in keep]
    s7, s11 = summaries(list(report["tools"]), nodes, len(part["nodes"]))
    return {
        **report,
        "suites": suites,
        "counts": counts(part, nodes, excluded),
        "parity": s7,
        "s11_jinja": s11,
        "nodes": nodes,
        "excluded": excluded,
    }


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
