"""The checks of the S7 trace oracle (docs/decisions/s7-tests-design.md,
"Trace oracle").

scripts/s7-tests/trace-nodes runs the original pytest nodes with the pinned
sqlfluff (or with sqlfluff[rs]) and records each CLI call, simple-API call,
and Linter path call with its inputs and outputs. This module reads that
trace only; sqlfluff is not a module of the harness. For each tool it checks:

1. The inputs of each case are the traced inputs of its call (case i is
   traced call i of the node).
2. The checks of each case, on the traced outputs, give the pytest outcome
   of the node: pass if the node passed, fail if it failed.
3. The pytest outcome of each node is the status of the node in the runner
   report.
4. A check of a case cites each assert of the source test (asserts.py), or
   the not-reproduced record has it. The record can have no row before the
   pointer section of harness/not-reproduced.md exists (decision 4).

A node of the class python-internal must pass and have no traced CLI or
simple-API call. The oracle fails closed (an error, not a status) on a
process that it cannot trace, on an untraced call, on a call or a node
outside the requested nodes, on a node that the report has and the trace
does not, and on an input that it cannot map to a case.
"""

import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..cases import FAIL, PASS
from ..paths import REPO_ROOT
from .asserts import AssertSourceError, find_asserts
from .caseformat import SQLFLUFF_VERSION, Case, Node
from .runner import (
    API_DIALECT,
    CheckFailed,
    check_violations,
    cli_violations,
    match_text,
)

KIND = "sqll-s7-tests-oracle"
FORMAT = 1
TRACE_KIND = "sqll-s7-tests-trace"
TRACE_FORMAT = 1
TOOLS = ("sqlfluff", "sqlfluff-rs")
RUST_TOOL = "sqlfluff-rs"
INTERNAL = "python-internal"
ROOT_MARK = "{sqlfluff}"
OUTCOMES = {"passed": PASS, "failed": FAIL}
NOT_REPRODUCED = REPO_ROOT / "docs" / "decisions" / "s7-tests-not-reproduced.md"
HARNESS_NOT_REPRODUCED = REPO_ROOT / "harness" / "not-reproduced.md"
# The section of harness/not-reproduced.md that makes the S7 record a part
# of the record of PROCESS.md rule 7 (decision 4).
POINTER_SECTION = "## S7 test conversion"
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|(.+)\|\s*$")


class OracleError(Exception):
    """The oracle cannot map a traced call to a case, or a check to an
    output."""


@dataclass
class Record:
    """A row of the not-reproduced record: an assert that no check cites."""

    node: str
    assert_id: str
    reason: str


@dataclass
class NotReproduced:
    records: list[Record]
    pointer: bool  # harness/not-reproduced.md points to the record
    errors: list[str] = field(default_factory=list)


def load_not_reproduced(
    path: Path = NOT_REPRODUCED, harness_file: Path = HARNESS_NOT_REPRODUCED
) -> NotReproduced:
    """Read the rows of the "## Records" section. A line of the section that
    starts with "|" and is not the header, the rule, or a row of 3 cells is
    an error."""
    text = path.read_text(encoding="utf8")
    errors = []
    records = []
    lines = text.splitlines()
    try:
        start = lines.index("## Records") + 1
    except ValueError:
        errors.append(f"{path.name}: no '## Records' section")
        start = len(lines)
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        if line.startswith("| Node |") or set(line) <= set("|- "):
            continue
        match = _ROW.match(line)
        if match is None:
            errors.append(f"{path.name}: not a record row: {line}")
            continue
        records.append(Record(match[1], match[2], match[3].strip()))
    pointer = has_pointer(harness_file.read_text(encoding="utf8"), path.name)
    return NotReproduced(records, pointer, errors)


