"""S3 T18: the native tests of the base, and the list check of sqll.

The base is sqlfluffrs 4.4.0 (docs/decisions/s3-base.md). Its native tests
are the Rust tests of its workspace: the unit tests and doc tests of the
crates, and the tests of the root crate (tests/, src/test_harness.rs).
sqll has a port of each of them (crates/ported.json). The S3 exit needs:
each base test that passes in the base passes in sqll.

Commands (harness Python, repository root):

    flock /tmp/sqll-machine.lock uv run --frozen --project harness python scripts/s3/base_native_tests.py record --scratch DIR
    uv run --frozen --project harness python scripts/s3/base_native_tests.py check [--log FILE]

"record" makes DIR (it must not exist) and copies the submodule into
DIR/sqlfluff (git archive), as T5 did. There it generates the dialect
tables with the pinned sqlfluff of the tool venv (utils/rustify.py build),
and stops if they are not the tables of crates/sqll_dialects/generated.json.
Then it runs CARGO_TEST_BASE in the sqlfluffrs workspace of the copy, with
the toolchain of sqlfluffrs/rust-toolchain.toml, no feature "python", and
Python commands on PATH that record each call and fail. It never builds in
the submodule. scripts/check-submodule runs before and after. Output:
RECORD_FILE (each test and its result, each command and its exit code) and
LOG_FILE (the cargo test output, stderr merged into stdout).

"check" (CI job build, scripts/verify) runs CARGO_TEST_SQLL in the
repository, or reads FILE (the output of that command, stderr merged into
stdout). It fails closed: on a cargo test failure, on output that it cannot
read, and when a base test that passes in RECORD_FILE does not exist in
sqll or does not pass there.

Exit code: 0 pass, 1 a failure or a difference, 2 a usage or setup error.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RECORD_FILE = ROOT / "results" / "s3" / "base-native-tests.json"
LOG_FILE = ROOT / "results" / "s3" / "base-native-tests.log"
MANIFEST = ROOT / "crates" / "sqll_dialects" / "generated.json"
SUBMODULE = ROOT / "third_party" / "sqlfluff"
KIND = "sqll-s3-base-native-tests"
WORKSPACE = "sqlfluffrs"
GENERATED_DIR = "sqlfluffrs/sqlfluffrs_dialects/src/dialect/"
# The packages of the base workspace that have native tests. Not tested:
# sqlfluffrs_python (Python bindings only) and sqlfluffrs_benchmarks
# (benchmarks, no tests).
BASE_PACKAGES = (
    "sqlfluffrs",
    "sqlfluffrs_types",
    "sqlfluffrs_lexer",
    "sqlfluffrs_parser",
    "sqlfluffrs_dialects",
    "sqlfluffrs_rules",
)
CARGO_TEST_BASE = ["cargo", "test", "--locked", "--offline", "--no-fail-fast"] + [
    a for p in BASE_PACKAGES for a in ("-p", p)
]
CARGO_TEST_SQLL = ["cargo", "test", "--locked", "--no-fail-fast"]
# The library name of each base crate and of its port in sqll. The root
# crate keeps its library name (crates/sqll_base_tests/Cargo.toml).
LIBRARIES = {
    "sqlfluffrs": "sqlfluffrs",
    "sqlfluffrs_types": "sqll_types",
    "sqlfluffrs_lexer": "sqll_lexer",
    "sqlfluffrs_parser": "sqll_parser",
    "sqlfluffrs_dialects": "sqll_dialects",
    "sqlfluffrs_rules": "sqll_rules",
}
PYTHON_VARS = (
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONSTARTUP",
    "VIRTUAL_ENV",
    "MATURIN_PYTHON_INTERPRETER",
    "PYO3_PYTHON",
)
PYTHON_NAMES = ("python", "python3") + tuple(f"python3.{m}" for m in range(9, 15))
SHIM_EXIT = 97
# Variables that change the cargo test output or the build.
CARGO_UNSET = (*PYTHON_VARS, "CARGO_TARGET_DIR", "RUSTFLAGS", "RUST_LOG")
# No incremental cache: the same build, with less disk use.
CARGO_SET = {"CARGO_TERM_COLOR": "never", "CARGO_INCREMENTAL": "0"}
PY_INFO = (
    "import json, sys, sqlfluff;"
    "print(json.dumps({'sqlfluff_version': sqlfluff.__version__,"
    " 'sqlfluff_file': sqlfluff.__file__, 'python': sys.version.split()[0]}))"
)
_SCRIPT = "uv run --frozen --project harness python scripts/s3/base_native_tests.py"
COMMANDS = {
    "record": f"flock /tmp/sqll-machine.lock {_SCRIPT} record --scratch $SCRATCH",
    "check": f"{_SCRIPT} check",
}

RUNNING_UNIT = re.compile(r"^\s*Running unittests (\S+) \((\S+)\)$")
RUNNING_TEST = re.compile(r"^\s*Running (\S+) \((\S+)\)$")
DOC_TESTS = re.compile(r"^\s*Doc-tests (\S+)$")
RUNNING_N = re.compile(r"^running (\d+) tests?$")
TEST_LINE = re.compile(r"^test (.+) \.\.\. (ok|FAILED|ignored(?:, .*)?)$")
RESULT_LINE = re.compile(
    r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored;"
    r" (\d+) measured; (\d+) filtered out"
)
DOC_LINE = re.compile(r" \(line \d+\)")
RESULTS = {"ok": "passed", "FAILED": "failed"}


class DataError(Exception):
    """A step failed, or the data do not agree."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def dump(data: Any) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


