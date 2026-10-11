# Third-party code and test data

## sqlfluff

- Source: https://github.com/sqlfluff/sqlfluff
- Version: tag `4.4.0`, commit `0348222a3bcdb0226563f7349c5a39beb0641955`
- License: MIT. Copyright (c) 2018-2026 Alan Cruickshank. See
  `third_party/sqlfluff/LICENSE.md`.
- Path: `third_party/sqlfluff` (git submodule). We do not change these files.

Test data that the harness reads:

- `test/fixtures/dialects/`: SQL files and expected parse trees.

Ported code (MIT, attribution in each file header):

| sqll file | sqlfluff source |
|---|---|
| `harness/sqll_harness/compare.py` | `test/conftest.py` (`process_struct`, `load_yaml`), `test/dialects/dialects_test.py` (empty-tree rule) |
| `harness/sqll_harness/suites/dialects.py` | `test/conftest.py` (`get_parse_fixtures`, `DEEP_PARSE_DEPTH_OVERRIDES`) |

## Tools

The harness installs these tools in `.tools/` from `tools/<tool>/uv.lock`. We do
not distribute them.

| Tool | Version | License |
|---|---|---|
| sqlfluff | 4.4.0 (PyPI) | MIT |
