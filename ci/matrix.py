#!/usr/bin/env python3
"""Print the CI test matrix: one entry for each suite, tool, and shard.

ci/matrix.d/ has one fragment for each track: ci/matrix.d/<track>.json
(PROCESS.md, "Tracks"). Each fragment is a list of {"suite", "tool",
"shards"}. The matrix is all fragments, in the order of their file names.
To add a suite or a tool to CI, add an entry to the fragment of your track.
The report job gives the same folder to "sqll-harness merge --expect"
(merge.load_expected reads it the same way), so a missing shard report
makes CI fail.

Usage: ci/matrix.py [MATRIX_DIR_OR_JSON]
"""

import json
import sys
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent / "matrix.d"


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


def expand(entries: list[dict]) -> dict:
    include = []
    seen = set()
    for e in entries:
        suite, tool, shards = e["suite"], e["tool"], int(e["shards"])
        if shards < 1:
            raise ValueError(f"{suite}/{tool}: shards must be 1 or more")
        if (suite, tool) in seen:
            raise ValueError(f"{suite}/{tool}: two entries")
        seen.add((suite, tool))
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
    path = Path(argv[0]) if argv else DEFAULT
    print(json.dumps(expand(load(path)), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
