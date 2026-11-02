"""S3 phase B, task T20: the data of the S3 exit record
(docs/decisions/s3-exit.md).

One command. Run it with the harness Python:

    uv run --frozen --project harness python scripts/s3/exit.py [--check]

It reads only committed files (INPUTS): the S2 baseline with the final sqll,
the S1 summary, the T18 record of the native tests of the base, and the T14
record (the speed target). It writes OUT_FILE. With --check it writes
nothing and fails if OUT_FILE is not the new text. It runs no tool and no
benchmark.

Each value has an id, the value, and the text that the exit record shows.
A value is "copied" ("from" and "key" name the file and the key) or
"derived" (a "formula" over other values). A key part in brackets selects
one item of a list by its fields: "results[id=start/ansi,tool=sqll]".

The criteria:
- S3 exit 1 (STONES.md): sqll passes all cases that the base passes: the
  dialect suite of S1 and the native tests of the base (T18).
- S3 exit 2 and G3.5 for S3: sqll is faster than sqruff (median wall time,
  one controlled session) on each start and parse benchmark where sqruff is
  valid. G3.4 for S3: sqll is faster than sqlfluff on each start and parse
  benchmark. sqll runs only start and parse until S5; lint and fix are
  unsupported, so G3.4 and G3.5 on lint and fix and the G3.5 total are for
  later stones.

It stops with exit code 1 (DataError) if a key is missing, if the baseline
is not a full baseline of all tools, or if the inputs do not agree (for
example, another sqll version in the S1 summary and the baseline).
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))
from sqll_harness.bench import baseline as bench_baseline  # noqa: E402
from sqll_harness.bench import definitions  # noqa: E402

OUT_FILE = ROOT / "results" / "s3" / "exit.json"
COMMAND = "uv run --frozen --project harness python scripts/s3/exit.py"

INPUTS = {
    "s2": "results/s2/baseline.json",
    "s1": "results/s1/summary.json",
    "t18": "results/s3/base-native-tests.json",
    "t14": "results/s3/speed-profile.json",
}

TOOL = "sqll"
OTHER = ("sqruff", "sqlfluff")
SQLL_COMMANDS = ("start", "parse")
LATER_COMMANDS = ("lint", "fix")
VALID = "valid"
STATE = "S3 awaiting human approval"

RULES = [
    "copied: the value of the key in the file. derived: a formula over other "
    "values. A key part in brackets selects one list item by its fields "
    '("a=x+y" matches the list [x, y]).',
    "A time is the median wall time of a result in the baseline (one "
    "controlled session). A ratio is sqll / other tool; below 1, sqll is "
    "faster. A tie is not faster.",
    "text: the form that docs/decisions/s3-exit.md shows. A ratio has 3 "
    "digits, a time sum in seconds has 2 digits.",
]


class DataError(Exception):
    """A key is missing, or the inputs do not agree."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(paths: dict[str, Path]) -> dict[str, dict]:
    data = {}
    for name, path in paths.items():
        try:
            data[name] = json.loads(path.read_text("utf8"))
        except (OSError, ValueError) as exc:
            raise DataError(f"{INPUTS[name]}: {exc}") from None
    return data


def _parts(key: str) -> list[str]:
    parts, word, depth = [], "", 0
    for ch in key:
        if ch == "[":
            if depth == 0 and word:
                parts.append(word)
                word = ""
            depth += 1
            word += ch
        elif ch == "]":
            depth -= 1
            word += ch
        elif ch == "." and depth == 0:
            if word:
                parts.append(word)
            word = ""
        else:
            word += ch
    return [*parts, word] if word else parts


def _field(value) -> str:
    return "+".join(map(str, value)) if isinstance(value, list) else str(value)


def get(doc, key: str):
    """Return the value of a dotted key. "[a=x,b=y]" selects the one list
    item with these field values; "a=x+y" matches the list value [x, y]."""
    value = doc
    for part in _parts(key):
        try:
            if part.startswith("["):
                want = dict(f.split("=", 1) for f in part[1:-1].split(","))
                found = [
                    item
                    for item in value
                    if all(_field(item.get(k)) == v for k, v in want.items())
                ]
                if len(found) != 1:
                    raise KeyError(part)
                value = found[0]
            else:
                value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, ValueError, TypeError, AttributeError):
            raise DataError(f"no key {key!r}") from None
    return value


