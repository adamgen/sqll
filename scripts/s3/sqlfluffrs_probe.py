"""S3 phase A, task T5: the sqlfluffrs standalone probe (criterion C4 of
docs/decisions/s3-base.md).

The probe (scripts/s3/probe-sqlfluffrs/) is research code, not sqll. It
lexes and parses one file with the sqlfluffrs 4.4.0 crates, with no
Python, and prints the parse record as "sqlfluff parse -f json" does.

Commands. Run them on the host with the harness Python. The build and the
timing session take the machine lock (PROCESS.md, rule 7):

    flock /tmp/sqll-machine.lock uv run --frozen --project harness python scripts/s3/sqlfluffrs_probe.py build --scratch DIR
    uv run --frozen --project harness python scripts/s3/sqlfluffrs_probe.py fixtures --scratch DIR
    flock /tmp/sqll-machine.lock uv run --frozen --project harness python scripts/s3/sqlfluffrs_probe.py time --scratch DIR
    uv run --frozen --project harness python scripts/s3/sqlfluffrs_probe.py report [--check]

"build" makes DIR (it must not exist) and copies the submodule into
DIR/sqlfluff (git archive). There it generates the dialect tables with the
pinned sqlfluff (utils/rustify.py build), builds the lexer, parser,
dialects, and rules crates and the probe with no Python on PATH, and runs
the native fixture tests (tests/fixture_tests.rs). It never builds in the
submodule: the build script of sqlfluffrs_dialects writes generated files
into its source tree. Needs git, rustup, cargo, ldd, readelf, and docker.
Output: BUILD_FILE.
"fixtures" runs the probe on each dialect fixture case and compares the
tree with the harness compare code. Output: CASES_FILE.
"time" runs the start and parse benchmarks of the probe, sqlfluff, and
sqruff in one session: the CI image in docker, serial, with the harness
timer and validity checks (harness/bench.md). Output: BENCH_FILE.
"report" reads only the committed files and the pinned submodule, and
writes OUT_FILE. With --check it writes nothing and fails if OUT_FILE is
not the new text.

Each command stops with exit code 1 if a step fails or the data do not
agree (DataError).
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import tomllib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqll_harness import preflight
from sqll_harness.adapters.base import EmptyHome, isolated_env
from sqll_harness.bench import definitions as bench_definitions
from sqll_harness.bench import report as bench_report
from sqll_harness.bench import run as bench_run
from sqll_harness.bench.adapter import PARSE, BenchAdapter
from sqll_harness.bench.inputs import START
from sqll_harness.bench.timer import VALID
from sqll_harness.code_only import code_only_record, sqlfluff_record
from sqll_harness.compare import has_node, load_yaml, record_to_tuple, trees_match
from sqll_harness.paths import SQLFLUFF_ROOT, sqlfluff_ref, tools_dir
from sqll_harness.suites import dialects

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_a  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "s3"
BUILD_FILE = RESULTS / "sqlfluffrs-probe-build.json"
CASES_FILE = RESULTS / "sqlfluffrs-probe-cases.json"
BENCH_FILE = RESULTS / "sqlfluffrs-probe-bench.json"
OUT_FILE = RESULTS / "sqlfluffrs-probe.json"
BASELINE_FILE = phase_a.read_path("results/s2/baseline.json")
PROBE_SRC = ROOT / "scripts" / "s3" / "probe-sqlfluffrs"
PROBE = "probe-sqlfluffrs"
PROBE_FILES = ("Cargo.toml", "Cargo.lock", "src/main.rs")
WORKSPACE = "sqlfluffrs"
CRATES = (
    "sqlfluffrs_lexer",
    "sqlfluffrs_parser",
    "sqlfluffrs_dialects",
    "sqlfluffrs_rules",
)
# The crate folders of the workspace. "sqlfluffrs" is the root crate.
CRATE_DIRS = {
    "sqlfluffrs": ".",
    "sqlfluffrs_types": "sqlfluffrs_types",
    "sqlfluffrs_dialects": "sqlfluffrs_dialects",
    "sqlfluffrs_lexer": "sqlfluffrs_lexer",
    "sqlfluffrs_parser": "sqlfluffrs_parser",
    "sqlfluffrs_rules": "sqlfluffrs_rules",
    "sqlfluffrs_python": "sqlfluffrs_python",
    "sqlfluffrs_benchmarks": "sqlfluffrs_benchmarks",
}
GENERATED_DIR = "sqlfluffrs/sqlfluffrs_dialects/src/dialect"
GENERATOR_SCRIPTS = (
    "utils/rustify.py",
    "utils/build_dialect.py",
    "utils/build_dialects.py",
    "utils/build_lexers.py",
    "utils/build_parsers.py",
)
# The interpreter names that sqlfluffrs_dialects/build.rs tries.
PYTHON_NAMES = ("python", "python3") + tuple(f"python3.{m}" for m in range(9, 15))
PYTHON_VARS = (
    "PYTHONPATH",
    "PYTHONHOME",
    "VIRTUAL_ENV",
    "MATURIN_PYTHON_INTERPRETER",
    "PYO3_PYTHON",
)
SHIM_EXIT = 97
DOCKERFILE = ROOT / "ci" / "Dockerfile"
SELECT_1 = "SELECT 1;\n"
SELECT_1_TREE = {
    "file": {
        "statement": {
            "select_statement": {
                "select_clause": {
                    "keyword": "SELECT",
                    "whitespace": " ",
                    "select_clause_element": {"numeric_literal": "1"},
                }
            }
        },
        "statement_terminator": ";",
        "newline": "\n",
    }
}
BENCH_COMMANDS = (START, PARSE)
PHASE_RUNS = 5
IDLE_LOAD = 0.3
MAX_SESSION_LOAD = 1.5
PHASES = ("setup_s", "lex_s", "parse_s", "record_s", "write_s")
BENCH_TOOLS = (PROBE, "sqlfluff", "sqruff")
DIFF_TEXT = 160
FIXTURE_TEST_RE = re.compile(r"^test_(\w+)_fixtures$")
YAML_TEST_RE = re.compile(r"^test_yaml_output_matches_python_(\w+)$")

_SCRIPT = "uv run --frozen --project harness python scripts/s3/sqlfluffrs_probe.py"
# The machine lock (PROCESS.md, rule 7): the build and the timing session
# measure time.
COMMANDS = {
    "build": f"flock /tmp/sqll-machine.lock {_SCRIPT} build",
    "fixtures": f"{_SCRIPT} fixtures",
    "time": f"flock /tmp/sqll-machine.lock {_SCRIPT} time",
    "report": f"{_SCRIPT} report",
}


class DataError(Exception):
    """A step failed, or the data do not agree."""


def rel(path: Path) -> str:
    """The path from the repository root, or the path if it is outside."""
    if path.is_relative_to(ROOT):
        return phase_a.name_of(path.relative_to(ROOT).as_posix())
    return str(path)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def dump(data: Any) -> str:
    return json.dumps(data, indent=1, sort_keys=False, ensure_ascii=False) + "\n"


def line_count(data: bytes) -> int:
    """The lines of a text: the newlines, and 1 more for a last line with
    no newline."""
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


# Commands and their record.


class Steps:
    """Runs the commands of a command and records each one: the argv, the
    folder, the environment changes, the exit code, and the wall time. In
    the record, the scratch folder is $SCRATCH and the repository is $REPO,
    so that a reviewer can repeat each command."""

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
        log: Path | None = None,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess:
        argv = [str(a) for a in argv]
        env = {k: v for k, v in os.environ.items() if k not in unset}
        env.update(set_env or {})
        start = time.perf_counter()
        proc = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
        wall = round(time.perf_counter() - start, 3)
        shown = {k: self.show(v) for k, v in (set_env or {}).items()}
        shown.update(shown_env or {})
        entry = {
            "step": step,
            "cwd": self.show(str(cwd)),
            "argv": [self.show(a) for a in argv],
            "env": dict(sorted(shown.items())),
            "unset": sorted(unset),
            "exit_code": proc.returncode,
            "wall_s": wall,
        }
        if log is not None:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(
                f"$ {' '.join(argv)}\n--- stdout ---\n{proc.stdout}"
                f"--- stderr ---\n{proc.stderr}",
                encoding="utf8",
            )
            entry["log"] = self.show(str(log))
        self.entries.append(entry)
        if check and proc.returncode != 0:
            tail = (proc.stderr or proc.stdout)[-600:]
            raise DataError(f"{step}: exit code {proc.returncode}: {tail}")
        return proc


# build


PY_INFO = (
    "import json, sys, sqlfluff;"
    "print(json.dumps({'sqlfluff_version': sqlfluff.__version__,"
    " 'sqlfluff_file': sqlfluff.__file__, 'python': sys.version.split()[0]}))"
)


def rust_image() -> str:
    """The pinned RUST_IMAGE of ci/Dockerfile: Debian trixie with no Python."""
    m = re.search(r"^ARG RUST_IMAGE=(\S+)$", DOCKERFILE.read_text("utf8"), re.MULTILINE)
    if not m:
        raise DataError("ci/Dockerfile has no RUST_IMAGE")
    return m[1]


def ci_image() -> str:
    """The local tag of the CI image of this commit: sqll-ci:<ci/image_tag.py>."""
    tag = subprocess.run(
        [sys.executable, str(ROOT / "ci" / "image_tag.py")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return f"sqll-ci:{tag}"


def write_shims(folder: Path, log: Path) -> None:
    """Python commands that record their call and fail. With them first on
    PATH, a build that calls Python fails, and the log shows the call."""
    folder.mkdir(parents=True)
    for name in PYTHON_NAMES:
        path = folder / name
        path.write_text(
            f'#!/bin/sh\necho "$0 $*" >> "{log}"\nexit {SHIM_EXIT}\n', encoding="utf8"
        )
        path.chmod(0o755)


def tree_packages(text: str) -> list[str]:
    """The package names of "cargo tree --prefix none" output."""
    names = set()
    for line in text.splitlines():
        parts = line.split()
        if parts and not line.startswith(("[", "warning", "error")):
            names.add(parts[0])
    return sorted(names)


def needed_libraries(readelf: str) -> list[str]:
    return sorted(re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", readelf))


def ldd_libraries(ldd: str) -> list[str]:
    names = []
    for line in ldd.splitlines():
        line = line.strip()
        if line:
            names.append(line.split()[0])
    return sorted(names)


def tracked_files(repo: Path) -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        capture_output=True,
        check=True,
    ).stdout
    return {p for p in out.decode("utf8").split("\0") if p}


def generated_files(copy: Path, tracked: set[str]) -> list[dict]:
    """The files of the copy that the submodule does not track. All must be
    in GENERATED_DIR."""
    out = []
    for path in sorted(copy.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(copy).as_posix()
        if rel in tracked:
            continue
        if not rel.startswith(GENERATED_DIR + "/"):
            raise DataError(f"an untracked file outside {GENERATED_DIR}: {rel}")
        data = path.read_bytes()
        entry = {
            "path": rel,
            "lines": line_count(data),
            "bytes": len(data),
            "sha256": sha256_bytes(data),
        }
        m = re.search(rb"^//\s+Instructions:\s+(\d+)", data, re.MULTILINE)
        if m:
            entry["grammar_instructions"] = int(m[1])
        out.append(entry)
    return out


def rust_lines(workspace: Path, tracked: set[str]) -> dict:
    """For each crate folder: the files and lines of the hand-written
    (tracked) and generated (not tracked) .rs files, by part (src, tests,
    benches, build.rs). The root crate has only its own src, tests, and
    benches."""
    out = {}
    for crate, rel in CRATE_DIRS.items():
        base = workspace / rel
        parts: dict[str, dict] = {}
        for path in sorted(base.rglob("*.rs")):
            rel_crate = path.relative_to(base).as_posix()
            if "target/" in rel_crate or rel_crate.startswith("target"):
                continue
            first = rel_crate.split("/", 1)[0]
            if crate == "sqlfluffrs" and first not in ("src", "tests", "benches"):
                continue
            part = first if first in ("src", "tests", "benches") else rel_crate
            rel_sub = path.relative_to(workspace.parent).as_posix()
            kind = "hand_written" if rel_sub in tracked else "generated"
            data = path.read_bytes()
            slot = parts.setdefault(kind, {}).setdefault(part, {"files": 0, "lines": 0})
            slot["files"] += 1
            slot["lines"] += line_count(data)
        totals = {
            kind: {
                "files": sum(p["files"] for p in by_part.values()),
                "lines": sum(p["lines"] for p in by_part.values()),
                "by_part": dict(sorted(by_part.items())),
            }
            for kind, by_part in sorted(parts.items())
        }
        for kind in ("hand_written", "generated"):
            totals.setdefault(kind, {"files": 0, "lines": 0, "by_part": {}})
        out[crate] = totals
    return out


def fixture_counts(sqlfluff_root: Path) -> dict[str, int]:
    """The fixtures that tests/fixture_tests.rs reads for each dialect: each
    .sql file with a .yml file of the same name."""
    base = sqlfluff_root / dialects.FIXTURE_DIR
    out = {}
    for d in sorted(os.listdir(base)):
        if not (base / d).is_dir():
            continue
        names = set(os.listdir(base / d))
        out[d] = sum(
            1 for n in names if n.endswith(".sql") and n[:-4] + ".yml" in names
        )
    return out


def parse_fixture_tests(stdout: str, stderr: str) -> dict:
    """Read the output of "cargo test --test fixture_tests -- --nocapture
    --test-threads 1"."""
    # With one test thread, the output of a test comes after its
    # "test NAME ... " line and before the next one.
    markers = list(re.finditer(r"^test (\w+) \.\.\. ?", stdout, re.MULTILINE))
    sections = {
        m[1]: stdout[
            m.end() : (markers[i + 1].start() if i + 1 < len(markers) else len(stdout))
        ]
        for i, m in enumerate(markers)
    }
    results: dict[str, str | None] = {name: None for name in sections}
    summary = re.search(
        r"^test result: (\w+)\. (\d+) passed; (\d+) failed; (\d+) ignored",
        stdout,
        re.MULTILINE,
    )
    if not summary:
        raise DataError("no 'test result' line in the fixture test output")
    failed = set()
    block = re.search(r"^failures:\n((?:    \S+\n)+)", stdout, re.MULTILINE)
    if block:
        failed = {line.strip() for line in block[1].splitlines()}
    for name in results:
        results[name] = "failed" if name in failed else "passed"
    if Counter(results.values())["failed"] != int(summary[3]):
        raise DataError("the failed tests do not agree with the 'test result' line")
    if Counter(results.values())["passed"] != int(summary[2]):
        raise DataError("the passed tests do not agree with the 'test result' line")
    yaml_counts = {}
    yaml_failed: dict[str, list[str]] = {}
    parse_counts = {}
    for name, text in sections.items():
        y = YAML_TEST_RE.match(name)
        f = FIXTURE_TEST_RE.match(name)
        if y:
            m = re.search(
                r"^YAML output comparison for dialect '(\w+)': (\d+) total, (\d+) failed",
                text,
                re.MULTILINE,
            )
            if m:
                yaml_counts[y[1]] = {"total": int(m[2]), "failed": int(m[3])}
            m = re.search(
                r"^Failed tests for dialect '\w+':\n((?:  \S+\n)+)", text, re.MULTILINE
            )
            if m:
                yaml_failed[y[1]] = [line.strip() for line in m[1].splitlines()]
        elif f:
            found = re.search(r"^Found (\d+) \w+ fixture tests", text, re.MULTILINE)
            res = re.search(r"^Results: (\d+) passed, (\d+) failed", text, re.MULTILINE)
            if found and res:
                parse_counts[f[1]] = {
                    "found": int(found[1]),
                    "passed": int(res[1]),
                    "failed": int(res[2]),
                }
    panics = {
        m[1]: m[2].strip()
        for m in re.finditer(
            r"^thread '(\w+)'(?: \(\d+\))? panicked at [^\n]*:\n([^\n]*)",
            stderr,
            re.MULTILINE,
        )
    }
    return {
        "result": summary[1],
        "passed": int(summary[2]),
        "failed": int(summary[3]),
        "ignored": int(summary[4]),
        "tests": dict(sorted(results.items())),
        "yaml_counts": dict(sorted(yaml_counts.items())),
        "yaml_failed": dict(sorted(yaml_failed.items())),
        "parse_counts": dict(sorted(parse_counts.items())),
        "panics": dict(sorted(panics.items())),
    }


