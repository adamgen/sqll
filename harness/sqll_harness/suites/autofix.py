# The case discovery and the checks in this file are a port of sqlfluff 4.4.0
# code: test/rules/std_fix_auto_test.py (test_cases, auto_fix_test).
# Copyright (c) 2018-2026 Alan Cruickshank. MIT License. See THIRD_PARTY.md.
"""Autofix suite: test/fixtures/linter/autofix/<dialect>/<case>/.

The checks are those of auto_fix_test in sqlfluff, through the fix command of
a tool. See harness/autofix.md.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..adapters import Adapter
from ..adapters.base import FileFixResult
from ..cases import ERROR, FAIL, PASS, CaseResult
from .rules import NON_LINT_CODES

NAME = "autofix"
FIXTURE_DIR = Path("test") / "fixtures" / "linter" / "autofix"
# The file names in the temporary folder of the test.
SQL_NAME = "testing.sql"
CONFIG_NAME = ".sqlfluff"
NOT_LINTED_REASON = "the tool did not lint the file; the test fails ('LintedDir empty')"
NO_TREE_REASON = (
    "the tool has no parse tree for the file; the test fails ('res.tree' is None)"
)
GATE_REASON = (
    "fix: 'sqlfluff fix' does not apply fixes to a file with a templating or "
    "parse error, also an ignored one, but the test applies them"
)


@dataclass(frozen=True)
class AutofixCase:
    """One autofix case: a folder <dialect>/<name>/ with its files."""

    id: str
    dialect: str
    folder: Path


def discover_dir(base: Path) -> list[AutofixCase]:
    """Find the cases in base as test_cases in sqlfluff does.

    Each entry in a dialect folder is a case. The test ignores only the
    entries of base that end with ".md". The order is sorted.
    """
    cases = []
    for dialect in sorted(os.listdir(base)):
        if dialect.endswith(".md"):
            continue
        for name in sorted(os.listdir(base / dialect)):
            cases.append(
                AutofixCase(f"{NAME}/{dialect}/{name}", dialect, base / dialect / name)
            )
    return cases


def discover(sqlfluff_root: Path) -> list[AutofixCase]:
    return discover_dir(sqlfluff_root / FIXTURE_DIR)


@dataclass(frozen=True)
class CaseConfig:
    """The test-config.yml of a case, as auto_fix_test reads it.

    rules is None if the test gives no rules override: the rules of the
    config files apply.
    """

    rules: str | None
    raise_on_non_linting_violations: Any


def load_test_config(path: Path) -> CaseConfig:
    """Read test-config.yml as auto_fix_test does.

    The rules are joined with "," and then upper-cased. If the result has
    "ALL" in it, or is empty, the test sets no rules. The test ignores the
    other keys, for example "dialect". An error here makes the test fail.
    """
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    rules: str | None = ",".join(cfg["test-config"].get("rules")).upper()
    if "ALL" in rules:
        rules = None
    raise_on_non_linting = cfg["test-config"].get(
        "raise_on_non_linting_violations", True
    )
    return CaseConfig(rules or None, raise_on_non_linting)


def write_text(path: Path, text: str) -> None:
    """Write a file as the test does: text mode, with the default newline."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read_text(path: Path) -> str:
    """Read a file as the test does: text mode, with universal newlines.

    Thus "\\r\\n" and "\\r" become "\\n". The test uses the locale
    encoding; the harness uses UTF-8.
    """
    with open(path, encoding="utf-8") as f:
        return f.read()


def expected_violations(data: Any) -> set[tuple]:
    """Return the check tuples of a violations.json, as the test makes them.

    Each item of violations.linting.<rule> is a list [line, position]; the
    tuple is (rule, line, position).
    """
    expected = set()
    for rule_key in data["violations"]["linting"]:
        for elem in data["violations"]["linting"][rule_key]:
            expected.add((rule_key, *elem))
    return expected


def check_tuples(violations: list[dict[str, Any]]) -> set[tuple]:
    """Return the check tuples of the lint violations (LintedDir.check_tuples)."""
    return {
        (v["code"], v["start_line_no"], v["start_line_pos"])
        for v in violations
        if v["code"] not in NON_LINT_CODES
    }


def _result(case: AutofixCase, adapter: Adapter, status: str, **kw) -> CaseResult:
    return CaseResult(case.id, NAME, adapter.name, status, **kw)


