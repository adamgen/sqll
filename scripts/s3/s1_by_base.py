"""S3 phase A, task T2: the S1 results of each base, by suite and by dialect.

Two commands. Run them with the harness Python:

    uv run --frozen --project harness python scripts/s3/s1_by_base.py extract \\
        --checkout CLONE CLONE/out/report.json
    uv run --frozen --project harness python scripts/s3/s1_by_base.py build [--check]

"extract" reads the report of a sqruff run of the 4 parity suites (RUN_COMMAND
in a clean clone, CLONE) and writes the compact per-case list CASES_FILE.
"build" reads only committed files (CASES_FILE, the S1 summary, the
known-failures files, and the pinned fixtures) and writes OUT_FILE. With
--check it writes nothing and fails if OUT_FILE is not the new text.

Each command stops with exit code 1 if the data do not agree: the case ids
are not those of the fixtures, a count is not that of the S1 summary, or the
failed cases are not those of known_failures/sqruff.txt.
"""

import argparse
import functools
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from sqll_harness import known_failures
from sqll_harness.cases import ERROR, FAIL, PASS, SKIP, CaseResult
from sqll_harness.paths import RECORDED_SUMMARY, SQLFLUFF_ROOT, sqlfluff_ref
from sqll_harness.suites import SUITES, autofix, rules, templater

ROOT = Path(__file__).resolve().parents[2]
CASES_FILE = ROOT / "results" / "s3" / "sqruff-cases.json"
OUT_FILE = ROOT / "results" / "s3" / "s1-by-base.json"
KNOWN_FAILURES = ROOT / "known_failures"

PARITY_SUITES = ("dialects", "rules", "autofix", "templater")
# The checks of each suite, in the order of the per-case rows.
CHECKS = {
    "dialects": ("exact", "no_unparsable"),
    "rules": ("pass_str", "fail_str", "fix", "after_fix"),
    "autofix": ("tree", "non_linting", "violations", "fix"),
    "templater": ("exact", "no_unparsable"),
}
STATUSES = (PASS, FAIL, ERROR, SKIP)
NEEDS_PYTHON = templater.NEEDS_PYTHON

RUN_COMMAND = (
    "scripts/test --tool sqruff --suite dialects --suite rules --suite autofix"
    " --suite templater --jobs 4"
)
EXTRACT_COMMAND = (
    "uv run --frozen --project harness python scripts/s3/s1_by_base.py extract"
    " --checkout CLONE CLONE/out/report.json"
)
BUILD_COMMAND = (
    "uv run --frozen --project harness python scripts/s3/s1_by_base.py build"
)

SQLFLUFF_RS_NOTE = (
    "sqlfluff-rs is sqlfluff 4.4.0 with use_rust_parser and use_rust_rules "
    "(harness/sqlfluff-rs.md). Its parser is generated from the sqlfluff "
    "grammar and gives 2306 of 2306 exact dialect trees. But Python sqlfluff "
    "drives it: the CLI, the config, the templaters, and the rules are "
    "Python; only CP01, CP03, and CP04 have a Rust detection. Thus these "
    "results prove the generated parser, not a standalone tool. The S1 data "
    "have no per-case list for sqlfluff-rs: each case passes "
    "(known_failures/sqlfluff-rs.txt is empty, passed = total in the "
    "summary), so the case lists and the checks of each case come from the "
    "pinned fixtures; their counts agree with the summary."
)
SQRUFF_NOTE = (
    "Per-case data: results/s3/sqruff-cases.json, a new local run of the 4 "
    "suites (commands.run) at harness.commit. Its counts agree with the S1 "
    "summary and its failed cases are those of known_failures/sqruff.txt. "
    "Failure reasons: the reason prefixes of known_failures/sqruff.txt "
    "(sqll-harness known-failures --counts). 'no_result': the check applies "
    "to the case but has no result (an unsupported item, an earlier "
    "failure, or an unknown result)."
)
NEW_PARSER_NOTE = (
    "Option 3 has no implementation, thus it has no S1 data. The decision "
    "record gives estimates for it, labelled as estimates (T9)."
)


