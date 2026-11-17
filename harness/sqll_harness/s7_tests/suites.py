"""The 3 S7 suites of the harness (docs/decisions/s7-tests-design.md,
"Suites and tools"). A suite is a set of node groups of scope.json.

A scope file of another stone (sqll_harness.s7_tests.scopes, for example
the scope of S6) gives its own suites and tools in the keys "suites" and
"tools" of its scope data. The functions here take that scope data. With
no scope data, or with scope data that has no such key
(results/S7-tests/scope.json), they give the S7 suites and tools.

This module imports nothing heavy: the harness CLI reads it for the choices
of "sqll-harness s7 run".
"""

from typing import Any

SUITES: dict[str, tuple[str, ...]] = {
    "s7_rules": ("rules",),
    "s7_config": ("config", "config_fixtures"),
    "s7_cli": ("cli",),
}
# The tools of the S7 suites. sqll joins in track S7-sqll.
TOOLS = ("sqlfluff", "sqlfluff-rs", "sqruff")
# The node groups of the S7 scope.json, in the order of the report counts.
GROUPS = ("cli", "rules", "config", "config_fixtures")


def suite_table(scope: dict[str, Any] | None = None) -> dict[str, tuple[str, ...]]:
    """The suites of the scope data: {suite: (group, ...)}."""
    if scope is None or "suites" not in scope:
        return SUITES
    return {s: tuple(gs) for s, gs in scope["suites"].items()}


def tool_list(scope: dict[str, Any] | None = None) -> tuple[str, ...]:
    """The tools of the scope data, in the order of a report."""
    if scope is None or "tools" not in scope:
        return TOOLS
    return tuple(scope["tools"])


def group_list(scope: dict[str, Any] | None = None) -> tuple[str, ...]:
    """The node groups of the scope data, in the order of the report counts."""
    if scope is None or "suites" not in scope:
        return GROUPS
    return tuple(g for gs in suite_table(scope).values() for g in gs)


def groups(suites: list[str], scope: dict[str, Any] | None = None) -> set[str]:
    """The node groups of the suites."""
    table = suite_table(scope)
    unknown = sorted(set(suites) - set(table))
    if unknown:
        what = "S7 suites" if table is SUITES else "suites of the scope"
        raise ValueError(f"unknown {what} {unknown}; the suites are {list(table)}")
    return {g for s in suites for g in table[s]}


def suite_of(group: str, scope: dict[str, Any] | None = None) -> str:
    """The suite of a node group."""
    return next(s for s, gs in suite_table(scope).items() if group in gs)
