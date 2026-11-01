"""S3 T10: the phase B start in STATUS.md and status/S3.md."""

import json
import re

from sqll_harness.paths import REPO_ROOT

INDEX = (REPO_ROOT / "STATUS.md").read_text("utf8")
STATUS = (REPO_ROOT / "status" / "S3.md").read_text("utf8")
STATE = (
    "Phase B: speed work continues (human owner, 2026-11-01): T17 next; the base"
    " is sqlfluffrs (human owner, 2026-10-29)."
)
TASKS = (
    [f"T{i}" for i in range(10, 17)]
    + ["T16b", "T17", "T17b", "T17c"]
    + [f"T{i}" for i in range(18, 21)]
)
DECISION = [
    "- The T14 result stays no-go on the estimate. Its data does not change.",
    "- Continue the speed work: T15, T16, then the checkpoint T16b, which runs the"
    " T14 method again.",
    "- If T16b shows that the target is still out of reach, the S3 track stops for"
    " a new human decision.",
]
DECISION_T16B = [
    "- The T16b result stays no-go on the estimate. Its data does not change: 71"
    " of 108 below the target, 104 of 108 in reach, worst needed factor 1.53.",
    "- Option (a): continue the speed work with T17, up to 3 rounds (T17, T17b,"
    " T17c), to the S3 exit.",
    "- Option 3 of the decision record is not chosen.",
]
LICENSE = (
    "The human owner delegated the choice on 2026-11-01. The choice is MIT, the"
    " license of the ported code (sqlfluff, sqlfluffrs); all 54 dependencies of the"
    " base have a permissive option (T7). T19 makes the LICENSE file and answers"
    " the open questions (`results/s3/license-size.json`)."
)
STATES = ("Not started", "In work")


def phase_b() -> str:
    return STATUS.split("\n## S3 phase B\n", 1)[1].split("\n## ", 1)[0]


def part(title: str) -> str:
    return phase_b().split(f"\n### {title}\n", 1)[1].split("\n### ", 1)[0]


def section(title: str) -> str:
    return STATUS.split(f"\n## {title}\n", 1)[1].split("\n## ", 1)[0]


def words(text: str) -> str:
    return " ".join(text.split())


def test_the_index_row_has_the_phase_b_state():
    (row,) = [line for line in INDEX.splitlines() if line.startswith("| S3 |")]
    assert row.startswith(f"| S3 | S3 | {STATE} ")
    assert row.endswith(" | [status/S3.md](status/S3.md) |")
    assert "License: MIT (the human owner delegated the choice, 2026-11-01)." in row
    # The human decisions of 2026-11-01 are made (status/S3.md), also the
    # decision on the no-go of the checkpoint T16b. The row asks for none.
    assert "Open question" not in row
    assert "human decision needed" not in row
    assert "not in reach" not in row
    t16b = json.loads(
        (REPO_ROOT / "results" / "s3" / "speed" / "T16b.json").read_text("utf8")
    )
    assert t16b["go"]["result"] == "no-go"
    assert section("Human owner decision after T16b (2026-11-01)").strip()


def test_the_status_file_has_the_phase_b_state():
    assert (
        STATUS.splitlines().count(
            "- State: **Phase B started: the base is sqlfluffrs"
            " (human owner, 2026-10-29).**"
        )
        == 1
    )
    assert "phase B next" not in STATUS
    assert "PR #PRNUM" not in STATUS


def test_the_phase_b_task_table():
    rows = [
        [cell.strip() for cell in line.split("|")[1:-1]]
        for line in part("Tasks").splitlines()
        if re.match(r"\| T\d+[bc]? \|", line)
    ]
    assert [r[0] for r in rows] == TASKS
    for task, description, state in rows:
        assert description, task
        assert state in STATES or re.fullmatch(
            r"(In review|Merged) \(PR #\d+\)", state
        ), (task, state)
    by_task = {r[0]: r for r in rows}
    assert rows[0][2] != "Not started"
    # Up to 3 rounds of T17 (human owner, 2026-11-01).
    assert by_task["T17"][1] == "Parse speed 4: close the gap, round 1 of 3"
    assert by_task["T17b"][1] == "Parse speed 4b: round 2"
    assert by_task["T17c"][1] == "Parse speed 4c: round 3"
    assert by_task["T16b"][1] == "Checkpoint: run the T14 method again"


