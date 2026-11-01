# sqll Status

This is the index of the stones and their state. Only the orchestrator
edits it. Each track writes the details to its own status file
(PROCESS.md, "Tracks").

sqlfluff reference: tag `4.4.0`, commit `0348222a3bcdb0226563f7349c5a39beb0641955`.

| Stone | Track | State | Details |
|---|---|---|---|
| S1 | | Complete. The human owner approved it on 2026-10-19 | [status/S1.md](status/S1.md) |
| S2 | | Complete. The human owner approved it on 2026-10-26 | [status/S2.md](status/S2.md) |
| S3 | S3 | Phase B started: the base is sqlfluffrs (human owner, 2026-10-29); the phase B task list in [status/S3.md](status/S3.md). T14: the speed target is not in reach on the estimate (no-go); the human owner decided on 2026-11-01 to continue the speed work (T15, T16, then the checkpoint T16b). T16b: the speed target is still not in reach on the estimate (no-go, 104 of 108): human decision needed (the S3 track stops). License: MIT (the human owner delegated the choice, 2026-11-01). Decision record: [docs/decisions/s3-base.md](docs/decisions/s3-base.md) | [status/S3.md](status/S3.md) |
| S3b | core | Not started. Needs S3 | |
| S7 test conversion | S7-tests | Ready to start: S1 is approved | |
| S9 | S9 | Approved (human owner, 2026-11-01) for sqlfluff, `sqlfluff[rs]`, and sqruff. The sqll results come after S3b | [status/S9.md](status/S9.md) |
| S4, S5, S6, S7 sqll part, S8, S10 | | Not started. See "Needs:" in STONES.md | |

Parity, known failures, and the S1 decisions: [status/S1.md](status/S1.md).
The benchmark baseline: [status/S2.md](status/S2.md).
