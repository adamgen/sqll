"""The corpus report (docs/decisions/s9-corpus.md, "Report").

build() makes a report, check() returns each schema error, and write()
writes only a report with no error. check() computes the stats, the
derived fields of each result, the totals, and the compared totals again
from the samples and the inputs, so a report cannot have other numbers.
The machine, timer, harness, and parts records are those of the S2 report
(bench/report.py), and the checks of these records are its checks.
"""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from ..bench.report import (
    SHA256,
    SHARD,
    _check_machine,
    _check_parts,
    _check_timer,
    _Checker,
    _is_int,
    _is_text,
    _same,
    _samples,
)
from ..bench.timer import DIGITS, TIMED, WARMUP, Measurement, sample_stats
from ..paths import OUT_DIR
from .manifest import JINJA, MIN_BYTES, CorpusFile

KIND = "sqll-corpus-report"
FORMAT = 1
DEFAULT_REPORT = OUT_DIR / "corpus.json"

OK = "ok"
UNPARSABLE = "unparsable"
NO_REFERENCE = "no_reference"
INVALID = "invalid"
UNSUPPORTED = "unsupported"
ERROR = "error"
STATUSES = (OK, UNPARSABLE, NO_REFERENCE, INVALID, UNSUPPORTED, ERROR)
# The statuses of a complete series (warmup and timed runs): they have stats.
TIMED_STATUSES = (OK, UNPARSABLE, NO_REFERENCE)
# A complete parse exits with 0, or with 1 if the tree has an unparsable
# segment (sqlfluff and sqruff "parse").
PARSE_EXITS = (0, 1)
# The wall time ratios of the compared totals are to this tool.
RATIO_BASE = "sqlfluff"
REFERENCE_OK = "ok"
REFERENCE_FAILED = "failed"

TOP = (
    "kind",
    "format",
    "sqlfluff_ref",
    "harness",
    "profile",
    "policy",
    "machine",
    "timer",
    "manifest_sha256",
    "scope",
    "tools",
    "inputs",
    "results",
    "totals",
    "compared",
    "parts",
)
SCOPE = ("tools", "shard")
TOOL = ("version", "settings")
INPUT = (
    "source",
    "path",
    "dialect",
    "templater",
    "bytes",
    "lines",
    "sha256",
    "reference",
)
REFERENCE = ("status", "sha256", "reason")
RESULT = (
    "file",
    "tool",
    "status",
    "reason",
    "exit_code",
    "unparsable",
    "runs",
    "samples",
    "stats",
    "max_rss_kib",
    "bytes_per_s",
)
UNPARSABLE_FIELDS = ("count", "bytes")
COMPARED = ("tools", "files", "bytes", "results")
COMPARED_TOOL = ("wall_s", "cpu_s", "bytes_per_s", "wall_ratio", "cpu_ratio")
RUNS = (WARMUP, TIMED)


class ReportError(Exception):
    """The report does not agree with the schema."""


# Records.


def input_record(entry: CorpusFile, reference: dict | None) -> dict:
    """Return the report record of a manifest file. reference: the record
    of the sqlfluff render (templated files only), else None."""
    return {
        "source": entry.source,
        "path": entry.path,
        "dialect": entry.dialect,
        "templater": entry.templater,
        "bytes": entry.bytes,
        "lines": entry.lines,
        "sha256": entry.sha256,
        "reference": reference,
    }


def reference_record(sha256: str | None, reason: str | None) -> dict:
    """Return the record of a render: its sha256, or the reason why it failed."""
    if sha256 is not None:
        return {"status": REFERENCE_OK, "sha256": sha256, "reason": None}
    return {"status": REFERENCE_FAILED, "sha256": None, "reason": reason}


def _bytes_per_s(size: int, stats: dict | None) -> float | None:
    if stats is None:
        return None
    wall = stats["wall_s"]["median"]
    return round(size / wall, DIGITS) if wall > 0 else None


