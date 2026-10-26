"""The recorded S2 baseline (results/s2/baseline.json), the drift check of
"sqll-harness bench check --baseline" (harness/bench.md, "Baseline"), and
the agreement of status/S2.md with the baseline."""

import copy
import json
import re
import subprocess
from collections import Counter

import pytest

from sqll_harness import cli
from sqll_harness.bench import baseline, definitions, registry, report
from sqll_harness.bench import run as bench_run
from sqll_harness.bench.timer import ERROR, INVALID, STATUSES, UNSUPPORTED, VALID
from sqll_harness.paths import REPO_ROOT

DEFS = definitions.load()
BASE = report.load(baseline.BASELINE)
TOOLS = ["sqlfluff", "sqlfluff-rs", "sqruff"]
VERSIONS = {"sqlfluff": "4.4.0", "sqlfluff-rs": "4.4.0", "sqruff": "0.41.0"}
SMOKE_SIZES = bench_run.PROFILE_SIZES["smoke"]


def bench(*args) -> int:
    return cli.main(["bench", *[str(a) for a in args]])


# The recorded baseline.


def test_the_baseline_is_a_full_run_of_all_tools():
    assert report.check(BASE) == []
    assert baseline.recorded(BASE, DEFS) == []
    assert BASE["profile"] == "full"
    assert BASE["parts"] is None and BASE["scope"]["shard"] is None
    assert BASE["scope"]["tools"] == TOOLS == registry.names()
    assert BASE["harness"]["clean"] is True
    assert re.fullmatch(r"[0-9a-f]{40}", BASE["harness"]["commit"])


def test_the_baseline_is_of_the_pinned_sqlfluff_and_tools():
    pin = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD:third_party/sqlfluff"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert BASE["sqlfluff_ref"] == DEFS["sqlfluff_ref"] == pin
    assert {t: BASE["tools"][t]["version"] for t in TOOLS} == VERSIONS
    for tool in TOOLS:
        assert BASE["tools"][tool]["settings"] == registry.get(tool).config(None)


def test_the_baseline_has_the_benchmarks_and_inputs_of_the_definitions():
    want = {b["id"]: b for b in DEFS["benchmarks"]}
    assert len(want) == 280
    for r in BASE["results"]:
        assert {k: r[k] for k in ("id", *baseline.BENCHMARK)} == want[r["id"]]
    assert sorted(BASE["inputs"]) == sorted(DEFS["inputs"])
    for name, record in BASE["inputs"].items():
        assert record["sha256"] == DEFS["inputs"][name]["sha256"], name
        assert record == {k: DEFS["inputs"][name][k] for k in report.INPUT}


def test_the_baseline_has_one_result_for_each_benchmark_and_tool():
    keys = Counter((r["id"], r["tool"]) for r in BASE["results"])
    assert set(keys.values()) == {1}
    assert set(keys) == {(b["id"], t) for b in DEFS["benchmarks"] for t in TOOLS}
    assert len(keys) == 280 * 3
    for r in BASE["results"]:
        assert r["status"] in STATUSES
        if r["status"] == VALID:
            assert r["stats"] is not None and r["reason"] is None
            assert 3 <= r["runs"]["timed"] <= 20
        else:
            assert r["stats"] is None and r["reason"], (r["id"], r["tool"])


# The drift check.


def _rebuild(rep: dict, **change) -> dict:
    fields = {
        k: rep[k]
        for k in (
            "sqlfluff_ref",
            "profile",
            "machine",
            "harness",
            "timer",
            "scope",
            "tools",
            "inputs",
            "results",
            "parts",
        )
    }
    return report.build(**{**copy.deepcopy(fields), **change})


def _part(sizes=SMOKE_SIZES) -> dict:
    """A report with the results of the baseline for start and these sizes:
    the benchmarks of a smoke run, with the stable data of the baseline."""
    scope = report.scope(BASE["scope"]["tools"], BASE["scope"]["dialects"], sizes=sizes)
    ids = {b["id"] for b in bench_run.expected(scope)}
    results = [r for r in BASE["results"] if r["id"] in ids]
    used = {r["input"] for r in results}
    inputs = {k: v for k, v in BASE["inputs"].items() if k in used}
    return _rebuild(BASE, scope=scope, results=results, inputs=inputs)


