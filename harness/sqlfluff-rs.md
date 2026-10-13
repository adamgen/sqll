# sqlfluff-rs adapter

The `sqlfluff-rs` tool is sqlfluff 4.4.0 with sqlfluffrs 4.4.0
(`sqlfluff[rs]`, venv `<tools>/sqlfluff-rs`). See [README.md](README.md).

## Config layer

The adapter (`adapters/sqlfluff_rs.py`) is the `sqlfluff` adapter with one
more config layer:

```toml
[tool.sqlfluff.core]
use_rust_parser = true
use_rust_rules = true
```

The sqlfluff default is `use_rust_parser = auto`. With `auto`, sqlfluff uses
the Python parser and gives no message if sqlfluffrs does not load. With
`true`, it logs the warning `sqlfluffrs not available`. `use_rust_rules` runs
the Rust detection of a rule if the rule has one: in 4.4.0 only CP01, CP03,
and CP04. sqlfluff does not log it.

All 4 suites get the layer:

- `dialects` and `rules` (`--ignore-local-config`): the adapter adds the 2
  keys to the case config, in the `--config` file `pyproject.toml`.
- `autofix` and `templater` (config files of the user): the adapter gives
  `--config <tmp>/pyproject.toml` with only the layer. The folder is not a
  case folder. sqlfluff loads this file after the config files of the user,
  and before the in-file config lines.

The layer must not change a setting of the case. If the case config, a
config file that sqlfluff can read for the case, or an in-file config line
has `use_rust_parser` or `use_rust_rules`, the status is `error`
(`RustConfigConflict`). The check reads the text of the files in each
parent folder of the current folder and of the SQL file, in home, and in the
user config folders. Thus it can find more than sqlfluff reads, but not
less. No 4.4.0 fixture has these keys.

## Proof that the Rust parser runs

- Preflight (`sqll-harness tools`, and `sqll-harness run` before the first
  case), 2 checks with a control each:
  - `sqlfluff parse -vvv` with the layer must log `Using Rust parser`. With
    `use_rust_parser = false` it must not.
  - Only the Rust parser reads `rust_parser_max_iterations`. With the layer
    and a limit of 1, the parse must stop with `maximum iteration limit`.
    With `use_rust_parser = false` and the same limit, it must give a tree.

  If sqlfluffrs does not import, or a check fails, the run stops with exit
  code 2 and an error for each problem.
- Each command: if sqlfluff logs `sqlfluffrs not available` (no Rust parser)
  or `falling back to Python` (no Rust parse arena, thus no Rust rules), the
  status of the case is `error` (`RustParserNotUsed`).
- `test_each_command_gets_the_layer[True]` adds `-vvv` to each command of
  one case of each suite (8 commands) and finds `Using Rust parser` in each
  log.
- The report has `tools.sqlfluff-rs.config` (the layer) and
  `tools.sqlfluff-rs.preflight` (`rust_parser` and `rust_iteration_limit`).
- The oracles with `--rust` count 0 runs of the Python parser.

## Oracle

The oracle scripts take `--rust`. Run them with
`<tools>/sqlfluff-rs-oracle/bin/python`. Then each `FluffConfig` gets the 2
keys under the config of the test, and the default `--tool` is
`sqlfluff-rs`. The script counts the parse runs of `RustParser` and of the
Python `Parser`. The exit code is 1 if the Python parser runs or the Rust
parser does not.

The `dialects` suite has no oracle. `test__dialect__base_parse_struct` makes
its tree with the Python `Parser` class (`parse_example_file` in
`test/conftest.py`), also when the config sets `use_rust_parser`. Thus no
sqlfluff test compares a tree of the Rust parser with the YAML.

## Results

sqlfluff-rs passes all 4937 cases, as sqlfluff does:

| Suite | Total | Passed | Checks |
|---|---|---|---|
| dialects | 2306 | 2306 | exact 2306, no_unparsable 2306 |
| rules | 2527 | 2527 | after_fix 851, fail_str 1193, fix 1193, pass_str 1332 |
| autofix | 61 | 61 | fix 61, non_linting 61, tree 61, violations 1 |
| templater | 43 | 43 | exact 43, no_unparsable 43 |

`known_failures/sqlfluff-rs.txt` is empty. The oracles with `--rust` give
the same status for all 2527 rule, 61 autofix, and 43 templater cases.
