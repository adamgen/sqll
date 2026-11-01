"""S3 T18: the native tests of the base and the list check of sqll
(scripts/s3/base_native_tests.py).

The record results/s3/base-native-tests.json has each native test of the
base (sqlfluffrs 4.4.0) and its result. The check of CI and scripts/verify
runs cargo test of sqll and fails closed if a base test that passes in the
base is not in sqll or does not pass there. These tests check the record
and the check on synthetic cargo test output.
"""

import hashlib
import importlib.util
import json
import re

import pytest
import yaml

from sqll_harness.paths import REPO_ROOT

spec = importlib.util.spec_from_file_location(
    "base_native_tests", REPO_ROOT / "scripts" / "s3" / "base_native_tests.py"
)
bnt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bnt)

RECORD = json.loads(bnt.RECORD_FILE.read_text("utf8"))
COMMIT = "0348222a3bcdb0226563f7349c5a39beb0641955"
CHECK = "uv run --frozen --project harness python scripts/s3/base_native_tests.py check"


def test_the_record_is_a_full_run_of_the_pinned_base():
    assert RECORD["kind"] == bnt.KIND
    assert RECORD["base"]["commit"] == COMMIT
    assert RECORD["base"]["tag"] == "4.4.0"
    assert RECORD["base"]["packages"] == list(bnt.BASE_PACKAGES)
    assert RECORD["cargo_test"]["argv"] == bnt.CARGO_TEST_BASE
    assert RECORD["cargo_test"]["exit_code"] == 0
    assert RECORD["python_shim_calls"] == []
    assert RECORD["generation"]["files"] == 85
    assert RECORD["generation"]["python"]["sqlfluff_version"] == "4.4.0"
    assert RECORD["harness"]["clean"] is True
    for step in RECORD["steps"]:
        assert step["exit_code"] == 0, step["step"]
    first, last = RECORD["steps"][0], RECORD["steps"][-1]
    assert first["argv"][0] == last["argv"][0] == "$REPO/scripts/check-submodule"
    assert "cargo test of the base" in [s["step"] for s in RECORD["steps"]]


def test_the_record_agrees_with_its_log():
    log = (REPO_ROOT / RECORD["cargo_test"]["log"]).read_text("utf8")
    assert (
        hashlib.sha256(log.encode()).hexdigest() == RECORD["cargo_test"]["log_sha256"]
    )
    parsed = bnt.parse_output(log)
    assert parsed["problems"] == []
    assert parsed["tests"] == RECORD["tests"]
    assert [u["unit"] for u in parsed["units"]] == [u["unit"] for u in RECORD["units"]]
    assert RECORD["totals"] == bnt.totals(RECORD["tests"])
    assert sum(u["tests"] for u in RECORD["units"]) == len(RECORD["tests"])


def test_the_record_numbers():
    assert RECORD["totals"] == {"tests": 162, "passed": 162, "failed": 0, "ignored": 0}
    units = {u["unit"]: u["tests"] for u in RECORD["units"]}
    assert units["test fixture_tests"] == 60
    assert units["unittests sqlfluffrs_parser"] == 21
    assert units["unittests sqlfluffrs_rules"] == 0
    # Each unit has a port in sqll.
    for u in RECORD["units"]:
        assert u["sqll_unit"] == bnt.sqll_unit(u["unit"]) is not None


# Synthetic cargo test output of sqll.

DEPS = "target/debug/deps"
HASH = "0123456789abcdef"


def render(tests: list[dict], units: list[str]) -> str:
    """cargo test output (stderr merged into stdout) for these tests."""
    marks = {"passed": "ok", "failed": "FAILED", "ignored": "ignored"}
    out = []
    for unit in units:
        kind, name = unit.split(" ", 1)
        mine = [t for t in tests if t["unit"] == unit]
        if kind == "unittests":
            out.append(f"     Running unittests src/lib.rs ({DEPS}/{name}-{HASH})")
        elif kind == "test":
            out.append(f"     Running tests/{name}.rs ({DEPS}/{name}-{HASH})")
        else:
            out.append(f"   Doc-tests {name}")
        out += ["", f"running {len(mine)} test{'' if len(mine) == 1 else 's'}"]
        out += [f"test {t['name']} ... {marks[t['result']]}" for t in mine]
        n = {r: sum(1 for t in mine if t["result"] == r) for r in marks}
        status = "FAILED" if n["failed"] else "ok"
        out += [
            "",
            f"test result: {status}. {n['passed']} passed; {n['failed']} failed;"
            f" {n['ignored']} ignored; 0 measured; 0 filtered out; finished in 0.01s",
            "",
        ]
    return "\n".join(out) + "\n"


