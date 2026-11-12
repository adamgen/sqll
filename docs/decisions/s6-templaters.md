# Decision record: the templater design

Status: proposed (2026-11-11). The orchestrator decides the 6 items for
the human owner (standing delegation, CONSTITUTION.md section 5). No item
is for the human owner. Written in T1 (design record, fixture set from the
data, status file, and track paths: the S6 scope and design are recorded
and tested) of S6 (templater parity: sqll passes 100% of the placeholder
and Python format-string templater fixtures that do not need a Python
runtime). The scope is that stone in STONES.md. Plan and tasks:
[status/S6.md](../../status/S6.md).

Goals of CONSTITUTION.md:

- G1 (lint parity with sqlfluff: sqll does all that the pinned sqlfluff
  version does (dialects, rules, fixes, configuration, templaters), except
  Python plugins and features that need a Python runtime. Only the human
  owner approves each version change (the standing delegation keeps it).
  Parity is the percentage of sqlfluff test cases that sqll passes through
  a binary. The same harness runs sqlfluff, sqruff, and sqll).
- G3 (speed: each command, start time included, is as fast as reasonably
  possible and has a benchmark that measures sqlfluff, sqruff, and sqll on
  the same input. sqll is faster than sqlfluff on each benchmark, not
  slower than sqruff on any benchmark, and faster than sqruff on the total
  of all benchmarks. A change that makes a benchmark slower gives the
  reason. Correctness is more important than speed: do not make a result
  wrong to make it fast).
- G4 (verification first: each behavior has an automated test; tests come
  from external sources (sqlfluff first, then large, complex public SQL
  files); external test data has its source, version, and license, and
  does not change to make a test pass; one command runs all tests and
  benchmarks, and the output is machine-readable; each known failure is in
  a list).

## Decisions

Each item has a recommendation, the other options, and the data. The
orchestrator writes its decision and the date here and in the status file.

1. The set (see "Set"). Recommendation: the parity number of this stone is
   the 54 black-box nodes of the placeholder and Python templater tests.
   The 25 internal nodes are a separate number (item 3). The 13 rule
   fixture cases have their exit in S5 (rule parity: 100% of the rule
   fixtures, lint and fix; cases that need the Jinja templater move to
   S11); this stone checks their templated text and source slices. The 43
   cases of the templater suite of the test harness are Jinja cases and go
   to S11 (Jinja templater: the last stone; decision of the human owner
   (2026-11-07): do not write a Jinja engine in sqll; decide with data how
   sqll supports Jinja; sqll passes 100% of the Jinja cases that the
   decision keeps, and S8 supports Jinja if kept; each other Jinja case is
   in a known-failure list with its reason). Other option: count only the
   54 black-box nodes and drop the internal nodes. Data: "Set".
2. The rule "needs a Python runtime" (see that section). Recommendation:
   accept the rule. It classifies 0 of 79 nodes as "needs a Python
   runtime".
3. The 25 internal nodes. Recommendation: option A (see "Internal nodes").
4. The black-box form. Recommendation: the case format, the runner, and
   the trace oracle of the test conversion of S7 (CLI and config parity:
   the sqlfluff CLI, config, and Python rule tests as black-box cases;
   sqll passes 100% of the converted cases; cases that need the Jinja
   templater move to S11), with a scope file of this stone (see
   "Black-box form").
5. The port source and license. Recommendation: port sqlfluff
   `placeholder.py` and `python.py` (MIT) to Rust (see "Port").
6. Speed. Recommendation: new templater benchmarks (see "Speed").

## Set

`scripts/s6/inventory.py` makes
[results/S6/scope.json](../../results/S6/scope.json) from the pinned
sqlfluff 4.4.0 (commit `0348222a`). It reads the submodule in place. It
collects the pytest nodes with `pytest --collect-only` in the Python of
the sqlfluff oracle tools (`scripts/s6/unit_nodes.py`). It runs no test.
Its key `license` gives the license of the test data (MIT), and
THIRD_PARTY.md has the record of the scripts and of `scope.json`.

