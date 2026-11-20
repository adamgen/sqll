"""The S7 trace oracle (docs/decisions/s7-tests-design.md, "Trace oracle").

results/S7-tests/oracle.json must be the check of the recorded traces, and a
new run of the oracle must give it again. Each fail-closed check has a
mutation test: a change of a case, of the trace, of the report, or of the
not-reproduced record that the oracle must refuse. The tests of the trace
step run trace-nodes on a small test tree with the oracle tools.
"""

import copy
import dataclasses
import importlib.machinery
import importlib.util
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
AM09_INTERNAL = (
    "test/rules/std_AM09_test.py"
    "::test__rules__std_AM09_eval_short_circuit_on_non_select_segment"
)
# The python-internal nodes of T7 (convert the rule tests, part 2).
ST06_INTERNAL = (
    "test/rules/std_LT04_ST06_test.py"
    "::test_rule_st06_simple_expression_helpers_reject_non_simple_segments"
)
GLOBAL_CONFIG_INTERNAL = (
    "test/rules/yaml_test_cases_test.py::test__rule_test_global_config"
)
# The python-internal node of T18 (convert the rule tests, part 3, the Jinja
# rule nodes).
JJ01_INTERNAL = "test/rules/std_JJ01_test.py::test_lint_jj01_pickled_config"
EXCLUDE = (
    "test/core/config/fluffconfig_test.py::test__config__glob_exclude_config_tests"
)
CV02 = "test/rules/std_CV02_test.py::test__rules__std_CV02_raised"
LT05 = (
    "test/rules/std_LT05_LT09_combo_test.py::test__rules__std_LT05_LT09_long_line_fix"
)
ST03 = "test/rules/std_ST03_test.py::test__rules__std_ST03_multiple_unused_ctes"
# The proof nodes of T16: a Linter string call with a config, and CLI calls
# with a temporary folder.
LT03 = "test/rules/std_LT03_test.py::test__rules__std_LT03_trailing"
ROUNDTRIP = (
    "test/rules/std_roundtrip_test.py"
    "::test__cli__command__fix[LT01-test/fixtures/linter/whitespace_errors.sql]"
)
# The proof nodes of T17: a Linter made with dialect and rules (2 Linter
# string calls), and an error of RuleSet.get_rulepack in pytest.raises.
KWARGS = next(n.id for n in CASES.nodes if "std_AL09_CP02_RF06[rules0-" in n.id)
REJECTED = (
    "test/rules/std_test.py::test_improper_configs_are_rejected[rule_config_dict3]"
)
# Nodes of T18 (convert the rule tests, part 3, the Jinja rule nodes): a
# Linter string call with the Jinja context and delimiters, simple-API calls
# with the keys of a layout type, and CLI calls in the sqlfluff root with a
# .sqlfluff file in the temporary folder.
JJ01 = "test/rules/std_JJ01_test.py::test_lint_jj01_custom_delimiters"
LT01_JINJA = (
    "test/rules/std_LT01_jinja_alignment_test.py"
    "::test_lt01_alias_alignment_templated_siblings"
)
TEMPLATED = "test/rules/std_roundtrip_test.py::test__cli__command__fix_templated[LT01]"
# Nodes of T8 (Rust dispatch tests cp01, cp03, cp04: classification and
# conversion): an error of FluffConfig.from_string, a spy node, and a mock
# node (python-internal; skipped with no Rust parser).
CP01 = "test/rules/cp01_rust_dispatch_test.py"
RUST_CONFIG_ERROR = f"{CP01}::test__use_rust_rules_requires_rust_parser"
CP01_SPY = f"{CP01}::test__cp01_dispatch__engages_rust_only_when_enabled"
CP01_MOCK = f"{CP01}::test__dispatch__rust_error_is_recoverable"
# Nodes of T22 (convert the rule tests, part 3): a Linter string call with
# fix=True whose violations are not those of a lint run (it maps only to its
# fix case), and an error call with the capitalisation_policy of the
# functions (an extra key of the config model).
FIX_ONLY = next(n.id for n in CASES.nodes if "std_AL09_CP02_RF06[rules3-" in n.id)
REJECTED_FUNCTIONS = (
    "test/rules/std_test.py::test_improper_configs_are_rejected[rule_config_dict7]"
)
FIX_RUN = (
    "the violations of the fix run are not the violations of a lint run; the"
    " lint command cannot show them"
)


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
def test_the_oracle_agrees_with_each_converted_case(tool):
    result = RECORDED["tools"][tool]
    assert result["errors"] == []
    report_ids = [n["id"] for n in REPORT["nodes"]]
    assert [n["id"] for n in result["nodes"]] == report_ids
    assert report_ids == [n.id for n in CASES.nodes]
    # The 15 pilot nodes of T2, the 23 rule nodes of T6, the 2 proof nodes
    # of T16, the 2 proof nodes of T17, the 49 rule nodes of T7, the 15
    # Jinja rule nodes of T18, the 1 Rust dispatch node of T8, and the 5 rule
    # nodes of T22.
    assert result["counts"]["agree"] == result["counts"]["nodes"] == 112
    status = {n["id"]: n["results"][tool]["status"] for n in REPORT["nodes"]}
    for node in result["nodes"]:
        assert node["trace"] == status[node["id"]], node["id"]
        assert node["pytest"] == {"pass": "passed", "fail": "failed"}[node["trace"]]
        assert node["errors"] == []
    # Each assert of the source tests: 223 (97 before T7, 184 before T18,
    # 213 before T8, 214 before T22), each cited by a check.
    assert result["counts"]["asserts"] == 223
    assert result["counts"]["not_reproduced"] == 0
    internal = [e["id"] for e in REPORT["excluded"] if e["class"] == "python-internal"]
    assert [n["id"] for n in result["python_internal"]] == internal
    # The 9 mock and spy nodes of T8: Linter string calls with a
    # unittest.mock patch of sqlfluffrs; with sqlfluff (no Rust parser),
    # each skips.
    rust = [n for n in internal if "_rust_dispatch_test.py::" in n]
    assert len(rust) == 9
    assert [n for n in internal if n not in rust] == [
        INTERNAL,
        AM09_INTERNAL,
        JJ01_INTERNAL,
        ST06_INTERNAL,
        GLOBAL_CONFIG_INTERNAL,
    ]
    for item in result["python_internal"]:
        if item["id"] not in rust:
            assert item["calls"] == {}, item
        elif tool == "sqlfluff":
            assert item["pytest"] == "skipped" and item["calls"] == {}, item
            assert item["skip_reason"] == oracle.RUST_ONLY_SKIP
        else:
            assert item["pytest"] == "passed", item
            assert set(item["calls"]) == {"linter_string"}, item
            assert all(m.startswith("sqlfluffrs.") for m in item["mocks"]), item


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


def test_the_pointer_section_makes_the_record_a_part_of_rule_7():
    # Decision 4: T4 adds the pointer section in harness/not-reproduced.md.
    # No case uses a row yet.
    records = oracle.load_not_reproduced()
    assert records.records == [] and records.errors == []
    assert records.pointer
    assert RECORDED["not_reproduced"] == {"records": 0, "pointer": True}
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


def _config_value(node):
    files = node.cases[0].files
    files[".sqlfluff"] = files[".sqlfluff"].replace("trailing", "leading")


def _file_content(node):
    node.cases[0].files["testing.sql"] += "-- x\n"


def _no_files_check(node):
    node.cases[1].checks.pop("files")


def _kwargs_config(node):
    files = node.cases[0].files
    files[".sqlfluff"] = files[".sqlfluff"].replace("AL09", "CP02")


def _error_config(node):
    files = node.cases[0].files
    files[".sqlfluff"] = files[".sqlfluff"].replace("blah", "upper")


def _jinja_context(node):
    files = node.cases[0].files
    files[".sqlfluff"] = files[".sqlfluff"].replace("foo = bar", "foo = baz")


def _layout_key(node):
    files = node.cases[0].files
    files[".sqlfluff"] = files[".sqlfluff"].replace("bracketed", "select_clause")


def _folder_config(node):
    files = node.cases[0].files
    files[".sqlfluff"] = files[".sqlfluff"].replace("another_table", "a_table")


def _functions_policy(node):
    files = node.cases[0].files
    files[".sqlfluff"] = files[".sqlfluff"].replace(
        "capitalisation.functions", "capitalisation.types"
    )


def _fix_only_stdin(node):
    node.cases[0].stdin = node.cases[0].stdin.replace("I as I", "I")


