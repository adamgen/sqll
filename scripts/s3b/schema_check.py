"""S3b task C15: validate the JSON Schema output of the code generation
interface (docs/interfaces/schema.md) with the jsonschema package.

Run it with the harness Python from the repository root:

    uv run --frozen --project harness python scripts/s3b/schema_check.py check
    uv run --frozen --project harness python scripts/s3b/schema_check.py write
    uv run --frozen --project harness python scripts/s3b/schema_check.py validate [FOLDER]

check (CI job build, scripts/verify): run the ignored test TEST of
crates/sqll_interfaces/tests/schema.rs (cargo test --locked). It writes the
output of the JSON Schema writer for each case into a new folder. The new
files must be the committed record (RECORD and RECORD_DIR). Then validate
the new files.

validate: for each case of the record (FOLDER, default results/S3b): the
schema is valid against the meta-schema of JSON Schema draft 2020-12, its
"$schema" is that draft, each "valid" example passes the schema, and each
"invalid" example fails it. It runs no cargo (harness/tests/test_s3b_schema.py
validates the committed record).

write: run the test into results/S3b (the record), then validate.

Exit code: 0 pass, 1 a failure.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "results" / "S3b"
RECORD_NAME = "C15-schema.json"
RECORD_DIR_NAME = "C15-schema"
RECORD = FOLDER / RECORD_NAME
RECORD_DIR = FOLDER / RECORD_DIR_NAME
KIND = "sqll-s3b-c15-schema"
DRAFT = "https://json-schema.org/draft/2020-12/schema"
COMMAND = "uv run --frozen --project harness python scripts/s3b/schema_check.py"
TEST = "write_the_record"
OUT_ENV = "SQLL_SCHEMA_OUT"
CASES = ("minimal", "named", "question_mark", "numeric_dollar")


class DataError(Exception):
    """A step failed, or the data does not agree."""


def validate(folder: Path) -> tuple[list[str], dict]:
    """Return the problems of the record in folder, and the counts."""
    problems = []
    counts = {"schemas": 0, "valid": 0, "invalid": 0}
    try:
        record = json.loads((folder / RECORD_NAME).read_text("utf8"))
    except (OSError, ValueError) as e:
        return [f"{RECORD_NAME}: {e}"], counts
    if record.get("kind") != KIND:
        problems.append(f"{RECORD_NAME}: kind is not {KIND}")
    if record.get("meta_schema") != DRAFT:
        problems.append(f"{RECORD_NAME}: meta_schema is not {DRAFT}")
    if record.get("command") != f"{COMMAND} write":
        problems.append(f"{RECORD_NAME}: command is not '{COMMAND} write'")
    cases = record.get("cases") or []
    names = tuple(c.get("name") for c in cases)
    if names != CASES:
        problems.append(f"{RECORD_NAME}: the cases are {names}, not {CASES}")
    for case in cases:
        name = case.get("name")
        path = case.get("schema", "")
        if path != f"{RECORD_DIR_NAME}/{name}.json":
            problems.append(f"{name}: the schema file is {path!r}")
            continue
        try:
            schema = json.loads((folder / path).read_text("utf8"))
        except (OSError, ValueError) as e:
            problems.append(f"{name}: {path}: {e}")
            continue
        counts["schemas"] += 1
        bad = schema_problems(schema, name)
        problems += [f"{name}: {p}" for p in bad]
        if bad:
            continue
        if not case.get("valid") or not case.get("invalid"):
            problems.append(f"{name}: no valid or no invalid example")
            continue
        validator = Draft202012Validator(
            schema, format_checker=Draft202012Validator.FORMAT_CHECKER
        )
        for i, example in enumerate(case["valid"]):
            errors = [e.message for e in validator.iter_errors(example)]
            if errors:
                problems.append(f"{name}: valid example {i} fails: {errors[0]}")
            counts["valid"] += 1
        for i, example in enumerate(case["invalid"]):
            if validator.is_valid(example):
                problems.append(f"{name}: invalid example {i} passes")
            counts["invalid"] += 1
    return problems, counts


def schema_problems(schema: object, title: str) -> list[str]:
    """The problems of one schema: not valid against the draft 2020-12
    meta-schema, another "$schema", or another title."""
    if not isinstance(schema, dict):
        return ["the schema is not a JSON object"]
    problems = []
    meta = Draft202012Validator(Draft202012Validator.META_SCHEMA)
    for error in meta.iter_errors(schema):
        path = "/".join(str(p) for p in error.absolute_path)
        problems.append(
            f"not valid against the meta-schema at /{path}: {error.message}"
        )
    if schema.get("$schema") != DRAFT:
        problems.append(f"$schema is not {DRAFT}")
    if schema.get("title") != title:
        problems.append(f"the title is not {title!r}")
    return problems


def run_test(out: Path) -> None:
    """Run TEST: it writes the record files into out."""
    env = {k: v for k, v in os.environ.items() if k != "CARGO_TERM_COLOR"}
    env["CARGO_TERM_COLOR"] = "never"
    env[OUT_ENV] = str(out)
    argv = ["cargo", "test", "--locked", "--test", "schema", "--", "--ignored"]
    argv += ["--exact", TEST]
    print("schema_check: $ " + " ".join(argv), flush=True)
    proc = subprocess.run(
        argv, cwd=ROOT, env=env, text=True, capture_output=True, check=False
    )
    output = proc.stdout + proc.stderr
    if proc.returncode != 0 or "test result: ok. 1 passed;" not in output:
        raise DataError(f"cargo test: exit code {proc.returncode}\n{output[-4000:]}")


def files(folder: Path) -> dict[str, bytes]:
    """The record files in folder, by path relative to folder."""
    out = {}
    if (folder / RECORD_NAME).is_file():
        out[RECORD_NAME] = (folder / RECORD_NAME).read_bytes()
    if (folder / RECORD_DIR_NAME).is_dir():
        for path in sorted((folder / RECORD_DIR_NAME).iterdir()):
            out[f"{RECORD_DIR_NAME}/{path.name}"] = path.read_bytes()
    return out


def compare(new: Path, old: Path) -> list[str]:
    """The record files that are not the same in new and old."""
    a, b = files(new), files(old)
    return [
        f"{p} is not the committed record"
        for p in sorted(a.keys() | b.keys())
        if a.get(p) != b.get(p)
    ]


def report(problems: list[str], counts: dict) -> int:
    for p in problems:
        print(f"schema check: {p}", file=sys.stderr)
    if problems:
        print(f"schema check: FAIL: {len(problems)} problems", file=sys.stderr)
        return 1
    print(
        f"schema check: PASS: {counts['schemas']} schemas valid against the JSON"
        f" Schema draft 2020-12 meta-schema; {counts['valid']} valid examples pass"
        f" and {counts['invalid']} invalid examples fail"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser(
        "check", help="write the record again (cargo test), compare, validate"
    )
    sub.add_parser("write", help="write the record (cargo test), validate")
    v = sub.add_parser("validate", help="validate a record folder (no cargo)")
    v.add_argument("folder", nargs="?", type=Path, default=FOLDER)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "validate":
            return report(*validate(args.folder))
        if args.cmd == "write":
            run_test(FOLDER)
            return report(*validate(FOLDER))
        with tempfile.TemporaryDirectory(prefix="sqll-c15-") as tmp:
            out = Path(tmp)
            run_test(out)
            problems = compare(out, FOLDER)
            more, counts = validate(out)
            return report(problems + more, counts)
    except DataError as e:
        print(f"schema check: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
