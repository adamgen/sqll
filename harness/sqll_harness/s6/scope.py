"""The scope file of S6 (templater parity: sqll passes 100% of the
placeholder and Python format-string templater fixtures that do not need a
Python runtime). See docs/decisions/s6-templaters.md, "Black-box form".

The case runner ("sqll-harness s7 run --scope s6") and the trace oracle
("scripts/s7-tests/oracle --scope s6") of the test conversion of S7 read
this scope. It is the black-box nodes of results/S6/scope.json (the output
of scripts/s6/inventory.py), in the form of results/S7-tests/scope.json:
each node has its id, its file, and its group (its templater). The 25
internal nodes are not in it (design item 3: they are Rust unit tests).
The case files are in harness/sqll_harness/s6/cases/, at the path of their
sqlfluff test file (test/core/templaters/placeholder_test.py gives
core/templaters/placeholder_test.yml). The scope has no exclusion list and
no not-reproduced record.

load() fails closed (ScopeError) if the data is not the S6 set: a node that
is black box and needs a Python runtime, a templater that is not a group,
counts that are not those of scope.json, or a sqlfluff pin that is not the
pin of the case format.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

from ..paths import REPO_ROOT
from ..s7_tests.scopes import Scope

SCOPE_FILE = REPO_ROOT / "results" / "S6" / "scope.json"
CASES_DIR = Path(__file__).resolve().parent / "cases"
# The suites of the scope: one for each templater.
SUITES: dict[str, tuple[str, ...]] = {
    "s6_placeholder": ("placeholder",),
    "s6_python": ("python",),
}
# The tools of the S6 cases (G1: the same harness runs sqlfluff, sqruff, and
# sqll).
TOOLS = ("sqlfluff", "sqruff", "sqll")
# The oracle proves the cases with the pinned sqlfluff only.
ORACLE_TOOLS = ("sqlfluff",)
# scripts/s7-tests/trace-nodes traces the templater calls of the nodes.
TRACE_ARGS = ("--templaters",)
# The count of the black-box nodes of each templater in scope.json.
COUNT_KEYS = {"placeholder": "placeholder_nodes", "python": "python_nodes"}


class ScopeError(Exception):
    """results/S6/scope.json is not the S6 set that the runner can read."""


def from_s6(data: dict[str, Any]) -> dict[str, Any]:
    """The scope data of the runner from the data of results/S6/scope.json."""
    from ..s7_tests import caseformat

    errors = []
    if data.get("sqlfluff") != caseformat.SQLFLUFF_VERSION:
        errors.append(f"sqlfluff {data.get('sqlfluff')}, not the pin")
    if data.get("commit") != caseformat.SQLFLUFF_COMMIT:
        errors.append(f"the commit {data.get('commit')} is not the pin")
    groups = [g for gs in SUITES.values() for g in gs]
    nodes = []
    for node in data["nodes"]:
        if node["kind"] != "black_box":
            continue
        if node["needs_python_runtime"]:
            errors.append(f"{node['id']}: a black-box node that needs a Python runtime")
        if node["templater"] not in groups:
            errors.append(f"{node['id']}: the templater {node['templater']!r}")
            continue
        nodes.append(
            {"id": node["id"], "file": node["file"], "group": node["templater"]}
        )
    found = Counter(n["group"] for n in nodes)
    counts = data["counts"]
    for group, key in COUNT_KEYS.items():
        if found[group] != counts[key]["black_box"]:
            errors.append(
                f"{found[group]} black-box {group} nodes, not {key}.black_box"
                f" {counts[key]['black_box']}"
            )
    if len(nodes) != counts["s6_black_box"]:
        errors.append(f"{len(nodes)} black-box nodes, not {counts['s6_black_box']}")
    if len({n["id"] for n in nodes}) != len(nodes):
        errors.append("a node id is in the list 2 times")
    if errors:
        raise ScopeError("results/S6/scope.json: " + "; ".join(errors))
    files: dict[str, dict[str, Any]] = {}
    for node in nodes:
        entry = files.setdefault(node["file"], {"group": node["group"], "nodes": 0})
        if entry["group"] != node["group"]:
            raise ScopeError(f"{node['file']}: nodes of 2 templaters")
        entry["nodes"] += 1
    return {
        "source": "results/S6/scope.json",
        "sqlfluff": data["sqlfluff"],
        "commit": data["commit"],
        "suites": {s: list(gs) for s, gs in SUITES.items()},
        "tools": list(TOOLS),
        "counts": {**{g: found[g] for g in groups}, "total": len(nodes)},
        "files": files,
        "nodes": nodes,
    }


def load(path: Path = SCOPE_FILE) -> dict[str, Any]:
    return from_s6(json.loads(path.read_text(encoding="utf8")))


def load_cases(cases_dir: Path = CASES_DIR, path: Path = SCOPE_FILE):
    """The checked case set of the S6 case files (caseformat.load)."""
    from ..s7_tests import caseformat

    return caseformat.load(cases_dir, None, load(path))


def no_record():
    """The S6 scope has no not-reproduced record: a check must cite each
    assert of each converted node."""
    from ..s7_tests import oracle

    return oracle.NotReproduced([], False)


SCOPE = Scope(
    name="s6",
    suites=tuple(SUITES),
    tools=TOOLS,
    load_scope=load,
    load_cases=load_cases,
    load_not_reproduced=no_record,
    out_dir=REPO_ROOT / "out" / "s6",
    results_dir=REPO_ROOT / "results" / "S6",
    oracle_tools=ORACLE_TOOLS,
    trace_args=TRACE_ARGS,
    exclusions=False,
)
