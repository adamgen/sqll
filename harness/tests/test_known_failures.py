import json

import pytest

from sqll_harness import cli, known_failures, report
from sqll_harness.adapters.sqlfluff import SqlfluffAdapter
from sqll_harness.cases import ERROR, FAIL, PASS, SKIP, CaseResult


def _r(case_id: str, status: str) -> CaseResult:
    return CaseResult(id=case_id, suite="dialects", tool="t", status=status)


def test_parse_reads_ids_and_reasons():
    text = "# header\n\ndialects/a/x  # tree differs\ndialects/b/y\n"
    assert known_failures.parse(text) == {
        "dialects/a/x": "tree differs",
        "dialects/b/y": "",
    }


def test_parse_rejects_unsorted_ids():
    with pytest.raises(known_failures.KnownFailuresError):
        known_failures.parse("dialects/b/y\ndialects/a/x\n")


def test_parse_rejects_duplicate_ids():
    with pytest.raises(known_failures.KnownFailuresError):
        known_failures.parse("dialects/a/x\ndialects/a/x\n")


def test_listed_failure_is_ok():
    out = known_failures.evaluate(
        [_r("dialects/a/x", FAIL)], {"dialects/a/x": ""}, {"dialects"}
    )
    assert out.ok


def test_new_failure():
    out = known_failures.evaluate([_r("dialects/a/x", FAIL)], {}, {"dialects"})
    assert not out.ok
    assert [r.id for r in out.new_failures] == ["dialects/a/x"]


def test_unexpected_pass():
    out = known_failures.evaluate(
        [_r("dialects/a/x", PASS)], {"dialects/a/x": ""}, {"dialects"}
    )
    assert out.unexpected_passes == ["dialects/a/x"]
    assert "t: unexpected pass: dialects/a/x" in out.messages("t")


def test_fake_id_is_reported_for_complete_suite_only():
    known = {"dialects/fake/case": ""}
    out = known_failures.evaluate([_r("dialects/a/x", PASS)], known, {"dialects"})
    assert out.not_found == ["dialects/fake/case"]
    assert any("unexpected pass: dialects/fake/case" in m for m in out.messages("t"))
    assert known_failures.evaluate([_r("dialects/a/x", PASS)], known, set()).ok


def test_id_with_unknown_suite_is_reported_when_every_case_ran():
    known = {"dialect/ansi/x": "", "fake_case": ""}
    results = [_r("dialects/a/x", PASS)]
    out = known_failures.evaluate(results, known, {"dialects"}, every_case_ran=True)
    assert out.not_found == ["dialect/ansi/x", "fake_case"]
    assert "t: unexpected pass: fake_case (no such case; remove it from the list)" in (
        out.messages("t")
    )
    assert known_failures.evaluate(results, known, {"dialects"}).ok


needs_sqlfluff = pytest.mark.skipif(
    not SqlfluffAdapter().binary.exists(),
    reason="sqlfluff tool venv is not installed; run scripts/test",
)


@needs_sqlfluff
def test_cli_exits_non_zero_on_listed_passing_case(tmp_path, capsys):
    case_id = "dialects/ansi/select_simple_a"
    (tmp_path / "sqlfluff.txt").write_text(case_id + "\n")
    out = tmp_path / "report.json"
    rc = cli.main(
        [
            "run",
            "--tool=sqlfluff",
            "--suite=dialects",
            f"--filter={case_id}",
            f"--known-failures={tmp_path}",
            f"--out={out}",
        ]
    )
    assert rc == 1
    assert f"sqlfluff: unexpected pass: {case_id}" in capsys.readouterr().out
    rep = json.loads(out.read_text())
    assert rep["known_failures"]["sqlfluff"]["unexpected_passes"] == [case_id]


@needs_sqlfluff
def test_cli_passes_with_empty_list(tmp_path, capsys):
    out = tmp_path / "report.json"
    rc = cli.main(
        [
            "run",
            "--tool=sqlfluff",
            "--filter=dialects/ansi/select_simple_",
            f"--known-failures={tmp_path}",
            f"--out={out}",
        ]
    )
    assert rc == 0
    rep = json.loads(out.read_text())
    assert set(rep) >= {"sqlfluff_ref", "tools", "summary", "cases"}
    s = rep["summary"]["dialects"]["sqlfluff"]
    assert s["total"] == s["passed"] == s["exact"] == s["no_unparsable"] > 0
    case = rep["cases"][0]
    assert set(case) == {
        "id",
        "suite",
        "tool",
        "status",
        "checks",
        "reason",
        "duration_ms",
        "tags",
    }
    assert case["tags"] == []


class _EmptySuite:
    NAME = "dialects"

    @staticmethod
    def discover(root):
        return []