| Count | Value |
|---|---|
| `templater_suite.total` | 43 |
| `templater_suite.jinja` | 43 |
| `templater_suite.placeholder` | 0 |
| `templater_suite.python` | 0 |
| `templater_suite.needs_python` | 3 |
| `placeholder_nodes.total` | 26 |
| `placeholder_nodes.black_box` | 26 |
| `placeholder_nodes.internal` | 0 |
| `placeholder_nodes.needs_python_runtime` | 0 |
| `python_nodes.total` | 53 |
| `python_nodes.black_box` | 28 |
| `python_nodes.internal` | 25 |
| `python_nodes.needs_python_runtime` | 0 |
| `rule_cases.total` | 13 |
| `rule_cases.placeholder` | 12 |
| `rule_cases.python` | 1 |
| `fixtures_not_in_set` | 1 |
| `fixture_configs` | 9 |
| `other_tests` | 7 |
| `s6_black_box` | 54 |
| `s6_internal` | 25 |

- Templater suite: the parametrize list of `test__templater_full` in
  `test/core/templaters/jinja_test.py` (`harness/templater.md`). Its helper
  `get_parsed` calls `Linter()` with no argument. `Linter()` makes its
  templater from the default config: `jinja` in `default_config.cfg`.
  `parse_path` also reads the config files of the folders of the file. It
  also reads the inline config of the file. But these cannot change the
  templater: `Linter.render_string` uses the templater of the `Linter`. Data
  (sqlfluff 4.4.0, `Linter().parse_path`): a `.sqlfluff` file in the folder
  of a file sets `templater = placeholder`. The output is the Jinja output
  and the warning "Attempt to set templater to placeholder failed. Using
  jinja templater." A file with the inline line
  `-- sqlfluff:templater:placeholder` also gives the Jinja output. The inventory
  reads the config of each case in this order: the config files of the root
  folders, the config files of each folder to the file, and the inline
  config. It records `core.templater` as `config_templater`. It stops with
  exit code 1 if a case sets a value that is not the templater of
  `Linter()`. No case sets it. Thus each case uses `jinja`, and 0 of 43
  cases use the placeholder or python templater. Each case is in the
  known-failure list of this stone with the reason `jinja: S11` (see item
  1). 3 cases also have the tag `needs_python` (`library_path`) of the
  templater suite.
- Nodes: `test/core/templaters/placeholder_test.py` and `python_test.py`. A
  node is `black_box` if its test function calls `process()` (the templater
  output or error). Else it is `internal`.
- Rule cases: the rule cases of the test harness that set `core.templater`
  in their `configs`. The cases with `placeholder`: AM04 3, AM07 1, CP02 4,
  CP02_LT01 1, RF03 1, ST10 1, and ST11 1. The case with `python`: JJ01
  `test_pass_python_templater`. The 9 `fixture_configs` are their 8 YAML
  files and `test/fixtures/config/placeholder/.sqlfluff-placeholder`. The
  owner of that file is the test conversion of S7 (CLI and config parity:
  the sqlfluff CLI, config, and Python rule tests as black-box cases; sqll
  passes 100% of the converted cases; cases that need the Jinja templater
  move to S11), because `loader_test.py` reads it.
- Fixture not in the set:
  `test/fixtures/templater/placeholder_flyway_var/placeholder_flyway_var_a.sql`.
  No test of sqlfluff 4.4.0 names its folder, and it has no expected output.
- Fail-closed checks: the inventory stops with exit code 1 if one of
  these is true:
  - A node has no test function.
  - A templater input of a node is not a literal, a parameter, a local
    literal, or `dict(...)`.
  - `get_parsed` does not call `Linter()` one time.
  - The config of a templater suite case sets a different templater.
  - A test file names these templaters and has no owner, or an owner names
    a file that does not name them.
  - A fixture file sets these templaters and has no owner.
  - A fixture in a non-Jinja folder has a user.
  - The rule case files are not the rule fixture files that set these
    templaters.