def build(scratch: Path, python: Path) -> dict:
    scratch = scratch.absolute()
    if scratch.exists():
        raise DataError(f"{scratch} exists; use a new folder")
    configs = preflight.parent_configs(scratch / "x")
    if configs:
        raise DataError(
            f"a sqlfluff config file is above the scratch folder: {configs}"
        )
    load_before, waited = wait_idle()
    scratch.mkdir(parents=True)
    st = Steps(scratch)
    started = now()
    st.run(
        "check the submodule before",
        [ROOT / "scripts" / "check-submodule", "before the T5 build"],
        ROOT,
    )
    sub = SQLFLUFF_ROOT
    commit = st.run("submodule commit", ["git", "-C", sub, "rev-parse", "HEAD"], ROOT)
    tag = st.run(
        "submodule tag",
        ["git", "-C", sub, "describe", "--tags", "--exact-match", "HEAD"],
        ROOT,
    )
    paths_env = {"SCRATCH": str(scratch), "REPO": str(ROOT)}
    st.run(
        "copy the submodule",
        [
            "sh",
            "-c",
            'git -C "$REPO/third_party/sqlfluff" archive --format=tar '
            '--prefix=sqlfluff/ HEAD | tar -x -C "$SCRATCH"',
        ],
        scratch,
        set_env=paths_env,
    )
    copy = scratch / "sqlfluff"
    workspace = copy / WORKSPACE
    tracked = tracked_files(sub)
    copied = {p.relative_to(copy).as_posix() for p in copy.rglob("*") if p.is_file()}
    if copied != tracked:
        raise DataError("the copy does not have the tracked files of the submodule")

    # Generation: the pinned sqlfluff (the tool venv), not the copy's src.
    gen_python = {
        "installed": json.loads(
            st.run(
                "python (installed sqlfluff)",
                [python, "-c", PY_INFO],
                copy,
                unset=PYTHON_VARS,
            ).stdout
        )
    }
    st.run(
        "generate the dialect tables",
        [python, "utils/rustify.py", "build"],
        copy,
        unset=PYTHON_VARS,
        log=scratch / "logs" / "generate.log",
    )
    generated = generated_files(copy, tracked)
    st.run(
        "check the generation (installed sqlfluff)",
        [python, "utils/rustify.py", "check"],
        copy,
        unset=PYTHON_VARS,
        log=scratch / "logs" / "generate-check.log",
    )
    src_env = {"PYTHONPATH": str(copy / "src")}
    gen_python["submodule_src"] = json.loads(
        st.run(
            "python (submodule src)", [python, "-c", PY_INFO], copy, set_env=src_env
        ).stdout
    )
    st.run(
        "check the generation (submodule src)",
        [python, "utils/rustify.py", "check"],
        copy,
        set_env=src_env,
        log=scratch / "logs" / "generate-check-src.log",
    )
    if not gen_python["submodule_src"]["sqlfluff_file"].startswith(str(copy / "src")):
        raise DataError("PYTHONPATH did not select the src of the copy")
    if gen_python["installed"]["sqlfluff_file"].startswith(str(copy)):
        raise DataError(
            "the generation used the src of the copy, not the pinned package"
        )
    for info in gen_python.values():
        info["sqlfluff_file"] = st.show(info["sqlfluff_file"])
    gen_python["installed"]["python_binary"] = st.show(str(python))

    # The Rust build: the toolchain of rust-toolchain.toml, no Python on PATH.
    channel = tomllib.loads((workspace / "rust-toolchain.toml").read_text("utf8"))[
        "toolchain"
    ]["channel"]
    shims = scratch / "no-python" / "bin"
    shim_log = scratch / "no-python" / "calls.log"
    write_shims(shims, shim_log)
    cargo_env = {
        "RUSTUP_TOOLCHAIN": channel,
        "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}",
    }
    cargo_shown = {"PATH": "$SCRATCH/no-python/bin:$PATH"}
    cargo_unset = (*PYTHON_VARS, "CARGO_TARGET_DIR", "RUSTFLAGS")

    def cargo(step, argv, cwd, **kw):
        return st.run(
            step,
            argv,
            cwd,
            set_env=cargo_env,
            shown_env=cargo_shown,
            unset=cargo_unset,
            **kw,
        )

    st.run(
        "install the toolchain",
        ["rustup", "toolchain", "install", channel, "--profile", "minimal"],
        scratch,
    )
    rustc = cargo("rustc version", ["rustc", "-vV"], workspace).stdout
    cargo_version = cargo("cargo version", ["cargo", "-V"], workspace).stdout.strip()
    cargo("fetch the crates", ["cargo", "fetch", "--locked"], workspace)
    crates_build = cargo(
        "build the crates",
        ["cargo", "build", "--release", "--locked", "--offline"]
        + [a for c in CRATES for a in ("-p", c)],
        workspace,
        log=scratch / "logs" / "build-crates.log",
    )
    trees = {}
    for crate in (*CRATES, WORKSPACE):
        out = cargo(
            f"cargo tree {crate}",
            ["cargo", "tree", "--locked", "--offline", "-e", "normal,build"]
            + ["--prefix", "none", "-p", crate],
            workspace,
        ).stdout
        trees[crate] = tree_packages(out)
    control = cargo(
        "cargo tree sqlfluffrs_parser with the python feature (control)",
        ["cargo", "tree", "--locked", "--offline", "-e", "normal,build"]
        + [
            "--prefix",
            "none",
            "-p",
            "sqlfluffrs_parser",
            "-F",
            "sqlfluffrs_parser/python",
        ],
        workspace,
    ).stdout
    control_packages = tree_packages(control)
    if "pyo3" not in control_packages:
        raise DataError("the control tree has no pyo3: the check cannot find it")

    probe_dir = scratch / PROBE
    for rel in PROBE_FILES:
        (probe_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROBE_SRC / rel, probe_dir / rel)
    cargo("fetch the probe crates", ["cargo", "fetch", "--locked"], probe_dir)
    probe_build = cargo(
        "build the probe",
        ["cargo", "build", "--release", "--locked", "--offline"],
        probe_dir,
        log=scratch / "logs" / "build-probe.log",
    )
    trees[PROBE] = tree_packages(
        cargo(
            "cargo tree probe",
            [
                "cargo",
                "tree",
                "--locked",
                "--offline",
                "-e",
                "normal,build",
                "--prefix",
                "none",
            ],
            probe_dir,
        ).stdout
    )
    binary = probe_dir / "target" / "release" / PROBE
    ldd = st.run("ldd probe", ["ldd", binary], scratch).stdout
    readelf = st.run("readelf probe", ["readelf", "-d", binary], scratch).stdout
    shim_calls = shim_log.read_text("utf8").splitlines() if shim_log.exists() else []

    # Run the probe where no Python exists: the pinned Rust image of the CI.
    (scratch / "select1.sql").write_text(SELECT_1, encoding="utf8")
    image = rust_image()
    no_python_script = (
        "if command -v python3 python; then exit 3; fi; "
        'if [ -n "$(find / -xdev -name "libpython*" 2>/dev/null)" ]; then exit 4; fi; '
        f"/scratch/{PROBE}/target/release/{PROBE} --dialect ansi /scratch/select1.sql"
    )
    no_python = st.run(
        "run the probe with no Python",
        ["docker", "run", "--rm", "--network", "none", "-v", f"{scratch}:/scratch:ro"]
        + [image, "sh", "-c", no_python_script],
        scratch,
    )
    tree = json.loads(no_python.stdout)[0]["segments"]
    if tree != SELECT_1_TREE:
        raise DataError(f"the probe gave another tree for SELECT 1: {tree}")

    tests = cargo(
        "native fixture tests",
        [
            "cargo",
            "test",
            "--release",
            "--locked",
            "--offline",
            "--test",
            "fixture_tests",
        ]
        + ["--", "--test-threads", "1", "--nocapture"],
        workspace,
        log=scratch / "logs" / "fixture-tests.log",
        check=False,
        timeout=4 * 3600,
    )
    fixture_tests = parse_fixture_tests(tests.stdout, tests.stderr)
    tests_trees = {
        WORKSPACE + " (tests)": tree_packages(
            cargo(
                "cargo tree sqlfluffrs with dev dependencies",
                ["cargo", "tree", "--locked", "--offline", "-e", "normal,build,dev"]
                + ["--prefix", "none", "-p", WORKSPACE],
                workspace,
            ).stdout
        )
    }
    lines = rust_lines(workspace, tracked)
    st.run(
        "check the submodule after",
        [ROOT / "scripts" / "check-submodule", "after the T5 build"],
        ROOT,
    )
    return {
        "kind": "sqll-s3-sqlfluffrs-probe-build",
        "command": COMMANDS["build"] + " --scratch $SCRATCH",
        "started": started,
        "finished": now(),
        "scratch": str(scratch),
        "machine": bench_report.machine(),
        "load": {"before": load_before, "idle_wait_s": waited, "after": read_load()},
        "harness": bench_report.harness(),
        "sqlfluffrs": {
            "version": cargo_package_version(workspace / "Cargo.toml"),
            "submodule": "third_party/sqlfluff",
            "commit": commit.stdout.strip(),
            "tag": tag.stdout.strip(),
        },
        "toolchain": {
            "channel": channel,
            "source": "sqlfluffrs/rust-toolchain.toml",
            "rustc": rustc.strip().splitlines(),
            "cargo": cargo_version,
        },
        "generation": {
            "python": gen_python,
            "files": generated,
        },
        "builds": {
            "crates": {
                "exit_code": crates_build.returncode,
                "wall_s": st_wall(st, "build the crates"),
            },
            "probe": {
                "exit_code": probe_build.returncode,
                "wall_s": st_wall(st, "build the probe"),
            },
        },
        "python_shim_calls": shim_calls,
        "cargo_tree": trees,
        "cargo_tree_dev": tests_trees,
        "cargo_tree_control": {"sqlfluffrs_parser --features python": control_packages},
        "probe": {
            "source_sha256": {r: sha256_file(probe_dir / r) for r in PROBE_FILES},
            "bytes": binary.stat().st_size,
            "sha256": sha256_file(binary),
            "ldd": ldd_libraries(ldd),
            "needed": needed_libraries(readelf),
            "no_python_run": {
                "image": image,
                "script": no_python_script,
                "exit_code": no_python.returncode,
                "tree": tree,
            },
        },
        "fixture_tests": fixture_tests,
        "fixture_test_inputs": fixture_counts(copy),
        "lines": lines,
        "steps": st.entries,
    }


