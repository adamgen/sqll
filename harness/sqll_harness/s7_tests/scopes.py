"""The scope files of the case runner and of the trace oracle
(docs/decisions/s7-tests-design.md, "Scope files").

A scope file gives the nodes, the case files, and the suites and tools of a
run of "sqll-harness s7 run" and of scripts/s7-tests/oracle. The default
scope is that of the test conversion of S7 (results/S7-tests/scope.json).
The scope of S6 (templater parity) is sqll_harness/s6/scope.py: the
black-box nodes of results/S6/scope.json. There is one runner and one
oracle for all scopes (S6 design item 4: no second runner).

This module imports nothing heavy: the harness CLI reads the names and the
choices of the scopes. Each Scope loads its data and its cases only when a
command calls it.
"""

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..paths import REPO_ROOT
from .suites import SUITES, TOOLS

DEFAULT = "s7"


@dataclass(frozen=True)
class Scope:
    """One scope file.

    load_scope gives the scope data (the form of results/S7-tests/scope.json:
    "nodes" with "id" and "group", "files", and "counts" with "total"; a
    scope of another stone also has "suites" and "tools"). load_cases gives
    the checked case set (caseformat.load). load_not_reproduced gives the
    not-reproduced record of the oracle check 4. trace_args are the options
    of scripts/s7-tests/trace-nodes for the nodes of the scope. exclusions
    is False for a scope with no exclusion list (the run summary then has
    no "excluded by class" line).
    """

    name: str
    suites: tuple[str, ...]
    tools: tuple[str, ...]
    load_scope: Callable[[], dict[str, Any]]
    load_cases: Callable[[], Any]
    load_not_reproduced: Callable[[], Any]
    out_dir: Path
    results_dir: Path
    oracle_tools: tuple[str, ...]
    trace_args: tuple[str, ...] = field(default=())
    exclusions: bool = True


def _s7_scope() -> dict[str, Any]:
    from . import caseformat

    return caseformat.load_scope()


def _s7_cases():
    from . import caseformat

    return caseformat.load()


def _s7_not_reproduced():
    from . import oracle

    return oracle.load_not_reproduced()


S7 = Scope(
    name="s7",
    suites=tuple(SUITES),
    tools=TOOLS,
    load_scope=_s7_scope,
    load_cases=_s7_cases,
    load_not_reproduced=_s7_not_reproduced,
    out_dir=REPO_ROOT / "out" / "s7-tests",
    results_dir=REPO_ROOT / "results" / "S7-tests",
    oracle_tools=("sqlfluff", "sqlfluff-rs"),
)

# The module and the name of each scope.
SCOPES = {
    "s7": ("sqll_harness.s7_tests.scopes", "S7"),
    "s6": ("sqll_harness.s6.scope", "SCOPE"),
}


def get(name: str) -> Scope:
    if name not in SCOPES:
        raise ValueError(f"unknown scope {name!r}; the scopes are {list(SCOPES)}")
    module, attr = SCOPES[name]
    return getattr(importlib.import_module(module), attr)


def all_suites() -> list[str]:
    """The suites of each scope (the choices of --suite)."""
    return sorted({s for name in SCOPES for s in get(name).suites})


def all_tools() -> list[str]:
    """The tools of each scope (the choices of --tool), in a stable order."""
    out: list[str] = []
    for name in SCOPES:
        out += [t for t in get(name).tools if t not in out]
    return out
