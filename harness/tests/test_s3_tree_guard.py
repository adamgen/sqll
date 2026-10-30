"""S3 T14: the S2 tree guard (scripts/s3/tree_guard.py).

The CI job build runs the guard on the sqll build of each pull request. These
tests prove that the record is complete and that the guard fails for a
changed tree, a changed exit code, and a missing or extra input."""

import copy
import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

from sqll_harness.bench import definitions as bench_definitions
from sqll_harness.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "tree_guard", REPO_ROOT / "scripts" / "s3" / "tree_guard.py"
)
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)

RECORD = json.loads(tg.RECORD_FILE.read_text("utf8"))
DEFS = bench_definitions.load()


def test_the_record_has_each_parse_input_of_the_definitions():
    parse_inputs = {
        name: entry["sha256"]
        for name, entry in DEFS["inputs"].items()
        if name != "start"
    }
    assert len(parse_inputs) == tg.PARSE_INPUTS == 84
    assert {n: e["sha256"] for n, e in RECORD["inputs"].items()} == parse_inputs


def test_the_record_is_that_of_the_reference_build():
    assert RECORD["kind"] == tg.KIND
    assert RECORD["sqlfluff_ref"] == DEFS["sqlfluff_ref"]
    assert RECORD["reference"]["commit"] == tg.REFERENCE_COMMIT
    for entry in RECORD["inputs"].values():
        for run in tg.RUNS:
            assert entry[run]["exit_code"] == 0
            assert entry[run]["stderr"] == ""
            assert entry[run]["stdout_bytes"] > 0


def test_the_sqlfluff_counts_are_those_of_the_inputs():
    s = RECORD["sqlfluff"]
    rows = RECORD["inputs"].values()
    assert s["default_equal"] == sum(r["sqlfluff"]["default_equal"] for r in rows)
    assert s["meta_tree_equal"] == sum(r["sqlfluff"]["meta_tree_equal"] for r in rows)
    assert s["not_equal"]["default"] == [
        n for n, r in RECORD["inputs"].items() if not r["sqlfluff"]["default_equal"]
    ]
    assert RECORD["summary"]["sqlfluff_default_equal"] == s["default_equal"]
    assert RECORD["summary"]["sqlfluff_meta_tree_equal"] == s["meta_tree_equal"]


# compare


def observed_of(record):
    return {
        name: {k: v for k, v in entry.items() if k != "sqlfluff"}
        for name, entry in copy.deepcopy(record["inputs"]).items()
    }


def test_the_record_compares_equal_with_itself():
    assert tg.compare(RECORD, observed_of(RECORD)) == []


@pytest.mark.parametrize(
    "key, value",
    [
        ("stdout_sha256", "0" * 64),
        ("stdout_bytes", 1),
        ("exit_code", 1),
        ("stderr", "PRS: x\n"),
    ],
)
def test_a_changed_output_fails(key, value):
    observed = observed_of(RECORD)
    observed["ansi/large"]["meta"][key] = value
    errors = tg.compare(RECORD, observed)
    assert len(errors) == 1
    assert errors[0].startswith(f"ansi/large (meta): {key} is")


def test_a_missing_or_extra_input_fails():
    observed = observed_of(RECORD)
    del observed["tsql/small"]
    observed["tsql/huge"] = observed["tsql/large"]
    errors = tg.compare(RECORD, observed)
    assert "tsql/small: in the record, but not an input" in errors
    assert "tsql/huge: an input, but not in the record" in errors


def test_another_input_fails():
    observed = observed_of(RECORD)
    observed["ansi/small"]["sha256"] = "1" * 64
    assert tg.compare(RECORD, observed) == [
        "ansi/small: the input is not the input of the record"
    ]


def test_a_record_with_fewer_inputs_fails():
    record = copy.deepcopy(RECORD)
    del record["inputs"]["ansi/small"]
    observed = observed_of(record)
    assert tg.compare(record, observed) == ["the record has 83 inputs, not 84"]


# The guard with a binary: a fake sqll prints a tree of each input. A record
# of the fake passes; a fake that changes one tree fails.

FAKE = """#!{python}
import json, sys
args = sys.argv[1:]
path = args[-1]
leaves = open(path, encoding="utf8").read().split()
if {mutate!r} and path == "ansi/medium.sql":
    leaves[3] = leaves[3] + "x"
meta = ["-m"] if "-m" in args else []
tree = {{"file": [{{"raw": leaf}} for leaf in leaves] + meta}}
print(json.dumps([{{"filepath": path, "segments": tree}}]))
"""


def fake(tmp_path: Path, mutate: bool) -> Path:
    path = tmp_path / ("mutated" if mutate else "fake")
    path.write_text(FAKE.format(python=sys.executable, mutate=mutate), "utf8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    folder = tmp_path_factory.mktemp("guard") / "inputs"
    return folder, tg.build_inputs(folder)


def test_the_guard_passes_for_the_same_trees_and_fails_for_a_changed_tree(
    inputs, tmp_path
):
    folder, digests = inputs
    observed, _ = tg.observe(fake(tmp_path, False), folder, digests)
    record = {"kind": tg.KIND, "inputs": observed}
    assert tg.guard(fake(tmp_path, False), record, folder) == []
    errors = tg.guard(fake(tmp_path, True), record, folder)
    assert {e.split(":")[0] for e in errors} == {
        "ansi/medium (default)",
        "ansi/medium (meta)",
    }
    assert sum("stdout_sha256" in e for e in errors) == 2
