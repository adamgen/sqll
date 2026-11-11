"""The S7 case runner (sqll_harness/s7_tests/runner.py): the checks of a case
and the runs through a binary. The binaries here are small shell scripts, so
these tests need no installed tool."""

import json
import stat
from pathlib import Path

import pytest

from sqll_harness.adapters.base import Adapter, FixResult, LintResult
from sqll_harness.adapters.sqlfluff_rs import RustConfigConflict
from sqll_harness.cases import ERROR, FAIL, PASS
from sqll_harness.s7_tests import runner
from sqll_harness.s7_tests.caseformat import Case, Node
from sqll_harness.s7_tests.runner import (
    CaseOutcome,
    NodeOutcome,
    ToolRun,
    check_files,
    check_violations,
    match_text,
)

V1 = {"code": "AL04", "description": "Duplicate table alias 'a'.", "start_line_no": 5}
V2 = {"code": "AL04", "description": "Duplicate table alias 'a'.", "start_line_no": 6}
V3 = {"code": "LT01", "description": "Expected single whitespace.", "warning": False}


# Text checks.


def test_match_text_passes():
    text = "== [a.sql] FAIL\nL:   2 | P:   1 | LT02\n"
    matcher = {
        "equals": text,
        "startswith": "== [a.sql]",
        "contains": ["LT02", "FAIL"],
        "not_contains": ["Traceback"],
    }
    assert match_text("stdout", text, matcher) == []
    assert match_text("stdout", '{"a": [1]}', {"json": {"a": [1]}}) == []


@pytest.mark.parametrize(
    ("matcher", "error"),
    [
        ({"equals": "x"}, "stdout.equals: the text is"),
        ({"startswith": "L:"}, "stdout.startswith: the text starts with"),
        ({"contains": ["LT02", "CP01"]}, "stdout.contains[1]: 'CP01' is not in"),
        ({"not_contains": ["FAIL"]}, "stdout.not_contains[0]: 'FAIL' is in"),
        ({"json": {"a": 1}}, "stdout.json: the text is not JSON"),
    ],
)
def test_match_text_fails(matcher, error):
    out = match_text("stdout", "== [a.sql] FAIL\nL:   2 | P:   1 | LT02\n", matcher)
    assert len(out) == 1 and out[0].startswith(error), out


# Violation checks.


def test_violation_checks_pass():
    found = [V1, V3, V2]
    assert check_violations("v", found, {"count": 3}) == []
    assert (
        check_violations("v", found, {"select": {"code": "LT01"}, "min_count": 1}) == []
    )
    assert check_violations("v", found, {"select": {"code": "RF02"}, "count": 0}) == []
    check = {
        "select": {"code": "AL04", "description": {"contains": "alias 'a'"}},
        "records": [{"start_line_no": 5}, {"start_line_no": 6}],
    }
    assert check_violations("v", found, check) == []
    exact = {"select": {"code": "LT01"}, "exact": True, "records": [dict(V3)]}
    assert check_violations("v", found, exact) == []


@pytest.mark.parametrize(
    ("check", "error"),
    [
        ({"count": 2}, "v.count: 3 violations, not 2"),
        ({"select": {"code": "RF02"}, "min_count": 1}, "v.min_count: 0 violations"),
        (
            {"select": {"code": "AL04"}, "records": [{}]},
            "v.records: 2 violations, not 1",
        ),
        (
            {"select": {"code": "AL04"}, "records": [{"start_line_no": 6}, {}]},
            "v.records[0]: the violation is",
        ),
        (
            {"select": {"code": "LT01"}, "exact": True, "records": [{"code": "LT01"}]},
            "v.records[0]: more keys ['description', 'warning']",
        ),
        # A key that the violation does not have does not match.
        ({"select": {"fixes": []}, "min_count": 1}, "v.min_count: 0 violations"),
        # The type must be the same: 0 is not False.
        ({"select": {"warning": 0}, "min_count": 1}, "v.min_count: 0 violations"),
    ],
)
def test_violation_checks_fail(check, error):
    out = check_violations("v", [V1, V3, V2], check)
    assert out and out[0].startswith(error), out


