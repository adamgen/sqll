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

`scripts/sqlfluff-autofix-oracle` imports and runs
`test/rules/std_fix_auto_test.py` from the submodule. The harness does not.

Ported code (MIT, attribution in each file header):

| sqll file | sqlfluff source |
|---|---|
| `harness/sqll_harness/compare.py` | `test/conftest.py` (`process_struct`, `load_yaml`), `test/dialects/dialects_test.py` (empty-tree rule) |
| `harness/sqll_harness/suites/dialects.py` | `test/conftest.py` (`get_parse_fixtures`, `DEEP_PARSE_DEPTH_OVERRIDES`) |
| `harness/sqll_harness/suites/rules.py` | `src/sqlfluff/utils/testing/rules.py` (`load_test_cases`, `_setup_config`, `assert_rule_fail_in_sql`, `assert_rule_pass_in_sql`, `prep_violations`, `rules__test_helper`) |
| `harness/sqll_harness/suites/autofix.py` | `test/rules/std_fix_auto_test.py` (`test_cases`, `auto_fix_test`) |
| `scripts/sqlfluff_oracle.py` | `test/conftest.py` (`fail_on_parse_error_after_fix`) |

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
The harness does not use it.
