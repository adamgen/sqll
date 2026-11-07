"""Tests of scripts/s3b/tree_check.py (S3b task C7): the check of the
cargo test output, the conversion cost record, and its numbers in
status/S3b.md."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "s3b" / "tree_check.py"


def load():
    spec = importlib.util.spec_from_file_location("tree_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["tree_check"] = module
    spec.loader.exec_module(module)
    return module


tc = load()

GOOD = (
    "running 1 test\n"
    f"{tc.PASS_LINE} (280339 nodes)\n"
    f"test {tc.TEST} ... ok\n\n"
    "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 5 filtered out\n"
)


def test_a_passing_run_has_no_problem():
    assert tc.check_output(0, GOOD) == []


@pytest.mark.parametrize(
    "code, output",
    [
        (101, GOOD),
        (0, GOOD.replace(f"{tc.TEST} ... ok", f"{tc.TEST} ... ignored")),
        (0, GOOD.replace("1 passed", "0 passed")),
        (0, GOOD.replace("84 of 84", "83 of 84")),
        (0, ""),
    ],
)
def test_the_check_fails_closed(code, output):
    assert tc.check_output(code, output)


def test_the_pass_line_is_the_line_of_the_rust_test():
    text = (REPO_ROOT / "crates" / "sqll_interfaces" / "tests" / "tree.rs").read_text(
        "utf8"
    )
    assert '"tree: {passed} of {files} {what}: lossless and node for node equal' in text
    assert 'report("S2 parse inputs", files, total, &problems);' in text
    assert f"const S2_PARSE_INPUTS: usize = {tc.PARSE_INPUTS};" in text
    assert f"fn {tc.TEST}()" in text
    assert f'const S2_INPUTS_ENV: &str = "{tc.INPUTS_ENV}";' in text


def test_the_ci_job_runs_the_check():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text("utf8")
    assert (
        "run: uv run --frozen --project harness python scripts/s3b/tree_check.py check"
        in ci
    )


DOC = json.loads(tc.MEASURE_FILE.read_text("utf8"))


def test_the_record_has_the_28_large_inputs_of_the_definitions():
    from sqll_harness.bench import definitions

    assert DOC["kind"] == tc.KIND
    assert DOC["runs"] >= 1
    assert DOC["crates_clean"] is True
    items = DOC["data"]["items"]
    names = [i["input"] for i in items]
    assert len(names) == tc.LARGE_INPUTS == len(set(names))
    assert all(n.endswith("/large") for n in names)
    defs = definitions.load()["inputs"]
    for item in items:
        assert item["sha256"] == defs[item["input"]]["sha256"]
        assert item["nodes"] > 0 and item["tree_heap_bytes"] > item["bytes"]
        for step in tc.STEPS:
            assert item["median_ns"][step] > 0
            assert item["min_ns"][step] <= item["median_ns"][step]


def test_the_totals_and_ratios_are_those_of_the_items():
    data = DOC["data"]
    want = tc.derive(data["items"])
    assert {k: data[k] for k in want} == want


def test_status_cites_the_numbers_of_the_record():
    status = (REPO_ROOT / "status" / "S3b.md").read_text("utf8")
    for line in tc.summary_lines(DOC):
        assert line in status, line
