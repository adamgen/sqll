"""Tests of scripts/s3b/cli_oracle.py (S3b task C13): the record of the
sqlfluff runs that crates/sqll/tests/cli.rs compares sqll with. The CI job
build runs "check", which makes the data again."""

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "s3b" / "cli_oracle.py"
TEST = REPO_ROOT / "crates" / "sqll" / "tests" / "cli.rs"


def load():
    spec = importlib.util.spec_from_file_location("cli_oracle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cli_oracle"] = module
    spec.loader.exec_module(module)
    return module


co = load()
RECORD = json.loads(co.RECORD_FILE.read_text("utf8"))


def test_the_record_has_each_scenario_of_the_script_in_order():
    assert RECORD["count"] == len(co.SCENARIOS) == len(RECORD["scenarios"])
    for got, want in zip(RECORD["scenarios"], co.SCENARIOS, strict=True):
        for key in ("name", "files", "cwd", "args", "stdin", "tty", "sqll"):
            assert got[key] == want[key], (want["name"], key)
    assert RECORD["kind"] == co.KIND
    assert RECORD["sqlfluff"]["version"] == "4.4.0"


def test_the_writer_gives_the_record_again():
    assert co.dumps(RECORD) == co.RECORD_FILE.read_text("utf8")


def test_each_scenario_has_a_known_mark_and_its_data():
    for s in RECORD["scenarios"]:
        assert s["sqll"] in (None, "unsupported", "usage"), s["name"]
        assert isinstance(s["exit_code"], int), s["name"]
        if s["sqll"] == "unsupported":
            # sqll fails closed where sqlfluff runs.
            assert s["exit_code"] != 2, s["name"]
            assert ("stdout" in s) == (s["name"] in co.KEEP_OUTPUT), s["name"]
            assert "stderr" not in s and "after" not in s, s["name"]
        else:
            assert {"stdout", "stderr", "after"} <= set(s), s["name"]
    assert co.problems_of(RECORD["scenarios"]) == []


def test_each_command_and_format_has_a_scenario():
    args = [s["args"] for s in RECORD["scenarios"] if s["sqll"] is None]
    commands = {a[0] for a in args}
    assert commands == {"lint", "fix", "rules", "dialects"}
    formats = set()
    for a in args:
        if a[0] == "lint":
            fmt = "human"
            for i, x in enumerate(a):
                if x in ("-f", "--format"):
                    fmt = a[i + 1]
            formats.add(fmt)
    assert formats == {
        "human",
        "json",
        "yaml",
        "github-annotation",
        "github-annotation-native",
        "none",
    }
    codes = {s["exit_code"] for s in RECORD["scenarios"] if s["sqll"] is None}
    assert codes == {0, 1, 2}
    assert any(s["tty"] for s in RECORD["scenarios"])
    assert any(s["stdin"] for s in RECORD["scenarios"] if s["args"][0] == "fix")


def test_the_timings_are_masked():
    text = (
        '{"timings": {"templating": 1.5e-05, "CP01": 0.25}}\n'
        "  timings:\n    lexing: 0.001\n"
    )
    assert co.mask_timings(text) == (
        '{"timings": {"templating": 0.0, "CP01": 0.0}}\n  timings:\n    lexing: 0.0\n'
    )
    assert "each_c13_scenario_gives_the_sqlfluff_result" in TEST.read_text("utf8")


def test_the_memory_record_shows_no_growth_for_lint_and_fix():
    """scripts/s3b/memory_check.py: the record of C13 (status/S3b.md)."""
    record = json.loads((REPO_ROOT / "results/S3b/C13-memory.json").read_text("utf8"))
    assert record["kind"] == "sqll-s3b-c13-memory"
    assert record["pass"] is True
    for mode in record["bounded_modes"]:
        peaks = [r["vmhwm_kib"] for r in record["runs"] if r["mode"] == mode]
        files = [r["files"] for r in record["runs"] if r["mode"] == mode]
        assert files == [3, 30, 300, 3000], mode
        assert max(peaks) <= min(peaks) * 1.10, mode
        assert record["ratio_largest_to_previous"][mode] <= record["max_ratio"]
    assert all(r["exit_code"] in (0, 1) for r in record["runs"])
    # The output bytes of each run (status/S3b.md gives those of lint json).
    for r in record["runs"]:
        assert r["stdout_bytes"] > 0, r
    big = [r for r in record["runs"] if r["mode"] == "lint json" and r["files"] == 3000]
    assert big[0]["stdout_bytes"] > 100_000_000


