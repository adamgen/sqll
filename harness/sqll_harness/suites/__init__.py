"""Test suites. Each suite has NAME, discover(root), and run(adapter, case, root)."""

from types import ModuleType

from . import autofix, dialects, rules, templater

SUITES: dict[str, ModuleType] = {
    dialects.NAME: dialects,
    rules.NAME: rules,
    autofix.NAME: autofix,
    templater.NAME: templater,
}

__all__ = ["SUITES"]
