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
  can also occur in only one of the 2 modes.
- In a templated file with more than one variant, the test puts the lint
  errors of the other variants after those of the root variant at the same
  line and position. `lint -f json` does not show the variant of a
  violation, so the harness puts them in rule code order.
- In a templated file with more than one variant, the test removes the lint
  errors of an other variant with the noqa comments of that variant.
  `lint -f json` also applies the noqa comments of the root variant to them.
  No 4.4.0 case with a noqa comment has a template tag.
- If `sqlfluff fix` does not write the file, the fixes that the test
  applies. The `fix` check is not known and the status is `error`. No 4.4.0
  case has this condition.
- A SQL string with an in-file config line. The status is `error`. No 4.4.0
  case has one.
- The test uses `caplog` to show the debug log. It is not a check.

## Dialect cases

- `validate_segment_with_reparse` in `test__dialect__base_file_parse`.
- The `_hash` field of the dialect YAML files. It only makes contributors use
  the generator script. The tree check is sufficient.
- `test__dialect__base_broad_fix`. It has no expected result in data.