# The cargo test output.


def binary_name(path: str) -> str:
    """The target name of a test binary: its file name without "-<hash>"."""
    return re.sub(r"-[0-9a-f]{16}$", "", Path(path).name)


def doc_name(name: str, seen: dict[str, int]) -> str:
    """A doc test name without its line number, which the attribution header
    of a ported file changes. A second test of the same item gets "#2"."""
    key = DOC_LINE.sub("", name)
    seen[key] = seen.get(key, 0) + 1
    return key if seen[key] == 1 else f"{key} #{seen[key]}"


def parse_output(text: str) -> dict:
    """Read the output of "cargo test" (stderr merged into stdout). Return
    the units (test binaries and doc tests), the tests, and the problems:
    output that does not agree with itself."""
    units: list[dict] = []
    tests: list[dict] = []
    problems: list[str] = []
    unit: dict | None = None
    doc_seen: dict[str, int] = {}

    def close(u: dict | None) -> None:
        if u is not None and u["result"] is None:
            problems.append(f"{u['unit']}: no 'test result' line")

    for line in text.splitlines():
        m_unit = RUNNING_UNIT.match(line)
        m_test = None if m_unit else RUNNING_TEST.match(line)
        m_doc = DOC_TESTS.match(line)
        if m_unit or m_test or m_doc:
            close(unit)
            if m_unit:
                key = f"unittests {binary_name(m_unit[2])}"
            elif m_test:
                key = f"test {binary_name(m_test[2])}"
            else:
                key = f"doc {m_doc[1]}"
            if any(u["unit"] == key for u in units):
                problems.append(f"{key}: two units with this name")
            unit = {"unit": key, "line": line.strip(), "running": None, "result": None}
            units.append(unit)
            doc_seen = {}
            continue
        if unit is None:
            continue
        m = RUNNING_N.match(line)
        if m:
            unit["running"] = int(m[1])
            continue
        m = TEST_LINE.match(line)
        if m:
            name = m[1]
            if unit["unit"].startswith("doc "):
                name = doc_name(name, doc_seen)
            result = RESULTS.get(m[2], "ignored")
            tests.append({"unit": unit["unit"], "name": name, "result": result})
            continue
        m = RESULT_LINE.match(line)
        if m and unit["result"] is None:
            unit["result"] = m[1]
            unit["passed"], unit["failed"], unit["ignored"] = (
                int(m[2]),
                int(m[3]),
                int(m[4]),
            )
            unit["filtered_out"] = int(m[6])
    close(unit)

    for u in units:
        mine = [t for t in tests if t["unit"] == u["unit"]]
        if u["running"] is None:
            problems.append(f"{u['unit']}: no 'running N tests' line")
        elif u["running"] != len(mine):
            problems.append(
                f"{u['unit']}: {len(mine)} test lines, 'running {u['running']}'"
            )
        if u["result"] is not None:
            for key in ("passed", "failed", "ignored"):
                n = sum(1 for t in mine if t["result"] == key)
                if n != u[key]:
                    problems.append(
                        f"{u['unit']}: {n} {key}, the 'test result' line has {u[key]}"
                    )
            if u["filtered_out"]:
                problems.append(f"{u['unit']}: {u['filtered_out']} filtered out")
    names = [(t["unit"], t["name"]) for t in tests]
    for dup in sorted({n for n in names if names.count(n) > 1}):
        problems.append(f"{dup[0]}: two tests named {dup[1]}")
    return {"units": units, "tests": tests, "problems": problems}