def test_the_rules_table_scenario_keeps_its_output():
    """The scenario of KEEP_OUTPUT is unsupported in sqll (the default
    "rules = all") and keeps the sqlfluff table of each rule."""
    for name in co.KEEP_OUTPUT:
        s = next(s for s in RECORD["scenarios"] if s["name"] == name)
        assert s["sqll"] == "unsupported" and s["exit_code"] == 0
        assert s["stdout"].count("\n      groups: ") == 79


def test_the_documents_give_the_counts_of_the_record():
    """harness/sqll.md and status/S3b.md give the scenario counts of the
    record by mark (a false count in a document blocks a merge)."""
    by_mark: dict = {None: {}, "unsupported": {}, "usage": {}}
    for s in RECORD["scenarios"]:
        counts = by_mark[s["sqll"]]
        counts[s["args"][0]] = counts.get(s["args"][0], 0) + 1

    def listing(mark):
        return ", ".join(
            f"{n} {c}"
            for c in ("lint", "fix", "rules", "dialects")
            if (n := by_mark[mark].get(c))
        )

    total = len(RECORD["scenarios"])
    same, closed, usage = (sum(by_mark[m].values()) for m in by_mark)
    assert by_mark["usage"].keys() == {"lint"}
    doc = " ".join((REPO_ROOT / "harness/sqll.md").read_text("utf8").split())
    assert f"has {total} scenarios of `lint`, `fix`, `rules`, and `dialects`." in doc
    assert f"In {same} ({listing(None)})," in doc
    assert f"{closed} fail closed ({listing('unsupported')};" in doc
    assert f"{usage} are usage errors (lint;" in doc
    status = " ".join((REPO_ROOT / "status/S3b.md").read_text("utf8").split())
    assert f"sqlfluff 4.4.0 for {total} scenarios" in status
    same_text = f"{same} give the same stdout, stderr, exit code, and changed files;"
    assert same_text in status
    assert f"{closed} fail closed (`unsupported`" in status
    assert f"{usage} are usage errors" in status


def test_the_documents_give_the_numbers_of_the_memory_record():
    """harness/sqll.md and status/S3b.md give the peaks (MiB, one decimal)
    and the output bytes of results/S3b/C13-memory.json."""
    record = json.loads((REPO_ROOT / "results/S3b/C13-memory.json").read_text("utf8"))

    def peak(mode, files):
        kib = next(
            r["vmhwm_kib"]
            for r in record["runs"]
            if r["mode"] == mode and r["files"] == files
        )
        return f"{kib / 1024:.1f}"

    doc = " ".join((REPO_ROOT / "harness/sqll.md").read_text("utf8").split())
    status = " ".join((REPO_ROOT / "status/S3b.md").read_text("utf8").split())
    lint = (peak("lint human", 3), peak("lint human", 3000))
    fix = (peak("fix", 3), peak("fix", 3000))
    assert f"{lint[0]} and {lint[1]} MiB (lint), {fix[0]} and {fix[1]} MiB (fix)" in doc
    assert f"lint {lint[0]} to {lint[1]} MiB, fix {fix[0]} to {fix[1]} MiB" in status
    ratios = record["ratio_largest_to_previous"]
    assert f"1.015 and {ratios['fix']:.3f})" in status
    assert f"(3000 / 300 files: {ratios['lint human']:.3f} and" in status
    big = next(
        r for r in record["runs"] if r["mode"] == "lint json" and r["files"] == 3000
    )
    mib = round(big["vmhwm_kib"] / 1024)
    assert f"{mib} MiB for 3000 files with" in doc
    assert f"({mib} MiB for 3000 files; `stdout_bytes` {big['stdout_bytes']})" in status
