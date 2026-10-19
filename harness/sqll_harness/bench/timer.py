"""The benchmark timer. See harness/bench.md ("Measurement").

The timer starts one argv as a subprocess, with stdout and stderr to files.
Wall time is time.perf_counter_ns() from before the start of the process to
its exit. CPU time and max RSS come from os.wait4() (the process and the
descendants that it waited for). A pidfd tells when the process exits, so
the timer kills a process at the timeout before it reaps it: the process
id cannot go to another process before the kill. Linux only.

A series is the runs of one job: 1 warmup run (the validity run), then the
timed runs of the policy. measure() runs one series. run_in_turn() runs
some series and lets each do one timed run in turn, so that drift has the
same effect on each tool (harness/bench.md, "Noise control").
"""

import os
import select
import shutil
import signal
import statistics
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

VALID = "valid"
INVALID = "invalid"
UNSUPPORTED = "unsupported"
ERROR = "error"
STATUSES = (VALID, INVALID, UNSUPPORTED, ERROR)

WARMUP = "warmup"
TIMED = "timed"
STDOUT = "stdout"
STDERR = "stderr"
STDERR_TAIL = 300
DIGITS = 6
OVERHEAD_ARGV = ("/bin/true",)
OVERHEAD_RUNS = 10


@dataclass(frozen=True)
class Policy:
    """How many timed runs a series does. harness/bench.md has the values.

    The timed runs continue while there are fewer than min_runs, or while
    their wall time is less than budget_s and there are fewer than
    max_runs. A run that does not stop in timeout_s is killed.
    """

    min_runs: int
    max_runs: int
    budget_s: float
    timeout_s: float

    def __post_init__(self):
        if not 1 <= self.min_runs <= self.max_runs:
            raise ValueError(f"policy needs 1 <= min_runs <= max_runs: {self}")
        if self.budget_s < 0 or self.timeout_s <= 0:
            raise ValueError(f"policy needs budget_s >= 0 and timeout_s > 0: {self}")

    def as_dict(self) -> dict:
        return {
            "warmup_runs": 1,
            "min_runs": self.min_runs,
            "max_runs": self.max_runs,
            "budget_s": self.budget_s,
            "timeout_s": self.timeout_s,
        }


PROFILES = {
    "smoke": Policy(min_runs=1, max_runs=1, budget_s=0.0, timeout_s=120.0),
    "full": Policy(min_runs=3, max_runs=20, budget_s=2.0, timeout_s=120.0),
}


@dataclass(frozen=True)
class Sample:
    """One run. Times in seconds; max RSS in KiB (Linux ru_maxrss).

    exit_code is negative if a signal stopped the process.
    """

    kind: str  # WARMUP or TIMED
    wall_s: float
    user_s: float
    sys_s: float
    max_rss_kib: int
    exit_code: int
    timed_out: bool

    @property
    def cpu_s(self) -> float:
        return round(self.user_s + self.sys_s, DIGITS)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "wall_s": self.wall_s,
            "user_s": self.user_s,
            "sys_s": self.sys_s,
            "max_rss_kib": self.max_rss_kib,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
        }


@dataclass(frozen=True)
class Run:
    """A completed run: its sample and its folder with stdout and stderr."""

    sample: Sample
    folder: Path

    @property
    def stdout(self) -> Path:
        return self.folder / STDOUT

    @property
    def stderr(self) -> Path:
        return self.folder / STDERR

    def stderr_tail(self) -> str:
        try:
            data = self.stderr.read_bytes()
        except OSError:
            return ""
        return data[-STDERR_TAIL:].decode("utf8", "replace").strip()


# A check gets the warmup run and returns None if it is valid, or the reason
# why it is not. Tool adapters give the checks of harness/bench.md.
Check = Callable[[Run], str | None]


