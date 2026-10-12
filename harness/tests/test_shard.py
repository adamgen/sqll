from collections import Counter

import pytest

from sqll_harness import shard
from sqll_harness.paths import SQLFLUFF_ROOT
from sqll_harness.suites import dialects


@pytest.mark.parametrize("text, expected", [("1/1", (1, 1)), ("3/4", (3, 4))])
def test_parse(text, expected):
    assert shard.parse(text) == expected


@pytest.mark.parametrize("text", ["", "1", "0/4", "5/4", "a/b", "1/0", "-1/2", "1/2/3"])
def test_parse_rejects_bad_text(text):
    with pytest.raises(ValueError):
        shard.parse(text)


def test_index_is_stable():
    # Fixed values: a change of the split moves cases between CI jobs.
    assert shard.index("dialects/ansi/select_simple_a", 4) == 4
    assert shard.index("dialects/ansi/select_simple_a", 6) == 6
    assert shard.index("x", 6) == 1


def test_each_case_is_in_exactly_one_shard():
    ids = [c.id for c in dialects.discover(SQLFLUFF_ROOT)]
    n = 6
    for case_id in ids:
        hits = [k for k in range(1, n + 1) if shard.contains((k, n), case_id)]
        assert hits == [shard.index(case_id, n)]
    counts = Counter(shard.index(i, n) for i in ids)
    assert sum(counts.values()) == len(ids) == 2306
    # The split is by hash, so the sizes are near, not equal.
    assert max(counts.values()) < 1.2 * len(ids) / n
    assert min(counts.values()) > 0.8 * len(ids) / n


def test_no_shard_contains_all():
    assert shard.contains(None, "anything")
