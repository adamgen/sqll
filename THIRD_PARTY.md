# Third-party code and test data

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

`scripts/s3/sqlfluffrs_probe.py` (S3 research, task T5) copies the
submodule into a scratch folder, runs `utils/rustify.py` there, and builds
the sqlfluffrs crates and the probe there. The generated Rust files stay in
the scratch folder; the repository has no copy.
`results/s3/sqlfluffrs-probe-build.json` has only their paths, sizes, and
sha256, the crate names of `cargo tree`, and test names and counts.
`scripts/s3/probe-sqlfluffrs/Cargo.lock` has the crate versions of
`sqlfluffrs/Cargo.lock`. The probe is research code, not sqll.

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
| `scripts/s3/probe-sqlfluffrs/src/main.rs` | S3 research code, not sqll: `sqlfluffrs/src/test_harness.rs` (`FixtureTest::run`), `sqlfluffrs/sqlfluffrs_parser/src/parser/python.rs` (`PyParser` limits), `src/sqlfluff/core/default_config.cfg` (the parse limits and indentation defaults) |

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
`rust-toolchain.toml` have no sqlfluff code. The crates.io dependencies are
in `Cargo.lock`. Task T19 records the license of sqll and the notices.

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
