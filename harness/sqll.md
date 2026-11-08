# sqll in the harness

sqll is the tool of this repository (S3 phase B). `scripts/build-sqll`
builds it from the worktree to `out/sqll/bin/sqll` (`SQLL_BIN` sets another
path). `scripts/test` and `scripts/verify` build it before the run. In CI the
`build` job builds it, and each `test` job of sqll uses the binary of the
`build` artifact (`ci/matrix.d/S3.json`).

## Commands

The commands follow the shape of the sqlfluff CLI. Since S3b C13 they are
in the crate `sqll_cli`; the crate `sqll` keeps main, the allocator, the
license text, the version, and the dispatch.

| Command | Result |
|---|---|
| `sqll --version` | `sqll, version <crate version>+tables.<sha256 of crates/sqll_dialects/generated.json>` |
| `sqll --license` | The sqll license (MIT) and the notices of the code in the binary (THIRD_PARTY.md, "sqll") |
| `sqll version [--build]` | The version, or the build record (JSON): version, `tables_sha256`, `source_sha256`, `source_files` |
| `sqll parse [-d D] [-t T] [--config F] [--ignore-local-config] [-f json] [-c] [-m] [--max-parse-depth N] [--timings] PATH` | The record of `sqlfluff parse -f json` |
| `sqll lint [OPTIONS] [PATHS]...` | `sqlfluff lint`: formats `human`, `json`, `yaml`, `github-annotation`, `github-annotation-native`, `none` ("Lint and fix" below) |
| `sqll fix [OPTIONS] [PATHS]...` | `sqlfluff fix`: in place, `--check`, `-f`, `-x`, stdin |
| `sqll rules` | `sqlfluff rules`; a selected rule that sqll does not have fails closed |
| `sqll dialects` | `sqlfluff dialects` |

`sqll parse` prints the record of `sqlfluff parse -f json`. Since S3b C11
it reads the sqlfluff config as `sqlfluff parse` does
([config.md](../docs/interfaces/config.md)). `--max-parse-depth` is a sqll
option that overrides the config value `max_parse_depth` (default 600);
`sqlfluff parse` has no such option. `--timings` (a sqll option for the
speed work, S3 T14) adds one JSON line to the end of stderr: the seconds
of each phase (`init`, `setup`, `lex`, `parse`, `record`, `write`, `free`;
`crates/sqll_cli/src/parse/timings.rs`), their sum, and the token count. Since S3
T15, `write` has the stderr error lines and the JSON, which sqll writes
from the tree, and `free` has no work (sqll exits with no drop of the
tree). Since S3b C9, `record` has the conversion of the parser tree to the
syntax tree (the parse interface, `docs/interfaces/parse.md`). The output
and the exit code do not change. The defaults of the other parser limits
are those of sqlfluff (`max_parse_nodes` 100000,
`rust_parser_max_iterations` 3000000); the config can change them. As in
sqlfluff, the config of the file comes from the folders of the path that
`os.path.normpath` gives (thus `t/../a.sql` does not read the config of
`t`), and sqll reads that path. Only the PATH `-` is stdin: `./-` is the
file `-`, as in sqlfluff. Exit codes: 0; 1 for a lex error, a parse error
(also at a parser limit), or an unparsable segment (the error lines go to
stderr; an unparsable segment has no line); 2 for a usage, input, or
output error, or a parse tree that the syntax tree refuses (a sqll bug,
`sqll_syntax::ParseError`; no input of the tests gives it). Only a panic
(a sqll bug) gives another exit code (101). stdout has only the JSON
record: the bytes of the sqlfluff output (Python `json.dumps`) and a new
line. The `filepath` is the path as `os.path.normpath` gives it (`stdin`
for `-`). A file with an extension that is not in `sql_file_exts` of the
config (default `.sql`, `.sql.j2`, `.dml`, `.ddl`, `.pkb`; in any case)
gives `[]` and exit code 0, as in sqlfluff. A file over
`large_file_skip_byte_limit` (default 20000 bytes) gives `[]` and exit
code 0, and one over `large_file_skip_char_limit` gives `"segments": null`
and exit code 0, as in sqlfluff (a warning line on stderr). As in click,
sqll reads all arguments before `-h`: an unknown option or a missing value
is an error also with `-h`.

