"""S3 phase A, task T6: speed by base and the distance to the G3 targets
(criterion C5 of docs/decisions/s3-base.md).

One command. Run it with the harness Python:

    uv run --frozen --project harness python scripts/s3/speed_by_base.py [--check]

It reads only committed files: the S2 baseline (BASELINE_FILE) and the T5
probe report (PROBE_FILE). It writes OUT_FILE. With --check it writes
nothing and fails if OUT_FILE is not the new text. It runs no benchmark.

For each base (1: sqruff, 2: sqlfluffrs, 3: a new parser, low and high
bound) and each benchmark: the time of the base, the ratio to sqlfluff and
to sqruff, and the result for the G3 targets (CONSTITUTION.md G3.4, G3.5).
A value is "measured" (copied from a committed file, "from" names it) or
an "estimate" ("formula" names the formula in FORMULAS).

It stops with exit code 1 (DataError) if the inputs do not agree: the
probe report is not from the committed baseline, a tool version or the
sqlfluff commit is not the pin, a benchmark is missing, a ratio of the
probe report is not the ratio of its medians, or a reason of a result that
is not valid has no known class.
"""

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from sqll_harness.bench import report as bench_report
from sqll_harness.bench.compare import NOISE
from sqll_harness.bench.timer import VALID
from sqll_harness.paths import SQLFLUFF_ROOT, sqlfluff_ref

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_a  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BASELINE_FILE = phase_a.read_path("results/s2/baseline.json")
PROBE_FILE = ROOT / "results" / "s3" / "sqlfluffrs-probe.json"
OUT_FILE = ROOT / "results" / "s3" / "speed-by-base.json"
COMMAND = "uv run --frozen --project harness python scripts/s3/speed_by_base.py"

PROBE = "probe-sqlfluffrs"
VERSIONS = {"sqlfluff": "4.4.0", "sqruff": "0.41.0"}
COMMANDS = ("start", "parse", "lint", "fix")
MEASURED_BY_PROBE = ("start", "parse")
BASES = {
    "sqruff": 1,
    "sqlfluffrs": 2,
    "new-parser-low": 3,
    "new-parser-high": 3,
}
ESTIMATE_BASES = ("sqlfluffrs", "new-parser-low", "new-parser-high")
NOISE_LIMIT = 1 + NOISE.wall_pct
RATIO_DIGITS = 4
TIME_DIGITS = 6

# The class of the reason of each result that is not valid, after the
# status "unsupported". The first match gives the class (harness/bench.md,
# "Validity").
REASON_CLASSES = (
    ("panic", "the tool crashed (panic)"),
    ("timeout", "timeout after "),
    ("rule_codes", "the rule codes are not those of the sqlfluff reference"),
)

MET, NOT_MET, UNKNOWN, SKIPPED = "met", "not_met", "unknown", "skipped"
OUTCOMES = (MET, NOT_MET, UNKNOWN, SKIPPED)

SOURCES = {
    "baseline": {
        "path": "results/s2/baseline.json",
        "value": "results[id, tool].stats.wall_s.median; a ratio to sqlfluff: "
        "results[id, tool].ratio.wall",
    },
    "session": {
        "path": "results/s3/sqlfluffrs-probe.json",
        "value": "speed.benchmarks[id].<tool>.median_s; the ratios: "
        "speed.benchmarks[id].probe_over_sqlfluff and probe_over_sqruff",
    },
    "phases": {
        "path": "results/s3/sqlfluffrs-probe.json",
        "value": "speed.benchmarks[id].probe_phases (setup_s, lex_s, parse_s)",
    },
}

