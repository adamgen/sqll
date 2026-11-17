"""The case runner and the trace oracle of the test conversion with the scope
file of S6 (docs/decisions/s6-templaters.md, "Black-box form").

S6: templater parity (sqll passes 100% of the placeholder and Python
format-string templater fixtures that do not need a Python runtime). T2 (the
case runner and the trace oracle of the test conversion run the cases of
this stone with its scope file) adds the scope file
(sqll_harness/s6/scope.py), the checks "templated" and "source_slices" of
the case format, and the templater map of the trace oracle. There is one
runner (S6 design item 4).

The fixtures are in harness/tests/fixtures/s6/: a test tree that calls the
templaters (tree/test/templater_calls_test.py), its cases
(tree/templater_calls_test.yml), and its trace with --templaters
(trace.json). The tests of the trace step run trace-nodes on the tree with
the oracle tools.
"""

import copy
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from conftest import needs

from sqll_harness import cli
from sqll_harness.adapters import ADAPTERS
from sqll_harness.cases import FAIL, PASS
from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT, tools_dir
from sqll_harness.s6 import scope as s6scope
from sqll_harness.s7_tests import caseformat, oracle, report, runner, scopes, suites

FIXTURES = REPO_ROOT / "harness" / "tests" / "fixtures" / "s6"
TREE = FIXTURES / "tree"
TREE_FILE = "test/templater_calls_test.py"
TREE_CASES = TREE / "templater_calls_test.yml"
TRACE = json.loads((FIXTURES / "trace.json").read_text("utf8"))
S6_DATA = json.loads(s6scope.SCOPE_FILE.read_text("utf8"))
SCRIPTS = REPO_ROOT / "scripts" / "s7-tests"
needs_oracle = needs("sqlfluff-oracle/bin/python")
needs_tools = needs("sqlfluff/bin/sqlfluff", "sqruff/bin/sqruff")


def tree_nodes() -> dict[str, caseformat.Node]:
    data = caseformat.load_yaml(TREE_CASES)
    file, items, errors = caseformat.parse_case_file(
        data, TREE_CASES.name, {TREE_FILE: {}}
    )
    assert errors == [] and file == TREE_FILE
    return {
        node_id: caseformat.Node(node_id, "placeholder", TREE_CASES.name, cases, cited)
        for node_id, cases, cited in items
    }


NODES = tree_nodes()
MAPPED = [n for n in NODES if "::test_map_" in n]
# The error of each call that the map must refuse.
REFUSED = {
    f"{TREE_FILE}::test_refuse_jinja": (
        "case x: a process() call of the templater 'jinja'; the map knows only"
        " ['placeholder', 'python']"
    ),
    f"{TREE_FILE}::test_refuse_not_a_literal": (
        "case x: a context value that is not a literal"
    ),
    f"{TREE_FILE}::test_refuse_config_from_kwargs": (
        "case x: a config from {'method': 'from_kwargs', 'args': {'dialect':"
        " 'ansi'}}; the map knows only FluffConfig(overrides=...)"
    ),
    f"{TREE_FILE}::test_refuse_untraced_method": (
        "an untraced call: a templater method (PythonTemplater.get_context)"
    ),
}
PLACEHOLDER = f"{TREE_FILE}::test_map_placeholder"
VALUE_ERROR = f"{TREE_FILE}::test_map_value_error"


def check(node_id: str, data: dict | None = None, node=None, root: Path = TREE):
    """The oracle check of a tree node on the fixture trace (or data)."""
    data = TRACE["nodes"][node_id] if data is None else data
    return oracle.check_node(node or NODES[node_id], data, PASS, root, [])


def test_the_tree_has_each_case():
    assert set(NODES) == set(TRACE["nodes"])
    assert len(MAPPED) == 5 and set(NODES) - set(MAPPED) == set(REFUSED)


# The scope file.


