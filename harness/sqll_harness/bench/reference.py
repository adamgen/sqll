"""The sqlfluff reference of the definitions (harness/bench.md, "Validity").

For each input (not start), sqlfluff lints and fixes it with the benchmark
settings, through its benchmark adapter. The reference stores the rule codes
of lint, and if fix changes the file. Each run must pass the checks of
harness/bench.md (only the comparison with the reference is off), so an
invalid run gives no reference.
"""

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .adapter import FIX, LINT, BenchAdapter, Context
from .definitions import REFERENCE_TOOL
from .inputs import START


def make(
    adapter: BenchAdapter,
    definitions: Mapping[str, Any],
    inputs_dir: Path,
    work_root: Path,
    jobs: int = 1,
) -> tuple[dict, list[str]]:
    """Return (reference, errors). The adapter must be that of sqlfluff."""
    if adapter.name != REFERENCE_TOOL:
        raise ValueError(f"the reference tool is {REFERENCE_TOOL}, not {adapter.name}")
    ctx = Context(definitions, inputs_dir, work_root, record_reference=True)
    names = [n for n in definitions["inputs"] if n != START]

    def one(name: str) -> str | None:
        return ctx.validity(adapter, FIX, name.split("/")[0], name)

    with ThreadPoolExecutor(max(1, jobs)) as pool:
        reasons = dict(zip(names, pool.map(one, names), strict=True))
    errors = [f"{name}: {reason}" for name, reason in reasons.items() if reason]
    entries = {}
    for name in names:
        if reasons[name]:
            continue
        dialect = name.split("/")[0]
        lint = ctx.work[(adapter.name, LINT, dialect, name)]
        fix = ctx.work[(adapter.name, FIX, dialect, name)]
        entries[name] = {
            "sha256": definitions["inputs"][name]["sha256"],
            "lint_codes": lint["codes"],
            "fix_changes": fix["changed"],
        }
    reference = {"sqlfluff_version": adapter.version(), "inputs": entries}
    return reference, errors


def differences(old: Mapping[str, Any] | None, new: Mapping[str, Any]) -> list[str]:
    """Return each difference between a recorded reference and a new one."""
    old = old or {}
    out = []
    key = "sqlfluff_version"
    if old.get(key) != new[key]:
        out.append(f"{key}: recorded {old.get(key)!r}, new {new[key]!r}")
    old_inputs = old.get("inputs") or {}
    for name in sorted(set(old_inputs) | set(new["inputs"])):
        a, b = old_inputs.get(name), new["inputs"].get(name)
        if a != b:
            out.append(f"{name}: recorded {a}, new {b}")
    return out
