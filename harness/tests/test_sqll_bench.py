"""S3 T13: the benchmark adapter of sqll (harness/sqll_harness/bench/sqll.py).

The tests use a fake sqll binary (a Python script), so they need no build.
The CI job bench-smoke runs the real binary of the build job, and
test_bench_baseline.py checks the recorded results of the real binary.
"""

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sqll_harness import tools
from sqll_harness.adapters import sqll as sqll_adapter
from sqll_harness.adapters.base import Unsupported
from sqll_harness.bench import definitions, registry
from sqll_harness.bench import sqll as sqll_bench
from sqll_harness.bench.adapter import INPUT_FILE, Context, settings
from sqll_harness.bench.sqll import OPTIONS_NAME, SqllBench, options
from sqll_harness.bench.timer import PROFILES, UNSUPPORTED, VALID
from sqll_harness.paths import REPO_ROOT, TOOL_SPECS_DIR

SMOKE = PROFILES["smoke"]
VERSION = "0.1.0+tables." + "a" * 64
FAKE = """#!{python} -I
import json, os, sys
args = sys.argv[1:]
with open({log!r}, "a", encoding="utf8") as f:
    f.write(json.dumps([os.getcwd(), args]) + "\\n")
if args == ["--version"]:
    print("sqll, version {version}")
    sys.exit(0)
if args[:1] == ["version"]:
    print(json.dumps({{"version": "{version}", "source_sha256": "{source}"}}))
    sys.exit(0)
if args[:3] != ["parse", "-f", "json"] or args[3] != "--dialect":
    sys.exit(2)
path = args[-1]
with open(path, encoding="utf8") as f:
    text = f.read()
# A tree whose leaf text is the input, in the record shape of sqlfluff.
lines = text.splitlines(keepends=True)
print(json.dumps([{{"filepath": path, "segments": {{"file": [
    {{"line": line}} for line in lines]}}}}]))
"""


def fake_sqll(tmp_path: Path, version: str = VERSION, source: str = "0" * 64):
    """Return (binary, log). The log has one line for each run: [cwd, argv]."""
    log = tmp_path / "sqll-calls.jsonl"
    binary = tmp_path / "bin" / "sqll"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(
        FAKE.format(python=sys.executable, log=str(log), version=version, source=source)
    )
    binary.chmod(0o755)
    return binary, log


def calls(log: Path) -> list[list]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


# The registry and the settings.


def test_sqll_is_in_the_registry(monkeypatch, tmp_path):
    assert registry.REGISTRY["sqll"] is SqllBench
    binary, _ = fake_sqll(tmp_path)
    monkeypatch.setenv("SQLL_BIN", str(binary))
    adapter = registry.get("sqll")
    assert isinstance(adapter, SqllBench)
    assert adapter.s1.binary == binary


def test_the_settings_are_those_of_all_tools():
    adapter = SqllBench(Path("/x/sqll"))
    assert adapter.config(None) == settings()
    assert adapter.config("tsql") == settings("tsql")
    assert adapter.unsupported(adapter.config("tsql")) is None
    assert options(settings("tsql")) == ["--dialect", "tsql"]


def test_max_parse_depth_is_an_option():
    config = settings("ansi")
    config["core"]["max_parse_depth"] = 2000
    assert options(config) == ["--dialect", "ansi", "--max-parse-depth", "2000"]


@pytest.mark.parametrize(
    "section, key, value, item",
    [
        ("core", "templater", "jinja", "setting core.templater = 'jinja'"),
        ("core", "rules", "LT01", "setting core.rules = 'LT01'"),
        ("core", "large_file_skip_byte_limit", 20000, None),
        ("core", "large_file_skip_char_limit", False, None),
        ("core", "max_parse_nodes", 0, "setting core.max_parse_nodes"),
        ("core", "use_rust_parser", True, "setting core.use_rust_parser"),
        ("core", "dialect", "", "setting core.dialect = ''"),
        ("layout", "x", 1, "setting layout.x"),
    ],
)
def test_each_other_setting_is_unsupported(section, key, value, item):
    config = settings("ansi")
    config.setdefault(section, {})[key] = value
    item = item or f"setting {section}.{key} = {value!r}"
    with pytest.raises(Unsupported) as exc:
        options(config)
    assert exc.value.item == item
    assert SqllBench(Path("/x/sqll")).unsupported(config) == item


