"""The recorded S2 baseline (results/s2/baseline.json) and the drift check
of a run against it (harness/bench.md, "Baseline").

recorded() returns each reason why a report cannot be the baseline: it must
be a full run of all tools on all benchmarks of the definitions. drift()
compares the stable data of a run with the baseline: the sqlfluff ref, the
tool versions and settings, the input records, and for each result its
benchmark and status (and, if both are valid, its work). It does not
compare timings ("Noise control"). A result, tool, or input that the
baseline does not have is a difference, so the check fails closed.
missing() is the check of a full run (the CI job bench-merge): it must have
the profile and each result of the baseline.
"""

from collections.abc import Mapping
from typing import Any

from ..paths import REPO_ROOT
from . import registry, report
from . import run as bench_run
from .inputs import SIZES
from .timer import VALID

BASELINE = REPO_ROOT / "results" / "s2" / "baseline.json"
PROFILE = "full"
# The fields of a result that give its benchmark.
BENCHMARK = ("command", "dialect", "size", "input")


def recorded(base: Mapping[str, Any], defs: Mapping[str, Any]) -> list[str]:
    """Return each error that stops this report from being the baseline: a
    schema error, a scope that is not all tools of the registry on all
    benchmarks of the definitions, another profile or sqlfluff ref, a
    worktree with changes, or a result or input that is not complete."""
    errors = report.check(base)
    if errors:
        return [f"schema: {e}" for e in errors]
    want_scope = report.scope(
        registry.names(),
        sorted({b["dialect"] for b in defs["benchmarks"]}),
        report.ALL_COMMANDS,
        tuple(SIZES),
        None,
    )
    if base["scope"] != want_scope:
        errors.append(
            "the scope is not all tools of the registry on all benchmarks "
            f"of the definitions: {base['scope']}"
        )
    if base["profile"] != PROFILE:
        errors.append(f"profile {base['profile']}, not {PROFILE}")
    if base["sqlfluff_ref"] != defs["sqlfluff_ref"]:
        errors.append(
            f"sqlfluff_ref {base['sqlfluff_ref']} is not that of the definitions"
        )
    if not base["harness"]["clean"]:
        errors.append("the harness worktree had changes")
    errors += bench_run.incomplete(base, defs)
    want = sorted(b["id"] for b in defs["benchmarks"])
    for tool in base["scope"]["tools"]:
        have = sorted(r["id"] for r in base["results"] if r["tool"] == tool)
        if have != want:
            errors.append(f"{tool}: the benchmark ids are not those of the definitions")
    return errors


def _key(r: Mapping[str, Any]) -> tuple[str, str]:
    return r["id"], r["tool"]


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
        if want != record:
            errors.append(f"input {name}: {record}, baseline {want}")
    by_key = {_key(r): r for r in base["results"]}
    for r in sorted(rep["results"], key=_key):
        b = by_key.get(_key(r))
        where = f"{r['tool']} {r['id']}"
        if b is None:
            errors.append(f"{where}: no result in the baseline")
            continue
        for field in BENCHMARK:
            if r[field] != b[field]:
                errors.append(f"{where}: {field} {r[field]!r}, baseline {b[field]!r}")
        if r["status"] != b["status"]:
            errors.append(
                f"{where}: status {r['status']} ({r['reason']}), baseline "
                f"{b['status']} ({b['reason']})"
            )
        elif r["status"] == VALID and r["work"] != b["work"]:
            errors.append(f"{where}: work {r['work']}, baseline {b['work']}")
    return errors


def missing(rep: Mapping[str, Any], base: Mapping[str, Any]) -> list[str]:
    """Return each reason why rep is not a run of all benchmarks of base:
    another profile, or a result of base that rep does not have."""
    errors = []
    if rep["profile"] != base["profile"]:
        errors.append(f"profile {rep['profile']}, baseline {base['profile']}")
    have = {_key(r) for r in rep["results"]}
    lost = sorted(
        f"{t} {i}" for i, t in map(_key, base["results"]) if (i, t) not in have
    )
    if lost:
        errors.append(
            f"no result for {len(lost)} results of the baseline: {bench_run.few(lost)}"
        )
    return errors