class DataError(Exception):
    """The inputs do not agree."""


# Cases of the pinned fixtures.


@functools.cache
def fixture_cases() -> dict[str, dict]:
    """Return {case id: {suite, group, applicable checks, tags}} of the 4 suites.

    The applicable checks are those that a passed case has: the checks that
    the suite gives for the fields of the case.
    """
    out: dict[str, dict] = {}
    for suite in PARITY_SUITES:
        for case in SUITES[suite].discover(SQLFLUFF_ROOT):
            if case.id in out:
                raise DataError(f"repeated case id {case.id}")
            out[case.id] = {
                "suite": suite,
                "group": _group(suite, case),
                "applicable": _applicable(suite, case),
                "tags": sorted(getattr(case, "tags", ())),
            }
    return out


def _group(suite: str, case) -> str:
    if suite == "rules":
        return ",".join(rules.rule_codes(case.rule))
    # dialects/<dialect>/<stem>, autofix/<dialect>/<case>,
    # templater/<folder>/<name>
    return case.id.split("/")[1]


def _applicable(suite: str, case) -> tuple[str, ...]:
    if suite == "rules":
        found = []
        if case.pass_str:
            found.append("pass_str")
        if case.fail_str:
            found += ["fail_str", "fix"]
            if case.fix_str:
                found.append("after_fix")
        return tuple(c for c in CHECKS[suite] if c in found)
    if suite == "autofix":
        cfg = autofix.load_test_config(case.folder / "test-config.yml")
        violations = case.folder / "violations.json"
        found = ["tree", "fix"]
        if cfg.raise_on_non_linting_violations:
            found.append("non_linting")
        if violations.exists() and json.loads(violations.read_text("utf-8")):
            found.append("violations")
        return tuple(c for c in CHECKS[suite] if c in found)
    return CHECKS[suite]


# extract: report -> CASES_FILE


