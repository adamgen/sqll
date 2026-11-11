"""S3b C5: the speed check of a change (scripts/speed-check; harness/bench.md,
"Speed check of a change").

results/S3b/speed/C5.json is the proof run (BASE = HEAD = main). The drift
test makes its summary again from the committed record. The other tests use
fake sqll binaries and changed copies of the record: the compare logic, and
each refusal (exit code 2) of the tool.
"""

import copy
import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from sqll_harness import cli, tools
from sqll_harness.adapters import sqll as sqll_adapter
from sqll_harness.bench import compare, definitions, registry
from sqll_harness.bench import run as bench_run
from sqll_harness.bench.adapter import Context
from sqll_harness.bench.sqll import SqllBaseBench, SqllBench
from sqll_harness.bench.timer import INVALID, PROFILES, VALID
from sqll_harness.paths import REPO_ROOT, TOOL_SPECS_DIR

_loader = importlib.machinery.SourceFileLoader(
    "speed_check", str(REPO_ROOT / "scripts" / "speed-check")
)
_spec = importlib.util.spec_from_loader("speed_check", _loader)
sc = importlib.util.module_from_spec(_spec)
_loader.exec_module(sc)

C5_FILE = sc.SPEED_DIR / "C5.json"
C5 = json.loads(C5_FILE.read_text("utf8"))


def record() -> dict:
    return copy.deepcopy(C5)


def write_task(tmp_path: Path, monkeypatch, data: dict, task: str = "C5") -> Path:
    monkeypatch.setattr(sc, "SPEED_DIR", tmp_path / "speed")
    path = sc.task_file(task)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sc.dump(data), "utf8")
    return path


def result(data: dict, bid: str, tool: str) -> dict:
    return next(
        r for r in data["report"]["results"] if r["id"] == bid and r["tool"] == tool
    )


# The proof run and the drift test.


def test_the_committed_summary_is_the_summary_of_the_committed_record():
    assert sc.main(["report", "--task", "C5", "--check"]) == 0


def test_the_check_fails_on_a_changed_summary(tmp_path, monkeypatch):
    data = record()
    data["summary"]["ok"] = not data["summary"]["ok"]
    write_task(tmp_path, monkeypatch, data)
    assert sc.main(["report", "--task", "C5", "--check"]) == 1


def test_report_writes_the_summary_again(tmp_path, monkeypatch):
    data = record()
    del data["summary"]
    path = write_task(tmp_path, monkeypatch, data)
    assert sc.main(["report", "--task", "C5"]) == 0
    assert path.read_text("utf8") == C5_FILE.read_text("utf8")


def test_the_proof_run_is_a_null_change_with_no_slower_benchmark():
    s = C5["summary"]
    assert C5["base"]["commit"] == C5["head"]["commit"] == s["base"] == s["head"]
    assert C5["base"]["ref"] == C5["head"]["ref"] == "origin/main"
    assert s["same_source"] is True
    slow = s["slowdowns"]
    assert slow["benchmarks"] == 112
    assert slow["slower"] == [] and slow["failure"] == []
    assert slow["counts"]["slower"] == 0
    assert sum(slow["counts"].values()) == 112
    sqruff = s["g3"]["sqruff"]
    assert sqruff["pairs"] == sqruff["head_faster"] == 108
    assert [n["id"] for n in sqruff["no_pair"]] == [
        "start/soql",
        "parse/soql/small",
        "parse/soql/medium",
        "parse/soql/large",
    ]
    sqlfluff = s["g3"]["sqlfluff"]
    assert sqlfluff["pairs"] == sqlfluff["head_faster"] == 112
    assert sqruff["ok"] and sqlfluff["ok"] and s["ok"]
    assert s["exit_code"] == 0


