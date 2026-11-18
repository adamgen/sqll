"""The S9 report and check for sqll (docs/decisions/s9-corpus.md, "sqll
results", decisions 3 and 4): compared has only sqlfluff, sqlfluff[rs], and
sqruff; the check of a sqll result gives the direction of each change; and
"rebase --tool sqll" replaces only the sqll record and results of a
baseline. The reports are synthetic: the report builder of test_s9_report
and the stub tools of test_s9_run."""

import copy
import json
from pathlib import Path

import pytest
from test_s9_report import (
    OK0,
    TOOLS3,
    build,
    build3,
    entry,
    results,
    sqll_results,
    times,
)
from test_s9_run import TOOLS3 as STUBS3
from test_s9_run import Env, by_key, rebuild, retime

from sqll_harness.bench.timer import Measurement, Sample, sample_stats
from sqll_harness.corpus import __main__ as corpus_main
from sqll_harness.corpus import baseline, report
from sqll_harness.corpus import manifest as m
from sqll_harness.corpus import run as corpus_run

# compared (decision 4).


def test_compared_has_only_the_3_tools():
    assert report.COMPARED_TOOLS == ("sqlfluff", "sqlfluff-rs", "sqruff")
    rep = build3()
    assert report.check(rep) == []
    assert rep["compared"]["tools"] == ["sqlfluff", "sqruff"]
    assert set(rep["compared"]["results"]) == {"sqlfluff", "sqruff"}


def _without_sqll(rep: dict) -> dict:
    tools = {t: v for t, v in rep["tools"].items() if t != "sqll"}
    return build(
        results=[r for r in rep["results"] if r["tool"] != "sqll"],
        scope={"tools": sorted(tools), "shard": None},
        tools=tools,
    )


@pytest.mark.parametrize("sqll_a", ["ok", "invalid", "unsupported"])
def test_a_report_with_sqll_has_the_compared_of_the_report_with_no_sqll(sqll_a):
    """sqll does not change compared: not when it is ok, and not when it
    is not ok on a file where each other tool is ok (s/a.sql)."""
    rows = [r for r in results() + sqll_results() if r["file"] != "s/a.sql"]
    rows += [r for r in results() if r["file"] == "s/a.sql"]
    if sqll_a == "ok":
        rows.append(entry("s/a.sql", "sqll", "ok", s=times(0.35, 0.3), unparsable=OK0))
    elif sqll_a == "invalid":
        warmup = [Sample("warmup", 0.1, 0.1, 0.0, 10, 1, False)]
        rows.append(entry("s/a.sql", "sqll", "invalid", "warmup run: x", warmup))
    else:
        rows.append(entry("s/a.sql", "sqll", "unsupported", "unsupported: x"))
    with_sqll = build3(rows=rows)
    assert report.check(with_sqll) == []
    no_sqll = _without_sqll(with_sqll)
    assert report.check(no_sqll) == [] and "pairs" not in no_sqll
    assert with_sqll["compared"] == no_sqll["compared"] == build()["compared"]
    for key in ("tools", "files", "bytes", "results"):
        assert with_sqll["compared"][key] == no_sqll["compared"][key]
    assert with_sqll["compared"]["files"] == 1


def test_the_schema_check_fails_if_compared_names_sqll(monkeypatch):
    rep = copy.deepcopy(build3())
    rep["compared"]["tools"] = ["sqlfluff", "sqll", "sqruff"]
    errors = report.check(rep)
    assert any("compared: names ['sqll']" in e for e in errors), errors
    # The compared of the old rule (each tool of the report, sqll too).
    monkeypatch.setattr(report, "COMPARED_TOOLS", ("sqlfluff", "sqll", "sqruff"))
    old = build3()
    assert "sqll" in old["compared"]["results"]
    monkeypatch.undo()
    errors = report.check(old)
    assert any("compared: names ['sqll']" in e for e in errors), errors
    assert any(e.startswith("compared: not ") for e in errors), errors


def test_the_summary_names_the_compared_tools():
    lines = corpus_run.summary_lines(build3())
    want = "compared: 1 files where each of sqlfluff, sqruff is ok, 20000 bytes"
    assert want in lines
    only = build3({"sqll": TOOLS3["sqll"]})
    assert (
        "compared: no tool of sqlfluff, sqlfluff-rs, sqruff in the report"
        in corpus_run.summary_lines(only)
    )


