# Third-party code and test data

## sqll

sqll is under the MIT license: `LICENSE`, "Copyright (c) 2026 The sqll
authors". Each crate in `crates/` has `license = "MIT"`. `sqll --license`
prints the sqll license and the notices of the code in the binary: the
sqlfluff MIT notice, the CPython license, the tomli and PyYAML MIT
licenses, the Rust MIT notice, and the dependency notice list ("Rust"). The decision and its reasons:
`status/S3.md`, "License decision (T19)".

## sqlfluff

- Source: https://github.com/sqlfluff/sqlfluff
- Version: tag `4.4.0`, commit `0348222a3bcdb0226563f7349c5a39beb0641955`
- License: MIT. Copyright (c) 2018-2026 Alan Cruickshank. See
  `third_party/sqlfluff/LICENSE.md`.
- Path: `third_party/sqlfluff` (git submodule). We do not change these files.

Test data that the harness reads:

- `test/fixtures/dialects/`: SQL files and expected parse trees. The S2
  benchmark inputs are made from these SQL files (MIT) at run time
  (`sqll-harness bench inputs`, `harness/bench.md`); the repository has no
  copy. `harness/sqll_harness/bench/` stores only their fixture paths and
  the sha256, bytes, and lines of each input.
- `test/fixtures/rules/std_rule_cases/`: rule cases (SQL, config, lint and
  fix results).
- `test/fixtures/linter/autofix/`: autofix cases (SQL before and after the
  fix, config, violations).
- `test/fixtures/templater/`: templater cases (SQL, config, macros,
  libraries, parse trees).
- `test/core/templaters/jinja_test.py`: the case table of
  `test__templater_full`. The harness reads only its literal list.

`scripts/sqlfluff-dialect-oracle` imports and runs
`test/dialects/dialects_test.py`, `test/conftest.py`, and
`test/core/parser/parity/corpus_test.py` from the submodule.
`scripts/sqlfluff-autofix-oracle` imports and runs
`test/rules/std_fix_auto_test.py` from the submodule.
`scripts/sqlfluff-templater-oracle` imports and runs
`test/core/templaters/jinja_test.py` and `test/conftest.py` from the
submodule. `scripts/sqlfluff-case-ids` runs `pytest --collect-only` on
`test/dialects/dialects_test.py`, `test/rules/yaml_test_cases_test.py`,
`test/rules/std_fix_auto_test.py`, and `test/core/templaters/jinja_test.py`
from the submodule. The harness does not.

`results/s3/sqruff-rule-types.json` (`sqlfluff_types`) has the segment type
names of the sqlfluff 4.4.0 dialects and segment classes.
`scripts/s3/sqruff_rules.py` reads them from the installed sqlfluff package.
No sqlfluff code is copied.

`scripts/s3b/source_map_oracle.py` (S3b task C8) imports and runs the
installed sqlfluff 4.4.0 package (MIT): its `TemplatedFile` and its
templaters, on the fixtures of `test/fixtures/templater/`.
`results/S3b/C8-source-map.json` has its output for `jinja_a/jinja.sql`
and `jinja_b/jinja.sql`: the templated texts, the slices, the source
ranges, lines, and positions, and the segment types. It has no source text
of the fixtures; the tests read the submodule. The random files of its
`check` are invented, not sqlfluff data. No sqlfluff code is copied.

`scripts/s3b/config_oracle.py` (S3b task C11) imports and runs the
installed sqlfluff 4.4.0 package (MIT): its config reader, its templaters,
and its `parse` command. It reads the config fixtures of
`test/fixtures/config/`, `tox.ini`, `pyproject.toml`, and
`src/sqlfluff/core/default_config.cfg` of the submodule, and the dialect
fixtures. `results/S3b/C11-config.json` has its output: the values of the
default config, the dicts that sqlfluff reads from these files (the record
names each file; it has no copy of a file), and the output of
`sqlfluff parse` for invented files. The tests copy the cited fixture files
of the submodule into a temporary folder. No sqlfluff code is copied.

`scripts/s3b/cli_oracle.py` (S3b task C13) runs the `sqlfluff` command of
the installed sqlfluff 4.4.0 package (MIT): `lint`, `fix`, `rules`, and
`dialects`, on invented files and on the pinned fixtures
`test/fixtures/dialects/sparksql/select_div.sql` and
`test/fixtures/linter/parse_lex_error.sql`.
`results/S3b/C13-cli.json` has, for each scenario, the input files (with
the text of these fixtures), the arguments, and the stdout, stderr, exit
code, and changed files of sqlfluff. The stdout of the scenario
"rules default" is the rules table of sqlfluff (the code, name, and
description of each rule). No sqlfluff code is copied.

