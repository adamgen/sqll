# The discovery rules and the depth overrides in this file are ported from
# sqlfluff 4.4.0, test/conftest.py (get_parse_fixtures,
# DEEP_PARSE_DEPTH_OVERRIDES). Copyright (c) 2018-2026 Alan Cruickshank.
# MIT License. See THIRD_PARTY.md.
"""Dialect parse suite: test/fixtures/dialects/<dialect>/*.sql and *.yml."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..adapters import Adapter
from ..cases import FAIL, PASS, CaseResult
from ..compare import load_yaml, record_to_tuple, trees_match

NAME = "dialects"
FIXTURE_DIR = Path("test") / "fixtures" / "dialects"

DEEP_PARSE_DEPTH_OVERRIDES: dict[tuple[str, str], int] = {
    ("ansi", "expression_recursion.sql"): 2000,
}


@dataclass(frozen=True)
class DialectCase:
    id: str
    dialect: str
    sql: Path
    yml: Path
    code_only: bool
    extra_config: dict[str, Any] | None


def discover(sqlfluff_root: Path) -> list[DialectCase]:
    """Find each SQL file that has a sibling .yml (code only) or _nc.yml file.

    Paths in the cases are relative to sqlfluff_root.
    """
    base = sqlfluff_root / FIXTURE_DIR
    cases = []
    for dialect in sorted(os.listdir(base)):
        if dialect.endswith(".md"):
            continue
        names = set(os.listdir(base / dialect))
        for name in sorted(names):
            if not name.endswith(".sql"):
                continue
            stem = name[:-4]
            depth = DEEP_PARSE_DEPTH_OVERRIDES.get((dialect, name))
            extra = {"core": {"max_parse_depth": depth}} if depth else None
            for suffix, code_only in ((".yml", True), ("_nc.yml", False)):
                if stem + suffix not in names:
                    continue
                case_stem = stem if code_only else stem + "_nc"
                cases.append(
                    DialectCase(
                        id=f"{NAME}/{dialect}/{case_stem}",
                        dialect=dialect,
                        sql=FIXTURE_DIR / dialect / name,
                        yml=FIXTURE_DIR / dialect / (stem + suffix),
                        code_only=code_only,
                        extra_config=extra,
                    )
                )
    return cases


def run(adapter: Adapter, case: DialectCase, sqlfluff_root: Path) -> CaseResult:
    """Parse the case and compare the tree with the fixture."""
    result = adapter.parse(
        case.sql,
        case.dialect,
        code_only=case.code_only,
        include_meta=False,
        cwd=sqlfluff_root,
        extra_config=case.extra_config,
    )
    _, expected = load_yaml(sqlfluff_root / case.yml)
    actual = record_to_tuple(result.tree) if result.tree is not None else None
    exact = trees_match(expected, actual)
    no_unparsable = (
        result.tree is not None
        and not result.has_unparsable
        and not result.errors
        and result.rc == 0
    )
    reasons = []
    if not exact:
        reasons.append("tree differs" if result.tree is not None else "no tree")
    if result.has_unparsable:
        reasons.append("unparsable segment")
    reasons += result.errors
    checks = {"exact": exact, "no_unparsable": no_unparsable}
    return CaseResult(
        id=case.id,
        suite=NAME,
        tool=adapter.name,
        status=PASS if all(checks.values()) else FAIL,
        checks=checks,
        reason="; ".join(reasons),
    )