FORMULAS = {
    "rule_time": "lint and fix of options 2 and 3: T = Tq(c, i) + Pq(i) * (r(i) - 1). "
    "Tq(c, i), Pq(i): the sqruff median of the command c and of parse on the "
    "input i (baseline). r(i) = Tb(parse, i) / Pq_session(i): the parse time of "
    "the base over the sqruff parse time, in the probe session. Thus: the sqruff "
    "time with its parse part (process start, lex, parse, tree output) replaced by "
    "that of the base, in the units of the baseline session. The rules take the "
    "sqruff rule time Tq(c) - Pq. Only if the sqruff results of c and parse are "
    "valid; else no estimate.",
    "option3_high": "start and parse of option 3, high bound: T = the probe median "
    "(session). The new parser has the speed of the sqlfluffrs engine on the same "
    "generated tables.",
    "option3_low": "start and parse of option 3, low bound: T = the probe median - "
    "the probe setup phase (session, phases). Also, the dialect tables cost no run "
    "time (made at compile time).",
    "total_all": "the total of all commands: sum(R * Tq) / sum(Tq), over the "
    "benchmarks with a pair. R: the ratio of the row to sqruff. Tq: the sqruff "
    "median of the benchmark (baseline). Thus each ratio comes from one session, "
    "and the weights from the baseline.",
    "speedup": "lex and parse speed-up for G3.5 on one start or parse benchmark: "
    "k = LP / (S - (T - LP)). LP: lex_s + parse_s of the probe phases; T: the "
    "time of the base; S: the sqruff time (session). Unreachable if S <= T - LP. "
    "not_valid: the entry has no time (its probe result is not valid).",
    "unscaled": "sensitivity of rule_time, the simple form: T = Tb(parse, i) + "
    "Tq(c, i) - Pq(i). It adds a time of the probe session to times of the "
    "baseline session.",
}

TARGETS = {
    "g3_4": "G3.4: faster than sqlfluff on each benchmark (ratio < 1).",
    "g3_5_each": "G3.5: not slower than sqruff on any benchmark (ratio <= 1).",
    "g3_5_total": "G3.5: faster than sqruff on the total of all benchmarks "
    "(ratio of the sums < 1).",
}

RULES = [
    "Ratios: base / other tool, on the same benchmark, with the times of one "
    "session (the ref_from of the row). Below 1: the base is faster.",
    "Pairs (harness/bench.md, Validity): a result that is not valid of the base "
    "fails its comparison (not_met). A pair is skipped only if the other tool is "
    "not valid. A total uses only the benchmarks with a pair.",
    "unknown: an estimate is not possible (the sqruff result that the formula "
    "needs is not valid), and the other tool is valid.",
    "A probe result that is not valid makes the start or parse entry of options "
    "2 and 3 not_valid, and also lint and fix on the same input: the lint and "
    "fix checks need the parse check of the same tool (harness/bench.md).",
    f"No noise limit: a ratio just above 1 counts as not_met. over_noise counts "
    f"the ratios above {NOISE_LIMIT} (the wall time limit of bench compare).",
    "Under rule_time, a lint or fix estimate is at most the sqruff time if, and "
    "only if, r(i) <= 1. Thus G3.5 on lint and fix of options 2 and 3 follows "
    "parse on the same input.",
]

LIMITS = [
    "Option 1 is sqruff itself: its ratio to sqruff is 1 by definition. G3.5 "
    "needs a gain on the total; G3.4 needs its results that are not valid to "
    "become valid, at an unknown time.",
    "Options 2 and 3 have no rules: rule_time assumes rules as fast as the sqruff "
    "rules on the sqlfluff trees, and one parse for fix. The sqruff parse time "
    "has its tree output, which lint does not write; thus Tq(c) - Pq is a low "
    "value of the rule time.",
    "Option 3 has no implementation. Its bounds are assumptions, not proven "
    "limits: a new engine that is slower than the sqlfluffrs engine is above the "
    "high bound; one that lexes or parses faster is below the low bound.",
    "The low bound of option 3 needs a change that option 2 can also make.",
    "The probe phases are the median of 5 other runs; a difference of a phase "
    "and a wall time median is an estimate.",
]


class DataError(Exception):
    """The inputs do not agree."""


def rel(path: Path) -> str:
    try:
        return phase_a.name_of(path.resolve().relative_to(ROOT).as_posix())
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rt(x: float | None) -> float | None:
    return None if x is None else round(x, TIME_DIGITS)


def rr(x: float | None) -> float | None:
    return None if x is None else round(x, RATIO_DIGITS)


def reason_class(status: str, reason: str | None) -> str:
    text = reason or ""
    if status == "unsupported" and text.startswith("unsupported: "):
        return "unsupported"
    for name, needle in REASON_CLASSES:
        if needle in text:
            return name
    raise DataError(f"no class for the reason {text[:80]!r} ({status})")


