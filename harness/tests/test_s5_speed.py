"""The speed script of S5 (rule parity: sqll passes 100% of the rule fixtures,
lint and fix; cases that need the Jinja templater move to the Jinja templater
stone): scripts/s5/speed.

Task T3 (goal of the task: each pull request of this track that changes the
lint and fix path gives the HEAD / BASE, HEAD / sqlfluff, and HEAD / sqruff
ratios of the lint and fix benchmarks for the rules that sqll has) of S5.
Design record: docs/decisions/s5-rules.md, section 5.

results/S5/speed/T3.json is the record of one real run (CP01, CP03, CP04).
The drift test makes its summary again from the committed record. The other
tests use changed copies of the record (the ratio math, the slower lists,
and each refusal), the rule selection, the machine lock, and a session with
fake tools (the reference with the rules, and each failure of a session).
"""

import copy
import fcntl
import importlib.machinery
import importlib.util
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

from sqll_harness.adapters import sqll as sqll_adapter
from sqll_harness.bench import compare, definitions
from sqll_harness.bench.adapter import (
    PARSE,
    BenchAdapter,
    Context,
    settings,
)
from sqll_harness.bench.timer import INVALID, PROFILES, VALID
from sqll_harness.bench.tools import SqlfluffBench, parse_record
from sqll_harness.paths import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "s5" / "speed"
_loader = importlib.machinery.SourceFileLoader("s5_speed", str(SCRIPT))
_spec = importlib.util.spec_from_loader("s5_speed", _loader)
sp = importlib.util.module_from_spec(_spec)
_loader.exec_module(sp)

T3_FILE = sp.SPEED_DIR / "T3.json"
T3 = json.loads(T3_FILE.read_text("utf8"))
RULES = ["CP01", "CP03", "CP04"]
DIALECTS = sorted({b["dialect"] for b in definitions.load()["benchmarks"]})


def record() -> dict:
    return copy.deepcopy(T3)


def write_label(tmp_path: Path, monkeypatch, data: dict, label: str = "T3") -> Path:
    monkeypatch.setattr(sp, "SPEED_DIR", tmp_path / "speed")
    path = sp.label_file(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sp.dump(data), "utf8")
    return path


def result(data: dict, bid: str, tool: str) -> dict:
    return next(
        r for r in data["report"]["results"] if r["id"] == bid and r["tool"] == tool
    )


def summary_of(data: dict) -> dict:
    new = {k: v for k, v in data.items() if k != "summary"}
    return sp.summarize(new)


def row(summary: dict, bid: str) -> dict:
    return next(r for r in summary["benchmarks"] if r["id"] == bid)


# The record of the real run, and the drift test.


def test_the_committed_summary_is_the_summary_of_the_committed_record(capsys):
    code = sp.main(["report", "--label", "T3", "--check"])
    assert "results/S5/speed/T3.json is up to date" in capsys.readouterr().out
    assert code == T3["summary"]["exit_code"]


def test_the_check_fails_on_a_changed_summary(tmp_path, monkeypatch):
    data = record()
    data["summary"]["ok"] = not data["summary"]["ok"]
    write_label(tmp_path, monkeypatch, data)
    assert sp.main(["report", "--label", "T3", "--check"]) == 1


def test_report_writes_the_summary_again(tmp_path, monkeypatch):
    data = record()
    del data["summary"]
    path = write_label(tmp_path, monkeypatch, data)
    assert sp.main(["report", "--label", "T3"]) == T3["summary"]["exit_code"]
    assert path.read_text("utf8") == T3_FILE.read_text("utf8")


def test_the_real_run_has_the_rules_cp01_cp03_cp04_for_each_tool():
    assert T3["rules"] == RULES
    s = T3["summary"]
    assert s["rules"] == RULES
    assert s["tool_rules"] == {t: RULES for t in sp.TOOLS}
    for tool in sp.TOOLS:
        assert T3["tool_rules"][tool]["ran"] == RULES
        assert set(RULES) <= set(T3["tool_rules"][tool]["has"])
        core = T3["report"]["tools"][tool]["settings"]["core"]
        assert core["rules"] == "CP01,CP03,CP04"
        assert core["templater"] == "raw"
    assert T3["tool_rules"][sp.BASE]["has"] == RULES