### Other test files

The owner "S7 test conversion" is the track S7-tests (the track that
converts the S7 tests to black-box cases (the test conversion of S7)), a
part of S7 (CLI and config parity: the sqlfluff CLI, config, and Python
rule tests as black-box cases; sqll passes 100% of the converted cases;
cases that need the Jinja templater move to S11).

| File | Owner | Reason |
|---|---|---|
| `test/core/config/fluffconfig_test.py` | S7 test conversion | Group `config` of results/S7-tests/scope.json: the templater selection by name |
| `test/core/config/loader_test.py` | S7 test conversion | Group `config`: the config loader and the context values of each templater |
| `test/core/linter/linter_test.py` | out of scope | python-internal: `Linter.render_string` with config objects and a log capture |
| `test/core/parser/lexer_test.py` | out of scope | python-internal: the lexer of `sqlfluff[rs]` on a `TemplatedFile` object |
| `test/utils/reflow/respace_test.py` | out of scope | `placeholder` is a layout type of a Jinja segment, not the templater |
| `test/core/parser/parity/cases_test.py` | out of scope | engine-comparison (owner decision of the binary test harness on `test/fixtures/parity/`); only `jinja` |
| `test/core/parser/parity/compare.py` | out of scope | the helper of the parity tests; it sets only `jinja` |

## Needs a Python runtime

G1 (lint parity with sqlfluff: sqll does all that the pinned sqlfluff
version does (dialects, rules, fixes, configuration, templaters), except
Python plugins and features that need a Python runtime. Only the human owner
approves each version change (the standing delegation keeps it). Parity is
the percentage of sqlfluff test cases that sqll passes through a binary. The
same harness runs sqlfluff, sqruff, and sqll) excludes features that need a
Python runtime. A node or case needs a Python runtime if the output that it
checks depends on one of these:

1. Python code: a module that the config loads (`library_path`), a
   templater that runs Python code of the user or of a Python package (the
   `dbt` templater, a templater plugin), or a function in the input that
   is not a constant function.
2. An object address, for example `<object at 0x7f3a...>` or `id()`.
3. A templater input (a context or config value) that is a Python object
   that `ast.literal_eval` of a config value cannot make, for example a
   `datetime` or a class instance.

`scripts/s6/s6common.py` (`runtime_needs`) and `unit_nodes.py` apply the
rule to the evaluated inputs and to the test source. The tag
`needs_python` of the templater suite of the test harness marks each case
with the `python` templater (`harness/templater.md`). This stone does not
use that part: STONES.md puts the Python format-string templater in this
stone. No templater suite case uses the `python` templater, so both rules
give the same 3 templater suite cases.

| Test function | Nodes | Kind | Needs a Python runtime |
|---|---|---|---|
| `placeholder_test.py::test__templater_raw` | 1 | black_box | no |
| `placeholder_test.py::test__templater_param_style` | 22 | black_box | no |
| `placeholder_test.py::test__templater_custom_regex` | 1 | black_box | no |
| `placeholder_test.py::test__templater_setup` | 1 | black_box | no |
| `placeholder_test.py::test__templater_styles` | 1 | black_box | no |
| `python_test.py::test__templater_python` | 1 | black_box | no |
| `python_test.py::test__templater_python_error` | 1 | black_box | no |
| `python_test.py::test__templater_python_large_file_check` | 1 | black_box | no |
| `python_test.py::test__templater_python_dot_notation_variables` | 12 | black_box | no |
| `python_test.py::test__templater_python_dot_notation_fail` | 2 | black_box | no |
| `python_test.py::test__templater_python_ignore_templating` | 11 | black_box | no |
| `python_test.py::test__templater_python_intermediate__trim` | 4 | internal | no |
| `python_test.py::test__templater_python_substring_occurrences` | 4 | internal | no |
| `python_test.py::test__templater_python_sorted_occurrence_tuples` | 3 | internal | no |
| `python_test.py::test__templater_python_slice_template` | 3 | internal | no |
| `python_test.py::test__templater_python_split_invariants` | 2 | internal | no |
| `python_test.py::test__templater_python_split_uniques_coalesce_rest` | 4 | internal | no |
| `python_test.py::test__templater_python_slice_file` | 5 | internal | no |

