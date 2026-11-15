"""The parity check of S4 (parser parity: sqll passes 100% of the dialect
parse fixtures with an exact tree match): scripts/s4/parity.

Task T2 (each dialect fixture of the pinned sqlfluff is one harness case, and
the check fails closed on each gap) of S4. Design record:
docs/decisions/s4-parity.md, section 3. Each test of a gap makes one gap in
good inputs and finds exit code 1 and the gap in its list. Thus a test fails
if the check of its gap is removed. Each test of an input that is missing or
not valid finds exit code 2.

Most tests use a small repository in a temp folder: a superproject with the
submodule third_party/sqlfluff (4 dialect cases in 2 dialects), a copy of
scripts/check-submodule, and known_failures/sqll.txt. The tests do not change
the submodule of this repository.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT
from sqll_harness.suites import dialects

SCRIPT = REPO_ROOT / "scripts" / "s4" / "parity"
RECORD = REPO_ROOT / "results" / "S4" / "parity.json"
STATUS = REPO_ROOT / "status" / "S4.md"
REPORT = Path("out") / "report.json"
ORACLE = Path("out") / "dialect-oracle-sqlfluff.jsonl"
KNOWN = Path("known_failures") / "sqll.txt"
SUB = Path("third_party") / "sqlfluff"

# The fixture files of the small submodule. ansi/c.sql has no YAML file, thus
# it is not a case. README.md is not a dialect.
FIXTURES = {
    "README.md": "Not a dialect.\n",
    "ansi/a.sql": "SELECT 1\n",
    "ansi/a.yml": "file: {}\n",
    "ansi/b.sql": "SELECT 2\n",
    "ansi/b.yml": "file: {}\n",
    "ansi/b_nc.yml": "file: {}\n",
    "ansi/c.sql": "SELECT 3\n",
    "postgres/d.sql": "SELECT 4\n",
    "postgres/d.yml": "file: {}\n",
}
CASES = [
    "dialects/ansi/a",
    "dialects/ansi/b",
    "dialects/ansi/b_nc",
    "dialects/postgres/d",
]
KNOWN_TEXT = "rules/LT01/test_a  # a failure of another suite\n"

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


def case(case_id: str, **changes) -> dict:
    """A case record of the report (CaseResult of the harness)."""
    record = {
        "id": case_id,
        "suite": "dialects",
        "tool": "sqll",
        "status": "pass",
        "checks": {"exact": True, "no_unparsable": True},
        "reason": "",
        "duration_ms": 1,
        "tags": [],
    }
    record.update(changes)
    return record


def report(ref: str, ids: list[str]) -> dict:
    """A good report. It also has cases of other tools and suites that do not
    pass. The check must not use them."""
    cases = [case(i) for i in ids]
    cases.append(
        case(
            "dialects/ansi/a",
            tool="sqlfluff",
            status="fail",
            checks={"exact": False, "no_unparsable": False},
        )
    )
    cases.append(case("rules/LT01/test_a", suite="rules", status="fail", checks={}))
    return {
        "sqlfluff_ref": ref,
        "scope": {"suites": ["dialects"], "tools": ["sqll"]},
        "tools": {"sqll": {"version": "test"}},
        "summary": {},
        "known_failures": {},
        "cases": cases,
    }


def oracle_text(statuses: dict[str, str]) -> str:
    return "".join(
        json.dumps({"id": i, "status": s, "reason": ""}) + "\n"
        for i, s in statuses.items()
    )


class Repo:
    """A small repository in a temp folder, with good inputs."""

    def __init__(self, base: Path):
        source = base / "sqlfluff-source"
        fixtures = source / dialects.FIXTURE_DIR
        for name, text in FIXTURES.items():
            path = fixtures / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf8")
        git(source, "init", "-q")
        git(source, "add", ".")
        git(source, "commit", "-q", "-m", "fixtures")

        self.root = base / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q")
        git(self.root, "submodule", "add", "-q", str(source), SUB.as_posix())
        (self.root / "scripts").mkdir()
        shutil.copy2(REPO_ROOT / "scripts" / "check-submodule", self.root / "scripts")
        self.write(KNOWN, KNOWN_TEXT)
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "repository")
        self.pinned = git(self.root, "rev-parse", f"HEAD:{SUB.as_posix()}")
        self.report = report(self.pinned, CASES)
        self.oracle = dict.fromkeys(CASES, "pass")

    def write(self, relative: Path, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf8")

    def sqll_case(self, case_id: str) -> dict:
        return next(
            c
            for c in self.report["cases"]
            if c["id"] == case_id and c["suite"] == "dialects" and c["tool"] == "sqll"
        )

    def run(self, *args: str, write: bool = True) -> tuple[int, dict]:
        if write:
            self.write(REPORT, json.dumps(self.report))
            self.write(ORACLE, oracle_text(self.oracle))
        return run_check("--root", str(self.root), *args)


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


@pytest.fixture
def repo(tmp_path) -> Repo:
    return Repo(tmp_path)


def other_gaps(result: dict, *names: str) -> dict:
    return {k: v for k, v in result["gaps"].items() if v and k not in names}


def assert_gap(result: dict, rc: int, item: int, name: str, expected: list) -> None:
    """Exit code 1, the gap in its list, and its item is not ok."""
    assert rc == 1, result
    assert result["status"] == "fail"
    assert result["gaps"][name] == expected
    items = {i["item"]: i for i in result["items"]}
    assert items[item]["ok"] is False
    assert items[item]["gaps"][name] == len(expected)


# Good inputs.


def test_good_inputs_pass(repo):
    rc, result = repo.run()
    assert rc == 0, result
    assert result["status"] == "pass"
    assert result["errors"] == []
    assert result["pinned_commit"] == repo.pinned
    assert result["report_sqlfluff_ref"] == repo.pinned
    assert result["commit"] == git(repo.root, "rev-parse", "HEAD")
    assert result["counts"] == {
        "discovered_cases": 4,
        "discovered_dialects": 2,
        "report_cases": 4,
        "report_dialects": 2,
        "passed": 4,
        "failed": 0,
        "skipped": 0,
        "exact": 4,
        "no_unparsable": 4,
        "oracle_cases": 4,
        "oracle_passed": 4,
        "passed_in_oracle": 4,
        "known_failures_lines": 1,
        "known_failures_dialects_lines": 0,
        "gaps": 0,
    }
    assert result["by_dialect"] == {
        "ansi": {"cases": 3, "passed": 3},
        "postgres": {"cases": 1, "passed": 1},
    }
    assert [i["item"] for i in result["items"]] == [1, 2, 3, 4, 5]
    assert all(i["ok"] for i in result["items"])
    assert all(v == [] for v in result["gaps"].values())
    assert result["inputs"] == {
        "report": "out/report.json",
        "oracle": "out/dialect-oracle-sqlfluff.jsonl",
        "known_failures": "known_failures/sqll.txt",
        "fixtures": "third_party/sqlfluff/test/fixtures/dialects",
    }


def test_out_file_is_the_output(repo, tmp_path):
    out = tmp_path / "parity" / "result.json"
    rc, result = repo.run("--out", str(out))
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf8")) == result


def test_each_gap_is_in_one_item(repo):
    _, result = repo.run()
    names = [n for i in result["items"] for n in i["gaps"]]
    assert sorted(names) == sorted(result["gaps"])
    assert len(names) == len(set(names))


# Item 1: the sqll dialects case ids are exactly the discovered cases.


def test_missing_case(repo):
    repo.report["cases"].remove(repo.sqll_case("dialects/ansi/b"))
    rc, result = repo.run()
    assert_gap(result, rc, 1, "missing", ["dialects/ansi/b"])
    assert result["counts"]["report_cases"] == 3
    assert other_gaps(result, "missing") == {}


def test_no_sqll_case_is_each_case_missing(repo):
    repo.report = report(repo.pinned, [])
    rc, result = repo.run()
    assert_gap(result, rc, 1, "missing", CASES)


def test_extra_case(repo):
    repo.report["cases"].append(case("dialects/ansi/zzz"))
    rc, result = repo.run()
    assert_gap(result, rc, 1, "extra", ["dialects/ansi/zzz"])
    assert other_gaps(result, "extra") == {}


def test_duplicate_case(repo):
    repo.report["cases"].append(case("dialects/postgres/d"))
    rc, result = repo.run()
    assert_gap(result, rc, 1, "duplicate", ["dialects/postgres/d"])
    assert other_gaps(result, "duplicate") == {}


def test_skipped_case(repo):
    repo.sqll_case("dialects/ansi/a")["status"] = "skip"
    rc, result = repo.run()
    assert_gap(result, rc, 1, "skipped", ["dialects/ansi/a"])
    assert result["counts"]["skipped"] == 1
    assert other_gaps(result, "skipped") == {}


# Item 2: each sqll dialects case passes, with exact and no_unparsable true.


@pytest.mark.parametrize("status", ["fail", "error"])
def test_failed_case(repo, status):
    repo.sqll_case("dialects/ansi/b_nc")["status"] = status
    rc, result = repo.run()
    assert_gap(result, rc, 2, "not_passed", ["dialects/ansi/b_nc"])
    assert result["counts"]["failed"] == 1
    assert other_gaps(result, "not_passed") == {}


def test_exact_false(repo):
    repo.sqll_case("dialects/ansi/a")["checks"]["exact"] = False
    rc, result = repo.run()
    assert_gap(result, rc, 2, "exact_false", ["dialects/ansi/a"])
    assert result["counts"]["exact"] == 3
    assert other_gaps(result, "exact_false") == {}


def test_no_unparsable_false(repo):
    repo.sqll_case("dialects/postgres/d")["checks"]["no_unparsable"] = False
    rc, result = repo.run()
    assert_gap(result, rc, 2, "no_unparsable_false", ["dialects/postgres/d"])
    assert result["counts"]["no_unparsable"] == 3
    assert other_gaps(result, "no_unparsable_false") == {}


def test_a_missing_check_is_false(repo):
    repo.sqll_case("dialects/ansi/b")["checks"] = {}
    rc, result = repo.run()
    assert_gap(result, rc, 2, "exact_false", ["dialects/ansi/b"])
    assert result["gaps"]["no_unparsable_false"] == ["dialects/ansi/b"]


# Item 3: known_failures/sqll.txt has no dialects line.


def test_dialects_line_in_known_failures(repo):
    repo.write(KNOWN, "dialects/ansi/a  # a parser gap\n" + KNOWN_TEXT)
    rc, result = repo.run()
    assert_gap(result, rc, 3, "known_failures_dialects", ["dialects/ansi/a"])
    assert result["counts"]["known_failures_dialects_lines"] == 1
    assert other_gaps(result, "known_failures_dialects") == {}


def test_known_failures_option(repo, tmp_path):
    other = tmp_path / "sqll.txt"
    other.write_text("dialects/postgres/d  # a parser gap\n", encoding="utf8")
    rc, result = repo.run("--known-failures", str(other))
    assert_gap(result, rc, 3, "known_failures_dialects", ["dialects/postgres/d"])


# Item 4: the oracle has each case, and each sqll pass passes in the oracle.


def test_case_missing_in_the_oracle(repo):
    del repo.oracle["dialects/ansi/b_nc"]
    rc, result = repo.run()
    assert_gap(result, rc, 4, "oracle_missing", ["dialects/ansi/b_nc"])
    assert result["counts"]["passed_in_oracle"] == 3
    assert other_gaps(result, "oracle_missing") == {}


def test_extra_case_in_the_oracle(repo):
    repo.oracle["dialects/ansi/zzz"] = "pass"
    rc, result = repo.run()
    assert_gap(result, rc, 4, "oracle_extra", ["dialects/ansi/zzz"])
    assert other_gaps(result, "oracle_extra") == {}


@pytest.mark.parametrize("status", ["fail", "skip"])
def test_oracle_does_not_pass_a_sqll_pass(repo, status):
    repo.oracle["dialects/postgres/d"] = status
    rc, result = repo.run()
    assert_gap(result, rc, 4, "oracle_not_pass", ["dialects/postgres/d"])
    assert result["counts"]["oracle_passed"] == 3
    assert other_gaps(result, "oracle_not_pass") == {}


def test_oracle_option(repo, tmp_path):
    other = tmp_path / "oracle.jsonl"
    other.write_text(oracle_text(dict.fromkeys(CASES[1:], "pass")), encoding="utf8")
    rc, result = repo.run("--oracle", str(other))
    assert_gap(result, rc, 4, "oracle_missing", [CASES[0]])


# Item 5: the pinned commit and a clean submodule.


def test_wrong_sqlfluff_ref(repo):
    repo.report["sqlfluff_ref"] = "1" * 40
    rc, result = repo.run()
    assert rc == 1
    assert result["gaps"]["sqlfluff_ref"] == [
        f"the report sqlfluff_ref {'1' * 40} is not the pinned commit"
        f" {repo.pinned} (HEAD:third_party/sqlfluff)"
    ]
    assert_gap(result, rc, 5, "sqlfluff_ref", result["gaps"]["sqlfluff_ref"])
    assert result["report_sqlfluff_ref"] == "1" * 40
    assert other_gaps(result, "sqlfluff_ref") == {}


def test_report_option(repo, tmp_path):
    other = tmp_path / "report.json"
    data = report("unknown", CASES)
    other.write_text(json.dumps(data), encoding="utf8")
    repo.write(ORACLE, oracle_text(repo.oracle))
    rc, result = run_check("--root", str(repo.root), "--report", str(other))
    assert rc == 1
    assert len(result["gaps"]["sqlfluff_ref"]) == 1
    assert result["inputs"]["report"] == str(other)


@pytest.mark.parametrize(
    "change",
    [
        "untracked file",
        "changed file",
        "deleted file",
    ],
)
def test_submodule_has_a_change(repo, change):
    fixtures = repo.root / SUB / dialects.FIXTURE_DIR
    if change == "untracked file":
        (fixtures / "ansi" / "new.txt").write_text("new\n", encoding="utf8")
    elif change == "changed file":
        (fixtures / "ansi" / "a.yml").write_text("file: {x: 1}\n", encoding="utf8")
    else:
        (fixtures / "ansi" / "c.sql").unlink()
    rc, result = repo.run()
    assert rc == 1
    [gap] = result["gaps"]["submodule"]
    assert gap.startswith("scripts/check-submodule exit 1: error: third_party/sqlfluff")
    assert_gap(result, rc, 5, "submodule", [gap])
    assert other_gaps(result, "submodule") == {}


def test_submodule_checkout_is_not_the_pinned_commit(repo):
    sub = repo.root / SUB
    (sub / "NEW.md").write_text("new\n", encoding="utf8")
    git(sub, "add", "NEW.md")
    git(sub, "commit", "-q", "-m", "a new commit")
    head = git(sub, "rev-parse", "HEAD")
    rc, result = repo.run()
    assert_gap(
        result,
        rc,
        5,
        "submodule",
        [
            f"the checkout of third_party/sqlfluff is {head}, not the pinned"
            f" commit {repo.pinned}"
        ],
    )
    assert other_gaps(result, "submodule") == {}


def test_more_gaps_give_each_item(repo):
    repo.report["cases"].remove(repo.sqll_case("dialects/ansi/a"))
    repo.sqll_case("dialects/ansi/b")["status"] = "fail"
    repo.write(KNOWN, "dialects/ansi/b  # a parser gap\n" + KNOWN_TEXT)
    repo.oracle["dialects/postgres/d"] = "fail"
    repo.report["sqlfluff_ref"] = "unknown"
    rc, result = repo.run()
    assert rc == 1
    assert [i["ok"] for i in result["items"]] == [False] * 5


# Exit code 2: an input is missing or not valid.


def assert_error(rc: int, result: dict, text: str) -> None:
    assert rc == 2, result
    assert result["status"] == "error"
    assert result["counts"] is None and result["gaps"] is None
    assert any(text in e for e in result["errors"]), result["errors"]


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (None, "report: "),
        ("", "not valid JSON"),
        ("{", "not valid JSON"),
        ("[]", "not a JSON object"),
        ('{"cases": []}', "no sqlfluff_ref text"),
        ('{"sqlfluff_ref": "", "cases": []}', "no sqlfluff_ref text"),
        ('{"sqlfluff_ref": "x"}', "no cases list"),
        ('{"sqlfluff_ref": "x", "cases": {}}', "no cases list"),
        ('{"sqlfluff_ref": "x", "cases": [1]}', "case 0: not a JSON object"),
        ('{"sqlfluff_ref": "x", "cases": [{"id": "a"}]}', "case 0: no suite text"),
    ],
)
def test_report_not_valid(repo, text, error):
    repo.run()
    path = repo.root / REPORT
    if text is None:
        path.unlink()
    else:
        path.write_text(text, encoding="utf8")
    rc, result = repo.run(write=False)
    assert_error(rc, result, error)


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"status": "passed"}, "status 'passed' is not known"),
        ({"checks": None}, "checks is not an object"),
        ({"checks": {"exact": 1, "no_unparsable": True}}, "checks is not an object"),
    ],
)
def test_report_case_not_valid(repo, changes, error):
    repo.sqll_case("dialects/ansi/a").update(changes)
    rc, result = repo.run()
    assert_error(rc, result, f"case dialects/ansi/a: {error}")


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (None, "oracle: "),
        ("", "no case (no data)"),
        ("\n\n", "no case (no data)"),
        ("{\n", ":1: not valid JSON"),
        ('"text"\n', ":1: no id text"),
        ('{"status": "pass"}\n', ":1: no id text"),
        ('{"id": "dialects/ansi/a", "status": "error"}\n', "status 'error' is not"),
        ('{"id": "dialects/ansi/a"}\n', "status None is not known"),
        (
            '{"id": "dialects/ansi/a", "status": "pass"}\n' * 2,
            ":2: duplicate id dialects/ansi/a",
        ),
    ],
)
def test_oracle_not_valid(repo, text, error):
    repo.run()
    path = repo.root / ORACLE
    if text is None:
        path.unlink()
    else:
        path.write_text(text, encoding="utf8")
    rc, result = repo.run(write=False)
    assert_error(rc, result, error)


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (None, "known failures: "),
        ("rules/b  # x\nrules/a  # x\n", "ids are not sorted"),
        ("rules/a  # x\nrules/a  # y\n", "duplicate id rules/a"),
    ],
)
def test_known_failures_not_valid(repo, text, error):
    path = repo.root / KNOWN
    if text is None:
        path.unlink()
    else:
        path.write_text(text, encoding="utf8")
    rc, result = repo.run()
    assert_error(rc, result, error)


def test_no_submodule_checkout(repo):
    shutil.rmtree(repo.root / SUB)
    rc, result = repo.run()
    assert_error(rc, result, "fixtures: ")
    assert any("no such folder" in e for e in result["errors"])


def test_no_fixture_case(repo):
    fixtures = repo.root / SUB / dialects.FIXTURE_DIR
    for path in fixtures.glob("*/*.yml"):
        path.unlink()
    rc, result = repo.run()
    assert_error(rc, result, "no case (no data)")


def test_no_pinned_commit(repo, tmp_path):
    copy = tmp_path / "not-a-repository"
    shutil.copytree(repo.root, copy, ignore=shutil.ignore_patterns(".git"))
    (copy / SUB / ".git").unlink(missing_ok=True)
    rc, result = run_check("--root", str(copy))
    assert_error(rc, result, "pinned commit: ")


def test_no_check_submodule_script(repo):
    (repo.root / "scripts" / "check-submodule").unlink()
    rc, result = repo.run()
    assert_error(rc, result, "submodule: ")
    assert any("check-submodule: no such file" in e for e in result["errors"])


def test_each_input_error_is_given(repo):
    (repo.root / KNOWN).unlink()
    rc, result = run_check(
        "--root",
        str(repo.root),
        "--report",
        str(repo.root / "none.json"),
        "--oracle",
        str(repo.root / "none.jsonl"),
    )
    assert rc == 2
    assert [e.split(":", 1)[0] for e in result["errors"]] == [
        "report",
        "oracle",
        "known failures",
    ]


# This repository: the pinned fixtures, the record, and the status file.


def test_this_repository_with_a_report_of_each_discovered_case(tmp_path):
    """The real fixtures, the real known_failures/sqll.txt, and the real
    submodule check, with a report and an oracle output that pass each
    discovered case."""
    cases = dialects.discover(SQLFLUFF_ROOT)
    pinned = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD:third_party/sqlfluff"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    ids = [c.id for c in cases]
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report(pinned, ids)), encoding="utf8")
    oracle_path = tmp_path / "oracle.jsonl"
    oracle_path.write_text(oracle_text(dict.fromkeys(ids, "pass")), encoding="utf8")
    rc, result = run_check("--report", str(report_path), "--oracle", str(oracle_path))
    assert rc == 0, result["gaps"] or result["errors"]
    assert result["counts"]["discovered_cases"] == len(cases)
    assert result["counts"]["passed"] == len(cases)
    assert result["counts"]["known_failures_dialects_lines"] == 0
    assert result["inputs"]["known_failures"] == "known_failures/sqll.txt"


def test_the_record_is_a_real_pass_of_each_pinned_case():
    """results/S4/parity.json: one real local run on main."""
    record = json.loads(RECORD.read_text(encoding="utf8"))
    cases = dialects.discover(SQLFLUFF_ROOT)
    output = record["output"]
    assert record["exit_code"] == output["exit_code"] == 0
    assert output["status"] == "pass"
    assert output["errors"] == []
    assert all(v == [] for v in output["gaps"].values())
    assert all(i["ok"] for i in output["items"])
    counts = output["counts"]
    assert counts["discovered_cases"] == len(cases)
    assert counts["discovered_dialects"] == len({c.dialect for c in cases})
    for name in (
        "report_cases",
        "passed",
        "exact",
        "no_unparsable",
        "oracle_cases",
        "oracle_passed",
        "passed_in_oracle",
    ):
        assert counts[name] == len(cases), name
    assert counts["gaps"] == 0
    assert re.fullmatch(r"[0-9a-f]{40}", record["main_commit"])
    assert output["commit"] == record["main_commit"]
    assert output["pinned_commit"] == output["report_sqlfluff_ref"]
    assert record["command"].startswith(
        "uv run --frozen --project harness python scripts/s4/parity"
    )


def test_the_record_gives_the_start_numbers():
    """The design record gives 2306 cases in 28 dialects at the start."""
    counts = json.loads(RECORD.read_text(encoding="utf8"))["output"]["counts"]
    assert (counts["discovered_cases"], counts["discovered_dialects"]) == (2306, 28)
    text = " ".join(
        (REPO_ROOT / "docs" / "decisions" / "s4-parity.md").read_text("utf8").split()
    )
    assert "2306 cases in 28 dialects" in text


def test_status_row_of_t2():
    row = next(
        line
        for line in STATUS.read_text("utf8").splitlines()
        if line.startswith("| T2 |")
    )
    assert "`scripts/s4/parity`" in row
    assert "`results/S4/parity.json`" in row
    assert (
        "S4 (parser parity: sqll passes 100% of the dialect parse fixtures with an"
        " exact tree match)" in row
    )
    assert re.search(r"\| (In review|Done) \(PR #\d+\) \|$", row), row


def test_status_gives_the_numbers_of_the_record():
    record = json.loads(RECORD.read_text(encoding="utf8"))
    counts = record["output"]["counts"]
    text = STATUS.read_text("utf8").split("\n## Parity check\n", 1)[1]
    text = text.split("\n## ", 1)[0]
    assert f"main\n`{record['main_commit'][:7]}`" in text
    rows = {
        "Discovered cases": f"{counts['discovered_cases']} cases in"
        f" {counts['discovered_dialects']} dialects",
        "sqll dialects cases in the report": f"{counts['report_cases']} in"
        f" {counts['report_dialects']} dialects; {counts['passed']} pass; `exact`"
        f" {counts['exact']}; `no_unparsable` {counts['no_unparsable']}",
        "Oracle output": f"{counts['oracle_cases']} cases; {counts['oracle_passed']}"
        f" pass; {counts['passed_in_oracle']} sqll passes pass in the oracle",
        "`known_failures/sqll.txt`": f"{counts['known_failures_lines']} lines;"
        f" {counts['known_failures_dialects_lines']} `dialects` lines",
        "Pinned commit and report `sqlfluff_ref`": "`"
        + record["output"]["pinned_commit"]
        + "`; `scripts/check-submodule` exit 0",
        "Gaps": f"{counts['gaps']}; exit code {record['exit_code']}",
    }
    for name, value in rows.items():
        assert f"| {name} | {value} |" in text, name
