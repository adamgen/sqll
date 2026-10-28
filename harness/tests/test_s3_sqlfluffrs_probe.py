"""S3 T5: the sqlfluffrs standalone probe.

results/s3/sqlfluffrs-probe.json is the report of scripts/s3/sqlfluffrs_probe.py
on the committed records of the build, the fixture check, and the timing
session. The records agree with the pinned submodule, the S1 dialect cases,
and the S2 benchmark definitions."""

import importlib.util
import json
import re
import tomllib

import pytest

from sqll_harness.bench import definitions as bench_definitions
from sqll_harness.bench import report as bench_report
from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT, sqlfluff_ref
from sqll_harness.suites import dialects

_spec = importlib.util.spec_from_file_location(
    "sqlfluffrs_probe", REPO_ROOT / "scripts" / "s3" / "sqlfluffrs_probe.py"
)
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)

BUILD = json.loads(sp.BUILD_FILE.read_text("utf8"))
CASES = json.loads(sp.CASES_FILE.read_text("utf8"))
BENCH = json.loads(sp.BENCH_FILE.read_text("utf8"))
OUT = json.loads(sp.OUT_FILE.read_text("utf8"))
WORKSPACE = SQLFLUFF_ROOT / "sqlfluffrs"


# The drift test.


def test_the_committed_report_is_the_report_of_the_committed_records(capsys):
    assert sp.main(["report", "--check"]) == 0


def test_the_check_fails_on_a_change(tmp_path, monkeypatch):
    out = tmp_path / "out.json"
    out.write_text(sp.OUT_FILE.read_text("utf8").replace('"T5"', '"T6"'), "utf8")
    monkeypatch.setattr(sp, "OUT_FILE", out)
    assert sp.main(["report", "--check"]) == 1


def test_a_record_of_another_probe_fails(tmp_path):
    cases = dict(CASES, probe_sha256="0" * 64)
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases), "utf8")
    with pytest.raises(sp.DataError, match="probe"):
        sp.make_report(cases_path=path)


def test_a_missing_case_fails(tmp_path):
    cases = dict(CASES, cases=CASES["cases"][1:])
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases), "utf8")
    with pytest.raises(sp.DataError, match="dialect cases"):
        sp.make_report(cases_path=path)


# The record of the build.


def test_the_versions_are_the_pins():
    sqlfluffrs = OUT["sqlfluffrs"]
    manifest = tomllib.loads((WORKSPACE / "Cargo.toml").read_text("utf8"))
    assert sqlfluffrs["version"] == manifest["package"]["version"] == "4.4.0"
    assert sqlfluffrs["commit"] == sqlfluff_ref(SQLFLUFF_ROOT)
    assert sqlfluffrs["tag"] == "4.4.0"
    channel = tomllib.loads((WORKSPACE / "rust-toolchain.toml").read_text("utf8"))
    toolchain = OUT["toolchain"]
    assert toolchain["channel"] == channel["toolchain"]["channel"]
    assert toolchain["rustc"][0].startswith(f"rustc {toolchain['channel']}.")
    assert toolchain["cargo"].startswith(f"cargo {toolchain['channel']}.")
    python = OUT["generation"]["python"]["installed"]
    assert python["sqlfluff_version"] == "4.4.0"
    assert "/sqlfluff/lib/python" in python["sqlfluff_file"]


def test_each_machine_is_recorded():
    for machine in OUT["machines"].values():
        assert machine["cpu_count"] > 0
        assert machine["cpu_model"] and machine["os"] and machine["kernel"]
    assert OUT["machines"]["timing"]["os"].startswith("Debian")


def test_each_command_has_its_exit_code_and_no_step_failed():
    for steps in OUT["steps"].values():
        assert steps
        for step in steps:
            assert set(step) >= {
                "step",
                "cwd",
                "argv",
                "env",
                "unset",
                "exit_code",
                "wall_s",
            }
            assert step["exit_code"] == 0, step
            text = json.dumps(step)
            assert str(REPO_ROOT) not in text
            assert BUILD["scratch"] not in text