def fmt_ratio(x: float) -> str:
    return f"{x:.3f}"


def fmt_sum(x: float) -> str:
    return f"{x:.2f}"


class Values:
    """The values of the exit record, each with its source."""

    def __init__(self, data: dict[str, dict]):
        self.data = data
        self.items: dict[str, dict] = {}

    def _add(self, vid: str, entry: dict) -> object:
        if vid in self.items:
            raise DataError(f"two values with the id {vid}")
        if "text" not in entry:
            entry["text"] = str(entry["value"])
        self.items[vid] = entry
        return entry["value"]

    def copy(self, vid: str, src: str, key: str, text=None) -> object:
        value = get(self.data[src], key)
        entry = {"kind": "copied", "value": value, "from": INPUTS[src], "key": key}
        if text is not None:
            entry["text"] = text(value) if callable(text) else text
        return self._add(vid, entry)

    def derive(self, vid: str, value, formula: str, text=None) -> object:
        entry = {"kind": "derived", "value": value, "formula": formula}
        if text is not None:
            entry["text"] = text(value) if callable(text) else text
        return self._add(vid, entry)

    def v(self, vid: str):
        return self.items[vid]["value"]


# The baseline run and its agreement with the other inputs.


def check_baseline(data: dict[str, dict]) -> None:
    """The baseline must be a full baseline of all tools (as the S2 baseline
    test checks), and the sqll of the S1 summary must be its sqll."""
    errors = bench_baseline.recorded(data["s2"], definitions.load())
    if errors:
        raise DataError(f"{INPUTS['s2']} is not a full baseline: {errors[0]}")
    if data["s1"]["sqlfluff_ref"] != data["s2"]["sqlfluff_ref"]:
        raise DataError("the S1 summary and the baseline have another sqlfluff ref")
    s1_version = data["s1"]["tools"][TOOL]["version"]
    if s1_version != data["s2"]["tools"][TOOL]["version"]:
        raise DataError(
            f"sqll {s1_version} in the S1 summary is not the sqll of the baseline"
        )


def run_values(vs: Values) -> None:
    vs.copy("s2.commit", "s2", "harness.commit", text=lambda v: v[:7])
    vs.copy("s2.clean", "s2", "harness.clean")
    vs.copy("s2.profile", "s2", "profile")
    vs.copy("s2.tools", "s2", "scope.tools", text=lambda v: str(len(v)))
    for tool in (TOOL, *OTHER):
        vs.copy(f"s2.{tool}.version", "s2", f"tools.{tool}.version")
    vs.copy("s1.sqll.version", "s1", f"tools.{TOOL}.version")
    vs.copy("t14.margin", "t14", "target.margin")
    vs.copy("t14.ratio_below", "t14", "target.ratio_below", text=fmt_ratio)


# S3 exit 1: the base cases.


def base_case_values(vs: Values) -> None:
    suite = f"results.{TOOL}.suites.dialects"
    vs.copy("s1.dialects.total", "s1", f"{suite}.total")
    vs.copy("s1.dialects.exact", "s1", f"{suite}.checks.exact")
    vs.copy("s1.dialects.no_unparsable", "s1", f"{suite}.checks.no_unparsable")
    for key in ("new_failures", "unexpected_passes"):
        vs.copy(
            f"s1.known_failures.{key}",
            "s1",
            f"results.{TOOL}.known_failures_check.{key}",
        )
    for key in ("tests", "passed", "failed", "ignored"):
        vs.copy(f"t18.base.{key}", "t18", f"totals.{key}")
    vs.copy("t18.base.exit_code", "t18", "cargo_test.exit_code")
    vs.derive(
        "exit.dialects",
        vs.v("s1.dialects.exact") == vs.v("s1.dialects.total")
        and vs.v("s1.known_failures.new_failures") == 0
        and vs.v("s1.known_failures.unexpected_passes") == 0,
        "s1.dialects.exact == s1.dialects.total and the known-failure check has "
        "0 new failures and 0 unexpected passes",
    )
    vs.derive(
        "exit.native_base",
        vs.v("t18.base.passed") == vs.v("t18.base.tests")
        and vs.v("t18.base.exit_code") == 0,
        "t18.base.passed == t18.base.tests and cargo test of the base gave exit "
        "code 0. The sqll side is the list check (scripts/s3/base_native_tests.py "
        "check: CI job build and scripts/verify): each base test that passes in "
        "the base passes in sqll",
    )


