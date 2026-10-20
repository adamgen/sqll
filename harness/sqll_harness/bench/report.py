"""The benchmark report: out/bench.json. harness/README.md has the schema.

build() makes a report, check() returns each schema error, and write()
writes only a report with no error. A result that is not valid keeps its
samples, but it has no stats, and totals and pairs use only valid results.
check() computes the stats, totals, pairs, and ratios again from the
samples, so a report cannot have other numbers.
"""

import json
import os
import platform
import re
import subprocess
from collections.abc import Iterable, Mapping
from itertools import combinations
from pathlib import Path

from ..paths import OUT_DIR, REPO_ROOT
from .definitions import COMMANDS
from .inputs import SIZES, START
from .timer import (
    DIGITS,
    PROFILES,
    STATUSES,
    TIMED,
    VALID,
    WARMUP,
    Measurement,
    Sample,
    sample_stats,
)

KIND = "sqll-bench-report"
FORMAT = 2
DEFAULT_REPORT = OUT_DIR / "bench.json"
ALL_COMMANDS = (START, *COMMANDS)

TOP = (
    "kind",
    "format",
    "sqlfluff_ref",
    "harness",
    "profile",
    "policy",
    "machine",
    "timer",
    "scope",
    "tools",
    "inputs",
    "results",
    "totals",
    "pairs",
    "parts",
)
HARNESS = ("commit", "clean")
MACHINE = ("cpu_model", "cpu_count", "memory_kib", "os", "kernel", "arch", "python")
TIMER = ("clock", "rusage", "overhead")
OVERHEAD = ("argv", "samples", "stats")
SCOPE = ("tools", "dialects", "commands", "sizes", "shard")
TOOL = ("version", "settings")
INPUT = ("bytes", "lines", "sha256")
RESULT = (
    "id",
    "command",
    "dialect",
    "size",
    "input",
    "tool",
    "status",
    "reason",
    "runs",
    "work",
    "samples",
    "stats",
    "ratio",
)
RUNS = (WARMUP, TIMED)
SAMPLE = ("kind", "wall_s", "user_s", "sys_s", "max_rss_kib", "exit_code", "timed_out")
COUNTS = STATUSES
TOTAL = (*COUNTS, "wall_s", "cpu_s")
PAIR = ("tools", "benchmarks", "skipped", "wall_s", "cpu_s", "wall_ratio")
PART = ("shard", "machine", "timer")
RATIO = ("wall", "cpu")
# The ratio of each result is to the result of this tool on the same benchmark.
RATIO_BASE = "sqlfluff"
SHARD = re.compile(r"(\d+)/(\d+)")
SHA256 = re.compile(r"[0-9a-f]{64}")


class ReportError(Exception):
    """The report does not agree with the schema."""


# Records of the run.


def machine() -> dict:
    """Return the record of this machine."""
    cpu_model = platform.processor() or "unknown"
    memory_kib = None
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                memory_kib = int(line.split()[1])
                break
    except (OSError, ValueError, IndexError):
        pass
    try:
        os_name = platform.freedesktop_os_release().get("PRETTY_NAME", "")
    except OSError:
        os_name = ""
    return {
        "cpu_model": cpu_model,
        "cpu_count": os.cpu_count() or 0,
        "memory_kib": memory_kib,
        "os": os_name or platform.system(),
        "kernel": platform.release(),
        "arch": platform.machine(),
        "python": platform.python_version(),
    }