def result_entry(
    file_id: str,
    size: int,
    tool: str,
    status: str,
    reason: str | None,
    m: Measurement,
    unparsable: dict | None,
) -> dict:
    """Return the report entry of one file and tool."""
    samples = m.samples
    stats = m.stats if status in TIMED_STATUSES else None
    return {
        "file": file_id,
        "tool": tool,
        "status": status,
        "reason": reason,
        "exit_code": samples[0].exit_code if samples else None,
        "unparsable": unparsable if status in TIMED_STATUSES else None,
        "runs": {k: sum(s.kind == k for s in samples) for k in RUNS},
        "samples": [s.as_dict() for s in samples],
        "stats": stats,
        "max_rss_kib": max(s.max_rss_kib for s in samples) if samples else None,
        "bytes_per_s": _bytes_per_s(size, stats),
    }


# Totals.


def totals(results: list[dict], tools: Iterable[str]) -> dict:
    """Return the count of each status for each tool."""
    out = {}
    for tool in sorted(tools):
        mine = [r["status"] for r in results if r["tool"] == tool]
        out[tool] = {s: mine.count(s) for s in STATUSES}
    return out


def _ratio(a: float, b: float) -> float | None:
    return round(a / b, DIGITS) if b else None


def compared(results: list[dict], tools: Iterable[str], inputs: Mapping) -> dict:
    """Return the totals over the files where each tool is ok: the file
    count, the input bytes, and for each tool the sums of the median wall
    and CPU times, the bytes per second, and the ratios to RATIO_BASE."""
    tools = sorted(tools)
    ok = {(r["file"], r["tool"]): r for r in results if r["status"] == OK}
    files = sorted(f for f in inputs if tools and all((f, t) in ok for t in tools))
    size = sum(inputs[f]["bytes"] for f in files)
    sums = {
        t: {
            key: round(sum(ok[(f, t)]["stats"][key]["median"] for f in files), DIGITS)
            for key in ("wall_s", "cpu_s")
        }
        for t in tools
    }
    base = sums.get(RATIO_BASE)
    out = {}
    for t in tools:
        wall, cpu = sums[t]["wall_s"], sums[t]["cpu_s"]
        out[t] = {
            "wall_s": wall,
            "cpu_s": cpu,
            "bytes_per_s": round(size / wall, DIGITS) if wall else None,
            "wall_ratio": _ratio(wall, base["wall_s"]) if base else None,
            "cpu_ratio": _ratio(cpu, base["cpu_s"]) if base else None,
        }
    return {"tools": tools, "files": len(files), "bytes": size, "results": out}


def build(
    *,
    sqlfluff_ref: str,
    profile: str,
    policy: dict,
    machine: dict,
    harness: dict,
    timer: dict,
    manifest_sha256: str,
    scope: dict,
    tools: dict[str, dict],
    inputs: dict[str, dict],
    results: list[dict],
    parts: list[dict] | None = None,
) -> dict:
    """Return the report. parts: only for a merged report, the {shard,
    machine, timer} of each shard report."""
    ordered = sorted(results, key=lambda r: (r["file"], r["tool"]))
    return {
        "kind": KIND,
        "format": FORMAT,
        "sqlfluff_ref": sqlfluff_ref,
        "harness": harness,
        "profile": profile,
        "policy": policy,
        "machine": machine,
        "timer": timer,
        "manifest_sha256": manifest_sha256,
        "scope": scope,
        "tools": dict(sorted(tools.items())),
        "inputs": dict(sorted(inputs.items())),
        "results": ordered,
        "totals": totals(ordered, tools),
        "compared": compared(ordered, tools, inputs),
        "parts": parts,
    }


def write(report: dict, path: Path = DEFAULT_REPORT) -> None:
    """Write the report. ReportError if check() finds an error."""
    errors = check(report)
    if errors:
        raise ReportError("; ".join(errors[:5]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1) + "\n", encoding="utf8")


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf8"))


# Schema check.


def check(report, profiles: Mapping[str, dict] | None = None) -> list[str]:
    """Return each schema error of a report. No error: an empty list.
    profiles: {name: policy record} of the known profiles (default: those of
    the corpus run)."""
    if profiles is None:
        from .run import PROFILES

        profiles = {k: p.as_dict() for k, p in PROFILES.items()}
    c = _Checker()
    try:
        _check(c, report, profiles)
    except Exception as exc:
        # A value of a type that a check did not expect. Fail closed.
        c.error("report", f"cannot check: {exc!r}")
    return c.errors


