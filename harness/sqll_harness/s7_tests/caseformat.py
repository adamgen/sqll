"""The S7 case format and the exclusion list (docs/decisions/s7-tests-design.md,
"Case format").

A case file holds the black-box cases of one sqlfluff test file. The loader
fails closed: each error in a case file or in the exclusion list stops the
load (CaseFormatError), and the message names each error.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from ..paths import REPO_ROOT

PACKAGE_DIR = Path(__file__).resolve().parent
CASES_DIR = PACKAGE_DIR / "cases"
EXCLUSIONS_FILE = PACKAGE_DIR / "exclusions.yml"
SCOPE_FILE = REPO_ROOT / "results" / "S7-tests" / "scope.json"

SQLFLUFF_VERSION = "4.4.0"
SQLFLUFF_COMMIT = "0348222a3bcdb0226563f7349c5a39beb0641955"
LICENSE = "MIT"

# The exclusion classes (design record, "Exclusions"). A node of a class in
# NEEDS_REASON must have a reason of one line.
CLASSES = (
    "python-internal",
    "needs-python-runtime",
    "engine-comparison",
    "environment",
)
NEEDS_REASON = frozenset({"needs-python-runtime", "environment"})

RUNS = ("cli", "api")
API_FUNCTIONS = ("lint", "fix")
CWDS = ("sqlfluff", "tmp")
# The argv placeholders: the temporary folder of the case and the root of
# the sqlfluff submodule.
TMP_MARK = "{tmp}"
SQLFLUFF_MARK = "{sqlfluff}"
# The keys of a violation in "sqlfluff lint -f json" and in the simple API.
VIOLATION_KEYS = frozenset(
    {
        "code",
        "description",
        "name",
        "warning",
        "start_line_no",
        "start_line_pos",
        "start_file_pos",
        "end_line_no",
        "end_line_pos",
        "end_file_pos",
        "fixes",
    }
)
MATCHERS = ("equals", "startswith", "contains", "not_contains", "json")

_HEADER_KEYS = {"source", "license", "nodes"}
_SOURCE_KEYS = {"project", "version", "commit", "file"}
_NODE_KEYS = {"node", "cases"}
_COMMON_KEYS = {"name", "run", "needs_jinja", "checks"}
_CLI_KEYS = _COMMON_KEYS | {"argv", "cwd", "stdin", "files", "sqruff"}
_API_KEYS = _COMMON_KEYS | {
    "function",
    "sql",
    "dialect",
    "rules",
    "exclude_rules",
    "config",
}
_CLI_CHECKS = {"exit_code", "stdout", "stderr", "files", "violations"}
_API_CHECKS = {"lint": {"violations"}, "fix": {"fixed"}}
_VIOLATION_CHECK_KEYS = {"file", "select", "count", "min_count", "records", "exact"}
_EXCLUSION_KEYS = {"node", "class", "reason"}


class CaseFormatError(Exception):
    """A case file or the exclusion list is not valid. args[0] is the list
    of errors."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__(errors)
        self.errors = errors

    def __str__(self) -> str:
        return "\n".join(self.errors)


@dataclass
class Case:
    """One black-box case. run is "cli" (the CLI of the tool) or "api" (a
    simple-API function through the adapter of the tool)."""

    name: str
    run: str
    checks: dict[str, Any]
    needs_jinja: bool = False
    # cli
    argv: list[str] = field(default_factory=list)
    cwd: str = "sqlfluff"
    stdin: str | None = None
    files: dict[str, str] = field(default_factory=dict)
    sqruff: list[str] | None = None
    # api
    function: str | None = None
    sql: str | None = None
    dialect: str | None = None
    rules: list[str] | None = None
    exclude_rules: list[str] | None = None
    config: dict[str, Any] | None = None


@dataclass
class Node:
    """One pytest node of the sqlfluff tests and its cases."""

    id: str
    group: str
    case_file: str
    cases: list[Case]

    @property
    def needs_jinja(self) -> bool:
        """The node moves to S11 if a case needs the Jinja templater."""
        return any(c.needs_jinja for c in self.cases)