def test_the_real_run_has_each_lint_and_fix_input_with_3_ratios():
    rep = T3["report"]
    assert rep["profile"] == "full"
    assert rep["scope"]["commands"] == ["lint", "fix"]
    assert rep["scope"]["dialects"] == DIALECTS
    assert rep["scope"]["sizes"] == ["small", "medium", "large"]
    table = T3["summary"]["benchmarks"]
    assert len(table) == 2 * 3 * len(DIALECTS) == 168
    for r in table:
        assert set(r["ratio"]) == {"head_base", "head_sqlfluff", "head_sqruff"}
        assert r["status"][sp.HEAD] == VALID, r["id"]
        assert r["ratio"]["head_sqlfluff"] is not None, r["id"]
    assert sorted(T3["reference"]["inputs"]) == sorted(rep["inputs"])
    assert len(rep["inputs"]) == 3 * len(DIALECTS)


def test_the_real_run_used_the_s2_method_and_the_machine_lock():
    method = T3["method"]
    assert method["image"].startswith("sqll-ci:")
    assert method["machine_lock"].startswith("/tmp/sqll-machine.lock: ")
    session = next(s for s in T3["steps"] if s["step"] == "session")
    argv = session["argv"]
    assert argv[:5] == ["docker", "run", "--rm", "--network", "none"]
    assert "$REPO:$REPO:ro" in argv
    assert f"/tmp/sqll-machine.lock:{sp.C_LOCK}:ro" in argv
    assert argv[-5:] == ["run-inside", "--scratch", sp.C_SCRATCH, "--lock", sp.C_LOCK]
    assert session["exit_code"] == 0


def test_each_median_is_the_median_of_the_timed_runs():
    for r in T3["report"]["results"]:
        if r["status"] != VALID:
            continue
        assert len(r["samples"]["wall_s"]) >= PROFILES["full"].min_runs
        want = statistics.median(r["samples"]["wall_s"])
        assert r["stats"]["wall_s"]["median"] == pytest.approx(want, abs=1e-6)


# The ratio math.


def test_the_ratio_is_head_divided_by_the_other_tool():
    assert sp.ratio(0.5, 2.0) == 0.25
    assert sp.ratio(1.0, 3.0) == 0.3333
    assert sp.ratio(2.0, 3.0) == 0.6667
    assert sp.ratio(None, 1.0) is None
    assert sp.ratio(1.0, None) is None
    assert sp.ratio(1.0, 0.0) is None


def test_each_ratio_of_the_record_is_that_of_the_medians():
    by_key = {(r["id"], r["tool"]): r for r in T3["report"]["results"]}

    def median(bid, tool):
        r = by_key[(bid, tool)]
        return r["stats"]["wall_s"]["median"] if r["status"] == VALID else None

    for r in T3["summary"]["benchmarks"]:
        head = median(r["id"], sp.HEAD)
        assert r["wall_s"][sp.HEAD] == head
        for key, tool in sp.PAIRS.items():
            other = median(r["id"], tool)
            want = None if head is None or other is None else round(head / other, 4)
            assert r["ratio"][key] == want, (r["id"], key)


def test_the_group_ratio_is_the_ratio_of_the_sums_of_the_pairs():
    table = T3["summary"]["benchmarks"]
    for g in T3["summary"]["groups"]:
        members = [
            r
            for r in table
            if g["group"] == "total" or sp.group_of(r["id"]) == g["group"]
        ]
        assert g["benchmarks"] == len(members)
        for key, tool in sp.PAIRS.items():
            pairs = [
                r
                for r in members
                if r["wall_s"][sp.HEAD] is not None and r["wall_s"][tool] is not None
            ]
            head = sum(r["wall_s"][sp.HEAD] for r in pairs)
            other = sum(r["wall_s"][tool] for r in pairs)
            assert g[key]["pairs"] == len(pairs)
            assert g[key]["ratio"]["total"] == pytest.approx(head / other, abs=1e-4)
            ratios = sorted(r["ratio"][key] for r in pairs)
            assert g[key]["ratio"]["min"] == ratios[0]
            assert g[key]["ratio"]["max"] == ratios[-1]
    names = [g["group"] for g in T3["summary"]["groups"]]
    assert names == [
        "lint/small",
        "lint/medium",
        "lint/large",
        "fix/small",
        "fix/medium",
        "fix/large",
        "total",
    ]


def test_the_rows_use_the_compare_entry_of_bench_compare():
    by_key = {(r["id"], r["tool"]): r for r in T3["report"]["results"]}
    for r in T3["summary"]["benchmarks"]:
        entry = compare.benchmark_entry(
            by_key[(r["id"], sp.BASE)], by_key[(r["id"], sp.HEAD)]
        )
        assert r["head_base"] == {k: entry[k] for k in ("change", "wall", "cpu")}


