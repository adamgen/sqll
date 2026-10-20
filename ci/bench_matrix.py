#!/usr/bin/env python3
"""Print the CI matrix of the full benchmark: one entry for each shard.

ci/bench-matrix.json is {"shards": N}. The bench-full job runs shard K/N of
"sqll-harness bench run" for each entry (the dialects go to the shards in
turn). The bench-merge job gives the same file to "sqll-harness bench merge
--expect", so a missing shard report makes CI fail.

Usage: ci/bench_matrix.py [BENCH_MATRIX_JSON]
"""

import json
import sys
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent / "bench-matrix.json"


def expand(data: dict) -> dict:
    if not isinstance(data, dict) or set(data) != {"shards"}:
        raise ValueError('the file must be {"shards": N}')
    n = data["shards"]
    if type(n) is not int or n < 1:
        raise ValueError("shards must be an integer, 1 or more")
    return {
        "include": [
            {"shard": f"{k}/{n}", "name": f"{k}-of-{n}"} for k in range(1, n + 1)
        ]
    }


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else DEFAULT
    print(json.dumps(expand(json.loads(path.read_text())), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
