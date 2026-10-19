"""scripts/verify must run each check of CI (harness/sqll_harness/verify.py).

If CI gets a new step, add a check for it to verify.checks(), or add it to
verify.CI_ONLY if it is CI mechanics only (with its run text in
verify.CI_ONLY_RUN).
"""

import copy
import dataclasses
import fcntl
import json
import subprocess

import pytest

from sqll_harness import verify

CI = verify.load_ci()
KEYS = [key for key, _, _ in verify.ci_steps(CI)]
CHECKS = verify.checks()


def test_ci_step_names_are_unique():
    assert len(KEYS) == len(set(KEYS))


def test_no_drift_between_ci_and_the_local_checks():
    assert verify.drift(CHECKS, CI) == []


def _step(data: dict, job: str, name: str) -> dict:
    return next(s for s in data["jobs"][job]["steps"] if s.get("name") == name)


def _ci_change(change) -> list[str]:
    data = copy.deepcopy(CI)
    change(data)
    return verify.drift(CHECKS, data)


def _unit(data):
    return _step(data, "lint", "Unit tests")


def _rust(data):
    return _step(
        data, "lint", "Check the harness fixtures with the sqlfluff test and --rust"
    )


CI_CHANGES = {
    "new step env": lambda d: _unit(d)["env"].update(SQLL_STRICT="1"),
    "changed step env": lambda d: _unit(d)["env"].update(SQLL_REQUIRE_TOOLS="0"),
    "job env": lambda d: d["jobs"]["lint"].update(env={"X": "1"}),
    "container env": lambda d: d["jobs"]["lint"]["container"].update(env={"X": "1"}),
    "workflow env": lambda d: d["env"].update(X="1"),
    "new named step": lambda d: d["jobs"]["report"]["steps"].append(
        {"name": "New thing", "run": "true"}
    ),
    "new unnamed step": lambda d: d["jobs"]["lint"]["steps"].append({"run": "x"}),
    "new oracle argument": lambda d: _step(
        d, "report", "Compare the rule results with the sqlfluff test"
    ).update(
        run=_step(d, "report", "Compare the rule results with the sqlfluff test")[
            "run"
        ].replace("--out out/oracle.jsonl", "--out out/oracle.jsonl --strict")
    ),
    "run shard filter": lambda d: _step(d, "test", "Run shard").update(
        run=_step(d, "test", "Run shard")["run"] + " --filter x"
    ),
    "--rust removed from one line": lambda d: _rust(d).update(
        run=_rust(d)["run"].replace("--rust \\", "\\", 1)
    ),
    "duplicated command": lambda d: _rust(d).update(
        run=_rust(d)["run"] + "scripts/check-submodule x\nscripts/check-submodule x\n"
    ),
    "--rust moved to the sqlfluff dialect oracle": lambda d: d["jobs"][
        "dialect-oracle"
    ]["strategy"]["matrix"]["include"][0].update(args="--rust"),
    "new dialect-oracle tool": lambda d: d["jobs"]["dialect-oracle"]["strategy"][
        "matrix"
    ]["include"].append({"tool": "x", "venv": "x", "args": ""}),
    "--strict on the CI_ONLY merge": lambda d: _step(d, "report", "Merge").update(
        run=_step(d, "report", "Merge")["run"] + " --strict"
    ),
    "new line in a CI_ONLY step": lambda d: _step(
        d, "report", "Check test jobs"
    ).update(run="true\n" + _step(d, "report", "Check test jobs")["run"]),
    "changed expression in a CI_ONLY step": lambda d: _step(
        d, "report", "Check test jobs"
    ).update(
        run=_step(d, "report", "Check test jobs")["run"].replace(
            "needs.test.result", "needs.image.result"
        )
    ),
    "env on a CI_ONLY step": lambda d: _step(d, "report", "Merge").update(
        env={"SQLL_X": "1"}
    ),
    "changed env of a CI_ONLY step": lambda d: next(
        s for s in d["jobs"]["image"]["steps"] if s.get("id") == "find"
    )["env"].update(IMAGE="x"),
    "new line in safe.directory": lambda d: d["jobs"]["lint"]["steps"][1].update(
        run=d["jobs"]["lint"]["steps"][1]["run"] + "\ngit config x y"
    ),
    "working-directory": lambda d: _unit(d).update({"working-directory": "harness"}),
    "shell": lambda d: _step(d, "lint", "Tools").update(shell="bash {0}"),
    "continue-on-error": lambda d: _step(d, "report", "Merge").update(
        {"continue-on-error": True}
    ),
    "workflow defaults": lambda d: d.update(
        defaults={"run": {"working-directory": "harness"}}
    ),
    "job defaults": lambda d: d["jobs"]["lint"].update(
        defaults={"run": {"shell": "bash {0}"}}
    ),
    "if on the lint job": lambda d: d["jobs"]["lint"].update(
        {"if": "needs.changes.outputs.full == 'true'"}
    ),
    "if on the image job": lambda d: d["jobs"]["image"].update({"if": "false"}),
    "changed test job if": lambda d: d["jobs"]["test"].update({"if": "false"}),
    "removed report job if": lambda d: d["jobs"]["report"].pop("if"),
    "changed changes command": lambda d: _step(d, "changes", "Changed files").update(
        run="python3 ci/changes.py pull_request"
    ),
    "changed changes env": lambda d: _step(d, "changes", "Changed files")["env"].update(
        BEFORE="x"
    ),
    "ruff check --check": lambda d: _step(d, "lint", "Lint").update(
        run=_step(d, "lint", "Lint")["run"].replace(
            "ruff check harness", "ruff check --check harness"
        )
    ),
}


