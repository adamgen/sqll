# S7-tests status

The S7-tests track writes this file (PROCESS.md, "Tracks").

- Track S7-tests: the test conversion part of S7 (CLI and config parity:
  the sqlfluff CLI, config, and Python rule tests as black-box cases).
- State: in work. S7 test conversion needs only S1 (binary test harness:
  run the sqlfluff test fixtures through a binary), and S1 is approved.
  The sqll part of S7 is track S7-sqll. It needs S3b (core: the shared
  syntax tree, source map, frozen interfaces, and the sqll binary
  skeleton).
- Design record:
  [docs/decisions/s7-tests-design.md](../docs/decisions/s7-tests-design.md).

## S7-tests tasks

Each task is a part of S7 (CLI and config parity: the sqlfluff CLI, config,
and Python rule tests as black-box cases). Plan of 2026-11-11: to recover
one lost day, T9 converts all config tests (before: 2 tasks).

| Task | Description | Goal | State |
|---|---|---|---|
| T1 | Design record, scope inventory, and status files | The scope (643 nodes), the design, and the 4 decisions are recorded and tested | In review |
| T2 | Case format, case runner, and pilot cases | One case format and one runner run pilot cases through a tool binary | Not started |
| T3 | Trace oracle with fail-closed checks | Each case agrees with a trace of its original pytest node | Not started |
| T4 | Cross-track (Core): harness hooks for the S7 suites | The harness core runs the 3 S7 suites | Not started |
| T5 | Cross-track (Core): CI jobs, oracle step, and local verify for the S7 suites; the ruff lint of `scripts/s7-tests/` in CI; first recorded results | CI and `scripts/verify` run the S7 suites and record the results | Not started |
| T6 | Convert the rule tests, part 1: lint-only tests through the simple API | The lint-only rule nodes are black-box cases | Not started |
| T7 | Convert the rule tests, part 2: fix, combination, file, and template tests | The other rule nodes (not Rust dispatch) are black-box cases | Not started |
| T8 | Rust dispatch tests (cp01, cp03, cp04): classification and conversion | Each Rust dispatch node is converted or excluded by decision 3 | Not started |
| T9 | Convert the config tests: the config fixture tests (users of `test/fixtures/config`) and the other config tests (`test/core/config`) | The 140 nodes of `config` and `config_fixtures` are black-box cases or excluded with a class | Not started |
| T10 | Convert the CLI tests, part 1: commands, arguments, and exit codes | The CLI nodes of commands, arguments, and exit codes are black-box cases | Not started |
| T11 | Convert the CLI tests, part 2: output formats and serialization | The CLI nodes of output formats are black-box cases | Not started |
| T12 | Convert the CLI tests, part 3: stdin, render, noqa, and inline config | The CLI nodes of stdin, render, noqa, and inline config are black-box cases | Not started |
| T13 | Convert the CLI tests, part 4: fix and format | The CLI nodes of fix and format are black-box cases | Not started |
| T14 | Convert the CLI tests, part 5: verbosity, quiet, progress bars, and the other `test/cli` files | Each of the 295 `cli` nodes is a black-box case or is excluded with a class | Not started |
| T15 | S7 test conversion exit: proof and "awaiting human approval" | The report shows each in-scope node as converted or excluded, with proof | Not started |

## Decisions

The orchestrator decided these 4 items on 2026-11-11 for the human owner
(standing delegation, CONSTITUTION.md section 5). The design record has
the same decisions.

1. Scope rule: ACCEPT. Do not make `config_fixtures` wider. Data:
   `scope.json` gives `cli` 295, `rules` 208, `config` 137,
   `config_fixtures` 3, total 643. The source rule finds 2 nodes. The run
   rule finds 1 node in both runs: sqlfluff 8268 passed, 3 failed, 2529
   skipped; `sqlfluff[rs]` 10792 passed, 3 failed, 5 skipped. The 3 failed
   `test/core/plugin_test.py` nodes do not read `test/fixtures/config`.
2. The 4 exclusion classes: ACCEPT, with these conditions:
   - A machine-readable list gives each excluded node with its node id
     and its class, apart from parity.
   - Each `needs-python-runtime` and `environment` node has a reason of
     one line.
   - The report gives the in-scope total, the converted count, and the
     excluded count.
3. Rust dispatch: Option A. The 87 `fix_parity` nodes (cp01 32, cp03 35,
   cp04 20) are `engine-comparison`. Their source assert compares
   `use_rust_rules` True and False and has no expected value. The S1 data
   cases cover the same rules: `CP01.yml` 29 cases (16 with `fix_str`),
   `CP03.yml` 17 (8), `CP04.yml` 5 (4). S1 compares sqlfluff and
   `sqlfluff[rs]` on 4937 cases. The same rule applies to the other
   compare-only nodes, for example the 3 `ignore_words_parity` nodes. A
   mock or spy node is `python-internal`. A node with an expected value
   that the CLI shows is converted.
4. Pointer section in `harness/not-reproduced.md`: ACCEPT. It comes in the
   cross-track T4 or T5 pull request. That pull request merges before an S7
   case uses a not-reproduced record.

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

No case is converted yet. Parity numbers and known failures come with T5
(CI jobs and first recorded results of the S7 suites).
