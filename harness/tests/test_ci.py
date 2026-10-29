"""Tests for the CI scripts in ci/: the image tag and the test matrix."""

import json
import re
import shlex
import subprocess

import pytest
from conftest import ci_module

from sqll_harness import merge
from sqll_harness.adapters import ADAPTERS
from sqll_harness.paths import REPO_ROOT
from sqll_harness.suites import SUITES, runs_for

_load = ci_module
image_tag = _load("image_tag")
matrix = _load("matrix")
ownership = _load("ownership")
MATRIX_DIR = REPO_ROOT / "ci" / "matrix.d"


def test_tag_is_stable_and_short():
    entries = image_tag.read_inputs()
    tag = image_tag.compute(entries)
    assert tag == image_tag.compute(dict(reversed(entries.items())))
    assert re.fullmatch(r"[0-9a-f]{20}", tag)


def test_each_input_change_changes_the_tag():
    entries = image_tag.read_inputs()
    base = image_tag.compute(entries)
    for path, (content, executable) in entries.items():
        variants = [
            {**entries, path: (content + b"\n", executable)},
            {**entries, path: (content, not executable)},
            {k: v for k, v in entries.items() if k != path},
        ]
        for variant in variants:
            assert image_tag.compute(variant) != base, path
    assert image_tag.compute({**entries, "tools/new/uv.lock": (b"", False)}) != base


def test_rename_changes_the_tag():
    a = image_tag.compute({"tools/a": (b"x", False)})
    assert a != image_tag.compute({"tools/b": (b"x", False)})


def test_inputs_include_each_tool_file_and_the_uv_pin():
    files = image_tag.input_files()
    for name in (
        "ci/Dockerfile",
        "ci/uv-requirements.txt",
        "harness/uv.lock",
        "scripts/setup",
        "tools/sqlfluff/uv.lock",
        "tools/sqlfluff-rs/uv.lock",
        "tools/sqlfluff-rs-oracle/uv.lock",
        "tools/sqruff/uv.lock",
        "tools/sqruff/install.sh",
    ):
        assert name in files


def test_local_state_is_not_an_input(tmp_path):
    for rel in image_tag.INPUTS:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel == "tools":
            (path / "x" / ".venv").mkdir(parents=True)
            (path / "x" / ".venv" / "f").write_text("")
            (path / "x" / "__pycache__").mkdir()
            (path / "x" / "a.pyc").write_text("")
            (path / "x" / "uv.lock").write_text("")
        else:
            path.write_text("")
    files = image_tag.input_files(tmp_path)
    assert "tools/x/uv.lock" in files
    assert not [f for f in files if ".venv" in f or "pyc" in f]


def _covered(path):
    return any(
        path == i or path.startswith(i.rstrip("/") + "/") for i in image_tag.INPUTS
    )


def _dockerfile_lines():
    text = (REPO_ROOT / "ci" / "Dockerfile").read_text()
    return text.replace("\\\n", " ").splitlines()


def test_dockerfile_copies_only_inputs():
    sources = []
    for line in _dockerfile_lines():
        words = shlex.split(line)
        if words[:1] == ["COPY"] and not any(w.startswith("--from") for w in words):
            sources += [w for w in words[1:-1] if not w.startswith("--")]
    assert sources
    for src in sources:
        assert _covered(src.rstrip("/")), src


def test_dockerignore_allows_only_inputs():
    lines = (REPO_ROOT / ".dockerignore").read_text().splitlines()
    allowed = [x[1:].rstrip("/") for x in lines if x.startswith("!")]
    assert allowed
    for path in allowed:
        assert _covered(path), path


def test_base_images_are_pinned_by_digest():
    images = [
        line.split("=", 1)[1]
        for line in _dockerfile_lines()
        if line.startswith("ARG ") and "_IMAGE=" in line
    ]
    assert len(images) == 2
    for image in images:
        assert re.search(r":[0-9][^@]*@sha256:[0-9a-f]{64}$", image), image
    pin = (REPO_ROOT / "ci" / "uv-requirements.txt").read_text()
    assert re.search(r"^uv==[0-9.]+ \\\n +--hash=sha256:[0-9a-f]{64}$", pin, re.M)