@dataclass
class Exclusion:
    id: str
    group: str
    cls: str
    reason: str | None


@dataclass
class CaseSet:
    scope: dict[str, Any]
    nodes: list[Node]
    exclusions: list[Exclusion]


class _UniqueKeyLoader(yaml.SafeLoader):
    """A YAML loader that refuses a repeated key in a mapping."""


def _mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    keys = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in keys:
            raise yaml.constructor.ConstructorError(
                None, None, f"repeated key {key!r}", key_node.start_mark
            )
        keys.add(key)
    return loader.construct_mapping(node, deep=deep)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping
)


def load_yaml(path: Path) -> Any:
    try:
        return yaml.load(path.read_text(encoding="utf8"), Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise CaseFormatError([f"{path.name}: YAML error: {exc}"]) from exc


def load_scope(path: Path = SCOPE_FILE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf8"))


def case_file_path(source_file: str) -> PurePosixPath:
    """The path of the case file of a sqlfluff test file, relative to
    CASES_DIR: test/cli/commands_test.py -> cli/commands_test.yml."""
    path = PurePosixPath(source_file)
    return path.relative_to("test").with_suffix(".yml")


class _Errors:
    def __init__(self, where: str) -> None:
        self.where = where
        self.items: list[str] = []

    def add(self, at: str, message: str) -> None:
        self.items.append(f"{self.where}: {at}: {message}")


def _is_str_list(value: Any, empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (empty or bool(value))
        and all(isinstance(v, str) for v in value)
    )


def _keys(err: _Errors, at: str, value: Any, allowed: set[str]) -> bool:
    """Add an error if value is not a mapping with only allowed keys."""
    if not isinstance(value, dict):
        err.add(at, "must be a mapping")
        return False
    unknown = sorted(str(k) for k in value if k not in allowed)
    if unknown:
        err.add(at, f"unknown keys {unknown}")
    return True


def _check_matcher(err: _Errors, at: str, value: Any) -> None:
    if not _keys(err, at, value, set(MATCHERS)):
        return
    if not value:
        err.add(at, "has no matcher")
    for key in ("equals", "startswith"):
        if key in value and not isinstance(value[key], str):
            err.add(f"{at}.{key}", "must be a string")
    for key in ("contains", "not_contains"):
        if key in value and not _is_str_list(value[key]):
            err.add(f"{at}.{key}", "must be a list of strings with one or more items")


def _check_violation_value(err: _Errors, at: str, value: Any) -> None:
    if isinstance(value, dict):
        if set(value) != {"contains"} or not isinstance(value["contains"], str):
            err.add(at, "a mapping value must be {contains: <string>}")
    elif value is not None and not isinstance(value, (str, int, bool, list)):
        err.add(at, f"has the type {type(value).__name__}")


def _check_violations(err: _Errors, at: str, value: Any, run: str) -> None:
    if not isinstance(value, list) or not value:
        err.add(at, "must be a list with one or more checks")
        return
    for i, item in enumerate(value):
        here = f"{at}[{i}]"
        if not _keys(err, here, item, _VIOLATION_CHECK_KEYS):
            continue
        if "file" in item and (run != "cli" or not isinstance(item["file"], str)):
            err.add(f"{here}.file", "is a string, and only in a cli case")
        if not ({"count", "min_count", "records"} & set(item)):
            err.add(here, "needs count, min_count, or records")
        if "count" in item and "min_count" in item:
            err.add(here, "has count and min_count")
        for key, low in (("count", 0), ("min_count", 1)):
            if key in item and (
                not isinstance(item[key], int)
                or isinstance(item[key], bool)
                or item[key] < low
            ):
                err.add(f"{here}.{key}", f"must be an integer >= {low}")
        if "exact" in item and (
            not isinstance(item["exact"], bool) or "records" not in item
        ):
            err.add(f"{here}.exact", "is a bool, and only with records")
        select = item.get("select", {})
        if _keys(err, f"{here}.select", select, set(VIOLATION_KEYS)):
            for key, v in select.items():
                _check_violation_value(err, f"{here}.select.{key}", v)
        records = item.get("records", [])
        if not isinstance(records, list):
            err.add(f"{here}.records", "must be a list")
            continue
        for j, record in enumerate(records):
            where = f"{here}.records[{j}]"
            if _keys(err, where, record, set(VIOLATION_KEYS)):
                if not record:
                    err.add(where, "is empty")
                for key, v in record.items():
                    _check_violation_value(err, f"{where}.{key}", v)
        if "count" in item and "records" in item and item["count"] != len(records):
            err.add(here, "count is not the number of records")


def _check_rel_path(err: _Errors, at: str, name: Any) -> None:
    path = PurePosixPath(name) if isinstance(name, str) else None
    if path is None or path.is_absolute() or ".." in path.parts or not path.parts:
        err.add(at, f"{name!r} is not a relative path in the case folder")


def _check_cli(err: _Errors, at: str, case: dict[str, Any]) -> None:
    if not _is_str_list(case.get("argv")):
        err.add(f"{at}.argv", "must be a list of strings with one or more items")
    if "sqruff" in case and not _is_str_list(case["sqruff"]):
        err.add(f"{at}.sqruff", "must be a list of strings with one or more items")
    cwd = case.get("cwd", "sqlfluff")
    if cwd not in CWDS:
        err.add(f"{at}.cwd", f"must be one of {list(CWDS)}")
    if "stdin" in case and not isinstance(case["stdin"], str):
        err.add(f"{at}.stdin", "must be a string")
    files = case.get("files", {})
    if not isinstance(files, dict) or not all(
        isinstance(v, str) for v in files.values()
    ):
        err.add(f"{at}.files", "must map each path to a string")
        files = {}
    if files and cwd != "tmp":
        # The cases read the fixtures in place and never write to the
        # submodule (G4.5).
        err.add(f"{at}.files", "needs cwd: tmp")
    for name in files:
        _check_rel_path(err, f"{at}.files", name)
    checks = case.get("checks")
    if not _keys(err, f"{at}.checks", checks, _CLI_CHECKS):
        return
    code = checks.get("exit_code")
    if not isinstance(code, int) or isinstance(code, bool):
        err.add(
            f"{at}.checks.exit_code", "must be an integer (each cli case checks it)"
        )
    for stream in ("stdout", "stderr"):
        if stream in checks:
            _check_matcher(err, f"{at}.checks.{stream}", checks[stream])
    if "files" in checks:
        after = checks["files"]
        if cwd != "tmp":
            err.add(f"{at}.checks.files", "needs cwd: tmp")
        if not isinstance(after, dict) or not all(
            isinstance(v, str) for v in after.values()
        ):
            err.add(f"{at}.checks.files", "must map each path to a string")
        else:
            for name in after:
                _check_rel_path(err, f"{at}.checks.files", name)
    if "violations" in checks:
        _check_violations(err, f"{at}.checks.violations", checks["violations"], "cli")


def _check_api(err: _Errors, at: str, case: dict[str, Any]) -> None:
    function = case.get("function")
    if function not in API_FUNCTIONS:
        err.add(f"{at}.function", f"must be one of {list(API_FUNCTIONS)}")
        return
    if not isinstance(case.get("sql"), str):
        err.add(f"{at}.sql", "must be a string")
    if "dialect" in case and not isinstance(case["dialect"], str):
        err.add(f"{at}.dialect", "must be a string")
    for key in ("rules", "exclude_rules"):
        if key in case and not _is_str_list(case[key]):
            err.add(f"{at}.{key}", "must be a list of strings with one or more items")
    if "config" in case and not isinstance(case["config"], dict):
        err.add(f"{at}.config", "must be a mapping")
    checks = case.get("checks")
    allowed = _API_CHECKS[function]
    if not _keys(err, f"{at}.checks", checks, allowed):
        return
    for key in sorted(allowed - set(checks)):
        err.add(f"{at}.checks", f"needs {key}")
    if "violations" in checks:
        _check_violations(err, f"{at}.checks.violations", checks["violations"], "api")
    if "fixed" in checks and not isinstance(checks["fixed"], str):
        err.add(f"{at}.checks.fixed", "must be a string")


def _to_case(data: dict[str, Any]) -> Case:
    names = {k: v for k, v in data.items() if k not in {"run", "checks"}}
    return Case(run=data["run"], checks=data["checks"], **names)


def parse_case_file(
    data: Any, rel_path: str, scope_files: dict[str, Any]
) -> tuple[str, list[tuple[str, list[Case]]], list[str]]:
    """Check the content of one case file.

    Return the source file, the (node id, cases) pairs, and the errors.
    rel_path is the path of the case file relative to CASES_DIR.
    """
    err = _Errors(rel_path)
    nodes: list[tuple[str, list[Case]]] = []
    if not isinstance(data, dict):
        err.add("file", "must be a mapping")
        return "", nodes, err.items
    for key in sorted(_HEADER_KEYS - set(data)):
        err.add("header", f"has no {key}")
    _keys(err, "header", data, _HEADER_KEYS)
    if data.get("license", LICENSE) != LICENSE:
        err.add("license", f"must be {LICENSE} (the license of sqlfluff)")
    source = data.get("source", {})
    file = ""
    if _keys(err, "source", source, _SOURCE_KEYS):
        for key in sorted(_SOURCE_KEYS - set(source)):
            err.add("source", f"has no {key}")
        want = {
            "project": "sqlfluff",
            "version": SQLFLUFF_VERSION,
            "commit": SQLFLUFF_COMMIT,
        }
        for key, value in want.items():
            if key in source and source[key] != value:
                err.add(f"source.{key}", f"{source[key]!r} is not {value!r}")
        file = source.get("file", "")
        if "file" in source:
            if file not in scope_files:
                err.add("source.file", f"{file!r} has no node in scope.json")
            elif str(case_file_path(file)) != rel_path:
                err.add(
                    "source.file", f"the case file of {file} is {case_file_path(file)}"
                )
    items = data.get("nodes")
    if not isinstance(items, list) or not items:
        err.add("nodes", "must be a list with one or more nodes")
        return file, nodes, err.items
    for i, item in enumerate(items):
        at = f"nodes[{i}]"
        if not _keys(err, at, item, _NODE_KEYS):
            continue
        node_id = item.get("node")
        if not isinstance(node_id, str) or not node_id.startswith(f"{file}::"):
            err.add(f"{at}.node", f"{node_id!r} is not a node of {file}")
            continue
        at = node_id
        cases = item.get("cases")
        if not isinstance(cases, list) or not cases:
            err.add(at, "cases must be a list with one or more cases")
            continue
        names = set()
        good: list[Case] = []
        for j, case in enumerate(cases):
            where = f"{at} case {j}"
            if not isinstance(case, dict):
                err.add(where, "must be a mapping")
                continue
            name = case.get("name")
            if not isinstance(name, str) or not name or name in names:
                err.add(f"{where}.name", f"{name!r} is not a new, non-empty string")
            names.add(name)
            run = case.get("run")
            if run not in RUNS:
                err.add(f"{where}.run", f"must be one of {list(RUNS)}")
                continue
            before = len(err.items)
            _keys(err, where, case, _CLI_KEYS if run == "cli" else _API_KEYS)
            if "needs_jinja" in case and not isinstance(case["needs_jinja"], bool):
                err.add(f"{where}.needs_jinja", "must be a bool")
            (_check_cli if run == "cli" else _check_api)(err, where, case)
            if len(err.items) == before:
                good.append(_to_case(case))
        nodes.append((node_id, good))
    return file, nodes, err.items


def parse_exclusions(
    data: Any, scope_ids: dict[str, str], where: str = "exclusions.yml"
) -> tuple[list[Exclusion], list[str]]:
    """Check the exclusion list. scope_ids maps each node id to its group."""
    err = _Errors(where)
    out: list[Exclusion] = []
    if not isinstance(data, dict) or set(data) != {"excluded"}:
        err.add("file", "must be a mapping with only the key 'excluded'")
        return out, err.items
    items = data["excluded"]
    if not isinstance(items, list):
        err.add("excluded", "must be a list")
        return out, err.items
    seen: set[str] = set()
    for i, item in enumerate(items):
        at = f"excluded[{i}]"
        if not _keys(err, at, item, _EXCLUSION_KEYS):
            continue
        node_id = item.get("node")
        if not isinstance(node_id, str) or node_id not in scope_ids:
            err.add(f"{at}.node", f"{node_id!r} is not in scope.json")
            continue
        if node_id in seen:
            err.add(at, f"{node_id} is in the list 2 times")
            continue
        seen.add(node_id)
        cls = item.get("class")
        if cls not in CLASSES:
            err.add(node_id, f"unknown class {cls!r}; the classes are {list(CLASSES)}")
            continue
        reason = item.get("reason")
        if reason is not None and (
            not isinstance(reason, str) or not reason.strip() or "\n" in reason.strip()
        ):
            err.add(node_id, "the reason must be one line of text")
            continue
        if cls in NEEDS_REASON and reason is None:
            err.add(node_id, f"class {cls} needs a reason of one line")
            continue
        out.append(
            Exclusion(node_id, scope_ids[node_id], cls, reason and reason.strip())
        )
    return out, err.items


def load(
    cases_dir: Path = CASES_DIR,
    exclusions_file: Path = EXCLUSIONS_FILE,
    scope: dict[str, Any] | None = None,
) -> CaseSet:
    """Load and check all case files and the exclusion list. Fail closed."""
    scope = scope if scope is not None else load_scope()
    scope_ids = {n["id"]: n["group"] for n in scope["nodes"]}
    errors: list[str] = []
    nodes: list[Node] = []
    owner: dict[str, str] = {}
    files = sorted(cases_dir.rglob("*"))
    for path in files:
        if path.is_dir():
            continue
        rel = path.relative_to(cases_dir).as_posix()
        if path.suffix != ".yml":
            errors.append(f"{rel}: a file in the case folder that is not a .yml file")
            continue
        try:
            data = load_yaml(path)
        except CaseFormatError as exc:
            errors += [f"{rel}: {e}" for e in exc.errors]
            continue
        _, pairs, errs = parse_case_file(data, rel, scope["files"])
        errors += errs
        for node_id, cases in pairs:
            if node_id not in scope_ids:
                errors.append(f"{rel}: {node_id}: not in scope.json")
            elif node_id in owner:
                errors.append(f"{rel}: {node_id}: also in {owner[node_id]}")
            else:
                owner[node_id] = rel
                nodes.append(Node(node_id, scope_ids[node_id], rel, cases))
    exclusions: list[Exclusion] = []
    if exclusions_file.exists():
        try:
            data = load_yaml(exclusions_file)
        except CaseFormatError as exc:
            errors += exc.errors
        else:
            exclusions, errs = parse_exclusions(data, scope_ids, exclusions_file.name)
            errors += errs
    else:
        errors.append(f"{exclusions_file.name}: the exclusion list does not exist")
    for ex in exclusions:
        if ex.id in owner:
            errors.append(f"{ex.id}: excluded, but {owner[ex.id]} converts it")
    if errors:
        raise CaseFormatError(errors)
    order = {node_id: i for i, node_id in enumerate(scope_ids)}
    nodes.sort(key=lambda n: order[n.id])
    exclusions.sort(key=lambda e: order[e.id])
    return CaseSet(scope, nodes, exclusions)