Data: each context and config value is a `str`, `int`, `bool`, `None`, or
a `dict` of these. The `slice_file` nodes give `lambda x: templated_file`,
a constant function of a parameter. No text has an object address. A
config file gives the same outputs. Real runs of `sqlfluff render` (4.4.0):
the `pyformat` node values `limit = 15` and `someflag = False` give
`LIMIT 15` and `someflag = False`; the python context `num = 123` and
`sqlfluff = {"foo.label": "café", "self.number": 42}` give `123.00`,
`'caf\xe9'`, and `0042` for `{num:.2f}`, `{foo.label!a}`, and
`{self.number!s:0>4}`.

## Internal nodes

The 25 internal nodes call internal functions of the Python templater
(`trim_ends`, `_substring_occurrences`, `_sorted_occurrence_tuples`,
`_slice_template`, `_split_invariants`, `_split_uniques_coalesce_rest`,
`slice_file`) with Python objects. A binary has no input for them.

- Option A (recommended): Rust unit tests of the ported slicer in
  `crates/sqll_templater/tests/`, with the same literal data and the
  source of each node (file, node id, MIT). A record gives each node and
  its Rust test. The report gives this number apart from the binary parity
  number. Also, the black-box cases check the source slices through the
  binary (see "Black-box form"). Thus the slicer has a binary check too.
- Option B: exclude the 25 nodes as `python-internal`, a class of the test
  conversion of S7 (CLI and config parity: the sqlfluff CLI, config, and
  Python rule tests as black-box cases; sqll passes 100% of the converted
  cases; cases that need the Jinja templater move to S11). The slicer then
  has only the binary check. A port error that the black-box cases do not
  show stays hidden.
- Option C: count them in the binary parity number through a test command
  of sqll. This adds a command that sqlfluff does not have. The same harness
  cannot run sqlfluff and sqruff on it, against G1 (lint parity with
  sqlfluff: sqll does all that the pinned sqlfluff version does (dialects,
  rules, fixes, configuration, templaters), except Python plugins and
  features that need a Python runtime. Only the human owner approves each
  version change (the standing delegation keeps it). Parity is the
  percentage of sqlfluff test cases that sqll passes through a binary. The
  same harness runs sqlfluff, sqruff, and sqll).

## Black-box form

- Recommended: use the case format, the runner (`sqll-harness s7 run`), and
  the trace oracle of the test conversion of S7 (CLI and config parity: the
  sqlfluff CLI, config, and Python rule tests as black-box cases; sqll
  passes 100% of the converted cases; cases that need the Jinja templater
  move to S11). Their source is `harness/sqll_harness/s7_tests` and
  [s7-tests-design.md](s7-tests-design.md). This stone adds a scope file
  (the `nodes` of `results/S6/scope.json`) and case files in
  `harness/sqll_harness/s6/`. It does not add a second runner. A case gives
  the SQL file, a `.sqlfluff` file, and the checks. The `.sqlfluff` file has
  the templater section, from the evaluated `context` and `config` of the
  node.