def _lint_case_of_fix_only(node):
    lint = copy.deepcopy(node.cases[0])
    lint.name, lint.argv = "lint", ["lint", "-f", "json", "-"]
    lint.checks = {"exit_code": 1}
    node.cases.insert(0, lint)


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
    # The maps of T16: a Linter string call with a config (stdin and a
    # .sqlfluff file in a temporary folder), and CLI calls with a temporary
    # folder (the files before and after each call).
    ("config value", LT03, _config_value, "case trailing: input files"),
    (
        "no config file",
        LT03,
        lambda n: n.cases[0].files.clear(),
        "case trailing: input files",
    ),
    (
        "Linter stdin",
        LT03,
        lambda n: setattr(n.cases[0], "stdin", "SELECT 1\n"),
        "case trailing: input stdin",
    ),
    (
        "Linter cwd",
        LT03,
        lambda n: setattr(n.cases[0], "cwd", "sqlfluff"),
        "case trailing: input cwd",
    ),
    ("file content", ROUNDTRIP, _file_content, "case lint_before: input files"),
    (
        "tmp argv",
        ROUNDTRIP,
        lambda n: n.cases[2].argv.__setitem__(-1, "{tmp}/other.sql"),
        "case lint_after: input argv",
    ),
    ("missing files check", ROUNDTRIP, _no_files_check, "check 2"),
    (
        "changed files check",
        ROUNDTRIP,
        lambda n: n.cases[1]
        .checks["files"]
        .update({"testing.sql": n.cases[0].files["testing.sql"]}),
        "check 2",
    ),
    ("Linter exit code", LT03, _checks(["exit_code"], 0), "check 2"),
    (
        "Linter violations",
        LT03,
        _checks(["violations", 0, "select", "code"], "LT04"),
        "check 2",
    ),
    ("a case with no call", CV02, _extra_case, "cases with no traced call"),
    # The maps of T17: a Linter made with dialect and rules, and an error of
    # RuleSet.get_rulepack that the CLI gives.
    ("Linter argument config", KWARGS, _kwargs_config, "case lint: input files"),
    (
        "Linter argument stdin",
        KWARGS,
        lambda n: setattr(n.cases[2], "stdin", n.cases[0].stdin),
        "case lint_fixed: input stdin",
    ),
    (
        "Linter argument fixed SQL",
        KWARGS,
        lambda n: n.cases[1].checks["stdout"].update(equals=n.cases[0].stdin),
        "check 2",
    ),
    (
        "Linter argument violations after the fix",
        KWARGS,
        lambda n: n.cases[2].checks["violations"][0]["records"].pop(),
        "check 2",
    ),
    ("error config", REJECTED, _error_config, "case rejected: input files"),
    (
        "error argv",
        REJECTED,
        lambda n: setattr(n.cases[0], "argv", ["lint", "-f", "json", "-"]),
        "case rejected: input argv",
    ),
    ("error exit code", REJECTED, _checks(["exit_code"], 1), "check 2"),
    (
        "error message",
        REJECTED,
        _checks(["stderr", "contains", 0], "Invalid option 'blah' for allow_scalar"),
        "check 2",
    ),
    (
        "uncited error",
        REJECTED,
        _uncite("L106:raises"),
        "assert L106:raises: no check cites it",
    ),
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
    assert result["counts"]["agree"] == len(CASES.nodes) - 1


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
        "a simple-API call with a config has 0 inner calls",
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
        lambda t: _call(t, EXCLUDE)["inputs"]["linter"].update(user_rules=["X"]),
        "Linter arguments ['user_rules'] other than config, dialect, rules",
    ),
    (
        "a Linter path call with a Linter argument and no proof",
        lambda t: _call(t, EXCLUDE)["inputs"]["linter"].update(dialect="ansi"),
        "a Linter with a config and the arguments ['dialect']",
    ),
    # The maps of T16. Each call that the maps do not know is an error.
    (
        "a config key that the map does not know",
        lambda t: _call(t, LT03)["inputs"].update(
            config_file={
                "error": "core:not_a_key: the map knows only the keys of the"
                " default config"
            }
        ),
        "case trailing: the config of the Linter: core:not_a_key",
    ),
    (
        "a config file that the CLI loads as another config",
        lambda t: _call(t, LT03)["inputs"].update(config_proof=["core:rule_allowlist"]),
        "the keys ['core:rule_allowlist'] are different",
    ),
    (
        "a config that changed after the Linter was made",
        lambda t: _call(t, LT03)["inputs"].update(config_changed=True),
        "the config of the Linter changed after the Linter was made",
    ),
    (
        "an unknown Linter method",
        lambda t: _call(t, LT03)["inputs"].update(method="lint_rendered"),
        "case trailing: the Linter method 'lint_rendered'",
    ),
    (
        "an untraced Linter call",
        lambda t: _node(t, LT03).update(
            untraced_linter=["a Linter parse (Linter.parse_rendered)"]
        ),
        "an untraced Linter call: a Linter parse (Linter.parse_rendered)",
    ),
    (
        "an untraced Linter call outside the nodes",
        lambda t: t["outside"].update(untraced_linter=["a Linter render"]),
        "1 untraced_linter outside the nodes",
    ),
    (
        "a Linter string option",
        lambda t: _call(t, LT03)["inputs"]["options"].update(fname="a.sql"),
        "Linter.lint_string_wrapped option fname='a.sql'",
    ),
    (
        "a Linter string argument",
        lambda t: _call(t, LT03)["inputs"]["linter"].update(formatter="<f>"),
        "case trailing: Linter arguments ['formatter'] other than config, dialect",
    ),
    (
        "a Linter string call in another folder",
        lambda t: _call(t, LT03)["inputs"].update(cwd="/tmp/x"),
        "a Linter string call in the folder /tmp/x",
    ),
    (
        "a carriage return on stdin",
        lambda t: _call(t, LT03)["inputs"].update(sql="SELECT 1\r\n"),
        "the SQL has a carriage return",
    ),
    (
        "a fix run with other violations than a lint run",
        lambda t: _call(t, LT03)["inputs"]["options"].update(fix=True)
        or _call(t, LT03)["outputs"].update(
            fixed="x", lint={"records": [], "violations": 0}
        ),
        "the violations of the fix run are not the violations of a lint run",
    ),
    (
        "a config file in the temporary folder",
        lambda t: _call(t, ROUNDTRIP)["inputs"]["tmp"]["files"].update(
            {".sqlfluff": "[sqlfluff]\n"}
        ),
        "the temporary folder has the config or ignore files ['.sqlfluff']",
    ),
    (
        "a sqlfluff config above the temporary folder",
        lambda t: _call(t, ROUNDTRIP)["inputs"]["tmp"].update(
            outer_config={"core": {"dialect": "ansi"}}
        ),
        "a folder above the temporary folder has a sqlfluff config",
    ),
    (
        "a path in the sqlfluff root with a temporary folder",
        lambda t: _call(t, ROUNDTRIP)["inputs"]["tmp"].update(cwd_paths=["test"]),
        "the arguments ['test'] are paths in the sqlfluff root",
    ),
    (
        "a temporary folder and another working folder",
        lambda t: _call(t, ROUNDTRIP)["inputs"].update(cwd="/x"),
        "a CLI call in the folder /x with a temporary folder",
    ),
    (
        "2 temporary folders",
        lambda t: _call(t, ROUNDTRIP)["inputs"]["unsupported"].append(
            "2 temporary folders"
        ),
        "case lint_before: 2 temporary folders",
    ),
    (
        "a changed file after the call",
        lambda t: _call(t, ROUNDTRIP, 1)["outputs"]["files"].update(
            {"testing.sql": "x"}
        ),
        "check 2",
    ),
    (
        "a Linter path config from overrides that the map does not know",
        lambda t: _call(t, EXCLUDE)["inputs"].update(
            linter={"config": {"method": "FluffConfig", "args": {}}},
            overrides={
                "values": {"templater": "jinja"},
                "extra_config_path": None,
                "ignore_local_config": False,
                "proof": [],
            },
        ),
        "the overrides ['templater']; the map knows only",
    ),
    (
        "a Linter path config that is not its overrides",
        lambda t: _call(t, EXCLUDE)["inputs"].update(
            linter={"config": {"method": "FluffConfig", "args": {}}},
            overrides={
                "values": {"dialect": "ansi"},
                "extra_config_path": None,
                "ignore_local_config": False,
                "proof": ["layout:type:comma:line_position"],
            },
        ),
        "is not FluffConfig(overrides=<its overrides>)",
    ),
    (
        "a Linter path config from overrides gives lint options",
        lambda t: _call(t, EXCLUDE)["inputs"].update(
            linter={"config": {"method": "FluffConfig", "args": {}}},
            overrides={
                "values": {"dialect": "ansi", "rules": "LT01"},
                "extra_config_path": None,
                "ignore_local_config": False,
                "proof": [],
            },
        ),
        "input argv: the case gives ['lint', '-f', 'json', 'test/fixtures",
    ),
    # The maps of T17. Each call that the maps do not know is an error.
    (
        "Linter arguments that are not the overrides",
        lambda t: _call(t, KWARGS)["inputs"]["linter"]["kwargs_config"][
            "values"
        ].update(rules="CP02"),
        "case lint: the Linter arguments {'dialect': 'ansi', 'rules': ['AL09']}"
        " give the overrides",
    ),
    (
        "a Linter argument config that is not its overrides",
        lambda t: _call(t, KWARGS)["inputs"]["linter"]["kwargs_config"].update(
            proof=["core:dialect"]
        ),
        "is not FluffConfig(overrides=<its overrides>)",
    ),
    (
        "Linter arguments with no proof",
        lambda t: _call(t, KWARGS)["inputs"]["linter"].pop("kwargs_config"),
        "case lint: a Linter with the arguments ['dialect', 'rules']: the trace"
        " has no proof of its config",
    ),
    (
        "a Linter rules argument that is not a list",
        lambda t: _call(t, KWARGS, 1)["inputs"]["linter"].update(rules="AL09"),
        "case lint_fixed: the Linter argument rules='AL09'",
    ),
    (
        "an error that the CLI gives as another error",
        lambda t: _call(t, REJECTED)["cli"]["errors"][0].update(error="ValueError"),
        "case rejected: the CLI does not give the same error",
    ),
    (
        "an error that the CLI does not give",
        lambda t: _call(t, REJECTED)["cli"].update(errors=[]),
        "the CLI run gets []",
    ),
    (
        "an error of a function that the map does not know",
        lambda t: _call(t, REJECTED)["inputs"].update(function="FluffConfig"),
        "of FluffConfig; the oracle maps only an error of",
    ),
    (
        "an error with no CLI input",
        lambda t: _call(t, REJECTED).pop("cli")
        and _call(t, REJECTED)["inputs"].update(no_cli_input="the reason"),
        "case rejected: the error",
    ),
    (
        "an error with another CLI output",
        lambda t: _call(t, REJECTED)["cli"].update(exit_code=1),
        "check 2",
    ),
    (
        "an error call in another folder",
        lambda t: _call(t, REJECTED)["inputs"].update(cwd="/tmp/x"),
        "an error call in the folder /tmp/x",
    ),
    (
        "a FluffConfig.from_string error that the CLI gives from another function",
        lambda t: _call(t, RUST_CONFIG_ERROR)["cli"]["errors"][0].update(
            function="FluffConfig.from_string"
        ),
        "case rejected: the CLI does not give the same error",
    ),
    (
        "a FluffConfig.from_string error with no CLI input",
        lambda t: _call(t, RUST_CONFIG_ERROR).pop("cli")
        and _call(t, RUST_CONFIG_ERROR)["inputs"].update(no_cli_input="overrides"),
        "case rejected: the error",
    ),
    (
        "a FluffConfig.from_string error with another config file",
        lambda t: _call(t, RUST_CONFIG_ERROR)["cli"]["files"].update(
            {".sqlfluff": "[sqlfluff]\n"}
        ),
        "case rejected: input files",
    ),
    (
        "python-internal node that skips for another reason",
        lambda t: _node(t, CP01_SPY).update(skip_reason="Skipped: other"),
        "the pytest outcome is skipped",
    ),
    (
        "python-internal node that skips with a traced call",
        lambda t: _node(t, CP01_SPY)["calls"].append(_call(t, LT03)),
        "skipped with",
    ),
    (
        "python-internal node with an error call that maps",
        lambda t: _node(t, INTERNAL)["calls"].append(_call(t, REJECTED)),
        "class python-internal, but the error",
    ),
    (
        "a test helper call with no inner call",
        lambda t: _node(t, CV02)["calls"].__setitem__(
            0,
            {
                "kind": "helper",
                "inputs": {
                    "function": "assert_rule_raises_violations_in_file",
                    "args": {},
                    "cwd": "{sqlfluff}",
                },
                "inner": [],
            },
        ),
        "has 0 inner calls, not 1 call of the kind linter",
    ),
    (
        "a test helper that the map does not know",
        lambda t: _node(t, CV02)["calls"].__setitem__(
            0,
            {
                "kind": "helper",
                "inputs": {"function": "assert_rule_fail_in_sql", "cwd": "{sqlfluff}"},
                "inner": [],
            },
        ),
        "the test helper assert_rule_fail_in_sql; the oracle maps only",
    ),
    (
        "a simple-API config with 2 inner calls",
        lambda t: _call(t, CV02)["inputs"].update(config={"method": "FluffConfig"})
        or _call(t, CV02).update(inner=[_call(t, LT03), _call(t, LT03)]),
        "a simple-API call with a config has 2 inner calls",
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
    # T8: a mock or spy node can have Linter string calls only with a
    # unittest.mock patch, and only sqlfluff (no Rust parser) can skip it.
    for node_id in (CP01_SPY, CP01_MOCK):
        assert _node(TRACES["sqlfluff-rs"], node_id)["mocks"]
        trace = _trace(lambda t, n=node_id: _node(t, n).pop("mocks"), "sqlfluff-rs")
        result = check("sqlfluff-rs", trace=trace)
        assert errors_with(
            result,
            "linter_string calls and the node patches nothing with unittest.mock",
        ), result["errors"]
    skipped = copy.deepcopy(TRACES["sqlfluff"]["nodes"][CP01_SPY])
    assert skipped["outcome"] == "skipped"
    trace = _trace(lambda t: t["nodes"].update({CP01_SPY: skipped}), "sqlfluff-rs")
    result = check("sqlfluff-rs", trace=trace)
    assert errors_with(result, "the pytest outcome is skipped"), result["errors"]


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


# The exit code of scripts/s7-tests/oracle on the 4 checks. The script checks
# the recorded traces (--trace) and does not run the tools.


def _oracle_script():
    loader = importlib.machinery.SourceFileLoader(
        "s7_tests_oracle_script", str(SCRIPTS / "oracle")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _run_oracle(tmp_path, monkeypatch, nodes=None, report=None, trace=None):
    """Run the oracle script on the recorded traces. trace: a changed trace
    of sqlfluff."""
    script = _oracle_script()
    if nodes is not None:
        cases = dataclasses.replace(CASES, nodes=nodes)
        monkeypatch.setattr(script.caseformat, "load", lambda: cases)
    argv = ["--out", str(tmp_path / "oracle.json")]
    for tool in oracle.TOOLS:
        path = RESULTS / f"oracle-trace-{tool}.json"
        if trace is not None and tool == "sqlfluff":
            path = tmp_path / "trace.json"
            path.write_text(json.dumps(trace), encoding="utf8")
        argv += ["--trace", f"{tool}={path}"]
    if report is not None:
        path = tmp_path / "report.json"
        path.write_text(json.dumps(report), encoding="utf8")
        argv += ["--report", str(path)]
    return script.main(argv)


EXIT_MUTATIONS = [
    ("a case input that differs from the trace", DIRECTED, _argv, None, "input argv"),
    (
        "a check that fails on the traced output",
        DIALECT,
        _checks(["exit_code"], 1),
        None,
        "check 2",
    ),
    (
        "a status that differs from the report",
        None,
        None,
        _status(CV02, "fail"),
        "check 3: the report gives fail",
    ),
    (
        "a source assert with no citing check and no record",
        DIRECTED,
        _uncite("L108"),
        None,
        "assert L108: no check cites it and no record has it",
    ),
]


def test_the_oracle_exits_0_on_the_recorded_traces(tmp_path, monkeypatch, capsys):
    assert _run_oracle(tmp_path, monkeypatch) == 0
    assert "error:" not in capsys.readouterr().err
    assert json.loads((tmp_path / "oracle.json").read_text("utf8")) == RECORDED


@pytest.mark.parametrize(
    ("node_id", "change", "report_change", "error"),
    [m[1:] for m in EXIT_MUTATIONS],
    ids=[m[0] for m in EXIT_MUTATIONS],
)
def test_a_failed_check_makes_the_oracle_exit_1(
    tmp_path, monkeypatch, capsys, node_id, change, report_change, error
):
    nodes = None if change is None else _set(node_id, change)
    report = None if report_change is None else _report(report_change)
    assert _run_oracle(tmp_path, monkeypatch, nodes, report) == 1
    errors = [e for e in capsys.readouterr().err.splitlines() if error in e]
    assert errors, error
    assert all(e.startswith("error: ") for e in errors)


# T16: a mutation of each new map (a Linter string call with a config, and
# CLI calls with a temporary folder) gives exit code 1.
MAP_EXIT_MUTATIONS = [
    ("a changed config value", LT03, _config_value, "case trailing: input files"),
    (
        "a changed stdin",
        LT03,
        lambda n: setattr(n.cases[0], "stdin", "SELECT 1\n"),
        "case trailing: input stdin",
    ),
    (
        "a changed file content",
        ROUNDTRIP,
        _file_content,
        "case lint_before: input files",
    ),
    (
        "a missing file check",
        ROUNDTRIP,
        _no_files_check,
        "check 2: the checks on the traced outputs give fail",
    ),
    # T17: a Linter made with dialect and rules, and an error call.
    (
        "a changed config of Linter arguments",
        KWARGS,
        _kwargs_config,
        "case lint: input files",
    ),
    (
        "a changed config of an error call",
        REJECTED,
        _error_config,
        "case rejected: input files",
    ),
    # T18: the Jinja context, the keys of a layout type, and a config file
    # in the temporary folder of a call in the sqlfluff root.
    ("a changed Jinja context", JJ01, _jinja_context, "case lint: input files"),
    ("a changed layout key", LT01_JINJA, _layout_key, "case fix: input files"),
    (
        "a changed config file in the folder",
        TEMPLATED,
        _folder_config,
        "case lint_before: input files",
    ),
    # T22: the capitalisation_policy of the functions, and a fix run with
    # other violations than a lint run (only the fix case: a lint case of the
    # call is an error).
    (
        "a changed rule section of the capitalisation_policy",
        REJECTED_FUNCTIONS,
        _functions_policy,
        "case rejected: input files",
    ),
    (
        "a changed stdin of a fix run with other violations",
        FIX_ONLY,
        _fix_only_stdin,
        "case fix: input stdin",
    ),
    (
        "a lint case of a fix run with other violations",
        FIX_ONLY,
        _lint_case_of_fix_only,
        "case lint: input argv",
    ),
]


@pytest.mark.parametrize(
    ("node_id", "change", "error"),
    [m[1:] for m in MAP_EXIT_MUTATIONS],
    ids=[m[0] for m in MAP_EXIT_MUTATIONS],
)
def test_a_changed_map_case_makes_the_oracle_exit_1(
    tmp_path, monkeypatch, capsys, node_id, change, error
):
    assert _run_oracle(tmp_path, monkeypatch, _set(node_id, change)) == 1
    errors = [e for e in capsys.readouterr().err.splitlines() if error in e]
    # Each tool: sqlfluff and sqlfluff-rs.
    for tool in oracle.TOOLS:
        assert [e for e in errors if e.startswith(f"error: {tool}: {node_id}: ")]
    assert len(errors) == len(oracle.TOOLS), errors


# An unmapped call gives exit code 1 and a message: a config with a key that
# the map does not know (trace-nodes records the error, see
# test_trace_step_maps_the_calls_of_t16), and a Linter method that the
# trace does not map (an untraced Linter render or parse).
UNMAPPED = [
    (
        "a config key that the map does not know",
        lambda t: _call(t, LT03)["inputs"].update(
            config_file={
                "error": "core:not_a_key: the map knows only the keys of the"
                " default config"
            }
        ),
        f"error: sqlfluff: {LT03}: case trailing: the config of the Linter:"
        " core:not_a_key: the map knows only the keys of the default config",
    ),
    (
        "an unknown Linter method",
        lambda t: _node(t, LT03).update(
            untraced_linter=["a Linter render (Linter.render_string)"]
        ),
        f"error: sqlfluff: {LT03}: an untraced Linter call: a Linter render"
        " (Linter.render_string)",
    ),
    # T17: Linter arguments with no proof of the config, and an error that
    # the CLI run does not give.
    (
        "Linter arguments with no proof of the config",
        lambda t: _call(t, KWARGS)["inputs"]["linter"].pop("kwargs_config"),
        f"error: sqlfluff: {KWARGS}: case lint: a Linter with the arguments"
        " ['dialect', 'rules']: the trace has no proof of its config",
    ),
    (
        "an error that the CLI does not give",
        lambda t: _call(t, REJECTED)["cli"].update(errors=[]),
        f"error: sqlfluff: {REJECTED}: case rejected: the CLI does not give the"
        f" same error: the test gets {_call(TRACES['sqlfluff'], REJECTED)['error']!r}"
        " from RuleSet.get_rulepack, the CLI run gets []",
    ),
    # T18: a call in the sqlfluff root with a config file in its temporary
    # folder, with no run in the folder, with an error of that run, and with
    # other outputs of that run.
    (
        "a config file in the folder and no run in the folder",
        lambda t: _call(t, TEMPLATED)["outputs"].pop("cwd_outputs"),
        f"error: sqlfluff: {TEMPLATED}: case lint_before: the temporary folder"
        " has the config or ignore files ['.sqlfluff']; the case runs in the"
        " folder, the call did not, and the trace has no run of the call in the"
        " folder",
    ),
    (
        "a config file in the folder and an error of the run in the folder",
        lambda t: _call(t, TEMPLATED, 1)["outputs"].update(
            cwd_outputs={"error": "OSError: x"}
        ),
        f"error: sqlfluff: {TEMPLATED}: case fix: the temporary folder has the"
        " config or ignore files ['.sqlfluff']; the run of the call in the folder:"
        " OSError: x",
    ),
    (
        "a config file in the folder and other outputs of the run in the folder",
        lambda t: _call(t, TEMPLATED, 2)["outputs"]["cwd_outputs"].update(
            exit_code=1, files={}
        ),
        f"error: sqlfluff: {TEMPLATED}: case lint_after: the temporary folder"
        " has the config or ignore files ['.sqlfluff']; the run of the call in"
        " the folder gives other outputs: ['exit_code', 'files']",
    ),
    # T22: a fix run with other violations than a lint run whose result the
    # node reads in another way than fix_string, with no reads in the trace,
    # or of Linter.lint_string_wrapped; and the capitalisation_policy in a
    # rule section that the map does not know.
    (
        "a read of the violations of a fix run with other violations",
        lambda t: _call(t, FIX_ONLY)["reads"].append("violations"),
        f"error: sqlfluff: {FIX_ONLY}: case fix: {FIX_RUN}, and the node reads"
        " ['violations'] of the result; the map allows only ['fix_string']",
    ),
    (
        "a special method of the result of a fix run with other violations",
        lambda t: _call(t, FIX_ONLY)["reads"].append("__iter__"),
        f"error: sqlfluff: {FIX_ONLY}: case fix: {FIX_RUN}, and the node reads"
        " ['__iter__'] of the result; the map allows only ['fix_string']",
    ),
    (
        "a fix run with other violations and no reads",
        lambda t: _call(t, FIX_ONLY).pop("reads"),
        f"error: sqlfluff: {FIX_ONLY}: case fix: {FIX_RUN}, and the trace has no"
        " reads of the result",
    ),
    (
        "a fix run with other violations of Linter.lint_string_wrapped",
        lambda t: _call(t, FIX_ONLY)["inputs"].update(method="lint_string_wrapped"),
        f"error: sqlfluff: {FIX_ONLY}: case fix: {FIX_RUN}, and the trace watches"
        " the reads only of the result of Linter.lint_string, not of"
        " Linter.lint_string_wrapped",
    ),
    (
        "the capitalisation_policy in another rule section",
        lambda t: _call(t, REJECTED_FUNCTIONS).pop("cli")
        and _call(t, REJECTED_FUNCTIONS)["inputs"].update(
            no_cli_input="the config model: rules:capitalisation.types:"
            "capitalisation_policy: the map knows only the keys of the default"
            " config and the extra keys"
        ),
        f"error: sqlfluff: {REJECTED_FUNCTIONS}: case rejected: the error"
        f" {_call(TRACES['sqlfluff'], REJECTED_FUNCTIONS)['error']!r} of"
        " RuleSet.get_rulepack: the config model:"
        " rules:capitalisation.types:capitalisation_policy: the map knows only"
        " the keys of the default config and the extra keys",
    ),
]


@pytest.mark.parametrize(
    ("change", "error"), [m[1:] for m in UNMAPPED], ids=[m[0] for m in UNMAPPED]
)
def test_an_unmapped_call_makes_the_oracle_exit_1(
    tmp_path, monkeypatch, capsys, change, error
):
    assert _run_oracle(tmp_path, monkeypatch, trace=_trace(change)) == 1
    assert error in capsys.readouterr().err.splitlines()


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
    # A mention of the file name is not a pointer section.
    harness.write_text("# Checks\n\ns7-tests-not-reproduced.md\n")
    assert not oracle.load_not_reproduced(path, harness).pointer
    # A link in another section is not a pointer section.
    link = "See [x](../docs/decisions/s7-tests-not-reproduced.md).\n"
    harness.write_text("# Checks\n\n## Other\n\n" + link)
    assert not oracle.load_not_reproduced(path, harness).pointer
    harness.write_text(f"# Checks\n\n{oracle.POINTER_SECTION}\n\n{link}\n## Next\n")
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


# T17: the test helper assert_rule_raises_violations_in_file of
# sqlfluff.utils.testing.rules has one check (one id). Each other helper of
# that module, and a helper of that name from another module, is refused.
HELPER_SOURCE = """
from sqlfluff.utils.testing.rules import assert_rule_raises_violations_in_file
from sqlfluff.utils.testing.rules import load_test_cases


def test_file():
    assert_rule_raises_violations_in_file("LT01", "a.sql", [(1, 2)], None)


def test_keywords():
    assert_rule_raises_violations_in_file(
        rule="LT01", fpath="a.sql", violations=[], fluff_config=None
    )


def test_load():
    load_test_cases("x")
"""
OTHER_HELPER_SOURCE = """
from test.helpers import assert_rule_raises_violations_in_file


def test_file():
    assert_rule_raises_violations_in_file("LT01", "a.sql", [], None)
"""


def test_find_asserts_of_the_rule_test_helper(tmp_path):
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "a_test.py").write_text(HELPER_SOURCE)
    (tmp_path / "test" / "b_test.py").write_text(OTHER_HELPER_SOURCE)
    assert _ids(tmp_path, "test_file") == ["L7:violations"]
    assert _ids(tmp_path, "test_keywords") == ["L11:violations"]
    with pytest.raises(AssertSourceError, match="load_test_cases comes from the"):
        asserts.find_asserts(tmp_path, "test/a_test.py::test_load")
    with pytest.raises(AssertSourceError, match="is not the helper of sqlfluff"):
        asserts.find_asserts(tmp_path, "test/b_test.py::test_file")
    node = (
        "test/rules/std_test.py"
        "::test__rules__std_file[LT01-indentation_errors.sql-violations0]"
    )
    ids = [a.id for a in asserts.find_asserts(SQLFLUFF_ROOT, node)]
    assert ids == ["L80:violations"]
    ids = [a.id for a in asserts.find_asserts(SQLFLUFF_ROOT, REJECTED)]
    assert ids == ["L106:raises"]


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
    assert f'"agree": {len(CASES.nodes)}' in proc.stdout


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


import pytest


@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown")


def test_teardown_error(broken_teardown):
    assert sqlfluff.lint("SELECT 2\\n", rules=["CV02"]) == []
"""
TREE_MODULE_CALL = """
import sqlfluff

RESULT = sqlfluff.lint("SELECT 1\\n")


def test_x():
    assert isinstance(RESULT, list)
"""


def _lint_node(node_id: str, line: int, sql: str = "SELECT 1\n") -> caseformat.Node:
    case = caseformat.Case(
        name="lint",
        run="api",
        function="lint",
        sql=sql,
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
    teardown = name + "test_teardown_error"
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
        + nodes
        + [teardown],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    trace = json.loads(out.read_text())
    traced = trace["nodes"]
    assert {n: traced[n]["outcome"] for n in nodes} == dict.fromkeys(nodes, "passed")

    # The call passes and the teardown fails: pytest gives an error, and the
    # oracle refuses the node.
    assert traced[teardown]["outcome"] == "error"
    line = next(
        i for i, text in enumerate(TREE_TEST.splitlines(), 1) if "SELECT 2" in text
    )
    bad = oracle.check_node(
        _lint_node(teardown, line, "SELECT 2\n"), traced[teardown], "pass", root, []
    )
    assert bad.errors == ["the pytest outcome is error"]
    assert oracle.check_internal(teardown, traced[teardown])["errors"]

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


# T16: the trace step and the oracle on the new maps, with the oracle tools.

TREE_MAPS = """
import os
import tempfile

import sqlfluff
from click.testing import CliRunner
from sqlfluff.cli.commands import lint
from sqlfluff.core import FluffConfig, Linter

SQL = "SELECT a  FROM b\\n"
FIXED = "SELECT a FROM b\\n"


def config():
    return FluffConfig(
        configs={"indentation": {"tab_space_size": 2}},
        overrides={"dialect": "ansi", "rules": "LT01"},
    )


def write(folder, name, text):
    with open(os.path.join(folder, name), "w") as f:
        f.write(text)


def test_string_lint():
    result = Linter(config=config()).lint_string(SQL)
    assert [v.rule_code() for v in result.violations] == ["LT01"]


def test_string_fix():
    cfg = FluffConfig.from_kwargs(dialect="ansi", rules=["LT01"])
    cfg.set_value(["rules", "layout.long_lines", "ignore_comment_lines"], True)
    result = Linter(config=cfg).lint_string(SQL, fix=True)
    assert len(result.violations) == 1
    assert result.fix_string()[0] == FIXED


def test_api_lint():
    assert len(sqlfluff.lint(SQL, config=config(), rules=["CV02"])) == 1


def test_api_fix():
    assert sqlfluff.fix(SQL, config=config()) == FIXED


def test_path_overrides():
    cfg = FluffConfig(overrides={"dialect": "ansi", "rules": "LT01"})
    assert len(Linter(config=cfg).lint_path("test/a.sql").check_tuples()) == 1


def test_tmp_file():
    folder = tempfile.mkdtemp()
    write(folder, "a.sql", SQL)
    args = ["--dialect=ansi", "--rules", "LT01", os.path.join(folder, "a.sql")]
    assert CliRunner().invoke(lint, args).exit_code == 1


def test_tmp_path_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, ".sqlfluff", "[sqlfluff]\\ndialect = ansi\\n")
    write(tmp_path, "a.sql", SQL)
    assert CliRunner().invoke(lint, ["--rules", "LT01", "a.sql"]).exit_code == 1


