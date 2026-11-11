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
| T1 | Design record, scope inventory, and status files | The scope (643 nodes), the design, and the 4 decisions are recorded and tested | Done (PR #60) |
| T2 | Case format, case runner, and pilot cases | One case format and one runner run pilot cases through a tool binary | Done (PR #78) |
| T3 | Trace oracle with fail-closed checks | Each case agrees with a trace of its original pytest node | Done (PR #80) |
| T4 | Cross-track (Core): harness hooks for the S7 suites | The harness core runs the 3 S7 suites | Done (PR #82; the Core track reviews it) |
| T5 | Cross-track (Core): CI jobs, oracle step, and local verify for the S7 suites; the ruff lint of `scripts/s7-tests/` in CI; first recorded results | CI and `scripts/verify` run the S7 suites and record the results | In review (PR #83; the Core track reviews it) |
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

## Pilot (T2)

T2 (case format, case runner, and pilot cases; S7: CLI and config parity,
the sqlfluff CLI, config, and Python rule tests as black-box cases) gives
the case format, the case runner (`scripts/s7-tests/run-cases`; T4 (harness
hooks for the S7 suites: the harness core runs the 3 S7 suites; S7: CLI and
config parity, the sqlfluff CLI, config, and Python rule tests as black-box
cases) moved it to `sqll-harness s7 run`), and pilot cases of each group.
The recorded report is
[results/S7-tests/report.json](../results/S7-tests/report.json): in scope
643, converted 15, excluded 3, not yet converted 625. The converted nodes:
`cli` 8, `rules` 5, `config` 2. 1 converted node needs Jinja
(`std_LT04_test.py::test__rules__std_LT04_unparseable`) and moves to S11
(Jinja templater: the last stone; decision of the human owner (2026-11-07):
do not write a Jinja engine in sqll; decide with data how sqll supports
Jinja; sqll passes 100% of the Jinja cases that the decision keeps, and S8
supports Jinja if kept; each other Jinja case is in a known-failure list
with its reason). The excluded nodes: 1 `python-internal`, 1
`needs-python-runtime`, 1 `engine-comparison`.

Parity of the 14 converted nodes that S7 (CLI and config parity: the
sqlfluff CLI, config, and Python rule tests as black-box cases) keeps
(nodes):

| Tool | Nodes | Passed | Failed | Error |
|---|---|---|---|---|
| sqlfluff | 14 | 14 | 0 | 0 |
| sqlfluff-rs | 14 | 13 | 1 | 0 |
| sqruff | 14 | 1 | 13 | 0 |

- sqlfluff-rs: `test__cli__command_directed` fails. With
  `use_rust_rules`, the CP01 description is "Keywords must be consistent."
  and not "Keywords must be consistently upper case.".
- sqruff: 11 nodes fail with `unsupported: <item>` (no sqruff translation
  of the CLI command, `rule all`, or output fields). 2 translated CLI nodes
  fail on the output: `test__cli__command_directed` (sqruff writes the
  lint output to stderr, not to stdout) and `test__cli__command_dialect` (exit code 1, not 2).

T5 (CI jobs, oracle step, and local verify for the S7 suites: CI and
`scripts/verify` run the S7 suites and record the results; S7: CLI and
config parity, the sqlfluff CLI, config, and Python rule tests as black-box
cases) adds the S7 CI jobs and the known-failure lists; see "CI and
recorded results (T5)".

## Trace oracle (T3)

T3 (trace oracle with fail-closed checks: each case agrees with a trace of
its original pytest node; S7: CLI and config parity, the sqlfluff CLI,
config, and Python rule tests as black-box cases) gives
`scripts/s7-tests/oracle`. The design and its limits are in the design
record, "Trace oracle". The recorded result is
[results/S7-tests/oracle.json](../results/S7-tests/oracle.json), with the
traces `oracle-trace-sqlfluff.json` and `oracle-trace-sqlfluff-rs.json`.

| Tool | Nodes | Agree | Pass | Fail | Asserts | Not reproduced | `python-internal` |
|---|---|---|---|---|---|---|---|
| sqlfluff | 15 | 15 | 15 | 0 | 49 | 0 | 1 |
| sqlfluff-rs | 15 | 15 | 14 | 1 | 49 | 0 | 1 |

- Each of the 15 converted pilot nodes agrees with its trace, with
  sqlfluff and with `sqlfluff[rs]`. The 1 sqlfluff-rs failure is
  `test__cli__command_directed`: the pytest node fails too.
- Each of the 49 asserts of the pilot source tests has a check that cites
  it. No case uses a row of
  [s7-tests-not-reproduced.md](../docs/decisions/s7-tests-not-reproduced.md).
  T4 (harness hooks for the S7 suites: the harness core runs the 3 S7
  suites; S7: CLI and config parity, the sqlfluff CLI, config, and Python
  rule tests as black-box cases) added the pointer section in
  `harness/not-reproduced.md` (decision 4); the recorded result now has
  `"pointer": true`.
- The `python-internal` node has no traced CLI or simple-API call.
- The case files now have an `asserts` map for each node.
- The oracle exits with code 1 if a case input is not the traced input, a
  check fails on the traced output, the report status is not the pytest
  outcome, or an assert has no citation and no record. A harness test
  proves each of these 4 failure paths.

## Harness hooks (T4)

T4 (cross-track, Core reviews: harness hooks for the S7 suites; the harness
core runs the 3 S7 suites `s7_rules`, `s7_config`, `s7_cli`; S7: CLI and
config parity, the sqlfluff CLI, config, and Python rule tests as
black-box cases) adds `sqll-harness s7 run [--suite S] [--tool T]`. It
replaces `scripts/s7-tests/run-cases`. The design is in the design record,
"Case runner" and "Report".

- The report has the key `suites` (format 2). The scope of a report is the
  nodes of its suites: `s7_rules` 208, `s7_config` 140, `s7_cli` 295.
- Before a tool runs, the command fails closed (exit code 2) if an assert
  of a converted source test has no citing check and no row of the
  not-reproduced record.
- `harness/not-reproduced.md` has the pointer section "S7 test conversion"
  (decision 4). THIRD_PARTY.md has the entry of S7 (CLI and config parity:
  the sqlfluff CLI, config, and Python rule tests as black-box cases).
- The command of S1 (binary test harness: run the sqlfluff test fixtures
  through a binary, not through function calls; sqlfluff passes 100% of the
  cases through the harness, and the results of the other tools are
  recorded), `sqll-harness run`, and its suites do not change.

Results of each suite with each tool, for the pilot cases of T2 (case
format, case runner, and pilot cases: one case format and one runner run
pilot cases through a tool binary; S7: CLI and config parity, the sqlfluff
CLI, config, and Python rule tests as black-box cases). They are equal to
[results/S7-tests/report.json](../results/S7-tests/report.json):

| Suite | In scope | Converted | Excluded | sqlfluff | sqlfluff-rs | sqruff |
|---|---|---|---|---|---|---|
| `s7_rules` | 208 | 5 | 1 | 4/4 | 4/4 | 1/4 |
| `s7_config` | 140 | 2 | 0 | 2/2 | 2/2 | 0/2 |
| `s7_cli` | 295 | 8 | 2 | 8/8 | 7/8 | 0/8 |

The parity columns count the converted nodes that S7 (CLI and config
parity: the sqlfluff CLI, config, and Python rule tests as black-box cases)
keeps (passed/nodes); 1 converted `s7_rules` node needs Jinja and moves to
S11 (Jinja templater: the last stone; decision of the human owner
(2026-11-07): do not write a Jinja engine in sqll; decide with data how sqll
supports Jinja; sqll passes 100% of the Jinja cases that the decision keeps,
and S8 supports Jinja if kept; each other Jinja case is in a known-failure
list with its reason).

## CI and recorded results (T5)

T5 (cross-track, Core reviews: CI jobs, oracle step, and local verify for
the S7 suites; CI and `scripts/verify` run the S7 suites and record the
results; S7: CLI and config parity, the sqlfluff CLI, config, and Python
rule tests as black-box cases). The design is in the design record,
"Known failures", "Summary", and "CI".

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

Known failures (nodes) of the recorded results:

| Tool | Known failures | Reason |
|---|---|---|
| sqlfluff | 0 | sqlfluff passes each converted node |
| sqlfluff-rs | 1 | `test__cli__command_directed`: with `use_rust_rules`, the CP01 description is different; the pytest node fails with `--rust` too |
| sqruff | 14 | 12 `unsupported: <item>`: 8 CLI commands with no sqruff translation, 3 `rule all`, 1 output fields. 2 translated CLI nodes fail on the output: `test__cli__command_directed` (the lint output is on stderr) and `test__cli__command_dialect` (exit code 1, not 2). 1 of the 14 (`test__rules__std_LT04_unparseable`) needs Jinja and moves to S11 (Jinja templater: the last stone; decision of the human owner (2026-11-07): do not write a Jinja engine in sqll; decide with data how sqll supports Jinja; sqll passes 100% of the Jinja cases that the decision keeps, and S8 supports Jinja if kept; each other Jinja case is in a known-failure list with its reason) |
