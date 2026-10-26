"""S3 T3: the classes of the sqruff parse tree mismatches.

results/s3/sqruff-tree-diffs.json is the output of scripts/s3/sqruff_trees.py
on the committed inputs, the hunks file is the output of a new sqruff run,
and the data agree with the T2 files and known_failures/sqruff.txt."""

import copy
import importlib.util
import itertools
import json
from collections import Counter

import pytest
from conftest import needs

from sqll_harness import known_failures
from sqll_harness.paths import KNOWN_FAILURES_DIR, REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "sqruff_trees", REPO_ROOT / "scripts" / "s3" / "sqruff_trees.py"
)
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)

HUNKS = json.loads(st.HUNKS_FILE.read_text("utf8"))
HAND = json.loads(st.HANDCHECK_FILE.read_text("utf8"))
OUT = json.loads(st.OUT_FILE.read_text("utf8"))
CASES = json.loads(st.CASES_FILE.read_text("utf8"))
KNOWN = known_failures.load(KNOWN_FAILURES_DIR, "sqruff")


def N(name, *children):
    return (name, tuple(children))


def L(name, raw):
    return (name, raw)


def classes(expected, actual):
    return sorted({h[0] for h in st.diff(expected, actual)["hunks"]})


def keys(expected, actual, dialect="-"):
    return sorted({h[1] for h in st.diff(expected, actual, dialect)["hunks"]})


# The classifier on small trees.


def test_renamed():
    e = N("file", N("statement", N("x", L("keyword", "a"), L("keyword", "b"))))
    a = N("file", N("statement", N("y", L("keyword", "a"), L("keyword", "b"))))
    assert keys(e, a) == ["renamed: x -> y"]
    assert st.diff(e, a)["first_path"] == "file/statement/x"


def test_missing_and_extra_wrapper():
    e = N("file", N("s", N("w", L("keyword", "a"), L("keyword", "b")), L("k", "c")))
    a = N("file", N("s", L("keyword", "a"), L("keyword", "b"), L("k", "c")))
    assert keys(e, a) == ["missing_wrapper: w in s"]
    assert keys(a, e) == ["extra_wrapper: w in s"]


def test_a_wrapper_with_the_same_span_pairs_from_the_outer_end():
    e = N("file", N("schema_reference", L("naked_identifier", "s")))
    a = N(
        "file",
        N("table_reference", N("object_reference", L("naked_identifier", "s"))),
    )
    assert keys(e, a) == [
        "extra_wrapper: object_reference in table_reference",
        "renamed: schema_reference -> table_reference",
    ]


def test_nesting():
    e = N("file", N("s", N("x", L("k", "a"), L("k", "b")), L("k", "c")))
    a = N("file", N("s", L("k", "a"), N("y", L("k", "b"), L("k", "c"))))
    assert keys(e, a) == ["nesting: sqlfluff x in s", "nesting: sqruff y in s"]


def test_leaf_types():
    e = N("file", L("keyword", "a"), L("comma", ","))
    a = N("file", L("naked_identifier", "a"), L("symbol", ","))
    assert keys(e, a) == [
        "keyword_vs_identifier: keyword -> naked_identifier in file",
        "leaf_type: comma -> symbol in file",
    ]


def test_token_split():
    e = N("file", L("numeric_literal", "1.5"))
    a = N(
        "file",
        L("numeric_literal", "1"),
        L("dot", "."),
        L("numeric_literal", "5"),
    )
    assert keys(e, a) == [
        "token_split: numeric_literal -> numeric_literal dot numeric_literal"
    ]


def test_leaf_text():
    e = N("file", N("s", L("keyword", "a")), L("terminator", "/"))
    a = N("file", N("s", L("keyword", "a")), L("terminator", "/\n"))
    assert keys(e, a) == ["leaf_text: terminator -> terminator"]


def test_meta():
    e = N("file", L("keyword", "a"), L("indent", ""), L("keyword", "b"))
    a = N("file", L("keyword", "a"), L("implicit", ""), L("keyword", "b"))
    assert keys(e, a) == ["meta: indent -> implicit"]


def test_a_sqruff_leaf_with_text_that_the_fixture_does_not_have_is_not_meta():
    e = N("file", L("keyword", "a"))
    a = N("file", L("keyword", "a"), L("newline", "\n"))
    assert classes(e, a) == ["leaf_text"]