- The templated text: sqll has no `render` command. `render` is a part of
  S7 (CLI and config parity: the sqlfluff CLI, config, and Python rule tests
  as black-box cases; sqll passes 100% of the converted cases; cases that
  need the Jinja templater move to S11). The check is the concatenation of
  the raw leaves of `parse -f json`. Data (sqlfluff 4.4.0): the `colon` text
  of `test__templater_raw` has `{{blah}}`, `%(gnepr)s`, and `e~':'`. For
  this text, `parse` gives exit code 1 (unparsable), and the leaves give the
  full templated text. The node
  `test__templater_param_style[colon_simple_substitution]` of
  `placeholder_test.py` has the `colon` style and uses the values `user_id`
  and `start_date`. For its input text, with no change, the leaves equal the
  `render` output without its last newline.
- Source slices: `parse -f json -m` gives the source position of each leaf.
  Data: in the input text of that node, the leaf `'2021-10-01'` has 12
  code points. Its source range (`start_file_pos` to `end_file_pos`) is 114
  to 125 (`:start_date`, 11 code points). sqll `parse -m`
  gives no position keys now (`harness/sqll.md`). The sqll option is in
  `crates/sqll_cli`. That path is a path of the track S7-sqll (the track
  that makes sqll pass the converted S7 cases (the sqll part of S7)). Thus
  T9 (the templated text and source slices of sqll equal those of sqlfluff)
  of S6 (templater parity: sqll passes 100% of the placeholder and Python
  format-string templater fixtures that do not need a Python runtime) is
  cross-track.
- The trace oracle needs one more call map, from
  `<Templater>(override_context=C).process(in_str=S, config=F)` to a CLI
  case. The case has S as the file, and C and F in the config. A test that
  expects an error maps to the exit code and to the `TMP` violation or the
  error text.
- Alternative: compare with the output of `sqlfluff render`. sqll has no
  `render` command before S7 (CLI and config parity: the sqlfluff CLI,
  config, and Python rule tests as black-box cases; sqll passes 100% of the
  converted cases; cases that need the Jinja templater move to S11) is
  complete. Thus sqll cannot run these cases until then.

## Port

- Source: sqlfluff 4.4.0 `src/sqlfluff/core/templaters/placeholder.py` and
  `python.py` (MIT, Copyright (c) 2018-2026 Alan Cruickshank) to
  `crates/sqll_templater`, with a record in `crates/ported.json` and
  THIRD_PARTY.md. `crates/ported.json` and THIRD_PARTY.md are paths of the
  track core (the track that does S3b and owns the shared core). Thus each
  task that ports code to `crates/sqll_templater` is cross-track (the
  status file, column "Other tracks").
- Regex: the 12 `KNOWN_STYLES` patterns use the Python `regex` module
  (`regex.UNICODE`), a lookbehind, and a backreference
  (`colon_optional_quotes`: `\1`). `fancy-regex` is a workspace dependency
  (0.17.0) and supports both. A `param_regex` of the user with a feature
  that `fancy-regex` does not have fails closed (`unsupported`). A new
  dependency of `sqll_templater` changes its `Cargo.toml`, a path of the
  track core (the track that does S3b and owns the shared core).
- Python: the format mini-language (`str.format`, `!r`, `!s`, `!a`, the
  format spec), `repr`, `ascii`, and `ast.literal_eval` for the context
  values, in Rust. The source is CPython (PSF-2.0). The license text is
  already in `crates/LICENSE-cpython.txt`; the port adds its entry to
  THIRD_PARTY.md.
- sqruff 0.41.0 (`sqruff-lib`, Apache-2.0) has a placeholder templater in
  Rust (`src/templaters/placeholder.rs`, `fancy_regex`). Differences from
  sqlfluff 4.4.0 in its source:
  - `colon_optional_quotes` has the lookbehind `(?<!:)`; sqlfluff has
    `(?<![:\w\x5c])`.
  - It has 2 more styles, `at` and `apache_camel`.
  - Other error texts, for example "Both param_regex and param_style were
    provided to the placeholder templater." (sqlfluff: "Either param_style
    or param_regex must be provided, not both").
  - Its `flyway_var` unit test uses `${flywaydatabase}`, not
    `${flyway:database}`.
  Its python templater calls the Python module
  `sqruff.templaters.python_templater` through pyo3 (feature `python`).
  Recommendation: port from sqlfluff, the reference of G1 (lint parity with
  sqlfluff: sqll does all that the pinned sqlfluff version does (dialects,
  rules, fixes, configuration, templaters), except Python plugins and
  features that need a Python runtime. Only the human owner approves each
  version change (the standing delegation keeps it). Parity is the
  percentage of sqlfluff test cases that sqll passes through a binary. The
  same harness runs sqlfluff, sqruff, and sqll), with one license (MIT). Do
  not port from sqruff.