For the 2306 dialect files, sqll and `sqlfluff parse --templater raw
--ignore-local-config` give the same output and exit code (status/S3.md,
T12). Differences from `sqlfluff parse`:

- sqll reads no `noqa` comment. In sqlfluff, a `noqa` comment (for example
  `-- noqa`, `-- noqa: PRS`, or `-- noqa: disable=all`) removes the lex or
  parse error of its lines. Then sqlfluff gives exit code 0 and sqll gives
  exit code 1. The output is the same.
- sqll reads no in-file config line (`-- sqlfluff:...` or
  `--sqlfluff:...`). sqlfluff applies
  them, also with `--ignore-local-config`. A line can change the dialect,
  `max_parse_depth`, or another setting, so the tree and the exit code can
  be different. Only 1 dialect file has such a line, with no effect
  (`harness/not-reproduced.md`).
- The config: a setting that sqll cannot do yet fails closed
  (`unsupported`, exit code 2), and some errors differ. See
  [config.md](../docs/interfaces/config.md), "Differences from sqlfluff".
- `-f` has only `json`, and it is the default.
- Each other option of `sqlfluff parse` (for example `--rules`,
  `--exclude-rules`, `--encoding`, `--ignore`, `--library-path`,
  `--stdin-filename`, `--write-output`, `--nofail`, `-v`, `--nocolor`)
  gives a usage error and exit code 2.
- With `-m`, sqlfluff also adds the 6 source position keys
  (`start_line_no`, `start_line_pos`, `start_file_pos`, `end_line_no`,
  `end_line_pos`, `end_file_pos`) to each record. Thus the children of a
  segment with 2 or more children have duplicate keys, and sqlfluff gives
  them as a list of one-key records. sqll gives no position keys, and the
  record shape of the output with no `-m` (one record with a key for each
  child, if the keys are unique). For example, `ansi/commit.sql`: sqlfluff
  gives `{"file": [{"statement": ...}, {"newline": "\n"}, {"end_of_file":
  ""}]}` (with the position keys), and sqll gives `{"file": {"statement":
  ..., "newline": "\n", "end_of_file": ""}}`. No parity case runs sqll
  with `-m` (the templater cases fail before a run).
- The parse depth of sqll is at most 10000: `--max-parse-depth 0` (no
  limit in sqlfluff) and each value above 10000 give 10000. A deeper parse
  stops with `PRS: Maximum parse depth exceeded (limit 10000)` and exit
  code 1. The limit keeps the parse and the tree in the stack of the
  command thread (256 MiB): at the limit, the deepest trees that were
  measured need about 10 MiB (33 MiB in a debug build). sqlfluff has no
  such limit, but a deep tree stops it with a `RecursionError` and exit
  code 1 (for example 800 nested brackets with `max_parse_depth = 0`). The
  sqlfluff test gives each dialect file the depth 600, or 2000 for
  `ansi/expression_recursion.sql`.
- The parser of sqll is a port of the sqlfluff Rust parser. It counts the
  parse depth in frames of that parser. A probe sub-parse (for a
  terminator, a delimiter, or an exclusion) starts at the depth of the
  frame that starts it. The sqlfluff Rust parser starts each probe at depth
  0; thus nesting through probes, for example bracketed joins, has no depth
  limit there. The sqlfluff Python parser counts the depth in another way
  and gets to the limit at a smaller nesting. Thus sqll can give the tree
  where sqlfluff stops with `PRS: Maximum parse depth exceeded` and exit
  code 1. The first nesting that stops at depth 600 (sqlfluff / sqll), in
  18 measured forms: brackets after `select` 35/40, after `where` 36/42,
  after `order by` 35/40, after `group by` 35/40, after `from` 125/190;
  function calls 23/28; subqueries 19/24; `case` 31/37; `in` subqueries
  18/20; `exists` 21/27; `cast` 23/28; bracketed `union` 57/72; nested
  CTEs 47/64; bracketed joins 37/47; postgres `array[` 44/58; bigquery
  `struct(` 22/27; brackets in tsql 30/35 and snowflake 35/40. Thus sqll
  stops 2 to 65 levels after sqlfluff, never before it. No dialect file
  shows the difference: sqlfluff gives the tree for each one
  (`harness/not-reproduced.md`).