# The direction of a changed sqll result (decision 3).


def result(file: str, tool: str, status: str, u: dict | None = None) -> dict:
    """A result entry with a valid form for its status."""
    if status == "ok":
        return entry(file, tool, "ok", s=times(0.35, 0.3), unparsable=OK0)
    if status in ("unparsable", "no_reference"):
        u = u or {"count": 1, "bytes": 8}
        why = "no reference: bad" if status == "no_reference" else "1 unparsable"
        return entry(file, tool, status, why, times(0.35, 0.3, 1), u)
    if status == "invalid":
        warmup = [Sample("warmup", 0.1, 0.1, 0.0, 10, 0, False)]
        return entry(file, tool, "invalid", "warmup run: no parse tree", warmup)
    return entry(file, tool, status, f"{status}: x")


def with_result(rep: dict, new: dict) -> dict:
    """Return the report (of build3) with new in place of its result."""
    rows = [
        r
        for r in rep["results"]
        if (r["file"], r["tool"]) != (new["file"], new["tool"])
    ]
    return build3(tools=rep["tools"], rows=[*rows, new])


ORDER = ["ok", "unparsable", "no_reference", "unsupported", "invalid", "error"]
# The statuses that a file can have: s/n.sql has no reference render, so
# its only timed status is no_reference.
RAW = ["ok", "unparsable", "unsupported", "invalid", "error"]
NOREF = ["no_reference", "unsupported", "invalid", "error"]
CHANGES = [
    (file, old, new)
    for file, statuses in (("s/a.sql", RAW), ("s/n.sql", NOREF))
    for old in statuses
    for new in statuses
    if old != new
]


def test_the_status_order_is_that_of_the_decision():
    assert list(baseline.ORDER) == ORDER
    assert sorted(baseline.ORDER) == sorted(report.STATUSES)


@pytest.mark.parametrize("file, old, new", CHANGES)
def test_each_status_change_of_sqll_fails_with_its_direction(file, old, new):
    base = with_result(build3(), result(file, "sqll", old))
    rep = with_result(base, result(file, "sqll", new))
    assert report.check(base) == [] and report.check(rep) == []
    errors = baseline.drift(rep, base)
    assert len(errors) == 1, errors
    want = "worse" if ORDER.index(new) > ORDER.index(old) else "better"
    assert errors[0].startswith(f"sqll {file}: status {new} (")
    assert f", baseline {old} (" in errors[0]
    assert f"; {want}; the new result is" in errors[0]


@pytest.mark.parametrize(
    "old, new, want",
    [
        ({"count": 2, "bytes": 10}, {"count": 2, "bytes": 9}, "better"),
        ({"count": 2, "bytes": 10}, {"count": 2, "bytes": 11}, "worse"),
        ({"count": 2, "bytes": 10}, {"count": 1, "bytes": 10}, "better"),
        ({"count": 2, "bytes": 10}, {"count": 3, "bytes": 10}, "worse"),
        # The bytes first, then the segments.
        ({"count": 2, "bytes": 10}, {"count": 5, "bytes": 9}, "better"),
        ({"count": 2, "bytes": 10}, {"count": 1, "bytes": 11}, "worse"),
    ],
)
def test_each_unparsable_change_of_sqll_fails_with_its_direction(old, new, want):
    base = with_result(build3(), result("s/a.sql", "sqll", "unparsable", old))
    rep = with_result(base, result("s/a.sql", "sqll", "unparsable", new))
    assert baseline.drift(rep, base) == [
        f"sqll s/a.sql: unparsable {new}, baseline {old}; {want}; the new result is "
        "not the sqlfluff result of the file (ok, unparsable {'count': 0, "
        "'bytes': 0})"
    ]
    # The same rule for no_reference (s/n.sql).
    base = with_result(build3(), result("s/n.sql", "sqll", "no_reference", old))
    rep = with_result(base, result("s/n.sql", "sqll", "no_reference", new))
    errors = baseline.drift(rep, base)
    assert len(errors) == 1 and f"; {want}; " in errors[0]