def test_tmp_config():
    folder = tempfile.mkdtemp()
    write(folder, ".sqlfluff", "[sqlfluff]\\ndialect = ansi\\n")
    write(folder, "a.sql", SQL)
    args = ["--rules", "LT01", os.path.join(folder, "a.sql")]
    assert CliRunner().invoke(lint, args).exit_code == 1


def test_set_core():
    cfg = FluffConfig(overrides={"dialect": "ansi"})
    cfg.set_value(["core", "rules"], "LT01")
    assert Linter(config=cfg).lint_string(SQL).violations


def test_unknown_key():
    cfg = config()
    cfg._configs["core"]["not_a_key"] = 1
    assert Linter(config=cfg).lint_string(SQL).violations


def test_not_a_scalar():
    cfg = config()
    cfg._configs["core"]["sql_file_exts"] = [".sql"]
    assert Linter(config=cfg).lint_string(SQL).violations


def test_changed_after_linter():
    cfg = config()
    linter = Linter(config=cfg)
    cfg.set_value(["indentation", "tab_space_size"], 8)
    assert linter.lint_string(SQL).violations


def test_parse_string():
    assert Linter(config=config()).parse_string(SQL).tree
"""
TREE_SQL = "SELECT a  FROM b\n"
TREE_FIXED = "SELECT a FROM b\n"
TREE_CONFIG = (
    "[sqlfluff]\ndialect = ansi\nrules = LT01\n\n"
    "[sqlfluff:indentation]\ntab_space_size = 2\n"
)


def _cli_case(name, argv, exit_code, **inputs):
    checks = {"exit_code": exit_code, **inputs.pop("checks", {})}
    return caseformat.Case(name=name, run="cli", argv=argv, checks=checks, **inputs)


def _tree_node(root, node_id, cases):
    """A node that cites each assert of its source test with a check of its
    first case (check 4)."""
    ids = [a.id for a in asserts.find_asserts(root, node_id)]
    cite = {aid: [f"{cases[0].name}:exit_code"] for aid in ids}
    return caseformat.Node(node_id, "rules", "x.yml", cases, cite)


def _stdin_case(name, argv, exit_code, config, **checks):
    return _cli_case(
        name,
        argv,
        exit_code,
        stdin=TREE_SQL,
        cwd="tmp",
        files={".sqlfluff": config},
        checks=checks,
    )


@needs_oracles
def test_trace_step_maps_the_calls_of_t16(tmp_path):
    root = tmp_path / "root"
    (root / "test").mkdir(parents=True)
    (root / "test" / "maps_test.py").write_text(TREE_MAPS)
    (root / "test" / "a.sql").write_text(TREE_SQL)
    name = "test/maps_test.py::"
    names = [
        line[4:].split("(")[0]
        for line in TREE_MAPS.splitlines()
        if line.startswith("def test_")
    ]
    out = tmp_path / "trace.json"
    python = tools_dir() / "sqlfluff-oracle" / "bin" / "python"
    proc = subprocess.run(
        [str(python), str(SCRIPTS / "trace-nodes"), "--out", str(out)]
        + ["--root", str(root)]
        + [name + n for n in names],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    trace = json.loads(out.read_text())
    traced = trace["nodes"]
    assert {n: traced[name + n]["outcome"] for n in names} == dict.fromkeys(
        names, "passed"
    )
    assert oracle.trace_errors(trace, "sqlfluff", [name + n for n in names]) == []
    lint_stdin = ["lint", "-f", "json", "-"]
    one = {"violations": [{"select": {"code": "LT01"}, "count": 1}]}
    fix_config = (
        "[sqlfluff]\ndialect = ansi\nrules = LT01\n\n"
        "[sqlfluff:rules:layout.long_lines]\nignore_comment_lines = 1\n"
    )
    good = {
        # A Linter string call: lint on stdin with the .sqlfluff file.
        "test_string_lint": [_stdin_case("lint", lint_stdin, 1, TREE_CONFIG, **one)],
        # With fix: 2 cases. set_value(True) stores 1 (coerce_value), and
        # the file gives 1.
        "test_string_fix": [
            _stdin_case("lint", lint_stdin, 1, fix_config, **one),
            _stdin_case(
                "fix", ["fix", "-"], 0, fix_config, stdout={"equals": TREE_FIXED}
            ),
        ],
        # A simple-API call with a config: sqlfluff uses only the config.
        "test_api_lint": [_stdin_case("lint", lint_stdin, 1, TREE_CONFIG, **one)],
        "test_api_fix": [
            _stdin_case(
                "fix", ["fix", "-"], 0, TREE_CONFIG, stdout={"equals": TREE_FIXED}
            )
        ],
        # A Linter path call with a config from overrides: lint options.
        "test_path_overrides": [
            _cli_case(
                "lint",
                ["lint", "-f", "json", "--dialect", "ansi", "--rules", "LT01"]
                + ["test/a.sql"],
                1,
                checks=one,
            )
        ],
        # A temporary folder in an argument, and as the working folder.
        "test_tmp_file": [
            _cli_case(
                "lint",
                ["lint", "--dialect=ansi", "--rules", "LT01", "{tmp}/a.sql"],
                1,
                cwd="tmp",
                files={"a.sql": TREE_SQL},
            )
        ],
        "test_tmp_path_cwd": [
            _cli_case(
                "lint",
                ["lint", "--rules", "LT01", "a.sql"],
                1,
                cwd="tmp",
                files={".sqlfluff": "[sqlfluff]\ndialect = ansi\n", "a.sql": TREE_SQL},
            )
        ],
        # A config file in the temporary folder of a call in the sqlfluff
        # root (T18): the run of the call in the folder gives the same
        # outputs. test_trace_step_maps_the_calls_of_t18 has the refusal.
        "test_tmp_config": [
            _cli_case(
                "lint",
                ["lint", "--rules", "LT01", "{tmp}/a.sql"],
                1,
                cwd="tmp",
                files={".sqlfluff": "[sqlfluff]\ndialect = ansi\n", "a.sql": TREE_SQL},
            )
        ],
    }
    for test, cases in good.items():
        node = _tree_node(root, name + test, cases)
        result = oracle.check_node(node, traced[name + test], "pass", root, [])
        assert result.errors == [] and result.trace == "pass", (test, result.errors)
    data = traced[name + "test_path_overrides"]["calls"][0]["inputs"]["overrides"]
    assert data["values"] == {"dialect": "ansi", "rules": "LT01"}
    assert data["proof"] == []

    # Mutations: a changed config value and a changed stdin.
    node = _tree_node(root, name + "test_string_lint", good["test_string_lint"])
    node.cases[0].files[".sqlfluff"] = TREE_CONFIG.replace("= 2", "= 3")
    errors = oracle.check_node(
        node, traced[name + "test_string_lint"], "pass", root, []
    ).errors
    assert any("case lint: input files" in e for e in errors), errors
    node.cases[0].files[".sqlfluff"] = TREE_CONFIG
    node.cases[0].stdin = "SELECT 1\n"
    errors = oracle.check_node(
        node, traced[name + "test_string_lint"], "pass", root, []
    ).errors
    assert any("case lint: input stdin" in e for e in errors), errors

    # The calls that the maps do not know: each is an error with a message.
    refused = {
        "test_set_core": "the keys ['core:rule_allowlist'] are different",
        "test_unknown_key": (
            "the config of the Linter: core:not_a_key: the map knows only the"
            " keys of the default config"
        ),
        "test_not_a_scalar": "core:sql_file_exts: the value ['.sql'] is not a scalar",
        "test_changed_after_linter": "changed after the Linter was made",
        "test_parse_string": "an untraced Linter call: a Linter render",
    }
    for test, error in refused.items():
        node = _tree_node(root, name + test, [_cli_case("lint", ["lint"], 0)])
        errors = oracle.check_node(node, traced[name + test], "pass", root, []).errors
        assert any(error in e for e in errors), (test, errors)
    # parse_string is also a parse.
    assert traced[name + "test_parse_string"]["untraced_linter"] == [
        "a Linter render (Linter.render_string)",
        "a Linter parse (Linter.parse_rendered)",
    ]


# T17: the trace step and the oracle on the maps of T17, with the oracle
# tools: a Linter made with dialect, rules, and exclude_rules; the test helper
# assert_rule_raises_violations_in_file; and an error in pytest.raises that
# the CLI gives (an error call). Each call that the maps do not know is an
# error with a message.

TREE_T17 = """
import pytest
from sqlfluff.core import FluffConfig, Linter
from sqlfluff.core.rules import get_ruleset
from sqlfluff.utils.testing.rules import assert_rule_raises_violations_in_file

