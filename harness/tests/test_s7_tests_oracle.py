"""The S7 trace oracle (docs/decisions/s7-tests-design.md, "Trace oracle").

results/S7-tests/oracle.json must be the check of the recorded traces, and a
new run of the oracle must give it again. Each fail-closed check has a
mutation test: a change of a case, of the trace, of the report, or of the
not-reproduced record that the oracle must refuse. The tests of the trace
step run trace-nodes on a small test tree with the oracle tools.
"""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import needs

from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT, tools_dir
from sqll_harness.s7_tests import asserts, caseformat, oracle
from sqll_harness.s7_tests.asserts import AssertSourceError

RESULTS = REPO_ROOT / "results" / "S7-tests"
SCRIPTS = REPO_ROOT / "scripts" / "s7-tests"
REPORT = json.loads((RESULTS / "report.json").read_text("utf8"))
RECORDED = json.loads((RESULTS / "oracle.json").read_text("utf8"))
TRACES = {
    tool: json.loads((RESULTS / f"oracle-trace-{tool}.json").read_text("utf8"))
    for tool in oracle.TOOLS
}
CASES = caseformat.load()
NONE = oracle.NotReproduced([], False)
DESIGN = (REPO_ROOT / "docs" / "decisions" / "s7-tests-design.md").read_text("utf8")
needs_oracles = needs("sqlfluff-oracle/bin/python", "sqlfluff-rs-oracle/bin/python")

CLI = "test/cli/commands_test.py"
DIRECTED = f"{CLI}::test__cli__command_directed"
DIALECT = f"{CLI}::test__cli__command_dialect"
RENDER = f"{CLI}::test__cli__command_no_dialect[command0]"
VERSION = f"{CLI}::test__cli__command_version"
INTERNAL = f"{CLI}::test__get_filtered_parse_violations_caches_rulepack_per_config"
EXCLUDE = (
    "test/core/config/fluffconfig_test.py::test__config__glob_exclude_config_tests"
)
CV02 = "test/rules/std_CV02_test.py::test__rules__std_CV02_raised"
LT05 = (
    "test/rules/std_LT05_LT09_combo_test.py::test__rules__std_LT05_LT09_long_line_fix"
)
ST03 = "test/rules/std_ST03_test.py::test__rules__std_ST03_multiple_unused_ctes"


def check(tool="sqlfluff", trace=None, nodes=None, report=None, records=NONE):
    return oracle.check_tool(
        tool,
        TRACES[tool] if trace is None else trace,
        CASES.nodes if nodes is None else nodes,
        REPORT if report is None else report,
        SQLFLUFF_ROOT,
        records,
    )


def node_of(nodes, node_id):
    return next(n for n in nodes if n.id == node_id)


def errors_with(result, text):
    return [e for e in result["errors"] if text in e]


# The recorded result.


def test_recorded_result_is_the_check_of_the_recorded_traces():
    records = oracle.load_not_reproduced()
    by_tool = {tool: check(tool, records=records) for tool in oracle.TOOLS}
    assert oracle.build(by_tool, records) == RECORDED


@pytest.mark.parametrize("tool", oracle.TOOLS)
def test_the_oracle_agrees_with_each_pilot_case(tool):
    result = RECORDED["tools"][tool]
    assert result["errors"] == []
    report_ids = [n["id"] for n in REPORT["nodes"]]
    assert [n["id"] for n in result["nodes"]] == report_ids
    assert report_ids == [n.id for n in CASES.nodes]
    assert result["counts"]["agree"] == result["counts"]["nodes"] == 15
    status = {n["id"]: n["results"][tool]["status"] for n in REPORT["nodes"]}
    for node in result["nodes"]:
        assert node["trace"] == status[node["id"]], node["id"]
        assert node["pytest"] == {"pass": "passed", "fail": "failed"}[node["trace"]]
        assert node["errors"] == []
    # Each assert of the source tests: 49, each cited by a check.
    assert result["counts"]["asserts"] == 49
    assert result["counts"]["not_reproduced"] == 0
    internal = [e["id"] for e in REPORT["excluded"] if e["class"] == "python-internal"]
    assert [n["id"] for n in result["python_internal"]] == internal == [INTERNAL]
    assert result["python_internal"][0]["calls"] == {}


