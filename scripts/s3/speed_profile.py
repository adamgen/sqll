"""S3 T14: parse speed, part 1. Measure and profile sqll, set the target, and
decide if the target is in reach (status/S3.md, "Stop rule").

Commands. Run them on the host with the harness Python. "time" and
"profile" measure, so they take the machine lock (PROCESS.md, rule 7):

    flock /tmp/sqll-machine.lock uv run --frozen --project harness python scripts/s3/speed_profile.py time --scratch DIR
    flock /tmp/sqll-machine.lock uv run --frozen --project harness python scripts/s3/speed_profile.py profile --scratch DIR
    uv run --frozen --project harness python scripts/s3/speed_profile.py report [--check]

"time" runs SESSIONS sessions of the start and parse benchmarks of sqll and
sqruff, each in a new container of the CI image (the S2 baseline method,
harness/bench.md: serial, no network, the full profile, the tools in turn
for each repeat). Session 1 is the controlled session; it also runs
"sqll parse --timings" PHASE_RUNS times on each input. The other sessions
measure the noise. sqll is out/sqll/bin/sqll, a fresh build of the
worktree. Output: SESSIONS_FILE.
"profile" builds the same source with symbols (debug line tables, not
stripped) in DIR, and runs valgrind callgrind on the inputs of the worst
benchmarks of session 1. Output: PROFILE_FILE.
"report" reads only the committed files and writes OUT_FILE. With --check it
writes nothing and fails if OUT_FILE is not the new text (the drift test).

Each command stops with exit code 1 if a step fails or the data do not
agree (DataError).
"""

import argparse
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqll_harness.adapters import sqll as sqll_adapter
from sqll_harness.adapters.base import EmptyHome, isolated_env
from sqll_harness.bench import definitions as bench_definitions
from sqll_harness.bench import registry as bench_registry
from sqll_harness.bench import report as bench_report
from sqll_harness.bench import run as bench_run
from sqll_harness.bench.timer import VALID
from sqll_harness.paths import SQLFLUFF_ROOT

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sqlfluffrs_probe as probe  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "s3"
SESSIONS_FILE = RESULTS / "speed-profile-sessions.json"
PROFILE_FILE = RESULTS / "speed-profile-callgrind.json"
OUT_FILE = RESULTS / "speed-profile.json"
SPEED_BY_BASE_FILE = RESULTS / "speed-by-base.json"
TOOLS = ("sqll", "sqruff")
COMMANDS = ("start", "parse")
SESSIONS = 5
PHASE_RUNS = 5
PHASES = ("init", "setup", "lex", "parse", "record", "write", "free")
DataError = probe.DataError

_SCRIPT = "uv run --frozen --project harness python scripts/s3/speed_profile.py"
COMMAND_LINES = {
    "time": f"flock /tmp/sqll-machine.lock {_SCRIPT} time",
    "profile": f"flock /tmp/sqll-machine.lock {_SCRIPT} profile",
    "report": f"{_SCRIPT} report",
}


def dump(data: Any) -> str:
    return probe.dump(data)


# time


def time_inside(scratch: Path, session: int, phases: bool) -> None:
    """(In the CI image.) One session: start and parse of sqll and sqruff."""
    errors = bench_run.check_tools(list(TOOLS))
    if errors:
        raise DataError("; ".join(errors))
    defs = bench_definitions.load()
    scope, benchmarks = bench_run.plan(
        defs, tools=list(TOOLS), profile="full", commands=list(COMMANDS)
    )
    work = scratch / f"work-{session}"
    if work.exists():
        shutil.rmtree(work)
    report = bench_run.run(
        defs=defs,
        adapters=[bench_registry.get(t) for t in TOOLS],
        profile="full",
        scope=scope,
        benchmarks=benchmarks,
        sqlfluff_root=SQLFLUFF_ROOT,
        work=work,
        progress=bench_run.progress_to_stderr,
    )
    (scratch / f"session-{session}.json").write_text(dump(report), "utf8")
    if phases:
        out = sqll_phases(sqll_adapter.binary_path(), work / "inputs", benchmarks)
        (scratch / "phases.json").write_text(dump(out), "utf8")


