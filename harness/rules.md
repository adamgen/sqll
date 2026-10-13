# Rule case suite

The `rules` suite of the harness. See [README.md](README.md).

## Cases

The suite loads the cases as `load_test_cases` in sqlfluff does. Each
top-level key of a file, except `rule` and `configs`, is a case. The file-level
`configs` applies to each case with no `configs` key. Case id:
`rules/<file stem>/<key>`. A key that is not a `RuleTestCase` field is an error.

For each case the harness makes a temporary folder with the SQL strings and
the config, and removes it after the case. The adapter runs:

1. `lint` on `pass.sql`, `fail.sql`, and `fixed.sql` (the `fix_str`) together.
2. `fix` on `fix.sql`, a copy of `fail.sql`. Then it reads the file.

The rules are the codes in `rule` (`AL02, LT01` gives `AL02,LT01`). The
dialect is `ansi` only if the case config sets no dialect. The sqlfluff
adapter uses `--ignore-local-config`, `--encoding utf-8`, and `--config
<tmp>/pyproject.toml`. The TOML file keeps the YAML types: bools, ints,
strings with new lines, and nested lists.

`lint -f json` removes the violations that the core `ignore` config or a
noqa comment hides. The sqlfluff test uses lists with no filter for some
checks. Thus the harness can lint 3 more times:

- With no `ignore`, if the case config has `ignore`. These lint violations
  are those of the test: a noqa comment for a rule removes its lint errors
  before any list.
- With no `ignore` and with `disable_noqa`, if a SQL string has `noqa` or can
  be templated. Templating can make a noqa comment that is not in the
  source. These TMP, LXR, and PRS violations are those of the test. This
  lint gives no PRS for a bad noqa comment; the PRS that only the first of
  the 2 lints gives are those.
- `fail.sql` only, with no `ignore` and with `ignore_templated_areas` set to
  false, if the `fail_str` can be templated. In fix mode the test applies the
  fixes of a lint error in a templated area. `remove_templated_errors`
  removes the error only after the fix loop. Only the `fix` check uses this
  lint.

A string can be templated if the case config sets a `templater` that is not
`raw`, or if the string has a jinja start string: `{{`, `{%`, `{#`, or a
`variable_start_string`, `block_start_string`, or `comment_start_string` of
the `templater.jinja` config. If the config sets one of these keys to a value
that is not a string, or to an empty string, all strings can be templated.

Each check uses the same list as the test:

- `filtered`: the lint with the case config, with no warnings
  (`get_violations()`).
- `raw`: all violations with no filter (`LintedFile.violations`).
- `parse`: the TMP, LXR, and PRS of `raw` from templating, lexing, and
  parsing (`ParsedString.violations`). Not the PRS of a bad noqa comment.

The checks are those of `rules__test_helper`. An empty string is no string.

- `skip` set: status `skip`. No tool runs.
- A SQL string with a carriage return: status `error`. sqlfluff reads a file
  with universal newlines, so no file gives the same string to the tool.
- A SQL string with an in-file config line (a line that starts with
  `-- sqlfluff` or `--sqlfluff`): status `error`. The line overrides the
  config file, so the extra lints cannot remove an `ignore` in it.
- A SQL string that can be templated, where the lint with no `ignore` and
  the lint with `disable_noqa` are different (a noqa comment has an effect):
  status `error`. `lint -f json` applies the noqa comments of the root
  variant to the lint errors of all variants. The test does not. Thus the
  harness cannot get the lists of the test. The other checks do not run.
- `pass_str`: no violation in `parse`, and no violation of the rules in
  `raw`. Warnings count.
- `fail_str`: in `filtered`, no TMP or PRS violation, no `Unexpected
  exception`, and one or more violations of the rules. If set, `line_numbers`
  are the lines of the lint violations in `filtered`, and `violations` are
  equal to `raw` in the order of the test (see below). A violation with no
  `code` gets the rule of the case.
- `fix`: the fixed file is equal to `fix_str`, or to `fail_str` if there is no
  `fix_str`. Else the reason is `fix mismatch`.
- `after_fix` (only with `fail_str` and `fix_str`): if `violations_after_fix`
  is set, the `fail_str` check on `fix_str` with that list. Else the
  `pass_str` check on `fix_str`.

The test always applies the fixes. `sqlfluff fix` does not write the file if
`raw` has a TMP or PRS and `fix_even_unparsable` is not set, or if no
violation in `filtered` (with warnings) has fixes. If it does not write the
file and a violation in a lint output has fixes, the result of the `fix`
check is not known. The result is also not known if `sqlfluff fix` logs a
`CRITICAL` message, or if `fix` fails. The CLI only logs a rule exception or
conflicting fixes for one anchor. The test can fail on them.

If a lint gives no usable output (no JSON, no output for a file, or an exit
code that is not 0), the status is `error` and no check runs. The reason of
a lint or `fix` failure has the first line of stderr (for a Python
traceback, the last line).

A case passes only if all its checks pass. If a check fails, the status is
`fail`, because the test stops at that check. Else, if the result of the
`fix` check is not known, the status is `error`.

Of the limits of the CLI, only the conditions above give `error`. A timeout
or an exception in the harness also gives `error` (see
[README.md](README.md)). Some limits in [not-reproduced.md](not-reproduced.md)
can give `pass` where the test fails: fix mode (`violations` and
`line_numbers` from lint mode), `is_fix_compatible`, and the order of the lint
errors of other template variants.

The order of `violations`: the test makes the list in this order: TMP, then
the LXR and PRS of the root variant, then the PRS of each bad noqa comment,
then the lint errors in rule code order. Then it does a stable sort by line
and position. A bad noqa PRS has position 0 in this sort. `lint -f json`
sorts by line, position, and code, and keeps the order of equal items. The
harness does a stable sort of that output by line, position, and the rank of
the violation type in the list above. Then it compares the result with the
expected list.

[not-reproduced.md](not-reproduced.md) gives the checks of the test that the
harness does not reproduce, and why.

## Agreement with the sqlfluff test

`scripts/sqlfluff-rule-oracle` runs `rules__test_helper` of the pinned
sqlfluff on each rule case through Python, and compares the status of each
case with a report. Only this check imports sqlfluff; the harness does not.
`scripts/setup` installs its sqlfluff and pytest in
`<dir>/sqlfluff-oracle` (`tools/sqlfluff-oracle`). It is not a harness tool.

```sh
scripts/test --tool sqlfluff --suite rules
.tools/sqlfluff-oracle/bin/python scripts/sqlfluff-rule-oracle \
    --report out/report.json --out out/oracle.jsonl
```

The exit code is 1 if a status is different or a case is only in one of the
two. Only CI runs it: the CI `report` job on the merged report.
`scripts/test` does not, because it runs sqlfluff through Python, not through
a binary. As the autouse fixture `fail_on_parse_error_after_fix` of
`test/conftest.py`, the oracle makes `_report_conflicting_fixes_same_anchor`
and `_log_apply_fixes_check_issue` raise `ValueError`. The oracle does not set
the `caplog` DEBUG levels of `test__rule_test_case`. They change only the log.
`--cases 'harness/tests/fixtures/rules/*.yml' --check-prefixes` runs the
harness test fixtures: the key prefix `expect_pass_` or `expect_fail_` must
agree. The CI `lint` job runs this.