def test_a_ratio_on_a_small_report():
    def res(bid, tool, wall, status=VALID):
        stats = {"wall_s": {"median": wall, "mad": 0.0}}
        stats["cpu_s"] = {"median": wall, "mad": 0.0}
        return {
            "id": bid,
            "tool": tool,
            "status": status,
            "reason": None if status == VALID else "x",
            "stats": stats if status == VALID else None,
        }

    rep = {
        "results": [
            res("lint/ansi/small", sp.HEAD, 0.010),
            res("lint/ansi/small", sp.BASE, 0.010),
            res("lint/ansi/small", "sqlfluff", 0.500),
            res("lint/ansi/small", "sqruff", 0.020),
            res("fix/ansi/small", sp.HEAD, 0.030),
            res("fix/ansi/small", sp.BASE, 0.010),
            res("fix/ansi/small", "sqlfluff", 0.030),
            res("fix/ansi/small", "sqruff", 0.020, INVALID),
        ]
    }
    table = sp.rows(rep)
    assert [r["id"] for r in table] == ["lint/ansi/small", "fix/ansi/small"]
    assert table[0]["ratio"] == {
        "head_base": 1.0,
        "head_sqlfluff": 0.02,
        "head_sqruff": 0.5,
    }
    assert table[1]["ratio"] == {
        "head_base": 3.0,
        "head_sqlfluff": 1.0,
        "head_sqruff": None,
    }
    grouped = sp.groups(table)
    total = grouped[-1]
    assert total["head_base"]["ratio"]["total"] == 2.0  # 0.040 / 0.020
    assert total["head_sqlfluff"]["ratio"]["total"] == 0.0755  # 0.040 / 0.530
    assert total["head_sqruff"]["pairs"] == 1
    slow = sp.slower(table, total)
    assert slow["head_base"] == ["fix/ansi/small"]
    assert slow["sqlfluff"] == ["fix/ansi/small"]  # a tie is not faster
    assert slow["sqruff"] == [] and slow["sqruff_total"] is False
    gaps = sp.no_pair(rep, table)
    assert gaps["head_sqruff"] == [
        {"id": "fix/ansi/small", "status": INVALID, "reason": "x"}
    ]
    assert gaps["head_base"] == [] and gaps["head_sqlfluff"] == []


# The slower benchmarks (exit code 1).


def test_a_slower_head_is_in_the_list(tmp_path, monkeypatch):
    data = record()
    head = result(data, "lint/ansi/large", sp.HEAD)
    for key in ("wall_s", "cpu_s"):
        head["stats"][key]["median"] *= 2
    write_label(tmp_path, monkeypatch, data)
    assert sp.main(["report", "--label", "T3"]) == 1
    s = json.loads(sp.label_file("T3").read_text("utf8"))["summary"]
    assert "lint/ansi/large" in s["slower"]["head_base"]
    assert row(s, "lint/ansi/large")["head_base"]["change"] == compare.SLOWER
    assert not s["ok"] and s["exit_code"] == 1


def test_a_head_that_is_not_valid_is_a_failure(tmp_path, monkeypatch):
    data = record()
    head = result(data, "fix/tsql/medium", sp.HEAD)
    head.update(status=INVALID, reason="warmup run: exit code 1", stats=None)
    s = summary_of(data)
    assert s["slower"]["failure"] == ["fix/tsql/medium"]
    assert s["slower"]["head_not_valid"] == ["fix/tsql/medium"]
    assert row(s, "fix/tsql/medium")["ratio"]["head_sqlfluff"] is None
    assert s["exit_code"] == 1


def test_a_tie_with_sqlfluff_is_slower(tmp_path, monkeypatch):
    data = record()
    head = result(data, "lint/ansi/small", sp.HEAD)
    other = result(data, "lint/ansi/small", "sqlfluff")
    other["stats"]["wall_s"]["median"] = head["stats"]["wall_s"]["median"]
    s = summary_of(data)
    assert "lint/ansi/small" in s["slower"]["sqlfluff"]
    assert row(s, "lint/ansi/small")["ratio"]["head_sqlfluff"] == 1.0
    assert s["exit_code"] == 1