def test_the_sqlfluff_rs_failure_is_the_report_failure():
    # With use_rust_rules, CP01 has another description (status/S7-tests.md).
    nodes = {n["id"]: n for n in RECORDED["tools"]["sqlfluff-rs"]["nodes"]}
    assert nodes[DIRECTED]["pytest"] == "failed"
    assert nodes[DIRECTED]["cases"][0]["reason"].startswith("stdout.startswith:")
    assert sum(n["trace"] == "fail" for n in nodes.values()) == 1


def test_each_trace_is_of_its_tool():
    for tool, trace in TRACES.items():
        assert oracle.trace_errors(trace, tool, list(trace["nodes"])) == []
        assert trace["sqlfluff"] == "4.4.0"
        assert trace["root_config"] == {}
    assert TRACES["sqlfluff-rs"]["sqlfluffrs"] == "4.4.0"
    assert TRACES["sqlfluff-rs"]["parse_runs"]["Parser"] == 0
    assert TRACES["sqlfluff-rs"]["parse_runs"]["RustParser"] > 0


def test_no_case_uses_a_not_reproduced_record_yet():
    # Decision 4: the pointer section comes in T4 or T5. Until it merges, the
    # record has no row, and the oracle refuses one.
    records = oracle.load_not_reproduced()
    assert records.records == [] and records.errors == []
    assert not records.pointer
    assert RECORDED["not_reproduced"] == {"records": 0, "pointer": False}
    for tool in oracle.TOOLS:
        assert RECORDED["tools"][tool]["counts"]["not_reproduced"] == 0
        assert all(n["not_reproduced"] == 0 for n in RECORDED["tools"][tool]["nodes"])


def test_design_record_gives_the_limits():
    section = DESIGN[DESIGN.index("### Limits of the oracle") :]
    section = section[: section.index("\n## ")]
    for item in (
        "1. Inputs.",
        "2. Order.",
        "3. Meaning.",
        "4. Asserts.",
        "5. Processes.",
        "6. In process.",
        "7. Tools and classes.",
        "8. `--rust`",
    ):
        assert item in section, item


# Mutations of a case. Each one must make the oracle fail.


def _set(node_id, change):
    nodes = copy.deepcopy(CASES.nodes)
    change(node_of(nodes, node_id))
    return nodes


def _argv(node):
    node.cases[0].argv[-1] = "test/fixtures/linter/indentation_errors.sql"


def _swap(node):
    node.cases.reverse()


def _extra_case(node):
    node.cases.append(copy.deepcopy(node.cases[0]))
    node.cases[-1].name = "again"


def _uncite(aid):
    return lambda node: node.asserts.pop(aid)


def _checks(path, value):
    """Set a value in the checks of the first case (path of keys)."""

    def change(node):
        target = node.cases[0].checks
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return change


