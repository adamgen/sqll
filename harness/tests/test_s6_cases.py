"""The placeholder and python cases of S6 (templater parity: sqll passes
100% of the placeholder and Python format-string templater fixtures that do
not need a Python runtime).

T3 (each placeholder node is a case that sqlfluff passes and that agrees
with its trace) converts the 26 placeholder nodes of results/S6/scope.json
to the case file harness/sqll_harness/s6/cases/core/templaters/
placeholder_test.yml. These tests do not run a tool. They check that:

- The case file has each placeholder node of the scope, in the order of
  the scope, and no other node. A missing node or a node that is not in
  the scope fails.
- Each node has the cases of the templater map of the trace oracle: a call
  that returns has the case "templated" (parse, the check "templated") and
  the case "slices" (parse -m, the check "source_slices"); a ValueError of
  the templater has a parse case with the exit code and the stderr.
- The data of each case is the data of the sqlfluff 4.4.0 test, with no
  change: the SQL file is in_str, the .sqlfluff file has the context of the
  call, the templated text is the expected output of the test, and the
  stderr text has the match text of pytest.raises. The tests read the
  values from the source of the test (third_party/sqlfluff), with ast.

T4 (each black-box python node is a case that sqlfluff passes and that
agrees with its trace) converts the 28 black-box python nodes of
results/S6/scope.json to the case file harness/sqll_harness/s6/cases/core/
templaters/python_test.yml, with the same checks. A SQLTemplaterError has a
lint case (the TMP violation), and a SQLFluffSkipFile a parse case (the
stdout and the stderr). Each context value of a python case is a literal:
the python templater evaluates it with ast.literal_eval, and no value needs
a Python runtime (docs/decisions/s6-templaters.md, "Needs a Python
runtime"). The check fails closed on another value.

The trace oracle (scripts/s7-tests/oracle --scope s6) is the proof that
each case agrees with the trace of its node.
"""

import ast
import configparser
import copy
import importlib.util
import json
import re
from collections import Counter
from typing import Any

import pytest

from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT
from sqll_harness.s6 import scope as s6scope
from sqll_harness.s7_tests import caseformat

SOURCE = "test/core/templaters/placeholder_test.py"
CASE_FILE = "core/templaters/placeholder_test.yml"
CASE_PATH = s6scope.CASES_DIR / CASE_FILE
SCOPE = json.loads(s6scope.SCOPE_FILE.read_text("utf8"))
SCOPE_IDS = [
    n["id"] for n in SCOPE["nodes"] if n["file"] == SOURCE and n["kind"] == "black_box"
]
TEMPLATED = ["parse", "-f", "json", "case.sql"]
SLICES = ["parse", "-f", "json", "-m", "case.sql"]


def scope_gaps(case_ids: list[str], scope_ids: list[str]) -> list[str]:
    """The differences between the nodes of a case file and the nodes of the
    scope: a missing node, a node that is not in the scope, a node 2 times,
    and an order that is not the order of the scope."""
    out = [f"missing: {n}" for n in scope_ids if n not in case_ids]
    out += [f"not in the scope: {n}" for n in case_ids if n not in scope_ids]
    out += [f"2 times: {n}" for n, c in Counter(case_ids).items() if c > 1]
    if not out and case_ids != scope_ids:
        out.append("the order is not the order of the scope")
    return out


def placeholder_nodes(cases: caseformat.CaseSet) -> list[caseformat.Node]:
    return [n for n in cases.nodes if n.case_file == CASE_FILE]


# The values of the sqlfluff test, from its source.


def _value(node: ast.expr) -> Any:
    """A literal, or a dict(...) call with literal keywords, also in a list
    or a tuple."""
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "dict":
        assert not node.args
        return {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords}
    if isinstance(node, ast.List):
        return [_value(item) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_value(item) for item in node.elts)
    return ast.literal_eval(node)


def _functions() -> dict[str, ast.FunctionDef]:
    tree = ast.parse((SQLFLUFF_ROOT / SOURCE).read_text("utf8"))
    return {f.name: f for f in tree.body if isinstance(f, ast.FunctionDef)}


