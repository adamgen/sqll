# sqll harness

The harness runs the sqlfluff test fixtures through tool binaries. It does not
import the tools. Each tool is in its own virtual environment.

## Run

```sh
git submodule update --init
scripts/test                       # all tools, all suites
scripts/test --tool sqlfluff --suite dialects --jobs 8
scripts/test --filter dialects/ansi/   # only ids that start with this text
```

`scripts/test` runs `scripts/setup`, writes `out/tools.json` with
`sqll-harness tools`, runs `pytest harness/tests`, then runs the suites. The
exit code is not 0 if a result is different from `known_failures/<tool>.txt`.
It also fails if `third_party/sqlfluff` has a change or an untracked or ignored
file before the tests or after the run. CI makes the same check.

## Tools

`scripts/setup` installs the pinned tools in `SQLL_TOOLS_DIR` (default
`.tools/`; `/opt/sqll/tools` in the CI image). The harness reads the same
setting. Needs: uv, Python 3.13 with a shared libpython, and cargo.

| Tool | Pin | Installed as |
|---|---|---|
| `sqlfluff` | `tools/sqlfluff/uv.lock` | `<dir>/sqlfluff` (venv) |
| `sqlfluff-rs` | `tools/sqlfluff-rs/uv.lock` | `<dir>/sqlfluff-rs` (venv with `sqlfluffrs`) |
| `sqruff` | `tools/sqruff/uv.lock` | `<dir>/sqruff/bin/sqruff` and `<dir>/sqruff/python` |

`tools/sqruff/install.sh` builds sqruff with `cargo install --locked
--features parser,python`. The `parser` feature adds the `parse` command. The
`python` feature adds the jinja, python, dbt, and sqlmesh templaters. They
import the `sqruff` Python package. The interpreter in sqruff finds it through
the first `python3` on `PATH`, so run sqruff with `tools.sqruff_env()`. The
binary links to the libpython of the Python that it was built with.

`sqll-harness tools` prints each tool as JSON: name, version, pin, binary, and
checks. It fails if a version is not the pin, if `sqlfluffrs` does not import
in the `sqlfluff-rs` venv, or if `sqruff parse` or its jinja templater does not
work. `sqll-harness run` makes the same check for the tools that it runs.

## Shards and CI

`sqll-harness run --shard K/N` runs only the cases in shard K. The shard of a
case is a hash of its id. `sqll-harness merge REPORT...` merges shard reports
into `out/report.json` and does the known-failure check again on all results.
Thus it reports a listed id that no shard ran. It fails if a shard report is
missing or is in two reports.

CI (`.github/workflows/ci.yml`):

1. `image`: `ci/image_tag.py` hashes all inputs of `ci/Dockerfile`. If
   `ghcr.io/adamgen/sqll-ci:<hash>` does not exist, CI builds and pushes it.
2. `lint`: `sqll-harness tools`, ruff, and the unit tests, in the image.
3. `test`: one job for each suite, tool, and shard in `ci/matrix.json`.
4. `report`: `sqll-harness merge --expect ci/matrix.json`. It uploads
   `out/report.json`.

To add a suite or a tool to CI, add an entry to `ci/matrix.json`.

## Suites

| Suite | Fixtures | Checks |
|---|---|---|
| `dialects` | `test/fixtures/dialects/<d>/*.sql` with `.yml` or `_nc.yml` | `exact`, `no_unparsable` |
| `rules` | each case key in `test/fixtures/rules/std_rule_cases/*.yml` | `pass_str`, `fail_str`, `fix`, `after_fix` |

Dialect case id: `dialects/<dialect>/<stem>` (`<stem>_nc` for `_nc.yml`).

- `exact`: the tree is equal to the YAML tree, with the sqlfluff rules
  (`process_struct`). Two trees with no children are equal. Parity uses this
  check.
- `no_unparsable`: the tree has no `unparsable` node, and the tool gave no
  error and exit code 0. `sqlfluff parse -f json` gives no violation codes; a
  PRS, LXR, or TMP violation gives exit code 1.

A case passes only if all its checks pass.

The sqlfluff adapter uses `--templater raw`, because the sqlfluff test does not
use a templater. Extra config goes in a temporary file named `pyproject.toml`,
because sqlfluff reads a config file as TOML only with that name. It also uses
`--ignore-local-config`, because the sqlfluff test reads no config file. Without
it the CLI reads the `.sqlfluff` files in `test/fixtures/dialects/<d>/`.

## Rule cases

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

The checks are those of `rules__test_helper`. An empty string is no string.

- `skip` set: status `skip`. No tool runs.
- `pass_str`: no TMP, LXR, or PRS violation and no violation of the rules.
- `fail_str`: no TMP or PRS violation, no `Unexpected exception`, one or more
  violations of the rules. If set, `line_numbers` are the lines of the lint
  violations, and `violations` are equal to all violations of the file. A
  violation with no `code` gets the rule of the case. Warnings are not lint
  violations.
- `fix`: the fixed file is equal to `fix_str`, or to `fail_str` if there is no
  `fix_str`. Else the reason is `fix mismatch`.
- `after_fix` (only with `fail_str` and `fix_str`): if `violations_after_fix`
  is set, the `fail_str` check on `fix_str` with that list. Else the
  `pass_str` check on `fix_str`.

## Checks that are not reproduced

These checks exist only as Python internals:

- `is_fix_compatible` in `assert_rule_fail_in_sql`: if the fix changes the
  SQL, one of the rules must have this class attribute. No CLI command shows
  it.
- The test lints a `fail_str` in fix mode. In fix mode, the fixes of one rule
  change the SQL before the next rule runs, and a fix loop that does not end
  removes the fixes from the violations. `lint -f json` has no fix mode, and
  `fix` gives no JSON. For one rule the violations are the same. No case with
  two rules has `line_numbers` or `violations`.
- The test keeps violations with the same line and position in rule order.
  `lint -f json` sorts them by code. The harness compares in the order of
  `lint -f json`.
- The test uses `caplog` to show the debug log. It is not a check.

- `validate_segment_with_reparse` in `test__dialect__base_file_parse`.
- The `_hash` field of the dialect YAML files. It only makes contributors use
  the generator script. The tree check is sufficient.
- `test__dialect__base_broad_fix`. It has no expected result in data.

Results of the sqlfluff pytest for `test/rules/yaml_test_cases_test.py` and of
the `rules` suite must agree. The PR of T3 has the comparison.

## Report: `out/report.json`

```json
{
  "sqlfluff_ref": "<commit of third_party/sqlfluff>",
  "scope": {"suites": [], "tools": [], "filter": null, "shard": "K/N"},
  "tools": {"<tool>": {"version": "<version>"}},
  "summary": {"<suite>": {"<tool>": {
    "total": 0, "passed": 0, "failed": 0, "skipped": 0, "<check>": 0}}},
  "known_failures": {"<tool>": {"new_failures": [], "unexpected_passes": []}},
  "cases": [{"id": "", "suite": "", "tool": "", "status": "pass|fail|error|skip",
             "checks": {"<check>": true}, "reason": "", "duration_ms": 0}]
}
```

`scope` is what the run tried to run. A merged report has `"scope": null` and
a `parts` list with the scope of each merged report. `<check>` is the number
of cases where that check is true. A case has only the checks that apply to
it. `failed` counts `fail` and `error`. `error` means that the case did not
complete. `skip` means that the fixture skips the case; a skipped case must not
be in `known_failures/`.
