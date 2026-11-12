"""S3 T13, S3b C14, and S3b C17: the benchmark adapter of sqll
(harness/sqll_harness/bench/sqll.py).

The goals: S3 (choose the base and make the sqll binary from it); S3b
(core: the shared syntax tree, source map, frozen interfaces, and the sqll
binary skeleton); T13 (S2 benchmark adapter for sqll, and the new S2
baseline); C11 (config skeleton: the config model, the sqlfluff
defaults, and the config file reader in sqll parse); C14 (harness
adapters: sqll lint and fix in the test harness and the benchmarks); C17
(S3b exit: proof, exit record, and STATUS "S3b awaiting approval").

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
from sqll_harness.bench.sqll import (
    LEGACY_OPTIONS_NAME,
    SqllBaseBench,
    SqllBench,
    legacy_options,
    selected_rules,
)
from sqll_harness.bench.timer import PROFILES, UNSUPPORTED, VALID
from sqll_harness.paths import REPO_ROOT, TOOL_SPECS_DIR

SMOKE = PROFILES["smoke"]
VERSION = "0.1.0+tables." + "a" * 64
# The fake has the rules HAVE of the sqlfluff rules EVERY.
EVERY = ("AL01", "CP01", "CP03", "LT01")
FAKE = """#!{python} -I
import json, os, sys, tomllib
args = sys.argv[1:]
have = {have!r}
every = {every!r}
if args == ["--version"]:
    print("sqll, version {version}")
    sys.exit(0)
if args[:1] == ["version"]:
    print(json.dumps({{"version": "{version}", "source_sha256": "{source}"}}))
    sys.exit(0)
if args[:1] == ["rules"]:
    excluded = []
    if os.path.exists(".sqlfluff"):
        with open(".sqlfluff", encoding="utf8") as f:
            excluded = f.read().split("=")[1].strip().split(",")
    missing = [c for c in every if c not in have and c not in excluded]
    if missing:
        print("Error: unsupported: rules " + ", ".join(missing)
              + ": sqll does not have them yet (S5).", file=sys.stderr)
        sys.exit(2)
    print("==== sqlfluff - rules ====")
    for c in every:
        if c not in excluded:
            print(c + ": [name] A rule.")
            print("      groups: all")
    sys.exit(0)
if args == ["parse", "--help"]:
    print("Options: --dialect" + ("" if {legacy} else " --config"))
    sys.exit(0)
if args[:1] not in (["parse"], ["lint"], ["fix"]):
    sys.exit(2)
if "--config" in args and not {legacy}:
    with open(args[args.index("--config") + 1], "rb") as f:
        dialect = tomllib.load(f)["tool"]["sqlfluff"]["core"]["dialect"]
elif "--dialect" in args:
    dialect = args[args.index("--dialect") + 1]
else:
    sys.exit(2)
with open({log!r}, "a", encoding="utf8") as f:
    f.write(json.dumps([os.getcwd(), args, dialect]) + "\\n")
path = args[-1]
with open(path, encoding="utf8") as f:
    text = f.read()
if args[0] == "lint":
    print(json.dumps([{{"filepath": path, "violations": [{{"code": "CP01"}}]}}]))
    sys.exit(1)
if args[0] == "fix":
    with open(path, "w", encoding="utf8") as f:
        f.write(text.lower())
    sys.exit(0)
# A tree whose leaf text is the input, in the record shape of sqlfluff.
lines = text.splitlines(keepends=True)
print(json.dumps([{{"filepath": path, "segments": {{"file": [
    {{"line": line}} for line in lines]}}}}]))