def _pytest_ids(ids: list[str]) -> list[str]:
    """The node ids of pytest for the ids of parametrize: an id that is in
    the list 2 or more times gets its index (flyway_var0, flyway_var1)."""
    count = Counter(ids)
    seen: Counter[str] = Counter()
    out = []
    for item in ids:
        if count[item] > 1:
            out.append(f"{item}{seen[item]}")
            seen[item] += 1
        else:
            out.append(item)
    return out


def _calls(function: ast.FunctionDef, name: str) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(function)
        if isinstance(n, ast.Call)
        and (
            getattr(n.func, "id", None) == name or getattr(n.func, "attr", None) == name
        )
    ]


def _keyword(call: ast.Call, name: str) -> ast.expr:
    return next(kw.value for kw in call.keywords if kw.arg == name)


def expected_calls() -> dict[str, list[dict[str, Any]]]:
    """{node id: [{context, in_str, templated or match}, ...]} from the
    source of the sqlfluff test: one item for each process() call."""
    functions = _functions()
    out: dict[str, list[dict[str, Any]]] = {}
    param = functions["test__templater_param_style"]
    (mark,) = param.decorator_list
    args = {kw.arg: _value(kw.value) for kw in mark.keywords}
    rows = _value(mark.args[1])
    assert _value(mark.args[0]) == "instr, param_style, expected_outstr, values"
    for node_id, (instr, style, expected, values) in zip(
        _pytest_ids(args["ids"]), rows, strict=True
    ):
        out[f"{SOURCE}::test__templater_param_style[{node_id}]"] = [
            {
                "context": {**values, "param_style": style},
                "in_str": instr,
                "templated": expected,
            }
        ]
    for name, function in functions.items():
        if name == "test__templater_param_style":
            continue
        contexts = [
            _value(_keyword(c, "override_context"))
            for c in _calls(function, "PlaceholderTemplater")
        ]
        in_strs = [_keyword(c, "in_str") for c in _calls(function, "process")]
        raises = [c for c in _calls(function, "raises") if c.func.value.id == "pytest"]
        asserts = [n for n in ast.walk(function) if isinstance(n, ast.Assert)]
        items = []
        for context, in_str in zip(contexts, in_strs, strict=True):
            item: dict[str, Any] = {"context": context}
            if isinstance(in_str, ast.Name):
                # in_str=instr: the value of the local name.
                (assign,) = [
                    a
                    for a in function.body
                    if isinstance(a, ast.Assign)
                    and [getattr(t, "id", None) for t in a.targets] == [in_str.id]
                ]
                item["in_str"] = ast.literal_eval(assign.value)
            else:
                item["in_str"] = ast.literal_eval(in_str)
            items.append(item)
        if raises:
            assert len(raises) == len(items) and not asserts, name
            for item, call in zip(items, raises, strict=True):
                assert call.args[0].id == "ValueError"
                item["match"] = _value(_keyword(call, "match"))
        else:
            (check,) = asserts
            (item,) = items
            right = check.test.comparators[0]
            if isinstance(right, ast.Name):
                # assert str(outstr) == instr: the input is the output.
                (in_str,) = in_strs
                assert isinstance(in_str, ast.Name) and right.id == in_str.id
                item["templated"] = item["in_str"]
            else:
                item["templated"] = _value(right)
        out[f"{SOURCE}::{name}"] = items
    return out


EXPECTED = expected_calls()


@pytest.fixture(scope="module")
def nodes() -> dict[str, caseformat.Node]:
    """The placeholder nodes of the checked case set, by id."""
    return {n.id: n for n in placeholder_nodes(s6scope.load_cases())}


