# Config

Status: frozen (Core track, task C11). Package: `sqll_config` (no
dependencies). Interface test: `crates/sqll_interfaces/tests/config.rs`.
Design: [s3b-core.md](../decisions/s3b-core.md), Q6.

## The interface

- `Value`, `Table`: a config value with the Python type that sqlfluff
  gives it (`None`, `Bool`, `Int`, `Float`, `Str`, `List`, `Table`). A
  `Table` in a section is a nested section. `coerce_value` is the sqlfluff
  coercion of an INI value (an int, a float, `True`, `False`, `None`, or the
  text).
- `defaults()`: the sqlfluff default config (`default_config.cfg` of the
  pinned sqlfluff).
- `Env` (the working folder, `HOME`, `XDG_CONFIG_HOME`) and `Loader`: the
  reader of the config files, in the sqlfluff order (each later one has
  priority):
  1. the user config folder (`~/.config/sqlfluff`, else
     `$XDG_CONFIG_HOME/sqlfluff`), then the home folder;
  2. each folder between the home folder and the path;
  3. each folder from the working folder (or the common folder) to the
     path;
  4. the `--config` file.

  In a folder: `setup.cfg`, `tox.ini`, `pep8.ini`, `.sqlfluff`,
  `pyproject.toml` (`[tool.sqlfluff]`, TOML). Each other file is INI.
  `--ignore-local-config` reads only the `--config` file. A path setting
  (`*_path`, `*_dir`) is relative to the folder of its file.
- `Config::new(configs, overrides)`, `Config::from_path`,
  `Config::from_root` (`FluffConfig`): the defaults, the files, and the
  command line overrides of `core`, with the sqlfluff checks. `get`,
  `core`, `section`, `dialect`, `templater`, `indentation` (the `bool` of
  each value, as the parser gets it), `rule_section`, `templater_section`.
- `ParseSettings::new(root, file)`: the settings of `sqll parse`. The
  templater, `sql_file_exts`, `verbose`, and `recursion_limit` come from
  the root config (the working folder), the other settings from the
  config of the file, as in sqlfluff.
- `ConfigError`: `Invalid` (sqlfluff refuses the config), `Io`, and
  `Unsupported` (fail closed: `sqll parse` prints `unsupported: ...` and
  gives exit code 2).

## Settings of `sqll parse`

| Setting | sqll |
|---|---|
| `dialect`, `max_parse_depth`, `max_parse_nodes`, `rust_parser_max_iterations`, `rust_parser_warn_threshold`, `[sqlfluff:indentation]`, `large_file_skip_byte_limit`, `large_file_skip_char_limit`, `sql_file_exts` | As sqlfluff (with the Rust parser) |
| `templater` | `raw`; `jinja` (the default) only with its default settings and for a text that is not empty and has no `{{`, `{%`, or `{#` (`sqll_templater::jinja_is_literal`): then it gives the file of `raw` |
| `encoding` | `autodetect` (UTF-8 only), `utf-8`, `utf-8-sig` |
| `use_rust_parser` | Only the values that run the Rust parser |
| `rules`, `exclude_rules`, `[sqlfluff:rules:*]`, `[sqlfluff:layout:*]` | Only the defaults (sqlfluff checks them in a parse) |
| `ignore`, `warnings` | Only empty |
| `verbose`, `recursion_limit` | Only 0 and `None` |
| Settings for human output, lint, fix, or noqa; other templaters; unknown keys and sections | No effect on a parse: accepted |

Each other value of these settings fails closed. Also fail closed: a glob
in a path setting, a deprecated setting that sqlfluff moves to its new
key, a TOML date or time, a TOML array of arrays or tables (outside a
templater context), an int over 64 bits, a number with a non-ASCII digit,
a `.sqlfluffignore` file, and `ignore_paths`. Not read yet: in-file config
lines and `noqa` comments (S7-sqll, S5; harness/sqll.md).

## Proof (C11)

- `crates/sqll_config/tests/defaults.rs` reads `default_config.cfg` of the
  submodule and compares each of the 208 defaults.
- `scripts/s3b/config_oracle.py` records the answers of the pinned
  sqlfluff in `results/S3b/C11-config.json` (`check` in the CI job
  build): the defaults, `coerce_value` (40 texts), the INI and TOML
  readers (26 and 19 cases, with the files of `test/fixtures/config/`),
  34 load scenarios (each config file kind, the order, the user config
  folder, `XDG_CONFIG_HOME`, `--config`, `--ignore-local-config`, the
  overrides, and the errors), and 39 `sqlfluff parse` scenarios. The
  interface test and `crates/sqll/tests/cli_config.rs` give the same answers,
  or fail closed where the record says so.
- `jinja_as_raw`: for each of the 2303 dialect fixtures that are not
  empty and have no Jinja delimiter, the Jinja templated file of sqlfluff
  is that of the raw templater.

## Rules for a change

- A change of a signature fails the interface test (`signatures`). Change
  the test and this document in the same Core pull request.
- A setting that sqll can do later (S5, S6, S7-sqll) moves from "fail
  closed" to "as sqlfluff" with a scenario of the record.
