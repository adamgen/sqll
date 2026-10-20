"""The benchmark adapters with the real tools (harness/bench.md, "Validity").

These tests need sqlfluff, sqlfluff-rs, and sqruff (scripts/setup). With
SQLL_REQUIRE_TOOLS=1 (CI) a missing tool is a failure.
"""

import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from conftest import needs_all_tools

from sqll_harness.bench import definitions, registry
from sqll_harness.bench.adapter import INPUT_FILE, Context
from sqll_harness.bench.timer import INVALID, PROFILES, UNSUPPORTED, VALID, Policy
from sqll_harness.tools import RUST_PARSER_LOG

pytestmark = needs_all_tools

TOOLS = ("sqlfluff", "sqlfluff-rs", "sqruff")
DIALECTS = ("ansi", "bigquery", "tsql")
SMOKE = PROFILES["smoke"]
DEFS = definitions.load()
BENCHMARKS = {b["id"]: b for b in DEFS["benchmarks"]}
UNPARSABLE = b"select a from b\nwhere ))) garbage (((\n;\nSELECT  x FROM y;\n"
# Settings with the size limits of the tools (20000 bytes) on.
LIMIT_ON = {"core": {"templater": "raw", "rules": "all"}}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def custom(tmp_path: Path, sql: dict[str, bytes]) -> tuple[dict, Path]:
    folder = tmp_path / "inputs"
    defs = {"inputs": {}}
    for name, data in sql.items():
        (folder / f"{name}.sql").parent.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.sql").write_bytes(data)
        defs["inputs"][name] = {"sha256": _sha(data)}
    return defs, folder


def bench(command: str, name: str, dialect: str = "ansi") -> dict:
    return {
        "id": f"{command}/{name}",
        "command": command,
        "dialect": dialect,
        "size": None,
        "input": name,
    }


@pytest.mark.parametrize("tool", TOOLS)
def test_each_command_is_valid_on_small_inputs(tool, bench_inputs_dir, tmp_path):
    adapter = registry.get(tool)
    ctx = Context(DEFS, bench_inputs_dir, tmp_path)

    def run(dialect):
        ids = [f"start/{dialect}"]
        ids += [f"{c}/{dialect}/small" for c in ("parse", "lint", "fix")]
        out = {}
        for i in ids:
            bj = adapter.job(BENCHMARKS[i], ctx)
            out[i] = (bj.measure(SMOKE), bj.work)
        return out

    with ThreadPoolExecutor(len(DIALECTS)) as pool:
        results = {k: v for part in pool.map(run, DIALECTS) for k, v in part.items()}
    assert len(results) == 4 * len(DIALECTS)
    bad = {
        i: (m.status, m.reason) for i, (m, _) in results.items() if m.status != VALID
    }
    assert bad == {}
    ref = DEFS["reference"]["inputs"]
    for dialect in DIALECTS:
        m, work = results[f"lint/{dialect}/small"]
        assert work["codes"] == ref[f"{dialect}/small"]["lint_codes"]
        assert work["violations"] >= len(work["codes"]) > 0
        assert m.samples[0].exit_code == 1
        _, work = results[f"fix/{dialect}/small"]
        assert work["changed"] is ref[f"{dialect}/small"]["fix_changes"]


def test_sqruff_does_not_support_soql(tmp_path, bench_inputs_dir):
    ctx = Context(DEFS, bench_inputs_dir, tmp_path)
    adapter = registry.get("sqruff")
    for i in ("start/soql", "parse/soql/small", "lint/soql/medium", "fix/soql/large"):
        m = adapter.job(BENCHMARKS[i], ctx).measure(SMOKE)
        assert (m.status, m.reason, m.samples) == (
            UNSUPPORTED,
            "unsupported: dialect soql",
            [],
        )