def test_the_message_says_if_the_new_result_is_the_sqlfluff_result():
    """sqlfluff is ok on s/a.sql and no_reference {3, 30} on s/n.sql."""
    base = with_result(build3(), result("s/a.sql", "sqll", "invalid"))
    errors = baseline.drift(build3(), base)
    assert errors == [
        "sqll s/a.sql: status ok (None), baseline invalid (warmup run: no parse "
        "tree); better; the new result is the sqlfluff result of the file"
    ]
    rep = with_result(base, result("s/a.sql", "sqll", "unparsable"))
    assert baseline.drift(rep, base)[0].endswith(
        "; better; the new result is not the sqlfluff result of the file (ok, "
        "unparsable {'count': 0, 'bytes': 0})"
    )
    u = {"count": 3, "bytes": 30}
    base = with_result(build3(), result("s/n.sql", "sqll", "invalid"))
    rep = with_result(base, result("s/n.sql", "sqll", "no_reference", u))
    assert baseline.drift(rep, base)[0].endswith(
        "; better; the new result is the sqlfluff result of the file"
    )
    rep = with_result(base, result("s/n.sql", "sqll", "no_reference"))
    assert baseline.drift(rep, base)[0].endswith(
        "; better; the new result is not the sqlfluff result of the file "
        "(no_reference, unparsable {'count': 3, 'bytes': 30})"
    )


def test_the_target_is_the_sqlfluff_result_of_the_report_else_of_the_baseline():
    two = {k: TOOLS3[k] for k in ("sqll", "sqruff")}
    base = build3()
    rep = with_result(build3(two), result("s/a.sql", "sqll", "invalid"))
    errors = baseline.drift(rep, base)
    assert errors == [
        "sqll s/a.sql: status invalid (warmup run: no parse tree), baseline ok "
        "(None); worse; the new result is not the sqlfluff result of the file "
        "(ok, unparsable {'count': 0, 'bytes': 0})"
    ]
    base2 = build3(two)
    errors = baseline.drift(rep, base2)
    assert errors[0].endswith("; worse; the file has no sqlfluff result")
    # The report has its own sqlfluff result (here also changed): the sqll
    # message uses it, not the sqlfluff result of the baseline.
    rep = with_result(rep, result("s/a.sql", "sqlfluff", "invalid"))
    assert baseline.drift(rep, base) == [
        "sqlfluff s/a.sql: status invalid (warmup run: no parse tree), baseline "
        "ok (None)",
        "sqll s/a.sql: status invalid (warmup run: no parse tree), baseline ok "
        "(None); worse; the new result is the sqlfluff result of the file",
    ]


@pytest.mark.parametrize(
    "edit, text",
    [
        (
            lambda t: t.update(version="0.2.0"),
            "tool sqll: version 0.2.0, baseline 0.1.0",
        ),
        (
            lambda t: t["settings"]["raw"]["core"].update(x=1),
            "tool sqll: the settings are not those of the baseline",
        ),
    ],
)
def test_a_changed_sqll_record_fails(edit, text):
    rep = copy.deepcopy(build3())
    edit(rep["tools"]["sqll"])
    assert baseline.drift(rep, build3()) == [text]


@pytest.mark.parametrize(
    "file, tool, new, want",
    [
        (
            "s/b.sql",
            "sqruff",
            "ok",
            "sqruff s/b.sql: status ok (None), baseline unparsable (1 unparsable "
            "segments (8 bytes))",
        ),
        (
            "s/a.sql",
            "sqlfluff",
            "invalid",
            "sqlfluff s/a.sql: status invalid (warmup run: no parse tree), "
            "baseline ok (None)",
        ),
    ],
)
def test_the_messages_of_the_other_tools_do_not_change(file, tool, new, want):
    rep = with_result(build3(), result(file, tool, new))
    assert baseline.drift(rep, build3()) == [want]
    u = {"count": 2, "bytes": 9}
    rep = with_result(build3(), result("s/b.sql", "sqruff", "unparsable", u))
    assert baseline.drift(rep, build3()) == [
        "sqruff s/b.sql: unparsable {'count': 2, 'bytes': 9}, baseline "
        "{'count': 1, 'bytes': 8}"
    ]


def test_drift_of_a_report_with_sqll_and_no_change_is_empty():
    assert baseline.drift(build3(), build3()) == []


# The check command and "rebase --tool sqll" on the full run of 3 stub tools.


