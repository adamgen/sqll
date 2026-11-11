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
column with the goal is sufficient. A track of tracks.yml that is not in
this table has the name of its stone and the goal of that stone. The
source of each goal is CONSTITUTION.md (G1 to G4) and STONES.md (the
stones). If this table and a source do not agree, the source is correct.

| Name | Goal |
|---|---|
| S1 | Binary test harness: run the sqlfluff test fixtures through a binary, not through function calls; sqlfluff passes 100% of the cases through the harness, and the results of the other tools are recorded |
| S2 | Benchmarks: a benchmark for each command (start, parse, lint, fix) with small, medium, and large inputs for each dialect; one command gives a machine-readable report for sqlfluff, `sqlfluff[rs]`, and sqruff, and the baseline is recorded |
| S3 | Choose the base and make the sqll binary from it; sqll passes all cases that the base passes and is not slower than sqruff on any benchmark |
| S3b | Core: the shared syntax tree, source map, frozen interfaces, and the sqll binary skeleton (CLI, config, output) with the sqll adapters of the S1 harness and the S2 benchmarks; the S1 harness and the S2 benchmarks run sqll through its adapters, the interfaces are documented, and after S3b, each change to the core goes through the Core track |
| S4 | Parser parity: 100% of the dialect parse fixtures with an exact tree match |
| S5 | Rule parity: 100% of the rule fixtures, lint and fix; cases that need the Jinja templater move to S11 |
| S6 | Templater parity: 100% of the placeholder and Python format-string templater fixtures that do not need a Python runtime |
| S7 | CLI and config parity: the sqlfluff CLI, config, and Python rule tests as black-box cases; sqll passes 100% of the converted cases; cases that need the Jinja templater move to S11 |
| S8 | Code generation: types of query parameters and result columns as JSON Schema; the JSON Schema output is valid and correct for each parameter style, code made from the schema by one existing tool compiles, and the harness shows one parse for each file when one command lints and generates code |
| S9 | External corpus: large, complex SQL files from public sources, with their source and license; the report shows parse success and speed for each file, for each tool |
| S10 | PL/pgSQL bodies: parse and lint SQL in PostgreSQL function bodies; a test set of PL/pgSQL functions parses with no unparsable segments |
| S11 | Jinja templater: the last stone; decision of the human owner (2026-11-07): do not write a Jinja engine in sqll; decide with data how sqll supports Jinja; sqll passes 100% of the Jinja cases that the decision keeps, and S8 supports Jinja if kept; each other Jinja case is in a known-failure list with its reason |
| G1 | Lint parity with sqlfluff: sqll does all that the pinned sqlfluff version does (dialects, rules, fixes, configuration, templaters), except Python plugins and features that need a Python runtime. Only the human owner approves each version change (the standing delegation keeps it). Parity is the percentage of sqlfluff test cases that sqll passes through a binary. The same harness runs sqlfluff, sqruff, and sqll |
| G2 | Code generation: typed code from SQL, as sqlc does. The input parameters and output columns of each query in a standard schema format, for each parameter style and templater of G1, with the parser of the linter |
| G3 | Speed: each command, start time included, is as fast as reasonably possible and has a benchmark that measures sqlfluff, sqruff, and sqll on the same input. sqll is faster than sqlfluff on each benchmark, not slower than sqruff on any benchmark, and faster than sqruff on the total of all benchmarks. A change that makes a benchmark slower gives the reason. Correctness is more important than speed: do not make a result wrong to make it fast |
| G4 | Verification first: each behavior has an automated test; tests come from external sources (sqlfluff first, then large, complex public SQL files); external test data has its source, version, and license, and does not change to make a test pass; one command runs all tests and benchmarks, and the output is machine-readable; each known failure is in a list |
| core (track) | The track that does S3b and owns the shared core |
| S7-tests (track) | The track that converts the S7 tests to black-box cases (the test conversion of S7) |
| S7-sqll (track) | The track that makes sqll pass the converted S7 cases (the sqll part of S7) |
