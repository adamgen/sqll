# Agent instructions

Read these documents before you start work. They are the law of this repository.

1. CONSTITUTION.md: goals and rules.
2. STONES.md: milestones.
3. PROCESS.md: how to do the work.
4. STATUS.md: the current state.

## Names: write the goal with each name

Request of the human owner (2026-11-11). Each time that you write the name
of a stone (S1 to S11, S3b), a goal (G1 to G4), a track, or a task (for
example C16 or T1), also write its full goal. This applies to messages to
the human owner, pull requests, commit messages, and status files. Write
the name, then the goal in parentheses. Example: "S4 (parser parity: sqll
passes 100% of the dialect parse fixtures with an exact tree match)". For a
task, write the goal of the task and the goal of its stone. In a table, a
column with the goal is sufficient.

| Name | Goal |
|---|---|
| S1 | Binary test harness: run the sqlfluff test fixtures through a binary |
| S2 | Benchmarks: start, parse, lint, and fix for each tool and dialect |
| S3 | Choose the base and make the sqll binary from it |
| S3b | Core: the shared syntax tree, source map, frozen interfaces, and the sqll binary skeleton (CLI, config, output) |
| S4 | Parser parity: 100% of the dialect parse fixtures with an exact tree match |
| S5 | Rule parity: 100% of the rule fixtures, lint and fix |
| S6 | Templater parity: the placeholder and Python format-string templaters |
| S7 | CLI and config parity: the sqlfluff CLI, config, and Python rule tests as black-box cases |
| S8 | Code generation: types of query parameters and result columns as JSON Schema |
| S9 | External corpus: parse success and speed on large public SQL files |
| S10 | PL/pgSQL bodies: parse and lint SQL in PostgreSQL function bodies |
| S11 | Jinja templater: the last stone; decide with data how sqll supports Jinja |
| G1 | Lint parity with sqlfluff |
| G2 | Code generation |
| G3 | Speed: sqll is faster than sqlfluff and not slower than sqruff |
| G4 | Verification first: each behavior has an automated test; external test data has its source and license |
| core (track) | The track that does S3b and owns the shared core |