def harness(root: Path = REPO_ROOT) -> dict:
    """Return the commit of the harness, and if the worktree has no change."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    try:
        return {
            "commit": git("rev-parse", "HEAD").strip(),
            "clean": git("status", "--porcelain").strip() == "",
        }
    except (OSError, subprocess.CalledProcessError):
        return {"commit": "unknown", "clean": False}


def scope(
    tools: Iterable[str],
    dialects: Iterable[str],
    commands: Iterable[str] = ALL_COMMANDS,
    sizes: Iterable[str] = tuple(SIZES),
    shard: tuple[int, int] | None = None,
) -> dict:
    """Return the record of what a run tried to run."""
    return {
        "tools": sorted(tools),
        "dialects": sorted(dialects),
        "commands": [c for c in ALL_COMMANDS if c in set(commands)],
        "sizes": [s for s in SIZES if s in set(sizes)],
        "shard": f"{shard[0]}/{shard[1]}" if shard else None,
    }


def result_entry(
    benchmark: Mapping, tool: str, m: Measurement, work: dict | None = None
) -> dict:
    """Return the report entry of one benchmark (a definitions entry) and tool."""
    return {
        "id": benchmark["id"],
        "command": benchmark["command"],
        "dialect": benchmark["dialect"],
        "size": benchmark["size"],
        "input": benchmark["input"],
        "tool": tool,
        "status": m.status,
        "reason": m.reason,
        "runs": {k: sum(s.kind == k for s in m.samples) for k in RUNS},
        "work": work,
        "samples": [s.as_dict() for s in m.samples],
        "stats": m.stats if m.status == VALID else None,
        "ratio": None,
    }


# Totals and pairs: only valid results.


def _valid(results: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r["tool"], r["id"]): r for r in results if r["status"] == VALID}


def totals(results: list[dict], tools: Iterable[str]) -> dict:
    """Return for each tool the count of each status, and the sum of the
    median wall and CPU times of its valid results."""
    out = {}
    for tool in sorted(tools):
        mine = [r for r in results if r["tool"] == tool]
        valid = [r for r in mine if r["status"] == VALID]
        entry = {s: sum(r["status"] == s for r in mine) for s in COUNTS}
        for key in ("wall_s", "cpu_s"):
            entry[key] = round(sum(r["stats"][key]["median"] for r in valid), DIGITS)
        out[tool] = entry
    return out


def pairs(results: list[dict], tools: Iterable[str]) -> list[dict]:
    """Return for each pair of tools the sums of the median times over the
    benchmarks where both are valid. skipped counts the other benchmarks
    that one of the 2 tools has."""
    valid = _valid(results)
    out = []
    for a, b in combinations(sorted(tools), 2):
        ids = {r["id"] for r in results if r["tool"] in (a, b)}
        both = sorted(i for i in ids if (a, i) in valid and (b, i) in valid)
        sums = {}
        for key in ("wall_s", "cpu_s"):
            sums[key] = [
                round(sum(valid[(t, i)]["stats"][key]["median"] for i in both), DIGITS)
                for t in (a, b)
            ]
        wall_a, wall_b = sums["wall_s"]
        out.append(
            {
                "tools": [a, b],
                "benchmarks": len(both),
                "skipped": len(ids) - len(both),
                "wall_s": sums["wall_s"],
                "cpu_s": sums["cpu_s"],
                "wall_ratio": round(wall_a / wall_b, DIGITS) if wall_b else None,
            }
        )
    return out


def _ratio(a: float, b: float) -> float | None:
    return round(a / b, DIGITS) if b else None


def ratios(results: list[dict]) -> dict[tuple[str, str], dict | None]:
    """Return {(tool, id): ratio} for each result. The ratio is the median
    wall and CPU time of the result divided by those of the RATIO_BASE result
    of the same benchmark in the same report. It is None for the base tool,
    and if the result or the base result is not valid."""
    valid = _valid(results)
    out = {}
    for r in results:
        key = (r["tool"], r["id"])
        base = valid.get((RATIO_BASE, r["id"]))
        if r["tool"] == RATIO_BASE or key not in valid or base is None:
            out[key] = None
            continue
        out[key] = {
            k: _ratio(
                valid[key]["stats"][f"{k}_s"]["median"],
                base["stats"][f"{k}_s"]["median"],
            )
            for k in RATIO
        }
    return out


def build(
    *,
    sqlfluff_ref: str,
    profile: str,
    machine: dict,
    harness: dict,
    timer: dict,
    scope: dict,
    tools: dict[str, dict],
    inputs: dict[str, dict],
    results: list[dict],
    parts: list[dict] | None = None,
) -> dict:
    """Return the report. tools maps each tool to {version, settings};
    inputs maps each input name to {bytes, lines, sha256}. parts: only for a
    merged report, the {shard, machine, timer} of each shard report."""
    ordered = [dict(r) for r in sorted(results, key=lambda r: (r["id"], r["tool"]))]
    want = ratios(ordered)
    for r in ordered:
        r["ratio"] = want[(r["tool"], r["id"])]
    return {
        "kind": KIND,
        "format": FORMAT,
        "sqlfluff_ref": sqlfluff_ref,
        "harness": harness,
        "profile": profile,
        "policy": PROFILES[profile].as_dict(),
        "machine": machine,
        "timer": timer,
        "scope": scope,
        "tools": dict(sorted(tools.items())),
        "inputs": dict(sorted(inputs.items())),
        "results": ordered,
        "totals": totals(ordered, tools),
        "pairs": pairs(ordered, tools),
        "parts": parts,
    }


def write(report: dict, path: Path = DEFAULT_REPORT) -> None:
    """Write the report. ReportError if check() finds an error."""
    errors = check(report)
    if errors:
        raise ReportError("; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1) + "\n", encoding="utf8")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf8"))


# Schema check.


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v) -> bool:
    return (_is_int(v) or isinstance(v, float)) and v >= 0


def _is_text(v) -> bool:
    return isinstance(v, str) and v != ""


def _same(a, b) -> bool:
    """Equal values of equal JSON types: true is not 1, and 1 is not 1.0."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