def _git(checkout: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def extract(report: dict, commit: str, clean: bool) -> dict:
    """Return the per-case record of a sqruff run report."""
    errors = []
    scope = report.get("scope") or {}
    want_scope = {
        "suites": sorted(PARITY_SUITES),
        "tools": ["sqruff"],
        "filter": None,
        "shard": None,
    }
    if scope != want_scope:
        errors.append(f"scope is {scope}, not {want_scope}")
    if report.get("parts"):
        errors.append("the report is a merge of shards")
    if not clean:
        errors.append("the checkout of the run has changes")
    kf = report.get("known_failures", {}).get("sqruff")
    if kf != {"new_failures": [], "unexpected_passes": []}:
        errors.append(f"known-failure check of the run: {kf}")
    if report["sqlfluff_ref"] != sqlfluff_ref(SQLFLUFF_ROOT):
        errors.append("the sqlfluff ref of the run is not the pinned one")
    results = [CaseResult(**c) for c in report["cases"]]
    # The run must give the reasons of known_failures/sqruff.txt.
    recorded = (KNOWN_FAILURES / "sqruff.txt").read_text("utf8")
    if known_failures.render(results) != recorded:
        errors.append("the failed cases and reasons are not known_failures/sqruff.txt")
    rows = []
    for r in results:
        if r.tool != "sqruff" or r.suite not in CHECKS:
            errors.append(f"{r.id}: tool {r.tool}, suite {r.suite}")
            continue
        extra = set(r.checks) - set(CHECKS[r.suite])
        if extra:
            errors.append(f"{r.id}: unknown checks {sorted(extra)}")
        values = [_bit(r.checks.get(c)) for c in CHECKS[r.suite]]
        row = [r.id, r.status, values]
        if r.tags:
            row.append(sorted(r.tags))
        rows.append(row)
    if errors:
        raise DataError("; ".join(errors))
    record = {
        "kind": "sqll-s3-cases",
        "format": 1,
        "sqlfluff_ref": report["sqlfluff_ref"],
        "harness": {"commit": commit, "clean": clean},
        "commands": {"run": RUN_COMMAND, "extract": EXTRACT_COMMAND},
        "tool": "sqruff",
        "record": report["tools"]["sqruff"],
        "checks": {s: list(c) for s, c in CHECKS.items()},
        "values": "1: the check is true, 0: false, null: no result",
        "cases": sorted(rows),
    }
    check_cases(record, fixture_cases(), _summary())
    return record


def _bit(value: bool | None) -> int | None:
    return None if value is None else int(value)


# build: committed files -> OUT_FILE


def _summary() -> dict:
    return json.loads(RECORDED_SUMMARY.read_text("utf8"))


def _new_row(suite: str) -> dict:
    return {
        "total": 0,
        **dict.fromkeys(STATUSES, 0),
        "checks": {c: {"pass": 0, "fail": 0, "no_result": 0} for c in CHECKS[suite]},
    }


def _add(row: dict, status: str, applicable, values: dict[str, bool]) -> None:
    row["total"] += 1
    row[status] += 1
    for c in applicable:
        v = values.get(c)
        row["checks"][c]["no_result" if v is None else "pass" if v else "fail"] += 1


def _drop_unused_checks(row: dict) -> dict:
    row["checks"] = {
        c: v for c, v in row["checks"].items() if v["pass"] + v["fail"] + v["no_result"]
    }
    return row


def tables(cases: list[tuple[str, str, dict[str, bool], list[str]]], fixtures) -> dict:
    """Return the tables of one tool. cases: (id, status, checks, tags)."""
    suites = {s: _new_row(s) for s in PARITY_SUITES}
    groups: dict[str, dict[str, dict]] = {s: {} for s in PARITY_SUITES}
    for case_id, status, values, tags in cases:
        fx = fixtures[case_id]
        suite = fx["suite"]
        for row in (
            suites[suite],
            groups[suite].setdefault(fx["group"], _new_row(suite)),
        ):
            _add(row, status, fx["applicable"], values)
            if suite == "templater":
                tag = row.setdefault(NEEDS_PYTHON, {"total": 0, PASS: 0})
                if NEEDS_PYTHON in tags:
                    tag["total"] += 1
                    tag[PASS] += status == PASS
    return {
        "suites": {s: _drop_unused_checks(r) for s, r in suites.items()},
        "dialects": _sorted_rows(groups["dialects"]),
        "rules": _sorted_rows(groups["rules"]),
        "autofix": _sorted_rows(groups["autofix"]),
        "templater": _sorted_rows(groups["templater"]),
    }


def _sorted_rows(rows: dict[str, dict]) -> dict[str, dict]:
    return {k: _drop_unused_checks(rows[k]) for k in sorted(rows)}


def check_tables(tool: str, t: dict, summary: dict) -> list[str]:
    """Return the differences between the tables of a tool and the summary."""
    errors = []
    for suite in PARITY_SUITES:
        want = summary["results"][tool]["suites"][suite]
        row = t["suites"][suite]
        got = {
            "total": row["total"],
            "passed": row[PASS],
            "failed": row[FAIL],
            "error": row[ERROR],
            "skipped": row[SKIP],
            "checks": {
                c: v["pass"]
                for c, v in sorted(row["checks"].items())
                if v["pass"] + v["fail"]
            },
        }
        if suite == "templater":
            tag = row[NEEDS_PYTHON]
            got["tags"] = {NEEDS_PYTHON: {"total": tag["total"], "passed": tag[PASS]}}
        else:
            got["tags"] = {NEEDS_PYTHON: {"total": 0, "passed": 0}}
        if got != want:
            errors.append(f"{tool} {suite}: {got} is not the summary {want}")
        sums = Counter()
        for r in t[suite].values():
            sums.update({k: r[k] for k in ("total", *STATUSES)})
        if dict(sums) != {k: row[k] for k in ("total", *STATUSES)}:
            errors.append(f"{tool} {suite}: the groups do not add up to the suite")
    return errors


def check_cases(record: dict, fixtures: dict, summary: dict) -> None:
    """Raise DataError if the sqruff per-case list does not agree with the
    fixtures, the S1 summary, and known_failures/sqruff.txt."""
    errors = []
    if record["sqlfluff_ref"] != summary["sqlfluff_ref"]:
        errors.append("the sqlfluff ref is not that of the summary")
    if record["sqlfluff_ref"] != sqlfluff_ref(SQLFLUFF_ROOT):
        errors.append("the sqlfluff ref is not that of the submodule")
    if record["record"] != summary["tools"]["sqruff"]:
        errors.append("the sqruff record is not that of the summary")
    if record["checks"] != {s: list(c) for s, c in CHECKS.items()}:
        errors.append("the check names are not those of the script")
    ids = [row[0] for row in record["cases"]]
    if len(ids) != len(set(ids)):
        errors.append("repeated case ids")
    if set(ids) != set(fixtures):
        missing = sorted(set(fixtures) - set(ids))[:5]
        extra = sorted(set(ids) - set(fixtures))[:5]
        errors.append(f"case ids are not those of the fixtures: {missing} {extra}")
    known = known_failures.load(KNOWN_FAILURES, "sqruff")
    failed = set()
    for row in record["cases"]:
        case_id, status, values = row[0], row[1], row[2]
        fx = fixtures.get(case_id)
        if fx is None:
            continue
        suite = fx["suite"]
        if status not in STATUSES or len(values) != len(CHECKS[suite]):
            errors.append(f"{case_id}: bad row")
            continue
        present = {
            c for c, v in zip(CHECKS[suite], values, strict=True) if v is not None
        }
        if not present <= set(fx["applicable"]):
            errors.append(f"{case_id}: checks {sorted(present)} do not apply")
        if (status == PASS) != (
            present == set(fx["applicable"]) and all(v for v in values if v is not None)
        ):
            errors.append(f"{case_id}: status {status} does not agree with the checks")
        if status in (FAIL, ERROR):
            failed.add(case_id)
        tags = row[3] if len(row) > 3 else []
        if tags != fx["tags"]:
            errors.append(f"{case_id}: tags {tags} are not {fx['tags']}")
    for suite in PARITY_SUITES:
        got = {i for i in failed if fixtures[i]["suite"] == suite}
        want = {i for i in known if i.split("/", 1)[0] == suite}
        if got != want:
            errors.append(
                f"{suite}: the failed cases are not those of known_failures/"
                f"sqruff.txt ({len(got - want)} more, {len(want - got)} fewer)"
            )
    if errors:
        raise DataError("; ".join(errors))
    t = tables(_sqruff_cases(record), fixtures)
    errors = check_tables("sqruff", t, summary)
    if errors:
        raise DataError("; ".join(errors))


def _sqruff_cases(record: dict):
    for row in record["cases"]:
        suite = row[0].split("/", 1)[0]
        values = {
            c: bool(v)
            for c, v in zip(CHECKS[suite], row[2], strict=True)
            if v is not None
        }
        yield row[0], row[1], values, row[3] if len(row) > 3 else []


def _all_pass_cases(fixtures: dict):
    for case_id, fx in fixtures.items():
        yield case_id, PASS, dict.fromkeys(fx["applicable"], True), fx["tags"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(cases_file: Path = CASES_FILE) -> dict:
    """Return the content of OUT_FILE. Raise DataError if the inputs do not
    agree."""
    summary = _summary()
    fixtures = fixture_cases()
    record = json.loads(cases_file.read_text("utf8"))
    check_cases(record, fixtures, summary)

    errors = []
    for tool in ("sqlfluff-rs",):
        res = summary["results"][tool]
        if known_failures.load(KNOWN_FAILURES, tool):
            errors.append(f"known_failures/{tool}.txt is not empty")
        if res["parity"]["passed"] != res["parity"]["total"]:
            errors.append(f"{tool}: not all cases pass in the summary")
    rs = tables(_all_pass_cases(fixtures), fixtures)
    errors += check_tables("sqlfluff-rs", rs, summary)
    sq = tables(_sqruff_cases(record), fixtures)
    if errors:
        raise DataError("; ".join(errors))

    known = known_failures.load(KNOWN_FAILURES, "sqruff")
    prefixes: dict[str, dict[str, int]] = {}
    for case_id, reason in known.items():
        by_suite = prefixes.setdefault(known_failures.reason_prefix(reason), {})
        suite = case_id.split("/", 1)[0]
        by_suite[suite] = by_suite.get(suite, 0) + 1
    prefixes = {p: dict(sorted(prefixes[p].items())) for p in sorted(prefixes)}

    inputs = {
        CASES_FILE: cases_file,
        RECORDED_SUMMARY: RECORDED_SUMMARY,
        KNOWN_FAILURES / "sqruff.txt": KNOWN_FAILURES / "sqruff.txt",
        KNOWN_FAILURES / "sqlfluff-rs.txt": KNOWN_FAILURES / "sqlfluff-rs.txt",
    }
    tools = summary["tools"]
    return {
        "kind": "sqll-s3-s1-by-base",
        "format": 1,
        "sqlfluff_ref": summary["sqlfluff_ref"],
        "harness": record["harness"],
        "commands": {**record["commands"], "build": BUILD_COMMAND},
        "inputs": {str(k.relative_to(ROOT)): _sha256(v) for k, v in inputs.items()},
        "row": (
            "total: cases; pass, fail, error, skip: cases with that status; "
            "checks.<check>: of the cases where the check applies, pass, fail, "
            "and no_result; needs_python (templater): cases with the tag, and "
            "how many pass. Groups: dialects by dialect, rules by the rule "
            "codes of the case, autofix by dialect, templater by fixture folder."
        ),
        "bases": {
            "sqruff": {
                "option": 1,
                "tool": "sqruff",
                "version": tools["sqruff"]["version"],
                "record": tools["sqruff"],
                "data": "measured",
                "note": SQRUFF_NOTE,
                **sq,
                "failure_reasons": prefixes,
            },
            "sqlfluffrs": {
                "option": 2,
                "tool": "sqlfluff-rs",
                "version": tools["sqlfluff-rs"]["version"],
                "record": tools["sqlfluff-rs"],
                "data": "measured (S1 summary)",
                "note": SQLFLUFF_RS_NOTE,
                **rs,
                "failure_reasons": {},
            },
            "new-parser": {
                "option": 3,
                "data": None,
                "note": NEW_PARSER_NOTE,
            },
        },
    }


# Output: one line for each table row and each case.


def dumps(value, indent: int = 0) -> str:
    if isinstance(value, dict) and value and not _is_row(value):
        pad = " " * (indent + 1)
        items = [
            f"{pad}{json.dumps(k)}: {dumps(v, indent + 1)}" for k, v in value.items()
        ]
        return "{\n" + ",\n".join(items) + "\n" + " " * indent + "}"
    if isinstance(value, list) and value and isinstance(value[0], list):
        pad = " " * (indent + 1)
        items = [pad + json.dumps(v) for v in value]
        return "[\n" + ",\n".join(items) + "\n" + " " * indent + "]"
    return json.dumps(value)


def _is_row(value: dict) -> bool:
    """A table row, or a dict of scalars: one line."""
    return "total" in value or not any(
        isinstance(v, dict | list) for v in value.values()
    )


def text(value: dict) -> str:
    return dumps(value) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="s1_by_base.py")
    sub = p.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="Write CASES_FILE from a sqruff run report.")
    ex.add_argument("report", type=Path)
    ex.add_argument("--checkout", type=Path, required=True)
    ex.add_argument("--out", type=Path, default=CASES_FILE)
    bd = sub.add_parser("build", help="Write OUT_FILE from the committed inputs.")
    bd.add_argument("--cases", type=Path, default=CASES_FILE)
    bd.add_argument("--out", type=Path, default=OUT_FILE)
    bd.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.command == "extract":
            report = json.loads(args.report.read_text("utf8"))
            commit = _git(args.checkout, "rev-parse", "HEAD").strip()
            clean = _git(args.checkout, "status", "--porcelain") == ""
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text(extract(report, commit, clean)), "utf8")
            print(f"wrote {args.out}")
            return 0
        new = text(build(args.cases))
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.check:
        if not args.out.exists() or args.out.read_text("utf8") != new:
            print(f"error: {args.out} is not the output of the build", file=sys.stderr)
            return 1
        print(f"{args.out}: no change")
        return 0
    args.out.write_text(new, "utf8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
