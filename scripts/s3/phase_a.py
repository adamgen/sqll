"""The frozen inputs of the S3 phase A scripts (results/s3/phase-a/).

S3 phase B records new S1 and S2 results for sqll in
results/s1/summary.json and results/s2/baseline.json. The phase A records
(T2 to T9) cite the sha256 of these files as phase A read them. Thus the
phase A scripts read byte copies of those files, and the records keep the
old names. harness/tests/test_s3_phase_a.py checks that each copy has the
sha256 that the records cite.

The phase A records also quote STONES.md and CONSTITUTION.md. Later stones
change these documents, so the quotes are checked against copies of them as
they were at the S3 decision (commit cba2020, PR #42): DOCUMENTS.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FROZEN = {
    "results/s1/summary.json": "results/s3/phase-a/s1-summary.json",
    "results/s2/baseline.json": "results/s3/phase-a/s2-baseline.json",
}
DOCUMENTS = {
    "STONES.md": "results/s3/phase-a/STONES.md",
    "CONSTITUTION.md": "results/s3/phase-a/CONSTITUTION.md",
}
_NAMES = {v: k for k, v in FROZEN.items()}


def read_path(name: str) -> Path:
    """The file to read for a name that a phase A record cites."""
    return ROOT / FROZEN.get(name, name)


def name_of(rel: str) -> str:
    """The name that a phase A record cites for a path from the root."""
    return _NAMES.get(rel, rel)


def document_path(name: str) -> Path:
    """The file to read for a document that a phase A record quotes."""
    return ROOT / DOCUMENTS.get(name, name)
