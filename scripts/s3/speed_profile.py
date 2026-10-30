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
import concurrent.futures
import json
import math
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
GROUPS = ("start", "parse/small", "parse/medium", "parse/large")


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
PROFILE_JOBS = 4
# The phases that the profile collects alone (valgrind --toggle-collect):
# the cost of each call of the function and its callees. Each function is
# not recursive, and each run calls it once.
PROFILE_PHASES = {
    "setup": "*Dialect>::get_lexers",
    "lex": "*Lexer>::lex",
    "parse": "*Parser>::root_parse",
}
# callgrind_annotate: "<Ir> (<share>%)  <file>:<function> [<object>]".
ANNOTATE_LINE = re.compile(
    r"^\s*([\d,]+)\s+\(\s*([\d.]+)%\)\s+(.+?)(?:\s+\[(.+)\])?\s*$"
)
TOTALS_LINE = re.compile(r"^\s*([\d,]+)\s+\(100\.0%\)\s+PROGRAM TOTALS")
# A recursion level of a function in callgrind ("f'2").
RECURSION = re.compile(r"'\d+$")
# The cost classes of a function (self cost), in this order: the first
# pattern that matches the function name gives its class.
COST_CLASSES = (
    (
        "copy",
        r"^__mem(cpy|move|set)|^mem(cpy|move|set)|"
        r"^<alloc::(string::String|vec::Vec<[^>]*>) as core::clone::Clone>::clone$",
    ),
    (
        "allocator",
        r"^(malloc|free|realloc|calloc|cfree|_int_malloc|_int_free\w*|"
        r"_int_realloc|malloc_consolidate|unlink_chunk\S*|tcache\w*|"
        r"alloc_perturb|_mid_memalign\S*|_int_memalign|posix_memalign|__rustc::__rd[lg]_\w+|__rustc::__rust_\w*alloc\w*|"
        r"<alloc::raw_vec::RawVecInner(<_>)?>::\w+.*)$",
    ),
    ("drop", r"drop_glue|drop_in_place"),
    ("hashing", r"hashbrown|core::hash|foldhash|ahash|Hasher|hash_one"),
    ("regex", r"regex_automata|regex_syntax|regex::|fancy_regex|aho_corasick|memchr"),
    ("output", r"serde_json|serde_yaml|serde::|sqll::output|as_record"),
    ("lexer", r"sqll_lexer::|LexMatcher|::lexer::"),
    ("parser", r"sqll_parser::|sqll_types::"),
    ("dialect_tables", r"sqll_dialects::|once_cell"),
    ("loader", r"^_dl_|^dl_|_dl_relocate|^__libc_start|^_start$"),
)


def worst(sessions: dict) -> list[str]:
    """The benchmarks with the top functions in the record: in the
    controlled session, the worst start benchmark, the worst parse benchmark
    of each size, and the second and third worst parse/large (by R)."""
    rows = [r for r in benchmark_rows(sessions) if r["ratio"] is not None]
    out = []
    for group in GROUPS:
        members = sorted(
            (r for r in rows if group_of(r["id"]) == group),
            key=lambda r: (-r["ratio"], r["id"]),
        )
        out += [r["id"] for r in members[: 3 if group == "parse/large" else 1]]
    return out


def annotate_text(text: str) -> tuple[int, dict[str, int]]:
    """The program total and the cost of each function (summed over the
    files of the function) of callgrind_annotate --auto=no output."""
    total, costs, in_table = None, {}, False
    for line in text.splitlines():
        m = TOTALS_LINE.match(line)
        if m:
            total = int(m[1].replace(",", ""))
            continue
        if line.startswith("Ir") and "file:function" in line:
            in_table = True
            continue
        if not in_table or not line.strip() or line.startswith("-"):
            continue
        if line.split()[0] == ".":
            continue
        m = ANNOTATE_LINE.match(line)
        if not m:
            raise DataError(f"not a callgrind_annotate line: {line!r}")
        where = m[3]
        function = where.split(":", 1)[1] if ":" in where else where
        costs[function] = costs.get(function, 0) + int(m[1].replace(",", ""))
    if total is None:
        raise DataError("no PROGRAM TOTALS in the callgrind_annotate output")
    return total, costs


