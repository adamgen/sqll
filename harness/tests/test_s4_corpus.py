"""The corpus information of S4 (parser parity: sqll passes 100% of the
dialect parse fixtures with an exact tree match): scripts/s4/corpus.py.

Task T4 (the parse status of sqll and sqlfluff on each corpus file is
recorded, and each difference has a row) of S4. Design record:
docs/decisions/s4-parity.md, section 4. The tests build complete corpus
reports for the files of the full profile of the corpus manifest, with
synthetic results of sqll and sqlfluff (the report schema of the corpus
harness). Each test of a class makes one difference and finds its row and
class. Each test of an input that is missing or not valid finds exit code 2.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from sqll_harness.bench.timer import Measurement, Sample, sample_stats
from sqll_harness.corpus import report as corpus_report
from sqll_harness.corpus import run as corpus_run
from sqll_harness.corpus.manifest import JINJA, MANIFEST, load
from sqll_harness.paths import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "s4" / "corpus.py"
REPORT = REPO_ROOT / "results" / "S4" / "corpus.json"
RECORD = REPO_ROOT / "results" / "S4" / "corpus-diff.json"
STATUS = REPO_ROOT / "status" / "S4.md"
SHA = "a" * 64
MACHINE = {
    "cpu_model": "test",
    "cpu_count": 4,
    "memory_kib": 1024,
    "os": "test",
    "kernel": "1",
    "arch": "x86_64",
    "python": "3.13",
}
OVERHEAD = [Sample("timed", 0.001, 0.0, 0.0, 1000, 0, False)]
TIMER = {
    "clock": "time.perf_counter_ns",
    "rusage": "os.wait4",
    "overhead": {
        "argv": ["/bin/true"],
        "samples": [s.as_dict() for s in OVERHEAD],
        "stats": sample_stats(OVERHEAD),
    },
}
SETTINGS = {"raw": {"core": {"templater": "raw"}}, "jinja": {"core": {}}}
JINJA_REASON = (
    "warmup run: sqll does not support an item: Error: unsupported: templater jinja"
)


@pytest.fixture(scope="module")
def manifest():
    return load(MANIFEST)


def samples(code: int) -> list[Sample]:
    return [
        Sample("warmup", 1.0, 0.5, 0.01, 5000, code, False),
        Sample("timed", 1.0, 0.5, 0.01, 6000, code, False),
    ]


def entry(file, size, tool, status, count=0, nbytes=0, reason=None) -> dict:
    """A result entry of the corpus report schema."""
    if status in corpus_report.TIMED_STATUSES:
        s = samples(0 if count == 0 else 1)
        unparsable = {"count": count, "bytes": nbytes}
    else:
        s = [Sample("warmup", 1.0, 0.5, 0.0, 100, 2, False)]
        unparsable = None
    timed = [x for x in s if x.kind == "timed"]
    m = Measurement(status, reason, s, sample_stats(timed) if timed else None)
    return corpus_report.result_entry(file, size, tool, status, reason, m, unparsable)


class Corpus:
    """A complete full-profile report of sqll and sqlfluff. By default, each
    tool gives the same result on each file: ok on a raw file, and 2
    unparsable segments on a templated file."""

    def __init__(self, manifest):
        self.files = corpus_run.select(manifest, "full", None)
        self.sha256 = manifest.sha256
        self.results = {}
        for f in self.files:
            for tool in ("sqlfluff", "sqll"):
                if f.templater == JINJA:
                    self.set(f.id, tool, "unparsable", 2, 10, "2 unparsable segments")
                else:
                    self.set(f.id, tool, "ok")

    def file(self, templater: str) -> str:
        return next(f.id for f in self.files if f.templater == templater)

    def set(self, file_id, tool, status, count=0, nbytes=0, reason=None):
        size = next(f.bytes for f in self.files if f.id == file_id)
        self.results[(file_id, tool)] = entry(
            file_id, size, tool, status, count, nbytes, reason
        )

    def report(self, **changes) -> dict:
        inputs = {
            f.id: corpus_report.input_record(
                f,
                corpus_report.reference_record(SHA, None)
                if f.templater == JINJA
                else None,
            )
            for f in self.files
        }
        args = {
            "sqlfluff_ref": "0" * 40,
            "profile": "full",
            "policy": corpus_run.PROFILES["full"].as_dict(),
            "machine": MACHINE,
            "harness": {"commit": "c" * 40, "clean": True},
            "timer": TIMER,
            "manifest_sha256": self.sha256,
            "scope": {"tools": ["sqlfluff", "sqll"], "shard": None},
            "tools": {
                "sqlfluff": {"version": "4.4.0", "settings": SETTINGS},
                "sqll": {"version": "0.1.0", "settings": SETTINGS},
            },
            "inputs": inputs,
            "results": list(self.results.values()),
            "parts": [
                {"shard": f"{k}/2", "machine": MACHINE, "timer": TIMER} for k in (1, 2)
            ],
        }
        args.update(changes)
        return corpus_report.build(**args)


@pytest.fixture
def corpus(manifest) -> Corpus:
    return Corpus(manifest)


def run_script(*args: str) -> tuple[int, dict | str]:
    done = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if "--table" in args and done.returncode == 0:
        return done.returncode, done.stdout
    try:
        result = json.loads(done.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"no JSON output: {done.stdout!r} {done.stderr!r}")
    assert result["exit_code"] == done.returncode
    return done.returncode, result


def run_on(tmp_path: Path, rep, *args: str, text: str | None = None):
    path = tmp_path / "corpus.json"
    path.write_text(text if text is not None else json.dumps(rep), encoding="utf8")
    return run_script("--report", str(path), *args)


def write_settings(tmp_path: Path, entries) -> Path:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"format": 1, "entries": entries}), encoding="utf8")
    return path


def proof(file_id, without, with_) -> dict:
    return {
        "file": file_id,
        "setting": "core.max_parse_depth",
        "value": 2000,
        "with": with_,
        "without": without,
        "command": "sqll parse ...",
    }


# The output and the classes.


def test_equal_results_give_no_row(tmp_path, corpus):
    code, out = run_on(tmp_path, corpus.report())
    assert code == 0 and out["status"] == "pass" and out["errors"] == []
    c = out["counts"]
    assert c["files"] == len(corpus.files) > 0
    assert c["same"] == c["files"] and c["rows"] == 0 and out["rows"] == []
    assert c["by_class"] == {"settings": 0, "templater": 0, "parser gap": 0}
    assert len(out["files"]) == c["files"]
    assert all(f["same"] for f in out["files"])
    raw = corpus.file("raw")
    record = next(f for f in out["files"] if f["file"] == raw)
    want = {"status": "ok", "unparsable_count": 0, "unparsable_bytes": 0}
    assert record["sqll"] == want and record["sqlfluff"] == want
    assert out["report"]["parts"] == ["1/2", "2/2"]
    assert out["report"]["tools"] == {"sqlfluff": "4.4.0", "sqll": "0.1.0"}
    jinja = sum(f.templater == JINJA for f in corpus.files)
    assert c["by_tool"]["sqll"]["ok"] == c["files"] - jinja
    assert c["by_tool"]["sqll"]["unparsable"] == jinja


def test_a_different_unparsable_count_is_a_parser_gap(tmp_path, corpus):
    raw = corpus.file("raw")
    corpus.set(raw, "sqlfluff", "unparsable", 1, 5, "1 unparsable segments")
    corpus.set(raw, "sqll", "unparsable", 2, 9, "2 unparsable segments")
    code, out = run_on(tmp_path, corpus.report())
    assert code == 0
    assert out["counts"]["rows"] == 1
    assert out["counts"]["by_class"]["parser gap"] == 1
    (row,) = out["rows"]
    assert row["file"] == raw and row["class"] == "parser gap"
    assert row["sqlfluff"]["unparsable_count"] == 1
    assert row["sqll"]["unparsable_count"] == 2
    assert next(f for f in out["files"] if f["file"] == raw)["same"] is False


def test_a_different_status_is_a_parser_gap(tmp_path, corpus):
    raw = corpus.file("raw")
    corpus.set(raw, "sqll", "invalid", reason="warmup run: no parse tree")
    code, out = run_on(tmp_path, corpus.report())
    assert code == 0
    (row,) = out["rows"]
    assert row["class"] == "parser gap"
    assert row["sqll"]["status"] == "invalid"
    assert row["sqll"]["unparsable_count"] is None


def test_the_same_count_with_other_bytes_is_no_row(tmp_path, corpus):
    # The rule compares the status and the unparsable count.
    raw = corpus.file("raw")
    corpus.set(raw, "sqlfluff", "unparsable", 1, 5, "1 unparsable segments")
    corpus.set(raw, "sqll", "unparsable", 1, 7, "1 unparsable segments")
    code, out = run_on(tmp_path, corpus.report())
    assert code == 0 and out["rows"] == []


def test_a_jinja_file_that_sqll_fails_closed_on_is_templater(tmp_path, corpus):
    jinja = corpus.file(JINJA)
    corpus.set(jinja, "sqll", "invalid", reason=JINJA_REASON)
    code, out = run_on(tmp_path, corpus.report())
    assert code == 0
    (row,) = out["rows"]
    assert row["file"] == jinja and row["class"] == "templater"
    assert "S11" in row["cause"]
    assert out["counts"]["by_class"]["templater"] == 1


def test_a_jinja_file_with_another_failure_is_a_parser_gap(tmp_path, corpus):
    jinja = corpus.file(JINJA)
    corpus.set(jinja, "sqll", "invalid", reason="warmup run: no parse tree")
    code, out = run_on(tmp_path, corpus.report())
    assert code == 0
    assert [r["class"] for r in out["rows"]] == ["parser gap"]


def test_a_raw_file_that_sqll_fails_closed_on_is_not_templater(tmp_path, corpus):
    raw = corpus.file("raw")
    corpus.set(raw, "sqll", "invalid", reason=JINJA_REASON)
    code, out = run_on(tmp_path, corpus.report())
    assert code == 0
    assert [r["class"] for r in out["rows"]] == ["parser gap"]


def test_a_settings_row_gives_the_result_with_and_without(tmp_path, corpus):
    raw = corpus.file("raw")
    corpus.set(raw, "sqll", "invalid", reason="warmup run: no parse tree")
    without = {"status": "invalid", "unparsable_count": None}
    with_ = {"status": "ok", "unparsable_count": 0}
    settings = write_settings(tmp_path, [proof(raw, without, with_)])
    code, out = run_on(tmp_path, corpus.report(), "--settings", str(settings))
    assert code == 0
    (row,) = out["rows"]
    assert row["class"] == "settings"
    assert row["setting"] == {
        "name": "core.max_parse_depth",
        "value": 2000,
        "with": with_,
        "without": without,
        "command": "sqll parse ...",
    }
    assert out["counts"]["by_class"] == {
        "settings": 1,
        "templater": 0,
        "parser gap": 0,
    }


def test_each_difference_has_one_row(tmp_path, corpus):
    raws = [f.id for f in corpus.files if f.templater == "raw"][:3]
    jinja = corpus.file(JINJA)
    corpus.set(raws[0], "sqll", "unparsable", 1, 4, "1 unparsable segments")
    corpus.set(raws[1], "sqll", "invalid", reason="warmup run: timeout")
    corpus.set(raws[2], "sqlfluff", "invalid", reason="warmup run: no parse tree")
    corpus.set(jinja, "sqll", "invalid", reason=JINJA_REASON)
    without = {"status": "invalid", "unparsable_count": None}
    settings = write_settings(
        tmp_path,
        [proof(raws[1], without, {"status": "ok", "unparsable_count": 0})],
    )
    code, out = run_on(tmp_path, corpus.report(), "--settings", str(settings))
    assert code == 0
    got = {r["file"]: r["class"] for r in out["rows"]}
    assert got == {
        raws[0]: "parser gap",
        raws[1]: "settings",
        raws[2]: "parser gap",
        jinja: "templater",
    }
    assert len(out["rows"]) == 4
    assert out["counts"]["same"] == out["counts"]["files"] - 4
    assert sorted(f["file"] for f in out["files"] if not f["same"]) == sorted(got)


def test_the_table_has_the_counts_and_each_row(tmp_path, corpus):
    raw = corpus.file("raw")
    jinja = corpus.file(JINJA)
    corpus.set(raw, "sqll", "unparsable", 1, 4, "1 unparsable segments")
    corpus.set(jinja, "sqll", "invalid", reason=JINJA_REASON)
    code, text = run_on(tmp_path, corpus.report(), "--table")
    assert code == 0
    assert "| sqll | " in text and "| sqlfluff | " in text
    assert f"| `{raw}` |" in text and "| parser gap |" in text
    assert f"| `{jinja}` |" in text and "| templater |" in text


def test_out_is_the_output(tmp_path, corpus):
    out_file = tmp_path / "diff" / "corpus-diff.json"
    code, out = run_on(tmp_path, corpus.report(), "--out", str(out_file))
    assert code == 0
    assert json.loads(out_file.read_text("utf8")) == out


# Exit code 2: an input is missing or not valid.


def test_no_report(tmp_path):
    out_file = tmp_path / "corpus-diff.json"
    code, out = run_script(
        "--report", str(tmp_path / "none.json"), "--out", str(out_file)
    )
    assert code == 2 and out["status"] == "error"
    assert "does not exist" in out["errors"][0]
    assert not out_file.exists()


def test_a_report_that_is_not_json(tmp_path):
    code, out = run_on(tmp_path, None, text="{not json")
    assert code == 2 and "not valid JSON" in out["errors"][0]


def test_a_report_that_is_not_an_object(tmp_path):
    code, out = run_on(tmp_path, [])
    assert code == 2 and "not a JSON object" in out["errors"][0]


def test_a_report_with_a_schema_error(tmp_path, corpus):
    rep = corpus.report()
    rep["totals"]["sqll"]["ok"] += 1
    code, out = run_on(tmp_path, rep)
    assert code == 2 and "schema error" in out["errors"][0]


def test_a_report_with_no_file(tmp_path, corpus):
    rep = corpus.report(inputs={}, results=[])
    code, out = run_on(tmp_path, rep)
    assert code == 2 and "no file" in out["errors"][0]


def test_a_smoke_report(tmp_path, corpus):
    rep = corpus.report(profile="smoke", policy=corpus_run.PROFILES["smoke"].as_dict())
    code, out = run_on(tmp_path, rep)
    assert code == 2 and "profile smoke" in out["errors"][0]


def test_a_shard_report(tmp_path, corpus):
    rep = corpus.report(scope={"tools": ["sqlfluff", "sqll"], "shard": "1/2"})
    code, out = run_on(tmp_path, rep)
    assert code == 2 and "shard" in out["errors"][0]


def test_a_report_without_sqll(tmp_path, corpus):
    results = [r for r in corpus.results.values() if r["tool"] == "sqlfluff"]
    rep = corpus.report(
        scope={"tools": ["sqlfluff"], "shard": None},
        tools={"sqlfluff": {"version": "4.4.0", "settings": SETTINGS}},
        results=results,
    )
    code, out = run_on(tmp_path, rep)
    assert code == 2 and "no results of sqll" in out["errors"][0]


def test_a_report_with_a_missing_file(tmp_path, corpus):
    gone = corpus.file("raw")
    rep = corpus.report()
    del rep["inputs"][gone]
    rep = corpus.report(
        inputs=rep["inputs"],
        results=[r for r in corpus.results.values() if r["file"] != gone],
    )
    code, out = run_on(tmp_path, rep)
    assert code == 2 and "not complete" in out["errors"][0]


def test_a_report_of_another_manifest(tmp_path, corpus):
    code, out = run_on(tmp_path, corpus.report(manifest_sha256="b" * 64))
    assert code == 2 and "not complete" in out["errors"][0]


def test_a_result_with_the_status_error(tmp_path, corpus):
    corpus.set(corpus.file("raw"), "sqll", "error", reason="harness error")
    code, out = run_on(tmp_path, corpus.report())
    assert code == 2 and "status error" in out["errors"][0]


def test_a_manifest_that_does_not_exist(tmp_path, corpus):
    code, out = run_on(
        tmp_path, corpus.report(), "--manifest", str(tmp_path / "none.json")
    )
    assert code == 2 and "manifest" in out["errors"][0]


def test_a_settings_file_that_does_not_exist(tmp_path, corpus):
    code, out = run_on(
        tmp_path, corpus.report(), "--settings", str(tmp_path / "none.json")
    )
    assert code == 2 and "does not exist" in out["errors"][0]


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"format": 2, "entries": []},
        {"format": 1, "entries": [{"file": "x"}]},
        {
            "format": 1,
            "entries": [proof("x", {"status": "bad", "unparsable_count": None}, {})],
        },
    ],
)
def test_a_settings_file_that_is_not_valid(tmp_path, corpus, data):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf8")
    code, out = run_on(tmp_path, corpus.report(), "--settings", str(path))
    assert code == 2 and out["errors"]


def test_a_settings_entry_of_a_file_with_no_difference(tmp_path, corpus):
    raw = corpus.file("raw")
    ok = {"status": "ok", "unparsable_count": 0}
    settings = write_settings(tmp_path, [proof(raw, ok, ok)])
    code, out = run_on(tmp_path, corpus.report(), "--settings", str(settings))
    assert code == 2 and "no difference" in out["errors"][0]


def test_a_settings_entry_of_an_unknown_file(tmp_path, corpus):
    ok = {"status": "ok", "unparsable_count": 0}
    settings = write_settings(tmp_path, [proof("no/such.sql", ok, ok)])
    code, out = run_on(tmp_path, corpus.report(), "--settings", str(settings))
    assert code == 2 and "no file" in out["errors"][0]


def test_a_setting_that_does_not_remove_the_difference(tmp_path, corpus):
    raw = corpus.file("raw")
    corpus.set(raw, "sqll", "invalid", reason="warmup run: no parse tree")
    without = {"status": "invalid", "unparsable_count": None}
    still = {"status": "unparsable", "unparsable_count": 3}
    settings = write_settings(tmp_path, [proof(raw, without, still)])
    code, out = run_on(tmp_path, corpus.report(), "--settings", str(settings))
    assert code == 2 and "does not remove the difference" in out["errors"][0]


def test_a_settings_entry_that_is_not_the_result_of_the_report(tmp_path, corpus):
    raw = corpus.file("raw")
    corpus.set(raw, "sqll", "invalid", reason="warmup run: no parse tree")
    other = {"status": "unparsable", "unparsable_count": 3}
    ok = {"status": "ok", "unparsable_count": 0}
    settings = write_settings(tmp_path, [proof(raw, other, ok)])
    code, out = run_on(tmp_path, corpus.report(), "--settings", str(settings))
    assert code == 2 and "not the result of the report" in out["errors"][0]


def test_a_settings_entry_of_a_templater_row(tmp_path, corpus):
    jinja = corpus.file(JINJA)
    corpus.set(jinja, "sqll", "invalid", reason=JINJA_REASON)
    without = {"status": "invalid", "unparsable_count": None}
    with_ = {"status": "unparsable", "unparsable_count": 2}
    settings = write_settings(tmp_path, [proof(jinja, without, with_)])
    code, out = run_on(tmp_path, corpus.report(), "--settings", str(settings))
    assert code == 2 and "templater difference" in out["errors"][0]


def test_a_report_copy_is_not_changed(tmp_path, corpus):
    rep = corpus.report()
    before = copy.deepcopy(rep)
    code, _ = run_on(tmp_path, rep)
    assert code == 0
    assert json.loads((tmp_path / "corpus.json").read_text("utf8")) == before


# The record of T4.


def test_the_record_is_the_output_of_the_script():
    record = json.loads(RECORD.read_text(encoding="utf8"))
    code, out = run_script("--report", str(REPORT))
    assert code == 0
    for key in ("commit", "inputs"):
        record.pop(key)
        out.pop(key)
    assert out == record


def test_the_record_is_of_24_merged_shards_of_one_clean_commit():
    rep = json.loads(REPORT.read_text(encoding="utf8"))
    assert rep["profile"] == "full" and rep["scope"]["shard"] is None
    assert rep["scope"]["tools"] == ["sqlfluff", "sqll"]
    assert rep["harness"]["clean"] is True
    assert [p["shard"] for p in rep["parts"]] == [f"{k}/24" for k in range(1, 25)]


def test_the_status_table_has_each_row():
    record = json.loads(RECORD.read_text(encoding="utf8"))
    text = STATUS.read_text("utf8").split("\n## Corpus information\n", 1)[1]
    text = text.split("\n## ", 1)[0]
    for row in record["rows"]:
        line = next(
            (x for x in text.splitlines() if x.startswith(f"| `{row['file']}` |")),
            None,
        )
        assert line is not None, row["file"]
        assert f"| {row['class']} |" in line
    for tool in ("sqlfluff", "sqll"):
        n = record["counts"]["by_tool"][tool]
        cells = " | ".join(str(n[s]) for s in corpus_report.STATUSES)
        assert f"| {tool} | {cells} |" in text
