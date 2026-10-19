"""A test double for the benchmark timer. It does the steps of its argv.

Steps: sleep S | busy S (CPU time) | alloc MIB | exit N | crash |
skip (prints a size-limit skip warning) | log FILE TEXT (appends a line) |
need FILE (exit 3 if FILE is not in the current folder) |
call FILE (adds 1 to the counter in FILE) |
on CALL STEP... (do the next step only on that call of the counter) |
fork FILE (starts a child in the same process group that sleeps; writes
its pid to FILE).
"""

import os
import signal
import subprocess
import sys
import time

STEPS = {
    "sleep",
    "busy",
    "alloc",
    "exit",
    "crash",
    "skip",
    "log",
    "need",
    "call",
    "on",
    "fork",
}
args = sys.argv[1:]
calls = 0
while args:
    step, *args = args
    if step == "sleep":
        time.sleep(float(args.pop(0)))
    elif step == "busy":
        end = time.process_time() + float(args.pop(0))
        while time.process_time() < end:
            pass
    elif step == "alloc":
        data = bytearray(int(args.pop(0)) * 1024 * 1024)
        for i in range(0, len(data), 4096):
            data[i] = 1
    elif step == "exit":
        sys.exit(int(args.pop(0)))
    elif step == "crash":
        os.kill(os.getpid(), signal.SIGSEGV)
    elif step == "skip":
        print(
            "WARNING: input.sql is over the limit (20000 bytes). SKIP", file=sys.stderr
        )
    elif step == "log":
        path, text = args.pop(0), args.pop(0)
        with open(path, "a") as f:
            f.write(text + "\n")
    elif step == "need":
        if not os.path.isfile(args.pop(0)):
            print("input file is missing", file=sys.stderr)
            sys.exit(3)
    elif step == "call":
        path = args.pop(0)
        calls = int(open(path).read()) + 1 if os.path.exists(path) else 1
        with open(path, "w") as f:
            f.write(str(calls))
    elif step == "on":
        if calls != int(args.pop(0)):
            args.pop(0)
            # Skip the arguments of the skipped step.
            while args and args[0] not in STEPS:
                args.pop(0)
    elif step == "fork":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        with open(args.pop(0), "w") as f:
            f.write(str(child.pid))
    else:
        sys.exit(f"unknown step {step!r}")