def _median(result: dict | None) -> float | None:
    if result is None or result["status"] != VALID:
        return None
    return result["stats"]["wall_s"]["median"]


# Inputs and their checks.


def load(baseline_path: Path, probe_path: Path) -> tuple[dict, dict]:
    baseline = json.loads(baseline_path.read_text("utf8"))
    probe = json.loads(probe_path.read_text("utf8"))
    want = probe["inputs"].get("results/s2/baseline.json")
    if want != sha256_file(baseline_path):
        raise DataError("the probe report is not from the committed baseline")
    errors = bench_report.check(baseline)
    if errors:
        raise DataError("the baseline is not correct: " + "; ".join(errors[:5]))
    ref = sqlfluff_ref(SQLFLUFF_ROOT)
    if baseline["sqlfluff_ref"] != ref or probe["sqlfluffrs"]["commit"] != ref:
        raise DataError("an input is not from the pinned sqlfluff commit")
    session = probe["speed"]["session"]["tools"]
    for tool, version in VERSIONS.items():
        if baseline["tools"][tool]["version"] != version or session[tool] != version:
            raise DataError(f"the {tool} version is not the pin {version}")
    ids = {r["id"] for r in baseline["results"] if r["command"] in MEASURED_BY_PROBE}
    got = [r["id"] for r in probe["speed"]["benchmarks"]]
    if sorted(got) != sorted(ids) or len(set(got)) != len(got):
        raise DataError("the probe benchmarks are not the start and parse benchmarks")
    return baseline, probe


# One row for each benchmark.


def _outcome(base_valid: bool, ratio: float | None, other_valid: bool, limit) -> str:
    if not other_valid:
        return SKIPPED
    if not base_valid:
        return NOT_MET
    if ratio is None:
        return UNKNOWN
    return MET if limit(ratio) else NOT_MET


def _ratio(a: float | None, b: float | None) -> float | None:
    return rr(a / b) if a is not None and b else None


def _entry(
    *,
    time_s: float | None,
    kind: str,
    origin: str,
    sqlfluff_s: float | None,
    sqruff_s: float | None,
    ref_from: str,
    status: str | None = None,
    over_sqlfluff: float | None = None,
    over_sqruff: float | None = None,
) -> dict:
    """kind: measured (origin: a SOURCES key), not_valid (the measured result,
    or the probe result that an estimate needs, is not valid), estimate
    (origin: a FORMULAS key), or no_estimate."""
    base_valid = kind != "not_valid"
    return {
        "time_s": rt(time_s),
        "kind": kind,
        ("from" if kind in ("measured", "not_valid") else "formula"): origin,
        "status": status,
        "sqlfluff_s": rt(sqlfluff_s),
        "sqruff_s": rt(sqruff_s),
        "ref_from": ref_from,
        "over_sqlfluff": over_sqlfluff,
        "over_sqruff": over_sqruff,
        "g3_4": _outcome(
            base_valid, over_sqlfluff, sqlfluff_s is not None, lambda x: x < 1
        ),
        "g3_5": _outcome(
            base_valid, over_sqruff, sqruff_s is not None, lambda x: x <= 1
        ),
    }


def _sqruff_entry(bid: str, base: dict) -> dict:
    res = base[(bid, "sqruff")]
    t = _median(res)
    refs = {
        "sqlfluff_s": _median(base[(bid, "sqlfluff")]),
        "sqruff_s": t,
        "ref_from": "baseline",
        "status": res["status"],
    }
    if t is None:
        return _entry(time_s=None, kind="not_valid", origin="baseline", **refs)
    return _entry(
        time_s=t,
        kind="measured",
        origin="baseline",
        over_sqlfluff=res["ratio"]["wall"],
        over_sqruff=1.0,
        **refs,
    )


def _parse_time(base_name: str, row: dict) -> float | None:
    """The start or parse time of an estimate base, or None."""
    if row["status"][PROBE] != VALID:
        return None
    t = row[PROBE]["median_s"]
    if base_name == "new-parser-low":
        setup = row["probe_phases"]["setup_s"]
        if not 0 < setup < t:
            raise DataError(f"{row['id']}: the setup phase is not in the probe time")
        t -= setup
    return t