# S3 exit 2, G3.4 and G3.5 on the benchmarks that sqll runs.


def _result(vs: Values, bid: str, tool: str) -> dict:
    return get(vs.data["s2"], f"results[id={bid},tool={tool}]")


def benchmark_rows(vs: Values) -> list[dict]:
    """One row for each start and parse benchmark: the median wall times of
    sqll, sqruff, and sqlfluff, and the ratios."""
    ids = sorted(
        r["id"]
        for r in vs.data["s2"]["results"]
        if r["tool"] == TOOL and r["command"] in SQLL_COMMANDS
    )
    rows = []
    for bid in ids:
        row = {"id": bid, "command": bid.split("/")[0]}
        if _result(vs, bid, TOOL)["status"] != VALID:
            raise DataError(f"sqll {bid}: not valid in the baseline")
        key = f"results[id={bid},tool=%s].stats.wall_s.median"
        sqll = vs.copy(f"time.{bid}.{TOOL}", "s2", key % TOOL)
        for other in OTHER:
            status = vs.copy(
                f"status.{bid}.{other}", "s2", f"results[id={bid},tool={other}].status"
            )
            if status != VALID:
                vs.copy(
                    f"reason.{bid}.{other}",
                    "s2",
                    f"results[id={bid},tool={other}].reason",
                )
                row[other] = None
                continue
            t = vs.copy(f"time.{bid}.{other}", "s2", key % other)
            ratio = vs.derive(
                f"ratio.{bid}.{other}",
                round(sqll / t, 4),
                f"time.{bid}.{TOOL} / time.{bid}.{other}",
                text=fmt_ratio,
            )
            row[other] = {"ratio": ratio, "faster": sqll < t}
        rows.append(row)
    return rows


def speed_values(vs: Values, rows: list[dict]) -> None:
    paired = [r for r in rows if r["sqruff"] is not None]
    vs.derive("g3.benchmarks", len(rows), "count of the start and parse benchmarks")
    vs.derive(
        "g35.pairs",
        len(paired),
        "count of the start and parse benchmarks where sqruff is valid",
    )
    vs.derive(
        "g35.no_pair",
        sorted(r["id"] for r in rows if r["sqruff"] is None),
        "the start and parse benchmarks where sqruff is not valid",
        text=lambda v: str(len(v)),
    )
    slower = sorted(r["id"] for r in paired if not r["sqruff"]["faster"])
    vs.derive(
        "g35.slower",
        slower,
        "the pairs where time.sqll is not below time.sqruff",
        text=lambda v: str(len(v)),
    )
    vs.derive(
        "g35.faster",
        len(paired) - len(slower),
        "g35.pairs - count of g35.slower",
    )
    worst = max(paired, key=lambda r: (r["sqruff"]["ratio"], r["id"]))
    vs.derive(
        "g35.worst",
        {"id": worst["id"], "ratio": worst["sqruff"]["ratio"]},
        "the pair with the largest ratio to sqruff",
        text=lambda v: fmt_ratio(v["ratio"]),
    )
    ratios = sorted(r["sqruff"]["ratio"] for r in paired)
    mid = len(ratios) // 2
    median = ratios[mid] if len(ratios) % 2 else (ratios[mid - 1] + ratios[mid]) / 2
    vs.derive(
        "g35.median_ratio",
        round(median, 4),
        "the median of the ratios to sqruff of the pairs",
        text=fmt_ratio,
    )
    limit = vs.v("t14.ratio_below")
    above = sorted(r["id"] for r in paired if not r["sqruff"]["ratio"] < limit)
    vs.derive(
        "g35.below_target",
        len(paired) - len(above),
        "count of the pairs with a ratio to sqruff below t14.ratio_below "
        "(the T14 target: no tie within the noise)",
    )
    vs.derive(
        "g35.above_target",
        above,
        "the pairs not below t14.ratio_below",
        text=lambda v: str(len(v)),
    )
    not_faster = sorted(
        r["id"] for r in rows if r["sqlfluff"] is None or not r["sqlfluff"]["faster"]
    )
    vs.derive(
        "g34.not_faster",
        not_faster,
        "the start and parse benchmarks where sqlfluff is not valid or time.sqll "
        "is not below time.sqlfluff",
        text=lambda v: str(len(v)),
    )
    vs.derive(
        "g34.faster",
        len(rows) - len(not_faster),
        "g3.benchmarks - count of g34.not_faster",
    )
    worst = max(
        (r for r in rows if r["sqlfluff"] is not None),
        key=lambda r: (r["sqlfluff"]["ratio"], r["id"]),
    )
    vs.derive(
        "g34.worst",
        {"id": worst["id"], "ratio": worst["sqlfluff"]["ratio"]},
        "the benchmark with the largest ratio to sqlfluff",
        text=lambda v: fmt_ratio(v["ratio"]),
    )


