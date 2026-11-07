# S7 decision: the test conversion design

Status: design (T1). Scope: STONES.md S7, the test conversion part (track
S7-tests). The sqll part is track S7-sqll. Goals: CONSTITUTION.md G1.4,
G1.5, G3, G4. Plan and tasks: [status/S7-tests.md](../../status/S7-tests.md).
The orchestrator records the approval of each decision below (standing
delegation, CONSTITUTION.md section 5).

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
  nodes) and `test__std_fix_auto` (61 nodes). The S1 suites `rules` and
  `autofix` convert them.
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
  (T4, cross-track). The cases read fixture files in place. They do not copy
  or change them (G4.5).
- T2 sets the exact case format and the case runner.

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
  node with an expected value that the CLI shows is converted. The
  orchestrator records this decision before T8 merges.
- `environment`: the node needs a condition that the harness cannot make.

Parity counts the converted cases and nodes. The report gives the excluded
nodes apart, each with its reason class.

## Trace oracle (T3)

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
- Cross-track pull requests (T4, T5) that the Core track reviews: the
  harness core hooks, the CI workflow, `scripts/verify`, THIRD_PARTY.md, and
  a pointer section in `harness/not-reproduced.md`. The orchestrator
  records that the pointer section makes `s7-tests-not-reproduced.md` part
  of the not-reproduced record of PROCESS.md rule 7.
- STATUS.md is an orchestrator file. Only T1 and T16 change the S7 test
  conversion row, with the `cross-track` label, because the orchestrator
  task asks for it. At T16 the row says "S7 test conversion (track
  S7-tests): awaiting human approval". The S7 exit (sqll passes 100%)
  belongs to track S7-sqll.

## G3 and G4 for each task

- G3: this track changes no tool code, so no benchmark changes. Each pull
  request gives the added CI time of the S7 jobs and the `bench compare`
  result. T11 opens a Core issue for each command that S7 cases use and
  that has no S2 benchmark.
- G4: the scope comes from the pinned test code, not from a hand list. Each
  task proves its claims with harness output. `scripts/check-submodule`
  shows no change after each run.
