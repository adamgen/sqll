"""The benchmark timer (harness/bench.md, "Measurement"), with test doubles."""

import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from sqll_harness.bench import timer
from sqll_harness.bench.timer import (
    ERROR,
    INVALID,
    TIMED,
    VALID,
    WARMUP,
    Job,
    Policy,
    Series,
    measure,
    run_in_turn,
)

DOUBLE = Path(__file__).parent / "fixtures" / "bench" / "double.py"
SLEEP = shutil.which("sleep")
# The upper limit of the measured time above the time of a sleep: process
# start and exit, and the noise of a shared CI runner.
TOLERANCE_S = 0.1


def double(*steps) -> list[str]:
    return [sys.executable, str(DOUBLE), *map(str, steps)]


def policy(min_runs=3, max_runs=None, budget_s=0.0, timeout_s=30.0) -> Policy:
    return Policy(min_runs, max_runs or min_runs, budget_s, timeout_s)


def timed(m: timer.Measurement) -> list[timer.Sample]:
    return [s for s in m.samples if s.kind == TIMED]


# Measured values.


def test_a_sleep_is_measured_within_the_tolerance(tmp_path):
    m = measure(Job([SLEEP, "0.2"]), policy(3), tmp_path)
    assert m.status == VALID, m.reason
    assert m.stats["wall_s"]["n"] == 3
    for s in timed(m):
        assert 0.2 <= s.wall_s <= 0.2 + TOLERANCE_S, s
        assert s.cpu_s < 0.1, s
    assert 0.2 <= m.stats["wall_s"]["median"] <= 0.2 + TOLERANCE_S


def test_cpu_time_and_max_rss_come_from_the_process(tmp_path):
    m = measure(Job(double("busy", 0.3, "alloc", 64)), policy(1), tmp_path)
    assert m.status == VALID, m.reason
    (s,) = timed(m)
    assert s.user_s + s.sys_s >= 0.3
    assert s.wall_s >= 0.3
    assert s.max_rss_kib >= 64 * 1024
    assert m.stats["cpu_s"]["median"] == s.cpu_s


def test_stats_are_median_min_max_and_mad():
    assert timer.stats([3.0, 1.0, 2.0, 10.0]) == {
        "n": 4,
        "median": 2.5,
        "min": 1.0,
        "max": 10.0,
        "mad": 1.0,
    }
    with pytest.raises(ValueError):
        timer.stats([])


# Exit codes.


def test_a_non_zero_exit_code_in_the_warmup_run_is_invalid(tmp_path):
    m = measure(
        Job(double("log", "/dev/stderr", "boom", "exit", 2)), policy(), tmp_path
    )
    assert m.status == INVALID
    assert m.reason == "warmup run: exit code 2, expected 0; stderr: boom"
    assert [s.kind for s in m.samples] == [WARMUP]
    assert m.stats is None


@pytest.mark.parametrize("bad_call", [2, 3, 4])
def test_a_non_zero_exit_code_in_any_timed_run_is_invalid(tmp_path, bad_call):
    counter = tmp_path / "calls"
    job = Job(double("call", counter, "on", bad_call, "exit", 1))
    m = measure(job, policy(3), tmp_path / "w")
    run = bad_call - 1
    assert m.status == INVALID
    assert m.reason == (
        f"timed run {run}: exit code 1, expected exit code 0 (the warmup run)"
    )
    # The samples stay, up to the bad run; there are no stats.
    assert [s.exit_code for s in m.samples] == [0] * run + [1]
    assert m.stats is None
    # The folder of the bad run stays for the analysis.
    assert (tmp_path / "w" / str(run) / "stderr").is_file()


def test_a_timed_run_needs_the_exit_code_of_the_warmup_run(tmp_path):
    counter = tmp_path / "calls"
    job = Job(
        double("call", counter, "on", 1, "exit", 1),
        expected_exits=frozenset({0, 1}),
    )
    m = measure(job, policy(3), tmp_path / "w")
    assert m.status == INVALID
    assert m.reason == "timed run 1: exit code 0, expected exit code 1 (the warmup run)"


