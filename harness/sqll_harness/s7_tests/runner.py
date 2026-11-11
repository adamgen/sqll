"""Run the S7 cases through a tool binary (docs/decisions/s7-tests-design.md,
"Case runner").

A cli case runs the CLI of the tool. An api case runs a simple-API function
(lint, fix) through the adapter of the tool, which runs the CLI. Thus each
case runs through a binary (G1.5). A node passes only if all its cases pass.
"""

import copy
import json
import subprocess
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..adapters import ADAPTERS, Adapter
from ..adapters.base import EmptyHome, Unsupported, isolated_env
from ..adapters.sqlfluff import CONFIG_NAME, sqlfluff_toml
from ..adapters.sqlfluff_rs import _RUST_KEY as RUST_KEY
from ..adapters.sqlfluff_rs import (
    ARENA_WARNING,
    CONFIG_FILES,
    FALLBACK_WARNING,
    RUST_CONFIG,
    RustConfigConflict,
    RustParserNotUsed,
    user_config_folders,
)
from ..adapters.sqruff import sqruff_env
from ..cases import ERROR, FAIL, PASS, UNSUPPORTED
from ..paths import SQLFLUFF_ROOT
from .caseformat import SQLFLUFF_MARK, TMP_MARK, Case, Node

TOOLS = ("sqlfluff", "sqlfluff-rs", "sqruff")
TIMEOUT_S = 600
# The simple API uses the ansi dialect if the call gives no dialect.
API_DIALECT = "ansi"
# The simple API runs all rules if the call gives no rules. "all" is the
# default of the core "rules" setting.
ALL_RULES = ["all"]
# The file name of the SQL of an api case in its temporary folder.
API_SQL_NAME = "case.sql"
# The CLI commands that read a config file (--config). The sqlfluff-rs layer
# goes to these commands.
CONFIG_COMMANDS = frozenset({"lint", "fix", "format", "parse", "render"})
# The suffixes of the default sql_file_exts of sqlfluff (.sql, .sql.j2, .dml,
# .ddl).
SQL_SUFFIXES = frozenset({".sql", ".j2", ".dml", ".ddl"})
REASON_LIMIT = 400


@dataclass
class CaseOutcome:
    name: str
    status: str
    reason: str = ""


@dataclass
class NodeOutcome:
    """The result of one node for one tool: pass only if each case passes;
    error if a case has an error; else fail."""

    id: str
    tool: str
    cases: list[CaseOutcome] = field(default_factory=list)

    @property
    def status(self) -> str:
        statuses = {c.status for c in self.cases}
        if statuses == {PASS}:
            return PASS
        return ERROR if ERROR in statuses else FAIL


class CheckFailed(Exception):
    """The output of a case does not agree with its checks."""


# Check evaluation. Each function returns the list of failed checks.


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 80 else text[:77] + "..."


def match_text(where: str, text: str, matcher: dict[str, Any]) -> list[str]:
    out = []
    if "equals" in matcher and text != matcher["equals"]:
        out.append(f"{where}.equals: the text is {_short(text)}")
    if "startswith" in matcher and not text.startswith(matcher["startswith"]):
        out.append(f"{where}.startswith: the text starts with {_short(text[:80])}")
    for i, part in enumerate(matcher.get("contains", [])):
        if part not in text:
            out.append(f"{where}.contains[{i}]: {_short(part)} is not in the text")
    for i, part in enumerate(matcher.get("not_contains", [])):
        if part in text:
            out.append(f"{where}.not_contains[{i}]: {_short(part)} is in the text")
    if "json" in matcher:
        try:
            value = json.loads(text)
        except ValueError:
            out.append(f"{where}.json: the text is not JSON")
        else:
            if value != matcher["json"]:
                out.append(f"{where}.json: the value is {_short(value)}")
    return out


def _value_matches(actual: Any, want: Any) -> bool:
    if isinstance(want, dict):
        return isinstance(actual, str) and want["contains"] in actual
    return actual == want and type(actual) is type(want)