def totals(tests: list[dict]) -> dict:
    out = {"tests": len(tests), "passed": 0, "failed": 0, "ignored": 0}
    for t in tests:
        out[t["result"]] += 1
    return out


def sqll_unit(unit: str) -> str | None:
    """The sqll unit of a base unit, or None if sqll has no port of it."""
    kind, name = unit.split(" ", 1)
    if kind == "test":
        return unit
    if name in LIBRARIES:
        return f"{kind} {LIBRARIES[name]}"
    return None


def compare(record: dict, sqll: dict) -> list[str]:
    """Each base test that passes in the record must exist in sqll and pass.
    Return one line for each problem. No problem only if all agree."""
    problems = list(sqll["problems"])
    if not record.get("tests"):
        problems.append("the record has no test")
    if not sqll["tests"]:
        problems.append("the sqll output has no test")
    got = {(t["unit"], t["name"]): t["result"] for t in sqll["tests"]}
    for t in record.get("tests", []):
        if t["result"] != "passed":
            continue
        unit = sqll_unit(t["unit"])
        if unit is None:
            problems.append(f"{t['unit']}: no sqll port of this unit")
            continue
        result = got.get((unit, t["name"]))
        if result is None:
            problems.append(f"{unit}: {t['name']}: not in sqll")
        elif result != "passed":
            problems.append(f"{unit}: {t['name']}: {result} in sqll")
    return problems


# record


class Steps:
    """Runs commands and records each one: the argv, the folder, the
    environment changes, the exit code, and the wall time. In the record,
    the scratch folder is $SCRATCH and the repository is $REPO."""

    def __init__(self, scratch: Path) -> None:
        self.scratch = scratch
        self.entries: list[dict] = []

    def show(self, text: str) -> str:
        return text.replace(str(self.scratch), "$SCRATCH").replace(str(ROOT), "$REPO")

    def run(
        self,
        step: str,
        argv: list,
        cwd: Path,
        *,
        set_env: dict[str, str] | None = None,
        shown_env: dict[str, str] | None = None,
        unset: tuple[str, ...] = (),
        check: bool = True,
        merge: bool = False,
    ) -> subprocess.CompletedProcess:
        argv = [str(a) for a in argv]
        env = {k: v for k, v in os.environ.items() if k not in unset}
        env.update(set_env or {})
        start = time.perf_counter()
        proc = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge else subprocess.PIPE,
            text=True,
            errors="replace",
        )
        shown = {k: self.show(v) for k, v in (set_env or {}).items()}
        shown.update(shown_env or {})
        self.entries.append(
            {
                "step": step,
                "cwd": self.show(str(cwd)),
                "argv": [self.show(a) for a in argv],
                "env": dict(sorted(shown.items())),
                "unset": sorted(unset),
                "exit_code": proc.returncode,
                "wall_s": round(time.perf_counter() - start, 3),
            }
        )
        if check and proc.returncode != 0:
            tail = ((proc.stderr or "") + (proc.stdout or ""))[-800:]
            raise DataError(f"{step}: exit code {proc.returncode}: {tail}")
        return proc


def write_shims(folder: Path, log: Path) -> None:
    """Python commands that record their call and fail."""
    folder.mkdir(parents=True)
    for name in PYTHON_NAMES:
        path = folder / name
        path.write_text(
            f'#!/bin/sh\necho "$0 $*" >> "{log}"\nexit {SHIM_EXIT}\n', encoding="utf8"
        )
        path.chmod(0o755)