def run(adapter: Adapter, case: AutofixCase, sqlfluff_root: Path) -> CaseResult:
    """Run one case as auto_fix_test in sqlfluff does.

    The current folder of the tool is the sqlfluff root, as for the test: a
    case config can load macros with a path relative to it. There are 2
    copies of the files. In <tmp>/fix/ the harness parses the file (parse
    does not change it), then runs "fix": this gives the fixed file and
    tells if the tool did not fix because of a parse error. In <tmp>/show/
    it runs "fix" that shows the violations.
    """
    # The test reads these files. If one is missing or not valid, it fails.
    try:
        test_config = load_test_config(case.folder / "test-config.yml")
        before = read_text(case.folder / "before.sql")
        # The test opens .sqlfluff for writing before it reads the config of
        # the case. Thus the file is empty if the case has no config.
        config_path = case.folder / CONFIG_NAME
        config = read_text(config_path) if config_path.exists() else ""
        violations_path = case.folder / "violations.json"
        expected = None
        if violations_path.exists():
            with open(violations_path, encoding="utf-8") as f:
                expected = json.load(f)
        after = read_text(case.folder / "after.sql")
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        yaml.YAMLError,
    ) as exc:
        return _result(
            case, adapter, FAIL, reason=f"the test fails: {type(exc).__name__}: {exc}"
        )
    rules = test_config.rules.split(",") if test_config.rules else None

    runs: list[FileFixResult] = []
    fixed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sqll-autofix-") as tmp:
        for show in (False, True):
            work = Path(tmp) / ("show" if show else "fix")
            work.mkdir()
            sql = work / SQL_NAME
            write_text(sql, before)
            write_text(work / CONFIG_NAME, config)
            if not show:
                parsed = adapter.parse_file(sql, case.dialect, sqlfluff_root)
            runs.append(adapter.fix_file(sql, rules, case.dialect, sqlfluff_root, show))
            fixed.append(read_text(sql) if not runs[-1].errors else "")
    fix_run, show_run = runs

    errors = [f"parse: {e}" for e in parsed.errors]
    errors += [f"fix: {e}" for r in runs for e in r.errors]
    if errors:
        return _result(case, adapter, ERROR, reason="; ".join(errors))
    critical = [c for r in runs for c in r.critical]
    if critical:
        # The test fails on conflicting fixes, but not on a rule exception.
        return _result(
            case,
            adapter,
            ERROR,
            reason=f"fix: the tool logged CRITICAL '{critical[0]}'; the test "
            "can fail there",
        )
    if not show_run.linted:
        return _result(case, adapter, FAIL, reason=NOT_LINTED_REASON)

    if parsed.tree is None:
        return _result(
            case, adapter, FAIL, checks={"tree": False}, reason=NO_TREE_REASON
        )

    checks: dict[str, bool] = {"tree": True}
    reasons: list[str] = []
    unknown: list[str] = []
    # A tool with no warning field (sqruff) gives no "warning" key; the
    # adapter fails the case if the config sets warnings.
    shown = [v for v in show_run.violations or [] if not v.get("warning")]
    non_lint = [v for v in shown if v["code"] in NON_LINT_CODES]
    raises = bool(test_config.raise_on_non_linting_violations) and bool(non_lint)
    if test_config.raise_on_non_linting_violations:
        checks["non_linting"] = not non_lint
        if non_lint:
            v = non_lint[0]
            reasons.append(
                f"non_linting: {v['code']} at line {v['start_line_no']}, "
                f"position {v['start_line_pos']}"
            )
    if expected:
        try:
            want = expected_violations(expected)
        except (KeyError, TypeError, AttributeError) as exc:
            checks["violations"] = False
            reasons.append(f"violations: violations.json: {type(exc).__name__}")
        else:
            got = check_tuples(shown)
            checks["violations"] = got == want
            if got != want:
                reasons.append(
                    f"violations: missing {sorted(want - got, key=str)}, "
                    f"extra {sorted(got - want, key=str)}"
                )
    # The 2 runs fix the same file with the same config. A tool can find the
    # gate only in one of them (for example, only from shown violations).
    if fix_run.unparsable_gate or show_run.unparsable_gate:
        if not raises:
            unknown.append(GATE_REASON)
    elif fixed[0] != fixed[1]:
        unknown.append("fix: the 2 fix runs gave different files")
    else:
        checks["fix"] = fixed[0] == after
        if not checks["fix"]:
            reasons.append("fix mismatch")

    # The test stops at the first check that fails. Thus a failed check gives
    # "fail" also if the result of another check is not known.
    if not all(checks.values()):
        status = FAIL
    elif unknown:
        status = ERROR
    else:
        status = PASS
    return _result(
        case, adapter, status, checks=checks, reason="; ".join(reasons + unknown)
    )