def test_the_build_never_ran_in_the_submodule():
    for step in BUILD["steps"]:
        if step["argv"][0] in ("cargo", "rustc") or "rustify.py" in " ".join(
            step["argv"]
        ):
            assert step["cwd"].startswith("$SCRATCH/"), step
    names = [s["step"] for s in BUILD["steps"]]
    assert names[0] == "check the submodule before"
    assert names[-1] == "check the submodule after"
    assert BENCH["steps"][-1]["step"] == "check the submodule after"


def test_the_crates_and_the_probe_have_no_python():
    standalone = OUT["standalone"]
    trees = standalone["pyo3_in_dependency_tree"]
    assert set(trees) == {*sp.CRATES, sp.WORKSPACE, sp.PROBE}
    assert not any(trees.values())
    assert standalone["pyo3_with_python_feature_control"] is True
    assert standalone["python_calls_during_cargo"] == []
    assert standalone["libpython_linked"] is False
    assert not any("python" in lib for lib in standalone["ldd"])
    assert standalone["run_with_no_python"]["exit_code"] == 0
    assert standalone["run_with_no_python"]["tree_is_select_1"] is True
    assert standalone["run_with_no_python"]["image"] == sp.rust_image()


def test_the_build_steps_use_the_python_shims():
    for step in BUILD["steps"]:
        if step["argv"][0] == "cargo":
            assert step["env"]["PATH"] == "$SCRATCH/no-python/bin:$PATH"
            assert step["env"]["RUSTUP_TOOLCHAIN"] == OUT["toolchain"]["channel"]
            assert "PYTHONPATH" in step["unset"] and "VIRTUAL_ENV" in step["unset"]


def test_the_generated_files_are_the_dialect_tables():
    gen = OUT["generation"]
    files = BUILD["generation"]["files"]
    dialect_names = sorted(
        d.name for d in (SQLFLUFF_ROOT / dialects.FIXTURE_DIR).iterdir() if d.is_dir()
    )
    assert sorted(gen["by_dialect"]) == dialect_names
    assert gen["files"] == len(files) == 3 * len(dialect_names) + 1
    for d in gen["by_dialect"].values():
        assert d["files"] == 3 and d["grammar_instructions"] > 0
    assert all(f["path"].startswith(sp.GENERATED_DIR + "/") for f in files)
    assert gen["check_installed_exit_code"] == gen["check_submodule_src_exit_code"] == 0


def test_the_line_counts_split_hand_written_and_generated():
    lines = OUT["build"]["lines"]
    assert set(lines) == set(sp.CRATE_DIRS)
    for crate, kinds in lines.items():
        if crate == "sqlfluffrs_dialects":
            assert kinds["generated"]["lines"] == OUT["generation"]["lines"]
        else:
            assert kinds["generated"]["lines"] == 0
        assert kinds["hand_written"]["lines"] > 0
    total = OUT["build"]["lines_total"]
    assert total["generated"] == OUT["generation"]["lines"]


def test_the_build_times_and_size():
    build = OUT["build"]
    assert build["crates"]["exit_code"] == build["probe"]["exit_code"] == 0
    assert build["crates"]["wall_s"] > 0 and build["probe"]["wall_s"] > 0
    assert build["probe_binary_bytes"] == BUILD["probe"]["bytes"] > 0


def test_the_native_fixture_tests():
    native = OUT["native_fixture_tests"]
    inputs = BUILD["fixture_test_inputs"]
    assert sum(inputs.values()) == 2306
    assert set(native["by_dialect"]) == set(inputs)
    for d, row in native["by_dialect"].items():
        assert row["fixtures"] == inputs[d]
        assert row["parse_test"]["found"] == inputs[d]
        assert row["parse_test"]["passed"] + row["parse_test"]["failed"] == inputs[d]
        if row["yaml_shape_test"]["status"] == "passed":
            assert row["yaml_shape_test"]["total"] == inputs[d]
            assert row["yaml_shape_test"]["failed"] == 0
    assert native["passed"] + native["failed"] == len(BUILD["fixture_tests"]["tests"])


# The exact-tree check.