def test_cli_violations_reads_lint_json():
    stdout = json.dumps(
        [
            {"filepath": "a.sql", "violations": [V1]},
            {"filepath": "b.sql", "violations": [V3]},
        ]
    )
    assert runner.cli_violations(stdout, "b.sql") == [V3]
    with pytest.raises(runner.CheckFailed, match="2 files in the output, not 1"):
        runner.cli_violations(stdout, None)
    with pytest.raises(runner.CheckFailed, match="no output for the file c.sql"):
        runner.cli_violations(stdout, "c.sql")
    with pytest.raises(runner.CheckFailed, match="not lint JSON output"):
        runner.cli_violations("All Finished!", None)


# Files of a tmp case.


def test_check_files():
    case = Case(
        "c",
        "cli",
        {"exit_code": 0, "files": {"a.sql": "SELECT 1\n", "out.txt": "x"}},
        cwd="tmp",
        files={"a.sql": "select 1\n", "b.sql": "select 2\n"},
    )
    good = {"a.sql": "SELECT 1\n", "b.sql": "select 2\n", "out.txt": "x"}
    assert check_files(case, good) == []
    assert check_files(case, good | {"a.sql": "select 1\n"}) == [
        "files.a.sql: not the changed content: 'select 1\\n'"
    ]
    assert check_files(case, good | {"b.sql": "SELECT 2\n"}) == [
        "files.b.sql: not the unchanged content: 'SELECT 2\\n'"
    ]
    assert check_files(case, good | {"new.sql": ""}) == [
        "files.new.sql: a new file that the case does not give"
    ]
    assert check_files(case, {k: v for k, v in good.items() if k != "out.txt"}) == [
        "files.out.txt: the file does not exist"
    ]


# Node status.


@pytest.mark.parametrize(
    ("statuses", "status"),
    [
        ([PASS], PASS),
        ([PASS, PASS], PASS),
        ([PASS, FAIL], FAIL),
        ([FAIL, ERROR, PASS], ERROR),
        ([], FAIL),
    ],
)
def test_a_node_passes_only_if_each_case_passes(statuses, status):
    cases = [
        CaseOutcome(f"c{i}", s, "" if s == PASS else "r")
        for i, s in enumerate(statuses)
    ]
    assert NodeOutcome("n", "sqlfluff", cases).status == status


# Runs through a binary: a shell script that prints its argv, cwd, and stdin.

SCRIPT = """#!/bin/sh
echo "cwd=$(pwd)"
printf 'arg=%s\\n' "$@"
cat > /dev/null
echo "err" >&2
if [ "$1" = fix ] && [ -f a.sql ]; then printf 'SELECT 1\\n' > a.sql; fi
exit "${EXIT_CODE:-0}"
"""


class FakeAdapter(Adapter):
    name = "fake"
    lint_fields = None

    def __init__(self, violations=None, fixed=None, errors=()):
        self.violations = violations or []
        self.fixed = fixed
        self.errors = list(errors)
        self.calls = []

    def version(self):
        return "0"

    def parse(self, *args, **kwargs):
        raise NotImplementedError

    def parse_file(self, *args, **kwargs):
        raise NotImplementedError

    def fix_file(self, *args, **kwargs):
        raise NotImplementedError

    def lint(self, sql_paths, rules, dialect, config, workdir):
        self.calls.append(("lint", sql_paths[0].read_text(), rules, dialect, config))
        return LintResult({sql_paths[0]: self.violations}, list(self.errors))

    def fix(self, sql_path, rules, dialect, config, workdir):
        self.calls.append(("fix", sql_path.read_text(), rules, dialect, config))
        return FixResult(self.fixed, list(self.errors))


def fake_run(tmp_path: Path, name: str = "sqlfluff", exit_code: int = 0) -> ToolRun:
    binary = tmp_path / "bin" / "tool"
    binary.parent.mkdir(exist_ok=True)
    binary.write_text(SCRIPT)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    env = {"PATH": "/usr/bin:/bin", "EXIT_CODE": str(exit_code)}
    return ToolRun(name, FakeAdapter(), binary, env)


def cli_case(**kwargs) -> Case:
    checks = kwargs.pop("checks", {"exit_code": 0})
    return Case("c", "cli", checks, **{"argv": ["lint", "-"], **kwargs})