def _check(c: _Checker, report, profiles: Mapping[str, dict]) -> None:
    if not c.fields("report", report, TOP):
        return
    c.want("kind", report["kind"] == KIND, f"not {KIND!r}")
    c.want("format", _same(report["format"], FORMAT), f"not {FORMAT}")
    c.want("sqlfluff_ref", _is_text(report["sqlfluff_ref"]), "empty")
    if c.fields("harness", report["harness"], ("commit", "clean")):
        h = report["harness"]
        c.want("harness", _is_text(h["commit"]), "empty commit")
        c.want("harness", isinstance(h["clean"], bool), "clean is not a bool")
    profile = report["profile"]
    if not isinstance(profile, str) or profile not in profiles:
        c.error("profile", f"unknown profile {profile!r}")
    else:
        want = profiles[profile]
        c.want(
            "policy", _same(report["policy"], want), f"not the {profile} policy {want}"
        )
    _check_machine(c, "machine", report["machine"])
    _check_timer(c, "timer", report["timer"])
    _check_parts(c, report)
    sha = report["manifest_sha256"]
    c.want(
        "manifest_sha256",
        isinstance(sha, str) and SHA256.fullmatch(sha) is not None,
        "not a sha256",
    )
    tools = report["tools"]
    if c.fields("scope", report["scope"], SCOPE):
        s = report["scope"]
        names = s["tools"]
        ok = isinstance(names, list) and all(isinstance(t, str) for t in names)
        c.want("scope", ok and s["tools"] == sorted(set(s["tools"])), "bad tools")
        c.want(
            "scope",
            ok and isinstance(tools, dict) and set(s["tools"]) == set(tools),
            "the tools of the scope are not the tools",
        )
        m = SHARD.fullmatch(s["shard"]) if isinstance(s["shard"], str) else None
        c.want(
            "scope",
            s["shard"] is None or (m is not None and 1 <= int(m[1]) <= int(m[2])),
            "bad shard",
        )
    if not isinstance(tools, dict):
        c.error("tools", "not an object")
        return
    for name, t in tools.items():
        if c.fields(f"tool {name}", t, TOOL):
            c.want(f"tool {name}", _is_text(t["version"]), "empty version")
            settings = t["settings"]
            c.want(
                f"tool {name}",
                isinstance(settings, dict)
                and set(settings) == set(MIN_BYTES)
                and all(isinstance(v, dict) for v in settings.values()),
                f"settings must have an object for each of {sorted(MIN_BYTES)}",
            )
    inputs = report["inputs"]
    if not isinstance(inputs, dict):
        c.error("inputs", "not an object")
        return
    for name, i in inputs.items():
        _check_input(c, name, i)
    results = report["results"]
    if not isinstance(results, list):
        c.error("results", "not a list")
        return
    before = len(c.errors)
    for r in results:
        _check_result(c, report, r)
    if len(c.errors) != before:
        c.error("totals", "not checked: a result has an error")
        return
    keys = [(r["file"], r["tool"]) for r in results]
    c.want("results", len(keys) == len(set(keys)), "a file and tool are repeated")
    c.want("results", keys == sorted(keys), "not sorted by file and tool")
    want_totals = totals(results, tools)
    c.want("totals", _same(report["totals"], want_totals), f"not {want_totals}")
    want = compared(results, tools, inputs)
    c.want("compared", _same(report["compared"], want), f"not {want}")


def _check_input(c: _Checker, name: str, i) -> None:
    where = f"input {name}"
    if not c.fields(where, i, INPUT):
        return
    ok = (
        all(_is_text(i[k]) for k in ("source", "path", "dialect"))
        and name == f"{i['source']}/{i['path']}"
        and i["templater"] in MIN_BYTES
        and _is_int(i["bytes"])
        and _is_int(i["lines"])
        and isinstance(i["sha256"], str)
        and SHA256.fullmatch(i["sha256"]) is not None
    )
    c.want(where, ok, f"bad value: {i!r}")
    ref = i["reference"]
    if i["templater"] != JINJA:
        c.want(where, ref is None, "a file that is not templated has no reference")
        return
    if not c.fields(f"{where} reference", ref, REFERENCE):
        return
    if ref["status"] == REFERENCE_OK:
        good = (
            isinstance(ref["sha256"], str)
            and SHA256.fullmatch(ref["sha256"]) is not None
            and ref["reason"] is None
        )
    else:
        good = (
            ref["status"] == REFERENCE_FAILED
            and ref["sha256"] is None
            and _is_text(ref["reason"])
        )
    c.want(f"{where} reference", good, f"bad value: {ref!r}")


