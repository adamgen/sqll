# S7 decision: the test conversion design

Status: decided (2026-11-11). The orchestrator decided the 4 open items
for the human owner (standing delegation, CONSTITUTION.md section 5); see
"Decisions". Written in T1 (design record, scope inventory, and status
files). Scope: STONES.md S7 (CLI and config parity: the sqlfluff CLI,
config, and Python rule tests as black-box cases), the test conversion part
(track S7-tests). The sqll part is track S7-sqll. Goals: CONSTITUTION.md
G1.4 and G1.5 (lint parity with sqlfluff: a percentage of test cases, run
through a binary), G3 (speed), G4 (verification first). Plan and tasks:
[status/S7-tests.md](../../status/S7-tests.md).

## Decisions

The orchestrator decided these 4 items on 2026-11-11 for the human owner
(standing delegation, CONSTITUTION.md section 5). The status file has the
same decisions.

1. Scope rule: ACCEPT. Do not make `config_fixtures` wider. Data:
   `scope.json` gives `cli` 295, `rules` 208, `config` 137,
   `config_fixtures` 3, total 643. The source rule finds 2 nodes. The run
   rule finds 1 node in both runs: sqlfluff 8268 passed, 3 failed, 2529
   skipped; `sqlfluff[rs]` 10792 passed, 3 failed, 5 skipped. The 3 failed
   `test/core/plugin_test.py` nodes do not read `test/fixtures/config`.
2. The 4 exclusion classes: ACCEPT, with these conditions. A
   machine-readable list gives each excluded node with its node id and its
   class, apart from parity. Each `needs-python-runtime` and `environment`
   node has a reason of one line. The report gives the in-scope total, the
   converted count, and the excluded count.
3. Rust dispatch: Option A. The 87 `fix_parity` nodes (cp01 32, cp03 35,
   cp04 20) are `engine-comparison`. Their source assert compares
   `use_rust_rules` True and False and has no expected value. The S1 data
   cases cover the same rules: `CP01.yml` 29 cases (16 with `fix_str`),
   `CP03.yml` 17 (8), `CP04.yml` 5 (4). S1 compares sqlfluff and
   `sqlfluff[rs]` on 4937 cases. The same rule applies to the other
   compare-only nodes, for example the 3 `ignore_words_parity` nodes. A
   mock or spy node is `python-internal`. A node with an expected value
   that the CLI shows is converted. T8 (Rust dispatch tests:
   classification and conversion) applies this rule.
4. Pointer section in `harness/not-reproduced.md`: ACCEPT. It comes in the
   cross-track T4 or T5 pull request. That pull request merges before an S7
   case uses a not-reproduced record.

## Scope

The conversion unit is one pytest node of the pinned sqlfluff 4.4.0 tests.
`scripts/s7-tests/inventory` makes the list from the pinned test code with
`pytest --collect-only` (no test runs, no bytecode, no cache) and writes
[results/S7-tests/scope.json](../../results/S7-tests/scope.json). A node is
in scope if it is in one of these groups:

| Group | Nodes |
|---|---|
| `cli` | 295 |
| `rules` | 208 |
| `config` | 137 |
| `config_fixtures` | 3 |
| `total` | 643 |

- `cli`: all nodes of `test/cli/`. pytest collects only `*_test.py`
  (`python_files`), so the inventory gives
  `test/cli/test_parse_with_positions.py` (10 nodes) by path.
- `rules`: all nodes of `test/rules/`, but not `test__rule_test_case` (2527
  nodes) and `test__std_fix_auto` (61 nodes). The suites `rules` and
  `autofix` of S1 (binary test harness: run the sqlfluff test fixtures
  through a binary) convert them.