def test_head_slower_than_sqruff_is_in_the_list(tmp_path, monkeypatch):
    data = record()
    bid = next(
        r["id"]
        for r in T3["summary"]["benchmarks"]
        if r["ratio"]["head_sqruff"] is not None
    )
    head = result(data, bid, sp.HEAD)
    other = result(data, bid, "sqruff")
    other["stats"]["wall_s"]["median"] = head["stats"]["wall_s"]["median"] / 2
    s = summary_of(data)
    assert bid in s["slower"]["sqruff"]
    assert row(s, bid)["ratio"]["head_sqruff"] == 2.0
    assert s["exit_code"] == 1


def test_no_sqruff_pair_fails_the_total(tmp_path, monkeypatch):
    data = record()
    for r in data["report"]["results"]:
        if r["tool"] == "sqruff":
            r.update(status=INVALID, reason="x", stats=None)
    s = summary_of(data)
    assert s["groups"][-1]["head_sqruff"]["pairs"] == 0
    assert s["slower"]["sqruff_total"] is True
    assert len(s["no_pair"]["head_sqruff"]) == 168
    assert s["exit_code"] == 1


def test_a_base_that_is_not_valid_has_no_pair_and_is_not_slower():
    data = record()
    base = result(data, "lint/postgres/large", sp.BASE)
    base.update(status=INVALID, reason="warmup run: exit code 1", stats=None)
    s = summary_of(data)
    r = row(s, "lint/postgres/large")
    assert r["ratio"]["head_base"] is None
    assert r["head_base"]["change"] == compare.STATUS
    assert {
        "id": "lint/postgres/large",
        "status": INVALID,
        "reason": "warmup run: exit code 1",
    } in s["no_pair"]["head_base"]
    assert "lint/postgres/large" not in s["slower"]["head_base"]
    assert s["exit_code"] == T3["summary"]["exit_code"]


# The refusals of a record (exit code 2).


def _refused(tmp_path, monkeypatch, capsys, data) -> str:
    write_label(tmp_path, monkeypatch, data)
    assert sp.main(["report", "--label", "T3", "--check"]) == 2
    return capsys.readouterr().err


def test_a_missing_result_is_refused(tmp_path, monkeypatch, capsys):
    data = record()
    data["report"]["results"] = [
        r
        for r in data["report"]["results"]
        if not (r["id"] == "fix/ansi/large" and r["tool"] == "sqruff")
    ]
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "sqruff: no result for 1: fix/ansi/large" in err


def test_a_missing_input_is_refused(tmp_path, monkeypatch, capsys):
    data = record()
    del data["report"]["inputs"]["ansi/large"]
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "inputs: missing ansi/large" in err


def test_an_input_that_is_not_that_of_the_definitions_is_refused(
    tmp_path, monkeypatch, capsys
):
    data = record()
    data["report"]["inputs"]["ansi/large"]["sha256"] = "0" * 64
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "input ansi/large: not that of the definitions" in err


def test_a_smaller_scope_is_refused(tmp_path, monkeypatch, capsys):
    data = record()
    data["report"]["scope"]["dialects"] = ["ansi"]
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "the scope is " in err


def test_a_tool_with_other_rules_is_refused(tmp_path, monkeypatch, capsys):
    data = record()
    data["report"]["tools"]["sqruff"]["settings"]["core"]["rules"] = "all"
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "sqruff: the settings do not have only the rules" in err


def test_other_s2_settings_are_refused(tmp_path, monkeypatch, capsys):
    data = record()
    data["report"]["tools"]["sqlfluff"]["settings"]["core"]["templater"] = "jinja"
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "sqlfluff: the settings are not the S2 settings with the rules" in err


def test_a_tool_that_does_not_have_a_rule_is_refused(tmp_path, monkeypatch, capsys):
    data = record()
    data["tool_rules"]["sqruff"]["has"].remove("CP04")
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "sqruff does not have the rules CP04" in err


def test_rules_that_are_not_those_of_base_are_refused(tmp_path, monkeypatch, capsys):
    data = record()
    data["tool_rules"][sp.BASE]["has"] = ["CP01", "CP03"]
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "the rules are not those that sqll-base has" in err


def test_rules_that_are_not_sorted_are_refused(tmp_path, monkeypatch, capsys):
    data = record()
    data["rules"] = ["CP03", "CP01", "CP04"]
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "the rules are not a sorted list" in err