def st_wall(st: Steps, step: str) -> float:
    return next(e["wall_s"] for e in st.entries if e["step"] == step)


def cargo_package_version(manifest: Path) -> str:
    return tomllib.loads(manifest.read_text("utf8"))["package"]["version"]


# fixtures


def first_difference(expected, actual, path=()) -> dict:
    """The first place where two trees (type, value) differ: the path of
    types, and the expected and actual node there (short)."""
    if expected is None or actual is None or expected[0] != actual[0]:
        return {
            "path": list(path),
            "expected": short(expected),
            "actual": short(actual),
        }
    e_value, a_value = expected[1], actual[1]
    here = (*path, expected[0])
    if isinstance(e_value, str) or isinstance(a_value, str):
        return {
            "path": list(here),
            "expected": short(e_value),
            "actual": short(a_value),
        }
    for e_child, a_child in zip(e_value, a_value):
        if e_child != a_child:
            return first_difference(e_child, a_child, here)
    return {
        "path": list(here),
        "expected": f"{len(e_value)} children",
        "actual": f"{len(a_value)} children",
    }


def short(value) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= DIFF_TEXT else text[: DIFF_TEXT - 3] + "..."


def probe_argv(binary: Path, case: dialects.DialectCase, code_only: bool) -> list[str]:
    argv = [str(binary), "--dialect", case.dialect]
    if code_only:
        argv.append("--code-only")
    depth = (case.extra_config or {}).get("core", {}).get("max_parse_depth")
    if depth:
        argv += ["--max-parse-depth", str(depth)]
    return argv + [case.sql.as_posix()]