def _violation_matches(violation: dict[str, Any], want: dict[str, Any]) -> bool:
    return all(
        key in violation and _value_matches(violation[key], value)
        for key, value in want.items()
    )


def check_violations(
    where: str, violations: list[dict[str, Any]], check: dict[str, Any]
) -> list[str]:
    """One violation check: select the violations, then count or compare
    them. records describe all selected violations, in order."""
    select = check.get("select", {})
    chosen = [v for v in violations if _violation_matches(v, select)]
    out = []
    if "count" in check and len(chosen) != check["count"]:
        out.append(f"{where}.count: {len(chosen)} violations, not {check['count']}")
    if "min_count" in check and len(chosen) < check["min_count"]:
        out.append(
            f"{where}.min_count: {len(chosen)} violations, not {check['min_count']}"
            " or more"
        )
    records = check.get("records")
    if records is not None:
        if len(chosen) != len(records):
            out.append(f"{where}.records: {len(chosen)} violations, not {len(records)}")
        for i, (got, want) in enumerate(zip(chosen, records, strict=False)):
            if not _violation_matches(got, want):
                out.append(f"{where}.records[{i}]: the violation is {_short(got)}")
            elif check.get("exact") and set(got) != set(want):
                extra = sorted(set(got) - set(want))
                out.append(f"{where}.records[{i}]: more keys {extra}")
    return out


def violation_keys(checks: dict[str, Any]) -> set[str]:
    """The violation keys that the violation checks read."""
    keys: set[str] = set()
    for check in checks.get("violations", []):
        keys |= set(check.get("select", {}))
        for record in check.get("records", []):
            keys |= set(record)
    return keys


def cli_violations(stdout: str, file: str | None) -> list[dict[str, Any]]:
    """The violations of one file in "lint -f json" output."""
    try:
        records = json.loads(stdout)
        by_file = {r["filepath"]: r["violations"] for r in records}
    except (ValueError, KeyError, TypeError) as exc:
        raise CheckFailed("violations: the stdout is not lint JSON output") from exc
    if file is None:
        if len(by_file) != 1:
            raise CheckFailed(f"violations: {len(by_file)} files in the output, not 1")
        return next(iter(by_file.values()))
    if file not in by_file:
        raise CheckFailed(f"violations: no output for the file {file}")
    return by_file[file]


def read_tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes().decode("utf8", "replace")
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def check_files(case: Case, after: dict[str, str]) -> list[str]:
    """The files of a tmp case after the run: each changed or new file must
    be in checks.files with its content; each other file must not change."""
    want = {**case.files, **case.checks.get("files", {})}
    out = []
    for name in sorted(set(want) | set(after)):
        if name not in after:
            out.append(f"files.{name}: the file does not exist")
        elif name not in want:
            out.append(f"files.{name}: a new file that the case does not give")
        elif after[name] != want[name]:
            what = "changed" if name in case.checks.get("files", {}) else "unchanged"
            out.append(f"files.{name}: not the {what} content: {_short(after[name])}")
    return out


# Running the cases.


@dataclass
class ToolRun:
    """The binary, environment, and argv prefix of one tool."""

    name: str
    adapter: Adapter
    binary: Path
    env: dict[str, str]
    layer_file: Path | None = None


def tool_run(name: str, adapter: Adapter, layer_dir: Path) -> ToolRun:
    if name == "sqruff":
        return ToolRun(name, adapter, adapter.binary, sqruff_env(adapter.root))
    run = ToolRun(name, adapter, adapter.binary, isolated_env(EmptyHome.path()))
    if name == "sqlfluff-rs":
        run.layer_file = layer_dir / CONFIG_NAME
        run.layer_file.write_text(sqlfluff_toml(RUST_CONFIG), encoding="utf8")
    return run