def has_pointer(text: str, name: str) -> bool:
    """True if the text has the section POINTER_SECTION with a Markdown link
    to the record file name (decision 4)."""
    lines = text.splitlines()
    if POINTER_SECTION not in lines:
        return False
    body = []
    for line in lines[lines.index(POINTER_SECTION) + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    link = re.compile(r"\]\(([^)\s]*/)?" + re.escape(name) + r"\)")
    return link.search(" ".join(body)) is not None


# Inputs.


def case_inputs(case: Case) -> dict[str, Any]:
    """The inputs of a case, in the form of the traced inputs."""
    if case.run == "cli":
        return {
            "run": "cli",
            "argv": list(case.argv),
            "stdin": case.stdin or "",
            "cwd": case.cwd,
            "files": dict(case.files),
        }
    return {
        "run": "api",
        "function": case.function,
        "sql": case.sql,
        "dialect": case.dialect or API_DIALECT,
        "rules": case.rules,
        "exclude_rules": case.exclude_rules,
        "config": case.config,
    }


def _linter_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """A Linter path call as the CLI case that it is: "lint -f json PATH...".

    The mapping holds only for a Linter made with
    FluffConfig.from_path(<folder of the path>) and no other argument, and
    for a path method with no option. Else OracleError.
    """
    paths = inputs["paths"]
    if inputs["options"]:
        raise OracleError(f"Linter.{inputs['method']} options {inputs['options']}")
    linter = inputs["linter"] or {}
    others = {k: v for k, v in linter.items() if k != "config" and v is not None}
    if others:
        raise OracleError(f"Linter arguments {sorted(others)} other than config")
    source = linter.get("config") or {}
    folder = (source.get("args") or {}).get("path")
    if source.get("method") != "from_path" or set(source["args"]) != {"path"}:
        raise OracleError(
            f"a Linter config from {source}; the oracle maps only"
            " FluffConfig.from_path(<folder>)"
        )
    if len(paths) != 1 or posixpath.dirname(paths[0]) != folder:
        raise OracleError(
            f"Linter config from_path({folder!r}) is not the folder of {paths}"
        )
    return {
        "run": "cli",
        "argv": ["lint", "-f", "json", *paths],
        "stdin": "",
        "cwd": "sqlfluff" if inputs["cwd"] == ROOT_MARK else inputs["cwd"],
        "files": {},
    }


def call_inputs(call: dict[str, Any]) -> dict[str, Any]:
    """The inputs of a traced call, in the form of case_inputs."""
    if "inputs_error" in call:
        raise OracleError(
            f"the trace could not read the inputs: {call['inputs_error']}"
        )
    inputs = call["inputs"]
    kind = call["kind"]
    if kind == "cli":
        if inputs["unsupported"]:
            raise OracleError("; ".join(inputs["unsupported"]))
        return {
            "run": "cli",
            "argv": inputs["argv"],
            "stdin": inputs["stdin"] or "",
            "cwd": "sqlfluff" if inputs["cwd"] == ROOT_MARK else inputs["cwd"],
            "files": {},
        }
    if kind == "linter":
        return _linter_inputs(inputs)
    if kind == "api":
        if inputs["cwd"] != ROOT_MARK:
            raise OracleError(f"a simple-API call in the folder {inputs['cwd']}")
        for key in ("config", "config_path", "fix_even_unparsable"):
            if inputs.get(key) is not None:
                raise OracleError(
                    f"simple-API argument {key}={inputs[key]!r}; the oracle"
                    " maps only the default"
                )
        return {
            "run": "api",
            "function": inputs["function"],
            "sql": inputs["sql"],
            "dialect": inputs["dialect"] or API_DIALECT,
            "rules": inputs["rules"],
            "exclude_rules": inputs["exclude_rules"],
            "config": None,
        }
    raise OracleError(f"a traced call of the unknown kind {kind!r}")


def input_differences(case: Case, call: dict[str, Any]) -> list[str]:
    want = case_inputs(case)
    got = call_inputs(call)
    return [
        f"{key}: the case gives {want.get(key)!r}, the trace {got.get(key)!r}"
        for key in sorted(set(want) | set(got))
        if want.get(key) != got.get(key)
    ]


# Outputs.


def failed_checks(case: Case, call: dict[str, Any]) -> list[str]:
    """The checks of a case that fail on the traced outputs of its call."""
    if "raised" in call:
        return [f"the call raised {call['raised']}"]
    if "outputs_error" in call:
        raise OracleError(
            f"the trace could not read the outputs: {call['outputs_error']}"
        )
    outputs = call["outputs"]
    checks = case.checks
    failed: list[str] = []
    if case.run == "api":
        if case.function == "fix":
            if outputs != checks["fixed"]:
                failed.append(f"fixed: the text is {outputs!r}")
            return failed
        for i, check in enumerate(checks["violations"]):
            failed += check_violations(f"violations[{i}]", outputs, check)
        return failed
    if case.cwd != "sqlfluff" or "files" in checks:
        raise OracleError("a files check; the trace has no files")
    if outputs["exit_code"] != checks["exit_code"]:
        failed.append(f"exit_code: {outputs['exit_code']}, not {checks['exit_code']}")
    if call["kind"] == "linter":
        for stream in ("stdout", "stderr"):
            if stream in checks:
                raise OracleError(f"a {stream} check; a Linter call has no {stream}")
        stdout = json.dumps(outputs["records"])
    else:
        if "exception" in outputs:
            failed.append(f"the command raised {outputs['exception']}")
        stdout = outputs["stdout"]
        for stream in ("stdout", "stderr"):
            if stream in checks:
                failed += match_text(stream, outputs[stream], checks[stream])
    for i, check in enumerate(checks.get("violations", [])):
        try:
            found = cli_violations(stdout, check.get("file"))
        except CheckFailed as exc:
            failed.append(f"violations[{i}]: {exc}")
            continue
        failed += check_violations(f"violations[{i}]", found, check)
    return failed


# Nodes.


@dataclass
class NodeResult:
    id: str
    pytest: str
    trace: str | None
    report: str | None
    cases: list[dict[str, str]] = field(default_factory=list)
    asserts: int = 0
    not_reproduced: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pytest": self.pytest,
            "trace": self.trace,
            "report": self.report,
            "cases": self.cases,
            "asserts": self.asserts,
            "not_reproduced": self.not_reproduced,
            "errors": self.errors,
        }