@pytest.mark.parametrize("name", CI_CHANGES)
def test_drift_finds_a_ci_change(name):
    assert _ci_change(CI_CHANGES[name])


LOCAL_CHANGES = {
    "|| true": ("recorded-summary", lambda c: c + " || true"),
    "||true": ("recorded-summary", lambda c: c + "||true"),
    "--filter": ("run", lambda c: c + " --filter dialects/"),
    "no SQLL_REQUIRE_TOOLS": (
        "unit-tests",
        lambda c: c.replace("SQLL_REQUIRE_TOOLS=1 ", ""),
    ),
    "set +e": ("summary", lambda c: "set +e\n" + c),
    "removed line": ("oracle-rules", lambda c: c.splitlines()[0]),
}


@pytest.mark.parametrize("name", LOCAL_CHANGES)
def test_drift_finds_a_local_change(name):
    target, change = LOCAL_CHANGES[name]
    changed = [
        dataclasses.replace(c, command=change(c.command)) if c.name == target else c
        for c in CHECKS
    ]
    assert verify.drift(changed, CI)


def test_ci_only_run_names_only_ci_only_steps_with_run():
    with_run = {k for k, step, _ in verify.ci_steps(CI) if "run" in step}
    assert set(verify.CI_ONLY_RUN) == with_run & set(verify.CI_ONLY)
    assert set(verify.CI_ONLY_RUN_ENV) <= set(verify.CI_ONLY_RUN)


def test_drift_finds_a_stale_ci_only_run_entry(monkeypatch):
    monkeypatch.setitem(verify.CI_ONLY_RUN, "report: actions/checkout", "x")
    monkeypatch.setitem(verify.CI_ONLY_RUN, "lint: Tools", "x")
    assert verify.drift(CHECKS, CI) == [
        "report: actions/checkout: CI_ONLY_RUN has a run text, but the step has none",
        "CI_ONLY_RUN 'lint: Tools': not a CI_ONLY step",
    ]


def test_drift_finds_a_weak_local_only_check():
    changed = [
        dataclasses.replace(c, command="scripts/setup || :") if c.name == "setup" else c
        for c in CHECKS
    ]
    assert verify.drift(changed, CI) == [
        "setup: ':' can hide a failure",
        "setup: '||' can hide a failure",
    ]


def test_drift_finds_a_word_moved_between_lint_commands():
    def move(c):
        if c.name == "ruff-check":
            return dataclasses.replace(
                c, command=c.command.replace(" check ", " check --check ")
            )
        if c.name == "ruff-format":
            return dataclasses.replace(c, command=c.command.replace("--check ", ""))
        return c

    assert verify.drift([move(c) for c in CHECKS], CI)


def test_ci_commands_use_env_and_matrix():
    step = {"run": "scripts/x --a\\\n  --b $V", "env": {"V": "--c\\d"}}
    assert verify.lines(verify.ci_commands(step, {})[0]) == [
        ("scripts/x", "--a", "--b", "--cd")
    ]
    step = {"run": "a\nb ${V}\n", "env": {"V": "1", "W": "x y"}}
    assert verify.ci_commands(step, {"env": {"IMAGE_REPO": "r"}}) == [
        "W='x y' a\nW='x y' b 1"
    ]
    job = {"strategy": {"matrix": {"include": [{"a": "1"}, {"a": ""}]}}}
    assert verify.ci_commands({"run": "x ${{ matrix.a }} ${{ y }}"}, job) == [
        "x 1 {}",
        "x  {}",
    ]


def test_check_names_are_unique_and_local_only_checks_are_few():
    names = [c.name for c in CHECKS]
    assert len(names) == len(set(names))
    assert [c.name for c in CHECKS if not c.ci] == ["setup", "submodule-before"]


