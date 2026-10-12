#!/usr/bin/env python3
"""Print the CI test matrix: one entry for each suite, tool, and shard.

ci/matrix.json is a list of {"suite", "tool", "shards"}. To add a suite or
a tool to CI, add an entry there. The report job gives the same file to
"sqll-harness merge --expect", so a missing shard report makes CI fail.

Usage: ci/matrix.py [MATRIX_JSON]
"""

import json
import sys
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent / "matrix.json"


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
    print(json.dumps(expand(json.loads(path.read_text())), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
