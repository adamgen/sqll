"""S3b (Core: the shared syntax tree, source map, frozen interfaces, and the
sqll binary skeleton), task C17 (S3b exit: proof, exit record, and the
request for approval): the S3b exit record.

results/S3b/exit.json is the output of scripts/s3b/exit.py. The tests run
the check (it also runs the ownership probe again on the frozen and the
live tracks.yml), show that a changed record or input fails, read each
copied value again from its file and key, and check the exit record
docs/decisions/s3b-exit.md and the state in STATUS.md and status/S3b.md."""

import copy
import hashlib
import importlib.util
import json
import re

import pytest

from sqll_harness.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "s3b_exit", REPO_ROOT / "scripts" / "s3b" / "exit.py"
)
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

OUT = json.loads(ex.OUT_FILE.read_text("utf8"))
VALUES = OUT["values"]
RECORD = (REPO_ROOT / "docs" / "decisions" / "s3b-exit.md").read_text("utf8")
INDEX = (REPO_ROOT / "STATUS.md").read_text("utf8")
STATUS = (REPO_ROOT / "status" / "S3b.md").read_text("utf8")
STATE = "S3b awaiting approval"
# The sha256 of the frozen copies that the record cites (C17). A change of a
# copy changes its sha256.
CITED = {
    "results/s1/summary.json": (
        "7d58a946e0f3fbaffaaa9fe799f41265ec96b3d25e980efead0af897ceaab41c"
    ),
    "docs/interfaces/README.md": (
        "61b83588b7268831b0d65ba1d8e74b98add65f4cc6ea0b52bf0cccb028fc6887"
    ),
    "tracks.yml": "794840ac005ac8038fe6931524b89f94adeee989aa8e86fd8d5c8360abea48ae",
}


def v(vid):
    return VALUES[vid]["value"]


def t(vid):
    return VALUES[vid]["text"]


def words(text: str) -> str:
    return " ".join(text.split())


def section(title: str) -> str:
    return RECORD.split(f"\n## {title}\n", 1)[1].split("\n## ", 1)[0]


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# The check and the inputs.


def test_the_committed_output_is_the_output_of_the_committed_inputs(capsys):
    assert ex.main(["--check"]) == 0
    assert capsys.readouterr().out.startswith("exit check: PASS: ")


@pytest.mark.parametrize(
    "old, new",
    [
        ('"C17"', '"C16"'),
        # A changed number: the count of the rows of the interface index.
        ('"text": "8"', '"text": "9"'),
        ('"exit_code": 1', '"exit_code": 0'),
    ],
)
def test_the_check_fails_on_a_changed_record(tmp_path, monkeypatch, old, new):
    text = ex.OUT_FILE.read_text("utf8")
    assert old in text
    out = tmp_path / "exit.json"
    out.write_text(text.replace(old, new, 1), "utf8")
    monkeypatch.setattr(ex, "OUT_FILE", out)
    assert ex.main(["--check"]) == 1


def test_the_inputs_are_the_committed_files():
    assert OUT["inputs"] == {
        rel: sha256(ex.read_path(name)) for name, rel in ex.INPUTS.items()
    }


def test_the_frozen_copies_have_the_cited_sha256():
    assert set(ex.FROZEN) == {"s1", "index", "tracks"}
    for name, copy_rel in ex.FROZEN.items():
        assert copy_rel.startswith("results/S3b/exit-inputs/"), name
        assert ex.read_path(name) == REPO_ROOT / copy_rel
        assert OUT["inputs"][ex.INPUTS[name]] == sha256(REPO_ROOT / copy_rel)
    for rel, digest in CITED.items():
        assert OUT["inputs"][rel] == digest


@pytest.mark.parametrize("name", ["s1", "index", "tracks"])
def test_a_changed_frozen_copy_fails_the_check(tmp_path, monkeypatch, name):
    """One more byte at the end: the sha256 in the record is not that of the
    copy."""
    changed = tmp_path / ex.read_path(name).name
    changed.write_bytes(ex.read_path(name).read_bytes() + b"\n")
    monkeypatch.setitem(ex.FROZEN, name, str(changed))
    assert ex.read_path(name) == changed
    assert ex.main(["--check"]) == 1


