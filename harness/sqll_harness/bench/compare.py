"""Compare benchmark reports (harness/bench.md, "Slowdowns"; the output
schema is in harness/README.md, "Benchmark compare").

compare(base, new) compares each benchmark and tool that both reports have,
and flags a slowdown above the noise limit. tool_totals() compares the tools
of one report over the benchmarks that are valid for all of them. Each
total uses only valid results.
"""

import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

from ..paths import OUT_DIR
from . import report
from . import run as bench_run
from .timer import DIGITS, VALID

KIND = "sqll-bench-compare"
FORMAT = 1
DEFAULT_OUT = OUT_DIR / "bench-compare.json"
METRICS = {"wall": "wall_s", "cpu": "cpu_s"}

SLOWER = "slower"
FASTER = "faster"
SAME = "same"
FAILURE = "failure"
STATUS = "status"
NOT_VALID = "not_valid"
CHANGES = (SLOWER, FASTER, SAME, FAILURE, STATUS, NOT_VALID)

TOP = (
    "kind",
    "format",
    "base",
    "new",
    "noise",
    "tools",
    "warnings",
    "benchmarks",
    "only_base",
    "only_new",
    "totals",
    "tool_totals",
    "counts",
    "ok",
)
REPORT_REF = ("path", "commit", "clean", "profile", "machine")
BENCHMARK = (
    "id",
    "tool",
    "base_status",
    "new_status",
    "reason",
    "change",
    "wall",
    "cpu",
)
METRIC = ("base", "new", "ratio", "limit", "change")
TOTAL = ("benchmarks", "wall_s", "cpu_s", "wall_ratio", "cpu_ratio")
TOOL_TOTALS = ("tools", "benchmarks", "excluded", "wall_s", "cpu_s", "pairs")
PAIR = ("tools", "wall_ratio", "cpu_ratio", "first_slower", "first_faster")


class CompareError(Exception):
    """The reports cannot be compared."""


@dataclass(frozen=True)
class Noise:
    """The noise limit (harness/bench.md, "Slowdowns").

    A metric is slower if NEW/BASE of its median is more than 1 + limit, and
    faster if it is less than 1 / (1 + limit). limit is the largest of the
    fixed part of the metric (wall_pct or cpu_pct), k times the sum of the
    relative MADs (MAD / median) of the 2 results, and min_diff_s / the BASE
    median.
    """

    wall_pct: float = 0.25
    cpu_pct: float = 0.10
    k: float = 3.0
    min_diff_s: float = 0.005

    def limit(self, name: str, base: Mapping, new: Mapping) -> float:
        pct = {"wall": self.wall_pct, "cpu": self.cpu_pct}[name]
        spread = _relative_mad(base) + _relative_mad(new)
        return round(
            max(pct, self.k * spread, self.min_diff_s / base["median"]), DIGITS
        )


NOISE = Noise()


def _relative_mad(stats: Mapping) -> float:
    return stats["mad"] / stats["median"] if stats["median"] else 0.0


def _ratio(a: float, b: float) -> float | None:
    return round(a / b, DIGITS) if b else None


def metric(name: str, base: Mapping, new: Mapping, noise: Noise = NOISE) -> dict:
    """Compare the stats of one metric (wall or cpu) of 2 valid results."""
    b, n = base["median"], new["median"]
    if b == 0:
        # No ratio. Only the absolute limit applies.
        change = SLOWER if n - b > noise.min_diff_s else SAME
        return {"base": b, "new": n, "ratio": None, "limit": None, "change": change}
    limit = noise.limit(name, base, new)
    ratio = n / b
    if ratio > 1 + limit:
        change = SLOWER
    elif ratio < 1 / (1 + limit):
        change = FASTER
    else:
        change = SAME
    return {
        "base": b,
        "new": n,
        "ratio": round(ratio, DIGITS),
        "limit": limit,
        "change": change,
    }


