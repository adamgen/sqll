# sqll Status

This is the index of the stones and their state. Only the orchestrator
edits it. Each track writes the details to its own status file
(PROCESS.md, "Tracks").

sqlfluff reference: tag `4.4.0`, commit `0348222a3bcdb0226563f7349c5a39beb0641955`.

| Stone | Track | State | Details |
|---|---|---|---|
| S1 | | Complete. The human owner approved it on 2026-10-19 | [status/S1.md](status/S1.md) |
| S2 | | Complete. The human owner approved it on 2026-10-26 | [status/S2.md](status/S2.md) |
| S3 | S3 | Approved (human owner, 2026-11-06). Exit record (T20): [docs/decisions/s3-exit.md](docs/decisions/s3-exit.md); the base is sqlfluffrs (human owner, 2026-10-29). License: MIT (the human owner delegated the choice, 2026-11-01). Decision record: [docs/decisions/s3-base.md](docs/decisions/s3-base.md) | [status/S3.md](status/S3.md) |
| S3b | core | Approved (orchestrator under the standing delegation of the human owner, 2026-11-11) (track core: the track that does S3b and owns the shared core). Goal of S3b: the shared syntax tree, source map, frozen interfaces, and the sqll binary skeleton (CLI, config, output) with the sqll adapters of the test harness and the benchmarks; exits: the test harness and the benchmarks run sqll through its adapters, the interfaces are documented, and after this stone, each change to the core goes through that track. Each task of the plan is merged. Proof of the independent check: (1) CI run 43071390211 on main `7f98014` (the merge of PR #79): 77 of 77 jobs pass, with the exit check, 162 of 162 native base tests, and the tree guard 84 of 84 inputs; (2) a local harness run of sqll gives the numbers of the exit record (dialects 2306 of 2306 exact, rules 38 of 2527, autofix 0 of 61, templater 0 of 43), and 2942 harness tests pass; (3) each of the 8 interface documents has a test, 60 of 60 Core changes of the other tracks fail without the label `cross-track`, and 0 of 112 benchmarks are slower than the base. Details: [status/S3b.md](status/S3b.md), "Approval". The exit record: [docs/decisions/s3b-exit.md](docs/decisions/s3b-exit.md). Plan: [status/S3b.md](status/S3b.md) | [status/S3b.md](status/S3b.md) |
| S7 test conversion | S7-tests | In work (track S7-tests) | [status/S7-tests.md](status/S7-tests.md) |
| S9 | S9 | Approved (human owner, 2026-11-01) for sqlfluff, `sqlfluff[rs]`, and sqruff. The sqll results come after S3b | [status/S9.md](status/S9.md) |
| S4, S5, S6, S7 sqll part, S8, S10 | | Not started. See "Needs:" in STONES.md | |
| S11 | | Not started. The Jinja templater is the last stone (human owner, 2026-11-07) | |

Approvals: the orchestrator approves the stones and the human decisions by
the standing delegation of the human owner (CONSTITUTION.md, section 5).

Parity, known failures, and the S1 decisions: [status/S1.md](status/S1.md).
The benchmark baseline: [status/S2.md](status/S2.md).