def sum_values(vs: Values, rows: list[dict]) -> None:
    """The sums of the median times (G3.5 total: lint and fix are later)."""
    pair = "pairs[tools=sqll+sqruff]"
    vs.copy("sum.sqruff.benchmarks", "s2", f"{pair}.benchmarks")
    if vs.v("sum.sqruff.benchmarks") != vs.v("g35.pairs"):
        raise DataError("the sqll and sqruff pair of the baseline has other benchmarks")
    vs.copy("sum.sqruff.sqll", "s2", f"{pair}.wall_s.0", text=fmt_sum)
    vs.copy("sum.sqruff.sqruff", "s2", f"{pair}.wall_s.1", text=fmt_sum)
    vs.copy("sum.sqruff.ratio", "s2", f"{pair}.wall_ratio", text=fmt_ratio)
    pair = "pairs[tools=sqlfluff+sqll]"
    vs.copy("sum.sqlfluff.benchmarks", "s2", f"{pair}.benchmarks")
    vs.copy("sum.sqlfluff.sqlfluff", "s2", f"{pair}.wall_s.0", text=fmt_sum)
    vs.copy("sum.sqlfluff.sqll", "s2", f"{pair}.wall_s.1", text=fmt_sum)
    vs.copy("sum.sqlfluff.ratio_inverse", "s2", f"{pair}.wall_ratio", text=fmt_ratio)
    for command in SQLL_COMMANDS:
        mine = [r for r in rows if r["command"] == command and r["sqruff"] is not None]
        sqll = sum(vs.v(f"time.{r['id']}.{TOOL}") for r in mine)
        other = sum(vs.v(f"time.{r['id']}.sqruff") for r in mine)
        vs.derive(f"sum.{command}.pairs", len(mine), f"count of the {command} pairs")
        vs.derive(
            f"sum.{command}.sqll",
            round(sqll, 4),
            f"sum of time.<id>.sqll over the {command} pairs",
            text=fmt_sum,
        )
        vs.derive(
            f"sum.{command}.sqruff",
            round(other, 4),
            f"sum of time.<id>.sqruff over the {command} pairs",
            text=fmt_sum,
        )
        vs.derive(
            f"sum.{command}.ratio",
            round(sqll / other, 4),
            f"sum.{command}.sqll / sum.{command}.sqruff",
            text=fmt_ratio,
        )


