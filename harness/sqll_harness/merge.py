"""Merge the reports of shard runs into one report.

The known-failure check runs again on the merged results. Thus a listed id
that no shard ran is reported, also when each shard run passed.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import known_failures, report
from .cases import CaseResult
from .known_failures import Outcome
from .suites import SUITES, runs_for


class MergeError(Exception):
    """The reports cannot be merged into a correct report."""


@dataclass
class _Group:
    """The shard runs of one suite and one tool."""

    count: int
    filter: str | None
    seen: set[int] = field(default_factory=set)


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf8"))
    except (OSError, ValueError) as exc:
        raise MergeError(f"{path}: cannot read the report: {exc}") from None


def load_expected(path: Path) -> list[tuple[str, str, int]]:
    """Read a JSON list of {"suite", "tool", "shards"} objects.

    If path is a folder (ci/matrix.d), read each *.json file in it, in the
    order of the file names, as ci/matrix.py does. A suite and tool in two
    entries is an error."""
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise MergeError(f"{path}: no *.json file")
        out = [e for f in files for e in load_expected(f)]
        seen: set[tuple[str, str]] = set()
        for suite, tool, _ in out:
            if (suite, tool) in seen:
                raise MergeError(f"{path}: {suite}/{tool} is in two entries")
            seen.add((suite, tool))
        return out
    try:
        entries = json.loads(path.read_text(encoding="utf8"))
        return [(e["suite"], e["tool"], int(e["shards"])) for e in entries]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MergeError(f"{path}: not a list of suite/tool/shards: {exc}") from None


def _groups(reports: list[tuple[str, dict]]) -> dict[tuple[str, str], _Group]:
    groups: dict[tuple[str, str], _Group] = {}
    for name, rep in reports:
        scope = rep.get("scope")
        if not isinstance(scope, dict):
            raise MergeError(f"{name}: the report has no run scope")
        k, n = (1, 1)
        if scope["shard"]:
            k, n = (int(x) for x in scope["shard"].split("/"))
        for suite in scope["suites"]:
            for tool in scope["tools"]:
                g = groups.setdefault((suite, tool), _Group(n, scope["filter"]))
                where = f"{suite}/{tool}"
                if g.count != n:
                    raise MergeError(f"{where}: shard counts {g.count} and {n} differ")
                if g.filter != scope["filter"]:
                    raise MergeError(f"{where}: the runs used different filters")
                if k in g.seen:
                    raise MergeError(f"{where}: shard {k}/{n} is in two reports")
                g.seen.add(k)
    for (suite, tool), g in sorted(groups.items()):
        missing = sorted(set(range(1, g.count + 1)) - g.seen)
        if missing:
            text = ", ".join(f"{k}/{g.count}" for k in missing)
            raise MergeError(f"{suite}/{tool}: no report for shard {text}")
    return groups


def merge(
    reports: list[tuple[str, dict]],
    known_dir: Path,
    all_suites: list[str],
    expected: list[tuple[str, str, int]] | None = None,
) -> tuple[dict, dict[str, Outcome]]:
    """Merge (name, report) pairs. Return the report and the outcome of each tool.

    all_suites are the suites that the harness has. If each of them that
    runs for a tool (suites.runs_for) ran completely for it, each listed id
    of that tool that did not run is not found, also when its suite is not
    known.
    """
    if not reports:
        raise MergeError("no reports to merge")
    refs = {rep.get("sqlfluff_ref") for _, rep in reports}
    if len(refs) != 1:
        raise MergeError(f"the reports have different sqlfluff refs: {sorted(refs)}")
    groups = _groups(reports)
    for suite, tool, count in expected or []:
        g = groups.get((suite, tool))
        if g is None:
            raise MergeError(f"{suite}/{tool}: no report")
        if g.count != count:
            raise MergeError(f"{suite}/{tool}: {g.count} shards, expected {count}")

    tool_infos: dict[str, dict] = {}
    results: list[CaseResult] = []
    seen: set[tuple[str, str, str]] = set()
    for name, rep in reports:
        for tool, info in rep["tools"].items():
            first = tool_infos.setdefault(tool, info)
            if first["version"] != info["version"]:
                raise MergeError(f"{name}: {tool} version {info['version']} differs")
            if first != info:
                raise MergeError(f"{name}: {tool} config or preflight differs")
        scope = rep["scope"]
        for case in rep["cases"]:
            r = CaseResult(**case)
            if r.suite not in scope["suites"] or r.tool not in scope["tools"]:
                raise MergeError(f"{name}: {r.suite}/{r.tool} is not in the scope")
            key = (r.suite, r.tool, r.id)
            if key in seen:
                raise MergeError(f"{name}: case {r.tool} {r.id} is in two reports")
            seen.add(key)
            results.append(r)

    tools = sorted({tool for _, tool in groups})
    outcomes = {}
    for tool in tools:
        complete = {s for (s, t), g in groups.items() if t == tool and not g.filter}
        tool_suites = {
            s for s in all_suites if s not in SUITES or runs_for(SUITES[s], tool)
        }
        outcomes[tool] = known_failures.evaluate(
            [r for r in results if r.tool == tool],
            known_failures.load(known_dir, tool),
            complete,
            every_case_ran=tool_suites <= complete,
        )
    rep = report.build(refs.pop(), tool_infos, results, outcomes, None)
    rep["parts"] = sorted(
        (r["scope"] for _, r in reports),
        key=lambda s: json.dumps(s, sort_keys=True),
    )
    return rep, outcomes
