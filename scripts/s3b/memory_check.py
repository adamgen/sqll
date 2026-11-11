"""S3b task C13: the peak memory of "sqll lint" and "sqll fix" on many
files in one process (the allocator note of S3 T17, status/S3.md).

Run it with the harness Python from the repository root, with the machine
lock:

    flock /tmp/sqll-machine.lock uv run --frozen --project harness \
        python scripts/s3b/memory_check.py measure [--binary out/sqll/bin/sqll]

Method:

1. Build the S2 inputs (harness/bench.md) and take the 3 ansi parse inputs
   (small, medium, large).
2. For each count in COPIES, write that many copies of the 3 inputs to a new
   folder (3 x count files), and a config file with
   large_file_skip_byte_limit = 0 (else the large input is skipped).
3. Run sqll on the folder in one process, for each mode of MODES (lint with
   the human and the json format, fix), with the rules CP01, CP03, CP04.
   Each run starts from new copies.
4. Peak memory: the VmHWM of /proc/<pid>/status, read each 5 ms while the
   process runs (the last value before the exit), and ru_maxrss of
   os.wait4. On Linux ru_maxrss also has the RSS of this Python process
   at the start of the child (Core issue #38); the record gives it as the
   floor (the ru_maxrss of /bin/true started the same way).
5. Output: the bytes of stdout of each run (to a file).

The record (RECORD_FILE) has each run and the ratio of the peak of the
largest count to that of the count before it, for each mode. The check
passes if the ratio of each mode of BOUNDED is at most MAX_RATIO: the peak
does not grow with the number of files. The json format keeps the record
of each file until the end (as sqlfluff), so its peak grows with the
output; the record gives its ratio, with no limit.

Exit code: 0 pass, 1 a failure.
"""

import argparse
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECORD_FILE = ROOT / "results" / "S3b" / "C13-memory.json"
KIND = "sqll-s3b-c13-memory"
COPIES = (1, 10, 100, 1000)
MODES = {
    "lint human": ["lint", "--rules", "CP01,CP03,CP04", "--dialect", "ansi"],
    "lint json": [
        "lint",
        "--rules",
        "CP01,CP03,CP04",
        "--dialect",
        "ansi",
        "-f",
        "json",
    ],
    "fix": ["fix", "--rules", "CP01,CP03,CP04", "--dialect", "ansi"],
}
INPUTS = ("ansi/small", "ansi/medium", "ansi/large")
BOUNDED = ("lint human", "fix")
MAX_RATIO = 1.10
COMMAND = "uv run --frozen --project harness python scripts/s3b/memory_check.py measure"


def vmhwm(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def run(argv: list[str], cwd: Path, env: dict, out: Path) -> dict:
    start = time.monotonic()
    with open(out, "wb") as stdout:
        proc = subprocess.Popen(
            argv, cwd=cwd, env=env, stdout=stdout, stderr=subprocess.DEVNULL
        )
        peak, status, usage = wait(proc)
    proc.returncode = os.waitstatus_to_exitcode(status)
    return {
        "exit_code": proc.returncode,
        "seconds": round(time.monotonic() - start, 3),
        "vmhwm_kib": peak,
        "ru_maxrss_kib": usage.ru_maxrss,
        "stdout_bytes": out.stat().st_size,
    }


def wait(proc: subprocess.Popen) -> tuple:
    """Wait for the process; read its VmHWM each 5 ms."""
    peak = 0
    while True:
        pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
        if pid:
            break
        value = vmhwm(proc.pid)
        if value:
            peak = max(peak, value)
        time.sleep(0.005)
    return peak, status, usage


def build_inputs(folder: Path) -> dict[str, bytes]:
    sys.path.insert(0, str(ROOT / "harness"))
    from sqll_harness.bench import definitions as bench_definitions
    from sqll_harness.bench import run as bench_run
    from sqll_harness.paths import SQLFLUFF_ROOT

    bench_run.build_inputs(SQLFLUFF_ROOT, bench_definitions.load(), folder)
    return {name: (folder / f"{name}.sql").read_bytes() for name in INPUTS}


def version(binary: Path) -> dict:
    out = subprocess.run(
        [str(binary), "version", "--build"], capture_output=True, check=True
    )
    return json.loads(out.stdout)


def measure(binary: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="sqll-c13-mem-") as tmp:
        tmp = Path(tmp)
        inputs = build_inputs(tmp / "inputs")
        home = tmp / "home"
        home.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env["HOME"] = str(home)
        env.pop("XDG_CONFIG_HOME", None)
        out = tmp / "stdout"
        floor = run(["/bin/true"], tmp, env, out)["ru_maxrss_kib"]
        runs = []
        for mode, args in MODES.items():
            for copies in COPIES:
                work = tmp / "work"
                shutil.rmtree(work, ignore_errors=True)
                files = work / "files"
                for i in range(copies):
                    for name, data in inputs.items():
                        path = files / f"{i:04d}" / f"{name.replace('/', '_')}.sql"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(data)
                (work / ".sqlfluff").write_text(
                    "[sqlfluff]\nlarge_file_skip_byte_limit = 0\n", encoding="ascii"
                )
                r = run([str(binary.resolve()), *args, "files"], work, env, out)
                r.update(mode=mode, copies=copies, files=copies * len(inputs))
                print(f"memory_check: {json.dumps(r)}", flush=True)
                runs.append(r)
        ratios = {}
        for mode in MODES:
            peaks = [r["vmhwm_kib"] for r in runs if r["mode"] == mode]
            ratios[mode] = round(peaks[-1] / peaks[-2], 3)
        return {
            "kind": KIND,
            "about": (
                "S3b C13: the peak memory of sqll lint and fix on many files in one "
                "process (scripts/s3b/memory_check.py; status/S3b.md, C13)."
            ),
            "command": COMMAND,
            "method": __doc__.split("Method:")[1].split("The record")[0].strip(),
            "sqll": version(binary),
            "inputs": {name: len(data) for name, data in inputs.items()},
            "floor_ru_maxrss_kib": floor,
            "max_ratio": MAX_RATIO,
            "runs": runs,
            "ratio_largest_to_previous": ratios,
            "bounded_modes": list(BOUNDED),
            "pass": all(ratios[m] <= MAX_RATIO for m in BOUNDED)
            and all(r["exit_code"] in (0, 1) for r in runs),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("measure", help="measure and write the record")
    m.add_argument(
        "--binary", type=Path, default=ROOT / "out" / "sqll" / "bin" / "sqll"
    )
    args = parser.parse_args(argv)
    record = measure(args.binary)
    RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECORD_FILE.write_text(json.dumps(record, indent=1) + "\n", encoding="utf8")
    print(
        f"memory_check: ratios {record['ratio_largest_to_previous']}: "
        f"{'PASS' if record['pass'] else 'FAIL'}"
    )
    return 0 if record["pass"] else 1


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    sys.exit(main())