PART = _part()


def _result(rep: dict, tool: str, status: str) -> dict:
    return next(
        r for r in rep["results"] if r["tool"] == tool and r["status"] == status
    )


def _set_status(rep: dict) -> None:
    r = _result(rep, "sqruff", VALID)
    r.update(status=INVALID, reason="invalid: changed", stats=None)


def _set_sha(rep: dict) -> None:
    rep["inputs"]["ansi/small"]["sha256"] = "0" * 64


def _set_version(rep: dict) -> None:
    rep["tools"]["sqruff"]["version"] = "0.41.1"


def _set_settings(rep: dict) -> None:
    rep["tools"]["sqlfluff-rs"]["settings"]["core"]["use_rust_rules"] = False


def _set_ref(rep: dict) -> None:
    rep["sqlfluff_ref"] = "0" * 40


def _set_work(rep: dict) -> None:
    r = next(
        x
        for x in rep["results"]
        if x["status"] == VALID and x["command"] == "lint" and x["tool"] == "sqruff"
    )
    r["work"] = {**r["work"], "violations": r["work"]["violations"] + 1}


def _new_tool(rep: dict) -> None:
    rep["tools"]["sqll"] = rep["tools"].pop("sqruff")
    for r in rep["results"]:
        if r["tool"] == "sqruff":
            r["tool"] = "sqll"


def _new_result(rep: dict) -> None:
    extra = copy.deepcopy(rep["results"][0])
    extra["id"] += "-new"
    rep["results"].append(extra)


DRIFT = {
    "status": (
        _set_status,
        r"sqruff \S+: status invalid \(invalid: changed\), baseline valid",
    ),
    "input sha256": (_set_sha, r"input ansi/small: .*baseline"),
    "tool version": (_set_version, r"tool sqruff: version 0\.41\.1, baseline 0\.41\.0"),
    "tool settings": (_set_settings, r"tool sqlfluff-rs: the settings are not"),
    "sqlfluff ref": (_set_ref, r"sqlfluff_ref 0+, baseline"),
    "work": (_set_work, r"sqruff lint/\S+: work .*baseline"),
    "new tool": (_new_tool, r"tool sqll: not in the baseline"),
    "a result the baseline has not": (_new_result, r"-new: no result in the baseline"),
}


def test_the_part_of_the_baseline_has_no_drift():
    assert report.check(PART) == []
    assert bench_run.incomplete(PART, DEFS) == []
    assert baseline.drift(PART, BASE) == []
    assert len(PART["results"]) == 112 * 3


@pytest.mark.parametrize("name", DRIFT)
def test_drift_finds_each_change_of_the_stable_data(name):
    change, pattern = DRIFT[name]
    rep = copy.deepcopy(PART)
    change(rep)
    errors = baseline.drift(rep, BASE)
    assert errors
    assert any(re.search(pattern, e) for e in errors), errors


def test_drift_finds_a_result_that_the_baseline_does_not_have():
    base = copy.deepcopy(BASE)
    i = next(i for i, r in enumerate(base["results"]) if r["size"] == "small")
    gone = base["results"].pop(i)
    errors = baseline.drift(PART, base)
    assert errors == [f"{gone['tool']} {gone['id']}: no result in the baseline"]


def test_drift_does_not_compare_timings():
    rep = copy.deepcopy(PART)
    for r in rep["results"]:
        for s in r["samples"]:
            s["wall_s"] *= 3
    assert baseline.drift(rep, BASE) == []


@pytest.mark.parametrize(
    "change, match",
    [
        # The policy of the smoke profile is not that of the samples.
        (lambda b: b.update(profile="smoke"), "schema"),
        (lambda b: b["harness"].update(clean=False), "worktree had changes"),
        (lambda b: b["scope"]["tools"].remove("sqruff"), "schema"),
        (lambda b: b["results"].pop(), "schema"),
    ],
)
def test_a_report_that_is_not_a_full_baseline_is_refused(change, match):
    base = copy.deepcopy(BASE)
    change(base)
    assert any(match in e for e in baseline.recorded(base, DEFS))