def test_image_source_label():
    text = (REPO_ROOT / "ci" / "Dockerfile").read_text()
    assert "org.opencontainers.image.source=https://github.com/adamgen/sqll" in text


def test_matrix_expansion():
    got = matrix.expand([{"suite": "s", "tool": "t", "shards": 2}])
    assert got == {
        "include": [
            {"suite": "s", "tool": "t", "shard": "1/2", "name": "s-t-1-of-2"},
            {"suite": "s", "tool": "t", "shard": "2/2", "name": "s-t-2-of-2"},
        ]
    }


@pytest.mark.parametrize(
    "entries",
    [
        [{"suite": "s", "tool": "t", "shards": 0}],
        [{"suite": "s", "tool": "t", "shards": 1}] * 2,
    ],
)
def test_matrix_rejects_bad_entries(entries):
    with pytest.raises(ValueError):
        matrix.expand(entries)


def _fragment(folder, name, entries):
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(json.dumps(entries))


def test_matrix_merges_the_fragments_in_name_order(tmp_path, capsys):
    folder = tmp_path / "matrix.d"
    _fragment(folder, "b.json", [{"suite": "s", "tool": "b", "shards": 1}])
    _fragment(folder, "a.json", [{"suite": "s", "tool": "a", "shards": 2}])
    (folder / "README.txt").write_text("not a fragment")
    assert [e["tool"] for e in matrix.load(folder)] == ["a", "b"]
    assert matrix.main([str(folder)]) == 0
    names = [e["name"] for e in json.loads(capsys.readouterr().out)["include"]]
    assert names == ["s-a-1-of-2", "s-a-2-of-2", "s-b-1-of-1"]
    assert merge.load_expected(folder) == [("s", "a", 2), ("s", "b", 1)]


def test_matrix_rejects_an_entry_in_two_fragments(tmp_path):
    folder = tmp_path / "matrix.d"
    _fragment(folder, "a.json", [{"suite": "s", "tool": "t", "shards": 1}])
    _fragment(folder, "b.json", [{"suite": "s", "tool": "t", "shards": 2}])
    with pytest.raises(ValueError, match="two entries"):
        matrix.expand(matrix.load(folder))
    with pytest.raises(merge.MergeError, match="in two entries"):
        merge.load_expected(folder)


def test_matrix_rejects_an_empty_folder_or_a_bad_fragment(tmp_path):
    folder = tmp_path / "matrix.d"
    folder.mkdir()
    with pytest.raises(ValueError, match="no"):
        matrix.load(folder)
    with pytest.raises(merge.MergeError):
        merge.load_expected(folder)
    _fragment(folder, "a.json", {"suite": "s"})
    with pytest.raises(ValueError, match="not a list"):
        matrix.load(folder)
    with pytest.raises(merge.MergeError):
        merge.load_expected(folder)


def test_ci_matrix_fragments_are_of_tracks():
    names = {p.stem for p in MATRIX_DIR.glob("*.json")}
    assert "core" in names
    assert names <= set(ownership.load())
    assert not (REPO_ROOT / "ci" / "matrix.json").exists()


def test_the_report_job_expects_the_matrix_of_the_test_jobs():
    entries = matrix.load(MATRIX_DIR)
    want = [(e["suite"], e["tool"], int(e["shards"])) for e in entries]
    assert merge.load_expected(MATRIX_DIR) == want
    assert matrix.DEFAULT == MATRIX_DIR


def test_ci_matrix_names_real_suites_and_tools():
    entries = matrix.load(MATRIX_DIR)
    assert entries
    for e in entries:
        assert e["suite"] in SUITES
        assert e["tool"] in ADAPTERS
    assert matrix.expand(entries)["include"]