def test_the_proof_run_used_the_s2_method():
    method = C5["method"]
    assert method["image"].startswith("sqll-ci:")
    assert method["machine_lock"].startswith("/tmp/sqll-machine.lock: ")
    assert C5["report"]["profile"] == "full"
    assert sorted(C5["report"]["tools"]) == ["sqlfluff", "sqll", "sqll-base", "sqruff"]
    session = next(s for s in C5["steps"] if s["step"] == "session")
    argv = session["argv"]
    assert argv[:5] == ["docker", "run", "--rm", "--network", "none"]
    assert "$REPO:$REPO:ro" in argv
    assert argv[-3:] == ["run-inside", "--scratch", sc.C_SCRATCH]


def test_each_median_is_the_median_of_the_timed_runs():
    import statistics

    for r in C5["report"]["results"]:
        if r["status"] != VALID:
            continue
        for key in ("wall_s", "cpu_s"):
            want = statistics.median(r["samples"][key])
            assert r["stats"][key]["median"] == pytest.approx(want, abs=1e-6), r["id"]


def test_the_run_time_is_in_bench_md():
    text = (REPO_ROOT / "harness" / "bench.md").read_text("utf8")
    minutes = round(C5["time_s"]["total"] / 60)
    assert f"{minutes} min" in text


# The compare logic.


def test_a_slower_head_is_a_slowdown(tmp_path, monkeypatch):
    data = record()
    head = result(data, "parse/ansi/large", sc.HEAD)
    for key in ("wall_s", "cpu_s"):
        head["stats"][key]["median"] *= 2
    write_task(tmp_path, monkeypatch, data)
    assert sc.main(["report", "--task", "C5"]) == 1
    s = json.loads(sc.task_file("C5").read_text("utf8"))["summary"]
    assert s["slowdowns"]["slower"] == ["parse/ansi/large"]
    assert s["slowdowns"]["counts"]["slower"] == 1
    group = next(g for g in s["slowdowns"]["groups"] if g["group"] == "parse/large")
    assert group["slower"] == 1
    assert not s["ok"] and s["exit_code"] == 1


def test_a_change_inside_the_noise_limit_is_not_a_slowdown(tmp_path, monkeypatch):
    data = record()
    head = result(data, "parse/ansi/large", sc.HEAD)
    head["stats"]["wall_s"]["median"] *= 1.2
    head["stats"]["cpu_s"]["median"] *= 1.05
    write_task(tmp_path, monkeypatch, data)
    assert sc.main(["report", "--task", "C5"]) == 0


def test_a_head_that_is_not_valid_is_a_failure(tmp_path, monkeypatch):
    data = record()
    head = result(data, "parse/tsql/medium", sc.HEAD)
    head.update(status=INVALID, reason="warmup run: exit code 1", stats=None)
    write_task(tmp_path, monkeypatch, data)
    assert sc.main(["report", "--task", "C5"]) == 1
    s = json.loads(sc.task_file("C5").read_text("utf8"))["summary"]
    assert s["slowdowns"]["failure"] == ["parse/tsql/medium"]
    for tool in sc.OTHERS:
        assert s["g3"][tool]["head_not_valid"] == ["parse/tsql/medium"]
        assert not s["g3"][tool]["ok"]


def test_head_slower_than_sqruff_fails_g3_5(tmp_path, monkeypatch):
    data = record()
    sqruff = result(data, "start/ansi", "sqruff")
    head = result(data, "start/ansi", sc.HEAD)
    sqruff["stats"]["wall_s"]["median"] = head["stats"]["wall_s"]["median"] / 2
    write_task(tmp_path, monkeypatch, data)
    assert sc.main(["report", "--task", "C5"]) == 1
    s = json.loads(sc.task_file("C5").read_text("utf8"))["summary"]
    assert s["g3"]["sqruff"]["head_slower"] == ["start/ansi"]
    assert not s["g3"]["sqruff"]["ok"] and s["g3"]["sqlfluff"]["ok"]
    assert s["slowdowns"]["slower"] == []


