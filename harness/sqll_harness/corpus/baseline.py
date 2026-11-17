"""The recorded corpus baseline and the drift check of a run against it
(docs/decisions/s9-corpus.md, "Report"), as in S2 (bench/baseline.py).

recorded() returns each reason why a report cannot be the baseline: it must
be a complete full run of the default tools (run.tool_names()) on all files of
the manifest, from a worktree with no change. drift() compares the stable
data of a run with the baseline: the sqlfluff ref, the tool versions and
settings, the input records (with their sha256 and the reference render),
and for each result its status and its unparsable count and bytes. It does
not compare timings, reasons, exit codes, or the machine. A result, tool,
or input that the baseline does not have is a difference, so the check
fails closed. missing() is the check of a full run: it must have the
profile and each result of the baseline.

sqll (docs/decisions/s9-corpus.md, "sqll results", decision 3): drift()
compares the same stable data of sqll, and each change fails, in each
direction. The message of a changed sqll result also gives the direction
("worse" or "better", direction()) and says if the new result is the
sqlfluff result of the file. The messages of the other tools do not change.
rebase() replaces only the sqll tool record and the sqll results of a
baseline with those of a full report, and fails closed on each other change.
"""

from collections.abc import Mapping
from typing import Any

from ..paths import REPO_ROOT
from . import report
from . import run as corpus_run
from .manifest import Manifest

PROFILE = "full"
# The report of the controlled full run (status/S9.md, "S9 results").
BASELINE = REPO_ROOT / "results" / "S9" / "baseline.json"
# The tool whose results can change on main (S4 and the core paths change
# its parser), and the tool of the target result of each file.
SQLL = "sqll"
TARGET = "sqlfluff"
REBASE_TOOLS = (SQLL,)
WORSE = "worse"
BETTER = "better"
# The statuses from better to worse (decision 3).
ORDER = (
    report.OK,
    report.UNPARSABLE,
    report.NO_REFERENCE,
    report.UNSUPPORTED,
    report.INVALID,
    report.ERROR,
)


class RebaseError(Exception):
    """The report cannot give the new results of the baseline."""


def recorded(base: Mapping[str, Any], manifest: Manifest) -> list[str]:
    """Return each error that stops this report from being the baseline."""
    errors = report.check(base)
    if errors:
        return [f"schema: {e}" for e in errors]
    if base["profile"] != PROFILE:
        errors.append(f"profile {base['profile']}, not {PROFILE}")
        return errors
    if base["scope"] != corpus_run.scope(corpus_run.tool_names(), None):
        errors.append(
            f"the scope is not the default tools, not sharded: {base['scope']}"
        )
    if not base["harness"]["clean"]:
        errors.append("the harness worktree had changes")
    errors += corpus_run.incomplete(base, manifest)
    return errors


def _key(r: Mapping[str, Any]) -> tuple[str, str]:
    return r["file"], r["tool"]


def drift(rep: Mapping[str, Any], base: Mapping[str, Any]) -> list[str]:
    """Return each difference of the stable data of rep from base. Call it
    on reports with no schema error."""
    errors = []
    if rep["sqlfluff_ref"] != base["sqlfluff_ref"]:
        errors.append(
            f"sqlfluff_ref {rep['sqlfluff_ref']}, baseline {base['sqlfluff_ref']}"
        )
    for tool, record in sorted(rep["tools"].items()):
        want = base["tools"].get(tool)
        if want is None:
            errors.append(f"tool {tool}: not in the baseline")
            continue
        if record["version"] != want["version"]:
            errors.append(
                f"tool {tool}: version {record['version']}, baseline {want['version']}"
            )
        if record["settings"] != want["settings"]:
            errors.append(f"tool {tool}: the settings are not those of the baseline")
    for name, record in sorted(rep["inputs"].items()):
        want = base["inputs"].get(name)
        if want is None:
            errors.append(f"input {name}: not in the baseline")
            continue
        for key in report.INPUT:
            a, b = record[key], want[key]
            if key == "reference" and a is not None and b is not None:
                a = {k: a[k] for k in ("status", "sha256")}
                b = {k: b[k] for k in ("status", "sha256")}
            if a != b:
                errors.append(f"input {name}: {key} {a!r}, baseline {b!r}")
    by_key = {_key(r): r for r in base["results"]}
    targets = _targets(rep, base)
    for r in sorted(rep["results"], key=_key):
        b = by_key.get(_key(r))
        where = f"{r['tool']} {r['file']}"
        if b is None:
            errors.append(f"{where}: no result in the baseline")
            continue
        if r["status"] != b["status"]:
            text = (
                f"{where}: status {r['status']} ({r['reason']}), baseline "
                f"{b['status']} ({b['reason']})"
            )
        elif r["unparsable"] != b["unparsable"]:
            text = f"{where}: unparsable {r['unparsable']}, baseline {b['unparsable']}"
        else:
            continue
        if r["tool"] == SQLL:
            text += f"; {direction(b, r)}; {target_text(r, targets.get(r['file']))}"
        errors.append(text)
    return errors


def _rank(r: Mapping[str, Any]) -> tuple[int, int, int]:
    """The order of a result, from better (small) to worse: the status, then
    the unparsable bytes, then the unparsable count."""
    u = r["unparsable"] or {"count": 0, "bytes": 0}
    return ORDER.index(r["status"]), u["bytes"], u["count"]


def direction(old: Mapping[str, Any], new: Mapping[str, Any]) -> str:
    """Return WORSE or BETTER for a result that changed from old to new: the
    status order (ORDER); with the same status, fewer unparsable bytes is
    better, and with the same bytes, fewer unparsable segments."""
    return WORSE if _rank(new) > _rank(old) else BETTER