def run_probe(argv: list[str], cwd: Path) -> tuple[int, Any, list[str], str]:
    """Return (exit code, tree, errors, stderr) as the sqlfluff adapter reads
    "sqlfluff parse -f json" output."""
    proc = subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=600
    )
    errors = []
    tree = None
    try:
        payload = json.loads(proc.stdout)
        tree = payload[0]["segments"]
    except (ValueError, IndexError, KeyError, TypeError):
        errors.append("no JSON parse output")
    if proc.returncode != 0:
        errors.append(f"exit code {proc.returncode}")
    return proc.returncode, tree, errors, proc.stderr


def check_case(binary: Path, case: dialects.DialectCase) -> dict:
    """The S1 dialect check (suites/dialects.run) on the probe output: the
    exact tree and no unparsable segment. The probe gives the code-only tree
    itself, as "sqlfluff parse -c". Second check: the harness filter
    (code_only.code_only_record, as for sqruff) on the full probe tree."""
    _, expected = load_yaml(SQLFLUFF_ROOT / case.yml)
    rc, tree, errors, stderr = run_probe(
        probe_argv(binary, case, case.code_only), SQLFLUFF_ROOT
    )
    actual = record_to_tuple(tree) if tree is not None else None
    exact = trees_match(expected, actual)
    unparsable = has_node(tree, "unparsable")
    no_unparsable = tree is not None and not unparsable and not errors and rc == 0
    if case.code_only:
        rc2, full, errors2, _ = run_probe(
            probe_argv(binary, case, False), SQLFLUFF_ROOT
        )
        filtered = code_only_record(full) if full is not None else None
    else:
        rc2, errors2 = rc, errors
        filtered = sqlfluff_record(tree) if tree is not None else None
    filtered_tuple = record_to_tuple(filtered) if filtered is not None else None
    exact_filter = trees_match(expected, filtered_tuple)
    reasons = []
    if not exact:
        reasons.append("tree differs" if tree is not None else "no tree")
    if unparsable:
        reasons.append("unparsable segment")
    reasons += errors
    entry = {
        "id": case.id,
        "dialect": case.dialect,
        "status": "pass" if exact and no_unparsable else "fail",
        "exact": exact,
        "no_unparsable": no_unparsable,
        "exact_harness_filter": exact_filter,
        "exit_code": rc,
        "reason": "; ".join(reasons),
    }
    if not exact:
        entry["difference"] = first_difference(expected, actual)
    if rc != 0:
        entry["stderr"] = stderr.strip()[-DIFF_TEXT:]
    if rc2 != rc or errors2 != errors:
        entry["full_tree_exit_code"] = rc2
    return entry


def fixtures(scratch: Path, jobs: int = 4) -> dict:
    scratch = scratch.absolute()
    binary = scratch / PROBE / "target" / "release" / PROBE
    build_record = json.loads(BUILD_FILE.read_text("utf8"))
    if sha256_file(binary) != build_record["probe"]["sha256"]:
        raise DataError("the probe binary is not the binary of BUILD_FILE")
    cases = dialects.discover(SQLFLUFF_ROOT)
    started = now()
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        results = list(pool.map(lambda c: check_case(binary, c), cases))
    return {
        "kind": "sqll-s3-sqlfluffrs-probe-cases",
        "command": COMMANDS["fixtures"] + " --scratch $SCRATCH",
        "started": started,
        "finished": now(),
        "machine": bench_report.machine(),
        "harness": bench_report.harness(),
        "sqlfluff_ref": sqlfluff_ref(SQLFLUFF_ROOT),
        "probe_sha256": build_record["probe"]["sha256"],
        "checks": {
            "exact": "suites/dialects.run: compare.trees_match of the fixture tree "
            "(compare.load_yaml) and the probe tree (compare.record_to_tuple). The "
            "probe gives the code-only tree for a .yml case (--code-only).",
            "no_unparsable": "a tree, no unparsable node, no error, exit code 0",
            "exact_harness_filter": "the same, with the full probe tree and the "
            "harness filter (code_only.code_only_record), as for sqruff",
        },
        "cases": sorted(results, key=lambda r: r["id"]),
    }


