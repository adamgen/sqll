"""S3 T17: the record of the terminator hint check (scripts/s3/hint_check.py)
and the documents that cite it."""

import hashlib
import json
import subprocess

from sqll_harness.paths import REPO_ROOT

PATCH = REPO_ROOT / "scripts" / "s3" / "hint-check.patch"
RECORD = json.loads(
    (REPO_ROOT / "results" / "s3" / "speed" / "T17-hint-check.json").read_text("utf8")
)
PORTED = json.loads((REPO_ROOT / "crates" / "ported.json").read_text("utf8"))
MATCH = "crates/sqll_parser/src/parser/table_driven/match_algorithms.rs"


def words(text: str) -> str:
    return " ".join(text.split())


def test_the_record_is_of_the_committed_patch():
    assert RECORD["kind"] == "sqll-s3-hint-check"
    assert RECORD["patch_sha256"] == hashlib.sha256(PATCH.read_bytes()).hexdigest()


def test_the_patch_applies_to_the_tree():
    # The check stays runnable: a change of the patched lines needs a new patch.
    subprocess.run(["git", "apply", "--check", str(PATCH)], cwd=REPO_ROOT, check=True)


def test_no_excluded_probe_matches_or_reaches_a_limit():
    s = RECORD["summary"]
    assert (s["inputs"], s["fixtures"], s["parse_inputs"]) == (2390, 2306, 84)
    assert s["exclusions"] > 0
    assert s["probe_matches"] == s["probe_limits"] == s["different_runs"] == 0
    assert RECORD["matches"] == RECORD["limits"] == RECORD["different"] == []


def test_the_ported_record_gives_the_check_and_the_limit_effect():
    (entry,) = [f for f in PORTED["files"] if f["path"] == MATCH]
    text = entry["changed"]
    assert "The parse does not change" not in text
    assert "results/s3/speed/T17-hint-check.json" in text
    assert f"{RECORD['summary']['exclusions']} exclusions" in text
    assert "A probe that is not run cannot reach a parser limit" in text
    assert "sqll can give a tree where the source stops the parse" in text


def test_the_documents_give_the_check():
    sqll_md = words((REPO_ROOT / "harness" / "sqll.md").read_text("utf8"))
    assert "sqll does not run a terminator probe where the simple hint" in sqll_md
    assert "`results/s3/speed/T17-hint-check.json`" in sqll_md
    data = words((REPO_ROOT / "results" / "s3" / "data.md").read_text("utf8"))
    assert f"{RECORD['summary']['exclusions']} exclusions, no probe match" in data