`scripts/s3b/jinja_raw_oracle.py` (S3b task C14) imports and runs the
installed sqlfluff 4.4.0 package (MIT): `JinjaTemplater`, `RawTemplater`,
`Linter._normalise_newlines`, and `FluffConfig`. It reads the rule
fixtures of `test/fixtures/rules/std_rule_cases/` and the autofix fixtures
of `test/fixtures/linter/autofix/` through the harness suites, and the
root config of the submodule. `results/S3b/C14-jinja-raw.json` has only
sha256 values of fixture texts and counts. It has no fixture text. No
sqlfluff code is copied.

`harness/sqll_harness/s7_tests/cases/` (S7: CLI and config parity, the
sqlfluff CLI, config, and Python rule tests as black-box cases; track
S7-tests) has the black-box cases of the sqlfluff 4.4.0 tests (MIT). They
are a derived work of the test files of `test/cli/`, `test/rules/`,
`test/core/config/`, `test/core/helpers/`, and `test/core/linter/`: the
inline SQL, the CLI arguments, the config, and the expected values. The
header of each case file names its source test file, the sqlfluff version
and commit, the copyright, and the MIT license.
`harness/sqll_harness/s7_tests/exclusions.yml` names the excluded test
nodes, and `results/S7-tests/scope.json` names each test node in scope.
`sqll-harness s7 run` runs the cases on the fixture files of
`test/fixtures/` in place (for example `test/fixtures/linter/` and
`test/fixtures/config/`); it does not copy them. It reads the source of
each converted test file with `ast` to find its asserts. The S7 scripts
`scripts/s7-tests/inventory` and `scripts/s7-tests/config-readers` collect
and run the sqlfluff tests, and `scripts/s7-tests/trace-nodes` runs the
converted test nodes, from the submodule. `results/S7-tests/` has their
output: node ids, counts, and the inputs and outputs of the traced CLI and
simple-API calls (`oracle-trace-*.json`). No sqlfluff code is copied.

`scripts/s6/inventory.py` and `scripts/s6/unit_nodes.py` (track S6; task
T1 (the S6 scope and design are recorded and tested) of S6 (templater
parity: sqll passes 100% of the placeholder and Python format-string
templater fixtures that do not need a Python runtime)) read the sqlfluff
4.4.0 tests (MIT) of the submodule in place. `unit_nodes.py` runs
`pytest --collect-only` on `test/core/templaters/placeholder_test.py` and
`test/core/templaters/python_test.py` with the Python of the sqlfluff
oracle tools. The collection imports these test modules, but it runs no
test. It reads the source of these test files with `ast` to find the
templater inputs of each node. It imports the templater classes of the
installed sqlfluff 4.4.0 package (MIT) only for their method names. `inventory.py` also
reads the templater suite, the rule fixtures, the config fixtures, and the
other test files that name these templaters. `results/S6/scope.json` has
their output: the pytest node ids (some ids have the inline SQL of the
tests), the literal context and config values of each node, the case ids
of the templater suite and of the rule cases, and the paths of fixture and
test files. Its key `license` gives the license and the copyright line of
`third_party/sqlfluff/LICENSE.md`. It has no copy of a fixture file. No
sqlfluff code is copied.

`scripts/s3/sqlfluffrs_probe.py` (S3 research, task T5) copies the
submodule into a scratch folder, runs `utils/rustify.py` there, and builds
the sqlfluffrs crates and the probe there. The generated Rust files stay in
the scratch folder; the repository has no copy.
`results/s3/sqlfluffrs-probe-build.json` has only their paths, sizes, and
sha256, the crate names of `cargo tree`, and test names and counts.
`scripts/s3/probe-sqlfluffrs/Cargo.lock` has the crate versions of
`sqlfluffrs/Cargo.lock`. The probe is research code, not sqll.

`scripts/s3/base_native_tests.py` (S3 task T18) copies the submodule into
a scratch folder, generates the tables there as `scripts/build-sqll` does,
and runs `cargo test` of the sqlfluffrs workspace there. The generated
files stay in the scratch folder. `results/s3/base-native-tests.json` and
`results/s3/base-native-tests.log` have the cargo output: the names of the
crates, test files, and tests, and the results. No sqlfluffrs code is
copied there.

