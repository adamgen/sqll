"""Benchmark adapters and the validity checks (harness/bench.md, "Settings",
"Validity", "Add a tool").

A benchmark adapter maps each command of a benchmark (start, parse, lint,
fix) to the argv, env, and config file of one tool, and reads the output of
the tool. The checks in this module are the same for each tool. A tool is
one BenchAdapter subclass and one entry in registry.py; the definitions do
not change.

Each job runs in its own folder: config/ has the config file, runs/ has one
new folder for each run. prepare() writes a fresh copy of the input into the
folder of each run, so a fix run never sees the output of an earlier run.
"""

import hashlib
import json
import re
import shutil
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import preflight
from ..adapters.base import Unsupported
from ..code_only import to_node
from ..compare import has_node
from .inputs import START
from .timer import (
    ERROR,
    INVALID,
    PROFILES,
    UNSUPPORTED,
    WARMUP,
    Job,
    Measurement,
    Policy,
    Run,
    Series,
    run_in_turn,
    run_once,
)

PARSE = "parse"
LINT = "lint"
FIX = "fix"
COMMANDS = (START, PARSE, LINT, FIX)
EXPECTED_EXITS = {
    START: frozenset({0}),
    PARSE: frozenset({0}),
    LINT: frozenset({0, 1}),
    FIX: frozenset({0, 1}),
}
# The check of a lint run needs the check of parse on the same input; fix
# needs lint.
REQUIRES = {LINT: PARSE, FIX: LINT}
INPUT_FILE = "input.sql"
CONFIG_DIR = "config"
RUNS_DIR = "runs"
CHECKS_DIR = "checks"
# Violation codes of a lex, parse, or template error.
PARSE_ERROR_CODES = frozenset({"LXR", "PRS", "TMP"})
_UNPARSABLE_TEXT = re.compile(r"unparsable section", re.IGNORECASE)
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
REASON_TEXT = 200

# Messages that make a run of any tool invalid.
COMMON_PROBLEMS = (
    (re.compile(r"Traceback \(most recent call last\)"), "the tool crashed"),
    (re.compile(r"panicked at"), "the tool crashed (panic)"),
    (re.compile(r"^CRITICAL\s", re.MULTILINE), "a CRITICAL log"),
)


def settings(dialect: str | None = None) -> dict[str, Any]:
    """Return the settings of all tools, in the sqlfluff config structure."""
    core: dict[str, Any] = {} if dialect is None else {"dialect": dialect}
    core.update(
        {
            "templater": "raw",
            "rules": "all",
            "large_file_skip_byte_limit": 0,
            "large_file_skip_char_limit": 0,
        }
    )
    return {"core": core}


class InputError(Exception):
    """The input file is missing or is not the input of the definitions."""


class NoReference(Exception):
    """The definitions have no sqlfluff reference for the input."""


class ConfigAbove(Exception):
    """A folder above the work folder has a config file that a tool can read."""


Key = tuple[str, str, str, str]  # tool, command, dialect, input


