"""S3 T14: the S2 tree guard of the parse speed work.

A speed change must not change a tree (CONSTITUTION.md, "Conflicts"). The
guard runs sqll on each of the 84 S2 parse inputs (harness/bench.md,
"Inputs"), with no option and with -m (the meta segments), and compares the
stdout (sha256 and size), the stderr, and the exit code with RECORD_FILE.
The record is the output of the sqll of the T11 port with no engine change
(the binary of commit REFERENCE_COMMIT). Thus a change of a tree, of a
meta segment, or of the JSON output fails the guard.

Commands (run them with the harness Python from the repository root):

    uv run --frozen --project harness python scripts/s3/tree_guard.py check [--binary B]
    uv run --frozen --project harness python scripts/s3/tree_guard.py record --binary B

"check" (CI job build, scripts/verify) fails if the binary is not a fresh
build of the worktree (sqll-harness tools), if the inputs are not those of
the S2 definitions, or if an input is missing, extra, or different. The
default binary is out/sqll/bin/sqll (SQLL_BIN). "record" writes RECORD_FILE
with the output of B. It also runs sqlfluff 4.4.0 (the tool venv) on each
input and records where the sqll output equals the sqlfluff output: with no
option, the stdout bytes and the exit code; with -m, the tree after the
position keys of sqlfluff are removed (process_struct of the sqlfluff
test). A change of RECORD_FILE needs a reason in the pull request: it
changes what the guard protects.

Exit code: 0 pass, 1 a difference, 2 a usage or setup error.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqll_harness import tools
from sqll_harness.adapters import sqll as sqll_adapter
from sqll_harness.adapters.base import EmptyHome, isolated_env
from sqll_harness.bench import definitions as bench_definitions
from sqll_harness.bench import run as bench_run
from sqll_harness.bench.inputs import SIZES
from sqll_harness.compare import record_to_tuple, strip_positions
from sqll_harness.paths import SQLFLUFF_ROOT, sqlfluff_ref, tools_dir

ROOT = Path(__file__).resolve().parents[2]
RECORD_FILE = ROOT / "results" / "s3" / "tree-guard.json"
KIND = "sqll-s3-tree-guard"
# The T11 port with no engine change: main after T13 (PR #47).
REFERENCE_COMMIT = "1a2219c4d8bfd3df8db76ef885183f2f7782fdf8"
RUNS = {"default": [], "meta": ["-m"]}
PARSE_INPUTS = 84
TIMEOUT_S = 120
SQLFLUFF_ARGS = ["parse", "-f", "json", "--templater", "raw", "--ignore-local-config"]


class GuardError(Exception):
    """The guard cannot run: a setup or input error."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(data: Any) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def sqll_argv(binary: Path, dialect: str, sql: str, run: str) -> list[str]:
    return [str(binary), "parse", "-f", "json", *RUNS[run], "--dialect", dialect, sql]


def build_inputs(folder: Path) -> dict[str, str]:
    """Build the S2 inputs into folder (checked with the definitions).
    Return the sha256 of each parse input ("<dialect>/<size>")."""
    defs = bench_definitions.load()
    try:
        bench_run.build_inputs(SQLFLUFF_ROOT, defs, folder)
    except bench_run.RunError as exc:
        raise GuardError(str(exc)) from None
    names = sorted(name for name in defs["inputs"] if name.split("/")[-1] in SIZES)
    out = {name: sha256((folder / f"{name}.sql").read_bytes()) for name in names}
    if len(out) != PARSE_INPUTS:
        raise GuardError(f"{len(out)} parse inputs, not {PARSE_INPUTS}")
    return out


def run_one(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        env=isolated_env(EmptyHome.path()),
        timeout=TIMEOUT_S,
    )


def output_record(proc: subprocess.CompletedProcess) -> dict:
    return {
        "exit_code": proc.returncode,
        "stdout_sha256": sha256(proc.stdout),
        "stdout_bytes": len(proc.stdout),
        "stderr": proc.stderr.decode("utf8", "replace"),
    }


def observe(
    binary: Path, folder: Path, inputs: dict[str, str]
) -> tuple[dict[str, dict], dict[tuple[str, str], bytes]]:
    """Run the binary on each input with each run. Return the record of each
    input and the stdout of each (input, run)."""
    records, stdouts = {}, {}
    for name, digest in inputs.items():
        dialect = name.split("/")[0]
        entry = {"sha256": digest}
        for run in RUNS:
            proc = run_one(sqll_argv(binary, dialect, f"{name}.sql", run), folder)
            entry[run] = output_record(proc)
            stdouts[(name, run)] = proc.stdout
        records[name] = entry
    return records, stdouts


def compare(record: dict, observed: dict[str, dict]) -> list[str]:
    """Return each difference between the record and the observed outputs."""
    errors = []
    want = record.get("inputs", {})
    if record.get("kind") != KIND:
        errors.append(f"the record kind is not {KIND}")
    if len(want) != PARSE_INPUTS:
        errors.append(f"the record has {len(want)} inputs, not {PARSE_INPUTS}")
    for name in sorted(set(want) - set(observed)):
        errors.append(f"{name}: in the record, but not an input")
    for name in sorted(set(observed) - set(want)):
        errors.append(f"{name}: an input, but not in the record")
    for name in sorted(set(want) & set(observed)):
        w, o = want[name], observed[name]
        if w["sha256"] != o["sha256"]:
            errors.append(f"{name}: the input is not the input of the record")
            continue
        for run in RUNS:
            for key in ("exit_code", "stdout_sha256", "stdout_bytes", "stderr"):
                if w[run][key] != o[run][key]:
                    errors.append(
                        f"{name} ({run}): {key} is {o[run][key]!r}, "
                        f"the record has {w[run][key]!r}"
                    )
    return errors