def test_non_code_placement():
    e = N("file", N("s", N("x", L("keyword", "a")), L("whitespace", " ")))
    a = N("file", N("s", N("x", L("keyword", "a"), L("whitespace", " "))))
    assert keys(e, a) == ["non_code_placement: x"]


def test_unparsable_absorbs_its_statement_and_keeps_other_hunks():
    stmt = N("statement", N("select_statement", L("keyword", "SELECT")))
    e = N(
        "file",
        N("batch", stmt, N("statement", N("x", L("keyword", "a"), L("keyword", "b")))),
    )
    # sqruff ends its batch in the second statement; the rest is unparsable.
    a = N(
        "file",
        N("oracle_batch", stmt, N("statement", N("y", L("keyword", "a")))),
        N("unparsable", L("word", "b")),
    )
    assert keys(e, a, "oracle") == [
        "renamed: batch -> oracle_batch",
        "unparsable: oracle: x in x",
    ]


def test_the_unparsable_key_has_the_dialect_and_the_failing_segment():
    def tree(*select):
        return N("file", N("statement", N("select_statement", *select)))

    clause = N("select_clause", L("keyword", "SELECT"), L("raw", "x"))
    e1 = tree(clause, N("where_clause", L("keyword", "WHERE"), L("raw", "y")))
    a1 = tree(clause, N("unparsable", L("word", "WHERE"), L("word", "y")))
    e2 = tree(clause, N("pivot_clause", L("keyword", "PIVOT"), L("raw", "y")))
    a2 = tree(clause, N("unparsable", L("word", "PIVOT"), L("word", "y")))
    got = {
        tuple(k for k in keys(e, a, d) if k.startswith("unparsable"))
        for e, a, d in ((e1, a1, "hive"), (e2, a2, "hive"), (e1, a1, "mysql"))
    }
    assert got == {
        ("unparsable: hive: where_clause in select_statement",),
        ("unparsable: hive: pivot_clause in select_statement",),
        ("unparsable: mysql: where_clause in select_statement",),
    }


def test_an_unparsable_node_with_no_code_leaf_has_the_segment_dash():
    def select(*middle):
        return N("select_statement", L("keyword", "SELECT"), *middle, L("raw", "x"))

    comment = L("comment", "/* c */")
    e = N("file", N("statement", select(comment)))
    a = N("file", N("statement", select(N("unparsable", comment))))
    assert keys(e, a, "ansi") == ["unparsable: ansi: - in select_statement"]
    # With no code node that holds it: the root.
    e = N("file", N("statement", select()), comment)
    a = N("file", N("statement", select()), N("unparsable", comment))
    assert keys(e, a, "ansi") == ["unparsable: ansi: - in file"]


def test_leaf_changes_show_moved_removed_and_added_leaves():
    e = N("file", N("s", N("x", L("keyword", "a")), L("keyword", "b")))
    a = N("file", N("s", L("keyword", "a"), L("word", "c")))
    assert st.leaf_changes(e, a) == [
        ("~ s: x -> ()", 1),
        ("- file/s | keyword 'b'", 1),
        ("+ file/s | word 'c'", 1),
    ]


def test_equal_trees_give_other():
    t = N("file", L("keyword", "a"))
    assert classes(t, t) == ["other"]


# Drift.


def test_the_committed_output_is_the_build_of_the_committed_inputs():
    assert st.text(st.build()) == st.OUT_FILE.read_text("utf8")
    assert st.main(["build", "--check"]) == 0


def test_the_check_fails_on_a_change(tmp_path):
    changed = copy.deepcopy(OUT)
    changed["groups"]["top"]["10"]["cases"] += 1
    out = tmp_path / "out.json"
    out.write_text(st.text(changed), "utf8")
    assert st.main(["build", "--check", "--out", str(out)]) == 1
    assert st.main(["build", "--check", "--out", str(tmp_path / "none")]) == 1


@needs("sqruff/bin/sqruff", "sqruff/python/bin/python3")
def test_a_new_sqruff_run_gives_the_committed_hunks():
    assert st.text(st.collect()) == st.HUNKS_FILE.read_text("utf8")


# Fail-closed checks against the T2 data and the known failures.


def _write(tmp_path, name, record):
    path = tmp_path / name
    path.write_text(st.text(record), "utf8")
    return path


def test_a_missing_case_fails(tmp_path):
    hunks = copy.deepcopy(HUNKS)
    hunks["cases"].pop("dialects/ansi/alter_sequence")
    with pytest.raises(st.DataError, match="known_failures/sqruff.txt"):
        st.build(_write(tmp_path, "h.json", hunks))