def test_a_tie_with_sqlfluff_fails_g3_4(tmp_path, monkeypatch):
    data = record()
    sqlfluff = result(data, "start/ansi", "sqlfluff")
    head = result(data, "start/ansi", sc.HEAD)
    sqlfluff["stats"]["wall_s"]["median"] = head["stats"]["wall_s"]["median"]
    write_task(tmp_path, monkeypatch, data)
    assert sc.main(["report", "--task", "C5"]) == 1
    s = json.loads(sc.task_file("C5").read_text("utf8"))["summary"]
    assert s["g3"]["sqlfluff"]["ties"] == ["start/ansi"]
    assert not s["g3"]["sqlfluff"]["ok"]


def test_the_rows_use_the_compare_entry_of_bench_compare():
    rep = C5["report"]
    rows = {r["id"]: r for r in sc.rows(rep)}
    assert len(rows) == 112
    by_key = {(r["id"], r["tool"]): r for r in rep["results"]}
    for bid, row in rows.items():
        entry = compare.benchmark_entry(by_key[(bid, sc.BASE)], by_key[(bid, sc.HEAD)])
        assert row["wall"] == entry["wall"] and row["cpu"] == entry["cpu"]
        assert row["change"] == entry["change"]


FAKE = """#!{python} -I
import json, sys, time
args = sys.argv[1:]
if args == ["--version"]:
    print("sqll, version {version}")
    sys.exit(0)
if args[:1] == ["version"]:
    print(json.dumps({{"version": "{version}", "source_sha256": "{source}"}}))
    sys.exit(0)
if args[:3] != ["parse", "-f", "json"]:
    sys.exit(2)
time.sleep({sleep})
with open(args[-1], encoding="utf8") as f:
    lines = f.read().splitlines(keepends=True)
print(json.dumps([{{"filepath": args[-1], "segments": {{"file": [
    {{"line": line}} for line in lines]}}}}]))
"""


def fake_sqll(
    folder: Path, sleep: float = 0.0, version: str = "0.1.0", source: str = "0" * 64
) -> Path:
    binary = folder / "bin" / "sqll"
    binary.parent.mkdir(parents=True, exist_ok=True)
    text = FAKE.format(
        python=sys.executable, version=version, source=source, sleep=sleep
    )
    binary.write_text(text)
    binary.chmod(0o755)
    return binary


def test_the_compare_logic_on_a_run_of_2_fake_binaries(
    bench_inputs_dir, tmp_path, monkeypatch
):
    """A HEAD that sleeps 50 ms more than BASE in each parse is slower on
    each benchmark; BASE against itself is not."""
    monkeypatch.setenv(sqll_adapter.BASE_BINARY_ENV, str(fake_sqll(tmp_path / "b")))
    monkeypatch.setenv("SQLL_BIN", str(fake_sqll(tmp_path / "h", sleep=0.05)))
    defs = definitions.load()
    ids = ("start/ansi", "parse/ansi/small")
    benchmarks = [b for b in defs["benchmarks"] if b["id"] in ids]
    ctx = Context(defs, bench_inputs_dir, tmp_path / "work")
    adapters = [registry.get(sc.HEAD), registry.get(sc.BASE)]
    results = bench_run.run_benchmarks(benchmarks, adapters, ctx, "full")
    assert {(r["id"], r["tool"], r["status"]) for r in results} == {
        (i, t, VALID) for i in ids for t in (sc.HEAD, sc.BASE)
    }
    rep = {"results": results}
    table = sc.rows(rep)
    assert [r["id"] for r in table] == list(ids)
    assert all(r["change"] == compare.SLOWER for r in table)
    slow = sc.slowdowns(rep, table)
    assert slow["slower"] == list(ids)
    assert slow["groups"][-1]["slower"] == 2
    same = [{**r, "tool": sc.HEAD} for r in results if r["tool"] == sc.BASE]
    same += [r for r in results if r["tool"] == sc.BASE]
    assert sc.slowdowns({"results": same}, sc.rows({"results": same}))["slower"] == []


# sqll-base: the registry entry and its tool check.