def test_scope_is_the_black_box_nodes_of_s6():
    data = s6scope.load()
    black_box = [n for n in S6_DATA["nodes"] if n["kind"] == "black_box"]
    assert [n["id"] for n in data["nodes"]] == [n["id"] for n in black_box]
    assert [n["group"] for n in data["nodes"]] == [n["templater"] for n in black_box]
    counts = S6_DATA["counts"]
    assert (
        data["counts"]
        == {
            "placeholder": counts["placeholder_nodes"]["black_box"],
            "python": counts["python_nodes"]["black_box"],
            "total": counts["s6_black_box"],
        }
        == {"placeholder": 26, "python": 28, "total": 54}
    )
    assert data["files"] == {
        "test/core/templaters/placeholder_test.py": {
            "group": "placeholder",
            "nodes": 26,
        },
        "test/core/templaters/python_test.py": {"group": "python", "nodes": 28},
    }
    assert suites.suite_table(data) == s6scope.SUITES
    assert suites.tool_list(data) == ("sqlfluff", "sqruff", "sqll")
    assert suites.group_list(data) == ("placeholder", "python")
    assert suites.groups(["s6_python"], data) == {"python"}
    with pytest.raises(ValueError, match="unknown suites of the scope"):
        suites.groups(["s7_cli"], data)
    # The S7 scope data has no "suites" or "tools": the S7 suites.
    s7 = caseformat.load_scope()
    assert suites.suite_table(s7) is suites.SUITES
    assert suites.tool_list(s7) == suites.TOOLS


def _mutate(change):
    data = copy.deepcopy(S6_DATA)
    change(data)
    return data


def _node(data, kind="black_box"):
    return next(n for n in data["nodes"] if n["kind"] == kind)


@pytest.mark.parametrize(
    "change, error",
    [
        (
            lambda d: _node(d).update(needs_python_runtime=["python code: x"]),
            "a black-box node that needs a Python runtime",
        ),
        (lambda d: _node(d).update(templater="jinja"), "the templater 'jinja'"),
        (
            lambda d: _node(d, "internal").update(kind="black_box"),
            "29 black-box python nodes, not python_nodes.black_box 28",
        ),
        (lambda d: d.update(commit="0" * 40), "is not the pin"),
        (lambda d: d.update(sqlfluff="4.3.0"), "sqlfluff 4.3.0, not the pin"),
        (
            lambda d: d["nodes"].append(_node(d)),
            "a node id is in the list 2 times",
        ),
    ],
)
def test_scope_fails_closed(change, error):
    with pytest.raises(s6scope.ScopeError, match=re.escape(error)):
        s6scope.from_s6(_mutate(change))


def test_scopes_of_the_runner_and_the_oracle():
    assert scopes.get("s6") is s6scope.SCOPE
    assert scopes.get("s7") is scopes.S7 and scopes.DEFAULT == "s7"
    with pytest.raises(ValueError, match="unknown scope 'x'"):
        scopes.get("x")
    assert s6scope.SCOPE.suites == ("s6_placeholder", "s6_python")
    assert s6scope.SCOPE.tools == ("sqlfluff", "sqruff", "sqll")
    assert s6scope.SCOPE.oracle_tools == ("sqlfluff",)
    assert s6scope.SCOPE.trace_args == ("--templaters",)
    assert scopes.S7.trace_args == () and scopes.S7.tools == suites.TOOLS
    assert scopes.all_tools() == ["sqlfluff", "sqlfluff-rs", "sqruff", "sqll"]
    assert scopes.all_suites() == sorted([*suites.SUITES, *s6scope.SUITES])
    assert s6scope.no_record() == oracle.NotReproduced([], False)