class _Checker:
    def __init__(self):
        self.errors: list[str] = []

    def error(self, where: str, text: str) -> None:
        self.errors.append(f"{where}: {text}")

    def fields(self, where: str, obj, names: tuple[str, ...]) -> bool:
        """Report a value that is not an object, a missing or an unknown
        field. Return True if obj is an object with exactly these fields."""
        if not isinstance(obj, dict):
            self.error(where, f"not an object: {obj!r}")
            return False
        missing = [n for n in names if n not in obj]
        unknown = sorted(set(obj) - set(names))
        for n in missing:
            self.error(where, f"missing field {n!r}")
        for n in unknown:
            self.error(where, f"unknown field {n!r}")
        return not missing and not unknown

    def want(self, where: str, ok: bool, text: str) -> None:
        if not ok:
            self.error(where, text)


def _check_stats(c: _Checker, where: str, value, samples: list[Sample]) -> None:
    if not samples:
        c.error(where, "no timed sample")
        return
    want = sample_stats(samples)
    c.want(where, _same(value, want), f"stats {value!r} are not those of the samples")


def _samples(c: _Checker, where: str, value) -> list[Sample] | None:
    """Return the samples, or None if one has an error."""
    if not isinstance(value, list):
        c.error(where, "samples: not a list")
        return None
    out = []
    for i, s in enumerate(value):
        w = f"{where} sample {i}"
        if not c.fields(w, s, SAMPLE):
            return None
        ok = (
            s["kind"] in RUNS
            and all(_is_number(s[k]) for k in ("wall_s", "user_s", "sys_s"))
            and _is_int(s["max_rss_kib"])
            and s["max_rss_kib"] >= 0
            and _is_int(s["exit_code"])
            and isinstance(s["timed_out"], bool)
        )
        if not ok:
            c.error(w, f"bad value: {s!r}")
            return None
        out.append(Sample(**s))
    kinds = [s.kind for s in out]
    if WARMUP in kinds and (kinds.count(WARMUP) > 1 or kinds[0] != WARMUP):
        c.error(where, "the warmup sample must be the first and only one")
        return None
    return out