- `config`: all nodes of `test/core/config/`.
- `config_fixtures`: each other node that names a path in
  `test/fixtures/config` in its test function (2 nodes, "by source"), or
  that opens or lists such a path when it runs (1 node, "by run").
  `scripts/s7-tests/config-readers` runs the other sqlfluff tests on a copy
  of the submodule, 2 times: with sqlfluff
  ([config-readers.json](../../results/S7-tests/config-readers.json)) and
  with `sqlfluff[rs]`
  ([config-readers-rs.json](../../results/S7-tests/config-readers-rs.json)).
  Without `sqlfluff[rs]`, 2529 nodes are skipped (most need the Rust
  parser). With it, 5 are skipped. Both runs found only
  `test/core/linter/discovery_test.py::test__linter__path_from_paths__dot`:
  it walks the checkout from `.` and reads the config files.
- Fail-closed checks of the source rule: the inventory stops if a name is
  outside a collected test function, if a name in a decorator is in no
  parameter value, or if a file that pytest cannot import has a name.
  `test/dialects/bigquery_test.py` cannot import (no `hypothesis` in the
  oracle tools) and has no name.
- Checks of the run: the trace sees the reads of the test process, of its
  forked processes, and of each new Python process. The script stops on a
  read in the collection that is not a folder list, on a read outside a
  test, and on a node that starts more programs than the trace sees (for
  example a program that is not Python). 3 nodes fail in each run: the
  example plugin (`plugins/sqlfluff-plugin-example`) is not installed in
  the oracle tools. Their file `test/core/plugin_test.py` does not name the
  folder. The oracle `bin` folder is on `PATH`, so the 5
  `test/diff_quality_plugin_test.py` nodes find `sqlfluff` and pass.

The Rust dispatch tests (`cp01`, `cp03`, `cp04_rust_dispatch_test.py`) are
102 nodes of `rules`. 87 of them are `fix_parity` nodes. They compare the
Python and the Rust engines and have no expected output in data.

`harness/tests/test_s7_tests_scope.py` fails if `scope.json` is not the
inventory output, or if this table or the table in the status file is not
the counts of `scope.json`. A change of the pinned sqlfluff version needs a
new `config-readers` run with each oracle (about 13 minutes each) and a
new inventory.

## Cases

- One node has one or more black-box cases. A node passes only if all its
  cases pass.
- A case runs a tool binary (G1.5): the CLI, or the simple API through the
  adapter of the tool. The case has inputs (argv, stdin, files, config) and
  checks on the outputs (exit code, stdout, stderr, changed files).
- A case file has a header with the source (sqlfluff 4.4.0, file, and node)
  and the license (MIT). Inline SQL, argv, and expected values from the
  Python tests are a derived work of sqlfluff. THIRD_PARTY.md gets an entry
  in T4 (harness hooks for the S7 suites, cross-track). The cases read
  fixture files in place. They do not copy or change them (G4.5).
- T2 (case format, case runner, and pilot cases) set the format, the
  runner, and the report below.

## Case format

One YAML file holds the cases of one sqlfluff test file:
`harness/sqll_harness/s7_tests/cases/<path>.yml`. `<path>` is the path of
the test file without `test/` (`test/cli/commands_test.py` gives
`cli/commands_test.yml`). The pilot files are examples.

```yaml
source:                     # required: the source of the cases
  project: sqlfluff
  version: 4.4.0
  commit: 0348222a3bcdb0226563f7349c5a39beb0641955
  file: test/cli/commands_test.py
license: MIT                # required: the license of sqlfluff
nodes:
  - node: test/cli/commands_test.py::test__cli__command_dialect  # pytest node id
    cases:                  # one or more; the node passes if all pass
      - name: unknown_dialect
        run: cli            # cli or api
        needs_jinja: false  # true: the node needs Jinja and moves to S11
        argv: [lint, -n, --dialect, faslkjh, test/fixtures/linter/indentation_error_simple.sql]
        cwd: sqlfluff       # sqlfluff (default) or tmp
        stdin: "SELECT 1"
        files: {}           # only with cwd tmp: {path: text}
        sqruff: [lint, --dialect, faslkjh, test/fixtures/linter/indentation_error_simple.sql]
        checks:
          exit_code: 2      # required for each cli case
          stdout: {contains: [Unknown dialect]}
```