@pytest.fixture(scope="module")
def run3(tmp_path_factory):
    """A full run of the 3 stub tools (sqll too), and a smoke run. Each
    report has a harness from a worktree with no change, as the reports of
    a controlled run: rebase refuses a report from a harness with changes
    (test_rebase_refuses_a_report_from_a_harness_with_changes)."""
    tmp = tmp_path_factory.mktemp("full3")
    with pytest.MonkeyPatch.context() as mp:
        env = Env(tmp, mp, STUBS3)
        codes = [
            env.run("all.json", "--profile", "full"),
            env.run("smoke.json", "--profile", "smoke"),
            env.run("shard.json", "--profile", "full", "--shard", "1/2"),
        ]
        reports = {name: env.load(f"{name}.json") for name in ("all", "smoke", "shard")}
        for rep in reports.values():
            rep["harness"]["clean"] = True
        return {"env": env, "codes": codes, **reports}


@pytest.fixture
def env3(run3, monkeypatch):
    assert run3["codes"] == [0, 0, 0]
    run3["env"].patch(monkeypatch)
    return run3


@pytest.fixture
def base3(env3, tmp_path) -> Path:
    """The full run of the 3 stub tools as a recorded baseline."""
    rep = copy.deepcopy(env3["all"])
    rep["harness"]["clean"] = True
    path = tmp_path / "base.json"
    report.write(rep, path)
    return path


def set_status(rep: dict, path: str, tool: str, status: str, u=None) -> dict:
    """Return rep with a new status (and unparsable data) of one result. The
    samples of the result give the new samples."""
    results = copy.deepcopy(rep["results"])
    i = next(
        n
        for n, r in enumerate(results)
        if (r["file"], r["tool"]) == (f"demo/{path}", tool)
    )
    old = results[i]
    code = {"ok": 0, "unparsable": 1}.get(status, 0)
    s = [Sample(**{**x, "exit_code": code}) for x in old["samples"]]
    if status == "invalid":
        s = s[:1]
    elif status not in report.TIMED_STATUSES:
        s = []
    if status in report.TIMED_STATUSES and not any(x.kind == "timed" for x in s):
        s = [Sample("warmup", 0.1, 0.1, 0.0, 10, code, False)] + [
            Sample("timed", 0.1, 0.1, 0.0, 10, code, False)
        ] * 2
    timed = [x for x in s if x.kind == "timed"]
    reason = None if status == "ok" else f"{status}: test"
    if status == "ok":
        u = {"count": 0, "bytes": 0}
    m = Measurement(status, reason, s, sample_stats(timed) if timed else None)
    results[i] = report.result_entry(
        old["file"],
        rep["inputs"][old["file"]]["bytes"],
        tool,
        status,
        reason,
        m,
        u if status in report.TIMED_STATUSES else None,
    )
    return rebuild(rep, results=results)


def write(env3, rep: dict, name: str) -> Path:
    path = env3["env"].tmp / name
    report.write(rep, path)
    return path


def test_check_fails_on_each_changed_sqll_result_with_its_direction(
    env3, base3, capsys
):
    rep = set_status(env3["all"], "sql/ok.sql", "sqll", "invalid")
    rep = set_status(rep, "sql/unparsable.sql", "sqll", "ok")
    path = write(env3, rep, "changed.json")
    assert env3["env"].main("check", path, "--baseline", base3, "--full") == 1
    out = capsys.readouterr().out
    assert (
        "sqll demo/sql/ok.sql: status invalid (invalid: test), baseline ok (None); "
        "worse; the new result is not the sqlfluff result of the file (ok, "
        "unparsable {'count': 0, 'bytes': 0})"
    ) in out
    assert (
        "sqll demo/sql/unparsable.sql: status ok (None), baseline unparsable (2 "
        "unparsable segments ("
    ) in out
    assert "; better; the new result is not the sqlfluff result of the file " in out
    assert "FAIL: " in out and "has 2 errors." in out


def test_check_passes_on_the_same_sqll_results_with_other_timings(env3, base3, capsys):
    path = write(env3, retime(env3["all"], 2.0), "slow.json")
    assert env3["env"].main("check", path, "--baseline", base3, "--full") == 0
    assert "is that of the baseline" in capsys.readouterr().out


def rebase(env3, base: Path, rep: Path, out: Path) -> int:
    return env3["env"].main("rebase", "--tool", "sqll", base, rep, "--out", out)