SQL = "SELECT a  FROM b\\n"
FIXED = "SELECT a FROM b\\n"


def test_kwargs_string():
    linter = Linter(dialect="ansi", rules=["LT01"])
    assert linter.lint_string(SQL, fix=True).fix_string()[0] == FIXED


def test_kwargs_path():
    linter = Linter(dialect="ansi", rules=["LT01"], exclude_rules=["LT02"])
    assert len(linter.lint_path("test/a.sql").check_tuples()) == 1


def test_helper():
    assert_rule_raises_violations_in_file(
        rule="LT01",
        fpath="test/a.sql",
        violations=[(1, 9)],
        fluff_config=FluffConfig(overrides={"dialect": "ansi", "rules": "LT01"}),
    )


def test_rulepack_error():
    config = FluffConfig(
        configs={"rules": {"allow_scalar": "blah"}}, overrides={"dialect": "ansi"}
    )
    with pytest.raises(ValueError):
        get_ruleset().get_rulepack(config)


def test_helper_fails():
    assert_rule_raises_violations_in_file(
        rule="LT01",
        fpath="test/a.sql",
        violations=[(1, 10)],
        fluff_config=FluffConfig(overrides={"dialect": "ansi", "rules": "LT01"}),
    )


def test_kwargs_other_argument():
    assert Linter(dialect="ansi", rules=["LT01"], user_rules=[]).lint_string(SQL)