@needs_sqlfluff
@pytest.mark.parametrize("case_id", ["fake_case", "dialect/ansi/x"])
def test_cli_full_run_reports_id_with_unknown_suite(
    tmp_path, capsys, monkeypatch, case_id
):
    monkeypatch.setattr(cli, "SUITES", {"dialects": _EmptySuite})
    (tmp_path / "sqlfluff.txt").write_text(case_id + "\n")
    rc = cli.main(
        [
            "run",
            "--tool=sqlfluff",
            f"--known-failures={tmp_path}",
            f"--out={tmp_path / 'report.json'}",
        ]
    )
    assert rc == 1
    assert f"sqlfluff: unexpected pass: {case_id} (no such case" in (
        capsys.readouterr().out
    )


def test_shard_reports_only_its_own_listed_ids():
    from sqll_harness import shard

    ids = [f"dialects/x/{i}" for i in range(20)]
    known = dict.fromkeys(ids, "")
    for k in (1, 2, 3):
        out = known_failures.evaluate([], known, {"dialects"}, shard=(k, 3))
        assert out.not_found == [i for i in ids if shard.index(i, 3) == k]


def test_skipped_case_is_not_a_failure():
    out = known_failures.evaluate([_r("dialects/a/x", SKIP)], {}, {"dialects"})
    assert out.ok


def test_listed_skipped_case_is_reported():
    out = known_failures.evaluate(
        [_r("dialects/a/x", SKIP)], {"dialects/a/x": ""}, {"dialects"}
    )
    assert out.unexpected_passes == ["dialects/a/x"]


def test_summary_counts_skipped_cases():
    results = [_r("a", PASS), _r("b", FAIL), _r("c", ERROR), _r("d", SKIP)]
    summary = report.summarize(results)["dialects"]["t"]
    assert summary == {"total": 4, "passed": 1, "failed": 2, "skipped": 1}


def test_summary_check_order_does_not_depend_on_case_order():
    a = CaseResult("a", "rules", "t", PASS, checks={"pass_str": True})
    b = CaseResult("b", "rules", "t", PASS, checks={"fail_str": True, "fix": True})
    for results in ([a, b], [b, a]):
        summary = report.summarize(results)["rules"]["t"]
        assert list(summary) == [
            "total",
            "passed",
            "failed",
            "skipped",
            "fail_str",
            "fix",
            "pass_str",
        ]


@pytest.mark.parametrize(
    "reason, prefix",
    [
        ("unsupported: setting rules.indent_unit", "unsupported: setting"),
        ("unsupported: rule CV13", "unsupported: rule"),
        ("unsupported: dialect soql", "unsupported: dialect"),
        ("unsupported: output field end_line_no (x)", "unsupported: output field"),
        ("unsupported: upper-case key a.B (x)", "unsupported: upper-case key"),
        (
            "unsupported: comment character '#' in a.b (x)",
            "unsupported: comment character",
        ),
        ("unsupported: something new", "unsupported:"),
        ("tree differs; unparsable segment", "tree differs"),
        ("fail_str: no violation of LT01; fix mismatch", "fail_str"),
        ("parse: exit code 1: x", "parse"),
        ("", "no reason"),
    ],
)
def test_reason_prefix(reason, prefix):
    assert known_failures.reason_prefix(reason) == prefix


def test_render_and_counts():
    results = [
        CaseResult("rules/b/x", "rules", "t", FAIL, reason="fix mismatch"),
        CaseResult(
            "dialects/a/x", "dialects", "t", ERROR, reason="a\nb  c: " + "x" * 400
        ),
        CaseResult("dialects/a/y", "dialects", "t", PASS),
        CaseResult("dialects/a/z", "dialects", "t", SKIP),
        CaseResult("rules/a/x", "rules", "t", FAIL, reason="fix mismatch; b"),
        CaseResult("rules/c/x", "rules", "t", FAIL),
    ]
    text = known_failures.render(results)
    lines = text.splitlines()
    assert [line.split()[0] for line in lines] == [
        "dialects/a/x",
        "rules/a/x",
        "rules/b/x",
        "rules/c/x",
    ]
    assert lines[0].startswith("dialects/a/x  # a b c: xxx")
    assert lines[0].endswith("...") and len(lines[0]) < 330
    assert lines[3] == "rules/c/x"
    # The file is valid.
    assert list(known_failures.parse(text)) == [line.split()[0] for line in lines]
    assert known_failures.prefix_counts(results) == {
        "a b c": {"dialects": 1},
        "fix mismatch": {"rules": 2},
        "no reason": {"rules": 1},
    }


def test_render_removes_volatile_panic_text():
    reason = (
        "lint: exit code 101: thread 'main' (26037) panicked at /root/.cargo/"
        "registry/src/index.crates.io-1949cf8c6b5b557f/sqruff-lib-0.41.0/src/"
        "rules/references/rf05.rs:31:18:"
    )
    results = [CaseResult("rules/a/x", "rules", "t", ERROR, reason=reason)]
    assert known_failures.render(results) == (
        "rules/a/x  # lint: exit code 101: thread 'main' panicked at "
        "sqruff-lib-0.41.0/src/rules/references/rf05.rs:31:18:\n"
    )