def test_rebase_replaces_only_the_sqll_record_and_results(env3, base3, capsys):
    old = report.load(base3)
    rep = retime(env3["all"], 3.0)
    rep = set_status(rep, "sql/ok.sql", "sqll", "invalid")
    rep = set_status(rep, "sql/unparsable.sql", "sqll", "ok")
    rep = set_status(
        rep, "sql/unparsable0.sql", "sqll", "unparsable", {"count": 1, "bytes": 3}
    )
    # A copy: rebuild() keeps the tool records of the module fixture run3.
    rep = copy.deepcopy(rep)
    rep["tools"]["sqll"]["version"] = "1.1"
    rep["tools"]["sqll"]["settings"]["raw"]["core"]["x"] = 1
    rep = rebuild(rep)
    path = write(env3, rep, "new.json")
    out = env3["env"].tmp / "rebased.json"
    assert rebase(env3, base3, path, out) == 0
    text = capsys.readouterr().out.splitlines()
    new = report.load(out)
    assert report.check(new) == []
    assert baseline.recorded(new, m.load(env3["env"].manifest)) == []
    # Only the sqll record and the sqll results come from the report.
    assert new["tools"]["sqll"] == rep["tools"]["sqll"]
    assert {t: v for t, v in new["tools"].items() if t != "sqll"} == {
        t: v for t, v in old["tools"].items() if t != "sqll"
    }
    mine = [r for r in new["results"] if r["tool"] == "sqll"]
    assert mine == [r for r in rep["results"] if r["tool"] == "sqll"]
    others = [r for r in new["results"] if r["tool"] != "sqll"]
    assert others == [r for r in old["results"] if r["tool"] != "sqll"]
    for key in ("sqlfluff_ref", "harness", "profile", "policy", "machine", "timer"):
        assert new[key] == old[key], key
    for key in ("manifest_sha256", "scope", "inputs", "parts"):
        assert new[key] == old[key], key
    # totals, compared, and pairs are calculated again.
    assert new["totals"] == report.totals(new["results"], new["tools"])
    assert new["totals"]["sqll"] != old["totals"]["sqll"]
    assert new["compared"] == old["compared"]
    assert new["pairs"] == report.pairs(new["results"], new["tools"], new["inputs"])
    assert new["pairs"] != old["pairs"]
    # Each changed sqll result, with its direction.
    assert text == [
        "tool sqll: version 1.0 -> 1.1",
        "tool sqll: the settings changed",
        "sqll demo/sql/ok.sql: ok (unparsable {'count': 0, 'bytes': 0}) -> "
        "invalid (unparsable None): worse; the new result is not the sqlfluff "
        "result of the file (ok, unparsable {'count': 0, 'bytes': 0})",
        "sqll demo/sql/unparsable.sql: unparsable (unparsable "
        f"{_u(old, 'sql/unparsable.sql')}) -> ok (unparsable {{'count': 0, "
        "'bytes': 0}): better; the new result is not the sqlfluff result of the "
        f"file (unparsable, unparsable {_u(old, 'sql/unparsable.sql')})",
        "sqll demo/sql/unparsable0.sql: unparsable (unparsable "
        f"{_u(old, 'sql/unparsable0.sql')}) -> unparsable (unparsable "
        "{'count': 1, 'bytes': 3}): better; the new result is not the sqlfluff "
        f"result of the file (unparsable, unparsable "
        f"{_u(old, 'sql/unparsable0.sql')})",
        harness_line(path, out, base3, rep, old),
        f"{out}: the baseline {base3} with the sqll record and results of {path}; "
        "3 sqll results changed.",
    ]
    # The new baseline passes the check of the report it came from.
    assert env3["env"].main("check", path, "--baseline", out, "--full") == 0


def harness_line(path: Path, out: Path, base: Path, rep: dict, old: dict) -> str:
    return (
        f"harness: the sqll results of {path} come from the harness commit "
        f"{rep['harness']['commit']} (clean); {out} keeps the harness record of "
        f"{base} (commit {old['harness']['commit']})."
    )


def _u(rep: dict, path: str) -> dict:
    return by_key(rep)[(path, "sqll")]["unparsable"]