`scripts/s3/license_size.py` (S3 research, task T7) generates the
sqlfluffrs tables in a scratch copy, as T5; the generated files stay there.
`results/s3/license-size-sources.json` has the text of the license files of
the submodule (MIT), the names, versions, and license fields of the
dependencies of the sqlfluffrs workspace (cargo metadata), the license
metadata of the Python packages of the sqlfluff tool venv, and line counts.
`results/s3/license-size.json` (task T7) has the first line and the
copyright line of `LICENSE.md` and `sqlfluffrs/LICENSE.md`, and it quotes
the MIT condition
("The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.").
`results/s3/license-size-sources.json` and `results/s3/license-size.json`
quote one declaration line of
`sqlfluffrs/sqlfluffrs_parser/src/parser/arena.rs` (MIT):
`pub fn is_type(&self, id: NodeId, target: &str) -> bool {`.
`results/s3/license-size.json` also has this line in the text of
`structure.rules`. No other sqlfluffrs code is copied.

`scripts/s3/capabilities.py` (S3 research, task T8) runs the help commands
of the pinned sqlfluff and reads the click objects, the templaters, the
placeholder styles, and the default config keys of the tool venv.
`results/s3/capabilities-sources.json` has the help text of each sqlfluff
4.4.0 command, and the 12 placeholder style regexes and the default config
key names of sqlfluff 4.4.0. `results/s3/capabilities.json` has the option
names, the placeholder regexes, the config key names, and cited lines
(with the file, the line numbers, and the sha256; at most 8 lines of a
file in one entry) of these submodule files: `src/sqlfluff/core/templaters/` (`__init__.py`,
`base.py`, `jinja.py`, `python.py`, `placeholder.py`),
`src/sqlfluff/core/config/` (`loader.py`, `ini.py`, `toml.py`,
`fluffconfig.py`), `src/sqlfluff/core/linter/discovery.py`,
`plugins/sqlfluff-templater-dbt/sqlfluff_templater_dbt/templater.py`,
`plugins/sqlfluff-templater-sqlmesh/sqlfluff_templater_sqlmesh/templater.py`,
`test/cli/commands_test.py` (line 1), and of the sqlfluffrs files
`sqlfluffrs_types/src/templater/` (`mod.rs`, `templatefile.rs`,
`fileslice.rs`), `sqlfluffrs_types/src/config/fluffconfig.rs`,
`sqlfluffrs_lexer/src/lexer.rs` (`LexInput`),
`sqlfluffrs_parser/src/parser/types.rs`, and
`sqlfluffrs_parser/src/parser/core.rs`. These are facts for the S3
decision, not sqll code.

Ported code (MIT, attribution in each file header):