def config_of(text: str) -> tuple[dict[str, str], dict[str, str]]:
    """The [sqlfluff] and [sqlfluff:templater:placeholder] sections of a
    .sqlfluff file, as sqlfluff reads them (the delimiter "=", as in
    sqlfluff/core/config/ini.py)."""
    parser = configparser.ConfigParser(delimiters="=", interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read_string(text)
    assert parser.sections() == ["sqlfluff", "sqlfluff:templater:placeholder"]
    return dict(parser["sqlfluff"]), dict(parser["sqlfluff:templater:placeholder"])


# The nodes of the case file.


def test_the_case_file_has_each_placeholder_node_of_the_scope():
    cases = s6scope.load_cases()
    nodes = placeholder_nodes(cases)
    assert len(SCOPE_IDS) == SCOPE["counts"]["placeholder_nodes"]["black_box"] == 26
    assert scope_gaps([n.id for n in nodes], SCOPE_IDS) == []
    assert {n.group for n in nodes} == {"placeholder"}
    # The source of the test data and its license.
    data = caseformat.load_yaml(CASE_PATH)
    assert data["source"] == {
        "project": "sqlfluff",
        "version": caseformat.SQLFLUFF_VERSION,
        "commit": caseformat.SQLFLUFF_COMMIT,
        "file": SOURCE,
    }
    assert data["license"] == "MIT"
    # The source of the test has each node of the scope.
    assert sorted(EXPECTED) == sorted(SCOPE_IDS)


def test_scope_gaps_finds_a_missing_and_an_other_node():
    ids = list(SCOPE_IDS)
    assert scope_gaps(ids[1:], SCOPE_IDS) == [f"missing: {ids[0]}"]
    extra = f"{SOURCE}::test__templater_other"
    assert scope_gaps([*ids, extra], SCOPE_IDS) == [f"not in the scope: {extra}"]
    assert scope_gaps([*ids, ids[3]], SCOPE_IDS) == [f"2 times: {ids[3]}"]
    assert scope_gaps(ids[::-1], SCOPE_IDS) == [
        "the order is not the order of the scope"
    ]


def _write(tmp_path, data, name: str = "placeholder_test.yml") -> None:
    folder = tmp_path / "core" / "templaters"
    folder.mkdir(parents=True)
    text = json.dumps(data)  # JSON is YAML.
    (folder / name).write_text(text, "utf8")


def test_a_case_file_without_a_node_fails(tmp_path):
    data = caseformat.load_yaml(CASE_PATH)
    removed = data["nodes"].pop(5)["node"]
    _write(tmp_path, data)
    cases = caseformat.load(tmp_path, None, s6scope.load())
    ids = [n.id for n in placeholder_nodes(cases)]
    assert scope_gaps(ids, SCOPE_IDS) == [f"missing: {removed}"]


def test_a_case_of_no_scope_node_fails(tmp_path):
    data = caseformat.load_yaml(CASE_PATH)
    node = copy.deepcopy(data["nodes"][0])
    node["node"] = f"{SOURCE}::test__templater_other"
    data["nodes"].append(node)
    _write(tmp_path, data)
    with pytest.raises(caseformat.CaseFormatError) as exc:
        caseformat.load(tmp_path, None, s6scope.load())
    assert "test__templater_other" in str(exc.value)


# The cases of each node.


@pytest.mark.parametrize("node_id", SCOPE_IDS)
def test_each_node_has_the_cases_of_the_templater_map(node_id, nodes):
    node = nodes[node_id]
    calls = EXPECTED[node_id]
    for case in node.cases:
        assert (case.run, case.cwd, case.stdin) == ("cli", "tmp", None)
        assert set(case.files) == {".sqlfluff", "case.sql"}
    if "match" in calls[0]:
        # A ValueError of the templater: one parse case for each call.
        assert len(node.cases) == len(calls)
        for case in node.cases:
            assert case.argv == TEMPLATED
            assert set(case.checks) == {"exit_code", "stderr"}
            assert case.checks["exit_code"] == 1
        # Each pytest.raises cites the exit code and the stderr of its case.
        assert list(node.asserts.values()) == [
            [f"{c.name}:exit_code", f"{c.name}:stderr.contains[0]"] for c in node.cases
        ]
        assert all(a.endswith(":raises") for a in node.asserts)
        return
    templated, slices = node.cases
    assert (templated.name, templated.argv) == ("templated", TEMPLATED)
    assert (slices.name, slices.argv) == ("slices", SLICES)
    assert set(templated.checks) == {"exit_code", "templated"}
    assert set(slices.checks) == {"exit_code", "source_slices"}
    assert templated.files == slices.files
    assert templated.checks["exit_code"] == slices.checks["exit_code"]
    assert list(node.asserts.values()) == [["templated:templated"]]


@pytest.mark.parametrize("node_id", SCOPE_IDS)
def test_each_case_has_the_data_of_the_sqlfluff_test(node_id, nodes):
    node = nodes[node_id]
    calls = EXPECTED[node_id]
    returned = "templated" in calls[0]
    cases = node.cases[:1] if returned else node.cases
    assert len(cases) == len(calls)
    for case, call in zip(cases, calls, strict=True):
        assert case.files["case.sql"] == call["in_str"]
        main, placeholder = config_of(case.files[".sqlfluff"])
        # The config of the call: the dialect ansi of FluffConfig(overrides=
        # {"dialect": "ansi"}). A call with no config gets the same dialect:
        # the CLI needs a dialect, and the placeholder templater does not
        # read it.
        assert main == {"dialect": "ansi", "templater": "placeholder"}
        assert placeholder == {k: str(v) for k, v in call["context"].items()}
        if returned:
            assert case.checks["templated"] == call["templated"]
        else:
            (text,) = case.checks["stderr"]["contains"]
            assert text.startswith("ValueError: ")
            assert re.search(call["match"], text), (call["match"], text)
    if returned:
        # The leaves of the source slices give the templated text. Each
        # position is in the SQL file, and no leaf starts before the start
        # of the leaf before it. (The leaves of one replacement, for example
        # "(1, 2, 3, 45)", all have the source slice of the placeholder.)
        slices = node.cases[1].checks["source_slices"]
        assert "".join(raw for raw, _, _ in slices) == calls[0]["templated"]
        size = len(calls[0]["in_str"])
        last = 0
        for _, start, end in slices:
            assert last <= start <= end <= size, (start, end)
            last = start
        assert slices[-1][2] == size


def test_the_count_of_each_kind_of_node(nodes):
    returned = [n for n in nodes.values() if "match" not in EXPECTED[n.id][0]]
    raised = [n for n in nodes.values() if "match" in EXPECTED[n.id][0]]
    assert (len(returned), len(raised)) == (24, 2)
    # 4 nodes have SQL that the ansi dialect cannot parse fully: parse gives
    # exit code 1, with the parse tree.
    unparsable = sorted(
        n.id.split("::")[1] for n in returned if n.cases[0].checks["exit_code"] == 1
    )
    assert unparsable == [
        "test__templater_param_style[ampersand]",
        "test__templater_param_style[flyway_var1]",
        "test__templater_param_style[params_not_specified]",
        "test__templater_raw",
    ]
    for node in returned:
        if node.id.split("::")[1] not in unparsable:
            assert node.cases[0].checks["exit_code"] == 0, node.id


# The python cases (T4 (each black-box python node is a case that sqlfluff
# passes and that agrees with its trace) of S6).

PY_SOURCE = "test/core/templaters/python_test.py"
PY_CASE_FILE = "core/templaters/python_test.yml"
PY_CASE_PATH = s6scope.CASES_DIR / PY_CASE_FILE
PY_SCOPE = {
    n["id"]: n
    for n in SCOPE["nodes"]
    if n["file"] == PY_SOURCE and n["kind"] == "black_box"
}
PY_IDS = list(PY_SCOPE)
PY_SECTION = "sqlfluff:templater:python:context"
LINT = ["lint", "-f", "json", "case.sql"]
TMP_START = "Failure in Python templating: "


def _s6common():
    path = REPO_ROOT / "scripts" / "s6" / "s6common.py"
    spec = importlib.util.spec_from_file_location("s6common", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


s6common = _s6common()


def python_nodes(cases: caseformat.CaseSet) -> list[caseformat.Node]:
    return [n for n in cases.nodes if n.case_file == PY_CASE_FILE]


@pytest.fixture(scope="module")
def py_nodes() -> dict[str, caseformat.Node]:
    """The python nodes of the checked case set, by id."""
    return {n.id: n for n in python_nodes(s6scope.load_cases())}


class ContextError(ValueError):
    """A context value that is not a literal of the S6 set."""


def context_value(text: str) -> Any:
    """The value that the python templater makes from the text of a context
    value: the coercion of the ini loader (sqlfluff/core/config/ini.py,
    coerce_value), then PythonTemplater.infer_type (ast.literal_eval of a
    text, else the text)."""
    for kind in (int, float):
        try:
            return kind(text)
        except ValueError:
            pass
    words = {"true": True, "false": False, "none": None}
    if text.strip().lower() in words:
        return words[text.strip().lower()]
    try:
        return ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return text


def python_context(text: str) -> dict[str, Any]:
    """The context of the python templater from a .sqlfluff file. Fail closed
    (ContextError) on a value that is not in the S6 literal set, or that has
    an object address (scripts/s6/s6common.py, runtime_needs). The S6
    literal set (s6common.literal_ok) is stricter than ast.literal_eval: a
    dict key must be a str. Thus {1: 'a'} fails closed, although
    ast.literal_eval can make it."""
    parser = configparser.ConfigParser(delimiters="=", interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read_string(text)
    if PY_SECTION not in parser:
        return {}
    context = {k: context_value(v) for k, v in parser[PY_SECTION].items()}
    errors = s6common.runtime_needs([context])
    errors += [
        f"not in the S6 literal set: {k}"
        for k, v in context.items()
        if not s6common.literal_ok(v)
    ]
    if errors:
        raise ContextError("; ".join(sorted(set(errors))))
    return context


def python_main(text: str) -> dict[str, str]:
    parser = configparser.ConfigParser(delimiters="=", interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read_string(text)
    assert set(parser.sections()) <= {"sqlfluff", PY_SECTION}
    return dict(parser["sqlfluff"])


# The values of the sqlfluff test, from its source.


def _py_value(node: ast.expr) -> Any:
    """_value, and SQLTemplaterError("text") as ("SQLTemplaterError", text)."""
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == (
        "SQLTemplaterError"
    ):
        (arg,) = node.args
        return ("SQLTemplaterError", ast.literal_eval(arg))
    if isinstance(node, ast.List):
        return [_py_value(item) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_py_value(item) for item in node.elts)
    return _value(node)


def _parametrize(function: ast.FunctionDef) -> list[dict[str, Any]]:
    (mark,) = function.decorator_list
    names = [n.strip() for n in _value(mark.args[0]).split(",")]
    return [dict(zip(names, row, strict=True)) for row in _py_value(mark.args[1])]


def _function_ids(name: str) -> list[str]:
    return [i for i in PY_IDS if i.split("::")[1].split("[")[0] == name]


def python_expected() -> dict[str, list[dict[str, Any]]]:
    """{node id: [{in_str, context, overrides, and templated or raises}, ...]}
    from the source of the sqlfluff test: one item for each process() call.
    The parametrized nodes of a function are in the order of its rows."""
    tree = ast.parse((SQLFLUFF_ROOT / PY_SOURCE).read_text("utf8"))
    functions = {f.name: f for f in tree.body if isinstance(f, ast.FunctionDef)}
    (python_string,) = [
        ast.literal_eval(a.value)
        for a in tree.body
        if isinstance(a, ast.Assign) and a.targets[0].id == "PYTHON_STRING"
    ]
    out: dict[str, list[dict[str, Any]]] = {}

    def context_of(name: str) -> Any:
        (call,) = _calls(functions[name], "PythonTemplater")
        return _value(_keyword(call, "override_context"))

    def assert_value(name: str) -> Any:
        (check,) = [n for n in ast.walk(functions[name]) if isinstance(n, ast.Assert)]
        return check.test.comparators[0]

    name = "test__templater_python"
    out[f"{PY_SOURCE}::{name}"] = [
        {
            "in_str": python_string,
            "context": context_of(name),
            "overrides": {},
            "templated": _value(assert_value(name)),
        }
    ]
    name = "test__templater_python_error"
    out[f"{PY_SOURCE}::{name}"] = [
        {
            "in_str": python_string,
            "context": context_of(name),
            "overrides": {},
            "raises": "SQLTemplaterError",
        }
    ]
    name = "test__templater_python_large_file_check"
    calls = _calls(functions[name], "process")
    configs = _calls(functions[name], "FluffConfig")
    (overrides,) = [_value(_keyword(c, "overrides")) for c in configs]
    (match,) = [
        ast.literal_eval(n.test.left)
        for n in ast.walk(functions[name])
        if isinstance(n, ast.Assert) and isinstance(n.test, ast.Compare)
    ]
    out[f"{PY_SOURCE}::{name}"] = [
        {
            "in_str": _value(_keyword(calls[0], "in_str")),
            "context": None,
            "overrides": {},
            "returns": True,
        },
        {
            "in_str": _value(_keyword(calls[1], "in_str")),
            "context": None,
            "overrides": overrides,
            "raises": "SQLFluffSkipFile",
            "match": match,
        },
    ]
    name = "test__templater_python_dot_notation_variables"
    (assign,) = [
        a
        for a in functions[name].body
        if isinstance(a, ast.Assign)
        and [getattr(t, "id", None) for t in a.targets] == ["context"]
    ]
    context = _value(assign.value)
    for node_id, row in zip(
        _function_ids(name), _parametrize(functions[name]), strict=True
    ):
        out[node_id] = [
            {
                "in_str": row["raw_str"],
                "context": context,
                "overrides": {},
                "templated": row["result"],
            }
        ]
    name = "test__templater_python_dot_notation_fail"
    (call,) = _calls(functions[name], "process")
    in_str = _value(_keyword(call, "in_str"))
    for node_id, row in zip(
        _function_ids(name), _parametrize(functions[name]), strict=True
    ):
        out[node_id] = [
            {
                "in_str": in_str,
                "context": row["context"],
                "overrides": {},
                "raises": "SQLTemplaterError",
                "match": row["error_string"],
            }
        ]
    name = "test__templater_python_ignore_templating"
    for node_id, row in zip(
        _function_ids(name), _parametrize(functions[name]), strict=True
    ):
        item = {
            "in_str": row["in_str"],
            "context": row["context"],
            "overrides": {"dialect": "ansi", "ignore": row["ignore"]},
        }
        if row["expected_violation"]:
            kind, text = row["expected_violation"]
            item.update(raises=kind, match=text)
            assert row["expected_templated_str"] is None
        else:
            item["templated"] = row["expected_templated_str"]
        out[node_id] = [item]
    return out


PY_EXPECTED = python_expected()


# The citations of each function: the result of the node gives them. The
# asserts of a branch that does not run for a parameter cite the check of
# the branch that runs (the citation check needs each assert of the test).
CITATIONS = {
    "test__templater_python": {"L21": ["templated:templated"]},
    "test__templater_python_error": {
        "L28:raises": ["missing:exit_code", "missing:violations[0]"]
    },
    "test__templater_python_large_file_check": {
        "L489:raises": ["skip:stdout.json", "skip:stderr.contains[0]"],
        "L498": ["skip:stderr.contains[0]"],
    },
    "test__templater_python_dot_notation_variables": {"L567": ["templated:templated"]},
    "test__templater_python_dot_notation_fail": {
        "L591:raises": ["missing:exit_code", "missing:violations[0]"],
        "L593": ["missing:violations[0].records[0]"],
    },
    ("test__templater_python_ignore_templating", "raises"): {
        "L698:raises": ["missing:exit_code", "missing:violations[0]"],
        "L704": ["missing:violations[0]"],
        "L705": ["missing:violations[0]"],
        "L706": ["missing:violations[0]"],
    },
    ("test__templater_python_ignore_templating", "returns"): {
        "L698:raises": ["templated:exit_code"],
        "L704": ["templated:exit_code", "templated:templated"],
        "L705": ["templated:templated"],
        "L706": ["templated:exit_code"],
    },
}


def test_the_case_file_has_each_python_node_of_the_scope():
    cases = s6scope.load_cases()
    nodes = python_nodes(cases)
    assert len(PY_IDS) == SCOPE["counts"]["python_nodes"]["black_box"] == 28
    assert scope_gaps([n.id for n in nodes], PY_IDS) == []
    assert {n.group for n in nodes} == {"python"}
    data = caseformat.load_yaml(PY_CASE_PATH)
    assert data["source"] == {
        "project": "sqlfluff",
        "version": caseformat.SQLFLUFF_VERSION,
        "commit": caseformat.SQLFLUFF_COMMIT,
        "file": PY_SOURCE,
    }
    assert data["license"] == "MIT"
    assert sorted(PY_EXPECTED) == sorted(PY_IDS)
    # The black-box nodes of the scope: 26 placeholder and 28 python nodes.
    assert len(cases.nodes) == SCOPE["counts"]["s6_black_box"] == 54


def test_a_python_case_file_without_a_node_fails(tmp_path):
    data = caseformat.load_yaml(PY_CASE_PATH)
    removed = data["nodes"].pop(7)["node"]
    _write(tmp_path, data, "python_test.yml")
    cases = caseformat.load(tmp_path, None, s6scope.load())
    ids = [n.id for n in python_nodes(cases)]
    assert scope_gaps(ids, PY_IDS) == [f"missing: {removed}"]


@pytest.mark.parametrize("node_id", PY_IDS)
def test_each_python_case_has_the_data_of_the_sqlfluff_test(node_id, py_nodes):
    node = py_nodes[node_id]
    calls = PY_EXPECTED[node_id]
    scope = PY_SCOPE[node_id]
    function = node_id.split("::")[1].split("[")[0]
    groups = []
    cases = list(node.cases)
    for call in calls:
        size = 1 if "raises" in call else 2
        groups.append(cases[:size])
        cases = cases[size:]
    assert cases == []
    assert len(scope["context"]) == len(calls)
    for i, (call, group) in enumerate(zip(calls, groups, strict=True)):
        for case in group:
            assert (case.run, case.cwd, case.stdin) == ("cli", "tmp", None)
            assert set(case.files) == {".sqlfluff", "case.sql"}
            assert case.files["case.sql"] == call["in_str"]
            assert case.files == group[0].files
            # The context of the test and of the inventory (scope.json).
            context = python_context(case.files[".sqlfluff"])
            assert context == (call["context"] or {})
            assert context == (scope["context"][i] or {})
            # The config of the call: the dialect ansi, the python templater,
            # and the overrides of FluffConfig that are not the default (an
            # empty ignore is the default).
            want = {"dialect": "ansi", "templater": "python"}
            want |= {k: str(v) for k, v in call["overrides"].items() if v != ""}
            assert python_main(case.files[".sqlfluff"]) == want
        if "raises" not in call:
            templated, slices = group
            assert (templated.name, templated.argv) == ("templated", TEMPLATED)
            assert (slices.name, slices.argv) == ("slices", SLICES)
            assert set(templated.checks) == {"exit_code", "templated"}
            assert set(slices.checks) == {"exit_code", "source_slices"}
            # The templated SQL of each node parses in the ansi dialect.
            assert templated.checks["exit_code"] == slices.checks["exit_code"] == 0
            if "templated" in call:
                assert templated.checks["templated"] == call["templated"]
            # The leaves of the source slices give the templated text, and
            # each position is in the SQL file. The leaves of one replacement
            # are not always in order: for "{foo.bar!r:>10}" sqlfluff 4.4.0
            # gives the leaf "  " 8 to 22 and the leaf "'foobar'" 7 to 22.
            leaves = slices.checks["source_slices"]
            assert "".join(raw for raw, _, _ in leaves) == templated.checks["templated"]
            for _, start, end in leaves:
                assert 0 <= start <= end <= len(call["in_str"]), (start, end)
            assert leaves[-1][2] == len(call["in_str"])
        elif call["raises"] == "SQLTemplaterError":
            (case,) = group
            assert (case.name, case.argv) == ("missing", LINT)
            assert case.checks["exit_code"] == 1
            (check,) = case.checks["violations"]
            assert check["select"] == {"code": "TMP"}
            (record,) = check["records"]
            assert list(record) == ["description"]
            text = record["description"]["contains"]
            if "match" in call:
                # The error_string of the test, or the message of the
                # expected SQLTemplaterError.
                assert text == call["match"]
            else:
                assert text.startswith(TMP_START)
        else:
            (case,) = group
            assert call["raises"] == "SQLFluffSkipFile"
            assert (case.name, case.argv) == ("skip", TEMPLATED)
            assert case.checks["exit_code"] == 0
            assert case.checks["stdout"] == {
                "json": [{"filepath": "case.sql", "segments": None}]
            }
            (text,) = case.checks["stderr"]["contains"]
            assert call["match"] in text
    key: Any = function
    if function == "test__templater_python_ignore_templating":
        key = (function, "raises" if "raises" in calls[0] else "returns")
    assert node.asserts == CITATIONS[key]


def test_the_count_of_each_kind_of_python_call(py_nodes):
    kinds = Counter(c.get("raises", "returns") for i in PY_IDS for c in PY_EXPECTED[i])
    # 4 nodes raise a SQLTemplaterError (the design record, "Black-box form").
    assert kinds == {"returns": 24, "SQLTemplaterError": 4, "SQLFluffSkipFile": 1}
    assert sum(len(n.cases) for n in py_nodes.values()) == 24 * 2 + 4 + 1


# The context values: literals only.


def test_each_python_context_value_is_a_literal(py_nodes):
    values = []
    for node in py_nodes.values():
        for case in node.cases:
            values += python_context(case.files[".sqlfluff"]).values()
    types = {type(v).__name__ for v in values}
    assert types == {"str", "int", "dict"}
    assert s6common.runtime_needs([dict(enumerate(values))]) == []


def _context_file(*lines: str) -> str:
    body = "".join(f"{line}\n" for line in lines)
    return f"[sqlfluff]\ndialect = ansi\ntemplater = python\n\n[{PY_SECTION}]\n{body}"


def test_python_context_reads_the_values_as_sqlfluff_does():
    assert python_context(_context_file()) == {}
    assert python_context(
        _context_file(
            "a = foo",
            "b = 123",
            "c = 1.5",
            "d = True",
            "e = none",
            "f = {'x.y': 'café', 'n': 42}",
            "g = [1, 'a']",
            "h = 'quoted'",
        )
    ) == {
        "a": "foo",
        "b": 123,
        "c": 1.5,
        "d": True,
        "e": None,
        "f": {"x.y": "café", "n": 42},
        "g": [1, "a"],
        "h": "quoted",
    }


@pytest.mark.parametrize(
    "line,error",
    [
        # ast.literal_eval can make these 2 values. The S6 literal set
        # (s6common.literal_ok) accepts only str dict keys, so they fail.
        ("x = {1: 'a'}", "not in the S6 literal set: x"),
        ("x = {'a': {1: 'b'}}", "not in the S6 literal set: x"),
        # These 2 values have a text with an object address.
        ("x = <object at 0x7f3a12345678>", "object address: input0.x"),
        ("x = {'a': '<f at 0x7f3a12345678>'}", "object address: input0.x.a"),
    ],
)
def test_python_context_fails_closed_on_another_value(line, error):
    with pytest.raises(ContextError) as exc:
        python_context(_context_file(line))
    assert error in str(exc.value)


def test_a_changed_context_value_fails(py_nodes):
    node_id = f"{PY_SOURCE}::test__templater_python"
    case = py_nodes[node_id].cases[0]
    changed = case.files[".sqlfluff"].replace("blah = foo", "blah = {1: 'foo'}")
    assert changed != case.files[".sqlfluff"]
    with pytest.raises(ContextError):
        python_context(changed)
    changed = case.files[".sqlfluff"].replace("blah = foo", "blah = bar")
    assert python_context(changed) != PY_EXPECTED[node_id][0]["context"]