def _check_result(c: _Checker, report: dict, r) -> None:
    where = f"result {r.get('id') if isinstance(r, dict) else r!r}"
    if not c.fields(where, r, RESULT):
        return
    where = f"result {r['id']} ({r['tool']})"
    names = ("id", "command", "dialect", "input", "tool")
    texts = all(isinstance(r[k], str) for k in names)
    if not texts or not (r["size"] is None or isinstance(r["size"], str)):
        c.error(where, f"{', '.join(names)} must be text, and size text or null")
        return
    command, dialect, size = r["command"], r["dialect"], r["size"]
    if command == START:
        good = size is None and r["id"] == f"{START}/{dialect}" and r["input"] == START
    else:
        good = (
            command in COMMANDS
            and size in SIZES
            and r["id"] == f"{command}/{dialect}/{size}"
            and r["input"] == f"{dialect}/{size}"
        )
    c.want(where, good, "id, command, dialect, size, and input do not agree")

    def names_of(obj, key: str) -> list:
        value = obj.get(key) if isinstance(obj, dict) else None
        return list(value) if isinstance(value, dict | list) else []

    scope = report.get("scope")
    c.want(where, r["tool"] in names_of(report, "tools"), "tool not in tools")
    c.want(where, r["input"] in names_of(report, "inputs"), "input not in inputs")
    c.want(where, r["tool"] in names_of(scope, "tools"), "tool not in the scope")
    c.want(where, dialect in names_of(scope, "dialects"), "dialect not in the scope")
    c.want(where, command in names_of(scope, "commands"), "command not in the scope")
    c.want(
        where, size is None or size in names_of(scope, "sizes"), "size not in the scope"
    )
    c.want(where, r["work"] is None or isinstance(r["work"], dict), "bad work")
    ratio = r["ratio"]
    if ratio is not None and c.fields(f"{where} ratio", ratio, RATIO):
        c.want(
            where,
            all(v is None or _is_number(v) for v in ratio.values()),
            f"bad ratio {ratio!r}",
        )

    status = r["status"]
    if status not in STATUSES:
        c.error(where, f"unknown status {status!r}")
        return
    samples = _samples(c, where, r["samples"])
    if samples is None:
        return
    runs = {k: sum(s.kind == k for s in samples) for k in RUNS}
    c.want(where, _same(r["runs"], runs), f"runs {r['runs']!r} are not {runs!r}")
    if status != VALID:
        c.want(where, _is_text(r["reason"]), f"status {status} needs a reason")
        c.want(where, r["stats"] is None, f"status {status} must have no stats")
        return
    c.want(where, r["reason"] is None, "a valid result must have no reason")
    if r["stats"] is None:
        c.error(where, "a valid result needs stats")
        return
    if runs[WARMUP] != 1:
        c.error(where, "a valid result needs the warmup sample")
        return
    timed = [s for s in samples if s.kind == TIMED]
    policy = report.get("policy")
    if isinstance(policy, dict):
        low, high = policy.get("min_runs"), policy.get("max_runs")
        c.want(
            where,
            _is_int(low) and _is_int(high) and low <= len(timed) <= high,
            f"{len(timed)} timed runs, the policy needs {low} to {high}",
        )
    c.want(where, not any(s.timed_out for s in samples), "a run has a timeout")
    exits = {s.exit_code for s in samples}
    c.want(where, len(exits) == 1, f"the runs have other exit codes: {exits}")
    _check_stats(c, where, r["stats"], timed)


def _check_machine(c: _Checker, where: str, m) -> None:
    if c.fields(where, m, MACHINE):
        c.want(where, _is_int(m["cpu_count"]), "bad cpu_count")
        c.want(where, m["memory_kib"] is None or _is_int(m["memory_kib"]), "bad memory")
        for k in ("cpu_model", "os", "kernel", "arch", "python"):
            c.want(where, isinstance(m[k], str), f"bad {k}")


def _check_timer(c: _Checker, where: str, t) -> None:
    if c.fields(where, t, TIMER) and c.fields(
        f"{where}.overhead", t["overhead"], OVERHEAD
    ):
        o = t["overhead"]
        samples = _samples(c, f"{where}.overhead", o["samples"])
        if samples is not None:
            c.want(
                f"{where}.overhead",
                all(s.kind == TIMED for s in samples),
                "the samples must be timed",
            )
            _check_stats(c, f"{where}.overhead", o["stats"], samples)


def _check_parts(c: _Checker, report: dict) -> None:
    """parts is null, or a merged report has one part for each shard 1/N to
    N/N, and the machine and timer of the report are those of part 1."""
    parts = report["parts"]
    if parts is None:
        return
    if not isinstance(parts, list) or not parts:
        c.error("parts", "not null or a list of parts")
        return
    scope = report["scope"]
    c.want(
        "parts",
        isinstance(scope, dict) and scope.get("shard") is None,
        "a merged report must have scope.shard null",
    )
    shards = []
    for i, p in enumerate(parts):
        where = f"part {i}"
        if not c.fields(where, p, PART):
            return
        m = SHARD.fullmatch(p["shard"]) if isinstance(p["shard"], str) else None
        if m is None:
            c.error(where, f"bad shard {p['shard']!r}")
            return
        shards.append((int(m[1]), int(m[2])))
        _check_machine(c, f"{where}.machine", p["machine"])
        _check_timer(c, f"{where}.timer", p["timer"])
    n = len(parts)
    c.want(
        "parts",
        shards == [(k, n) for k in range(1, n + 1)],
        f"the shards are not 1/{n} to {n}/{n} in order: {shards}",
    )
    first = parts[0]
    c.want(
        "parts",
        _same(report["machine"], first["machine"])
        and _same(report["timer"], first["timer"]),
        "the machine and timer of the report are not those of part 1",
    )