def _copied_ratio(row: dict, other: str, want: float | None) -> float | None:
    got = row[f"probe_over_{other}"]
    if got != want:
        raise DataError(
            f"{row['id']}: probe_over_{other} {got} is not the ratio of the "
            f"medians {want}"
        )
    return got


def _not_valid_probe(row: dict, refs: dict) -> dict:
    return _entry(
        time_s=None,
        kind="not_valid",
        origin="session",
        status=row["status"][PROBE],
        **refs,
    )


def _probe_entry(base_name: str, row: dict) -> dict:
    t = _parse_time(base_name, row)
    refs = {
        "sqlfluff_s": row["sqlfluff"]["median_s"] if row["sqlfluff"] else None,
        "sqruff_s": row["sqruff"]["median_s"] if row["sqruff"] else None,
        "ref_from": "session",
    }
    if t is None:
        return _not_valid_probe(row, refs)
    if base_name == "sqlfluffrs":
        return _entry(
            time_s=t,
            kind="measured",
            origin="session",
            status=VALID,
            over_sqlfluff=_copied_ratio(row, "sqlfluff", _ratio(t, refs["sqlfluff_s"])),
            over_sqruff=_copied_ratio(row, "sqruff", _ratio(t, refs["sqruff_s"])),
            **refs,
        )
    formula = "option3_low" if base_name == "new-parser-low" else "option3_high"
    return _entry(
        time_s=t,
        kind="estimate",
        origin=formula,
        over_sqlfluff=_ratio(t, refs["sqlfluff_s"]),
        over_sqruff=_ratio(t, refs["sqruff_s"]),
        **refs,
    )


def rule_time(tq: float, pq: float, tb_parse: float, pq_session: float) -> float:
    return tq + pq * (tb_parse / pq_session - 1)


def unscaled_rule_time(tq: float, pq: float, tb_parse: float) -> float:
    return tb_parse + tq - pq


def _rule_entry(
    base_name: str, bid: str, base: dict, session_parse: dict, formula: str
) -> dict:
    rest = bid.split("/", 1)[1]
    tq = _median(base[(bid, "sqruff")])
    pq = _median(base[(f"parse/{rest}", "sqruff")])
    tb = _parse_time(base_name, session_parse)
    pqs = session_parse["sqruff"]["median_s"] if session_parse["sqruff"] else None
    refs = {
        "sqlfluff_s": _median(base[(bid, "sqlfluff")]),
        "sqruff_s": tq,
        "ref_from": "baseline",
    }
    if tb is None:
        return _not_valid_probe(session_parse, refs)
    if None in (tq, pq, pqs):
        return _entry(time_s=None, kind="no_estimate", origin=formula, **refs)
    if formula == "rule_time":
        t = rule_time(tq, pq, tb, pqs)
    else:
        t = unscaled_rule_time(tq, pq, tb)
    return _entry(
        time_s=t,
        kind="estimate",
        origin=formula,
        over_sqlfluff=_ratio(t, refs["sqlfluff_s"]),
        over_sqruff=_ratio(t, tq),
        **refs,
    )


def rows(baseline: dict, probe: dict) -> list[dict]:
    base = {(r["id"], r["tool"]): r for r in baseline["results"]}
    session = {r["id"]: r for r in probe["speed"]["benchmarks"]}
    out = []
    for bid in sorted({r["id"] for r in baseline["results"]}):
        first = base[(bid, "sqlfluff")]
        entry = {
            "id": bid,
            "command": first["command"],
            "dialect": first["dialect"],
            "size": first["size"],
            "bases": {"sqruff": _sqruff_entry(bid, base)},
        }
        for name in ESTIMATE_BASES:
            if first["command"] in MEASURED_BY_PROBE:
                entry["bases"][name] = _probe_entry(name, session[bid])
            else:
                parse = session["parse/" + bid.split("/", 1)[1]]
                entry["bases"][name] = _rule_entry(name, bid, base, parse, "rule_time")
        out.append(entry)
    return out


# Summaries.


def _counts(entries: list[dict], key: str) -> dict:
    n = Counter(e[key] for e in entries)
    return {o: n[o] for o in OUTCOMES}


