# Checks that the harness does not reproduce

These checks of the sqlfluff tests exist only as Python internals, or the CLI
cannot give the same input. See [README.md](README.md), [rules.md](rules.md),
[autofix.md](autofix.md), and [templater.md](templater.md).

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
- The test sets the `DEBUG` level of 2 loggers with `caplog`. This changes
  only the log.

## Dialect cases

- `validate_segment_with_reparse` in `test__dialect__base_file_parse`.
- The `_hash` field of the dialect YAML files. It only makes contributors use
  the generator script. The tree check is sufficient.
- `test__dialect__base_broad_fix`. It has no expected result in data.