def sqll_phases(binary: Path, inputs_dir: Path, benchmarks: list[dict]) -> dict:
    """The seconds of each phase of "sqll parse --timings" on the input of
    each benchmark: each of PHASE_RUNS runs, after the timed runs."""
    out = {}
    env = isolated_env(EmptyHome.path())
    for b in benchmarks:
        argv = [str(binary), "parse", "-f", "json", "--timings"]
        argv += ["--dialect", b["dialect"], str(inputs_dir / f"{b['input']}.sql")]
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
                raise DataError(f"{b['id']}: sqll gave exit code {proc.returncode}")
            samples.append(json.loads(proc.stderr.strip().splitlines()[-1]))
        out[b["id"]] = samples
    return out


def compact(report: dict) -> dict:
    """The report with the samples of each result as lists: the wall time,
    the CPU time (user and system), and the exit code of each timed run.
    The warmup run and the other sample fields are left out."""
    out = dict(report)
    results = []
    for r in report["results"]:
        timed = [s for s in r["samples"] if s["kind"] == "timed"]
        results.append(
            {
                **{k: v for k, v in r.items() if k != "samples"},
                "samples": {
                    "wall_s": [s["wall_s"] for s in timed],
                    "cpu_s": [round(s["user_s"] + s["sys_s"], 6) for s in timed],
                    "exit_code": [s["exit_code"] for s in timed],
                },
            }
        )
    out["results"] = results
    return out


def time_sessions(scratch: Path, image: str | None, sessions: int) -> dict:
    """Run the sessions in the CI image: a new container for each session."""
    scratch = scratch.absolute()
    scratch.mkdir(parents=True, exist_ok=True)
    binary = sqll_adapter.binary_path()
    build = json.loads(
        subprocess.run(
            [str(binary), "version", "--build"], capture_output=True, check=True
        ).stdout
    )
    want, _ = sqll_adapter.source_hash(ROOT)
    if build["source_sha256"] != want:
        raise DataError(
            "out/sqll/bin/sqll is not a fresh build. Run scripts/build-sqll."
        )
    image = image or probe.ci_image()
    st = probe.Steps(scratch)
    image_id = st.run(
        "CI image id",
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        ROOT,
    ).stdout.strip()
    docker_version = st.run(
        "docker version", ["docker", "version", "--format", "{{.Server.Version}}"], ROOT
    ).stdout.strip()
    records = []
    for k in range(1, sessions + 1):
        load_before, waited = probe.wait_idle()
        started = probe.now()
        argv = ["docker", "run", "--rm", "--network", "none"]
        argv += ["-v", f"{ROOT}:/repo:ro", "-v", f"{scratch}:/scratch"]
        argv += ["-e", "PYTHONPATH=/repo/harness", "-w", "/repo", image]
        argv += ["/opt/sqll/harness-venv/bin/python", "scripts/s3/speed_profile.py"]
        argv += ["time-inside", "--scratch", "/scratch", "--session", str(k)]
        argv += ["--phases"] if k == 1 else []
        st.run(
            f"session {k}",
            argv,
            ROOT,
            log=scratch / "logs" / f"session-{k}.log",
            timeout=4 * 3600,
        )
        load_after = probe.read_load()
        if load_after[1] > probe.MAX_SESSION_LOAD:
            raise DataError(
                f"session {k}: the 5-minute load average after the session is "
                f"{load_after[1]}: other processes ran during the serial session"
            )
        records.append(
            {
                "session": k,
                "role": "controlled" if k == 1 else "noise",
                "started": started,
                "finished": probe.now(),
                "load": {
                    "before": load_before,
                    "after": load_after,
                    "idle_wait_s": waited,
                },
                "report": compact(
                    json.loads((scratch / f"session-{k}.json").read_text("utf8"))
                ),
            }
        )
    phases = json.loads((scratch / "phases.json").read_text("utf8"))
    st.run(
        "check the submodule after",
        [ROOT / "scripts" / "check-submodule", "after the T14 sessions"],
        ROOT,
    )
    return {
        "kind": "sqll-s3-speed-profile-sessions",
        "command": COMMAND_LINES["time"] + " --scratch $SCRATCH",
        "method": {
            "text": "harness/bench.md (the S2 baseline method): the CI image in "
            "docker, a new container for each session, serial, no network, no other "
            "load; the full profile; the tools run in turn for each repeat "
            "(timer.run_in_turn). Session 1 is the controlled session; sessions 2 to "
            f"{sessions} measure the noise. After the timed runs of session 1, "
            f"each sqll input runs {PHASE_RUNS} times with --timings.",
            "image": image,
            "image_id": image_id,
            "docker": docker_version,
            "host": bench_report.machine(),
            "machine_lock": "the command ran under flock /tmp/sqll-machine.lock "
            "(PROCESS.md, rule 7)",
            "load_rule": f"each session starts when the 1-minute load average is "
            f"below {probe.IDLE_LOAD}; after it, the 5-minute load average must be "
            f"at most {probe.MAX_SESSION_LOAD}",
        },
        "sqll": {
            "version": build["version"],
            "source_sha256": build["source_sha256"],
            "binary_sha256": probe.sha256_file(binary),
        },
        "steps": st.entries,
        "sessions": records,
        "phases": {"runs": PHASE_RUNS, "samples": phases},
    }