def _trace_errors(data: dict[str, Any]) -> list[str]:
    """A process, an untraced call, or a call input that the trace could not
    read."""
    out = [f"starts a process: {p}" for p in data["processes"]]
    out += [f"an untraced call: {u}" for u in data["untraced"]]
    return out


def check_asserts(
    node: Node, source_root: Path, records: list[Record]
) -> tuple[int, int, list[str]]:
    """(asserts, not reproduced, errors) of check 4 for one node."""
    try:
        found = {a.id for a in find_asserts(source_root, node.id)}
    except (AssertSourceError, OSError, SyntaxError) as exc:
        return 0, 0, [f"the asserts of the source test: {exc}"]
    errors = []
    recorded = {r.assert_id for r in records if r.node == node.id}
    for aid in sorted(found - set(node.asserts) - recorded):
        errors.append(f"assert {aid}: no check cites it and no record has it")
    for aid in sorted(set(node.asserts) - found):
        errors.append(f"cites {aid}, which is not an assert of the source test")
    for aid in sorted(recorded - found):
        errors.append(f"a not-reproduced record of {aid}, not an assert of the test")
    for aid in sorted(recorded & set(node.asserts)):
        errors.append(f"assert {aid}: a check cites it and a record has it")
    return len(found), len(recorded & found), errors


def record_errors(converted: set[str], not_reproduced: NotReproduced) -> list[str]:
    """The errors of the not-reproduced record as a whole: a row that the
    loader cannot read, a row before the pointer section of
    harness/not-reproduced.md (decision 4), a row of a node that is not
    converted."""
    errors = list(not_reproduced.errors)
    if not_reproduced.records and not not_reproduced.pointer:
        errors.append(
            f"{len(not_reproduced.records)} not-reproduced records, but"
            f" {HARNESS_NOT_REPRODUCED.name} has no pointer section to"
            f" {NOT_REPRODUCED.name} (decision 4); no case may use"
            " a record before it"
        )
    for record in not_reproduced.records:
        if record.node not in converted:
            errors.append(
                f"a not-reproduced record of {record.node}, not a converted node"
            )
    return errors


