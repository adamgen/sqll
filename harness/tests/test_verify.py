"""scripts/verify must run each check of CI (harness/sqll_harness/verify.py).

If CI gets a new step, add a check for it to verify.checks(), or add it to
verify.CI_ONLY if it is CI mechanics only (with its run text in
verify.CI_ONLY_RUN).
"""

import copy
import dataclasses
import fcntl
import json
import os
import subprocess

import pytest

from sqll_harness import cli, verify

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


def _bench_smoke(data):
    return _step(data, "bench-smoke", "Run the smoke benchmark")


def _bench_shard(data):
    return _step(data, "bench-full", "Run the benchmark shard")


def _without_step(data, job: str, name: str) -> None:
    steps = data["jobs"][job]["steps"]
    steps.remove(_step(data, job, name))


BASELINE_STEP = "Check the smoke report against the baseline"
MERGE_CHECK = "Check the merged report against the baseline"


def _merge_check_run(d, old: str, new: str):
    step = _step(d, "bench-merge", MERGE_CHECK)
    step["run"] = step["run"].replace(old, new)


CI_CHANGES = {
    "no baseline check step": lambda d: _without_step(d, "bench-smoke", BASELINE_STEP),
    "baseline check of a smoke run without --baseline": lambda d: _step(
        d, "bench-smoke", BASELINE_STEP
    ).update(
        run=_step(d, "bench-smoke", BASELINE_STEP)["run"].replace(
            " --baseline results/s2/baseline.json", ""
        )
    ),
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
        EVENT="pull_request"
    ),
    "changes outputs full forced false": lambda d: d["jobs"]["changes"][
        "outputs"
    ].update(full="false"),
    "changes outputs removed": lambda d: d["jobs"]["changes"].pop("outputs"),
    "changes step id renamed": lambda d: _step(d, "changes", "Changed files").update(
        id="files"
    ),
    "new step id": lambda d: _unit(d).update(id="unit"),
    "image outputs changed": lambda d: d["jobs"]["image"]["outputs"].update(
        matrix="{}"
    ),
    "test job if back to == 'true'": lambda d: d["jobs"]["test"].update(
        {"if": "needs.changes.outputs.full == 'true'"}
    ),
    "test job continue-on-error": lambda d: d["jobs"]["test"].update(
        {"continue-on-error": True}
    ),
    "report job services": lambda d: d["jobs"]["report"].update(
        services={"db": {"image": "x"}}
    ),
    "if on a check step": lambda d: _step(
        d, "report", "Check the recorded summary"
    ).update({"if": "false"}),
    "if on a CI_ONLY step": lambda d: _step(d, "report", "Merge").update(
        {"if": "false"}
    ),
    "changed step if": lambda d: _step(d, "report", "Check test jobs").update(
        {"if": "false"}
    ),
    "removed step if": lambda d: d["jobs"]["test"]["steps"][-1].pop("if"),
    "pull_request paths-ignore": lambda d: d[True].update(
        pull_request={"paths-ignore": ["**.md"]}
    ),
    "push paths": lambda d: d[True]["push"].update(paths=["docs/**"]),
    "push trigger removed": lambda d: d[True].pop("push"),
    "cancel-in-progress on push": lambda d: d["concurrency"].update(
        {"cancel-in-progress": True}
    ),
    "concurrency removed": lambda d: d.pop("concurrency"),
    "new workflow key": lambda d: d.update({"run-name": "x"}),
    "test needs only image": lambda d: d["jobs"]["test"].update(needs="image"),
    "dialect-oracle needs only image": lambda d: d["jobs"]["dialect-oracle"].update(
        needs=["image"]
    ),
    "lint needs changes": lambda d: d["jobs"]["lint"].update(
        needs=["changes", "image"]
    ),
    "needs on the changes job": lambda d: d["jobs"]["changes"].update(needs="image"),
    # The benchmark jobs.
    "smoke benchmark with the full profile": lambda d: _bench_smoke(d).update(
        run=_bench_smoke(d)["run"].replace("smoke", "full")
    ),
    "smoke benchmark of one dialect": lambda d: _bench_smoke(d).update(
        run=_bench_smoke(d)["run"] + " --dialect ansi"
    ),
    "smoke benchmark || true": lambda d: _bench_smoke(d).update(
        run=_bench_smoke(d)["run"] + " || true"
    ),
    "new benchmark step with no check": lambda d: d["jobs"]["bench-smoke"][
        "steps"
    ].insert(3, {"name": "Compare", "run": "uv run sqll-harness bench compare"}),
    "new unnamed benchmark step": lambda d: d["jobs"]["bench-full"]["steps"].append(
        {"run": "scripts/check-submodule x"}
    ),
    "submodule check removed from bench-full": lambda d: d["jobs"]["bench-full"][
        "steps"
    ].pop(3),
    "smoke submodule check text": lambda d: _step(
        d, "bench-smoke", "Check that the sqlfluff submodule is clean"
    ).update(run='scripts/check-submodule "after the tests"'),
    "bench-smoke runs on a docs-only pull request": lambda d: d["jobs"][
        "bench-smoke"
    ].pop("if"),
    "bench-smoke needs only image": lambda d: d["jobs"]["bench-smoke"].update(
        needs=["image"]
    ),
    "bench-full runs on each pull request": lambda d: d["jobs"]["bench-full"].pop("if"),
    "bench-full only on push": lambda d: d["jobs"]["bench-full"].update(
        {"if": "github.event_name == 'push'"}
    ),
    "bench-full needs changes": lambda d: d["jobs"]["bench-full"].update(
        needs=["changes", "image"]
    ),
    "bench-full continue-on-error": lambda d: d["jobs"]["bench-full"].update(
        {"continue-on-error": True}
    ),
    "bench-full shard of the smoke profile": lambda d: _bench_shard(d).update(
        run=_bench_shard(d)["run"].replace("--profile full", "--profile smoke")
    ),
    "bench-full shard of one size": lambda d: _bench_shard(d).update(
        run=_bench_shard(d)["run"] + " --size large"
    ),
    "bench-full shard with env": lambda d: _bench_shard(d).update(
        env={"SQLL_TOOLS_DIR": "/x"}
    ),
    "bench-full shard step continue-on-error": lambda d: _bench_shard(d).update(
        {"continue-on-error": True}
    ),
    "bench-full shard step if": lambda d: _bench_shard(d).update({"if": "false"}),
    "bench-full upload if removed": lambda d: d["jobs"]["bench-full"]["steps"][-1].pop(
        "if"
    ),
    "bench-smoke upload of no file is not an error": lambda d: d["jobs"]["bench-smoke"][
        "steps"
    ][-1]["with"].update({"if-no-files-found": "warn"}),
    "bench-merge upload with no if-no-files-found": lambda d: d["jobs"]["bench-merge"][
        "steps"
    ][-1]["with"].pop("if-no-files-found"),
    "bench-merge does not need bench-full": lambda d: d["jobs"]["bench-merge"].update(
        needs=["image"]
    ),
    "bench-merge always": lambda d: d["jobs"]["bench-merge"].update(
        {"if": "always() && github.event_name != 'pull_request'"}
    ),
    "bench-merge without --expect": lambda d: _step(d, "bench-merge", "Merge").update(
        run=_step(d, "bench-merge", "Merge")["run"].replace(
            "--expect ci/bench-matrix.json ", ""
        )
    ),
    "bench-merge check removed": lambda d: d["jobs"]["bench-merge"]["steps"].pop(3),
    "bench-merge check || true": lambda d: _step(d, "bench-merge", MERGE_CHECK).update(
        run=_step(d, "bench-merge", MERGE_CHECK)["run"] + "||true"
    ),
    "bench-merge check without --baseline": lambda d: _merge_check_run(
        d, " --baseline results/s2/baseline.json", ""
    ),
    "bench-merge check without --full": lambda d: _merge_check_run(d, " --full", ""),
    "bench-merge check of another baseline": lambda d: _merge_check_run(
        d, "results/s2/baseline.json", "out/bench.json"
    ),
    "bench-merge check of a shard": lambda d: _merge_check_run(
        d, " out/bench.json ", " out/bench-shards/x.json "
    ),
    "bench_matrix output changed": lambda d: d["jobs"]["image"]["outputs"].update(
        bench_matrix='{"include": [{"shard": "1/1", "name": "x"}]}'
    ),
    "bench_matrix line removed from the tag step": lambda d: next(
        s for s in d["jobs"]["image"]["steps"] if s.get("id") == "tag"
    ).update(
        run=next(s for s in d["jobs"]["image"]["steps"] if s.get("id") == "tag")[
            "run"
        ].split('echo "bench_matrix')[0]
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
    "smoke benchmark of one dialect": ("bench-smoke", lambda c: c + " --dialect ansi"),
    "smoke benchmark || true": ("bench-smoke", lambda c: c + " || true"),
    "smoke benchmark full profile": (
        "bench-smoke",
        lambda c: c.replace("--profile smoke", "--profile full"),
    ),
    "baseline check of another file": (
        "bench-baseline",
        lambda c: c.replace("results/s2/baseline.json", "out/bench.json"),
    ),
    "no baseline check": (
        "bench-baseline",
        lambda c: c.replace(" --baseline results/s2/baseline.json", ""),
    ),
    "submodule check after the benchmarks": (
        "submodule-after-bench",
        lambda c: c.replace("benchmarks", "tests"),
    ),
    "full benchmark of one size": ("bench-full", lambda c: c + " --size large"),
    "full benchmark with the smoke profile": (
        "bench-full",
        lambda c: c.replace("--profile full", "--profile smoke"),
    ),
    "full baseline check without --full": (
        "bench-full-baseline",
        lambda c: c.replace(" --full", ""),
    ),
    "full baseline check without --baseline": (
        "bench-full-baseline",
        lambda c: c.replace(" --baseline results/s2/baseline.json", ""),
    ),
    "full baseline check of the smoke report": (
        "bench-full-baseline",
        lambda c: c.replace("out/bench-full.json", "out/bench.json"),
    ),
    "submodule check after the full benchmark": (
        "submodule-after-full-bench",
        lambda c: c.replace("benchmarks", "tests"),
    ),
}


