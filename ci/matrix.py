#!/usr/bin/env python3
"""Print the CI test matrix: one entry for each suite, tool, and shard.

ci/matrix.d/ has one fragment for each track: ci/matrix.d/<track>.json
(PROCESS.md, "Tracks"). Each fragment is a list of {"suite", "tool",
"shards"}. The matrix is all fragments, in the order of their file names.
To add a suite or a tool to CI, add an entry to the fragment of your track.
The report job gives the same folder to "sqll-harness merge --expect"
(merge.load_expected reads it the same way), so a missing shard report
makes CI fail.

The entries of the S7 suites (S7_SUITES) are not in the matrix of the test
jobs: with --s7, the output is only these entries, for the s7 jobs ("sqll-
harness s7 run"). The s7-report job gives the folder to "sqll-harness s7
merge --expect". The S7 runner has no shards, so an S7 entry must have 1
shard.

Usage: ci/matrix.py [--s7] [MATRIX_DIR_OR_JSON]
"""

import json
import sys
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent / "matrix.d"
# The S7 suites (harness/sqll_harness/s7_tests/suites.py; a unit test
# compares them). This script runs before the harness is installed, so it
# does not import it.
S7_SUITES = ("s7_rules", "s7_config", "s7_cli")


def load(path: Path) -> list[dict]:
    """Return the entries of a fragment, or of all fragments of a folder."""
    if not path.is_dir():
        entries = json.loads(path.read_text(encoding="utf8"))
        if not isinstance(entries, list):
            raise ValueError(f"{path}: not a list")
        return entries
    files = sorted(path.glob("*.json"))
    if not files:
        raise ValueError(f"{path}: no *.json fragment")
    return [e for f in files for e in load(f)]


def expand(entries: list[dict], s7: bool = False) -> dict:
    """The matrix of the S1 entries, or with s7 of the S7 entries. Each entry
    is checked."""
    include = []
    seen = set()
    for e in entries:
        suite, tool, shards = e["suite"], e["tool"], int(e["shards"])
        if shards < 1:
            raise ValueError(f"{suite}/{tool}: shards must be 1 or more")
        if suite in S7_SUITES and shards != 1:
            raise ValueError(f"{suite}/{tool}: an S7 suite must have 1 shard")
        if (suite, tool) in seen:
            raise ValueError(f"{suite}/{tool}: two entries")
        seen.add((suite, tool))
        if (suite in S7_SUITES) != s7:
            continue
        for k in range(1, shards + 1):
            include.append(
                {
                    "suite": suite,
                    "tool": tool,
                    "shard": f"{k}/{shards}",
                    "name": f"{suite}-{tool}-{k}-of-{shards}",
                }
            )
    return {"include": include}


def main(argv: list[str]) -> int:
    # --s7 can be before or after the path. Another option, a second --s7,
    # or more than 1 path is an error (exit code 2): a wrong command must not
    # print a matrix.
    s7 = "--s7" in argv
    rest = [a for a in argv if a != "--s7"]
    if argv.count("--s7") > 1 or len(rest) > 1 or any(a.startswith("-") for a in rest):
        print("usage: ci/matrix.py [--s7] [MATRIX_DIR_OR_JSON]", file=sys.stderr)
        return 2
    path = Path(rest[0]) if rest else DEFAULT
    print(json.dumps(expand(load(path), s7), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