def test_rebase_with_no_change_changes_no_result(env3, base3, capsys):
    rep = retime(env3["all"], 0.5)
    path = write(env3, rep, "same.json")
    out = env3["env"].tmp / "same-rebased.json"
    assert rebase(env3, base3, path, out) == 0
    assert capsys.readouterr().out.splitlines() == [
        harness_line(path, out, base3, rep, report.load(base3)),
        f"{out}: the baseline {base3} with the sqll record and results of {path}; "
        "0 sqll results changed.",
    ]
    new, old = report.load(out), report.load(base3)
    assert [stable(r) for r in new["results"]] == [stable(r) for r in old["results"]]


def stable(r: dict) -> tuple:
    return r["file"], r["tool"], r["status"], r["unparsable"]


def _edit_sqlfluff_status(rep):
    return set_status(rep, "sql/ok.sql", "sqlfluff", "invalid")


def _edit_sqruff_version(rep):
    rep = copy.deepcopy(rep)
    rep["tools"]["sqruff"]["version"] = "2.0"
    return rebuild(rep)


def _edit_sqruff_settings(rep):
    rep = copy.deepcopy(rep)
    rep["tools"]["sqruff"]["settings"]["raw"]["core"]["x"] = 1
    return rebuild(rep)


def _edit_sqlfluff_ref(rep):
    rep = copy.deepcopy(rep)
    rep["sqlfluff_ref"] = "f" * 40
    return rebuild(rep)


def _edit_input(rep):
    inputs = copy.deepcopy(rep["inputs"])
    inputs["demo/sql/ok.sql"]["lines"] += 1
    return rebuild(rep, inputs=inputs)


def _edit_reference(rep):
    inputs = copy.deepcopy(rep["inputs"])
    inputs["demo/models/tmpl.sql"]["reference"]["sha256"] = "1" * 64
    return rebuild(rep, inputs=inputs)


def _drop_tool(rep):
    tools = {t: v for t, v in rep["tools"].items() if t != "sqruff"}
    rep = copy.deepcopy(rep)
    rep["tools"] = tools
    rep["scope"] = {"tools": sorted(tools), "shard": None}
    return rebuild(rep, results=[r for r in rep["results"] if r["tool"] != "sqruff"])


@pytest.mark.parametrize(
    "edit, text",
    [
        (_edit_sqlfluff_status, "report: sqlfluff demo/sql/ok.sql: status invalid"),
        (_edit_sqruff_version, "report: tool sqruff: version 2.0, baseline 1.0"),
        (_edit_sqruff_settings, "report: tool sqruff: the settings are not"),
        (_edit_sqlfluff_ref, "report: sqlfluff_ref"),
        (_edit_input, "report: input demo/sql/ok.sql: not the record of the manifest"),
        (_edit_reference, "report: input demo/models/tmpl.sql: reference {"),
        (_drop_tool, "report: scope"),
    ],
)
def test_rebase_fails_closed_on_a_change_to_another_tool_or_an_input(
    env3, base3, capsys, edit, text
):
    rep = set_status(env3["all"], "sql/ok.sql", "sqll", "invalid")
    path = write(env3, edit(rep), "bad.json")
    out = env3["env"].tmp / "never.json"
    assert rebase(env3, base3, path, out) == 1
    got = capsys.readouterr().out
    assert got.startswith("FAIL: ") and text in got, got
    assert not out.exists()


def test_rebase_fails_closed_on_another_profile_or_a_shard(env3, base3, capsys):
    out = env3["env"].tmp / "never.json"
    path = write(env3, env3["smoke"], "smoke-report.json")
    assert rebase(env3, base3, path, out) == 1
    assert "report: profile 'smoke', baseline 'full'" in capsys.readouterr().out
    path = write(env3, env3["shard"], "shard-report.json")
    assert rebase(env3, base3, path, out) == 1
    assert "report: scope " in capsys.readouterr().out
    assert not out.exists()


def _edit_policy(rep):
    rep = copy.deepcopy(rep)
    rep["policy"]["max_runs"] += 1
    return rebuild(rep)


def _edit_manifest_sha256(rep):
    rep = copy.deepcopy(rep)
    rep["manifest_sha256"] = "2" * 64
    return rebuild(rep)


