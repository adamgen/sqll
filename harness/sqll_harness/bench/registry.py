"""The benchmark tools. A new tool is one BenchAdapter subclass and one entry
here (harness/bench.md, "Add a tool"). The definitions do not change."""

from collections.abc import Callable

from .adapter import BenchAdapter
from .sqll import SqllBaseBench, SqllBench
from .tools import SqlfluffBench, SqlfluffRsBench, SqruffBench

REGISTRY: dict[str, Callable[[], BenchAdapter]] = {
    SqlfluffBench.name: SqlfluffBench,
    SqlfluffRsBench.name: SqlfluffRsBench,
    SqruffBench.name: SqruffBench,
    SqllBench.name: SqllBench,
}
# The tools that a run has only when a caller names them: not in names(),
# thus not in a default run or in the baseline.
EXTRA: dict[str, Callable[[], BenchAdapter]] = {
    SqllBaseBench.name: SqllBaseBench,
}


def names() -> list[str]:
    return sorted(REGISTRY)


def get(name: str) -> BenchAdapter:
    """Return a new adapter of the tool (REGISTRY or EXTRA). KeyError for
    an unknown tool."""
    adapter = (REGISTRY.get(name) or EXTRA[name])()
    if adapter.name != name:
        raise ValueError(f"the registry entry {name!r} gives tool {adapter.name!r}")
    return adapter


def register(name: str, factory: Callable[[], BenchAdapter]) -> None:
    if name in REGISTRY or name in EXTRA:
        raise ValueError(f"tool {name!r} is already in the registry")
    REGISTRY[name] = factory