def test_linter_error():
    with pytest.raises(KeyError):
        Linter(dialect="not_a_dialect")


def test_config_error():
    with pytest.raises(ValueError):
        FluffConfig(configs={"core": {"templater": "nope"}})


def test_rulepack_error_unknown_key():
    # T22 maps capitalisation_policy only in capitalisation.functions.
    config = FluffConfig(
        configs={"rules": {"capitalisation.types": {"capitalisation_policy": "x"}}},
        overrides={"dialect": "ansi"},
    )
    with pytest.raises(ValueError):
        get_ruleset().get_rulepack(config)


def test_no_cli_state_after_the_error_calls():
    # The trace runs the CLI for the error calls above; the test must not
    # see it (limit 5 of the design record).
    import logging

    import colorama.initialise

    logger = logging.getLogger("sqlfluff")
    assert logger.propagate and logger.handlers == []
    assert colorama.initialise.wrapped_stdout is None
    assert not colorama.initialise.atexit_done
"""
T17_CONFIG = "[sqlfluff]\ndialect = ansi\nrules = LT01\n"
T17_ERROR_CONFIG = (
    "[sqlfluff]\ndialect = ansi\n\n[sqlfluff:rules]\nallow_scalar = blah\n"
)
T17_LT01 = {
    "violations": [
        {"records": [{"code": "LT01", "start_line_no": 1, "start_line_pos": 9}]}
    ]
}
T17_PATH_ARGV = ["lint", "-f", "json", "--dialect", "ansi", "--rules", "LT01"]


def _t17_good() -> dict[str, list[caseformat.Case]]:
    return {
        # A Linter string call of a Linter with dialect and rules: the
        # config model of its config (FluffConfig(overrides=...)).
        "test_kwargs_string": [
            _stdin_case("lint", ["lint", "-f", "json", "-"], 1, T17_CONFIG, **T17_LT01),
            _stdin_case(
                "fix", ["fix", "-"], 0, T17_CONFIG, stdout={"equals": TREE_FIXED}
            ),
        ],
        # A Linter path call of such a Linter: the overrides as lint options.
        "test_kwargs_path": [
            _cli_case(
                "lint",
                [*T17_PATH_ARGV, "--exclude-rules", "LT02", "test/a.sql"],
                1,
                checks=T17_LT01,
            )
        ],
        # The test helper: the case of its one Linter path call.
        "test_helper": [
            _cli_case("lint", [*T17_PATH_ARGV, "test/a.sql"], 1, checks=T17_LT01)
        ],
        # An error of RuleSet.get_rulepack that the CLI gives.
        "test_rulepack_error": [
            _cli_case(
                "rejected",
                ["lint", "-"],
                2,
                cwd="tmp",
                files={".sqlfluff": T17_ERROR_CONFIG},
                checks={
                    "stderr": {
                        "contains": [
                            "User Error: Invalid option 'blah' for allow_scalar"
                        ]
                    }
                },
            )
        ],
    }


def _t17_trace(tmp_path) -> tuple[Path, str, dict]:
    root = tmp_path / "root"
    (root / "test").mkdir(parents=True)
    (root / "test" / "t17_test.py").write_text(TREE_T17)
    (root / "test" / "a.sql").write_text(TREE_SQL)
    name = "test/t17_test.py::"
    names = [
        line[4:].split("(")[0]
        for line in TREE_T17.splitlines()
        if line.startswith("def test_")
    ]
    out = tmp_path / "trace.json"
    python = tools_dir() / "sqlfluff-oracle" / "bin" / "python"
    proc = subprocess.run(
        [str(python), str(SCRIPTS / "trace-nodes"), "--out", str(out)]
        + ["--root", str(root)]
        + [name + n for n in names],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    trace = json.loads(out.read_text())
    outcomes = {n: trace["nodes"][name + n]["outcome"] for n in names}
    want = dict.fromkeys(names, "passed")
    want["test_helper_fails"] = "failed"
    assert outcomes == want
    assert oracle.trace_errors(trace, "sqlfluff", [name + n for n in names]) == []
    return root, name, trace


@needs_oracles
def test_trace_step_maps_the_calls_of_t17(tmp_path):
    root, name, trace = _t17_trace(tmp_path)
    traced = trace["nodes"]
    good = _t17_good()
    for test, cases in good.items():
        node = _tree_node(root, name + test, cases)
        result = oracle.check_node(node, traced[name + test], "pass", root, [])
        assert result.errors == [] and result.trace == "pass", (test, result.errors)
    # The proof of each map in the trace.
    linter = traced[name + "test_kwargs_string"]["calls"][0]["inputs"]["linter"]
    assert linter["kwargs_config"]["values"] == {"dialect": "ansi", "rules": "LT01"}
    assert linter["kwargs_config"]["proof"] == []
    helper = traced[name + "test_helper"]["calls"]
    assert [c["kind"] for c in helper] == ["helper"]
    assert [c["kind"] for c in helper[0]["inner"]] == ["linter"]
    error = traced[name + "test_rulepack_error"]["calls"][0]
    assert error["kind"] == "error"
    assert error["cli"]["errors"] == [
        {"function": "RuleSet.get_rulepack", "error": error["error"]}
    ]
    assert error["error"].startswith("SQLFluffUserError: Invalid option 'blah'")
    # An error call that maps is not python-internal.
    errors = oracle.check_internal(
        name + "test_rulepack_error", traced[name + "test_rulepack_error"]
    )["errors"]
    assert errors == [
        f"class python-internal, but the error {error['error']!r} of"
        " RuleSet.get_rulepack maps to a CLI case"
    ]
    # The helper raised: its case passes on the traced output, pytest gives
    # failed (check 2).
    node = _tree_node(root, name + "test_helper_fails", good["test_helper"])
    errors = oracle.check_node(
        node, traced[name + "test_helper_fails"], "fail", root, []
    ).errors
    assert errors == [
        "check 2: the checks on the traced outputs give pass, pytest gives failed"
    ]

    # The calls that the maps do not know: each is an error with a message.
    refused = {
        "test_kwargs_other_argument": "case lint: Linter arguments ['user_rules']"
        " other than config, dialect, rules, and exclude_rules",
        "test_linter_error": "case lint: the CLI does not give the same error: the"
        " test gets \"KeyError: 'Unknown dialect'\" from Linter, the CLI run gets []",
        "test_config_error": "of FluffConfig; the oracle maps only an error of"
        " ['RuleSet.get_rulepack', 'Linter', 'FluffConfig.from_string']",
        "test_rulepack_error_unknown_key": "the config model:"
        " rules:capitalisation.types:capitalisation_policy: the map knows only"
        " the keys of the default config",
    }
    for test, error in refused.items():
        node = _tree_node(root, name + test, [_cli_case("lint", ["lint"], 0)])
        errors = oracle.check_node(node, traced[name + test], "pass", root, []).errors
        assert any(error in e for e in errors), (test, errors)
    # The refusals of the helper map, on changed copies of the traced helper
    # call: an inner call that is not the call of the helper arguments
    # (method, path, or config), a call in another folder, and a helper that
    # raised before its inner call.
    helper_data = traced[name + "test_helper"]
    not_the_call = (
        "case lint: the inner Linter call is not the call of the helper"
        " assert_rule_raises_violations_in_file"
    )
    helper_refused = [
        (
            lambda c: c["inner"][0]["inputs"].update(method="lint_paths"),
            not_the_call,
        ),
        (
            lambda c: c["inner"][0]["inputs"].update(paths=["test/b.sql"]),
            not_the_call,
        ),
        (
            lambda c: c["inputs"]["args"].update(fluff_config={"method": "other"}),
            not_the_call,
        ),
        (
            lambda c: c["inputs"].update(cwd="/tmp/x"),
            "case lint: a test helper call in the folder /tmp/x",
        ),
        (
            lambda c: c.update(raised="AssertionError: x", inner=[]),
            "case lint: the test helper assert_rule_raises_violations_in_file"
            " raised AssertionError: x",
        ),
    ]
    for change, error in helper_refused:
        call = copy.deepcopy(helper_data["calls"][0])
        change(call)
        node = _tree_node(root, name + "test_helper", good["test_helper"])
        data = {**helper_data, "calls": [call]}
        errors = oracle.check_node(node, data, "pass", root, []).errors
        assert error in errors, (error, errors)
    config_error = traced[name + "test_config_error"]["calls"][0]["inputs"]
    assert config_error["no_cli_input"].startswith("the FluffConfig construction")
    # The CLI run of the Linter error gave exit code 2 with no Linter error.
    linter_error = traced[name + "test_linter_error"]["calls"][0]["cli"]
    assert linter_error["argv"] == ["lint", "--dialect", "not_a_dialect", "-"]
    assert linter_error["exit_code"] == 2 and linter_error["errors"] == []


def _run_tree_oracle(monkeypatch, tmp_path, root, trace, nodes) -> int:
    """Run scripts/s7-tests/oracle on a trace of the test tree, for the tool
    sqlfluff, with these case nodes (each one passes in the report)."""
    script = _oracle_script()
    cases = dataclasses.replace(CASES, nodes=nodes)
    monkeypatch.setattr(script.caseformat, "load", lambda: cases)
    monkeypatch.setattr(script, "SQLFLUFF_ROOT", root)
    monkeypatch.setattr(script, "sqlfluff_ref", lambda _: caseformat.SQLFLUFF_COMMIT)
    ids = {n.id for n in nodes}
    trace = {**trace, "nodes": {k: v for k, v in trace["nodes"].items() if k in ids}}
    trace_path = tmp_path / "tree-trace.json"
    trace_path.write_text(json.dumps(trace), encoding="utf8")
    report = {
        "nodes": [
            {"id": n.id, "results": {"sqlfluff": {"status": "pass"}}} for n in nodes
        ],
        "excluded": [],
    }
    report_path = tmp_path / "tree-report.json"
    report_path.write_text(json.dumps(report), encoding="utf8")
    argv = ["--tool", "sqlfluff", "--trace", f"sqlfluff={trace_path}"]
    argv += ["--report", str(report_path), "--out", str(tmp_path / "oracle.json")]
    return script.main(argv)


def _t17_files(case):
    case.files[".sqlfluff"] = case.files[".sqlfluff"].replace("LT01", "LT02")


# A changed input of each map of T17 gives exit code 1 with a message.
T17_EXIT_MUTATIONS = [
    ("Linter arguments", "test_kwargs_string", 0, _t17_files, "case lint: input files"),
    (
        "Linter arguments in a path call",
        "test_kwargs_path",
        0,
        lambda c: c.argv.remove("--exclude-rules"),
        "case lint: input argv",
    ),
    (
        "test helper",
        "test_helper",
        0,
        lambda c: c.argv.__setitem__(-1, "test/b.sql"),
        "case lint: input argv",
    ),
    (
        "error call",
        "test_rulepack_error",
        0,
        lambda c: setattr(c, "stdin", "SELECT 1\n"),
        "case rejected: input stdin",
    ),
]


@needs_oracles
def test_a_changed_input_of_each_t17_map_makes_the_oracle_exit_1(
    tmp_path, monkeypatch, capsys
):
    root, name, trace = _t17_trace(tmp_path)
    good = _t17_good()

    def nodes():
        return [_tree_node(root, name + t, copy.deepcopy(c)) for t, c in good.items()]

    assert _run_tree_oracle(monkeypatch, tmp_path, root, trace, nodes()) == 0
    out = capsys.readouterr()
    assert "error:" not in out.err
    assert f'"agree": {len(good)}' in out.out
    for _, test, index, change, error in T17_EXIT_MUTATIONS:
        changed = nodes()
        node = next(n for n in changed if n.id == name + test)
        change(node.cases[index])
        assert _run_tree_oracle(monkeypatch, tmp_path, root, trace, changed) == 1
        lines = capsys.readouterr().err.splitlines()
        assert f"error: sqlfluff: {name}{test}: {error}" in "\n".join(lines), lines


# T18 (convert the rule tests, part 3, the Jinja rule nodes): the trace step
# and the oracle on the extra keys of the config model (the Jinja context and
# delimiters, the keys of a layout type) and on a config file in the
# temporary folder of a CLI call in the sqlfluff root, with the oracle tools.
# Each call that the maps do not know is an error with a message.

TREE_T18 = """
import os
import tempfile

