# S7-tests status

The S7-tests track writes this file (PROCESS.md, "Tracks").

- Track S7-tests (the track that converts the S7 tests to black-box cases:
  the test conversion of S7): the test conversion part of S7 (CLI and
  config parity: the sqlfluff CLI, config, and Python rule tests as
  black-box cases; sqll passes 100% of the converted cases; cases that need
  the Jinja templater move to S11 (Jinja templater: the last stone;
  decision of the human owner (2026-11-07): do not write a Jinja engine in
  sqll; decide with data how sqll supports Jinja; sqll passes 100% of the
  Jinja cases that the decision keeps, and S8 (code generation: types of
  query parameters and result columns as JSON Schema; the JSON Schema
  output is valid and correct for each parameter style, code made from the
  schema by one existing tool compiles, and the harness shows one parse
  for each file when one command lints and generates code) supports Jinja
  if kept; each other Jinja case is in a known-failure list with its
  reason)).
- State: in work. 7 of the 21 tasks of S7 (CLI and config parity: the sqlfluff
  CLI, config, and Python rule tests as black-box cases; sqll passes 100% of
  the converted cases; cases that need the Jinja templater move to the Jinja
  templater stone) are done, and 1 is in review. These 7 tasks are merged (the
  last on 2026-11-16, PR #99):
  - T1 (design record, scope inventory, and status files; goal: the scope
    (643 nodes), the design, and the 4 decisions are recorded and tested).
  - T2 (case format, case runner, and pilot cases; goal: one case format
    and one runner run pilot cases through a tool binary).
  - T3 (trace oracle with fail-closed checks; goal: each case agrees with
    a trace of its original pytest node).
  - T4 (harness hooks for the S7 suites; goal: the harness core runs the 3
    S7 suites).
  - T5 (CI jobs, oracle step, and local verify for the S7 suites; goal: CI
    and `scripts/verify` run the S7 suites and record the results).
  - T6 (convert the rule tests, part 1, the simple-API nodes; goal: the
    rule nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are
    black-box cases), PR #96.
  - T16 (trace oracle and case runner, extension 1; goal: the trace oracle
    maps and proves the calls that the remaining rule nodes use, and fails
    closed on each other call), PR #99.

  T17 (trace oracle and case runner, extension 2; goal: the trace oracle
  maps and proves the calls of the remaining rule nodes that T16 did not
  map, and fails closed on each other call) is in review (PR #101). The
  other 13 tasks are not started. The table "S7-tests tasks" gives each
  task with its goal, in the order of the plan.
- The S7 test conversion needs only S1 (binary test harness: run the
  sqlfluff test fixtures through a binary, not through function calls;
  sqlfluff passes 100% of the cases through the harness, and the results
  of the other tools are recorded), and S1 is approved.
- The sqll part of S7 is track S7-sqll (the track that makes sqll pass the
  converted S7 cases: the sqll part of S7). It needs S3b (core: the shared
  syntax tree, source map, frozen interfaces, and the sqll binary skeleton
  (CLI, config, output) with the sqll adapters of the test harness and the
  benchmarks; the test harness and the benchmarks run sqll through its
  adapters, the interfaces are documented, and after S3b, each change to
  the core goes through the Core track). S3b is approved (2026-11-11). The
  track S7-sqll is not started (STATUS.md).
- Design record:
  [docs/decisions/s7-tests-design.md](../docs/decisions/s7-tests-design.md).

## S7-tests tasks

Each task is a part of S7 (CLI and config parity: the sqlfluff CLI, config,
and Python rule tests as black-box cases; sqll passes 100% of the converted
cases; cases that need the Jinja templater move to the Jinja templater
stone). Plan of 2026-11-11: to recover one lost day, T9 (convert the config
tests; goal: the 140 nodes of `config` and `config_fixtures` are black-box
cases or excluded with a class) converts all config tests (before: 2
tasks). The orchestrator added T16 (trace oracle and case runner, extension
1; goal: the trace oracle maps and proves the calls that the remaining rule
nodes use, and fails closed on each other call) on 2026-11-15, before T7
(convert the rule tests, part 2; goal: the other rule nodes, not Rust
dispatch, are black-box cases): the rule nodes of T7 use calls that the
trace oracle did not map. The orchestrator added T17 (trace oracle and case
runner, extension 2; goal: the trace oracle maps and proves the calls of the
remaining rule nodes that T16 did not map, and fails closed on each other
call) on 2026-11-17 for the calls that T16 refuses. T17 added 4 tasks to the
plan (2026-11-17), each before the conversion task that needs it, from the
data of "Plan data (T17)":

- T18 (trace oracle and case runner, extension 3; goal: the trace oracle
  maps and proves the calls of the rule nodes that T17 did not map, and
  fails closed on each other call).
- T19 (trace oracle and case runner, extension 4; goal: the trace oracle
  maps and proves each config call of the config nodes that a CLI command
  shows, and fails closed on each other call).
- T20 (trace oracle and case runner, extension 5; goal: the trace oracle
  maps and proves the CLI calls of the CLI nodes that do not use
  `CliRunner.invoke`, and fails closed on each other call).
- T21 (trace oracle and case runner, extension 6; goal: the trace oracle
  maps and proves the other calls of the CLI nodes, and fails closed on
  each other call).

The rows of the table are in the order of the plan.

| Task | Description | Goal | State |
|---|---|---|---|
| T1 | Design record, scope inventory, and status files | The scope (643 nodes), the design, and the 4 decisions are recorded and tested | Done (PR #60) |
| T2 | Case format, case runner, and pilot cases | One case format and one runner run pilot cases through a tool binary | Done (PR #78) |
| T3 | Trace oracle with fail-closed checks | Each case agrees with a trace of its original pytest node | Done (PR #80) |
| T4 | Cross-track (Core): harness hooks for the S7 suites | The harness core runs the 3 S7 suites | Done (PR #82; the Core track approved it) |
| T5 | Cross-track (Core): CI jobs, oracle step, and local verify for the S7 suites; the ruff lint of `scripts/s7-tests/` in CI; first recorded results | CI and `scripts/verify` run the S7 suites and record the results | Done (PR #83; the Core track approved it) |
| T6 | Convert the rule tests, part 1: the simple-API nodes (`sqlfluff.lint` and `sqlfluff.fix` with `sql`, `dialect`, `rules`, and `exclude_rules`; no config) | The rule nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are black-box cases | Done (PR #96) |
| T16 | Trace oracle and case runner, extension 1: Linter string calls with a config, the simple-API config, Linter path calls with a config from overrides, and temporary folders with file checks; at most 2 proof nodes | The trace oracle maps and proves the calls that the remaining rule nodes use, and fails closed on each other call | Done (PR #99) |
| T17 | Trace oracle and case runner, extension 2: Linter arguments `dialect`, `rules`, and `exclude_rules`; the test helper `assert_rule_raises_violations_in_file`; an error of `RuleSet.get_rulepack` or of a Linter construction that the CLI gives; at most 2 proof nodes | The trace oracle maps and proves the calls of the remaining rule nodes that T16 did not map, and fails closed on each other call | In review (PR #101) |
| T18 | Trace oracle and case runner, extension 3: the calls of the rule nodes that T17 refuses: a config key that the default config does not have (Jinja context and delimiters, `align_scope`, the `capitalisation_policy` of functions), a fix run whose violations are not those of a lint run, and a config file in a temporary folder of a CLI call in the sqlfluff root | The trace oracle maps and proves the calls of the rule nodes that T17 did not map, and fails closed on each other call | Not started |
| T7 | Convert the rule tests, part 2: the rule nodes that are not simple-API nodes and not Rust dispatch (for example the nodes that give a config or a templater, or that call `Linter`); it needs the maps of T16, T17, and T18 | The other rule nodes (not Rust dispatch) are black-box cases | Not started |
| T8 | Rust dispatch tests (cp01, cp03, cp04): classification and conversion | Each Rust dispatch node is converted or excluded by decision 3 | Not started |
| T19 | Trace oracle and case runner, extension 4: the config calls of the `config` and `config_fixtures` nodes (FluffConfig loaders and errors) that a CLI command shows | The trace oracle maps and proves each config call of the config nodes that a CLI command shows, and fails closed on each other call | Not started |
| T9 | Convert the config tests: the config fixture tests (users of `test/fixtures/config`) and the other config tests (`test/core/config`); it needs the maps of T19 | The 140 nodes of `config` and `config_fixtures` are black-box cases or excluded with a class | Not started |
| T20 | Trace oracle and case runner, extension 5: the sqlfluff CLI commands that a `cli` node runs without `CliRunner.invoke` (`Command.main`, `get_config`) | The trace oracle maps and proves the CLI calls of the CLI nodes that do not use `CliRunner.invoke`, and fails closed on each other call | Not started |
| T21 | Trace oracle and case runner, extension 6: the other calls of the `cli` nodes that the oracle refuses: Linter path calls with options, `CliRunner.invoke` arguments that the trace cannot read, paths in the sqlfluff root and in a temporary folder in one call, a config file in a temporary folder, and programs | The trace oracle maps and proves the other calls of the CLI nodes, and fails closed on each other call | Not started |
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

## Pilot (T2)

T2 (case format, case runner, and pilot cases; S7: CLI and config parity, the
sqlfluff CLI, config, and Python rule tests as black-box cases; sqll passes
100% of the converted cases; cases that need the Jinja templater move to the
Jinja templater stone) gives the case format, the case runner
(`scripts/s7-tests/run-cases`; T4 (harness hooks for the S7 suites: the
harness core runs the 3 S7 suites; S7: CLI and config parity, the sqlfluff
CLI, config, and Python rule tests as black-box cases; sqll passes 100% of the
converted cases; cases that need the Jinja templater move to the Jinja
templater stone) moved it to `sqll-harness s7 run`), and pilot cases of each
group. T2 (case format, case runner, and pilot cases; goal: one case format
and one runner run pilot cases through a tool binary) of S7 (CLI and config
parity: the sqlfluff CLI, config, and Python rule tests as black-box cases;
sqll passes 100% of the converted cases; cases that need the Jinja templater
move to the Jinja templater stone) converted 15 pilot nodes (`cli` 8, `rules`
5, `config` 2) and excluded 3 nodes. The current counts and the parity of each
tool are in "Recorded results".

T5 (CI jobs, oracle step, and local verify for the S7 suites: CI and
`scripts/verify` run the S7 suites and record the results; S7: CLI and config
parity, the sqlfluff CLI, config, and Python rule tests as black-box cases;
sqll passes 100% of the converted cases; cases that need the Jinja templater
move to the Jinja templater stone) added the S7 CI jobs and the known-failure
lists; see "CI and recorded results (T5)".

## Trace oracle (T3)

T3 (trace oracle with fail-closed checks: each case agrees with a trace of its
original pytest node; S7: CLI and config parity, the sqlfluff CLI, config, and
Python rule tests as black-box cases; sqll passes 100% of the converted cases;
cases that need the Jinja templater move to the Jinja templater stone) gives
`scripts/s7-tests/oracle`. The design and its limits are in the design record,
"Trace oracle". The recorded result is
[results/S7-tests/oracle.json](../results/S7-tests/oracle.json), with the
traces `oracle-trace-sqlfluff.json` and `oracle-trace-sqlfluff-rs.json`.
The current result is in "Recorded results".

- In T3 (trace oracle with fail-closed checks; goal: each case agrees with a
  trace of its original pytest node) of S7 (CLI and config parity: the
  sqlfluff CLI, config, and Python rule tests as black-box cases; sqll passes
  100% of the converted cases; cases that need the Jinja templater move to the
  Jinja templater stone), each of the 15 pilot nodes that T2 (case format,
  case runner, and pilot cases; goal: one case format and one runner run pilot
  cases through a tool binary) converted agreed with its trace, and each of
  the 49 asserts of the pilot source tests had a check that cites it.
- T4 (harness hooks for the S7 suites: the harness core runs the 3 S7 suites;
  S7: CLI and config parity, the sqlfluff CLI, config, and Python rule tests
  as black-box cases; sqll passes 100% of the converted cases; cases that need
  the Jinja templater move to the Jinja templater stone) added the pointer
  section in `harness/not-reproduced.md` (decision 4); the recorded result now
  has `"pointer": true`.
- A `python-internal` node has no traced CLI or simple-API call.
- The case files now have an `asserts` map for each node.
- The oracle exits with code 1 if a case input is not the traced input, a
  check fails on the traced output, the report status is not the pytest
  outcome, or an assert has no citation and no record. A harness test
  proves each of these 4 failure paths.

## Harness hooks (T4)

T4 (cross-track task: harness hooks for the S7 suites; the harness core
runs the 3 S7 suites `s7_rules`, `s7_config`, `s7_cli`) is merged (PR #82,
2026-11-11). Its stone is S7 (CLI and config parity: the sqlfluff CLI,
config, and Python rule tests as black-box cases; sqll passes 100% of the
converted cases; cases that need the Jinja templater move to S11 (Jinja
templater: the last stone; decision of the human owner (2026-11-07): do not
write a Jinja engine in sqll; decide with data how sqll supports Jinja;
sqll passes 100% of the Jinja cases that the decision keeps, and S8 (code
generation: types of query parameters and result columns as JSON Schema;
the JSON Schema output is valid and correct for each parameter style, code
made from the schema by one existing tool compiles, and the harness shows
one parse for each file when one command lints and generates code)
supports Jinja if kept; each other Jinja case is in a known-failure list
with its reason)). The Core track (the track that does S3b and owns the
shared core) approved it. It added
`sqll-harness s7 run [--suite S] [--tool T]`. This command replaces
`scripts/s7-tests/run-cases`. The design is in the design record, "Case
runner" and "Report".

- The report has the key `suites` (format 2). The scope of a report is the
  nodes of its suites: `s7_rules` 208, `s7_config` 140, `s7_cli` 295.
- Before a tool runs, the command fails closed (exit code 2) if an assert
  of a converted source test has no citing check and no row of the
  not-reproduced record.
- `harness/not-reproduced.md` has the pointer section "S7 test conversion"
  (decision 4). THIRD_PARTY.md has the entry of S7 (CLI and config parity: the
  sqlfluff CLI, config, and Python rule tests as black-box cases; sqll passes
  100% of the converted cases; cases that need the Jinja templater move to the
  Jinja templater stone).
- The command of S1 (binary test harness: run the sqlfluff test fixtures
  through a binary, not through function calls; sqlfluff passes 100% of the
  cases through the harness, and the results of the other tools are
  recorded), `sqll-harness run`, and its suites do not change.

The results of each suite with each tool are in "Recorded results".

## CI and recorded results (T5)

T5 (cross-track task: CI jobs, oracle step, and local verify for the S7
suites; CI and `scripts/verify` run the S7 suites and record the results)
is merged (PR #83, 2026-11-12). Its stone is S7 (CLI and config parity:
the sqlfluff CLI, config, and Python rule tests as black-box cases; sqll
passes 100% of the converted cases; cases that need the Jinja templater
move to S11 (Jinja templater: the last stone; decision of the human owner
(2026-11-07): do not write a Jinja engine in sqll; decide with data how
sqll supports Jinja; sqll passes 100% of the Jinja cases that the decision
keeps, and S8 (code generation: types of query parameters and result
columns as JSON Schema; the JSON Schema output is valid and correct for
each parameter style, code made from the schema by one existing tool
compiles, and the harness shows one parse for each file when one command
lints and generates code) supports Jinja if kept; each other Jinja case is
in a known-failure list with its reason)). The Core track (the track that
does S3b and owns the shared core) approved it in review round W1 (PR
comment 6829565360). The design is in the design record, "Known failures",
"Summary", and "CI".

- CI: 9 `s7` jobs (`ci/matrix.d/S7-tests.json`: `s7_rules`, `s7_config`,
  and `s7_cli`, each with sqlfluff, sqlfluff-rs, and sqruff), and the
  `s7-report` job: the merge of the 9 reports, the known-failure check, the
  check of the recorded summary, and the trace oracle on the merged report.
- A new failure that is not in a known-failure list, and a listed node that
  passes, give exit code 1 in its `s7` job and in `s7-report`.
- The lint job runs ruff on `scripts/s7-tests/` and on each S7 script with
  no extension.
- `scripts/verify` runs the same checks on one run of all suites and tools;
  `scripts/verify --s7` runs only the S7 checks. Each mode but `--quick`
  takes the machine lock (PROCESS.md, "Tracks", rule 7).
- Recorded results: [summary.json](../results/S7-tests/summary.json) and
  the known-failure lists in
  [known_failures/](../results/S7-tests/known_failures/).

The known failures of each tool are in "Recorded results".

## Rule tests, part 1 (T6)

T6 (convert the rule tests, part 1, the simple-API nodes; goal: the rule
nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are black-box
cases) of S7 (CLI and config parity: the sqlfluff CLI, config, and Python rule
tests as black-box cases; sqll passes 100% of the converted cases;
cases that need the Jinja templater move to S11
(Jinja templater: the last stone; decision of the human owner (2026-11-07):
do not write a Jinja engine in sqll; decide with data how sqll supports
Jinja; sqll passes 100% of the Jinja cases that the decision keeps, and S8
(code generation: types of query parameters and result columns as JSON
Schema; the JSON Schema output is valid and correct for each parameter
style, code made from the schema by one existing tool compiles, and the
harness shows one parse for each file when one command lints and generates
code) supports Jinja if kept; each other Jinja case is in a known-failure
list with its reason)) converted 23 rule nodes and excluded 1 node (PR
#96).

| Source file | Converted in T6 | Excluded in T6 | Not converted yet | Goal of T6 |
|---|---|---|---|---|
| `std_AL04_test.py` | 2 (the pilot has the third node) | 0 | 0 | The rule nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are black-box cases |
| `std_AM06_test.py` | 3 | 0 | 0 | The rule nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are black-box cases |
| `std_AM09_test.py` | 4 | 1 `python-internal` | 0 | The rule nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are black-box cases |
| `std_LT01_LT04_test.py` | 1 | 0 | 0 | The rule nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are black-box cases |
| `std_RF02_test.py` | 1 | 0 | 0 | The rule nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are black-box cases |
| `std_LT02_LT11_combo_test.py` | 2 | 0 | 0 | The rule nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are black-box cases |
| `std_LT01_LT02_LT09_combo_test.py` | 1 | 0 | 0 | The rule nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are black-box cases |
| `std_LT05_LT09_combo_test.py` | 2 (the pilot has the third node) | 0 | 0 | The rule nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are black-box cases |
| `std_ST12_test.py` | 6 | 0 | 2 | The rule nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are black-box cases |
| `std_LT03_test.py` | 1 | 0 | 2 | The rule nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are black-box cases |

- Each case is an `api` case: `lint` or `fix` with the `sql`, `rules`, and
  `exclude_rules` of the source call. The trace oracle maps each call.
- A loop or a chain of calls in the source gives one case for each call:
  `test__rules__std_ST12_basic_patterns` has 6 cases, and
  `test__rules__std_ST12_fix_functionality` has 2 (fix, then lint the
  fixed SQL).
- 2 checks are stronger than their asserts. The case file gives the
  reason. `test__rules__std_ST12_complex_multistatement`: the records give
  the 7 positions of sqlfluff 4.4.0; the source checks only that the 7
  positions are different. `test__rules__std_ST12_fix_functionality`: the
  check gives the exact fixed SQL of sqlfluff 4.4.0; the source checks
  that the SQL changed and has fewer semicolons, and the second call lints
  this fixed SQL.
- The excluded node,
  `test__rules__std_AM09_eval_short_circuit_on_non_select_segment`, calls
  `Rule_AM09._eval` on a fake segment. The oracle shows that it has no
  traced CLI or simple-API call.
- Not converted in T6 (4 nodes of these files): the 2 `templated_*` nodes of
  `std_ST12_test.py` give a Jinja config to `sqlfluff.lint`, and
  `test__rules__std_LT03_leading` and `test__rules__std_LT03_trailing` call
  `Linter.lint_string_wrapped` with a config. The trace oracle of T6 did not
  map these calls. T16 (trace oracle and case runner, extension 1; goal: the
  trace oracle maps and proves the calls that the remaining rule nodes use,
  and fails closed on each other call; see "Trace oracle, extension 1 (T16)")
  maps them and converts `test__rules__std_LT03_trailing` as a proof node. T7
  (convert the rule tests, part 2; goal: the other rule nodes, not Rust
  dispatch, are black-box cases) of S7 (CLI and config parity: the sqlfluff
  CLI, config, and Python rule tests as black-box cases; sqll passes 100% of
  the converted cases; cases that need the Jinja templater move to the Jinja
  templater stone) converts the other 3.

## Trace oracle, extension 1 (T16)

T16 (trace oracle and case runner, extension 1; goal: the trace oracle
maps and proves the calls that the remaining rule nodes use, and fails
closed on each other call) of S7 (CLI and config parity: the sqlfluff CLI,
config, and Python rule tests as black-box cases; sqll passes 100% of the
converted cases; cases that need the Jinja templater move to the Jinja
templater stone). The design record gives each map and the new limits
("Trace oracle", "Config model", "Limits of the oracle").

- New maps, each to a `cli` case:
  - A Linter string call (`Linter(config=...).lint_string`,
    `lint_string_wrapped`): `lint -f json -` on stdin, and also `fix -`
    if the call fixes, in a `cwd: tmp` case with the config as a
    `.sqlfluff` file. The trace loads that file as the CLI does and proves
    that the config is the config of the Linter.
  - A simple-API call with `config=`: the same map, through its inner
    Linter string call.
  - A Linter path call with a config from overrides: `lint -f json` with
    `--dialect`, `--rules`, and `--exclude-rules`.
  - A CLI call with a path in a temporary folder of the node, or in that
    folder: a `cwd: tmp` case. The files of the folder before the call are
    the case files; the files after the call are the `files` check.
- Fail-closed checks (exit code 1 with a message): a config key that the
  default config does not have, a value that is not a scalar, a path key,
  a config that the file does not give again (for example
  `set_value(["core", "rules"], ...)`), a config change after the Linter
  was made, a Linter render or parse outside each traced call (for example
  `Linter.parse_string`), a Linter method or option that the map does not
  know, a config or ignore file in a temporary folder of a call in the
  sqlfluff root, and 2 temporary folders in one call.
- Proof nodes (2): `test__rules__std_LT03_trailing` (a Linter string call
  with a config) and
  `test__cli__command__fix[LT01-test/fixtures/linter/whitespace_errors.sql]`
  of `std_roundtrip_test.py` (3 CLI calls in a temporary folder). sqlfluff
  and `sqlfluff[rs]` pass both. sqruff fails both with `unsupported`: the
  cases have no sqruff translation.
- The recorded results change only by the 2 proof nodes: the other nodes
  of `report.json` and `oracle.json` do not change. The trace of the
  `python-internal` node
  `test__get_filtered_parse_violations_caches_rulepack_per_config` gets
  `untraced_linter` (it calls `Linter.parse_string`); a `python-internal`
  node can have it, so its oracle result does not change.
- Speed: the oracle run (`scripts/s7-tests/oracle`, 2 tools) took 7.0 s
  before and 6.8 s after (the 2 proof nodes add 4 traced calls). No tool
  code changes, so no benchmark changes.

## Trace oracle, extension 2 (T17)

T17 (trace oracle and case runner, extension 2; goal: the trace oracle maps
and proves the calls of the remaining rule nodes that T16 did not map, and
fails closed on each other call) of S7 (CLI and config parity: the sqlfluff
CLI, config, and Python rule tests as black-box cases; sqll passes 100% of
the converted cases; cases that need the Jinja templater move to the Jinja
templater stone). The design record gives each map and its limits ("Trace
oracle", "Config model", "Limits of the oracle").

- New maps:
  - Linter arguments (`Linter(dialect=..., rules=..., exclude_rules=...)`,
    for example `std_AL09_CP02_RF06_combo_test.py`): the trace proves that
    the config is `FluffConfig(overrides=<the arguments>)`. Then a Linter
    string call gives the `.sqlfluff` file of the config model, and a
    Linter path call gives the lint options, as in T16 (trace oracle and
    case runner, extension 1; goal: the trace oracle maps and proves the
    calls that the remaining rule nodes use, and fails closed on each
    other call).
  - The test helper `assert_rule_raises_violations_in_file` of
    `sqlfluff.utils.testing.rules` (`std_test.py::test__rules__std_file`):
    the trace records the helper call and its one Linter path call; the
    case is that call. The asserts finder gives the helper one id,
    `L<line>:violations`, and still fails closed on each other helper.
  - An error call: an error of `RuleSet.get_rulepack` or of a Linter
    construction outside each traced call (for example in `pytest.raises`,
    `std_test.py::test_improper_configs_are_rejected`). The trace gives the
    config to the CLI and runs `lint -` in process. The oracle maps the
    error to a `cwd: tmp` CLI case (exit code and message) only if that run
    gives the same error first: the same function, exception type, and
    message.
- Fail-closed checks (exit code 1 with a message): a Linter argument other
  than these 3, Linter arguments with a config or with no proof of the
  config, overrides that are not the arguments; a test helper that the map
  does not know, or with another inner call; an error of another function
  (for example of a FluffConfig construction), an error whose config the
  trace cannot give to the CLI, and an error that the CLI run does not give
  first.
- Proof nodes (2): `test__rules__std_AL09_CP02_RF06[rules0-...]` (Linter
  arguments; 3 cases: lint, fix, lint of the fixed SQL) and
  `test_improper_configs_are_rejected[rule_config_dict3]` (an error call;
  exit code 2 and `User Error: Invalid option 'blah' for
  capitalisation_policy configuration.`). sqlfluff and `sqlfluff[rs]` pass
  both, and each agrees with its trace. sqruff fails both with
  `unsupported`: the cases have no sqruff translation.
- The recorded results change only by the 2 proof nodes: the other nodes of
  `report.json` and `oracle.json`, and their traces, do not change.
- Speed: the oracle run (`scripts/s7-tests/oracle`, 2 tools) took 6.8 s
  before and 6.2 s after. A full local `sqll-harness s7 run` (3 suites, 3
  tools) took 12.0 s and 10.8 s before, and 11.2 s and 11.3 s after: the 4
  new cases for each tool are in the noise. No tool code changes, so no
  benchmark changes.

### Plan data (T17)

A trace with the oracle of T17 (trace oracle and case runner, extension 2;
goal: the trace oracle maps and proves the calls of the remaining rule nodes
that T16 did not map, and fails closed on each other call) for sqlfluff
(`trace-nodes`, then `oracle.map_call` on each traced call), on 2026-11-17,
of the 496 nodes that are not converted after T17, not excluded, and not
Rust dispatch nodes. The 2 proof nodes of T17 are not in this set (498
before T17; the `rules` row was then 75 nodes: each call maps 53, no
traced call 3, refused 19; the other rows were the same). Each of the 496
nodes passed in the trace. A node is in 1 column: "each call maps" (each
traced call maps, and the trace has no other error), "no traced call" (the
trace has no traced call), or "refused" (the trace has a traced call, and
the oracle refuses a traced call or the trace has an untraced call or a
process). The column "untraced" is the part of "no traced call" that has an
untraced call.

| Group | Nodes | Each call maps | No traced call | Untraced | Refused |
|---|---|---|---|---|---|
| `rules` | 73 | 51 | 3 | 2 | 19 |
| `config`, `config_fixtures` | 138 | 4 | 129 | 0 | 5 |
| `cli` | 285 | 195 | 55 | 5 | 35 |

- `rules`: the 19 refused nodes need T18 (trace oracle and case runner,
  extension 3; goal: the trace oracle maps and proves the calls of the rule
  nodes that T17 did not map, and fails closed on each other call): a
  config key that the default config does not have (13 nodes: 8
  `align_scope`, 4 Jinja context and delimiters, and 1 error call with the
  `capitalisation_policy` of functions), a fix run with other violations
  than a lint run (4), and a config file in a temporary folder (2). Of the
  3 nodes with no traced call, 2 have an untraced Linter render and parse
  (`python-internal` candidates for T7 (convert the rule tests, part 2;
  goal: the other rule nodes, not Rust dispatch, are black-box cases)), and
  1 has no call.
- `config`: 129 nodes have no traced call: they test FluffConfig in
  Python. The 5 refused nodes: 4 errors of a FluffConfig construction and
  1 simple-API `parse` with a config. T19 (trace oracle and case runner,
  extension 4; goal: the trace oracle maps and proves each config call of
  the config nodes that a CLI command shows, and fails closed on each other
  call) maps the config calls that a CLI command shows; T9 (convert the
  config tests; goal: the 140 nodes of `config` and `config_fixtures` are
  black-box cases or excluded with a class) excludes the others with a
  class.
- `cli`: the 35 refused nodes and the 5 untraced nodes: 21 nodes with an
  untraced CLI command (`Command.main`, `get_config`; 13 of them also with
  Linter path options, 8 with `CliRunner.invoke` arguments that the trace
  cannot read) and 2 untraced nodes with only an untraced `get_config` are
  for T20 (trace oracle and case runner, extension 5; goal: the trace
  oracle maps and proves the CLI calls of the CLI nodes that do not use
  `CliRunner.invoke`, and fails closed on each other call). The other 14
  refused nodes (8 paths in the sqlfluff root and a temporary folder in one
  call, 3 config files in a temporary folder, 2 programs, 1 input file
  that is not UTF-8) are for T21 (trace oracle and case runner, extension
  6; goal: the trace oracle maps and proves the other calls of the CLI
  nodes, and fails closed on each other call). The 3 untraced nodes with an
  untraced Linter render are `python-internal` candidates.
- The same run with the `trace-nodes` of the first review head (before the
  saved CLI state of the error calls) gave the same column for each of the
  498 nodes.

## Recorded results

The recorded results of T17 (trace oracle and case runner, extension 2; goal:
the trace oracle maps and proves the calls of the remaining rule nodes that
T16 did not map, and fails closed on each other call) of S7 (CLI and config
parity: the sqlfluff CLI, config, and Python rule tests as black-box cases;
sqll passes 100% of the converted cases; cases that need the Jinja templater
move to the Jinja templater stone):
[report.json](../results/S7-tests/report.json),
[summary.json](../results/S7-tests/summary.json),
[oracle.json](../results/S7-tests/oracle.json) with the traces, and
[known_failures/](../results/S7-tests/known_failures/). The counts: in scope 643,
converted 42, excluded 4, not yet converted 597. The converted nodes:
`cli` 8, `rules` 32, `config` 2. 1 converted node needs Jinja
(`std_LT04_test.py::test__rules__std_LT04_unparseable`) and moves to S11
(Jinja templater: the last stone; decision of the human owner (2026-11-07):
do not write a Jinja engine in sqll; decide with data how sqll supports
Jinja; sqll passes 100% of the Jinja cases that the decision keeps, and S8
(code generation: types of query parameters and result columns as JSON
Schema; the JSON Schema output is valid and correct for each parameter
style, code made from the schema by one existing tool compiles, and the
harness shows one parse for each file when one command lints and generates
code) supports Jinja if kept; each other Jinja case is in a known-failure
list with its reason). The excluded nodes: 2
`python-internal`, 1 `needs-python-runtime`, 1 `engine-comparison`.

Parity of the 41 converted nodes that S7 (CLI and config parity: the sqlfluff
CLI, config, and Python rule tests as black-box cases; sqll passes 100% of the
converted cases; cases that need the Jinja templater move to the Jinja
templater stone) keeps (nodes):

| Tool | Nodes | Passed | Failed | Error |
|---|---|---|---|---|
| sqlfluff | 41 | 41 | 0 | 0 |
| sqlfluff-rs | 41 | 40 | 1 | 0 |
| sqruff | 41 | 8 | 33 | 0 |

- sqlfluff-rs: `test__cli__command_directed` fails. With
  `use_rust_rules`, the CP01 description is "Keywords must be consistent."
  and not "Keywords must be consistently upper case.".
- sqruff: 31 nodes fail with `unsupported: <item>`: 12 CLI nodes with no
  sqruff translation of the command (4 of them the proof nodes of the
  trace oracle extensions 1 and 2),
  18 `rule all`, and 1 output fields.
  2 translated CLI nodes fail on the output: `test__cli__command_directed`
  (sqruff writes the lint output to stderr, not to stdout) and
  `test__cli__command_dialect` (exit code 1, not 2). sqruff passes the 8
  rule nodes whose source call gives `rules`: `std_CV02`, `std_LT01_LT04`,
  and the 6 converted nodes of `std_ST12`.

Results of each suite with each tool. The parity columns count the converted
nodes that S7 (CLI and config parity: the sqlfluff CLI, config, and Python
rule tests as black-box cases; sqll passes 100% of the converted cases; cases
that need the Jinja templater move to the Jinja templater stone) keeps
(passed/nodes):

| Suite | In scope | Converted | Excluded | sqlfluff | sqlfluff-rs | sqruff |
|---|---|---|---|---|---|---|
| `s7_rules` | 208 | 32 | 2 | 31/31 | 31/31 | 8/31 |
| `s7_config` | 140 | 2 | 0 | 2/2 | 2/2 | 0/2 |
| `s7_cli` | 295 | 8 | 2 | 8/8 | 7/8 | 0/8 |

Trace oracle (`results/S7-tests/oracle.json`):

| Tool | Nodes | Agree | Pass | Fail | Asserts | Not reproduced | `python-internal` |
|---|---|---|---|---|---|---|---|
| sqlfluff | 42 | 42 | 42 | 0 | 97 | 0 | 2 |
| sqlfluff-rs | 42 | 42 | 41 | 1 | 97 | 0 | 2 |

- Each of the 42 converted nodes agrees with its trace, with sqlfluff and
  with `sqlfluff[rs]`. The 1 sqlfluff-rs failure is
  `test__cli__command_directed`: the pytest node fails too.
- Each of the 97 asserts of the converted source tests has a check that
  cites it. No case uses a row of
  [s7-tests-not-reproduced.md](../docs/decisions/s7-tests-not-reproduced.md).

Known failures (nodes):

| Tool | Known failures | Reason |
|---|---|---|
| sqlfluff | 0 | sqlfluff passes each converted node |
| sqlfluff-rs | 1 | `test__cli__command_directed`: with `use_rust_rules`, the CP01 description is different; the pytest node fails with `--rust` too |
| sqruff | 34 | 32 `unsupported: <item>`: 12 CLI nodes with no sqruff translation of the command, 19 `rule all`, 1 output fields. 2 translated CLI nodes fail on the output: `test__cli__command_directed` (the lint output is on stderr) and `test__cli__command_dialect` (exit code 1, not 2). 1 of the 34 (`test__rules__std_LT04_unparseable`) needs Jinja and moves to S11 (Jinja templater: the last stone; decision of the human owner (2026-11-07): do not write a Jinja engine in sqll; decide with data how sqll supports Jinja; sqll passes 100% of the Jinja cases that the decision keeps, and S8 (code generation: types of query parameters and result columns as JSON Schema; the JSON Schema output is valid and correct for each parameter style, code made from the schema by one existing tool compiles, and the harness shows one parse for each file when one command lints and generates code) supports Jinja if kept; each other Jinja case is in a known-failure list with its reason) |
