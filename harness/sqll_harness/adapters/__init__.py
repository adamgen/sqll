"""Tool adapters."""

from .base import Adapter, ParseResult, ToolNotInstalled
from .sqlfluff import SqlfluffAdapter
from .sqlfluff_rs import SqlfluffRsAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    SqlfluffAdapter.name: SqlfluffAdapter,
    SqlfluffRsAdapter.name: SqlfluffRsAdapter,
}

__all__ = ["ADAPTERS", "Adapter", "ParseResult", "ToolNotInstalled"]