def test_sqll_base_has_the_adapter_and_settings_of_sqll(tmp_path, monkeypatch):
    binary = fake_sqll(tmp_path)
    monkeypatch.setenv(sqll_adapter.BASE_BINARY_ENV, str(binary))
    base = registry.get("sqll-base")
    assert isinstance(base, SqllBaseBench) and isinstance(base, SqllBench)
    assert base.name == "sqll-base"
    assert base.s1.binary == binary
    assert base.commands == SqllBench.commands
    for dialect in (None, "ansi", "tsql"):
        assert base.config(dialect) == SqllBench(Path("/x")).config(dialect)


def test_sqll_base_is_not_a_default_tool():
    assert "sqll-base" not in registry.names()
    assert "sqll-base" not in tools.CHECKS
    with pytest.raises(ValueError):
        registry.register("sqll-base", SqllBaseBench)


def _fake_readelf(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "path"
    path.mkdir(exist_ok=True)
    (path / "readelf").write_text(
        "#!/bin/sh\necho ' 0x1 (NEEDED)  Shared library: [libc.so.6]'\n"
    )
    (path / "readelf").chmod(0o755)
    monkeypatch.setenv("PATH", f"{path}{os.pathsep}{os.environ['PATH']}")


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    (root / "crates" / "sqll_dialects").mkdir(parents=True)
    (root / "Cargo.toml").write_text('[workspace.package]\nversion = "0.1.0"\n')
    for name in ("Cargo.lock", "rust-toolchain.toml", "LICENSE"):
        (root / name).write_text(f"{name}\n")
    (root / "crates" / "sqll_dialects" / "generated.json").write_text('{"files": []}\n')
    return root


def _base_env(tmp_path, monkeypatch, *, stale: bool = False) -> Path:
    _fake_readelf(tmp_path, monkeypatch)
    root = _source(tmp_path)
    version = sqll_adapter.expected_version(root)
    source = "f" * 64 if stale else sqll_adapter.source_hash(root)[0]
    binary = fake_sqll(tmp_path / "base", version=version, source=source)
    monkeypatch.setenv(sqll_adapter.BASE_BINARY_ENV, str(binary))
    monkeypatch.setenv(sqll_adapter.BASE_SOURCE_ENV, str(root))
    return binary


def test_a_fresh_base_binary_passes_its_tool_check(tmp_path, monkeypatch):
    _base_env(tmp_path, monkeypatch)
    [info] = tools.check(["sqll-base"])
    assert info.name == "sqll-base"
    assert info.ok, info.errors
    assert bench_run.check_tools(["sqll-base"]) == []


def test_a_stale_base_binary_fails_its_tool_check(tmp_path, monkeypatch):
    _base_env(tmp_path, monkeypatch, stale=True)
    errors = bench_run.check_tools(["sqll-base"])
    assert len(errors) == 1 and errors[0].startswith("sqll-base: stale binary")


def test_a_missing_base_binary_fails_its_tool_check(tmp_path, monkeypatch):
    _base_env(tmp_path, monkeypatch)
    monkeypatch.setenv(sqll_adapter.BASE_BINARY_ENV, str(tmp_path / "no" / "sqll"))
    errors = bench_run.check_tools(["sqll-base"])
    assert errors and all(e.startswith("sqll-base: ") for e in errors)
    assert "not found" in errors[0] or "does not exist" in errors[0], errors


def test_a_base_with_no_source_folder_fails_its_tool_check(tmp_path, monkeypatch):
    _base_env(tmp_path, monkeypatch)
    monkeypatch.delenv(sqll_adapter.BASE_SOURCE_ENV)
    [info] = tools.check(["sqll-base"])
    assert info.errors == [
        f"{sqll_adapter.BASE_SOURCE_ENV} must be the source folder of the base "
        "binary: None"
    ]


def test_the_head_check_uses_the_source_folder_setting(tmp_path, monkeypatch):
    _fake_readelf(tmp_path, monkeypatch)
    root = _source(tmp_path)
    version = sqll_adapter.expected_version(root)
    binary = fake_sqll(
        tmp_path, version=version, source=sqll_adapter.source_hash(root)[0]
    )
    monkeypatch.setenv("SQLL_BIN", str(binary))
    monkeypatch.setenv(sqll_adapter.SOURCE_ENV, str(root))
    assert tools.check_sqll(tmp_path, TOOL_SPECS_DIR).ok
    monkeypatch.delenv(sqll_adapter.SOURCE_ENV)
    assert not tools.check_sqll(tmp_path, TOOL_SPECS_DIR).ok


def test_the_cli_tool_check_accepts_sqll_base(tmp_path, monkeypatch, capsys):
    _base_env(tmp_path, monkeypatch, stale=True)
    assert cli.main(["tools", "--tool", "sqll-base"]) != 0
    assert "stale binary" in capsys.readouterr().out


# The tool fails closed (exit code 2).


def test_run_inside_stops_on_a_missing_binary(tmp_path, monkeypatch, capsys):
    _base_env(tmp_path, monkeypatch)
    monkeypatch.setenv("SQLL_BIN", str(tmp_path / "no" / "sqll"))
    assert sc.main(["run-inside", "--scratch", str(tmp_path / "s")]) == 2
    err = capsys.readouterr().err
    assert "the tool check: " in err and "sqll: " in err
    assert not (tmp_path / "s" / "session.json").exists()


def test_run_inside_stops_on_a_stale_base_binary(tmp_path, monkeypatch, capsys):
    _base_env(tmp_path, monkeypatch, stale=True)
    assert sc.main(["run-inside", "--scratch", str(tmp_path / "s")]) == 2
    assert "sqll-base: stale binary" in capsys.readouterr().err


def test_collect_binary_refuses_a_missing_or_stale_build(tmp_path):
    root = _source(tmp_path)
    with pytest.raises(sc.Refused, match="the build has no binary"):
        sc.collect_binary(root, tmp_path / "bin")
    built = root / "out" / "sqll" / "bin"
    version = sqll_adapter.expected_version(root)
    fake = fake_sqll(tmp_path / "f", version=version, source="f" * 64)
    built.mkdir(parents=True)
    (built / "sqll").write_bytes(fake.read_bytes())
    (built / "sqll").chmod(0o755)
    with pytest.raises(sc.Refused, match="stale binary"):
        sc.collect_binary(root, tmp_path / "bin")
    fresh = fake_sqll(
        tmp_path / "g", version=version, source=sqll_adapter.source_hash(root)[0]
    )
    (built / "sqll").write_bytes(fresh.read_bytes())
    rec = sc.collect_binary(root, tmp_path / "bin")
    assert rec["version"] == version
    assert rec["source_sha256"] == sqll_adapter.source_hash(root)[0]


def _refused(tmp_path, monkeypatch, capsys, data) -> str:
    write_task(tmp_path, monkeypatch, data)
    assert sc.main(["report", "--task", "C5", "--check"]) == 2
    return capsys.readouterr().err


def test_a_different_input_sha256_is_refused(tmp_path, monkeypatch, capsys):
    data = record()
    data["report"]["inputs"]["ansi/large"]["sha256"] = "0" * 64
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "input ansi/large: not that of the definitions" in err


def test_a_missing_sqruff_result_is_refused(tmp_path, monkeypatch, capsys):
    data = record()
    data["report"]["results"].remove(result(data, "parse/ansi/large", "sqruff"))
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "sqruff: no result for 1: parse/ansi/large" in err


def test_a_report_with_no_sqruff_is_refused(tmp_path, monkeypatch, capsys):
    data = record()
    rep = data["report"]
    rep["results"] = [r for r in rep["results"] if r["tool"] != "sqruff"]
    del rep["tools"]["sqruff"]
    rep["scope"]["tools"].remove("sqruff")
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "the scope is" in err


def test_a_sqruff_status_that_is_not_that_of_the_baseline_is_refused(
    tmp_path, monkeypatch, capsys
):
    data = record()
    r = result(data, "parse/ansi/large", "sqruff")
    r.update(status=INVALID, reason="x", stats=None)
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "sqruff parse/ansi/large: status invalid, the baseline has valid" in err


def test_a_base_that_is_not_valid_is_refused(tmp_path, monkeypatch, capsys):
    data = record()
    r = result(data, "start/ansi", sc.BASE)
    r.update(status=INVALID, reason="x", stats=None)
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "sqll-base start/ansi: invalid: x" in err


def test_other_settings_of_the_base_are_refused(tmp_path, monkeypatch, capsys):
    data = record()
    data["report"]["tools"][sc.BASE]["settings"]["core"]["rules"] = "LT01"
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "sqll-base and sqll have different settings" in err


def test_a_version_that_is_not_that_of_the_build_is_refused(
    tmp_path, monkeypatch, capsys
):
    data = record()
    data["head"]["version"] = "0.0.0"
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "sqll: the version is not that of the head build" in err


def test_a_record_of_another_task_is_refused(tmp_path, monkeypatch, capsys):
    data = record()
    data["task"] = "C6"
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "is not the speed check record of C5" in err


def test_a_missing_record_and_a_bad_task_name_are_refused(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(sc, "SPEED_DIR", tmp_path)
    assert sc.main(["report", "--task", "C5"]) == 2
    assert sc.main(["report", "--task", "../C5"]) == 2
    err = capsys.readouterr().err
    assert "does not exist" in err and "not a task name" in err


def test_run_refuses_a_scratch_folder_that_is_not_empty(tmp_path, capsys):
    (tmp_path / "x").write_text("x")
    argv = ["run", "--task", "C5", "--scratch", str(tmp_path)]
    assert sc.main(argv) == 2
    assert "the scratch folder is not empty" in capsys.readouterr().err


# The machine lock and the container.


def test_the_lock_of_a_parent_process_is_found(tmp_path):
    lock = tmp_path / "lock"
    lock.write_text("")
    st = os.stat(lock)
    key = f"{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino}"
    line = "1: FLOCK  ADVISORY  WRITE {pid} {key} 0 EOF\n"
    parent = line.format(pid=os.getppid(), key=key)
    other = line.format(pid=999999999, key=key)
    waiter = f"1: -> FLOCK  ADVISORY  WRITE {os.getppid()} {key} 0 EOF\n"
    assert sc.held_by_parent(lock, parent)
    assert not sc.held_by_parent(lock, other)
    assert not sc.held_by_parent(lock, waiter)
    assert not sc.held_by_parent(tmp_path / "missing", parent)


def test_the_lock_is_taken_and_given_back(tmp_path):
    import fcntl

    lock = tmp_path / "lock"
    with sc.machine_lock(lock) as how:
        assert how == "taken by scripts/speed-check"
        fd = os.open(lock, os.O_RDWR)
        with pytest.raises(BlockingIOError):
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.close(fd)
    fd = os.open(lock, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.close(fd)


def test_the_container_has_no_network_and_a_read_only_repository(tmp_path):
    argv = sc.docker_argv(tmp_path, "sqll-ci:x")
    assert argv[:5] == ["docker", "run", "--rm", "--network", "none"]
    assert f"{sc.ROOT}:{sc.ROOT}:ro" in argv
    common = sc.git(
        sc.probe.Steps(tmp_path),
        "common",
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
    )
    if not Path(common).is_relative_to(sc.ROOT):
        assert f"{common}:{common}:ro" in argv
    assert argv[argv.index("-w") + 1] == str(sc.ROOT)
    env = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    assert f"SQLL_BIN={sc.C_SCRATCH}/bin/head/sqll" in env
    assert f"{sqll_adapter.BASE_BINARY_ENV}={sc.C_SCRATCH}/bin/base/sqll" in env
    assert f"{sqll_adapter.SOURCE_ENV}={sc.C_SCRATCH}/src/head" in env
    assert f"{sqll_adapter.BASE_SOURCE_ENV}={sc.C_SCRATCH}/src/base" in env
    assert argv[-3:] == ["run-inside", "--scratch", sc.C_SCRATCH]


def test_the_profile_is_full_with_3_timed_runs_at_least():
    assert PROFILES["full"].min_runs >= 3
