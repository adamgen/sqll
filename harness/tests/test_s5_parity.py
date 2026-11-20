"""The parity check of S5 (rule parity: sqll passes 100% of the rule fixtures,
lint and fix; cases that need the Jinja templater move to the Jinja templater
stone): scripts/s5/parity.

Task T2 (goal of the task: each rule and autofix case of the pinned sqlfluff
has one class from the data, and the check fails closed) of S5. Design
record: docs/decisions/s5-rules.md, sections 3 and 4.

Each test of a failure makes one failure in good inputs and finds exit code 1
and the failure in its list. Thus a test fails if the check of its failure is
removed. Each test of an input that is missing or not valid finds exit code
2. The tests of the class rules give each rule of section 3 one case.

Most tests use a small repository in a temp folder: a superproject with the
submodule third_party/sqlfluff (2 rule files with 15 cases, and 7 autofix
cases in 2 dialects), a copy of scripts/check-submodule, a Jinja as raw
record, and known_failures/sqll.txt. The tests do not change the submodule
of this repository.
"""

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sqll_harness import known_failures
from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT
from sqll_harness.suites import autofix, rules

SCRIPT = REPO_ROOT / "scripts" / "s5" / "parity"
RECORD = REPO_ROOT / "results" / "S5" / "parity.json"
STATUS = REPO_ROOT / "status" / "S5.md"
DESIGN = REPO_ROOT / "docs" / "decisions" / "s5-rules.md"
REPORT = Path("out") / "report.json"
ORACLE = Path("out") / "oracle.jsonl"
AUTOFIX_ORACLE = Path("out") / "autofix-oracle.jsonl"
JINJA_RAW = Path("results") / "S3b" / "C14-jinja-raw.json"
KNOWN = Path("known_failures") / "sqll.txt"
RECORDED = Path("recorded.json")
SUB = Path("third_party") / "sqlfluff"
RULE_DIR = rules.FIXTURE_DIR
AUTOFIX_DIR = autofix.FIXTURE_DIR

PASS = "pass"
JINJA = "jinja: S11"
TEMPLATER = "templater of S6"
GAP = "gap"
NO_CLASS = "no class"

# The rule files of the small submodule. Each case is one class rule of
# section 3 of the design record.
AA01 = """\
rule: CP01

test_pass_jinja_as_raw:
  pass_str: SELECT 1

test_fail_jinja_as_raw:
  fail_str: SELECT a
  fix_str: SELECT b

test_tag_in_pass_str:
  pass_str: SELECT {{ x }}

test_tag_in_fail_str:
  fail_str: "{% if x %}SELECT a{% endif %}"

test_tag_in_fix_str:
  fail_str: SELECT a
  fix_str: "SELECT {# c #} a"

test_custom_start_string:
  pass_str: SELECT <<x>>
  configs:
    templater:
      jinja:
        variable_start_string: "<<"

test_templater_section:
  pass_str: SELECT 2
  configs:
    templater:
      jinja:
        context:
          x: 1

test_library_path:
  pass_str: SELECT 3
  configs:
    core:
      library_path: libs

test_explicit_jinja_with_tag:
  pass_str: SELECT {{ y }}
  configs:
    core:
      templater: jinja

test_placeholder:
  pass_str: SELECT :a
  configs:
    core:
      templater: placeholder
    templater:
      placeholder:
        param_style: colon

test_python:
  pass_str: SELECT {a}
  configs:
    core:
      templater: python

test_raw_with_tag:
  pass_str: SELECT {{ x }}
  configs:
    core:
      templater: raw

test_fix_str_with_no_fail_str:
  pass_str: SELECT 1
  fix_str: SELECT {{ z }}
"""
# The file-level configs apply to each case with no configs of its own.
AA02 = """\
rule: CP02
configs:
  core:
    templater: placeholder

test_file_configs:
  pass_str: SELECT :b

test_own_configs:
  pass_str: SELECT 1
  configs:
    core:
      dialect: ansi
"""

FIXTURES = {
    RULE_DIR / "AA01.yml": AA01,
    RULE_DIR / "AA02.yml": AA02,
    AUTOFIX_DIR / "README.md": "Not a dialect.\n",
    AUTOFIX_DIR / "ansi" / "001_plain" / "before.sql": "SELECT 1\n",
    AUTOFIX_DIR / "ansi" / "002_tag" / "before.sql": "SELECT {{ x }}\n",
    AUTOFIX_DIR / "ansi" / "003_setting" / "before.sql": "SELECT 2\n",
    AUTOFIX_DIR / "ansi" / "003_setting" / ".sqlfluff": (
        "[sqlfluff:templater:jinja]\nload_macros_from_path = macros\n"
    ),
    AUTOFIX_DIR / "ansi" / "004_library_path" / "before.sql": "SELECT 3\n",
    AUTOFIX_DIR / "ansi" / "004_library_path" / ".sqlfluff": (
        "[sqlfluff]\nlibrary_path = libs\n"
    ),
    AUTOFIX_DIR / "bigquery" / "001_placeholder" / "before.sql": "SELECT :a\n",
    AUTOFIX_DIR / "bigquery" / "001_placeholder" / ".sqlfluff": (
        "[sqlfluff]\ntemplater = placeholder\n"
    ),
    AUTOFIX_DIR / "bigquery" / "002_raw" / "before.sql": "SELECT {{ x }}\n",
    AUTOFIX_DIR / "bigquery" / "002_raw" / ".sqlfluff": "[sqlfluff]\ntemplater = raw\n",
    AUTOFIX_DIR / "bigquery" / "003_other_config" / "before.sql": "SELECT 4\n",
    AUTOFIX_DIR / "bigquery" / "003_other_config" / ".sqlfluff": (
        "[sqlfluff:rules:capitalisation.keywords]\ncapitalisation_policy = lower\n"
    ),
}
# The texts of the Jinja as raw record of the small repository.
EQUAL_TEXTS = ["SELECT 1", "SELECT a", "SELECT b", "SELECT 1\n", "SELECT 4\n"]