| sqll file | sqlfluff source |
|---|---|
| `harness/sqll_harness/compare.py` | `test/conftest.py` (`process_struct`, `load_yaml`), `test/dialects/dialects_test.py` (empty-tree rule) |
| `harness/sqll_harness/suites/dialects.py` | `test/conftest.py` (`get_parse_fixtures`, `DEEP_PARSE_DEPTH_OVERRIDES`) |
| `harness/sqll_harness/suites/rules.py` | `src/sqlfluff/utils/testing/rules.py` (`load_test_cases`, `_setup_config`, `assert_rule_fail_in_sql`, `assert_rule_pass_in_sql`, `prep_violations`, `rules__test_helper`) |
| `harness/sqll_harness/suites/autofix.py` | `test/rules/std_fix_auto_test.py` (`test_cases`, `auto_fix_test`) |
| `harness/sqll_harness/suites/templater.py` | `test/core/templaters/jinja_test.py` (`get_parsed`, `assert_structure`, `test__templater_full`) |
| `harness/sqll_harness/code_only.py` | `src/sqlfluff/core/parser/segments/base.py` (`to_tuple`, `structural_simplify`, `is_code`), and the `is_code` and `is_meta` values of the segment classes |
| `harness/sqll_harness/adapters/config_files.py` | `src/sqlfluff/core/config/` (`load_config_up_to_path`, `load_config_at_path`, `_resolve_paths_in_config`, `load_ini_string`), `src/sqlfluff/core/helpers/file.py` (`iter_intermediate_paths`) |
| `scripts/sqlfluff_oracle.py` | `test/conftest.py` (`fail_on_parse_error_after_fix`) |
| `scripts/sqlfluff-autofix-oracle` | `test/rules/std_fix_auto_test.py` (`test_cases`) |
| `crates/sqll_syntax/src/parse.rs` | The lexer and parser calls and the limits of the T5 probe (row below): `sqlfluffrs/src/test_harness.rs` (`FixtureTest::run`), `sqlfluffrs/sqlfluffrs_parser/src/parser/python.rs` (`PyParser` limits), `src/sqlfluff/core/default_config.cfg` (the parse limits and indentation defaults). The message of an unparsable section: `src/sqlfluff/core/linter/linter.py` (`Linter.parse_rendered`). S3b C9 moved the calls and limits from `crates/sqll/src/parse.rs` |
| `scripts/s3/probe-sqlfluffrs/src/main.rs` | S3 research code, not sqll: `sqlfluffrs/src/test_harness.rs` (`FixtureTest::run`), `sqlfluffrs/sqlfluffrs_parser/src/parser/python.rs` (`PyParser` limits), `src/sqlfluff/core/default_config.cfg` (the parse limits and indentation defaults) |
| `crates/sqll/tests/cli.rs` | `test/conftest.py` (`process_struct`) |
| `scripts/s3b/tree-cost/src/main.rs` | S3b C4 measurement, not sqll: the lexer and parser calls and the limits of `crates/sqll/src/parse.rs` before S3b C9 (now `crates/sqll_syntax/src/parse.rs`, row above) |
| `crates/sqll_tree/build/kinds.rs` | The node construction rules of `sqlfluffrs/sqlfluffrs_parser` as `crates/sqll_parser` has them: `src/parser/match_result.rs` (`MatchResult::apply`, `token_to_node`, `MatchedClass`), `src/parser/core.rs` (the terminal parser handlers, `aux_block_bounds`, `read_string_ids_from_aux`), `src/parser/table_driven/ref_grammar.rs` (`build_ref_wrap`) |
| `scripts/s3b/convert-cost/src/main.rs` | S3b C7 measurement, not sqll: the lexer and parser calls and the limits of `crates/sqll/src/parse.rs` before S3b C9 (now `crates/sqll_syntax/src/parse.rs`, row above) |
| `crates/sqll_source/src/map.rs` | `sqlfluffrs/sqlfluffrs_types/src/templater/templatefile.rs`: the slice search of `find_slice_indices_of_templated_pos` and the rule for an empty slice of `templated_slice_to_source_slice` (S3b C8) |
| `crates/sqll_templater/src/raw.rs` | `src/sqlfluff/core/templaters/base.py` (`RawTemplater.process`) (S3b C8) |
| `crates/sqll_config/src/value.rs` | `src/sqlfluff/core/config/ini.py` (`coerce_value`) (S3b C11) |
| `crates/sqll_config/src/dict.rs` | `src/sqlfluff/core/helpers/dict.py` (`nested_combine`, `records_to_nested_dict`, `iter_records_from_nested_dict`) (S3b C11) |
| `crates/sqll_config/src/ini.rs` | `src/sqlfluff/core/config/ini.py` (`load_ini_string`) (S3b C11; also CPython below) |
| `crates/sqll_config/src/toml.rs` | `src/sqlfluff/core/config/toml.py` (`load_toml_file_config` and its helpers) (S3b C11; also tomllib below) |
| `crates/sqll_config/src/defaults.rs` | The values of `src/sqlfluff/core/default_config.cfg` (S3b C11) |
| `crates/sqll_config/src/validate.rs` | `src/sqlfluff/core/config/validate.py` and `removed.py` (S3b C11) |
| `crates/sqll_config/src/loader.rs` | `src/sqlfluff/core/config/loader.py`, `file.py`, and `src/sqlfluff/core/helpers/file.py` (`iter_intermediate_paths`) (S3b C11) |
| `crates/sqll_config/src/config.rs` | `src/sqlfluff/core/config/fluffconfig.py` (`FluffConfig`, parts) and `src/sqlfluff/core/helpers/string.py` (`split_comma_separated_string`) (S3b C11) |
| `crates/sqll_lint/src/rule.rs` | `src/sqlfluff/core/rules/base.py` (`BaseRule`, `LintResult`) and `crawlers.py` (`RootOnlyCrawler`, `SegmentSeekerCrawler`, `passes_filter`) (S3b C12) |
| `crates/sqll_lint/src/config.rs` | `src/sqlfluff/core/rules/base.py` (`RuleSet._validate_config_options`, the rule keyword arguments of `get_rulepack`) and `src/sqlfluff/core/helpers/string.py` (`split_comma_separated_string`) (S3b C12) |
| `crates/sqll_lint/src/fix.rs` | `src/sqlfluff/core/rules/fix.py` (`LintFix`), `rules/base.py` (`discard_unsafe_fixes`), and `linter/fix.py` (`AnchorEditInfo`, `compute_anchor_edit_info`) (S3b C12) |
| `crates/sqll_lint/src/registry.rs` | `src/sqlfluff/core/rules/base.py` (`rule_reference_map`, `_expand_rule_refs`, `get_rulepack`) (S3b C12) |
| `crates/sqll_lint/src/linter.rs` | `src/sqlfluff/core/linter/linter.py` (`lint_fix_parsed`, `remove_templated_errors`), `linted_file.py` (`deduplicate_in_source_space`), and `rules/base.py` (`crawl`, `_process_lint_result`) (S3b C12) |
| `crates/sqll_cli/src/color.rs` | `src/sqlfluff/core/types.py` (`Color`), `src/sqlfluff/cli/formatters.py` (`should_produce_plain_output`, `colorize_helper`), and the log line of `set_logging_level` in `src/sqlfluff/cli/commands.py` (S3b C13) |
| `crates/sqll_cli/src/text.rs` | `src/sqlfluff/cli/helpers.py` (`wrap_field`, `pad_line`) and `src/sqlfluff/cli/formatters.py` (`cli_table_row`, `cli_table`, `split_string_on_spaces`) (S3b C13; also CPython below) |
| `crates/sqll_cli/src/info.rs` | `src/sqlfluff/cli/commands.py` (`rules`, `dialects`), `src/sqlfluff/cli/formatters.py` (`format_rules`, `_format_rule_description`, `format_dialects`), and the dialect names of `dialect_readout` (S3b C13) |
| `crates/sqll_cli/src/lint/mod.rs` | `src/sqlfluff/cli/commands.py` (`get_config`, `lint`, `fix`, `_paths_fix`, `_stdin_fix`, `_handle_unparsable`, `do_fixes`), `src/sqlfluff/cli/outputstream.py` (`OutputPolicy`), `src/sqlfluff/cli/formatters.py` (`print_out_residual_error_counts`, `completion_message`), `src/sqlfluff/core/linter/linter.py` (`lint_paths`), `linted_dir.py` and `linting_result.py` (the counts), `linted_file.py` (`persist_tree`, `_safe_create_replace_file`) (S3b C13) |
| `crates/sqll_cli/src/lint/file.rs` | `src/sqlfluff/core/linter/linter.py` (`load_raw_file_and_config`, `render_string`, `parse_rendered`, `lint_parsed`), `runner.py` (`iter_rendered`, `iter_partials`), `linted_file.py` (`deduplicate_in_source_space`, `get_violations`), `src/sqlfluff/core/errors.py` (`ignore_if_in`, `warning_if_in`) (S3b C13) |
| `crates/sqll_cli/src/lint/files.rs` | `src/sqlfluff/core/linter/discovery.py` (`paths_from_path`, `_iter_files_in_path`) (S3b C13) |
| `crates/sqll_cli/src/lint/record.rs` | `src/sqlfluff/core/errors.py` (`to_dict`), `src/sqlfluff/core/rules/fix.py` (`LintFix.to_dict`), `src/sqlfluff/core/linter/linted_dir.py` (`LintedDir.add`), `src/sqlfluff/cli/commands.py` (`lint`: the github formats), `src/sqlfluff/cli/formatters.py` (`format_filename`, `format_violation`, `_format_file_violations`) (S3b C13) |
| `crates/sqll_lint/src/sqlfluff.rs` | The rule manifest (code, name, description, groups, aliases, phase, config keywords) of `src/sqlfluff/rules/` and the validation lists of the rule config info, as data (S3b C12, `scripts/s3b/rules_oracle.py`) |

