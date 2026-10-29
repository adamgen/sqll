"""S3 T8: the capabilities of each base for S6, S7, G2 and S8, and the
cause of the G3 start time.

results/s3/capabilities.json is the output of scripts/s3/capabilities.py
(report) on results/s3/capabilities-sources.json (collect),
results/s3/capabilities-start.json (time), the other committed results,
and the pinned submodule. The tests check the parsers, the evidence of each
entry, and the fail-closed checks. With the tools installed, they run the
recorded commands again."""

import copy
import importlib.util
import json
import os
import re
import subprocess

import pytest
from conftest import needs

from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT, tools_dir

_spec = importlib.util.spec_from_file_location(
    "capabilities", REPO_ROOT / "scripts" / "s3" / "capabilities.py"
)
cap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cap)

OUT = json.loads(cap.OUT_FILE.read_text("utf8"))
SOURCES = json.loads(cap.SOURCES_FILE.read_text("utf8"))
START = json.loads(cap.START_FILE.read_text("utf8"))
T7_SOURCES = json.loads(cap.T7_SOURCES.read_text("utf8"))


# The drift test and the fail-closed checks.


def test_the_committed_output_is_the_output_of_the_committed_inputs():
    assert cap.main(["report", "--check"]) == 0


def test_the_check_fails_on_a_change(tmp_path, monkeypatch):
    out = tmp_path / "out.json"
    out.write_text(cap.OUT_FILE.read_text("utf8").replace('"T8"', '"T9"'), "utf8")
    monkeypatch.setattr(cap, "OUT_FILE", out)
    assert cap.main(["report", "--check"]) == 1


def test_the_inputs_are_the_committed_files():
    for path, digest in OUT["inputs"].items():
        assert cap.sha256_file(REPO_ROOT / path) == digest, path
    assert set(OUT["inputs"]) >= {
        "results/s3/capabilities-sources.json",
        "results/s3/capabilities-start.json",
        "results/s3/s1-by-base.json",
        "known_failures/sqruff.txt",
    }


def _report_of(tmp_path, sources=None, start=None):
    s = tmp_path / "sources.json"
    t = tmp_path / "start.json"
    s.write_text(json.dumps(sources or SOURCES), "utf8")
    t.write_text(json.dumps(start or START), "utf8")
    return cap.make_report(sources_path=s, start_path=t)


def test_the_report_of_copies_of_the_inputs_is_the_output(tmp_path):
    out = _report_of(tmp_path)
    assert out["tables"] == OUT["tables"]
    assert out["S7"] == OUT["S7"]


def test_help_of_another_sqruff_version_fails(tmp_path):
    sources = copy.deepcopy(SOURCES)
    sources["commands"]["sqruff --version"]["stdout"] = "sqruff 0.40.0\n"
    with pytest.raises(cap.DataError, match="not of sqruff 0.41.0"):
        _report_of(tmp_path, sources=sources)


def test_a_failed_command_fails(tmp_path):
    sources = copy.deepcopy(SOURCES)
    sources["commands"]["sqruff lint --help"]["exit_code"] = 2
    with pytest.raises(cap.DataError, match="exit code 2"):
        _report_of(tmp_path, sources=sources)


def test_a_crate_that_is_not_the_crate_of_t7_fails(tmp_path):
    sources = copy.deepcopy(SOURCES)
    sources["sqruff"]["crates"]["sqruff-lib"]["sha256"] = "0" * 64
    with pytest.raises(cap.DataError, match="not the crate of T7"):
        _report_of(tmp_path, sources=sources)


def test_a_fact_from_another_crate_fails(tmp_path):
    sources = copy.deepcopy(SOURCES)
    ev = sources["sqruff"]["facts"]["config_files"]["evidence"][0]["source"]
    ev["crate_sha256"] = "0" * 64
    with pytest.raises(cap.DataError, match="not a file of the recorded crate"):
        _report_of(tmp_path, sources=sources)


def test_another_syntax_kind_count_than_t7_fails(tmp_path):
    sources = copy.deepcopy(SOURCES)
    sources["sqruff"]["facts"]["syntax_kinds"]["value"] += 1
    with pytest.raises(cap.DataError, match="count of T7"):
        _report_of(tmp_path, sources=sources)


