"""Tests for the CI scripts in ci/: the image tag and the test matrix."""

import importlib.util
import json
import re
import shlex

import pytest

from sqll_harness.adapters import ADAPTERS
from sqll_harness.paths import REPO_ROOT
from sqll_harness.suites import SUITES


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "ci" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


image_tag = _load("image_tag")
matrix = _load("matrix")


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


def test_ci_matrix_names_real_suites_and_tools():
    entries = json.loads((REPO_ROOT / "ci" / "matrix.json").read_text())
    assert entries
    for e in entries:
        assert e["suite"] in SUITES
        assert e["tool"] in ADAPTERS
    assert matrix.expand(entries)["include"]


def test_ci_matrix_runs_sqlfluff_rs_on_each_suite():
    entries = json.loads((REPO_ROOT / "ci" / "matrix.json").read_text())
    shards = {(e["suite"], e["tool"]): e["shards"] for e in entries}
    for suite in SUITES:
        assert shards[(suite, "sqlfluff-rs")] == shards[(suite, "sqlfluff")]
