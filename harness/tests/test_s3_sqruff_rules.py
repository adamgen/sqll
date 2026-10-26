"""S3 T4: the classes of the sqruff rule, autofix, and templater failures,
and the coupling of the sqruff rules to tree shapes.

results/s3/sqruff-rule-diffs.json is the output of scripts/s3/sqruff_rules.py
on the committed inputs, the parses file is the output of a new run, and
the data agree with known_failures/sqruff.txt, the T2 per-case list, and T3."""

import copy
import importlib.util
import json
import re
import sys
from collections import Counter

import pytest
from conftest import needs, needs_sqlfluff

from sqll_harness import known_failures
from sqll_harness.compare import load_yaml
from sqll_harness.paths import KNOWN_FAILURES_DIR, REPO_ROOT, SQLFLUFF_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts" / "s3"))
_spec = importlib.util.spec_from_file_location(
    "sqruff_rules", REPO_ROOT / "scripts" / "s3" / "sqruff_rules.py"
)
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)

PARSES = json.loads(sr.PARSES_FILE.read_text("utf8"))
TYPES = json.loads(sr.TYPES_FILE.read_text("utf8"))
OUT = json.loads(sr.OUT_FILE.read_text("utf8"))
T3 = json.loads(sr.TREES_FILE.read_text("utf8"))
HUNKS = json.loads(sr.HUNKS_FILE.read_text("utf8"))
KNOWN = known_failures.load(KNOWN_FAILURES_DIR, "sqruff")


# The source scan.


@pytest.mark.parametrize(
    ("variant", "name"),
    [
        ("SelectStatement", "select_statement"),
        ("Implicit", "implicit"),
        ("CTEColumnList", "cte_column_list"),
        ("AlterTableOnlineDDLOption", "alter_table_online_ddl_option"),
        ("S3ExternalStageParameters", "s3_external_stage_parameters"),
        ("Int64Type", "int64_type"),
    ],
)
def test_snake_case_is_that_of_strum(variant, name):
    assert sr.snake_case(variant) == name


def test_strip_rust_removes_comments_literals_and_test_items():
    code = (
        'let a = r#"SyntaxKind::InRaw"#; // SyntaxKind::InLine\n'
        "/* SyntaxKind::InBlock /* nested */ */\n"
        'let s = "SyntaxKind::InString \\" x";\n'
        "let c = '{'; fn f<'a>(x: &'a str) { SyntaxKind::Kept }\n"
        "#[cfg(test)]\nmod tests { fn t() { if x { SyntaxKind::InTest } } }\n"
        "#[cfg(test)]\nuse SyntaxKind::InTestUse;\n"
        "SyntaxKind::AlsoKept"
    )
    assert sr.type_names(sr.strip_rust(code)) == ["also_kept", "kept"]


def test_use_paths():
    code = (
        "use a::b::{c, d::{e, f as g}, self};\n"
        "use x::y as z;\nuse super::cp01::RuleCP01;"
    )
    assert sr.use_paths(code) == [
        ["a", "b", "c"],
        ["a", "b", "d", "e"],
        ["a", "b", "d", "f"],
        ["a", "b"],
        ["x", "y"],
        ["super", "cp01", "RuleCP01"],
    ]


def test_rule_modules_follow_use_items_inside_the_helper_folders():
    lib = sr.Crate(
        "sqruff-lib",
        {
            "rules/x/ab01.rs": (
                "use crate::utils::reflow::sequence::ReflowSequence;\n"
                "use super::ab02::helper;\nuse crate::core::config::Value;\n"
                "use sqruff_lib_core::parser::segments::ErasedSegment;\n"
                "use sqruff_lib_core::parser::segments::from::F;"
            ),
            "rules/x/ab02.rs": "SyntaxKind::B",
            "utils/reflow/sequence.rs": "use super::config::C; SyntaxKind::S",
            "utils/reflow/config.rs": "SyntaxKind::Cfg",
            "core/config.rs": "SyntaxKind::NotAHelper",
        },
    )
    core = sr.Crate(
        "sqruff-lib-core",
        {
            "parser/segments.rs": "SyntaxKind::Base",
            "parser/segments/from.rs": "SyntaxKind::From",
        },
    )
    crates = {"sqruff-lib": lib, "sqruff-lib-core": core}
    assert sr.rule_modules(crates, "rules/x/ab01.rs") == [
        "sqruff-lib-core/parser/segments/from.rs",
        "sqruff-lib/rules/x/ab02.rs",
        "sqruff-lib/utils/reflow/config.rs",
        "sqruff-lib/utils/reflow/sequence.rs",
    ]


