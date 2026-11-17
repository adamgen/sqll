"""The checks of the S7 trace oracle (docs/decisions/s7-tests-design.md,
"Trace oracle").

scripts/s7-tests/trace-nodes runs the original pytest nodes with the pinned
sqlfluff (or with sqlfluff[rs]) and records each CLI call, simple-API call,
Linter path call, and Linter string call with its inputs and outputs. This
module reads that trace only; sqlfluff is not a module of the harness.
map_call gives the cases of each traced call (the maps of the design
record). For each tool it checks:

1. The inputs of each case are the inputs of its case of the traced calls,
   in order.
2. The checks of each case, on the traced outputs, give the pytest outcome
   of the node: pass if the node passed, fail if it failed.
3. The pytest outcome of each node is the status of the node in the runner
   report.
4. A check of a case cites each assert of the source test (asserts.py), or
   the not-reproduced record has it. The record can have no row before the
   pointer section of harness/not-reproduced.md exists (decision 4).

The templater map (S6, templater parity; docs/decisions/s6-templaters.md,
"Black-box form"; trace-nodes --templaters) gives the CLI cases of a
process() call of the placeholder or python templater: the SQL file
case.sql and the .sqlfluff file of the context and the config. The trace
runs these cases and proves that the templater result of each run is the
result of the call.

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
from pathlib import Path, PurePosixPath
from typing import Any

from ..cases import FAIL, PASS
from ..paths import REPO_ROOT
from .asserts import AssertSourceError, find_asserts
from .caseformat import SQLFLUFF_VERSION, TMP_MARK, Case, Node
from .runner import (
    API_DIALECT,
    CheckFailed,
    check_files,
    check_violations,
    cli_violations,
    match_text,
    tree_failures,
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

# The .sqlfluff file of a case that maps a Linter string call, and the names
# of the files that the CLI reads as config or ignore files in a folder.
CONFIG_FILE = ".sqlfluff"
CONFIG_FILES = frozenset(
    {".sqlfluff", "setup.cfg", "tox.ini", "pyproject.toml", ".sqlfluffignore"}
)
# The file name of a Linter string call with no name, and the name that the
# CLI gives to stdin.
STRING_FNAME = "<string input>"
STDIN_FNAME = "stdin"
# The options of a Linter string method that the map allows: only these
# values (and any fix).
STRING_OPTIONS = {
    "lint_string": {"fname": STRING_FNAME, "config": None, "encoding": "utf8"},
    "lint_string_wrapped": {"fname": STRING_FNAME, "stdin_filename": None},
}
# The lint options that give an override of a Linter config to a Linter path
# call (sqlfluff.cli.commands.get_config: the options are overrides).
OVERRIDE_OPTIONS = {
    "dialect": "--dialect",
    "rules": "--rules",
    "exclude_rules": "--exclude-rules",
}


@dataclass
class Mapped:
    """One case of a traced call: the case inputs, and the outputs in the
    form that failed_checks reads. A cli case has the outputs exit_code,
    stdout, stderr, records (the lint records, if not from stdout), files
    (the files of the temporary folder after the call), and exception.

    A case of a templater call that returned also has: required, the parse
    tree check that the case must have ("templated" or "source_slices"),
    and templated, the templated text that the call returned. The value of
    a "templated" check must be that text."""

    what: str
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None = None
    raised: str | None = None
    outputs_error: str | None = None
    required: str | None = None
    templated: str | None = None


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


def _mapped(what: str, call: dict[str, Any], inputs: dict[str, Any], outputs):
    """A Mapped case; outputs(call outputs) gives its outputs."""
    item = Mapped(what, inputs, raised=call.get("raised"))
    item.outputs_error = call.get("outputs_error")
    if "outputs" in call:
        item.outputs = outputs(call["outputs"])
    return item


def _linter_args(linter: dict[str, Any] | None) -> None:
    others = {
        k: v for k, v in (linter or {}).items() if k != "config" and v is not None
    }
    if others:
        raise OracleError(f"Linter arguments {sorted(others)} other than config")


def _cli_outputs(out: dict[str, Any]) -> dict[str, Any]:
    return {
        "exit_code": out["exit_code"],
        "stdout": out["stdout"],
        "stderr": out["stderr"],
        "records": None,
        "files": out.get("files"),
        "exception": out.get("exception"),
    }


def _cli(call: dict[str, Any]) -> list[Mapped]:
    """A CLI call. In the sqlfluff root it is a cwd: sqlfluff case. With a
    temporary folder of the node (in an argument or as the working folder)
    it is a cwd: tmp case with the files of the folder."""
    inputs = call["inputs"]
    if inputs["unsupported"]:
        raise OracleError("; ".join(inputs["unsupported"]))
    cwd = inputs["cwd"]
    mapped = {
        "run": "cli",
        "argv": inputs["argv"],
        "stdin": inputs["stdin"] or "",
        "cwd": "sqlfluff" if cwd == ROOT_MARK else cwd,
        "files": {},
    }
    tmp = inputs.get("tmp")
    if tmp is not None:
        if tmp["outer_config"]:
            raise OracleError(
                "a folder above the temporary folder has a sqlfluff config"
                f" {tmp['outer_config']}"
            )
        if cwd == ROOT_MARK:
            # The CLI reads a config file in the working folder for each
            # file, and a config file in another folder only for the files
            # in it. Thus the temporary folder must not have one.
            configs = sorted(
                n for n in tmp["files"] if PurePosixPath(n).name in CONFIG_FILES
            )
            if configs:
                raise OracleError(
                    f"the temporary folder has the config or ignore files {configs};"
                    " the case runs in the folder, the call did not"
                )
            if tmp["cwd_paths"]:
                raise OracleError(
                    f"the arguments {tmp['cwd_paths']} are paths in the sqlfluff"
                    " root; the case runs in the temporary folder"
                )
        elif cwd != TMP_MARK:
            raise OracleError(f"a CLI call in the folder {cwd} with a temporary folder")
        mapped["cwd"] = "tmp"
        mapped["files"] = dict(tmp["files"])
    return [_mapped("CLI call", call, mapped, _cli_outputs)]


def _linter_path(call: dict[str, Any]) -> list[Mapped]:
    """A Linter path call as the CLI case that it is: "lint -f json PATH...".

    The mapping holds for a Linter made with
    FluffConfig.from_path(<folder of the path>) and no other argument, or
    with a config from overrides only (the overrides become lint options),
    and for a path method with no option. Else OracleError.
    """
    inputs = call["inputs"]
    paths = inputs["paths"]
    if inputs["options"]:
        raise OracleError(f"Linter.{inputs['method']} options {inputs['options']}")
    linter = inputs["linter"] or {}
    _linter_args(linter)
    source = linter.get("config") or {}
    options: list[str] = []
    if source.get("method") == "from_path" and set(source["args"]) == {"path"}:
        folder = source["args"]["path"]
        if len(paths) != 1 or posixpath.dirname(paths[0]) != folder:
            raise OracleError(
                f"Linter config from_path({folder!r}) is not the folder of {paths}"
            )
    elif "overrides" in inputs and source.get("method") != "from_path":
        options = _override_options(inputs["overrides"])
    else:
        raise OracleError(
            f"a Linter config from {source}; the oracle maps only"
            " FluffConfig.from_path(<folder>) and a config from overrides"
        )
    mapped = {
        "run": "cli",
        "argv": ["lint", "-f", "json", *options, *paths],
        "stdin": "",
        "cwd": "sqlfluff" if inputs["cwd"] == ROOT_MARK else inputs["cwd"],
        "files": {},
    }

    def outputs(out: dict[str, Any]) -> dict[str, Any]:
        return {
            "exit_code": out["exit_code"],
            "stdout": None,
            "stderr": None,
            "records": out["records"],
            "files": None,
        }

    return [_mapped("Linter call", call, mapped, outputs)]


def _override_options(model: dict[str, Any]) -> list[str]:
    """The lint options of the overrides of a Linter config. The trace
    proves that the config is FluffConfig(overrides=<them>)."""
    if model["extra_config_path"] is not None or model["ignore_local_config"]:
        raise OracleError(
            "a Linter config with extra_config_path or ignore_local_config"
        )
    if model["proof"]:
        raise OracleError(
            "the Linter config is not FluffConfig(overrides=<its overrides>):"
            f" the keys {model['proof']} are different"
        )
    values = model["values"]
    unknown = sorted(set(values) - set(OVERRIDE_OPTIONS))
    if unknown:
        raise OracleError(
            f"the overrides {unknown}; the map knows only {list(OVERRIDE_OPTIONS)}"
        )
    options = []
    for key, option in OVERRIDE_OPTIONS.items():
        if key in values:
            if not isinstance(values[key], str) or not values[key]:
                raise OracleError(f"the override {key}={values[key]!r} is not a text")
            options += [option, values[key]]
    return options


def _stdin_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(records) != 1 or records[0]["filepath"] != STRING_FNAME:
        raise OracleError(f"{len(records)} lint records, not 1 of {STRING_FNAME!r}")
    return [{**records[0], "filepath": STDIN_FNAME}]


def _without_fixes(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [
        [
            {k: v for k, v in violation.items() if k != "fixes"}
            for violation in r["violations"]
        ]
        for r in records
    ]


def _linter_string(
    call: dict[str, Any], parts: tuple[str, ...]
) -> list[Mapped | OracleError]:
    """A Linter string call (Linter.lint_string, lint_string_wrapped) as CLI
    cases on stdin in a temporary folder with the .sqlfluff file of the
    config model. parts: "lint" ("lint -f json -") and "fix" ("fix -")."""
    inputs = call["inputs"]
    method = inputs["method"]
    if method not in STRING_OPTIONS:
        raise OracleError(f"the Linter method {method!r}")
    _linter_args(inputs["linter"])
    options = dict(inputs["options"])
    fix = options.pop("fix")
    if not isinstance(fix, bool):
        raise OracleError(f"Linter.{method} fix={fix!r}")
    allowed = STRING_OPTIONS[method]
    for key, value in options.items():
        if key not in allowed or allowed[key] != value:
            raise OracleError(
                f"Linter.{method} option {key}={value!r}; the oracle maps only"
                " the default"
            )
    if inputs["cwd"] != ROOT_MARK:
        raise OracleError(f"a Linter string call in the folder {inputs['cwd']}")
    if inputs["config_changed"]:
        raise OracleError("the config of the Linter changed after the Linter was made")
    model = inputs["config_file"]
    if "error" in model:
        raise OracleError(f"the config of the Linter: {model['error']}")
    if inputs["config_proof"]:
        raise OracleError(
            f"the CLI config from the {CONFIG_FILE} file is not the config of the"
            f" Linter: the keys {inputs['config_proof']} are different"
        )
    sql = inputs["sql"]
    if "\r" in sql:
        raise OracleError("the SQL has a carriage return; the CLI reads stdin as text")
    files = {CONFIG_FILE: model["text"]} if model["text"] else {}
    base = {"run": "cli", "stdin": sql, "cwd": "tmp", "files": files}

    def lint_outputs(out: dict[str, Any]) -> dict[str, Any]:
        lint = out["lint"] if fix else out
        if fix and _without_fixes(out["records"]) != _without_fixes(lint["records"]):
            raise OracleError(
                "the violations of the fix run are not the violations of a lint"
                " run; the lint command cannot show them"
            )
        return {
            "exit_code": 1 if lint["violations"] > 0 else 0,
            "stdout": None,
            "stderr": None,
            "records": _stdin_records(lint["records"]),
            "files": files,
        }

    def fix_outputs(out: dict[str, Any]) -> dict[str, Any]:
        # sqlfluff.cli.commands._stdin_fix with no templater or parse error.
        if out["tmp_prs"]:
            raise OracleError(
                f"{out['tmp_prs']} templater or parse errors; the fix command"
                " does not apply the fixes"
            )
        return {
            "exit_code": 1 if out["unfixable"] else 0,
            "stdout": out["fixed"] if out["fixable"] else sql,
            "stderr": None,
            "records": None,
            "files": files,
        }

    out: list[Mapped | OracleError] = []
    for part in parts:
        if part == "fix" and not fix:
            raise OracleError(f"Linter.{method} with no fix has no fixed SQL")
        argv, outputs = (
            (["lint", "-f", "json", "-"], lint_outputs)
            if part == "lint"
            else (["fix", "-"], fix_outputs)
        )
        try:
            out.append(
                _mapped("Linter string call", call, {**base, "argv": argv}, outputs)
            )
        except OracleError as exc:
            out.append(exc)
    return out


def _api(call: dict[str, Any]) -> list[Mapped | OracleError]:
    inputs = call["inputs"]
    if inputs["cwd"] != ROOT_MARK:
        raise OracleError(f"a simple-API call in the folder {inputs['cwd']}")
    if inputs.get("config") is not None:
        return _api_config(call)
    for key in ("config_path", "fix_even_unparsable"):
        if inputs.get(key) is not None:
            raise OracleError(
                f"simple-API argument {key}={inputs[key]!r}; the oracle"
                " maps only the default"
            )
    mapped = {
        "run": "api",
        "function": inputs["function"],
        "sql": inputs["sql"],
        "dialect": inputs["dialect"] or API_DIALECT,
        "rules": inputs["rules"],
        "exclude_rules": inputs["exclude_rules"],
        "config": None,
    }
    return [_mapped("simple-API call", call, mapped, lambda out: out)]


def _api_config(call: dict[str, Any]) -> list[Mapped | OracleError]:
    """A simple-API lint or fix with a config. sqlfluff.api.simple then uses
    only the config (not dialect, rules, exclude_rules, or config_path) and
    calls Linter(config=config).lint_string_wrapped(sql, fix=<fix>). The
    trace records that inner call; the case is its lint or fix case."""
    inputs = call["inputs"]
    function = inputs["function"]
    for key in ("config_path", "fix_even_unparsable"):
        if inputs.get(key) is not None:
            raise OracleError(
                f"simple-API argument {key}={inputs[key]!r} with a config; the"
                " oracle maps only the default"
            )
    if function not in ("lint", "fix"):
        raise OracleError(f"the simple-API function {function} with a config")
    inner = call.get("inner") or []
    if "raised" in call and not inner:
        return [Mapped("simple-API call", {}, raised=call["raised"])]
    if len(inner) != 1 or inner[0]["kind"] != "linter_string":
        raise OracleError(
            f"a simple-API call with a config has {len(inner)} inner calls, not 1"
            " Linter string call"
        )
    sub = inner[0]
    sub_inputs = sub.get("inputs", {})
    fix = function == "fix"
    if (
        sub_inputs.get("method") != "lint_string_wrapped"
        or sub_inputs.get("sql") != inputs["sql"]
        or sub_inputs.get("options", {}).get("fix") is not fix
    ):
        raise OracleError("the inner Linter call is not the call of the simple API")
    part = "fix" if fix else "lint"
    mapped = _linter_string(sub, (part,))[0]
    if isinstance(mapped, OracleError):
        raise mapped
    mapped.what = "simple-API call"
    if "raised" in call:
        mapped.raised = call["raised"]
    elif mapped.outputs is not None and "outputs" in call:
        got = call["outputs"]
        want = (
            mapped.outputs["stdout"]
            if fix
            else mapped.outputs["records"][0]["violations"]
        )
        if got != want:
            raise OracleError(
                f"the simple-API {function} gives {got!r}, not the {part} output"
                " of the CLI model"
            )
    return [mapped]


# The templater map. The templaters that the map knows, the SQL file of a
# case, and the argv of the cases of each result of a process() call
# (scripts/s7-tests/trace-nodes has the same table): a call that returns
# gives the templated text case and the source slices case; a templater
# error gives the TMP violation of lint; a large file skip and each other
# error give the stderr and the exit code of parse.
TEMPLATERS = ("placeholder", "python")
TEMPLATER_SQL = "case.sql"
TEMPLATER_CASES = {
    "returned": (
        ("parse", "-f", "json", TEMPLATER_SQL),
        ("parse", "-f", "json", "-m", TEMPLATER_SQL),
    ),
    "templater_error": (("lint", "-f", "json", TEMPLATER_SQL),),
    "skip_file": (("parse", "-f", "json", TEMPLATER_SQL),),
    "other_error": (("parse", "-f", "json", TEMPLATER_SQL),),
}
# The parse tree check that each case of a call that returns must have, in
# the order of TEMPLATER_CASES["returned"]. Without it, a case of the call
# would not test the templated text or the source slices.
TEMPLATER_TREE_CHECKS = ("templated", "source_slices")


def _templater(call: dict[str, Any]) -> list[Mapped]:
    """A process() call of a templater as its CLI cases: cwd tmp, the files
    .sqlfluff (the config model of the call) and case.sql (in_str), and the
    argv of the result of the call. The outputs are those of the CLI runs of
    the trace. Fail closed (OracleError) on a templater that the map does
    not know, on an input that the trace marks, on a config that the model
    does not map, and on each difference of the proof."""
    inputs = call["inputs"]
    name = inputs["templater"]
    if name not in TEMPLATERS:
        raise OracleError(
            f"a process() call of the templater {name!r}; the map knows only"
            f" {list(TEMPLATERS)}"
        )
    if inputs["unsupported"]:
        raise OracleError("; ".join(inputs["unsupported"]))
    model = inputs["config_file"]
    if "error" in model:
        raise OracleError(f"the config of the templater call: {model['error']}")
    if call.get("proof_error"):
        raise OracleError(f"the trace could not prove the map: {call['proof_error']}")
    kind = call.get("error_kind", "returned") if "raised" in call else "returned"
    if kind not in TEMPLATER_CASES:
        raise OracleError(f"a templater call with the result {kind!r}")
    want = [list(argv) for argv in TEMPLATER_CASES[kind]]
    runs = call.get("cases") or []
    if [r["argv"] for r in runs] != want:
        raise OracleError(
            f"the trace ran the cases {[r['argv'] for r in runs]}, not the cases"
            f" {want} of the map"
        )
    if call.get("proof") is None or call["proof"]:
        raise OracleError(
            "the templater result of the CLI case is not the result of the call:"
            f" {call.get('proof')}"
        )
    files = {CONFIG_FILE: model["text"], TEMPLATER_SQL: inputs["in_str"]}
    required: tuple[str | None, ...] = (None,) * len(runs)
    templated = None
    if kind == "returned":
        templated = (call.get("outputs") or {}).get("templated")
        if not isinstance(templated, str):
            raise OracleError("a templater call that returned has no templated text")
        required = TEMPLATER_TREE_CHECKS
    out = []
    for run, argv, check in zip(runs, want, required, strict=True):
        if run["outer_config"]:
            raise OracleError(
                "a folder above the case folder has a sqlfluff config"
                f" {run['outer_config']}"
            )
        # An uncaught exception of the CLI is the expected result only if
        # the call raised it too (other_error); the proof compares them.
        exception = None if kind == "other_error" else run.get("exception")
        inputs_of = {"run": "cli", "argv": argv, "stdin": "", "cwd": "tmp"}
        out.append(
            Mapped(
                "templater call",
                {**inputs_of, "files": dict(files)},
                outputs={
                    "exit_code": run["exit_code"],
                    "stdout": run["stdout"],
                    "stderr": run["stderr"],
                    "records": None,
                    "files": run["files"],
                    "exception": exception,
                },
                required=check,
                templated=templated,
            )
        )
    return out


def map_call(call: dict[str, Any]) -> list[Mapped | OracleError]:
    """The cases of a traced call, in order. A Linter string call with fix
    gives 2 cases (lint, then fix); each other call gives 1. An item that is
    an OracleError is a case that the oracle cannot map."""
    if "inputs_error" in call:
        raise OracleError(
            f"the trace could not read the inputs: {call['inputs_error']}"
        )
    kind = call["kind"]
    if kind == "cli":
        return _cli(call)
    if kind == "linter":
        return _linter_path(call)
    if kind == "linter_string":
        fix = call["inputs"]["options"].get("fix")
        return _linter_string(call, ("lint", "fix") if fix else ("lint",))
    if kind == "api":
        return _api(call)
    if kind == "templater":
        return _templater(call)
    raise OracleError(f"a traced call of the unknown kind {kind!r}")


def input_differences(case: Case, mapped: Mapped) -> list[str]:
    want = case_inputs(case)
    got = mapped.inputs
    return [
        f"{key}: the case gives {want.get(key)!r}, the trace {got.get(key)!r}"
        for key in sorted(set(want) | set(got))
        if want.get(key) != got.get(key)
    ]


# Outputs.


def failed_checks(case: Case, mapped: Mapped) -> list[str]:
    """The checks of a case that fail on the traced outputs of its call."""
    if mapped.raised is not None:
        return [f"the call raised {mapped.raised}"]
    if mapped.outputs_error is not None:
        raise OracleError(
            f"the trace could not read the outputs: {mapped.outputs_error}"
        )
    if mapped.outputs is None:
        raise OracleError("the trace has no outputs")
    outputs = mapped.outputs
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
    if outputs["exit_code"] != checks["exit_code"]:
        failed.append(f"exit_code: {outputs['exit_code']}, not {checks['exit_code']}")
    if outputs.get("exception"):
        failed.append(f"the command raised {outputs['exception']}")
    for stream in ("stdout", "stderr"):
        if stream in checks:
            if outputs[stream] is None:
                raise OracleError(f"a {stream} check; a {mapped.what} has no {stream}")
            failed += match_text(stream, outputs[stream], checks[stream])
    if case.cwd == "tmp":
        if outputs["files"] is None:
            raise OracleError("a files check; the trace has no files")
        failed += check_files(case, outputs["files"])
    elif "files" in checks:
        raise OracleError("a files check; the trace has no files")
    if outputs["records"] is not None:
        stdout = json.dumps(outputs["records"])
    else:
        stdout = outputs["stdout"]
    for i, check in enumerate(checks.get("violations", [])):
        if stdout is None:
            raise OracleError(f"a violations check; a {mapped.what} has no lint output")
        try:
            found = cli_violations(stdout, check.get("file"))
        except CheckFailed as exc:
            failed.append(f"violations[{i}]: {exc}")
            continue
        failed += check_violations(f"violations[{i}]", found, check)
    if mapped.required is not None and mapped.required not in checks:
        raise OracleError(
            f"the case of a {mapped.what} that returned has no {mapped.required!r}"
            " check"
        )
    if any(k in checks for k in ("templated", "source_slices")) and stdout is None:
        raise OracleError(f"a parse tree check; a {mapped.what} has no stdout")
    if (
        mapped.templated is not None
        and "templated" in checks
        and checks["templated"] != mapped.templated
    ):
        failed.append(f"templated: the call returned {mapped.templated!r}")
    failed += tree_failures(checks, stdout)
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


def _linter_errors(data: dict[str, Any]) -> list[str]:
    """A Linter render or parse outside each traced call: a Linter method
    that the oracle does not map. A python-internal node can have it."""
    return [f"an untraced Linter call: {u}" for u in data.get("untraced_linter", [])]


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
    result.errors += _trace_errors(data) + _linter_errors(data)
    calls = data["calls"]
    pytest_status = OUTCOMES.get(data["outcome"])
    if pytest_status is None:
        result.errors.append(f"the pytest outcome is {data['outcome']}")
    # The cases of the calls, in order. A call that the oracle cannot map
    # counts as 1 case.
    parts: list[Mapped | OracleError] = []
    for call in calls:
        try:
            parts += map_call(call)
        except OracleError as exc:
            parts.append(exc)
    statuses = []
    for case, part in zip(node.cases, parts, strict=False):
        try:
            if isinstance(part, OracleError):
                raise part
            diff = input_differences(case, part)
            if diff:
                result.errors += [f"case {case.name}: input {d}" for d in diff]
                continue
            failed = failed_checks(case, part)
        except OracleError as exc:
            result.errors.append(f"case {case.name}: {exc}")
            continue
        status = FAIL if failed else PASS
        statuses.append(status)
        result.cases.append(
            {"name": case.name, "status": status, "reason": "; ".join(failed)}
        )
    if len(parts) > len(node.cases):
        counts = f"{len(calls)} traced calls"
        if len(parts) != len(calls):
            counts += f" ({len(parts)} cases)"
        result.errors.append(f"{counts}, {len(node.cases)} cases: a call has no case")
    elif len(parts) < len(node.cases):
        # A failed node can stop before its last calls. Then a traced case
        # must fail, so that the failure is a failure of a check.
        missing = [c.name for c in node.cases[len(parts) :]]
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
    for key in ("calls", "untraced", "untraced_linter", "processes"):
        if outside.get(key):
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