- Each sub-parse of sqll (the main parse, and each probe for a terminator
  or a delimiter) has its own count of iterations, with the limit
  `rust_parser_max_iterations` (default 3000000). When a sub-parse
  reaches the limit, the full parse stops with `PRS: Parser exceeded
  maximum iteration limit (<limit>)...` (the limit of the config),
  `"segments": null`, and exit code 1. A probe that reaches
  a parser limit (iterations, depth, or nodes) also stops the full parse:
  the parse does not continue after it. But sqll does not run a terminator
  probe where the simple hint of the terminator cannot match (S3 T17), as
  the sqlfluff Python parser; the sqlfluff Rust parser runs it. Thus where
  such a probe reaches a limit, sqll can give the tree where the sqlfluff
  Rust parser stops. No dialect file or S2 parse input has such a probe
  (`scripts/s3/hint_check.py`, `results/s3/speed/T17-hint-check.json`).
  The sqlfluff Python parser has no iteration limit. A long flat
  expression can reach the limit in a small file. Examples:
  `select a=a=...=a` with 7853 `=a` (15715 bytes; 7852 give the tree)
  reaches it in the main parse, and `select a from t order by a=a=...=a`
  with 7854 `=a` (15735 bytes; 7853 give the tree) reaches it in a
  probe. For the two examples, the sqlfluff Python parser gives the
  tree with exit code 0, and sqlfluff with the Rust parser stops with a
  `PanicException` and exit code 1. No dialect file reaches the limit.
- An argument that is not UTF-8 (for example a file name) gives
  `unsupported: non-UTF-8 argument` and exit code 2. sqlfluff reads it.
- sqll reads UTF-8 only (with or without a byte order mark). sqlfluff also
  detects other encodings. For stdin, sqlfluff uses the encoding of the
  locale; sqll reads UTF-8, and other bytes give `unsupported` and exit
  code 2.
- PATH is one file, or `-` (stdin). A folder gives `unsupported: folder`.

## Lint and fix (S3b C13)

`results/S3b/C13-cli.json` (`scripts/s3b/cli_oracle.py`; test
`crates/sqll/tests/cli.rs`) has 144 scenarios of `lint`, `fix`, `rules`,
and `dialects`. In 120 (74 lint, 39 fix, 4 rules, 3 dialects), sqll gives
the stdout, the stderr, the exit code (0, 1, 2), and the changed files of
sqlfluff. 22 fail closed (16 lint, 4 fix, 2 rules; `unsupported`, exit
code 2; sqlfluff runs them). 2 are usage errors (lint; exit code 2 for
both, the texts differ). The time values of a json or yaml record
are those of sqll. PATHS are files, folders, or `-` (stdin); no path is the
working folder. The config is that of `sqll parse` (C11), with the rule
settings, `ignore`, and `warnings`.

Options: `-d`, `-t`, `-r/--rules`, `-e/--exclude-rules`, `--config`,
`--ignore-local-config`, `--encoding`, `-i/--ignore`, `--disable-noqa`,
`--disable-noqa-except`, `-n/--nocolor`, `--color`, `-q`, `-p` (1 only),
`--disable-progress-bar` (no effect), `--warn-unused-ignores`,
`--disregard-sqlfluffignores`; lint: `-f`, `--write-output`,
`--annotation-level`, `--nofail`; fix: `-f/--force`, `--check`,
`-x/--fixed-suffix`.

Fail closed (`unsupported`, exit code 2), never a silent skip:

- a rule that the config selects and sqll does not have, also in `sqll
  rules`: the default `rules = all` selects the 79 rules of sqlfluff, so
  `--rules` (or the config) must select only CP01, CP03, or CP04;
- each other sqlfluff option (for example `-v`, `--bench`,
  `--stdin-filename`, `--library-path`, `--persist-timing`,
  `--show-lint-violations`, `--FIX-EVEN-UNPARSABLE`), the formats `sarif`
  and `gitlab`, and more than one process for more than one file;
- a `noqa` comment (C12), an in-file config line (`-- sqlfluff` or
  `--sqlfluff` at the start of a line), an
  ignore file (`.sqlfluffignore`, `ignore_paths`), a Jinja tag,
  `large_file_skip_char_limit`, and `verbose` other than 0;