def stable(r: Mapping[str, Any]) -> tuple[str, Any]:
    return r["status"], r["unparsable"]


def _targets(rep: Mapping[str, Any], base: Mapping[str, Any]) -> dict[str, dict]:
    """Return the TARGET result of each file: that of the report, else that
    of the baseline."""
    out = {r["file"]: r for r in base["results"] if r["tool"] == TARGET}
    out.update({r["file"]: r for r in rep["results"] if r["tool"] == TARGET})
    return out


def target_text(r: Mapping[str, Any], target: Mapping[str, Any] | None) -> str:
    """Say if the new result r is the TARGET result of its file."""
    if target is None:
        return f"the file has no {TARGET} result"
    if stable(r) == stable(target):
        return f"the new result is the {TARGET} result of the file"
    return (
        f"the new result is not the {TARGET} result of the file "
        f"({target['status']}, unparsable {target['unparsable']})"
    )


def missing(rep: Mapping[str, Any], base: Mapping[str, Any]) -> list[str]:
    """Return each reason why rep is not a run of all results of base:
    another profile, or a result of base that rep does not have."""
    errors = []
    if rep["profile"] != base["profile"]:
        errors.append(f"profile {rep['profile']}, baseline {base['profile']}")
    have = {_key(r) for r in rep["results"]}
    lost = sorted(
        f"{t} {f}" for f, t in map(_key, base["results"]) if (f, t) not in have
    )
    if lost:
        errors.append(
            f"no result for {len(lost)} results of the baseline: {corpus_run.few(lost)}"
        )
    return errors


def rebase(
    base: Mapping[str, Any], rep: Mapping[str, Any], tool: str, manifest: Manifest
) -> tuple[dict, list[str]]:
    """Return the baseline with the tool record and the results of tool
    from the full report rep, and a line for each changed result of tool.
    The totals, compared, and pairs are calculated again. RebaseError if
    base is not a recorded baseline with tool, if rep is not a complete full
    report of the same tools, or if rep changes anything else of the
    baseline: the stable data of another tool, an input, the sqlfluff ref,
    the manifest, the profile, or the policy."""
    if tool not in REBASE_TOOLS:
        raise RebaseError(f"only the results of {', '.join(REBASE_TOOLS)} can change")
    errors = [f"baseline: {e}" for e in recorded(base, manifest)]
    if not errors and tool not in base["tools"]:
        errors.append(
            f"baseline: no {tool} results; a complete baseline needs one "
            "controlled full run of all tools"
        )
    errors += [f"report: schema: {e}" for e in report.check(rep)]
    if not errors:
        errors += [f"report: {e}" for e in corpus_run.incomplete(rep, manifest)]
    if errors:
        raise RebaseError("; ".join(errors[:5]))
    for key in ("sqlfluff_ref", "profile", "policy", "manifest_sha256"):
        if rep[key] != base[key]:
            errors.append(f"report: {key} {rep[key]!r}, baseline {base[key]!r}")
    if rep["scope"] != base["scope"]:
        errors.append(f"report: scope {rep['scope']}, baseline {base['scope']}")
    others = _without(rep, tool)
    errors += [f"report: {e}" for e in drift(others, base)]
    errors += [f"report: {e}" for e in missing(rep, base)]
    if errors:
        raise RebaseError("; ".join(errors[:5]))
    results = [r for r in base["results"] if r["tool"] != tool]
    results += [r for r in rep["results"] if r["tool"] == tool]
    tools = {**base["tools"], tool: rep["tools"][tool]}
    new = report.build(
        sqlfluff_ref=base["sqlfluff_ref"],
        profile=base["profile"],
        policy=base["policy"],
        machine=base["machine"],
        harness=base["harness"],
        timer=base["timer"],
        manifest_sha256=base["manifest_sha256"],
        scope=base["scope"],
        tools=tools,
        inputs=base["inputs"],
        results=results,
        parts=base["parts"],
    )
    errors = [f"new baseline: {e}" for e in recorded(new, manifest)]
    if errors:
        raise RebaseError("; ".join(errors[:5]))
    return new, changes(base, new, tool)


def _without(rep: Mapping[str, Any], tool: str) -> dict:
    """Return the stable parts of rep that drift() reads, without tool."""
    return {
        "sqlfluff_ref": rep["sqlfluff_ref"],
        "tools": {t: v for t, v in rep["tools"].items() if t != tool},
        "inputs": rep["inputs"],
        "results": [r for r in rep["results"] if r["tool"] != tool],
    }


def changes(base: Mapping[str, Any], new: Mapping[str, Any], tool: str) -> list[str]:
    """Return a line for the changed version and settings of tool, and for
    each result of tool whose stable data changed from base to new: the
    file, the old and the new status and unparsable data, the direction,
    and if the new result is the TARGET result of the file."""
    lines = []
    old_tool, new_tool = base["tools"][tool], new["tools"][tool]
    if old_tool["version"] != new_tool["version"]:
        lines.append(
            f"tool {tool}: version {old_tool['version']} -> {new_tool['version']}"
        )
    if old_tool["settings"] != new_tool["settings"]:
        lines.append(f"tool {tool}: the settings changed")
    old = {r["file"]: r for r in base["results"] if r["tool"] == tool}
    targets = _targets(new, base)
    for r in sorted(new["results"], key=_key):
        b = old[r["file"]] if r["tool"] == tool else None
        if b is None or stable(b) == stable(r):
            continue
        lines.append(
            f"{tool} {r['file']}: {b['status']} (unparsable {b['unparsable']}) -> "
            f"{r['status']} (unparsable {r['unparsable']}): {direction(b, r)}; "
            f"{target_text(r, targets.get(r['file']))}"
        )
    return lines