import sqlfluff
from click.testing import CliRunner
from sqlfluff.cli.commands import fix, lint
from sqlfluff.core import FluffConfig, Linter

SQL = "SELECT {{ x }}  FROM b\\n"
FIXED = "SELECT {{ x }} FROM b\\n"
ALIGN = "select\\n    {{ x }} as a,\\n    bbbbbbbb as b\\n"
ALIGNED = "select\\n    {{ x }}  as a,\\n    bbbbbbbb as b\\n"


def write(folder, name, text):
    with open(os.path.join(folder, name), "w") as f:
        f.write(text)


def layout(cfg):
    cfg._configs.setdefault("layout", {}).setdefault("type", {}).setdefault(
        "alias_expression", {}
    ).update(
        {
            "spacing_before": "align",
            "align_within": "select_clause",
            "align_scope": "bracketed",
        }
    )
    return cfg


def test_jinja_string():
    config = FluffConfig.from_string(
        "[sqlfluff]\\ndialect = ansi\\nrules = JJ01\\n"
        "[sqlfluff:templater:jinja]\\n"
        "variable_start_string = <%\\nvariable_end_string = %>\\n"
        "[sqlfluff:templater:jinja:context]\\nfoo = bar\\n"
    )
    result = Linter(config=config).lint_string("SELECT <%foo%>\\n")
    assert [v.rule_code() for v in result.violations] == ["JJ01"]


def test_layout_api_fix():
    cfg = layout(FluffConfig.from_kwargs(dialect="ansi", rules=["LT01"]))
    cfg._configs["templater"]["jinja"].setdefault("context", {})["x"] = "a"
    assert sqlfluff.fix(ALIGN, config=cfg) == ALIGNED


def test_tmp_config_root():
    folder = tempfile.mkdtemp()
    write(folder, ".sqlfluff", "[sqlfluff:templater:jinja:context]\\nx = a\\n")
    write(folder, "a.sql", SQL)
    path = os.path.join(folder, "a.sql")
    args = ["--dialect=ansi", "--rules", "LT01", path]
    assert CliRunner().invoke(lint, args).exit_code == 1
    assert CliRunner().invoke(fix, args).exit_code == 0
    with open(path) as f:
        assert f.read() == FIXED


def test_tmp_config_root_other_outputs():
    folder = tempfile.mkdtemp()
    write(folder, ".sqlfluff", "[sqlfluff]\\noutput_line_length = 30\\n")
    write(folder, "a.sql", SQL)
    args = ["--dialect=ansi", "--rules", "LT01", os.path.join(folder, "a.sql")]
    assert CliRunner().invoke(lint, args).exit_code == 1


def test_function_in_context():
    cfg = FluffConfig.from_kwargs(dialect="ansi", rules=["LT01"])
    cfg._configs["templater"]["jinja"].setdefault("context", {})["x"] = lambda: "a"
    assert sqlfluff.lint(SQL, config=cfg)


def test_other_jinja_key():
    cfg = FluffConfig.from_kwargs(dialect="ansi", rules=["LT01"])
    cfg._configs["templater"]["jinja"]["not_a_key"] = "a"
    assert sqlfluff.lint(SQL, config=cfg)
"""
TREE_T18_SQL = "SELECT {{ x }}  FROM b\n"
TREE_T18_FIXED = "SELECT {{ x }} FROM b\n"
TREE_T18_ALIGN = "select\n    {{ x }} as a,\n    bbbbbbbb as b\n"
TREE_T18_ALIGNED = "select\n    {{ x }}  as a,\n    bbbbbbbb as b\n"
TREE_T18_LAYOUT = (
    "[sqlfluff]\ndialect = ansi\nrules = LT01\n\n"
    "[sqlfluff:layout:type:alias_expression]\nalign_scope = bracketed\n"
    "align_within = select_clause\nspacing_before = align\n\n"
    "[sqlfluff:templater:jinja:context]\nx = a\n"
)
TREE_T18_JINJA = (
    "[sqlfluff]\ndialect = ansi\nrules = JJ01\n\n"
    "[sqlfluff:templater:jinja]\nvariable_end_string = %>\n"
    "variable_start_string = <%\n\n"
    "[sqlfluff:templater:jinja:context]\nfoo = bar\n"
)


@needs_oracles
def test_trace_step_maps_the_calls_of_t18(tmp_path):
    root = tmp_path / "root"
    (root / "test").mkdir(parents=True)
    (root / "test" / "t18_test.py").write_text(TREE_T18)
    name = "test/t18_test.py::"
    names = [
        line[4:].split("(")[0]
        for line in TREE_T18.splitlines()
        if line.startswith("def test_")
    ]
    out = tmp_path / "trace.json"
    python = tools_dir() / "sqlfluff-oracle" / "bin" / "python"
    proc = subprocess.run(
        [str(python), str(SCRIPTS / "trace-nodes"), "--out", str(out)]
        + ["--root", str(root)]
        + [name + n for n in names],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    trace = json.loads(out.read_text())
    traced = trace["nodes"]
    assert {n: traced[name + n]["outcome"] for n in names} == dict.fromkeys(
        names, "passed"
    )
    assert oracle.trace_errors(trace, "sqlfluff", [name + n for n in names]) == []
    folder_config = "[sqlfluff:templater:jinja:context]\nx = a\n"
    folder_files = {".sqlfluff": folder_config, "a.sql": TREE_T18_SQL}
    args = ["--dialect=ansi", "--rules", "LT01", "{tmp}/a.sql"]
    good = {
        # A Linter string call with the Jinja context and delimiters.
        "test_jinja_string": [
            _cli_case(
                "lint",
                ["lint", "-f", "json", "-"],
                1,
                stdin="SELECT <%foo%>\n",
                cwd="tmp",
                files={".sqlfluff": TREE_T18_JINJA},
                checks={"violations": [{"records": [{"code": "JJ01"}]}]},
            )
        ],
        # A simple-API fix with the keys of a layout type and a Jinja
        # context.
        "test_layout_api_fix": [
            _cli_case(
                "fix",
                ["fix", "-"],
                0,
                stdin=TREE_T18_ALIGN,
                cwd="tmp",
                files={".sqlfluff": TREE_T18_LAYOUT},
                checks={"stdout": {"equals": TREE_T18_ALIGNED}},
            )
        ],
        # 2 calls in the sqlfluff root with a .sqlfluff file in the folder.
        "test_tmp_config_root": [
            _cli_case("lint", ["lint", *args], 1, cwd="tmp", files=folder_files),
            _cli_case(
                "fix",
                ["fix", *args],
                0,
                cwd="tmp",
                files=folder_files,
                checks={"files": {"a.sql": TREE_T18_FIXED}},
            ),
        ],
    }
    for test, cases in good.items():
        node = _tree_node(root, name + test, cases)
        result = oracle.check_node(node, traced[name + test], "pass", root, [])
        assert result.errors == [] and result.trace == "pass", (test, result.errors)
    # The run in the folder: the same outputs as the call.
    for call in traced[name + "test_tmp_config_root"]["calls"]:
        outputs = dict(call["outputs"])
        proof = outputs.pop("cwd_outputs")
        assert proof == outputs, proof

    # Mutations: a changed Jinja context, layout key, and folder config.
    mutations = [
        ("test_jinja_string", 0, "foo = bar", "foo = baz"),
        ("test_layout_api_fix", 0, "bracketed", "select_clause"),
        ("test_tmp_config_root", 1, "x = a", "x = b"),
    ]
    for test, index, old, new in mutations:
        node = _tree_node(root, name + test, copy.deepcopy(good[test]))
        files = node.cases[index].files
        files[".sqlfluff"] = files[".sqlfluff"].replace(old, new)
        errors = oracle.check_node(node, traced[name + test], "pass", root, []).errors
        case = node.cases[index].name
        assert any(f"case {case}: input files" in e for e in errors), (test, errors)

    # The calls that the maps do not know: each is an error with a message.
    # output_line_length of the folder config changes the lint output only
    # when the folder is the working folder (the CLI reads it from there).
    refused = {
        "test_tmp_config_root_other_outputs": (
            "the temporary folder has the config or ignore files ['.sqlfluff'];"
            " the run of the call in the folder gives other outputs: ['stdout']"
        ),
        "test_function_in_context": (
            "templater:jinja:context:x: the value {'<object>': 'builtins.function'}"
            " is not a scalar"
        ),
        "test_other_jinja_key": (
            "templater:jinja:not_a_key: the map knows only the keys of the default"
            " config and the extra keys"
        ),
    }
    for test, error in refused.items():
        node = _tree_node(root, name + test, [_cli_case("lint", ["lint"], 0)])
        errors = oracle.check_node(node, traced[name + test], "pass", root, []).errors
        assert any(error in e for e in errors), (test, errors)


# T8 (Rust dispatch tests cp01, cp03, cp04: classification and conversion):
# the trace step and the oracle on an error of FluffConfig.from_string, on a
# mock or spy node (python-internal), and on a node that skips with no Rust
# parser, with the oracle tools. Each call that the maps do not know is an
# error with a message.

TREE_T8 = """
import os
from unittest import mock

