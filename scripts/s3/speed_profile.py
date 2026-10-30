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
        if b["tool"] != "sqll":
            continue
        argv = [str(binary), "parse", "-f", "json", "--timings"]
        argv += ["--dialect", b["dialect"], str(inputs_dir / f"{b['input']}.sql")]
        samples = []
        for _ in range(PHASE_RUNS):
            proc = subprocess.run(
                argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=env
            )
            if proc.returncode != 0:
                raise DataError(f"{b['id']}: sqll gave exit code {proc.returncode}")
            samples.append(json.loads(proc.stderr.strip().splitlines()[-1]))
        out[b["id"]] = samples
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
        raise DataError("out/sqll/bin/sqll is not a fresh build. Run scripts/build-sqll.")
    image = image or probe.ci_image()
    st = probe.Steps(scratch)
    image_id = st.run(
        "CI image id", ["docker", "image", "inspect", "--format", "{{.Id}}", image], ROOT
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
                "load": {"before": load_before, "after": load_after, "idle_wait_s": waited},
                "report": json.loads((scratch / f"session-{k}.json").read_text("utf8")),
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