def test_cli_case_passes_and_fails(tmp_path):
    run = fake_run(tmp_path, exit_code=1)
    case = cli_case(checks={"exit_code": 1, "stderr": {"equals": "err\n"}})
    assert runner.run_case(run, case) == CaseOutcome("c", PASS)
    case = cli_case(checks={"exit_code": 0, "stdout": {"contains": ["nothing"]}})
    out = runner.run_case(run, case)
    assert out.status == FAIL
    assert out.reason == (
        "exit_code: 1, not 0; stdout.contains[0]: 'nothing' is not in the text"
    )


def test_cli_case_cwd_and_placeholders(tmp_path):
    from sqll_harness.paths import SQLFLUFF_ROOT

    run = fake_run(tmp_path)
    # The default cwd is the root of the submodule: the fixtures are read in
    # place.
    case = cli_case(
        checks={"exit_code": 0, "stdout": {"startswith": f"cwd={SQLFLUFF_ROOT}\n"}}
    )
    assert runner.run_case(run, case).status == PASS
    # A tmp case: its files, the placeholders, and a changed file.
    case = cli_case(
        argv=["fix", "{tmp}/a.sql", "{sqlfluff}/x"],
        cwd="tmp",
        files={"a.sql": "select 1\n"},
        checks={
            "exit_code": 0,
            "stdout": {
                "contains": ["arg=fix\narg=/", f"/a.sql\narg={SQLFLUFF_ROOT}/x\n"],
                "not_contains": ["{tmp}", "{sqlfluff}", f"cwd={SQLFLUFF_ROOT}"],
            },
            "files": {"a.sql": "SELECT 1\n"},
        },
    )
    assert runner.run_case(run, case) == CaseOutcome("c", PASS)
    assert runner._substitute(["{tmp}/a", "b{sqlfluff}", "{x}"], Path("/t")) == [
        "/t/a",
        f"b{SQLFLUFF_ROOT}",
        "{x}",
    ]


def test_cli_case_changed_file_that_the_case_does_not_give(tmp_path):
    run = fake_run(tmp_path)
    case = cli_case(
        argv=["fix", "a.sql"],
        cwd="tmp",
        files={"a.sql": "select 1\n"},
        checks={"exit_code": 0},
    )
    out = runner.run_case(run, case)
    assert out == CaseOutcome(
        "c", FAIL, "files.a.sql: not the unchanged content: 'SELECT 1\\n'"
    )


def test_sqruff_needs_a_translation(tmp_path):
    run = fake_run(tmp_path, name="sqruff")
    out = runner.run_case(run, cli_case())
    assert out == CaseOutcome(
        "c",
        FAIL,
        "unsupported: sqlfluff CLI command 'lint' (the case has no sqruff translation)",
    )
    case = cli_case(sqruff=["lint", "-"], checks={"exit_code": 0})
    assert runner.run_case(run, case).status == PASS
    case = cli_case(
        sqruff=["lint", "-"], checks={"exit_code": 0, "violations": [{"count": 0}]}
    )
    out = runner.run_case(run, case)
    assert out.reason == "unsupported: violations check on the sqruff CLI output"


def test_sqlfluff_rs_layer(tmp_path):
    run = fake_run(tmp_path, name="sqlfluff-rs")
    run.layer_file = tmp_path / "layer.toml"
    case = cli_case(
        argv=["lint", "a.sql"],
        cwd="tmp",
        files={"a.sql": "select 1\n"},
        checks={"exit_code": 0},
    )
    case.checks["stdout"] = {
        "contains": [f"arg=lint\narg=--config\narg={run.layer_file}\narg=a.sql\n"]
    }
    # The layer goes after the command.
    assert runner.run_case(run, case) == CaseOutcome("c", PASS)
    # A command that reads no config file gets no layer.
    case = cli_case(argv=["version"], checks={"exit_code": 0})
    assert runner.run_case(run, case).status == PASS


@pytest.mark.parametrize(
    "case",
    [
        cli_case(argv=["lint", "--config", "x.cfg", "-"]),
        cli_case(argv=["lint", "-"], stdin="-- sqlfluff:use_rust_rules:False\n"),
        cli_case(
            argv=["lint", "a.sql"],
            cwd="tmp",
            files={
                "a.sql": "select 1\n",
                ".sqlfluff": "[sqlfluff]\nuse_rust_parser=1\n",
            },
        ),
        cli_case(
            argv=["lint", "d"],
            cwd="tmp",
            files={"d/a.sql": "-- sqlfluff:use_rust_parser:False\nselect 1\n"},
        ),
    ],
)
def test_sqlfluff_rs_layer_conflict_is_an_error(tmp_path, case):
    run = fake_run(tmp_path, name="sqlfluff-rs")
    run.layer_file = tmp_path / "layer.toml"
    out = runner.run_case(run, case)
    assert out.status == ERROR
    assert out.reason.startswith("RustConfigConflict: ")
    assert RustConfigConflict.__name__ in out.reason


