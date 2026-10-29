"""S3 T7: license, attribution duties, code size, and structure of each base.

results/s3/license-size.json is the output of scripts/s3/license_size.py
(report) on results/s3/license-size-sources.json (collect), the T5 build
record, and the pinned submodule. The tests compute the derived values
again from the sources and check the sqlfluff facts on the submodule."""

import copy
import importlib.util
import json
import re

import pytest

from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT

_spec = importlib.util.spec_from_file_location(
    "license_size", REPO_ROOT / "scripts" / "s3" / "license_size.py"
)
ls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ls)

OUT = json.loads(ls.OUT_FILE.read_text("utf8"))
SOURCES = json.loads(ls.SOURCES_FILE.read_text("utf8"))
T5 = json.loads(ls.T5_BUILD_FILE.read_text("utf8"))
BASES = OUT["bases"]
DEPENDENCY_SOURCES = {
    "sqruff": SOURCES["sqruff"]["dependencies"],
    "sqlfluffrs": SOURCES["sqlfluffrs"]["dependencies"],
}


# The drift test and the fail-closed checks.


def test_the_committed_output_is_the_output_of_the_committed_inputs():
    assert ls.main(["report", "--check"]) == 0


def test_the_check_fails_on_a_change(tmp_path, monkeypatch):
    out = tmp_path / "out.json"
    out.write_text(ls.OUT_FILE.read_text("utf8").replace('"T7"', '"T8"'), "utf8")
    monkeypatch.setattr(ls, "OUT_FILE", out)
    assert ls.main(["report", "--check"]) == 1


def test_the_inputs_are_the_committed_files():
    assert OUT["inputs"] == {
        "results/s3/license-size-sources.json": ls.probe.sha256_file(ls.SOURCES_FILE),
        "results/s3/sqlfluffrs-probe-build.json": ls.probe.sha256_file(
            ls.T5_BUILD_FILE
        ),
    }


def _report_of(tmp_path, sources=None, t5=None):
    s = tmp_path / "sources.json"
    t = tmp_path / "t5.json"
    s.write_text(json.dumps(sources or SOURCES), "utf8")
    t.write_text(json.dumps(t5 or T5), "utf8")
    return ls.make_report(sources_path=s, t5_path=t)


def test_a_license_file_that_is_not_the_submodule_file_fails(tmp_path):
    sources = copy.deepcopy(SOURCES)
    sources["sqlfluff"]["license_files"][0]["sha256"] = "0" * 64
    with pytest.raises(ls.DataError, match="not the file of the submodule"):
        _report_of(tmp_path, sources=sources)


def test_a_license_text_that_is_not_the_recorded_file_fails(tmp_path):
    sources = copy.deepcopy(SOURCES)
    entry = sources["sqruff"]["repository"]["license_files"][0]
    entry["text"] = entry["text"].replace("Apache", "Other", 1)
    with pytest.raises(ls.DataError, match="not the recorded file"):
        _report_of(tmp_path, sources=sources)


def test_other_sqlfluffrs_lines_fail(tmp_path):
    sources = copy.deepcopy(SOURCES)
    sources["sqlfluffrs"]["lines"]["sqlfluffrs_parser"]["hand_written"]["lines"] += 1
    with pytest.raises(ls.DataError, match="hand-written lines"):
        _report_of(tmp_path, sources=sources)


def test_other_generated_files_than_t5_fail(tmp_path):
    sources = copy.deepcopy(SOURCES)
    sources["sqlfluffrs"]["generated_files"][0]["sha256"] = "0" * 64
    with pytest.raises(ls.DataError, match="T5 build"):
        _report_of(tmp_path, sources=sources)


def test_crates_of_another_commit_fail(tmp_path):
    sources = copy.deepcopy(SOURCES)
    sources["sqruff"]["crates"]["sqruff-lib"]["vcs_commit"] = "0" * 40
    with pytest.raises(ls.DataError, match="tag commit"):
        _report_of(tmp_path, sources=sources)


