# S6 decision: the templater design

Status: proposed (2026-11-11). The orchestrator decides the 6 items for
the human owner (standing delegation, CONSTITUTION.md section 5). No item
is for the human owner. Written in T1 (design record, fixture set from the
data, status file, and track paths: the S6 scope and design are recorded
and tested). Scope: STONES.md S6 (templater parity: sqll passes 100% of
the placeholder and Python format-string templater fixtures that do not
need a Python runtime). Goals: G1 (lint parity with sqlfluff: a
percentage of sqlfluff test cases, run through a binary; G1.3 excludes
features that need a Python runtime), G3 (speed: sqll faster than sqlfluff
on each benchmark, not slower than sqruff, no slowdown without a reason),
G4 (verification first). Plan and tasks: [status/S6.md](../../status/S6.md).

## Decisions

Each item has a recommendation, the other options, and the data. The
orchestrator writes its decision and the date here and in the status file.

1. The set (see "Set"). Recommendation: the S6 parity number is the 54
   black-box nodes of the placeholder and Python templater tests. The 25
   internal nodes are a separate number (item 3). The 13 rule fixture cases
   have their exit in S5 (rule parity: 100% of the rule fixtures, lint and
   fix); S6 checks their templated text and source slices. The 43 cases of
   the templater suite of S1 (binary test harness) are Jinja cases and go
   to S11 (Jinja templater: the last stone). Other option: count only the
   54 black-box nodes and drop the internal nodes. Data: "Set".
2. The rule "needs a Python runtime" (see that section). Recommendation:
   accept the rule. It classifies 0 of 79 nodes as "needs a Python
   runtime".
3. The 25 internal nodes. Recommendation: option A (see "Internal nodes").
4. The black-box form. Recommendation: the S7-tests case format, runner,
   and trace oracle, with an S6 scope file (see "Black-box form").
5. The port source and license. Recommendation: port sqlfluff
   `placeholder.py` and `python.py` (MIT) to Rust (see "Port").
6. G3. Recommendation: new templater benchmarks in T10 (see "G3").

## Set

`scripts/s6/inventory.py` makes
[results/S6/scope.json](../../results/S6/scope.json) from the pinned
sqlfluff 4.4.0 (commit `0348222a`). It reads the submodule in place. It
collects the pytest nodes with `pytest --collect-only` in the Python of
the sqlfluff oracle tools (`scripts/s6/unit_nodes.py`). It runs no test.

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
  `get_parsed` calls `Linter()` with no argument. Thus each case uses the
  default templater of `default_config.cfg`, `jinja`. 0 of 43 cases use
  the placeholder or python templater. Each case is in the S6
  known-failure list with the reason `jinja: S11`. 3 cases also have the
  S1 tag `needs_python` (`library_path`).
- Nodes: `test/core/templaters/placeholder_test.py` and `python_test.py`.
  A node is `black_box` if its test function calls `process()` (the
  templater output or error). Else it is `internal`.
- Rule cases: the S1 rule cases whose `configs` set `core.templater` to
  `placeholder` (AM04 3, AM07 1, CP02 4, CP02_LT01 1, RF03 1, ST10 1,
  ST11 1) or `python` (JJ01 `test_pass_python_templater`). The 9
  `fixture_configs` are their 8 YAML files and
  `test/fixtures/config/placeholder/.sqlfluff-placeholder` (S7 test
  conversion, `loader_test.py`).
- Fixture not in the set:
  `test/fixtures/templater/placeholder_flyway_var/placeholder_flyway_var_a.sql`.
  No test of sqlfluff 4.4.0 names its folder, and it has no expected output.
- Fail-closed checks: the inventory stops with exit code 1 if a node has
  no test function, if a templater input of a node is not a literal, a
  parameter, a local literal, or `dict(...)`, if `get_parsed` does not call
  `Linter()` once, if a test file names these templaters and has no owner
  (or an owner names a file that does not), if a fixture file sets these
  templaters and has no owner, if a fixture in a non-Jinja folder has a
  user, or if the rule case files are not the rule fixture files that set
  these templaters.

### Other test files

| File | Owner | Reason |
|---|---|---|
| `test/core/config/fluffconfig_test.py` | S7 test conversion | Group `config` of results/S7-tests/scope.json: the templater selection by name |
| `test/core/config/loader_test.py` | S7 test conversion | Group `config`: the config loader and the context values of each templater |
| `test/core/linter/linter_test.py` | out of scope | python-internal: `Linter.render_string` with config objects and a log capture |
| `test/core/parser/lexer_test.py` | out of scope | python-internal: the lexer of `sqlfluff[rs]` on a `TemplatedFile` object |
| `test/utils/reflow/respace_test.py` | out of scope | `placeholder` is a layout type of a Jinja segment, not the templater |
| `test/core/parser/parity/cases_test.py` | out of scope | engine-comparison (S1, binary test harness: owner decision on `test/fixtures/parity/`); only `jinja` |
| `test/core/parser/parity/compare.py` | out of scope | the helper of the parity tests; it sets only `jinja` |

## Needs a Python runtime

G1.3 excludes features that need a Python runtime. A node or case needs a
Python runtime if the output that it checks depends on one of these:

1. Python code: a module that the config loads (`library_path`), a
   templater that runs Python code of the user or of a Python package (the
   `dbt` templater, a templater plugin), or a function in the input that
   is not a constant function.