def _substitute(argv: list[str], tmp: Path) -> list[str]:
    return [
        a.replace(TMP_MARK, str(tmp)).replace(SQLFLUFF_MARK, str(SQLFLUFF_ROOT))
        for a in argv
    ]


def _check_rust_inputs(case: Case, argv: list[str], cwd: Path) -> None:
    """Fail if a config file or in-file line that the run can read sets a
    key of the sqlfluff-rs layer. As the adapter: the check reads more
    files than sqlfluff reads, never less."""
    if any(a == "--config" or a.startswith("--config=") for a in argv):
        raise RustConfigConflict(
            "the case gives --config; the sqlfluff-rs layer needs --config"
        )
    texts = [case.stdin or ""]
    files: set[Path] = set()
    for arg in [".", *argv[1:]]:
        full = cwd / arg
        if not full.exists():
            continue
        for folder in user_config_folders(Path(arg), cwd, EmptyHome.path()):
            files |= {folder / name for name in CONFIG_FILES}
        if full.is_file():
            files.add(full)
        elif arg != ".":
            # The SQL and config files that the tool can read in the folder.
            files |= {
                p
                for p in full.rglob("*")
                if p.name in CONFIG_FILES or p.suffix in SQL_SUFFIXES
            }
    texts += [p.read_bytes().decode("utf8", "replace") for p in files if p.is_file()]
    if any(RUST_KEY.search(text) for text in texts):
        raise RustConfigConflict("an input of the case has a sqlfluff-rs layer key")


def run_cli(run: ToolRun, case: Case) -> list[str]:
    """Run a cli case. Return the failed checks."""
    if run.name == "sqruff":
        if case.sqruff is None:
            raise Unsupported(
                f"sqlfluff CLI command {case.argv[0]!r} (the case has no sqruff"
                " translation)"
            )
        if "violations" in case.checks:
            raise Unsupported("violations check on the sqruff CLI output")
    with tempfile.TemporaryDirectory(prefix="sqll-s7-") as name:
        tmp = Path(name)
        for rel, text in case.files.items():
            path = tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf8"))
        cwd = tmp if case.cwd == "tmp" else SQLFLUFF_ROOT
        argv = _substitute(case.sqruff if run.name == "sqruff" else case.argv, tmp)
        if run.layer_file is not None and argv[0] in CONFIG_COMMANDS:
            _check_rust_inputs(case, argv, cwd)
            argv = [argv[0], "--config", str(run.layer_file), *argv[1:]]
        proc = subprocess.run(
            [str(run.binary), *argv],
            cwd=cwd,
            input=(case.stdin or "").encode("utf8"),
            capture_output=True,
            env=run.env,
            timeout=TIMEOUT_S,
            check=False,
        )
        stdout = proc.stdout.decode("utf8", "replace")
        stderr = proc.stderr.decode("utf8", "replace")
        if run.layer_file is not None:
            for warning in (FALLBACK_WARNING, ARENA_WARNING):
                if warning in stdout + stderr:
                    raise RustParserNotUsed(f"sqlfluff logged '{warning}'")
        after = read_tree(tmp) if case.cwd == "tmp" else {}
    failed = []
    checks = case.checks
    if proc.returncode != checks["exit_code"]:
        failed.append(f"exit_code: {proc.returncode}, not {checks['exit_code']}")
    for stream, text in (("stdout", stdout), ("stderr", stderr)):
        if stream in checks:
            failed += match_text(stream, text, checks[stream])
    if case.cwd == "tmp":
        failed += check_files(case, after)
    for i, check in enumerate(checks.get("violations", [])):
        try:
            found = cli_violations(stdout, check.get("file"))
        except CheckFailed as exc:
            failed.append(f"violations[{i}]: {exc}")
            continue
        failed += check_violations(f"violations[{i}]", found, check)
    return failed