def benchmark_entry(base: Mapping, new: Mapping, noise: Noise = NOISE) -> dict:
    """Compare the results of one benchmark and tool in 2 reports."""
    entry = {
        "id": new["id"],
        "tool": new["tool"],
        "base_status": base["status"],
        "new_status": new["status"],
        "reason": new["reason"],
        "change": None,
        "wall": None,
        "cpu": None,
    }
    if base["status"] == VALID and new["status"] == VALID:
        for name, key in METRICS.items():
            entry[name] = metric(name, base["stats"][key], new["stats"][key], noise)
        changes = {entry[name]["change"] for name in METRICS}
        entry["change"] = next(c for c in (SLOWER, FASTER, SAME) if c in changes)
    elif base["status"] == VALID:
        entry["change"] = FAILURE
    elif base["status"] != new["status"]:
        entry["change"] = STATUS
    else:
        entry["change"] = NOT_VALID
    return entry


def _by_key(rep: Mapping) -> dict[tuple[str, str], dict]:
    return {(r["id"], r["tool"]): r for r in rep["results"]}


def _sum(results: Iterable[Mapping], key: str) -> float:
    return round(sum(r["stats"][key]["median"] for r in results), DIGITS)


def totals(base: Mapping, new: Mapping, tools: Iterable[str]) -> dict:
    """For each tool, the sums of the median times in BASE and NEW over the
    benchmarks where the tool is valid in both reports."""
    b, n = _by_key(base), _by_key(new)
    out = {}
    for tool in sorted(tools):
        keys = sorted(
            k
            for k in set(b) & set(n)
            if k[1] == tool and b[k]["status"] == VALID and n[k]["status"] == VALID
        )
        entry: dict[str, Any] = {"benchmarks": len(keys)}
        for name, key in METRICS.items():
            sums = [_sum((b[k] for k in keys), key), _sum((n[k] for k in keys), key)]
            entry[key] = sums
            entry[f"{name}_ratio"] = _ratio(sums[1], sums[0])
        out[tool] = {k: entry[k] for k in TOTAL}
    return out


def tool_totals(rep: Mapping, tools: Iterable[str]) -> dict:
    """Compare tools in one report. The sums use only the benchmarks where
    each of the tools has a valid result; the others are in "excluded"."""
    tools = sorted(tools)
    results = _by_key(rep)
    ids = sorted({r["id"] for r in rep["results"]})
    used, excluded = [], []
    for i in ids:
        mine = {t: results.get((i, t)) for t in tools}
        if tools and all(r is not None and r["status"] == VALID for r in mine.values()):
            used.append(i)
        elif any(r is not None for r in mine.values()):
            statuses = {t: r["status"] for t, r in mine.items() if r is not None}
            excluded.append({"id": i, "statuses": statuses})
    sums = {
        key: {t: _sum((results[(i, t)] for i in used), key) for t in tools}
        for key in METRICS.values()
    }
    pairs = []
    for a, b in combinations(tools, 2):
        wall = [
            (
                results[(i, a)]["stats"]["wall_s"]["median"],
                results[(i, b)]["stats"]["wall_s"]["median"],
            )
            for i in used
        ]
        pairs.append(
            {
                "tools": [a, b],
                "wall_ratio": _ratio(sums["wall_s"][a], sums["wall_s"][b]),
                "cpu_ratio": _ratio(sums["cpu_s"][a], sums["cpu_s"][b]),
                "first_slower": sum(x > y for x, y in wall),
                "first_faster": sum(x < y for x, y in wall),
            }
        )
    return {
        "tools": tools,
        "benchmarks": len(used),
        "excluded": excluded,
        "wall_s": sums["wall_s"],
        "cpu_s": sums["cpu_s"],
        "pairs": pairs,
    }


def _report_ref(path: str, rep: Mapping) -> dict:
    return {
        "path": path,
        "commit": rep["harness"]["commit"],
        "clean": rep["harness"]["clean"],
        "profile": rep["profile"],
        "machine": rep["machine"],
    }