# The session data.

SIZE_ORDER = {"small": 0, "medium": 1, "large": 2}


def group_of(bid: str) -> str:
    parts = bid.split("/")
    return "start" if parts[0] == "start" else f"parse/{parts[2]}"


def bench_input(bid: str) -> str:
    parts = bid.split("/")
    return "start" if parts[0] == "start" else f"{parts[1]}/{parts[2]}"


def sort_key(bid: str) -> tuple:
    parts = bid.split("/")
    size = SIZE_ORDER.get(parts[2], -1) if len(parts) == 3 else -1
    return (COMMANDS.index(parts[0]), size, parts[1])


def medians(report: dict) -> dict[tuple[str, str], float | None]:
    return {
        (r["id"], r["tool"]): (
            r["stats"]["wall_s"]["median"] if r["status"] == VALID else None
        )
        for r in report["results"]
    }


def statuses(report: dict) -> dict[tuple[str, str], str]:
    return {(r["id"], r["tool"]): r["status"] for r in report["results"]}


def rr(x: float | None, digits: int = 4) -> float | None:
    return None if x is None else round(x, digits)


def benchmark_rows(sessions: dict) -> list[dict]:
    """One row for each benchmark: the medians and the ratio of the
    controlled session, and the ratio of each session."""
    reports = [s["report"] for s in sessions["sessions"]]
    first = statuses(reports[0])
    for k, rep in enumerate(reports[1:], start=2):
        if statuses(rep) != first:
            raise DataError(f"session {k} has other statuses than session 1")
    meds = [medians(rep) for rep in reports]
    ids = sorted({bid for bid, tool in first if tool == "sqll"}, key=sort_key)
    if len(ids) != 112:
        raise DataError(f"{len(ids)} benchmarks, not 112")
    rows = []
    for bid in ids:
        if first[(bid, "sqll")] != VALID:
            raise DataError(f"{bid}: sqll is {first[(bid, 'sqll')]}")
        ratios = []
        for m in meds:
            a, b = m[(bid, "sqll")], m.get((bid, "sqruff"))
            ratios.append(None if b is None else a / b)
        parts = bid.split("/")
        rows.append(
            {
                "id": bid,
                "command": parts[0],
                "dialect": parts[1],
                "size": parts[2] if len(parts) == 3 else None,
                "sqll_s": meds[0][(bid, "sqll")],
                "sqruff_s": meds[0].get((bid, "sqruff")),
                "sqruff_status": first.get((bid, "sqruff")),
                "ratio": rr(ratios[0]),
                "session_ratios": [rr(x) for x in ratios],
            }
        )
    return rows


# profile

