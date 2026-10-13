# Checks that the harness does not reproduce

These checks of the sqlfluff tests exist only as Python internals, or the CLI
cannot give the same input. See [README.md](README.md) and [rules.md](rules.md).

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

## Dialect cases

- `validate_segment_with_reparse` in `test__dialect__base_file_parse`.
- The `_hash` field of the dialect YAML files. It only makes contributors use
  the generator script. The tree check is sufficient.
- `test__dialect__base_broad_fix`. It has no expected result in data.