def _check(name: str, rep: Any) -> None:
    errors = report.check(rep)
    if not errors:
        errors = bench_run.incomplete(rep)
    if errors:
        more = f" and {len(errors) - 3} more" if len(errors) > 3 else ""
        raise CompareError(f"{name}: {'; '.join(errors[:3])}{more}")


def _tools(reports: list[Mapping], only: Iterable[str] | None) -> list[str]:
    known = sorted({t for rep in reports for t in rep["tools"]})
    if not only:
        return known
    unknown = sorted(set(only) - set(known))
    if unknown:
        raise CompareError(f"no report has the tool {', '.join(unknown)}")
    return sorted(set(only))


def _refuse_mismatch(base: Mapping, new: Mapping, tools: list[str]) -> None:
    """CompareError if an input or the settings of a compared tool differ."""
    errors = []
    for name in sorted(set(base["inputs"]) & set(new["inputs"])):
        b, n = base["inputs"][name], new["inputs"][name]
        if b != n:
            errors.append(
                f"input {name}: sha256 {b['sha256'][:12]} ({b['bytes']} bytes) "
                f"in BASE, {n['sha256'][:12]} ({n['bytes']} bytes) in NEW"
            )
    for tool in tools:
        if tool in base["tools"] and tool in new["tools"]:
            b, n = base["tools"][tool]["settings"], new["tools"][tool]["settings"]
            if b != n:
                errors.append(f"tool {tool}: settings {b} in BASE, {n} in NEW")
    if errors:
        raise CompareError("different inputs or settings: " + "; ".join(errors))


def _warnings(base: Mapping, new: Mapping, tools: list[str]) -> list[str]:
    out = []
    for key in ("sqlfluff_ref", "profile", "machine"):
        if base[key] != new[key]:
            out.append(f"the {key} of BASE and NEW differ")
    for name, rep in (("BASE", base), ("NEW", new)):
        if not rep["harness"]["clean"]:
            out.append(f"{name} is of a worktree with changes")
        if rep["policy"]["max_runs"] == 1:
            out.append(
                f"{name} has 1 timed run for each benchmark (profile "
                f"{rep['profile']}): expect false slowdowns"
            )
    for tool in tools:
        if tool in base["tools"] and tool in new["tools"]:
            b, n = base["tools"][tool]["version"], new["tools"][tool]["version"]
            if b != n:
                out.append(f"tool {tool}: version {b} in BASE, {n} in NEW")
    return out


def _counts(entries: list[dict]) -> dict:
    return {"compared": len(entries)} | {
        c: sum(e["change"] == c for e in entries) for c in CHANGES
    }


def compare(
    new: tuple[str, Any],
    base: tuple[str, Any] | None = None,
    tools: Iterable[str] | None = None,
    noise: Noise = NOISE,
) -> dict:
    """Compare NEW with BASE, and the tools of NEW. Each is (path, report).
    With no BASE, only the tools of NEW. CompareError if a report has a
    schema error or is not complete for its scope, if a tool is in no
    report, or if an input or the settings of a compared tool differ."""
    new_path, new_rep = new
    _check("NEW", new_rep)
    reports = [new_rep]
    if base is not None:
        _check("BASE", base[1])
        reports.insert(0, base[1])
    names = _tools(reports, tools)
    out = {
        "kind": KIND,
        "format": FORMAT,
        "base": None,
        "new": _report_ref(new_path, new_rep),
        "noise": asdict(noise),
        "tools": {
            t: {
                "base": base[1]["tools"].get(t, {}).get("version") if base else None,
                "new": new_rep["tools"].get(t, {}).get("version"),
            }
            for t in names
        },
        "warnings": [],
        "benchmarks": [],
        "only_base": [],
        "only_new": [],
        "totals": {},
        "tool_totals": tool_totals(
            new_rep, [t for t in names if t in new_rep["tools"]]
        ),
    }
    if base is not None:
        base_path, base_rep = base
        _refuse_mismatch(base_rep, new_rep, names)
        b, n = _by_key(base_rep), _by_key(new_rep)
        keys = sorted(k for k in set(b) | set(n) if k[1] in names)
        out["base"] = _report_ref(base_path, base_rep)
        out["warnings"] = _warnings(base_rep, new_rep, names)
        out["benchmarks"] = [
            benchmark_entry(b[k], n[k], noise) for k in keys if k in b and k in n
        ]
        out["only_base"] = [{"id": i, "tool": t} for i, t in keys if (i, t) not in n]
        out["only_new"] = [{"id": i, "tool": t} for i, t in keys if (i, t) not in b]
        both = [t for t in names if t in base_rep["tools"] and t in new_rep["tools"]]
        out["totals"] = totals(base_rep, new_rep, both)
    out["counts"] = _counts(out["benchmarks"])
    out["ok"] = out["counts"][SLOWER] == 0 and out["counts"][FAILURE] == 0
    return out