def coverage_errors(
    nodes: list[Node], source_root: Path, not_reproduced: NotReproduced
) -> list[str]:
    """Check 4 with no trace: a check cites each assert of the source test of
    each converted node, or a row of the not-reproduced record has it. Also
    the errors of the record as a whole. The harness runs it before the S7
    cases."""
    errors = record_errors({n.id for n in nodes}, not_reproduced)
    for node in nodes:
        _, _, node_errors = check_asserts(node, source_root, not_reproduced.records)
        errors += [f"{node.id}: {e}" for e in node_errors]
    return errors


def check_node(
    node: Node,
    data: dict[str, Any] | None,
    report_status: str | None,
    source_root: Path,
    records: list[Record],
) -> NodeResult:
    if data is None:
        return NodeResult(
            node.id, "no trace", None, report_status, errors=["not in the trace"]
        )
    result = NodeResult(node.id, data["outcome"], None, report_status)
    result.errors += _trace_errors(data)
    calls = data["calls"]
    pytest_status = OUTCOMES.get(data["outcome"])
    if pytest_status is None:
        result.errors.append(f"the pytest outcome is {data['outcome']}")
    statuses = []
    for case, call in zip(node.cases, calls, strict=False):
        try:
            diff = input_differences(case, call)
            if diff:
                result.errors += [f"case {case.name}: input {d}" for d in diff]
                continue
            failed = failed_checks(case, call)
        except OracleError as exc:
            result.errors.append(f"case {case.name}: {exc}")
            continue
        status = FAIL if failed else PASS
        statuses.append(status)
        result.cases.append(
            {"name": case.name, "status": status, "reason": "; ".join(failed)}
        )
    if len(calls) > len(node.cases):
        result.errors.append(
            f"{len(calls)} traced calls, {len(node.cases)} cases: a call has no case"
        )
    elif len(calls) < len(node.cases):
        # A failed node can stop before its last calls. Then a traced case
        # must fail, so that the failure is a failure of a check.
        missing = [c.name for c in node.cases[len(calls) :]]
        if pytest_status == FAIL and FAIL in statuses:
            result.cases += [
                {"name": n, "status": "not traced", "reason": "the node stopped"}
                for n in missing
            ]
        else:
            result.errors.append(f"cases with no traced call: {missing}")
    if not result.errors:
        result.trace = FAIL if FAIL in statuses else PASS
        if result.trace != pytest_status:
            result.errors.append(
                f"check 2: the checks on the traced outputs give {result.trace},"
                f" pytest gives {data['outcome']}"
            )
        if report_status != pytest_status:
            result.errors.append(
                f"check 3: the report gives {report_status}, pytest gives"
                f" {data['outcome']}"
            )
    asserts, not_reproduced, errors = check_asserts(node, source_root, records)
    result.asserts, result.not_reproduced = asserts, not_reproduced
    result.errors += errors
    return result


def check_internal(node_id: str, data: dict[str, Any] | None) -> dict[str, Any]:
    """A python-internal node must pass with no traced CLI or simple-API
    call."""
    if data is None:
        return {
            "id": node_id,
            "pytest": "no trace",
            "calls": {},
            "errors": ["not in the trace"],
        }
    errors = _trace_errors(data)
    calls: dict[str, int] = {}
    for call in data["calls"]:
        calls[call["kind"]] = calls.get(call["kind"], 0) + 1
    for kind in ("cli", "api"):
        if calls.get(kind):
            errors.append(
                f"class {INTERNAL}, but the trace has {calls[kind]} {kind} calls"
            )
    if data["outcome"] != "passed":
        errors.append(
            f"the pytest outcome is {data['outcome']}; the trace of a node that"
            " does not pass can be incomplete"
        )
    return {"id": node_id, "pytest": data["outcome"], "calls": calls, "errors": errors}


