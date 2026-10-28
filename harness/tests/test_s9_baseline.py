"""The recorded S9 baseline (results/S9/baseline.json): the report of the
controlled full corpus run (T6). It must pass the schema check and the
baseline rules, have one result for each manifest file and tool with the
input records of the manifest, and status/S9.md must show its data."""

import copy
import json
import re
import subprocess
from collections import Counter

from sqll_harness.bench import registry
from sqll_harness.corpus import __main__ as corpus_main
from sqll_harness.corpus import baseline, report, tables
from sqll_harness.corpus import run as corpus_run
from sqll_harness.corpus.manifest import JINJA, MIN_BYTES, load
from sqll_harness.paths import REPO_ROOT

MANIFEST = load()
BASE = report.load(baseline.BASELINE)
TOOLS = ["sqlfluff", "sqlfluff-rs", "sqruff"]
VERSIONS = {"sqlfluff": "4.4.0", "sqlfluff-rs": "4.4.0", "sqruff": "0.41.0"}
STATUS = (REPO_ROOT / "status" / "S9.md").read_text(encoding="utf8")
SHARDS = 4


def corpus(*args) -> int:
    return corpus_main.main([str(a) for a in args])


# The recorded report.


def test_the_baseline_is_a_full_run_of_all_tools_and_files():
    assert report.check(BASE) == []
    assert baseline.recorded(BASE, MANIFEST) == []
    assert BASE["profile"] == "full"
    assert BASE["parts"] is None and BASE["scope"]["shard"] is None
    assert BASE["scope"]["tools"] == TOOLS == registry.names()
    assert BASE["harness"]["clean"] is True
    assert re.fullmatch(r"[0-9a-f]{40}", BASE["harness"]["commit"])
    assert BASE["policy"] == corpus_run.PROFILES["full"].as_dict()


def test_the_baseline_is_of_the_pinned_sqlfluff_and_tools():
    pin = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD:third_party/sqlfluff"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert BASE["sqlfluff_ref"] == pin
    assert {t: BASE["tools"][t]["version"] for t in TOOLS} == VERSIONS
    for tool in TOOLS:
        adapter = registry.get(tool)
        want = {t: corpus_run.tool_config(adapter, t, None) for t in sorted(MIN_BYTES)}
        assert BASE["tools"][tool]["settings"] == want, tool


def test_the_inputs_are_the_files_of_the_manifest():
    assert BASE["manifest_sha256"] == MANIFEST.sha256
    assert list(BASE["inputs"]) == sorted(f.id for f in MANIFEST.files)
    assert len(BASE["inputs"]) == len(MANIFEST.files) == 164
    for entry in MANIFEST.files:
        record = BASE["inputs"][entry.id]
        assert record["sha256"] == entry.sha256, entry.id
        assert record == report.input_record(entry, record["reference"])
        assert (record["reference"] is not None) == (entry.templater == JINJA)


def test_the_baseline_has_one_result_for_each_file_and_tool():
    keys = Counter((r["file"], r["tool"]) for r in BASE["results"])
    assert set(keys.values()) == {1}
    assert set(keys) == {(f.id, t) for f in MANIFEST.files for t in TOOLS}
    assert len(keys) == 164 * 3
    for r in BASE["results"]:
        if r["status"] in report.TIMED_STATUSES:
            assert r["stats"] is not None and r["bytes_per_s"] is not None
        else:
            assert r["stats"] is None and r["reason"], (r["file"], r["tool"])


def test_check_full_passes_on_the_baseline(capsys):
    assert (
        corpus("check", baseline.BASELINE, "--baseline", baseline.BASELINE, "--full")
        == 0
    )
    out = capsys.readouterr().out
    assert f"The stable data of {164 * 3} results is that of the baseline" in out
    assert "The report has the profile and each result of the baseline." in out


# A shard of the baseline (as a CI shard of a full run).


def _shard(k: int, n: int) -> dict:
    ids = {f.id for f in corpus_run.select(MANIFEST, "full", (k, n))}
    fields = {
        key: copy.deepcopy(BASE[key])
        for key in (
            "sqlfluff_ref",
            "profile",
            "policy",
            "machine",
            "harness",
            "timer",
            "manifest_sha256",
            "tools",
        )
    }
    return report.build(
        **fields,
        scope=corpus_run.scope(TOOLS, (k, n)),
        inputs={i: r for i, r in BASE["inputs"].items() if i in ids},
        results=[r for r in BASE["results"] if r["file"] in ids],
    )


def test_a_shard_of_the_baseline_has_no_drift_and_merges_to_it():
    parts = [_shard(k, SHARDS) for k in range(1, SHARDS + 1)]
    for part in parts:
        assert report.check(part) == []
        assert corpus_run.incomplete(part, MANIFEST) == []
        assert baseline.drift(part, BASE) == []
    errors = baseline.missing(parts[0], BASE)
    assert len(errors) == 1 and errors[0].startswith("no result for ")
    merged = corpus_run.merge([(str(k), p) for k, p in enumerate(parts)], MANIFEST)
    assert merged["results"] == BASE["results"]
    assert merged["compared"] == BASE["compared"]
    assert baseline.missing(merged, BASE) == []


def test_drift_finds_a_changed_status_of_the_baseline():
    rep = copy.deepcopy(BASE)
    r = next(x for x in rep["results"] if x["status"] == report.OK)
    r["status"] = report.UNPARSABLE
    assert baseline.drift(rep, BASE) == [
        f"{r['tool']} {r['file']}: status unparsable (None), baseline ok (None)"
    ]