def annotate(path: Path, inclusive: bool) -> tuple[int, dict[str, int]]:
    proc = subprocess.run(
        [
            "callgrind_annotate",
            "--auto=no",
            f"--inclusive={'yes' if inclusive else 'no'}",
            "--threshold=100",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return annotate_text(proc.stdout)


def cost_class(function: str) -> str:
    for name, pattern in COST_CLASSES:
        if re.search(pattern, function):
            return name
    return "other"


def self_by_function(costs: dict[str, int]) -> dict[str, int]:
    """Self costs with the recursion levels of a function added together."""
    out: dict[str, int] = {}
    for function, ir in costs.items():
        name = RECURSION.sub("", function)
        out[name] = out.get(name, 0) + ir
    return out


def classes_of(total: int, costs: dict[str, int]) -> dict[str, float]:
    sums = {name: 0 for name, _ in COST_CLASSES} | {"other": 0}
    for function, ir in costs.items():
        sums[cost_class(function)] += ir
    missing = total - sum(sums.values())
    if abs(missing) > total * 0.001:
        raise DataError(f"the functions give {total - missing} of {total} Ir")
    return {name: rr(ir / total) for name, ir in sums.items()}


def top(total: int, costs: dict[str, int]) -> list[dict]:
    rows = sorted(costs.items(), key=lambda kv: (-kv[1], kv[0]))[:PROFILE_TOP]
    return [{"function": f, "ir": ir, "share": rr(ir / total)} for f, ir in rows]


def callgrind(binary: Path, argv: list, out: Path, toggle: str | None) -> list[str]:
    cmd = ["valgrind", "--tool=callgrind", f"--callgrind-out-file={out}"]
    cmd += [f"--toggle-collect={toggle}"] if toggle else []
    return [*cmd, str(binary), *[str(a) for a in argv]]


def profile_one(
    st: probe.Steps, binary: Path, inputs: Path, bid: str, folder: Path, full: bool
) -> dict:
    dialect = bid.split("/")[1]
    argv = [
        "parse",
        "-f",
        "json",
        "--dialect",
        dialect,
        inputs / f"{bench_input(bid)}.sql",
    ]
    stem = bid.replace("/", "-")
    entry: dict[str, Any] = {"id": bid}
    runs = {"all": None, **PROFILE_PHASES}
    for phase, toggle in runs.items():
        out = folder / f"{stem}.{phase}.out"
        cmd = callgrind(binary, argv, out, toggle)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        st.entries.append(
            {
                "step": f"{bid}: callgrind {phase}",
                "argv": [st.show(a) for a in cmd],
                "exit_code": proc.returncode,
            }
        )
        if proc.returncode != 0:
            raise DataError(f"{bid}: callgrind {phase}: exit code {proc.returncode}")
        total, self_costs = annotate(out, inclusive=False)
        self_costs = self_by_function(self_costs)
        record = {"ir": total, "classes": classes_of(total, self_costs)}
        if full:
            record["self_top"] = top(total, self_costs)
            if phase == "all":
                _, incl = annotate(out, inclusive=True)
                record["inclusive_top"] = top(total, incl)
        entry[phase] = record
    return entry


def profile(scratch: Path) -> dict:
    scratch = scratch.absolute()
    sessions = json.loads(SESSIONS_FILE.read_text("utf8"))
    rows = benchmark_rows(sessions)
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
    for r in rows:
        dialect = r["dialect"]
        argv = ["parse", "-f", "json", "--dialect", dialect]
        argv.append(inputs / f"{bench_input(r['id'])}.sql")
        a = subprocess.run([binary, *argv], capture_output=True)
        b = subprocess.run([release, *argv], capture_output=True)
        if (a.stdout, a.returncode) != (b.stdout, b.returncode):
            raise DataError(f"{r['id']}: the symbol build gives another output")
    st.entries.append(
        {
            "step": "the symbol build and the release build give the same stdout and "
            f"exit code on the {len(rows)} inputs",
            "exit_code": 0,
        }
    )
    folder = scratch / "callgrind"
    folder.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(PROFILE_JOBS) as pool:
        futures = [
            pool.submit(
                profile_one,
                probe.Steps(scratch),
                binary,
                inputs,
                r["id"],
                folder,
                r["id"] in chosen,
            )
            for r in rows
        ]
        out = [f.result() for f in futures]
    return {
        "kind": "sqll-s3-speed-profile-callgrind",
        "command": COMMAND_LINES["profile"] + " --scratch $SCRATCH",
        "method": "valgrind callgrind: the instruction count (Ir) of one run of "
        "the symbol build on the input of each benchmark; for each phase of "
        "PROFILE_PHASES, one more run that collects only the cost of that "
        "function and its callees (--toggle-collect). The symbol build is the "
        "source of the sessions with debug line tables and no strip "
        "(CARGO_PROFILE_RELEASE_DEBUG=line-tables-only, "
        "CARGO_PROFILE_RELEASE_STRIP=none); its stdout and exit code are those of "
        "the release build on each input. Self cost: the instructions of the "
        "function itself, summed over its files and recursion levels. The cost "
        "classes (COST_CLASSES) group the self costs by function name. "
        "Inclusive cost: with the callees; a recursive function can have more "
        "than 100%. Limit: Ir is not time (a cache miss costs time, not "
        "instructions); the estimates use Ir shares as time shares.",
        "valgrind": valgrind,
        "host": bench_report.machine(),
        "sqll_source_sha256": build["source_sha256"],
        "phases": PROFILE_PHASES,
        "cost_classes": {name: pattern for name, pattern in COST_CLASSES},
        "worst": chosen,
        "steps": st.entries,
        "benchmarks": out,
    }


# report

FORMULAS = {
    "ratio": "R = T / S: T and S are the median wall times of sqll and sqruff on "
    "the benchmark in the controlled session (session 1).",
    "spread": "the spread of a benchmark: the largest R of the sessions divided "
    "by the smallest R of the sessions, minus 1.",
    "margin": "m = the largest spread of a benchmark with a sqruff pair, rounded "
    "up to 0.01. Thus, in the sessions that were measured, R of one session is "
    "at most (1 + m) times R of another session.",
    "target": "R < 1 / (1 + m) for each start and parse benchmark with a sqruff "
    "pair, in one controlled session. Then another controlled session gives "
    "R < 1 (G3.5), as far as the measured noise shows.",
    "needed_factor": "F = max(1, R * (1 + m)): T must become T / F or less.",
    "phases": "the median of each phase of the --timings runs of session 1 "
    "(seconds), and total, the sum of these medians.",
    "outside_fixed": "the time outside main of the dialect: T - total of the "
    "start benchmark of the same dialect, at least 0 (process start and exit, "
    "the loader, and the timer). The start benchmark has no other cost.",
    "phase_time": "the phases as parts of T: each phase * k, with k = (T - "
    "outside_fixed) / total. Thus the phases and outside_fixed add up to T. "
    "Reason: the --timings runs are not the timed runs (k is from "
    "{k_min} to {k_max}).",
    "removable": "the cost that a class can remove (seconds), from the phase "
    "times and the Ir shares of the profile of the phase (classes).",
    "gain": "the gain of a class = r * removable. central: the r of the class; "
    "upper: r = 1 (all of the removable cost goes).",
    "estimate": "T_est = T - the sum of the gains; the reachable factor "
    "A = T / T_est (central and upper).",
    "lex_parse_factor": "the T6 formula speedup with the margin: k = LP / "
    "(S / (1 + m) - (T - LP)), LP = lex + parse of the phase times. With m = 0 "
    "it is the T6 formula. Unreachable if S / (1 + m) <= T - LP.",
    "break_even_r": "the largest, over the benchmarks with a sqruff pair, of the "
    "smallest r (the same r for each class with r < 1 in CLASSES) that gives "
    "A >= F. in_reach_central_no_margin: the benchmarks where the central A >= "
    "max(1, R), thus with m = 0.",
    "go": "go if the central A >= F for each start and parse benchmark with a "
    "sqruff pair; else no-go (status/S3.md, Stop rule).",
}

# The improvement classes. removable(row) gives the seconds; r is the central
# fraction of it that the class removes (an estimate; "basis" gives the
# reason). The upper bound uses r = 1.
CLASSES = (
    {
        "id": "exit_without_free",
        "task": "T15",
        "what": "Exit with no drop of the parser, the tokens, the tree, and the "
        "record: the operating system frees the memory of the process.",
        "removable": "free",
        "r": 1.0,
        "basis": "measured phase free; the change removes all of it.",
    },
    {
        "id": "direct_output",
        "task": "T15",
        "what": "Write the JSON from the parse tree, with no serde_yaml_ng Value "
        "record between them.",
        "removable": "max(0, record - write)",
        "r": 1.0,
        "basis": "measured phases: the record phase goes; a walk of the tree "
        "that writes the JSON stays, at the cost of the write phase.",
    },
    {
        "id": "lexer_tables",
        "task": "T15",
        "what": "Set up the lexer tables of the dialect at less cost: no clone of "
        "the matcher list, and only the regexes that the run uses.",
        "removable": "setup",
        "r": 0.5,
        "basis": "measured phase setup; regex compile is the largest class of its "
        "profile. r = 0.5: an assumption (T15 measures it).",
    },
    {
        "id": "process_start",
        "task": "T15",
        "what": "Less work outside main: fewer relocations of the static tables "
        "(74k relocations of a position-independent binary), fewer page faults.",
        "removable": "max(0, outside_fixed - timer overhead)",
        "r": 0.5,
        "basis": "measured: outside_fixed, and the timer overhead (/bin/true) of "
        "the session. r = 0.5: an assumption.",
    },
    {
        "id": "command_init",
        "task": "T15",
        "what": "Less work from main to the file read (the command thread with a "
        "256 MiB stack, the arguments, the file).",
        "removable": "init",
        "r": 0.5,
        "basis": "measured phase init. r = 0.5: an assumption.",
    },
    {
        "id": "parse_allocation_copy",
        "task": "T16",
        "what": "Fewer allocations, frees, drops, and copies in the parser: frames "
        "and match results by index or in an arena, with no move of large values "
        "and no clone of strings.",
        "removable": "parse * (copy + allocator + drop shares of the parse profile)",
        "r": 0.5,
        "basis": "the parse profile: memcpy, malloc and free, and drops. r = 0.5: "
        "an assumption (Ir is not time; a part of the work stays).",
    },
    {
        "id": "parse_hashing",
        "task": "T16",
        "what": "A faster hash for the parse cache (SipHash now).",
        "removable": "parse * hashing share of the parse profile",
        "r": 0.5,
        "basis": "the parse profile. r = 0.5: an assumption.",
    },
    {
        "id": "lex_allocation_copy",
        "task": "T16",
        "what": "Fewer allocations, frees, drops, and copies in the lexer.",
        "removable": "lex * (copy + allocator + drop shares of the lex profile)",
        "r": 0.5,
        "basis": "the lex profile. r = 0.5: an assumption.",
    },
    {
        "id": "lex_regex",
        "task": "T16",
        "what": "Less regex work in the lexer: direct matchers for the frequent "
        "token types.",
        "removable": "lex * regex share of the lex profile",
        "r": 0.5,
        "basis": "the lex profile. r = 0.5: an assumption.",
    },
)
NOT_ESTIMATED = (
    "The own instructions of the parser (class parser of the parse profile) and "
    "changes of the parse algorithm have no estimate: no class gives them a gain."
)
REMOVABLE_CLASSES = ("copy", "allocator", "drop")


def spread(ratios: list[float | None]) -> float | None:
    values = [x for x in ratios if x is not None]
    if not values:
        return None
    return max(values) / min(values) - 1


def ceil2(x: float) -> float:
    return math.ceil(round(x * 100, 6)) / 100


def noise(rows: list[dict], sessions: dict) -> dict:
    """The spread of R between the sessions, and of the median wall time of
    each tool between the sessions."""
    reports = [s["report"] for s in sessions["sessions"]]
    meds = [medians(rep) for rep in reports]
    paired = [r for r in rows if r["ratio"] is not None]
    by_group: dict[str, dict] = {}
    for group in GROUPS:
        members = [r for r in paired if group_of(r["id"]) == group]
        spreads = sorted(spread(r["session_ratios"]) for r in members)
        tools = {}
        for tool in TOOLS:
            ts = sorted(spread([m[(r["id"], tool)] for m in meds]) for r in members)
            tools[tool] = {"median": rr(statistics.median(ts)), "max": rr(max(ts))}
        by_group[group] = {
            "benchmarks": len(members),
            "ratio_spread": {
                "median": rr(statistics.median(spreads)),
                "p90": rr(spreads[math.ceil(0.9 * len(spreads)) - 1]),
                "max": rr(spreads[-1]),
            },
            "time_spread": tools,
        }
    widest = max(paired, key=lambda r: (spread(r["session_ratios"]), r["id"]))
    largest = spread(widest["session_ratios"])
    return {
        "sessions": len(reports),
        "by_group": by_group,
        "largest_spread": {"id": widest["id"], "spread": rr(largest)},
        "margin": ceil2(largest),
        "formula": "margin",
    }


def phase_medians(samples: list[dict]) -> dict:
    out = {p: statistics.median(s[f"{p}_s"] for s in samples) for p in PHASES}
    out["total"] = sum(out[p] for p in PHASES)
    return out


def removable(row: dict, cls: dict, timer_overhead: float, shares_of) -> float:
    ph = row["phase_time"]
    q = shares_of(row["id"])
    match cls["id"]:
        case "exit_without_free":
            return ph["free"]
        case "direct_output":
            return max(0.0, ph["record"] - ph["write"])
        case "lexer_tables":
            return ph["setup"]
        case "process_start":
            return max(0.0, ph["outside_fixed"] - timer_overhead)
        case "command_init":
            return ph["init"]
        case "parse_allocation_copy":
            return ph["parse"] * sum(q["parse"][c] for c in REMOVABLE_CLASSES)
        case "parse_hashing":
            return ph["parse"] * q["parse"]["hashing"]
        case "lex_allocation_copy":
            return ph["lex"] * sum(q["lex"][c] for c in REMOVABLE_CLASSES)
        case "lex_regex":
            return ph["lex"] * q["lex"]["regex"]
    raise DataError(f"no formula for class {cls['id']}")


def break_even_r(row: dict) -> float:
    """The smallest r of the classes with r < 1 that gives A >= F (the
    classes with r = 1 keep it). 0 if they are not necessary."""
    t, f = row["sqll_s"], row["needed_factor"]
    gains = row["estimate"]["gains"]
    fixed = sum(gains[c["id"]]["removable_s"] for c in CLASSES if c["r"] == 1.0)
    variable = sum(gains[c["id"]]["removable_s"] for c in CLASSES if c["r"] < 1.0)
    need = t - t / f - fixed
    return 0.0 if need <= 0 else need / variable


def lex_parse_factor(row: dict, margin: float) -> float | str | None:
    if row["sqruff_s"] is None:
        return None
    t, s = row["sqll_s"], row["sqruff_s"] / (1 + margin)
    if t <= s:
        return None
    lp = row["phase_time"]["lex"] + row["phase_time"]["parse"]
    room = s - (t - lp)
    return "unreachable" if room <= 0 else rr(lp / room)


def _factors(values: list) -> dict:
    nums = sorted(v for v in values if isinstance(v, float))
    return {
        "needed": len([v for v in values if v is not None]),
        "median_factor": rr(statistics.median(nums)) if nums else None,
        "max_factor": rr(max(nums)) if nums else None,
        "unreachable": sum(v == "unreachable" for v in values),
    }


def check_inputs(sessions: dict, prof: dict) -> None:
    want = sqll_adapter.expected_version(ROOT)
    if sessions["sqll"]["version"] != want:
        raise DataError(
            f"the sessions ran sqll {sessions['sqll']['version']}, not {want}"
        )
    if prof["sqll_source_sha256"] != sessions["sqll"]["source_sha256"]:
        raise DataError("the profile is not of the sqll source of the sessions")
    for s in sessions["sessions"]:
        tools = s["report"]["tools"]
        if set(tools) != set(TOOLS):
            raise DataError(f"session {s['session']} has the tools {sorted(tools)}")
        if tools["sqruff"]["version"] != "0.41.0":
            raise DataError(f"session {s['session']}: sqruff version")
        if s["report"]["harness"]["clean"] is not True:
            raise DataError(f"session {s['session']} ran on a changed worktree")


def make_report(
    sessions_path: Path = SESSIONS_FILE,
    profile_path: Path = PROFILE_FILE,
    t6_path: Path = SPEED_BY_BASE_FILE,
) -> dict:
    sessions = json.loads(sessions_path.read_text("utf8"))
    prof = json.loads(profile_path.read_text("utf8"))
    t6 = json.loads(t6_path.read_text("utf8"))
    check_inputs(sessions, prof)
    rows = benchmark_rows(sessions)
    nz = noise(rows, sessions)
    m = nz["margin"]
    control = sessions["sessions"][0]["report"]
    timer_overhead = control["timer"]["overhead"]["stats"]["wall_s"]["median"]
    samples = sessions["phases"]["samples"]
    profiles = {b["id"]: b for b in prof["benchmarks"]}
    if set(profiles) != {r["id"] for r in rows} or set(samples) != set(profiles):
        raise DataError("the profile or the phases do not have each benchmark")

    def shares_of(bid: str) -> dict:
        return {ph: profiles[bid][ph]["classes"] for ph in PROFILE_PHASES}

    raw = {r["id"]: phase_medians(samples[r["id"]]) for r in rows}
    outside_fixed = {
        r["dialect"]: max(0.0, r["sqll_s"] - raw[r["id"]]["total"])
        for r in rows
        if r["command"] == "start"
    }
    ks = []
    for r in rows:
        ph = raw[r["id"]]
        fixed = outside_fixed[r["dialect"]]
        if r["command"] == "start":
            k = 1.0
        else:
            k = (r["sqll_s"] - fixed) / ph["total"]
            ks.append(k)
        r["phases"] = {p: rr(ph[p], 6) for p in (*PHASES, "total")}
        r["phases"]["tokens"] = samples[r["id"]][0]["tokens"]
        r["phase_time"] = {p: ph[p] * k for p in PHASES} | {"outside_fixed": fixed}
        r["k"] = k
    for r in rows:
        pt = r["phase_time"]
        r["shares"] = {p: rr(v / r["sqll_s"]) for p, v in pt.items()}
        r["needed_factor"] = (
            None
            if r["ratio"] is None
            else rr(max(1.0, r["sqll_s"] / r["sqruff_s"] * (1 + m)))
        )
        gains = {}
        for cls in CLASSES:
            rem = removable(r, cls, timer_overhead, shares_of)
            gains[cls["id"]] = {
                "removable_s": rr(rem, 6),
                "central_s": rr(cls["r"] * rem, 6),
            }
        central = sum(cls["r"] * gains[cls["id"]]["removable_s"] for cls in CLASSES)
        upper = sum(g["removable_s"] for g in gains.values())
        t = r["sqll_s"]
        r["estimate"] = {
            "formula": "estimate",
            "gains": gains,
            "central": {"time_s": rr(t - central, 6), "factor": rr(t / (t - central))},
            "upper": {"time_s": rr(t - upper, 6), "factor": rr(t / (t - upper))},
        }
        if r["needed_factor"] is not None:
            f = r["needed_factor"]
            r["in_reach"] = {
                "central": t / (t - central) >= f,
                "upper": t / (t - upper) >= f,
            }
        r["lex_parse_factor"] = {
            "margin": lex_parse_factor(r, m),
            "no_margin": lex_parse_factor(r, 0.0),
        }
        r["phase_time"] = {p: rr(v, 6) for p, v in pt.items()}
        r["k"] = rr(r["k"])
        q = profiles[r["id"]]
        r["profile"] = {
            "ir": {ph: q[ph]["ir"] for ph in ("all", *PROFILE_PHASES)},
            "classes": {ph: q[ph]["classes"] for ph in ("all", *PROFILE_PHASES)},
        }
    paired = [r for r in rows if r["needed_factor"] is not None]
    groups = {}
    for group in (*GROUPS, "all"):
        members = [r for r in paired if group == "all" or group_of(r["id"]) == group]
        groups[group] = {
            "benchmarks": len(members),
            "ratio": {
                "median": rr(statistics.median(r["ratio"] for r in members)),
                "max": max(r["ratio"] for r in members),
            },
            "below_target": sum(r["ratio"] < 1 / (1 + m) for r in members),
            "needed_factor": {
                "median": rr(statistics.median(r["needed_factor"] for r in members)),
                "max": max(r["needed_factor"] for r in members),
            },
            "reachable_factor_central": {
                "median": rr(
                    statistics.median(
                        r["estimate"]["central"]["factor"] for r in members
                    )
                ),
                "min": min(r["estimate"]["central"]["factor"] for r in members),
            },
            "in_reach": {
                kind: sum(r["in_reach"][kind] for r in members)
                for kind in ("central", "upper")
            },
            "mean_shares": {
                p: rr(statistics.mean(r["shares"][p] for r in members))
                for p in (*PHASES, "outside_fixed")
            },
        }
    out_central = [r["id"] for r in paired if not r["in_reach"]["central"]]
    no_margin = sum(
        r["estimate"]["central"]["factor"] >= max(1.0, r["ratio"]) for r in paired
    )
    r_star = max(break_even_r(r) for r in paired)
    out_upper = [r["id"] for r in paired if not r["in_reach"]["upper"]]
    parse_rows = [r for r in paired if r["command"] == "parse"]
    t6_parse = t6["bases"]["sqlfluffrs"]["lex_parse_speedup"]["parse"]
    go = not out_central
    worst_rows = sorted(paired, key=lambda r: (-r["needed_factor"], r["id"]))[:5]
    reason = (
        f"The central estimate reaches the needed factor F on "
        f"{len(paired) - len(out_central)} of {len(paired)} benchmarks; the upper "
        f"bound (r = 1 for each class) on {len(paired) - len(out_upper)}. "
    )
    reason += (
        "Thus the target is in reach."
        if go
        else f"Not in reach (central): {len(out_central)} benchmarks, the largest F: "
        + ", ".join(
            f"{r['id']} F {r['needed_factor']}, A {r['estimate']['central']['factor']}"
            for r in worst_rows
        )
        + ". Human decision needed (status/S3.md, Stop rule)."
    )
    k_values = [rr(k, 2) for k in ks]
    formulas = dict(FORMULAS)
    formulas["phase_time"] = formulas["phase_time"].format(
        k_min=min(k_values), k_max=max(k_values)
    )
    return {
        "kind": "sqll-s3-speed-profile",
        "task": "T14",
        "about": "Parse speed, part 1: the speed of sqll and sqruff on the 28 start "
        "and 84 parse benchmarks, the noise and the margin, the target, the phase "
        "times, the profile, the improvement classes, and the go or no-go. Each "
        "value is measured (the session and profile files), or derived or "
        "estimated with a formula of 'formulas'.",
        "command": COMMAND_LINES["report"],
        "inputs": {
            probe.rel(p): probe.sha256_file(p)
            for p in (sessions_path, profile_path, t6_path)
        },
        "method": {
            "sessions": sessions["method"]["text"],
            "profile": prof["method"],
            "image": sessions["method"]["image"],
            "host": sessions["method"]["host"],
            "sqll": sessions["sqll"],
            "sqruff": control["tools"]["sqruff"]["version"],
            "timer_overhead_s": timer_overhead,
        },
        "formulas": formulas,
        "noise": nz,
        "target": {
            "margin": m,
            "ratio_below": rr(1 / (1 + m)),
            "formula": "target",
            "benchmarks": len(paired),
            "no_sqruff_pair": [r["id"] for r in rows if r["needed_factor"] is None],
        },
        "groups": groups,
        "t6_comparison": {
            "t6": {
                "from": "results/s3/speed-by-base.json, "
                "bases.sqlfluffrs.lex_parse_speedup.parse",
                "needed": t6_parse["needed"],
                "median_factor": t6_parse["median_factor"],
                "max_factor": t6_parse["max_factor"],
            },
            "now_no_margin": _factors(
                [r["lex_parse_factor"]["no_margin"] for r in parse_rows]
            ),
            "now_margin": _factors(
                [r["lex_parse_factor"]["margin"] for r in parse_rows]
            ),
            "formula": "lex_parse_factor",
        },
        "classes": [
            {k: v for k, v in c.items()}
            | {
                "gain_s_central": {
                    group: rr(
                        statistics.mean(
                            r["estimate"]["gains"][c["id"]]["central_s"]
                            for r in paired
                            if group == "all" or group_of(r["id"]) == group
                        ),
                        6,
                    )
                    for group in (*GROUPS, "all")
                },
            }
            for c in CLASSES
        ],
        "not_estimated": NOT_ESTIMATED,
        "go": {
            "result": "go" if go else "no-go",
            "formula": "go",
            "reason": reason,
            "not_in_reach_central": out_central,
            "sensitivity": {
                "in_reach_central_no_margin": no_margin,
                "break_even_r": rr(r_star),
                "formula": "break_even_r",
            },
            "not_in_reach_upper": out_upper,
        },
        "profile": {
            "worst": prof["worst"],
            "top": {
                b: {
                    "all": {
                        k: profiles[b]["all"][k]
                        for k in ("ir", "self_top", "inclusive_top")
                    },
                    **{
                        ph: {
                            "ir": profiles[b][ph]["ir"],
                            "self_top": profiles[b][ph]["self_top"],
                        }
                        for ph in PROFILE_PHASES
                    },
                }
                for b in prof["worst"]
            },
        },
        "benchmarks": [
            {
                k: r[k]
                for k in (
                    "id",
                    "sqll_s",
                    "sqruff_s",
                    "sqruff_status",
                    "ratio",
                    "session_ratios",
                    "needed_factor",
                    "phases",
                    "k",
                    "phase_time",
                    "shares",
                    "profile",
                    "estimate",
                    "lex_parse_factor",
                )
            }
            | ({"in_reach": r["in_reach"]} if "in_reach" in r else {})
            for r in rows
        ],
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