# {case id: (class, fixture class, sqll status)} of the good inputs.
EXPECTED = {
    "rules/AA01/test_pass_jinja_as_raw": (PASS, "other", "pass"),
    "rules/AA01/test_fail_jinja_as_raw": (GAP, "other", "fail"),
    "rules/AA01/test_tag_in_pass_str": (JINJA, "jinja", "fail"),
    "rules/AA01/test_tag_in_fail_str": (JINJA, "jinja", "fail"),
    "rules/AA01/test_tag_in_fix_str": (JINJA, "jinja", "fail"),
    "rules/AA01/test_custom_start_string": (JINJA, "jinja", "fail"),
    "rules/AA01/test_templater_section": (JINJA, "jinja", "fail"),
    "rules/AA01/test_library_path": (JINJA, "jinja", "fail"),
    "rules/AA01/test_explicit_jinja_with_tag": (JINJA, "jinja", "fail"),
    "rules/AA01/test_placeholder": (TEMPLATER, "templater", "fail"),
    "rules/AA01/test_python": (TEMPLATER, "templater", "error"),
    "rules/AA01/test_raw_with_tag": (PASS, "other", "pass"),
    "rules/AA01/test_fix_str_with_no_fail_str": (GAP, "other", "error"),
    "rules/AA02/test_file_configs": (TEMPLATER, "templater", "fail"),
    "rules/AA02/test_own_configs": (PASS, "other", "pass"),
    "autofix/ansi/001_plain": (PASS, "other", "pass"),
    "autofix/ansi/002_tag": (JINJA, "jinja", "fail"),
    "autofix/ansi/003_setting": (JINJA, "jinja", "fail"),
    "autofix/ansi/004_library_path": (JINJA, "jinja", "fail"),
    "autofix/bigquery/001_placeholder": (TEMPLATER, "templater", "fail"),
    "autofix/bigquery/002_raw": (GAP, "other", "fail"),
    "autofix/bigquery/003_other_config": (GAP, "other", "fail"),
}
WHY = {
    "rules/AA01/test_pass_jinja_as_raw": (
        "jinja, and each text is in the Jinja as raw record"
    ),
    "rules/AA01/test_tag_in_pass_str": "the Jinja tag '{{' in pass_str",
    "rules/AA01/test_tag_in_fail_str": "the Jinja tag '{%' in fail_str",
    "rules/AA01/test_tag_in_fix_str": "the Jinja tag '{#' in fix_str",
    "rules/AA01/test_custom_start_string": "the Jinja tag '<<' in pass_str",
    "rules/AA01/test_templater_section": (
        "the Jinja templater setting a templater section"
    ),
    "rules/AA01/test_library_path": "the Jinja templater setting core.library_path",
    "rules/AA01/test_explicit_jinja_with_tag": "the Jinja tag '{{' in pass_str",
    "rules/AA01/test_placeholder": "core.templater placeholder",
    "rules/AA01/test_python": "core.templater python",
    "rules/AA01/test_raw_with_tag": "core.templater raw",
    "rules/AA02/test_file_configs": "core.templater placeholder",
    "autofix/ansi/002_tag": "the Jinja tag '{{' in before.sql",
    "autofix/ansi/003_setting": "the Jinja templater setting a templater section",
    "autofix/ansi/004_library_path": "the Jinja templater setting core.library_path",
    "autofix/bigquery/001_placeholder": "core.templater placeholder",
    "autofix/bigquery/002_raw": "core.templater raw",
}
GOOD_RECORDED = {
    "rules": {"cases": 15, "jinja": 7, "templater": 3},
    "autofix": {"cases": 7, "jinja": 3, "templater": 1},
}

GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "protocol.file.allow=always",
            "-c",
            "init.defaultBranch=main",
            *args,
        ],
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def case(case_id: str, status: str, **changes) -> dict:
    """A case record of the report (CaseResult of the harness)."""
    record = {
        "id": case_id,
        "suite": case_id.split("/", 1)[0],
        "tool": "sqll",
        "status": status,
        "checks": {},
        "reason": "",
        "duration_ms": 1,
        "tags": [],
    }
    record.update(changes)
    return record


def oracle_text(statuses: dict[str, str]) -> str:
    return "".join(
        json.dumps({"id": i, "status": s, "reason": ""}) + "\n"
        for i, s in statuses.items()
    )


def known_text(ids) -> str:
    return "".join(f"{i}  # a reason\n" for i in sorted(ids))


