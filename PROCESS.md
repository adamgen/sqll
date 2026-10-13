# sqll Process

This document tells agents how to do the work in STONES.md.

## Roles

- **Orchestrator:** starts the other agents. It does not write code.
- **Planner:** divides a stone into tasks. Each task is one pull request.
- **Author:** does one task and opens one pull request.
- **Reviewer:** examines the pull request and writes findings. It does not change the code.
- **Fixer:** changes the code for the findings. Usually the author does this.

Each agent starts with new context. Use a Workflow script to run the cycle when one is available.

## Cycle for each task

1. The author opens a pull request.
2. CI runs the tests and the benchmarks.
3. A reviewer writes findings.
4. If there are findings, the fixer changes the code. Then a new reviewer examines it.
5. Merge when CI passes and a reviewer approves.

## Rules

1. A task is smaller than a stone. A reviewer must be able to examine it well.
2. CI is the main gate. Do not merge when CI fails, even with an approval.
3. An agent must not approve its own changes.
4. After review round 3 with no approval, the fixer fixes the open findings.
   Then one verification round examines only those findings. If they are
   fixed and CI passes, merge. If not, stop and ask a human.
5. Keep STATUS.md correct: the current stone, open tasks, parity numbers, and known failures.
6. A human approves each completed stone before the next stone starts.
7. A false pass that only a mutated or invented fixture shows (no fixture of
   the pinned sqlfluff version has the pattern) does not block a merge if
   `harness/not-reproduced.md` records it or a fail-closed check covers it.
   It blocks a merge if a pinned fixture has the pattern or the oracle does
   not agree on a pinned case. A missing or false record, or a false claim
   in a document, also blocks a merge.