def test_an_input_over_the_size_limit_is_a_skip(tmp_path, bench_inputs_dir):
    """With the default size limit (20000 bytes) on, each skip is invalid,
    also when the exit code is 0. With the benchmark settings (limit 0), the
    same runs are valid."""
    # sqruff fix of ansi large does not stop (bench.md); of snowflake it does.
    data = (bench_inputs_dir / "snowflake" / "large.sql").read_bytes()
    data += (bench_inputs_dir / "snowflake" / "medium.sql").read_bytes()
    assert len(data) > 20000
    defs, folder = custom(tmp_path, {"big": data})
    ctx = Context(defs, folder, tmp_path / "on")
    skips = {}
    for tool in TOOLS:
        adapter = registry.get(tool)
        adapter.base_settings = LIMIT_ON
        # "sqruff parse" has no size limit.
        commands = ("lint", "fix") if tool == "sqruff" else ("parse", "lint", "fix")
        for command in commands:
            b = bench(command, "big", "snowflake")
            m = adapter.job(b, ctx).measure(SMOKE)
            skips[(tool, command)] = (m.status, m.reason, m.samples[0].exit_code)
    size = "warmup run: the tool skipped the file (size limit): "
    for (tool, command), (status, reason, code) in skips.items():
        assert status == INVALID, (tool, command, reason)
        if (tool, command) == ("sqruff", "lint"):
            # sqruff gives "{}" and no message.
            assert reason == "warmup run: no lint result for the input file"
        else:
            assert reason.startswith(size), (tool, command, reason)
        assert code == 0, (tool, command, reason)
    # Control: the benchmark settings (limit 0). Only the size limit is
    # different; the reference is not used here.
    ctx = Context(defs, folder, tmp_path / "off", record_reference=True)
    for tool, command in [("sqlfluff", "parse"), ("sqruff", "lint"), ("sqruff", "fix")]:
        bj = registry.get(tool).job(bench(command, "big", "snowflake"), ctx)
        m = bj.measure(SMOKE)
        assert m.status == VALID, (tool, command, m.reason)
    assert bj.work["changed"] is True


def test_an_unparsable_input_is_invalid(tmp_path):
    defs, folder = custom(tmp_path, {"bad": UNPARSABLE})
    ctx = Context(defs, folder, tmp_path / "work")
    for tool in TOOLS:
        adapter = registry.get(tool)
        out = {}
        for command in ("parse", "lint", "fix"):
            m = adapter.job(bench(command, "bad"), ctx).measure(SMOKE)
            out[command] = (m.status, m.reason)
        assert {s for s, _ in out.values()} == {INVALID}, (tool, out)
        # Each tool gives exit code 1 for a parse error.
        assert out["parse"][1].startswith("warmup run: exit code 1, expected 0")
        assert out["lint"][1] == (
            "warmup run: the lint output has a parse error: PRS, unparsable section"
        ), tool
        assert (
            "parse errors" in out["fix"][1] or "the lint check fails" in out["fix"][1]
        ), (tool, out["fix"])


def test_the_dialect_setting_reaches_each_tool(tmp_path, bench_inputs_dir):
    """tsql SQL with the ansi dialect: each tool gives a parse error."""
    ctx = Context(DEFS, bench_inputs_dir, tmp_path)
    for tool in TOOLS:
        b = bench("parse", "tsql/small", dialect="ansi")
        m = registry.get(tool).job(b, ctx).measure(SMOKE)
        assert m.status == INVALID, tool
        b = bench("parse", "tsql/small", dialect="tsql")
        m = registry.get(tool).job(b, ctx).measure(SMOKE)
        assert m.status == VALID, (tool, m.reason)


def test_sqlfluff_rs_uses_the_rust_parser(tmp_path, bench_inputs_dir):
    ctx = Context(DEFS, bench_inputs_dir, tmp_path)
    logs = {}
    for tool in ("sqlfluff-rs", "sqlfluff"):
        bj = registry.get(tool).job(BENCHMARKS["parse/ansi/small"], ctx)
        folder = tmp_path / "manual" / tool
        folder.mkdir(parents=True)
        bj.job.prepare(folder)
        argv = [*bj.job.argv[:2], "-vvv", *bj.job.argv[2:]]
        proc = subprocess.run(
            argv, cwd=folder, env=bj.job.env, capture_output=True, text=True
        )
        assert proc.returncode == 0, proc.stderr[-500:]
        logs[tool] = RUST_PARSER_LOG in proc.stderr
    assert logs == {"sqlfluff-rs": True, "sqlfluff": False}


def test_each_fix_run_gets_an_unchanged_copy(tmp_path, bench_inputs_dir):
    ctx = Context(DEFS, bench_inputs_dir, tmp_path)
    source = bench_inputs_dir / "ansi" / "small.sql"
    before = source.read_bytes()
    bj = registry.get("sqruff").job(BENCHMARKS["fix/ansi/small"], ctx)
    m = bj.measure(Policy(3, 3, 0.0, 120.0), keep_timed=True)
    assert m.status == VALID, m.reason
    assert bj.work["changed"] is True
    for run in ("warmup", "1", "2", "3"):
        fixed = (bj.runs_folder / run / INPUT_FILE).read_bytes()
        assert _sha(fixed) == bj.work["fixed_sha256"]
    assert source.read_bytes() == before


def test_only_soql_is_an_unsupported_dialect():
    dialects = {b["dialect"] for b in DEFS["benchmarks"]}
    assert len(dialects) == 28
    for tool in TOOLS:
        adapter = registry.get(tool)
        no = {d for d in dialects if adapter.unsupported(adapter.config(d))}
        assert no == (set() if tool != "sqruff" else {"soql"}), tool
