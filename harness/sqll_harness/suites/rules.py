# The case loading and the checks in this file are a port of sqlfluff
# 4.4.0 code: src/sqlfluff/utils/testing/rules.py (load_test_cases,
# _setup_config, assert_rule_fail_in_sql, assert_rule_pass_in_sql,
# prep_violations, rules__test_helper). Copyright (c) 2018-2026 Alan
# Cruickshank. MIT License. See THIRD_PARTY.md.
"""Rule case suite: test/fixtures/rules/std_rule_cases/*.yml.

Each top-level key of a file, except "rule" and "configs", is one case. The
checks are those of rules__test_helper in sqlfluff, through the lint and fix
commands of a tool. See harness/rules.md.
"""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..adapters import Adapter
from ..adapters.base import LintResult, Unsupported
from ..cases import ERROR, FAIL, PASS, SKIP, CaseResult

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
CARRIAGE_RETURN_REASON = (
    "a SQL string has a carriage return; the tool reads files with universal "
    "newlines, so the harness cannot give it the same string"
)
# FluffConfig.process_raw_file_for_config reads a line with one of these
# prefixes as config.
INLINE_CONFIG_PREFIXES = ("-- sqlfluff", "--sqlfluff")
INLINE_CONFIG_REASON = (
    "a SQL string has an in-file config line ('-- sqlfluff...'); it overrides "
    "the config file, so the harness cannot get the violation lists with no "
    "filter"
)
# The jinja templater (the default) starts a tag with one of these strings.
# The case config can change them in the templater.jinja section.
JINJA_START_STRINGS = {
    "variable_start_string": "{{",
    "block_start_string": "{%",
    "comment_start_string": "{#",
}
TEMPLATED_NOQA_REASON = (
    "a SQL string can be templated and a noqa comment changes the lint "
    "output; the tool applies the noqa comments of the root variant to all "
    "variants, so the harness cannot get the violation lists of the test"
)
# The rank of each violation type in the list of the test before its sort by
# line and position: templating, lexing, parsing, bad noqa, lint errors.
_STAGE_RANK = {"TMP": 0, "LXR": 1, "PRS": 2}
_NOQA_RANK = 3
_LINT_RANK = 4


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


@dataclass
class Found:
    """The violations of one SQL file, as the sqlfluff test sees them.

    filtered: what get_violations() gives, but with warnings. "lint -f json"
    with the case config gives this list.
    raw: all violations (LintedFile.violations), with no "ignore" or noqa
    filter.
    parse_stage: the TMP, LXR, and PRS violations of templating, lexing,
    and parsing, with no filter (ParsedString.violations).
    noqa_errors: the PRS violations in raw for a bad noqa comment.
    """

    filtered: list[dict]
    raw: list[dict]
    parse_stage: list[dict]
    noqa_errors: list[dict] = field(default_factory=list)

    @classmethod
    def from_one(cls, violations: list[dict]) -> "Found":
        """Use when no filter applies: no core "ignore" and no noqa comment."""
        stage = [v for v in violations if v.get("code") in PARSE_STAGE_CODES]
        return cls(violations, violations, stage)


def compose(filtered: list[dict], unignored: list[dict], no_noqa: list[dict]) -> Found:
    """Make Found from 3 lint outputs of one file.

    filtered: lint with the case config.
    unignored: lint with no core "ignore". The lint errors are those of the
    test: a noqa comment for a rule removes its lint errors before any list.
    no_noqa: lint with no core "ignore" and with disable_noqa. The noqa
    comments do not remove TMP, LXR, or PRS violations, and give no PRS for a
    bad noqa comment.
    """
    stage = [v for v in no_noqa if v.get("code") in PARSE_STAGE_CODES]
    lint = [v for v in unignored if v.get("code") not in NON_LINT_CODES]
    noqa_errors = [v for v in unignored if v.get("code") == "PRS"]
    for v in stage:
        if v in noqa_errors:
            noqa_errors.remove(v)
    return Found(filtered, stage + noqa_errors + lint, stage, noqa_errors)


def pass_problems(found: Found, codes: list[str]) -> list[str]:
    """Return why a pass_str fails (assert_rule_pass_in_sql).

    The test fails on each violation of parse_rendered, and on each lint
    error of the rules in the full list. Thus "ignore" and noqa do not apply.
    """
    problems = []
    stage = found.parse_stage
    if stage:
        problems.append(f"{stage[0]['code']}: {stage[0].get('description', '')}")
    hits = [v for v in found.raw if v.get("code") in codes]
    if hits:
        lines = sorted({v.get("start_line_no") for v in hits})
        problems.append(f"{len(hits)} violations of {','.join(codes)} (lines {lines})")
    return problems