PROFILE_TOP = 15
# callgrind_annotate: "<Ir> (<share>%)  <file>:<function> [<object>]".
ANNOTATE_LINE = re.compile(
    r"^\s*([\d,]+)\s+\(\s*([\d.]+)%\)\s+(.+?)(?:\s+\[(.+)\])?\s*$"
)
# The cost classes of a function (self cost), in this order: the first
# pattern that matches the function name gives its class.
COST_CLASSES = (
    (
        "allocation",
        r"malloc|free|realloc|calloc|memcpy|memmove|memset|_int_|"
        r"alloc::alloc|alloc::raw_vec|__rust_(alloc|dealloc|realloc)|cfree",
    ),
    ("drop", r"drop_in_place"),
    ("hashing", r"hashbrown|core::hash|foldhash|ahash|Hasher|hash_one|BuildHasher"),
    ("regex", r"regex_automata|regex_syntax|regex::|fancy_regex|aho_corasick|memchr"),
    ("output", r"serde_json|serde_yaml|serde::|output::|PythonFormatter|as_record"),
    ("lexer", r"sqll_lexer::|sqlfluffrs_lexer::|LexMatcher|lexer::"),
    ("parser", r"sqll_parser::|sqlfluffrs_parser::|sqll_types::|sqlfluffrs_types::"),
    ("dialect_tables", r"sqll_dialects::|sqlfluffrs_dialects::|once_cell|Lazy"),
    ("process", r"_dl_|ld-linux|__libc_start|_start$|dl_main|mmap|clone|pthread"),
)


def worst(sessions: dict) -> list[str]:
    """The benchmarks to profile: in the controlled session, the worst start
    benchmark, the worst parse benchmark of each size, and the second and
    third worst parse/large (by the sqll/sqruff ratio)."""
    rows = [r for r in benchmark_rows(sessions) if r["ratio"] is not None]
    out = []
    for group in ("start", "parse/small", "parse/medium", "parse/large"):
        members = sorted(
            (r for r in rows if group_of(r["id"]) == group),
            key=lambda r: (-r["ratio"], r["id"]),
        )
        out += [r["id"] for r in members[: 3 if group == "parse/large" else 1]]
    return out