import pytest
from sqlfluff.core import FluffConfig, Linter
from sqlfluff.core.errors import SQLFluffUserError

BAD = "[sqlfluff]\\ndialect=ansi\\nuse_rust_parser=False\\nuse_rust_rules=True\\n"
GOOD = "[sqlfluff]\\ndialect=ansi\\nrules=LT01\\n"


def test_string_error():
    with pytest.raises(SQLFluffUserError, match="use_rust_parser"):
        FluffConfig.from_string(BAD)


def test_string_error_overrides():
    with pytest.raises(SQLFluffUserError):
        FluffConfig.from_string(BAD, overrides={"dialect": "ansi"})


def test_spy():
    with mock.patch("os.getloadavg", wraps=os.getloadavg) as spy:
        Linter(config=FluffConfig.from_string(GOOD)).lint_string("SELECT 1\\n")
    assert not spy.called


def test_no_mock():
    assert Linter(config=FluffConfig.from_string(GOOD)).lint_string("SELECT 1\\n")


@pytest.mark.skipif(True, reason="Rust parser not available")
def test_rust_only():
    pass


@pytest.mark.skipif(True, reason="another reason")
def test_other_skip():
    pass
"""
T8_ERROR = (
    "SQLFluffUserError: use_rust_rules is enabled but use_rust_parser is"
    " disabled. Rust-native rules require the Rust parser (they read its parse"
    " arena), so this combination does nothing. Set use_rust_parser to 'auto' or"
    " 'True', or disable use_rust_rules."
)
T8_BAD = "[sqlfluff]\ndialect=ansi\nuse_rust_parser=False\nuse_rust_rules=True\n"


@needs_oracles
def test_trace_step_maps_the_calls_of_t8(tmp_path, monkeypatch, capsys):
    root = tmp_path / "root"
    (root / "test").mkdir(parents=True)
    (root / "test" / "t8_test.py").write_text(TREE_T8)
    name = "test/t8_test.py::"
    names = [
        line[4:].split("(")[0]
        for line in TREE_T8.splitlines()
        if line.startswith("def test_")
    ]
    out = tmp_path / "trace.json"
    python = tools_dir() / "sqlfluff-oracle" / "bin" / "python"
    proc = subprocess.run(
        [str(python), str(SCRIPTS / "trace-nodes"), "--out", str(out)]
        + ["--root", str(root)]
        + [name + n for n in names],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    trace = json.loads(out.read_text())
    traced = trace["nodes"]
    assert oracle.trace_errors(trace, "sqlfluff", [name + n for n in names]) == []
    assert {n: traced[name + n]["outcome"] for n in names} == {
        "test_string_error": "passed",
        "test_string_error_overrides": "passed",
        "test_spy": "passed",
        "test_no_mock": "passed",
        "test_rust_only": "skipped",
        "test_other_skip": "skipped",
    }

    # The error of FluffConfig.from_string: the config string is the
    # .sqlfluff file, and the CLI loads it with FluffConfig.from_root.
    error = traced[name + "test_string_error"]["calls"][0]
    assert error["error"] == T8_ERROR
    assert error["inputs"]["function"] == "FluffConfig.from_string"
    assert error["cli"]["errors"] == [
        {"function": "FluffConfig.from_root", "error": T8_ERROR}
    ]
    case = _cli_case(
        "rejected",
        ["lint", "-"],
        2,
        cwd="tmp",
        stdin="",
        files={".sqlfluff": T8_BAD},
        checks={"stdout": {"contains": ["Error loading config: use_rust_rules"]}},
    )
    node = _tree_node(root, name + "test_string_error", [case])
    result = oracle.check_node(
        node, traced[name + "test_string_error"], "pass", root, []
    )
    assert result.errors == [] and result.trace == "pass", result.errors
    assert _run_tree_oracle(monkeypatch, tmp_path, root, trace, [node]) == 0
    assert '"agree": 1' in capsys.readouterr().out
    changed = copy.deepcopy(node)
    changed.cases[0].checks["stdout"]["contains"] = ["User Error"]
    assert _run_tree_oracle(monkeypatch, tmp_path, root, trace, [changed]) == 1
    assert "check 2" in capsys.readouterr().err
    # With overrides, the trace has no CLI input: the oracle refuses it.
    overrides = traced[name + "test_string_error_overrides"]
    assert "cli" not in overrides["calls"][0]
    node = _tree_node(root, name + "test_string_error_overrides", [case])
    errors = oracle.check_node(node, overrides, "pass", root, []).errors
    assert any("FluffConfig.from_string with overrides" in e for e in errors), errors

    # A spy node is python-internal: it has a Linter string call and a mock.
    spy = traced[name + "test_spy"]
    assert spy["mocks"] == ["os.getloadavg"]
    assert [c["kind"] for c in spy["calls"]] == ["linter_string"]
    assert oracle.check_internal(name + "test_spy", spy)["errors"] == []
    # A node with a Linter string call and no mock is not python-internal.
    errors = oracle.check_internal(name + "test_no_mock", traced[name + "test_no_mock"])
    assert errors["errors"] == [
        "class python-internal, but the trace has 1 linter_string calls and the"
        " node patches nothing with unittest.mock"
    ]
    # A node that skips with no Rust parser: only with the tool sqlfluff.
    rust_only = traced[name + "test_rust_only"]
    assert rust_only["skip_reason"] == oracle.RUST_ONLY_SKIP
    result = oracle.check_internal(name + "test_rust_only", rust_only, "sqlfluff")
    assert result["errors"] == [] and result["skip_reason"] == oracle.RUST_ONLY_SKIP
    result = oracle.check_internal(name + "test_rust_only", rust_only, "sqlfluff-rs")
    assert result["errors"] == [
        "the pytest outcome is skipped; the trace of a node that does not pass can"
        " be incomplete"
    ]
    other = traced[name + "test_other_skip"]
    assert other["skip_reason"] == "Skipped: another reason"
    errors = oracle.check_internal(name + "test_other_skip", other, "sqlfluff")[
        "errors"
    ]
    assert errors and errors[0].startswith("the pytest outcome is skipped")


# T22 (convert the rule tests, part 3; goal: each other rule node, not Rust
# dispatch, is a black-box case or is excluded with a class): the trace step
# and the oracle on a fifth test tree. A Linter.lint_string call with
# fix=True whose violations are not those of a lint run maps only to its fix
# case if the node reads only fix_string() of the result; the
# capitalisation_policy of the functions is an extra key of the config
# model. Each other call is an error with a message.

TREE_T22 = """
import pytest
from sqlfluff.core import FluffConfig, Linter
from sqlfluff.core.rules import get_ruleset

SQL = "select a, I as I from b\\n"
FIXED = "select a, i from b\\n"


def linter():
    return Linter(dialect="ansi", rules=["AL09", "CP02"])


def rulepack(section, **values):
    config = FluffConfig(
        configs={"rules": {section: values}}, overrides={"dialect": "ansi"}
    )
    with pytest.raises(ValueError):
        get_ruleset().get_rulepack(config)


def test_fix_only():
    result = linter().lint_string(SQL, fix=True)
    fixed, _ = result.fix_string()
    assert fixed == FIXED
    assert linter().lint_string(fixed).check_tuples() == []


def test_same_violations():
    linter = Linter(dialect="ansi", rules=["LT01"])
    result = linter.lint_string("SELECT a  FROM b\\n", fix=True)
    assert result.fix_string()[0] == "SELECT a FROM b\\n"


def test_functions_policy():
    rulepack("capitalisation.functions", capitalisation_policy="blah")


def test_reads_violations():
    result = linter().lint_string(SQL, fix=True)
    assert len(result.violations) == 2


def test_reads_check_tuples():
    result = linter().lint_string(SQL, fix=True)
    assert result.check_tuples() == [("AL09", 1, 11), ("CP02", 1, 11)]


def test_unpacks_the_result():
    path, *_ = linter().lint_string(SQL, fix=True)
    assert path == "<string input>"


def test_wrapped():
    result = linter().lint_string_wrapped(SQL, fix=True)
    assert result.paths[0].files[0].fix_string()[0] == FIXED


def test_types_policy():
    rulepack("capitalisation.types", capitalisation_policy="blah")


def test_functions_other_key():
    rulepack("capitalisation.functions", capitalisation_policy="blah", not_a_key="x")