def test_only_the_run_has_a_ci_diff():
    assert [c.name for c in CHECKS if c.ci_diff] == ["run"]


def test_each_report_check_also_needs_the_setup():
    for check in CHECKS:
        if verify.REPORT_FILE in check.needs:
            assert verify.SETUP in check.needs, check.name


def test_quick_has_no_run_or_report_check():
    for check in CHECKS:
        if check.quick:
            assert verify.REPORT_FILE not in check.needs
            assert check.name != "run"


def test_jobs_goes_to_the_run_only():
    changed = [c for a, c in zip(CHECKS, verify.checks(3), strict=True) if a != c]
    assert [c.name for c in changed] == ["run"]
    assert " --jobs 3 " in changed[0].command


# --- Runner ------------------------------------------------------------------


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A scratch repository root for the runner."""
    monkeypatch.setattr(verify, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(verify, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(verify, "REPORT", tmp_path / "out" / "report.json")
    monkeypatch.setattr(verify, "LOCK", tmp_path / "out" / "verify.lock")
    monkeypatch.setattr(verify.preflight, "check", lambda: 0)
    return tmp_path


S, R = verify.SETUP, verify.REPORT_FILE


def test_failures_and_skips(root, capsys):
    selected = [
        verify.Check("setup", "false"),
        verify.Check("tools", "true", needs=(S,)),
        verify.Check("lint", "false; echo after"),
        verify.Check("ok", "echo ok"),
        verify.Check("run", "echo old > out/report.json", needs=(S,)),
        verify.Check("report", "true", needs=(S, R)),
    ]
    result = verify.run_checks(selected, quick=False)
    status = {c["name"]: c["status"] for c in result["checks"]}
    assert status == {
        "setup": "fail",
        "tools": "skip",
        "lint": "fail",
        "ok": "pass",
        "run": "skip",
        "report": "skip",
    }
    assert result["result"] == "fail"
    assert (root / "out" / "verify" / "ok.log").read_text().endswith("ok\n")


def test_the_run_deletes_an_old_report(root):
    (root / "out").mkdir()
    (root / "out" / "report.json").write_text("{}")
    selected = [
        verify.Check("run", "false", removes=("out/report.json",)),
        verify.Check("report", "true", needs=(R,)),
    ]
    result = verify.run_checks(selected, quick=False)
    assert [c["status"] for c in result["checks"]] == ["fail", "skip"]


def test_quick_does_not_overwrite_the_full_result(root, capsys):
    selected = [verify.Check("ok", "true")]
    assert verify._main(selected, quick=False) == 0
    assert verify._main([verify.Check("bad", "false")], quick=True) == 1
    full = json.loads((root / "out" / "verify.json").read_text())
    quick = json.loads((root / "out" / "verify-quick.json").read_text())
    assert (full["mode"], full["result"]) == ("full", "pass")
    assert (quick["mode"], quick["result"]) == ("quick", "fail")
    assert (root / "out" / "verify" / "ok.log").exists()
    assert (root / "out" / "verify-quick" / "bad.log").exists()


def test_git_failure_is_not_a_clean_worktree(root, capsys):
    result = verify.run_checks([verify.Check("ok", "true")], quick=False)
    assert (result["commit"], result["worktree_clean"]) == (None, None)
    assert "WARNING: git failed" in capsys.readouterr().out


def test_dirty_worktree_gives_a_warning(root, capsys):
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    (root / ".gitignore").write_text("out/\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    result = verify.run_checks([verify.Check("ok", "true")], quick=False)
    assert result["worktree_clean"] is True
    assert "WARNING" not in capsys.readouterr().out
    assert verify._main([verify.Check("dirty", "touch new")], quick=False) == 0
    result = json.loads((root / "out" / "verify.json").read_text())
    assert result["worktree_clean"] is False
    assert "WARNING: the worktree has changes" in capsys.readouterr().out


def test_a_second_run_in_the_same_checkout_stops(root, monkeypatch, capsys):
    monkeypatch.setattr(
        verify, "checks", lambda jobs=None: [verify.Check("ok", "true", quick=True)]
    )
    (root / "out").mkdir()
    with (root / "out" / "verify.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert verify.main(["--quick"]) == 2
    assert "another scripts/verify runs" in capsys.readouterr().err
    assert verify.main(["--quick"]) == 0


def test_preflight_failure_stops_verify(root, monkeypatch):
    monkeypatch.setattr(verify.preflight, "check", lambda: 2)
    assert verify.main(["--quick"]) == 2
    assert not (root / "out" / "verify-quick.json").exists()