- Inputs of a `cli` case: `argv` (without the program name), `stdin`,
  `cwd`, and `files`. `cwd: sqlfluff` runs in the submodule root, as the
  sqlfluff tests do, and reads the fixtures in place. `cwd: tmp` runs in a
  new temporary folder with `files`. In `argv`, `{tmp}` is the temporary
  folder and `{sqlfluff}` the submodule root. Config files are `files` (for
  example `.sqlfluff`). `sqruff` is the sqruff translation of `argv`.
- Inputs of an `api` case: `function` (`lint` or `fix`), `sql`, `dialect`
  (default `ansi`), `rules` (default all rules), `exclude_rules`, and
  `config` (the sqlfluff config structure). These are the arguments of the
  simple API (`sqlfluff.lint`, `sqlfluff.fix`).
- Checks: `exit_code`; `stdout` and `stderr` with `equals`, `startswith`,
  `contains`, `not_contains`, or `json`; `files` (cli, `cwd: tmp`): the
  content of each changed or new file; `violations` (cli `lint -f json`
  output, or api `lint`); `fixed` (api `fix`).
- A `violations` check: `select` (key: value, or key: `{contains: text}`),
  then `count`, `min_count`, or `records` (one partial violation for each
  selected violation, in order). `exact: true` makes each record give all
  keys. `file` selects a file of the cli output.
- The loader fails closed (exit code 2) on: no `source` or `license`, a
  source that is not sqlfluff 4.4.0 at the pinned commit, a case file at a
  path that is not that of its source file, a node id that is not in
  `scope.json` or not of the source file, a node in 2 places (also in the
  exclusion list), an unknown key, a repeated YAML key, a case with no
  checks, a cli case with no `exit_code`, and `files` without `cwd: tmp`.

## Exclusion list

`harness/sqll_harness/s7_tests/exclusions.yml` gives each excluded node:
`node` (the pytest node id), `class` (one of the 4 classes), and `reason`.
Each `needs-python-runtime` and `environment` node needs a reason of one
line. The loader fails closed on an unknown class, a missing or empty
reason, a reason of more lines, and a node that is not in `scope.json`.

## Case runner

`uv run --frozen --project harness scripts/s7-tests/run-cases [--tool T]
[--require-pass T] [--check FILE]` loads the cases, checks the tools
(`sqll-harness tools`), runs each case for each tool, writes the report
(default `out/s7-tests/report.json`), and runs `scripts/check-submodule`.

- `cli`: the CLI of the tool, with the environment of its adapter (an
  empty home). `sqlfluff-rs` gets the layer of its adapter
  (`harness/sqlfluff-rs.md`) as `--config <file>` after the command, for
  `lint`, `fix`, `format`, `parse`, and `render`. A case that gives
  `--config`, or an input with a layer key, is an `error`. sqruff runs the
  `sqruff` argv; with no translation the case fails with `unsupported:
  sqlfluff CLI command '<command>'`.
- `api`: `lint()` or `fix()` of the adapter of the tool, which runs the
  CLI with `--ignore-local-config`, as the simple API. All rules are
  `--rules all`. sqruff fails such a case with `unsupported: rule all`, and
  a check of a field that sqruff does not give with `unsupported: output
  field <key>`.
- A case status is `pass`, `fail`, or `error` (the tool or the harness did
  not complete). A node is `pass` only if each case passes, `error` if a
  case has an error, else `fail`.
- Exit code 1 if the submodule changed (G4.5), if a `--require-pass` tool
  did not pass a node, or if the report is not the `--check` file.

## Report

`results/S7-tests/report.json` is the recorded report of all tools.

- `nodes`: each converted node with its group, case file, number of cases,
  `needs_jinja`, and for each tool its status and each case that did not
  pass, with its reason.
- `excluded`: each excluded node with its group, class, and reason, apart
  from parity.
- `counts`: `in_scope` (643, from `scope.json`), `converted`, `excluded`,
  `not_yet_converted`, `needs_jinja`, the same counts for each group, and
  the count of each class.