def annotate(path: Path, inclusive: bool) -> tuple[int, list[dict]]:
    proc = subprocess.run(
        [
            "callgrind_annotate",
            f"--inclusive={'yes' if inclusive else 'no'}",
            "--threshold=100",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    total, rows = None, []
    for line in proc.stdout.splitlines():
        m = re.match(r"^\s*([\d,]+)\s+\(100\.0%\)\s+PROGRAM TOTALS", line)
        if m:
            total = int(m[1].replace(",", ""))
            continue
        m = ANNOTATE_LINE.match(line)
        if m and total is not None:
            where = m[3]
            function = where.split(":", 1)[1] if ":" in where else where
            rows.append({"function": function, "ir": int(m[1].replace(",", ""))})
    if total is None:
        raise DataError(f"no PROGRAM TOTALS in callgrind_annotate of {path}")
    return total, rows


def cost_class(function: str) -> str:
    for name, pattern in COST_CLASSES:
        if re.search(pattern, function):
            return name
    return "other"


def profile(scratch: Path) -> dict:
    scratch = scratch.absolute()
    sessions = json.loads(SESSIONS_FILE.read_text("utf8"))
    chosen = worst(sessions)
    st = probe.Steps(scratch)
    target = scratch / "target-profile"
    env = {
        "CARGO_TARGET_DIR": str(target),
        "CARGO_PROFILE_RELEASE_DEBUG": "line-tables-only",
        "CARGO_PROFILE_RELEASE_STRIP": "none",
        "SQLL_TABLES_DIR": str(ROOT / "target" / "sqll-tables"),
    }
    st.run(
        "symbol build",
        ["cargo", "build", "--release", "--locked", "-p", "sqll"],
        ROOT,
        set_env=env,
        log=scratch / "logs" / "build.log",
    )
    binary = target / "release" / "sqll"
    build = json.loads(
        st.run("build record", [binary, "version", "--build"], ROOT).stdout
    )
    if build["source_sha256"] != sessions["sqll"]["source_sha256"]:
        raise DataError("the symbol build is not of the source of the sessions")
    release = sqll_adapter.binary_path()
    inputs = scratch / "inputs"
    bench_run.build_inputs(SQLFLUFF_ROOT, bench_definitions.load(), inputs)
    valgrind = st.run(
        "valgrind version", ["valgrind", "--version"], ROOT
    ).stdout.strip()
    out = []
    for bid in chosen:
        dialect, name = bid.split("/")[1], bench_input(bid)
        sql = inputs / f"{name}.sql"
        argv = ["parse", "-f", "json", "--dialect", dialect, sql]
        same = (
            st.run(f"{bid}: symbol build", [binary, *argv], ROOT).stdout
            == st.run(f"{bid}: release build", [release, *argv], ROOT).stdout
        )
        if not same:
            raise DataError(f"{bid}: the symbol build gives another output")
        cg = scratch / "callgrind" / f"{bid.replace('/', '-')}.out"
        cg.parent.mkdir(parents=True, exist_ok=True)
        st.run(
            f"{bid}: callgrind",
            [
                "valgrind",
                "--tool=callgrind",
                f"--callgrind-out-file={cg}",
                binary,
                *argv,
            ],
            ROOT,
            log=scratch / "logs" / f"{bid.replace('/', '-')}.log",
        )
        total, self_rows = annotate(cg, inclusive=False)
        _, incl_rows = annotate(cg, inclusive=True)
        classes: dict[str, int] = {}
        for r in self_rows:
            c = cost_class(r["function"])
            classes[c] = classes.get(c, 0) + r["ir"]
        classes["below_threshold"] = total - sum(r["ir"] for r in self_rows)
        out.append(
            {
                "id": bid,
                "total_ir": total,
                "self_top": self_rows[:PROFILE_TOP],
                "inclusive_top": incl_rows[:PROFILE_TOP],
                "self_classes": dict(sorted(classes.items(), key=lambda kv: -kv[1])),
            }
        )
    return {
        "kind": "sqll-s3-speed-profile-callgrind",
        "command": COMMAND_LINES["profile"] + " --scratch $SCRATCH",
        "method": "valgrind callgrind (instruction counts, Ir) of one run of the "
        "symbol build on the input of each benchmark. The symbol build is the "
        "source of the sessions, built with debug line tables and no strip "
        "(CARGO_PROFILE_RELEASE_DEBUG=line-tables-only, "
        "CARGO_PROFILE_RELEASE_STRIP=none); its output is the output of the "
        "release build. Self cost: the instructions of the function itself; "
        "inclusive: with its callees. The cost classes (COST_CLASSES of the "
        "script) group the functions of the self cost by name.",
        "valgrind": valgrind,
        "host": bench_report.machine(),
        "sqll_source_sha256": build["source_sha256"],
        "chosen": chosen,
        "cost_classes": {name: pattern for name, pattern in COST_CLASSES},
        "steps": st.entries,
        "benchmarks": out,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="speed_profile.py")
    sub = p.add_subparsers(dest="command", required=True)
    t = sub.add_parser("time", help="The sessions of sqll and sqruff in docker.")
    t.add_argument("--scratch", type=Path, required=True)
    t.add_argument("--image", default=None, help="Default: sqll-ci:<ci/image_tag.py>.")
    t.add_argument("--sessions", type=int, default=SESSIONS)
    ti = sub.add_parser("time-inside", help="(In the CI image) one session.")
    ti.add_argument("--scratch", type=Path, required=True)
    ti.add_argument("--session", type=int, required=True)
    ti.add_argument("--phases", action="store_true")
    pr = sub.add_parser("profile", help="callgrind of the worst benchmarks.")
    pr.add_argument("--scratch", type=Path, required=True)
    r = sub.add_parser("report", help="Write OUT_FILE from the committed files.")
    r.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.command == "time":
            record = time_sessions(args.scratch, args.image, args.sessions)
            SESSIONS_FILE.write_text(dump(record), encoding="utf8")
            print(f"wrote {probe.rel(SESSIONS_FILE)}")
        elif args.command == "time-inside":
            time_inside(args.scratch, args.session, args.phases)
        elif args.command == "profile":
            record = profile(args.scratch)
            PROFILE_FILE.write_text(dump(record), encoding="utf8")
            print(f"wrote {probe.rel(PROFILE_FILE)}")
        else:
            text = dump(make_report())
            if args.check:
                if not OUT_FILE.exists() or OUT_FILE.read_text("utf8") != text:
                    print(f"{probe.rel(OUT_FILE)} is not the report of the inputs")
                    return 1
                print(f"{probe.rel(OUT_FILE)} is up to date")
            else:
                OUT_FILE.write_text(text, encoding="utf8")
                print(f"wrote {probe.rel(OUT_FILE)}")
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