@pytest.mark.parametrize(
    "edit, text, own",
    [
        (
            _edit_policy,
            "report: schema: policy: not the full policy",
            "report: policy {",
        ),
        (
            _edit_manifest_sha256,
            f"report: manifest_sha256 {'2' * 64} is not that of the manifest",
            f"report: manifest_sha256 '{'2' * 64}', baseline '",
        ),
    ],
)
def test_rebase_fails_closed_on_another_policy_or_manifest(
    env3, base3, capsys, monkeypatch, edit, text, own
):
    """The policy and the manifest of the report must be those of the
    baseline. The schema check and incomplete() see such a change first.
    The compare of rebase() itself also sees it if these checks find no
    error."""
    rep = edit(set_status(env3["all"], "sql/ok.sql", "sqll", "invalid"))
    path = env3["env"].tmp / "other.json"
    path.write_text(json.dumps(rep))
    out = env3["env"].tmp / "never.json"
    assert rebase(env3, base3, path, out) == 1
    got = capsys.readouterr().out
    assert got.startswith("FAIL: ") and text in got, got
    assert not out.exists()
    # The compare of rebase() alone, with no schema or completeness error.
    monkeypatch.setattr(report, "check", lambda rep: [])
    monkeypatch.setattr(corpus_run, "incomplete", lambda rep, manifest: [])
    with pytest.raises(baseline.RebaseError) as exc:
        baseline.rebase(report.load(base3), rep, "sqll", m.load(env3["env"].manifest))
    assert own in str(exc.value), str(exc.value)


def test_rebase_says_when_the_report_is_from_another_machine(env3, base3, capsys):
    """The new baseline keeps the baseline machine, and the first line says
    that its pairs compare sqll times of another machine."""
    rep = copy.deepcopy(env3["all"])
    rep["machine"] = {**rep["machine"], "cpu_model": "other CPU", "cpu_count": 64}
    rep = set_status(rebuild(rep), "sql/ok.sql", "sqll", "invalid")
    path = write(env3, rep, "machine.json")
    out = env3["env"].tmp / "machine-rebased.json"
    assert rebase(env3, base3, path, out) == 0
    text = capsys.readouterr().out.splitlines()
    old = report.load(base3)
    assert text[0] == (
        "machine: the report machine is not the baseline machine (cpu_count "
        f"{old['machine']['cpu_count']!r} -> 64, cpu_model "
        f"{old['machine']['cpu_model']!r} -> 'other CPU'); the sqll times come "
        "from that machine, and the pairs compare them with the times of "
        "the other tools from the baseline machine"
    )
    assert text[1].startswith("sqll demo/sql/ok.sql: ok ")
    assert text[-2] == harness_line(path, out, base3, rep, old)
    assert text[-1].endswith("; 1 sqll results changed.")
    assert report.load(out)["machine"] == old["machine"]


def test_rebase_says_when_a_shard_of_a_merged_report_is_from_another_machine(
    env3, base3, capsys
):
    """The machine of a merged report is that of its first shard. rebase
    also compares the machine of each other shard with the baseline
    machine."""
    rep = copy.deepcopy(env3["all"])
    other = {**rep["machine"], "cpu_model": "other CPU"}
    rep["parts"] = [
        {"shard": "1/2", "machine": rep["machine"], "timer": rep["timer"]},
        {"shard": "2/2", "machine": other, "timer": rep["timer"]},
    ]
    rep = set_status(rebuild(rep), "sql/ok.sql", "sqll", "invalid")
    assert report.check(rep) == []
    path = write(env3, rep, "merged.json")
    out = env3["env"].tmp / "merged-rebased.json"
    assert rebase(env3, base3, path, out) == 0
    text = capsys.readouterr().out.splitlines()
    old = report.load(base3)
    assert rep["machine"] == old["machine"]
    assert text[0] == (
        "machine: the machine of shard 2/2 is not the baseline machine "
        f"(cpu_model {old['machine']['cpu_model']!r} -> 'other CPU'); the sqll "
        "times of the shard come from that machine, and the pairs compare them "
        "with the times of the other tools from the baseline machine"
    )
    assert text[1].startswith("sqll demo/sql/ok.sql: ok ")
    assert not any(line.startswith("machine: ") for line in text[1:])
    # With the machine of the baseline in each shard, no machine line.
    rep["parts"][1]["machine"] = rep["machine"]
    path = write(env3, rebuild(rep), "merged-same.json")
    assert rebase(env3, base3, path, out) == 0
    text = capsys.readouterr().out.splitlines()
    assert not any(line.startswith("machine: ") for line in text)


