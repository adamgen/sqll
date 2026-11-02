"""S3 T20: the S3 exit record.

results/s3/exit.json is the output of scripts/s3/exit.py on the S2
baseline with the final sqll, the S1 summary, the T18 record, and the T14
record. The tests read each copied value again from its file and key,
compute the derived values again, and check the exit criteria, the exit
record docs/decisions/s3-exit.md, and the state in STATUS.md and
status/S3.md."""

import copy
import importlib.util
import json
import re

import pytest
from conftest import s3_record

from sqll_harness.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "s3_exit", REPO_ROOT / "scripts" / "s3" / "exit.py"
)
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

OUT = json.loads(ex.OUT_FILE.read_text("utf8"))
VALUES = OUT["values"]
INPUTS = {
    rel: json.loads((REPO_ROOT / rel).read_text("utf8")) for rel in ex.INPUTS.values()
}
RECORD = (REPO_ROOT / "docs" / "decisions" / "s3-exit.md").read_text("utf8")
INDEX = (REPO_ROOT / "STATUS.md").read_text("utf8")
STATUS = s3_record()
STATE = "S3 awaiting human approval"


def v(vid):
    return VALUES[vid]["value"]


def t(vid):
    return VALUES[vid]["text"]


def words(text: str) -> str:
    return " ".join(text.split())


def section(title: str) -> str:
    return RECORD.split(f"\n## {title}\n", 1)[1].split("\n## ", 1)[0]


# The drift test and the inputs.


def test_the_committed_output_is_the_output_of_the_committed_inputs():
    assert ex.main(["--check"]) == 0


@pytest.mark.parametrize(
    "old, new",
    [
        ('"T20"', '"T19"'),
        # A changed number: the sqruff pair count.
        ('"text": "108"', '"text": "107"'),
    ],
)
def test_the_check_fails_on_a_change(tmp_path, monkeypatch, old, new):
    text = ex.OUT_FILE.read_text("utf8")
    assert old in text
    out = tmp_path / "exit.json"
    out.write_text(text.replace(old, new, 1), "utf8")
    monkeypatch.setattr(ex, "OUT_FILE", out)
    assert ex.main(["--check"]) == 1


def test_the_inputs_are_the_committed_files():
    assert OUT["inputs"] == {
        rel: ex.sha256_file(REPO_ROOT / rel) for rel in ex.INPUTS.values()
    }


def _paths(tmp_path, name, change):
    paths = {k: REPO_ROOT / rel for k, rel in ex.INPUTS.items()}
    doc = copy.deepcopy(INPUTS[ex.INPUTS[name]])
    change(doc)
    paths[name] = tmp_path / f"{name}.json"
    paths[name].write_text(json.dumps(doc), "utf8")
    return paths


def _sqll(doc, bid):
    return next(r for r in doc["results"] if r["id"] == bid and r["tool"] == "sqll")


def test_a_changed_time_in_the_baseline_fails_closed(tmp_path):
    """The stats of a baseline result must be those of its samples, so a
    changed median is not a full baseline."""
    bid = v("g35.worst")["id"]

    def change(doc):
        _sqll(doc, bid)["stats"]["wall_s"]["median"] = v(f"time.{bid}.sqruff")

    with pytest.raises(ex.DataError, match="not a full baseline"):
        ex.make_report(_paths(tmp_path, "s2", change))


def test_a_slower_sqll_benchmark_is_not_met():
    """The criteria on the committed values with one sqll time set to the
    sqruff time (a tie is not faster)."""
    data = ex.load({k: REPO_ROOT / rel for k, rel in ex.INPUTS.items()})
    bid = v("g35.worst")["id"]
    _sqll(data["s2"], bid)["stats"]["wall_s"]["median"] = v(f"time.{bid}.sqruff")
    vs = ex.Values(data)
    ex.run_values(vs)
    ex.base_case_values(vs)
    rows = ex.benchmark_rows(vs)
    ex.speed_values(vs, rows)
    assert vs.v("g35.slower") == [bid]
    crit = {c["id"]: c for c in ex.criteria(vs)}
    assert crit["S3.exit.sqruff"]["met"] is False
    assert crit["S3.exit.base_cases"]["met"] is True


def test_another_sqll_in_the_s1_summary_fails(tmp_path):
    def change(doc):
        doc["tools"]["sqll"]["version"] = "0.1.0+tables." + "0" * 64

    with pytest.raises(ex.DataError, match="is not the sqll of the baseline"):
        ex.make_report(_paths(tmp_path, "s1", change))