def test_an_unparsable_class_that_t2_does_not_give_fails(tmp_path):
    hunks = copy.deepcopy(HUNKS)
    row = next(
        r
        for r in hunks["cases"].values()
        if any(h[0] == "unparsable" for h in r["hunks"])
    )
    row["hunks"] = [h for h in row["hunks"] if h[0] != "unparsable"] or [
        ["renamed", "renamed: a -> b", "file", 1, 0]
    ]
    with pytest.raises(st.DataError, match="no_unparsable"):
        st.build(_write(tmp_path, "h.json", hunks))


def test_a_dialect_failure_with_another_reason_fails(tmp_path, monkeypatch):
    text = (st.KNOWN_FAILURES / "sqruff.txt").read_text("utf8")
    line = "dialects/ansi/alter_sequence  # tree differs"
    assert line in text
    (tmp_path / "sqruff.txt").write_text(
        text.replace(line, "dialects/ansi/alter_sequence  # parse error"), "utf8"
    )
    monkeypatch.setattr(st, "KNOWN_FAILURES", tmp_path)
    with pytest.raises(st.DataError, match="alter_sequence: reason 'parse error'"):
        st.build()


def test_another_dialect_count_than_t2_fails(tmp_path, monkeypatch):
    by_base = json.loads(st.S1_BY_BASE.read_text("utf8"))
    by_base["bases"]["sqruff"]["dialects"]["ansi"]["fail"] += 1
    monkeypatch.setattr(st, "S1_BY_BASE", _write(tmp_path, "b.json", by_base))
    with pytest.raises(st.DataError, match="ansi"):
        st.build()


def test_a_hand_check_that_is_not_the_sample_fails(tmp_path):
    hand = copy.deepcopy(HAND)
    hand["cases"] = hand["cases"][1:]
    with pytest.raises(st.DataError, match="not the sample"):
        st.build(st.HUNKS_FILE, _write(tmp_path, "hc.json", hand))
    hand = copy.deepcopy(HAND)
    hand["cases"][0]["classes"] = ["no_such_class"]
    with pytest.raises(st.DataError, match="unknown hand class"):
        st.build(st.HUNKS_FILE, _write(tmp_path, "hc.json", hand))


# The results.


def test_each_case_has_a_class_and_other_is_reported():
    rows = OUT["cases"]
    assert len(rows) == 763 == OUT["scope"]["cases"]
    assert Counter(r[0].split("/")[0] for r in rows) == {
        "dialects": 758,
        "templater": 5,
    }
    assert all(r[2] and set(r[2]) <= set(st.CLASSES) for r in rows)
    assert set(OUT["classes"]) == set(st.CLASSES)
    assert OUT["classes"]["other"]["cases"] == sum("other" in r[2] for r in rows)
    for name, row in OUT["classes"].items():
        assert row["cases"] == sum(name in r[2] for r in rows)
    assert sum(row["primary"] for row in OUT["classes"].values()) == 763
    failed = {i for i, r in KNOWN.items() if i.startswith("dialects/")}
    failed |= {i for i, r in KNOWN.items() if r == "tree differs"}
    assert {r[0] for r in rows} == failed


def test_the_top_group_shares_are_measured():
    rows = OUT["cases"]
    groups = Counter(k for r in rows for k in r[3])
    ranked = sorted(groups, key=lambda k: (-groups[k], k))
    assert OUT["groups"]["groups"] == len(groups)
    for n in st.TOP:
        top = set(ranked[:n])
        covered = sum(1 for r in rows if set(r[3]) <= top)
        assert OUT["groups"]["top"][str(n)]["cases"] == covered
        assert OUT["groups"]["top"][str(n)]["share"] == round(covered / 763, 4)
    singles = {k for k, v in groups.items() if v == 1}
    assert OUT["groups"]["cases_with_a_unique_fix"] == sum(
        1 for r in rows if set(r[3]) & singles
    )
    # The tie range: each order of the groups with equal counts.
    for n in st.TOP:
        size = groups[ranked[n - 1]]
        above = {k for k in groups if groups[k] > size}
        tied = sorted(k for k in groups if groups[k] == size)
        values = {
            sum(1 for r in rows if set(r[3]) <= above | set(pick))
            for pick in itertools.combinations(tied, n - len(above))
        }
        got = OUT["groups"]["top"][str(n)]
        assert got["tie_range"] == [min(values), max(values)]
        assert min(values) <= got["cases"] <= max(values)
    assert [g[:2] for g in OUT["groups"]["top_50"]] == [
        [k, groups[k]] for k in ranked[:50]
    ]


