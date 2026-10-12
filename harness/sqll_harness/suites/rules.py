# The case loading and the checks in this file are a port of sqlfluff
# 4.4.0 code: src/sqlfluff/utils/testing/rules.py (load_test_cases,
# _setup_config, assert_rule_fail_in_sql, assert_rule_pass_in_sql,
# prep_violations, rules__test_helper). Copyright (c) 2018-2026 Alan
# Cruickshank. MIT License. See THIRD_PARTY.md.
"""Rule case suite: test/fixtures/rules/std_rule_cases/*.yml.

Each top-level key of a file, except "rule" and "configs", is one case. The
checks are those of rules__test_helper in sqlfluff, through the lint and fix
commands of a tool. See harness/README.md.
"""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..adapters import Adapter
from ..adapters.base import LintResult
from ..cases import FAIL, PASS, SKIP, CaseResult

NAME = "rules"
FIXTURE_DIR = Path("test") / "fixtures" / "rules" / "std_rule_cases"

# The fields of RuleTestCase in sqlfluff, other than "rule". sqlfluff fails
# on a case with another key.
CASE_FIELDS = frozenset(
    {
        "desc",
        "pass_str",
        "fail_str",
        "violations",
        "fix_str",
        "violations_after_fix",
        "configs",
        "skip",
        "line_numbers",
    }
)
# Violations from templating, lexing, and parsing. Any of them makes a
# pass_str fail (the test parses the string and fails on each violation).
PARSE_STAGE_CODES = frozenset({"TMP", "LXR", "PRS"})
# The fail_str check fails only on SQLParseError and SQLTemplaterError.
FAIL_STR_ERROR_CODES = frozenset({"TMP", "PRS"})
# The codes of the violations that are not lint violations (SQLLintError).
NON_LINT_CODES = frozenset({"TMP", "LXR", "PRS", "NOQA"})


@dataclass(frozen=True)
class RuleCase:
    """One rule test case. The fields are those of RuleTestCase in sqlfluff."""

    id: str
    rule: str
    desc: str | None = None
    pass_str: str | None = None
    fail_str: str | None = None
    violations: list[dict[str, Any]] | None = None
    fix_str: str | None = None
    violations_after_fix: list[dict[str, Any]] | None = None
    configs: dict[str, Any] | None = None
    skip: str | None = None
    line_numbers: list[int] = field(default_factory=list)


def load_file(path: Path) -> list[RuleCase]:
    """Load the cases of one YAML file, as load_test_cases in sqlfluff does.

    The file-level "configs" applies to each case that has no "configs" key.
    The case id is rules/<file stem>/<key>.
    """
    data = yaml.safe_load(path.read_text(encoding="utf8"))
    if not isinstance(data, dict) or "rule" not in data:
        raise ValueError(f"{path}: no 'rule' key")
    rule = data.pop("rule")
    global_config = data.pop("configs", None)
    cases = []
    for key, spec in data.items():
        if not isinstance(spec, dict):
            raise ValueError(f"{path}: case {key!r} is not a mapping")
        unknown = set(spec) - CASE_FIELDS
        if unknown:
            raise ValueError(f"{path}: case {key!r} has unknown keys {sorted(unknown)}")
        if global_config and "configs" not in spec:
            spec = {**spec, "configs": global_config}
        cases.append(RuleCase(id=f"{NAME}/{path.stem}/{key}", rule=rule, **spec))
    return cases


def discover(sqlfluff_root: Path) -> list[RuleCase]:
    """Load each case of each std_rule_cases/*.yml file, in file order."""
    cases = []
    for path in sorted((sqlfluff_root / FIXTURE_DIR).glob("*.yml")):
        cases += load_file(path)
    return cases


def rule_codes(rule: str) -> list[str]:
    """Split "AL02, LT01" into ["AL02", "LT01"]."""
    return [code.strip() for code in rule.split(",") if code.strip()]


def default_dialect(configs: dict[str, Any] | None) -> str | None:
    """Return "ansi" if the case config sets no dialect, as sqlfluff does."""
    core = configs.get("core", {}) if configs else {}
    if not isinstance(core, dict) or "dialect" not in core:
        return "ansi"
    return None


def pass_problems(violations: list[dict], codes: list[str]) -> list[str]:
    """Return why a pass_str fails (assert_rule_pass_in_sql)."""
    problems = []
    stage = [v for v in violations if v.get("code") in PARSE_STAGE_CODES]
    if stage:
        problems.append(f"{stage[0]['code']}: {stage[0].get('description', '')}")
    found = [v for v in violations if v.get("code") in codes]
    if found:
        lines = sorted({v.get("start_line_no") for v in found})
        problems.append(f"{len(found)} violations of {','.join(codes)} (lines {lines})")
    return problems