def _paths(tmp_path, name, change):
    paths = {k: ex.read_path(k) for k in ex.INPUTS}
    doc = copy.deepcopy(json.loads(paths[name].read_text("utf8")))
    change(doc)
    paths[name] = tmp_path / f"{name}.json"
    paths[name].write_text(json.dumps(doc), "utf8")
    return paths


def _job(doc, name):
    return next(j for j in doc["jobs"] if j["name"] == name)


def test_a_missing_ci_line_fails(tmp_path):
    def change(doc):
        _job(doc, "report")["lines"].remove(ex.CI_LINES["report"][1])

    with pytest.raises(ex.DataError, match="0 lines"):
        ex.make_report(_paths(tmp_path, "ci", change))


def test_a_failed_ci_job_is_not_met(tmp_path):
    def change(doc):
        _job(doc, "build")["conclusion"] = "failure"

    out = ex.make_report(_paths(tmp_path, "ci", change))
    crit = {c["id"]: c for c in out["criteria"]}
    assert crit["S3b.exit.adapters"]["met"] is False
    assert out["result"]["met"] is False


def test_another_head_in_the_ci_record_fails(tmp_path):
    def change(doc):
        doc["head_sha"] = "0" * 40

    with pytest.raises(ex.DataError, match="not the head of the CI run"):
        ex.make_report(_paths(tmp_path, "ci", change))


def test_another_speed_base_fails(tmp_path):
    def change(doc):
        doc["base"]["commit"] = "0" * 40

    with pytest.raises(ex.DataError, match="not the S3 exit"):
        ex.make_report(_paths(tmp_path, "speed", change))


def test_another_s1_result_is_not_met(tmp_path, monkeypatch):
    def change(doc):
        doc["results"]["sqll"]["suites"]["rules"]["passed"] = 37

    paths = _paths(tmp_path, "s1", change)
    out = ex.make_report(paths)
    assert out["result"]["met"] is False


def test_a_slower_benchmark_without_a_reason_is_not_met(tmp_path, monkeypatch):
    bid = OUT["values"]["speed.slower_ids"]["value"]
    bid = bid[0] if bid else "start/ansi"

    def change(doc):
        slow = doc["summary"]["slowdowns"]
        if bid not in slow["slower"]:
            slow["slower"].append(bid)

    monkeypatch.setattr(ex, "REASONS", {})
    out = ex.make_report(_paths(tmp_path, "speed", change))
    assert bid in out["values"]["speed.no_reason"]["value"]
    assert out["result"]["met"] is False


def test_the_probe_fails_on_a_tracks_yml_that_gives_a_core_path_away(tmp_path):
    """A tracks.yml that gives Cargo.lock to S4 (parser parity): the probe of
    S4 passes without the label, so the exit is not met."""
    text = ex.read_path("tracks").read_text("utf8")
    old = "      - crates/sqll_parser/src/**\n"
    assert old in text
    changed = tmp_path / "tracks.yml"
    changed.write_text(text.replace(old, old + "      - Cargo.lock\n"), "utf8")
    paths = {k: ex.read_path(k) for k in ex.INPUTS}
    paths["tracks"] = changed
    out = ex.make_report(paths)
    crit = {c["id"]: c for c in out["criteria"]}
    assert crit["S3b.exit.core_track"]["met"] is False
    (run,) = [
        r
        for r in out["probe"]
        if r["track"] == "S4" and r["path"] == "Cargo.lock" and not r["label"]
    ]
    assert run["exit_code"] == 0


def test_get_selects_a_list_item_by_its_fields():
    doc = {"a": [{"name": "x (y)", "n": 1}, {"name": "z", "n": 2}]}
    assert ex.get(doc, "a[name=x (y)].n") == 1
    assert ex.get(doc, "a.1.n") == 2
    with pytest.raises(ex.DataError):
        ex.get(doc, "a[name=none].n")


