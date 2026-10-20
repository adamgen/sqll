"""The benchmark adapters and validity checks (harness/bench.md, "Validity",
"Add a tool"), with a test-double tool and recorded outputs. The tests with
the real tools are in test_bench_tools.py."""

import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sqll_harness import cli
from sqll_harness.adapters.base import EmptyHome, isolated_env
from sqll_harness.adapters.sqlfluff_rs import RUST_CONFIG
from sqll_harness.adapters.sqruff_config import SQLFLUFF_DEFAULTS
from sqll_harness.bench import adapter as bench_adapter
from sqll_harness.bench import definitions, reference, registry
from sqll_harness.bench.adapter import (
    INPUT_FILE,
    BenchAdapter,
    ConfigAbove,
    Context,
    check_run,
    settings,
)
from sqll_harness.bench.timer import (
    ERROR,
    INVALID,
    PROFILES,
    UNSUPPORTED,
    VALID,
    WARMUP,
    Policy,
    Run,
    Sample,
)
from sqll_harness.bench.tools import SqlfluffBench, SqlfluffRsBench, SqruffBench

TOOL = Path(__file__).parent / "fixtures" / "bench" / "tool.py"
SMOKE = PROFILES["smoke"]


class DoubleBench(BenchAdapter):
    """The adapter of the test-double tool (fixtures/bench/tool.py)."""

    name = "double"

    def __init__(self, defs_file: Path = definitions.DEFINITIONS, no=()) -> None:
        super().__init__()
        self.defs_file = defs_file
        self.no = set(no)

    def version(self) -> str:
        return "1.0"

    def unsupported(self, config):
        dialect = config["core"]["dialect"]
        return f"dialect {dialect}" if dialect in self.no else None

    def write_config(self, config, folder):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "double.json"
        path.write_text(json.dumps(config), encoding="utf8")
        return path

    def argv(self, command, config_file, sql):
        command = "parse" if command == "start" else command
        return [sys.executable, "-I", str(TOOL), command, str(config_file), sql]

    def env(self):
        env = isolated_env(EmptyHome.path())
        env["SQLL_DOUBLE_DEFINITIONS"] = str(self.defs_file)
        return env

    def read_tree(self, stdout, sql):
        return json.loads(stdout)

    def read_violations(self, stdout, sql):
        return json.loads(stdout).get(sql)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def custom(tmp_path: Path, sql: dict[str, bytes], reference=None) -> tuple[dict, Path]:
    """Return definitions and an inputs folder with these inputs."""
    folder = tmp_path / "inputs"
    defs = {"inputs": {}, "reference": {"sqlfluff_version": "1", "inputs": {}}}
    for name, data in sql.items():
        path = folder / f"{name}.sql"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        defs["inputs"][name] = {"sha256": _sha(data)}
    for name, (codes, changes) in (reference or {}).items():
        defs["reference"]["inputs"][name] = {
            "sha256": _sha(sql[name]),
            "lint_codes": codes,
            "fix_changes": changes,
        }
    return defs, folder


def bench(command: str, name: str, dialect: str = "ansi") -> dict:
    return {
        "id": f"{command}/{name}",
        "command": command,
        "dialect": dialect,
        "size": None,
        "input": name,
    }


# Registry and settings.


def test_the_registry_has_the_3_tools():
    assert registry.names() == ["sqlfluff", "sqlfluff-rs", "sqruff"]
    for name in registry.names():
        assert registry.REGISTRY[name].name == name