# The jobs.


def bench(command: str, dialect: str = "tsql", size: str | None = "small") -> dict:
    name = "start" if command == "start" else f"{dialect}/{size}"
    bid = f"start/{dialect}" if command == "start" else f"{command}/{name}"
    return {
        "id": bid,
        "command": command,
        "dialect": dialect,
        "size": None if command == "start" else size,
        "input": name,
    }


def test_start_and_parse_run_sqll_parse_with_the_dialect(bench_inputs_dir, tmp_path):
    binary, log = fake_sqll(tmp_path)
    ctx = Context(definitions.load(), bench_inputs_dir, tmp_path / "work")
    adapter = SqllBench(binary)
    for command in ("start", "parse"):
        bj = adapter.job(bench(command), ctx)
        argv = [str(binary), "parse", "-f", "json", "--dialect", "tsql", INPUT_FILE]
        assert bj.job.argv == argv
        assert (bj.folder / "config" / OPTIONS_NAME).is_file()
        m = bj.measure(SMOKE)
        assert (m.status, m.reason) == (VALID, None)
    # One warmup run and one timed run of each, in a fresh run folder.
    runs = [c for c in calls(log) if c[1][0] == "parse"]
    assert len(runs) == 4
    assert {Path(cwd).name for cwd, _ in runs} == {"warmup", "1"}


@pytest.mark.parametrize("command", ["lint", "fix"])
def test_lint_and_fix_are_unsupported_with_no_run(command, bench_inputs_dir, tmp_path):
    binary, log = fake_sqll(tmp_path)
    ctx = Context(definitions.load(), bench_inputs_dir, tmp_path / "work")
    adapter = SqllBench(binary)
    bj = adapter.job(bench(command), ctx)
    assert bj.job is None
    assert (bj.status, bj.reason) == (UNSUPPORTED, f"unsupported: {command}")
    m = bj.measure(SMOKE)
    assert (m.status, m.reason, m.samples, m.stats) == (
        UNSUPPORTED,
        f"unsupported: {command}",
        [],
        None,
    )
    assert not bj.folder.exists()
    assert calls(log) == []
    with pytest.raises(ValueError, match="no lint"):
        adapter.read_violations(b"[]", INPUT_FILE)
    with pytest.raises(ValueError, match=f"no {command}"):
        adapter.argv(command, tmp_path / "x.json", INPUT_FILE)


def test_a_bad_tree_or_exit_code_is_invalid(bench_inputs_dir, tmp_path):
    binary, _ = fake_sqll(tmp_path)
    ctx = Context(definitions.load(), bench_inputs_dir, tmp_path / "work")
    adapter = SqllBench(binary)
    assert adapter.read_tree(
        b'[{"filepath": "input.sql", "segments": {"file": null}}]\n', INPUT_FILE
    ) == {"file": None}
    with pytest.raises(ValueError, match="is for 'other.sql'"):
        adapter.read_tree(b'[{"filepath": "other.sql", "segments": {}}]', INPUT_FILE)
    # For example a dialect that sqll does not know: exit code 2.
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "sqll").write_text(f"#!{sys.executable} -I\nimport sys\nsys.exit(2)\n")
    (bad / "sqll").chmod(0o755)
    m = SqllBench(bad / "sqll").job(bench("parse"), ctx).measure(SMOKE)
    assert m.status == "invalid"
    assert m.reason == "warmup run: exit code 2, expected 0"