def test_s6_has_no_second_runner():
    # S6 design item 4: the S6 package has the scope file and the case files
    # only. The runner and the oracle are those of the test conversion.
    package = REPO_ROOT / "harness" / "sqll_harness" / "s6"
    files = sorted(
        p.relative_to(package).as_posix()
        for p in package.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    assert [f for f in files if not f.startswith("cases/")] == [
        "__init__.py",
        "scope.py",
    ]
    assert all(f.endswith(".yml") for f in files if f.startswith("cases/"))
    source = (package / "scope.py").read_text("utf8")
    for name in ("subprocess", "ThreadPoolExecutor", "run_nodes"):
        assert name not in source


# The case files of the scope.


def test_s6_case_files_load():
    cases = s6scope.load_cases()
    assert cases.exclusions == []
    assert len(cases.scope["nodes"]) == 54
    by_file = {}
    for node in cases.nodes:
        by_file.setdefault(node.case_file, []).append(node.id)
        assert node.group == node.id.split("/")[-1].split("_test.py")[0]
        for case in node.cases:
            assert case.run == "cli" and case.cwd == "tmp"
            assert set(case.files) == {".sqlfluff", "case.sql"}
    assert set(by_file) == {
        "core/templaters/placeholder_test.yml",
        "core/templaters/python_test.yml",
    }
    # Each assert has a citing check (the scope has no not-reproduced record).
    errors = oracle.coverage_errors(cases.nodes, SQLFLUFF_ROOT, s6scope.no_record())
    assert errors == []


def test_a_case_file_of_another_scope_is_refused(tmp_path):
    # An S7 case file in the S6 case folder: its source file has no node in
    # the S6 scope.
    folder = tmp_path / "cli"
    folder.mkdir()
    shutil.copy(caseformat.CASES_DIR / "cli" / "commands_test.yml", folder)
    with pytest.raises(caseformat.CaseFormatError) as exc:
        caseformat.load(tmp_path, None, s6scope.load())
    assert "has no node in scope.json" in str(exc.value)


# The parse tree checks of the case format.


def _tree_case(name: str) -> dict:
    data = caseformat.load_yaml(TREE_CASES)
    node = next(n for n in data["nodes"] if n["node"] == PLACEHOLDER)
    return copy.deepcopy(next(c for c in node["cases"] if c["name"] == name))


def _format_errors(case: dict) -> list[str]:
    err = caseformat._Errors("x.yml")
    caseformat._check_cli(err, "case", case)
    return err.items


def test_the_tree_checks_of_the_fixture_are_valid():
    assert _format_errors(_tree_case("templated")) == []
    assert _format_errors(_tree_case("slices")) == []
    assert caseformat.parse_json_argv(["parse", "--format=json", "-m", "a"]) == (
        True,
        True,
    )
    assert caseformat.parse_json_argv(["parse", "--format", "json", "a"]) == (
        True,
        False,
    )
    assert caseformat.parse_json_argv(["lint", "-f", "json", "-m"]) == (False, False)
    assert caseformat.parse_json_argv(["parse", "-f", "yaml", "a"]) == (False, False)


def _set(case, key, value):
    case[key] = value
    return case


def _check(case, key, value):
    case["checks"][key] = value
    return case


@pytest.mark.parametrize(
    "name, change, error",
    [
        (
            "templated",
            lambda c: _set(c, "argv", ["parse", "-f", "json", "-m", "case.sql"]),
            "templated: needs the argv parse -f json with no meta option (-m)",
        ),
        (
            "templated",
            lambda c: _set(c, "argv", ["lint", "-f", "json", "case.sql"]),
            "templated: needs the argv parse -f json with no meta option (-m)",
        ),
        (
            "templated",
            lambda c: _check(c, "templated", 1),
            "templated: must be a string",
        ),
        (
            "slices",
            lambda c: _set(c, "argv", ["parse", "-f", "json", "case.sql"]),
            "source_slices: needs the argv parse -f json with the meta option (-m)",
        ),
        (
            "slices",
            lambda c: _check(c, "source_slices", []),
            "source_slices: must be a list with one or more",
        ),
        (
            "slices",
            lambda c: _check(c, "source_slices", [["SELECT", 6, 0]]),
            "source_slices[0]: must be [raw, start_file_pos, end_file_pos]",
        ),
        (
            "slices",
            lambda c: _check(c, "source_slices", [["SELECT", 0, True]]),
            "source_slices[0]: must be [raw, start_file_pos, end_file_pos]",
        ),
        (
            "slices",
            lambda c: _check(c, "source_slices", [[1, 0, 6]]),
            "source_slices[0]: must be [raw, start_file_pos, end_file_pos]",
        ),
    ],
)
def test_the_tree_checks_fail_closed(name, change, error):
    errors = _format_errors(change(_tree_case(name)))
    assert len(errors) == 1 and error in errors[0], errors


# The parse tree checks of the runner, on the CLI outputs of the trace.


def _runs(node_id: str) -> list[dict]:
    return [r for c in TRACE["nodes"][node_id]["calls"] for r in c["cases"]]


def test_the_tree_checks_pass_on_the_traced_outputs():
    for node_id in (PLACEHOLDER, f"{TREE_FILE}::test_map_python_no_config"):
        runs = _runs(node_id)
        for case, run in zip(NODES[node_id].cases, runs, strict=True):
            assert runner.tree_failures(case.checks, run["stdout"]) == []
    plain, meta = _runs(PLACEHOLDER)
    leaves = runner.parse_leaves(plain["stdout"])
    assert "".join(x.raw for x in leaves) == "SELECT 1 FROM t\n"
    assert {x.start_file_pos for x in leaves} == {None}
    leaves = runner.parse_leaves(meta["stdout"])
    one = next(x for x in leaves if x.raw == "1")
    # The leaf "1" has the source slice of ":a".
    assert (one.type, one.start_file_pos, one.end_file_pos) == ("numeric_literal", 7, 9)


@pytest.mark.parametrize(
    "index, stdout, checks, error",
    [
        (0, None, {"templated": "SELECT 2 FROM t\n"}, "templated: the text is"),
        (
            1,
            None,
            {"source_slices": [["SELECT", 0, 6]]},
            "source_slices: 13 leaves, not 1",
        ),
        (
            0,
            None,
            {"source_slices": [["SELECT", 0, 6]]},
            "source_slices: a leaf has no position (no -m)",
        ),
        (
            0,
            '[{"filepath": "case.sql", "segments": null}]',
            {"templated": "SELECT 1 FROM t\n"},
            "templated: the parse output has no parse tree (segments is null)",
        ),
        (0, "Error", {"templated": "x"}, "templated: the stdout is not parse JSON"),
        (
            0,
            '[{"filepath": "a", "segments": {}}, {"filepath": "b", "segments": {}}]',
            {"templated": "x"},
            "the stdout is not the parse JSON output of 1 file",
        ),
        (
            1,
            '[{"filepath": "a", "segments": {"start_line_no": 1, "file": []}}]',
            {"source_slices": [["x", 0, 1]]},
            "a segment with positions is not one segment",
        ),
    ],
)
def test_the_tree_checks_fail(index, stdout, checks, error):
    stdout = _runs(PLACEHOLDER)[index]["stdout"] if stdout is None else stdout
    failed = runner.tree_failures(checks, stdout)
    assert len(failed) == 1 and error in failed[0], failed


def test_a_changed_source_slice_fails():
    case = NODES[PLACEHOLDER].cases[1]
    want = copy.deepcopy(case.checks["source_slices"])
    want[3] = ["1", 7, 8]
    assert runner.tree_failures(
        {"source_slices": want}, _runs(PLACEHOLDER)[1]["stdout"]
    ) == ["source_slices[3]: the leaf is ['1', 7, 9]"]


@needs("sqlfluff/bin/sqlfluff")
def test_the_runner_runs_the_tree_cases_with_sqlfluff(tmp_path):
    run = runner.tool_run("sqlfluff", ADAPTERS["sqlfluff"](), tmp_path)
    for node_id in MAPPED:
        for case in NODES[node_id].cases:
            assert runner.run_case(run, case) == runner.CaseOutcome(case.name, PASS)
    case = copy.deepcopy(NODES[PLACEHOLDER].cases[1])
    case.checks["source_slices"][3] = ["1", 7, 8]
    out = runner.run_case(run, case)
    assert (out.status, out.reason) == (
        FAIL,
        "source_slices[3]: the leaf is ['1', 7, 9]",
    )


# The templater map of the oracle, on the fixture trace.


def test_the_oracle_agrees_with_each_mapped_call():
    for node_id in MAPPED:
        result = check(node_id)
        assert result.errors == [] and result.trace == PASS, (node_id, result.errors)
    # A call that returns gives 2 cases; each error gives 1 case.
    shapes = {
        n.split("::")[1]: [
            (c.get("error_kind", "returned"), [r["argv"] for r in c["cases"]])
            for c in TRACE["nodes"][n]["calls"]
        ]
        for n in MAPPED
    }
    parse = ["parse", "-f", "json", "case.sql"]
    meta = ["parse", "-f", "json", "-m", "case.sql"]
    assert shapes == {
        "test_map_placeholder": [("returned", [parse, meta])],
        "test_map_python_no_config": [("returned", [parse, meta])],
        "test_map_value_error": [("other_error", [parse])],
        "test_map_templater_error": [
            ("templater_error", [["lint", "-f", "json", "case.sql"]])
        ],
        "test_map_skip_file": [("skip_file", [parse])],
    }


def test_the_oracle_refuses_each_other_call():
    for node_id, error in REFUSED.items():
        result = check(node_id)
        assert result.trace is None, node_id
        assert any(e.startswith(error) for e in result.errors), (node_id, result.errors)


def _call(data: dict, i: int = 0) -> dict:
    return data["calls"][i]


def _trace_change(node_id: str, change):
    data = copy.deepcopy(TRACE["nodes"][node_id])
    change(data)
    return data


@pytest.mark.parametrize(
    "node_id, change, error",
    [
        (
            PLACEHOLDER,
            lambda d: _call(d).update(proof=["parse: the templated_str is different"]),
            "case templated: the templater result of the CLI case is not the result"
            " of the call: ['parse: the templated_str is different']",
        ),
        (
            PLACEHOLDER,
            lambda d: _call(d).pop("proof"),
            "case templated: the templater result of the CLI case is not the result"
            " of the call: None",
        ),
        (
            PLACEHOLDER,
            lambda d: _call(d).update(proof_error="KeyError: x"),
            "case templated: the trace could not prove the map: KeyError: x",
        ),
        (
            PLACEHOLDER,
            lambda d: _call(d)["cases"].pop(),
            "case templated: the trace ran the cases",
        ),
        (
            VALUE_ERROR,
            lambda d: _call(d).update(error_kind="templater_error"),
            "case error: the trace ran the cases",
        ),
        (
            VALUE_ERROR,
            lambda d: _call(d).update(error_kind="new_error"),
            "case error: a templater call with the result 'new_error'",
        ),
        (
            PLACEHOLDER,
            lambda d: _call(d)["inputs"].update(templater="raw"),
            "case templated: a process() call of the templater 'raw'",
        ),
        (
            PLACEHOLDER,
            lambda d: _call(d)["inputs"].update(unsupported=["a formatter"]),
            "case templated: a formatter",
        ),
        (
            PLACEHOLDER,
            lambda d: _call(d)["inputs"].update(config_file={"error": "x: y"}),
            "case templated: the config of the templater call: x: y",
        ),
        (
            PLACEHOLDER,
            lambda d: _call(d)["cases"][0].update(outer_config={"core": {"x": 1}}),
            "case templated: a folder above the case folder has a sqlfluff config",
        ),
        (
            PLACEHOLDER,
            lambda d: _call(d)["cases"][0].update(
                stdout=_call(d)["cases"][0]["stdout"].replace('"1"', '"2"')
            ),
            "check 2: the checks on the traced outputs give fail, pytest gives passed",
        ),
        (
            PLACEHOLDER,
            lambda d: _call(d)["cases"][1].update(exit_code=1),
            "check 2: the checks on the traced outputs give fail, pytest gives passed",
        ),
        (
            PLACEHOLDER,
            lambda d: _call(d)["cases"][0].update(exception="ValueError: x"),
            "check 2: the checks on the traced outputs give fail, pytest gives passed",
        ),
        (
            PLACEHOLDER,
            lambda d: _call(d)["cases"][0]["files"].update({"new.txt": "x"}),
            "check 2: the checks on the traced outputs give fail, pytest gives passed",
        ),
        (
            PLACEHOLDER,
            lambda d: d["calls"].append(copy.deepcopy(_call(d))),
            "2 traced calls (4 cases), 2 cases: a call has no case",
        ),
        (
            PLACEHOLDER,
            lambda d: d["untraced"].append("a templater method (X.slice_file)"),
            "an untraced call: a templater method (X.slice_file)",
        ),
    ],
)
def test_trace_mutation_makes_the_oracle_fail(node_id, change, error):
    result = check(node_id, _trace_change(node_id, change))
    assert any(error in e for e in result.errors), result.errors


def _case_change(node_id: str, index: int, change) -> caseformat.Node:
    node = copy.deepcopy(NODES[node_id])
    change(node.cases[index])
    return node


@pytest.mark.parametrize(
    "index, change, error",
    [
        (
            0,
            lambda c: c.files.update({".sqlfluff": c.files[".sqlfluff"] + "b = 2\n"}),
            "case templated: input files: the case gives",
        ),
        (
            0,
            lambda c: c.files.update({"case.sql": "SELECT :b FROM t\n"}),
            "case templated: input files: the case gives",
        ),
        (
            0,
            lambda c: setattr(c, "argv", ["parse", "-f", "json", "x.sql"]),
            "case templated: input argv: the case gives",
        ),
        (
            0,
            lambda c: c.checks.update(templated="SELECT :a FROM t\n"),
            "check 2: the checks on the traced outputs give fail, pytest gives passed",
        ),
        (
            1,
            lambda c: c.checks["source_slices"].__setitem__(3, ["1", 7, 8]),
            "check 2: the checks on the traced outputs give fail, pytest gives passed",
        ),
    ],
)
def test_case_mutation_makes_the_oracle_fail(index, change, error):
    result = check(PLACEHOLDER, node=_case_change(PLACEHOLDER, index, change))
    assert any(error in e for e in result.errors), result.errors


def test_a_missing_citation_makes_the_oracle_fail():
    node = copy.deepcopy(NODES[PLACEHOLDER])
    node.asserts = {}
    result = check(PLACEHOLDER, node=node)
    assert result.errors == ["assert L31: no check cites it and no record has it"]


# The trace step: trace-nodes on the test tree with the oracle tools.


def _env(home: Path) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "VIRTUAL_ENV"}
    }
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
    return env


