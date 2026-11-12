# sqll Status

This is the index of the stones and their state. Only the orchestrator
edits it. Each track writes the details to its own status file
(PROCESS.md, "Tracks").

sqlfluff reference: tag `4.4.0`, commit `0348222a3bcdb0226563f7349c5a39beb0641955`.

Request of the human owner (Thursday, 2026-11-12): finish all open work, also
into the weekend if necessary, so that the work of next week starts with no
open ends.

| Stone | Track | State | Details |
|---|---|---|---|
| S1 | | Complete. The human owner approved it on 2026-10-19 | [status/S1.md](status/S1.md) |
| S2 | | Complete. The human owner approved it on 2026-10-26 | [status/S2.md](status/S2.md) |
| S3 | S3 | Approved (human owner, 2026-11-06). Exit record (T20): [docs/decisions/s3-exit.md](docs/decisions/s3-exit.md); the base is sqlfluffrs (human owner, 2026-10-29). License: MIT (the human owner delegated the choice, 2026-11-01). Decision record: [docs/decisions/s3-base.md](docs/decisions/s3-base.md) | [status/S3.md](status/S3.md) |
| S3b | core | Approved (orchestrator under the standing delegation of the human owner, 2026-11-11) (track core: the track that does S3b and owns the shared core). Goal of S3b: the shared syntax tree, source map, frozen interfaces, and the sqll binary skeleton (CLI, config, output) with the sqll adapters of the test harness and the benchmarks; exits: the test harness and the benchmarks run sqll through its adapters, the interfaces are documented, and after this stone, each change to the core goes through that track. Each task of the plan is merged. Proof of the independent check: (1) CI run 43071390211 on main `7f98014` (the merge of PR #79): 77 of 77 jobs pass, with the exit check, 162 of 162 native base tests, and the tree guard 84 of 84 inputs; (2) a local harness run of sqll gives the numbers of the exit record (dialects 2306 of 2306 exact, rules 38 of 2527, autofix 0 of 61, templater 0 of 43), and 2942 harness tests pass; (3) each of the 8 interface documents has a test, 60 of 60 Core changes of the other tracks fail without the label `cross-track`, and 0 of 112 benchmarks are slower than the base. Details: [status/S3b.md](status/S3b.md), "Approval". The exit record: [docs/decisions/s3b-exit.md](docs/decisions/s3b-exit.md). Plan: [status/S3b.md](status/S3b.md) | [status/S3b.md](status/S3b.md) |
| S4 | S4 | In work (track S4). S4 (parser parity: 100% of the dialect parse fixtures with an exact tree match). T1 (start the track: the status file, the design record, and the track paths; goal: the plan, the tree path, the gap rule, the CI gate design, the corpus rule, the speed rule, and the start data are recorded; this track owns its records, scripts, and harness tests) is merged (PR #85). Next task: T2 (fixture inventory and parity check; goal: each dialect fixture of the pinned sqlfluff is one harness case, and the check fails closed on each gap) | [status/S4.md](status/S4.md) |
| S6 | S6 | In work (track S6). S6 (templater parity: 100% of the placeholder and Python format-string templater fixtures that do not need a Python runtime). T1 (design record, fixture set from the data, status file, and track paths; goal: the scope and design of S6 are recorded and tested) is merged (PR #86). The 6 items of [docs/decisions/s6-templaters.md](docs/decisions/s6-templaters.md) wait for the decision of the orchestrator. Next task: T2 (goal: the case runner and the trace oracle of the track S7-tests (the track that converts the S7 tests to black-box cases) run the cases of S6 with its scope file; cross-track with that track and the track core (the track that does S3b and owns the shared core)) | [status/S6.md](status/S6.md) |
| S7 test conversion | S7-tests | In work (track S7-tests) | [status/S7-tests.md](status/S7-tests.md) |
| S9 | S9 | Approved (human owner, 2026-11-01) for sqlfluff, `sqlfluff[rs]`, and sqruff. S9 (external corpus: large, complex SQL files from public sources, with their source and license; the report shows parse success and speed for each file, for each tool). The sqll results are in work (track S9): T9 to T11 are merged (PR #87, PR #88, PR #89): T9 (the plan and design record of the sqll results), T10 (the corpus CI jobs and the local verify get the sqll binary), and T11 (the sqll corpus layer and the pair speed tables). The goal of each of these 3 tasks is the goal of S9. Next task: T12 (goal: the report and the check support sqll: the status `unsupported` when sqll fails closed, the "PRS: " message in the reason, `compared` for the 3 tools, the direction in each sqll check message, and the `rebase --tool sqll` command, with tests; the recorded baseline stays valid) | [status/S9.md](status/S9.md) |
| S5, S7 sqll part, S8, S10 | | Not started. See "Needs:" in STONES.md. S5 (rule parity: 100% of the rule fixtures, lint and fix; cases that need the Jinja templater move to the Jinja templater stone). The sqll part of S7 (CLI and config parity: the sqlfluff CLI, config, and Python rule tests as black-box cases; track S7-sqll: sqll passes 100% of the converted cases; cases that need the Jinja templater move to the Jinja templater stone). S8 (code generation: types of query parameters and result columns as JSON Schema; the JSON Schema output is valid and correct for each parameter style, code made from the schema by one existing tool compiles, and the harness shows one parse for each file when one command lints and generates code). S10 (PL/pgSQL bodies: parse and lint SQL in PostgreSQL function bodies; a test set of PL/pgSQL functions parses with no unparsable segments) | |
| S11 | | Not started. S11 (Jinja templater: the last stone; decision of the human owner (2026-11-07): do not write a Jinja engine in sqll; decide with data how sqll supports Jinja; sqll passes 100% of the Jinja cases that the decision keeps, and the code generation stone supports Jinja if kept; each other Jinja case is in a known-failure list with its reason) | |

S7 test conversion (track S7-tests: the test conversion of S7 (CLI and config
parity: the sqlfluff CLI, config, and Python rule tests as black-box cases;
sqll passes 100% of the converted cases; cases that need the Jinja templater
move to the Jinja templater stone)): T5 (CI jobs, oracle step, and local
verify for the S7 suites; goal: CI and `scripts/verify` run the S7 suites
and record the results) is merged (PR #83). Next task: T6
(convert the rule tests, part 1; goal: the lint-only rule nodes are
black-box cases).

Approvals: the orchestrator approves the stones and the human decisions by
the standing delegation of the human owner (CONSTITUTION.md, section 5).

Parity, known failures, and the S1 decisions: [status/S1.md](status/S1.md).
The benchmark baseline: [status/S2.md](status/S2.md).