def test_a_help_text_that_drops_an_option_fails(tmp_path):
    sources = copy.deepcopy(SOURCES)
    entry = sources["commands"]["sqlfluff lint --help"]
    lines = entry["stdout"].splitlines(keepends=True)
    entry["stdout"] = "".join(line for line in lines if "--nofail" not in line)
    with pytest.raises(cap.DataError, match="not the click options"):
        _report_of(tmp_path, sources=sources)


def test_other_sqruff_templaters_than_the_source_fail(tmp_path):
    sources = copy.deepcopy(SOURCES)
    sources["commands"]["sqruff templaters"]["stdout"] = "raw\nplaceholder\n"
    with pytest.raises(cap.DataError, match="TEMPLATERS list"):
        _report_of(tmp_path, sources=sources)


def test_other_placeholder_styles_than_the_source_fail(tmp_path):
    sources = copy.deepcopy(SOURCES)
    del sources["sqlfluff"]["placeholder_styles"]["percent"]
    with pytest.raises(cap.DataError, match="placeholder styles"):
        _report_of(tmp_path, sources=sources)


def test_unsupported_settings_that_do_not_agree_with_t2_fail(tmp_path, monkeypatch):
    text = cap.KNOWN_FAILURES.read_text("utf8")
    line = next(x for x in text.splitlines() if "# unsupported: setting" in x)
    path = tmp_path / "sqruff.txt"
    path.write_text(text.replace(line + "\n", ""), "utf8")
    monkeypatch.setattr(cap, "KNOWN_FAILURES", path)
    with pytest.raises(cap.DataError, match="T2 has"):
        _report_of(tmp_path)


def test_a_start_session_with_missing_results_fails(tmp_path):
    start = copy.deepcopy(START)
    start["report"]["results"] = [
        r for r in start["report"]["results"] if r["id"] != "start/ansi"
    ]
    with pytest.raises(cap.DataError, match="28 valid sqlfluff"):
        _report_of(tmp_path, start=start)


@pytest.mark.parametrize(
    "entry, message",
    [
        ({"value": 1, "evidence": []}, "no evidence"),
        ({"value": 1, "evidence": [{"command": "x"}]}, "unknown command"),
        ({"value": 1, "evidence": [{"other": 1}]}, "unknown evidence kind"),
        (
            {"value": 1, "estimate": True, "evidence": [{"search": "s"}]},
            "no judgement",
        ),
        (
            {"value": 1, "evidence": [{"result": "results/s3/none.json", "key": "a"}]},
            "does not exist",
        ),
        (
            {
                "value": 1,
                "evidence": [{"document": "STONES.md", "text": "no such text"}],
            },
            "does not have the text",
        ),
    ],
)
def test_the_evidence_check(entry, message):
    with pytest.raises(cap.DataError, match=message):
        cap.check_evidence({"x": entry}, SOURCES, START)


def test_a_result_key_that_does_not_exist_fails():
    entry = {
        "value": 1,
        "evidence": [{"result": "results/s3/s1-by-base.json", "key": "x"}],
    }
    with pytest.raises(KeyError):
        cap.check_evidence({"x": entry}, SOURCES, START)


def test_a_fact_or_estimate_needs_evidence():
    with pytest.raises(cap.DataError):
        cap.fact(1)
    with pytest.raises(cap.DataError):
        cap.estimate(1, "why")


# The help text parsers.

CLAP = """Lint SQL files

Usage: sqruff lint [OPTIONS] [PATHS]...

Arguments:
  [PATHS]...
          Files or directories to fix

Options:
  -v, --verbose...
          Show more detail

      --disregard-sqruffignores
          Perform the operation regardless of ignore files

          [alias: --disregard-sqlfluffignores]

  -f, --format <FORMAT>
          Possible values:
          - human
          - json
          - none:   Produce no output

          [default: human]

      --config <CONFIG>
          Path to a configuration file
  -h, --help
          Print help
"""

CLICK = """Usage: sqlfluff lint [OPTIONS] [PATHS]...

  Lint SQL files.

Options:
  -n, --nocolor / --color         No color - output will be without ANSI color
                                  codes.
  --stdin-filename PATH           When using stdin as an input, load the
                                  - configuration.
  --logger [templater|lexer|parser]
                                  Choose a logger.
  -h, --help                      Show this message and exit.
"""


