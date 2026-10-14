# sqruff adapter

The `sqruff` tool is the sqruff 0.41.0 binary `<tools>/sqruff/bin/sqruff`
(features `parser,python`). The adapter (`adapters/sqruff.py`) runs it with
`tools.sqruff_env()`, so the jinja and python templaters find their venv.
See [README.md](README.md).

## Commands

| Adapter call | Command |
|---|---|
| `parse`, `parse_file` | `sqruff parse -f json [--include-meta] [--dialect D] --config <tmp>/.sqruff FILE` |
| `lint` | `sqruff lint -f json --parsing-errors [--dialect D] --config <tmp>/.sqruff FILES` |
| `fix` | `sqruff fix [--dialect D] --config <tmp>/.sqruff FILE` |
| `fix_file` | `sqruff parse -f json --dialect D --config <tmp>/.sqruff FILE` (no `fix_even_unparsable`), then `sqruff fix -f json --dialect D --config <tmp>/.sqruff FILE` |

With `--config`, sqruff reads only that file: no other config file of the
user or of the folders.

## Config

The adapter makes the `.sqruff` file (INI, sqruff section names, for example
`[sqruff:rules:capitalisation.keywords]`) from the config in the sqlfluff
structure (`adapters/sqruff_config.py`). It merges these layers, a later one
over an earlier one:

1. The sqlfluff defaults that differ from the sqruff defaults:
   `templater = jinja`, `rules = all`, and
   `layout.type.match_condition.spacing_within = touch:inline`. The fixtures
   expect the sqlfluff defaults. The report shows this layer in
   `tools.sqruff.config`. sqruff stops on the layout types
   `alias_column_list` and `semantic_view`, so their sqlfluff defaults are
   not in the layer.
2. The config of the case:
   - `dialects`: the depth override. The templater is `raw`, as
     `--templater raw` for sqlfluff.
   - `rules`: the YAML config, then `rules = <rules of the case>` and
     `encoding = utf-8`.
   - `autofix` and `templater`: the config files that sqlfluff reads for the
     file (`adapters/config_files.py`, a port of the sqlfluff file search:
     home, the folders between home and the file, and the folders from the
     common path of the current folder and the file). A path value that
     sqlfluff finds near its config file becomes that path. Another relative
     path becomes absolute from the current folder (sqruff makes it relative
     to its config file). The templater is that of the config of the current
     folder, as the sqlfluff CLI does. The CLI options `--dialect` and the
     rules of `test-config.yml` go over it.

sqruff reads the in-file config lines (`-- sqlfluff:...`) itself.

## Unsupported items

A case fails with the reason `unsupported: <item>` if it uses an item that
sqruff does not support. It never passes. The items:

| Reason prefix | When |
|---|---|
| `unsupported: setting` | A setting that the sqruff 0.41.0 documentation does not have: `default_config.cfg` (the full list of settings), `docs/usage/configuration.md`, and `docs/reference/templaters.md`. sqruff can read some of these settings, for example `rules.references.consistent.single_table_references`; the harness does not give them. Also a documented setting that the sqruff source does not read (`NOT_READ` in `sqruff_config.py`): `core.output_line_length`, `indentation.template_blocks_indent`, `capitalisation.types` `ignore_words` and `ignore_words_regex`, `templater.jinja.library_path`, and `templater.dbt.profile`. Also a `core.ignore` value other than `templating` (`core.ignore=parsing`): sqruff gives only `templating` to its Python templaters, and its linter does not read `core.ignore`. A rule section with a rule code as its name (for example `rules.AL03`) is also in this group. sqlfluff 4.4.0 ignores such a section with a warning, so the case fails also where sqlfluff passes it. |
| `unsupported: rule` | A rule code that `sqruff rules` does not list (`CV13`, `TQ01`). |
| `unsupported: dialect` | A dialect that `sqruff dialects` does not list (`soql`). |
| `unsupported: templater` | A templater that `sqruff templaters` does not list. |
| `unsupported: output field` | The case compares a `violations` or `violations_after_fix` list that is not empty. The test compares each violation with `to_dict()`, which always has `name` and `warning`. `sqruff lint -f json` gives only the code, the message, and the start line and position. It gives no `name`, `warning`, `fixes`, `start_file_pos`, or end position. Also: the config or an in-file config line sets `warnings` (the output has no warning field). |
| `unsupported: upper-case key` | A config key with an upper-case letter. sqruff makes INI keys and section names lower case. sqlfluff keeps the case. |
| `unsupported: multi-line value` | A value with a new line. sqruff reads an INI value on one line. |
| `unsupported: comment character` | A key, section name, or value with `#` or `;`. sqruff (configparser `Ini::new`) cuts an INI line at the first `#` or `;`. |
| `unsupported: layout type` | sqruff stops (`not implemented: <type>`) on a layout type in the config. |
| `unsupported: in-file config line` | sqlfluff and sqruff do not read the same in-file config lines: sqruff reads `-- sqlfluff:` or `-- sqruff:` after leading spaces; sqlfluff reads `-- sqlfluff` or `--sqlfluff` at the line start. |