@dataclass(frozen=True)
class Job:
    """What one series runs.

    prepare(folder) runs before each run, outside the timed part, with the
    new empty folder of the run (for fix: copy the input into it). The run
    starts in cwd, or in its folder if cwd is None. The warmup run must have
    an exit code in expected_exits and pass check; each timed run must have
    the exit code of the warmup run.
    """

    argv: Sequence[str]
    expected_exits: frozenset[int] = frozenset({0})
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    prepare: Callable[[Path], None] | None = None
    check: Check | None = None


def _seconds(ns: int) -> float:
    return round(ns / 1e9, DIGITS)


def run_once(
    argv: Sequence[str],
    folder: Path,
    *,
    kind: str,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: float,
) -> Run:
    """Run argv once and measure it. folder gets the stdout and stderr files.

    OSError if the process cannot start.
    """
    folder.mkdir(parents=True, exist_ok=True)
    with (
        open(folder / STDOUT, "wb") as out,
        open(folder / STDERR, "wb") as err,
    ):
        start = time.perf_counter_ns()
        proc = subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            cwd=cwd or folder,
            env=None if env is None else dict(env),
            start_new_session=True,
        )
    timed_out = False
    pidfd = os.pidfd_open(proc.pid)
    try:
        poller = select.poll()
        poller.register(pidfd, select.POLLIN)
        if not poller.poll(int(timeout_s * 1000)):
            # The process is not reaped yet, so its process and group ids
            # are still its own.
            timed_out = True
            signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            poller.poll()
        end = time.perf_counter_ns()
    finally:
        os.close(pidfd)
    _, status, usage = os.wait4(proc.pid, 0)
    proc.returncode = os.waitstatus_to_exitcode(status)
    sample = Sample(
        kind=kind,
        wall_s=_seconds(end - start),
        user_s=round(usage.ru_utime, DIGITS),
        sys_s=round(usage.ru_stime, DIGITS),
        max_rss_kib=usage.ru_maxrss,
        exit_code=proc.returncode,
        timed_out=timed_out,
    )
    return Run(sample, folder)


def stats(values: Sequence[float]) -> dict:
    """Return n, median, min, max, and MAD (median absolute deviation)."""
    if not values:
        raise ValueError("no values")
    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values)
    return {
        "n": len(values),
        "median": round(median, DIGITS),
        "min": round(min(values), DIGITS),
        "max": round(max(values), DIGITS),
        "mad": round(mad, DIGITS),
    }


def sample_stats(samples: Sequence[Sample]) -> dict:
    """Return the statistics of the timed samples. The warmup is not in them."""
    timed = [s for s in samples if s.kind == TIMED]
    return {
        "wall_s": stats([s.wall_s for s in timed]),
        "cpu_s": stats([s.cpu_s for s in timed]),
    }


@dataclass
class Measurement:
    """The result of one series."""

    status: str
    reason: str | None
    samples: list[Sample]
    stats: dict | None
    warmup: Run | None = None


def _exit_text(code: int) -> str:
    if code < 0:
        try:
            return f"signal {signal.Signals(-code).name}"
        except ValueError:
            return f"signal {-code}"
    return f"exit code {code}"


def _failure(run: Run, what: str) -> str:
    tail = run.stderr_tail()
    return f"{what}; stderr: {tail}" if tail else what