def test_a_smaller_scope_is_not_a_full_baseline():
    errors = baseline.recorded(PART, DEFS)
    assert any(e.startswith("the scope is not all tools") for e in errors)
    assert "sqlfluff: the benchmark ids are not those of the definitions" in errors


# The CLI: "bench check REPORT --baseline FILE" (the CI step of bench-smoke).


def _write(tmp_path, rep: dict, name: str = "bench.json"):
    path = tmp_path / name
    path.write_text(json.dumps(rep))
    return path


def test_check_passes_with_the_data_of_the_baseline(tmp_path, capsys):
    path = _write(tmp_path, PART)
    assert bench("check", path, "--baseline", baseline.BASELINE) == 0
    out = capsys.readouterr().out
    assert f"The stable data of {112 * 3} results is that of the baseline" in out


@pytest.mark.parametrize(
    "change", [_set_status, _set_sha, _set_version], ids=["status", "sha", "version"]
)
def test_check_fails_if_the_stable_data_is_not_that_of_the_baseline(
    tmp_path, capsys, change
):
    rep = copy.deepcopy(PART)
    change(rep)
    rep = _rebuild(rep)
    if change is _set_sha:
        # The definitions check of "bench check" finds it first.
        path = _write(tmp_path, rep)
        assert bench("check", path, "--baseline", baseline.BASELINE) == 1
        assert (
            "input ansi/small: not that of the definitions" in capsys.readouterr().out
        )
        return
    assert report.check(rep) == []
    path = _write(tmp_path, rep)
    assert bench("check", path, "--baseline", baseline.BASELINE) == 1
    out = capsys.readouterr().out
    assert "FAIL:" in out


def test_check_fails_with_a_changed_baseline(tmp_path, capsys):
    base = copy.deepcopy(BASE)
    _set_version(base)
    base_path = _write(tmp_path, base, "baseline.json")
    path = _write(tmp_path, PART)
    assert bench("check", path, "--baseline", base_path) == 1
    assert "tool sqruff: version 0.41.0, baseline 0.41.1" in capsys.readouterr().out


def test_check_refuses_a_baseline_that_is_not_full(tmp_path, capsys):
    base_path = _write(tmp_path, PART, "baseline.json")
    path = _write(tmp_path, PART)
    assert bench("check", path, "--baseline", base_path) == 1
    assert "baseline: the scope is not all tools" in capsys.readouterr().out


def test_check_refuses_a_missing_baseline(tmp_path, capsys):
    path = _write(tmp_path, PART)
    assert bench("check", path, "--baseline", tmp_path / "none.json") == 2
    assert "error:" in capsys.readouterr().err


# status/S2.md and the STATUS.md index


INDEX = (REPO_ROOT / "STATUS.md").read_text(encoding="utf8")
STATUS = (REPO_ROOT / "status" / "S2.md").read_text(encoding="utf8")
COUNT_STATUSES = (VALID, INVALID, UNSUPPORTED, ERROR)


def _rows(header: str) -> list[list[str]]:
    """Return the cells of each row of the status/S2.md table with this header."""
    lines = STATUS.splitlines()
    start = lines.index(header)
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def _name(tool: str) -> str:
    return f"{tool} {BASE['tools'][tool]['version']}"


def test_status_says_s2_is_approved_and_names_the_baseline():
    assert (
        "| S2 | | Complete. The human owner approved it on 2026-10-26"
        " | [status/S2.md](status/S2.md) |"
    ) in INDEX
    assert "| S3 | S3 | In work: " in INDEX
    assert "**S2 complete**: the human owner approved it on 2026-10-26" in STATUS
    assert f"`{BASE['harness']['commit'][:7]}`" in STATUS
    assert "results/s2/baseline.json" in STATUS