def test_a_baseline_with_changes_in_the_worktree_fails(tmp_path):
    def change(doc):
        doc["harness"]["clean"] = False

    with pytest.raises(ex.DataError, match="worktree had changes"):
        ex.make_report(_paths(tmp_path, "s2", change))


def test_a_missing_key_fails(tmp_path):
    with pytest.raises(ex.DataError, match="no key 'totals.passed'"):
        ex.make_report(_paths(tmp_path, "t18", lambda d: d["totals"].pop("passed")))


def test_get_selects_a_list_item_by_its_fields():
    doc = {"a": [{"id": "x/y", "t": ["p", "q"], "n": 1}, {"id": "z", "t": [], "n": 2}]}
    assert ex.get(doc, "a[id=x/y].n") == 1
    assert ex.get(doc, "a[t=p+q].n") == 1
    assert ex.get(doc, "a.1.n") == 2
    with pytest.raises(ex.DataError):
        ex.get(doc, "a[id=none].n")


# Each value names its source; the tests read it again.


def test_each_value_has_a_kind_and_a_source():
    for vid, entry in VALUES.items():
        assert entry["kind"] in ("copied", "derived"), vid
        assert isinstance(entry["text"], str) and entry["text"], vid
        if entry["kind"] == "copied":
            assert entry["from"] in ex.INPUTS.values(), vid
            assert entry["key"], vid
        else:
            assert entry["formula"], vid


def test_each_copied_value_is_the_value_of_its_key():
    for vid, entry in VALUES.items():
        if entry["kind"] == "copied":
            assert ex.get(INPUTS[entry["from"]], entry["key"]) == entry["value"], vid


def test_each_ratio_is_the_quotient_of_its_times():
    rows = OUT["benchmarks"]
    assert len(rows) == v("g3.benchmarks") == 112
    for row in rows:
        bid = row["id"]
        for other in ("sqruff", "sqlfluff"):
            if row[other] is None:
                assert v(f"status.{bid}.{other}") != "valid"
                continue
            sqll, t_other = v(f"time.{bid}.sqll"), v(f"time.{bid}.{other}")
            assert v(f"ratio.{bid}.{other}") == round(sqll / t_other, 4)
            assert row[other] == {
                "ratio": v(f"ratio.{bid}.{other}"),
                "faster": sqll < t_other,
            }


def test_the_sums_are_those_of_the_times():
    for command in ("start", "parse"):
        ids = [
            r["id"]
            for r in OUT["benchmarks"]
            if r["command"] == command and r["sqruff"] is not None
        ]
        assert v(f"sum.{command}.pairs") == len(ids)
        for tool in ("sqll", "sqruff"):
            want = round(sum(v(f"time.{i}.{tool}") for i in ids), 4)
            assert v(f"sum.{command}.{tool}") == want
    assert v("sum.start.pairs") + v("sum.parse.pairs") == v("g35.pairs")
    total = v("sum.start.sqll") + v("sum.parse.sqll")
    assert total == pytest.approx(v("sum.sqruff.sqll"), abs=1e-3)


# The exit criteria (acceptance of T20).


def test_no_start_or_parse_benchmark_is_slower_than_sqruff():
    assert v("g35.pairs") == 108
    assert v("g35.slower") == []
    assert v("g35.faster") == 108
    assert v("g35.no_pair") == [
        "parse/soql/large",
        "parse/soql/medium",
        "parse/soql/small",
        "start/soql",
    ]
    for bid in v("g35.no_pair"):
        assert v(f"reason.{bid}.sqruff") == "unsupported: dialect soql"


def test_each_start_and_parse_benchmark_is_faster_than_sqlfluff():
    assert v("g34.not_faster") == []
    assert v("g34.faster") == 112


def test_lint_and_fix_are_unsupported_for_sqll():
    assert v("later.lint.unsupported") == v("later.fix.unsupported") == 84
    assert v("later.lint.reason") == ["unsupported: lint"]
    assert v("later.fix.reason") == ["unsupported: fix"]
    assert v("later.sqll.unsupported") == 168
    assert v("later.all_benchmarks") == 280


def test_the_base_cases_pass():
    assert v("s1.dialects.total") == v("s1.dialects.exact") == 2306
    assert v("s1.dialects.no_unparsable") == 2306
    assert v("s1.known_failures.new_failures") == 0
    assert v("s1.known_failures.unexpected_passes") == 0
    assert v("t18.base.tests") == v("t18.base.passed") == 162
    assert v("t18.base.failed") == 0
    assert v("s1.sqll.version") == v("s2.sqll.version")


