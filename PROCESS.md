# sqll Process

This document tells agents how to do the work in STONES.md.

## Roles

- **Orchestrator:** starts and stops the tracks and the other agents. It
  does not write code.
- **Planner:** divides a stone into tasks. Each task is one pull request.
- **Author:** does one task and opens one pull request.
- **Reviewer:** examines the pull request and writes findings. It does not change the code.
- **Fixer:** changes the code for the findings. Usually the author does this.

Each agent starts with new context. Use a Workflow script to run the cycle when one is available.

## Cycle for each task

1. The author opens a pull request.
2. CI runs the tests and the benchmarks. For a pull request that changes
   only documents, CI runs only the changes, image, and lint jobs.
3. A reviewer writes findings.
4. If there are findings, the fixer changes the code. Then a new reviewer examines it.
   Do steps 3 and 4 again until a reviewer approves.
5. Merge when CI passes and a reviewer approves.

## Rules

1. A task is smaller than a stone. A reviewer must be able to examine it well.
2. CI is the main gate. Do not merge when CI fails, even with an approval.
3. An agent must not approve its own changes.
4. There is no limit on review rounds. The author, the reviewers, and the
   fixers continue until the work is correct and a reviewer approves. Use
   as little human supervision as possible. Ask a human only for: approval
   of a stone, approval of a decision that STONES.md gives to a human (for
   example the S3 base), a change to CONSTITUTION.md, a change of the pinned
   sqlfluff version, and a blocker that only a human can remove (for example
   an account setting). Do not continue past such a decision before a human
   approves it.
5. Each track keeps its status file correct: open tasks, parity numbers,
   and known failures. The orchestrator keeps the STATUS.md index correct.
6. A human approves each completed stone. A stone starts only when each
   stone that it needs is approved (STONES.md, "Needs:").
7. A false pass that only a mutated or invented fixture shows (no fixture of
   the pinned sqlfluff version has the pattern) does not block a merge if
   `harness/not-reproduced.md` records it or a fail-closed check covers it.
   It blocks a merge if a pinned fixture has the pattern or the oracle does
   not agree on a pinned case. A missing or false record, or a false claim
   in a document, also blocks a merge.
8. If `sqll-harness bench compare` flags a benchmark of a change as slower,
   the pull request body must give the reason (G3.6, `harness/bench.md`,
   "Slowdowns").

## Tracks

Stones that do not need each other run in parallel, one track for each.

1. A track does one stone, or one part of a split stone (for example
   `S7-tests`). The Core track (`core`) does S3b.
2. Each track has its own branches (`claude/<track>` or
   `claude/<track>-<topic>`, in lowercase, for example `claude/s9-corpus`),
   its own git worktree, and at most one open pull request. `tracks.yml`
   gives the branches of each track.
3. `tracks.yml` gives the paths that each track owns. The `Ownership` CI
   check fails a pull request that changes a path of another track, unless
   the pull request has the label `cross-track`. Then the owning track must
   review it. A branch that is not in `tracks.yml` gets the Core track rules.
4. The Core track owns the shared tree and interfaces, the harness core,
   the CI workflow files, `ci/`, `scripts/`, and the protocol files
   (CONSTITUTION.md, PROCESS.md, STONES.md, STATUS.md, `tracks.yml`). Other
   tracks ask for a Core change with an issue.
5. Hot files: STATUS.md is a short index. Each track writes only its own
   status file `status/<track>.md` (for example `status/S9.md`; the Core
   track: `status/S3b.md`), its CI matrix entries in
   `ci/matrix.d/<track>.json`, and its results in `results/<track>/`. The
   old `results/s1/` and `results/s2/` stay.
6. Before a merge, merge the newest main into the branch, push, and wait
   for CI on that head. CI must pass on it.
7. Do only one long local run at a time on a machine (for example a full
   `scripts/verify` or `scripts/bench`). Take the machine lock:
   `flock /tmp/sqll-machine.lock scripts/verify`. Else CI is the proof.
8. One orchestrator starts and stops the tracks. It is the only editor of
   PROCESS.md, STONES.md, and the STATUS.md index. It makes these changes
   in Core track pull requests.