def test_register_adds_one_tool_and_refuses_a_repeated_name(monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY", dict(registry.REGISTRY))
    registry.register("double", DoubleBench)
    assert registry.names() == ["double", "sqlfluff", "sqlfluff-rs", "sqruff"]
    assert isinstance(registry.get("double"), DoubleBench)
    with pytest.raises(ValueError, match="already"):
        registry.register("sqruff", DoubleBench)


def test_each_tool_gets_the_same_settings_with_its_s1_layer(tmp_path):
    want = {
        "core": {
            "dialect": "tsql",
            "templater": "raw",
            "rules": "all",
            "large_file_skip_byte_limit": 0,
            "large_file_skip_char_limit": 0,
        }
    }
    assert settings("tsql") == want
    assert SqlfluffBench().config("tsql") == want
    rs = SqlfluffRsBench().config("tsql")
    assert rs == {"core": {**want["core"], **RUST_CONFIG["core"]}}
    sqruff = SqruffBench().config("tsql")
    assert sqruff["core"] == want["core"]
    assert sqruff["layout"] == SQLFLUFF_DEFAULTS["layout"]
    # The report record has no dialect.
    assert "dialect" not in SqlfluffBench().config(None)["core"]
    # The config files, as the S1 adapters write them.
    text = SqlfluffRsBench().write_config(rs, tmp_path / "a").read_text()
    assert 'dialect = "tsql"' in text and "use_rust_parser = true" in text
    assert "large_file_skip_byte_limit = 0" in text
    text = SqruffBench().write_config(sqruff, tmp_path / "b").read_text()
    lines = text.splitlines()
    assert lines[0] == "[sqruff]"
    for line in (
        "dialect = tsql",
        "templater = raw",
        "rules = all",
        "large_file_skip_byte_limit = 0",
        "large_file_skip_char_limit = 0",
        "[sqruff:layout:type:match_condition]",
        "spacing_within = touch:inline",
    ):
        assert line in lines


@pytest.mark.parametrize(
    "tool, command, words",
    [
        ("sqlfluff", "start", ["parse", "-f", "json", "--ignore-local-config"]),
        ("sqlfluff", "parse", ["parse", "-f", "json", "--ignore-local-config"]),
        ("sqlfluff", "lint", ["lint", "-f", "json", "--ignore-local-config"]),
        ("sqlfluff", "fix", ["fix", "--ignore-local-config"]),
        ("sqlfluff-rs", "lint", ["lint", "-f", "json", "--ignore-local-config"]),
        ("sqruff", "start", ["parse", "-f", "json"]),
        ("sqruff", "parse", ["parse", "-f", "json"]),
        ("sqruff", "lint", ["lint", "-f", "json", "--parsing-errors"]),
        ("sqruff", "fix", ["fix", "-f", "human"]),
    ],
)
def test_command_lines(tool, command, words):
    a = registry.get(tool)
    argv = a.argv(command, Path("/w/config/c"), INPUT_FILE)
    binary = "sqlfluff" if tool != "sqruff" else "sqruff"
    assert Path(argv[0]).name == binary
    assert argv[1:] == [*words, "--config", "/w/config/c", INPUT_FILE]


def test_the_tools_get_no_user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/x")
    for name in registry.names():
        env = registry.get(name).env()
        assert env["HOME"] == env["XDG_CONFIG_HOME"] == str(EmptyHome.path())
        assert "PYTHONPATH" not in env
    # A config file above the work folder stops the run.
    (tmp_path / "pyproject.toml").write_text("[tool.sqlfluff.core]\ndialect = 'x'\n")
    with pytest.raises(ConfigAbove, match="pyproject.toml"):
        Context({"inputs": {}}, tmp_path, tmp_path / "work")
    (tmp_path / "pyproject.toml").unlink()
    (tmp_path / ".sqruff").write_text("[sqruff]\n")
    with pytest.raises(ConfigAbove, match=".sqruff"):
        Context({"inputs": {}}, tmp_path, tmp_path / "work")


# The test-double tool.


def test_a_tool_from_the_registry_runs_all_definitions(
    bench_inputs_dir, tmp_path, monkeypatch
):
    """A new tool is one adapter and one registry entry: all benchmarks of
    the definitions are valid, and the definitions do not change."""
    before = definitions.DEFINITIONS.read_bytes()
    monkeypatch.setattr(registry, "REGISTRY", dict(registry.REGISTRY))
    registry.register("double", DoubleBench)
    defs = definitions.load()
    ctx = Context(defs, bench_inputs_dir, tmp_path / "work")
    tool = registry.get("double")
    by_dialect: dict[str, list[dict]] = {}
    for b in defs["benchmarks"]:
        by_dialect.setdefault(b["dialect"], []).append(b)

    def run(benchmarks):
        out = []
        for b in benchmarks:
            bj = tool.job(b, ctx)
            out.append((b["id"], bj.measure(SMOKE), bj.work))
        return out

    with ThreadPoolExecutor(4) as pool:
        results = [r for part in pool.map(run, by_dialect.values()) for r in part]
    assert len(results) == len(defs["benchmarks"]) == 280
    bad = [(i, m.status, m.reason) for i, m, _ in results if m.status != VALID]
    assert bad == []
    works = {i: w for i, _, w in results}
    ref = defs["reference"]["inputs"]
    assert works["lint/ansi/large"]["codes"] == ref["ansi/large"]["lint_codes"]
    assert works["fix/ansi/large"]["changed"] is True
    assert works["parse/ansi/large"] is None
    assert definitions.DEFINITIONS.read_bytes() == before


def test_an_unsupported_dialect_gives_unsupported_with_no_run(tmp_path):
    defs, folder = custom(tmp_path, {"start": b"SELECT 1;\n"})
    ctx = Context(defs, folder, tmp_path / "work")
    bj = DoubleBench(no={"soql"}).job(bench("start", "start", "soql"), ctx)
    assert bj.job is None
    m = bj.measure(SMOKE)
    assert (m.status, m.reason, m.samples, m.stats) == (
        UNSUPPORTED,
        "unsupported: dialect soql",
        [],
        None,
    )


def test_fix_runs_start_from_an_unchanged_copy_of_the_input(tmp_path):
    data = b"select a from b;\n"
    defs, folder = custom(tmp_path, {"d/s": data}, {"d/s": (["LT01"], True)})
    defs_file = tmp_path / "defs.json"
    defs_file.write_text(json.dumps(defs))
    ctx = Context(defs, folder, tmp_path / "work")
    tool = DoubleBench(defs_file)
    bj = tool.job(bench("fix", "d/s"), ctx)
    m = bj.measure(Policy(5, 5, 0.0, 30.0), keep_timed=True)
    # The double exits with code 3 if a run sees the fix of an earlier run.
    assert m.status == VALID, m.reason
    assert [s.exit_code for s in m.samples] == [0] * 6
    fixed = data + b"-- fixed by the test double\n"
    for run in ["warmup", "1", "2", "3", "4", "5"]:
        assert (bj.runs_folder / run / INPUT_FILE).read_bytes() == fixed
    assert bj.work == {"changed": True, "fixed_sha256": _sha(fixed)}
    assert (folder / "d" / "s.sql").read_bytes() == data
    # Control: a second fix of the same file fails.
    job = bj.job
    run = bench_adapter.run_once(
        job.argv,
        bj.runs_folder / "1",
        kind=WARMUP,
        cwd=bj.runs_folder / "1",
        env=job.env,
        timeout_s=30,
    )
    assert run.sample.exit_code == 3


def test_settings_that_the_tool_does_not_get_are_invalid(tmp_path):
    defs, folder = custom(tmp_path, {"start": b"SELECT 1;\n"})
    ctx = Context(defs, folder, tmp_path / "work")
    tool = DoubleBench()
    tool.base_settings = {"core": {"templater": "jinja", "rules": "all"}}
    m = tool.job(bench("start", "start"), ctx).measure(SMOKE)
    assert (m.status, m.reason) == (INVALID, "warmup run: exit code 2, expected 0")


def test_an_input_that_is_not_that_of_the_definitions_is_an_error(tmp_path):
    defs, folder = custom(tmp_path, {"d/s": b"select 1;\n"})
    (folder / "d" / "s.sql").write_bytes(b"select 2;\n")
    ctx = Context(defs, folder, tmp_path / "work")
    m = DoubleBench().job(bench("parse", "d/s"), ctx).measure(SMOKE)
    assert m.status == ERROR
    assert "is not the input of the definitions (sha256)" in m.reason


def test_no_reference_for_the_input_is_an_error(tmp_path):
    defs, folder = custom(tmp_path, {"d/s": b"select 1;\n"})
    defs_file = tmp_path / "defs.json"
    defs_file.write_text(json.dumps(defs))
    ctx = Context(defs, folder, tmp_path / "work")
    m = DoubleBench(defs_file).job(bench("lint", "d/s"), ctx).measure(SMOKE)
    assert m.status == ERROR
    assert "no sqlfluff reference for input d/s" in m.reason


def test_lint_and_fix_need_the_check_of_the_command_before(tmp_path):
    data = b"select a from b;\n"
    defs, folder = custom(tmp_path, {"d/s": data}, {"d/s": (["LT01"], True)})
    defs_file = tmp_path / "defs.json"
    defs_file.write_text(json.dumps(defs))
    ctx = Context(defs, folder, tmp_path / "work")
    tool = DoubleBench(defs_file)
    ctx.note(
        ("double", "parse", "ansi", "d/s"), "the tree has an unparsable segment", None
    )
    lint = tool.job(bench("lint", "d/s"), ctx).measure(SMOKE)
    assert lint.status == INVALID
    assert lint.reason == (
        "warmup run: the parse check fails: the tree has an unparsable segment"
    )
    fix = tool.job(bench("fix", "d/s"), ctx).measure(SMOKE)
    assert fix.reason == (
        "warmup run: the lint check fails: the parse check fails: the tree has "
        "an unparsable segment"
    )
    # With no earlier result, the check runs the command once, in checks/.
    ctx2 = Context(defs, folder, tmp_path / "work2")
    fix = tool.job(bench("fix", "d/s"), ctx2).measure(SMOKE)
    assert fix.status == VALID, fix.reason
    assert ctx2.checked == {
        ("double", c, "ansi", "d/s"): None for c in ("parse", "lint", "fix")
    }
    assert (tmp_path / "work2" / "double" / "checks" / "lint").is_dir()


def test_a_failed_warmup_is_recorded_for_the_next_check(tmp_path):
    defs, folder = custom(tmp_path, {"d/s": b"select 1;\n"})
    ctx = Context(defs, folder, tmp_path / "work")
    tool = DoubleBench()
    tool.base_settings = {"core": {}}
    m = tool.job(bench("parse", "d/s"), ctx).measure(SMOKE)
    assert m.status == INVALID
    assert ctx.checked[("double", "parse", "ansi", "d/s")] == m.reason


# The checks, on recorded outputs.


def fake_run(folder: Path, stdout=b"", stderr=b"", exit_code=0, fixed=None) -> Run:
    folder.mkdir(parents=True)
    (folder / "stdout").write_bytes(stdout)
    (folder / "stderr").write_bytes(stderr)
    if fixed is not None:
        (folder / INPUT_FILE).write_bytes(fixed)
    return Run(Sample(WARMUP, 0.1, 0.1, 0.0, 1000, exit_code, False), folder)


SQL = b"select a\nfrom b;\n"


def sqlfluff_tree(*leaves: tuple[str, str]) -> bytes:
    segments = {"file": [{k: v} for k, v in leaves]}
    return json.dumps([{"filepath": INPUT_FILE, "segments": segments}]).encode()


GOOD_TREE = sqlfluff_tree(("a", "select a\n"), ("b", "from b;\n"))


@pytest.fixture
def ctx(tmp_path) -> Context:
    defs, folder = custom(tmp_path, {"d/s": SQL}, {"d/s": (["CP01", "LT01"], True)})
    c = Context(defs, folder, tmp_path / "work")
    for tool in ("sqlfluff", "sqruff"):
        for command in ("parse", "lint"):
            c.note((tool, command, "ansi", "d/s"), None, None)
    return c


def check(ctx, tool, command, tmp_path, **out):
    adapter = registry.get(tool)
    return check_run(
        adapter, ctx, bench(command, "d/s"), SQL, fake_run(tmp_path / "r", **out)
    )


@pytest.mark.parametrize(
    "stdout, exit_code, reason",
    [
        (GOOD_TREE, 0, None),
        (GOOD_TREE, 1, "exit code 1, expected 0"),
        (
            sqlfluff_tree(("a", "select a\n"), ("unparsable", "from b;\n")),
            0,
            "the tree has an unparsable segment",
        ),
        (
            sqlfluff_tree(("a", "select a\n")),
            0,
            "the tree text (9 characters) is not the input text (17 characters)",
        ),
        (b"[]", 0, "no parse tree: ValueError('not 1 parse record: []')"),
        (
            json.dumps([{"filepath": INPUT_FILE, "segments": None}]).encode(),
            0,
            "no parse tree",
        ),
    ],
)
def test_the_parse_check(ctx, tmp_path, stdout, exit_code, reason):
    assert (
        check(ctx, "sqlfluff", "parse", tmp_path, stdout=stdout, exit_code=exit_code)[0]
        == reason
    )


@pytest.mark.parametrize(
    "tool, stderr, reason",
    [
        (
            "sqlfluff",
            b"WARNING    Length of file 'input.sql' is 24575 bytes which is over the "
            b"limit of 20000 bytes. Skipping to avoid parser lock.\n",
            "the tool skipped the file (size limit): WARNING    Length of file",
        ),
        (
            "sqlfluff",
            b"Traceback (most recent call last):\n  File x\nValueError\n",
            "the tool crashed: Traceback (most recent call last):",
        ),
        (
            "sqlfluff",
            b"WARNING    Tried to allowlist unknown rule references: ['x']\n",
            "unknown rule: WARNING    Tried to allowlist",
        ),
        (
            "sqlfluff-rs",
            b"WARNING    sqlfluffrs not available\n",
            "sqlfluff used the Python parser: WARNING    sqlfluffrs not available",
        ),
        (
            "sqruff",
            b"thread 'main' panicked at src/x.rs:1:2:\nboom\n",
            "the tool crashed (panic): thread 'main' panicked at src/x.rs:1:2:",
        ),
        (
            "sqruff",
            b"Unknown rule(s) in configuration: x. Available rules are: AL01\n",
            "unknown rule: Unknown rule(s) in configuration: x.",
        ),
    ],
)
def test_a_problem_message_makes_the_run_invalid(ctx, tmp_path, tool, stderr, reason):
    got, _ = check(ctx, tool, "parse", tmp_path, stdout=GOOD_TREE, stderr=stderr)
    assert got.startswith(reason), got


@pytest.mark.parametrize(
    "tool, stdout, reason",
    [
        (
            "sqlfluff",
            b"CRITICAL   [LT02] Applying rule LT02 threw an Exception\n",
            "a CRITICAL log: CRITICAL   [LT02]",
        ),
        (
            "sqlfluff",
            b"WARNING    Length of file 'input.sql' is over 9 characters. "
            b"Skipping to avoid parser lock.\n",
            "the tool skipped the file (size limit)",
        ),
        (
            "sqlfluff",
            b"  [1 templating/parsing errors found]\n",
            "the tool did not fix the file (parse errors)",
        ),
        (
            "sqruff",
            b"== [input.sql] SKIP: File is 24575 bytes, exceeding "
            b"large_file_skip_byte_limit of 20000 bytes.\n",
            "the tool skipped the file (size limit)",
        ),
    ],
)
def test_the_fix_check_reads_stdout_for_problems(ctx, tmp_path, tool, stdout, reason):
    got, _ = check(ctx, tool, "fix", tmp_path, stdout=stdout, fixed=SQL + b"x")
    assert got.startswith(reason), got


def test_the_lint_check(ctx, tmp_path):
    def lint(tool, violations, name=INPUT_FILE, exit_code=1, sub="a"):
        if tool == "sqlfluff":
            out = [{"filepath": name, "violations": violations}]
        else:
            out = {
                name: [
                    {
                        "range": {"start": {"line": 1, "character": 1}},
                        "message": v.get("description", ""),
                        "code": v["code"],
                    }
                    for v in violations
                ]
            }
        return check_run(
            registry.get(tool),
            ctx,
            bench("lint", "d/s"),
            SQL,
            fake_run(
                tmp_path / sub, stdout=json.dumps(out).encode(), exit_code=exit_code
            ),
        )

    good = [{"code": "LT01"}, {"code": "CP01"}, {"code": "LT01"}]
    assert lint("sqlfluff", good) == (
        None,
        {"violations": 3, "codes": ["CP01", "LT01"]},
    )
    assert lint("sqruff", good, sub="b")[0] is None
    assert (
        lint("sqlfluff", good, exit_code=2, sub="c")[0] == "exit code 2, expected 0, 1"
    )
    assert lint("sqlfluff", good, name="other.sql", sub="d")[0] == (
        "no lint result for the input file"
    )
    # sqruff gives "{}" for a file over its size limit, with no message.
    run = fake_run(tmp_path / "e", stdout=b"{}")
    assert check_run(registry.get("sqruff"), ctx, bench("lint", "d/s"), SQL, run)[
        0
    ] == ("no lint result for the input file")
    assert lint("sqlfluff", good[:1], sub="f")[0] == (
        "the rule codes are not those of the sqlfluff reference: missing "
        "['CP01'], extra []"
    )
    prs = [*good, {"code": "PRS", "description": "Found unparsable section: 'x'"}]
    assert lint("sqlfluff", prs, sub="g")[0] == (
        "the lint output has a parse error: PRS, unparsable section"
    )
    # sqruff gives no code for a parse error; the adapter gives it PRS.
    none = [*good, {"code": None, "description": "Unparsable section"}]
    assert lint("sqruff", none, sub="h")[0] == (
        "the lint output has a parse error: PRS, unparsable section"
    )


def test_the_fix_check(ctx, tmp_path):
    adapter = registry.get("sqlfluff")

    def fix(sub, fixed, exit_code=0):
        run = fake_run(tmp_path / sub, exit_code=exit_code, fixed=fixed)
        return check_run(adapter, ctx, bench("fix", "d/s"), SQL, run)

    assert fix("a", SQL.upper()) == (
        None,
        {"changed": True, "fixed_sha256": _sha(SQL.upper())},
    )
    assert fix("b", SQL)[0] == (
        "fix did not change the file; in the sqlfluff reference it does"
    )
    assert fix("c", None)[0].startswith("no fixed file")
    assert fix("d", SQL.upper(), exit_code=-9)[0] == "exit code -9, expected 0, 1"
    ctx.note(("sqlfluff", "lint", "ansi", "d/s"), "x", None)
    assert fix("e", SQL.upper())[0] == "the lint check fails: x"


# The sqlfluff reference in the definitions.


def test_the_recorded_reference_is_complete():
    recorded = definitions.load()
    assert definitions.check_reference(recorded) == []
    ref = recorded["reference"]
    from sqll_harness.paths import TOOL_SPECS_DIR
    from sqll_harness.tools import lock_version

    assert ref["sqlfluff_version"] == lock_version(
        TOOL_SPECS_DIR / "sqlfluff", "sqlfluff"
    )
    assert len(ref["inputs"]) == len(recorded["inputs"]) - 1


def test_check_reference_finds_a_missing_or_stale_entry():
    recorded = definitions.load()
    changed = json.loads(json.dumps(recorded))
    del changed["reference"]["inputs"]["ansi/small"]
    changed["reference"]["inputs"]["ansi/medium"]["sha256"] = "0" * 64
    changed["reference"]["inputs"]["ansi/large"]["lint_codes"] = ["LT01", "AL01"]
    changed["reference"]["inputs"]["x/small"] = {}
    assert definitions.check_reference(changed) == [
        "reference ansi/small: missing",
        "reference ansi/medium: made for another input (sha256)",
        "reference ansi/large: bad value "
        + str(changed["reference"]["inputs"]["ansi/large"]),
        "reference x/small: not an input",
    ]


def test_the_reference_is_made_from_valid_runs_only(tmp_path):
    sql = {"d/a": b"select a from b;\n", "d/b": b"select 1;\n"}
    defs, folder = custom(tmp_path, sql, {"d/a": (["CP01", "LT01"], True)})
    defs["inputs"]["start"] = {"sha256": _sha(b"x")}
    defs_file = tmp_path / "defs.json"
    defs_file.write_text(json.dumps(defs))

    class Reference(DoubleBench):
        name = "sqlfluff"

    tool = Reference(defs_file)
    new, errors = reference.make(tool, defs, folder, tmp_path / "w", jobs=2)
    # The double gives no codes and no fix for d/b (it is not in its file).
    assert errors == []
    assert new == {
        "sqlfluff_version": "1.0",
        "inputs": {
            "d/a": {
                "sha256": _sha(sql["d/a"]),
                "lint_codes": ["CP01", "LT01"],
                "fix_changes": True,
            },
            "d/b": {"sha256": _sha(sql["d/b"]), "lint_codes": [], "fix_changes": False},
        },
    }
    assert reference.differences(defs["reference"], new) == [
        "sqlfluff_version: recorded '1', new '1.0'",
        f"d/b: recorded None, new {new['inputs']['d/b']}",
    ]
    # An invalid run gives no reference for its input.
    tool.base_settings = {"core": {}}
    new, errors = reference.make(tool, defs, folder, tmp_path / "w2")
    assert new["inputs"] == {}
    assert errors == [
        "d/a: exit code 2, expected 0, 1",
        "d/b: exit code 2, expected 0, 1",
    ]
    with pytest.raises(ValueError, match="reference tool"):
        reference.make(DoubleBench(), defs, folder, tmp_path / "w3")


def test_registry_get_refuses_an_entry_with_another_tool_name(monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY", {"other": DoubleBench})
    with pytest.raises(ValueError, match="gives tool 'double'"):
        registry.get("other")
    with pytest.raises(KeyError):
        registry.get("sqruff")


def test_a_job_that_does_not_run_has_no_series(tmp_path):
    defs, folder = custom(tmp_path, {"start": b"SELECT 1;\n"})
    ctx = Context(defs, folder, tmp_path / "work")
    bj = DoubleBench(no={"soql"}).job(bench("start", "start", "soql"), ctx)
    with pytest.raises(ValueError, match="unsupported: dialect soql"):
        bj.series(SMOKE)
    with pytest.raises(ValueError, match="unknown command"):
        DoubleBench().job(bench("format", "start"), ctx)


def _bench_reference(*args) -> int:
    return cli.main(["bench", "reference", *map(str, args)])


def test_the_reference_command(tmp_path, monkeypatch, capsys):
    recorded = definitions.load()
    path = tmp_path / "definitions.json"
    path.write_text(definitions.render(recorded), encoding="utf8")
    made = {"ref": json.loads(json.dumps(recorded["reference"])), "failed": []}

    def fake_make(adapter, defs, inputs_dir, work_root, jobs=1):
        assert adapter.name == "sqlfluff"
        assert (inputs_dir / "ansi" / "large.sql").is_file()
        return made["ref"], made["failed"]

    monkeypatch.setattr(reference, "make", fake_make)
    assert _bench_reference("--definitions", path) == 0
    assert "The reference is that of" in capsys.readouterr().out
    made["ref"]["inputs"]["ansi/small"]["fix_changes"] = False
    assert _bench_reference("--definitions", path) == 1
    assert "ansi/small: recorded" in capsys.readouterr().out
    assert _bench_reference("--definitions", path, "--write") == 0
    assert definitions.load(path)["reference"] == made["ref"]
    made["failed"] = ["tsql/large: exit code 2, expected 0, 1"]
    assert _bench_reference("--definitions", path, "--write") == 1
    assert "invalid: tsql/large" in capsys.readouterr().out
    # Definitions that are not those of the build: exit code 2.
    changed = definitions.load(path)
    changed["inputs"]["ansi/small"]["sha256"] = "0" * 64
    path.write_text(definitions.render(changed), encoding="utf8")
    assert _bench_reference("--definitions", path) == 2