CASE_MUTATIONS = [
    # A changed input.
    ("cli argv", DIRECTED, _argv, "case directed: input argv"),
    ("cli stdin", RENDER, lambda n: setattr(n.cases[0], "stdin", "SELECT 2"), "stdin"),
    ("api sql", CV02, lambda n: setattr(n.cases[0], "sql", "SELECT 1"), "input sql"),
    ("api rules", CV02, lambda n: setattr(n.cases[0], "rules", None), "input rules"),
    (
        "api dialect",
        CV02,
        lambda n: setattr(n.cases[0], "dialect", "bigquery"),
        "input dialect",
    ),
    (
        "api function",
        LT05,
        lambda n: setattr(n.cases[0], "function", "lint"),
        "input function",
    ),
    (
        "linter path",
        EXCLUDE,
        lambda n: n.cases[0].argv.__setitem__(
            -1, "test/fixtures/config/glob_include/test.sql"
        ),
        "input argv",
    ),
    ("case order", VERSION, _swap, "case version_verbose: input argv"),
    ("a case with no call", CV02, _extra_case, "cases with no traced call"),
    # A changed expected value.
    ("exit code", DIALECT, _checks(["exit_code"], 1), "check 2"),
    (
        "stdout",
        VERSION,
        _checks(["stdout", "contains", 0], "4.3.0"),
        "check 2",
    ),
    ("stderr", RENDER, _checks(["stderr", "not_contains"], ["User"]), "check 2"),
    ("fixed", LT05, _checks(["fixed"], "SELECT 1\n"), "check 2"),
    (
        "violation record",
        ST03,
        _checks(["violations", 0, "records", 2, "end_file_pos"], 137),
        "check 2",
    ),
    (
        "linter violations",
        EXCLUDE,
        _checks(["violations", 0, "select", "start_line_pos"], 9),
        "check 2",
    ),
    # A missing assert citation.
    ("uncited assert", DIRECTED, _uncite("L108"), "assert L108: no check cites it"),
    ("uncited helper", DIALECT, _uncite("L114:ret_code"), "assert L114:ret_code"),
    ("uncited api", ST03, _uncite("L27"), "assert L27: no check cites it"),
    (
        "cites a non-assert",
        CV02,
        lambda n: n.asserts.__setitem__("L9", ["raised:violations[0]"]),
        "cites L9, which is not an assert",
    ),
]


@pytest.mark.parametrize(
    ("node_id", "change", "error"),
    [m[1:] for m in CASE_MUTATIONS],
    ids=[m[0] for m in CASE_MUTATIONS],
)
@pytest.mark.parametrize("tool", oracle.TOOLS)
def test_case_mutation_makes_the_oracle_fail(tool, node_id, change, error):
    result = check(tool, nodes=_set(node_id, change))
    found = errors_with(result, error)
    assert found, result["errors"]
    assert all(e.startswith(node_id) for e in result["errors"]), result["errors"]
    assert result["counts"]["agree"] == 14


# Mutations of the trace.


def _trace(change, tool="sqlfluff"):
    trace = copy.deepcopy(TRACES[tool])
    change(trace)
    return trace


def _node(trace, node_id):
    return trace["nodes"][node_id]


def _call(trace, node_id, index=0):
    return trace["nodes"][node_id]["calls"][index]