def fail_problems(
    found: Found,
    codes: list[str],
    line_numbers: list[int],
    expected: list[dict] | None,
    rule: str,
) -> list[str]:
    """Return why a fail_str fails (assert_rule_fail_in_sql).

    expected is the "violations" (or "violations_after_fix") list of the
    case. The test compares it with all violations of the file, with no
    filter. The other checks use get_violations(), which applies the
    filters and removes warnings.
    """
    shown = [v for v in found.filtered if not v.get("warning")]
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
    if expected and not violations_match(found.raw, expected, rule, found.noqa_errors):
        problems.append("violations differ")
    return problems


def sqlfluff_order(violations: list[dict], noqa_errors: list[dict]) -> list[dict]:
    """Put violations from "lint -f json" in the order of LintedFile.violations.

    lint_parsed makes the list in this order: TMP, then LXR and PRS of the
    root variant, then the PRS of each bad noqa comment, then the lint errors
    in rule code order. deduplicate_in_source_space then does a stable sort
    by line and position. A bad noqa PRS has position 0 in that sort.
    "lint -f json" sorts by line, position, and code, and keeps the order of
    equal items. Thus a stable sort by line, position, and rank gives the
    order of the test. The lint errors of other template variants are last
    at their position in the test; this function cannot find them.
    """

    def key(v: dict) -> tuple:
        line, pos = v.get("start_line_no", 0), v.get("start_line_pos", 0)
        if v in noqa_errors:
            return (line, 0, _NOQA_RANK)
        return (line, pos, _STAGE_RANK.get(v.get("code"), _LINT_RANK))

    return sorted(violations, key=key)


def violations_match(
    actual: list[dict],
    expected: list[dict],
    rule: str,
    noqa_errors: list[dict] | None = None,
) -> bool:
    """Compare violations as assert_violations_before_fix does.

    The test compares the list of all violations, in its order (see
    sqlfluff_order). As in prep_violations, a violation with no code gets the
    rule of the case.
    """
    prepared = [v if "code" in v else {**v, "code": rule} for v in expected]
    return sqlfluff_order(actual, noqa_errors or []) == prepared


def has_inline_config(sql: str) -> bool:
    """Return True if a line of sql is an in-file config line for sqlfluff."""
    return any(line.startswith(INLINE_CONFIG_PREFIXES) for line in sql.splitlines())


def can_template(sql: str, configs: dict[str, Any] | None) -> bool:
    """Return True if templating can make text that is not in sql.

    Then a noqa comment can be in the rendered SQL and not in sql, a
    template can have more than one variant, and a lint error can be in a
    templated area. The tags are the default jinja start strings and the
    start strings that the case config sets.
    """
    core = configs.get("core") if configs else None
    if isinstance(core, dict) and core.get("templater", "raw") != "raw":
        return True
    templater = configs.get("templater") if configs else None
    jinja = templater.get("jinja") if isinstance(templater, dict) else None
    tags = list(JINJA_START_STRINGS.values())
    if isinstance(jinja, dict):
        for key in JINJA_START_STRINGS:
            if key not in jinja:
                continue
            if not isinstance(jinja[key], str) or not jinja[key]:
                return True
            tags.append(jinja[key])
    return any(tag in sql for tag in tags)


def fix_not_shown(
    found: Found, lists: list[list[dict]], configs: dict[str, Any] | None
) -> str | None:
    """Return why the fixed file can be different from the test, or None.

    The test always applies the fixes (fix_string). "sqlfluff fix" writes the
    file only if it has no TMP or PRS violation, with no filter, or if
    fix_even_unparsable is set (Linter.lint_paths). It also writes the file
    only if a violation in the filtered list has fixes (persist_tree). If it
    does not write the file and a rule gave fixes, the result of the test is
    not known. lists are all lint outputs of the file, also the lint that
    keeps the lint errors in templated areas (see templated_area_config).
    """
    if not any(v.get("fixes") for violations in lists for v in violations):
        return None
    core = configs.get("core") if configs else None
    even = isinstance(core, dict) and core.get("fix_even_unparsable") is True
    blocking = [v for v in found.raw if v.get("code") in FAIL_STR_ERROR_CODES]
    if blocking and not even:
        return (
            f"'sqlfluff fix' does not write a file with a {blocking[0]['code']} "
            "violation, but the test applies the fixes"
        )
    if not any(v.get("fixes") for v in found.filtered):
        return (
            "'sqlfluff fix' does not write a file when only hidden violations "
            "(ignore, noqa, or templated areas) have fixes, but the test "
            "applies the fixes"
        )
    return None