def write(result: Mapping, path: Path = DEFAULT_OUT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1) + "\n", encoding="utf8")


# Text summary.


def _metric_text(m: Mapping | None) -> str:
    if m is None:
        return "-"
    if m["ratio"] is None:
        return f"{m['base']:.3f} -> {m['new']:.3f} s"
    return (
        f"{m['base']:.3f} -> {m['new']:.3f} s ({m['ratio']:.3f}, "
        f"limit {1 + m['limit']:.3f})"
    )


def summary_lines(result: Mapping) -> list[str]:
    lines = []
    new = result["new"]
    base = result["base"]
    if base is not None:
        c = result["counts"]
        lines.append(
            f"BASE {base['path']} ({base['commit'][:12]}, {base['profile']}), "
            f"NEW {new['path']} ({new['commit'][:12]}, {new['profile']}): "
            f"{c['compared']} compared; slower {c[SLOWER]}, faster {c[FASTER]}, "
            f"same {c[SAME]}, failure {c[FAILURE]}, other status change "
            f"{c[STATUS]}, not valid in both {c[NOT_VALID]}"
        )
        if result["only_base"] or result["only_new"]:
            lines.append(
                f"not compared: {len(result['only_base'])} only in BASE, "
                f"{len(result['only_new'])} only in NEW"
            )
        lines += [f"warning: {w}" for w in result["warnings"]]
        for e in result["benchmarks"]:
            if e["change"] == SLOWER:
                lines.append(
                    f"  slower: {e['tool']} {e['id']}: wall {_metric_text(e['wall'])}"
                    f", cpu {_metric_text(e['cpu'])}"
                )
        for e in result["benchmarks"]:
            if e["change"] in (FAILURE, STATUS):
                reason = (e["reason"] or "").replace("\n", " ")[:120]
                lines.append(
                    f"  {e['change']}: {e['tool']} {e['id']}: {e['base_status']} -> "
                    f"{e['new_status']}" + (f": {reason}" if reason else "")
                )
        lines.append("totals (the benchmarks where the tool is valid in both):")
        for tool, t in result["totals"].items():
            ratio = "-" if t["wall_ratio"] is None else f"{t['wall_ratio']:.3f}"
            lines.append(
                f"  {tool}: {t['benchmarks']} benchmarks, wall "
                f"{t['wall_s'][0]:.3f} -> {t['wall_s'][1]:.3f} s ({ratio})"
            )
    tt = result["tool_totals"]
    lines.append(
        f"tools of NEW: {tt['benchmarks']} benchmarks valid for all of "
        f"{', '.join(tt['tools'])} ({len(tt['excluded'])} excluded)"
    )
    for tool in tt["tools"]:
        lines.append(
            f"  {tool}: wall {tt['wall_s'][tool]:.3f} s, cpu {tt['cpu_s'][tool]:.3f} s"
        )
    for p in tt["pairs"]:
        a, b = p["tools"]
        ratio = "-" if p["wall_ratio"] is None else f"{p['wall_ratio']:.3f}"
        lines.append(
            f"  {a} / {b}: wall {ratio}; {a} is slower on {p['first_slower']}, "
            f"faster on {p['first_faster']}"
        )
    return lines