TRACE_MUTATIONS = [
    (
        "python-internal node with a cli call",
        lambda t: _node(t, INTERNAL)["calls"].append(_call(t, DIRECTED)),
        "class python-internal, but the trace has 1 cli calls",
    ),
    (
        "python-internal node with an api call",
        lambda t: _node(t, INTERNAL)["calls"].append(_call(t, CV02)),
        "class python-internal, but the trace has 1 api calls",
    ),
    (
        "python-internal node that fails",
        lambda t: _node(t, INTERNAL).update(outcome="failed"),
        "the trace of a node that does not pass can be incomplete",
    ),
    (
        "untraced subprocess",
        lambda t: _node(t, CV02)["processes"].append("program (subprocess.Popen)"),
        "starts a process: program (subprocess.Popen)",
    ),
    (
        "untraced subprocess in a python-internal node",
        lambda t: _node(t, INTERNAL)["processes"].append("new Python process"),
        "starts a process: new Python process",
    ),
    (
        "untraced call",
        lambda t: _node(t, DIRECTED)["untraced"].append("a sqlfluff CLI command"),
        "an untraced call: a sqlfluff CLI command",
    ),
    (
        "node of the report not in the trace",
        lambda t: t["nodes"].pop(ST03),
        f"{ST03}: not in the trace",
    ),
    (
        "python-internal node not in the trace",
        lambda t: t["nodes"].pop(INTERNAL),
        f"{INTERNAL}: not in the trace",
    ),
    (
        "a call with no case",
        lambda t: _node(t, CV02)["calls"].append(_call(t, CV02)),
        "2 traced calls, 1 cases: a call has no case",
    ),
    (
        "a call outside the nodes",
        lambda t: t["outside"]["calls"].append(_call(t, CV02)),
        "1 calls outside the nodes",
    ),
    (
        "a process outside the nodes",
        lambda t: t["outside"]["processes"].append("fork"),
        "1 processes outside the nodes",
    ),
    (
        "a node that the oracle did not ask for",
        lambda t: t["nodes"].update({"test/x_test.py::test_x": _node(t, CV02)}),
        "nodes that the oracle did not ask for",
    ),
    (
        "a collection error",
        lambda t: t["collection_errors"].update({"test/x_test.py": "ImportError"}),
        "collection error: test/x_test.py",
    ),
    (
        "a skipped node",
        lambda t: _node(t, CV02).update(outcome="skipped"),
        "the pytest outcome is skipped",
    ),
    (
        "a changed traced output",
        lambda t: _call(t, DIALECT)["outputs"].update(exit_code=0),
        "check 2: the checks on the traced outputs give fail",
    ),
    (
        "a CLI exception",
        lambda t: _call(t, VERSION)["outputs"].update(exception="ValueError: x"),
        "check 2",
    ),
    (
        "a call that raised",
        lambda t: _call(t, CV02).update(raised="APIParsingError: x"),
        "check 2",
    ),
    (
        "a CLI input that the oracle cannot map",
        lambda t: _call(t, DIALECT)["inputs"]["unsupported"].append("env"),
        "case unknown_dialect: env",
    ),
    (
        "a CLI call in another folder",
        lambda t: _call(t, DIALECT)["inputs"].update(cwd="/tmp/x"),
        "input cwd",
    ),
    (
        "a simple-API config",
        lambda t: _call(t, CV02)["inputs"].update(config={"method": "from_path"}),
        "simple-API argument config=",
    ),
    (
        "a simple-API call in another folder",
        lambda t: _call(t, CV02)["inputs"].update(cwd="/tmp/x"),
        "a simple-API call in the folder /tmp/x",
    ),
    (
        "a Linter config of another folder",
        lambda t: _call(t, EXCLUDE)["inputs"]["linter"]["config"]["args"].update(
            path="test/fixtures/config"
        ),
        "is not the folder of",
    ),
    (
        "a Linter config from overrides",
        lambda t: _call(t, EXCLUDE)["inputs"]["linter"].update(
            config={"method": "FluffConfig", "args": {"overrides": {}}}
        ),
        "the oracle maps only FluffConfig.from_path",
    ),
    (
        "a Linter option",
        lambda t: _call(t, EXCLUDE)["inputs"].update(options={"fix": True}),
        "Linter.lint_path options",
    ),
    (
        "a Linter argument",
        lambda t: _call(t, EXCLUDE)["inputs"]["linter"].update(dialect="ansi"),
        "Linter arguments ['dialect'] other than config",
    ),
    (
        "a call of an unknown kind",
        lambda t: _call(t, CV02).update(kind="other"),
        "a traced call of the unknown kind 'other'",
    ),
    (
        "a root config",
        lambda t: t.update(root_config={"core": {"dialect": "ansi"}}),
        "the sqlfluff root has a sqlfluff config",
    ),
    (
        "another sqlfluff version",
        lambda t: t.update(sqlfluff="4.3.0"),
        "the trace is of sqlfluff 4.3.0",
    ),
    (
        "a trace of the other tool",
        lambda t: t.update(rust=True),
        "the trace is not of the tool sqlfluff",
    ),
]


@pytest.mark.parametrize(
    ("change", "error"),
    [m[1:] for m in TRACE_MUTATIONS],
    ids=[m[0] for m in TRACE_MUTATIONS],
)
def test_trace_mutation_makes_the_oracle_fail(change, error):
    result = check(trace=_trace(change))
    assert errors_with(result, error), result["errors"]


def test_rust_trace_mutations_make_the_oracle_fail():
    def python_parser(trace):
        trace["parse_runs"]["Parser"] = 1

    result = check("sqlfluff-rs", trace=_trace(python_parser, "sqlfluff-rs"))
    assert errors_with(result, "--rust: the parse runs are"), result["errors"]
    result = check("sqlfluff-rs", trace=TRACES["sqlfluff"])
    assert errors_with(result, "the trace is not of the tool sqlfluff-rs")


