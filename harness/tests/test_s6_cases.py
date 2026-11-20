"""The placeholder cases of S6 (templater parity: sqll passes 100% of the
placeholder and Python format-string templater fixtures that do not need a
Python runtime).

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

The trace oracle (scripts/s7-tests/oracle --scope s6) is the proof that
each case agrees with the trace of its node.
"""

import ast
import configparser
import copy
import json
import re
from collections import Counter
from typing import Any

import pytest

from sqll_harness.paths import SQLFLUFF_ROOT
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


def _write(tmp_path, data) -> None:
    folder = tmp_path / "core" / "templaters"
    folder.mkdir(parents=True)
    text = json.dumps(data)  # JSON is YAML.
    (folder / "placeholder_test.yml").write_text(text, "utf8")


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