def guard(binary: Path, record: dict, folder: Path) -> list[str]:
    inputs = build_inputs(folder)
    observed, _ = observe(binary, folder, inputs)
    return compare(record, observed)


# record


def sqlfluff_tree(stdout: bytes) -> Any:
    return record_to_tuple(strip_positions(json.loads(stdout)[0]["segments"]))


def sqlfluff_equality(
    python: Path,
    folder: Path,
    inputs: dict[str, str],
    stdouts: dict[tuple[str, str], bytes],
    records: dict[str, dict],
    runner: Callable[[list[str], Path], subprocess.CompletedProcess] = run_one,
) -> dict:
    """Run sqlfluff on each input and add where sqll gives the same output."""
    sqlfluff = str(python.parent / "sqlfluff")
    not_equal = {"default": [], "meta": []}
    for name in inputs:
        dialect = name.split("/")[0]
        sql = f"{name}.sql"
        plain = runner([sqlfluff, *SQLFLUFF_ARGS, "--dialect", dialect, sql], folder)
        meta = runner(
            [sqlfluff, *SQLFLUFF_ARGS, "-m", "--dialect", dialect, sql], folder
        )
        rec = records[name]
        default_equal = (
            plain.stdout == stdouts[(name, "default")]
            and plain.returncode == rec["default"]["exit_code"]
        )
        meta_equal = meta.returncode == rec["meta"]["exit_code"] and sqlfluff_tree(
            meta.stdout
        ) == record_to_tuple(json.loads(stdouts[(name, "meta")])[0]["segments"])
        rec["sqlfluff"] = {
            "default_equal": default_equal,
            "meta_tree_equal": meta_equal,
        }
        if not default_equal:
            not_equal["default"].append(name)
        if not meta_equal:
            not_equal["meta"].append(name)
    version = subprocess.run(
        [sqlfluff, "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return {
        "version": version,
        "argv": [
            ["sqlfluff", *SQLFLUFF_ARGS, "--dialect", "D", "DIALECT/SIZE.sql"],
            ["sqlfluff", *SQLFLUFF_ARGS, "-m", "--dialect", "D", "DIALECT/SIZE.sql"],
        ],
        "compare": {
            "default": "the stdout bytes and the exit code",
            "meta": "the exit code, and the tree (process_struct of the sqlfluff "
            "test) after the position keys of sqlfluff are removed",
        },
        "default_equal": len(inputs) - len(not_equal["default"]),
        "meta_tree_equal": len(inputs) - len(not_equal["meta"]),
        "not_equal": not_equal,
    }


def make_record(binary: Path, folder: Path, python: Path) -> dict:
    build = json.loads(
        subprocess.run(
            [str(binary), "version", "--build"], capture_output=True, check=True
        ).stdout
    )
    inputs = build_inputs(folder)
    records, stdouts = observe(binary, folder, inputs)
    sqlfluff = sqlfluff_equality(python, folder, inputs, stdouts, records)
    exits = {r: sum(rec[r]["exit_code"] == 0 for rec in records.values()) for r in RUNS}
    return {
        "kind": KIND,
        "format": 1,
        "task": "T14",
        "about": "The sqll output of each S2 parse input. scripts/s3/tree_guard.py "
        "check compares a build with it (CI job build).",
        "sqlfluff_ref": sqlfluff_ref(SQLFLUFF_ROOT),
        "reference": {
            "commit": REFERENCE_COMMIT,
            "what": "the sqll binary of the T11 port with no engine change "
            "(scripts/build-sqll at the commit)",
            "version": build["version"],
            "source_sha256": build["source_sha256"],
            "binary_sha256": sha256(binary.read_bytes()),
        },
        "argv": {
            run: [
                "sqll",
                "parse",
                "-f",
                "json",
                *args,
                "--dialect",
                "D",
                "DIALECT/SIZE.sql",
            ]
            for run, args in RUNS.items()
        },
        "summary": {
            "inputs": len(records),
            "exit_code_0": exits,
            "sqlfluff_default_equal": sqlfluff["default_equal"],
            "sqlfluff_meta_tree_equal": sqlfluff["meta_tree_equal"],
        },
        "sqlfluff": sqlfluff,
        "inputs": records,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tree_guard.py")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="Compare a fresh sqll build with the record.")
    c.add_argument("--binary", type=Path, default=None)
    r = sub.add_parser("record", help="Write the record with the output of a binary.")
    r.add_argument("--binary", type=Path, required=True)
    r.add_argument(
        "--python",
        type=Path,
        default=None,
        help="The Python of sqlfluff 4.4.0 (default: the sqlfluff tool venv).",
    )
    args = p.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="sqll-tree-guard-") as tmp:
            folder = Path(tmp) / "inputs"
            if args.command == "record":
                python = args.python or tools_dir() / "sqlfluff" / "bin" / "python"
                record = make_record(args.binary.resolve(), folder, python)
                RECORD_FILE.write_text(dump(record), encoding="utf8")
                print(f"wrote {RECORD_FILE.relative_to(ROOT)}: {record['summary']}")
                return 0
            binary = (args.binary or sqll_adapter.binary_path()).resolve()
            info = tools.check_sqll(ROOT, ROOT, binary=binary)
            if info.errors:
                raise GuardError("; ".join(info.errors))
            record = json.loads(RECORD_FILE.read_text("utf8"))
            errors = guard(binary, record, folder)
    except GuardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if errors:
        print(f"tree guard: {len(errors)} differences", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    print(
        f"tree guard: {PARSE_INPUTS} of {PARSE_INPUTS} inputs, {len(RUNS)} runs each: same output as the record"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