def test_a_reference_with_another_rule_or_input_is_refused(
    tmp_path, monkeypatch, capsys
):
    data = record()
    data["reference"]["inputs"]["ansi/small"]["lint_codes"] = ["LT01"]
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "reference ansi/small: codes ['LT01'] are not of the rules" in err
    data = record()
    del data["reference"]["inputs"]["ansi/small"]
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "the reference does not have exactly the inputs of the report" in err


def test_a_version_that_is_not_that_of_the_build_is_refused(
    tmp_path, monkeypatch, capsys
):
    data = record()
    data["head"]["version"] = "0.0.0"
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "sqll: the version is not that of the head build" in err


def test_a_record_that_is_not_complete_is_refused(tmp_path, monkeypatch, capsys):
    data = record()
    del data["tool_rules"]
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "the record is not complete" in err


def test_a_record_of_another_label_and_a_bad_label_are_refused(
    tmp_path, monkeypatch, capsys
):
    data = record()
    data["label"] = "T4"
    err = _refused(tmp_path, monkeypatch, capsys, data)
    assert "is not the S5 speed record of T3" in err
    assert sp.main(["report", "--label", "T9"]) == 2
    assert "does not exist" in capsys.readouterr().err
    assert sp.main(["report", "--label", "../x"]) == 2
    assert "not a label" in capsys.readouterr().err


# The rule selection.

SQLFLUFF_RULES = """==== sqlfluff - rules ====
AL01: [aliasing.table] Implicit/explicit aliasing of table.
      groups: all, aliasing aliases: L011
CP01: [capitalisation.keywords] Inconsistent capitalisation of keywords.
      groups: all, core, capitalisation aliases: L010
CP04: [capitalisation.literals] Inconsistent capitalisation of boolean/null
      literal.
"""


def test_the_rule_codes_of_sqlfluff_rules():
    assert sp.sqlfluff_rule_codes(SQLFLUFF_RULES) == {"AL01", "CP01", "CP04"}


def test_the_rules_are_those_of_base_sorted():
    assert sp.select_rules(["CP04", "CP01", "CP03", "CP01"]) == RULES
    with pytest.raises(sp.Refused, match="sqll-base has no rule"):
        sp.select_rules([])
    with pytest.raises(sp.Refused, match="not a rule code: capitalisation"):
        sp.select_rules(["CP01", "capitalisation"])


def test_each_tool_must_have_each_rule():
    has = {t: RULES for t in sp.TOOLS}
    sp.check_rules(RULES, has)
    with pytest.raises(sp.Refused, match="sqruff does not have the rules CP03"):
        sp.check_rules(RULES, {**has, "sqruff": ["CP01", "CP04"]})
    with pytest.raises(sp.Refused, match="sqll does not have the rules CP04"):
        sp.check_rules(RULES, {**has, "sqll": ["CP01", "CP03"]})
    with pytest.raises(sp.Refused, match="sqlfluff: no rule list"):
        sp.check_rules(RULES, {t: v for t, v in has.items() if t != "sqlfluff"})


def test_the_settings_have_only_the_rules():
    adapter = sp.with_rules(SqlfluffBench(Path("/x")), RULES)
    config = adapter.config("ansi")
    assert config["core"]["rules"] == "CP01,CP03,CP04"
    assert sp.settings_rules(config) == RULES
    want = settings("ansi")
    want["core"]["rules"] = "CP01,CP03,CP04"
    assert config == want
    assert sp.settings_rules({"core": {}}) == []


def test_sqll_parse_runs_with_the_s2_rules_and_lint_with_the_rules(
    bench_inputs_dir, tmp_path
):
    adapter = sp.with_rules(sp.SqllRulesBench(tmp_path / "sqll"), RULES)
    ctx = Context(definitions.load(), bench_inputs_dir, tmp_path / "work")
    bench = {
        "id": "parse/ansi/small",
        "command": PARSE,
        "dialect": "ansi",
        "size": "small",
        "input": "ansi/small",
    }
    bj = adapter.job(bench, ctx)
    config = Path(bj.job.argv[bj.job.argv.index("--config") + 1]).read_text("utf8")
    assert 'rules = "all"' in config
    assert adapter.config(None)["core"]["rules"] == "CP01,CP03,CP04"
    for cls in (sp.SqllRulesBench, sp.SqllBaseRulesBench):
        assert issubclass(cls, sp.ParseWithAllRules)
    assert sp.adapter_of(sp.HEAD).name == sp.HEAD
    assert sp.adapter_of(sp.BASE).name == sp.BASE
    assert isinstance(sp.adapter_of(sp.BASE), sp.SqllBaseRulesBench)