@pytest.mark.parametrize("name", LOCAL_CHANGES)
def test_drift_finds_a_local_change(name):
    target, change = LOCAL_CHANGES[name]
    changed = [
        dataclasses.replace(c, command=change(c.command)) if c.name == target else c
        for c in CHECKS
    ]
    assert verify.drift(changed, CI)


BENCH = (verify.REPO_ROOT / verify.BENCH_LOCAL).read_text()
BENCH_RUN = 'uv run --quiet --frozen --project harness sqll-harness bench run "$@"'

BENCH_CHANGES = {
    "--size small": lambda t: t.replace(BENCH_RUN, BENCH_RUN + " --size small"),
    "--profile smoke": lambda t: t.replace('run "$@"', 'run --profile smoke "$@"'),
    "no $@": lambda t: t.replace('run "$@"', "run"),
    "--tool sqruff": lambda t: t.replace("bench run", "bench run --tool sqruff"),
    "a second bench run": lambda t: t + "\n" + BENCH_RUN + "\n",
    "no bench run": lambda t: t.replace(BENCH_RUN, "true"),
    "other project": lambda t: t.replace(
        "--project harness sqll-harness bench run", "--project x sqll-harness bench run"
    ),
}


def test_bench_has_the_expected_run_line():
    assert BENCH.count(BENCH_RUN) == 1
    assert verify.bench_local_drift(CI, BENCH) == []


