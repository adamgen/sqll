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


# Key phrases of each "- Exit:" line of STONES.md. Each phrase is in the
# exit text of the stone and in its row of the Names table.
EXITS = {
    "S1": (
        "sqlfluff passes 100% of the cases through the harness",
        "the results of the other tools are recorded",
    ),
    "S2": ("one command gives a machine-readable report", "baseline is recorded"),
    "S3": (
        "sqll passes all cases that the base passes",
        "not slower than sqruff on any benchmark",
    ),
    "S3b": (
        "the S1 harness and the S2 benchmarks run sqll through its adapters",
        "the interfaces are documented",
        "after S3b, each change to the core goes through the Core track",
    ),
    "S4": ("100% of the dialect parse fixtures with an exact tree match",),
    "S5": ("100% of the rule fixtures, lint and fix", "move to S11"),
    "S6": ("templater fixtures that do not need a Python runtime",),
    "S7": ("100% of the converted cases", "move to S11"),
    "S8": (
        "the JSON Schema output is valid and correct for each parameter style",
        "code made from the schema by one existing tool compiles",
        "the harness shows one parse for each file when one command lints and"
        " generates code",
    ),
    "S9": ("the report shows parse success and speed for each file, for each tool",),
    "S10": ("a test set of PL/pgSQL functions parses with no unparsable segments",),
    "S11": (
        "100% of the Jinja cases that the decision keeps",
        "S8 supports Jinja if kept",
        "each other Jinja case is in a known-failure list with its reason",
    ),
}
# Other parts of a stone that its row must keep.
STONE_PARTS = {
    "S1": ("not through function calls",),
    "S3b": ("sqll adapters of the S1 harness and the S2 benchmarks",),
    "S9": ("source and license",),
    "S11": ("Decision of the human owner (2026-11-07)", "Jinja engine in sqll"),
}
# Parts of each goal of CONSTITUTION.md section 1 that its row must keep.
GOAL_PARTS = {
    "G1": (
        "pinned sqlfluff version",
        "except Python plugins and features that need a Python runtime",
        "Only the human owner approves each version change",
        "percentage of sqlfluff test cases",
        "through a binary",
        "same harness runs sqlfluff, sqruff, and sqll",
    ),
    "G3": (
        "start time",
        "as fast as reasonably possible and has a benchmark",
        "on the same input",
        "faster than sqlfluff on each benchmark",
        "not slower than sqruff on any benchmark",
        "faster than sqruff on the total of all benchmarks",
        "makes a benchmark slower gives the reason",
        "Correctness is more important than speed",
    ),
    "G4": (
        "automated test",
        "external sources",
        "source, version, and license",
        "does not change",
        "one command runs all tests and benchmarks",
        "machine-readable",
        "known failure",
    ),
}


def exit_lines(body: str) -> list[str]:
    found = re.findall(r"(?ms)^- Exit: (.*?)(?=^- |^\S|\Z)", body)
    return [words(line).lower() for line in found]


def test_the_names_table_states_each_exit_of_each_stone():
    table = {name: goal.lower() for name, goal in names_table().items()}
    stones = re.split(r"(?m)^## (S\d+b?)\. ", read("STONES.md"))[1:]
    bodies = dict(zip(stones[::2], stones[1::2], strict=True))
    assert set(EXITS) == set(bodies)
    for name, body in bodies.items():
        lines = exit_lines(body)
        assert lines, name
        phrases = [phrase.lower() for phrase in EXITS[name]]
        for phrase in phrases:
            assert any(phrase in line for line in lines), (name, phrase)
            assert phrase in table[name], (name, phrase)
        # A new exit line in STONES.md needs a key phrase here.
        for line in lines:
            assert any(phrase in line for phrase in phrases), (name, line)
    for name, parts in STONE_PARTS.items():
        for part in parts:
            assert part.lower() in words(bodies[name]).lower(), (name, part)
            assert part.lower() in table[name], (name, part)


def test_the_names_table_states_each_part_of_each_goal():
    table = names_table()
    for name, parts in GOAL_PARTS.items():
        for part in parts:
            assert part in table[name], (name, part)