def test_rebase_refuses_a_report_from_a_harness_with_changes(env3, base3, capsys):
    """The new baseline keeps the harness record of the baseline (clean).
    Thus a report from a harness worktree with changes cannot give it new
    sqll results: exit code 1 and no file, also with a changed sqll result
    and another harness commit."""
    rep = set_status(env3["all"], "sql/ok.sql", "sqll", "invalid")
    rep["harness"] = {"commit": "f" * 40, "clean": False}
    path = write(env3, rep, "dirty-report.json")
    out = env3["env"].tmp / "never.json"
    assert rebase(env3, base3, path, out) == 1
    got = capsys.readouterr().out
    assert got.startswith("FAIL: "), got
    assert (
        f"report: the harness worktree had changes (harness commit {'f' * 40})"
    ) in got
    assert not out.exists()
    with pytest.raises(baseline.RebaseError, match="the harness worktree had"):
        baseline.rebase(report.load(base3), rep, "sqll", m.load(env3["env"].manifest))
    # The same report from a harness with no change passes.
    rep["harness"]["clean"] = True
    path = write(env3, rep, "clean-report.json")
    out = env3["env"].tmp / "clean-rebased.json"
    assert rebase(env3, base3, path, out) == 0
    got = capsys.readouterr().out
    assert f"come from the harness commit {'f' * 40} (clean)" in got
    assert report.load(out)["harness"] == report.load(base3)["harness"]


def test_rebase_fails_closed_on_a_report_with_a_schema_error(env3, base3, capsys):
    rep = copy.deepcopy(env3["all"])
    rep["totals"]["sqll"]["ok"] += 1
    path = env3["env"].tmp / "schema.json"
    path.write_text(json.dumps(rep))
    out = env3["env"].tmp / "never.json"
    assert rebase(env3, base3, path, out) == 1
    assert "report: schema: totals: not" in capsys.readouterr().out
    assert not out.exists()


def test_rebase_needs_a_recorded_baseline_with_sqll(
    env3, capsys, tmp_path, monkeypatch
):
    out = tmp_path / "never.json"
    rep = copy.deepcopy(env3["all"])
    path = write(env3, rep, "report.json")
    # A baseline from a worktree with changes.
    rep["harness"]["clean"] = False
    dirty = tmp_path / "dirty.json"
    report.write(rep, dirty)
    assert rebase(env3, dirty, path, out) == 1
    assert "baseline: the harness worktree had changes" in capsys.readouterr().out
    # A recorded baseline with no sqll (sqll is in LATER).
    monkeypatch.setattr(corpus_run, "LATER", frozenset({"sqll"}))
    two = copy.deepcopy(rep)
    two["tools"] = {t: v for t, v in rep["tools"].items() if t != "sqll"}
    two["scope"] = {"tools": sorted(two["tools"]), "shard": None}
    two["harness"]["clean"] = True
    two = rebuild(two, results=[r for r in rep["results"] if r["tool"] != "sqll"])
    old = tmp_path / "two.json"
    report.write(two, old)
    assert baseline.recorded(two, m.load(env3["env"].manifest)) == []
    assert rebase(env3, old, path, out) == 1
    got = capsys.readouterr().out
    assert "baseline: no sqll results; a complete baseline needs one" in got
    assert not out.exists()


def test_rebase_takes_only_sqll(env3, base3, capsys):
    path = env3["env"].tmp / "x.json"
    with pytest.raises(SystemExit) as exc:
        env3["env"].main("rebase", "--tool", "sqruff", base3, path, "--out", path)
    assert exc.value.code == 2
    assert "invalid choice: 'sqruff'" in capsys.readouterr().err
    with pytest.raises(baseline.RebaseError, match="only the results of sqll"):
        baseline.rebase({}, {}, "sqruff", None)


def test_rebase_refuses_the_recorded_baseline_of_3_tools(capsys, tmp_path):
    """The recorded baseline has no sqll results (sqll is in LATER): rebase
    fails closed until a complete baseline of the 4 tools."""
    out = tmp_path / "never.json"
    code = corpus_main.main(
        [
            "rebase",
            "--tool",
            "sqll",
            str(baseline.BASELINE),
            str(baseline.BASELINE),
            "--out",
            str(out),
        ]
    )
    assert code == 1
    assert "baseline: no sqll results" in capsys.readouterr().out
    assert not out.exists()
