#!/usr/bin/env python3
"""Print the CI matrix of the full corpus run: one entry for each shard.

corpus/ci-shards.json is {"shards": N}; the S9 track owns it. The
corpus-full job runs shard K/N of "python -m sqll_harness.corpus run
--profile full" for each entry (file i of the manifest is in shard
i % N + 1). The corpus-merge job gives the same file to "merge --expect",
so a missing shard report makes CI fail.

Usage: ci/corpus_matrix.py [SHARDS_JSON]
"""

import json
import sys
from pathlib import Path

from bench_matrix import expand

DEFAULT = Path(__file__).resolve().parents[1] / "corpus" / "ci-shards.json"


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else DEFAULT
    print(json.dumps(expand(json.loads(path.read_text())), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