def test_the_cases_are_the_s1_dialect_cases():
    ids = sorted(c.id for c in dialects.discover(SQLFLUFF_ROOT))
    assert [c["id"] for c in CASES["cases"]] == ids
    assert len(ids) == 2306


def test_the_fixture_counts_are_those_of_the_cases():
    fx = OUT["fixtures"]
    cases = CASES["cases"]
    for c in cases:
        assert c["status"] == ("pass" if c["exact"] and c["no_unparsable"] else "fail")
    assert fx["total"]["cases"] == len(cases)
    assert fx["total"]["pass"] == sum(c["status"] == "pass" for c in cases)
    assert sum(d["cases"] for d in fx["by_dialect"].values()) == len(cases)
    assert sum(d["pass"] for d in fx["by_dialect"].values()) == fx["total"]["pass"]
    failed = [c["id"] for c in cases if c["status"] != "pass"]
    assert [f["id"] for f in fx["failures"]] == failed
    assert len(failed) == fx["total"]["cases"] - fx["total"]["pass"]


def test_first_difference():
    expected = ("file", (("statement", (("keyword", "SELECT"),)),))
    actual = ("file", (("statement", (("keyword", "select"),)),))
    diff = sp.first_difference(expected, actual)
    assert diff == {
        "path": ["file", "statement", "keyword"],
        "expected": '"SELECT"',
        "actual": '"select"',
    }
    assert sp.first_difference(expected, None)["actual"] == "null"


# The timing session.


def test_the_bench_report_is_one_correct_session():
    report = BENCH["report"]
    assert bench_report.check(report) == []
    assert report["profile"] == "full"
    assert report["scope"]["tools"] == sorted(sp.BENCH_TOOLS)
    assert report["scope"]["commands"] == list(sp.BENCH_COMMANDS)
    assert report["sqlfluff_ref"] == sqlfluff_ref(SQLFLUFF_ROOT)
    defs = bench_definitions.load()
    for name, entry in report["inputs"].items():
        assert entry["sha256"] == defs["inputs"][name]["sha256"]
    session = BENCH["session"]
    assert session["image"].startswith("sqll-ci:")
    assert "--network" in BENCH["steps"][2]["argv"]


def test_each_benchmark_row_has_n_median_and_mad_and_its_ratios():
    rows = OUT["speed"]["benchmarks"]
    assert len(rows) == 28 + 84
    for row in rows:
        for tool in sp.BENCH_TOOLS:
            stat = row[tool]
            if row["status"][tool] != "valid":
                assert stat is None
                continue
            assert stat["n"] >= 3 and stat["median_s"] > 0 and stat["mad_s"] >= 0
        for other in ("sqruff", "sqlfluff"):
            ratio = row[f"probe_over_{other}"]
            if row[sp.PROBE] and row[other]:
                assert ratio == round(
                    row[sp.PROBE]["median_s"] / row[other]["median_s"], 4
                )
            else:
                assert ratio is None
    assert all(r["status"][sp.PROBE] == "valid" for r in rows)
    assert all(r["status"]["sqlfluff"] == "valid" for r in rows)
    unsupported = sorted(r["id"] for r in rows if r["status"]["sqruff"] != "valid")
    assert unsupported == [
        "parse/soql/large",
        "parse/soql/medium",
        "parse/soql/small",
        "start/soql",
    ]


def test_the_speed_rows_come_from_the_bench_report():
    report = BENCH["report"]
    by = {(r["id"], r["tool"]): r for r in report["results"]}
    for row in OUT["speed"]["benchmarks"]:
        for tool in sp.BENCH_TOOLS:
            r = by[(row["id"], tool)]
            if r["status"] == "valid":
                assert row[tool]["median_s"] == r["stats"]["wall_s"]["median"]
                assert row[tool]["mad_s"] == r["stats"]["wall_s"]["mad"]
                assert row[tool]["n"] == r["stats"]["wall_s"]["n"]


# The probe source and its record.