def test_ci_matrix_runs_each_suite_for_each_tool():
    entries = matrix.load(MATRIX_DIR)
    shards = {(e["suite"], e["tool"]): e["shards"] for e in entries}
    want = {
        (name, tool)
        for name, suite in SUITES.items()
        for tool in ADAPTERS
        if runs_for(suite, tool)
    }
    assert set(shards) == want
    for name, suite in SUITES.items():
        if runs_for(suite, "sqlfluff-rs"):
            assert shards[(name, "sqlfluff-rs")] == shards[(name, "sqlfluff")]
    assert ("code_only", "sqlfluff") in shards


bench_matrix = _load("bench_matrix")


def test_bench_matrix_expansion():
    assert bench_matrix.expand({"shards": 2}) == {
        "include": [
            {"shard": "1/2", "name": "1-of-2"},
            {"shard": "2/2", "name": "2-of-2"},
        ]
    }


@pytest.mark.parametrize(
    "data",
    [{"shards": 0}, {"shards": "2"}, {"shards": True}, {"shards": 2, "x": 1}, [2], {}],
)
def test_bench_matrix_rejects_bad_data(data):
    with pytest.raises(ValueError):
        bench_matrix.expand(data)


def test_ci_bench_matrix_has_a_dialect_in_each_shard():
    from sqll_harness.bench import definitions

    data = json.loads((REPO_ROOT / "ci" / "bench-matrix.json").read_text())
    dialects = {b["dialect"] for b in definitions.load()["benchmarks"]}
    include = bench_matrix.expand(data)["include"]
    assert 1 <= len(include) <= len(dialects)


corpus_matrix = _load("corpus_matrix")


def test_corpus_matrix_reads_the_s9_shard_file(capsys):
    assert corpus_matrix.DEFAULT == REPO_ROOT / "corpus" / "ci-shards.json"
    assert corpus_matrix.main([]) == 0
    data = json.loads(corpus_matrix.DEFAULT.read_text())
    assert json.loads(capsys.readouterr().out) == bench_matrix.expand(data)


def test_corpus_matrix_has_a_file_in_each_shard():
    from sqll_harness.corpus import manifest
    from sqll_harness.corpus import run as corpus_run

    files = manifest.load()
    n = corpus_run.expected_shards(corpus_matrix.DEFAULT)
    include = bench_matrix.expand({"shards": n})["include"]
    assert 2 <= len(include) <= len(files.files)
    for k in range(1, n + 1):
        assert corpus_run.select(files, "full", (k, n)), k


def test_corpus_matrix_refuses_bad_data(tmp_path):
    path = tmp_path / "shards.json"
    path.write_text('{"shards": 0}')
    with pytest.raises(ValueError):
        corpus_matrix.main([str(path)])


# ci/changes.py: the documents-only test

changes = _load("changes")

CODE_PATHS = (
    ".github/workflows/ci.yml",
    "third_party/sqlfluff",
    "harness/sqll_harness/verify.py",
    "harness/tests/test_ci.py",
    "harness/tests/fixtures/dialects/README.md",
    "harness/sqll_harness/x.md",
    "scripts/verify",
    "tools/sqruff/x.md",
    "ci/x.md",
    "known_failures/sqruff.txt",
    "results/s1/summary.json",
    "results/README.md",
    "status/S1/x.md",
    "status/x.json",
    "tracks.yml",
    "README.txt",
    "md",
    # The sqll Rust workspace (S3 T11).
    "Cargo.toml",
    "Cargo.lock",
    "rust-toolchain.toml",
    "crates/ported.json",
    "crates/LICENSE-sqlfluffrs.md",
    "crates/sqll_types/README.md",
    "crates/sqll_dialects/build.rs",
    "crates/sqll_dialects/generated.json",
    "scripts/build-sqll",
)


def test_documents_are_docs():
    for path in (
        "STATUS.md",
        "PROCESS.md",
        "harness/README.md",
        "status/S1.md",
        "new.md",
    ):
        assert changes.is_doc(path), path
    assert not changes.full_run(["STATUS.md", "harness/sqruff.md"])


@pytest.mark.parametrize("path", CODE_PATHS)
def test_other_paths_run_all_jobs(path):
    assert not changes.is_doc(path)
    assert changes.full_run(["STATUS.md", path])