def later_values(vs: Values) -> None:
    """Lint and fix: unsupported for sqll until S5."""
    results = vs.data["s2"]["results"]
    total = 0
    for command in LATER_COMMANDS:
        mine = [r for r in results if r["tool"] == TOOL and r["command"] == command]
        reasons = sorted({r["reason"] for r in mine if r["status"] == "unsupported"})
        unsupported = sum(r["status"] == "unsupported" for r in mine)
        if unsupported != len(mine):
            raise DataError(f"sqll {command}: a result that is not unsupported")
        vs.derive(
            f"later.{command}.unsupported",
            unsupported,
            f"count of the sqll {command} results with the status unsupported",
        )
        vs.derive(
            f"later.{command}.reason",
            reasons,
            f"the reasons of the sqll {command} results",
            text=lambda v: "; ".join(v),
        )
        total += unsupported
    vs.copy("later.sqll.unsupported", "s2", f"totals.{TOOL}.unsupported")
    if vs.v("later.sqll.unsupported") != total:
        raise DataError("the sqll unsupported total is not that of lint and fix")
    vs.derive(
        "later.all_benchmarks",
        len({r["id"] for r in results}),
        "count of the benchmarks of the baseline",
    )


def criteria(vs: Values) -> list[dict]:
    g35 = not vs.v("g35.slower")
    g34 = not vs.v("g34.not_faster")
    return [
        {
            "id": "S3.exit.base_cases",
            "text": "STONES.md S3 exit: sqll passes all cases that the base passes.",
            "met": vs.v("exit.dialects") and vs.v("exit.native_base"),
            "values": ["exit.dialects", "exit.native_base"],
            "note": "The base cases are the S1 dialect suite and the native tests "
            "of the base. The S1 rule cases of CP01, CP03, and CP04 are not base "
            "cases: the native base has no linter, config reader, CLI, or fix. The "
            "human owner checks this reading at stone approval.",
        },
        {
            "id": "S3.exit.sqruff",
            "text": "STONES.md S3 exit: sqll is not slower than sqruff on any "
            "benchmark (G3.5), on the benchmarks that sqll runs.",
            "met": g35,
            "values": ["g35.pairs", "g35.slower", "g35.no_pair"],
            "note": "sqll runs start and parse. Lint and fix are unsupported "
            "until S5 (later.lint.unsupported, later.fix.unsupported).",
        },
        {
            "id": "G3.4.start_parse",
            "text": "CONSTITUTION.md G3.4 on the benchmarks that sqll runs: sqll "
            "is faster than sqlfluff on each start and parse benchmark.",
            "met": g34,
            "values": ["g3.benchmarks", "g34.not_faster"],
        },
        {
            "id": "later",
            "text": "Not met yet, for later stones: G3.4 and G3.5 on lint and fix, "
            "and the G3.5 total over all benchmarks.",
            "met": None,
            "values": ["later.lint.unsupported", "later.fix.unsupported"],
        },
    ]


def make_report(paths: dict[str, Path] | None = None) -> dict:
    paths = paths or {k: ROOT / v for k, v in INPUTS.items()}
    data = load(paths)
    check_baseline(data)
    vs = Values(data)
    run_values(vs)
    base_case_values(vs)
    rows = benchmark_rows(vs)
    speed_values(vs, rows)
    sum_values(vs, rows)
    later_values(vs)
    crit = criteria(vs)
    met = all(c["met"] for c in crit if c["met"] is not None)
    return {
        "kind": "sqll-s3-exit",
        "task": "T20",
        "command": COMMAND,
        "inputs": {INPUTS[k]: sha256_file(p) for k, p in paths.items()},
        "rules": RULES,
        "criteria": crit,
        "result": {"met": met, "state": STATE if met else "S3 exit not met"},
        "benchmarks": rows,
        "values": vs.items,
    }


def text(report: dict) -> str:
    return json.dumps(report, indent=1, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="exit.py")
    p.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    try:
        new = text(make_report())
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        rel = OUT_FILE.resolve().relative_to(ROOT)
    except ValueError:
        rel = OUT_FILE
    if args.check:
        if not OUT_FILE.exists() or OUT_FILE.read_text("utf8") != new:
            print(f"error: {rel} is not the output of the inputs")
            return 1
        print(f"{rel}: no change")
        return 0
    OUT_FILE.write_text(new, "utf8")
    print(f"wrote {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