def _api_config(case: Case) -> dict[str, Any] | None:
    config = copy.deepcopy(case.config)
    if case.exclude_rules is not None:
        config = config or {}
        core = config.setdefault("core", {})
        if "exclude_rules" in core:
            raise ValueError("the case gives exclude_rules 2 times")
        core["exclude_rules"] = ",".join(case.exclude_rules)
    return config


def run_api(run: ToolRun, case: Case) -> list[str]:
    """Run an api case through the adapter of the tool. Return the failed
    checks."""
    adapter = run.adapter
    keys = violation_keys(case.checks)
    if adapter.lint_fields is not None and keys - adapter.lint_fields:
        missing = ", ".join(sorted(keys - adapter.lint_fields))
        raise Unsupported(f"output field {missing}")
    rules = case.rules or ALL_RULES
    dialect = case.dialect or API_DIALECT
    config = _api_config(case)
    with tempfile.TemporaryDirectory(prefix="sqll-s7-") as name:
        workdir = Path(name)
        path = workdir / API_SQL_NAME
        path.write_bytes((case.sql or "").encode("utf8"))
        if case.function == "lint":
            result = adapter.lint([path], rules, dialect, config, workdir)
            if result.errors or result.violations is None:
                raise RuntimeError("; ".join(result.errors) or "no lint output")
            found = result.violations[path]
            failed = []
            for i, check in enumerate(case.checks["violations"]):
                failed += check_violations(f"violations[{i}]", found, check)
            return failed
        fixed = adapter.fix(path, rules, dialect, config, workdir)
        if fixed.errors or fixed.fixed is None:
            raise RuntimeError("; ".join(fixed.errors) or "no fix output")
        if fixed.fixed != case.checks["fixed"]:
            return [f"fixed: the text is {_short(fixed.fixed)}"]
        return []


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= REASON_LIMIT else text[: REASON_LIMIT - 3] + "..."


def run_case(run: ToolRun, case: Case) -> CaseOutcome:
    try:
        failed = (run_cli if case.run == "cli" else run_api)(run, case)
    except Unsupported as exc:
        return CaseOutcome(case.name, FAIL, _clip(UNSUPPORTED + exc.item))
    except subprocess.TimeoutExpired:
        return CaseOutcome(case.name, ERROR, f"timeout after {TIMEOUT_S} s")
    except (
        RustConfigConflict,
        RustParserNotUsed,
        RuntimeError,
        ValueError,
        OSError,
    ) as exc:
        return CaseOutcome(case.name, ERROR, _clip(f"{type(exc).__name__}: {exc}"))
    if failed:
        return CaseOutcome(case.name, FAIL, _clip("; ".join(failed)))
    return CaseOutcome(case.name, PASS)


def run_nodes(
    nodes: list[Node],
    tools: list[str],
    jobs: int = 1,
    adapters: dict[str, Adapter] | None = None,
    progress: Callable[[NodeOutcome], None] | None = None,
) -> dict[str, list[NodeOutcome]]:
    """Run each case of each node for each tool. Return the node results of
    each tool, in the order of nodes."""
    unknown = [t for t in tools if t not in TOOLS]
    if unknown:
        raise ValueError(f"unknown tools {unknown}; the tools are {list(TOOLS)}")
    adapters = adapters or {t: ADAPTERS[t]() for t in tools}
    with tempfile.TemporaryDirectory(prefix="sqll-s7-layer-") as layer:
        runs = {t: tool_run(t, adapters[t], Path(layer)) for t in tools}

        def one(item: tuple[str, Node]) -> NodeOutcome:
            tool, node = item
            out = NodeOutcome(
                node.id, tool, [run_case(runs[tool], c) for c in node.cases]
            )
            if progress:
                progress(out)
            return out

        items = [(t, n) for t in tools for n in nodes]
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            results = list(pool.map(one, items))
    by_tool: dict[str, list[NodeOutcome]] = {t: [] for t in tools}
    for result in results:
        by_tool[result.tool].append(result)
    return by_tool