def test_status_baseline_table_is_the_baseline():
    rows = _rows(
        "| Tool | Command | Valid | Invalid | Unsupported | Error "
        "| Wall time (s) | CPU time (s) |"
    )
    want = []
    for tool in TOOLS:
        for command in report.ALL_COMMANDS:
            mine = [
                r
                for r in BASE["results"]
                if r["tool"] == tool and r["command"] == command
            ]
            valid = [r for r in mine if r["status"] == VALID]
            counts = [sum(r["status"] == s for r in mine) for s in COUNT_STATUSES]
            times = [
                f"{sum(r['stats'][k]['median'] for r in valid):.1f}"
                for k in ("wall_s", "cpu_s")
            ]
            want.append([_name(tool), command, *map(str, counts), *times])
    assert rows == want


def test_status_pair_table_is_the_baseline():
    rows = _rows("| Tools | Benchmarks | Wall time (s) | Wall time ratio |")
    want = [
        [
            f"{_name(p['tools'][0])} / {_name(p['tools'][1])}",
            str(p["benchmarks"]),
            " / ".join(f"{w:.1f}" for w in p["wall_s"]),
            f"{p['wall_ratio']:.3f}",
        ]
        for p in BASE["pairs"]
    ]
    assert rows == want


def test_status_lists_each_result_that_is_not_valid_with_its_reason():
    rows = _rows("| Tool | Status | Reason (text) | Benchmarks |")
    by_key = {(r["tool"], r["id"]): r for r in BASE["results"]}
    listed = []
    for tool, status, text, ids in rows:
        assert text, (tool, status)
        for i in ids.split(", "):
            r = by_key[(tool, i.strip("`"))]
            assert r["status"] == status, (tool, i)
            assert text.strip("`") in r["reason"], (tool, i)
            listed.append((tool, r["id"]))
    assert len(listed) == len(set(listed))
    want = {(r["tool"], r["id"]) for r in BASE["results"] if r["status"] != VALID}
    assert set(listed) == want


# "bench check REPORT --baseline FILE --full" (the CI step of bench-merge).


def test_missing_finds_nothing_in_a_full_run():
    assert baseline.missing(BASE, BASE) == []


def test_missing_finds_each_result_that_a_run_does_not_have():
    lost = sorted(
        f"{r['tool']} {r['id']}"
        for r in BASE["results"]
        if r["size"] in ("medium", "large")
    )
    assert len(lost) == (280 - 112) * 3
    assert baseline.missing(PART, BASE) == [
        f"no result for {len(lost)} results of the baseline: "
        f"{', '.join(lost[:5])} and {len(lost) - 5} more"
    ]


def test_missing_finds_another_profile():
    rep = copy.deepcopy(BASE)
    rep["profile"] = "smoke"
    assert baseline.missing(rep, BASE) == ["profile smoke, baseline full"]


def test_check_full_passes_on_a_full_run(tmp_path, capsys):
    path = _write(tmp_path, BASE)
    assert bench("check", path, "--baseline", baseline.BASELINE, "--full") == 0
    out = capsys.readouterr().out
    assert f"The stable data of {280 * 3} results is that of the baseline" in out
    assert "The report has the profile and each result of the baseline." in out


def test_check_full_fails_on_a_part_of_the_baseline(tmp_path, capsys):
    path = _write(tmp_path, PART)
    assert bench("check", path, "--baseline", baseline.BASELINE, "--full") == 1
    out = capsys.readouterr().out
    assert f"no result for {(280 - 112) * 3} results of the baseline" in out
    assert "FAIL:" in out


def test_check_full_fails_on_a_status_change_of_a_large_input(tmp_path, capsys):
    rep = copy.deepcopy(BASE)
    r = next(
        x
        for x in rep["results"]
        if x["tool"] == "sqlfluff" and x["size"] == "large" and x["status"] == VALID
    )
    r.update(status=INVALID, reason="invalid: changed", stats=None, ratio=None)
    rep = _rebuild(rep)
    assert report.check(rep) == []
    path = _write(tmp_path, rep)
    assert bench("check", path, "--baseline", baseline.BASELINE, "--full") == 1
    out = capsys.readouterr().out
    assert f"sqlfluff {r['id']}: status invalid (invalid: changed)" in out


def test_check_full_needs_a_baseline(tmp_path, capsys):
    path = _write(tmp_path, BASE)
    assert bench("check", path, "--full") == 2
    assert "--full needs --baseline" in capsys.readouterr().err