class Context:
    """The data that the checks of a run share: the definitions (input
    hashes and the sqlfluff reference), the built inputs, the work folder,
    and the result of each check that ran.

    record_reference: the lint and fix checks do not compare with the
    reference. Only "sqll-harness bench reference" uses it, to make the
    sqlfluff reference.
    """

    def __init__(
        self,
        definitions: Mapping[str, Any],
        inputs_dir: Path,
        work_root: Path,
        timeout_s: float = PROFILES["full"].timeout_s,
        record_reference: bool = False,
    ) -> None:
        self.inputs_dir = Path(inputs_dir)
        self.work_root = Path(work_root).absolute()
        found = config_files_above(self.work_root)
        if found:
            raise ConfigAbove(
                "a tool can read these config files above the work folder "
                f"{self.work_root}: "
                + ", ".join(f"{path} ({reason})" for path, reason in found)
            )
        self.inputs = dict(definitions["inputs"])
        reference = definitions.get("reference") or {}
        self.reference = dict(reference.get("inputs") or {})
        self.timeout_s = timeout_s
        self.record_reference = record_reference
        self.checked: dict[Key, str | None] = {}
        self.work: dict[Key, dict | None] = {}
        self._data: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def input_data(self, name: str) -> bytes:
        """Return the input. InputError if its sha256 is not that of the
        definitions."""
        with self._lock:
            if name in self._data:
                return self._data[name]
        want = self.inputs.get(name)
        if want is None:
            raise InputError(f"input {name} is not in the definitions")
        path = self.inputs_dir / f"{name}.sql"
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise InputError(f"input {name}: {exc}") from None
        if hashlib.sha256(data).hexdigest() != want["sha256"]:
            raise InputError(
                f"input {name}: {path} is not the input of the definitions (sha256)"
            )
        with self._lock:
            self._data[name] = data
        return data

    def _reference(self, name: str) -> dict | None:
        if self.record_reference:
            return None
        ref = self.reference.get(name)
        if ref is None or ref.get("sha256") != self.inputs[name]["sha256"]:
            raise NoReference(
                f"the definitions have no sqlfluff reference for input {name}. "
                "Run: sqll-harness bench reference --write"
            )
        return ref

    def compare_codes(self, name: str, codes: list[str]) -> str | None:
        ref = self._reference(name)
        if ref is None or codes == ref["lint_codes"]:
            return None
        want = set(ref["lint_codes"])
        return (
            "the rule codes are not those of the sqlfluff reference: missing "
            f"{sorted(want - set(codes))}, extra {sorted(set(codes) - want)}"
        )

    def compare_fix(self, name: str, changed: bool) -> str | None:
        ref = self._reference(name)
        if ref is None or changed == ref["fix_changes"]:
            return None
        if changed:
            return "fix changed the file; in the sqlfluff reference it does not"
        return "fix did not change the file; in the sqlfluff reference it does"

    def note(self, key: Key, reason: str | None, work: dict | None) -> None:
        with self._lock:
            self.checked[key] = reason
            self.work[key] = work

    def validity(
        self, adapter: "BenchAdapter", command: str, dialect: str, name: str
    ) -> str | None:
        """Return the reason why the check of command fails for this tool and
        input, or None if it passes. If no run has checked it, do one run
        (not timed) in <work>/<tool>/checks/."""
        key = (adapter.name, command, dialect, name)
        with self._lock:
            if key in self.checked:
                return self.checked[key]
        benchmark = {
            "id": f"{command}/{dialect}/{name}",
            "command": command,
            "dialect": dialect,
            "size": None,
            "input": name,
        }
        folder = self.work_root / adapter.name / CHECKS_DIR / command / dialect / name
        bj = adapter.job(benchmark, self, folder)
        if bj.job is None:
            reason = bj.reason if bj.status == UNSUPPORTED else f"error: {bj.reason}"
        else:
            run_folder = bj.runs_folder / WARMUP
            run_folder.mkdir(parents=True)
            bj.job.prepare(run_folder)
            run = run_once(
                bj.job.argv,
                run_folder,
                kind=WARMUP,
                cwd=bj.job.cwd,
                env=bj.job.env,
                timeout_s=self.timeout_s,
            )
            if run.sample.timed_out:
                reason = f"timeout after {self.timeout_s} s"
            else:
                reason = bj.job.check(run)
        self.note(key, reason, bj.work)
        return reason


def config_files_above(folder: Path) -> list[tuple[Path, str]]:
    """Return each config file in folder or a parent that sqlfluff or sqruff
    can read."""
    found = preflight.parent_configs(folder / "_")
    for parent in dict.fromkeys([folder, *folder.parents]):
        if (parent / ".sqruff").is_file():
            found.append((parent / ".sqruff", "a .sqruff file"))
    return found


@dataclass
class BenchJob:
    """One benchmark of one tool. If job is None, the tool does not run it:
    status (unsupported or error) and reason say why."""

    benchmark: dict
    tool: str
    folder: Path
    ctx: Context
    job: Job | None = None
    status: str | None = None
    reason: str | None = None
    # The facts that the check of the warmup run found.
    work: dict | None = None

    @property
    def key(self) -> Key:
        b = self.benchmark
        return (self.tool, b["command"], b["dialect"], b["input"])

    @property
    def runs_folder(self) -> Path:
        return self.folder / RUNS_DIR

    def series(self, policy: Policy, keep_timed: bool = False) -> Series:
        if self.job is None:
            raise ValueError(f"{self.benchmark['id']}: {self.status}: {self.reason}")
        return Series(self.job, policy, self.runs_folder, keep_timed)

    def not_run(self) -> Measurement:
        return Measurement(self.status, self.reason, [], None)

    def finish(self, m: Measurement) -> None:
        """Record a warmup run that failed before its check (exit code,
        timeout), so that a check that needs it does not run it again."""
        if m.status == INVALID and self.key not in self.ctx.checked:
            self.ctx.note(self.key, m.reason, None)

    def measure(self, policy: Policy, keep_timed: bool = False) -> Measurement:
        if self.job is None:
            return self.not_run()
        m = run_in_turn([self.series(policy, keep_timed)])[0]
        self.finish(m)
        return m