def test_lock_checksums():
    lock = (
        '[[package]]\nname = "sqruff-lib"\nversion = "0.41.0"\n'
        'source = "registry+x"\nchecksum = "ab12"\n\n'
        '[[package]]\nname = "local"\nversion = "1.0.0"\n'
    )
    assert sr.lock_checksums(lock) == {"sqruff-lib-0.41.0": "ab12"}


# The tree comparison and the classes.


def N(name, *children):
    return (name, tuple(children))


def L(name, raw):
    return (name, raw)


def test_compare_states():
    e = N("file", N("s", L("indent", ""), L("keyword", "a")))
    a = N("file", N("s", L("implicit", ""), L("keyword", "a")))
    assert sr.compare(e, e, "ansi") == ["equal", [], []]
    assert sr.compare(e, a, "ansi") == [sr.EQUAL_IMPLICIT, [], []]
    assert sr.compare(e, None, "ansi") == ["no sqruff tree", [], []]
    assert sr.compare(None, e, "ansi") == ["no sqlfluff tree", [], []]
    b = N("file", N("t", L("indent", ""), L("keyword", "a")))
    assert sr.compare(e, b, "ansi") == ["differs", ["renamed"], ["renamed: s -> t"]]


@pytest.mark.parametrize(
    ("key", "cls", "names"),
    [
        ("renamed: a -> b", "renamed", {"a", "b"}),
        ("leaf_type: comma -> symbol in file", "leaf_type", {"comma", "symbol"}),
        ("extra_wrapper: w in s", "extra_wrapper", {"w"}),
        ("nesting: sqruff y in s", "nesting", {"y"}),
        ("token_split: x -> y dot y", "token_split", {"x", "y", "dot"}),
        ("meta: - -> dedent", "meta", {"dedent"}),
        (
            "unparsable: tsql: create_x in table_ref",
            "unparsable",
            {"create_x", "table_ref"},
        ),
        ("missing_wrapper: a b c d e f ... in s", "missing_wrapper", set("abcdef")),
        ("unsupported_dialect: soql", "unsupported_dialect", set()),
    ],
)
def test_key_types(key, cls, names):
    assert sr.key_types(key) == (cls, names)


def _parsed(**files):
    return {"rule": "AB01", "dialect": "ansi", "files": files}


def test_classify_order_and_files():
    eq, diff = ["equal", [], []], ["differs", ["renamed"], ["renamed: a -> b"]]
    imp = [sr.EQUAL_IMPLICIT, [], []]
    reason = "unsupported: setting rules.x"
    assert sr.classify("rules", reason, None, [None] * 4)[:2] == (
        "unsupported_item",
        "setting",
    )
    p = _parsed(pass_=eq, fail=diff, fixed=eq)
    p["files"]["pass"] = p["files"].pop("pass_")
    # Only the fix check failed: it reads fail.sql.
    assert sr.classify("rules", "fix mismatch", p, [1, 1, 0, 1]) == (
        "parse_cause",
        "other tree shape",
        ["fail"],
    )
    # Only pass_str failed: pass.sql has the same tree.
    assert sr.classify("rules", "pass_str: x", p, [0, 1, 1, 1])[:2] == (
        "rule_logic",
        "pass_str",
    )
    # A tool error has no failed check: all files.
    got = sr.classify("rules", "lint: exit code 101: x panicked at y", p, [None] * 4)
    assert got == ("parse_cause", "other tree shape", ["fail", "fixed", "pass"])
    q = _parsed(before=imp)
    assert sr.classify("autofix", "fix mismatch", q, [1, 1, 1, 0])[:2] == (
        "rule_logic",
        "fix mismatch",
    )
    assert sr.classify("autofix", "fix mismatch", q, [1, 1, 1, 0], True)[0] == (
        "parse_cause"
    )
    t = _parsed(sql=imp)
    assert sr.classify("templater", "tree differs", t, [0, 1])[:2] == (
        "parse_cause",
        "implicit indent name",
    )


def test_an_unknown_unsupported_item_fails():
    with pytest.raises(sr.DataError, match="unknown unsupported item"):
        sr.unsupported_group("unsupported: something new")


# The committed data.


def test_the_committed_output_is_the_build_of_the_committed_inputs():
    assert sr.text(sr.build()) == sr.OUT_FILE.read_text("utf8")
    assert sr.main(["build", "--check"]) == 0


def test_the_check_fails_on_a_change(tmp_path):
    out = tmp_path / "out.json"
    out.write_text(sr.OUT_FILE.read_text("utf8").replace("rule_logic", "x", 1))
    assert sr.main(["build", "--check", "--out", str(out)]) == 1
    assert sr.main(["build", "--check", "--out", str(tmp_path / "none")]) == 1