def test_a_failed_node_can_stop_before_its_last_call():
    # The first case of the version node fails and pytest stops there.
    def stop(trace):
        node = _node(trace, VERSION)
        node["outcome"] = "failed"
        node["calls"] = node["calls"][:1]
        node["calls"][0]["outputs"]["exit_code"] = 1

    report = copy.deepcopy(REPORT)
    for node in report["nodes"]:
        if node["id"] == VERSION:
            node["results"]["sqlfluff"]["status"] = "fail"
    result = check(trace=_trace(stop), report=report)
    assert result["errors"] == []
    nodes = {n["id"]: n for n in result["nodes"]}
    assert [c["status"] for c in nodes[VERSION]["cases"]] == ["fail", "not traced"]
    # If the traced case passes, the stop is not a failure of a check.
    result = check(
        trace=_trace(
            lambda t: stop(t) or _call(t, VERSION)["outputs"].update(exit_code=0)
        ),
        report=report,
    )
    assert errors_with(result, "cases with no traced call: ['version_verbose']")


# Mutations of the report.


def _report(change):
    report = copy.deepcopy(REPORT)
    change(report)
    return report


def _status(node_id, status):
    def change(report):
        for node in report["nodes"]:
            if node["id"] == node_id:
                node["results"]["sqlfluff"]["status"] = status

    return change


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (_status(CV02, "fail"), "check 3: the report gives fail, pytest gives passed"),
        (_status(CV02, "error"), "check 3: the report gives error"),
        (lambda r: r["nodes"].pop(0), "the report is not of the case files"),
        (
            lambda r: r["excluded"].append(
                {
                    "id": "test/cli/commands_test.py::test___main___help",
                    "class": "python-internal",
                }
            ),
            "test___main___help: not in the trace",
        ),
    ],
)
def test_report_mutation_makes_the_oracle_fail(change, error):
    result = check(report=_report(change))
    assert errors_with(result, error), result["errors"]


# The not-reproduced record.


def test_a_record_is_refused_before_the_pointer_section():
    nodes = _set(DIRECTED, _uncite("L108"))
    row = oracle.Record(DIRECTED, "L108", "a reason")
    result = check(nodes=nodes, records=oracle.NotReproduced([row], False))
    assert errors_with(result, "no pointer section to s7-tests-not-reproduced.md")
    assert errors_with(result, "no case may use a record before it")
    # With the pointer section (T4), the row covers the assert.
    result = check(nodes=nodes, records=oracle.NotReproduced([row], True))
    assert result["errors"] == []
    assert result["counts"]["not_reproduced"] == 1


@pytest.mark.parametrize(
    ("row", "error"),
    [
        (oracle.Record(DIRECTED, "L108", "x"), "a check cites it and a record has it"),
        (oracle.Record(DIRECTED, "L109", "x"), "a not-reproduced record of L109"),
        (oracle.Record(INTERNAL, "L1180", "x"), "not a converted node"),
    ],
)
def test_a_wrong_record_makes_the_oracle_fail(row, error):
    result = check(records=oracle.NotReproduced([row], True))
    assert errors_with(result, error), result["errors"]


def test_load_not_reproduced(tmp_path):
    harness = tmp_path / "not-reproduced.md"
    harness.write_text("# Checks\n")
    path = tmp_path / "s7-tests-not-reproduced.md"
    head = "# X\n\n## Records\n\n| Node | Assert | Reason |\n|---|---|---|\n"
    path.write_text(
        head + f"| `{DIRECTED}` | `L108` | The text. |\n\n## Other\n| x |\n"
    )
    out = oracle.load_not_reproduced(path, harness)
    assert out.records == [oracle.Record(DIRECTED, "L108", "The text.")]
    assert out.errors == [] and not out.pointer
    harness.write_text("See [x](../docs/decisions/s7-tests-not-reproduced.md).\n")
    path.write_text(head + "| a | b | c |\n")
    out = oracle.load_not_reproduced(path, harness)
    assert out.pointer
    assert out.errors == [f"{path.name}: not a record row: | a | b | c |"]
    path.write_text("# X\n")
    assert oracle.load_not_reproduced(path, harness).errors == [
        f"{path.name}: no '## Records' section"
    ]
    # A load error is an error of the oracle.
    bad = oracle.NotReproduced([], False, ["bad row"])
    assert "bad row" in check(records=bad)["errors"]