## Speed

This section is for G3 (speed: each command, start time included, is as fast
as reasonably possible and has a benchmark that measures sqlfluff, sqruff,
and sqll on the same input. sqll is faster than sqlfluff on each benchmark,
not slower than sqruff on any benchmark, and faster than sqruff on the total
of all benchmarks. A change that makes a benchmark slower gives the reason.
Correctness is more important than speed: do not make a result wrong to make
it fast).

- No benchmark of S2 (benchmarks: a benchmark for each command (start,
  parse, lint, fix) with small, medium, and large inputs for each dialect;
  one command gives a machine-readable report for sqlfluff,
  `sqlfluff[rs]`, and sqruff, and the baseline is recorded) uses these
  templaters: all use `templater = raw` (`harness/bench.md`, "Settings").
- T10 (each templater benchmark measures sqlfluff, sqruff, and sqll on the
  same input; sqll is faster than sqlfluff on each and not slower than
  sqruff on any, and a slower benchmark has its reason) of S6 (templater
  parity: sqll passes 100% of the placeholder and Python format-string
  templater fixtures that do not need a Python runtime) adds
  templater benchmarks: `parse`, `lint`, and `fix` with the placeholder
  templater and with the python templater, small, medium, and large, for
  sqlfluff, sqruff, and sqll. The benchmarks are paths of the track core
  (the track that does S3b and owns the shared core): cross-track.
- sqruff 0.41.0 runs the placeholder templater in Rust. Its python
  templater needs Python through pyo3; the harness builds sqruff with the
  features `parser` and `python` (`tools/sqruff/install.sh`). Thus sqruff
  can run both benchmarks, and its python benchmark includes the start of
  Python.
- Each pull request of this stone gives the `bench compare` result. A
  slower benchmark needs a reason, by G3 (speed: each command, start time
  included, is as fast as reasonably possible and has a benchmark that
  measures sqlfluff, sqruff, and sqll on the same input. sqll is faster than
  sqlfluff on each benchmark, not slower than sqruff on any benchmark, and
  faster than sqruff on the total of all benchmarks. A change that makes a
  benchmark slower gives the reason. Correctness is more important than
  speed: do not make a result wrong to make it fast).

## Paths

`tracks.yml` gives S6 (templater parity: sqll passes 100% of the
placeholder and Python format-string templater fixtures that do not need a
Python runtime) these paths: `status/S6.md`, `ci/matrix.d/S6.json`,
`results/S6/**`, `crates/sqll_templater/src/**`,
`crates/sqll_templater/tests/**`, `docs/decisions/s6-*.md`,
`scripts/s6/**`, `harness/sqll_harness/s6/**`,
`harness/tests/test_s6_*.py`, and `harness/tests/fixtures/s6/**`.
`harness/tests/test_s6_scope.py` fails if `scope.json` is not the output
of the inventory, if a count in this record or in the status file is not
the count of `scope.json`, or if a number in the prose of "Decisions",
"Set", "Internal nodes", or the tasks table of the status file is not the
number of `scope.json`. It also fails if the column "Other tracks" of the
tasks table does not give the owner (`ci/ownership.py`, `owner`) of each
path that a task changes (`TASK_PATHS`), if a task of that table has no
entry in `TASK_PATHS`, or if a path in that column is not a path of the
track that the cell names.