def test_clap_options():
    opts = cap.clap_options(CLAP)
    assert [o["long"] for o in opts] == [
        "--verbose",
        "--disregard-sqruffignores",
        "--format",
        "--config",
        "--help",
    ]
    by = cap.option_index(opts)
    assert by["--disregard-sqlfluffignores"]["long"] == "--disregard-sqruffignores"
    assert by["--format"]["choices"] == ["human", "json", "none"]
    assert by["--format"]["short"] == "-f" and by["--format"]["value"] == "FORMAT"
    assert by["--config"]["choices"] is None and by["--config"]["short"] is None
    assert cap.usage_args(CLAP) == ["[PATHS]..."]
    two = cap.clap_options(
        CLAP.replace("[alias: --disregard-sqlfluffignores]", "[aliases: --a, --b]")
    )
    assert two[1]["aliases"] == ["--a", "--b"]


def test_the_recorded_sqruff_alias_matches_the_sqlfluff_option():
    lint = OUT["S7"]["options"]["lint"]["value"]
    assert "--disregard-sqlfluffignores" in lint["both"]


def test_clap_options_fail_on_a_line_that_they_do_not_read():
    with pytest.raises(cap.DataError, match="does not read"):
        cap.clap_options(CLAP.replace("--config <CONFIG>", "--config=<CONFIG>"))


def test_click_options():
    opts = cap.click_options(CLICK)
    assert [o["names"] for o in opts] == [
        ["-n", "--nocolor", "--color"],
        ["--stdin-filename"],
        ["--logger"],
        ["-h", "--help"],
    ]
    assert opts[1]["value"] == "PATH" and opts[1]["choices"] is None
    assert opts[2]["choices"] == ["templater", "lexer", "parser"]
    assert set(cap.option_index(opts)) == {
        "--nocolor",
        "--color",
        "--stdin-filename",
        "--logger",
        "--help",
    }


def test_click_options_fail_on_a_line_that_they_do_not_read():
    with pytest.raises(cap.DataError, match="does not read"):
        cap.click_options(CLICK.replace("  --logger [", "  --logger=["))
    with pytest.raises(cap.DataError, match="does not read"):
        cap.click_options(CLICK + " stray text\n")


def test_command_names_stop_at_the_end_of_the_list():
    text = "Usage: x\n\nCommands:\n  lint  Lint.\n  fix   Fix.\n\n  Examples:\n"
    assert cap.command_names(text) == ["lint", "fix"]
    with pytest.raises(cap.DataError):
        cap.command_names("Usage: x\n\nOptions:\n  -h\n")


def test_compare_options():
    a = cap.click_options(CLICK)
    b = cap.clap_options(CLAP)
    cmp = cap.compare_options(a, b)
    assert cmp["both"] == ["--help"]
    assert "--logger" in cmp["only_sqlfluff"] and "--format" in cmp["only_sqruff"]
    assert cmp["short_names_that_differ"] == {}


def test_setting_groups():
    assert cap.setting_group("layout.type.alias_expression.align_within") == (
        "layout.type.*.align_within"
    )
    assert cap.setting_group("templater.jinja.macros.foo") == "templater.jinja.macros.*"
    assert cap.setting_group("rules.indent_unit") == "rules.indent_unit"


def test_default_keys_of_an_ini_file():
    text = "[sqruff]\ndialect = ansi\n\n[sqruff:rules:aliasing.length]\nmin = 1\n"
    assert cap.ini_keys(text, "sqruff") == ["core.dialect", "rules.aliasing.length.min"]
    with pytest.raises(cap.DataError, match="not under"):
        cap.ini_keys("[other]\na = 1\n", "sqruff")
    assert cap.split_key("rules.capitalisation.keywords.x") == [
        "rules",
        "capitalisation.keywords",
        "x",
    ]


# The evidence.


def test_each_entry_has_evidence_and_each_estimate_a_judgement():
    entries = list(cap.walk_facts(OUT))
    assert len(entries) > 50
    for e in entries:
        assert e["evidence"], e
        if e.get("estimate"):
            assert e["judgement"].strip(), e
    cap.check_evidence(OUT, SOURCES, START)


def _sources(node):
    for e in cap.walk_facts(node):
        for ev in e["evidence"]:
            if "source" in ev:
                yield ev["source"]


def test_the_cited_submodule_and_repository_lines_are_the_file_lines():
    seen = 0
    for src in _sources(OUT):
        if src["base"] == "sqruff":
            continue
        path = REPO_ROOT / src["file"]
        assert cap.sha256_file(path) == src["sha256"], src["file"]
        lines = path.read_text("utf8").splitlines()
        for no, text in src["lines"].items():
            assert lines[int(no) - 1].strip() == text, (src["file"], no)
        if src["base"] in ("sqlfluff", "sqlfluffrs"):
            assert src["commit"] == cap.sqlfluff_ref(SQLFLUFF_ROOT)
            assert src["file"].startswith("third_party/sqlfluff/")
        seen += 1
    assert seen > 10