## sqlfluffrs in crates/

The sqll engine crates are a port of the sqlfluffrs crates of sqlfluff.

- Source: https://github.com/sqlfluff/sqlfluff, folder `sqlfluffrs/`.
- Version: tag `4.4.0`, commit `0348222a3bcdb0226563f7349c5a39beb0641955`
  (the submodule).
- License: MIT. Copyright (c) 2018-2026 Alan Cruickshank. The license text
  is in `crates/LICENSE-sqlfluffrs.md`, a copy of `sqlfluffrs/LICENSE.md`.

| sqll crate | Source crate |
|---|---|
| `crates/sqll_types` | `sqlfluffrs/sqlfluffrs_types` |
| `crates/sqll_lexer` | `sqlfluffrs/sqlfluffrs_lexer` |
| `crates/sqll_parser` | `sqlfluffrs/sqlfluffrs_parser` |
| `crates/sqll_dialects` | `sqlfluffrs/sqlfluffrs_dialects` |
| `crates/sqll_rules` | `sqlfluffrs/sqlfluffrs_rules` |
| `crates/sqll_base_tests/src` | `sqlfluffrs/src` |
| `crates/sqll_base_tests/tests` | `sqlfluffrs/tests` |

`crates/sqll_rules` has the rules CP01, CP03, and CP04 as a library (S3
T18; since S3b C12 over the rule interface of `crates/sqll_lint`); the sqll
binary does not use it yet. `crates/sqll_base_tests` has the
native tests of the root crate `sqlfluffrs` (its library keeps that name).
They read the sqlfluff fixtures in place in the submodule. Their
dev-dependency `blake2` 0.10.6 (crates.io, MIT OR Apache-2.0) and its new
dependency `subtle` 2.6.1 (BSD-3-Clause) are the versions of
`sqlfluffrs/Cargo.lock`. The sqll binary does not contain them.

