# sqll Status

- Current stone: **S2** (benchmarks). Design: [harness/bench.md](harness/bench.md).
- S1 is complete. The human owner approved it on 2026-10-19 (owner
  statement to the workflow). S1 tasks T1 to T9 are merged (PRs #3 to #11).
  CI on main passed after the last merge (run 39235508233, head `016a5e1`,
  54 of 54 jobs).
- sqlfluff reference: tag `4.4.0`, commit `0348222a3bcdb0226563f7349c5a39beb0641955`.

## S2 tasks

| Task | Description | State |
|---|---|---|
| T1 | S2 design record (`harness/bench.md`) and STATUS update | Merged (PR #12) |
| T2 | Benchmark definitions and deterministic input builder | Merged (PR #13) |
| T3 | Measurement core and the benchmark report schema | Merged (PR #14) |
| T4 | Benchmark adapters for sqlfluff, `sqlfluff[rs]`, and sqruff with validity checks | Merged (PR #15) |
| T5 | `sqll-harness bench run` and `scripts/bench`: one command, one machine-readable report | Merged (PR #16) |
| T6 | CI benchmark jobs and `scripts/verify` drift coverage | In review (PR #17) |
| T7 | Slowdown detection: `sqll-harness bench compare` and the change-record rule | Open |
| T8 | S2 exit: recorded baseline, exact drift checks, and STATUS | Open |

Benchmark definitions (`harness/sqll_harness/bench/definitions.json`): 280
benchmarks (28 dialect folders, also soql; `start` and 3 sizes of `parse`,
`lint`, `fix`) on 85 inputs (84 and `start`). The inputs use 2161 of 2306
dialect fixture files; 140 are in the frozen exclusion list. The
definitions also store the sqlfluff 4.4.0 reference of the 84 inputs
(`sqll-harness bench reference`): the `lint` rule codes (1 to 29 codes for
each input), and if `fix` changes the file (82 of 84; not `flink/small` and
`vertica/small`).

Measurement core (`harness/sqll_harness/bench/timer.py`, `report.py`): the
timer, the profiles (`full`: 3 to 20 timed runs, 2 s budget; `smoke`: 1
timed run; 120 s timeout), and the schema check of `out/bench.json`
(`harness/README.md`). Unit tests use test doubles only; no tool runs yet.
Measured: `/bin/sleep 0.2` median 0.202 s (10 runs), timer overhead
(`/bin/true`) median 1.4 ms.

Benchmark adapters (`harness/sqll_harness/bench/adapter.py`, `tools.py`,
`registry.py`): sqlfluff, `sqlfluff[rs]`, and sqruff, with the validity
checks of `harness/bench.md`. Tests with the real tools: on the small inputs
of ansi, bigquery, and tsql, each command of each tool is valid; sqruff on
soql is `unsupported: dialect soql`; with the default size limit, an input
of 20466 bytes is invalid (a skip with exit code 0) for each tool and
command that has the limit; an unparsable input is invalid for `parse`,
`lint`, and `fix`. A test-double tool runs all 280 benchmarks through the
registry, valid.

Benchmark runs (`harness/sqll_harness/bench/run.py`; `harness/README.md`,
"Benchmark runs"): `sqll-harness bench run`, `merge`, `check`, and
`scripts/bench`. On commit `b63cc7a`, `scripts/bench --profile smoke` (112
benchmarks, 3 tools) took 277 s, exit code 0. Valid: sqlfluff 112,
`sqlfluff[rs]` 112, sqruff 102 (details in PR #16). No timing is a baseline
yet (T8).

CI benchmark jobs (`harness/README.md`, "Benchmarks in CI"): `bench-smoke`
on each full CI run; `bench-full` (7 shards, by dialect) and `bench-merge`
on push to main and `workflow_dispatch`. Each job uploads its report. CI
gates on no timing. `scripts/verify` runs the smoke benchmark; the drift
test covers the new jobs and steps. The local copy of the full CI benchmark
is `scripts/bench`. A `workflow_dispatch` run on commit `128cd48` (run
39374292833) merged 7 of 7 shards, 280 benchmarks for each tool. Valid:
sqlfluff 280, `sqlfluff[rs]` 280, sqruff 216 (54 invalid, 10 unsupported).
Slowest shard: 1041 s. On the same commit, `scripts/verify` passed 25 of 25
checks (3779 s); its smoke benchmark: valid sqlfluff 112, `sqlfluff[rs]`
112, sqruff 102.

## S1 exit evidence (approved)

Proof: [`results/s1/summary.json`](results/s1/summary.json), the summary of
a full local run of all tools and suites (`sqll-harness run`, exit code 0).
The CI `report` job fails if this file is not the summary of the CI run, so
it cannot drift. CI passed on PR #10 (run 39217728740, head `b470bf9`, 53 of
53 jobs).

`scripts/verify` runs each CI check locally; a unit test fails if its
commands are not the CI commands. On commit `2a19de6` (the last code change
of PR #10; fresh clone, clean worktree) it passed 23 of 23 checks: exit code
0, 4104 s, 4 jobs.

| Criterion (STONES.md) | Proof |
|---|---|
| Submodule at tag `4.4.0` | `third_party/sqlfluff` at the commit above; `scripts/check-submodule` in CI: no change |
| Fixtures read in place | The suites read the submodule; check-submodule after each run |
| 4 fixture types | Suites `dialects` 2306, `rules` 2527, `autofix` 61, `templater` 43 cases: the cases that the sqlfluff tests collect (`harness/tests/test_case_counts.py`, see "Case counts" in `harness/README.md`) |
| Rule case is a YAML key | `harness/rules.md` |
| Adapters: sqlfluff, `sqlfluff[rs]`, sqruff | Results below, for all 4937 cases |
| 2 parse numbers | `exact` and `no_unparsable` in the summary; parity uses `exact` |
| Exit: sqlfluff passes 100% | 4937 of 4937, `known_failures/sqlfluff.txt` is empty. The sqlfluff tests (oracles) give the same status for each case |
| Exit: other tools recorded | `sqlfluff[rs]` and sqruff below |

## Parity

From `results/s1/summary.json`. The 4 suites, 4937 cases:

| Tool | Parity cases | Passed | Percent |
|---|---|---|---|
| sqlfluff 4.4.0 | 4937 | 4937 | 100.00 |
| sqlfluff-rs 4.4.0 | 4937 | 4937 | 100.00 |
| sqruff 0.41.0 | 4937 | 3806 | 77.09 |

| Suite | Tool | Total | Passed | Failed | Error | Skipped | Checks |
|---|---|---|---|---|---|---|---|
| dialects | sqlfluff 4.4.0 | 2306 | 2306 | 0 | 0 | 0 | exact 2306, no_unparsable 2306 |
| rules | sqlfluff 4.4.0 | 2527 | 2527 | 0 | 0 | 0 | after_fix 851, fail_str 1193, fix 1193, pass_str 1332 |
| autofix | sqlfluff 4.4.0 | 61 | 61 | 0 | 0 | 0 | fix 61, non_linting 61, tree 61, violations 1 |
| templater | sqlfluff 4.4.0 | 43 | 43 | 0 | 0 | 0 | exact 43, no_unparsable 43 |
| dialects | sqlfluff-rs 4.4.0 | 2306 | 2306 | 0 | 0 | 0 | exact 2306, no_unparsable 2306 |
| rules | sqlfluff-rs 4.4.0 | 2527 | 2527 | 0 | 0 | 0 | after_fix 851, fail_str 1193, fix 1193, pass_str 1332 |
| autofix | sqlfluff-rs 4.4.0 | 61 | 61 | 0 | 0 | 0 | fix 61, non_linting 61, tree 61, violations 1 |
| templater | sqlfluff-rs 4.4.0 | 43 | 43 | 0 | 0 | 0 | exact 43, no_unparsable 43 |
| dialects | sqruff 0.41.0 | 2306 | 1548 | 758 | 0 | 0 | exact 1548, no_unparsable 2164 |
| rules | sqruff 0.41.0 | 2527 | 2185 | 335 | 7 | 0 | after_fix 758, fail_str 1044, fix 997, pass_str 1207 |
| autofix | sqruff 0.41.0 | 61 | 45 | 16 | 0 | 0 | fix 45, non_linting 54, tree 54, violations 1 |
| templater | sqruff 0.41.0 | 43 | 28 | 15 | 0 | 0 | exact 28, no_unparsable 33 |

The sqlfluff tests give the same status for each case of the local report
(`scripts/sqlfluff-*-oracle`, also a CI step; with `--rust` for sqlfluff-rs,
which also runs the sqlfluff Python-vs-Rust parity test on the dialect
files). sqlfluff-rs is sqlfluff
with `use_rust_parser` and `use_rust_rules` set (`harness/sqlfluff-rs.md`).
sqruff has no oracle (`harness/sqruff.md`). 3 templater cases need a Python
runtime (`needs_python`, `harness/templater.md`). The `code_only` harness
check passes 2306 of 2306.

## Known failures

- sqlfluff: 0 (`known_failures/sqlfluff.txt` is empty).
- sqlfluff-rs: 0 (`known_failures/sqlfluff-rs.txt` is empty).
- sqruff: 1131 in `known_failures/sqruff.txt`: dialects 758, rules 342,
  autofix 16, templater 15. 7 are `error` (sqruff panics). The reasons are in
  `harness/sqruff.md`.

## Decisions

- Owner decision: sqlfluff `test/fixtures/parity/` is not part of the parity
  target. Its 29 cases (3 YAML files; 73 tests of
  `test/core/parser/parity/cases_test.py`) compare the Python and the Rust
  engines of sqlfluff and have no expected output. They compare engine
  internals that no CLI shows. The harness already compares sqlfluff and
  `sqlfluff[rs]` on all 4937 cases.

## Next

- From S3: a result cache with a key of tool version, fixtures, and harness
  code can let CI run again only the tool that changed (sqll). Do not make
  it now.
