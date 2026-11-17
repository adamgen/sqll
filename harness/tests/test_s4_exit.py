"""The exit check of S4 (parser parity: sqll passes 100% of the dialect parse
fixtures with an exact tree match): scripts/s4/exit.py.

Task T5 (the exit record gives the CI proof that sqll passes 100% of the
dialect parse fixtures with an exact tree match, and the orchestrator can
approve this stone) of this stone. Exit record: docs/decisions/s4-exit.md.

The tests use copies of the real inputs (results/S4/, results/s1/summary.json,
known_failures/sqll.txt) in a scratch folder. The git facts come from a fake
function, because a CI checkout is a shallow clone with no history; a test of
the real git commands uses a new git repository. Each test of an item changes
one input and finds exit code 1 and the failed check. Each test of an input
that is missing or not valid finds exit code 2 and no record.
"""

import copy
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sqll_harness.paths import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "s4" / "exit.py"
RECORD = REPO_ROOT / "results" / "S4" / "exit.json"
CI_RECORD = REPO_ROOT / "results" / "S4" / "exit-ci.json"
STATUS = REPO_ROOT / "status" / "S4.md"
DOC = REPO_ROOT / "docs" / "decisions" / "s4-exit.md"
OTHER = "f" * 40


def load_module():
    spec = importlib.util.spec_from_file_location("s4_exit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exit_mod = load_module()
INPUTS = exit_mod.INPUTS
PINNED = exit_mod.PINNED
START = exit_mod.START


def good_git(ci_head: str) -> dict:
    """The git facts of a clean checkout with no parse-path change."""
    return {
        "pinned": {
            "command": "git rev-parse HEAD:third_party/sqlfluff",
            "exit_code": 0,
            "output": PINNED,
        },
        "submodule_head": {
            "command": "git -C third_party/sqlfluff rev-parse HEAD",
            "exit_code": 0,
            "output": PINNED,
        },
        "check_submodule": {
            "command": 'scripts/check-submodule "in the S4 exit check"',
            "exit_code": 0,
            "output": [],
        },
        "start_in_ci_head": {"command": "start ci", "exit_code": 0},
        "ci_head_in_head": {"command": "ci HEAD", "exit_code": 0},
        "diff_ci": {
            "command": "git diff --name-only",
            "files": ["status/S4.md", "scripts/s4/parity"],
        },
        "diff_head_parse_path": {"command": "git diff HEAD", "files": []},
    }


@pytest.fixture
def case(tmp_path, monkeypatch):
    """Copies of the real inputs, the git facts, and a runner."""

    class Case:
        def __init__(self):
            self.dir = tmp_path / "inputs"
            self.dir.mkdir()
            self.paths = {}
            for name, rel in INPUTS.items():
                dst = self.dir / rel.name
                shutil.copyfile(REPO_ROOT / rel, dst)
                self.paths[name] = dst
            self.out = tmp_path / "exit.json"
            head = json.loads(self.paths["ci"].read_text("utf8"))["head_sha"]
            self.git = good_git(head)
            monkeypatch.setattr(
                exit_mod, "git_facts", lambda root, ci_head: copy.deepcopy(self.git)
            )

        def json(self, name: str) -> dict:
            return json.loads(self.paths[name].read_text("utf8"))

        def write(self, name: str, data) -> None:
            self.paths[name].write_text(
                json.dumps(data, indent=1) + "\n" if isinstance(data, dict) else data,
                "utf8",
            )

        def edit(self, name: str, change) -> None:
            data = self.json(name)
            change(data)
            self.write(name, data)

        def argv(self) -> list[str]:
            args = []
            for name, path in self.paths.items():
                args += [f"--{name.replace('_', '-')}", str(path)]
            return [*args, "--out", str(self.out)]

        def run(self, *extra: str) -> int:
            return exit_mod.main([*self.argv(), *extra])

        def report(self) -> dict:
            return json.loads(self.out.read_text("utf8"))

        def item(self, key: str) -> dict:
            return {i["item"]: i for i in self.report()["items"]}[key]

    return Case()


def step(ci: dict, name: str) -> dict:
    return next(s for s in ci["steps"] if s["name"] == name)


def edit_output(ci: dict, change) -> None:
    """Change the JSON output of the parity step and write its lines again."""
    lines = step(ci, exit_mod.STEP)["lines"]
    start = lines.index("{")
    out = json.loads("\n".join(lines[start:]))
    change(out)
    lines[start:] = json.dumps(out, indent=1).splitlines()


def edit_counts(**counts):
    return lambda ci: edit_output(ci, lambda out: out["counts"].update(counts))


def edit_item(number: int, ok: bool):
    def change(out):
        for item in out["items"]:
            if item["item"] == number:
                item["ok"] = ok

    return lambda ci: edit_output(ci, change)


def replace_line(name: str, old: str, new: str):
    def change(ci):
        lines = step(ci, name)["lines"]
        lines[lines.index(old)] = new

    return change


def remove_line(name: str, old: str):
    return lambda ci: step(ci, name)["lines"].remove(old)


# Exit code 0 on the real inputs.


def test_real_inputs_meet_each_item(case, capsys):
    assert case.run() == 0
    report = case.report()
    assert report["result"] == {
        "met": True,
        "failed_items": [],
        "state": "Awaiting approval",
    }
    assert [i["item"] for i in report["items"]] == list("abcdefg")
    assert all(i["met"] and not i["failed"] for i in report["items"])
    assert report["ci"]["event"] == "push"
    assert report["ci"]["branch"] == "main"
    assert report["ci"]["conclusion"] == "success"
    assert report["ci"]["summary_line"] == exit_mod.SUMMARY
    a = case.item("a")["values"]
    assert a["ci_summary_line"] == (
        "S4 parity: pass: sqll dialects 2306 of 2306 discovered cases pass in 28"
        " dialects (exact 2306, no_unparsable 2306, 2306 pass in the oracle); gaps 0"
    )
    assert a["ci_counts"]["exact"] == a["ci_counts"]["no_unparsable"] == 2306
    assert case.item("b")["values"]["dialects_lines"] == 0
    assert case.item("c")["values"]["ci_passed_in_oracle"] == 2306
    assert case.item("d")["values"]["pinned"] == PINNED
    assert case.item("f")["values"]["information_only"] is True
    assert case.item("g")["values"]["parse_path_files"] == []
    out = capsys.readouterr().out
    assert "S4 exit: pass: items met 7 of 7; failed items: none" in out


def test_check_mode(case):
    assert case.run() == 0
    assert case.run("--check") == 0
    case.out.write_text(case.out.read_text("utf8") + " ", "utf8")
    assert case.run("--check") == 1


def test_committed_record_is_met():
    """results/S4/exit.json is the record of a run with each item met, on the
    CI proof of results/S4/exit-ci.json."""
    record = json.loads(RECORD.read_text("utf8"))
    ci = json.loads(CI_RECORD.read_text("utf8"))
    assert record["result"]["met"] is True
    assert record["result"]["state"] == "Awaiting approval"
    assert all(i["met"] for i in record["items"])
    assert record["ci"]["run_id"] == ci["run_id"]
    assert record["ci"]["head_sha"] == ci["head_sha"]
    git = record["git"]
    assert git["pinned"]["output"] == PINNED
    assert git["submodule_head"]["output"] == PINNED
    assert git["check_submodule"]["exit_code"] == 0
    assert git["start_in_ci_head"]["exit_code"] == 0
    assert git["ci_head_in_head"]["exit_code"] == 0
    assert not [f for f in git["diff_ci"]["files"] if exit_mod.is_parse_path(f)]
    assert git["diff_head_parse_path"]["files"] == []


def test_live_inputs_with_the_recorded_git_facts(monkeypatch):
    """The committed inputs, with the git facts of the record, meet each item."""
    record = json.loads(RECORD.read_text("utf8"))
    monkeypatch.setattr(exit_mod, "git_facts", lambda root, head: record["git"])
    paths = {name: REPO_ROOT / rel for name, rel in INPUTS.items()}
    report = exit_mod.make_report(REPO_ROOT, paths)
    assert report["result"]["met"] is True
    assert report["ci"] == record["ci"]
    for new, old in zip(report["items"], record["items"], strict=True):
        assert new["item"] == old["item"]
        assert new["checks"] == old["checks"]


# Exit code 1: each item.

CI_CASES = {
    "a": [
        ("ci_workflow", lambda ci: ci.update(workflow="Ownership")),
        ("ci_push_on_main", lambda ci: ci.update(event="pull_request")),
        ("ci_push_on_main", lambda ci: ci.update(branch="claude/s4")),
        ("ci_run_success", lambda ci: ci.update(conclusion="failure")),
        (
            "ci_jobs_ok",
            lambda ci: ci.update(
                jobs_by_conclusion={"success": ci["jobs_total"] - 1, "failure": 1}
            ),
        ),
        (
            "ci_jobs_ok",
            lambda ci: ci.update(jobs_by_conclusion={"success": ci["jobs_total"] - 1}),
        ),
        ("ci_job_success", lambda ci: ci["job"].update(conclusion="failure")),
        ("ci_job_success", lambda ci: ci["job"].update(name="dialect-oracle (x)")),
        (
            "ci_step_success",
            lambda ci: step(ci, exit_mod.STEP).update(conclusion="skipped"),
        ),
        (
            "ci_step_success",
            lambda ci: step(ci, exit_mod.STEP).update(name="Another step"),
        ),
        (
            "ci_summary_line",
            replace_line(
                exit_mod.STEP,
                exit_mod.SUMMARY,
                exit_mod.SUMMARY.replace("gaps 0", "gaps 1"),
            ),
        ),
        ("ci_summary_line", remove_line(exit_mod.STEP, exit_mod.SUMMARY)),
        (
            "ci_output_pass",
            lambda ci: edit_output(ci, lambda o: o.update(status="fail")),
        ),
        ("ci_output_pass", lambda ci: edit_output(ci, lambda o: o.update(exit_code=1))),
        (
            "ci_output_pass",
            lambda ci: step(ci, exit_mod.STEP).update(lines=[exit_mod.SUMMARY]),
        ),
        (
            "ci_output_commit",
            lambda ci: edit_output(ci, lambda o: o.update(commit=OTHER)),
        ),
        ("ci_output_counts", edit_counts(exact=2305)),
        ("ci_output_counts", edit_counts(no_unparsable=2305)),
        ("ci_output_counts", edit_counts(discovered_cases=2305, report_cases=2305)),
        ("ci_output_counts", edit_counts(discovered_dialects=27)),
        ("ci_output_counts", edit_counts(skipped=1)),
        ("ci_output_counts", edit_counts(gaps=1)),
        ("ci_output_items", edit_item(2, False)),
        ("ci_output_items", lambda ci: edit_output(ci, lambda o: o["items"].pop())),
    ],
    "b": [
        ("ci_output", edit_counts(known_failures_dialects_lines=1)),
    ],
    "c": [
        (
            "ci_oracle_step_success",
            lambda ci: step(ci, exit_mod.ORACLE_STEP).update(conclusion="failure"),
        ),
        ("ci_oracle_line", remove_line(exit_mod.ORACLE_STEP, exit_mod.ORACLE_LINE)),
        (
            "ci_oracle_line",
            replace_line(
                exit_mod.ORACLE_STEP,
                exit_mod.ORACLE_LINE,
                exit_mod.ORACLE_LINE.replace("2306 of them", "2305 of them"),
            ),
        ),
        ("ci_passed_in_oracle", edit_counts(passed_in_oracle=2305)),
        ("ci_passed_in_oracle", edit_counts(oracle_cases=2305)),
        ("ci_item_4", edit_item(4, False)),
    ],
    "d": [
        (
            "ci_output",
            lambda ci: edit_output(ci, lambda o: o.update(report_sqlfluff_ref=OTHER)),
        ),
        (
            "ci_output",
            lambda ci: edit_output(ci, lambda o: o.update(pinned_commit=OTHER)),
        ),
    ],
}


@pytest.mark.parametrize(
    ("key", "check", "change"),
    [(k, c, f) for k, cases in CI_CASES.items() for c, f in cases],
)
def test_ci_record_gap_fails(case, key, check, change):
    case.edit("ci", change)
    assert case.run() == 1
    item = case.item(key)
    assert item["met"] is False
    assert check in item["failed"]
    assert key in case.report()["result"]["failed_items"]
    assert case.report()["result"]["state"] == "Exit not met"


def s1_dialects(data: dict) -> dict:
    return data["results"]["sqll"]["suites"]["dialects"]


OTHER_CASES = [
    ("s1", "a", "s1_summary", lambda d: s1_dialects(d).update(passed=2305)),
    ("s1", "a", "s1_summary", lambda d: s1_dialects(d).update(total=2305)),
    ("s1", "a", "s1_summary", lambda d: s1_dialects(d).update(skipped=1)),
    ("s1", "a", "s1_summary", lambda d: s1_dialects(d)["checks"].update(exact=2305)),
    (
        "s1",
        "a",
        "s1_sqll_adapter_parse",
        lambda d: d["tools"]["sqll"]["preflight"].update(parse=False),
    ),
    ("s1", "d", "s1_sqlfluff_ref", lambda d: d.update(sqlfluff_ref=OTHER)),
    ("parity", "a", "parity_record", lambda d: d.update(exit_code=1)),
    ("parity", "a", "parity_record", lambda d: d["output"].update(status="fail")),
    (
        "parity",
        "a",
        "parity_record",
        lambda d: d["output"]["counts"].update(exact=2305),
    ),
    (
        "parity",
        "b",
        "parity_record",
        lambda d: d["output"]["counts"].update(known_failures_dialects_lines=1),
    ),
    (
        "parity",
        "c",
        "parity_record",
        lambda d: d["output"]["counts"].update(passed_in_oracle=2305),
    ),
    ("parity", "d", "parity_record", lambda d: d["output"].update(pinned_commit=OTHER)),
    (
        "parity",
        "d",
        "parity_record",
        lambda d: d["output"].update(report_sqlfluff_ref=OTHER),
    ),
    ("corpus", "f", "record_pass", lambda d: d.update(status="error")),
    ("corpus", "f", "record_pass", lambda d: d.update(exit_code=2)),
    ("corpus", "f", "rows_classified", lambda d: d["counts"].update(rows=19)),
]


@pytest.mark.parametrize(("name", "key", "check", "change"), OTHER_CASES)
def test_record_gap_fails(case, name, key, check, change):
    case.edit(name, change)
    assert case.run() == 1
    item = case.item(key)
    assert item["met"] is False
    assert check in item["failed"]


def gate_run(name: str):
    def find(data):
        return next(r for r in data["injected_gaps"]["runs"] if r["name"] == name)

    return find


GATE_CASES = [
    ("run_control", lambda d: gate_run("control")(d).update(exit_code=1)),
    (
        "run_control",
        lambda d: gate_run("control")(d).update(gaps={"missing": ["dialects/a/b"]}),
    ),
    (
        "run_known-failures-dialects-line",
        lambda d: gate_run("known-failures-dialects-line")(d).update(exit_code=0),
    ),
    (
        "run_known-failures-dialects-line",
        lambda d: gate_run("known-failures-dialects-line")(d).update(gaps={}),
    ),
    (
        "run_report-case-removed",
        lambda d: gate_run("report-case-removed")(d).update(exit_code=0),
    ),
    (
        "run_report-case-removed",
        lambda d: gate_run("report-case-removed")(d).update(
            gaps={"missing": ["x"], "extra": ["y"]}
        ),
    ),
    (
        "run_no-oracle-output",
        lambda d: gate_run("no-oracle-output")(d).update(exit_code=0),
    ),
    (
        "run_no-oracle-output",
        lambda d: gate_run("no-oracle-output")(d).update(errors=[]),
    ),
    (
        "run_no-oracle-output",
        lambda d: d["injected_gaps"]["runs"].remove(gate_run("no-oracle-output")(d)),
    ),
    ("ci_gate_step", lambda d: d["ci"].update(step_conclusion="skipped")),
    ("ci_gate_step", lambda d: d["ci"].update(conclusion="failure")),
    ("ci_gate_step", lambda d: d["ci"].update(log="S4 parity: fail")),
    ("ci_gate_step", lambda d: d["ci"].update(log_exit_code=1)),
    ("ci_gate_step", lambda d: d["ci"].update(job="dialect-oracle (sqlfluff-rs)")),
]


@pytest.mark.parametrize(("check", "change"), GATE_CASES)
def test_gate_gap_fails(case, check, change):
    case.edit("gate", change)
    assert case.run() == 1
    item = case.item("e")
    assert item["met"] is False
    assert check in item["failed"]


def test_known_failures_dialects_line_fails(case):
    text = case.paths["known_failures"].read_text("utf8")
    lines = sorted([*text.splitlines(), "dialects/ansi/select_a  # injected"])
    case.write("known_failures", "\n".join(lines) + "\n")
    assert case.run() == 1
    item = case.item("b")
    assert item["failed"] == ["no_dialects_line"]
    assert item["values"]["dialects_ids"] == ["dialects/ansi/select_a"]
    assert case.report()["result"]["failed_items"] == ["b"]


GIT_CASES = [
    ("a", "ci_head_in_head", lambda g: g["ci_head_in_head"].update(exit_code=1)),
    ("d", "pinned_commit", lambda g: g["pinned"].update(output=OTHER)),
    ("d", "submodule_head", lambda g: g["submodule_head"].update(output=OTHER)),
    (
        "d",
        "submodule_head",
        lambda g: g["submodule_head"].update(exit_code=None, output="not checked out"),
    ),
    (
        "d",
        "check_submodule",
        lambda g: g["check_submodule"].update(
            exit_code=1, output=["error: third_party/sqlfluff is not clean"]
        ),
    ),
    ("g", "start_in_ci_head", lambda g: g["start_in_ci_head"].update(exit_code=1)),
    (
        "g",
        "no_parse_path_change_to_ci_head",
        lambda g: g["diff_ci"]["files"].append("crates/sqll_parser/src/lib.rs"),
    ),
    (
        "g",
        "no_parse_path_change_to_ci_head",
        lambda g: g["diff_ci"]["files"].append("Cargo.lock"),
    ),
    (
        "g",
        "no_parse_path_change_to_ci_head",
        lambda g: g["diff_ci"]["files"].append("third_party/sqlfluff"),
    ),
    (
        "g",
        "no_parse_path_change_to_ci_head",
        lambda g: g["diff_ci"]["files"].append("scripts/build-sqll"),
    ),
    (
        "g",
        "no_parse_path_change_to_head",
        lambda g: g["diff_head_parse_path"]["files"].append(
            "crates/sqll_dialects/src/lib.rs"
        ),
    ),
]


@pytest.mark.parametrize(("key", "check", "change"), GIT_CASES)
def test_git_gap_fails(case, key, check, change):
    change(case.git)
    assert case.run() == 1
    item = case.item(key)
    assert item["met"] is False
    assert check in item["failed"]


def test_corpus_parser_gap_is_information_only(case):
    """A parser gap row of the corpus does not block the exit (design record
    section 4): item f stays met, with the row count in the record."""

    def change(d):
        d["counts"]["rows"] += 1
        d["counts"]["by_class"]["parser gap"] += 1

    case.edit("corpus", change)
    assert case.run() == 0
    values = case.item("f")["values"]
    assert values["by_class"]["parser gap"] == 1
    assert values["changes_parity_number"] is False


def test_parse_path():
    for path in (
        "crates/sqll_parser/src/lib.rs",
        "crates/sqll_dialects/build.rs",
        "Cargo.toml",
        "Cargo.lock",
        "rust-toolchain.toml",
        "scripts/build-sqll",
        "third_party/sqlfluff",
        ".cargo/config.toml",
    ):
        assert exit_mod.is_parse_path(path), path
    for path in (
        "scripts/s4/exit.py",
        "harness/sqll_harness/run.py",
        "status/S4.md",
        "docs/decisions/s4-exit.md",
        "crates.md",
    ):
        assert not exit_mod.is_parse_path(path), path


# Exit code 2: a missing input or an input that is not valid.


@pytest.mark.parametrize("name", list(INPUTS))
def test_missing_input(case, name, capsys):
    case.paths[name].unlink()
    assert case.run() == 2
    assert not case.out.exists()
    assert "no such file" in capsys.readouterr().err


@pytest.mark.parametrize("name", [n for n in INPUTS if n != "known_failures"])
def test_input_not_json(case, name, capsys):
    case.write(name, "{ not json")
    assert case.run() == 2
    assert not case.out.exists()
    assert "not valid JSON" in capsys.readouterr().err


def test_known_failures_not_valid(case, capsys):
    case.write("known_failures", "b/x\na/y\n")
    assert case.run() == 2
    assert not case.out.exists()
    assert "not sorted" in capsys.readouterr().err


MISSING_KEYS = [
    ("ci", lambda d: d.pop("head_sha")),
    ("ci", lambda d: d.update(head_sha="6df6a6a")),
    ("ci", lambda d: d.pop("steps")),
    ("ci", lambda d: d["steps"][0].pop("lines")),
    ("ci", lambda d: d["job"].pop("conclusion")),
    ("ci", lambda d: d.update(run_id="44073788566")),
    ("parity", lambda d: d.pop("output")),
    ("parity", lambda d: d["output"].pop("counts")),
    ("gate", lambda d: d.pop("injected_gaps")),
    ("gate", lambda d: d.pop("ci")),
    ("corpus", lambda d: d["counts"].pop("by_class")),
    ("s1", lambda d: d["results"].pop("sqll")),
    ("s1", lambda d: d.pop("sqlfluff_ref")),
]


@pytest.mark.parametrize(("name", "change"), MISSING_KEYS)
def test_input_key_missing(case, name, change):
    case.edit(name, change)
    assert case.run() == 2
    assert not case.out.exists()


def test_git_input_error(case, monkeypatch, capsys):
    def fail(root, head):
        raise exit_mod.InputError(f"git: the commit {START} is not in the history")

    monkeypatch.setattr(exit_mod, "git_facts", fail)
    assert case.run() == 2
    assert not case.out.exists()
    assert "not in the history" in capsys.readouterr().err


def test_cli_missing_input(tmp_path):
    out = tmp_path / "exit.json"
    done = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--ci",
            str(tmp_path / "missing.json"),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert done.returncode == 2
    assert "S4 exit: error: ci:" in done.stderr
    assert "no such file" in done.stderr
    assert not out.exists()


# The git commands, in a new git repository.


def git(repo: Path, *args: str) -> str:
    env_args = [
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "init.defaultBranch=main",
    ]
    return subprocess.run(
        ["git", *env_args, *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repository: START (the pinned gitlink and scripts/check-submodule),
    a parse-path change (the CI head), and a document change (HEAD)."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    (root / "scripts").mkdir()
    shutil.copyfile(
        REPO_ROOT / "scripts" / "check-submodule", root / "scripts" / "check-submodule"
    )
    (root / "README.md").write_text("start\n", "utf8")
    git(root, "add", "-A")
    git(
        root,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{PINNED},third_party/sqlfluff",
    )
    git(root, "commit", "-qm", "start")
    start = git(root, "rev-parse", "HEAD")
    (root / "crates" / "sqll_parser" / "src").mkdir(parents=True)
    (root / "crates" / "sqll_parser" / "src" / "lib.rs").write_text("// x\n", "utf8")
    git(root, "add", "crates")
    git(root, "commit", "-qm", "parse path")
    ci_head = git(root, "rev-parse", "HEAD")
    (root / "status.md").write_text("x\n", "utf8")
    git(root, "add", "status.md")
    git(root, "commit", "-qm", "doc")
    monkeypatch.setattr(exit_mod, "START", start)
    return root, start, ci_head


def test_git_facts_in_a_repository(repo):
    root, start, ci_head = repo
    facts = exit_mod.git_facts(root, ci_head)
    assert facts["pinned"]["output"] == PINNED
    assert facts["pinned"]["exit_code"] == 0
    assert facts["start_in_ci_head"]["exit_code"] == 0
    assert facts["ci_head_in_head"]["exit_code"] == 0
    assert facts["diff_ci"]["files"] == ["crates/sqll_parser/src/lib.rs"]
    assert facts["diff_head_parse_path"]["files"] == ["crates/sqll_parser/src/lib.rs"]
    # No checkout of the submodule: check-submodule fails, and the HEAD of the
    # submodule is not known.
    assert facts["check_submodule"]["exit_code"] == 1
    assert any("not checked out" in x for x in facts["check_submodule"]["output"])
    assert facts["submodule_head"]["exit_code"] is None
    item_d = exit_mod.item_d(
        {
            "ci": {"steps": []},
            "parity": {"output": {}},
            "s1": {"sqlfluff_ref": PINNED},
        },
        facts,
    )
    assert {"submodule_head", "check_submodule"} <= set(item_d["failed"])
    item_g = exit_mod.item_g(facts)
    assert item_g["failed"] == [
        "no_parse_path_change_to_ci_head",
        "no_parse_path_change_to_head",
    ]
    assert item_g["values"]["parse_path_files"] == ["crates/sqll_parser/src/lib.rs"]


def test_git_facts_submodule_checkout(repo):
    """A clean checkout of another commit: check-submodule passes, and the
    HEAD of the submodule shows the other commit."""
    root, start, ci_head = repo
    sub = root / "third_party" / "sqlfluff"
    sub.mkdir(parents=True)
    git(sub, "init", "-q")
    (sub / "a.txt").write_text("a\n", "utf8")
    git(sub, "add", "a.txt")
    git(sub, "commit", "-qm", "a")
    facts = exit_mod.git_facts(root, ci_head)
    assert facts["check_submodule"]["exit_code"] == 0
    assert facts["submodule_head"]["exit_code"] == 0
    assert facts["submodule_head"]["output"] == git(sub, "rev-parse", "HEAD")
    assert facts["submodule_head"]["output"] != PINNED


def test_git_facts_not_ancestor(repo):
    root, start, ci_head = repo
    git(root, "checkout", "-q", start)
    facts = exit_mod.git_facts(root, ci_head)
    assert facts["ci_head_in_head"]["exit_code"] == 1
    assert facts["diff_head_parse_path"]["files"] == []


def test_git_facts_missing_commit(repo):
    root, start, ci_head = repo
    with pytest.raises(exit_mod.InputError, match="not in the history"):
        exit_mod.git_facts(root, OTHER)


def test_git_facts_no_pinned_commit(repo):
    root, start, ci_head = repo
    git(root, "rm", "-q", "--cached", "third_party/sqlfluff")
    git(root, "commit", "-qm", "no submodule")
    with pytest.raises(exit_mod.InputError, match="gives no commit"):
        exit_mod.git_facts(root, ci_head)


# The records of this task.


def test_exit_record_document():
    text = DOC.read_text("utf8")
    ci = json.loads(CI_RECORD.read_text("utf8"))
    assert ci["url"] in text
    assert ci["head_sha"][:7] in text
    assert exit_mod.SUMMARY in text
    assert PINNED in text
    assert START[:7] in text
    assert "Awaiting approval" in text


def test_status_state():
    text = STATUS.read_text("utf8")
    assert "- State: Awaiting approval." in text
    rows = [x for x in text.splitlines() if re.match(r"\| T\d+ \|", x)]
    states = {row.split(" | ")[0][2:]: row.rsplit(" | ", 1)[1] for row in rows}
    assert set(states) == {"T1", "T2", "T3", "T4", "T5"}
    for task in ("T1", "T2", "T3", "T4"):
        assert states[task].startswith("Done (PR #"), task
    assert states["T5"].startswith("In review (PR #")