# A session with fake tools.

FAKE_TOOL = """
import json, sys
command, config, sql, codes = sys.argv[1:5]
codes = [c for c in codes.split(",") if c]
with open(sql, encoding="utf8") as f:
    text = f.read()
if command == "parse":
    lines = text.splitlines(keepends=True)
    tree = {"file": [{"line": line} for line in lines]}
    print(json.dumps([{"filepath": sql, "segments": tree}]))
elif command == "lint":
    found = [{"code": c, "description": "x"} for c in codes]
    print(json.dumps([{"filepath": sql, "violations": found}]))
    sys.exit(1 if codes else 0)
"""


class FakeBench(BenchAdapter):
    """A tool that parses each line, lints with the codes, and fixes
    nothing."""

    def __init__(self, name: str, script: Path, has: list[str], codes: str):
        super().__init__()
        self.name, self.script, self.has, self.codes = name, script, has, codes

    def version(self) -> str:
        return "1.0"

    def write_config(self, config, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "config.json"
        path.write_text(json.dumps(config), "utf8")
        return path

    def argv(self, command, config_file, sql):
        command = PARSE if command == "start" else command
        return [sys.executable, "-I", str(self.script), command, str(config_file)] + [
            sql,
            self.codes,
        ]

    def env(self):
        return {"PATH": os.environ["PATH"]}

    def read_tree(self, stdout, sql):
        return parse_record(stdout, sql)

    def read_violations(self, stdout, sql):
        return SqlfluffBench.read_violations(self, stdout, sql)


def fakes(tmp_path: Path, **changes) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "fake_tool.py"
    script.write_text(FAKE_TOOL, "utf8")
    has = {
        sp.HEAD: ["CP01", "CP03"],
        sp.BASE: ["CP03", "CP01"],
        "sqlfluff": ["AL01", "CP01", "CP03"],
        "sqruff": ["CP01", "CP03", "LT01"],
    }
    codes = {t: "CP01" for t in sp.TOOLS}
    for tool, (tool_has, tool_codes) in changes.items():
        tool = tool.replace("_", "-")
        has[tool] = tool_has if tool_has is not None else has[tool]
        codes[tool] = tool_codes if tool_codes is not None else codes[tool]
    return {t: FakeBench(t, script, has[t], codes[t]) for t in sp.TOOLS}


@pytest.fixture
def fake_rules(monkeypatch):
    monkeypatch.setattr(sp, "tool_rules", lambda adapter: frozenset(adapter.has))


def test_a_session_of_fake_tools_runs_each_tool_with_the_rules(tmp_path, fake_rules):
    adapters = fakes(tmp_path / "t", sqruff=(None, "CP01,CP03"))
    data = sp.session(
        tmp_path / "s",
        adapters=adapters,
        dialects=["ansi"],
        profile="smoke",
        progress=None,
    )
    assert data["rules"] == ["CP01", "CP03"]
    for tool in sp.TOOLS:
        assert data["tool_rules"][tool]["ran"] == ["CP01", "CP03"]
        settings_core = data["report"]["tools"][tool]["settings"]["core"]
        assert settings_core["rules"] == "CP01,CP03"
    # The smoke profile has only the small inputs.
    names = ["ansi/small"]
    assert sorted(data["reference"]["inputs"]) == names
    for name in names:
        entry = data["reference"]["inputs"][name]
        assert entry["lint_codes"] == ["CP01"] and entry["fix_changes"] is False
    statuses = {(r["id"], r["tool"]): r for r in data["report"]["results"]}
    assert len(statuses) == 2 * 4
    for (bid, tool), r in statuses.items():
        if tool == "sqruff":
            # Its lint codes are not those of the sqlfluff reference with
            # the rules.
            assert r["status"] == INVALID, bid
            assert "not those of the sqlfluff reference" in r["reason"]
        else:
            assert r["status"] == VALID, (bid, tool, r["reason"])
    # The summary refuses a record that is not of the full scope.
    with pytest.raises(sp.Refused, match="the scope is"):
        sp.summarize({**data, "head": {}, "base": {}})


def test_a_session_stops_if_a_tool_does_not_have_a_rule(tmp_path, fake_rules):
    adapters = fakes(tmp_path / "t", sqruff=(["CP01"], None))
    with pytest.raises(sp.Refused, match="sqruff does not have the rules CP03"):
        sp.session(tmp_path / "s", adapters=adapters, dialects=["ansi"])
    assert not (tmp_path / "s" / "work").exists()


def test_a_session_stops_if_the_reference_has_another_rule(tmp_path, fake_rules):
    adapters = fakes(tmp_path / "t", sqlfluff=(None, "LT01"))
    with pytest.raises(sp.Refused, match="rule codes that the rules do not have"):
        sp.session(
            tmp_path / "s", adapters=adapters, dialects=["ansi"], profile="smoke"
        )


def test_a_session_stops_if_an_input_is_missing(tmp_path, fake_rules):
    adapters = fakes(tmp_path / "t")
    empty = tmp_path / "no-sqlfluff"
    empty.mkdir()
    with pytest.raises(sp.Refused, match="the inputs"):
        sp.session(
            tmp_path / "s", adapters=adapters, dialects=["ansi"], sqlfluff_root=empty
        )


def test_a_session_stops_if_an_input_is_not_that_of_the_definitions(
    tmp_path, fake_rules
):
    defs = definitions.load()
    defs["inputs"]["ansi/small"] = {**defs["inputs"]["ansi/small"], "sha256": "0"}
    adapters = fakes(tmp_path / "t")
    with pytest.raises(sp.Refused, match="not those of the definitions"):
        sp.session(tmp_path / "s", adapters=adapters, dialects=["ansi"], defs=defs)


def test_a_session_stops_on_a_missing_or_other_tool(tmp_path, fake_rules):
    adapters = fakes(tmp_path / "t")
    del adapters["sqruff"]
    with pytest.raises(sp.Refused, match="the tools are"):
        sp.session(tmp_path / "s", adapters=adapters)
    adapters = fakes(tmp_path / "t")
    adapters["sqruff"].name = "sqlfluff-rs"
    with pytest.raises(sp.Refused, match="the adapter of sqruff has another name"):
        sp.session(tmp_path / "s", adapters=adapters)


# The machine lock.


def _hold(path: Path) -> int:
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def test_run_stops_if_another_process_holds_the_lock(tmp_path, monkeypatch, capsys):
    lock = tmp_path / "lock"
    monkeypatch.setattr(sp, "LOCK_FILE", lock)
    fd = _hold(lock)
    try:
        scratch = tmp_path / "scratch"
        code = sp.main(["run", "--label", "X", "--scratch", str(scratch)])
    finally:
        os.close(fd)
    assert code == 2
    assert "is held by another process" in capsys.readouterr().err
    assert not scratch.exists()


def test_the_lock_is_taken_and_given_back(tmp_path):
    lock = tmp_path / "lock"
    with sp.machine_lock(lock) as how:
        assert how == "taken by scripts/s5/speed"
        assert sp.lock_is_held(lock)
    assert not sp.lock_is_held(lock)


def test_the_lock_of_a_parent_process_is_used(tmp_path, monkeypatch):
    lock = tmp_path / "lock"
    monkeypatch.setattr(sp.speed_check, "held_by_parent", lambda path: True)
    with sp.machine_lock(lock) as how:
        assert how == "held by a parent process"


def test_the_lock_check_of_the_container(tmp_path):
    lock = tmp_path / "lock"
    assert not sp.lock_is_held(lock)
    lock.write_text("")
    assert not sp.lock_is_held(lock)
    fd = _hold(lock)
    try:
        assert sp.lock_is_held(lock)
    finally:
        os.close(fd)


def test_run_inside_stops_if_the_lock_is_free(tmp_path, capsys):
    lock = tmp_path / "lock"
    lock.write_text("")
    scratch = tmp_path / "s"
    scratch.mkdir()
    argv = ["run-inside", "--scratch", str(scratch), "--lock", str(lock)]
    assert sp.main(argv) == 2
    assert "is free" in capsys.readouterr().err
    assert not (scratch / "session.json").exists()


def test_run_inside_with_the_lock_stops_on_the_tool_check(
    tmp_path, monkeypatch, capsys
):
    lock = tmp_path / "lock"
    monkeypatch.setenv(sqll_adapter.BASE_BINARY_ENV, str(tmp_path / "no" / "sqll"))
    scratch = tmp_path / "s"
    scratch.mkdir()
    fd = _hold(lock)
    try:
        argv = ["run-inside", "--scratch", str(scratch), "--lock", str(lock)]
        assert sp.main(argv) == 2
    finally:
        os.close(fd)
    assert "the tool check: " in capsys.readouterr().err
    assert not (scratch / "session.json").exists()


def test_run_refuses_a_scratch_folder_that_is_not_empty(tmp_path, capsys):
    (tmp_path / "x").write_text("x")
    assert sp.main(["run", "--label", "X", "--scratch", str(tmp_path)]) == 2
    assert "the scratch folder is not empty" in capsys.readouterr().err


# The builds and the container.


def test_the_container_has_no_network_and_a_read_only_repository(tmp_path):
    lock = tmp_path / "lock"
    sources = {"head": sp.ROOT, "base": tmp_path / "src" / "base"}
    argv = sp.docker_argv(tmp_path, "sqll-ci:x", sources, lock)
    assert argv[:5] == ["docker", "run", "--rm", "--network", "none"]
    assert f"{sp.ROOT}:{sp.ROOT}:ro" in argv
    assert f"{tmp_path}:{sp.C_SCRATCH}" in argv
    assert f"{lock}:{sp.C_LOCK}:ro" in argv
    env = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    assert f"SQLL_BIN={sp.C_SCRATCH}/bin/head/sqll" in env
    assert f"{sqll_adapter.SOURCE_ENV}={sp.ROOT}" in env
    assert f"{sqll_adapter.BASE_BINARY_ENV}={sp.C_SCRATCH}/bin/base/sqll" in env
    assert f"{sqll_adapter.BASE_SOURCE_ENV}={sp.C_SCRATCH}/src/base" in env
    assert argv[-8:] == [
        "sqll-ci:x",
        sp.C_PYTHON,
        "scripts/s5/speed",
        "run-inside",
        "--scratch",
        sp.C_SCRATCH,
        "--lock",
        sp.C_LOCK,
    ]
    with pytest.raises(sp.Refused, match="is not in the scratch folder"):
        sp.container_path(tmp_path, Path("/elsewhere"))


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_one_build_only_if_the_build_inputs_are_the_same(tmp_path):
    root = tmp_path / "repo"
    (root / "crates").mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "crates" / "a.rs").write_text("1")
    (root / "README").write_text("1")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "1")
    first = _git(root, "rev-parse", "HEAD")
    (root / "README").write_text("2")
    _git(root, "commit", "-qam", "2")
    docs = _git(root, "rev-parse", "HEAD")
    (root / "crates" / "a.rs").write_text("2")
    _git(root, "commit", "-qam", "3")
    code = _git(root, "rev-parse", "HEAD")
    st = sp.probe.Steps(tmp_path)
    assert sp.same_build(st, first, docs, root)
    assert not sp.same_build(st, docs, code, root)
    assert sp.root_is(st, code, root)
    assert not sp.root_is(st, docs, root)
    (root / "README").write_text("3")
    assert not sp.root_is(st, code, root)