def fail_problems(
    violations: list[dict],
    codes: list[str],
    line_numbers: list[int],
    expected: list[dict] | None,
    rule: str,
) -> list[str]:
    """Return why a fail_str fails (assert_rule_fail_in_sql).

    expected is the "violations" (or "violations_after_fix") list of the
    case. The test compares it with all violations of the file.
    """
    # The test uses get_violations(), which removes warnings.
    shown = [v for v in violations if not v.get("warning")]
    problems = []
    crashes = [
        v
        for v in shown
        if str(v.get("description", "")).startswith("Unexpected exception")
    ]
    if crashes:
        problems.append(f"rule crash: {crashes[0]['description'].splitlines()[0]}")
    errors = [v for v in shown if v.get("code") in FAIL_STR_ERROR_CODES]
    if errors:
        problems.append(f"{errors[0]['code']}: {errors[0].get('description', '')}")
    lint = [v for v in shown if v.get("code") not in NON_LINT_CODES]
    if not any(v.get("code") in codes for v in lint):
        problems.append(f"no violation of {','.join(codes)}")
    if line_numbers:
        actual = [v.get("start_line_no") for v in lint]
        if actual != line_numbers:
            problems.append(f"line numbers {actual}, expected {line_numbers}")
    if expected and not violations_match(violations, expected, rule):
        problems.append("violations differ")
    return problems


def _position(v: dict) -> tuple:
    return (v.get("start_line_no", 0), v.get("start_line_pos", 0))


def violations_match(actual: list[dict], expected: list[dict], rule: str) -> bool:
    """Compare violations as assert_violations_before_fix does.

    The test compares the list of all violations, in the order of sqlfluff:
    sorted by line and position. "lint -f json" sorts again by line,
    position, and code. Thus the expected list must be sorted by line and
    position, and equal to the tool output after the same second sort. As
    in prep_violations, a violation with no code gets the rule of the case.
    """
    prepared = [v if "code" in v else {**v, "code": rule} for v in expected]
    if prepared != sorted(prepared, key=_position):
        return False
    resorted = sorted(prepared, key=lambda v: (*_position(v), str(v["code"])))
    return actual == resorted


def _lint_problems(lint: LintResult) -> list[str]:
    return [f"lint: {e}" for e in lint.errors]


def run(adapter: Adapter, case: RuleCase, sqlfluff_root: Path) -> CaseResult:
    """Run one case as rules__test_helper in sqlfluff does."""
    if case.skip:
        return CaseResult(case.id, NAME, adapter.name, SKIP, reason=str(case.skip))
    codes = rule_codes(case.rule)
    dialect = default_dialect(case.configs)
    checks: dict[str, bool] = {}
    reasons: list[str] = []

    def check(name: str, problems: list[str]) -> None:
        checks[name] = not problems
        reasons.extend(f"{name}: {p}" for p in problems)

    with tempfile.TemporaryDirectory(prefix="sqll-rule-") as tmp:
        work = Path(tmp)
        # The truth tests are as in sqlfluff: an empty string is no string.
        sql = {
            "pass": case.pass_str,
            "fail": case.fail_str,
            "fixed": case.fix_str if case.fail_str else None,
        }
        paths = {k: work / f"{k}.sql" for k, text in sql.items() if text}
        for k, path in paths.items():
            path.write_bytes(sql[k].encode("utf8"))
        lint = None
        if paths:
            lint = adapter.lint(
                list(paths.values()), codes, dialect, case.configs, work
            )

        def violations(k: str) -> list[dict] | None:
            if lint is None or lint.violations is None or lint.errors:
                return None
            return lint.violations[paths[k]]

        if case.pass_str:
            found = violations("pass")
            check(
                "pass_str",
                _lint_problems(lint) if found is None else pass_problems(found, codes),
            )

        if case.fail_str:
            found = violations("fail")
            check(
                "fail_str",
                _lint_problems(lint)
                if found is None
                else fail_problems(
                    found, codes, case.line_numbers, case.violations, case.rule
                ),
            )
            fix_path = work / "fix.sql"
            fix_path.write_bytes(case.fail_str.encode("utf8"))
            fix = adapter.fix(fix_path, codes, dialect, case.configs, work)
            want = case.fix_str if case.fix_str else case.fail_str
            if fix.fixed is None:
                check("fix", [f"tool: {e}" for e in fix.errors])
            else:
                checks["fix"] = fix.fixed == want
                if not checks["fix"]:
                    reasons.append("fix mismatch")

            if case.fix_str:
                found = violations("fixed")
                if found is None:
                    problems = _lint_problems(lint)
                elif case.violations_after_fix:
                    problems = fail_problems(
                        found,
                        codes,
                        case.line_numbers,
                        case.violations_after_fix,
                        case.rule,
                    )
                else:
                    problems = pass_problems(found, codes)
                check("after_fix", problems)

    return CaseResult(
        id=case.id,
        suite=NAME,
        tool=adapter.name,
        status=PASS if all(checks.values()) else FAIL,
        checks=checks,
        reason="; ".join(reasons),
    )