A key or value that INI cannot hold the same way (a list outside the template
variables, spaces around a value, `=`, `:`, or `.` in a key) gives `error`.
No 4.4.0 case has one.

## Output

- Parse: sqruff gives the full tree as lists of one-key dicts, with position
  keys with `--include-meta`. The adapter removes the position keys and
  gives the tree in the form of `sqlfluff parse`. For a code-only case it
  applies the code-only filter (`code_only.py`), because sqruff has no
  code-only output. No JSON and `Error: Failed to parse` or `Failed to
  template file` on stderr: no tree. In the `dialects` suite exit code 1 (a
  parse error) is an error, as for sqlfluff.
- Lint: each violation has `code`, `description`, `start_line_no`, and
  `start_line_pos`. A parse error has no code; the adapter gives it `PRS`,
  as `sqruff parse` does.
- Fix: the harness reads the file that `sqruff fix` wrote. The output has no
  `fixes` field and no `CRITICAL` log. The rule suite compares this file,
  but a TMP or PRS in a lint output (also a noqa-masked one) with no
  `fix_even_unparsable` gives `error` for the `fix` check: sqruff does not
  write the file, and the fixes of the test are not known. With no
  `fix_even_unparsable`, `fix_file` finds that sqruff did not write the
  file from a TMP or PRS in the `fix -f json` output, or
  from `sqruff parse` before the fix (no tree, an `unparsable` segment, or
  exit code 1). The output does not show a noqa-masked error; the parse tree
  keeps its `unparsable` segment.
- A panic (`panicked at`) or another exit code than 0 or 1 is an error.

## Code-only filter

`code_only.code_only_record` is a port of `to_tuple(code_only=True)` and
`structural_simplify` of sqlfluff 4.4.0. It keeps a child only if it is code
and not meta. A raw segment is code if its type is not a type of a sqlfluff
non-code class (comments, whitespace, newlines, and the types that the
dialect lexers and parsers give them) or a meta type. Postgres
`meta_command` is a comment only if its text does not start with `\gset`,
`\gexec`, `\crosstabview`, `\copy`, or `\set`. Another segment is code if
one of its children is code.

The `code_only` suite proves the filter: for each of the 2306 dialect cases,
sqlfluff parses the file with and without `-c`, as the `dialects` suite
does. The filtered full tree must be equal to the `-c` tree (record and
tuple). It runs only for `sqlfluff`, in CI (8 shards). Result: 2306 of 2306.

## Results

| Suite | Total | Passed | Failed | Checks |
|---|---|---|---|---|
| dialects | 2306 | 1548 | 758 | exact 1548, no_unparsable 2164 |
| rules | 2527 | 2185 | 342 | after_fix 758, fail_str 1044, fix 997, pass_str 1207 |
| autofix | 61 | 45 | 16 | fix 45, non_linting 54, tree 54, violations 1 |
| templater | 43 | 28 | 15 | exact 28, no_unparsable 33 |

`known_failures/sqruff.txt` lists the 1131 failed cases with their reasons.
`sqll-harness known-failures REPORT --tool sqruff` writes this file from a
report, and `--counts` gives the counts for each reason prefix (see
STATUS.md). No sqlfluff test can run sqruff, so there is no oracle.
[not-reproduced.md](not-reproduced.md) gives the limits.
