# Third-party code and test data

## sqlfluff

- Source: https://github.com/sqlfluff/sqlfluff
- Version: tag `4.4.0`, commit `0348222a3bcdb0226563f7349c5a39beb0641955`
- License: MIT. Copyright (c) 2018-2026 Alan Cruickshank. See
  `third_party/sqlfluff/LICENSE.md`.
- Path: `third_party/sqlfluff` (git submodule). We do not change these files.

Test data that the harness reads:

- `test/fixtures/dialects/`: SQL files and expected parse trees.
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
submodule. The harness does not.

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

## sqruff

- Source: https://github.com/quarylabs/sqruff, version `0.41.0`.
- License: Apache-2.0.
- `harness/sqll_harness/adapters/sqruff_config.py` has the names of the
  documented sqruff settings, from `crates/lib/src/core/default_config.cfg`,
  `docs/usage/configuration.md`, and `docs/reference/templaters.md` of that
  version. No sqruff code is copied.

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

The oracle scripts (`scripts/sqlfluff-*-oracle`) run the pinned sqlfluff with
pytest 9.1.1 (PyPI `pytest`, MIT), pinned in `tools/sqlfluff-oracle/uv.lock`.
With `--rust` they run the pinned `sqlfluff[rs]` and pytest of
`tools/sqlfluff-rs-oracle/uv.lock`. The harness does not use them.
