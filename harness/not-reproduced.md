# Checks that the harness does not reproduce

These checks of the sqlfluff tests exist only as Python internals, or the CLI
cannot give the same input. See [README.md](README.md), [rules.md](rules.md),
[autofix.md](autofix.md), [templater.md](templater.md), and
[sqlfluff-rs.md](sqlfluff-rs.md).

## Rule cases

- `is_fix_compatible` in `assert_rule_fail_in_sql`: if the fix changes the
  SQL, one of the rules must have this class attribute. No CLI command shows
  it.
- The test lints a `fail_str` in fix mode. `lint -f json` has no fix mode,
  and `fix` gives no JSON. In fix mode, the fixes of one rule change the SQL
  before the next rule runs, and a fix loop that does not end removes the
  fixes from the violations. Also with one rule, fix mode can give other
  `fixes` and end positions. An example is
  `JJ01/test_fail_templated_segment_contains_leading_literal`. In sqlfluff
  4.4.0, 4 `fail_str` give other violation dicts in fix mode: this JJ01 case,
  `AL02_LT01/test_alias_expression_align_4515_3`,
  `CP02_LT01/test_fail_cp02_fail_lt01`, and
  `CP02_LT01/test_fail_fix_cp02_lt01_with_templating_6678`. Their codes,
  lines, and start positions do not change, and they have no `violations` or
  `line_numbers`. With 2 rules, an `Unexpected exception` of the second rule
  can also occur in only one of the 2 modes. In fix mode, `sqlfluff fix` logs
  it as `CRITICAL`, and the status is `error`. In lint mode only, the status
  is `fail` and the test passes.
- In a templated file with more than one variant, the test puts the lint
  errors of the other variants after those of the root variant at the same
  line and position. `lint -f json` does not show the variant of a
  violation, so the harness puts them in rule code order.
- In a templated file with more than one variant, the test removes the lint
  errors of an other variant with the noqa comments of that variant.
  `lint -f json` also applies the noqa comments of the root variant to them.
  If a SQL string can be templated and a noqa comment has an effect, the
  status is `error`. No 4.4.0 case has this condition.
- The fixes that the test applies when `sqlfluff fix` does not write the
  file. `sqlfluff fix` does not write the file if a TMP or PRS blocks the
  fix, or if no shown violation has fixes. The test also applies the fixes of
  violations that `ignore` or `remove_templated_errors` (a lint error in a
  templated area) removes. If a lint output has a violation with fixes and
  the tool does not write the file, the `fix` check is not known and the
  status is `error`. No 4.4.0 case has this condition.
- The autouse fixture `fail_on_parse_error_after_fix` of `test/conftest.py`
  makes the test fail on conflicting fixes for one anchor. `sqlfluff fix`
  only logs a `CRITICAL` message. If it logs one, the status is `error`.
- The test does not apply `large_file_skip_byte_limit`. `sqlfluff lint` skips
  a larger file and gives no output for it. The status is `error`. No 4.4.0
  SQL string is longer than 1252 bytes.
- A SQL string with an in-file config line. The status is `error`. No 4.4.0
  case has one.
- The test uses `caplog` to show the debug log. It is not a check.

### False passes with mutated fixtures

The T3 reviews found these false passes with fixtures that are not in sqlfluff
4.4.0. They are not fixed and no check fails closed for them:

- `JJ01/test_fail_templated_segment_contains_leading_literal` with
  `violations` from lint mode: the harness gives `pass`, the test fails.
  With `violations` from fix mode, the harness gives `fail` and the test
  passes. 2 real cases have a template tag and `violations`, so the harness
  cannot fail closed.

## Autofix cases

- `sqlfluff fix` does not apply fixes to a file with a TMP or PRS violation,
  also an ignored or noqa-masked one, if `fix_even_unparsable` is not set.
  The test applies them. If `fix` reports this and the test does not stop at
  `non_linting`, the status is `error`. No 4.4.0 case has this condition.
- The test fails on conflicting fixes for one anchor
  (`fail_on_parse_error_after_fix`). A rule exception only gives a lint
  error. `sqlfluff fix` logs both as `CRITICAL`. If it logs one, the status
  is `error`. No 4.4.0 case has this condition.
- If the linter crashes on the file, the test fails (`LintedDir empty`).
  `sqlfluff fix` logs a traceback, and the status is `error`. No 4.4.0 case
  has this condition.
- The text output of `fix` has no warning field. The harness finds a warning
  by the prefix `WARNING: ` of its description. A violation that is not a
  warning and has a description with this prefix is read as a warning. No
  4.4.0 case config sets `warnings`, and the 61 cases show 490 violations
  with no warning.
- The test reads and writes the files with the locale encoding. The harness
  uses UTF-8. All 4.4.0 autofix files are ASCII.
- The harness writes the files in `<tmp>/fix/` and `<tmp>/show/`, the test in
  `<tmp>/`. sqlfluff reads the config files of each parent folder. The
  folder between them has no config file.