def test_the_sqruff_sources_are_files_of_the_t7_crates():
    t7 = {k: v["sha256"] for k, v in T7_SOURCES["sqruff"]["crates"].items()}
    seen = 0
    for src in _sources(OUT):
        if src["base"] == "sqruff":
            assert src["version"] == "0.41.0"
            assert t7[src["crate"]] == src["crate_sha256"]
            assert re.fullmatch(r"[0-9a-f]{64}", src["sha256"])
            seen += 1
    assert seen > 10


def test_the_option_lists_come_from_the_recorded_help_commands():
    for name, entry in OUT["S7"]["options"].items():
        cited = [ev["command"] for ev in entry["evidence"] if "command" in ev]
        assert f"sqlfluff {name} --help" in cited and f"sqruff {name} --help" in cited
        for cid in cited[:2]:
            tool = cid.split()[0]
            rec = SOURCES["commands"][cid]
            assert rec["argv"] == [f"$TOOLS/{tool}/bin/{tool}", name, "--help"]
            assert rec["exit_code"] == 0
        parsed = cap.help_options(SOURCES)
        cmp = cap.compare_options(
            parsed["sqlfluff"]["by_command"][name]["options"],
            parsed["sqruff"]["by_command"][name]["options"],
        )
        assert entry["value"]["both"] == cmp["both"]


def _run_recorded(cid):
    rec = SOURCES["commands"][cid]
    argv = [a.replace("$TOOLS", str(tools_dir())) for a in rec["argv"]]
    if cid == "sqlfluff facts":
        argv[3] = cap.PY_FACTS
    env = {**os.environ, **SOURCES["help_env"]}
    proc = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=120)
    return proc.returncode, proc.stdout.replace(str(tools_dir()), "$TOOLS")