class Repo:
    """A small repository in a temp folder, with good inputs."""

    def __init__(self, base: Path, fixtures: dict[Path, str] | None = None):
        source = base / "sqlfluff-source"
        for relative, text in (fixtures or FIXTURES).items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf8")
        git(source, "init", "-q")
        git(source, "add", "-f", ".")
        git(source, "commit", "-q", "-m", "fixtures")

        self.root = base / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q")
        git(self.root, "submodule", "add", "-q", str(source), SUB.as_posix())
        (self.root / "scripts").mkdir()
        shutil.copy2(REPO_ROOT / "scripts" / "check-submodule", self.root / "scripts")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "repository")
        self.pinned = git(self.root, "rev-parse", f"HEAD:{SUB.as_posix()}")
        self.statuses = {i: status for i, (_, _, status) in EXPECTED.items()}
        self.oracle = {
            suite: {i: "pass" for i in EXPECTED if i.startswith(f"{suite}/")}
            for suite in ("rules", "autofix")
        }
        self.extra_cases: list[dict] = []
        self.ref = self.pinned
        self.record = {
            "kind": "sqll-s3b-c14-jinja-raw",
            "format": 1,
            "sqlfluff": {"version": "4.4.0", "commit": self.pinned},
            "counts": {},
            "notes": [],
            "equal": sorted(sha256(t) for t in EQUAL_TEXTS),
        }
        self.known = {i for i, s in self.statuses.items() if s != "pass"}
        self.recorded = json.loads(json.dumps(GOOD_RECORDED))

    def write(self, relative: Path, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf8")

    def report(self) -> dict:
        """The report: the sqll cases, and cases of another tool and suite
        that the check must not use."""
        cases = [case(i, s) for i, s in self.statuses.items()]
        cases.append(case("rules/AA01/test_python", "fail", tool="sqlfluff"))
        cases.append(case("dialects/ansi/a", "fail"))
        return {
            "sqlfluff_ref": self.ref,
            "scope": {"suites": ["rules", "autofix"], "tools": ["sqll"]},
            "tools": {"sqll": {"version": "test"}},
            "summary": {},
            "known_failures": {},
            "cases": cases + self.extra_cases,
        }

    def run(self, *args: str, write: bool = True, recorded: bool = True):
        if write:
            self.write(REPORT, json.dumps(self.report()))
            self.write(ORACLE, oracle_text(self.oracle["rules"]))
            self.write(AUTOFIX_ORACLE, oracle_text(self.oracle["autofix"]))
            self.write(JINJA_RAW, json.dumps(self.record))
            self.write(KNOWN, known_text(self.known))
            self.write(RECORDED, json.dumps(self.recorded))
        extra = ["--recorded", str(self.root / RECORDED)] if recorded else []
        return run_check("--root", str(self.root), *extra, *args)


def run_check(*args: str) -> tuple[int, dict]:
    done = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        result = json.loads(done.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"no JSON output: {done.stdout!r} {done.stderr!r}")
    assert result["exit_code"] == done.returncode
    return done.returncode, result


def parity_module():
    """Load scripts/s5/parity (a file with no .py suffix) as a module."""
    loader = importlib.machinery.SourceFileLoader("s5_parity", str(SCRIPT))
    spec = importlib.util.spec_from_loader("s5_parity", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path) -> Repo:
    return Repo(tmp_path)


def other_failures(result: dict, *names: str) -> dict:
    """The failures of the enforced items, other than names."""
    enforced = {
        name
        for item in result["items"]
        if item["enforced"]
        for name in item["failures"]
    }
    return {
        k: v
        for k, v in result["failures"].items()
        if v and k in enforced and k not in names
    }


def assert_failure(result: dict, rc: int, item: int, name: str, expected) -> None:
    """Exit code 1, the failure in its list, and its item is not ok."""
    assert rc == 1, result["failures"]
    assert result["status"] == "fail"
    assert result["failures"][name] == expected
    items = {i["item"]: i for i in result["items"]}
    assert items[item]["ok"] is False
    assert items[item]["failures"][name] == len(expected)


def assert_error(rc: int, result: dict, prefix: str) -> None:
    assert rc == 2
    assert result["status"] == "error"
    assert result["counts"] is None and result["cases"] is None
    assert any(e.startswith(prefix) for e in result["errors"]), result["errors"]


# Good inputs.


def test_good_inputs_pass(repo):
    rc, result = repo.run()
    assert rc == 0, result["failures"]
    assert result["status"] == "pass"
    assert result["errors"] == []
    assert result["exit_mode"] is False
    assert result["pinned_commit"] == repo.pinned
    assert result["report_sqlfluff_ref"] == repo.pinned
    assert result["jinja_raw_commit"] == repo.pinned
    assert result["commit"] == git(repo.root, "rev-parse", "HEAD")
    assert result["recorded"] == GOOD_RECORDED
    assert result["counts"] == {
        "rules": {
            "cases": 15,
            "classes": {PASS: 3, JINJA: 7, TEMPLATER: 3, GAP: 2, NO_CLASS: 0},
            "fixture_classes": {"jinja": 7, "templater": 3, "other": 5, "none": 0},
            "sqll_passed": 3,
            "passed_in_oracle": 3,
            "known_failures_lines": 12,
        },
        "autofix": {
            "cases": 7,
            "classes": {PASS: 1, JINJA: 3, TEMPLATER: 1, GAP: 2, NO_CLASS: 0},
            "fixture_classes": {"jinja": 3, "templater": 1, "other": 3, "none": 0},
            "sqll_passed": 1,
            "passed_in_oracle": 1,
            "known_failures_lines": 6,
        },
    }
    zero = {PASS: 0, JINJA: 0, TEMPLATER: 0, GAP: 0, NO_CLASS: 0}
    assert result["by_group"] == {
        "rules": {
            "AA01": {**zero, "cases": 13, PASS: 2, JINJA: 7, TEMPLATER: 2, GAP: 2},
            "AA02": {**zero, "cases": 2, PASS: 1, TEMPLATER: 1},
        },
        "autofix": {
            "ansi": {**zero, "cases": 4, PASS: 1, JINJA: 3},
            "bigquery": {**zero, "cases": 3, TEMPLATER: 1, GAP: 2},
        },
    }
    assert [i["item"] for i in result["items"]] == [1, 2, 3, 4, 5, 6]
    assert all(i["ok"] for i in result["items"] if i["enforced"])
    assert [i["enforced"] for i in result["items"]] == [True] * 5 + [False]
    assert result["inputs"] == {
        "report": "out/report.json",
        "oracle": "out/oracle.jsonl",
        "autofix_oracle": "out/autofix-oracle.jsonl",
        "jinja_raw": "results/S3b/C14-jinja-raw.json",
        "known_failures": "known_failures/sqll.txt",
        "fixtures": [
            "third_party/sqlfluff/test/fixtures/rules/std_rule_cases",
            "third_party/sqlfluff/test/fixtures/linter/autofix",
        ],
    }


def test_each_case_has_the_class_of_its_rule(repo):
    """Each class rule of section 3 of the design record, with one case."""
    rc, result = repo.run()
    assert rc == 0
    assert set(result["cases"]) == set(EXPECTED)
    for case_id, (cls, fixture, status) in EXPECTED.items():
        entry = result["cases"][case_id]
        assert entry["class"] == cls, case_id
        assert entry["fixture_class"] == fixture, case_id
        assert entry["sqll"] == status, case_id
        assert entry["oracle"] == "pass", case_id
        assert entry["known_failure"] is (status != "pass"), case_id
    for case_id, why in WHY.items():
        assert result["cases"][case_id]["why"] == why, case_id


def test_out_file_is_the_output(repo, tmp_path):
    out = tmp_path / "parity" / "result.json"
    rc, result = repo.run("--out", str(out))
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf8")) == result


def test_each_failure_is_in_one_item(repo):
    _, result = repo.run()
    names = [n for i in result["items"] for n in i["failures"]]
    assert sorted(names) == sorted(result["failures"])
    assert len(names) == len(set(names))


def test_a_templater_case_that_sqll_passes_is_a_pass(repo):
    """The count check uses the fixture classes: a case of the templater
    class that sqll passes becomes a pass, and the counts stay correct."""
    repo.statuses["rules/AA01/test_placeholder"] = "pass"
    repo.known.discard("rules/AA01/test_placeholder")
    rc, result = repo.run()
    assert rc == 0, result["failures"]
    assert result["cases"]["rules/AA01/test_placeholder"]["class"] == PASS
    assert result["counts"]["rules"]["classes"][TEMPLATER] == 2
    assert result["counts"]["rules"]["fixture_classes"]["templater"] == 3


# Item 1: each case has one class.


def no_class(result: dict) -> list[str]:
    return [f.split(": ", 1)[0] for f in result["failures"]["no_class"]]


def test_jinja_text_that_is_not_in_the_record_has_no_class(repo):
    repo.record["equal"].remove(sha256("SELECT b"))
    rc, result = repo.run()
    assert_failure(
        result,
        rc,
        1,
        "no_class",
        [
            "rules/AA01/test_fail_jinja_as_raw: jinja with no Jinja tag, but"
            " fix_str is not a text of the Jinja as raw record"
        ],
    )
    entry = result["cases"]["rules/AA01/test_fail_jinja_as_raw"]
    assert (entry["class"], entry["fixture_class"]) == (NO_CLASS, None)
    assert result["counts"]["rules"]["classes"][NO_CLASS] == 1
    assert other_failures(result, "no_class") == {}


def test_autofix_text_that_is_not_in_the_record_has_no_class(repo):
    repo.record["equal"].remove(sha256("SELECT 4\n"))
    rc, result = repo.run()
    assert rc == 1
    assert no_class(result) == ["autofix/bigquery/003_other_config"]
    assert other_failures(result, "no_class") == {}


def test_a_note_of_the_record_gives_no_class(repo):
    repo.record["notes"] = [
        "rules/AA01/test_tag_in_fail_str/fail: equal, but it has a Jinja delimiter",
        "autofix/ansi/001_plain: no Jinja delimiter, but TMP",
    ]
    rc, result = repo.run()
    assert rc == 1
    assert no_class(result) == [
        "rules/AA01/test_tag_in_fail_str",
        "autofix/ansi/001_plain",
    ]
    # The case of the note is no longer a pass, so its known failure is
    # still correct: only item 1 fails.
    assert other_failures(result, "no_class") == {"count": result["failures"]["count"]}


def test_an_unknown_templater_gives_no_class(tmp_path):
    fixtures = dict(FIXTURES)
    fixtures[RULE_DIR / "AA03.yml"] = (
        "rule: CP01\n\ntest_dbt:\n  pass_str: SELECT 1\n"
        "  configs:\n    core:\n      templater: dbt\n"
    )
    repo = Repo(tmp_path, fixtures)
    repo.statuses["rules/AA03/test_dbt"] = "fail"
    repo.oracle["rules"]["rules/AA03/test_dbt"] = "pass"
    repo.known.add("rules/AA03/test_dbt")
    repo.recorded["rules"]["cases"] = 16
    rc, result = repo.run()
    assert_failure(
        result,
        rc,
        1,
        "no_class",
        ["rules/AA03/test_dbt: core.templater 'dbt' is not known"],
    )
    assert other_failures(result, "no_class") == {}


def test_a_skip_case_has_no_class(tmp_path):
    fixtures = dict(FIXTURES)
    fixtures[RULE_DIR / "AA03.yml"] = (
        "rule: CP01\n\ntest_skip:\n  pass_str: SELECT 1\n  skip: not now\n"
    )
    repo = Repo(tmp_path, fixtures)
    repo.statuses["rules/AA03/test_skip"] = "skip"
    repo.oracle["rules"]["rules/AA03/test_skip"] = "skip"
    repo.known.add("rules/AA03/test_skip")
    repo.recorded["rules"]["cases"] = 16
    rc, result = repo.run()
    assert_failure(
        result, rc, 1, "no_class", ["rules/AA03/test_skip: the case has skip: not now"]
    )
    assert other_failures(result, "no_class") == {}


def test_an_autofix_case_with_no_before_sql_has_no_class(tmp_path):
    fixtures = dict(FIXTURES)
    fixtures[AUTOFIX_DIR / "ansi" / "005_empty" / "after.sql"] = "SELECT 5\n"
    repo = Repo(tmp_path, fixtures)
    repo.statuses["autofix/ansi/005_empty"] = "fail"
    repo.oracle["autofix"]["autofix/ansi/005_empty"] = "fail"
    repo.known.add("autofix/ansi/005_empty")
    repo.recorded["autofix"]["cases"] = 8
    rc, result = repo.run()
    assert rc == 1
    assert no_class(result) == ["autofix/ansi/005_empty"]
    assert "cannot read the case" in result["failures"]["no_class"][0]
    assert other_failures(result, "no_class") == {}


def test_a_case_with_no_sqll_result_has_no_class(repo):
    del repo.statuses["rules/AA01/test_fail_jinja_as_raw"]
    repo.known.discard("rules/AA01/test_fail_jinja_as_raw")
    rc, result = repo.run()
    assert_failure(
        result,
        rc,
        1,
        "no_class",
        [
            "rules/AA01/test_fail_jinja_as_raw: the report has no sqll result of"
            " the case"
        ],
    )
    assert other_failures(result, "no_class") == {}


def test_a_case_with_no_oracle_line_has_no_class(repo):
    del repo.oracle["autofix"]["autofix/bigquery/002_raw"]
    rc, result = repo.run()
    assert rc == 1
    assert result["failures"]["no_class"] == [
        "autofix/bigquery/002_raw: the oracle output has no line of the case"
    ]
    assert other_failures(result, "no_class") == {}


def test_a_skip_status_gives_no_class(repo):
    repo.statuses["rules/AA02/test_file_configs"] = "skip"
    rc, result = repo.run()
    assert rc == 1
    assert result["failures"]["no_class"] == [
        "rules/AA02/test_file_configs: sqll skip, oracle pass"
    ]
    assert other_failures(result, "no_class") == {}


def test_a_jinja_case_with_no_sqll_result_is_still_jinja(repo):
    """The Jinja class comes only from the fixtures."""
    del repo.statuses["rules/AA01/test_tag_in_pass_str"]
    repo.known.discard("rules/AA01/test_tag_in_pass_str")
    rc, result = repo.run()
    assert rc == 0, result["failures"]
    assert result["cases"]["rules/AA01/test_tag_in_pass_str"]["class"] == JINJA


def test_report_extra(repo):
    repo.extra_cases.append(case("rules/AA01/test_zzz", "fail"))
    repo.known.add("rules/AA01/test_zzz")
    rc, result = repo.run()
    assert_failure(result, rc, 1, "report_extra", ["rules/AA01/test_zzz"])
    # A known failure of a case that the fixtures do not have is stale.
    assert other_failures(result, "report_extra") == {
        "known_failures_stale": ["rules/AA01/test_zzz: no such case"]
    }


def test_oracle_extra(repo):
    repo.oracle["autofix"]["autofix/ansi/999_zzz"] = "pass"
    rc, result = repo.run()
    assert_failure(result, rc, 1, "oracle_extra", ["autofix/ansi/999_zzz"])
    assert other_failures(result, "oracle_extra") == {}


# Item 2: each case that sqll passes passes in the oracle.


@pytest.mark.parametrize("verdict", ["fail", "skip"])
def test_oracle_mismatch(repo, verdict):
    repo.oracle["rules"]["rules/AA01/test_pass_jinja_as_raw"] = verdict
    rc, result = repo.run()
    assert_failure(
        result,
        rc,
        2,
        "oracle_mismatch",
        [
            "rules/AA01/test_pass_jinja_as_raw: sqll passes the case, but the"
            f" oracle gives {verdict}"
        ],
    )
    entry = result["cases"]["rules/AA01/test_pass_jinja_as_raw"]
    if verdict == "fail":
        # A sqll pass that the oracle does not pass is a gap.
        assert entry["class"] == GAP
        assert other_failures(result, "oracle_mismatch") == {}
    else:
        assert entry["class"] == NO_CLASS
        assert other_failures(result, "oracle_mismatch", "no_class") == {}


def test_oracle_mismatch_of_an_autofix_case(repo):
    repo.oracle["autofix"]["autofix/ansi/001_plain"] = "fail"
    rc, result = repo.run()
    assert_failure(
        result,
        rc,
        2,
        "oracle_mismatch",
        ["autofix/ansi/001_plain: sqll passes the case, but the oracle gives fail"],
    )
    assert result["counts"]["autofix"]["passed_in_oracle"] == 0


def test_oracle_mismatch_of_a_jinja_case(repo):
    """Item 2 applies to each class, also to the Jinja class."""
    repo.statuses["autofix/ansi/002_tag"] = "pass"
    repo.known.discard("autofix/ansi/002_tag")
    repo.oracle["autofix"]["autofix/ansi/002_tag"] = "fail"
    rc, result = repo.run()
    assert_failure(
        result,
        rc,
        2,
        "oracle_mismatch",
        ["autofix/ansi/002_tag: sqll passes the case, but the oracle gives fail"],
    )
    assert result["cases"]["autofix/ansi/002_tag"]["class"] == JINJA
    assert other_failures(result, "oracle_mismatch") == {}


# Item 3: the count of each recorded class is the recorded count.


@pytest.mark.parametrize(
    "suite,name,value",
    [
        ("rules", "cases", 16),
        ("rules", "jinja", 6),
        ("rules", "templater", 4),
        ("autofix", "cases", 6),
        ("autofix", "jinja", 4),
        ("autofix", "templater", 0),
    ],
)
def test_a_changed_class_count(repo, suite, name, value):
    have = GOOD_RECORDED[suite][name]
    repo.recorded[suite][name] = value
    rc, result = repo.run()
    assert_failure(
        result,
        rc,
        3,
        "count",
        [f"{suite} {name}: {have}, the recorded count is {value}"],
    )
    assert other_failures(result, "count") == {}


def test_a_new_jinja_case_changes_the_count(tmp_path):
    """A new fixture case of the Jinja class is a changed class count."""
    fixtures = dict(FIXTURES)
    fixtures[RULE_DIR / "AA03.yml"] = "rule: CP01\n\ntest_tag:\n  pass_str: '{{ a }}'\n"
    repo = Repo(tmp_path, fixtures)
    repo.statuses["rules/AA03/test_tag"] = "fail"
    repo.oracle["rules"]["rules/AA03/test_tag"] = "pass"
    repo.known.add("rules/AA03/test_tag")
    rc, result = repo.run()
    assert_failure(
        result,
        rc,
        3,
        "count",
        [
            "rules cases: 16, the recorded count is 15",
            "rules jinja: 8, the recorded count is 7",
        ],
    )


def test_the_default_counts_are_those_of_the_design_record(repo):
    """With no --recorded, the check uses the counts of the design record;
    the small repository does not have them."""
    rc, result = repo.run(recorded=False)
    assert rc == 1
    assert result["recorded"] == {
        "rules": {"cases": 2527, "jinja": 169, "templater": 13},
        "autofix": {"cases": 61, "jinja": 21, "templater": 0},
    }
    assert result["failures"]["count"] == [
        "rules cases: 15, the recorded count is 2527",
        "rules jinja: 7, the recorded count is 169",
        "rules templater: 3, the recorded count is 13",
        "autofix cases: 7, the recorded count is 61",
        "autofix jinja: 3, the recorded count is 21",
        "autofix templater: 1, the recorded count is 0",
    ]


def test_recorded_counts_agree_with_the_design_record():
    """RECORDED of the script is the table of section 3 of the design
    record."""
    recorded = parity_module().RECORDED
    text = " ".join(DESIGN.read_text("utf8").split())
    section = text.split("## 3. The case classes", 1)[1].split("## 4.", 1)[0]
    rows = dict(
        re.findall(
            r"\| (pass|`jinja: S11`|templater of S6|gap) \| (\d+ \| \d+)", section
        )
    )
    jinja = [int(n) for n in rows["`jinja: S11`"].split(" | ")]
    templater = [int(n) for n in rows["templater of S6"].split(" | ")]
    total = [sum(int(rows[k].split(" | ")[n]) for k in rows) for n in range(2)]
    assert recorded["rules"] == {
        "cases": total[0],
        "jinja": jinja[0],
        "templater": templater[0],
    }
    assert recorded["autofix"] == {
        "cases": total[1],
        "jinja": jinja[1],
        "templater": templater[1],
    }
    assert recorded == {
        "rules": {"cases": 2527, "jinja": 169, "templater": 13},
        "autofix": {"cases": 61, "jinja": 21, "templater": 0},
    }


# Item 4: the known failures.


def test_known_failures_missing(repo):
    repo.known.discard("rules/AA01/test_python")
    rc, result = repo.run()
    assert_failure(result, rc, 4, "known_failures_missing", ["rules/AA01/test_python"])
    assert other_failures(result, "known_failures_missing") == {}


def test_known_failures_stale_pass(repo):
    repo.known.add("autofix/ansi/001_plain")
    rc, result = repo.run()
    assert_failure(
        result,
        rc,
        4,
        "known_failures_stale",
        ["autofix/ansi/001_plain: sqll passes the case"],
    )
    assert other_failures(result, "known_failures_stale") == {}


def test_known_failures_stale_no_case(repo):
    repo.known.add("rules/AA09/test_gone")
    rc, result = repo.run()
    assert_failure(
        result,
        rc,
        4,
        "known_failures_stale",
        ["rules/AA09/test_gone: no such case"],
    )
    assert other_failures(result, "known_failures_stale") == {}


def test_known_failures_of_other_suites_are_not_used(repo):
    repo.known.add("dialects/ansi/zzz")
    repo.known.add("templater/zzz")
    rc, result = repo.run()
    assert rc == 0, result["failures"]


# Item 5: the pinned commit.


def test_report_sqlfluff_ref(repo):
    repo.ref = "0" * 40
    rc, result = repo.run()
    assert_failure(
        result,
        rc,
        5,
        "sqlfluff_ref",
        [
            f"the report sqlfluff_ref {'0' * 40} is not the pinned commit"
            f" {repo.pinned} (HEAD:third_party/sqlfluff)"
        ],
    )
    assert other_failures(result, "sqlfluff_ref") == {}


def test_jinja_raw_commit(repo):
    repo.record["sqlfluff"]["commit"] = "1" * 40
    rc, result = repo.run()
    assert_failure(
        result,
        rc,
        5,
        "jinja_raw_commit",
        [
            f"the sqlfluff commit {'1' * 40} of the Jinja as raw record is not"
            f" the pinned commit {repo.pinned}"
        ],
    )
    assert other_failures(result, "jinja_raw_commit") == {}


def test_submodule_change(repo):
    path = repo.root / SUB / RULE_DIR / "AA01.yml"
    path.write_text(path.read_text("utf8") + "\n", encoding="utf8")
    rc, result = repo.run()
    assert rc == 1
    assert len(result["failures"]["submodule"]) == 1
    assert result["failures"]["submodule"][0].startswith(
        "scripts/check-submodule exit 1"
    )
    assert other_failures(result, "submodule") == {}


def test_submodule_checkout_is_not_the_pinned_commit(repo):
    sub = repo.root / SUB
    git(sub, "commit", "-q", "--allow-empty", "-m", "other")
    head = git(sub, "rev-parse", "HEAD")
    rc, result = repo.run()
    assert rc == 1
    assert any(head in f for f in result["failures"]["submodule"]), result["failures"]


# Item 6: no gap, only with --exit.


def gap_ids() -> list[str]:
    return [i for i, (cls, _, _) in EXPECTED.items() if cls in (GAP, TEMPLATER)]


def test_gaps_fail_only_with_exit(repo):
    rc, result = repo.run()
    assert rc == 0
    item = {i["item"]: i for i in result["items"]}[6]
    assert item == {
        "item": 6,
        "rule": item["rule"],
        "enforced": False,
        "ok": False,
        "failures": {"gap": 8},
    }
    assert sorted(result["failures"]["gap"]) == sorted(gap_ids())

    rc, result = repo.run("--exit")
    assert result["exit_mode"] is True
    assert_failure(result, rc, 6, "gap", result["failures"]["gap"])
    assert sorted(result["failures"]["gap"]) == sorted(gap_ids())
    assert other_failures(result, "gap") == {}


def test_one_gap_fails_with_exit(repo):
    for case_id in gap_ids():
        repo.statuses[case_id] = "pass"
        repo.known.discard(case_id)
    repo.statuses["autofix/bigquery/002_raw"] = "fail"
    repo.known.add("autofix/bigquery/002_raw")
    rc, result = repo.run("--exit")
    assert_failure(result, rc, 6, "gap", ["autofix/bigquery/002_raw"])
    assert other_failures(result, "gap") == {}


def test_a_templater_case_is_a_gap_with_exit(repo):
    for case_id in gap_ids():
        repo.statuses[case_id] = "pass"
        repo.known.discard(case_id)
    repo.statuses["rules/AA02/test_file_configs"] = "fail"
    repo.known.add("rules/AA02/test_file_configs")
    rc, result = repo.run("--exit")
    assert_failure(result, rc, 6, "gap", ["rules/AA02/test_file_configs"])


def test_exit_passes_with_only_jinja_failures(repo):
    """The exit of this stone: each case that is not in the Jinja class is a
    pass. The Jinja cases stay in the known failures."""
    for case_id in gap_ids():
        repo.statuses[case_id] = "pass"
        repo.known.discard(case_id)
    rc, result = repo.run("--exit")
    assert rc == 0, result["failures"]
    assert result["counts"]["rules"]["classes"] == {
        PASS: 8,
        JINJA: 7,
        TEMPLATER: 0,
        GAP: 0,
        NO_CLASS: 0,
    }
    assert all(i["ok"] for i in result["items"])


# Exit code 2: an input is missing or not valid.


def test_missing_report(repo):
    rc, result = repo.run("--report", str(repo.root / "none.json"))
    assert_error(rc, result, "report: ")


@pytest.mark.parametrize(
    "text,message",
    [
        ("{", "not valid JSON"),
        ("[]", "not a JSON object"),
        ('{"cases": []}', "no sqlfluff_ref text"),
        ('{"sqlfluff_ref": "x"}', "no cases list"),
        ('{"sqlfluff_ref": "x", "cases": [1]}', "not a JSON object"),
        ('{"sqlfluff_ref": "x", "cases": [{"id": "a"}]}', "no suite text"),
    ],
)
def test_bad_report(repo, text, message):
    repo.run()
    repo.write(REPORT, text)
    rc, result = repo.run(write=False)
    assert_error(rc, result, "report: ")
    assert any(message in e for e in result["errors"]), result["errors"]


def test_report_with_an_unknown_status(repo):
    repo.statuses["rules/AA01/test_python"] = "unsupported"
    rc, result = repo.run()
    assert_error(rc, result, "report: ")
    assert any("is not known" in e for e in result["errors"])


def test_report_with_a_duplicate_case(repo):
    repo.extra_cases.append(case("rules/AA01/test_python", "fail"))
    rc, result = repo.run()
    assert_error(rc, result, "report: ")
    assert any("duplicate id" in e for e in result["errors"])


def test_report_case_in_the_wrong_suite(repo):
    repo.extra_cases.append(case("autofix/ansi/zzz", "fail", suite="rules"))
    rc, result = repo.run()
    assert_error(rc, result, "report: ")
    assert any("is not in the suite rules" in e for e in result["errors"])


@pytest.mark.parametrize("suite", ["rules", "autofix"])
def test_report_with_no_sqll_case_of_a_suite(repo, suite):
    """No data is not a pass."""
    for case_id in list(repo.statuses):
        if case_id.startswith(f"{suite}/"):
            del repo.statuses[case_id]
    rc, result = repo.run()
    assert_error(rc, result, "report: ")
    assert any(f"no {suite} case of sqll (no data)" in e for e in result["errors"])


@pytest.mark.parametrize(
    "option,path,prefix",
    [
        ("--oracle", ORACLE, "oracle: "),
        ("--autofix-oracle", AUTOFIX_ORACLE, "autofix oracle: "),
    ],
)
@pytest.mark.parametrize(
    "text,message",
    [
        (None, "no such file"),
        ("", "no case (no data)"),
        ("{\n", "not valid JSON"),
        ('{"status": "pass"}\n', "no id text"),
        ("BAD_STATUS", "is not known"),
        ("DUPLICATE", "duplicate id"),
        ("WRONG_SUITE", "is not a"),
    ],
)
def test_bad_oracle(repo, option, path, prefix, text, message):
    repo.run()
    suite = "rules" if option == "--oracle" else "autofix"
    other = "autofix" if suite == "rules" else "rules"
    good_id = next(iter(repo.oracle[suite]))
    lines = {
        "BAD_STATUS": json.dumps({"id": good_id, "status": "error"}) + "\n",
        "DUPLICATE": oracle_text({good_id: "pass"}) * 2,
        "WRONG_SUITE": json.dumps({"id": f"{other}/x/y", "status": "pass"}) + "\n",
    }
    target = repo.root / path
    if text is None:
        target.unlink()
    else:
        target.write_text(lines.get(text, text), encoding="utf8")
    rc, result = repo.run(write=False)
    assert_error(rc, result, prefix)
    assert any(message in e for e in result["errors"]), result["errors"]


@pytest.mark.parametrize(
    "change,message",
    [
        (lambda r: None, "no such file"),
        (lambda r: {**r, "kind": "other"}, "kind 'other'"),
        (lambda r: {**r, "format": 2}, "format 2"),
        (lambda r: {**r, "sqlfluff": {}}, "no sqlfluff commit"),
        (lambda r: {**r, "equal": []}, "no equal text (no data)"),
        (lambda r: {**r, "equal": ["abc"]}, "not a list of sha256 texts"),
        (lambda r: {**r, "notes": "x"}, "notes is not a list of texts"),
        (lambda r: [], "not a JSON object"),
    ],
)
def test_bad_jinja_raw_record(repo, change, message):
    repo.run()
    new = change(repo.record)
    target = repo.root / JINJA_RAW
    if new is None:
        target.unlink()
    else:
        target.write_text(json.dumps(new), encoding="utf8")
    rc, result = repo.run(write=False)
    assert_error(rc, result, "jinja raw record: ")
    assert any(message in e for e in result["errors"]), result["errors"]


@pytest.mark.parametrize(
    "text,message",
    [
        (None, "no such file"),
        ("rules/b\nrules/a\n", "ids are not sorted"),
        ("rules/a\nrules/a\n", "duplicate id"),
    ],
)
def test_bad_known_failures(repo, text, message):
    repo.run()
    target = repo.root / KNOWN
    if text is None:
        target.unlink()
    else:
        target.write_text(text, encoding="utf8")
    rc, result = repo.run(write=False)
    assert_error(rc, result, "known failures: ")
    assert any(message in e for e in result["errors"]), result["errors"]


@pytest.mark.parametrize("folder", [RULE_DIR, AUTOFIX_DIR])
def test_no_fixture_folder(tmp_path, folder):
    fixtures = {k: v for k, v in FIXTURES.items() if folder not in k.parents}
    fixtures[Path("README.md")] = "x\n"
    repo = Repo(tmp_path, fixtures)
    rc, result = repo.run()
    assert_error(rc, result, "fixtures: ")
    assert any("no such folder" in e for e in result["errors"]), result["errors"]


def test_a_rule_file_that_is_not_valid(tmp_path):
    fixtures = dict(FIXTURES)
    fixtures[RULE_DIR / "AA03.yml"] = "test_a:\n  pass_str: SELECT 1\n"
    repo = Repo(tmp_path, fixtures)
    rc, result = repo.run()
    assert_error(rc, result, "fixtures: ")
    assert any("no 'rule' key" in e for e in result["errors"]), result["errors"]


def test_no_pinned_commit(tmp_path):
    folder = tmp_path / "not-a-repo"
    folder.mkdir()
    rc, result = run_check("--root", str(folder))
    assert rc == 2
    assert [e.split(":", 1)[0] for e in result["errors"]] == [
        "report",
        "oracle",
        "autofix oracle",
        "jinja raw record",
        "known failures",
        "fixtures",
        "pinned commit",
    ]


def test_no_check_submodule_script(repo):
    (repo.root / "scripts" / "check-submodule").unlink()
    rc, result = repo.run()
    assert_error(rc, result, "submodule: ")


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "[]",
        '{"rules": {"cases": 1, "jinja": 1, "templater": 1}}',
        '{"rules": {"cases": 1, "jinja": 1}, "autofix": {"cases": 1, "jinja": 1}}',
        '{"rules": {"cases": "1", "jinja": 1, "templater": 1},'
        ' "autofix": {"cases": 1, "jinja": 1, "templater": 1}}',
    ],
)
def test_bad_recorded_counts(repo, text):
    repo.run()
    repo.write(RECORDED, text)
    rc, result = repo.run(write=False)
    assert_error(rc, result, "recorded counts: ")


