#!/usr/bin/env python3
"""The corpus information of S4 (parser parity: sqll passes 100% of the
dialect parse fixtures with an exact tree match).

Design record: docs/decisions/s4-parity.md, section 4 ("The external
corpus"). Task T4 (the parse status of sqll and sqlfluff on each corpus file
is recorded, and each difference has a row) of S4 made this script.

  uv run --frozen --project harness python scripts/s4/corpus.py \\
      [--root DIR] [--report FILE] [--manifest FILE] [--settings FILE] \\
      [--out FILE] [--table]

The inputs. A default path is relative to --root (default: the root of this
repository):

  --report    the merged corpus report of one full-profile run of sqll and
              sqlfluff (default: results/S4/corpus.json), from the corpus
              harness of S9 (external corpus: large, complex SQL files from
              public sources, with their source and license; the report
              shows parse success and speed for each file, for each tool):
              "python -m sqll_harness.corpus run" or "merge".
  --manifest  the corpus manifest (default: corpus/sources.json). The report
              must be complete for it: the harness function incomplete().
  --settings  optional: the proof of each settings difference (a JSON object
              {"format": 1, "entries": [...]}, see SETTINGS_ENTRY). Each
              entry gives one file, the setting, and the sqll result with
              and without the setting.

For each file of the report, the output has the status and the unparsable
count and bytes of each tool. Each file where sqll and sqlfluff have a
different status or a different unparsable count gets one row, with one
class:

  settings     an iteration, depth, or render setting causes the difference.
               An entry of --settings gives the setting and the proof: the
               sqll result without the setting is the result of the report,
               and the sqll result with the setting is the sqlfluff result.
  templater    a templated (Jinja) file that sqll fails closed on, because
               sqll does not have the Jinja templater. That is S11 (Jinja
               templater: the last stone; decide with data how sqll supports
               Jinja), not a parser gap.
  parser gap   each other difference.

The result is information only (design record section 4): a row does not
fail the script. Exit code 0 if the output is written. Exit code 2 if an
input is missing or not valid (the list "errors"): a report with a schema
error, not a full-profile report of sqll and sqlfluff, a shard report, a
report that is not complete for the manifest, a result with the status
"error" (the harness could not run or check the tool), or a --settings
entry that is not a proof. The script never passes with no data: a report
with no file is not valid.

Output: one JSON object on stdout (with --table: the Markdown tables for
status/S4.md), and in --out if it is given.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from sqll_harness.corpus import report as corpus_report
from sqll_harness.corpus import run as corpus_run
from sqll_harness.corpus.manifest import JINJA, ManifestError, load
from sqll_harness.paths import REPO_ROOT

FORMAT = 1
SQLL = "sqll"
SQLFLUFF = "sqlfluff"
TOOLS = (SQLFLUFF, SQLL)
PROFILE = "full"
DEFAULT_REPORT = Path("results") / "S4" / "corpus.json"
DEFAULT_MANIFEST = Path("corpus") / "sources.json"
SETTINGS = "settings"
TEMPLATER = "templater"
PARSER_GAP = "parser gap"
CLASSES = (SETTINGS, TEMPLATER, PARSER_GAP)
# sqll fails closed on an item that it cannot do: "Error: unsupported: ..."
# and exit code 2. The bench adapter of sqll puts the line in the reason.
FAIL_CLOSED = re.compile(r"\bunsupported\b", re.I)
JINJA_TEXT = re.compile(r"\bjinja\b", re.I)
FAIL_CLOSED_STATUSES = (corpus_report.INVALID, corpus_report.UNSUPPORTED)
SETTINGS_ENTRY = ("file", "setting", "value", "with", "without", "command")
RESULT_KEYS = ("status", "unparsable_count")


class InputError(Exception):
    """An input is missing or not valid."""


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def read_json(path: Path, name: str):
    try:
        text = path.read_text(encoding="utf8")
    except FileNotFoundError:
        raise InputError(f"{name} {path} does not exist") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"{name} {path} cannot be read: {exc}") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{name} {path} is not valid JSON: {exc}") from None


def load_report(path: Path, manifest_path: Path) -> dict:
    """Return the report. InputError if it is not a complete full-profile
    report of sqll and sqlfluff for the manifest."""
    rep = read_json(path, "report")
    if not isinstance(rep, dict):
        raise InputError(f"report {path} is not a JSON object")
    errors = corpus_report.check(rep)
    if errors:
        raise InputError(
            f"report {path} has {len(errors)} schema errors: " + "; ".join(errors[:5])
        )
    if not rep["inputs"]:
        raise InputError(f"report {path} has no file")
    if rep["profile"] != PROFILE:
        raise InputError(
            f"report {path} has the profile {rep['profile']}, not {PROFILE}"
        )
    if rep["scope"]["shard"] is not None:
        raise InputError(
            f"report {path} is the shard {rep['scope']['shard']}, not a merged report"
        )
    missing = [t for t in TOOLS if t not in rep["scope"]["tools"]]
    if missing:
        raise InputError(f"report {path} has no results of {', '.join(missing)}")
    try:
        manifest = load(manifest_path)
    except ManifestError as exc:
        raise InputError(
            f"manifest {manifest_path} is not valid: " + "; ".join(exc.errors[:5])
        ) from None
    except OSError as exc:
        raise InputError(f"manifest {manifest_path} cannot be read: {exc}") from None
    errors = corpus_run.incomplete(rep, manifest)
    if errors:
        raise InputError(
            f"report {path} is not complete for the manifest {manifest_path}: "
            + "; ".join(errors[:5])
        )
    bad = [
        f"{r['tool']} {r['file']}: {r['reason']}"
        for r in rep["results"]
        if r["tool"] in TOOLS and r["status"] == corpus_report.ERROR
    ]
    if bad:
        raise InputError(
            f"report {path} has {len(bad)} results with the status error (no"
            " data): " + "; ".join(bad[:5])
        )
    return rep


def _result(value, where: str) -> dict:
    if not isinstance(value, dict) or set(value) != set(RESULT_KEYS):
        raise InputError(
            f"{where}: not an object with the keys {', '.join(RESULT_KEYS)}"
        )
    if value["status"] not in corpus_report.STATUSES:
        raise InputError(f"{where}: unknown status {value['status']!r}")
    count = value["unparsable_count"]
    if count is not None and (not isinstance(count, int) or isinstance(count, bool)):
        raise InputError(f"{where}: unparsable_count is not an int or null")
    return value


def load_settings(path: Path | None) -> dict[str, dict]:
    """Return the settings proofs by file. InputError if not valid."""
    if path is None:
        return {}
    data = read_json(path, "settings")
    if (
        not isinstance(data, dict)
        or data.get("format") != FORMAT
        or not isinstance(data.get("entries"), list)
    ):
        raise InputError(
            f'settings {path} is not an object {{"format": {FORMAT}, "entries": [...]}}'
        )
    out = {}
    for i, entry in enumerate(data["entries"]):
        where = f"settings {path} entry {i}"
        if not isinstance(entry, dict) or set(entry) != set(SETTINGS_ENTRY):
            raise InputError(f"{where}: not an object with the keys {SETTINGS_ENTRY}")
        for key in ("file", "setting", "command"):
            if not isinstance(entry[key], str) or not entry[key]:
                raise InputError(f"{where}: {key} is not a text")
        _result(entry["with"], f"{where} with")
        _result(entry["without"], f"{where} without")
        if entry["file"] in out:
            raise InputError(f"{where}: a second entry for {entry['file']}")
        out[entry["file"]] = entry
    return out


def tool_result(r: dict) -> dict:
    u = r["unparsable"]
    return {
        "status": r["status"],
        "unparsable_count": u["count"] if u else None,
        "unparsable_bytes": u["bytes"] if u else None,
        "reason": r["reason"],
    }


def same(a: dict, b: dict) -> bool:
    return all(a[k] == b[k] for k in RESULT_KEYS)


def is_templater(record: dict, sqll: dict) -> bool:
    """A templated file that sqll fails closed on for the Jinja templater."""
    reason = sqll["reason"] or ""
    return (
        record["templater"] == JINJA
        and sqll["status"] in FAIL_CLOSED_STATUSES
        and bool(FAIL_CLOSED.search(reason))
        and bool(JINJA_TEXT.search(reason))
    )


def classify(rep: dict, proofs: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Return (files, rows). InputError if a settings proof is not valid."""
    by_file: dict[str, dict] = {}
    for r in rep["results"]:
        if r["tool"] in TOOLS:
            by_file.setdefault(r["file"], {})[r["tool"]] = tool_result(r)
    unknown = sorted(set(proofs) - set(by_file))
    if unknown:
        raise InputError(f"settings: no file {', '.join(unknown[:5])} in the report")
    files, rows = [], []
    for file_id, record in rep["inputs"].items():
        results = by_file[file_id]
        equal = same(results[SQLFLUFF], results[SQLL])
        files.append(
            {
                "file": file_id,
                "dialect": record["dialect"],
                "templater": record["templater"],
                "bytes": record["bytes"],
                **{
                    t: {k: v for k, v in results[t].items() if k != "reason"}
                    for t in TOOLS
                },
                "same": equal,
            }
        )
        proof = proofs.get(file_id)
        if equal:
            if proof is not None:
                raise InputError(
                    f"settings: {file_id} has no difference, but it has an entry"
                )
            continue
        row = {
            "file": file_id,
            "dialect": record["dialect"],
            "templater": record["templater"],
            "bytes": record["bytes"],
            SQLFLUFF: results[SQLFLUFF],
            SQLL: results[SQLL],
        }
        if is_templater(record, results[SQLL]):
            if proof is not None:
                raise InputError(
                    f"settings: {file_id} is a templater difference, but it has"
                    " an entry"
                )
            row["class"] = TEMPLATER
            row["cause"] = (
                "sqll fails closed: it does not have the Jinja templater of"
                " S11 (Jinja templater: the last stone; decide with data how"
                " sqll supports Jinja)"
            )
        elif proof is not None:
            report_sqll = {k: results[SQLL][k] for k in RESULT_KEYS}
            report_sqlfluff = {k: results[SQLFLUFF][k] for k in RESULT_KEYS}
            if proof["without"] != report_sqll:
                raise InputError(
                    f"settings: the sqll result without {proof['setting']} on"
                    f" {file_id} is {proof['without']}, not the result of the"
                    f" report {report_sqll}"
                )
            if proof["with"] != report_sqlfluff:
                raise InputError(
                    f"settings: the sqll result with {proof['setting']} on"
                    f" {file_id} is {proof['with']}, not the sqlfluff result"
                    f" {report_sqlfluff}: the setting does not remove the"
                    " difference"
                )
            row["class"] = SETTINGS
            row["cause"] = f"the setting {proof['setting']}"
            row["setting"] = {
                "name": proof["setting"],
                "value": proof["value"],
                "with": proof["with"],
                "without": proof["without"],
                "command": proof["command"],
            }
        else:
            row["class"] = PARSER_GAP
            row["cause"] = (
                "a different status or unparsable count with the same settings"
            )
        rows.append(row)
    return files, rows