# time


class ProbeBench(BenchAdapter):
    """The probe in the S2 benchmarks. Only for this research session: it is
    not in the harness registry. Commands start and parse only.

    The probe has no settings: it has no templater (as the raw templater),
    no rules, and no file size limit (as the limit 0 of the settings).
    """

    name = PROBE

    def __init__(self, binary: Path, version: str) -> None:
        super().__init__()
        self.binary = binary
        self._version = version

    def version(self) -> str:
        return self._version

    def unsupported(self, config: dict[str, Any]) -> str | None:
        core = config["core"]
        if core.get("templater") != "raw":
            return f"templater {core.get('templater')}"
        return None

    def write_config(self, config: dict[str, Any], folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "probe.json"
        path.write_text(json.dumps(config, sort_keys=True), encoding="utf8")
        return path

    def argv(self, command: str, config_file: Path, sql: str) -> list[str]:
        if command not in BENCH_COMMANDS:
            raise ValueError(f"the probe has no command {command}")
        dialect = json.loads(config_file.read_text("utf8"))["core"]["dialect"]
        return [str(self.binary), "--dialect", dialect, sql]

    def env(self) -> dict[str, str]:
        return isolated_env(EmptyHome.path())

    def read_tree(self, stdout: bytes, sql: str) -> Any:
        records = json.loads(stdout)
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError(f"not 1 parse record: {str(records)[:100]}")
        if records[0]["filepath"] != sql:
            raise ValueError(f"the record is for {records[0]['filepath']!r}")
        return records[0]["segments"]

    def read_violations(self, stdout: bytes, sql: str) -> list[dict] | None:
        raise ValueError("the probe has no lint command")


def time_inside(scratch: Path, version: str) -> dict:
    """The session, in the CI image: start and parse, the 3 tools in turn."""
    from sqll_harness.bench.tools import SqlfluffBench, SqruffBench

    errors = bench_run.check_tools(["sqlfluff", "sqruff"])
    if errors:
        raise DataError("; ".join(errors))
    binary = scratch / PROBE / "target" / "release" / PROBE
    defs = bench_definitions.load()
    scope, benchmarks = bench_run.plan(
        defs, tools=list(BENCH_TOOLS), profile="full", commands=list(BENCH_COMMANDS)
    )
    work = scratch / "bench-work"
    if work.exists():
        shutil.rmtree(work)
    report = bench_run.run(
        defs=defs,
        adapters=[ProbeBench(binary, version), SqlfluffBench(), SqruffBench()],
        profile="full",
        scope=scope,
        benchmarks=benchmarks,
        sqlfluff_root=SQLFLUFF_ROOT,
        work=work,
        progress=bench_run.progress_to_stderr,
    )
    return report, probe_phases(binary, work / "inputs", benchmarks)


def probe_phases(binary: Path, inputs_dir: Path, benchmarks: list[dict]) -> dict:
    """The seconds of each phase of the probe (--timings) on the input of
    each benchmark: the median of PHASE_RUNS runs, after the timed runs of
    the session. The input files are those that the benchmarks checked."""
    out = {}
    env = isolated_env(EmptyHome.path())
    for b in benchmarks:
        argv = [str(binary), "--timings", "--dialect", b["dialect"]]
        argv.append(str(inputs_dir / f"{b['input']}.sql"))
        samples = []
        for _ in range(PHASE_RUNS):
            proc = subprocess.run(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            if proc.returncode != 0:
                raise DataError(
                    f"{b['id']}: the probe gave exit code {proc.returncode}"
                )
            samples.append(json.loads(proc.stderr.strip().splitlines()[-1]))
        out[b["id"]] = {
            "runs": PHASE_RUNS,
            "tokens": samples[0]["tokens"],
            **{k: round(statistics.median(s[k] for s in samples), 6) for k in PHASES},
        }
    return out


def read_load() -> list[float]:
    """The 1, 5, and 15-minute load averages of the host."""
    return [float(x) for x in Path("/proc/loadavg").read_text().split()[:3]]


def wait_idle(timeout_s: float = 900, step_s: float = 10) -> tuple[list[float], float]:
    """Wait until the 1-minute load average is below IDLE_LOAD, so that no
    other work runs at the start of the session. Return the load and the
    wait. DataError after timeout_s."""
    start = time.monotonic()
    while True:
        load = read_load()
        waited = round(time.monotonic() - start, 1)
        if load[0] < IDLE_LOAD:
            return load, waited
        if waited > timeout_s:
            raise DataError(f"the machine is not idle: load average {load}")
        time.sleep(step_s)


def time_session(scratch: Path, image: str | None) -> dict:
    """Run time_inside in the CI image: one container, serial, no network."""
    scratch = scratch.absolute()
    build_record = json.loads(BUILD_FILE.read_text("utf8"))
    binary = scratch / PROBE / "target" / "release" / PROBE
    if sha256_file(binary) != build_record["probe"]["sha256"]:
        raise DataError("the probe binary is not the binary of BUILD_FILE")
    image = image or ci_image()
    st = Steps(scratch)
    image_id = st.run(
        "CI image id",
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        ROOT,
    ).stdout.strip()
    docker_version = st.run(
        "docker version", ["docker", "version", "--format", "{{.Server.Version}}"], ROOT
    ).stdout.strip()
    version = f"sqlfluffrs {build_record['sqlfluffrs']['version']} (probe)"
    load_before, waited = wait_idle()
    started = now()
    st.run(
        "timing session",
        ["docker", "run", "--rm", "--network", "none"]
        + ["-v", f"{ROOT}:/repo:ro", "-v", f"{scratch}:/scratch"]
        + ["-e", "PYTHONPATH=/repo/harness", "-w", "/repo", image]
        + ["/opt/sqll/harness-venv/bin/python", "scripts/s3/sqlfluffrs_probe.py"]
        + ["time-inside", "--scratch", "/scratch", "--version", version],
        ROOT,
        log=scratch / "logs" / "timing.log",
        timeout=4 * 3600,
    )
    load_after = read_load()
    if load_after[1] > MAX_SESSION_LOAD:
        raise DataError(
            f"the 5-minute load average after the session is {load_after[1]}: "
            "other processes ran during the serial session"
        )
    report = json.loads((scratch / "bench-report.json").read_text("utf8"))
    phases = json.loads((scratch / "probe-phases.json").read_text("utf8"))
    st.run(
        "check the submodule after",
        [ROOT / "scripts" / "check-submodule", "after the T5 timing"],
        ROOT,
    )
    return {
        "kind": "sqll-s3-sqlfluffrs-probe-bench",
        "command": COMMANDS["time"] + " --scratch $SCRATCH",
        "started": started,
        "finished": now(),
        "session": {
            "image": image,
            "image_id": image_id,
            "docker": docker_version,
            "method": "harness/bench.md: the CI image in docker, one container, "
            "serial, no network, no other load; the full profile; the tools run in "
            "turn for each repeat (timer.run_in_turn)",
            "host": bench_report.machine(),
            "machine_lock": "the command ran under flock /tmp/sqll-machine.lock "
            "(PROCESS.md, rule 7)",
            "load": {
                "before": load_before,
                "after": load_after,
                "idle_wait_s": waited,
                "rule": f"start when the 1-minute load average is below {IDLE_LOAD}; "
                f"after the session, the 5-minute load average must be at most "
                f"{MAX_SESSION_LOAD} (one serial process gives about 1)",
            },
        },
        "probe_sha256": build_record["probe"]["sha256"],
        "steps": st.entries,
        "report": report,
        "probe_phases": phases,
    }


# report


def generator_facts(sqlfluff_root: Path) -> dict:
    """Facts about the grammar generator from its source (read only)."""
    utils = sqlfluff_root / "utils"
    scripts = {}
    for rel in GENERATOR_SCRIPTS:
        text = (sqlfluff_root / rel).read_text("utf8")
        scripts[rel] = {
            "lines": line_count(text.encode("utf8")),
            "sqlfluff_imports": sorted(
                set(re.findall(r"^from (sqlfluff[\w.]*) import", text, re.MULTILINE))
            ),
        }
    parsers = (utils / "build_parsers.py").read_text("utf8")
    lexers = (utils / "build_lexers.py").read_text("utf8")
    convert = _method(parsers, "_convert_to_inst")
    handlers = sorted(set(re.findall(r"self\.(_handle_\w+)\(", convert)))
    imported = set()
    for m in re.finditer(
        r"^from sqlfluff[\w.]* import (?:\(([^)]*)\)|(.*)$)", parsers, re.MULTILINE
    ):
        imported |= set(re.findall(r"\b([A-Z]\w+)\b", m[1] or m[2]))
    classes = sorted(imported & set(re.findall(r"\b([A-Z]\w+)\b", convert)))
    private = sorted(
        set(re.findall(r"(?<!self)(?<!cls)\.(_[a-z]\w*)\b", parsers + lexers))
        - {"_add_string"}
    )
    tables = _method(parsers, "generate_rust_tables")
    builder = parsers[
        parsers.index("class TableBuilder") : parsers.index(
            "def matchable_to_const_name"
        )
    ]
    dialect_dir = sqlfluff_root / "src" / "sqlfluff" / "dialects"
    custom_match = sorted(
        p.name
        for p in dialect_dir.glob("dialect_*.py")
        if re.search(r"^\s+def (match|root_parse)\(", p.read_text("utf8"), re.MULTILINE)
    )
    lexer_snippets = sorted(
        set(
            re.findall(
                r'^\s+"(\w+)": (?:\'|"|r"""|\()',
                _block(lexers, "is_match_valid_dict"),
                re.MULTILINE,
            )
        )
        | set(
            re.findall(
                r'^\s+"(\w+)": "Some', _block(lexers, "fallback_function"), re.MULTILINE
            )
        )
    )
    engine_names = {}
    for crate in ("sqlfluffrs_lexer", "sqlfluffrs_parser"):
        for path in sorted((sqlfluff_root / WORKSPACE / crate / "src").rglob("*.rs")):
            for no, line in enumerate(path.read_text("utf8").splitlines(), 1):
                if re.search(r"Dialect::[A-Z]\w*", line):
                    rel = path.relative_to(sqlfluff_root).as_posix()
                    engine_names.setdefault(rel, []).append(f"{no}: {line.strip()}")
    return {
        "scripts": scripts,
        "engine_lines_that_name_a_dialect": engine_names,
        "dialect_reader": "rustify.py lists the dialects with "
        "sqlfluff.core.dialects.dialect_readout() and runs 3 builders for each "
        "dialect in a new Python process: build_dialect.py (mod.rs), "
        "build_lexers.py (matcher.rs), build_parsers.py --table-driven "
        "(parser.rs); build_dialects.py writes dialect/mod.rs. The builders load "
        "the dialect with dialect_selector(name). They read the Python objects: "
        "the dialect _library (each segment class and grammar), the lexer "
        "matchers (get_lexer_matchers), the bracket sets and reserved keywords "
        "(bracket_sets, sets), and the attributes of each grammar object.",
        "grammar_classes": classes,
        "grammar_handlers": handlers,
        "private_attributes": private,
        "table_builder_lines": line_count(builder.encode("utf8")),
        "rust_emitter_lines": line_count(tables.encode("utf8")),
        "lines_note": "table_builder_lines: the TableBuilder class of "
        "build_parsers.py (dialect reading, flattening, validation, and output). "
        "rust_emitter_lines: its generate_rust_tables method, the part that "
        "writes Rust.",
        "lexer_rust_snippets": lexer_snippets,
        "dialect_files_with_custom_match": custom_match,
        "unknown_class_check": "TableBuilder.validate() fails the generation if "
        "an instruction is 'Missing' (a grammar class with no handler).",
    }


def _method(text: str, name: str) -> str:
    start = text.index(f"    def {name}(")
    m = re.compile(r"^    def |^\S", re.MULTILINE).search(text, start + 1)
    return text[start : m.start() if m else len(text)]


def _block(text: str, name: str) -> str:
    start = text.index(f"{name} = {{")
    end = text.index("\n    }\n", start)
    return text[start:end]


def _stat(result: dict | None) -> dict | None:
    if not result or result["status"] != VALID:
        return None
    wall = result["stats"]["wall_s"]
    cpu = result["stats"]["cpu_s"]
    return {
        "n": wall["n"],
        "median_s": wall["median"],
        "mad_s": wall["mad"],
        "cpu_median_s": cpu["median"],
        "cpu_mad_s": cpu["mad"],
    }


def _ratio(a: dict | None, b: dict | None) -> float | None:
    if a is None or b is None or not b["median_s"]:
        return None
    return round(a["median_s"] / b["median_s"], 4)


def speed(bench: dict, baseline: dict) -> dict:
    report = bench["report"]
    errors = bench_report.check(report)
    if errors:
        raise DataError("the bench report is not correct: " + "; ".join(errors[:5]))
    by = {(r["id"], r["tool"]): r for r in report["results"]}
    base = {(r["id"], r["tool"]): r for r in baseline["results"]}
    ids = sorted({r["id"] for r in report["results"]})
    rows = []
    for bid in ids:
        first = by[(bid, PROBE)]
        stats = {tool: _stat(by.get((bid, tool))) for tool in BENCH_TOOLS}
        row = {
            "id": bid,
            "command": first["command"],
            "dialect": first["dialect"],
            "size": first["size"],
            "status": {tool: by[(bid, tool)]["status"] for tool in BENCH_TOOLS},
            **{tool: stats[tool] for tool in BENCH_TOOLS},
            "probe_over_sqruff": _ratio(stats[PROBE], stats["sqruff"]),
            "probe_over_sqlfluff": _ratio(stats[PROBE], stats["sqlfluff"]),
            "baseline_over_session": {
                tool: _ratio(_stat(base.get((bid, tool))), stats[tool])
                for tool in ("sqlfluff", "sqruff")
            },
            "probe_phases": bench["probe_phases"][bid],
        }
        rows.append(row)
    if sorted(bench["probe_phases"]) != ids:
        raise DataError("the probe phases are not those of the benchmarks")
    return {
        "session": {
            **bench["session"],
            "machine": report["machine"],
            "harness": report["harness"],
            "policy": report["policy"],
            "timer_overhead_median_s": report["timer"]["overhead"]["stats"]["wall_s"][
                "median"
            ],
            "tools": {t: report["tools"][t]["version"] for t in BENCH_TOOLS},
        },
        "benchmarks": rows,
        "summary": speed_summary(rows),
        "notes": [
            "Each time is the median wall time of the timed runs of one benchmark "
            "(harness timer: process start to exit). Ratios: probe / other tool, "
            "on the same benchmark in the same session; below 1 means the probe is "
            "faster.",
            "probe_over_sqlfluff uses the sqlfluff times of this session. "
            "baseline_over_session: the S2 baseline median (results/s2/baseline.json, "
            "another session) / the median of this session, for sqlfluff and "
            "sqruff; near 1 means the two sessions agree.",
            "probe_phases: --timings of the probe, the median of "
            f"{PHASE_RUNS} runs after the timed runs, in the same container. setup: "
            "the dialect and lexer setup (the lazy dialect tables); parse: "
            "root_parse; record: the sqlfluff record of the tree; write: the JSON "
            "output. The process start and exit are not in the phases.",
        ],
    }


def _group(row: dict) -> str:
    return row["command"] if row["size"] is None else f"{row['command']}/{row['size']}"


def speed_summary(rows: list[dict]) -> dict:
    """For each group (start, parse/<size>, all): counts of valid pairs and
    the sum and median of the ratios. The sums use only the benchmarks where
    both tools are valid, as harness/bench.md "Report"."""
    out = {}
    groups = sorted({_group(r) for r in rows}) + ["all"]
    for group in groups:
        sel = [r for r in rows if group == "all" or _group(r) == group]
        entry = {"benchmarks": len(sel)}
        for other in ("sqruff", "sqlfluff"):
            key = f"probe_over_{other}"
            pairs = [r for r in sel if r[key] is not None]
            ratios = [r[key] for r in pairs]
            probe_sum = sum(r[PROBE]["median_s"] for r in pairs)
            other_sum = sum(r[other]["median_s"] for r in pairs)
            entry[key] = {
                "pairs": len(pairs),
                "probe_faster": sum(1 for x in ratios if x < 1),
                "median_ratio": round(statistics.median(ratios), 4) if ratios else None,
                "min_ratio": min(ratios) if ratios else None,
                "max_ratio": max(ratios) if ratios else None,
                "sum_probe_s": round(probe_sum, 6),
                f"sum_{other}_s": round(other_sum, 6),
                "sum_ratio": round(probe_sum / other_sum, 4) if other_sum else None,
            }
        drift = [
            r["baseline_over_session"][t]
            for r in sel
            for t in ("sqlfluff", "sqruff")
            if r["baseline_over_session"][t] is not None
        ]
        entry["baseline_over_session_median"] = (
            round(statistics.median(drift), 4) if drift else None
        )
        sums = {k: sum(r["probe_phases"][k] for r in sel) for k in PHASES}
        total = sum(sums.values())
        entry["probe_phases"] = {
            "sum_s": {k: round(v, 6) for k, v in sums.items()},
            "share": {
                k: round(v / total, 4) if total else None for k, v in sums.items()
            },
        }
        out[group] = entry
    return out


def fixture_summary(cases_record: dict, build_record: dict) -> dict:
    cases = cases_record["cases"]
    want = [c.id for c in dialects.discover(SQLFLUFF_ROOT)]
    got = [c["id"] for c in cases]
    if sorted(want) != got:
        raise DataError(
            "the cases file does not have the dialect cases of the fixtures"
        )
    if cases_record["probe_sha256"] != build_record["probe"]["sha256"]:
        raise DataError("the cases file is not from the probe of the build file")
    by_dialect: dict[str, Counter] = {}
    for c in cases:
        n = by_dialect.setdefault(c["dialect"], Counter())
        n["cases"] += 1
        n["pass"] += c["status"] == "pass"
        n["exact"] += c["exact"]
        n["no_unparsable"] += c["no_unparsable"]
        n["exact_harness_filter"] += c["exact_harness_filter"]
    total = sum(by_dialect.values(), Counter())
    keys = ("cases", "pass", "exact", "no_unparsable", "exact_harness_filter")
    failures = [
        {
            k: c[k]
            for k in ("id", "reason", "exact", "no_unparsable", "difference", "stderr")
            if k in c
        }
        for c in cases
        if c["status"] != "pass"
    ]
    filter_only = [c["id"] for c in cases if c["exact"] != c["exact_harness_filter"]]
    return {
        "total": {k: total[k] for k in keys},
        "by_dialect": {
            d: {k: n[k] for k in keys} for d, n in sorted(by_dialect.items())
        },
        "failures": failures,
        "exact_differs_with_harness_filter": filter_only,
    }


def native_tests_summary(build_record: dict) -> dict:
    ft = build_record["fixture_tests"]
    inputs = build_record["fixture_test_inputs"]
    by_dialect = {}
    for name, status in ft["tests"].items():
        m = FIXTURE_TEST_RE.match(name)
        y = YAML_TEST_RE.match(name)
        if m and m[1] in inputs:
            d = m[1]
            row = by_dialect.setdefault(d, {"fixtures": inputs[d]})
            counts = ft["parse_counts"].get(d)
            row["parse_test"] = {"status": status, **(counts or {})}
        elif y and y[1] in inputs:
            d = y[1]
            row = by_dialect.setdefault(d, {"fixtures": inputs[d]})
            counts = ft["yaml_counts"].get(d)
            row["yaml_shape_test"] = {
                "status": status,
                **(counts or {}),
                "failed_fixtures": ft["yaml_failed"].get(d, []),
                "panic": ft["panics"].get(name),
            }
    other = {
        n: s
        for n, s in ft["tests"].items()
        if not (FIXTURE_TEST_RE.match(n) or YAML_TEST_RE.match(n))
        or (FIXTURE_TEST_RE.match(n) and FIXTURE_TEST_RE.match(n)[1] not in inputs)
    }
    return {
        "command": "cargo test --release --locked --offline --test fixture_tests -- "
        "--test-threads 1 --nocapture",
        "result": ft["result"],
        "passed": ft["passed"],
        "failed": ft["failed"],
        "checks": {
            "parse_test": "test_<dialect>_fixtures: the parse of each fixture with "
            "a .yml file gives no error. It does not compare the tree.",
            "yaml_shape_test": "test_yaml_output_matches_python_<dialect>: the "
            "top-level keys and the child count of the root node are those of the "
            ".yml file. It does not compare the full tree. It stops at the first "
            "lex or parse error (a panic).",
        },
        "by_dialect": dict(sorted(by_dialect.items())),
        "other_tests": dict(sorted(other.items())),
    }


def standalone(build_record: dict) -> dict:
    trees = build_record["cargo_tree"]
    probe = build_record["probe"]
    steps = {e["step"]: e for e in build_record["steps"]}
    return {
        "pyo3_in_dependency_tree": {
            name: "pyo3" in pkgs for name, pkgs in trees.items()
        },
        "pyo3_with_python_feature_control": "pyo3"
        in build_record["cargo_tree_control"]["sqlfluffrs_parser --features python"],
        "python_calls_during_cargo": build_record["python_shim_calls"],
        "ldd": probe["ldd"],
        "needed": probe["needed"],
        "libpython_linked": any(
            "python" in lib for lib in probe["ldd"] + probe["needed"]
        ),
        "run_with_no_python": {
            "image": probe["no_python_run"]["image"],
            "exit_code": probe["no_python_run"]["exit_code"],
            "tree_is_select_1": probe["no_python_run"]["tree"] == SELECT_1_TREE,
        },
        "python_needed": {
            "generation": "yes: utils/rustify.py imports sqlfluff "
            f"(step 'generate the dialect tables', exit code "
            f"{steps['generate the dialect tables']['exit_code']})",
            "cargo_build": "no: Python commands on PATH fail and record each call; "
            f"{len(build_record['python_shim_calls'])} calls. sqlfluffrs_dialects/build.rs "
            "calls Python only if dialect/mod.rs is missing or older than a "
            "Python dialect or builder file.",
            "run": "no: ldd and readelf show no libpython, and the probe runs in an "
            "image with no Python",
        },
    }


def generation_summary(build_record: dict) -> dict:
    files = build_record["generation"]["files"]
    steps = {e["step"]: e for e in build_record["steps"]}
    by_dialect: dict[str, dict] = {}
    for f in files:
        parts = f["path"].split("/")
        if len(parts) == 6:
            d = by_dialect.setdefault(parts[4], {"files": 0, "lines": 0, "bytes": 0})
            d["files"] += 1
            d["lines"] += f["lines"]
            d["bytes"] += f["bytes"]
            if "grammar_instructions" in f:
                d["grammar_instructions"] = f["grammar_instructions"]
    return {
        "python": build_record["generation"]["python"],
        "wall_s": steps["generate the dialect tables"]["wall_s"],
        "check_installed_exit_code": steps["check the generation (installed sqlfluff)"][
            "exit_code"
        ],
        "check_submodule_src_exit_code": steps["check the generation (submodule src)"][
            "exit_code"
        ],
        "deterministic": "utils/rustify.py check makes each file again and compares "
        "it with the file: exit code 0 with the installed sqlfluff 4.4.0 (PyPI) and "
        "with the src of the submodule",
        "files": len(files),
        "lines": sum(f["lines"] for f in files),
        "bytes": sum(f["bytes"] for f in files),
        "sha256_of_list": sha256_bytes(
            "".join(f"{f['sha256']}  {f['path']}\n" for f in files).encode("utf8")
        ),
        "by_dialect": dict(sorted(by_dialect.items())),
    }


def option3_reuse(generator: dict, build_record: dict) -> dict:
    """Can option 3 (a new parser with a generated grammar) reuse the
    generator? The facts come from the build record and the generator
    source; the conclusion is a judgement."""
    steps = {e["step"]: e for e in build_record["steps"]}
    installed = build_record["generation"]["python"]["installed"]
    parser_lines = build_record["lines"]["sqlfluffrs_parser"]["hand_written"]["lines"]
    return {
        "kind": "judgement from the facts below",
        "facts": {
            "runs_outside_the_submodule": steps["generate the dialect tables"][
                "exit_code"
            ]
            == 0,
            "sqlfluff_used": installed,
            "deterministic": all(
                steps[s]["exit_code"] == 0
                for s in (
                    "check the generation (installed sqlfluff)",
                    "check the generation (submodule src)",
                )
            ),
            "unhandled_grammar_classes": "none: the generation passed "
            "TableBuilder.validate() for each dialect",
            "dialect_files_with_custom_match": generator[
                "dialect_files_with_custom_match"
            ],
            "private_sqlfluff_attributes_read": len(generator["private_attributes"]),
            "table_builder_lines": generator["table_builder_lines"],
            "rust_emitter_lines": generator["rust_emitter_lines"],
            "output_format": "Rust statics of sqlfluffrs_types: GrammarTables "
            "(instructions, child ids, terminators, strings, aux data, hints, "
            "segment types and classes) for the parser; LexMatcher lists, keywords, "
            "and bracket pairs for the lexer",
            "engine_that_reads_the_tables": f"sqlfluffrs_parser, {parser_lines} "
            "hand-written lines",
        },
        "conclusion": "Option 3 can reuse the generator. It reads only the loaded "
        "Python dialect objects of the pinned sqlfluff, needs Python only to "
        "generate, gives the same output each time, and fails on a grammar class "
        "that it does not know. The sqlfluff dialects have no custom match code, "
        "so the tables hold the full grammar. Two ways: (a) keep the "
        "sqlfluffrs_types table format and write a new engine that reads it; (b) "
        "keep the table builder (dialect reading and flattening) and write a new "
        "emitter for another format. In both, the new engine must give the "
        "semantics that sqlfluffrs_parser gives to the tables (S4: exact trees). "
        "Risk: the generator reads private sqlfluff attributes, so a new sqlfluff "
        "version can break it; the pin limits this risk.",
    }


def make_report(
    build_path: Path = BUILD_FILE,
    cases_path: Path = CASES_FILE,
    bench_path: Path = BENCH_FILE,
    baseline_path: Path = BASELINE_FILE,
) -> dict:
    build_record = json.loads(build_path.read_text("utf8"))
    cases_record = json.loads(cases_path.read_text("utf8"))
    bench = json.loads(bench_path.read_text("utf8"))
    baseline = json.loads(baseline_path.read_text("utf8"))
    if bench["probe_sha256"] != build_record["probe"]["sha256"]:
        raise DataError("the bench file is not from the probe of the build file")
    source = {r: sha256_file(PROBE_SRC / r) for r in PROBE_FILES}
    if build_record["probe"]["source_sha256"] != source:
        raise DataError("the probe source is not the source of the build file")
    if build_record["sqlfluffrs"]["commit"] != sqlfluff_ref(SQLFLUFF_ROOT):
        raise DataError("the build file is not from the pinned submodule commit")
    if bench["report"]["sqlfluff_ref"] != build_record["sqlfluffrs"]["commit"]:
        raise DataError("the bench report has another sqlfluff commit")
    builds = build_record["builds"]
    lines = build_record["lines"]
    generator = generator_facts(SQLFLUFF_ROOT)
    return {
        "kind": "sqll-s3-sqlfluffrs-probe",
        "task": "T5",
        "criterion": "C4",
        "inputs": {
            rel(p): sha256_file(p)
            for p in (build_path, cases_path, bench_path, baseline_path)
        },
        "commands": {
            k: v + (" [--check]" if k == "report" else " --scratch $SCRATCH")
            for k, v in COMMANDS.items()
        },
        "scratch": build_record["scratch"],
        "repeat": "Set SCRATCH to a new folder with no sqlfluff config file above "
        "it, and REPO to the repository. The 'steps' of each input file have the "
        "commands that ran, with these names.",
        "probe": {
            "source": "scripts/s3/probe-sqlfluffrs",
            "research_code": "yes: S3 research code, not sqll; no harness adapter or "
            "registry entry; no lint or fix command",
            "license": "MIT (parts follow sqlfluffrs 4.4.0 code; THIRD_PARTY.md)",
            "source_sha256": build_record["probe"]["source_sha256"],
            "bytes": build_record["probe"]["bytes"],
            "sha256": build_record["probe"]["sha256"],
        },
        "sqlfluffrs": build_record["sqlfluffrs"],
        "toolchain": build_record["toolchain"],
        "machines": {
            "build": build_record["machine"],
            "fixtures": cases_record["machine"],
            "timing": bench["report"]["machine"],
        },
        "build": {
            "crates": {
                "names": list(CRATES),
                "features": "default (no python)",
                **builds["crates"],
            },
            "probe": builds["probe"],
            "build_time_note": "Wall time of a release build with the crates fetched "
            "before (cargo fetch), 4 CPUs, on the build machine.",
            "probe_binary_bytes": build_record["probe"]["bytes"],
            "lines": lines,
            "lines_total": {
                kind: sum(c[kind]["lines"] for c in lines.values())
                for kind in ("hand_written", "generated")
            },
        },
        "standalone": standalone(build_record),
        "generation": generation_summary(build_record),
        "native_fixture_tests": native_tests_summary(build_record),
        "fixtures": fixture_summary(cases_record, build_record),
        "speed": speed(bench, baseline),
        "generator": generator,
        "option3_reuse": option3_reuse(generator, build_record),
        "steps": {
            "build": build_record["steps"],
            "time": bench["steps"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sqlfluffrs_probe.py")
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="Generate, build, and test in a scratch copy.")
    b.add_argument("--scratch", type=Path, required=True)
    b.add_argument(
        "--python",
        type=Path,
        default=None,
        help="The Python of the pinned sqlfluff (default: the sqlfluff tool venv).",
    )
    f = sub.add_parser(
        "fixtures", help="Check the probe trees on the dialect fixtures."
    )
    f.add_argument("--scratch", type=Path, required=True)
    f.add_argument("--jobs", type=int, default=4)
    t = sub.add_parser("time", help="Time the probe, sqlfluff, and sqruff in docker.")
    t.add_argument("--scratch", type=Path, required=True)
    t.add_argument("--image", default=None, help="Default: sqll-ci:<ci/image_tag.py>.")
    ti = sub.add_parser("time-inside", help="(In the CI image) the timing session.")
    ti.add_argument("--scratch", type=Path, required=True)
    ti.add_argument("--version", required=True)
    r = sub.add_parser("report", help="Write OUT_FILE from the committed files.")
    r.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.command == "build":
            python = args.python or tools_dir() / "sqlfluff" / "bin" / "python"
            record = build(args.scratch, python)
            BUILD_FILE.write_text(dump(record), encoding="utf8")
            print(f"wrote {rel(BUILD_FILE)}")
        elif args.command == "fixtures":
            record = fixtures(args.scratch, args.jobs)
            CASES_FILE.write_text(dump(record), encoding="utf8")
            print(f"wrote {rel(CASES_FILE)}")
        elif args.command == "time":
            record = time_session(args.scratch, args.image)
            BENCH_FILE.write_text(dump(record), encoding="utf8")
            print(f"wrote {rel(BENCH_FILE)}")
        elif args.command == "time-inside":
            report, phases = time_inside(args.scratch, args.version)
            (args.scratch / "bench-report.json").write_text(
                dump(report), encoding="utf8"
            )
            (args.scratch / "probe-phases.json").write_text(
                dump(phases), encoding="utf8"
            )
        else:
            text = dump(make_report())
            if args.check:
                if not OUT_FILE.exists() or OUT_FILE.read_text("utf8") != text:
                    print(f"{rel(OUT_FILE)} is not the report of the inputs")
                    return 1
                print(f"{rel(OUT_FILE)} is up to date")
            else:
                OUT_FILE.write_text(text, encoding="utf8")
                print(f"wrote {rel(OUT_FILE)}")
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