def config_without_ignore(configs: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the config with no core "ignore", or None if it has none."""
    core = configs.get("core") if configs else None
    if not isinstance(core, dict) or "ignore" not in core:
        return None
    return {**configs, "core": {k: v for k, v in core.items() if k != "ignore"}}


def config_without_noqa(configs: dict[str, Any] | None) -> dict[str, Any]:
    """Return the config with no core "ignore" and with disable_noqa."""
    core = configs.get("core") if configs else None
    core = dict(core) if isinstance(core, dict) else {}
    core.pop("ignore", None)
    core.pop("disable_noqa_except", None)
    core["disable_noqa"] = True
    return {**(configs or {}), "core": core}


def templated_area_config(configs: dict[str, Any] | None) -> dict[str, Any]:
    """Return the config with no core "ignore" and ignore_templated_areas off.

    In fix mode the test applies the fixes of a lint error in a templated
    area. remove_templated_errors removes the lint error only after the fix
    loop. Thus "lint -f json" with the case config does not show these fixes.
    """
    configs = config_without_ignore(configs) or configs or {}
    core = configs.get("core")
    core = dict(core) if isinstance(core, dict) else {}
    core["ignore_templated_areas"] = False
    return {**configs, "core": core}


def _lint_problems(lints: list[LintResult]) -> list[str]:
    # _lint_all can give the same result 2 times.
    unique = {id(lint): lint for lint in lints}.values()
    return [f"lint: {e}" for lint in unique for e in lint.errors]


def run(adapter: Adapter, case: RuleCase, sqlfluff_root: Path) -> CaseResult:
    """Run one case as rules__test_helper in sqlfluff does."""
    if case.skip:
        return CaseResult(case.id, NAME, adapter.name, SKIP, reason=str(case.skip))
    if any("\r" in s for s in (case.pass_str, case.fail_str, case.fix_str) if s):
        # sqlfluff reads a file with universal newlines: "\r" becomes "\n".
        # The test gives the string, so no file can give the same input.
        return CaseResult(
            case.id, NAME, adapter.name, ERROR, reason=CARRIAGE_RETURN_REASON
        )
    if any(
        has_inline_config(s) for s in (case.pass_str, case.fail_str, case.fix_str) if s
    ):
        return CaseResult(
            case.id, NAME, adapter.name, ERROR, reason=INLINE_CONFIG_REASON
        )
    check_fields(adapter, case)
    codes = rule_codes(case.rule)
    dialect = default_dialect(case.configs)
    checks: dict[str, bool] = {}
    reasons: list[str] = []
    # Checks that the CLI cannot show. Their result is not known.
    unknown: list[str] = []

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
        templated = [p for k, p in paths.items() if can_template(sql[k], case.configs)]
        lints: list[LintResult] = []
        if paths:
            lints = _lint_all(
                adapter, list(paths.values()), templated, codes, dialect, case, work
            )
        # In fix mode the test applies the fixes of the lint errors in
        # templated areas. Only a lint that keeps these errors shows them.
        templated_area: LintResult | None = None
        if "fail" in paths and paths["fail"] in templated:
            area_config = templated_area_config(case.configs)
            templated_area = adapter.lint(
                [paths["fail"]], codes, dialect, area_config, work
            )
        problems = _lint_problems(lints + ([templated_area] if templated_area else []))
        if problems:
            # The tool gave no usable output: the result is not known.
            return CaseResult(
                case.id, NAME, adapter.name, ERROR, reason="; ".join(problems)
            )
        if noqa_mask_active(lints, templated):
            return CaseResult(
                case.id, NAME, adapter.name, ERROR, reason=TEMPLATED_NOQA_REASON
            )

        def outputs(k: str) -> list[list[dict]]:
            return [r.violations[paths[k]] for r in lints]

        def found(k: str) -> Found:
            lists = outputs(k)
            if len(lists) == 1:
                return Found.from_one(lists[0])
            return compose(*lists)

        if case.pass_str:
            check("pass_str", pass_problems(found("pass"), codes))

        if case.fail_str:
            failed = found("fail")
            check(
                "fail_str",
                fail_problems(
                    failed, codes, case.line_numbers, case.violations, case.rule
                ),
            )
            fix_path = work / "fix.sql"
            fix_path.write_bytes(case.fail_str.encode("utf8"))
            fix = adapter.fix(fix_path, codes, dialect, case.configs, work)
            want = case.fix_str if case.fix_str else case.fail_str
            lists = outputs("fail")
            if templated_area is not None:
                lists.append(templated_area.violations[paths["fail"]])
            not_shown = fix_not_shown(failed, lists, case.configs)
            if fix.fixed is None:
                unknown.extend(f"fix: tool: {e}" for e in fix.errors)
            elif fix.critical:
                unknown.append(
                    f"fix: the tool logged CRITICAL '{fix.critical[0]}'; the "
                    "test can fail there"
                )
            elif not_shown:
                unknown.append(f"fix: {not_shown}")
            else:
                checks["fix"] = fix.fixed == want
                if not checks["fix"]:
                    reasons.append("fix mismatch")

            if case.fix_str:
                got = found("fixed")
                if case.violations_after_fix:
                    problems = fail_problems(
                        got,
                        codes,
                        case.line_numbers,
                        case.violations_after_fix,
                        case.rule,
                    )
                else:
                    problems = pass_problems(got, codes)
                check("after_fix", problems)

    # The test stops at the first check that fails. Thus a failed check gives
    # "fail" also if the result of another check is not known.
    if not all(checks.values()):
        status = FAIL
    elif unknown:
        status = ERROR
    else:
        status = PASS
    return CaseResult(
        id=case.id,
        suite=NAME,
        tool=adapter.name,
        status=status,
        checks=checks,
        reason="; ".join(reasons + unknown),
    )


def check_fields(adapter: Adapter, case: RuleCase) -> None:
    """Raise Unsupported if the case compares a violation field that the
    lint output of the tool does not have."""
    fields = getattr(adapter, "lint_fields", None)
    if fields is None:
        return
    for name in ("violations", "violations_after_fix"):
        expected = getattr(case, name) or []
        # prep_violations gives a code to a violation that has none.
        missing = {k for v in expected for k in v if k != "code"}
        missing -= fields
        if missing:
            raise Unsupported(
                f"output field {', '.join(sorted(missing))} (the case "
                f"compares '{name}'; the lint output has no such field)"
            )


def noqa_mask_active(lints: list[LintResult], paths: list[Path]) -> bool:
    """Return True if a noqa comment changes the lint output of a path.

    lints is the result of _lint_all. The lint with no "ignore" and the lint
    with disable_noqa are equal if no noqa comment has an effect.
    """
    if len(lints) != 3 or any(r.violations is None or r.errors for r in lints):
        return False
    _, unignored, no_noqa = lints
    return any(unignored.violations[p] != no_noqa.violations[p] for p in paths)


def _lint_all(
    adapter: Adapter,
    paths: list[Path],
    templated: list[Path],
    codes: list[str],
    dialect: str | None,
    case: RuleCase,
    work: Path,
) -> list[LintResult]:
    """Lint the files of a case. Return 1 result, or 3 if a filter can apply.

    "lint -f json" applies the core "ignore" config and the noqa comments.
    The test uses lists with no filter for some checks. Thus if the config
    has "ignore", lint again with no "ignore". If a SQL string has "noqa" or
    can be templated (templating can make a noqa comment), also lint with
    disable_noqa. See compose() and noqa_mask_active().
    """
    filtered = adapter.lint(paths, codes, dialect, case.configs, work)
    unignored_config = config_without_ignore(case.configs)
    noqa_can_apply = bool(templated) or any(
        "noqa" in p.read_text(encoding="utf8") for p in paths
    )
    if unignored_config is None and not noqa_can_apply:
        return [filtered]
    unignored = filtered
    if unignored_config is not None:
        unignored = adapter.lint(paths, codes, dialect, unignored_config, work)
    no_noqa = unignored
    if noqa_can_apply:
        no_noqa = adapter.lint(
            paths, codes, dialect, config_without_noqa(case.configs), work
        )
    return [filtered, unignored, no_noqa]
