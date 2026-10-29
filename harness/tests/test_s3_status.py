"""S3 T10: the phase B start in STATUS.md and status/S3.md."""

import json
import re

from sqll_harness.paths import REPO_ROOT

INDEX = (REPO_ROOT / "STATUS.md").read_text("utf8")
STATUS = (REPO_ROOT / "status" / "S3.md").read_text("utf8")
STATE = (
    "Phase B started: the base is sqlfluffrs (human owner, 2026-10-29); the"
    " phase B task list in [status/S3.md](status/S3.md)."
)
TASKS = [f"T{i}" for i in range(10, 21)]
STATES = ("Not started", "In work")


def phase_b() -> str:
    return STATUS.split("\n## S3 phase B\n", 1)[1].split("\n## ", 1)[0]


def part(title: str) -> str:
    return phase_b().split(f"\n### {title}\n", 1)[1].split("\n### ", 1)[0]


def words(text: str) -> str:
    return " ".join(text.split())


def test_the_index_row_has_the_phase_b_state():
    (row,) = [line for line in INDEX.splitlines() if line.startswith("| S3 |")]
    assert row.startswith(f"| S3 | S3 | {STATE} ")
    assert row.endswith(" | [status/S3.md](status/S3.md) |")
    assert "the license of sqll" in row


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
        if re.match(r"\| T\d+ \|", line)
    ]
    assert [r[0] for r in rows] == TASKS
    for task, description, state in rows:
        assert description, task
        assert state in STATES or re.fullmatch(
            r"(In review|Merged) \(PR #\d+\)", state
        ), (task, state)
    assert rows[0][2] != "Not started"
    assert "T17b, T17c" in rows[7][1]


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
    assert "It gives the data to the human owner" in text
    assert "option 3 of the decision record" in text
    assert "The S3 track does not change the base." in text


def test_the_open_license_question_is_t7_question_1():
    sizes = json.loads(
        (REPO_ROOT / "results" / "s3" / "license-size.json").read_text("utf8")
    )
    question = sizes["open_questions"][0]
    assert question.startswith("Which license does sqll use?")
    text = words(part("Open question for the human owner"))
    assert text.startswith("T19 needs the answer. Which license does sqll use?")
    assert "open question 1" in text


def test_the_phase_b_part_is_short():
    # A 5-minute read (CONSTITUTION.md 2.4).
    assert len(phase_b().split()) <= 600