def test_the_probe_lock_uses_the_versions_of_the_sqlfluffrs_lock():
    probe = tomllib.loads((sp.PROBE_SRC / "Cargo.lock").read_text("utf8"))["package"]
    pinned = tomllib.loads((WORKSPACE / "Cargo.lock").read_text("utf8"))["package"]
    versions = {(p["name"], p["version"]) for p in pinned}
    extra = [
        (p["name"], p["version"])
        for p in probe
        if (p["name"], p["version"]) not in versions
    ]
    assert extra == [(sp.PROBE, "0.0.0")]


def test_the_probe_builds_only_from_the_scratch_copy():
    manifest = tomllib.loads((sp.PROBE_SRC / "Cargo.toml").read_text("utf8"))
    paths = [
        d["path"] for d in manifest["dependencies"].values() if isinstance(d, dict)
    ]
    assert paths and all(p.startswith("../sqlfluff/sqlfluffrs/") for p in paths)
    assert manifest["package"]["publish"] is False
    assert "not sqll" in manifest["package"]["description"]


def test_the_probe_is_marked_as_research_code_with_its_attribution():
    main = (sp.PROBE_SRC / "src" / "main.rs").read_text("utf8")
    assert main.startswith("// S3 research probe (task T5). This is not sqll")
    assert "Copyright (c) 2018-2026 Alan Cruickshank. MIT License." in main
    third = (REPO_ROOT / "THIRD_PARTY.md").read_text("utf8")
    assert "scripts/s3/probe-sqlfluffrs/src/main.rs" in third
    assert "results/s3/sqlfluffrs-probe-build.json" in third
    assert "research" in OUT["probe"]["research_code"]


def test_the_probe_is_not_a_harness_tool():
    from sqll_harness.bench import registry

    assert sp.PROBE not in registry.names()
    harness = (REPO_ROOT / "harness").rglob("*.py")
    assert not any(
        "probe" in p.read_text("utf8") and "sqlfluffrs" in p.read_text("utf8")
        for p in harness
        if p.name != "test_s3_sqlfluffrs_probe.py"
    )


def test_the_probe_bench_adapter(tmp_path):
    adapter = sp.ProbeBench(tmp_path / "probe", "x")
    config = adapter.config("tsql")
    path = adapter.write_config(config, tmp_path / "config")
    assert adapter.argv("parse", path, "input.sql") == [
        str(tmp_path / "probe"),
        "--dialect",
        "tsql",
        "input.sql",
    ]
    with pytest.raises(ValueError):
        adapter.argv("lint", path, "input.sql")
    out = b'[{"filepath": "input.sql", "segments": {"file": null}}]'
    assert adapter.read_tree(out, "input.sql") == {"file": None}
    with pytest.raises(ValueError):
        adapter.read_tree(out, "other.sql")
    assert adapter.unsupported(config) is None


# The parsers of the tool output.


FIXTURE_TEST_OUTPUT = """
running 3 tests
test test_ansi_fixtures ...
Found 2 ANSI fixture tests
Running test: a
Results: 1 passed, 1 failed
FAILED
test test_ansi_fixtures_simple ...
Found 2 ANSI fixture tests
Testing 1 simple fixtures
Results: 1 passed, 0 failed
ok
test test_yaml_output_matches_python_ansi ...
YAML output comparison for dialect 'ansi': 2 total, 1 failed
Failed tests for dialect 'ansi':
  ansi::b
FAILED

failures:

failures:
    test_ansi_fixtures
    test_yaml_output_matches_python_ansi

test result: FAILED. 1 passed; 2 failed; 0 ignored; 0 measured; 0 filtered out
"""


def test_parse_fixture_tests():
    stderr = (
        "thread 'test_ansi_fixtures' (7) panicked at tests/x.rs:1:2:\ntests failed\n"
    )
    r = sp.parse_fixture_tests(FIXTURE_TEST_OUTPUT, stderr)
    assert r["tests"] == {
        "test_ansi_fixtures": "failed",
        "test_ansi_fixtures_simple": "passed",
        "test_yaml_output_matches_python_ansi": "failed",
    }
    assert r["parse_counts"] == {"ansi": {"found": 2, "passed": 1, "failed": 1}}
    assert r["yaml_counts"] == {"ansi": {"total": 2, "failed": 1}}
    assert r["yaml_failed"] == {"ansi": ["ansi::b"]}
    assert r["panics"] == {"test_ansi_fixtures": "tests failed"}


