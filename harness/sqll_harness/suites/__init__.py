"""Test suites. Each suite has NAME, discover(root), and run(adapter, case, root).

A suite with TOOLS runs only for those tools.
"""

from types import ModuleType

from . import autofix, code_only, dialects, rules, templater

SUITES: dict[str, ModuleType] = {
    dialects.NAME: dialects,
    rules.NAME: rules,
    autofix.NAME: autofix,
    templater.NAME: templater,
    code_only.NAME: code_only,
}

__all__ = ["SUITES", "runs_for"]


def runs_for(suite: ModuleType, tool: str) -> bool:
    """Return True if the suite runs for the tool."""
    return tool in getattr(suite, "TOOLS", (tool,))