# Each value names its source; the tests read it again.


def test_each_value_has_a_kind_and_a_source():
    for vid, entry in VALUES.items():
        assert entry["kind"] in ("copied", "line", "derived"), vid
        assert isinstance(entry["text"], str) and entry["text"], vid
        if entry["kind"] == "derived":
            assert entry["formula"], vid
        else:
            assert entry["from"] in ex.INPUTS.values(), vid


def test_each_copied_value_and_line_is_in_its_file():
    files = {
        rel: json.loads(ex.read_path(name).read_text("utf8"))
        for name, rel in ex.INPUTS.items()
        if rel.endswith(".json")
    }
    for vid, entry in VALUES.items():
        if entry["kind"] == "copied":
            assert ex.get(files[entry["from"]], entry["key"]) == entry["value"], vid
        elif entry["kind"] == "line":
            job = ex.get(files[entry["from"]], f"jobs[name={entry['job']}]")
            assert entry["value"] in job["lines"], vid


# The exit criteria (acceptance of C17).


def test_the_criteria_are_met():
    crit = {c["id"]: c for c in OUT["criteria"]}
    assert list(crit) == [
        "S3b.exit.adapters",
        "S3b.exit.interfaces",
        "S3b.exit.core_track",
        "G3.keep",
    ]
    for cid, c in crit.items():
        assert c["met"] is True, cid
        for vid in c["values"]:
            assert vid in VALUES, (cid, vid)
    assert OUT["result"] == {"met": True, "state": STATE}


def test_the_s1_results_of_sqll():
    assert v("s1.dialects.total") == v("s1.dialects.exact") == 2306
    assert v("s1.dialects.no_unparsable") == 2306
    assert (v("s1.rules.passed"), v("s1.rules.total")) == (38, 2527)
    assert (v("s1.autofix.passed"), v("s1.autofix.total")) == (0, 61)
    assert (v("s1.templater.passed"), v("s1.templater.total")) == (0, 43)
    assert v("s1.new_failures") == v("s1.unexpected_passes") == 0


def test_the_ci_run_passed_on_the_exit_head():
    assert v("ci.conclusion") == "success"
    assert v("ci.jobs_not_ok") == []
    assert v("ci.head") == v("speed.head")
    ci = json.loads(ex.read_path("ci").read_text("utf8"))
    names = {j["name"] for j in ci["jobs"]}
    for job in [*ex.CI_LINES, *ex.CI_PREFIXES, "image", "changes"]:
        assert job in names, job
    assert v("ci.jobs_total") == 77
    assert v("ci.event") == "push"


def test_each_stones_interface_maps_to_its_rows():
    rows = OUT["interfaces"]
    assert v("interfaces.rows") == v("interfaces.mapped") == len(rows) == 8
    assert v("interfaces.stones") == 4
    assert {r["stones"] for r in rows} == set(ex.STONES_INTERFACES)
    for r in rows:
        assert r["files_exist"] is True, r["interface"]
        assert r["test"].startswith("crates/sqll_interfaces/tests/"), r["interface"]


def test_each_stones_bullet_has_its_tasks_documents_and_tests():
    assert len(OUT["bullets"]) == 5
    for b in OUT["bullets"]:
        assert b["in_stones"] and b["files_exist"], b["bullet"]
        assert b["tasks"] and b["docs"] and b["tests"], b["bullet"]


def test_each_core_change_of_a_later_track_needs_the_label():
    assert v("probe.core_runs") == 7 * 6 == v("probe.fail_without_label")
    assert v("probe.pass_with_label") == v("probe.core_runs")
    assert v("probe.control_pass") == 7
    tracks = {r["track"] for r in OUT["probe"]}
    assert tracks == {"S4", "S5", "S6", "S7-sqll", "S8", "S10", "S11"}
    for path in ("Cargo.lock", "crates/sqll_dialects/build.rs"):
        assert path in ex.PROBE_PATHS