def generated_files(copy: Path) -> list[dict]:
    """The generated dialect tables of the copy, in the manifest format."""
    out = []
    for path in sorted((copy / GENERATED_DIR).rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            lines = data.count(b"\n") + (0 if not data or data.endswith(b"\n") else 1)
            out.append(
                {
                    "path": path.relative_to(copy).as_posix(),
                    "bytes": len(data),
                    "lines": lines,
                    "sha256": sha256_bytes(data),
                }
            )
    return out


def record(scratch: Path, python: Path) -> dict:
    from sqll_harness import preflight
    from sqll_harness.bench import report as bench_report

    scratch = scratch.absolute()
    if scratch.exists():
        raise DataError(f"{scratch} exists; use a new folder")
    configs = preflight.parent_configs(scratch / "x")
    if configs:
        raise DataError(
            f"a sqlfluff config file is above the scratch folder: {configs}"
        )
    scratch.mkdir(parents=True)
    st = Steps(scratch)
    started = now()
    # Before the record writes LOG_FILE into the worktree.
    harness = bench_report.harness()
    st.run(
        "check the submodule before",
        [ROOT / "scripts" / "check-submodule", "before the T18 base tests"],
        ROOT,
    )
    commit = st.run(
        "submodule commit", ["git", "-C", SUBMODULE, "rev-parse", "HEAD"], ROOT
    )
    tag = st.run(
        "submodule tag",
        ["git", "-C", SUBMODULE, "describe", "--tags", "--exact-match", "HEAD"],
        ROOT,
    )
    st.run(
        "copy the submodule",
        [
            "sh",
            "-c",
            'git -C "$REPO/third_party/sqlfluff" archive --format=tar '
            '--prefix=sqlfluff/ HEAD | tar -x -C "$SCRATCH"',
        ],
        scratch,
        set_env={"SCRATCH": str(scratch), "REPO": str(ROOT)},
    )
    copy = scratch / "sqlfluff"
    workspace = copy / WORKSPACE

    info = json.loads(
        st.run(
            "python (installed sqlfluff)",
            [python, "-I", "-c", PY_INFO],
            copy,
            unset=PYTHON_VARS,
        ).stdout
    )
    if info["sqlfluff_version"] != "4.4.0" or info["sqlfluff_file"].startswith(
        str(copy)
    ):
        raise DataError(f"not the pinned sqlfluff of the tool venv: {info}")
    st.run(
        "generate the dialect tables",
        [python, "utils/rustify.py", "build"],
        copy,
        set_env={"PYTHONDONTWRITEBYTECODE": "1"},
        unset=PYTHON_VARS,
    )
    files = generated_files(copy)
    want = json.loads(MANIFEST.read_text("utf8"))["files"]
    if files != want:
        raise DataError("the generated tables are not those of generated.json")

    channel = tomllib.loads((workspace / "rust-toolchain.toml").read_text("utf8"))[
        "toolchain"
    ]["channel"]
    shims = scratch / "no-python" / "bin"
    shim_log = scratch / "no-python" / "calls.log"
    write_shims(shims, shim_log)
    cargo_env = {
        **CARGO_SET,
        "RUSTUP_TOOLCHAIN": channel,
        "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}",
    }
    shown = {"PATH": "$SCRATCH/no-python/bin:$PATH"}

    def cargo(step: str, argv: list, **kw) -> subprocess.CompletedProcess:
        return st.run(
            step,
            argv,
            workspace,
            set_env=cargo_env,
            shown_env=shown,
            unset=CARGO_UNSET,
            **kw,
        )

    st.run(
        "install the toolchain",
        ["rustup", "toolchain", "install", channel, "--profile", "minimal"],
        scratch,
    )
    rustc = cargo("rustc version", ["rustc", "-vV"]).stdout.strip().splitlines()
    cargo_version = cargo("cargo version", ["cargo", "-V"]).stdout.strip()
    cargo("fetch the crates", ["cargo", "fetch", "--locked"])
    tree = cargo(
        "cargo tree of the tested packages",
        ["cargo", "tree", "--locked", "--offline", "-e", "normal,build,dev"]
        + ["--prefix", "none"]
        + [a for p in BASE_PACKAGES for a in ("-p", p)],
    ).stdout
    packages = sorted({ln.split()[0] for ln in tree.splitlines() if ln.strip()})
    if "pyo3" in packages or "sqlfluffrs_python" in packages:
        raise DataError("the tested packages need pyo3")
    test = cargo("cargo test of the base", CARGO_TEST_BASE, check=False, merge=True)
    log = st.show(test.stdout)
    parsed = parse_output(log)
    calls = shim_log.read_text("utf8").splitlines() if shim_log.exists() else []
    if calls:
        raise DataError(f"a Python call during cargo: {calls}")
    st.run(
        "check the submodule after",
        [ROOT / "scripts" / "check-submodule", "after the T18 base tests"],
        ROOT,
    )
    LOG_FILE.write_text(log, encoding="utf8")
    if parsed["problems"]:
        raise DataError(f"the cargo test output: {parsed['problems']}")
    units = [
        {
            "unit": u["unit"],
            "line": u["line"],
            "result": u["result"],
            "tests": u["running"],
            "sqll_unit": sqll_unit(u["unit"]),
        }
        for u in parsed["units"]
    ]
    return {
        "kind": KIND,
        "about": "The native tests of the base (sqlfluffrs 4.4.0) and their"
        " results: cargo test of its workspace, without the feature"
        ' "python". The check of sqll: scripts/s3/base_native_tests.py check.',
        "command": COMMANDS["record"],
        "started": started,
        "finished": now(),
        "machine": bench_report.machine(),
        "harness": harness,
        "base": {
            "submodule": "third_party/sqlfluff",
            "commit": commit.stdout.strip(),
            "tag": tag.stdout.strip(),
            "workspace": WORKSPACE,
            "packages": list(BASE_PACKAGES),
            "not_tested": {
                "sqlfluffrs_python": "Python bindings (pyo3); no tests",
                "sqlfluffrs_benchmarks": "benchmarks; no tests",
            },
            "features": 'the defaults (no feature "python")',
        },
        "toolchain": {
            "channel": channel,
            "source": "sqlfluffrs/rust-toolchain.toml",
            "rustc": rustc,
            "cargo": cargo_version,
        },
        "generation": {
            "python": {**info, "sqlfluff_file": st.show(info["sqlfluff_file"])},
            "files": len(files),
            "equal_to": "crates/sqll_dialects/generated.json",
        },
        "python_shim_calls": calls,
        "cargo_tree_packages": len(packages),
        "cargo_test": {
            "argv": CARGO_TEST_BASE,
            "exit_code": test.returncode,
            "log": LOG_FILE.relative_to(ROOT).as_posix(),
            "log_sha256": sha256_bytes(log.encode("utf8")),
        },
        "totals": totals(parsed["tests"]),
        "units": units,
        "tests": parsed["tests"],
        "steps": st.entries,
    }


# check


def run_sqll_tests() -> tuple[int, str]:
    """Run CARGO_TEST_SQLL in the repository. Print the output as it comes,
    and return the exit code and the output."""
    env = {
        k: v for k, v in os.environ.items() if k not in ("RUST_LOG", "CARGO_TERM_COLOR")
    }
    env["CARGO_TERM_COLOR"] = "never"
    print("$ " + " ".join(CARGO_TEST_SQLL), flush=True)
    proc = subprocess.Popen(
        CARGO_TEST_SQLL,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    lines = []
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        lines.append(line)
    sys.stdout.flush()
    return proc.wait(), "".join(lines)


def check(log: Path | None) -> int:
    rec = json.loads(RECORD_FILE.read_text("utf8"))
    if rec.get("kind") != KIND:
        raise DataError(f"{RECORD_FILE} is not a {KIND} record")
    if log is None:
        code, text = run_sqll_tests()
    else:
        code, text = 0, log.read_text("utf8")
    sqll = parse_output(text)
    problems = compare(rec, sqll)
    if code != 0:
        problems.insert(0, f"cargo test: exit code {code}")
    base_passed = sum(1 for t in rec["tests"] if t["result"] == "passed")
    t = totals(sqll["tests"])
    for p in problems:
        print(f"base native tests: {p}")
    status = "FAIL" if problems else "PASS"
    print(
        f"base native tests: {status}: {base_passed} base tests pass in the base;"
        f" sqll: {t['tests']} tests, {t['passed']} passed, {t['failed']} failed,"
        f" {t['ignored']} ignored; {len(problems)} problems"
    )
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="run the base tests in a scratch copy")
    rec.add_argument("--scratch", type=Path, required=True)
    chk = sub.add_parser("check", help="run the sqll tests and compare")
    chk.add_argument("--log", type=Path, help="read this cargo test output")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "record":
            from sqll_harness.paths import tools_dir

            python = tools_dir() / "sqlfluff" / "bin" / "python"
            data = record(args.scratch, python)
            RECORD_FILE.write_text(dump(data), encoding="utf8")
            tot = data["totals"]
            print(
                f"base native tests: {tot['tests']} tests, {tot['passed']} passed,"
                f" {tot['failed']} failed, {tot['ignored']} ignored;"
                f" cargo test exit code {data['cargo_test']['exit_code']}"
            )
            return 0
        return check(args.log)
    except (DataError, OSError, ValueError, KeyError) as e:
        print(f"base native tests: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
