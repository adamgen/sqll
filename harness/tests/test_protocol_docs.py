"""The protocol documents: the standing delegation of the human owner
(CONSTITUTION.md, section 5) and the length of each canonical document."""

import re

import pytest

from sqll_harness.paths import REPO_ROOT

DELEGATION = (
    "Standing delegation (human owner, 2026-11-06): the orchestrator acts for"
    " the human owner for the approval of each stone and for each decision that"
    " STONES.md or a stop rule gives to a human. It approves a stone only after"
    " an independent check finds no blocking gap, and it records each approval"
    " and decision with its data and date. It does not weaken a goal (G1 to G4)"
    " or an exit rule. Account and billing settings, legal advice, the"
    " publication of a release or a package, and a change of the pinned sqlfluff"
    " version still need the human owner. The human owner can stop or reverse"
    " the delegation at any time."
)
REFERENCE = "standing delegation (CONSTITUTION.md, section 5)"
CANONICAL = ("AGENTS.md", "CONSTITUTION.md", "STONES.md", "PROCESS.md", "STATUS.md")


def read(name: str) -> str:
    return (REPO_ROOT / name).read_text("utf8")


def words(text: str) -> str:
    return " ".join(text.split())


def rules(text: str) -> dict[int, str]:
    part = text.split("\n## Rules\n", 1)[1].split("\n## ", 1)[0]
    found = re.findall(r"(?ms)^(\d+)\. (.*?)(?=^\d+\. |\Z)", part)
    return {int(n): words(body) for n, body in found}


def test_the_constitution_has_the_delegation_after_the_change_rule():
    text = read("CONSTITUTION.md")
    sections = re.findall(r"(?m)^## (.*)$", text)
    assert sections[-2:] == ["4. Changes to this document", "5. Standing delegation"]
    change, delegation = text.split("\n## 4. Changes to this document\n", 1)[1].split(
        "\n## 5. Standing delegation\n", 1
    )
    assert "Only a human owner can approve it." in change
    assert words(delegation) == DELEGATION


def test_the_process_refers_to_the_delegation():
    found = rules(read("PROCESS.md"))
    # Rule 4: who approves, and what stays with the human owner.
    assert REFERENCE in found[4]
    assert (
        "The approval of a stone and of a decision that STONES.md or a stop rule"
        " gives to a human (for example the S3 base) comes from the human owner,"
        " or from the orchestrator by the" in found[4]
    )
    for item in (
        "a change to CONSTITUTION.md",
        "a change of the pinned sqlfluff version",
        "an item that the standing delegation keeps for the human owner",
        "a blocker that only a human can remove",
        "Do not continue past such a decision before it is approved.",
    ):
        assert item in found[4], item
    # Rule 6: the approval of a completed stone.
    assert found[6].startswith(
        f"The human owner, or the orchestrator by the {REFERENCE}, approves each"
        " completed stone."
    )
    assert "A human approves" not in read("PROCESS.md")


def test_the_status_index_names_the_delegation():
    assert (
        "the orchestrator approves the stones and the human decisions by the"
        " standing delegation of the human owner (CONSTITUTION.md, section 5)"
        in words(read("STATUS.md"))
    )


@pytest.mark.parametrize("name", CANONICAL)
def test_each_canonical_document_is_a_5_minute_read(name):
    # CONSTITUTION.md 2.4.
    assert len(read(name).split()) <= 1250, name


def names_table() -> dict[str, str]:
    part = read("AGENTS.md").split("\n## Names: write the goal with each name\n", 1)[1]
    rows = re.findall(r"(?m)^\| (.+?) \| (.+?) \|$", part)
    return {name: goal for name, goal in rows if name not in ("Name", "---")}


def test_the_names_table_has_each_stone_goal_and_track():
    table = names_table()
    stones = dict(re.findall(r"(?m)^## (S\d+b?)\. (.+)$", read("STONES.md")))
    goals = dict(re.findall(r"(?m)^### (G\d)\. (.+)$", read("CONSTITUTION.md")))
    assert len(stones) == 12 and len(goals) == 4
    for name, title in {**stones, **goals}.items():
        assert table[name].startswith(title), name
    tracks = re.findall(r"(?m)^  ([A-Za-z0-9-]+):$", read("tracks.yml"))
    for track in tracks:
        assert track in stones or f"{track} (track)" in table, track


def test_the_names_table_states_each_exit_number_and_the_full_speed_goal():
    # The table must not weaken a goal or an exit rule (CONSTITUTION.md 5).
    table = names_table()
    stones = re.split(r"(?m)^## (S\d+b?)\. ", read("STONES.md"))[1:]
    for name, body in zip(stones[::2], stones[1::2], strict=True):
        if "100%" in body:
            assert "100%" in table[name], name
        if "move to S11" in body:
            assert "move to S11" in table[name], name
    for part in (
        "faster than sqlfluff on each benchmark",
        "not slower than sqruff on any benchmark",
        "faster than sqruff on the total of all benchmarks",
    ):
        assert part in table["G3"], part
    for part in ("automated test", "source, version, and license", "does not change"):
        assert part in table["G4"], part