class BenchAdapter(ABC):
    """How one tool runs the benchmarks. Subclasses give the tool parts.

    base_settings: the settings of all tools (settings()). A test can change
    it, for example to set a size limit.
    problems: (pattern, reason) of messages in the tool output that make a
    run invalid, in addition to COMMON_PROBLEMS. The checks read stderr, and
    for fix also stdout (parse and lint write JSON on stdout).
    """

    name: str
    problems: tuple[tuple[re.Pattern[str], str], ...] = ()

    def __init__(self) -> None:
        self.base_settings = settings()

    @abstractmethod
    def version(self) -> str:
        """Return the tool version."""

    def layer(self, config: dict[str, Any]) -> dict[str, Any]:
        """Return the config with the layer of the tool (as the S1 adapter)."""
        return config

    def config(self, dialect: str | None) -> dict[str, Any]:
        """Return the settings that the tool gets, in the sqlfluff config
        structure. With dialect None: the record for the report."""
        base = json.loads(json.dumps(self.base_settings))
        if dialect is not None:
            base["core"] = {"dialect": dialect, **base.get("core", {})}
        return self.layer(base)

    def unsupported_command(self, command: str) -> str | None:
        """Return the command if the tool does not have it, else None."""
        return None

    def unsupported(self, config: dict[str, Any]) -> str | None:
        """Return the item of config that the tool does not support, or None."""
        return None

    @abstractmethod
    def write_config(self, config: dict[str, Any], folder: Path) -> Path:
        """Write the config file of the tool in folder. Return its path.
        Raise Unsupported for an item that the tool does not support."""

    @abstractmethod
    def argv(self, command: str, config_file: Path, sql: str) -> list[str]:
        """Return the command line. The run starts in the folder of sql."""

    @abstractmethod
    def env(self) -> dict[str, str]:
        """Return the environment: no user config (adapters.base.isolated_env)."""

    @abstractmethod
    def read_tree(self, stdout: bytes, sql: str) -> Any:
        """Return the parse tree record ({"file": ...}) of sql, or None if
        there is none. ValueError if the output cannot be read."""

    @abstractmethod
    def read_violations(self, stdout: bytes, sql: str) -> list[dict] | None:
        """Return the lint violations of sql (each with a "code"), or None if
        the output has no result for sql. ValueError if it cannot be read."""

    def job(
        self, benchmark: Mapping[str, Any], ctx: Context, folder: Path | None = None
    ) -> BenchJob:
        """Return the job of one benchmark (an entry of the definitions)."""
        command = benchmark["command"]
        if command not in COMMANDS:
            raise ValueError(f"unknown command {command!r}")
        folder = folder or ctx.work_root / self.name / benchmark["id"]
        bj = BenchJob(dict(benchmark), self.name, folder, ctx)
        config = self.config(benchmark["dialect"])
        item = self.unsupported_command(command) or self.unsupported(config)
        if item is not None:
            bj.status, bj.reason = UNSUPPORTED, f"unsupported: {item}"
            return bj
        try:
            data = ctx.input_data(benchmark["input"])
            if folder.exists():
                shutil.rmtree(folder)
            config_file = self.write_config(config, folder / CONFIG_DIR)
        except Unsupported as exc:
            bj.status, bj.reason = UNSUPPORTED, f"unsupported: {exc.item}"
            return bj
        except (InputError, ValueError, OSError) as exc:
            bj.status, bj.reason = ERROR, str(exc)
            return bj

        def prepare(run_folder: Path) -> None:
            (run_folder / INPUT_FILE).write_bytes(data)

        def check(run: Run) -> str | None:
            reason, work = check_run(self, ctx, bj.benchmark, data, run)
            bj.work = work
            ctx.note(bj.key, reason, work)
            return reason

        bj.job = Job(
            argv=self.argv(command, config_file, INPUT_FILE),
            expected_exits=EXPECTED_EXITS[command],
            env=self.env(),
            prepare=prepare,
            check=check,
        )
        return bj


# The checks.


