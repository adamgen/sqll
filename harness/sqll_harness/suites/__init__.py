"""Test suites. Each suite has NAME, discover(root), and run(adapter, case, root)."""

from types import ModuleType

from . import dialects

SUITES: dict[str, ModuleType] = {
    dialects.NAME: dialects,
}

__all__ = ["SUITES"]
