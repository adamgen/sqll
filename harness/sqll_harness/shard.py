"""Split the cases of a run into N shards.

The shard of a case depends only on its id. Thus a case stays in the same
shard when other cases are added or removed, and the shard of a listed
known-failure id is known also when the case does not exist.
"""

import hashlib

Shard = tuple[int, int]


def parse(text: str) -> Shard:
    """Parse "K/N" (1 <= K <= N) and return (K, N)."""
    k_text, sep, n_text = text.partition("/")
    try:
        if not sep:
            raise ValueError
        k, n = int(k_text), int(n_text)
    except ValueError:
        raise ValueError(f"shard must be K/N, for example 1/4: {text!r}") from None
    if not 1 <= k <= n:
        raise ValueError(f"shard K/N must have 1 <= K <= N: {text!r}")
    return k, n


def index(case_id: str, count: int) -> int:
    """Return the shard (1 to count) of a case id."""
    digest = hashlib.sha256(case_id.encode("utf8")).digest()
    return int.from_bytes(digest[:8], "big") % count + 1


def contains(shard: Shard | None, case_id: str) -> bool:
    """Return True if the case is in the shard. No shard contains all cases."""
    if shard is None:
        return True
    k, n = shard
    return index(case_id, n) == k