The workspace `Cargo.toml` is a port of `sqlfluffrs/Cargo.toml`. Each
ported file has a header with its source file, the version, the commit,
the copyright, and the license. `crates/ported.json` gives the source path
and sha256 of each ported file, the reason of each change, and the source
files that are not ported (for example the Python bindings). The test
`harness/tests/test_sqll_ported.py` checks it against the submodule.

Generated dialect tables: the repository has no copy. `scripts/build-sqll`
makes them with the generator of the submodule (`utils/rustify.py`,
`utils/build_dialect.py`, `utils/build_dialects.py`,
`utils/build_lexers.py`, `utils/build_parsers.py`) and the sqlfluff 4.4.0
dialects of the tool venv (PyPI `sqlfluff` 4.4.0). Both are MIT, with the
copyright above. `crates/sqll_dialects/generated.json` has the path, size,
lines, and sha256 of each of the 85 files. The build copies them into
`sqll_dialects`, so a sqll binary contains them.

The new sqll files in `crates/` (listed in `crates/ported.json`, "new") and
`rust-toolchain.toml` have no sqlfluff code, but `crates/sqll_syntax/src/parse.rs`,
`crates/sqll/tests/cli.rs`, `crates/sqll_tree/build/kinds.rs`,
`crates/sqll_source/src/map.rs`, `crates/sqll_templater/src/raw.rs`,
`crates/sqll_config/src/value.rs`, and the files of the lint crate but
`lib.rs` (`crates/sqll_lint/src/rule.rs`, `crates/sqll_lint/src/config.rs`,
`crates/sqll_lint/src/fix.rs`, `crates/sqll_lint/src/registry.rs`,
`crates/sqll_lint/src/linter.rs`, `crates/sqll_lint/src/sqlfluff.rs`),
and the CLI files `crates/sqll_cli/src/color.rs`,
`crates/sqll_cli/src/text.rs`, `crates/sqll_cli/src/info.rs`,
`crates/sqll_cli/src/lint/mod.rs`, `crates/sqll_cli/src/lint/file.rs`,
`crates/sqll_cli/src/lint/files.rs`, and `crates/sqll_cli/src/lint/record.rs`
(S3b C13) have ported parts ("Ported code" above),
and the other files of `crates/sqll_config/src/` but `lib.rs` and
`parse.rs` are ports of sqlfluff code ("Ported code" above) and of CPython
code ("CPython", "tomllib" below). The sqll binary (`crates/sqll`)
contains the ported crates and the tables. The tables are a substantial
portion of sqlfluff, so each sqll binary carries the sqlfluff MIT copyright
and permission notice: `sqll --license` prints `crates/LICENSE-sqlfluffrs.md`
(S3 T19).

## Rust

The Rust standard library is in each sqll binary.

- Source: https://github.com/rust-lang/rust, tag `1.97.0`, commit
  `2d8144b7880597b6e6d3dfd63a9a9efae3f533d3` (the toolchain of
  `rust-toolchain.toml`).