def test_other_python_lines_fail(tmp_path):
    sources = copy.deepcopy(SOURCES)
    sources["sqlfluff"]["python_lines"]["dialects"]["lines"] += 1
    with pytest.raises(ls.DataError, match="Python lines"):
        _report_of(tmp_path, sources=sources)


# License claims: each one cites the file and the version.


def test_each_base_license_cites_its_file_version_and_hash():
    for name, base in BASES.items():
        lic = base["license"]
        assert lic["file"] and lic["version"] and lic["source"], name
        assert re.fullmatch(r"[0-9a-f]{64}", lic["sha256"]), name
        assert lic["copyright"], name


def test_the_sqruff_license_is_read_at_the_tag_of_the_crates():
    repo = SOURCES["sqruff"]["repository"]
    commits = {c["vcs_commit"] for c in SOURCES["sqruff"]["crates"].values()}
    assert commits == {repo["commit"]}
    assert repo["tag"] == "v0.41.0"
    lic = BASES["sqruff"]["license"]
    assert repo["commit"] in lic["source"] and lic["version"] == "v0.41.0"
    entry = next(f for f in repo["license_files"] if f["path"] == "LICENSE")
    assert entry["text"].lstrip().startswith("Apache License")
    assert "Version 2.0, January 2004" in entry["text"]
    assert ls.sha256_bytes(entry["text"].encode("utf8")) == lic["sha256"]
    assert lic["copyright"] == ls.copyright_lines(entry["text"])
    assert lic["spdx"] == "Apache-2.0"
    assert set(lic["cargo_license_of_each_crate"].values()) == {"Apache-2.0"}


def test_the_published_sqruff_crates_have_no_license_file():
    crates = SOURCES["sqruff"]["crates"]
    assert set(crates) == set(ls.SQRUFF_CRATES)
    assert all(c["license_like_files"] == [] for c in crates.values())
    assert BASES["sqruff"]["license_files_in_published_crates"] == {
        name: [] for name in ls.SQRUFF_CRATES
    }


def test_the_sqruff_tag_has_no_notice_file():
    names = [f["path"] for f in SOURCES["sqruff"]["repository"]["license_files"]]
    assert not any(n.rsplit("/", 1)[-1].lower().startswith("notice") for n in names)
    assert BASES["sqruff"]["notice_files_in_repository"] == []


def test_the_sqlfluff_licenses_are_the_submodule_files():
    for entry in SOURCES["sqlfluff"]["license_files"]:
        data = (SQLFLUFF_ROOT / entry["path"]).read_bytes()
        assert ls.sha256_bytes(data) == entry["sha256"]
        assert entry["text"] == data.decode("utf8")
        assert entry["first_line"] == "MIT License"
    for name in ("sqlfluffrs", "new-parser"):
        lic = BASES[name]["license"]
        data = (SQLFLUFF_ROOT / lic["file"]).read_bytes()
        assert ls.sha256_bytes(data) == lic["sha256"]
        assert lic["copyright"] == ls.copyright_lines(data.decode("utf8"))
        assert "0348222a3bcdb0226563f7349c5a39beb0641955" in lic["source"]


def test_the_sqlfluffrs_crates_have_no_cargo_license_field():
    for folder in ls.probe.CRATE_DIRS.values():
        manifest = SQLFLUFF_ROOT / "sqlfluffrs" / folder / "Cargo.toml"
        assert not re.search(r"^license", manifest.read_text("utf8"), re.M)
    fields = BASES["sqlfluffrs"]["license"]["cargo_license_of_each_crate"]
    assert set(fields.values()) == {None}


def test_the_duties_quote_the_license_texts():
    mit = next(
        f for f in SOURCES["sqlfluff"]["license_files"] if f["path"] == "LICENSE.md"
    )
    assert BASES["sqlfluffrs"]["duties"]["condition_text"] in " ".join(
        mit["text"].split()
    )
    assert [d[:5] for d in BASES["sqruff"]["duties"]["section_4"]] == [
        "4(a):",
        "4(b):",
        "4(c):",
        "4(d):",
    ]


