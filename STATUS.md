# sqll Status

- Current stone: **S2** (benchmarks): **S2 awaiting human approval**.
  Design: [harness/bench.md](harness/bench.md). Do not start S3 before
  the approval.
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
| T6 | CI benchmark jobs and `scripts/verify` drift coverage | Merged (PR #17) |
| T7 | Slowdown detection: `sqll-harness bench compare` and the change-record rule | Merged (PR #18) |
| T8 | S2 exit: recorded baseline, exact drift checks, and STATUS | In review (PR #PRNUM) |

## S2 exit evidence (awaiting approval)

Proof: [`results/s2/baseline.json`](results/s2/baseline.json), the report
of the one command `scripts/bench --profile full` (G4.4): exit code 0,
6521 s, on 2026-10-20, harness commit `626f256` (clean worktree). It was a
controlled run: the CI image, built from `ci/Dockerfile` on the local
machine (Intel Xeon 2.10 GHz, 4 CPUs, 16 GiB), one container, serial, no
other load (`harness/bench.md`, "Baseline"). The report has the machine
record; timer overhead (`/bin/true`) median 1.5 ms.

CI compares each smoke run with the baseline, fail closed (`sqll-harness
bench check --baseline`): the sqlfluff ref, the tool versions and
settings, the input sha256, and the status of each result. CI does not
gate on timings. CI_EVIDENCE VERIFY_EVIDENCE

| Criterion (STONES.md) | Proof |
|---|---|
| A benchmark for each command: start, parse, lint, fix | 280 benchmarks in `harness/sqll_harness/bench/definitions.json`: `start/<dialect>`, and `<parse\|lint\|fix>/<dialect>/<size>` |
| Small, medium, and large inputs for each dialect | 84 inputs of the 28 dialect folders (985 to 1024, 4017 to 4096, and 16350 to 16383 bytes), built from 2161 of the 2306 pinned dialect fixtures; their sha256 are in the definitions |
| One command gives a machine-readable report for sqlfluff, `sqlfluff[rs]`, and sqruff | `scripts/bench` writes `out/bench.json` (schema in `harness/README.md`); `bench check` passes on the baseline |
| The baseline is recorded | `results/s2/baseline.json`. `harness/tests/test_bench_baseline.py`: it passes the schema check; its benchmark ids and input sha256 are those of the definitions; it has one result for each benchmark and tool; the tables below are those of the file |

Other S2 parts: the validity checks of each run (`harness/bench.md`,
"Validity"; T4), the CI jobs `bench-smoke`, `bench-full`, and
`bench-merge` (T6), and `sqll-harness bench compare` for slowdowns (G3.6,
PROCESS.md rule 8; T7). A test-double tool runs all 280 benchmarks
through the registry with no change to the definitions (sqll in S3).

## Baseline

From `results/s2/baseline.json`. Times: the sum of the median times of the
`valid` benchmarks of the tool and command. A tool with fewer valid
benchmarks has a smaller sum, thus compare tools with the pair table.

| Tool | Command | Valid | Invalid | Unsupported | Error | Wall time (s) | CPU time (s) |
|---|---|---|---|---|---|---|---|
| sqlfluff 4.4.0 | start | 28 | 0 | 0 | 0 | 14.5 | 13.4 |
| sqlfluff 4.4.0 | parse | 84 | 0 | 0 | 0 | 76.6 | 71.8 |
| sqlfluff 4.4.0 | lint | 84 | 0 | 0 | 0 | 165.3 | 157.0 |
| sqlfluff 4.4.0 | fix | 84 | 0 | 0 | 0 | 514.3 | 490.0 |
| sqlfluff-rs 4.4.0 | start | 28 | 0 | 0 | 0 | 13.5 | 12.6 |
| sqlfluff-rs 4.4.0 | parse | 84 | 0 | 0 | 0 | 51.9 | 48.4 |
| sqlfluff-rs 4.4.0 | lint | 84 | 0 | 0 | 0 | 145.1 | 136.6 |
| sqlfluff-rs 4.4.0 | fix | 84 | 0 | 0 | 0 | 504.5 | 480.9 |
| sqruff 0.41.0 | start | 27 | 0 | 1 | 0 | 0.5 | 0.4 |
| sqruff 0.41.0 | parse | 81 | 0 | 3 | 0 | 3.4 | 3.1 |
| sqruff 0.41.0 | lint | 55 | 26 | 3 | 0 | 6.2 | 5.8 |
| sqruff 0.41.0 | fix | 53 | 28 | 3 | 0 | 13.4 | 12.7 |

Pairs: the sums over the benchmarks where both tools are `valid`.

| Tools | Benchmarks | Wall time (s) | Wall time ratio |
|---|---|---|---|
| sqlfluff 4.4.0 / sqlfluff-rs 4.4.0 | 280 | 770.8 / 714.9 | 1.078 |
| sqlfluff 4.4.0 / sqruff 0.41.0 | 216 | 362.6 / 23.5 | 15.425 |
| sqlfluff-rs 4.4.0 / sqruff 0.41.0 | 216 | 323.2 / 23.5 | 13.749 |

Results that are not `valid` (no comparison or total uses them). The
reason of each result has the text of the row:

| Tool | Status | Reason (text) | Benchmarks |
|---|---|---|---|
| sqruff | invalid | the rule codes are not those of the sqlfluff reference | `fix/athena/large`, `fix/athena/medium`, `fix/athena/small`, `fix/databricks/large`, `fix/databricks/medium`, `fix/databricks/small`, `fix/duckdb/large`, `fix/greenplum/large`, `fix/hive/large`, `fix/impala/large`, `fix/impala/medium`, `fix/mariadb/large`, `fix/mysql/medium`, `fix/postgres/large`, `fix/redshift/large`, `fix/snowflake/large`, `fix/snowflake/medium`, `fix/sqlite/medium`, `fix/teradata/large`, `fix/trino/large`, `fix/trino/medium`, `fix/trino/small`, `fix/vertica/large` |
| sqruff | invalid | the rule codes are not those of the sqlfluff reference | `lint/athena/large`, `lint/athena/medium`, `lint/athena/small`, `lint/databricks/large`, `lint/databricks/medium`, `lint/databricks/small`, `lint/duckdb/large`, `lint/greenplum/large`, `lint/hive/large`, `lint/impala/large`, `lint/impala/medium`, `lint/mariadb/large`, `lint/mysql/medium`, `lint/postgres/large`, `lint/redshift/large`, `lint/snowflake/large`, `lint/snowflake/medium`, `lint/sqlite/medium`, `lint/teradata/large`, `lint/trino/large`, `lint/trino/medium`, `lint/trino/small`, `lint/vertica/large` |
| sqruff | invalid | the tool crashed (panic) | `fix/mysql/large`, `fix/oracle/large`, `fix/oracle/medium`, `fix/tsql/large`, `lint/mysql/large`, `lint/oracle/large`, `lint/oracle/medium` |
| sqruff | invalid | timeout after 120.0 s | `fix/ansi/large` |
| sqruff | unsupported | unsupported: dialect soql | `fix/soql/large`, `fix/soql/medium`, `fix/soql/small`, `lint/soql/large`, `lint/soql/medium`, `lint/soql/small`, `parse/soql/large`, `parse/soql/medium`, `parse/soql/small`, `start/soql` |

For these inputs, sqruff gives other rule codes than the sqlfluff
reference (rule differences, as in S1: `harness/sqruff.md`), or it
panics. The `fix/ansi/large` run of sqruff did not stop in 120 s. sqruff
has no soql dialect. sqlfluff and `sqlfluff[rs]` are valid on each
benchmark. The CI full run on commit `128cd48` (run 39374292833) gave the
same counts of each status.

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