def _total(entries: list[dict], weights: list[float] | None) -> dict:
    """The sums over the pairs (sqruff valid, base with a time). weights: None
    for the times of the rows; else total_all with the baseline sqruff times."""
    pairs = [
        (e, w)
        for e, w in zip(entries, weights or [None] * len(entries), strict=True)
        if e["over_sqruff"] is not None and (weights is None or w is not None)
    ]
    if weights is None:
        sb = sum(e["time_s"] for e, _ in pairs)
        sq = sum(e["sqruff_s"] for e, _ in pairs)
    else:
        sb = sum(e["over_sqruff"] * w for e, w in pairs)
        sq = sum(w for _, w in pairs)
    ratio = rr(sb / sq) if sq else None
    return {
        "pairs": len(pairs),
        "sum_base_s": rt(sb),
        "sum_sqruff_s": rt(sq),
        "ratio": ratio,
        "met": ratio is not None and ratio < 1,
        **({"formula": "total_all"} if weights is not None else {}),
    }


def summary(entries: list[dict], weights: list[float] | None = None) -> dict:
    g34 = _counts(entries, "g3_4")
    g35 = _counts(entries, "g3_5")
    to_sqlfluff = [
        e["over_sqlfluff"] for e in entries if e["over_sqlfluff"] is not None
    ]
    to_sqruff = [e["over_sqruff"] for e in entries if e["over_sqruff"] is not None]
    return {
        "benchmarks": len(entries),
        "kinds": dict(sorted(Counter(e["kind"] for e in entries).items())),
        "g3_4": {
            **g34,
            "all_met": g34[NOT_MET] == 0 and g34[UNKNOWN] == 0,
            "median_ratio": rr(statistics.median(to_sqlfluff)) if to_sqlfluff else None,
            "max_ratio": max(to_sqlfluff) if to_sqlfluff else None,
        },
        "g3_5_each": {
            **g35,
            "all_met": g35[NOT_MET] == 0 and g35[UNKNOWN] == 0,
            "median_ratio": rr(statistics.median(to_sqruff)) if to_sqruff else None,
            "max_ratio": max(to_sqruff) if to_sqruff else None,
            "over_noise": sum(x > NOISE_LIMIT for x in to_sqruff),
        },
        "g3_5_total": _total(entries, weights),
    }


def base_summary(name: str, table: list[dict]) -> dict:
    out = {}
    for command in COMMANDS:
        out[command] = summary(
            [r["bases"][name] for r in table if r["command"] == command]
        )
    entries = [r["bases"][name] for r in table]
    weights = [r["bases"]["sqruff"]["time_s"] for r in table]
    out["all"] = summary(entries, weights)
    return out


def speedup(name: str, table: list[dict], probe: dict) -> dict:
    """The lex and parse speed-up that each start and parse benchmark needs
    for G3.5 (formula "speedup")."""
    session = {r["id"]: r for r in probe["speed"]["benchmarks"]}
    out = {}
    for command in MEASURED_BY_PROBE:
        needed, factors, unreachable, not_valid = 0, [], [], []
        for r in table:
            e = r["bases"][name]
            if r["command"] != command or e["g3_5"] != NOT_MET:
                continue
            needed += 1
            if e["time_s"] is None:
                not_valid.append(r["id"])
                continue
            ph = session[r["id"]]["probe_phases"]
            lp = ph["lex_s"] + ph["parse_s"]
            room = e["sqruff_s"] - (e["time_s"] - lp)
            if room <= 0:
                unreachable.append(r["id"])
            else:
                factors.append(lp / room)
        out[command] = {
            "formula": "speedup",
            "needed": needed,
            "max_factor": rr(max(factors)) if factors else None,
            "median_factor": rr(statistics.median(factors)) if factors else None,
            "unreachable": unreachable,
            "not_valid": not_valid,
        }
    return out


def sensitivity(name: str, baseline: dict, probe: dict) -> dict:
    """G3 counts of lint and fix with the formula "unscaled"."""
    base = {(r["id"], r["tool"]): r for r in baseline["results"]}
    session = {r["id"]: r for r in probe["speed"]["benchmarks"]}
    out = {"formula": "unscaled"}
    for command in ("lint", "fix"):
        entries = [
            _rule_entry(
                name, bid, base, session["parse/" + bid.split("/", 1)[1]], "unscaled"
            )
            for bid in sorted({r["id"] for r in baseline["results"]})
            if bid.startswith(command + "/")
        ]
        s = summary(entries)
        out[command] = {
            "g3_4": {k: s["g3_4"][k] for k in (*OUTCOMES, "all_met")},
            "g3_5_each": {k: s["g3_5_each"][k] for k in (*OUTCOMES, "all_met")},
            "g3_5_total": s["g3_5_total"],
        }
    return out


