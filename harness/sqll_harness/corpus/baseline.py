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
    for r in sorted(rep["results"], key=_key):
        b = by_key.get(_key(r))
        where = f"{r['tool']} {r['file']}"
        if b is None:
            errors.append(f"{where}: no result in the baseline")
            continue
        if r["status"] != b["status"]:
            errors.append(
                f"{where}: status {r['status']} ({r['reason']}), baseline "
                f"{b['status']} ({b['reason']})"
            )
        elif r["unparsable"] != b["unparsable"]:
            errors.append(
                f"{where}: unparsable {r['unparsable']}, baseline {b['unparsable']}"
            )
    return errors


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