def test_sqlfluff_rs_fallback_warning_is_an_error(tmp_path):
    run = fake_run(tmp_path, name="sqlfluff-rs")
    run.layer_file = tmp_path / "layer.toml"
    run.binary.write_text("#!/bin/sh\necho 'sqlfluffrs not available' >&2\n")
    out = runner.run_case(run, cli_case(checks={"exit_code": 0}))
    assert out == CaseOutcome(
        "c", ERROR, "RustParserNotUsed: sqlfluff logged 'sqlfluffrs not available'"
    )


# api cases through an adapter.


def api_case(function: str, checks: dict, **kwargs) -> Case:
    return Case("c", "api", checks, function=function, sql="select 1\n", **kwargs)


def test_api_lint_defaults_of_the_simple_api(tmp_path):
    run = fake_run(tmp_path)
    run.adapter = FakeAdapter(violations=[V3])
    case = api_case("lint", {"violations": [{"select": {"code": "LT01"}, "count": 1}]})
    assert runner.run_case(run, case).status == PASS
    # No dialect and no rules: the simple API uses ansi and all rules.
    assert run.adapter.calls == [("lint", "select 1\n", ["all"], "ansi", None)]


def test_api_lint_gives_rules_dialect_and_exclude_rules(tmp_path):
    run = fake_run(tmp_path)
    run.adapter = FakeAdapter(violations=[])
    case = api_case(
        "lint",
        {"violations": [{"count": 0}]},
        rules=["CV02"],
        dialect="mysql",
        exclude_rules=["LT01", "LT02"],
        config={"rules": {"x": 1}},
    )
    assert runner.run_case(run, case).status == PASS
    config = {"rules": {"x": 1}, "core": {"exclude_rules": "LT01,LT02"}}
    assert run.adapter.calls == [("lint", "select 1\n", ["CV02"], "mysql", config)]
    # The case config does not change.
    assert case.config == {"rules": {"x": 1}}


def test_api_case_reads_only_the_output_fields_of_the_tool(tmp_path):
    run = fake_run(tmp_path, name="sqruff")
    run.adapter = FakeAdapter(violations=[V3])
    run.adapter.lint_fields = frozenset({"code", "description"})
    case = api_case(
        "lint",
        {"violations": [{"select": {"code": "LT01", "warning": False}, "count": 1}]},
    )
    assert runner.run_case(run, case) == CaseOutcome(
        "c", FAIL, "unsupported: output field warning"
    )


def test_api_fix(tmp_path):
    run = fake_run(tmp_path)
    run.adapter = FakeAdapter(fixed="SELECT 1\n")
    assert runner.run_case(run, api_case("fix", {"fixed": "SELECT 1\n"})).status == PASS
    out = runner.run_case(run, api_case("fix", {"fixed": "select 1\n"}))
    assert out == CaseOutcome("c", FAIL, "fixed: the text is 'SELECT 1\\n'")
    run.adapter = FakeAdapter(errors=["exit code 2: boom"])
    out = runner.run_case(run, api_case("fix", {"fixed": "x"}))
    assert out == CaseOutcome("c", ERROR, "RuntimeError: exit code 2: boom")


def test_run_nodes_keeps_the_order_and_refuses_an_unknown_tool():
    nodes = [Node(f"n{i}", "rules", "f.yml", []) for i in range(5)]
    adapters = {"sqlfluff": FakeAdapter()}
    adapters["sqlfluff"].binary = Path("/bin/true")
    out = runner.run_nodes(nodes, ["sqlfluff"], jobs=3, adapters=adapters)
    assert [n.id for n in out["sqlfluff"]] == [n.id for n in nodes]
    with pytest.raises(ValueError, match="unknown tools"):
        runner.run_nodes(nodes, ["sqll"], adapters=adapters)