- The test sets the `DEBUG` level of 2 loggers with `caplog`. This changes
  only the log.

## Templater cases

- The test finds an unparsable segment by the `type` of each segment
  (`type_set`). The harness finds the record key, which is `get_type()`. For
  a raw segment with instance types, `get_type()` is the first instance
  type. In sqlfluff 4.4.0 only `UnparsableSegment` has the type
  `unparsable`, and its `get_type()` is the same. A raw segment with the
  instance type `unparsable` gives `fail` where the test passes.
- The test uses the home folder of the user, and the harness an empty one.
  A sqlfluff config file in the home folder changes only the test.
- The test always uses the `jinja` templater. The CLI uses the templater of
  the config in home, in the folders after the common path of home and the
  current folder, and in the current folder (the sqlfluff root). If this
  config sets another templater, the status is `error`. The config
  files in the 4.4.0 sqlfluff root have no sqlfluff section.
- The test sets the `DEBUG` level of 2 loggers with `caplog`. This changes
  only the log.

## Dialect cases

- `validate_segment_with_reparse` in `test__dialect__base_file_parse`.
- The `_hash` field of the dialect YAML files. It only makes contributors use
  the generator script. The tree check is sufficient.
- `test__dialect__base_broad_fix`. It has no expected result in data.
- `sqlfluff parse` applies the in-file config lines (`-- sqlfluff:...`) of the
  SQL file. They have priority over `--dialect` and `--ignore-local-config`.
  The test (`parse_example_file`, `lex_and_parse`) does not apply them. A line
  that changes a setting can give a false pass or a false fail. The harness
  does not fail closed for it. In sqlfluff 4.4.0 only
  `clickhouse/create_user.sql` has such a line
  (`-- sqlfluff:dialect:clickhouse`). It sets the dialect of its folder, so it
  has no effect.

`scripts/sqlfluff-dialect-oracle` runs the 2 tests that have the first 2
checks (`test__dialect__base_file_parse`, `test__dialect__base_parse_struct`)
on the same cases. If a test fails on a case that the harness passes, the CI
comparison fails. This also shows a difference that an in-file config line
causes.

## sqlfluff-rs

- No sqlfluff test compares a tree of the Rust parser with a dialect YAML
  file: `test__dialect__base_parse_struct` always uses the Python `Parser`.
  The dialect oracle with `--rust` runs it with `RustParser`, and also runs
  `test__parity__dialect_fixture_corpus` (Python and Rust trees are equal).
- sqlfluff does not log the Rust detection of a rule (`use_rust_rules`: CP01,
  CP03, CP04 in 4.4.0). The harness cannot show that it ran. It finds only
  the warning `falling back to Python` (no Rust parse arena). The oracles set
  the same config.
- The oracles add the 2 keys under the config of the test. The adapter adds
  them over the config files of the case, and gives `error` if the case sets
  one of them. No 4.4.0 case sets them, so the 2 configs are equal.

## sqruff

No sqlfluff test runs sqruff, so the harness compares the sqruff output with
the data of the fixture. See [sqruff.md](sqruff.md). Limits:

- The code-only filter decides "code" by the segment type. The `code_only`
  suite proves it on the sqlfluff trees of all 2306 dialect cases. A sqruff
  segment that is code but has the type of a sqlfluff non-code segment (for
  example `comment`) is removed. A sqruff segment that is not code and has
  another type stays, and the tree differs. No 4.4.0 case shows this.
- The rule suite does not use `fix_not_shown` for sqruff: the lint output
  has no `fixes` field. The `fix` check compares the file that `sqruff fix`
  wrote. If a TMP or PRS that `ignore` hides stops the fix, and the case has
  no `fix_str`, the check passes. No 4.4.0 rule case sets `ignore`.
- In `fix_file`, the harness finds that sqruff did not write the file only
  from a TMP or PRS in the `fix -f json` output. A TMP or PRS that `ignore`
  hides is not in the output. Then the `fix` check compares the file. The
  4.4.0 autofix case with `ignore = templating` sets `fix_even_unparsable`.
- "unsupported" follows the sqruff documentation and the sqruff 0.41.0
  source. sqruff 0.41.0 reads some settings that its documentation does not
  have (these cases fail with `unsupported: setting`). The documented
  settings that the source does not read also give `unsupported: setting`
  (see [sqruff.md](sqruff.md)). The harness found them with a search of the
  source for each setting name. It does not run a check that sqruff uses
  each setting.
- sqruff and sqlfluff convert an INI value in the same way (int, float,
  bool, none, else text). A YAML string such as `"5"` becomes the int 5.
  A list in the template variables is written as Python text; the templater
  reads it with `ast.literal_eval`. sqruff cuts an INI line at `#` or `;`,
  so a value with one of them gives `unsupported: comment character`.
- sqruff has no dialect oracle. Thus no check shows a difference that an
  in-file config line causes in a dialect case. In 4.4.0 only
  `clickhouse/create_user.sql` has one, and it has no effect.
