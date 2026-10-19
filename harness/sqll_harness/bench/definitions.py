"""Benchmark definitions: harness/sqll_harness/bench/definitions.json.

The definitions are data with no tool entry. They give each benchmark id,
the bytes, lines, and sha256 of each built input, and the sqlfluff reference
of each input (the lint rule codes, and if fix changes the file; made by
"sqll-harness bench reference"). make() makes them from a build; check()
compares a build with the recorded definitions, so a change of a fixture, of
the exclusion list, or of the builder fails closed. check_reference() finds
a missing reference or a reference of another input.
"""

import json
from pathlib import Path

from .inputs import (
    ADDED_NEWLINE,
    ADDED_TERMINATOR,
    SIZES,
    SKIP_REASONS,
    START,
    Build,
)

DEFINITIONS = Path(__file__).with_name("definitions.json")
FORMAT = 2
REFERENCE_TOOL = "sqlfluff"
REFERENCE_FIELDS = ("sha256", "lint_codes", "fix_changes")
COMMANDS = ("parse", "lint", "fix")


def benchmarks(dialects: list[str]) -> list[dict]:
    """Return the benchmarks of these dialects, in run order."""
    out = []
    for dialect in dialects:
        out.append(
            {
                "id": f"start/{dialect}",
                "command": START,
                "dialect": dialect,
                "size": None,
                "input": START,
            }
        )
        for command in COMMANDS:
            for size in SIZES:
                out.append(
                    {
                        "id": f"{command}/{dialect}/{size}",
                        "command": command,
                        "dialect": dialect,
                        "size": size,
                        "input": f"{dialect}/{size}",
                    }
                )
    return out


def make(result: Build, reference: dict | None = None) -> dict:
    """Return the definitions of a build, with this reference
    ({"sqlfluff_version", "inputs"}; None: an empty one)."""
    sel = result.selection
    used = [p for pieces in sel.pieces.values() for p in pieces]
    return {
        "format": FORMAT,
        "sqlfluff_ref": result.sqlfluff_ref,
        "sizes": dict(SIZES),
        "selection": {
            "files": sel.files,
            "used": len(used),
            "skipped": {r: len(sel.skipped[r]) for r in SKIP_REASONS},
            "terminators_added": sum(ADDED_TERMINATOR in p.added for p in used),
            "newlines_added": sum(ADDED_NEWLINE in p.added for p in used),
        },
        "inputs": {
            name: {"bytes": len(i.data), "lines": i.lines, "sha256": i.sha256}
            for name, i in result.inputs.items()
        },
        "reference": reference or {"sqlfluff_version": None, "inputs": {}},
        "benchmarks": benchmarks(result.dialects),
    }


def render(defs: dict) -> str:
    """Return the file text: one line for each input and each benchmark."""

    def one(obj) -> str:
        return json.dumps(obj, separators=(", ", ": "))

    lines = ["{"]
    for key in ("format", "sqlfluff_ref", "sizes", "selection"):
        lines.append(f" {json.dumps(key)}: {one(defs[key])},")
    lines.append(' "inputs": {')
    items = [f"  {json.dumps(k)}: {one(v)}" for k, v in defs["inputs"].items()]
    lines.append(",\n".join(items))
    lines.append(" },")
    ref = defs["reference"]
    lines.append(' "reference": {')
    lines.append(f'  "sqlfluff_version": {one(ref["sqlfluff_version"])},')
    lines.append('  "inputs": {')
    items = [f"   {json.dumps(k)}: {one(v)}" for k, v in ref["inputs"].items()]
    lines.append(",\n".join(items))
    lines.append("  }")
    lines.append(" },")
    lines.append(' "benchmarks": [')
    lines.append(",\n".join(f"  {one(b)}" for b in defs["benchmarks"]))
    lines.append(" ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def load(path: Path = DEFINITIONS) -> dict:
    return json.loads(path.read_text(encoding="utf8"))


def check(recorded: dict, result: Build) -> list[str]:
    """Return each difference between the recorded definitions and a build."""
    new = make(result)
    errors = []
    for key in ("format", "sqlfluff_ref", "sizes", "selection"):
        if recorded.get(key) != new[key]:
            errors.append(f"{key}: recorded {recorded.get(key)!r}, built {new[key]!r}")
    old_inputs = recorded.get("inputs", {})
    for name in sorted(set(old_inputs) | set(new["inputs"])):
        old, cur = old_inputs.get(name), new["inputs"].get(name)
        if old is None:
            errors.append(f"input {name}: built, but not in the definitions")
        elif cur is None:
            errors.append(f"input {name}: in the definitions, but not built")
        elif old != cur:
            errors.append(f"input {name}: recorded {old}, built {cur}")
    if recorded.get("benchmarks") != new["benchmarks"]:
        old_ids = [b.get("id") for b in recorded.get("benchmarks", [])]
        new_ids = [b["id"] for b in new["benchmarks"]]
        errors.append(
            "benchmarks differ: "
            f"missing {sorted(set(new_ids) - set(old_ids))}, "
            f"extra {sorted(set(old_ids) - set(new_ids))}"
            + (
                " (same ids, other fields or order)"
                if set(old_ids) == set(new_ids)
                else ""
            )
        )
    return errors


def check_reference(defs: dict) -> list[str]:
    """Return each error of the sqlfluff reference of the definitions: each
    input (not start) needs an entry for its sha256."""
    ref = defs.get("reference")
    if not isinstance(ref, dict) or set(ref) != {"sqlfluff_version", "inputs"}:
        return ["reference: not an object with sqlfluff_version and inputs"]
    errors = []
    if not isinstance(ref["sqlfluff_version"], str) or not ref["sqlfluff_version"]:
        errors.append("reference: no sqlfluff_version")
    entries = ref.get("inputs") or {}
    names = [n for n in defs["inputs"] if n != START]
    for name in names:
        entry = entries.get(name)
        if entry is None:
            errors.append(f"reference {name}: missing")
        elif not isinstance(entry, dict) or tuple(entry) != REFERENCE_FIELDS:
            errors.append(f"reference {name}: the fields are not {REFERENCE_FIELDS}")
        elif entry["sha256"] != defs["inputs"][name]["sha256"]:
            errors.append(f"reference {name}: made for another input (sha256)")
        elif not _good_entry(entry):
            errors.append(f"reference {name}: bad value {entry}")
    for name in sorted(set(entries) - set(names)):
        errors.append(f"reference {name}: not an input")
    return errors


def _good_entry(entry: dict) -> bool:
    codes = entry["lint_codes"]
    return (
        isinstance(entry["fix_changes"], bool)
        and isinstance(codes, list)
        and all(isinstance(c, str) for c in codes)
        and codes == sorted(set(codes))
    )