- License: MIT OR Apache-2.0. sqll chooses MIT. `crates/LICENSE-rust-MIT.txt`
  is a copy of `LICENSE-MIT` of that tag ("Copyright (c) The Rust Project
  Contributors"). `sqll --license` prints it and names the file `COPYRIGHT`
  of that tag, which gives the notices of the parts with other licenses.

The crates.io dependencies are in `Cargo.lock`. `crates/sqll/build.rs` makes
the dependency notice list at build time from `cargo metadata` for the
target platform (`crates/sqll/build/notices.rs`). For each crate that the
package `sqll` needs (normal dependencies), the list gives the name, the
version, the source, if the binary links it (a proc-macro crate and its
dependencies run only in the compiler), the license expression, the chosen
license (the record of each OR choice), and the license texts from the
crate package (also its NOTICE file for Apache-2.0). `sqll --license`
prints the list.

The allow list, in the order of choice: MIT, Apache-2.0, BSL-1.0,
BSD-3-Clause, Zlib, Unicode-3.0, Unlicense, Apache-2.0 WITH LLVM-exception.
The build fails if a package has no choice in the allow list, if a package
is not from crates.io, if a sqll crate does not have the license MIT, or if
a package has no file with the text of its chosen license.
`crates/sqll/tests/license.rs` runs the same check on each package of the
workspace (each platform; normal, build, and dev dependencies), and on
invented packages with a copyleft license.

## sqruff

- Source: https://github.com/quarylabs/sqruff, version `0.41.0`.
- License: Apache-2.0.
- `harness/sqll_harness/adapters/sqruff_config.py` has the names of the
  documented sqruff settings, from `crates/lib/src/core/default_config.cfg`,
  `docs/usage/configuration.md`, and `docs/reference/templaters.md` of that
  version. No sqruff code is copied.
- `results/s3/sqruff-rule-types.json` has names from the crates.io crates
  `sqruff-lib` and `sqruff-lib-core` 0.41.0: the rule codes and names, the
  paths of the rule, helper, and base segment source files, the segment
  type names (`SyntaxKind` variants) that they name, and the layout type
  names of `default_config.cfg`. `scripts/s3/sqruff_rules.py` reads the
  crates from the cargo cache. No sqruff code is copied.
- `results/s3/license-size-sources.json` (task T7) has the text of the
  license files of the sqruff repository at tag `v0.41.0` (Apache-2.0).
  `results/s3/license-size-sources.json` and `results/s3/license-size.json`
  have: the first line and the copyright line of `LICENSE` of that tag; the
  file names, line counts, and license fields of the crates.io crates of
  sqruff 0.41.0; the names, versions, and license fields of their
  dependencies (cargo metadata); 62 short comment lines of the crates that
  name sqlfluff; the first line of `src/mariadb_keywords.rs` of
  `sqruff-lib-dialects`; and one declaration line of `src/core/rules.rs` of
  `sqruff-lib`: `pub trait Rule: Debug + 'static + Send + Sync {`.
  No other sqruff code is copied.
- `results/s3/capabilities-sources.json` and `results/s3/capabilities.json`
  (task T8) have the help text of each sqruff 0.41.0 command and the output
  of `sqruff templaters` (the binary of `tools/sqruff/install.sh`), the 14
  placeholder style regexes and the default config key names of the
  crates.io crates of sqruff 0.41.0, and cited lines (with the crate, the
  file, the line numbers, and the sha256; at most 8 lines of a file in one
  entry, but 28 lines of `src/templaters/types.rs`: the names and regexes
  of the placeholder styles) of `sqruff-lib` (`src/templaters.rs`,
  `src/templaters/` (`raw.rs`, `placeholder.rs`, `python.rs`, `jinja.rs`,
  `dbt.rs`, `sqlmesh.rs`, `python_shared.rs`, `types.rs`), `src/core/config.rs`, `src/core/default_config.cfg`
  (the first and last line), `src/ignore.rs`, `src/core/linter/core.rs`,
  `src/core/linter/common.rs`, `src/core/linter/discovery.rs`),
  `sqruff-lib-core` (`src/dialects/syntax.rs`, `src/parser/segments.rs`,
  `src/templaters.rs`), and the `Cargo.toml` features of the `sqruff`
  crate. These are facts for the S3 decision, not sqll code. No other
  sqruff code is copied.

## CPython

- Source: https://github.com/python/cpython, `Lib/posixpath.py`
  (`normpath`).
- Version: tag `v3.13.16`, commit
  `cbc944f4bc59639a444dd971c737788ba2283a91`.
- License: PSF-2.0 (Python Software Foundation License Version 2). Notice:
  "Copyright (c) 2001-2024 Python Software Foundation; All Rights
  Reserved". The license text is in `crates/LICENSE-cpython.txt`, a copy of
  `LICENSE` of that tag.
- `normpath` in `crates/sqll_cli/src/lib.rs` (in `crates/sqll/src/main.rs`
  before S3b C13) is a port of this function. sqll uses it to print the
  file path as sqlfluff does. Changes: Rust in place
  of Python; only `str` paths (no `bytes`); the root slashes are found in
  the function, not with `splitroot`.
- `crates/sqll_config/src/ini.rs` (S3b C11) is a port of the reader of
  `RawConfigParser` in `Lib/configparser.py` of the same tag (`_read_inner`
  and the functions that it calls, `_join_multiline_values`, `items`). sqll
  reads the sqlfluff INI config files with it. Changes: Rust in place of
  Python; only the settings that sqlfluff uses (delimiter "=", full-line
  comments, strict, empty lines in values, no interpolation); an error
  stops the read.
- `crates/sqll_cli/src/text.rs` (S3b C13) is a port of `wrap` of
  `Lib/textwrap.py` of the same tag (`_munge_whitespace`, `wordsep_re`,
  `_split`, `_wrap_chunks`, `_handle_long_word`). sqll wraps the tables of
  `rules` and `dialects` with it, as sqlfluff does. Changes: Rust in place
  of Python; only the default settings.

## tomllib

- Source: https://github.com/python/cpython, `Lib/tomllib/` (`_parser.py`,
  `_re.py`), tag `v3.13.16`, commit
  `cbc944f4bc59639a444dd971c737788ba2283a91`. The files have the notice
  "SPDX-License-Identifier: MIT", "SPDX-FileCopyrightText: 2021 Taneli
  Hukkinen", "Licensed to PSF under a Contributor Agreement" (the code of
  tomli).