@needs(
    "sqruff/bin/sqruff",
    "sqruff/python/bin/python3",
    "sqlfluff/bin/sqlfluff",
)
def test_a_new_run_gives_the_committed_parses():
    assert sr.text(sr.collect()) == sr.PARSES_FILE.read_text("utf8")


@needs_sqlfluff
def test_the_sqlfluff_types_are_those_of_the_pinned_sqlfluff():
    assert sr.sqlfluff_types() == TYPES["sqlfluff_types"]


def test_each_type_of_the_sqlfluff_fixture_trees_is_a_sqlfluff_type():
    types: set[str] = set()

    def walk(node):
        types.add(node[0])
        if isinstance(node[1], tuple):
            for child in node[1]:
                walk(child)

    fixtures = SQLFLUFF_ROOT / "test" / "fixtures"
    paths = list((fixtures / "dialects").rglob("*.yml"))
    paths += list((fixtures / "templater").rglob("*.yml"))
    for path in paths:
        tree = load_yaml(path)[1]
        if tree:
            walk(tree)
    assert len(types) > 1000
    assert types <= set(TYPES["sqlfluff_types"])


def _write(tmp_path, name, record):
    path = tmp_path / name
    path.write_text(sr.text(record), "utf8")
    return path


def test_a_missing_or_extra_case_fails(tmp_path):
    parses = copy.deepcopy(PARSES)
    parses["cases"].pop("rules/AL05/test_pass_tsql_naked_select_quoted_table")
    with pytest.raises(sr.DataError, match="missing"):
        sr.build(_write(tmp_path, "p.json", parses))
    parses = copy.deepcopy(PARSES)
    parses["cases"]["rules/AL01/new"] = parses["cases"][next(iter(parses["cases"]))]
    with pytest.raises(sr.DataError, match="extra"):
        sr.build(_write(tmp_path, "p.json", parses))


def test_another_failure_count_fails(monkeypatch):
    monkeypatch.setitem(sr.FAILURES, "rules", 341)
    with pytest.raises(sr.DataError, match="342 rules failures, not 341"):
        sr.build()


def test_each_failure_has_one_class_and_the_counts_add_up():
    rows = OUT["cases"]
    assert len(rows) == len({r[0] for r in rows}) == 373
    scope = {cid for cid in KNOWN if cid.split("/", 1)[0] in sr.SUITES}
    assert {r[0] for r in rows} == scope
    for suite in sr.SUITES:
        mine = [r for r in rows if r[1] == suite]
        assert len(mine) == sr.FAILURES[suite]
        assert len(mine) == sum(1 for c in KNOWN if c.startswith(suite + "/"))
        got = Counter(r[3] for r in mine)
        assert OUT["counts"][suite] == {c: got[c] for c in sr.CLASSES}
        assert sum(OUT["counts"][suite].values()) == sr.FAILURES[suite]
        kinds = Counter(f"{r[3]}: {r[4]}" for r in mine)
        assert OUT["kinds"][suite] == dict(sorted(kinds.items()))
    for r in rows:
        assert r[3] in sr.CLASSES
        assert (r[3] == "unsupported_item") == KNOWN[r[0]].startswith("unsupported: ")
    assert OUT["total"] == {
        c: sum(OUT["counts"][s][c] for s in sr.SUITES) for c in sr.CLASSES
    }
    assert sum(sum(v.values()) for v in OUT["by_rule"].values()) == 373
    for name in ("implicit_differs", "all_files"):
        assert sum(OUT["sensitivity"][name].values()) == 373


def test_the_parse_cause_cases_have_a_tree_difference():
    for r in OUT["cases"]:
        if r[3] == "unsupported_item":
            assert r[0] not in PARSES["cases"]
            continue
        states = [PARSES["cases"][r[0]]["files"][f][0] for f in r[5]]
        assert states
        equal = ("equal",) if r[1] == "templater" else sr.TREE_STATES_EQUAL
        assert (r[3] == "parse_cause") == any(s not in equal for s in states)


def test_the_templater_trees_agree_with_t3():
    for cid, row in PARSES["cases"].items():
        if not cid.startswith("templater/"):
            continue
        state = row["files"]["sql"][0]
        if KNOWN[cid] == "tree differs":
            # T3: only the meta name differs (meta: indent -> implicit).
            assert {h[1] for h in HUNKS["cases"][cid]["hunks"]} == {
                "meta: indent -> implicit"
            }
            assert state == sr.EQUAL_IMPLICIT
        else:
            assert state == "no sqruff tree"