def _text(data: bytes) -> str:
    return _ANSI.sub("", data.decode("utf8", errors="replace"))


def find_problem(adapter: BenchAdapter, text: str) -> str | None:
    """Return the first problem message in text, with its line."""
    for pattern, reason in (*COMMON_PROBLEMS, *adapter.problems):
        m = pattern.search(text)
        if m:
            start = text.rfind("\n", 0, m.start()) + 1
            end = text.find("\n", m.end())
            line = text[start : end if end >= 0 else len(text)].strip()
            return f"{reason}: {line[:REASON_TEXT]}"
    return None


def leaves(record: Any) -> Iterator[str]:
    """Yield the text of each leaf of a tree record in document order."""
    stack = [to_node(record)]
    while stack:
        _, value = stack.pop()
        if isinstance(value, str):
            yield value
        else:
            stack.extend(reversed(value))


def check_tree(adapter: BenchAdapter, stdout: bytes, data: bytes) -> str | None:
    """The parse check: a tree, with no unparsable segment, of all the input."""
    try:
        record = adapter.read_tree(stdout, INPUT_FILE)
        if record is None:
            return "no parse tree"
        if has_node(record, "unparsable"):
            return "the tree has an unparsable segment"
        text = "".join(leaves(record))
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return f"no parse tree: {exc!r}"[:REASON_TEXT]
    source = data.decode("utf8", errors="replace")
    if text != source:
        return (
            f"the tree text ({len(text)} characters) is not the input text "
            f"({len(source)} characters)"
        )
    return None


def check_run(
    adapter: BenchAdapter,
    ctx: Context,
    benchmark: Mapping[str, Any],
    data: bytes,
    run: Run,
) -> tuple[str | None, dict | None]:
    """Return (reason, work) for a run of a benchmark. reason is None if the
    run is valid. work has the facts that the check found."""
    command, dialect, name = (
        benchmark["command"],
        benchmark["dialect"],
        benchmark["input"],
    )
    stdout = run.stdout.read_bytes()
    text = _text(run.stderr.read_bytes())
    if command == FIX:
        text = _text(stdout) + "\n" + text
    problem = find_problem(adapter, text)
    if problem:
        return problem, None
    code = run.sample.exit_code
    if code not in EXPECTED_EXITS[command]:
        want = ", ".join(str(c) for c in sorted(EXPECTED_EXITS[command]))
        return f"exit code {code}, expected {want}", None
    if command in (START, PARSE):
        return check_tree(adapter, stdout, data), None
    if command == LINT:
        return _check_lint(adapter, ctx, dialect, name, stdout)
    return _check_fix(adapter, ctx, dialect, name, data, run)


def _required(adapter, ctx, command, dialect, name) -> str | None:
    need = REQUIRES[command]
    reason = ctx.validity(adapter, need, dialect, name)
    return None if reason is None else f"the {need} check fails: {reason}"


Checked = tuple[str | None, dict | None]


def _check_lint(adapter, ctx, dialect, name, stdout) -> Checked:
    try:
        violations = adapter.read_violations(stdout, INPUT_FILE)
    except (ValueError, TypeError, KeyError) as exc:
        return f"no lint output: {exc!r}"[:REASON_TEXT], None
    if violations is None:
        # sqruff gives no result and no message for a file over its size limit.
        return "no lint result for the input file", None
    codes = sorted({str(v["code"]) for v in violations})
    work = {"violations": len(violations), "codes": codes}
    errors = sorted(
        {str(v["code"]) for v in violations if v["code"] in PARSE_ERROR_CODES}
        | {
            "unparsable section"
            for v in violations
            if _UNPARSABLE_TEXT.search(str(v.get("description", "")))
        }
    )
    if errors:
        return f"the lint output has a parse error: {', '.join(errors)}", work
    reason = _required(adapter, ctx, LINT, dialect, name) or ctx.compare_codes(
        name, codes
    )
    return reason, work


def _check_fix(adapter, ctx, dialect, name, data, run) -> Checked:
    try:
        fixed = (run.folder / INPUT_FILE).read_bytes()
    except OSError as exc:
        return f"no fixed file: {exc}", None
    changed = fixed != data
    work = {"changed": changed, "fixed_sha256": hashlib.sha256(fixed).hexdigest()}
    reason = _required(adapter, ctx, FIX, dialect, name) or ctx.compare_fix(
        name, changed
    )
    return reason, work