@pytest.mark.parametrize("name", BENCH_CHANGES)
def test_drift_finds_a_change_of_the_local_full_benchmark(name):
    changed = BENCH_CHANGES[name](BENCH)
    assert changed != BENCH
    assert verify.drift(CHECKS, CI, changed)


def test_bench_local_words_ignore_comments():
    text = "# don't run 'sqll-harness bench run' here\n" + BENCH_RUN + " || s=$?\n"
    assert verify.bench_local_words(text) == tuple(
        "uv run --frozen --project harness sqll-harness bench run".split()
    )


def test_the_local_full_benchmark_is_the_full_profile():
    args = cli._parser().parse_args(["bench", "run"])
    assert args.profile == "full"
    assert args.tool is None and args.dialect is None and args.size is None
    assert args.bench_commands is None and args.shard is None


def test_no_ci_step_can_hide_a_failure():
    text = verify.CI_FILE.read_text()
    assert "continue-on-error" not in text
    for key, step, _ in verify.ci_steps(CI):
        assert verify.ci_weak_parts(step.get("run", "")) == [], key


def test_drift_finds_weak_ci_text():
    def change(d):
        step = next(s for s in d["jobs"]["image"]["steps"] if s.get("id") == "find")
        step["run"] = step["run"].replace("> /dev/null 2>&1", "|| :")
        step["run"] = step["run"].replace(
            '"$GITHUB_OUTPUT"\nfi', '"$GITHUB_OUTPUT"; true\nfi'
        )

    problems = _ci_change(change)
    assert "image: find: '||' in the CI run text can hide a failure" in problems
    assert "image: find: ':' in the CI run text can hide a failure" in problems
    assert "image: find: 'true' in the CI run text can hide a failure" in problems


def test_weak_words_after_an_operator_are_found():
    assert verify.weak_parts("scripts/setup; true") == ["true"]
    assert verify.weak_parts("scripts/setup &&:") == [":"]
    assert verify.ci_weak_parts("a;true") == ["true"]
    assert verify.ci_weak_parts("echo 'a || b'") == ["||"]


