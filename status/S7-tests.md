# S7-tests status

The S7-tests track writes this file (PROCESS.md, "Tracks").

- State: in work. The track converts the sqlfluff tests of STONES.md S7 to
  black-box cases. S7 test conversion needs only S1, and S1 is approved.
  The sqll part of S7 is track S7-sqll (it needs S3b).
- Design record:
  [docs/decisions/s7-tests-design.md](../docs/decisions/s7-tests-design.md).

## S7-tests tasks

| Task | Description | State |
|---|---|---|
| T1 | Design record, scope inventory, and status files | In review |
| T2 | Case format, case runner, and pilot cases | Not started |
| T3 | Trace oracle with fail-closed checks | Not started |
| T4 | Cross-track (Core): harness hooks for the S7 suites | Not started |
| T5 | Cross-track (Core): CI jobs, oracle step, and local verify for the S7 suites; the ruff lint of `scripts/s7-tests/` in CI; first recorded results | Not started |
| T6 | Convert the rule tests, part 1: lint-only tests through the simple API | Not started |
| T7 | Convert the rule tests, part 2: fix, combination, file, and template tests | Not started |
| T8 | Rust dispatch tests (cp01, cp03, cp04): classification and conversion | Not started |
| T9 | Convert the config fixture tests (users of `test/fixtures/config`) | Not started |
| T10 | Convert the other config tests (`test/core/config`) | Not started |
| T11 | Convert the CLI tests, part 1: commands, arguments, and exit codes | Not started |
| T12 | Convert the CLI tests, part 2: output formats and serialization | Not started |
| T13 | Convert the CLI tests, part 3: stdin, render, noqa, and inline config | Not started |
| T14 | Convert the CLI tests, part 4: fix and format | Not started |
| T15 | Convert the CLI tests, part 5: verbosity, quiet, progress bars, and the other `test/cli` files | Not started |
| T16 | S7 test conversion exit: proof and "awaiting human approval" | Not started |

Open decisions for the orchestrator to record (design record): the scope
rule, the exclusion classes, the Rust dispatch exclusion (before T8
merges), and the pointer section in `harness/not-reproduced.md`.

## Scope

From [results/S7-tests/scope.json](../results/S7-tests/scope.json), the
output of `scripts/s7-tests/inventory` on sqlfluff 4.4.0 (pytest nodes):

| Group | Nodes |
|---|---|
| `cli` | 295 |
| `rules` | 208 |
| `config` | 137 |
| `config_fixtures` | 3 |
| `total` | 643 |

- `cli`: 285 nodes that pytest collects, and 10 nodes of
  `test/cli/test_parse_with_positions.py`, which it collects only by path.
- `rules`: the S1 suites already have 2588 nodes (`test__rule_test_case`
  2527, `test__std_fix_auto` 61). The Rust dispatch tests are 102 nodes;
  87 of them are `fix_parity` nodes (engine comparison).
- `config_fixtures`: 2 nodes of
  `test/core/helpers/file_test.py::test__config__iter_config_paths` name
  the folder in their source. The run checks
  (`scripts/s7-tests/config-readers`: with sqlfluff 12.4 minutes, with
  `sqlfluff[rs]` 13.5 minutes) found 1 more node that reads it:
  `test/core/linter/discovery_test.py::test__linter__path_from_paths__dot`.

No case is converted yet. Parity numbers and known failures come with T5.