def test_the_unparsable_key_sensitivity_is_measured():
    rows = OUT["cases"]
    variants = {
        "used": lambda k, r: k,
        "dialect_and_statement": lambda k, r: (
            f"unparsable: {r[1]}: in {k.rsplit(' in ', 1)[1]}"
        ),
        "statement": lambda k, r: f"unparsable: in {k.rsplit(' in ', 1)[1]}",
        "case": lambda k, r: f"unparsable: {r[0]}",
    }
    sens = OUT["groups"]["unparsable_key_sensitivity"]
    assert set(sens) == set(variants)
    for name, fn in variants.items():
        case_keys = [
            {fn(k, r) if k.startswith("unparsable: ") else k for k in r[3]}
            for r in rows
        ]
        groups = Counter(k for ks in case_keys for k in ks)
        ranked = sorted(groups, key=lambda k: (-groups[k], k))
        for n in st.TOP:
            top = set(ranked[:n])
            assert sens[name]["top"][str(n)] == sum(1 for ks in case_keys if ks <= top)
        singles = {k for k, v in groups.items() if v == 1}
        assert sens[name]["groups"] == len(groups)
        assert sens[name]["cases_with_a_unique_fix"] == sum(
            1 for ks in case_keys if ks & singles
        )
    assert sens["used"]["top"] == {
        n: v["cases"] for n, v in OUT["groups"]["top"].items()
    }
    # Each unparsable key names one dialect.
    for r in rows:
        for k in r[3]:
            if k.startswith("unparsable: "):
                assert k.startswith(f"unparsable: {r[1]}: ")


def test_the_hand_check_is_recorded():
    hc = OUT["hand_check"]
    assert hc["size"] == len(hc["cases"]) >= 60
    assert hc["method"]
    rows = st.case_rows(HUNKS)
    assert hc["rule"] == st.select_sample(rows)[1]
    assert [c["id"] for c in hc["cases"]] == st.select_sample(rows)[0]
    assert hc["agree"] == sum(c["agree"] for c in hc["cases"])
    assert hc["rate"] == round(hc["agree"] / hc["size"], 4)
    dialects = {r[1] for r in OUT["cases"]}
    assert {c["dialect"] for c in hc["cases"]} == dialects
    for c in hc["cases"]:
        assert c["agree"] == (c["auto"] == c["hand"])
        assert c["note"]


def test_the_cases_without_no_unparsable_are_those_of_t2():
    want = {
        r[0] for r in CASES["cases"] if r[0].startswith("dialects/") and r[2][1] != 1
    }
    got = OUT["no_unparsable"]["cases"]
    assert {r[0] for r in got} == want
    assert len(got) == OUT["no_unparsable"]["count"] == 142
    assert all(r[3] for r in got)


def test_the_s3_status_file_and_the_decision_record_have_t3():
    status = (REPO_ROOT / "status" / "S3.md").read_text("utf8")
    row = next(r for r in status.splitlines() if r.startswith("| T3 |"))
    assert "PR #" in row
    flat = " ".join(status.split())
    top = OUT["groups"]["top"]
    for n in st.TOP:
        assert f"top {n} groups: {top[str(n)]['cases']}" in flat
        low, high = top[str(n)]["tie_range"]
        assert (
            f"top {n}: {low} to {high}" if low < high else f"top {n}: {low}"
        ) in flat
    assert f"{OUT['groups']['groups']} groups" in flat
    unique = OUT["groups"]["cases_with_a_unique_fix"]
    assert f"{unique} cases need a fix that no other case needs" in flat
    per_case = OUT["groups"]["unparsable_key_sensitivity"]["case"]
    assert f"{per_case['cases_with_a_unique_fix']} cases need a fix of their" in flat
    hc = OUT["hand_check"]
    assert f"{hc['agree']} of {hc['size']}" in flat
    for name in ("unparsable", "extra_wrapper", "renamed", "other"):
        assert f"| {name} | {OUT['classes'][name]['cases']} |" in status
    record = (REPO_ROOT / "docs" / "decisions" / "s3-base.md").read_text("utf8")
    out = f"`{st.OUT_FILE.relative_to(REPO_ROOT)}`"
    row = next(r for r in record.splitlines() if r.startswith("| C2 |") and out in r)
    assert "| T3 |" in row