def test_the_exit_target():
    probe = json.loads(
        (REPO_ROOT / "results" / "s3" / "sqlfluffrs-probe.json").read_text("utf8")
    )
    total = probe["fixtures"]["total"]
    assert total["cases"] == total["exact"] == 2306
    text = words(part("Exit target"))
    assert "2306 of 2306 cases with an exact tree match, through the sqll binary" in (
        text
    )
    assert "The native tests of the base pass." in text
    assert "sqll is not slower than sqruff on each S2 benchmark that sqll runs" in text
    assert "The human owner checks this reading at stone approval." in text


def test_the_stop_rule():
    text = words(part("Stop rule"))
    assert "shows that the speed target is out of reach, the S3 track stops" in text
    assert "If the parse speed work (T14 to T17c) shows" in text
    assert "It gives the data to the human owner" in text
    assert "option 3 of the decision record" in text
    assert "The S3 track does not change the base." in text
    assert (
        "The human owner decision of 2026-11-01 (below) adds the checkpoint T16b."
        in text
    )


def test_the_human_owner_decision_of_2026_11_01():
    first = part("Human owner decision (2026-11-01)").strip()
    assert first.startswith("- ")
    items = ["- " + words(item) for item in first[2:].split("\n- ")]
    assert items == DECISION
    after = section("Human owner decision after T16b (2026-11-01)").strip()
    assert after.startswith("- ")
    items = ["- " + words(item) for item in after[2:].split("\n- ")]
    assert items == DECISION_T16B
    # The numbers of the decision are those of the T16b record.
    t16b = json.loads(
        (REPO_ROOT / "results" / "s3" / "speed" / "T16b.json").read_text("utf8")
    )
    assert t16b["go"]["result"] == "no-go"
    assert t16b["groups"]["all"]["below_target"] == 71
    assert t16b["groups"]["all"]["in_reach"]["central"] == 104
    paired = [r for r in t16b["benchmarks"] if r["needed_factor"] is not None]
    assert len(paired) == 108
    assert f"{max(r['needed_factor'] for r in paired):.2f}" == "1.53"
    assert "Open question for the human owner" not in STATUS


def test_the_license_choice_is_one_line():
    sizes = json.loads(
        (REPO_ROOT / "results" / "s3" / "license-size.json").read_text("utf8")
    )
    # The open questions that T19 answers; question 1 is the license of sqll.
    assert sizes["open_questions"][0].startswith("Which license does sqll use?")
    # The reason of the choice is that of the T7 data.
    base = sizes["bases"]["sqlfluffrs"]
    assert base["license"]["spdx"] == sizes["bases"]["new-parser"]["license"]["spdx"]
    assert base["license"]["spdx"] == "MIT"
    deps = base["dependencies"]["standalone"]
    assert deps["packages"] == deps["by_class"]["permissive"] == 54
    assert part("License").strip().splitlines() == [LICENSE]


def test_the_phase_b_part_is_short():
    # A 5-minute read (CONSTITUTION.md 2.4).
    assert len(phase_b().split()) <= 600


def test_the_speed_target_is_that_of_the_t14_record():
    record = json.loads(
        (REPO_ROOT / "results" / "s3" / "speed-profile.json").read_text("utf8")
    )
    target_part = part("Speed target (T14)").strip()
    assert len(target_part.splitlines()) <= 5
    text = words(target_part)
    target, groups, go = record["target"], record["groups"], record["go"]
    worst = max(
        (r for r in record["benchmarks"] if r["needed_factor"] is not None),
        key=lambda r: r["needed_factor"],
    )
    assert f"1/(1 + m) = {target['ratio_below']:.3f}" in text
    assert f"each of the {target['benchmarks']} start and parse benchmarks" in text
    assert f"m = {target['margin']}" in text
    assert f"T14: {groups['all']['below_target']} of 108 meet it." in text
    assert f"at most {worst['needed_factor']:.2f} ({worst['id']})" in text
    central = groups["all"]["in_reach"]["central"]
    large = groups["parse/large"]["in_reach"]["central"]
    assert f"on {central} of 108 ({large} of 27 parse/large)" in text
    if go["result"] == "no-go":
        assert "**No-go: human decision needed.**" in text
        assert "The human owner decided on 2026-11-01 (below)." in text
        assert "T15 does not start." not in text
        # The index row gives the state after the second decision of
        # 2026-11-01 (after T16b); T14 is in the decision section.
        assert (
            part("Human owner decision (2026-11-01)")
            .strip()
            .startswith("- The T14 result stays no-go on the estimate.")
        )
    else:
        assert "No-go" not in text