# The assert finder.

SOURCE = """
import pytest
from sqlfluff.utils.testing.cli import invoke_assert_code
from sqlfluff.utils.testing.rules import assert_rule_fail_in_sql
from test.helpers import other_helper


def helper(x):
    assert x > 1
    return x


def test_a():
    assert helper(2)
    invoke_assert_code(ret_code=1, args=[], assert_stdout_contains="x")
    invoke_assert_code(0, [], None, None, "", "err")
    with pytest.raises(ValueError):
        int("x")


@pytest.mark.parametrize("p", [1, 2])
def test_param(p):
    invoke_assert_code(args=[])


class TestC:
    def test_m(self):
        pytest.fail("no")


def test_mock(m):
    m.assert_called_once()


def test_imported():
    assert_rule_fail_in_sql("x", "y")


def test_other():
    other_helper()


def test_star(a):
    invoke_assert_code(**a)
"""


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "test" / "a_test.py"
    path.parent.mkdir()
    path.write_text(SOURCE)
    return tmp_path


def _ids(root, node):
    return [a.id for a in asserts.find_asserts(root, f"test/a_test.py::{node}")]


def test_find_asserts(source):
    assert _ids(source, "test_a") == [
        "L9",
        "L14",
        "L15:assert_stdout_contains",
        "L15:ret_code",
        "L16:assert_stderr_contains",
        "L16:ret_code",
        "L17:raises",
    ]
    assert _ids(source, "test_param[1]") == ["L23:ret_code"]
    assert _ids(source, "TestC::test_m") == ["L28:fail"]


@pytest.mark.parametrize(
    ("node", "error"),
    [
        ("test_mock", "assert_called_once is an assert helper that the finder does"),
        ("test_imported", "assert_rule_fail_in_sql is an assert helper"),
        ("test_other", "other_helper comes from the test helper module test.helpers"),
        ("test_star", "invoke_assert_code with *args or **kwargs"),
        ("test_none", "no test function in a_test.py"),
        ("TestD::test_m", "no test function in a_test.py"),
    ],
)
def test_find_asserts_fails_closed(source, node, error):
    with pytest.raises(AssertSourceError, match=error.replace("*", r"\*")):
        asserts.find_asserts(source, f"test/a_test.py::{node}")


def test_the_pilot_asserts():
    ids = [a.id for a in asserts.find_asserts(SQLFLUFF_ROOT, DIRECTED)]
    assert ids == ["L90:ret_code", "L104", "L105", "L108"]
    ids = [a.id for a in asserts.find_asserts(SQLFLUFF_ROOT, INTERNAL)]
    assert ids == ["L1180"]


# The trace step and the oracle with the oracle tools.


def _env(home: Path) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "VIRTUAL_ENV"}
    }
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
    return env


