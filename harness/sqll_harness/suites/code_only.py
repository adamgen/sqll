"""Code-only filter check: the dialect cases, with sqlfluff.

sqruff has no code-only parse output, so the harness makes it from the full
tree with code_only.code_only_record. This suite proves the filter: for each
dialect case, sqlfluff parses the SQL file 2 times, with and without -c, as
the dialects suite does. The filtered full record must be equal to the -c
record. It is a check of the harness, not of a tool, so only the tools in
TOOLS run it. See harness/sqruff.md.
"""

from pathlib import Path

from ..adapters import Adapter
from ..cases import ERROR, FAIL, PASS, CaseResult
from ..code_only import code_only_record
from ..compare import record_to_tuple
from . import dialects

NAME = "code_only"
TOOLS = ("sqlfluff",)


def discover(sqlfluff_root: Path) -> list[dialects.DialectCase]:
    """The dialect cases, with ids code_only/<dialect>/<stem>."""
    out = []
    for case in dialects.discover(sqlfluff_root):
        rest = case.id.removeprefix(f"{dialects.NAME}/")
        out.append(
            dialects.DialectCase(
                id=f"{NAME}/{rest}",
                dialect=case.dialect,
                sql=case.sql,
                yml=case.yml,
                code_only=case.code_only,
                extra_config=case.extra_config,
            )
        )
    return out


def run(adapter: Adapter, case: dialects.DialectCase, sqlfluff_root: Path):
    def parse(code_only: bool):
        return adapter.parse(
            case.sql,
            case.dialect,
            code_only=code_only,
            include_meta=False,
            cwd=sqlfluff_root,
            extra_config=case.extra_config,
        )

    full, code = parse(False), parse(True)
    if full.tree is None or code.tree is None:
        # A parse error alone (exit code 1) still gives 2 trees to compare.
        errors = [f"full: {e}" for e in full.errors]
        errors += [f"-c: {e}" for e in code.errors]
        return CaseResult(
            case.id, NAME, adapter.name, ERROR, reason="; ".join(errors) or "no tree"
        )
    try:
        filtered = code_only_record(full.tree)
    except ValueError as exc:
        return CaseResult(case.id, NAME, adapter.name, ERROR, reason=str(exc))
    # Both comparisons: the record (dict order is not compared) and the tuple
    # (the order of the children is compared).
    same = filtered == code.tree and record_to_tuple(filtered) == record_to_tuple(
        code.tree
    )
    return CaseResult(
        case.id,
        NAME,
        adapter.name,
        PASS if same else FAIL,
        checks={"filter": same},
        reason="" if same else "the filtered tree is not the -c tree",
    )