def test_parse_fixture_tests_fails_on_counts_that_do_not_agree():
    text = FIXTURE_TEST_OUTPUT.replace("1 passed; 2 failed", "2 passed; 1 failed")
    with pytest.raises(sp.DataError):
        sp.parse_fixture_tests(text, "")
    with pytest.raises(sp.DataError):
        sp.parse_fixture_tests("no result", "")


def test_tool_output_readers():
    assert sp.tree_packages("a v1\nb v2 (proc-macro)\na v1 (*)\n\nwarning: x\n") == [
        "a",
        "b",
    ]
    ldd = "\tlinux-vdso.so.1 (0x1)\n\tlibc.so.6 => /lib/libc.so.6 (0x2)\n"
    assert sp.ldd_libraries(ldd) == ["libc.so.6", "linux-vdso.so.1"]
    readelf = " 0x1 (NEEDED)             Shared library: [libc.so.6]\n"
    assert sp.needed_libraries(readelf) == ["libc.so.6"]
    assert sp.line_count(b"") == 0
    assert sp.line_count(b"a\nb") == 2
    assert sp.line_count(b"a\nb\n") == 2


def test_an_untracked_file_outside_the_generated_folder_fails(tmp_path):
    (tmp_path / "x.rs").write_text("x\n", "utf8")
    with pytest.raises(sp.DataError, match="outside"):
        sp.generated_files(tmp_path, set())


def test_the_steps_record_hides_local_paths(tmp_path):
    st = sp.Steps(tmp_path)
    st.run(
        "echo", ["sh", "-c", 'echo "$X"'], tmp_path, set_env={"X": str(tmp_path / "a")}
    )
    entry = st.entries[0]
    assert entry["cwd"] == "$SCRATCH"
    assert entry["env"] == {"X": "$SCRATCH/a"}
    assert entry["exit_code"] == 0
    with pytest.raises(sp.DataError):
        st.run("fail", ["sh", "-c", "exit 3"], tmp_path)
    assert st.entries[1]["exit_code"] == 3


# The generator.


def test_the_generator_facts():
    gen = OUT["generator"]
    assert set(gen["scripts"]) == set(sp.GENERATOR_SCRIPTS)
    assert {"Ref", "Sequence", "OneOf", "Delimited", "Bracketed", "Conditional"} <= set(
        gen["grammar_classes"]
    )
    assert "_library" in gen["private_attributes"]
    assert gen["dialect_files_with_custom_match"] == []
    assert 0 < gen["rust_emitter_lines"] < gen["table_builder_lines"]
    reuse = OUT["option3_reuse"]
    assert reuse["kind"].startswith("judgement")
    assert reuse["facts"]["runs_outside_the_submodule"] is True
    assert reuse["facts"]["deterministic"] is True


# The status file and the decision record.


def test_the_s3_status_file_and_the_decision_record_have_t5():
    status = (REPO_ROOT / "status" / "S3.md").read_text("utf8")
    row = next(line for line in status.splitlines() if line.startswith("| T5 |"))
    assert "Not started" not in row
    assert "results/s3/sqlfluffrs-probe.json" in status
    fx = OUT["fixtures"]["total"]
    assert f"{fx['pass']} of {fx['cases']}" in status
    decision = (REPO_ROOT / "docs" / "decisions" / "s3-base.md").read_text("utf8")
    c4 = next(line for line in decision.splitlines() if line.startswith("| C4 |"))
    assert "`results/s3/sqlfluffrs-probe.json`" in c4
    assert "scripts/s3/sqlfluffrs_probe.py" in c4


def test_the_status_numbers_are_those_of_the_report():
    status = (REPO_ROOT / "status" / "S3.md").read_text("utf8")
    summary = OUT["speed"]["summary"]
    for group in ("start", "parse/small", "parse/medium", "parse/large"):
        ratio = summary[group]["probe_over_sqruff"]["median_ratio"]
        assert re.search(rf"\| {re.escape(group)} \|.*\| {ratio:.3f} \|", status), group