"""


def fake_sqll(
    tmp_path: Path,
    version: str = VERSION,
    source: str = "0" * 64,
    have: tuple[str, ...] = ("CP01", "CP03"),
    legacy: bool = False,
):
    """Return (binary, log). The log has one line for each parse, lint, or
    fix run: [cwd, argv, dialect]. have: the rules of the fake. legacy: a
    binary from before S3b C11 (no --config)."""
    log = tmp_path / "sqll-calls.jsonl"
    binary = tmp_path / "bin" / "sqll"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(
        FAKE.format(
            python=sys.executable,
            log=str(log),
            version=version,
            source=source,
            have=have,
            every=EVERY,
            legacy=legacy,
        )
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


def test_the_settings_are_those_of_all_tools(tmp_path):
    binary, _ = fake_sqll(tmp_path)
    adapter = SqllBench(binary)
    assert adapter.config(None) == settings()
    assert adapter.config("tsql") == settings("tsql")
    assert adapter.unsupported(adapter.config("tsql")) is None
    # The settings go to sqll as a sqlfluff config file.
    path = adapter.write_config(adapter.config("tsql"), tmp_path / "config")
    assert path.name == "pyproject.toml"
    assert path.read_text() == (
        "[tool.sqlfluff.core]\n"
        'dialect = "tsql"\n'
        'templater = "raw"\n'
        'rules = "all"\n'
        "large_file_skip_byte_limit = 0\n"
        "large_file_skip_char_limit = 0\n"
    )


# A base binary of a speed check from before S3b C11 (C17: the speed check
# of the S3b exit has the S3 exit as its base). The goals are in the module
# docstring.


def test_the_legacy_options():
    assert legacy_options(settings("tsql")) == ["--dialect", "tsql"]
    config = settings("ansi")
    config["core"]["max_parse_depth"] = 2000
    assert legacy_options(config) == ["--dialect", "ansi", "--max-parse-depth", "2000"]


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
def test_a_legacy_base_binary_gets_only_its_settings(
    section, key, value, item, tmp_path
):
    # It reads no config file: each other setting is unsupported with no run.
    config = settings("ansi")
    config.setdefault(section, {})[key] = value
    item = item or f"setting {section}.{key} = {value!r}"
    with pytest.raises(Unsupported) as exc:
        legacy_options(config)
    assert exc.value.item == item
    binary, _ = fake_sqll(tmp_path, legacy=True)
    assert SqllBaseBench(binary).unsupported(config) == item
    # A base binary since C11 reads the setting, and fails closed if it
    # cannot do it.
    binary, _ = fake_sqll(tmp_path / "new")
    assert SqllBaseBench(binary).unsupported(config) is None


def test_a_legacy_base_binary_gets_the_settings_as_options(bench_inputs_dir, tmp_path):
    binary, log = fake_sqll(tmp_path, legacy=True)
    ctx = Context(definitions.load(), bench_inputs_dir, tmp_path / "work")
    adapter = SqllBaseBench(binary)
    assert adapter.reads_config() is False
    for command in ("start", "parse"):
        bj = adapter.job(bench(command), ctx)
        argv = [str(binary), "parse", "-f", "json", "--dialect", "tsql", INPUT_FILE]
        assert bj.job.argv == argv
        assert (bj.folder / "config" / LEGACY_OPTIONS_NAME).is_file()
        m = bj.measure(SMOKE)
        assert (m.status, m.reason) == (VALID, None)
    assert {dialect for _, _, dialect in calls(log)} == {"tsql"}
    with pytest.raises(ValueError, match="no lint command"):
        adapter.argv("lint", bj.folder / "config" / LEGACY_OPTIONS_NAME, INPUT_FILE)
    bad = tmp_path / LEGACY_OPTIONS_NAME
    bad.write_text('{"x": 1}')
    with pytest.raises(ValueError, match="not a list of options"):
        adapter.argv("parse", bad, INPUT_FILE)


def test_only_a_legacy_base_binary_gets_the_options(bench_inputs_dir, tmp_path):
    """sqll (the head) always gets the config file; a base binary since C11
    also gets it. A legacy binary as sqll fails: it has no --config."""
    ctx = Context(definitions.load(), bench_inputs_dir, tmp_path / "work")
    new, _ = fake_sqll(tmp_path / "new")
    legacy, _ = fake_sqll(tmp_path / "legacy", legacy=True)
    assert SqllBaseBench(new).reads_config() is True
    for adapter in (SqllBaseBench(new), SqllBench(legacy), SqllBench(new)):
        bj = adapter.job(bench("parse"), ctx)
        assert "--config" in bj.job.argv
        assert (bj.folder / "config" / "pyproject.toml").is_file()
    m = SqllBench(legacy).job(bench("parse"), ctx).measure(SMOKE)
    assert m.status == "invalid"
    assert m.reason == "warmup run: exit code 2, expected 0"


def test_the_selected_rules():
    every = frozenset(EVERY)
    assert selected_rules(settings(), every) == sorted(EVERY)
    assert selected_rules({"core": {"rules": "CP01, LT01"}}, every) == ["CP01", "LT01"]
    assert selected_rules({"core": {"rules": ["CP01"]}}, every) == ["CP01"]
    config = {"core": {"rules": "all", "exclude_rules": "AL01,LT01"}}
    assert selected_rules(config, every) == ["CP01", "CP03"]
    # A name or a group stays as it is: it is never a rule of sqll.
    assert selected_rules({"core": {"rules": "core"}}, every) == ["core"]


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
        config = bj.folder / "config" / "pyproject.toml"
        argv = [str(binary), "parse", "-f", "json", "--ignore-local-config"]
        argv += ["--config", str(config), INPUT_FILE]
        assert bj.job.argv == argv
        assert config.is_file()
        m = bj.measure(SMOKE)
        assert (m.status, m.reason) == (VALID, None)
    # One warmup run and one timed run of each, in a fresh run folder.
    runs = calls(log)
    assert len(runs) == 4
    assert {Path(cwd).name for cwd, _, _ in runs} == {"warmup", "1"}
    assert {dialect for _, _, dialect in runs} == {"tsql"}


ALL_REASON = (
    "unsupported: rule AL01, LT01 ({command}: sqll does not have 2 of the 4 "
    "rules of the settings)"
)


@pytest.mark.parametrize("command", ["lint", "fix"])
def test_lint_and_fix_are_unsupported_with_no_run(command, bench_inputs_dir, tmp_path):
    # The S2 settings select all rules, and sqll does not have them all.
    binary, log = fake_sqll(tmp_path)
    ctx = Context(definitions.load(), bench_inputs_dir, tmp_path / "work")
    adapter = SqllBench(binary)
    bj = adapter.job(bench(command), ctx)
    reason = ALL_REASON.format(command=command)
    assert bj.job is None
    assert (bj.status, bj.reason) == (UNSUPPORTED, reason)
    m = bj.measure(SMOKE)
    assert (m.status, m.reason, m.samples, m.stats) == (UNSUPPORTED, reason, [], None)
    assert not bj.folder.exists()
    assert calls(log) == []
    # Also when sqll does not have one rule of the settings.
    adapter.base_settings["core"]["rules"] = "CP01,LT01"
    bj = adapter.job(bench(command), ctx)
    assert (bj.status, bj.job) == (UNSUPPORTED, None)
    assert bj.reason == (
        f"unsupported: rule LT01 ({command}: sqll does not have 1 of the 2 rules "
        "of the settings)"
    )
    assert calls(log) == []


@pytest.mark.parametrize("command", ["lint", "fix"])
def test_the_rule_check_uses_the_config_of_the_benchmark(
    command, bench_inputs_dir, tmp_path
):
    # The config of a benchmark can select other rules than the record
    # config (dialect None). The check must read the config of the job.
    binary, log = fake_sqll(tmp_path)

    class DialectRules(SqllBench):
        def layer(self, config):
            if config.get("core", {}).get("dialect") == "ansi":
                config["core"]["rules"] = "CP01"
            return config

    ctx = Context(definitions.load(), bench_inputs_dir, tmp_path / "work")
    adapter = DialectRules(binary)
    assert selected_rules(adapter.config(None), frozenset(EVERY)) == sorted(EVERY)
    bj = adapter.job(bench(command, dialect="ansi"), ctx)
    assert bj.status != UNSUPPORTED
    assert bj.job is not None
    bj = adapter.job(bench(command), ctx)
    assert (bj.status, bj.reason) == (UNSUPPORTED, ALL_REASON.format(command=command))
    assert calls(log) == []


def test_lint_and_fix_run_when_sqll_has_each_rule(bench_inputs_dir, tmp_path):
    binary, log = fake_sqll(tmp_path, have=EVERY)
    ctx = Context(definitions.load(), bench_inputs_dir, tmp_path / "work")
    adapter = SqllBench(binary)
    # With all rules in sqll, the S2 settings (rules = all) run.
    for command in ("parse", "lint", "fix"):
        bj = adapter.job(bench(command), ctx)
        config = bj.folder / "config" / "pyproject.toml"
        argv = [str(binary), *adapter.commands[command], "--ignore-local-config"]
        assert bj.job.argv == [*argv, "--config", str(config), INPUT_FILE]
        assert adapter.unsupported_command(command, adapter.config("tsql")) is None
        m = bj.measure(SMOKE)
        if command == "parse":
            assert (m.status, m.reason) == (VALID, None)
        else:
            # The fake gives only CP01, so the run reaches the comparison
            # with the sqlfluff reference, and it fails there.
            assert m.status == "invalid"
            assert m.reason.startswith("warmup run: ")
            assert "the rule codes are not those of the sqlfluff reference" in m.reason
    # parse: a warmup and a timed run; lint and fix stop after the warmup.
    assert [args[0] for _, args, _ in calls(log)] == ["parse", "parse", "lint", "fix"]
    assert adapter.read_violations(
        b'[{"filepath": "input.sql", "violations": [{"code": "CP01"}]}]', INPUT_FILE
    ) == [{"code": "CP01"}]
    assert adapter.read_violations(b"[]", INPUT_FILE) is None
    with pytest.raises(ValueError, match="no start"):
        adapter.argv("start2", tmp_path / "x.toml", INPUT_FILE)


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
            assert m.reason == ALL_REASON.format(command=b["command"])
        else:
            assert m.reason is None, (b["id"], m.reason)
    assert counts == {
        ("start", VALID): 28,
        ("parse", VALID): 84,
        ("lint", UNSUPPORTED): 84,
        ("fix", UNSUPPORTED): 84,
    }
    # Only parse runs, each with the dialect of its benchmark.
    runs = calls(log)
    assert len(runs) == 2 * 112
    dialects = {dialect for _, _, dialect in runs}
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