@dataclass
class Series:
    """The runs of one job in folder. Call warmup(), then timed() while
    wants_more(), then result()."""

    job: Job
    policy: Policy
    folder: Path
    keep_timed: bool = False
    samples: list[Sample] = field(default_factory=list)
    status: str | None = None
    reason: str | None = None
    warmup_run: Run | None = None
    timed_wall_s: float = 0.0

    @property
    def timed_runs(self) -> int:
        return sum(s.kind == TIMED for s in self.samples)

    def _run(self, kind: str, name: str) -> Run | None:
        folder = self.folder / name
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        try:
            if self.job.prepare:
                self.job.prepare(folder)
        except Exception as exc:
            self._stop(ERROR, f"{name} run: prepare failed: {exc!r}")
            return None
        try:
            run = run_once(
                self.job.argv,
                folder,
                kind=kind,
                cwd=self.job.cwd,
                env=self.job.env,
                timeout_s=self.policy.timeout_s,
            )
        except OSError as exc:
            self._stop(ERROR, f"{name} run: cannot start {self.job.argv[0]}: {exc}")
            return None
        self.samples.append(run.sample)
        if run.sample.timed_out:
            self._stop(
                INVALID,
                _failure(run, f"{name} run: timeout after {self.policy.timeout_s} s"),
            )
            return None
        return run

    def _stop(self, status: str, reason: str) -> None:
        self.status, self.reason = status, reason

    def warmup(self) -> None:
        run = self._run(WARMUP, WARMUP)
        if run is None:
            return
        self.warmup_run = run
        code = run.sample.exit_code
        if code not in self.job.expected_exits:
            want = ", ".join(str(c) for c in sorted(self.job.expected_exits))
            self._stop(
                INVALID,
                _failure(run, f"warmup run: {_exit_text(code)}, expected {want}"),
            )
            return
        try:
            reason = self.job.check(run) if self.job.check else None
        except Exception as exc:
            self._stop(ERROR, f"warmup run: check failed: {exc!r}")
            return
        if reason:
            self._stop(INVALID, f"warmup run: {reason}")

    def wants_more(self) -> bool:
        if self.status is not None or self.warmup_run is None:
            return False
        n = self.timed_runs
        if n < self.policy.min_runs:
            return True
        return n < self.policy.max_runs and self.timed_wall_s < self.policy.budget_s

    def timed(self) -> None:
        name = str(self.timed_runs + 1)
        run = self._run(TIMED, name)
        if run is None:
            return
        self.timed_wall_s += run.sample.wall_s
        want = self.warmup_run.sample.exit_code
        if run.sample.exit_code != want:
            self._stop(
                INVALID,
                _failure(
                    run,
                    f"timed run {name}: {_exit_text(run.sample.exit_code)}, expected "
                    f"{_exit_text(want)} (the warmup run)",
                ),
            )
        elif not self.keep_timed:
            shutil.rmtree(run.folder)

    def result(self) -> Measurement:
        if self.status is None and self.warmup_run is None:
            raise RuntimeError("the series has no warmup run")
        if self.status is None and self.wants_more():
            raise RuntimeError("the series needs more timed runs")
        if self.status is not None:
            return Measurement(
                self.status, self.reason, list(self.samples), None, self.warmup_run
            )
        return Measurement(
            VALID, None, list(self.samples), sample_stats(self.samples), self.warmup_run
        )


def run_in_turn(series: Sequence[Series]) -> list[Measurement]:
    """Do the warmup run of each series, then 1 timed run of each series in
    turn until no series wants more. Return the results in input order."""
    for s in series:
        s.warmup()
    while True:
        active = [s for s in series if s.wants_more()]
        if not active:
            break
        for s in active:
            s.timed()
    return [s.result() for s in series]


def measure(job: Job, policy: Policy, folder: Path, keep_timed: bool = False):
    """Run one series and return its Measurement."""
    return run_in_turn([Series(job, policy, folder, keep_timed)])[0]


def overhead(folder: Path, runs: int = OVERHEAD_RUNS, timeout_s: float = 10.0):
    """Measure the timer with /bin/true. Return the report "timer" entry."""
    samples = []
    for i in range(runs):
        run = run_once(
            OVERHEAD_ARGV, folder / str(i + 1), kind=TIMED, timeout_s=timeout_s
        )
        if run.sample.exit_code != 0 or run.sample.timed_out:
            raise RuntimeError(f"{OVERHEAD_ARGV[0]} failed: {run.sample}")
        samples.append(run.sample)
    shutil.rmtree(folder)
    return timer_entry(samples)


def timer_entry(samples: Sequence[Sample]) -> dict:
    return {
        "clock": "time.perf_counter_ns",
        "rusage": "os.wait4",
        "overhead": {
            "argv": list(OVERHEAD_ARGV),
            "samples": [s.as_dict() for s in samples],
            "stats": sample_stats(samples),
        },
    }