def sqruff_not_valid(baseline: dict) -> dict:
    results = sorted(
        (r for r in baseline["results"] if r["tool"] == "sqruff"),
        key=lambda r: r["id"],
    )
    items = [
        {
            "id": r["id"],
            "status": r["status"],
            "class": reason_class(r["status"], r["reason"]),
            "reason": (r["reason"] or "").splitlines()[0],
        }
        for r in results
        if r["status"] != VALID
    ]
    by = Counter((i["class"], i["id"].split("/")[0]) for i in items)
    classes = sorted({c for c, _ in by})
    return {
        "source": "baseline",
        "count": len(items),
        "by_class": {
            c: {cmd: by[(c, cmd)] for cmd in COMMANDS if by[(c, cmd)]} for c in classes
        },
        "results": items,
    }


def make_report(
    baseline_path: Path = BASELINE_FILE, probe_path: Path = PROBE_FILE
) -> dict:
    baseline, probe = load(baseline_path, probe_path)
    table = rows(baseline, probe)
    speed = probe["speed"]["session"]
    bases = {}
    for name, option in BASES.items():
        entry = {
            "option": option,
            "kind": {
                "sqruff": "measured",
                "sqlfluffrs": "measured (start, parse); estimate (lint, fix)",
            }.get(name, "estimate"),
            "summary": base_summary(name, table),
        }
        if name in ESTIMATE_BASES:
            entry["lex_parse_speedup"] = speedup(name, table, probe)
            entry["sensitivity"] = sensitivity(name, baseline, probe)
        bases[name] = entry
    bases["sqruff"]["not_valid"] = sqruff_not_valid(baseline)
    return {
        "kind": "sqll-s3-speed-by-base",
        "task": "T6",
        "criterion": "C5",
        "command": COMMAND + " [--check]",
        "inputs": {rel(p): sha256_file(p) for p in (baseline_path, probe_path)},
        "sessions": {
            "baseline": {
                "harness": baseline["harness"],
                "profile": baseline["profile"],
                "machine": baseline["machine"],
            },
            "session": {
                "harness": speed["harness"],
                "image": speed["image"],
                "machine": speed["machine"],
                "baseline_over_session_median": probe["speed"]["summary"]["all"][
                    "baseline_over_session_median"
                ],
            },
        },
        "sources": SOURCES,
        "formulas": FORMULAS,
        "targets": TARGETS,
        "rules": RULES,
        "limits": LIMITS,
        "bases": bases,
        "benchmarks": table,
    }


# Output: one line for each object of scalars and each short value.


def _flat(value: dict) -> bool:
    return not any(isinstance(v, dict | list) for v in value.values())


def dumps(value, indent: int = 0) -> str:
    pad = " " * (indent + 1)
    long = len(json.dumps(value)) > 100
    if isinstance(value, dict) and value and long and not _flat(value):
        items = [
            f"{pad}{json.dumps(k)}: {dumps(v, indent + 1)}" for k, v in value.items()
        ]
        return "{\n" + ",\n".join(items) + "\n" + " " * indent + "}"
    if isinstance(value, list) and value and long:
        items = [pad + dumps(v, indent + 1) for v in value]
        return "[\n" + ",\n".join(items) + "\n" + " " * indent + "]"
    return json.dumps(value, ensure_ascii=False)


def text(value: dict) -> str:
    return dumps(value) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="speed_by_base.py")
    p.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    try:
        new = text(make_report())
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.check:
        if not OUT_FILE.exists() or OUT_FILE.read_text("utf8") != new:
            print(f"error: {rel(OUT_FILE)} is not the output of the inputs")
            return 1
        print(f"{rel(OUT_FILE)}: no change")
        return 0
    OUT_FILE.write_text(new, "utf8")
    print(f"wrote {rel(OUT_FILE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