@needs_oracles
def test_oracle_run_is_the_recorded_result(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "oracle"),
            "--out",
            str(tmp_path / "oracle.json"),
            "--check",
            str(RESULTS / "oracle.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert '"agree": 15' in proc.stdout


TREE_TEST = """
import multiprocessing
import os
import subprocess
import sys

import sqlfluff


def test_lint():
    assert sqlfluff.lint("SELECT 1\\n", rules=["CV02"]) == []


def test_lint_and_program():
    assert sqlfluff.lint("SELECT 1\\n", rules=["CV02"]) == []
    subprocess.run(["true"], check=True)


def test_python_child():
    subprocess.run([sys.executable, "-c", "pass"], check=True)


def read(_):
    return 1


def test_spawn_pool():
    with multiprocessing.get_context("spawn").Pool(1) as pool:
        assert pool.map(read, [1]) == [1]


def test_fork():
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)


def test_untraced_cli():
    from sqlfluff.cli.commands import cli

    try:
        cli.main(["version"], standalone_mode=False)
    except SystemExit:
        pass


def test_untraced_api():
    from sqlfluff.api.simple import get_simple_config

    get_simple_config(dialect="ansi")
"""
TREE_MODULE_CALL = """
import sqlfluff

RESULT = sqlfluff.lint("SELECT 1\\n")


def test_x():
    assert isinstance(RESULT, list)
"""


def _lint_node(node_id: str, line: int) -> caseformat.Node:
    case = caseformat.Case(
        name="lint",
        run="api",
        function="lint",
        sql="SELECT 1\n",
        rules=["CV02"],
        checks={"violations": [{"count": 0}]},
    )
    return caseformat.Node(
        node_id, "rules", "x.yml", [case], {f"L{line}": ["lint:violations[0]"]}
    )


@needs_oracles
def test_trace_step_fails_closed(tmp_path):
    root = tmp_path / "root"
    (root / "test").mkdir(parents=True)
    (root / "test" / "tree_test.py").write_text(TREE_TEST)
    (root / "test" / "module_test.py").write_text(TREE_MODULE_CALL)
    name = "test/tree_test.py::"
    nodes = [
        name + n
        for n in (
            "test_lint",
            "test_lint_and_program",
            "test_python_child",
            "test_spawn_pool",
            "test_fork",
            "test_untraced_cli",
            "test_untraced_api",
        )
    ] + ["test/module_test.py::test_x"]
    out = tmp_path / "trace.json"
    python = tools_dir() / "sqlfluff-oracle" / "bin" / "python"
    proc = subprocess.run(
        [
            str(python),
            str(SCRIPTS / "trace-nodes"),
            "--out",
            str(out),
            "--root",
            str(root),
        ]
        + nodes,
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    trace = json.loads(out.read_text())
    traced = trace["nodes"]
    assert {n: traced[n]["outcome"] for n in nodes} == dict.fromkeys(nodes, "passed")

    # The node with only a simple-API call agrees with its case.
    good = oracle.check_node(
        _lint_node(name + "test_lint", 11), traced[name + "test_lint"], "pass", root, []
    )
    assert good.errors == [] and good.trace == "pass"
    # An untraced subprocess: the same call and a program.
    bad = oracle.check_node(
        _lint_node(name + "test_lint_and_program", 15),
        traced[name + "test_lint_and_program"],
        "pass",
        root,
        [],
    )
    assert bad.errors == ["starts a process: program (subprocess.Popen)"]
    # A new Python process, a spawn pool, and a fork.
    child = traced[name + "test_python_child"]["processes"]
    assert child == ["program (subprocess.Popen)", "new Python process"]
    assert "new Python process" in traced[name + "test_spawn_pool"]["processes"]
    assert traced[name + "test_fork"]["processes"] == ["fork"]
    # Untraced calls of the CLI and of the simple API.
    assert traced[name + "test_untraced_cli"]["untraced"] == [
        "a sqlfluff CLI command (Command.main)",
        "the CLI config (get_config)",
    ]
    assert traced[name + "test_untraced_api"]["untraced"] == [
        "the simple-API config (get_simple_config)"
    ]
    # A python-internal node with a traced call.
    assert oracle.check_internal(name + "test_lint", traced[name + "test_lint"])[
        "errors"
    ] == ["class python-internal, but the trace has 1 api calls"]
    for node in ("test_python_child", "test_fork", "test_untraced_cli"):
        assert oracle.check_internal(name + node, traced[name + node])["errors"]
    # A call in the collection is outside the nodes.
    assert len(trace["outside"]["calls"]) == 1
    errors = oracle.trace_errors(trace, "sqlfluff", nodes)
    assert any("1 calls outside the nodes" in e for e in errors), errors


def test_status_file_gives_the_recorded_result():
    status = (REPO_ROOT / "status" / "S7-tests.md").read_text("utf8")
    section = status[status.index("\n## Trace oracle (T3)\n") :]
    for tool in oracle.TOOLS:
        c = RECORDED["tools"][tool]["counts"]
        row = (
            f"| {tool} | {c['nodes']} | {c['agree']} | {c['pass']} | {c['fail']}"
            f" | {c['asserts']} | {c['not_reproduced']} | {c['python_internal']} |"
        )
        assert row in section, row