FAKE_SQLL = """#!{python} -I
import json, sys
if sys.argv[1:2] == ["version"]:
    print(json.dumps({{"version": "0.1.0", "source_sha256": "{source}"}}))
"""


def test_the_base_binary_is_a_copy_of_head_if_the_build_is_the_same(tmp_path):
    scratch = tmp_path / "scratch"
    head = scratch / "bin" / "head" / "sqll"
    head.parent.mkdir(parents=True)
    head.write_text(FAKE_SQLL.format(python=sys.executable, source="a" * 64))
    head.chmod(0o755)
    st = sp.probe.Steps(scratch)
    commit = _git(REPO_ROOT, "rev-parse", "HEAD")
    record, source = sp.build_base(st, scratch, commit, commit, Path("/head-src"))
    assert source == Path("/head-src")
    base = scratch / "bin" / "base" / "sqll"
    assert base.read_bytes() == head.read_bytes()
    assert record["version"] == "0.1.0" and record["source_sha256"] == "a" * 64
    assert record["build_s"] == 0.0
    assert record["source"].startswith("the HEAD build: ")


# The status and the design record.


def test_the_status_file_has_the_task_row_and_the_record():
    text = (REPO_ROOT / "status" / "S5.md").read_text("utf8")
    t3 = next(line for line in text.splitlines() if line.startswith("| T3 |"))
    assert "scripts/s5/speed" in t3
    assert "results/S5/speed/T3.json" in text
    design = (REPO_ROOT / "docs" / "decisions" / "s5-rules.md").read_text("utf8")
    assert "scripts/s5/speed" in design