def _check_result(c: _Checker, report: dict, r) -> None:
    where = f"result {r.get('file') if isinstance(r, dict) else r!r}"
    if not c.fields(where, r, RESULT):
        return
    if not (isinstance(r["file"], str) and isinstance(r["tool"], str)):
        c.error(where, "file and tool must be text")
        return
    where = f"result {r['file']} ({r['tool']})"
    inputs, scope = report["inputs"], report["scope"]
    c.want(where, r["tool"] in report["tools"], "tool not in tools")
    c.want(
        where,
        isinstance(scope, dict) and r["tool"] in (scope.get("tools") or []),
        "tool not in the scope",
    )
    if r["file"] not in inputs:
        c.error(where, "file not in inputs")
        return
    status = r["status"]
    if status not in STATUSES:
        c.error(where, f"unknown status {status!r}")
        return
    samples = _samples(c, where, r["samples"])
    if samples is None:
        return
    runs = {k: sum(s.kind == k for s in samples) for k in RUNS}
    c.want(where, _same(r["runs"], runs), f"runs {r['runs']!r} are not {runs!r}")
    exit_code = samples[0].exit_code if samples else None
    c.want(where, _same(r["exit_code"], exit_code), f"exit_code is not {exit_code}")
    rss = max(s.max_rss_kib for s in samples) if samples else None
    c.want(where, _same(r["max_rss_kib"], rss), f"max_rss_kib is not {rss}")
    if status == OK:
        c.want(where, r["reason"] is None, "an ok result must have no reason")
    else:
        c.want(where, _is_text(r["reason"]), f"status {status} needs a reason")
    if status == UNSUPPORTED:
        c.want(where, not samples, "an unsupported result must have no samples")
    if status not in TIMED_STATUSES:
        for key in ("stats", "unparsable", "bytes_per_s"):
            c.want(where, r[key] is None, f"status {status} must have no {key}")
        return
    if input_ref_failed(inputs[r["file"]]) != (status == NO_REFERENCE):
        c.error(where, f"status {status} does not agree with the reference record")
    _check_unparsable(c, where, status, r["unparsable"])
    if runs[WARMUP] != 1 or not samples or samples[0].kind != WARMUP:
        c.error(where, f"status {status} needs the warmup sample first")
        return
    timed = [s for s in samples if s.kind == TIMED]
    policy = report.get("policy")
    low = policy.get("min_runs") if isinstance(policy, dict) else None
    high = policy.get("max_runs") if isinstance(policy, dict) else None
    c.want(
        where,
        _is_int(low) and _is_int(high) and low <= len(timed) <= high,
        f"{len(timed)} timed runs, the policy needs {low} to {high}",
    )
    c.want(where, not any(s.timed_out for s in samples), "a run has a timeout")
    exits = {s.exit_code for s in samples}
    c.want(
        where,
        len(exits) == 1 and exit_code in PARSE_EXITS,
        f"the runs must have one exit code of {PARSE_EXITS}: {sorted(exits)}",
    )
    if status == OK:
        c.want(where, exit_code == 0, "an ok result needs exit code 0")
    if not timed:
        c.error(where, "no timed sample")
        return
    want = sample_stats(samples)
    c.want(where, _same(r["stats"], want), f"stats {r['stats']!r} are not {want!r}")
    rate = _bytes_per_s(inputs[r["file"]]["bytes"], want)
    c.want(where, _same(r["bytes_per_s"], rate), f"bytes_per_s is not {rate}")


def input_ref_failed(record: Mapping) -> bool:
    ref = record.get("reference")
    return isinstance(ref, dict) and ref.get("status") == REFERENCE_FAILED


def _check_unparsable(c: _Checker, where: str, status: str, value) -> None:
    if not c.fields(f"{where} unparsable", value, UNPARSABLE_FIELDS):
        return
    count, size = value["count"], value["bytes"]
    if not (_is_int(count) and _is_int(size) and count >= 0 and size >= 0):
        c.error(where, f"bad unparsable {value!r}")
    elif status == OK:
        c.want(where, count == 0 and size == 0, "an ok result has no unparsable")
    elif status == UNPARSABLE:
        c.want(where, count > 0, "an unparsable result needs a count > 0")
