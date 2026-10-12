import json

import pytest

from sqll_harness import cli, known_failures
from sqll_harness.adapters.sqlfluff import SqlfluffAdapter
from sqll_harness.cases import FAIL, PASS, CaseResult


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
    }


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