def test_the_criteria_are_met():
    crit = {c["id"]: c for c in OUT["criteria"]}
    assert list(crit) == [
        "S3.exit.base_cases",
        "S3.exit.sqruff",
        "G3.4.start_parse",
        "later",
    ]
    for cid in ("S3.exit.base_cases", "S3.exit.sqruff", "G3.4.start_parse"):
        assert crit[cid]["met"] is True, cid
        for vid in crit[cid]["values"]:
            assert vid in VALUES, (cid, vid)
    assert crit["later"]["met"] is None
    assert OUT["result"] == {"met": True, "state": STATE}


def test_the_baseline_is_a_clean_full_run():
    assert v("s2.clean") is True
    assert v("s2.profile") == "full"


# The exit record.


def numbers(text: str) -> list[str]:
    """Return the numbers of the text outside code, link targets, list
    markers, versions, dates, and ids such as G3.5, T20, or CP01."""
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"(?m)^\s*\d+\. ", " ", text)
    text = re.sub(r"\b\d+\.\d+\.\d+\b", " ", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)
    text = re.sub(r"\b[A-Z][A-Za-z]*\d+[a-z]?(?:\.\d+)*\b", " ", text)
    return re.findall(r"(?<![\w.-])\d+(?:\.\d+)?%?", text)


def test_numbers():
    assert numbers("a `x 5` [b](c/9) G3.5 T17b CP01 4.4.0 7 and 1.25") == [
        "7",
        "1.25",
    ]
    assert numbers("1. item 3\n2. item") == ["3"]


def test_each_number_of_the_record_is_a_value_of_the_data_file():
    texts = {e["text"] for e in VALUES.values()}
    found = numbers(RECORD)
    assert len(found) > 20
    assert sorted({n for n in found if n not in texts}) == []


def test_the_record_names_the_data_and_the_state():
    assert "[`results/s3/exit.json`](../../results/s3/exit.json)" in RECORD
    assert f"Status: {STATE}." in RECORD
    assert "`scripts/s3/exit.py`" in RECORD


def test_the_record_says_where_g35_applies():
    text = words(RECORD)
    assert "G3.5 applies to the benchmarks that sqll runs (start and parse)" in text
    assert "lint and fix are unsupported until S5" in text


def test_the_record_gives_what_is_not_met_yet():
    text = words(section("Not met yet"))
    assert "G3.4 and G3.5 on lint and fix" in text
    assert "the G3.5 total over all benchmarks" in text


def test_the_record_gives_the_base_cases():
    text = words(section("Base cases"))
    assert "the native base has no linter" in text
    assert f"{t('s1.dialects.exact')} of {t('s1.dialects.total')}" in text
    assert f"{t('t18.base.passed')} of {t('t18.base.tests')}" in text


S3B_QUESTIONS = (
    "Tree type",
    "Source map",
    "Lexer to parser to tree",
    "Rule interface",
    "Ownership",
    "CLI and config",
    "Generated table format",
)


def test_the_record_lists_the_open_s3b_interface_questions():
    part = section("Open interface questions for S3b")
    found = re.findall(r"(?m)^\d+\. \*\*([^*]+)\.\*\*", part)
    assert tuple(found) == S3B_QUESTIONS
    text = words(part)
    for needle in (
        "arena",
        "enum",
        "`TemplatedFile`",
        "arena read API",
        "`crates/**`",
        "Core track",
        "S3 CLI",
    ):
        assert needle in text, needle


def test_the_record_lists_the_open_legal_questions():
    text = words(section("Open legal questions"))
    assert "lawyer" in text
    assert "`COPYRIGHT`" in text


def test_the_record_gives_the_proof_of_g44():
    text = words(section("Proof"))
    assert "scripts/verify --full-bench" in text or "workflow_dispatch" in text


def test_the_record_is_short():
    # A 5-minute read (CONSTITUTION.md 2.4).
    assert len(RECORD.split()) <= 1250


# The state.


def test_the_index_and_the_status_file_say_awaiting_approval():
    (row,) = [line for line in INDEX.splitlines() if line.startswith("| S3 |")]
    assert STATE in row
    assert "[docs/decisions/s3-exit.md](docs/decisions/s3-exit.md)" in row
    assert f"- State: **{STATE}.**" in STATUS
