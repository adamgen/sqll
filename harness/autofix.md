# Autofix suite

The `autofix` suite of the harness. See [README.md](README.md).

## Cases

The suite finds the cases as `test_cases` in
`test/rules/std_fix_auto_test.py` does. Each entry of
`test/fixtures/linter/autofix/<dialect>/` is a case. An entry of `autofix/`
that ends with `.md` is not a dialect. Case id: `autofix/<dialect>/<case>`.
sqlfluff 4.4.0 has 61 cases.

The harness reads the files of a case as `auto_fix_test` does:

- `test-config.yml`: the `rules` list is joined with `,` and then
  upper-cased. If the result has `ALL` in it or is empty, the harness gives
  no `--rules`, and the rules of the config files apply.
  `raise_on_non_linting_violations` is true if it is not set. The test
  ignores the other keys, for example `dialect`.
- `violations.json` (optional) and `after.sql`.

If one of these files is missing or not valid, the status is `fail`, because
the test fails.

## Run

For each case the harness makes a temporary folder with `testing.sql` (the
text of `before.sql`) and `.sqlfluff` (the case config, or an empty file, as
in the test). It reads and writes them in text mode, as the test does:
`\r\n` becomes `\n`. The current folder of the tool is the sqlfluff root, as
for the test, because a case config can load macros with a path relative to
it. The tool reads the config files as for a user. The harness gives only
`--dialect <dialect>` and `--rules`.

The sqlfluff adapter runs 3 commands on 2 copies of the files: `parse` and
`fix` in `<tmp>/fix/`, and `fix --show-lint-violations` in `<tmp>/show/`.
`parse` does not change the files.

1. `parse -f json`: `"segments"` is null if the file has no parse tree.
2. `fix`: this gives the fixed file. If `fix` does not apply fixes because
   of a TMP or PRS violation (also an ignored one), it writes
   `[N templating/parsing errors found]` on stderr.
3. `fix --show-lint-violations`: this shows the violations that `fix` found,
   with no ignored or noqa-masked violations, and the files that it linted.

The test lints in fix mode. In fix mode, the fixes of one rule change the
SQL before the next rule runs. For 5 of the 61 cases, `lint -f json` gives
other violations. Thus the harness uses the violations of `fix`. `fix` has
no JSON output. The harness reads its text output. If that output is not
consistent, the status is `error`.

## Checks

The checks are those of `auto_fix_test`, in the same order:

- The tool must lint the file. Else the status is `fail` (the test fails
  with `LintedDir empty`).
- `tree`: the file has a parse tree. Else the status is `fail` (the test
  reads `res.tree.raw`).
- `non_linting` (only if `raise_on_non_linting_violations` is true): no TMP,
  LXR, or PRS violation that is not a warning (`check_tuples`).
- `violations` (only if `violations.json` is not empty): the set of (code,
  line, position) of the lint violations that are not warnings is equal to
  the set in the file.
- `fix`: the fixed file is equal to `after.sql`. Both are read in text mode.

If a check fails, the status is `fail`. Else, if the result is not known,
the status is `error`. The result is not known if:

- `fix` did not apply fixes because of a TMP or PRS violation, and the test
  does not stop at `non_linting`. The test applies the fixes.
- The 2 `fix` runs give different files.
- The tool logged `CRITICAL`. The test fails on conflicting fixes, but not on
  a rule exception.
- A command fails or gives output that the harness cannot read.

[not-reproduced.md](not-reproduced.md) gives the limits.

## Agreement with the sqlfluff test

`scripts/sqlfluff-autofix-oracle` runs `auto_fix_test` of the pinned
sqlfluff on each case through Python, and compares the status of each case
with a report. It imports `test/rules/std_fix_auto_test.py` from the
submodule, with the sqlfluff root as the current folder. It sets the same
patches as `scripts/sqlfluff-rule-oracle` (`fail_on_parse_error_after_fix`).

```sh
scripts/test --tool sqlfluff --suite autofix
.tools/sqlfluff-oracle/bin/python scripts/sqlfluff-autofix-oracle \
    --report out/report.json --out out/autofix-oracle.jsonl
```

The exit code is 1 if a status is different or a case is only in one of the
two. The CI `report` job runs it on the merged report.
`--root harness/tests/fixtures/autofix --check-prefixes` runs the harness
test fixtures: the name prefix `expect_pass_` or `expect_fail_` must agree.
The CI `lint` job runs this. `harness/tests/test_autofix.py` gives the
harness status of each of these fixtures. It is never `pass` for an
`expect_fail_` fixture.