def test_an_expected_non_zero_exit_code_is_valid(tmp_path):
    job = Job(double("exit", 1), expected_exits=frozenset({0, 1}))
    m = measure(job, policy(3), tmp_path)
    assert m.status == VALID, m.reason
    assert {s.exit_code for s in m.samples} == {1}


def test_a_crash_is_invalid(tmp_path):
    m = measure(Job(double("crash")), policy(), tmp_path)
    assert m.status == INVALID
    assert m.reason == "warmup run: signal SIGSEGV, expected 0"
    assert m.samples[0].exit_code == -11


def test_a_check_that_fails_is_an_error(tmp_path):
    def check(run: timer.Run) -> str | None:
        raise KeyError("tree")

    m = measure(Job(double("exit", 0), check=check), policy(), tmp_path)
    assert m.status == ERROR
    assert m.reason == "warmup run: check failed: KeyError('tree')"
    assert [s.kind for s in m.samples] == [WARMUP]


def test_the_check_examines_the_warmup_run(tmp_path):
    seen = []

    def check(run: timer.Run) -> str | None:
        seen.append(run.sample.kind)
        text = run.stderr.read_text()
        return "size-limit skip message" if "over the limit" in text else None

    m = measure(Job(double("skip"), check=check), policy(), tmp_path)
    assert m.status == INVALID
    assert m.reason == "warmup run: size-limit skip message"
    assert seen == [WARMUP]
    assert [s.exit_code for s in m.samples] == [0]

    m = measure(Job(double("exit", 0), check=check), policy(), tmp_path / "ok")
    assert m.status == VALID
    assert seen == [WARMUP, WARMUP]


def test_a_timeout_is_invalid_and_kills_the_process_group(tmp_path):
    pid_file = tmp_path / "child.pid"
    job = Job(double("fork", pid_file, "sleep", 30))
    start = time.monotonic()
    m = measure(job, policy(timeout_s=1.0), tmp_path / "w")
    assert time.monotonic() - start < 10
    assert m.status == INVALID
    assert m.reason == "warmup run: timeout after 1.0 s"
    (s,) = m.samples
    assert s.timed_out and s.exit_code == -9 and 1.0 <= s.wall_s < 5
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            break
        if state in ("Z", "X"):
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"the child {pid} of the timed out process runs")


def test_a_tool_that_cannot_start_is_an_error(tmp_path):
    m = measure(Job([str(tmp_path / "no-such-tool")]), policy(), tmp_path / "w")
    assert m.status == ERROR
    assert m.reason.startswith(f"warmup run: cannot start {tmp_path}/no-such-tool")
    assert m.samples == [] and m.stats is None


def test_a_prepare_failure_is_an_error(tmp_path):
    def prepare(folder: Path) -> None:
        raise OSError("disk full")

    m = measure(Job(double("exit", 0), prepare=prepare), policy(), tmp_path)
    assert m.status == ERROR
    assert m.reason == "warmup run: prepare failed: OSError('disk full')"


# Prepare and warmup are not timed.


def test_the_prepare_step_is_not_timed(tmp_path):
    folders = []

    def prepare(folder: Path) -> None:
        assert list(folder.iterdir()) == []
        folders.append(folder)
        time.sleep(0.5)
        (folder / "input.sql").write_text("SELECT 1;\n")

    job = Job(double("need", "input.sql"), prepare=prepare)
    m = measure(job, policy(3), tmp_path)
    assert m.status == VALID, m.reason
    assert len(folders) == 4 and len(set(folders)) == 4
    for s in m.samples:
        assert s.wall_s < 0.4, s


def test_without_the_prepare_step_the_input_is_missing(tmp_path):
    m = measure(Job(double("need", "input.sql")), policy(), tmp_path)
    assert m.status == INVALID
    assert (
        m.reason == "warmup run: exit code 3, expected 0; stderr: input file is missing"
    )


def test_the_warmup_run_is_not_in_the_statistics(tmp_path):
    counter = tmp_path / "calls"
    job = Job(double("call", counter, "on", 1, "sleep", 0.6))
    m = measure(job, policy(3), tmp_path / "w")
    assert m.status == VALID, m.reason
    warmup, *rest = m.samples
    assert warmup.kind == WARMUP and warmup.wall_s >= 0.6
    assert [s.kind for s in rest] == [TIMED] * 3
    assert m.stats["wall_s"]["n"] == m.stats["cpu_s"]["n"] == 3
    assert m.stats["wall_s"]["max"] < 0.5
    assert m.stats == timer.sample_stats(rest)


