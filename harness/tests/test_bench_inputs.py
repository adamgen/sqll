"""Benchmark definitions and the input builder (harness/bench.md, "Inputs")."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from sqll_harness import cli, known_failures
from sqll_harness.adapters import ADAPTERS
from sqll_harness.bench import definitions, inputs
from sqll_harness.paths import KNOWN_FAILURES_DIR, OUT_DIR, REPO_ROOT, SQLFLUFF_ROOT

RECORDED = definitions.load()
FIXTURES = inputs.fixture_dir(SQLFLUFF_ROOT)


@pytest.fixture(scope="module")
def pinned() -> inputs.Build:
    """One build of the pinned fixtures."""
    return inputs.build(SQLFLUFF_ROOT)


def _files(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def _bench_inputs(*args) -> int:
    return cli.main(["bench", "inputs", *map(str, args)])


# Two builds, the recorded definitions, and the pinned fixtures.


def test_two_builds_are_byte_identical(tmp_path):
    assert _bench_inputs("--out", tmp_path / "a") == 0
    assert _bench_inputs("--out", tmp_path / "b") == 0
    a, b = _files(tmp_path / "a"), _files(tmp_path / "b")
    assert a == b
    # The inputs of the definitions, and the manifest.
    assert len(a) == len(RECORDED["inputs"]) + 1
    assert inputs.MANIFEST in a


def test_the_recorded_definitions_are_those_of_the_build(pinned):
    assert definitions.check(RECORDED, pinned) == []
    new = definitions.render(definitions.make(pinned))
    assert definitions.DEFINITIONS.read_text(encoding="utf8") == new, (
        "Run: sqll-harness bench inputs --write-definitions"
    )


def test_each_built_input_has_the_recorded_sha256(pinned):
    assert set(pinned.inputs) == set(RECORDED["inputs"])
    for name, built in pinned.inputs.items():
        rec = RECORDED["inputs"][name]
        assert hashlib.sha256(built.data).hexdigest() == rec["sha256"], name
        assert len(built.data) == rec["bytes"], name
        assert built.data.count(b"\n") == rec["lines"], name


def test_each_dialect_folder_has_its_benchmarks_and_inputs():
    folders = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())
    assert len(folders) == 28 and "soql" in folders
    recorded = sorted({b["dialect"] for b in RECORDED["benchmarks"]})
    assert recorded == folders
    ids = [b["id"] for b in RECORDED["benchmarks"]]
    assert len(ids) == len(set(ids)) == 28 * 10
    for dialect in folders:
        mine = [b for b in RECORDED["benchmarks"] if b["dialect"] == dialect]
        assert [b["id"] for b in mine] == [f"start/{dialect}"] + [
            f"{c}/{dialect}/{s}"
            for c in ("parse", "lint", "fix")
            for s in ("small", "medium", "large")
        ]
        for b in mine:
            assert b["input"] in RECORDED["inputs"]
    assert {b["input"] for b in RECORDED["benchmarks"]} == set(RECORDED["inputs"])


def test_start_input():
    assert RECORDED["inputs"]["start"] == {
        "bytes": 10,
        "lines": 1,
        "sha256": hashlib.sha256(b"SELECT 1;\n").hexdigest(),
    }
    start = [b for b in RECORDED["benchmarks"] if b["command"] == "start"]
    assert len(start) == 28
    assert all(b["input"] == "start" and b["size"] is None for b in start)


def _tool_names(obj) -> list:
    """Return each "tool" key and each tool name in obj."""
    found = []
    names = set(ADAPTERS) - {"sqlfluff"}
    if isinstance(obj, dict):
        found += [k for k in obj if k in ("tool", "tools") or k in names]
        for v in obj.values():
            found += _tool_names(v)
    elif isinstance(obj, list):
        for v in obj:
            found += _tool_names(v)
    elif isinstance(obj, str) and obj in names:
        found.append(obj)
    return found


def test_the_definitions_have_no_tool_entry():
    assert _tool_names(RECORDED) == []
    assert "sqll" not in json.dumps(RECORDED)


def test_selection_counts_of_bench_md(pinned):
    """The counts and the size ranges in harness/bench.md ("Inputs")."""
    man = inputs.manifest(pinned)
    sel = man["selection"]
    assert sel["files"] == 2306
    assert sel["used"] == 2161
    assert sel["skipped"] == {
        "no_tree": [],
        "unparsable_tree": [],
        "in_file_config": ["clickhouse/create_user.sql"],
        "config_override": ["ansi/expression_recursion.sql"],
        "excluded": sorted(_exclusions()),
        "no_leaf": [
            "ansi/comments.sql",
            "ansi/empty_file.sql",
            "sqlite/block_comment_end_of_input.sql",
        ],
    }
    assert sel["added"]["newline"] == []
    assert len(sel["added"]["terminator"]) == 312
    ranges = {
        size: (
            min(v["bytes"] for k, v in man["inputs"].items() if k.endswith(size)),
            max(v["bytes"] for k, v in man["inputs"].items() if k.endswith(size)),
        )
        for size in inputs.SIZES
    }
    assert ranges == {
        "small": (985, 1024),
        "medium": (4017, 4096),
        "large": (16350, 16383),
    }
    repeated = {k for k, v in man["inputs"].items() if v["repeats"]}
    assert len(repeated) == 34
    for dialect, pieces in pinned.selection.pieces.items():
        for size, target in inputs.SIZES.items():
            if sum(len(p.data) for p in pieces) < target:
                assert f"{dialect}/{size}" in repeated


def test_each_input_is_a_join_of_unchanged_fixture_files(pinned):
    pieces = {
        p.path: p for dialect in pinned.selection.pieces.values() for p in dialect
    }
    for name, built in pinned.inputs.items():
        if name == inputs.START:
            continue
        dialect = name.split("/")[0]
        assert built.files and all(f.startswith(f"{dialect}/") for f in built.files)
        assert built.data == b"".join(pieces[f].data for f in built.files)
        assert len(built.data) <= inputs.SIZES[name.split("/")[1]]
    for path, piece in pieces.items():
        raw = (FIXTURES / path).read_bytes()
        assert piece.data.startswith(raw)
        assert piece.data[len(raw) :] in (b"", b"\n", b";\n", b"\n;\n")


# The exclusion list.


def _exclusions() -> dict[str, str]:
    return known_failures.parse(inputs.EXCLUSIONS.read_text(encoding="utf8"))


def test_each_exclusion_has_a_reason_and_is_a_pinned_fixture():
    entries = _exclusions()
    assert len(entries) == 140
    for path, reason in entries.items():
        assert reason, path
        assert path.endswith(".sql") and (FIXTURES / path).is_file(), path
    assert inputs.load_exclusions(inputs.EXCLUSIONS, SQLFLUFF_ROOT) == entries


def test_the_exclusion_reasons_are_true():
    entries = _exclusions()
    sqruff = {p for p, r in entries.items() if r.startswith("sqruff 0.41.0: ")}
    record = known_failures.load(KNOWN_FAILURES_DIR, "sqruff")
    unparsable = {
        case_id.removeprefix("dialects/") + ".sql"
        for case_id, reason in record.items()
        if case_id.startswith("dialects/") and "unparsable segment" in reason
    }
    assert len(unparsable) == 139
    assert sqruff == unparsable
    assert set(entries) - sqruff == {"ansi/bracket_in_comment.sql"}


@pytest.mark.parametrize(
    "text, message",
    [
        ("ansi/no_such_file.sql  # reason\n", "is not a SQL file"),
        ("ansi/bracket_in_comment.yml  # reason\n", "is not a SQL file"),
        ("ansi/bracket_in_comment.sql\n", "has no reason"),
        ("ansi/merge_into.sql  # a\nansi/bracket_in_comment.sql  # b\n", "sorted"),
        ("ansi/merge_into.sql  # a\nansi/merge_into.sql  # b\n", "duplicate"),
    ],
)
def test_a_bad_exclusion_list_fails_the_build(tmp_path, text, message):
    bad = tmp_path / "exclusions.txt"
    bad.write_text(text, encoding="utf8")
    with pytest.raises(inputs.BuildError, match=message):
        inputs.build(SQLFLUFF_ROOT, bad)


# Fail closed on a change of a fixture or of the definitions.


def _linked_copy(tmp_path: Path) -> Path:
    """Return a sqlfluff root whose dialect fixtures link to the pinned files."""
    root = tmp_path / "sqlfluff"
    shutil.copytree(FIXTURES, inputs.fixture_dir(root), copy_function=os.symlink)
    return root


def test_a_changed_fixture_fails_the_check(tmp_path):
    root = _linked_copy(tmp_path)
    same = inputs.build(root)
    # The copy has no git commit. Only that is different.
    assert [e.split(":")[0] for e in definitions.check(RECORDED, same)] == [
        "sqlfluff_ref"
    ]
    used = same.selection.pieces["ansi"][0].path
    target = inputs.fixture_dir(root) / used
    data = target.read_bytes()
    target.unlink()
    target.write_bytes(data.replace(b"\n", b"\n\n", 1))
    errors = definitions.check(RECORDED, inputs.build(root))
    changed = [e for e in errors if e.startswith("input ansi/")]
    assert changed and all("sha256" in e for e in changed)
    assert _bench_inputs("--out", tmp_path / "o", "--sqlfluff-root", root) == 1


def test_a_changed_definition_fails_the_check(tmp_path, pinned):
    changed = json.loads(json.dumps(RECORDED))
    changed["inputs"]["soql/small"]["sha256"] = "0" * 64
    del changed["benchmarks"][5]
    errors = definitions.check(changed, pinned)
    assert len(errors) == 2
    assert errors[0].startswith("input soql/small: recorded")
    assert errors[1].startswith("benchmarks differ: missing ['lint/ansi/medium']")
    path = tmp_path / "definitions.json"
    path.write_text(definitions.render(changed), encoding="utf8")
    assert _bench_inputs("--out", tmp_path / "o", "--definitions", path) == 1


# The output folder and the submodule.


def test_check_submodule_passes_after_a_build(tmp_path):
    assert _bench_inputs("--out", tmp_path / "o") == 0
    proc = subprocess.run(
        [REPO_ROOT / "scripts" / "check-submodule"], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    "out",
    [
        SQLFLUFF_ROOT / "bench-inputs",
        FIXTURES / "ansi",
        REPO_ROOT / "harness" / "bench-inputs",
        REPO_ROOT,
        OUT_DIR,
    ],
)
def test_an_output_folder_in_the_repository_is_refused(out):
    existed = out.exists()
    assert inputs.check_out_dir(out, SQLFLUFF_ROOT)
    assert _bench_inputs("--out", out) == 2
    assert out.exists() == existed


def test_an_output_folder_below_out_is_allowed():
    assert (
        inputs.check_out_dir(OUT_DIR / "bench" / "x" / "inputs", SQLFLUFF_ROOT) is None
    )


def test_a_folder_with_other_files_is_refused(tmp_path):
    (tmp_path / "keep.txt").write_text("x")
    assert "not empty" in inputs.check_out_dir(tmp_path, SQLFLUFF_ROOT)
    assert _bench_inputs("--out", tmp_path) == 2
    assert _files(tmp_path) == {"keep.txt": b"x"}


def test_a_new_build_replaces_an_earlier_build(tmp_path):
    out = tmp_path / "o"
    assert _bench_inputs("--out", out) == 0
    (out / "ansi" / "stale.sql").write_text("x")
    assert _bench_inputs("--out", out) == 0
    assert not (out / "ansi" / "stale.sql").exists()


# The rules on small fixture trees.


def _root(tmp_path: Path, files: dict[str, tuple[bytes, str | None]]) -> Path:
    root = tmp_path / "sqlfluff"
    for path, (sql, yml) in files.items():
        sql_path = inputs.fixture_dir(root) / path
        sql_path.parent.mkdir(parents=True, exist_ok=True)
        sql_path.write_bytes(sql)
        if yml is not None:
            sql_path.with_suffix(".yml").write_text(yml, encoding="utf8")
    return root


def _no_exclusions(tmp_path: Path) -> Path:
    path = tmp_path / "exclusions.txt"
    path.write_text("# none\n", encoding="utf8")
    return path


SELECT_TREE = "file:\n  statement:\n    keyword: select\n    numeric_literal: '1'\n"
TERMINATED_TREE = SELECT_TREE + "  statement_terminator: ;\n"
SLASH_TREE = "file:\n  statement:\n    keyword: begin\n  slash: /\n"


def test_the_join_adds_a_terminator_only_if_the_tree_has_none(tmp_path):
    root = _root(
        tmp_path,
        {
            "d/a.sql": (b"select 1\n", SELECT_TREE),
            "d/b.sql": (b"select 1;\n", TERMINATED_TREE),
            "d/c.sql": (b"begin\n/\n", SLASH_TREE),
            "d/e.sql": (b"select 1 -- end", SELECT_TREE),
            "d/f.sql": (b"select 1; -- a comment\n", TERMINATED_TREE),
        },
    )
    sel = inputs.select(root, {})
    assert [(p.path, p.data, p.added) for p in sel.pieces["d"]] == [
        ("d/a.sql", b"select 1\n;\n", ("terminator",)),
        ("d/b.sql", b"select 1;\n", ()),
        ("d/c.sql", b"begin\n/\n", ()),
        ("d/e.sql", b"select 1 -- end\n;\n", ("newline", "terminator")),
        ("d/f.sql", b"select 1; -- a comment\n", ()),
    ]


def test_the_selection_rules(tmp_path):
    root = _root(
        tmp_path,
        {
            "ansi/expression_recursion.sql": (b"select 1;\n", TERMINATED_TREE),
            "d/a_ok.sql": (b"select 1;\n", TERMINATED_TREE),
            "d/b_no_tree.sql": (b"select 1;\n", None),
            "d/c_unparsable.sql": (b"x;\n", "file:\n  unparsable:\n    word: x\n"),
            "d/d_config.sql": (b"-- sqlfluff:dialect:ansi\nselect 1;\n", SELECT_TREE),
            "d/e_config.sql": (b"select 1;\n  --SQLFluff:x\n", TERMINATED_TREE),
            "d/f_excluded.sql": (b"select 1;\n", TERMINATED_TREE),
            "d/g_no_leaf.sql": (b"-- only a comment\n", "file:\n"),
            "d/h_empty.sql": (b"", "file: null\n"),
            "d/i_not_config.sql": (b"select 1; -- sqlfluff\n", TERMINATED_TREE),
            "d/notes.txt": (b"not sql", None),
        },
    )
    sel = inputs.select(root, {"d/f_excluded.sql": "reason"})
    assert sel.files == 10
    assert [p.path for p in sel.pieces["d"]] == ["d/a_ok.sql", "d/i_not_config.sql"]
    assert sel.pieces["ansi"] == []
    assert sel.skipped == {
        "no_tree": ["d/b_no_tree.sql"],
        "unparsable_tree": ["d/c_unparsable.sql"],
        "in_file_config": ["d/d_config.sql", "d/e_config.sql"],
        "config_override": ["ansi/expression_recursion.sql"],
        "excluded": ["d/f_excluded.sql"],
        "no_leaf": ["d/g_no_leaf.sql", "d/h_empty.sql"],
    }


def _pieces(*sizes: int) -> list[inputs.Piece]:
    return [inputs.Piece(f"d/{i}.sql", b"x" * n, ()) for i, n in enumerate(sizes)]


@pytest.mark.parametrize(
    "sizes, target, order, passes",
    [
        ((10, 20), 64, [0, 1, 0, 1], 2),
        ((50, 10), 55, [0], 1),
        ((10, 50, 5), 20, [0, 2, 2], 2),
        ((10, 20), 30, [0, 1], 1),
        ((40,), 30, [], 0),
    ],
)
def test_fill_repeats_the_files_in_sorted_order(sizes, target, order, passes):
    pieces = _pieces(*sizes)
    chosen, n = inputs.fill(pieces, target)
    assert [pieces.index(p) for p in chosen] == order
    assert n == passes


def test_a_dialect_with_no_input_fails_the_build(tmp_path):
    big = b"select " + b"1 " * 600 + b";\n"
    root = _root(tmp_path, {"d/a.sql": (big, TERMINATED_TREE)})
    with pytest.raises(inputs.BuildError, match="d/small: no selected file fits"):
        inputs.build(root, _no_exclusions(tmp_path))
    root = _root(tmp_path / "2", {"d/a.sql": (b"x;\n", None)})
    with pytest.raises(inputs.BuildError, match="d/small: no selected file fits"):
        inputs.build(root, _no_exclusions(tmp_path))


def test_a_small_build(tmp_path):
    root = _root(
        tmp_path,
        {
            "d/a.sql": (b"select 1;\n" * 30, TERMINATED_TREE),
            "d/b.sql": (b"select 1\n", SELECT_TREE),
        },
    )
    result = inputs.build(root, _no_exclusions(tmp_path))
    assert sorted(result.inputs) == ["d/large", "d/medium", "d/small", "start"]
    small = result.inputs["d/small"]
    assert small.files[:4] == ("d/a.sql", "d/b.sql", "d/a.sql", "d/b.sql")
    assert small.repeats == len(small.files) - 2
    assert len(small.data) <= 1024 < len(small.data) + 300 + 11
    defs = definitions.make(result)
    assert [b["id"] for b in defs["benchmarks"]][:2] == ["start/d", "parse/d/small"]
    assert definitions.check(defs, result) == []