# Dependency tables.


def test_the_classes_of_spdx_expressions():
    cases = {
        "MIT": "permissive",
        "MIT OR Apache-2.0": "permissive",
        "MIT/Apache-2.0": "permissive",
        "(MIT OR Apache-2.0) AND Unicode-3.0": "permissive",
        "Apache-2.0 WITH LLVM-exception": "permissive",
        "Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT": "permissive",
        "MIT OR LGPL-3.0-or-later": "permissive",
        "MPL-2.0": "weak_copyleft",
        "MPL-2.0 AND MIT": "weak_copyleft",
        "GPL-3.0-only": "strong_copyleft",
        "GPL-3.0-only OR LGPL-2.1-or-later": "weak_copyleft",
        "MIT AND GPL-2.0-or-later": "strong_copyleft",
        "Apache-2.0 WITH Other-exception": "unknown",
        "Foo-1.0": "unknown",
        "MIT OR": "unknown",
        "(MIT": "unknown",
        "": "unknown",
        None: "unknown",
    }
    for expr, want in cases.items():
        assert ls.classify(expr) == want, expr


def test_the_non_permissive_names_of_an_expression():
    assert ls.names_non_permissive("MIT OR LGPL-3.0-or-later") == ["LGPL-3.0-or-later"]
    assert ls.names_non_permissive("Apache-2.0 WITH LLVM-exception OR MIT") == []
    assert ls.names_non_permissive(None) == []


def test_python_licenses():
    row = {
        "license_expression": None,
        "license_field": None,
        "license_classifiers": ["License :: OSI Approved :: MIT License"],
    }
    assert ls.python_license(row) == ("MIT", "Classifier")
    row["license_expression"] = "BSD-3-Clause"
    assert ls.python_license(row) == ("BSD-3-Clause", "License-Expression")
    row = {"license_expression": None, "license_field": "x", "license_classifiers": []}
    assert ls.python_license(row) == (None, "none")


@pytest.mark.parametrize(
    "base,profile",
    [(b, p) for b, profiles in DEPENDENCY_SOURCES.items() for p in profiles],
)
def test_each_dependency_table_counts_the_cargo_data(base, profile):
    rows = DEPENDENCY_SOURCES[base][profile]["packages"]
    table = BASES[base]["dependencies"][profile]
    third = [r for r in rows if not r["own"]]
    assert table["packages"] == len(third) > 0
    assert sum(table["by_license"].values()) == len(third)
    assert sum(table["by_class"].values()) == len(third)
    assert table["by_class"]["permissive"] == sum(
        ls.classify(r["license"]) == "permissive" for r in third
    )
    listed = {(r["name"], r["version"]) for r in table["not_permissive"]}
    assert listed == {
        (r["name"], r["version"])
        for r in third
        if ls.classify(r["license"]) != "permissive"
    }
    assert {(r["name"], r["version"]) for r in table["permissive_choice_over"]} == {
        (r["name"], r["version"])
        for r in third
        if ls.names_non_permissive(r["license"])
    } - listed
    own = {r["name"] for r in rows if r["own"]}
    assert own and all(n.startswith(("sqruff", "sqlfluffrs")) for n in own)
    assert all(r["version"] and r["source"] for r in rows)
    assert DEPENDENCY_SOURCES[base][profile]["command"].startswith(
        "cargo tree --locked -e normal,build --target all"
    )


def test_the_generator_environment_table():
    env = OUT["generator_environment"]
    rows = env["rows"]
    assert "sqlfluff" in {r["name"] for r in rows}
    assert (
        env["packages"]
        == len(rows)
        == len(SOURCES["sqlfluff"]["generator_environment"])
    )
    assert sum(env["by_class"].values()) == len(rows)
    listed = {r["name"] for r in env["not_permissive"]}
    assert listed == {
        r["name"] for r in rows if ls.classify(r["license"]) != "permissive"
    }