def test_unknown_or_empty_change_runs_all_jobs():
    assert changes.full_run(None)
    assert changes.full_run([])


def test_tracked_docs_are_markdown_outside_the_code_folders():
    files = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    docs = [f for f in files if changes.is_doc(f)]
    assert "STATUS.md" in docs
    assert "status/S1.md" in docs
    for path in docs:
        assert path.endswith(".md"), path
        assert path.count("/") == 0 or path.startswith(("harness/", "status/")), path
        assert path.count("/") <= 1, path


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _commit(repo, path, text):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", path)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, "STATUS.md", "a")
    return tmp_path


def test_push_is_always_a_full_run(repo, tmp_path, monkeypatch):
    # Pushes A (code), B (code), C (docs only). GitHub can cancel the pending
    # run of B; then the run of C has github.event.before = B. The run of C
    # must not skip the full jobs.
    _commit(repo, "harness/a.py", "A")
    b = _commit(repo, "harness/x.py", "B")
    _commit(repo, "STATUS.md", "C")
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    for argv in (["push", b], ["push"], ["workflow_dispatch"]):
        assert changes.main(argv) == 0
    assert out.read_text() == "full=true\n" * 3
    for event in ("push", "workflow_dispatch", ""):
        assert changes.changed_files(event, cwd=str(repo)) is None


def test_pull_request_compares_the_merge_with_its_base(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "pr")
    _commit(repo, "harness/x.py", "code")
    _commit(repo, "STATUS.md", "doc")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "PROCESS.md", "main")
    _git(repo, "merge", "-q", "--no-ff", "pr", "-m", "merge")
    assert _git(repo, "rev-parse", "HEAD^1") != base
    files = changes.changed_files("pull_request", cwd=str(repo))
    assert sorted(files) == ["STATUS.md", "harness/x.py"]
    assert changes.full_run(files)


def _merge(repo, branch):
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", branch, "-m", "merge")


def test_a_rename_shows_both_paths(repo):
    _git(repo, "checkout", "-q", "-b", "pr")
    _git(repo, "mv", "STATUS.md", "x.py")
    _git(repo, "commit", "-qm", "mv")
    _merge(repo, "pr")
    files = changes.changed_files("pull_request", cwd=str(repo))
    assert sorted(files) == ["STATUS.md", "x.py"]


def test_docs_only_pull_request_skips(repo):
    _git(repo, "checkout", "-q", "-b", "pr")
    _commit(repo, "STATUS.md", "b")
    _commit(repo, "harness/README.md", "c")
    _merge(repo, "pr")
    files = changes.changed_files("pull_request", cwd=str(repo))
    assert sorted(files) == ["STATUS.md", "harness/README.md"]
    assert not changes.full_run(files)


def test_pull_request_without_a_merge_commit_is_a_full_run(repo):
    _commit(repo, "PROCESS.md", "b")
    assert changes.changed_files("pull_request", cwd=str(repo)) is None


def test_main_writes_the_output(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(changes, "changed_files", lambda e: ["STATUS.md"])
    assert changes.main(["pull_request"]) == 0
    monkeypatch.setattr(changes, "changed_files", lambda e: None)
    assert changes.main(["push"]) == 0
    assert changes.main(["pull_request"]) == 0
    assert out.read_text() == "full=false\nfull=true\nfull=true\n"
    text = capsys.readouterr().out
    assert "- doc: STATUS.md" in text
    assert "Event push: not a pull request" in text
    assert "not known (git failed)" in text
    assert "Result: full run" in text
    assert "the dialect oracles, the smoke benchmark, and the corpus smoke run." in text


def test_a_non_ascii_path_is_not_quoted(repo):
    _git(repo, "checkout", "-q", "-b", "pr")
    _commit(repo, "corpus/é a.sql", "select 1")
    _merge(repo, "pr")
    files = changes.changed_files("pull_request", cwd=str(repo))
    assert files == ["corpus/é a.sql"]