# status/S9.md.


def _rows(header: str) -> list[list[str]]:
    """Return the cells of each row of the status/S9.md table with this
    header. An escaped | stays in its cell."""
    lines = STATUS.splitlines()
    start = lines.index(header)
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = re.split(r"(?<!\\)\|", line.strip()[1:-1])
        rows.append([c.strip() for c in cells])
    return rows


def test_status_has_the_tables_of_the_baseline():
    blocks = tables.markdown(BASE).strip("\n").split("\n\n")
    assert len(blocks) == 4
    for block in blocks:
        assert f"\n\n{block}\n\n" in STATUS, block.splitlines()[0]


def test_status_names_the_baseline_and_its_run():
    assert "results/S9/baseline.json" in STATUS
    assert f"`{BASE['harness']['commit'][:7]}`" in STATUS
    machine = BASE["machine"]
    assert machine["cpu_model"] in STATUS
    assert f"{machine['cpu_count']} CPUs" in STATUS


def test_status_counts_are_the_baseline():
    rows = _rows(tables.TOTALS_HEADER)
    want = [
        [t, VERSIONS[t]]
        + [
            str(sum(r["tool"] == t and r["status"] == s for r in BASE["results"]))
            for s in report.STATUSES
        ]
        for t in TOOLS
    ]
    assert rows == want


def test_status_compared_totals_are_the_baseline():
    rows = _rows(tables.COMPARED_HEADER)
    ok = {(r["file"], r["tool"]): r for r in BASE["results"] if r["status"] == "ok"}
    files = [f for f in BASE["inputs"] if all((f, t) in ok for t in TOOLS)]
    size = sum(BASE["inputs"][f]["bytes"] for f in files)
    assert files, "no file where each tool is ok"
    sums = {
        t: [
            sum(ok[(f, t)]["stats"][k]["median"] for f in files)
            for k in ("wall_s", "cpu_s")
        ]
        for t in TOOLS
    }
    for row, tool in zip(rows, TOOLS, strict=True):
        wall, cpu = sums[tool]
        assert row[:3] == [tool, str(len(files)), str(size)]
        assert abs(float(row[3]) - wall) < 0.001
        assert abs(float(row[4]) - cpu) < 0.001
        assert abs(float(row[5]) - size / wall) <= 1
        assert abs(float(row[6]) - wall / sums["sqlfluff"][0]) < 0.001
        assert abs(float(row[7]) - cpu / sums["sqlfluff"][1]) < 0.001


def test_status_file_table_shows_each_file_and_tool():
    rows = _rows(tables.files_header(TOOLS))
    by_key = {(r["file"], r["tool"]): r for r in BASE["results"]}
    assert [r[0].strip("`") for r in rows] == list(BASE["inputs"])
    for row in rows:
        name = row[0].strip("`")
        record = BASE["inputs"][name]
        assert row[1:3] == [record["dialect"], str(record["bytes"])]
        for tool, text in zip(TOOLS, row[3:], strict=True):
            r = by_key[(name, tool)]
            parts = text.split(", ")
            assert parts[0].split()[0] == r["status"], (name, tool)
            if r["status"] not in report.TIMED_STATUSES:
                assert parts == [r["status"]]
                continue
            u = r["unparsable"]
            if u["count"]:
                assert parts[0] == f"{r['status']} {u['count']} ({u['bytes']} B)"
            else:
                assert parts[0] == r["status"]
            wall = r["stats"]["wall_s"]["median"]
            assert abs(float(parts[1].removesuffix(" s")) - wall) <= 0.0005
            rate = float(parts[2].removesuffix(" B/s"))
            assert abs(rate - record["bytes"] / wall) <= 1


def test_status_lists_the_reason_of_each_result_that_is_not_ok():
    rows = _rows(tables.REASONS_HEADER)
    by_key = {(r["tool"], r["file"]): r for r in BASE["results"]}
    listed = []
    for tool, file, status, text in rows:
        r = by_key[(tool, file.strip("`"))]
        assert r["status"] == status
        shown = text.strip("`").replace("\\|", "|").removesuffix("...")
        assert " ".join(r["reason"].split()).replace("`", "'").startswith(shown)
        listed.append((tool, r["file"]))
    want = {
        (r["tool"], r["file"])
        for r in BASE["results"]
        if r["status"] not in (report.OK, report.UNPARSABLE)
    }
    assert len(listed) == len(set(listed)) and set(listed) == want


# "python -m sqll_harness.corpus tables REPORT".


def test_the_tables_command_prints_the_tables(capsys):
    assert corpus("tables", baseline.BASELINE) == 0
    assert capsys.readouterr().out == tables.markdown(BASE)


def test_the_tables_command_refuses_a_report_with_an_error(tmp_path, capsys):
    rep = copy.deepcopy(BASE)
    rep["totals"]["sqruff"]["ok"] += 1
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(rep))
    assert corpus("tables", path) == 1
    assert "FAIL:" in capsys.readouterr().out


def test_a_reason_is_one_short_line_in_a_code_span():
    text = tables.reason_text("a |b|\n`c`  " + "x" * 300)
    assert text.startswith("`a \\|b\\| 'c' x") and text.endswith("...`")
    assert len(text.replace("\\|", "|")) == tables.REASON_TEXT + 2