2. An object address, for example `<object at 0x7f3a...>` or `id()`.
3. A templater input (a context or config value) that is a Python object
   that `ast.literal_eval` of a config value cannot make, for example a
   `datetime` or a class instance.

`scripts/s6/s6common.py` (`runtime_needs`) and `unit_nodes.py` apply the
rule to the evaluated inputs and to the test source. The S1 tag
`needs_python` marks each case with the `python` templater
(`harness/templater.md`). S6 does not use that part: STONES.md puts the
Python format-string templater in S6. No S1 templater case uses the
`python` templater, so both rules give the same 3 S1 cases.

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
- Option B: exclude the 25 nodes as `python-internal` (the S7 class). The
  slicer then has only the binary check. A port error that the black-box
  cases do not show stays hidden.
- Option C: count them in the binary parity number through a test command
  of sqll. This adds a command that sqlfluff does not have, and the same
  harness cannot run sqlfluff and sqruff on it (G1.6: the same harness
  runs sqlfluff, sqruff, and sqll).

## Black-box form

- Recommended: the case format, the runner (`sqll-harness s7 run`), and
  the trace oracle of the S7 test conversion
  (`harness/sqll_harness/s7_tests`,
  [s7-tests-design.md](s7-tests-design.md)), with an S6 scope file (the
  `nodes` of `results/S6/scope.json`) and S6 case files in
  `harness/sqll_harness/s6/`. Not a second runner. A case gives the SQL
  file, a `.sqlfluff` file with the templater section (from the evaluated
  `context` and `config` of the node), and the checks.
- The templated text: sqll has no `render` command (`render` is S7: CLI
  and config parity). The check is the concatenation of the raw leaves of
  `parse -f json`. Data (sqlfluff 4.4.0): for the `colon` text of
  `test__templater_raw` (`{{blah}}`, `%(gnepr)s`, `e~':'`), `parse` gives
  exit code 1 (unparsable), and the leaves give the full templated text.
  For a `colon` file with 2 values, the leaves equal the `render` output.
- Source slices: `parse -f json -m` gives the source position of each
  leaf. Data: in the file above, the leaf `'2021-10-01'` (12 code points)
  has the source range 68 to 79 (`:start_date`, 11 code points). sqll
  `parse -m` gives no position keys now (`harness/sqll.md`). The sqll
  option is in `crates/sqll_cli` (track S7-sqll: the sqll part of S7), so
  T9 (the templated text and source slices of sqll equal those of
  sqlfluff) is cross-track.
- The trace oracle needs one more call map: `<Templater>(override_context=C)
  .process(in_str=S, config=F)` to a CLI case with S as the file and C
  and F in the config. A test that expects an error maps to the exit code
  and the `TMP` violation or the error text.
- Alternative: compare with `sqlfluff render` output. sqll has no
  `render` command before S7, so sqll cannot run these cases until then.

## Port

- Source: sqlfluff 4.4.0 `src/sqlfluff/core/templaters/placeholder.py` and
  `python.py` (MIT, Copyright (c) 2018-2026 Alan Cruickshank) to
  `crates/sqll_templater`, with a record in `crates/ported.json` and
  THIRD_PARTY.md (Core paths: cross-track).
- Regex: the 12 `KNOWN_STYLES` patterns use the Python `regex` module
  (`regex.UNICODE`), a lookbehind, and a backreference
  (`colon_optional_quotes`: `\1`). `fancy-regex` is a workspace dependency
  (0.17.0) and supports both. A `param_regex` of the user with a feature
  that `fancy-regex` does not have fails closed (`unsupported`). A new
  dependency of `sqll_templater` changes its `Cargo.toml` (a Core path).
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
  Recommendation: port from sqlfluff, the reference of G1, with one
  license (MIT). Do not port from sqruff.

## G3

- No S2 benchmark (benchmarks: start, parse, lint, and fix for each tool
  and dialect) uses these templaters: all use `templater = raw`
  (`harness/bench.md`, "Settings").
- T10 (each templater benchmark measures sqlfluff, sqruff, and sqll, and
  sqll meets G3) adds templater benchmarks: `parse`, `lint`, and `fix` with the
  placeholder templater and with the python templater, small, medium, and
  large, for sqlfluff, sqruff, and sqll. This is a Core change of the
  benchmarks (cross-track).
- sqruff 0.41.0 runs the placeholder templater in Rust. Its python
  templater needs Python through pyo3; the harness builds sqruff with the
  features `parser` and `python` (`tools/sqruff/install.sh`). Thus sqruff
  can run both benchmarks, and its python benchmark includes the start of
  Python.
- Each S6 pull request gives the `bench compare` result. A slower
  benchmark needs a reason (G3.6: a change that makes a benchmark slower
  gives the reason).

## Paths

`tracks.yml` gives S6 these paths: `status/S6.md`, `ci/matrix.d/S6.json`,
`results/S6/**`, `crates/sqll_templater/src/**`,
`crates/sqll_templater/tests/**`, `docs/decisions/s6-*.md`,
`scripts/s6/**`, `harness/sqll_harness/s6/**`,
`harness/tests/test_s6_*.py`, and `harness/tests/fixtures/s6/**`.
`harness/tests/test_s6_scope.py` fails if `scope.json` is not the output
of the inventory, or if a count in this record or in the status file is
not the count of `scope.json`.
