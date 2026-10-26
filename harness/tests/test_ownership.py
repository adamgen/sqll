"""Tests for the track ownership check: tracks.yml, ci/ownership.py, and
.github/workflows/ownership.yml (PROCESS.md, "Tracks")."""

import json
import subprocess

import pytest
import yaml
from conftest import ci_module

from sqll_harness import verify
from sqll_harness.paths import REPO_ROOT

ownership = ci_module("ownership")
TRACKS = ownership.load()
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ownership.yml"


def _tracked_files() -> list[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()


@pytest.mark.parametrize(
    "pattern, path, want",
    [
        ("ci/**", "ci/matrix.d/S9.json", True),
        ("ci/**", "ci", True),
        ("ci/**", "cix/a", False),
        ("ci/*", "ci/a/b", False),
        ("*.md", "status/S1.md", False),
        ("status/S1.md", "status/S1.md", True),
        ("harness/tests/test_s3_*.py", "harness/tests/test_s3_a.py", True),
        ("harness/tests/test_s3_*.py", "harness/tests/test_s30.py", False),
        ("a/**/b", "a/b", True),
        ("a/**/b", "a/x/y/b", True),
        ("claude/s9-*", "claude/s9-corpus", True),
        ("claude/s9-*", "claude/s9", False),
    ],
)
def test_matches(pattern, path, want):
    assert ownership.matches(pattern, path) is want


# tracks.yml


def test_tracks_file_has_the_tracks():
    assert {"core", "S3", "S7-tests", "S9"} <= set(TRACKS)
    for later in ("S4", "S5", "S6", "S7-sqll", "S8", "S10"):
        assert later in TRACKS


def test_core_owns_the_shared_files():
    for path in (
        "PROCESS.md",
        "STONES.md",
        "CONSTITUTION.md",
        "STATUS.md",
        "tracks.yml",
        "ci/ownership.py",
        "ci/matrix.d/core.json",
        ".github/workflows/ci.yml",
        "scripts/verify",
        "harness/sqll_harness/verify.py",
        "status/S1.md",
        "status/S2.md",
        "results/s1/summary.json",
    ):
        assert ownership.owner(path, TRACKS) == "core", path


def test_each_track_owns_its_hot_files():
    for name in TRACKS:
        if name == ownership.CORE:
            continue
        for path in (
            f"status/{name}.md",
            f"ci/matrix.d/{name}.json",
            f"results/{name}/x.json",
        ):
            assert ownership.owner(path, TRACKS) == name, path


def test_s3_owns_its_work_paths():
    for path in (
        "status/S3.md",
        "docs/decisions/s3-base.md",
        "results/s3/s1-by-base.json",
        "scripts/s3/s1_by_base.py",
        "harness/tests/test_s3_s1_by_base.py",
    ):
        assert ownership.owner(path, TRACKS) == "S3", path


def test_no_path_has_two_owners():
    # A sample path for each pattern ("*" and "**" become "x"), and each
    # tracked file. owner() raises TracksError if two tracks own a path.
    samples = set(_tracked_files())
    for track in TRACKS.values():
        for pattern in track["paths"]:
            samples.add(pattern.replace("**", "x").replace("*", "x"))
    for path in sorted(samples):
        ownership.owner(path, TRACKS)


def test_no_branch_is_in_two_tracks():
    samples = {"claude/protocol-tracks", "main"}
    for track in TRACKS.values():
        for pattern in track["branches"]:
            samples.add(pattern.replace("*", "x"))
    for branch in sorted(samples):
        ownership.track_of_branch(branch, TRACKS)


@pytest.mark.parametrize(
    "branch, want",
    [
        ("claude/laughing-clarke-jkf7w5", ("S3", True)),
        ("claude/s3-t2", ("S3", True)),
        ("claude/s9-corpus", ("S9", True)),
        ("claude/s7-tests", ("S7-tests", True)),
        ("claude/s7-sqll-cli", ("S7-sqll", True)),
        ("claude/s3b-tree", ("core", True)),
        ("claude/s10", ("S10", True)),
        ("claude/protocol-tracks", ("core", False)),
        ("feature/x", ("core", False)),
    ],
)
def test_track_of_branch(branch, want):
    assert ownership.track_of_branch(branch, TRACKS) == want


def test_a_branch_in_two_tracks_is_an_error():
    tracks = {
        "core": {"branches": ["claude/*"], "paths": []},
        "A": {"branches": ["claude/a"], "paths": []},
    }
    with pytest.raises(ownership.TracksError, match="in the tracks core, A"):
        ownership.track_of_branch("claude/a", tracks)


def test_a_path_of_two_tracks_is_an_error():
    tracks = {
        "core": {"branches": [], "paths": []},
        "A": {"branches": [], "paths": ["x/**"]},
        "B": {"branches": [], "paths": ["x/b/*"]},
    }
    assert ownership.owner("x/a", tracks) == "A"
    with pytest.raises(ownership.TracksError, match="owned by the tracks A, B"):
        ownership.owner("x/b/c", tracks)


@pytest.mark.parametrize(
    "data",
    [
        None,
        {"tracks": []},
        {"tracks": {"S3": {"branches": [], "paths": []}}},
        {"tracks": {"core": {"branches": "claude/core", "paths": []}}},
        {"tracks": {"core": {"branches": [], "paths": [""]}}},
        {"tracks": {"core": {"branches": []}}},
    ],
)
def test_validate_rejects_a_bad_tracks_file(data):
    with pytest.raises(ownership.TracksError):
        ownership.validate(data)


def test_load_rejects_a_file_that_is_not_yaml(tmp_path):
    path = tmp_path / "tracks.yml"
    path.write_text("tracks: [")
    with pytest.raises(ownership.TracksError, match="cannot read"):
        ownership.load(path)


# The check


def test_a_track_can_change_its_paths_and_paths_with_no_owner():
    ok, text = ownership.check(
        "claude/s9-corpus",
        [],
        ["corpus/a.sql", "status/S9.md", "ci/matrix.d/S9.json", "new/x"],
        TRACKS,
    )
    assert ok
    assert "- new/x: no owner" in text
    assert text[-1].startswith("Result: pass.")


def test_a_change_of_a_path_of_another_track_fails():
    ok, text = ownership.check(
        "claude/s9-corpus", [], ["corpus/a.sql", "PROCESS.md", "status/S3.md"], TRACKS
    )
    assert not ok
    assert "- PROCESS.md: owned by core (another track)" in text
    assert "- status/S3.md: owned by S3 (another track)" in text
    assert text[-1].startswith("Result: fail.")
    assert "the tracks S3, core." in text[-1]


def test_the_cross_track_label_lets_the_change_pass():
    ok, text = ownership.check(
        "claude/s9-corpus", ["other", "cross-track"], ["PROCESS.md"], TRACKS
    )
    assert ok
    assert text[-1] == (
        "Result: pass with the label 'cross-track'. These tracks must review"
        " the pull request: core."
    )


def test_an_unknown_branch_gets_the_core_rules():
    paths = ["PROCESS.md", "tracks.yml", "ci/ownership.py", "status/S2.md"]
    ok, text = ownership.check("claude/protocol-tracks", [], paths, TRACKS)
    assert ok
    assert "Core track rules" in text[0]
    ok, _ = ownership.check("claude/protocol-tracks", [], ["status/S3.md"], TRACKS)
    assert not ok


def test_a_track_cannot_change_core_files():
    for path in (
        ".github/workflows/ci.yml",
        "harness/sqll_harness/verify.py",
        "ci/matrix.d/core.json",
    ):
        ok, _ = ownership.check("claude/laughing-clarke-jkf7w5", [], [path], TRACKS)
        assert not ok, path


# main()


def _main(monkeypatch, tmp_path, paths, branch="claude/s9", labels="[]"):
    monkeypatch.setattr(ownership, "changed_files", lambda event: paths)
    monkeypatch.setattr(ownership, "rule_sets", lambda: [("a test", TRACKS)])
    monkeypatch.setenv("BRANCH", branch)
    monkeypatch.setenv("LABELS", labels)
    monkeypatch.delenv("REPO", raising=False)
    monkeypatch.delenv("HEAD_REPO", raising=False)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    code = ownership.main(["pull_request"])
    return code, summary.read_text()


def test_main_passes(monkeypatch, tmp_path, capsys):
    code, summary = _main(monkeypatch, tmp_path, ["status/S9.md"])
    assert code == 0
    assert "Result: pass." in summary
    assert "Result: pass." in capsys.readouterr().out


def test_main_fails_on_a_file_of_another_track(monkeypatch, tmp_path):
    code, summary = _main(monkeypatch, tmp_path, ["STONES.md"])
    assert code == 1
    assert "Result: fail." in summary


def test_main_reads_the_labels(monkeypatch, tmp_path):
    labels = json.dumps(["cross-track"])
    code, _ = _main(monkeypatch, tmp_path, ["STONES.md"], labels=labels)
    assert code == 0


@pytest.mark.parametrize(
    "paths, branch, labels",
    [
        (None, "claude/s9", "[]"),
        (["x"], "", "[]"),
        (["x"], "claude/s9", "{}"),
        (["x"], "claude/s9", "not json"),
    ],
)
def test_main_fails_closed(monkeypatch, tmp_path, paths, branch, labels):
    code, summary = _main(monkeypatch, tmp_path, paths, branch, labels)
    assert code == 1
    assert "error:" in summary


def test_main_does_nothing_on_another_event(capsys):
    assert ownership.main(["push"]) == 0
    assert "not a pull request" in capsys.readouterr().out


def test_a_fork_gets_no_track():
    ok, text = ownership.check("claude/core", [], ["new/x"], TRACKS, fork=True)
    assert ok
    assert text[0] == "Branch claude/core of a fork: no track."
    for path in ("PROCESS.md", "status/S9.md"):
        ok, text = ownership.check("claude/core", [], [path], TRACKS, fork=True)
        assert not ok, path
    ok, _ = ownership.check(
        "claude/core", ["cross-track"], ["PROCESS.md"], TRACKS, fork=True
    )
    assert ok


def test_main_gives_a_fork_no_track(monkeypatch, tmp_path):
    monkeypatch.setenv("REPO", "adamgen/sqll")
    for head_repo, want in (("adamgen/sqll", 0), ("x/sqll", 1), ("", 1)):
        monkeypatch.setattr(ownership, "changed_files", lambda event: ["PROCESS.md"])
        monkeypatch.setattr(ownership, "rule_sets", lambda: [("a test", TRACKS)])
        monkeypatch.setenv("BRANCH", "claude/core")
        monkeypatch.setenv("LABELS", "[]")
        monkeypatch.setenv("HEAD_REPO", head_repo)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        assert ownership.main(["pull_request"]) == want, head_repo


# The rules come from the tracks.yml of the base (a merge commit as on GitHub)


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _write(repo, files):
    for path, text in files.items():
        if text is None:
            _git(repo, "rm", "-q", path)
            continue
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c")


TRACKS_TEXT = (REPO_ROOT / "tracks.yml").read_text(encoding="utf8")


def _pull_request(tmp_path, monkeypatch, base, change, branch, labels="[]"):
    """Make a merge commit of a pull request as GitHub does. base and
    change: {path: text, or None to delete}. Return the code and the text
    of main()."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, {"README": "x", **base})
    _git(repo, "checkout", "-q", "-b", "pr")
    _write(repo, change)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "pr", "-m", "merge")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("BRANCH", branch)
    monkeypatch.setenv("LABELS", labels)
    monkeypatch.delenv("REPO", raising=False)
    monkeypatch.delenv("HEAD_REPO", raising=False)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    code = ownership.main(["pull_request"])
    return code, summary.read_text(encoding="utf8")


def _grant_s9(paths):
    """tracks.yml with more paths for the S9 track."""
    old = "      - harness/tests/test_s9_*.py\n"
    assert old in TRACKS_TEXT
    return TRACKS_TEXT.replace(old, old + "".join(f"      - {p}\n" for p in paths))


def test_a_pull_request_cannot_give_its_track_core_paths(tmp_path, monkeypatch):
    grant = _grant_s9(["tracks.yml", ".github/**", "PROCESS.md"])
    assert ownership.owner("PROCESS.md", ownership.parse(grant, "t")) == "S9"
    code, text = _pull_request(
        tmp_path,
        monkeypatch,
        {"tracks.yml": TRACKS_TEXT, "PROCESS.md": "a", ".github/workflows/ci.yml": ""},
        {"tracks.yml": grant, "PROCESS.md": "b", ".github/workflows/ci.yml": "b"},
        "claude/s9-z",
    )
    assert code == 1
    assert "Rules: the tracks.yml of the base " in text
    assert "- PROCESS.md: owned by core (another track)" in text
    assert "- tracks.yml: owned by core (another track)" in text
    assert "Rules: the tracks.yml of the pull request (it changes tracks.yml)" in text
    assert text.rstrip().endswith("Result: fail.")


def test_a_core_change_of_tracks_yml_uses_both_files(tmp_path, monkeypatch):
    base = {"tracks.yml": TRACKS_TEXT, "harness/x.py": "a"}
    grant = _grant_s9(["harness/x.py"])
    # Core gives harness/x.py to S9 and does not change it: pass.
    code, text = _pull_request(
        tmp_path, monkeypatch, base, {"tracks.yml": grant}, "claude/core"
    )
    assert code == 0, text
    assert text.count("Rules: ") == 2


def test_a_core_change_of_a_path_that_it_gives_away_needs_the_label(
    tmp_path, monkeypatch
):
    base = {"tracks.yml": TRACKS_TEXT, "harness/x.py": "a"}
    change = {"tracks.yml": _grant_s9(["harness/x.py"]), "harness/x.py": "b"}
    code, text = _pull_request(tmp_path, monkeypatch, base, change, "claude/core")
    assert code == 1
    assert "- harness/x.py: owned by S9 (another track)" in text


def test_the_base_rules_apply_when_tracks_yml_does_not_change(tmp_path, monkeypatch):
    base = {"tracks.yml": TRACKS_TEXT, "status/S3.md": "a"}
    code, text = _pull_request(
        tmp_path, monkeypatch, base, {"status/S3.md": "b"}, "claude/s9-z"
    )
    assert code == 1
    assert text.count("Rules: ") == 1
    (tmp_path / "s3").mkdir()
    code, _ = _pull_request(
        tmp_path / "s3", monkeypatch, base, {"status/S3.md": "b"}, "claude/s3-z"
    )
    assert code == 0


def test_the_pull_request_that_adds_tracks_yml_uses_its_own(tmp_path, monkeypatch):
    code, text = _pull_request(
        tmp_path, monkeypatch, {}, {"tracks.yml": TRACKS_TEXT}, "claude/core"
    )
    assert code == 0, text
    assert "Rules: the tracks.yml of the pull request (the base has no" in text


def test_a_pull_request_that_deletes_tracks_yml_fails(tmp_path, monkeypatch):
    code, text = _pull_request(
        tmp_path,
        monkeypatch,
        {"tracks.yml": TRACKS_TEXT},
        {"tracks.yml": None},
        "claude/core",
    )
    assert code == 1
    assert "error: the pull request has no tracks.yml" in text


def test_a_bad_tracks_yml_in_the_pull_request_fails(tmp_path, monkeypatch):
    code, text = _pull_request(
        tmp_path,
        monkeypatch,
        {"tracks.yml": TRACKS_TEXT},
        {"tracks.yml": "x: ["},
        "claude/core",
    )
    assert code == 1
    assert "error: HEAD:tracks.yml: cannot read" in text


def test_a_non_ascii_path_has_its_owner(tmp_path, monkeypatch):
    code, text = _pull_request(
        tmp_path,
        monkeypatch,
        {"tracks.yml": TRACKS_TEXT},
        {"corpus/\u00e9.sql": "select 1"},
        "claude/s7-tests-q",
    )
    assert code == 1
    assert "- corpus/\u00e9.sql: owned by S9 (another track)" in text


# .github/workflows/ownership.yml


def test_the_workflow_runs_the_check_on_each_pull_request_change():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf8"))
    assert data[True] == {
        "pull_request": {
            "types": ["opened", "synchronize", "reopened", "labeled", "unlabeled"]
        }
    }
    (job,) = data["jobs"].values()
    assert "if" not in job and "continue-on-error" not in job
    checkout, step = job["steps"]
    assert checkout["uses"] == "actions/checkout@v7"
    assert checkout["with"] == {"fetch-depth": 0}
    assert step["run"] == 'python3 ci/ownership.py "$EVENT"'
    assert step["env"] == {
        "EVENT": "${{ github.event_name }}",
        "BRANCH": "${{ github.head_ref }}",
        "LABELS": "${{ toJSON(github.event.pull_request.labels.*.name) }}",
        "REPO": "${{ github.repository }}",
        "HEAD_REPO": "${{ github.event.pull_request.head.repo.full_name }}",
    }
    assert set(step) == {"name", "env", "run"}
    assert verify.ci_weak_parts(step["run"]) == []