@pytest.mark.parametrize(
    "run, found",
    [
        ("exit 1", []),
        ('echo "x"\nexit 2', []),
        ("echo 'exit 0'", []),
        ("exit 0", ["exit 0"]),
        ("exit", ["exit"]),
        ("a\nexit", ["exit"]),
        ("a; exit 0", ["exit 0"]),
        ('exit "$s"', ["exit $s"]),
        ("exit -1", ["exit -1"]),
    ],
)
def test_ci_exit_must_be_a_failure(run, found):
    assert verify.ci_weak_parts(run) == found


def test_each_upload_fails_if_a_file_is_missing():
    uploads = [
        key
        for key, step, _ in verify.ci_steps(CI)
        if str(step.get("uses", "")).startswith(verify.UPLOAD)
    ]
    assert len(uploads) == 6
    for job in ("bench-smoke", "bench-full", "bench-merge"):
        assert f"{job}: actions/upload-artifact" in uploads

    def change(d):
        d["jobs"]["bench-full"]["steps"][-1]["with"]["if-no-files-found"] = "ignore"

    assert _ci_change(change) == [
        "bench-full: actions/upload-artifact: an upload needs"
        " 'if-no-files-found: error'"
    ]


def test_drift_finds_an_exit_0_in_a_ci_step():
    def change(d):
        step = _step(d, "bench-merge", MERGE_CHECK)
        step["run"] = "exit 0\n" + step["run"]

    problems = _ci_change(change)
    assert (
        f"bench-merge: {MERGE_CHECK}: 'exit 0' in the CI run text can hide a failure"
    ) in problems


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


def test_only_the_unsharded_runs_have_a_ci_diff():
    assert [c.name for c in CHECKS if c.ci_diff] == [
        "run",
        "bench-full",
        "bench-full-baseline",
    ]


def test_the_full_benchmark_checks_are_last_and_only_in_full_bench():
    full = [c.name for c in CHECKS if c.full_bench]
    assert full == ["bench-full", "submodule-after-full-bench", "bench-full-baseline"]
    assert [c.name for c in CHECKS[-3:]] == full
    assert not any(c.quick for c in CHECKS if c.full_bench)


def _listed(capsys, *args) -> list[str]:
    assert verify.main(["--list", *args]) == 0
    return [line.split(":")[0] for line in capsys.readouterr().out.splitlines()]


def test_full_bench_adds_the_full_benchmark_to_the_full_verification(capsys):
    names = [c.name for c in CHECKS]
    assert _listed(capsys) == names[:-3]
    assert _listed(capsys, "--full-bench") == names
    assert _listed(capsys, "--quick") == [c.name for c in CHECKS if c.quick]


def test_quick_and_full_bench_cannot_be_used_together(capsys):
    with pytest.raises(SystemExit) as exc:
        verify.main(["--quick", "--full-bench"])
    assert exc.value.code == 2
    assert "cannot be used together" in capsys.readouterr().err


def test_the_reports_of_the_checks():
    reports = {c.name: c.report for c in CHECKS if c.report}
    assert reports == {
        "run": "out/report.json",
        "bench-smoke": "out/bench.json",
        "bench-full": "out/bench-full.json",
    }


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
    # verify.main() sets SQLL_TOOLS_DIR if it is not set. The test must not
    # give that value (a tmp_path folder) to the tests that run after it.
    # setenv records the old state (also "not set"); the teardown restores it.
    old = os.environ.get("SQLL_TOOLS_DIR")
    monkeypatch.setenv("SQLL_TOOLS_DIR", old or "")
    if old is None:
        monkeypatch.delenv("SQLL_TOOLS_DIR")
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


def test_full_bench_result_names_the_reports(root, capsys):
    selected = [
        verify.Check("run", "echo {} > out/report.json", report="out/report.json"),
        verify.Check("smoke", "echo {} > out/bench.json", report="out/bench.json"),
        verify.Check("full", "false", report="out/bench-full.json"),
        verify.Check("check", "true"),
    ]
    (root / "out").mkdir()
    assert verify._main(selected, quick=False, full_bench=True) == 1
    result = json.loads((root / "out" / "verify-full-bench.json").read_text())
    assert (result["mode"], result["full_benchmark"]) == ("full-bench", True)
    assert result["full_verification"] is True
    assert result["reports"] == {"run": "out/report.json", "smoke": "out/bench.json"}
    assert (root / "out" / "verify-full-bench" / "full.log").exists()
    assert not (root / "out" / "verify.json").exists()


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
