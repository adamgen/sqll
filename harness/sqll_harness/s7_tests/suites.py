"""The 3 S7 suites of the harness (docs/decisions/s7-tests-design.md,
"Suites and tools"). A suite is a set of node groups of scope.json.

This module imports nothing heavy: the harness CLI reads it for the choices
of "sqll-harness s7 run".
"""

SUITES: dict[str, tuple[str, ...]] = {
    "s7_rules": ("rules",),
    "s7_config": ("config", "config_fixtures"),
    "s7_cli": ("cli",),
}
# The tools of the S7 suites. sqll joins in track S7-sqll.
TOOLS = ("sqlfluff", "sqlfluff-rs", "sqruff")


def groups(suites: list[str]) -> set[str]:
    """The node groups of the suites."""
    unknown = sorted(set(suites) - set(SUITES))
    if unknown:
        raise ValueError(f"unknown S7 suites {unknown}; the suites are {list(SUITES)}")
    return {g for s in suites for g in SUITES[s]}


def suite_of(group: str) -> str:
    """The suite of a node group."""
    return next(s for s, gs in SUITES.items() if group in gs)