def test_through_the_registry_sqll_runs_each_benchmark_of_the_definitions(
    bench_inputs_dir, tmp_path, monkeypatch
):
    """All 28 start and 84 parse benchmarks are valid, lint and fix are
    unsupported with no run, and the definitions do not change."""
    before = definitions.DEFINITIONS.read_bytes()
    binary, log = fake_sqll(tmp_path)
    monkeypatch.setenv("SQLL_BIN", str(binary))
    defs = definitions.load()
    ctx = Context(defs, bench_inputs_dir, tmp_path / "work")
    tool = registry.get("sqll")
    by_dialect: dict[str, list[dict]] = {}
    for b in defs["benchmarks"]:
        by_dialect.setdefault(b["dialect"], []).append(b)

    def run(benchmarks):
        return [(b, tool.job(b, ctx).measure(SMOKE)) for b in benchmarks]

    with ThreadPoolExecutor(4) as pool:
        results = [r for part in pool.map(run, by_dialect.values()) for r in part]
    counts: dict[tuple[str, str], int] = {}
    for b, m in results:
        key = (b["command"], m.status)
        counts[key] = counts.get(key, 0) + 1
        if m.status == UNSUPPORTED:
            assert m.reason == f"unsupported: {b['command']}"
        else:
            assert m.reason is None, (b["id"], m.reason)
    assert counts == {
        ("start", VALID): 28,
        ("parse", VALID): 84,
        ("lint", UNSUPPORTED): 84,
        ("fix", UNSUPPORTED): 84,
    }
    # Only parse runs, each with the dialect of its benchmark.
    runs = [args for _, args in calls(log) if args != ["--version"]]
    assert len(runs) == 2 * 112
    dialects = {args[4] for args in runs}
    assert dialects == set(by_dialect)
    assert definitions.DEFINITIONS.read_bytes() == before


# The tool record of the report.


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _fake_readelf(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "path"
    path.mkdir()
    (path / "readelf").write_text(
        "#!/bin/sh\necho ' 0x1 (NEEDED)  Shared library: [libc.so.6]'\n"
    )
    (path / "readelf").chmod(0o755)
    monkeypatch.setenv("PATH", f"{path}{os.pathsep}{os.environ['PATH']}")


def test_the_tool_record_is_the_same_for_2_commits(tmp_path, monkeypatch):
    """The report records the version and the settings of sqll. They are
    the same for 2 commits that change the code but not the crate version or
    the tables, so the baseline check does not fail for each commit. The
    source hash (the stale-binary check) is not the same."""
    _fake_readelf(tmp_path, monkeypatch)
    root = tmp_path / "worktree"
    root.mkdir()
    for name in sqll_adapter.SOURCE_FILES:
        shutil.copy2(REPO_ROOT / name, root / name)
    for top in sqll_adapter.SOURCE_DIRS:
        shutil.copytree(REPO_ROOT / top, root / top)
    _git(root, "init", "-q")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "a")
    main_rs = root / "crates" / "sqll" / "src" / "main.rs"
    main_rs.write_text(main_rs.read_text() + "\n// A change of the code.\n")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "b")
    commits = _git(root, "rev-list", "HEAD").split()
    assert len(commits) == 2
    records, sources = [], []
    for i, commit in enumerate(reversed(commits)):
        _git(root, "checkout", "-q", commit)
        version = sqll_adapter.expected_version(root)
        source, _ = sqll_adapter.source_hash(root)
        binary, _ = fake_sqll(tmp_path / str(i), version, source)
        info = tools.check_sqll(tmp_path, TOOL_SPECS_DIR, binary=binary, worktree=root)
        assert info.ok, info.errors
        adapter = SqllBench(binary)
        records.append({"version": adapter.version(), "settings": adapter.config(None)})
        sources.append(source)
    assert records[0] == records[1]
    assert records[0]["version"] == sqll_adapter.expected_version(REPO_ROOT)
    assert sources[0] != sources[1]


def test_the_module_is_the_registry_entry():
    assert sqll_bench.SqllBench.name == "sqll"
    assert sorted(registry.names()) == ["sqlfluff", "sqlfluff-rs", "sqll", "sqruff"]
