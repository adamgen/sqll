"""Test suites. Each suite has NAME, discover(root), and run(adapter, case, root)."""

from types import ModuleType

from . import autofix, dialects, rules

SUITES: dict[str, ModuleType] = {
    dialects.NAME: dialects,
    rules.NAME: rules,
    autofix.NAME: autofix,
}

__all__ = ["SUITES"]
