"""The read trace of scripts/s7-tests/config-readers.

install() adds an audit hook to this process. The hook appends a JSON line
to the log file (S7_TRACE_LOG) for each read of a path in
test/fixtures/config of S7_TRACE_ROOT, and for each start of a program. Each
line has the node id in S7_TRACE_NODE. A forked process keeps the hook. A new
Python process gets it from sitecustomize.py in this folder (config-readers
puts the folder on PYTHONPATH), and writes a "start" line.
"""

import json
import os
import sys

READS = ("open", "os.listdir", "os.scandir")
# Audit events that start a new program. A Python program writes a "start"
# line. Thus the reader can find a program that the trace does not see.
PROGRAMS = ("subprocess.Popen", "os.posix_spawn", "os.exec", "os.spawn", "os.system")
OUTSIDE = "<outside a test>"


def install() -> None:
    log = os.environ.get("S7_TRACE_LOG")
    root = os.environ.get("S7_TRACE_ROOT")
    if not log or not root:
        return
    target = os.path.join(root, "test", "fixtures", "config")
    fd = os.open(log, os.O_WRONLY | os.O_APPEND)

    def write(*record) -> None:
        node = os.environ.get("S7_TRACE_NODE", OUTSIDE)
        line = json.dumps([node, *record]) + "\n"
        os.write(fd, line.encode("utf8"))

    popen = [False]

    def audit(event: str, args: tuple) -> None:
        if event in PROGRAMS:
            # subprocess.Popen can start its program with os.posix_spawn: 1
            # program, 2 events.
            if not (event == "os.posix_spawn" and popen[0]):
                write("program", event)
            popen[0] = event == "subprocess.Popen"
            return
        if event not in READS or not args:
            return
        path = args[0]
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if not isinstance(path, str | os.PathLike):
            return
        full = os.path.abspath(os.fspath(path))
        if full == target or full.startswith(target + os.sep):
            write("read", event, os.path.relpath(full, root).replace(os.sep, "/"))

    if os.environ.get("S7_TRACE_MAIN") != str(os.getpid()):
        write("start")
    sys.addaudithook(audit)