def sqll_tests() -> tuple[list[dict], list[str]]:
    """The tests of the record as sqll names them, all passed, and 1 more."""
    tests = [
        {"unit": bnt.sqll_unit(t["unit"]), "name": t["name"], "result": "passed"}
        for t in RECORD["tests"]
    ]
    tests.append({"unit": "test cli", "name": "a_new_sqll_test", "result": "passed"})
    units = list(dict.fromkeys([bnt.sqll_unit(u["unit"]) for u in RECORD["units"]]))
    return tests, units + ["test cli"]


def check(text: str) -> list[str]:
    return bnt.compare(RECORD, bnt.parse_output(text))


def test_the_check_passes_when_sqll_has_each_base_test():
    tests, units = sqll_tests()
    assert check(render(tests, units)) == []


def _remove_test(tests, units):
    name = next(t for t in tests if t["unit"] == "test fixture_tests")["name"]
    return [t for t in tests if t["name"] != name], units


def _remove_unit_test(tests, units):
    gone = next(t for t in tests if t["unit"] == "unittests sqll_parser")
    return [t for t in tests if t is not gone], units


def _fail_test(tests, units):
    tests[0] = {**tests[0], "result": "failed"}
    return tests, units


def _ignore_test(tests, units):
    tests[-2] = {**tests[-2], "result": "ignored"}
    return tests, units


def _rename_test(tests, units):
    tests[3] = {**tests[3], "name": tests[3]["name"] + "_x"}
    return tests, units


def _remove_unit(tests, units):
    return [t for t in tests if t["unit"] != "test yaml_compare"], [
        u for u in units if u != "test yaml_compare"
    ]


def _no_tests(tests, units):
    return [], []


MUTATIONS = {
    "a removed test of fixture_tests": _remove_test,
    "a removed unit test of sqll_parser": _remove_unit_test,
    "a failed test": _fail_test,
    "an ignored test": _ignore_test,
    "a renamed test": _rename_test,
    "a removed test binary": _remove_unit,
    "no test": _no_tests,
}


@pytest.mark.parametrize("name", MUTATIONS)
def test_the_check_fails_for_a_changed_test_list(name):
    tests, units = MUTATIONS[name](*sqll_tests())
    assert check(render(tests, units)), name


TEXT_MUTATIONS = {
    "no test result line": lambda s: re.sub(r"(?m)^test result: .*\n", "", s, count=1),
    "a count that does not agree": lambda s: s.replace(
        "running 60 tests", "running 61 tests"
    ),
    "a filtered test": lambda s: s.replace("0 filtered out", "1 filtered out", 1),
    "a test line twice": lambda s: re.sub(
        r"(?m)^(test test_ansi_fixtures \.\.\. ok\n)", r"\1\1", s
    ),
    "a test binary twice": lambda s: s + s[: s.index("\n     Running", 10)] + "\n",
}


@pytest.mark.parametrize("name", TEXT_MUTATIONS)
def test_the_check_fails_closed_on_output_that_does_not_agree(name):
    text = render(*sqll_tests())
    assert check(text) == []
    changed = TEXT_MUTATIONS[name](text)
    assert changed != text
    assert check(changed), name


def test_main_check_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.log"
    good.write_text(render(*sqll_tests()), encoding="utf8")
    assert bnt.main(["check", "--log", str(good)]) == 0
    assert "PASS: 162 base tests pass in the base" in capsys.readouterr().out
    bad = tmp_path / "bad.log"
    bad.write_text(render(*_remove_test(*sqll_tests())), encoding="utf8")
    assert bnt.main(["check", "--log", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "not in sqll" in out and "FAIL" in out


def test_doc_test_names_do_not_have_the_line_number():
    seen: dict[str, int] = {}
    assert bnt.doc_name("src/a.rs - f (line 10)", seen) == "src/a.rs - f"
    assert bnt.doc_name("src/a.rs - f (line 20)", seen) == "src/a.rs - f #2"


def test_ci_runs_the_check_in_the_build_job():
    ci = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text("utf8"))
    runs = [s.get("run", "") for s in ci["jobs"]["build"]["steps"]]
    assert CHECK in runs
    assert not any(r.strip().startswith("cargo test") for r in runs)
    assert bnt.CARGO_TEST_SQLL == ["cargo", "test", "--locked", "--no-fail-fast"]