"""
T22_SQL = "select a, I as I from b\n"
T22_FIXED = "select a, i from b\n"
T22_CONFIG = "[sqlfluff]\ndialect = ansi\nrules = AL09,CP02\n"
T22_ERROR_CONFIG = (
    "[sqlfluff]\ndialect = ansi\n\n"
    "[sqlfluff:rules:capitalisation.functions]\ncapitalisation_policy = blah\n"
)
T22_REFUSED = {
    "test_reads_violations": f"case fix: {FIX_RUN}, and the node reads"
    " ['violations'] of the result; the map allows only ['fix_string']",
    "test_reads_check_tuples": f"case fix: {FIX_RUN}, and the node reads"
    " ['check_tuples'] of the result; the map allows only ['fix_string']",
    "test_unpacks_the_result": f"case fix: {FIX_RUN}, and the node reads"
    " ['__iter__'] of the result; the map allows only ['fix_string']",
    "test_wrapped": f"case fix: {FIX_RUN}, and the trace watches the reads only"
    " of the result of Linter.lint_string, not of Linter.lint_string_wrapped",
    "test_types_policy": "the config model:"
    " rules:capitalisation.types:capitalisation_policy: the map knows only the"
    " keys of the default config and the extra keys",
    "test_functions_other_key": "the config model:"
    " rules:capitalisation.functions:not_a_key: the map knows only the keys of"
    " the default config and the extra keys",
}


def _t22_good() -> dict[str, list[caseformat.Case]]:
    def stdin_case(name, argv, exit_code, sql, config, **checks):
        return _cli_case(
            name,
            argv,
            exit_code,
            stdin=sql,
            cwd="tmp",
            files={".sqlfluff": config},
            checks=checks,
        )

    return {
        # The fix call maps only to its fix case; then the lint of the fixed
        # SQL.
        "test_fix_only": [
            stdin_case(
                "fix",
                ["fix", "-"],
                0,
                T22_SQL,
                T22_CONFIG,
                stdout={"equals": T22_FIXED},
            ),
            stdin_case(
                "lint_fixed",
                ["lint", "-f", "json", "-"],
                0,
                T22_FIXED,
                T22_CONFIG,
                violations=[{"records": []}],
            ),
        ],
        # The same violations: the lint case and the fix case, as before T22.
        "test_same_violations": [
            stdin_case("lint", ["lint", "-f", "json", "-"], 1, TREE_SQL, T17_CONFIG),
            stdin_case(
                "fix",
                ["fix", "-"],
                0,
                TREE_SQL,
                T17_CONFIG,
                stdout={"equals": TREE_FIXED},
            ),
        ],
        # The capitalisation_policy of the functions in an error call.
        "test_functions_policy": [
            _cli_case(
                "rejected",
                ["lint", "-"],
                2,
                cwd="tmp",
                stdin="",
                files={".sqlfluff": T22_ERROR_CONFIG},
                checks={
                    "stderr": {
                        "contains": [
                            "User Error: Invalid option 'blah' for"
                            " capitalisation_policy configuration."
                        ]
                    }
                },
            )
        ],
    }


def _t22_trace(tmp_path) -> tuple[Path, str, dict]:
    root = tmp_path / "root"
    (root / "test").mkdir(parents=True)
    (root / "test" / "t22_test.py").write_text(TREE_T22)
    name = "test/t22_test.py::"
    names = [
        line[4:].split("(")[0]
        for line in TREE_T22.splitlines()
        if line.startswith("def test_")
    ]
    out = tmp_path / "trace.json"
    python = tools_dir() / "sqlfluff-oracle" / "bin" / "python"
    proc = subprocess.run(
        [str(python), str(SCRIPTS / "trace-nodes"), "--out", str(out)]
        + ["--root", str(root)]
        + [name + n for n in names],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    trace = json.loads(out.read_text())
    outcomes = {n: trace["nodes"][name + n]["outcome"] for n in names}
    assert outcomes == dict.fromkeys(names, "passed")
    assert oracle.trace_errors(trace, "sqlfluff", [name + n for n in names]) == []
    return root, name, trace


@needs_oracles
def test_trace_step_maps_the_calls_of_t22(tmp_path):
    root, name, trace = _t22_trace(tmp_path)
    traced = trace["nodes"]
    good = _t22_good()
    for test, cases in good.items():
        node = _tree_node(root, name + test, cases)
        result = oracle.check_node(node, traced[name + test], "pass", root, [])
        assert result.errors == [] and result.trace == "pass", (test, result.errors)
    # The reads of each watched result: only a fix run with other violations
    # than its lint run is watched.
    reads = {
        test: [c.get("reads") for c in data["calls"]]
        for test, data in ((t, traced[name + t]) for t in [*good, *T22_REFUSED])
    }
    assert reads == {
        "test_fix_only": [["fix_string"], None],
        "test_same_violations": [None],
        "test_functions_policy": [None],
        "test_reads_violations": [["violations"]],
        "test_reads_check_tuples": [["check_tuples"]],
        "test_unpacks_the_result": [["__iter__"]],
        "test_wrapped": [None],
        "test_types_policy": [None],
        "test_functions_other_key": [None],
    }
    fix = traced[name + "test_fix_only"]["calls"][0]["outputs"]
    assert fix["records"] != fix["lint"]["records"]
    error = traced[name + "test_functions_policy"]["calls"][0]
    assert error["cli"]["errors"] == [
        {"function": "RuleSet.get_rulepack", "error": error["error"]}
    ]
    # Each call that the maps do not know is an error with a message.
    for test, error in T22_REFUSED.items():
        node = _tree_node(root, name + test, [_cli_case("fix", ["fix", "-"], 0)])
        errors = oracle.check_node(node, traced[name + test], "pass", root, []).errors
        assert any(error in e for e in errors), (test, errors)


# A changed input of each map of T22 gives exit code 1 with a message.
T22_EXIT_MUTATIONS = [
    (
        "fix run with other violations",
        "test_fix_only",
        0,
        lambda c: setattr(c, "stdin", T22_FIXED),
        "case fix: input stdin",
    ),
    (
        "a lint case of a fix run with other violations",
        "test_fix_only",
        0,
        lambda c: setattr(c, "argv", ["lint", "-f", "json", "-"]),
        "case fix: input argv",
    ),
    (
        "capitalisation_policy of the functions",
        "test_functions_policy",
        0,
        lambda c: c.files.update(
            {".sqlfluff": T22_ERROR_CONFIG.replace("functions", "types")}
        ),
        "case rejected: input files",
    ),
]


@needs_oracles
def test_the_oracle_script_on_the_maps_of_t22(tmp_path, monkeypatch, capsys):
    root, name, trace = _t22_trace(tmp_path)
    good = _t22_good()

    def nodes():
        return [_tree_node(root, name + t, copy.deepcopy(c)) for t, c in good.items()]

    assert _run_tree_oracle(monkeypatch, tmp_path, root, trace, nodes()) == 0
    out = capsys.readouterr()
    assert "error:" not in out.err
    assert f'"agree": {len(good)}' in out.out
    for _, test, index, change, error in T22_EXIT_MUTATIONS:
        changed = nodes()
        node = next(n for n in changed if n.id == name + test)
        change(node.cases[index])
        assert _run_tree_oracle(monkeypatch, tmp_path, root, trace, changed) == 1
        lines = capsys.readouterr().err.splitlines()
        assert f"error: sqlfluff: {name}{test}: {error}" in "\n".join(lines), lines
    # An unmapped call: each refused node of the tree with a case.
    for test, error in T22_REFUSED.items():
        node = _tree_node(root, name + test, [_cli_case("fix", ["fix", "-"], 0)])
        assert _run_tree_oracle(monkeypatch, tmp_path, root, trace, [node]) == 1
        err = capsys.readouterr().err
        assert f"error: sqlfluff: {name}{test}: " in err and error in err, err


S7CONFIG_CHECK = """
import json
import sys

sys.path.insert(0, sys.argv[1])
import s7config

REF = {
    "core": {"dialect": None, "rules": "all", "color": None, "a_path": None},
    "rules": {"x.y": {"flag": False, "name": "a"}},
}


def text(effective):
    try:
        return s7config.config_text(effective, REF)
    except s7config.ConfigMapError as exc:
        return "error: " + str(exc)


def change(core=None, rule=None):
    out = json.loads(json.dumps(REF))
    out["core"].update(core or {})
    out["rules"]["x.y"].update(rule or {})
    return out


def extra(*path, value="v"):
    out = change()
    target = out
    for key in path[:-1]:
        target = target.setdefault(key, {})
    target[path[-1]] = value
    return out


missing = change()
del missing["rules"]["x.y"]["name"]
print(json.dumps({
    "jinja context": text(extra("templater", "jinja", "context", "foo")),
    "jinja delimiter": text(
        extra("templater", "jinja", "block_start_string", value="((")
    ),
    "layout key": text(
        extra("layout", "type", "alias_expression", "align_scope", value="bracketed")
    ),
    "other jinja key": text(extra("templater", "jinja", "not_a_key")),
    "other templater": text(extra("templater", "python", "context", "foo")),
    "nested context": text(extra("templater", "jinja", "context", "a", "b")),
    "other layout key": text(extra("layout", "type", "alias_expression", "x")),
    "function in context": text(
        extra("templater", "jinja", "context", "f", value={"<object>": "f"})
    ),
    "number text in context": text(
        extra("templater", "jinja", "context", "n", value="123")
    ),
    "functions policy": text(
        extra("rules", "capitalisation.functions", "capitalisation_policy")
    ),
    "types policy": text(
        extra("rules", "capitalisation.types", "capitalisation_policy")
    ),
    "other functions key": text(
        extra("rules", "capitalisation.functions", "not_a_key")
    ),
    "same": text(change()),
    "derived": text(change({"color": True})),
    "values": text(change({"dialect": "ansi"}, {"flag": 1, "name": "b c"})),
    "unknown": text(change({"other": 1})),
    "path": text(change({"a_path": "x"})),
    "loads as another value": text(change({"dialect": "True"})),
    "two lines": text(change({"dialect": "a\\nb"})),
    "list": text(change({"rules": ["a"]})),
    "missing": text(missing),
    "differences": s7config.differences(REF, change({"dialect": "ansi"})),
}))
"""


@needs_oracles
def test_config_model(tmp_path):
    script = tmp_path / "check.py"
    script.write_text(S7CONFIG_CHECK)
    python = tools_dir() / "sqlfluff-oracle" / "bin" / "python"
    proc = subprocess.run(
        [str(python), "-I", str(script), str(SCRIPTS)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["same"] == out["derived"] == ""
    assert out["values"] == (
        "[sqlfluff]\ndialect = ansi\n\n[sqlfluff:rules:x.y]\nflag = 1\nname = b c\n"
    )
    assert out["unknown"] == (
        "error: core:other: the map knows only the keys of the default config"
        " and the extra keys"
    )
    # T18: the extra keys (the Jinja context and delimiters, and the keys of a
    # layout type) map; each other key that the default config does not have
    # is an error.
    assert out["jinja context"] == "[sqlfluff:templater:jinja:context]\nfoo = v\n"
    assert out["jinja delimiter"] == (
        "[sqlfluff:templater:jinja]\nblock_start_string = ((\n"
    )
    assert out["layout key"] == (
        "[sqlfluff:layout:type:alias_expression]\nalign_scope = bracketed\n"
    )
    unknown = "the map knows only the keys of the default config and the extra keys"
    assert out["other jinja key"] == f"error: templater:jinja:not_a_key: {unknown}"
    assert out["other templater"] == (f"error: templater:python:context:foo: {unknown}")
    assert out["nested context"] == f"error: templater:jinja:context:a:b: {unknown}"
    assert out["other layout key"] == (
        f"error: layout:type:alias_expression:x: {unknown}"
    )
    assert out["function in context"] == (
        "error: templater:jinja:context:f: the value {'<object>': 'f'} is not a scalar"
    )
    assert out["number text in context"] == (
        "error: templater:jinja:context:n: the text '123' loads as another value"
    )
    # T22: the capitalisation_policy of the functions maps; the same key in
    # another rule section, and another key of the functions, are errors.
    assert out["functions policy"] == (
        "[sqlfluff:rules:capitalisation.functions]\ncapitalisation_policy = v\n"
    )
    assert out["types policy"] == (
        f"error: rules:capitalisation.types:capitalisation_policy: {unknown}"
    )
    assert out["other functions key"] == (
        f"error: rules:capitalisation.functions:not_a_key: {unknown}"
    )
    assert out["path"].startswith("error: core:a_path: a path key")
    assert out["loads as another value"] == (
        "error: core:dialect: the text 'True' loads as another value"
    )
    assert out["two lines"].startswith("error: core:dialect: the text")
    assert out["list"] == "error: core:rules: the value ['a'] is not a scalar"
    assert out["missing"] == (
        "error: the config has no value for the default keys ['rules:x.y:name']"
    )
    assert out["differences"] == ["core:dialect"]


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