- a parse error with no position in sqll (a parser stop, for example an
  unclosed bracket): sqlfluff gives it a position and no tree.

sqll does these checks for each file in turn. Thus a file that fails closed
stops the command after the earlier files: `lint` has printed their
results, and `fix` has written their fixes (as sqlfluff, `fix` writes each
file when its lint ends). Test: `crates/sqll/tests/cli.rs`,
`a_file_that_fails_closed_stops_the_fix_after_the_earlier_files`.

Other differences from sqlfluff:

- A usage error (an unknown option or value) has another text; the exit
  code is 2, as in sqlfluff.
- `fix --check` reads the key from the terminal as click does. If there is
  no terminal, sqll gives exit code 2 (sqlfluff stops with a Python error).
- The rule section warning with more than one match lists the codes in
  order; sqlfluff writes a Python set (its order changes from run to run).
- The warning texts of the fix loop are those of C12 (some are sqll only).
- In a lex or parse error text, sqll writes a character of the
  categories Cf, Co, and Cn (Python `str.isprintable()` is false; for
  example U+00AD, U+200B, or a byte order mark on stdin) as it is.
  sqlfluff writes an escape (`\u200b`) in all formats. The line wrap of the
  human format, and the quote style, the line folds, and the escapes of all
  of that text in the yaml format, can then also change. One pinned fixture
  has one: `test/fixtures/linter/parse_lex_error.sql` (U+200D in the
  unlexable text). sqll fails closed on it: its parse error has no position
  in sqll, so `lint` and `fix` give `unsupported: the parse error ...` and
  exit code 2, and change no file.

Memory: the peak RSS of `lint` (human format) and `fix` does not grow with
the number of files: 26.1 and 27.0 MiB (lint), 27.5 and 28.5 MiB (fix)
for 3 and 3000 files (`results/S3b/C13-memory.json`). The `json` and
`yaml` formats keep the output text of each file until the end, as
sqlfluff keeps the records: 214 MiB for 3000 files with 131 MB of output
(`stdout_bytes` of the record).

## Adapter

`sqll_harness/adapters/sqll.py` runs sqll as the sqlfluff adapter runs
sqlfluff (S3b C14):

- `parse()` (dialects suite): `sqll parse -f json` with `-c` and `-m` as
  asked, `--templater raw --dialect D --ignore-local-config`, and the extra
  config of the case as a `--config` file (`pyproject.toml`).
- `lint()` and `fix()` (rules suite): `sqll lint -f json --nofail` and
  `sqll fix`, with `--ignore-local-config --encoding utf-8 --rules R`, and
  `--dialect D` or the case config as a `--config` file.
- `parse_file()` and `fix_file()` (autofix and templater suites): `sqll
  parse -f json` and `sqll fix --nocolor --dialect D [--rules R]` in the
  working folder, with the config files of the user.

Before a run, the adapter fails closed (`unsupported: <item>`, status
`fail`) if one of these is not true:

| Item | Check |
|---|---|
| `rule` | Each rule of the case is in the sqll registry. The adapter reads it from `sqll rules`: with no config it fails closed and names the rules that sqll does not have; a second run with these in `exclude_rules` gives the table of the rules that sqll has. A rule case with no SQL string (2 CV06 cases) also needs its rule (`check_case_rules`). |
| `templater` | The templater is `raw`, or `jinja` (the sqlfluff default) with no templater setting and no `core.library_path`, and each SQL file is a text of `results/S3b/C14-jinja-raw.json`. In a run as a user: the templater of the working folder, and the config of the file sets no other one. Each other templater is unsupported. |
| `in-file config line` | No line of a SQL file starts with `-- sqlfluff` or `--sqlfluff`. |
| `output field` | `fix_file` with the violations of the fix (`sqll fix` has no `--show-lint-violations`), and `parse_file` with `-m` (sqll gives no source positions). |
| `setting` | A config file that the harness does not read (`[tool.sqlfluff]` in `pyproject.toml`) in a run as a user. |

sqll checks each other setting, option, and input itself: if it cannot do
it, it exits with code 2 and `unsupported: <item>` (C11, C13), and the
adapter raises `Unsupported(<item>)`. Another exit code that is not 0 or 1
gives `error`. Thus a run never ignores a setting.