def test_the_types_file_has_only_names():
    name = re.compile(r"^[a-z][a-z0-9_]*$")
    module = re.compile(r"^sqruff-lib(-core)?/[a-z0-9_/]+\.rs$")
    assert set(TYPES["crates"]) == set(sr.CRATES)
    assert len(TYPES["rules"]) == 77
    for code, row in TYPES["rules"].items():
        assert re.fullmatch(r"[A-Z]{2}\d{2}", code)
        assert set(row) == {"name", "file", "names", "modules"}
        assert re.fullmatch(r"[a-z_.]+", row["name"])
        assert module.match(row["file"])
        assert all(name.match(n) for n in row["names"])
        assert all(m in TYPES["modules"] for m in row["modules"])
    for mod, entry in TYPES["modules"].items():
        assert module.match(mod)
        assert set(entry) <= {"names", "layout_config"}
        assert all(name.match(n) for v in entry.values() for n in v)
    # sqlfluff 4.4.0 has one type with upper-case letters: drop_MODELstatement.
    assert all(re.match(r"^[A-Za-z][A-Za-z0-9_]*$", n) for n in TYPES["sqlfluff_types"])


def test_the_coupling_rows():
    sqlfluff = set(TYPES["sqlfluff_types"])
    rows = OUT["coupling"]["rules"]
    assert [r["code"] for r in rows] == sorted(TYPES["rules"])
    for r in rows:
        direct, names = sr.rule_names(TYPES, r["code"])
        assert r["names"] == names and r["direct"] == len(direct)
        assert set(direct) <= set(names)
        assert r["not_in_sqlfluff"] == [n for n in names if n not in sqlfluff]
        differ = set(r["not_in_sqlfluff"]) | set(r["renamed_in_t3"])
        assert r["differ"] == len(differ)
        assert r["differ_direct"] == len(differ & set(direct))
        assert set(r["renamed_in_t3"]) <= set(r["changed_in_t3"]) | set(names)
        assert 0 <= r["t3_cases"] <= 763
    summary = OUT["coupling"]["summary"]
    assert summary["rules"] == 77
    assert (
        summary["rules_that_see_a_changed_tree"]
        + len(summary["rules_that_see_no_changed_tree"])
        == 77
    )
    # Each T3 group key that renames a type shows in the renamed list.
    renamed = {
        n
        for row in T3["cases"]
        for k in row[3]
        if k.split(": ", 1)[0] in sr.T3_RENAME_CLASSES
        for n in sr.key_types(k)[1]
    }
    for r in rows:
        assert set(r["renamed_in_t3"]) == set(r["names"]) & renamed


def test_the_estimates_are_marked():
    assert OUT["touch"]["estimate"] is True
    parse = sum(
        1 for r in OUT["cases"] if r[3] == "parse_cause" and r[1] != "templater"
    )
    counts = [v for v in OUT["touch"].values() if type(v) is int]
    assert sum(counts) == parse
    assert "Estimates" in OUT["sensitivity"]["note"]
    assert OUT["coupling"]["estimates"]["fields"]
    assert "judgement" in OUT


def test_the_s3_status_file_and_the_decision_record_have_t4():
    status = (REPO_ROOT / "status" / "S3.md").read_text("utf8")
    row = next(r for r in status.splitlines() if r.startswith("| T4 |"))
    assert "PR #" in row
    flat = " ".join(status.split())
    for suite in sr.SUITES:
        c = OUT["counts"][suite]
        assert (
            f"| {suite} | {sr.FAILURES[suite]} | {c['unsupported_item']} | "
            f"{c['parse_cause']} | {c['rule_logic']} |"
        ) in status
    t = OUT["total"]
    assert (
        f"| all | 373 | {t['unsupported_item']} | {t['parse_cause']} | "
        f"{t['rule_logic']} |"
    ) in status
    sens = OUT["sensitivity"]["implicit_differs"]
    assert f"{sens['parse_cause']} parse_cause" in flat
    s = OUT["coupling"]["summary"]
    assert f"{s['rules_with_a_name_that_differs']} of 77 rules" in flat
    assert f"{s['rules_that_see_a_changed_tree']} of 77 rules" in flat
    touch = OUT["touch"]
    assert f"{touch['changes a type that the rule reads']} change a type" in flat
    record = (REPO_ROOT / "docs" / "decisions" / "s3-base.md").read_text("utf8")
    out = f"`{sr.OUT_FILE.relative_to(REPO_ROOT)}`"
    row = next(r for r in record.splitlines() if r.startswith("| C3 |") and out in r)
    assert "| T4 |" in row