- `parity` (for each tool, the converted nodes that S7 keeps) and
  `s11_jinja` (the nodes that need Jinja): `nodes`, `passed`, `failed`,
  `error`, `percent_of_converted`, and `percent_of_in_scope`. The second
  percentage counts each excluded node and each node that is not converted
  yet as not passed. Thus an exclusion cannot hide (G1.4).
- `report.check()` computes each count and status again and fails closed if
  one does not agree, if a class is unknown, or if a `needs-python-runtime`
  or `environment` node has no reason.

## Suites and tools

- 3 suites: `s7_rules` (group `rules`), `s7_config` (groups `config` and
  `config_fixtures`), and `s7_cli` (group `cli`).
- Tools: sqlfluff, `sqlfluff[rs]` (`sqlfluff-rs`), and sqruff. sqll joins in
  track S7-sqll: it adds sqll to the suite tools and to its CI matrix
  fragment.
- sqruff runs the lint and fix cases through its adapter, and a translated
  subset of the CLI cases. Each other case fails with
  `unsupported: <item>` and is a known failure.

## Exclusions

A node that the harness cannot run through a binary is excluded, with one
reason class:

- `python-internal`: the node calls no CLI command and no simple-API
  function. The trace oracle checks this class (no traced call).
- `needs-python-runtime`: G1.3, for example a Python plugin.
- `engine-comparison`: the node compares 2 engines and has no expected
  value. This includes the 87 `fix_parity` nodes, as the S1 owner decision
  on `test/fixtures/parity/` does (status/S1.md). Each other Rust dispatch
  node with an expected value that the CLI shows is converted (decision
  3).
- `environment`: the node needs a condition that the harness cannot make.

Parity counts the converted cases and nodes. The report gives the excluded
nodes apart, each with its reason class.

## Trace oracle (T3: each case agrees with a trace of its node)

The oracle runs the original pytest nodes in place with the pinned
sqlfluff, and with `--rust` for `sqlfluff[rs]`. It records each CLI call and
each simple-API call. It checks:

1. The inputs of each case are the traced inputs.
2. The checks of each case pass on the traced outputs.
3. The status of each node agrees with the harness report.
4. A check of a case cites each assert of the source test, or
   `docs/decisions/s7-tests-not-reproduced.md` records it as not
   reproduced.

## Results and ownership

- Track paths: the suites, `results/S7-tests/known_failures/<tool>.txt`,
  `results/S7-tests/summary.json`, `ci/matrix.d/S7-tests.json`, and
  `docs/decisions/s7-tests-not-reproduced.md`.
- Cross-track pull requests that the Core track reviews, T4 (harness hooks
  for the S7 suites) and T5 (CI jobs and first results of the S7 suites):
  the
  harness core hooks, the CI workflow, `scripts/verify`, THIRD_PARTY.md, and
  a pointer section in `harness/not-reproduced.md`. The pointer section
  makes `s7-tests-not-reproduced.md` part of the not-reproduced record of
  PROCESS.md rule 7 (decision 4).
- STATUS.md is an orchestrator file. Only T1 and T15 change the S7 test
  conversion row, with the `cross-track` label, because the orchestrator
  task asks for it. At T15 (the exit task: proof and "awaiting human
  approval") the row says "S7 test conversion (track S7-tests): awaiting
  human approval". The S7 exit (sqll passes 100%)
  belongs to track S7-sqll.

## G3 and G4 for each task

- G3: this track changes no tool code, so no benchmark changes. Each pull
  request gives the added CI time of the S7 jobs and the `bench compare`
  result. T10 (CLI tests, part 1: commands, arguments, and exit codes)
  opens a Core issue for each command that S7 cases use and that has no
  benchmark of S2 (benchmarks: start, parse, lint, and fix for each tool
  and dialect).
- G4: the scope comes from the pinned test code, not from a hand list. Each
  task proves its claims with harness output. `scripts/check-submodule`
  shows no change after each run.
