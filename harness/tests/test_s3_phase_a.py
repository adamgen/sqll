"""S3: the frozen inputs of the phase A scripts (scripts/s3/phase_a.py).

Phase B records new results in results/s1/summary.json and
results/s2/baseline.json. The phase A records cite the sha256 of these
files as phase A read them. Each frozen copy in results/s3/phase-a/ must
have that sha256, and the scripts must read the copies.
"""

import hashlib
import importlib.util
import json

from sqll_harness.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "phase_a", REPO_ROOT / "scripts" / "s3" / "phase_a.py"
)
phase_a = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(phase_a)

# The phase A records and the frozen names that each cites in "inputs".
RECORDS = {
    "s1-by-base.json": ["results/s1/summary.json"],
    "decision-data.json": ["results/s1/summary.json"],
    "sqlfluffrs-probe.json": ["results/s2/baseline.json"],
    "speed-by-base.json": ["results/s2/baseline.json"],
    "capabilities.json": ["results/s2/baseline.json"],
}


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_each_frozen_copy_has_the_sha256_that_the_records_cite():
    cited = set()
    for name, frozen in RECORDS.items():
        inputs = json.loads((REPO_ROOT / "results" / "s3" / name).read_text("utf8"))[
            "inputs"
        ]
        for rel in frozen:
            assert inputs[rel] == sha256(phase_a.read_path(rel)), (name, rel)
            cited.add(rel)
    assert cited == set(phase_a.FROZEN)


def test_the_copies_are_in_results_s3_phase_a():
    for rel, copy in phase_a.FROZEN.items():
        assert copy.startswith("results/s3/phase-a/")
        assert phase_a.read_path(rel) == REPO_ROOT / copy
        assert phase_a.name_of(copy) == rel
        assert (REPO_ROOT / copy).is_file()
    assert phase_a.read_path("results/s3/x.json") == REPO_ROOT / "results/s3/x.json"
    assert phase_a.name_of("results/s3/x.json") == "results/s3/x.json"


def test_no_record_cites_another_s1_or_s2_input():
    for path in (REPO_ROOT / "results" / "s3").glob("*.json"):
        inputs = json.loads(path.read_text("utf8")).get("inputs")
        if not isinstance(inputs, dict):
            continue
        for rel in inputs:
            if rel.startswith(("results/s1/", "results/s2/")):
                assert rel in RECORDS.get(path.name, []), (path.name, rel)