# This repository: the pinned fixtures, the record, and the status file.


def pinned_commit() -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD:third_party/sqlfluff"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def real_known() -> dict[str, str]:
    return known_failures.parse(
        (REPO_ROOT / KNOWN).read_text(encoding="utf8"), str(KNOWN)
    )


def test_this_repository_gives_the_recorded_classes(tmp_path):
    """The real fixtures, the real Jinja as raw record, the real
    known_failures/sqll.txt, and the real submodule check, with a report in
    which sqll passes each case that has no line in the known failures, and
    an oracle output that passes each case. The classes come from the data:
    the counts are those of the design record."""
    known = real_known()
    ids = [c.id for c in rules.discover(SQLFLUFF_ROOT)]
    ids += [c.id for c in autofix.discover(SQLFLUFF_ROOT)]
    report = {
        "sqlfluff_ref": pinned_commit(),
        "cases": [case(i, "fail" if i in known else "pass") for i in ids],
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf8")
    oracle = tmp_path / "oracle.jsonl"
    oracle.write_text(
        oracle_text({i: "pass" for i in ids if i.startswith("rules/")}), "utf8"
    )
    autofix_oracle = tmp_path / "autofix-oracle.jsonl"
    autofix_oracle.write_text(
        oracle_text({i: "pass" for i in ids if i.startswith("autofix/")}), "utf8"
    )
    rc, result = run_check(
        "--report",
        str(report_path),
        "--oracle",
        str(oracle),
        "--autofix-oracle",
        str(autofix_oracle),
    )
    assert rc == 0, (result["errors"], other_failures(result))
    counts = result["counts"]
    assert counts["rules"]["cases"] == 2527
    assert counts["rules"]["classes"][JINJA] == 169
    assert counts["rules"]["fixture_classes"]["templater"] == 13
    assert counts["rules"]["classes"][NO_CLASS] == 0
    assert counts["autofix"]["cases"] == 61
    assert counts["autofix"]["classes"][JINJA] == 21
    assert counts["autofix"]["fixture_classes"]["templater"] == 0
    assert counts["autofix"]["classes"][NO_CLASS] == 0
    assert result["inputs"]["jinja_raw"] == "results/S3b/C14-jinja-raw.json"
    assert result["inputs"]["known_failures"] == "known_failures/sqll.txt"
    # Each Jinja case is a known failure (the exit of this stone keeps them).
    jinja = [i for i, c in result["cases"].items() if c["class"] == JINJA]
    assert all(i in known for i in jinja)


def design_counts(name: str) -> dict[str, int]:
    """A list "AL01 1, AL02 1, ..." of section 3 of the design record."""
    text = " ".join(DESIGN.read_text("utf8").split())
    part = text.split(name, 1)[1].split(".", 1)[0]
    return {k: int(v) for k, v in re.findall(r"([A-Z]{2}\d{2}[\w-]*) (\d+)", part)}


def record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf8"))


def test_the_record_is_a_real_run_of_the_check():
    """results/S5/parity.json: one real local run on main."""
    data = record()
    output = data["output"]
    assert data["exit_code"] == output["exit_code"] == 0
    assert output["status"] == "pass"
    assert output["errors"] == []
    assert output["exit_mode"] is False
    assert all(i["ok"] for i in output["items"] if i["enforced"])
    assert re.fullmatch(r"[0-9a-f]{40}", data["main_commit"])
    assert output["commit"] == data["main_commit"]
    assert output["pinned_commit"] == output["report_sqlfluff_ref"] == pinned_commit()
    assert output["jinja_raw_commit"] == pinned_commit()
    assert data["command"].startswith(
        "uv run --frozen --project harness python scripts/s5/parity"
    )
    assert data["machine_lock"] == "flock /tmp/sqll-machine.lock"
    ids = {c.id for c in rules.discover(SQLFLUFF_ROOT)}
    ids |= {c.id for c in autofix.discover(SQLFLUFF_ROOT)}
    assert set(output["cases"]) == ids
    steps = {s["command"].split(" ", 1)[0]: s for s in data["steps"]}
    assert all(s["exit_code"] == 0 for s in data["steps"]), data["steps"]
    assert "scripts/build-sqll" in steps


def test_the_record_gives_the_numbers_of_the_task():
    """The acceptance of T2: rules 2527 (38 pass, 169 Jinja, 13 templater,
    2307 gap), autofix 61 (0 pass, 21 Jinja, 40 gap)."""
    counts = record()["output"]["counts"]
    assert counts["rules"]["cases"] == 2527
    assert counts["rules"]["classes"] == {
        PASS: 38,
        JINJA: 169,
        TEMPLATER: 13,
        GAP: 2307,
        NO_CLASS: 0,
    }
    assert counts["autofix"]["cases"] == 61
    assert counts["autofix"]["classes"] == {
        PASS: 0,
        JINJA: 21,
        TEMPLATER: 0,
        GAP: 40,
        NO_CLASS: 0,
    }
    assert counts["rules"]["passed_in_oracle"] == counts["rules"]["sqll_passed"]


def test_the_record_agrees_with_the_design_record_for_each_file():
    """Section 3 of the design record gives the Jinja count of each rule
    file, and the templater count of each rule file."""
    groups = record()["output"]["by_group"]
    jinja = {g: c[JINJA] for g, c in groups["rules"].items() if c[JINJA]}
    assert jinja == design_counts("The rule files with Jinja cases:")
    templater = {g: c[TEMPLATER] for g, c in groups["rules"].items() if c[TEMPLATER]}
    assert templater == design_counts("- The templater class:")
    autofix_jinja = {g: c[JINJA] for g, c in groups["autofix"].items() if c[JINJA]}
    assert autofix_jinja == {"ansi": 16, "bigquery": 5}
    passes = {g: c[PASS] for g, c in groups["rules"].items() if c[PASS]}
    assert passes == {"CP01": 23, "CP03": 10, "CP04": 5}


def status_rows() -> dict[str, str]:
    rows = {}
    for line in STATUS.read_text("utf8").splitlines():
        match = re.match(r"\| (T\d+[a-c]?) \|", line)
        if match:
            rows[match.group(1)] = line
    return rows


def test_status_row_of_t1_and_t2():
    rows = status_rows()
    assert rows["T1"].endswith("| Done (PR #108, main `64bbb0e`) |")
    assert "`scripts/s5/parity`" in rows["T2"]
    assert "`results/S5/parity.json`" in rows["T2"]
    assert re.search(r"\| (In review|Done) \(PR #\d+[^|]*\) \|$", rows["T2"]), rows[
        "T2"
    ]


SPLIT = {
    "T5": ["T5a", "T5b"],
    "T6": ["T6a", "T6b", "T6c"],
    "T10": ["T10a", "T10b", "T10c"],
    "T11": ["T11a", "T11b", "T11c"],
    "T12": ["T12a", "T12b", "T12c"],
    "T13": ["T13a", "T13b", "T13c"],
    "T14": ["T14a", "T14b", "T14c"],
    "T17": ["T17a", "T17b", "T17c"],
}


def test_status_records_the_split_tasks_with_their_goals():
    rows = status_rows()
    for task, parts in SPLIT.items():
        assert task not in rows, task
        for part in parts:
            cells = [c.strip() for c in rows[part].strip("|").split("|")]
            assert len(cells) == 4, part
            # The goal column of each split row is not empty.
            assert len(cells[2]) > 20, part
            assert cells[3] == "Not started", part
    order = list(rows)
    assert order == sorted(order, key=lambda t: (int(t[1:].rstrip("abc")), t))