# Policy, folders, and the order of the runs.


def test_the_policy_gives_the_number_of_timed_runs(tmp_path):
    true = Job(["/bin/true"])
    m = measure(true, Policy(3, 20, 0.0, 30.0), tmp_path / "a")
    assert len(timed(m)) == 3
    m = measure(true, Policy(3, 7, 100.0, 30.0), tmp_path / "b")
    assert len(timed(m)) == 7
    m = measure(Job([SLEEP, "0.1"]), Policy(2, 50, 0.35, 30.0), tmp_path / "c")
    walls = [s.wall_s for s in timed(m)]
    assert len(walls) >= 2
    assert sum(walls) >= 0.35 and sum(walls[:-1]) < 0.35


def test_bad_policies_are_refused():
    for args in ((0, 1, 0.0, 1.0), (3, 2, 0.0, 1.0), (1, 1, -1.0, 1.0), (1, 1, 0, 0)):
        with pytest.raises(ValueError):
            Policy(*args)


def test_the_profiles_are_those_of_bench_md():
    assert timer.PROFILES == {
        "smoke": Policy(1, 1, 0.0, 120.0),
        "full": Policy(3, 20, 2.0, 120.0),
    }
    text = (Path(__file__).parents[1] / "bench.md").read_text(encoding="utf8")
    flat = " ".join(text.split())
    assert "`full`: at least 3 and at most 20 timed runs" in flat
    assert "while their wall time is less than 2 s" in flat
    assert "`smoke`: 1 timed run" in flat
    assert "timeout (120 s" in flat


def test_runs_have_their_own_folder_cwd_and_env(tmp_path):
    work = tmp_path / "w"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    env = {**os.environ, "SQLL_DOUBLE": "x"}
    argv = [
        sys.executable,
        "-c",
        "import os; print(os.getcwd(), os.environ['SQLL_DOUBLE'])",
    ]
    m = measure(Job(argv, cwd=cwd, env=env), policy(2), work)
    assert m.status == VALID, m.reason
    assert m.warmup.stdout.read_text() == f"{cwd} x\n"
    # Only the folder of the warmup run stays.
    assert sorted(p.name for p in work.iterdir()) == [WARMUP]
    assert m.warmup.folder == work / WARMUP

    m = measure(
        Job(argv[:2] + ["import os; print(os.getcwd())"]), policy(2), work, True
    )
    assert m.warmup.stdout.read_text() == f"{work / WARMUP}\n"
    assert sorted(p.name for p in work.iterdir()) == ["1", "2", WARMUP]


def test_the_tools_run_in_turn(tmp_path):
    log = tmp_path / "log"
    series = [
        Series(Job(double("log", log, name)), policy(3), tmp_path / name)
        for name in ("a", "b")
    ]
    a, b = run_in_turn(series)
    assert a.status == b.status == VALID
    assert log.read_text().split() == ["a", "b"] * 4


def test_an_invalid_series_stops_and_the_others_continue(tmp_path):
    log = tmp_path / "log"
    calls = tmp_path / "calls"
    series = [
        Series(Job(double("log", log, "a")), policy(3), tmp_path / "a"),
        Series(
            Job(double("call", calls, "log", log, "b", "on", 2, "exit", 1)),
            policy(3),
            tmp_path / "b",
        ),
    ]
    a, b = run_in_turn(series)
    assert a.status == VALID and b.status == INVALID
    assert log.read_text().split() == ["a", "b", "a", "b", "a", "a"]


def test_the_timer_overhead(tmp_path):
    entry = timer.overhead(tmp_path / "o")
    o = entry["overhead"]
    assert o["argv"] == ["/bin/true"]
    assert len(o["samples"]) == timer.OVERHEAD_RUNS == o["stats"]["wall_s"]["n"]
    assert 0 < o["stats"]["wall_s"]["median"] < 0.1
    assert not (tmp_path / "o").exists()
