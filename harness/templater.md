# Templater suite

The `templater` suite of the harness. See [README.md](README.md).

## Cases

The cases are the parametrize list of `test__templater_full` in
`test/core/templaters/jinja_test.py` of the sqlfluff submodule. The harness
reads this list in place with the Python `ast` module and evaluates only
literals. If an entry is not a literal `(str, bool, bool)`, if the function
has another decorator or argument, or if 2 rows give one id, the harness
stops with an error. Case id: `templater/<subpath>`. sqlfluff 4.4.0 has 43
cases.

A unit test compares a hash of the test code (`get_parsed`,
`assert_structure`, `test__templater_full`, and `load_yaml` and
`process_struct` of `test/conftest.py`) with the hash of the code that the
harness ports. If sqlfluff changes this code, the unit test fails.

## Run

The test parses `test/fixtures/templater/<subpath>.sql` with `Linter()` and
the sqlfluff root as the current folder. Thus the config files in each
folder from the sqlfluff root to the file apply, for example
`test/fixtures/.sqlfluff` (`dialect = ansi`). The harness runs the tool in
the same folder with the same relative path. It gives no dialect, no
templater, and no config file:

1. `parse -f json [-c] [-m] <path>`, with `-c` for `code_only` and `-m` for
   `include_meta`.
2. If `code_only`: `parse -f json <path>` again, for the full tree.

The test always uses the `jinja` templater: `Linter()` reads no config
file, and a templater in the config of a file only gives a warning. The CLI
uses the templater of the config in home, in the folders after the common
path of home and the sqlfluff root, and in the sqlfluff root. If this
config sets another templater, the status is `error` and the harness does
not run the tool.

## Checks

The test fails if the full tree has an `unparsable` segment, or if
`to_tuple(code_only, show_raw=True, include_meta)` is not equal (`==`) to the
YAML tree.

- `no_unparsable`: the full tree has no `unparsable` node. The test does not
  check templating or lexing violations. Thus exit code 1 is not a failure.
  `jinja_t_loader_search_path/jinja` has 3 TMP violations and passes.
- `exact`: the tree is equal to `<subpath>.yml`, read with `load_yaml`
  (`compare.py`). With `-m` the CLI adds 6 position keys
  (`start_line_no` ... `end_file_pos`) to each segment record. The harness
  removes them. A position key with a value that is not an int gives
  `error`.

The empty-tree rule: `to_tuple` gives an empty tuple for a segment with no
children to show, and the CLI gives null. The harness makes null an empty
tuple. As in the test, YAML `[]` is equal to it, and YAML null is not. If
the tool gives no tree, the case fails. The dialect suite rule (null and
`[]` are equal) does not apply here.

If the SQL or YAML file is missing or not valid, the status is `fail`. If a
command fails or the 2 runs do not agree on a tree, the status is `error`.

## Python runtime

A case has the tag `needs_python` in the report if its config sets a
`library_path` (in `[sqlfluff]` or `[sqlfluff:templater:jinja]`, not
`none`), or sets the `python` or `dbt` templater. The harness reads the
config files as the tool does: home, the parent folders (see Run), the
folders from the sqlfluff root to the folder of the case, then the in-file
config lines of the SQL file. In 4.4.0 these 3 cases have it
(`library_path`): `jinja_j_libraries/jinja`,
`jinja_m_libraries_module/jinja`, and `jinja_s_filters_in_library/jinja`.
S6 uses this tag.

## Fixture files that are not data cases

These files in `test/fixtures/templater/` are not cases of this suite:

| Files | Why |
|---|---|
| `jinja_d_roundtrip/test.sql` | `test/rules/std_roundtrip_test.py` lints and fixes it with CP01 and LT01. The expected result is in Python code. |
| `jinja_lint_unreached_code/*.sql` (8 files) | `test__templater_lint_unreached_code`. The expected renderings are in Python code. |
| `jinja_macro_path_does_not_exist/.sqlfluff` | `test__templater_jinja_error_macro_path_does_not_exist` expects an error. No SQL file. |
| `jinja_r_library_in_macro/` (`jinja.sql`, `jinja.yml`, libs, macros) | Only `test/cli/commands_test.py` uses it: `render --library-path none` must give exit code 1. No test reads `jinja.yml`. |
| `jinja_slice_template_macros/` (macros) | `test__templater_jinja_slice_file`. The expected slices are in Python code. |
| `placeholder_flyway_var/placeholder_flyway_var_a.sql` | No sqlfluff 4.4.0 test uses it. |

The `.sqlfluff`, `macros/`, `libs/`, and other folders of the cases are
config and support files. Other tests also use some case files
(`jinja_a/jinja.sql`, `jinja_h_macros/jinja.sql`,
`jinja_exclude_macro_path/`, and `jinja_l_metas/002.sql` in
`test__templater_jinja_block_matching`), with expected results in Python
code. S7 converts such tests.

## Agreement with the sqlfluff test

`scripts/sqlfluff-templater-oracle` calls `test__templater_full` of the
pinned sqlfluff through Python, with the parameters that pytest gives it and
`load_yaml` of `test/conftest.py`. It compares the status of each case with
a report.

```sh
scripts/test --tool sqlfluff --suite templater
.tools/sqlfluff-oracle/bin/python scripts/sqlfluff-templater-oracle \
    --report out/report.json --out out/templater-oracle.jsonl
```

The exit code is 1 if a status is different or a case is only in one of the
two. The CI `report` job runs it on the merged report.
`--root harness/tests/fixtures/templater --check-prefixes` runs the harness
test fixtures: the subpath prefix `expect_pass_` or `expect_fail_` must
agree. Their table is `test/core/templaters/jinja_test.py` in that folder.
The CI `lint` job runs this. `harness/tests/test_templater.py` gives the
harness status of each of these fixtures.