def _trace_tree(tmp_path: Path, *flags: str) -> dict:
    root = tmp_path / "root"
    shutil.copytree(TREE / "test", root / "test")
    out = tmp_path / f"trace{len(flags)}.json"
    python = tools_dir() / "sqlfluff-oracle" / "bin" / "python"
    proc = subprocess.run(
        [str(python), str(SCRIPTS / "trace-nodes"), *flags, "--out", str(out)]
        + ["--root", str(root), *NODES],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(out.read_text("utf8"))


def _shape(nodes: dict) -> dict:
    """The calls of each node with no volatile output (the lint timings)."""
    out = {}
    for node_id, data in nodes.items():
        calls = []
        for call in data["calls"]:
            runs = [
                {k: v for k, v in r.items() if k != "stdout" or r["argv"][0] != "lint"}
                for r in call.get("cases", [])
            ]
            calls.append({**call, "cases": runs})
        out[node_id] = {**data, "calls": calls}
    return out


@needs_oracle
def test_trace_step_maps_the_templater_calls(tmp_path):
    trace = _trace_tree(tmp_path, "--templaters")
    assert oracle.trace_errors(trace, "sqlfluff", list(NODES)) == []
    assert {n["outcome"] for n in trace["nodes"].values()} == {"passed"}
    root = tmp_path / "root"
    for node_id in MAPPED:
        result = check(node_id, trace["nodes"][node_id], root=root)
        assert result.errors == [] and result.trace == PASS, (node_id, result.errors)
    for node_id, error in REFUSED.items():
        result = check(node_id, trace["nodes"][node_id], root=root)
        assert any(e.startswith(error) for e in result.errors), result.errors
    # The fixture trace is a trace of the tree now.
    assert _shape(trace["nodes"]) == _shape(TRACE["nodes"])


@needs_oracle
def test_trace_step_without_templaters_traces_no_templater_call(tmp_path):
    # The S7 scope: trace-nodes with no --templaters does not change.
    trace = _trace_tree(tmp_path)
    for data in trace["nodes"].values():
        assert data["calls"] == [] and data["untraced"] == []


# The case runner with the scope s6: sqll-harness s7 run --scope s6.

SQLL_STUB = """#!/bin/sh
if [ "$1" = "--version" ]; then echo "sqll, version 0.0.0+stub"; exit 0; fi
echo "Error: unsupported: setting core:templater (stub)" >&2
exit 2
"""


@needs_tools
def test_s7_run_runs_the_s6_case_files(tmp_path, monkeypatch, capsys):
    """The one runner runs the S6 case files for sqlfluff, sqruff, and sqll
    and writes the report of the test conversion. sqll is a stub here: the
    unit tests have no sqll build (the sqll result is the reason of the
    stub)."""
    from sqll_harness import tools

    stub = tmp_path / "sqll"
    stub.write_text(SQLL_STUB, "utf8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("SQLL_BIN", str(stub))
    real = tools.check
    monkeypatch.setattr(
        tools, "check", lambda names: real([n for n in names if n != "sqll"])
    )
    out = tmp_path / "report.json"
    argv = ["s7", "run", "--scope", "s6", "--out", str(out), "--require-pass"]
    assert cli.main([*argv, "sqlfluff"]) == 0
    printed = capsys.readouterr().out
    assert "S6 suites: s6_placeholder s6_python" in printed
    data = json.loads(out.read_text("utf8"))
    scope = s6scope.load()
    report.check(data, scope)
    cases = s6scope.load_cases()
    assert data["suites"] == ["s6_placeholder", "s6_python"]
    assert list(data["tools"]) == ["sqlfluff", "sqruff", "sqll"]
    assert [n["id"] for n in data["nodes"]] == [n.id for n in cases.nodes]
    assert data["counts"]["in_scope"] == 54
    assert data["counts"]["converted"] == len(cases.nodes)
    for node in data["nodes"]:
        results = node["results"]
        assert results["sqlfluff"]["status"] == PASS, node["id"]
        assert results["sqruff"]["status"] == FAIL
        assert all(
            c["reason"].startswith("unsupported: sqlfluff CLI command")
            for c in results["sqruff"]["failed_cases"]
        )
        assert results["sqll"]["status"] == FAIL
        assert all(
            c["reason"].startswith("exit_code: 2, not ")
            for c in results["sqll"]["failed_cases"]
        )
