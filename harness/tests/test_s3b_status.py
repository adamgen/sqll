"""S3b C3 and C4: the S3b plan in status/S3b.md and the S3b row of STATUS.md."""

import re

from sqll_harness.paths import REPO_ROOT

INDEX = (REPO_ROOT / "STATUS.md").read_text("utf8")
STATUS = (REPO_ROOT / "status" / "S3b.md").read_text("utf8")
TASKS = [f"C{i}" for i in range(1, 18)]
STATES = ("Not started", "In work", "In review")


def tasks() -> dict[str, tuple[str, str]]:
    rows = re.findall(r"(?m)^\| (C\d+) \| (.+) \| (.+) \|$", STATUS)
    found = {task: (text, state) for task, text, state in rows}
    assert len(found) == len(rows), "a task has two rows"
    return found


def test_the_plan_has_each_task_once_in_order():
    rows = re.findall(r"(?m)^\| (C\d+) \|", STATUS)
    assert rows == TASKS


def test_each_task_has_a_known_state():
    found = tasks()
    assert found["C1"][1] == "Merged (PR #57)"
    assert found["C2"][1] == "Merged (PR #58)"
    assert found["C3"][1] == "Merged (PR #59)"
    for task in TASKS[3:]:
        state = found[task][1]
        assert state in STATES or re.fullmatch(r"Merged \(PR #\d+\)", state), task


def test_the_index_row_names_the_core_track_and_the_plan():
    (row,) = [line for line in INDEX.splitlines() if line.startswith("| S3b |")]
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[1] == "core"
    assert cells[2].startswith("In work (track core).")
    assert "[status/S3b.md](status/S3b.md)" in cells[2]
    assert cells[3] == "[status/S3b.md](status/S3b.md)"