# Lines.


def test_the_line_tool_and_command_are_stated():
    assert "line_count of scripts/s3/sqlfluffrs_probe.py" in OUT["method"]["lines"]
    assert OUT["method"]["lines_command"] == ls.COMMANDS["collect"]


def test_the_line_counts_add_up():
    for name in ("sqruff", "sqlfluffrs"):
        size = BASES[name]["size"]
        for kind in ("hand_written", "generated"):
            assert size["totals"][kind] == sum(
                c[kind]["lines"] for c in size["crates"].values()
            )
            for c in size["crates"].values():
                assert c[kind]["lines"] == sum(
                    p["lines"] for p in c[kind]["by_part"].values()
                )


def test_the_sqlfluffrs_lines_are_those_of_t5_and_the_submodule():
    assert BASES["sqlfluffrs"]["size"]["crates"] == T5["lines"]
    tracked = ls.probe.tracked_files(SQLFLUFF_ROOT)
    hand = ls.probe.rust_lines(SQLFLUFF_ROOT / "sqlfluffrs", tracked)
    for crate, kinds in T5["lines"].items():
        assert hand[crate]["hand_written"] == kinds["hand_written"]
    generated = SOURCES["sqlfluffrs"]["generated_files"]
    assert (
        sum(f["lines"] for f in generated)
        == (BASES["sqlfluffrs"]["size"]["totals"]["generated"])
    )
    assert (
        sum(BASES["sqlfluffrs"]["size"]["generated_by_dialect"].values())
        == (BASES["sqlfluffrs"]["size"]["totals"]["generated"])
    )


def test_the_sqruff_generated_files_have_a_mark():
    for c in SOURCES["sqruff"]["crates"].values():
        for f in c["rust"]["generated_files"]:
            assert ls.GENERATED_MARK.search(f["first_line"])


def test_the_line_count_rule():
    assert ls.line_count(b"") == 0
    assert ls.line_count(b"a") == 1
    assert ls.line_count(b"a\n") == 1
    assert ls.line_count(b"a\n\nb") == 3


def test_the_option_3_size_is_an_estimate():
    size = BASES["new-parser"]["size"]
    assert size["kind"] == "estimate" and size["formula"]
    lines = BASES["sqlfluffrs"]["size"]["crates"]
    assert size["hand_written_engine"] == sum(
        lines[c]["hand_written"]["lines"]
        for c in ("sqlfluffrs_types", "sqlfluffrs_lexer", "sqlfluffrs_parser")
    )
    assert size["generated"] == BASES["sqlfluffrs"]["size"]["totals"]["generated"]


# Open questions, sqll, and status.


def test_open_questions_and_the_sqll_license_state():
    assert len(OUT["open_questions"]) >= 5
    assert OUT["sqll"]["root_license_files"] == []
    assert re.fullmatch(r"[0-9a-f]{40}", OUT["sqll"]["commit"])


def test_the_status_and_the_decision_record_name_the_output():
    status = (REPO_ROOT / "status" / "S3.md").read_text("utf8")
    row = next(line for line in status.splitlines() if line.startswith("| T7 |"))
    assert "Not started" not in row
    assert "results/s3/license-size.json" in status
    totals = BASES["sqruff"]["size"]["totals"]
    assert f"{totals['hand_written']} hand-written" in status
    rs = BASES["sqlfluffrs"]["size"]["totals"]
    assert f"{rs['hand_written']} hand-written" in status
    for base, profile in (("sqruff", "installed"), ("sqlfluffrs", "standalone")):
        n = BASES[base]["dependencies"][profile]["packages"]
        assert f"{n} packages" in status, (base, profile)
    decision = (REPO_ROOT / "docs" / "decisions" / "s3-base.md").read_text("utf8")
    c6 = next(
        line
        for line in decision.splitlines()
        if line.startswith("| C6 |") and "| T7 |" in line
    )
    assert "`results/s3/license-size.json`" in c6
    assert "scripts/s3/license_size.py" in c6