The jinja as raw record: `scripts/s3b/jinja_raw_oracle.py` (`check` in the
CI job build) runs the Jinja and the raw templater of the pinned sqlfluff
(`process_with_variants`, after the newline change of
`Linter.render_string`) on each SQL input of the rule and autofix suites
whose templater is jinja, with the config of the input. An input is equal
if both give one variant, no error, and the same text, sliced file, and
raw slices. The record has the sha256 of each equal text: 3422 inputs,
3178 equal (2522 texts). The 244 inputs with a Jinja delimiter are not
equal; each other input is equal.

Results in 4.4.0 (`known_failures/sqll.txt` lists the 2593 cases that do
not pass, each `unsupported`):

| Suite | Cases | Pass | Unsupported |
|---|---|---|---|
| `dialects` | 2306 | 2306 | 0 |
| `rules` | 2527 | 38 (CP01, CP03, CP04) | 2489: `rule` 2476, `setting` 7 (`ignore_words_regex`), `templater` 6 (a Jinja tag) |
| `autofix` | 61 | 0 | 61: `rule` 36 (3 of them: sqll refuses the default rule set), `setting` 4, `templater` 21 |
| `templater` | 43 | 0 | 43: `templater` |

The CI oracles (`--passes-of sqll`; [rules.md](rules.md), "Agreement with
the sqlfluff test") check that the sqlfluff test passes each case that
sqll passes.

## Benchmark adapter

`sqll_harness/bench/sqll.py` (S2 benchmarks, [bench.md](bench.md), "Add a
tool"). The commands are those of the sqlfluff adapter: `sqll parse -f
json`, `lint -f json`, or `fix`, then `--ignore-local-config --config
config/pyproject.toml input.sql`, with the settings of the benchmark in the
config file (S3b C11). `lint` and `fix` run only if sqll has each rule that
the settings of the benchmark select (`sqll rules`, S3b C14). The S2
settings select all rules (`rules = all`), so `lint` and `fix` give
`unsupported: rule ...` with no run, and the statuses of `results/s2/baseline.json` do not change. The
S9 corpus does not run sqll by default until its corpus results after S3b
(`LATER` in `sqll_harness/corpus/run.py`).

## Tree guard

`scripts/s3/tree_guard.py check` (S3 T14; CI job `build`, `scripts/verify`)
runs sqll on each of the 84 S2 parse inputs, with no option and with `-m`.
The stdout (sha256 and size), the stderr, and the exit code must be those of
`results/s3/tree-guard.json`: the output of main at `1a2219c` (the T11
port with the T12 limit changes, before any speed change). Thus a speed
change cannot change a tree or a meta segment. A new record
(`tree_guard.py record`) needs a reason in the pull request.

## Tool check

`sqll-harness tools --tool sqll` and each `sqll-harness run` with sqll
check the binary (`tools.check_sqll`). The check fails if:

- the binary does not exist;
- its version is not that of the worktree (`expected_version`);
- its source hash is not that of the worktree (a stale build). The hash is
  the sha256 of `Cargo.toml`, `Cargo.lock`, `rust-toolchain.toml`,
  `LICENSE`, and each file under `crates/`: for each file, sorted by path, the path, a NUL byte,
  the size, a NUL byte, and the bytes. `crates/sqll/build.rs` and
  `source_hash` compute it the same way;
- `readelf -d` cannot read it, or it needs `libpython`;
- `sqll parse` of `select 1` gives no tree.

The details in the report (`preflight`) are `fresh_build`,
`needs_libpython`, and `parse`. They and the version are the same for each
commit with the same tables, so `results/s1/summary.json` does not change
for each commit.

`SQLL_SOURCE_DIR` sets the source folder of the check (default: the
worktree). The tool `sqll-base` is the base binary of a speed check
(`scripts/speed-check`; [bench.md](bench.md), "Speed check of a change"):
the binary `SQLL_BASE_BIN` and the source folder `SQLL_BASE_SOURCE_DIR`,
with the same checks, adapter, and settings as sqll. A check or a run of
all tools does not include it.

The lint job checks only the tools of `scripts/setup` (`--tool sqlfluff
--tool sqlfluff-rs --tool sqruff`), because it has no sqll build.