@needs("sqlfluff/bin/sqlfluff", "sqruff/bin/sqruff")
@pytest.mark.parametrize("cid", sorted(SOURCES["commands"]))
def test_a_recorded_command_gives_the_recorded_output(cid, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, stdout = _run_recorded(cid)
    rec = SOURCES["commands"][cid]
    assert code == rec["exit_code"]
    assert stdout == rec["stdout"]


# The content.


def test_the_sqruff_templaters():
    rows = {r["templater"]: r for r in OUT["S6"]["templaters"]}
    native = {n for n, r in rows.items() if r["sqruff"]["value"]["native"]}
    python = {
        n for n, r in rows.items() if r["sqruff"]["value"]["needs_python_runtime"]
    }
    assert native == {"raw", "placeholder"}
    assert python == {"jinja", "python", "dbt", "sqlmesh"}
    for n in python:
        assert rows[n]["sqruff"]["value"]["pyo3_use_lines"] > 0, n
    for n in native:
        assert rows[n]["sqruff"]["value"]["pyo3_use_lines"] == 0, n
    for base in ("sqlfluffrs", "new-parser"):
        assert all(
            r[base]["estimate"] and not r[base]["value"]["exists"]
            for r in rows.values()
        )


def test_the_templater_suite_counts_are_those_of_t2():
    t2 = json.loads(cap.T2_FILE.read_text("utf8"))
    for base in ("sqruff", "sqlfluffrs"):
        v = OUT["S6"]["templater_suite"][base]["value"]
        s = t2["bases"][base]["suites"]["templater"]
        assert (v["cases"], v["pass"]) == (s["total"], s["pass"])
        assert v["no_python_cases"] + v["needs_python"] == v["cases"]


def test_the_unsupported_settings_add_up():
    v = OUT["S7"]["config_keys"]["s1_unsupported_settings"]["value"]
    assert sum(v["by_suite"].values()) == v["cases"]
    assert sum(v["by_group"].values()) == sum(v["by_setting"].values())
    assert sum(v["by_setting"].values()) >= v["cases"]


def test_the_start_shares_add_up():
    ref = OUT["G3_start"]["sqlfluff_reference"]["value"]
    total = (
        ref["python_share_of_start"]
        + ref["import_only_share_of_start"]
        + ref["rest_share_of_start"]
    )
    assert abs(total - 1) <= 0.002


def test_the_start_session_ran_on_an_idle_machine_in_the_ci_image():
    steps = {s["step"]: s for s in START["steps"]}
    assert steps["timing session"]["exit_code"] == 0
    assert "docker" == steps["timing session"]["argv"][0]
    assert START["session"]["load"]["after"][1] <= cap.MAX_SESSION_LOAD
    for s in START["series"].values():
        assert s["stats"]["wall_s"]["n"] == cap.START_POLICY["min_runs"]


def test_each_table_row_has_a_cell_for_each_column_and_option_3_is_an_estimate():
    assert set(OUT["tables"]) == {"S6", "S7", "G2_S8", "G3_start"}
    for name, table in OUT["tables"].items():
        cols = table["columns"]
        option3 = cols.index("3 new parser")
        for row in table["rows"]:
            assert len(row) == len(cols), (name, row)
            assert "estimate" in row[option3], (name, row)


def test_the_status_and_the_decision_record_name_the_output():
    status = (REPO_ROOT / "status" / "S3.md").read_text("utf8")
    row = next(line for line in status.splitlines() if line.startswith("| T8 |"))
    assert "Not started" not in row
    assert "results/s3/capabilities.json" in status
    decision = (REPO_ROOT / "docs" / "decisions" / "s3-base.md").read_text("utf8")
    c7 = next(
        line
        for line in decision.splitlines()
        if line.startswith("| C7 |") and "| T8 |" in line
    )
    assert "`results/s3/capabilities.json`" in c7
    assert "scripts/s3/capabilities.py" in c7


def test_the_status_numbers_are_those_of_the_output():
    status = " ".join((REPO_ROOT / "status" / "S3.md").read_text("utf8").split())
    s6 = OUT["S6"]
    suite = s6["templater_suite"]["sqruff"]["value"]
    assert f"sqruff passes {suite['pass']} of {suite['cases']}" in status
    assert (
        f"({suite['no_python_pass']} of the {suite['no_python_cases']} cases" in status
    )
    styles = s6["placeholder_styles"]["rows"]
    same = sum(r["sqruff"]["value"]["same_pattern"] for r in styles)
    assert f"{same} of the {len(styles)} sqlfluff placeholder styles" in status
    opts = OUT["S7"]["options"]
    both = sum(len(v["value"]["both"]) for v in opts.values())
    total = sum(v["value"]["sqlfluff"] for v in opts.values())
    assert f"{both} of the {total} option names of the {len(opts)} shared" in status
    keys = OUT["S7"]["config_keys"]
    assert (
        f"{keys['in_both_defaults']['value']} of the "
        f"{keys['sqlfluff_defaults']['value']} sqlfluff default keys"
    ) in status
    groups = keys["s1_unsupported_settings"]["value"]
    assert f"{groups['cases']} S1 cases fail with an unsupported setting" in status
    for name, n in list(groups["by_group"].items())[:2]:
        assert f"`{name}` ({n})" in status
    kinds = OUT["G2_S8"]["typed_tree"]["sqruff"]["value"]["syntax_kinds"]
    assert f"`SyntaxKind` enum ({kinds} kinds)" in status
    g3 = OUT["G3_start"]
    ref = g3["sqlfluff_reference"]["value"]
    assert f"Python {ref['python_share_of_start']}," in status
    assert f"the import of the CLI {ref['import_only_share_of_start']}," in status
    assert (
        "the rest (config, dialect, parse, output, all in Python) "
        f"{ref['rest_share_of_start']}" in status
    )
    over = g3["session_over_s2"]["value"]
    assert f"{over['sqlfluff']} (sqlfluff) and {over['sqruff']} (sqruff)" in status
    sq = g3["bases"]["sqruff"]["value"]
    assert f"the loader are {sq['process_share_of_start']} of it" in status


def test_third_party_md_names_each_cited_file_and_the_size_of_a_citation():
    text = " ".join((REPO_ROOT / "THIRD_PARTY.md").read_text("utf8").split())
    sqlfluff, sqruff = text.split(" ## sqruff ")
    for name in ("capabilities-sources.json", "capabilities.json"):
        assert f"results/s3/{name}" in sqlfluff and f"results/s3/{name}" in sqruff
    for node in (OUT, SOURCES):
        for src in _sources(node):
            name = src["file"].rsplit("/", 1)[-1]
            part = sqruff if src["base"] == "sqruff" else sqlfluff
            assert name in part, src["file"]
            limit = 28 if src["file"] == "src/templaters/types.rs" else 8
            assert len(src["lines"]) <= limit, src["file"]