def check(report) -> list[str]:
    """Return each schema error of a report. No error: an empty list."""
    c = _Checker()
    try:
        _check(c, report)
    except Exception as exc:
        # A value of a type that a check did not expect. Fail closed.
        c.error("report", f"cannot check: {exc!r}")
    return c.errors


def _check(c: _Checker, report) -> None:
    if not c.fields("report", report, TOP):
        return
    c.want("kind", report["kind"] == KIND, f"not {KIND!r}")
    c.want("format", _same(report["format"], FORMAT), f"not {FORMAT}")
    c.want("sqlfluff_ref", _is_text(report["sqlfluff_ref"]), "empty")
    if c.fields("harness", report["harness"], HARNESS):
        h = report["harness"]
        c.want("harness", _is_text(h["commit"]), "empty commit")
        c.want("harness", isinstance(h["clean"], bool), "clean is not a bool")
    profile = report["profile"]
    if not isinstance(profile, str) or profile not in PROFILES:
        c.error("profile", f"unknown profile {profile!r}")
    else:
        want = PROFILES[profile].as_dict()
        c.want(
            "policy", _same(report["policy"], want), f"not the {profile} policy {want}"
        )
    _check_machine(c, "machine", report["machine"])
    _check_timer(c, "timer", report["timer"])
    _check_parts(c, report)
    if c.fields("scope", report["scope"], SCOPE):
        s = report["scope"]
        lists = {}
        for k in ("tools", "dialects", "commands", "sizes"):
            ok = isinstance(s[k], list) and all(isinstance(x, str) for x in s[k])
            c.want("scope", ok, f"{k} is not a list of text")
            lists[k] = set(s[k]) if ok else set()
        known = {"commands": ALL_COMMANDS, "sizes": tuple(SIZES)}
        for k, names in known.items():
            unknown = sorted(lists[k] - set(names))
            c.want("scope", not unknown, f"unknown {k}: {unknown}")
        m = SHARD.fullmatch(s["shard"]) if isinstance(s["shard"], str) else None
        c.want(
            "scope",
            s["shard"] is None or (m is not None and 1 <= int(m[1]) <= int(m[2])),
            "bad shard",
        )
        c.want(
            "scope",
            lists["tools"]
            == set(report["tools"] if isinstance(report["tools"], dict) else []),
            "the tools of the scope are not the tools",
        )
    tools = report["tools"]
    if not isinstance(tools, dict):
        c.error("tools", "not an object")
    else:
        for name, t in tools.items():
            if c.fields(f"tool {name}", t, TOOL):
                c.want(f"tool {name}", _is_text(t["version"]), "empty version")
                c.want(f"tool {name}", isinstance(t["settings"], dict), "bad settings")
    inputs = report["inputs"]
    if not isinstance(inputs, dict):
        c.error("inputs", "not an object")
    else:
        for name, i in inputs.items():
            if c.fields(f"input {name}", i, INPUT):
                ok = (
                    _is_int(i["bytes"])
                    and _is_int(i["lines"])
                    and isinstance(i["sha256"], str)
                    and bool(SHA256.fullmatch(i["sha256"]))
                )
                c.want(f"input {name}", ok, f"bad value: {i!r}")
    results = report["results"]
    if not isinstance(results, list):
        c.error("results", "not a list")
        return
    keys = [(r.get("id"), r.get("tool")) for r in results if isinstance(r, dict)]
    if all(isinstance(k, str) for key in keys for k in key):
        c.want("results", len(keys) == len(set(keys)), "an id and tool are repeated")
        c.want("results", keys == sorted(keys), "not sorted by id and tool")
    before = len(c.errors)
    for r in results:
        _check_result(c, report, r)
    if len(c.errors) == before and isinstance(tools, dict):
        want_totals = totals(results, tools)
        c.want("totals", _same(report["totals"], want_totals), f"not {want_totals}")
        want_pairs = pairs(results, tools)
        c.want("pairs", _same(report["pairs"], want_pairs), f"not {want_pairs}")
        want_ratios = ratios(results)
        for r in results:
            want = want_ratios[(r["tool"], r["id"])]
            c.want(
                f"result {r['id']} ({r['tool']})",
                _same(r["ratio"], want),
                f"ratio {r['ratio']!r} is not {want!r}",
            )
    else:
        c.error("totals", "not checked: the results or the tools have an error")