- License: MIT. The license text is in `crates/LICENSE-tomli.txt`, a copy
  of `LICENSE` of https://github.com/hukkin/tomli, tag `2.0.1`.
- `crates/sqll_config/src/toml.rs` (S3b C11) is a port of the parser. sqll
  reads `pyproject.toml` with it, as sqlfluff does with tomllib. Changes:
  Rust in place of Python; the parser works on characters; a date or time
  value is checked but not kept, and it fails closed in `[tool.sqlfluff]`;
  an int over 64 bits fails closed.

## PyYAML

- Source: https://github.com/yaml/pyyaml, tag `6.0.3` (the version in the
  tool venv of sqlfluff 4.4.0): `yaml/emitter.py`, `yaml/resolver.py`,
  `yaml/representer.py`.
- License: MIT. Notice: "Copyright (c) 2017-2021 Ingy döt Net",
  "Copyright (c) 2006-2016 Kirill Simonov". The license text is in
  `crates/LICENSE-pyyaml.txt`, a copy of `LICENSE` of the dist-info.
- `crates/sqll_cli/src/lint/yaml.rs` (S3b C13) is a port of the parts of the
  emitter that `yaml.dump` uses for a lint record (block and empty flow
  collections, the scalar analysis and styles, the implicit resolvers, the
  float form). `sqll lint -f yaml` writes the output of sqlfluff with it.
  Changes: Rust in place of Python; only the values of a lint record.

## S9 corpus

The S9 corpus files are SQL files of public repositories with permissive
licenses. The repository stores no corpus SQL. The harness downloads each
file at run time by its pinned commit and checks its sha256.
`corpus/sources.json` is the record of the source, version (commit),
license, copyright holders, and license files of each corpus file. See
`corpus/README.md`.

## Tools

`scripts/setup` installs these tools in `SQLL_TOOLS_DIR` (default `.tools/`).
The pins are in `tools/<tool>/`. The CI image
`ghcr.io/adamgen/sqll-ci` contains them. That image is private to this
repository. We do not distribute the tools in another way.

| Tool | Version | Source | License |
|---|---|---|---|
| sqlfluff | 4.4.0 | PyPI `sqlfluff` | MIT |
| sqlfluffrs (in `sqlfluff[rs]`) | 4.4.0 | PyPI `sqlfluffrs`; code in `third_party/sqlfluff/sqlfluffrs/` | MIT |
| sqruff binary | 0.41.0 | crates.io `sqruff`, built with `cargo install --locked --features parser,python` | Apache-2.0 |
| sqruff Python templaters | 0.41.0 | PyPI `sqruff[jinja]` (only its Python modules are used) | Apache-2.0 |

The Python dependencies of each tool are in `tools/<tool>/uv.lock`.

The oracle scripts (`scripts/sqlfluff-*-oracle`) and
`scripts/sqlfluff-case-ids` run the pinned sqlfluff with pytest 9.1.1 (PyPI
`pytest`, MIT), pinned in `tools/sqlfluff-oracle/uv.lock`.
With `--rust` they run the pinned `sqlfluff[rs]` and pytest of
`tools/sqlfluff-rs-oracle/uv.lock`. The harness does not use them.

The harness test dependency `jsonschema` 4.26.0 (PyPI, MIT) validates the
JSON Schema output of sqll (S3b C15, `scripts/s3b/schema_check.py`). It
reads the draft 2020-12 meta-schema of `jsonschema-specifications`
2025.9.1 (MIT). Its other dependencies are `attrs` 26.1.0, `referencing`
0.37.0, and `rpds-py` 2026.9.1 (each MIT). `rfc3339-validator` 0.1.4
(MIT) and its dependency `six` 1.17.0 (MIT) let it check the formats
`date-time` and `time`. The pins are in `harness/uv.lock`. sqll does not
contain or distribute them.