def counts(files: list[dict], rows: list[dict]) -> dict:
    by_tool = {}
    for t in TOOLS:
        c = Counter(f[t]["status"] for f in files)
        by_tool[t] = {s: c[s] for s in corpus_report.STATUSES}
    by_class = Counter(r["class"] for r in rows)
    return {
        "files": len(files),
        "same": sum(f["same"] for f in files),
        "rows": len(rows),
        "by_tool": by_tool,
        "by_class": {c: by_class[c] for c in CLASSES},
    }


def report_record(rep: dict) -> dict:
    return {
        "sqlfluff_ref": rep["sqlfluff_ref"],
        "harness": rep["harness"],
        "profile": rep["profile"],
        "manifest_sha256": rep["manifest_sha256"],
        "tools": {t: rep["tools"][t]["version"] for t in TOOLS},
        "parts": [p["shard"] for p in rep["parts"] or []],
    }


def check(args: argparse.Namespace) -> dict:
    root = args.root
    report_path = args.report or root / DEFAULT_REPORT
    manifest_path = args.manifest or root / DEFAULT_MANIFEST
    result: dict = {
        "format": FORMAT,
        "check": "S4 corpus information (docs/decisions/s4-parity.md, section 4)",
        "status": "error",
        "exit_code": 2,
        "commit": None,
        "inputs": {
            "report": str(report_path),
            "manifest": str(manifest_path),
            "settings": str(args.settings) if args.settings else None,
        },
        "errors": [],
    }
    try:
        result["commit"] = git(root, "rev-parse", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        pass
    try:
        rep = load_report(report_path, manifest_path)
        proofs = load_settings(args.settings)
        files, rows = classify(rep, proofs)
    except InputError as exc:
        result["errors"].append(str(exc))
        return result
    result["report"] = report_record(rep)
    result["counts"] = counts(files, rows)
    result["files"] = files
    result["rows"] = rows
    result["status"] = "pass"
    result["exit_code"] = 0
    return result


def _cell(t: dict) -> str:
    if t["unparsable_count"] is None:
        return t["status"]
    return f"{t['status']} ({t['unparsable_count']}, {t['unparsable_bytes']} B)"


def table(result: dict) -> str:
    """Return the Markdown tables of the counts and the rows."""
    c = result["counts"]
    lines = [
        "| Tool | " + " | ".join(corpus_report.STATUSES) + " |",
        "|---|" + "---|" * len(corpus_report.STATUSES),
    ]
    for t in TOOLS:
        n = c["by_tool"][t]
        lines.append(
            f"| {t} | " + " | ".join(str(n[s]) for s in corpus_report.STATUSES) + " |"
        )
    lines += [
        "",
        "| File | Dialect | Templater | sqlfluff | sqll | Class | Cause |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in result["rows"]:
        cause = r["cause"]
        if r["class"] == SETTINGS:
            s = r["setting"]
            cause += f" = {s['value']}: with {s['with']}, without {s['without']}"
        lines.append(
            f"| `{r['file']}` | {r['dialect']} | {r['templater']} |"
            f" {_cell(r[SQLFLUFF])} | {_cell(r[SQLL])} | {r['class']} | {cause} |"
        )
    return "\n".join(lines) + "\n"


def summary_line(result: dict) -> str:
    if result["status"] == "error":
        return f"S4 corpus: error: {len(result['errors'])} input error(s)"
    c = result["counts"]
    classes = ", ".join(f"{k} {v}" for k, v in c["by_class"].items())
    return (
        f"S4 corpus: {c['files']} files; same status and unparsable count"
        f" {c['same']}; rows {c['rows']} ({classes})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="The corpus information of S4 (parser parity: sqll passes"
        " 100% of the dialect parse fixtures with an exact tree match)."
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--table", action="store_true", help="Print the Markdown tables on stdout."
    )
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    result = check(args)
    text = json.dumps(result, indent=1) + "\n"
    if args.table and result["exit_code"] == 0:
        sys.stdout.write(table(result))
    else:
        sys.stdout.write(text)
    if args.out and result["exit_code"] == 0:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf8")
    print(summary_line(result), file=sys.stderr)
    for error in result["errors"]:
        print(f"error: {error}", file=sys.stderr)
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