def trace_errors(trace: dict[str, Any], tool: str, requested: list[str]) -> list[str]:
    """The checks of the trace as a whole."""
    errors = []
    if trace.get("kind") != TRACE_KIND or trace.get("format") != TRACE_FORMAT:
        return [f"not a trace of format {TRACE_FORMAT}"]
    if trace["sqlfluff"] != SQLFLUFF_VERSION:
        errors.append(f"the trace is of sqlfluff {trace['sqlfluff']}")
    rust = tool == RUST_TOOL
    if trace["rust"] != rust or (trace["sqlfluffrs"] is None) == rust:
        errors.append(f"the trace is not of the tool {tool}")
    if rust:
        runs = trace["parse_runs"] or {}
        if runs.get("Parser", 0) or not runs.get("RustParser", 0):
            errors.append(f"--rust: the parse runs are {runs}")
    if trace["root_config"]:
        errors.append(
            f"the sqlfluff root has a sqlfluff config {trace['root_config']}; the"
            " simple-API cases do not give it"
        )
    for name, error in trace["collection_errors"].items():
        errors.append(f"collection error: {name}: {error}")
    outside = trace["outside"]
    for key in ("calls", "untraced", "processes"):
        if outside[key]:
            errors.append(
                f"{len(outside[key])} {key} outside the nodes: {outside[key]}"
            )
    extra = sorted(set(trace["nodes"]) - set(requested))
    if extra:
        errors.append(f"nodes that the oracle did not ask for: {extra}")
    return errors


def requested_nodes(report: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(converted, python-internal) node ids of a runner report."""
    converted = [n["id"] for n in report["nodes"]]
    internal = [e["id"] for e in report["excluded"] if e["class"] == INTERNAL]
    return converted, internal


def check_tool(
    tool: str,
    trace: dict[str, Any],
    nodes: list[Node],
    report: dict[str, Any],
    source_root: Path,
    not_reproduced: NotReproduced,
) -> dict[str, Any]:
    """Check the trace of one tool. The result has "errors" (all errors, by
    node); the oracle agrees only if it is empty."""
    converted, internal = requested_nodes(report)
    errors = trace_errors(trace, tool, converted + internal)
    by_id = {n.id: n for n in nodes}
    if sorted(by_id) != sorted(converted):
        errors.append(
            "the report is not of the case files: nodes only in the report"
            f" {sorted(set(converted) - set(by_id))}, only in the case files"
            f" {sorted(set(by_id) - set(converted))}"
        )
    status = {
        n["id"]: n["results"].get(tool, {}).get("status") for n in report["nodes"]
    }
    traced = trace.get("nodes", {})
    results = [
        check_node(
            by_id[i], traced.get(i), status.get(i), source_root, not_reproduced.records
        )
        for i in converted
        if i in by_id
    ]
    internals = [check_internal(i, traced.get(i)) for i in internal]
    errors += record_errors(set(by_id), not_reproduced)
    for item in [*results, *internals]:
        node_errors = item.errors if isinstance(item, NodeResult) else item["errors"]
        node_id = item.id if isinstance(item, NodeResult) else item["id"]
        errors += [f"{node_id}: {e}" for e in node_errors]
    agree = sum(1 for r in results if not r.errors)
    return {
        "tool": tool,
        "sqlfluff": trace.get("sqlfluff"),
        "sqlfluffrs": trace.get("sqlfluffrs"),
        "nodes": [r.as_dict() for r in results],
        "python_internal": internals,
        "counts": {
            "nodes": len(results),
            "agree": agree,
            "pass": sum(1 for r in results if not r.errors and r.trace == PASS),
            "fail": sum(1 for r in results if not r.errors and r.trace == FAIL),
            "python_internal": len(internals),
            "asserts": sum(r.asserts for r in results),
            "not_reproduced": sum(r.not_reproduced for r in results),
        },
        "errors": errors,
    }


def build(
    by_tool: dict[str, dict[str, Any]], not_reproduced: NotReproduced
) -> dict[str, Any]:
    return {
        "kind": KIND,
        "format": FORMAT,
        "not_reproduced": {
            "records": len(not_reproduced.records),
            "pointer": not_reproduced.pointer,
        },
        "tools": by_tool,
    }
