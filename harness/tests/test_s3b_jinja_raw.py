"""Tests of scripts/s3b/jinja_raw_oracle.py (S3b task C14): the jinja as raw
record that the sqll adapter reads. The CI job build runs "check", which
makes the data again with the pinned sqlfluff."""

import hashlib
import importlib.util
import json
import sys

from sqll_harness.adapters import sqll as sqll_adapter
from sqll_harness.paths import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "s3b" / "jinja_raw_oracle.py"


def load():
    spec = importlib.util.spec_from_file_location("jinja_raw_oracle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["jinja_raw_oracle"] = module
    spec.loader.exec_module(module)
    return module


jr = load()
RECORD = json.loads(jr.RECORD_FILE.read_text("utf8"))


def test_the_record_is_the_one_that_the_adapter_reads():
    assert jr.RECORD_FILE == sqll_adapter.JINJA_RAW_RECORD
    assert RECORD["kind"] == jr.KIND == sqll_adapter.JINJA_RAW_KIND
    assert RECORD["format"] == jr.FORMAT
    assert RECORD["sqlfluff"]["version"] == "4.4.0"
    assert jr.dumps(RECORD) == jr.RECORD_FILE.read_text("utf8")
    texts = sqll_adapter.jinja_raw_texts(jr.RECORD_FILE)
    assert texts == frozenset(RECORD["equal"])
    assert RECORD["equal"] == sorted(set(RECORD["equal"]))


def test_the_record_has_the_texts_of_the_inputs_with_no_jinja_delimiter():
    # sqlfluff gives the raw file for each input with no Jinja delimiter
    # and for no input with one. The harness makes the same inputs.
    items = jr.inputs()
    plain = {
        hashlib.sha256(i["text"].encode("utf8")).hexdigest()
        for i in items
        if not any(d in i["text"] for d in jr.JINJA_DELIMITERS)
    }
    assert set(RECORD["equal"]) == plain
    assert RECORD["notes"] == []
    assert RECORD["counts"] == {
        "inputs": len(items),
        "rule_inputs": sum(i["suite"] == "rules" for i in items),
        "autofix_inputs": 61,
        "inputs_with_delimiters": 244,
        "equal_inputs": 3178,
        "equal_texts": len(plain),
        "not_equal_texts": RECORD["counts"]["not_equal_texts"],
    }
    assert RECORD["counts"]["inputs"] == 3422
    # Each input is a jinja input: the rule cases with another templater
    # are not in it.
    assert all(
        jr.templater_of(i.get("configs")) == "jinja"
        for i in items
        if i["suite"] == "rules"
    )


def test_the_summary_drops_a_text_that_is_not_equal_for_one_input():
    items = [
        {"suite": "rules", "id": "a", "text": "select 1\n"},
        {"suite": "rules", "id": "b", "text": "select 1\n"},
        {"suite": "rules", "id": "c", "text": "select 2\n"},
        {"suite": "rules", "id": "d", "text": "select {{ x }}\n"},
    ]
    results = [
        {"id": "a", "reason": None},
        {"id": "b", "reason": "another sliced file"},
        {"id": "c", "reason": None},
        {"id": "d", "reason": "another templated text"},
    ]
    summary = jr.summarize(items, results)
    assert summary["equal"] == [jr.sha256("select 2\n")]
    assert summary["counts"]["equal_inputs"] == 1
    assert summary["counts"]["not_equal_texts"] == 2
    assert summary["counts"]["inputs_with_delimiters"] == 1
    # The notes show a result that the delimiters do not explain.
    assert jr.problems_of(items, results) == [
        "b: no Jinja delimiter, but another sliced file"
    ]
