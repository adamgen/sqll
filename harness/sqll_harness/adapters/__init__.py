"""Tool adapters."""

from .base import Adapter, ParseResult, ToolNotInstalled
from .sqlfluff import SqlfluffAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    "sqlfluff": SqlfluffAdapter,
}

__all__ = ["ADAPTERS", "Adapter", "ParseResult", "ToolNotInstalled"]