def test_the_speed_check_keeps_the_s3_speed():
    assert v("speed.base").startswith(ex.S3_EXIT)
    assert v("speed.failure") == 0
    assert v("speed.no_reason") == []
    assert v("speed.sqlfluff.head_faster") == v("speed.sqlfluff.pairs") == 112
    assert v("speed.sqruff.head_faster") == v("speed.sqruff.pairs") == 108
    assert v("speed.sqruff.head_slower") == []
    assert set(OUT["reasons"]) == set(v("speed.slower_ids"))


# The exit record.


def numbers(text: str) -> list[str]:
    """Return the numbers of the text outside code, link targets, list
    markers, versions, dates, and ids such as G3.5, C17, or S3b."""
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"(?m)^\s*\d+\. ", " ", text)
    text = re.sub(r"\b\d+\.\d+\.\d+\b", " ", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)
    text = re.sub(r"\b[A-Z][A-Za-z]*\d+[a-z]?(?:\.\d+)*\b", " ", text)
    return re.findall(r"(?<![\w.-])\d+(?:\.\d+)?%?", text)


def test_each_number_of_the_record_is_a_value_of_the_data_file():
    texts = {e["text"] for e in VALUES.values()}
    found = numbers(RECORD)
    assert len(found) > 20
    # The numbers of the 3 exit rules (1 to 3), the 4 STONES interfaces, and
    # the 5 S3b bullets.
    allowed = {"1", "2", "3", "4", "5"}
    assert sorted({n for n in found if n not in texts | allowed}) == []


def test_the_record_names_the_data_the_state_and_the_ci_run():
    assert "[`results/S3b/exit.json`](../../results/S3b/exit.json)" in RECORD
    assert f"Status: {STATE}" in RECORD
    assert "`scripts/s3b/exit.py`" in RECORD
    text = words(RECORD)
    assert f"run {t('ci.run_id')}" in text
    assert f"`{t('ci.head')}`" in text
    for lines in ex.CI_LINES.values():
        for line in lines:
            assert line in RECORD, line


def test_the_record_gives_each_exit_rule_and_each_bullet():
    for title in (
        "Exit 1: the S1 harness and the S2 benchmarks run sqll",
        "Exit 2: the interfaces are documented",
        "Exit 3: each change to the core goes through the Core track",
        "G3: keep the S3 speed",
        "Each S3b bullet",
    ):
        assert f"\n## {title}\n" in RECORD, title
    part = section("Each S3b bullet")
    for b in ex.BULLETS:
        assert b["bullet"] in part, b["bullet"]
        for f in [*b["docs"], *b["tests"]]:
            assert f in part, f
    part = section("Exit 2: the interfaces are documented")
    for stone, names in ex.STONES_INTERFACES.items():
        assert stone in part, stone
        for name in names:
            assert name in part, name


def test_the_record_gives_a_reason_for_each_slower_benchmark():
    part = words(section("G3: keep the S3 speed"))
    for bid, reason in OUT["reasons"].items():
        assert bid in part and reason in part, bid
    assert "C9" in part


def test_the_record_is_short():
    # A 5-minute read (CONSTITUTION.md 2.4).
    assert len(RECORD.split()) <= 1250


# The state.


def test_the_index_and_the_status_file_say_awaiting_approval():
    (row,) = [line for line in INDEX.splitlines() if line.startswith("| S3b |")]
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[1] == "core"
    assert cells[2].startswith(f"{STATE} (track core).")
    assert "[docs/decisions/s3b-exit.md](docs/decisions/s3b-exit.md)" in cells[2]
    assert "[status/S3b.md](status/S3b.md)" in cells[2]
    assert f"State: **{STATE}.**" in STATUS
    assert "[docs/decisions/s3b-exit.md](../docs/decisions/s3b-exit.md)" in STATUS
