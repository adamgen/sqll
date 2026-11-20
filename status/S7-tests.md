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
- State: in work. 12 of the 22 tasks of S7 (CLI and config parity: the sqlfluff
  CLI, config, and Python rule tests as black-box cases; sqll passes 100% of
  the converted cases; cases that need the Jinja templater move to the Jinja
  templater stone) are done, and 1 is in review. These 12 tasks are merged (the
  last on 2026-11-20, PR #112):
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
  - T17 (trace oracle and case runner, extension 2; goal: the trace oracle
    maps and proves the calls of the remaining rule nodes that T16 did not
    map, and fails closed on each other call), PR #101.
  - T7 (convert the rule tests, part 2; goal: the other rule nodes, not Rust
    dispatch and not Jinja, are black-box cases), PR #105.
  - T18 (convert the rule tests, part 3, the Jinja rule nodes; goal: each rule
    node that needs the Jinja templater is a black-box case marked for the
    Jinja templater stone), PR #109.
  - T8 (Rust dispatch tests cp01, cp03, cp04: classification and conversion;
    goal: each Rust dispatch node is converted or excluded by decision 3), PR
    #110.
  - T22 (convert the rule tests, part 3; goal: each other rule node, not Rust
    dispatch, is a black-box case or is excluded with a class), PR #112.

  T19 (trace oracle and case runner, extension 4; goal: the trace oracle maps
  and proves each config call of the config nodes that a CLI command shows,
  and fails closed on each other call) is in review (PR #115). The other 9
  tasks are not started. The table "S7-tests tasks" gives each task
  with its goal, in the order of the plan.
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
cases; cases that need the Jinja templater move to the Jinja templater stone).
Plan of 2026-11-11: to recover one lost day, T9 (convert the config tests;
goal: the 140 nodes of `config` and `config_fixtures` are black-box cases or
excluded with a class) converts all config tests (before: 2 tasks). The
orchestrator added T16 (trace oracle and case runner, extension 1; goal: the
trace oracle maps and proves the calls that the remaining rule nodes use, and
fails closed on each other call) on 2026-11-15, before T7 (convert the rule
tests, part 2; goal: the other rule nodes, not Rust dispatch and not Jinja,
are black-box cases): the rule nodes of T7 use calls that the trace oracle did
not map. The orchestrator added T17 (trace oracle and case runner, extension
2; goal: the trace oracle maps and proves the calls of the remaining rule
nodes that T16 did not map, and fails closed on each other call) on 2026-11-17
for the calls that T16 refuses. T17 added 4 tasks to the plan (2026-11-17),
each before the conversion task that needs it, from the data of "Plan data
(T17)":

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

The orchestrator gave T7 (convert the rule tests, part 2; goal: the other rule
nodes, not Rust dispatch and not Jinja, are black-box cases) its scope on
2026-11-17: the rule nodes of 14 source files, with the maps of T16 and T17,
and not the Jinja rule nodes. Thus T7 comes before T18 now. T7 added 1 task to
the plan (2026-11-17), from the data of "Rule tests, part 2 (T7)":

- T22 (convert the rule tests, part 3; goal: each other rule node, not Rust
  dispatch, is a black-box case or is excluded with a class): the 7 nodes that
  T7 did not convert, and the 15 Jinja rule nodes. It needs the maps of T18.

The orchestrator gave T18 a new scope on 2026-11-17: T18 (convert the rule
tests, part 3, the Jinja rule nodes; goal: each rule node that needs the Jinja
templater is a black-box case marked for the Jinja templater stone) converts
the 15 Jinja rule nodes and the 2 `test__cli__command__fix_templated` nodes,
with the maps of the trace oracle that these nodes need (the Jinja context
and delimiters, the keys of a layout type, and a config file in a temporary
folder of a CLI call in the sqlfluff root). Thus T22 (convert the rule tests,
part 3; goal: each other rule node, not Rust dispatch, is a black-box case or
is excluded with a class) has the other 5 rule nodes, with the 2 maps that
they need (the `capitalisation_policy` of functions, and a fix run whose
violations are not those of a lint run); see "Rule tests, part 3, the Jinja
rule nodes (T18)".

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
| T17 | Trace oracle and case runner, extension 2: Linter arguments `dialect`, `rules`, and `exclude_rules`; the test helper `assert_rule_raises_violations_in_file`; an error of `RuleSet.get_rulepack` or of a Linter construction that the CLI gives; at most 2 proof nodes | The trace oracle maps and proves the calls of the remaining rule nodes that T16 did not map, and fails closed on each other call | Done (PR #101) |
| T7 | Convert the rule tests, part 2: the rule nodes of 14 source files that are not simple-API nodes, not Rust dispatch, and not Jinja nodes (for example the nodes that give a config, or that call `Linter`); it uses the maps of T16 and T17 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases | Done (PR #105) |
| T18 | Convert the rule tests, part 3, the Jinja rule nodes: `std_JJ01_test.py` (5), `std_LT01_jinja_alignment_test.py` (8), the 2 `templated_*` nodes of `std_ST12_test.py`, and the 2 `test__cli__command__fix_templated` nodes of `std_roundtrip_test.py`; with the maps that they need: the extra keys of the config model (the Jinja context and delimiters, the keys of a layout type) and a config file in a temporary folder of a CLI call in the sqlfluff root | Each rule node that needs the Jinja templater is a black-box case marked for the Jinja templater stone | Done (PR #109) |
| T22 | Convert the rule tests, part 3: the 5 other rule nodes that the oracle refuses (`test_improper_configs_are_rejected[rule_config_dict7]` and 4 `test__rules__std_AL09_CP02_RF06` nodes), with the 2 maps that they need: the `capitalisation_policy` of functions (a key that the default config does not have), and a fix run whose violations are not those of a lint run | Each other rule node, not Rust dispatch, is a black-box case or is excluded with a class | Done (PR #112) |
| T8 | Rust dispatch tests (cp01, cp03, cp04): classification and conversion; with the maps that the nodes need: an error of `FluffConfig.from_string` that the CLI shows, a mock or spy node as `python-internal`, and a case that sets each key of the `sqlfluff-rs` layer | Each Rust dispatch node is converted or excluded by decision 3 | Done (PR #110) |
| T19 | Trace oracle and case runner, extension 4: the config calls of the `config` and `config_fixtures` nodes (FluffConfig loaders and errors) that a CLI command shows | The trace oracle maps and proves each config call of the config nodes that a CLI command shows, and fails closed on each other call | In review (PR #115) |
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

T4 (cross-track task: harness hooks for the S7 suites; the harness core runs
the 3 S7 suites `s7_rules`, `s7_config`, `s7_cli`) is merged (PR #82,
2026-11-11). Its stone is S7 (CLI and config parity: the sqlfluff CLI, config,
and Python rule tests as black-box cases; sqll passes 100% of the converted
cases; cases that need the Jinja templater move to S11 (Jinja templater: the
last stone; decision of the human owner (2026-11-07): do not write a Jinja
engine in sqll; decide with data how sqll supports Jinja; sqll passes 100% of
the Jinja cases that the decision keeps, and S8 (code generation: types of
query parameters and result columns as JSON Schema; the JSON Schema output is
valid and correct for each parameter style, code made from the schema by one
existing tool compiles, and the harness shows one parse for each file when one
command lints and generates code) supports Jinja if kept; each other Jinja
case is in a known-failure list with its reason)). The Core track (the track
that does S3b and owns the shared core; S3b (core: the shared syntax tree,
source map, frozen interfaces, and the sqll binary skeleton (CLI, config,
output) with the sqll adapters of the test harness and the benchmarks; the
test harness and the benchmarks run sqll through its adapters, the interfaces
are documented, and after S3b, each change to the core goes through the Core
track)) approved it. It added `sqll-harness s7 run [--suite S] [--tool T]`.
This command replaces `scripts/s7-tests/run-cases`. The design is in the
design record, "Case runner" and "Report".

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
suites; CI and `scripts/verify` run the S7 suites and record the results) is
merged (PR #83, 2026-11-12). Its stone is S7 (CLI and config parity: the
sqlfluff CLI, config, and Python rule tests as black-box cases; sqll passes
100% of the converted cases; cases that need the Jinja templater move to S11
(Jinja templater: the last stone; decision of the human owner (2026-11-07): do
not write a Jinja engine in sqll; decide with data how sqll supports Jinja;
sqll passes 100% of the Jinja cases that the decision keeps, and S8 (code
generation: types of query parameters and result columns as JSON Schema; the
JSON Schema output is valid and correct for each parameter style, code made
from the schema by one existing tool compiles, and the harness shows one parse
for each file when one command lints and generates code) supports Jinja if
kept; each other Jinja case is in a known-failure list with its reason)). The
Core track (the track that does S3b and owns the shared core; S3b (core: the
shared syntax tree, source map, frozen interfaces, and the sqll binary
skeleton (CLI, config, output) with the sqll adapters of the test harness and
the benchmarks; the test harness and the benchmarks run sqll through its
adapters, the interfaces are documented, and after S3b, each change to the
core goes through the Core track)) approved it in review round W1 (PR comment
6829565360). The design is in the design record, "Known failures", "Summary",
and "CI".

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
  dispatch and not Jinja, are black-box cases) of S7 (CLI and config parity:
  the sqlfluff CLI, config, and Python rule tests as black-box cases; sqll
  passes 100% of the converted cases; cases that need the Jinja templater move
  to the Jinja templater stone) converts `test__rules__std_LT03_leading`. T22
  (convert the rule tests, part 3; goal: each other rule node, not Rust
  dispatch, is a black-box case or is excluded with a class) has the 2 Jinja
  nodes of `std_ST12_test.py`.

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
  goal: the other rule nodes, not Rust dispatch and not Jinja, are black-box
  cases)), and
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

## Rule tests, part 2 (T7)

T7 (convert the rule tests, part 2; goal: the other rule nodes, not Rust
dispatch and not Jinja, are black-box cases) of S7 (CLI and config parity: the
sqlfluff CLI, config, and Python rule tests as black-box cases; sqll passes
100% of the converted cases; cases that need the Jinja templater move to the
Jinja templater stone) converts 49 rule nodes, excludes 2 nodes, and does not
convert 7 nodes of its 14 source files (58 nodes that were not converted or
excluded before T7).

| Source file | Converted in T7 | Excluded in T7 | Not converted | Goal of T7 |
|---|---|---|---|---|
| `std_test.py` | 23 (T17 (trace oracle and case runner, extension 2; goal: the trace oracle maps and proves the calls of the remaining rule nodes that T16 did not map, and fails closed on each other call) converted 1 more) | 0 | 1 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| `std_AL09_CP02_RF06_combo_test.py` | 5 (T17 (trace oracle and case runner, extension 2; goal: the trace oracle maps and proves the calls of the remaining rule nodes that T16 did not map, and fails closed on each other call) converted 1 more) | 0 | 4 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| `std_LT04_ST06_test.py` | 6 | 1 `python-internal` | 0 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| `std_roundtrip_test.py` | 5 (T16 (trace oracle and case runner, extension 1; goal: the trace oracle maps and proves the calls that the remaining rule nodes use, and fails closed on each other call) converted 1 more) | 0 | 2 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| `std_LT03_test.py` | 1 (T6 (convert the rule tests, part 1: the simple-API nodes; goal: the rule nodes that call only `sqlfluff.lint` and `sqlfluff.fix` are black-box cases) and T16 (trace oracle and case runner, extension 1; goal: the trace oracle maps and proves the calls that the remaining rule nodes use, and fails closed on each other call) converted 2 more) | 0 | 0 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| `std_CV09_test.py` | 1 | 0 | 0 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| `std_LT01_ST02_test.py` | 1 | 0 | 0 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| `std_LT02_LT04_test.py` | 1 | 0 | 0 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| `std_LT02_oscillation_test.py` | 1 | 0 | 0 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| `std_LT12_CV06_test.py` | 1 | 0 | 0 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| `std_RF01_LT09_test.py` | 1 | 0 | 0 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| `std_ST05_LT08_test.py` | 1 | 0 | 0 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| `std_ST05_LT09_test.py` | 2 | 0 | 0 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| `yaml_test_cases_test.py` (`test__rule_test_global_config`; S1 (binary test harness: run the sqlfluff test fixtures through a binary, not through function calls; sqlfluff passes 100% of the cases through the harness, and the results of the other tools are recorded) has the other nodes) | 0 | 1 `python-internal` | 0 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |
| Total | 49 | 2 | 7 | The other rule nodes, not Rust dispatch and not Jinja, are black-box cases |

- Data: a trace (`trace-nodes`, then `oracle.map_call` on each traced call)
  of the 58 nodes with sqlfluff and with `sqlfluff[rs]`, on 2026-11-17. Each
  node passed in both traces, and each node has the same column in both.
- The cases use the maps of T16 (trace oracle and case runner, extension 1;
  goal: the trace oracle maps and proves the calls that the remaining rule
  nodes use, and fails closed on each other call) and T17 (trace oracle and
  case runner, extension 2; goal: the trace oracle maps and proves the calls
  of the remaining rule nodes that T16 did not map, and fails closed on each
  other call): the test helper (`test__rules__std_file`, 17 nodes: `lint -f
  json --dialect ansi --rules <rule> <fixture>` in the sqlfluff root; the
  fixtures are read in place), error calls (6 nodes), Linter string calls
  with a config or with Linter arguments (20 nodes), and CLI calls in a
  temporary folder (5 nodes). Each case file has the source header (sqlfluff
  4.4.0, file, node, MIT).
- 2 converted nodes need Jinja (their SQL has Jinja tags) and move to S11
  (Jinja templater: the last stone; decision of the human owner (2026-11-07):
  do not write a Jinja engine in sqll; decide with data how sqll supports
  Jinja; sqll passes 100% of the Jinja cases that the decision keeps, and S8
  (code generation: types of query parameters and result columns as JSON
  Schema; the JSON Schema output is valid and correct for each parameter
  style, code made from the schema by one existing tool compiles, and the
  harness shows one parse for each file when one command lints and generates
  code) supports Jinja if kept; each other Jinja case is in a known-failure
  list with its reason):
  `std_test.py::test__rules__std_file[JJ01-heavy_templating.sql-violations16]`
  and `std_LT02_oscillation_test.py::test_rules_std_LT02_loop_comma_no_oscillation`.
- Checks that are stronger than their asserts (the case file gives the
  reason): the codes of the violations in the order of the lint output, where
  the source checks a set of codes; the records of the test helper cases in
  the order of the lint output, where the helper checks a set.
- Excluded (`python-internal`, `exclusions.yml`):
  `test_rule_st06_simple_expression_helpers_reject_non_simple_segments`
  (it calls `Linter.parse_string` and 2 helper methods of `Rule_ST06`; the
  trace has no traced call, only an untraced Linter render and parse) and
  `test__rule_test_global_config` (it calls the test helper
  `load_test_cases` on a YAML file; the trace has no call).
- Not converted (7 nodes). The oracle refuses a call of each. T22 (convert
  the rule tests, part 3; goal: each other rule node, not Rust dispatch, is a
  black-box case or is excluded with a class) converts them after T18 (trace
  oracle and case runner, extension 3; goal: the trace oracle maps and proves
  the calls of the rule nodes that T17 did not map, and fails closed on each
  other call) maps the calls:
  - `std_test.py::test_improper_configs_are_rejected[rule_config_dict7]`:
    the error call of `RuleSet.get_rulepack(config)`. The config model does
    not have the key `rules:capitalisation.functions:capitalisation_policy`.
  - `std_AL09_CP02_RF06_combo_test.py::test__rules__std_AL09_CP02_RF06`,
    nodes `rules3`, `rules6`, `rules7`, and `rules8`: the call
    `Linter(dialect=..., rules=...).lint_string(sql, fix=True)`. The
    violations of the fix run are not the violations of a lint run.
  - `std_roundtrip_test.py::test__cli__command__fix_templated[CP01]` and
    `[LT01]`: 3 calls of `CliRunner.invoke` (lint, fix, lint) with a path in
    a temporary folder that has a `.sqlfluff` file, in the sqlfluff root.
    The SQL has Jinja tags.
- Not in the scope of T7 (the Jinja rule nodes, 15 nodes). T18 (convert the
  rule tests, part 3, the Jinja rule nodes; goal: each rule node that needs
  the Jinja templater is a black-box case marked for the Jinja templater
  stone) has them and the 2 `test__cli__command__fix_templated` nodes; T22
  has the other 5 nodes above.
  With the oracle of T17: `std_LT01_jinja_alignment_test.py` 8 nodes (refused:
  the config key `align_scope`), `std_JJ01_test.py` 5 nodes (4 refused: the
  Jinja context and delimiters; `test_lint_jj01_pickled_config` has no traced
  call, only an untraced Linter render and parse), and the 2 `templated_*`
  nodes of `std_ST12_test.py` (each call maps).
- Asserts: each of the 87 asserts of the 49 converted nodes has a check that
  cites it. No case uses a row of
  [s7-tests-not-reproduced.md](../docs/decisions/s7-tests-not-reproduced.md).
- Speed: a full local `sqll-harness s7 run` (3 suites, 3 tools) took 11.2 s
  and 11.3 s before T7 (T17 data), and 35.0 s after: the 49 nodes add 87
  cases for each tool, and most are CLI runs. The oracle run (2 tools) took
  6.2 s before (T17 data) and 16.2 s after. No tool code changes, so no
  benchmark changes.

## Rule tests, part 3, the Jinja rule nodes (T18)

T18 (convert the rule tests, part 3, the Jinja rule nodes; goal: each rule
node that needs the Jinja templater is a black-box case marked for the Jinja
templater stone) of S7 (CLI and config parity: the sqlfluff CLI, config, and
Python rule tests as black-box cases; sqll passes 100% of the converted cases;
cases that need the Jinja templater move to the Jinja templater stone)
converts 15 nodes and excludes 2 nodes of its 17 nodes. 13 converted nodes
need Jinja and move to S11 (Jinja templater: the last stone; decision of the human owner
(2026-11-07): do not write a Jinja engine in sqll; decide with data how sqll
supports Jinja; sqll passes 100% of the Jinja cases that the decision keeps,
and S8 (code generation: types of query parameters and result columns as JSON
Schema; the JSON Schema output is valid and correct for each parameter style,
code made from the schema by one existing tool compiles, and the harness shows
one parse for each file when one command lints and generates code) supports
Jinja if kept; each other Jinja case is in a known-failure list with its
reason).

| Source file | Converted in T18 | Needs Jinja | Excluded in T18 | Goal of T18 |
|---|---|---|---|---|
| `std_JJ01_test.py` | 4 | 4 | 1 `python-internal` | Each rule node that needs the Jinja templater is a black-box case marked for the Jinja templater stone |
| `std_LT01_jinja_alignment_test.py` | 7 | 5 | 1 `needs-python-runtime` | Each rule node that needs the Jinja templater is a black-box case marked for the Jinja templater stone |
| `std_ST12_test.py` (`templated_*`) | 2 | 2 | 0 | Each rule node that needs the Jinja templater is a black-box case marked for the Jinja templater stone |
| `std_roundtrip_test.py` (`test__cli__command__fix_templated`) | 2 | 2 | 0 | Each rule node that needs the Jinja templater is a black-box case marked for the Jinja templater stone |
| Total | 15 | 13 | 2 | Each rule node that needs the Jinja templater is a black-box case marked for the Jinja templater stone |

- Data: a trace (`trace-nodes`, then `oracle.map_call` on each traced call)
  of the 17 nodes with sqlfluff and with `sqlfluff[rs]`, on 2026-11-17. Each
  node passed in both traces. Each mapped case has the same inputs in both
  traces. With the oracle of T17 (trace oracle and case runner, extension 2;
  goal: the trace oracle maps and proves the calls of the remaining rule nodes
  that T16 did not map, and fails closed on each other call), the oracle
  refused 14 nodes: the Jinja context and delimiters (4), the key
  `align_scope` (8), and the `.sqlfluff` file in the temporary folder of a
  CLI call in the sqlfluff root (2).
- New maps (the design record, "Trace oracle", "Config model", and "Limits
  of the oracle"):
  - Extra keys of the config model (`EXTRA_KEYS` of
    `scripts/s7-tests/s7config.py`): each key of the Jinja context
    (`[sqlfluff:templater:jinja:context]`), the 6 Jinja delimiters, and the 9
    keys of a layout type (`ALLOWABLE_LAYOUT_CONFIG_KEYS` of sqlfluff). The
    proof (the CLI loads the `.sqlfluff` file as the same config) checks each
    value. Each other key that the default config does not have is still an
    error.
  - A CLI call in the sqlfluff root with a config or ignore file in its
    temporary folder: the trace runs the call again in a copy of the folder,
    with the copy as the working folder (`cwd_outputs`). The oracle maps the
    call to its `cwd: tmp` case only if that run gives each output of the
    call (exit code, stdout, stderr, files, exception). Thus a config key
    that the CLI reads only from the working folder fails closed: a test tree
    node with `output_line_length = 30` in the folder gives other stdout and
    is refused.
- Fail-closed tests: the config model test (each extra key maps; another
  Jinja key, the context of another templater, a nested context key, another
  layout key, a Python function in the context, and a text that loads as a
  number are errors), a third test tree for `trace-nodes` (3 maps and 3
  refusals), and the oracle script on the recorded traces (exit code 1 for a
  changed Jinja context, layout key, or folder config file, and for a missing
  run in the folder, an error of it, or other outputs of it). The T16 test
  tree node `test_tmp_config` now maps with a case.
- needs_jinja: the SQL of each Jinja node has Jinja tags, or its config gives
  Jinja delimiters. The 2 nodes
  `test_lt01_alias_alignment_edge_case_no_segments_on_line` and
  `test_lt01_alias_alignment_target_segment_not_found` have no Jinja tag and
  no Jinja key in the SQL or the config: they do not need Jinja, and S7
  keeps them (`needs_jinja: false`).
- Excluded (`exclusions.yml`):
  - `test_lint_jj01_pickled_config` (`python-internal`): it calls
    `Linter.parse_path` and `Rule.crawl` with a pickled config. The trace has
    no traced call, only an untraced Linter render and parse; the oracle
    checks the class.
  - `test_lt01_alias_alignment_with_jinja_uses_source_positions`
    (`needs-python-runtime`, G1.3): its Jinja context has 2 Python functions
    (`generate_surrogate_key` and `ref`). A config file cannot give a Python
    function; the config model refuses it (not a scalar). It is a Jinja node:
    S11 (Jinja templater: the last stone; decision of the human owner
(2026-11-07): do not write a Jinja engine in sqll; decide with data how sqll
supports Jinja; sqll passes 100% of the Jinja cases that the decision keeps,
and S8 (code generation: types of query parameters and result columns as JSON
Schema; the JSON Schema output is valid and correct for each parameter style,
code made from the schema by one existing tool compiles, and the harness shows
one parse for each file when one command lints and generates code) supports
Jinja if kept; each other Jinja case is in a known-failure list with its
reason) decides if sqll supports it.
- Checks that are stronger than their asserts (the case file gives the
  reason): the exact fixed SQL of each LT01 fix case (the source checks the
  lines of the fixed SQL), the exact fixed file of the
  `test__cli__command__fix_templated` fix case (the source checks the Jinja
  tags of the file), and the exit code of each lint case.
- Asserts: each of the 29 asserts of the 15 converted nodes has a check that
  cites it. No case uses a row of
  [s7-tests-not-reproduced.md](../docs/decisions/s7-tests-not-reproduced.md).

The 13 converted nodes that need Jinja and move to S11 (Jinja templater: the last stone; decision of the human owner
(2026-11-07): do not write a Jinja engine in sqll; decide with data how sqll
supports Jinja; sqll passes 100% of the Jinja cases that the decision keeps,
and S8 (code generation: types of query parameters and result columns as JSON
Schema; the JSON Schema output is valid and correct for each parameter style,
code made from the schema by one existing tool compiles, and the harness shows
one parse for each file when one command lints and generates code) supports
Jinja if kept; each other Jinja case is in a known-failure list with its
reason):

| Node | Goal of S11 |
|---|---|
| `std_JJ01_test.py::test_lint_jj01_custom_delimiters` | Jinja templater (the last stone): sqll passes 100% of the Jinja cases that the decision of the human owner keeps; each other Jinja case is in a known-failure list with its reason |
| `std_JJ01_test.py::test_lint_jj01_mixed_custom_and_default_delimiters` | Jinja templater (the last stone): sqll passes 100% of the Jinja cases that the decision of the human owner keeps; each other Jinja case is in a known-failure list with its reason |
| `std_JJ01_test.py::test_lint_jj01_custom_block_delimiters` | Jinja templater (the last stone): sqll passes 100% of the Jinja cases that the decision of the human owner keeps; each other Jinja case is in a known-failure list with its reason |
| `std_JJ01_test.py::test_lint_jj01_partial_delimiter_override` | Jinja templater (the last stone): sqll passes 100% of the Jinja cases that the decision of the human owner keeps; each other Jinja case is in a known-failure list with its reason |
| `std_LT01_jinja_alignment_test.py::test_lt01_alias_alignment_with_jinja_coordinate_space_config_key` | Jinja templater (the last stone): sqll passes 100% of the Jinja cases that the decision of the human owner keeps; each other Jinja case is in a known-failure list with its reason |
| `std_LT01_jinja_alignment_test.py::test_lt01_alias_alignment_non_rendered_longer_than_template` | Jinja templater (the last stone): sqll passes 100% of the Jinja cases that the decision of the human owner keeps; each other Jinja case is in a known-failure list with its reason |
| `std_LT01_jinja_alignment_test.py::test_lt01_alias_alignment_source_coordinate_space_explicit` | Jinja templater (the last stone): sqll passes 100% of the Jinja cases that the decision of the human owner keeps; each other Jinja case is in a known-failure list with its reason |
| `std_LT01_jinja_alignment_test.py::test_lt01_alias_alignment_templated_next_segment` | Jinja templater (the last stone): sqll passes 100% of the Jinja cases that the decision of the human owner keeps; each other Jinja case is in a known-failure list with its reason |
| `std_LT01_jinja_alignment_test.py::test_lt01_alias_alignment_templated_siblings` | Jinja templater (the last stone): sqll passes 100% of the Jinja cases that the decision of the human owner keeps; each other Jinja case is in a known-failure list with its reason |
| `std_ST12_test.py::test__rules__std_ST12_templated_loop_no_false_positive` | Jinja templater (the last stone): sqll passes 100% of the Jinja cases that the decision of the human owner keeps; each other Jinja case is in a known-failure list with its reason |
| `std_ST12_test.py::test__rules__std_ST12_templated_consecutive_semicolons_detected` | Jinja templater (the last stone): sqll passes 100% of the Jinja cases that the decision of the human owner keeps; each other Jinja case is in a known-failure list with its reason |
| `std_roundtrip_test.py::test__cli__command__fix_templated[CP01]` | Jinja templater (the last stone): sqll passes 100% of the Jinja cases that the decision of the human owner keeps; each other Jinja case is in a known-failure list with its reason |
| `std_roundtrip_test.py::test__cli__command__fix_templated[LT01]` | Jinja templater (the last stone): sqll passes 100% of the Jinja cases that the decision of the human owner keeps; each other Jinja case is in a known-failure list with its reason |

- Speed: `scripts/verify --s7` (machine lock) gives `s7-run` 31.3 s and
  `s7-oracle` 16.1 s; at T7 (PR #105) they were 27.5 s and 13.1 s. The 15
  nodes add 26 cases for each tool, and the trace runs 6 CLI calls again in
  their folder. No tool code changes, so no benchmark changes; the pull
  request gives the `bench compare` result.

## Rust dispatch tests (T8)

T8 (Rust dispatch tests cp01, cp03, cp04: classification and conversion;
goal: each Rust dispatch node is converted or excluded by decision 3) of S7
(CLI and config parity: the sqlfluff CLI, config, and Python rule tests as
black-box cases; sqll passes 100% of the converted cases; cases that need the
Jinja templater move to the Jinja templater stone) converts 1 node and
excludes 100 nodes of its 101 nodes. The pilot of T2 (case format, case
runner, and pilot cases; goal: one case format and one runner run pilot cases
through a tool binary) excluded the 102nd node
(`test__cp01_dispatch__ignore_words_parity`); T8 gives its reason the S1 data
too.

| Source file | Nodes | Converted | `engine-comparison` | `python-internal` | Goal of T8 |
|---|---|---|---|---|---|
| `cp01_rust_dispatch_test.py` | 39 | 1 | 35 (1 by T2) | 3 | Each Rust dispatch node is converted or excluded by decision 3 |
| `cp03_rust_dispatch_test.py` | 39 | 0 | 36 | 3 | Each Rust dispatch node is converted or excluded by decision 3 |
| `cp04_rust_dispatch_test.py` | 24 | 0 | 21 | 3 | Each Rust dispatch node is converted or excluded by decision 3 |
| Total | 102 | 1 | 92 | 9 | Each Rust dispatch node is converted or excluded by decision 3 |

The data of decision 3 for each excluded group (`exclusions.yml` gives each
node with its reason of one line; the S1 counts are of the pinned sqlfluff
4.4.0 fixtures in `test/fixtures/rules/std_rule_cases/`). S1 (binary test
harness: run the sqlfluff test fixtures through a binary, not through function
calls; sqlfluff passes 100% of the cases through the harness, and the results
of the other tools are recorded) runs these data cases with sqlfluff and with
`sqlfluff[rs]` (`use_rust_rules = true`), and each tool passes 2527 of the 2527
rule cases ([results/s1/summary.json](../results/s1/summary.json)).

| Group | Nodes | Class | What the source assert does | S1 data cases of the same rule |
|---|---|---|---|---|
| `test__cp01_dispatch__fix_parity` | 32 | `engine-comparison` | Compares the fixed SQL of `use_rust_rules` True and False (4 policies, 8 SQL); no expected value | `CP01.yml`: 29 cases, 16 with `fix_str` |
| `test__cp03_dispatch__fix_parity` | 35 | `engine-comparison` | The same (7 policies, 5 SQL) | `CP03.yml`: 17 cases, 8 with `fix_str` |
| `test__cp04_dispatch__fix_parity` | 20 | `engine-comparison` | The same (4 policies, 5 SQL) | `CP04.yml`: 5 cases, 4 with `fix_str` |
| `ignore_words_parity` (cp01, cp03, cp04) | 3 | `engine-comparison` | The same, with `ignore_words` | `CP01.yml`, `CP03.yml`, `CP04.yml` (as above) |
| `test__dispatch__rule_without_rust_path_falls_back` | 1 | `engine-comparison` | The same for LT01, a rule with no Rust path | The 9 `LT01-*.yml` files: 188 cases, 82 with `fix_str` |
| `test__dispatch__cp02_inherits_eval_rust_and_falls_back` | 1 | `engine-comparison` | The same for CP02, a rule with no Rust path of its own | `CP02.yml`: 48 cases, 25 with `fix_str` |
| `engages_rust_only_when_enabled` (cp01, cp03, cp04) | 3 | `python-internal` | A spy (`mock.patch` of `sqlfluffrs.cp0N_violations`) checks if the Rust detection runs | `CP01.yml`, `CP03.yml`, `CP04.yml` (as above); they cover the result of the rule, not which detection runs, and the CLI does not show it |
| `regex_ignore_falls_back_to_python` (cp01, cp03, cp04) | 3 | `python-internal` | A spy checks that `ignore_words_regex` does not call the Rust detection | `CP01.yml`, `CP03.yml`, `CP04.yml` (as above), for the result |
| `not_hijacked_by_cp01_rust_path` (cp03, cp04) | 2 | `python-internal` | 2 spies check which Rust detection runs | `CP03.yml`, `CP04.yml` (as above), for the result |
| `test__dispatch__rust_error_is_recoverable` | 1 | `python-internal` | A mock makes the Rust detection raise `RuntimeError` | `CP01.yml` (as above), for the result; the CLI cannot make this error |

- Converted (1 node, 1 case):
  `cp01_rust_dispatch_test.py::test__use_rust_rules_requires_rust_parser`. Its
  expected value is an error that the CLI shows: `FluffConfig.from_string` of a
  config with `use_rust_parser=False` and `use_rust_rules=True` raises
  `SQLFluffUserError` (match `use_rust_parser`). The case runs `lint -` in a
  temporary folder with that config as the `.sqlfluff` file: exit code 2 and
  `Error loading config: use_rust_rules is enabled but use_rust_parser is
  disabled. ...` on stdout. It has no `skipif`, so sqlfluff and `sqlfluff[rs]`
  run it.
- Data: a trace (`trace-nodes`, then `oracle.map_call` and
  `oracle.check_internal` on each node) of the 102 nodes with sqlfluff and
  with `sqlfluff[rs]`, on 2026-11-17. With sqlfluff (no sqlfluffrs), 101 nodes
  skip (`Skipped: Rust parser not available`) and the converted node passes.
  With `sqlfluff[rs]`, the 102 nodes pass. With the oracle of T18 (convert the
  rule tests, part 3, the Jinja rule nodes; goal: each rule node that needs the
  Jinja templater is a black-box case marked for the Jinja templater stone),
  the oracle refused the error of the converted node (an error of a
  FluffConfig construction), the 9 mock and spy nodes failed the
  `python-internal` check with sqlfluff (skipped), and the runner gave the
  converted case the status `error` with sqlfluff-rs (`RustConfigConflict`).
- New maps and rules (the design record, "Case runner", "Exclusions", "Trace
  oracle", and "Limits of the oracle"):
  - An error of `FluffConfig.from_string(S)` with no overrides: the trace
    gives S to the CLI as the `.sqlfluff` file and runs `lint -` in process.
    The oracle maps the error to its `cwd: tmp` case only if the first error
    of that run is an error of `FluffConfig.from_root` (the config loader of
    the CLI) with the same type and message. With overrides, the trace has no
    CLI input and the oracle refuses it.
  - A mock or spy node: the trace records the target of each `unittest.mock`
    patch (`mocks`). A `python-internal` node with a Linter or test helper
    call and no mock is an error. With sqlfluff, a `python-internal` node can
    skip only with the reason `Skipped: Rust parser not available` and no
    traced call (`skip_reason`); with `sqlfluff-rs` it must pass. Thus the 9
    mock and spy nodes are checked with `sqlfluff-rs`: each passes, and each
    has Linter string calls and `sqlfluffrs.cp0N_violations` patches.
  - The sqlfluff-rs layer: a `cwd: tmp` case whose `.sqlfluff` file sets each
    key of the layer (`use_rust_parser`, `use_rust_rules`) in `[sqlfluff]`
    runs with no layer. The trace oracle puts the layer under the settings of
    the test (`force_rust`), so the layer changes nothing. Each other input
    with a layer key is still an `error`.
  - `engine-comparison`: the oracle does not check this class.
    `harness/tests/test_s7_tests_rust_dispatch.py` reads the source of each
    Rust dispatch test and gives each node its class: `python-internal` if it
    calls `mock.patch`, `engine-comparison` if each assert compares 2 calls
    that are the same but for `"True"` and `"False"`, else converted. The
    exclusion list and the case files must agree, and each reason must give
    the S1 counts above.
- The trace of the spy node
  `commands_test.py::test__get_filtered_parse_violations_caches_rulepack_per_config`
  now has `mocks` (`Linter.get_rulepack`). The other nodes of the recorded
  result before T8, and their traces, do not change.
- Asserts: the 1 assert of the converted node (`L161:raises`) has 2 checks
  that cite it (exit code and stdout). No case uses a row of
  [s7-tests-not-reproduced.md](../docs/decisions/s7-tests-not-reproduced.md).
- The `rules` group after T8: 208 nodes, converted 97, excluded 106, not
  converted 5. The 5 nodes are of T22 (convert the rule tests, part 3; goal:
  each other rule node, not Rust dispatch, is a black-box case or is excluded
  with a class): `test_improper_configs_are_rejected[rule_config_dict7]` and
  the 4 `test__rules__std_AL09_CP02_RF06` nodes `rules3`, `rules6`, `rules7`,
  and `rules8`. Each of the 102 Rust dispatch nodes is converted or excluded.
- Speed: `scripts/verify --s7` (machine lock) gives `s7-run` 30.0 s and
  `s7-oracle` 15.6 s; at T18 (PR #109) they were 31.3 s and 16.1 s. The 1 new
  case for each tool and the 10 new traced nodes are in the noise. No tool
  code changes and no benchmark input changes (each changed path is a path
  of the S7-tests track: the S7 harness, its tests, its script, its results,
  and its documents), so no benchmark changes.
- Review round 1 (2026-11-18): the acceptance of T8 asks for the S1 data
  counts in each reason. The 9 `python-internal` reasons did not give them.
  Each now gives the counts of the rule of its file (for the result of the
  rule, not for the detection that the spy checks), and
  `test_each_rust_dispatch_exclusion_gives_its_reason` checks the counts for
  the 2 classes. Only these 9 reasons of `report.json` change.

## Rule tests, part 3 (T22)

T22 (convert the rule tests, part 3; goal: each other rule node, not Rust
dispatch, is a black-box case or is excluded with a class) of S7 (CLI and
config parity: the sqlfluff CLI, config, and Python rule tests as black-box
cases; sqll passes 100% of the converted cases; cases that need the Jinja
templater move to the Jinja templater stone) converts the last 5 rule nodes
that the oracle refused, with 2 new maps. No node needs Jinja and no node is
excluded.

| Source file | Converted in T22 | Excluded in T22 | Map | Goal of T22 |
|---|---|---|---|---|
| `std_test.py` (`test_improper_configs_are_rejected[rule_config_dict7]`) | 1 | 0 | The `capitalisation_policy` of the functions | Each other rule node, not Rust dispatch, is a black-box case or is excluded with a class |
| `std_AL09_CP02_RF06_combo_test.py` (`test__rules__std_AL09_CP02_RF06`: `rules3`, `rules6`, `rules7`, `rules8`) | 4 | 0 | A fix run whose violations are not those of a lint run | Each other rule node, not Rust dispatch, is a black-box case or is excluded with a class |
| Total | 5 | 0 | 2 maps | Each other rule node, not Rust dispatch, is a black-box case or is excluded with a class |

- Data: a trace (`trace-nodes`, then `oracle.map_call` on each traced call)
  of the 5 nodes with sqlfluff and with `sqlfluff[rs]`, on 2026-11-20. Each
  node passed in both traces. With the oracle of T8 (Rust dispatch tests
  cp01, cp03, cp04: classification and conversion; goal: each Rust dispatch
  node is converted or excluded by decision 3), the oracle refused a call of
  each node:
  - `rule_config_dict7`: the error call of `RuleSet.get_rulepack(config)`.
    The config model refused the key
    `rules:capitalisation.functions:capitalisation_policy` (the default config
    does not have it), so the trace had no CLI input.
  - `rules3`, `rules6`, `rules7`, `rules8`: the call
    `Linter(dialect=..., rules=...).lint_string(sql, fix=True)`. The lint run
    of the same SQL gives 1 more CP02 violation (line 11, position 10) than
    the fix run, in each of the 4 nodes (for example `rules3`: 9 violations
    in the fix run, 10 in the lint run). The lint command cannot show the
    violations of the fix run.
- New maps (the design record, "Trace oracle", "Config model", and "Limits
  of the oracle"):
  - The `capitalisation_policy` of the functions is an extra key of the
    config model (`EXTRA_KEYS` of `scripts/s7-tests/s7config.py`). The rule
    `capitalisation.functions` (CP03) reads `extended_capitalisation_policy`;
    `RuleSet.get_rulepack` reads the section with `get_section`, checks the
    value, and gives each key of the section to the rule. The proof is as for
    each key: the CLI loads the `.sqlfluff` file as the same config, and the
    CLI run of the error call gives the same error first
    (`RuleSet.get_rulepack`, `SQLFluffUserError: Invalid option 'blah' for
    capitalisation_policy configuration. ...`). The same key in another
    section that the default config does not give it (for example
    `capitalisation.types`) and each other key of the functions are still
    errors.
  - A fix run whose violations are not those of a lint run: a
    `Linter.lint_string` call with `fix=True` maps only to its `fix -` case
    if the node reads only `fix_string` of the result. The trace watches the
    result of such a call (`watch_reads`: a subclass of the class of the
    result records each attribute and each special method that the node reads
    after the call) and records `reads`. The 4 nodes read only `fix_string`
    (`["fix_string"]` in both traces). The oracle refuses each other read
    (for example `violations`, `check_tuples`, `__iter__`), a call with no
    `reads`, and such a call of `lint_string_wrapped`. A fix call with the
    same violations as a lint run gives the lint case and the fix case, as
    before, and the trace does not watch it.
- The case runner needs no change: the 5 nodes are `cli` cases in a
  temporary folder with a `.sqlfluff` file (the case form of T16 (trace oracle
  and case runner, extension 1; goal: the trace oracle maps and proves the
  calls that the remaining rule nodes use, and fails closed on each other
  call) and T17 (trace oracle and case runner, extension 2; goal: the trace
  oracle maps and proves the calls of the remaining rule nodes that T16 did
  not map, and fails closed on each other call)).
- Cases: `rule_config_dict7` has 1 case, `rejected` (`lint -`, exit code 2,
  and the `User Error` on stderr). Each `test__rules__std_AL09_CP02_RF06` node
  has 2 cases: `fix` (`fix -`: exit code 1, because 2 AL09 violations of the
  fix run have no fix, and the fixed SQL on stdout), and `lint_fixed` (`lint
  -f json -` of the fixed SQL: exit code 0 and no violation). These nodes have
  no lint case of the input SQL.
- Fail-closed tests (`harness/tests/test_s7_tests_oracle.py`): the config
  model test (the key of the functions maps; the same key of
  `capitalisation.types` and another key of the functions are errors); a
  fifth test tree for `trace-nodes` and the oracle script (3 nodes that map:
  a fix run with other violations that reads only `fix_string`, a fix run
  with the same violations, and the error of the functions key; 6 refused
  nodes: a read of `violations`, of `check_tuples`, and of `__iter__`, a
  `lint_string_wrapped` fix run, the key of `capitalisation.types`, and
  another key of the functions). The oracle script gives exit code 0 on the
  trace of the tree and on the recorded traces, and exit code 1 for a changed
  input of each map, for a lint case of the fix-only call, and for each
  unmapped call. The T17 test tree node `test_rulepack_error_unknown_key` now
  gives the key to `capitalisation.types`: the map knows the key of the
  functions, and the node still proves the refusal of an unknown key.
- Asserts: each of the 9 asserts of the 5 converted nodes has a check that
  cites it (`L106:raises`: the exit code and the stderr; `L246`: the stdout
  of `fix`; `L251`: the violations of `lint_fixed`). No case uses a row of
  [s7-tests-not-reproduced.md](../docs/decisions/s7-tests-not-reproduced.md).
- The `rules` group after T22: 208 nodes, converted 102, excluded 106, not
  converted 0. Each rule node is converted or excluded with a class of
  decision 2 (`exclusions.yml` gives each excluded node with its class and a
  reason of one line).
- The other nodes of the recorded result before T22, and their traces, do
  not change: the recorded traces add only the 5 nodes.
- Speed: `scripts/verify --s7` (machine lock) gives `s7-run` 42.7 s and
  `s7-oracle` 21.1 s. At T8 (PR #110), this file gives 30.0 s and 15.6 s, and
  the last local run of T8 (head `c7b3e9f`) gave 37.9 s and 24.5 s: the time
  of one run changes by more than the 5 new nodes add. The 5 nodes add 9
  cases for each tool (each a CLI run) and 5 traced nodes for each oracle
  tool. No tool code, adapter, or benchmark input changes (each changed path
  is a path of the S7-tests track), so no benchmark changes. `sqll-harness
  bench compare` of 2 full-profile reports (dialect ansi, sqlfluff and
  sqruff; BASE main `7ab4c39`, NEW `c5e2afd`; this machine, serial, machine
  lock): 20 compared, slower 0, faster 0, same 19, not valid in both 1
  (sqruff `fix/ansi/large`: warmup timeout in both).

## Trace oracle, extension 4 (T19)

T19 (trace oracle and case runner, extension 4; goal: the trace oracle maps
and proves each config call of the config nodes that a CLI command shows, and
fails closed on each other call) of S7 (CLI and config parity: the sqlfluff
CLI, config, and Python rule tests as black-box cases; sqll passes 100% of the
converted cases; cases that need the Jinja templater move to the Jinja
templater stone). The design record gives each map and its limits ("Trace
oracle", "Limits of the oracle").

- Data before T19: a trace of the 138 `config` and `config_fixtures` nodes
  that were not converted, with sqlfluff and with `sqlfluff[rs]`
  (2026-11-20), gave the plan data of T17 (trace oracle and case runner,
  extension 2; goal: the trace oracle maps and proves the calls of the
  remaining rule nodes that T16 did not map, and fails closed on each other
  call): each call maps 4, no traced call 129, refused 5. The 5 refused
  calls: 3 errors of `FluffConfig(...)` (2 `templater_selection` nodes and
  `validate_configs_indirect`), 1 error of `FluffConfig.from_kwargs()`
  (`test__config_missing_dialect`), and 1 simple-API parse with a config
  (`test__api__immutable_config`).
- New maps:
  - An error of a FluffConfig construction: the configs and overrides of
    `FluffConfig` as a `.sqlfluff` file (`s7config.input_text`), the
    arguments of `FluffConfig.from_kwargs` as lint options, and the
    overrides `dialect`, `rules`, and `exclude_rules` of
    `FluffConfig.from_string` as lint options. The CLI run (`lint [options]
    -`) must give the same error first, from `FluffConfig.from_root` (the
    config loader of each command) or from
    `FluffConfig.verify_dialect_specified` (the dialect check of each
    command). The CLI message can name the file of the case
    (`'{tmp}/.sqlfluff'`) where the message of `FluffConfig` names
    `'<provided configs>'` or `'<provided overrides>'`.
  - A simple-API parse with a config: `parse -f json -` with the SQL on
    stdin in a temporary folder with the `.sqlfluff` file of the config
    model. The trace runs the case in process, and the parse tree of the run
    must be the tree that the call returned.
- Fail-closed checks (exit code 1 with a message): an error of
  `FluffConfig.from_path` or `from_root` (config files of a folder tree), of
  `FluffConfig` with `extra_config_path`, `ignore_local_config`, or
  `plugin_manager`, of a construction with a value that is not a scalar, of
  `from_string` with another override, an error that the CLI gives in
  another way or not first, an error of `verify_dialect_specified` outside a
  construction; a parse that raised, a parse with `config_path`, with a
  config that the model does not map, or with another tree in the CLI run.
  A FluffConfig loader call that returns is not a traced call: a case of
  such a node has no traced call, and the oracle fails closed on it.
- Changed checks of the older maps: the T8 (Rust dispatch tests cp01, cp03,
  cp04: classification and conversion; goal: each Rust dispatch node is
  converted or excluded by decision 3) test tree node
  `test_string_error_overrides` (`from_string` with the override `dialect`)
  now maps to `lint --dialect ansi -`; the T17 test tree node
  `test_config_error` (`FluffConfig(configs=...)` with no dialect) is still
  refused, now because the CLI gives another error first (the templater
  error, not the dialect error).
- Proof nodes (2):
  `fluffconfig_test.py::test__config__validate_configs_indirect` (case
  `outdated`: `lint -` with the `.sqlfluff` file of the configs; exit code 2
  and `Error loading config: Config file '{tmp}/.sqlfluff' set an outdated
  config value rules:L003:lint_templated_tokens.` on stdout) and
  `fluffconfig_test.py::test__config_missing_dialect` (case `no_dialect`:
  `lint -` in an empty folder; exit code 2 and `User Error: No dialect was
  specified. ...` on stderr). sqlfluff and `sqlfluff[rs]` pass both, and
  each agrees with its trace. sqruff fails both with `unsupported`: the
  cases have no sqruff translation. Each of the 3 asserts has a check that
  cites it.
- The recorded results change only by the 2 proof nodes: the other nodes of
  `report.json` and `oracle.json`, and their traces, do not change.

### Plan data (T19)

The plan data of T9 (convert the config tests; goal: the 140 nodes of
`config` and `config_fixtures` are black-box cases or excluded with a class).
A trace with the oracle of T19 (`trace-nodes`, then `oracle.map_call` on each
traced call), on 2026-11-20, of the 136 `config` and `config_fixtures` nodes
that are not converted after T19 (the 2 proof nodes of T19 are not in this
set). Each of the 136 nodes passed in each trace, and the 2 traces give the
same column for each node. The columns are those of "Plan data (T17)".

| Group | Tool | Nodes | Each call maps | No traced call | Untraced | Refused |
|---|---|---|---|---|---|---|
| `config` | sqlfluff | 133 | 7 | 126 | 0 | 0 |
| `config` | sqlfluff-rs | 133 | 7 | 126 | 0 | 0 |
| `config_fixtures` | sqlfluff | 3 | 0 | 3 | 0 | 0 |
| `config_fixtures` | sqlfluff-rs | 3 | 0 | 3 | 0 | 0 |

- Each call maps (7, `fluffconfig_test.py`): the 2 errors of
  `test__config__templater_selection` (`afefhlsakufe` and the empty name),
  `test__api__immutable_config` (the parse map; its 2 asserts read the
  config object), and the 4 nodes that mapped before T19
  (`test__config__nested_config_tests`, `test__config__rules_set_to_none`,
  `test__config__rules_group_with_exclude`, and
  `test__config__invalid_prefer_quoted_keyword_style`).
- No traced call (129): `fluffconfig_test.py` 25, `ini_test.py` 4,
  `loader_test.py` 39, `validate_test.py` 58 (`config`), and
  `helpers/file_test.py` 2 and `linter/discovery_test.py` 1
  (`config_fixtures`). They read a FluffConfig object or call the loader,
  validate, and path functions in Python; no node has an untraced call.
- Refused: 0. The refused calls of the plan data of T17 map now.

- Speed: `scripts/verify --s7` (machine lock) gives `s7-run` 41.9 s and
  `s7-oracle` 19.4 s; at T22 (PR #112) this file gives 42.7 s and 21.1 s. The
  2 new nodes add 2 cases for each tool and 2 traced nodes for each oracle
  tool. No tool code, adapter, bench code, or benchmark input changes (each
  changed path is a path of the S7-tests track), so no benchmark changes.
  `sqll-harness bench compare` of 2 full-profile reports (dialect ansi,
  sqlfluff and sqruff; this machine, serial, machine lock; both runs at the
  first commit of PR #115, `b2bdf75`, with the same tools and bench code as
  main `c2c70f3`): 20 compared, slower 0, faster 0, same 19, not valid in
  both 1 (sqruff `fix/ansi/large`: warmup timeout in both).

## Recorded results

The recorded results of T19 (trace oracle and case runner, extension 4; goal:
the trace oracle maps and proves each config call of the config nodes that a
CLI command shows, and fails closed on each other call) of S7 (CLI and config parity: the sqlfluff CLI, config, and Python rule tests as
black-box cases; sqll passes 100% of the converted cases; cases that need the
Jinja templater move to the Jinja templater stone):
[report.json](../results/S7-tests/report.json),
[summary.json](../results/S7-tests/summary.json),
[oracle.json](../results/S7-tests/oracle.json) with the traces, and
[known_failures/](../results/S7-tests/known_failures/). The counts: in scope
643, converted 114, excluded 108, not yet converted 421. The converted nodes:
`cli` 8, `rules` 102, `config` 4. 16 converted nodes need Jinja and move to
S11 (Jinja templater: the last stone; decision of the human owner
(2026-11-07): do not write a Jinja engine in sqll; decide with data how sqll
supports Jinja; sqll passes 100% of the Jinja cases that the decision keeps,
and S8 (code generation: types of query parameters and result columns as JSON
Schema; the JSON Schema output is valid and correct for each parameter style,
code made from the schema by one existing tool compiles, and the harness shows
one parse for each file when one command lints and generates code) supports
Jinja if kept; each other Jinja case is in a known-failure list with its
reason): the 13 nodes of T18 (see "Rule tests, part 3, the Jinja rule nodes
(T18)"), `std_LT04_test.py::test__rules__std_LT04_unparseable`,
`std_test.py::test__rules__std_file[JJ01-heavy_templating.sql-violations16]`,
and `std_LT02_oscillation_test.py::test_rules_std_LT02_loop_comma_no_oscillation`.
The report counts them as `needs_jinja` (16) and gives their result as
`s11_jinja`, apart from the parity of S7. The excluded nodes: 14
`python-internal`, 2 `needs-python-runtime`, 92 `engine-comparison`, 0
`environment`. The `rules` group: 208 nodes, converted 102, excluded 106, not
yet converted 0.

Parity of the 98 converted nodes that S7 (CLI and config parity: the sqlfluff CLI, config, and Python rule tests as
black-box cases; sqll passes 100% of the converted cases; cases that need the
Jinja templater move to the Jinja templater stone) keeps (nodes):

| Tool | Nodes | Passed | Failed | Error |
|---|---|---|---|---|
| sqlfluff | 98 | 98 | 0 | 0 |
| sqlfluff-rs | 98 | 97 | 1 | 0 |
| sqruff | 98 | 8 | 90 | 0 |

Result of the 16 converted nodes that need Jinja (`s11_jinja`, nodes): sqlfluff
16 of 16 pass, sqlfluff-rs 16 of 16 pass, sqruff 0 of 16 pass (each fails with
`unsupported: <item>`: 15 have no sqruff translation of the CLI command, 1 is
`rule all`).

- sqlfluff-rs: `test__cli__command_directed` fails. With
  `use_rust_rules`, the CP01 description is "Keywords must be consistent."
  and not "Keywords must be consistently upper case.".
- sqruff: 88 nodes fail with `unsupported: <item>`: 69 CLI nodes with no
  sqruff translation of the command (59 of them rule nodes and 4 config
  nodes: the cases of the trace oracle maps), 18 `rule all`, and 1 output
  fields.
  2 translated CLI nodes fail on the output: `test__cli__command_directed`
  (sqruff writes the lint output to stderr, not to stdout) and
  `test__cli__command_dialect` (exit code 1, not 2). sqruff passes the 8
  rule nodes whose source call gives `rules`: `std_CV02`, `std_LT01_LT04`,
  and the 6 converted nodes of `std_ST12` that give no config.

Results of each suite with each tool. The parity columns count the converted
nodes that S7 (CLI and config parity: the sqlfluff CLI, config, and Python rule tests as
black-box cases; sqll passes 100% of the converted cases; cases that need the
Jinja templater move to the Jinja templater stone) keeps (passed/nodes):

| Suite | In scope | Converted | Excluded | sqlfluff | sqlfluff-rs | sqruff |
|---|---|---|---|---|---|---|
| `s7_rules` | 208 | 102 | 106 | 86/86 | 86/86 | 8/86 |
| `s7_config` | 140 | 4 | 0 | 4/4 | 4/4 | 0/4 |
| `s7_cli` | 295 | 8 | 2 | 8/8 | 7/8 | 0/8 |

Trace oracle (`results/S7-tests/oracle.json`):

| Tool | Nodes | Agree | Pass | Fail | Asserts | Not reproduced | `python-internal` |
|---|---|---|---|---|---|---|---|
| sqlfluff | 114 | 114 | 114 | 0 | 226 | 0 | 14 |
| sqlfluff-rs | 114 | 114 | 113 | 1 | 226 | 0 | 14 |

- Each of the 114 converted nodes agrees with its trace, with sqlfluff and
  with `sqlfluff[rs]`. The 1 sqlfluff-rs failure is
  `test__cli__command_directed`: the pytest node fails too.
- Each of the 226 asserts of the converted source tests has a check that
  cites it. No case uses a row of
  [s7-tests-not-reproduced.md](../docs/decisions/s7-tests-not-reproduced.md).
- The 14 `python-internal` nodes pass the class check with each tool. With
  sqlfluff, the 9 mock and spy nodes of T8 (Rust dispatch tests cp01, cp03,
  cp04: classification and conversion; goal: each Rust dispatch node is
  converted or excluded by decision 3) skip (no Rust parser); with
  `sqlfluff[rs]` they pass.
- The nodes of the recorded result before T19, and their traces, do not
  change: T19 adds 2 nodes (see "Trace oracle, extension 4 (T19)").

Known failures (nodes):

| Tool | Known failures | Reason |
|---|---|---|
| sqlfluff | 0 | sqlfluff passes each converted node |
| sqlfluff-rs | 1 | `test__cli__command_directed`: with `use_rust_rules`, the CP01 description is different; the pytest node fails with `--rust` too |
| sqruff | 106 | 104 `unsupported: <item>`: 84 CLI nodes with no sqruff translation of the command, 19 `rule all`, 1 output fields. 2 translated CLI nodes fail on the output: `test__cli__command_directed` (the lint output is on stderr) and `test__cli__command_dialect` (exit code 1, not 2). 16 of the 106 need Jinja and move to S11 (Jinja templater: the last stone; decision of the human owner (2026-11-07): do not write a Jinja engine in sqll; decide with data how sqll supports Jinja; sqll passes 100% of the Jinja cases that the decision keeps, and S8 (code generation: types of query parameters and result columns as JSON Schema; the JSON Schema output is valid and correct for each parameter style, code made from the schema by one existing tool compiles, and the harness shows one parse for each file when one command lints and generates code) supports Jinja if kept; each other Jinja case is in a known-failure list with its reason): the 13 Jinja nodes of T18 (convert the rule tests, part 3, the Jinja rule nodes; goal: each rule node that needs the Jinja templater is a black-box case marked for the Jinja templater stone), `test__rules__std_LT04_unparseable`, `test__rules__std_file[JJ01-heavy_templating.sql-violations16]`, and `test_rules_std_LT02_loop_comma_no_oscillation` |
