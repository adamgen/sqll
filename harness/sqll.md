# sqll in the harness

sqll is the tool of this repository (S3 phase B). `scripts/build-sqll`
builds it from the worktree to `out/sqll/bin/sqll` (`SQLL_BIN` sets another
path). `scripts/test` and `scripts/verify` build it before the run. In CI the
`build` job builds it, and each `test` job of sqll uses the binary of the
`build` artifact (`ci/matrix.d/S3.json`).

## Commands

The commands follow the shape of the sqlfluff CLI, so that S3b can add to
them.

| Command | Result |
|---|---|
| `sqll --version` | `sqll, version <crate version>+tables.<sha256 of crates/sqll_dialects/generated.json>` |
| `sqll version [--build]` | The version, or the build record (JSON): version, `tables_sha256`, `source_sha256`, `source_files` |
| `sqll parse --dialect D [-f json] [-c] [-m] [--max-parse-depth N] PATH` | The record of `sqlfluff parse -f json` |
| `sqll lint`, `sqll fix` | `Error: unsupported: lint` (or `fix`), exit code 2 (rules come in S5) |

`sqll parse` prints the record of `sqlfluff parse -f json` with the raw
templater and the default config. `--max-parse-depth` is a sqll option for
the config value `max_parse_depth` (default 600); `sqlfluff parse` has no
such option. The other parser limits are the sqlfluff defaults
(`max_parse_nodes` 100000, `rust_parser_max_iterations` 3000000). Exit
codes: 0; 1 for a lex error, a parse error (also at a parser limit), or an
unparsable segment (the error lines go to stderr); 2 for a usage, input, or
output error. Only a panic (a sqll bug) gives another exit code (101).
stdout has only the JSON record: the bytes of the sqlfluff output (Python
`json.dumps`) and a new line. The `filepath` is the path as
`os.path.normpath` gives it (`stdin` for `-`). A file with an extension
that is not `.sql`, `.sql.j2`, `.dml`, `.ddl`, or `.pkb` (`sql_file_exts`
of the sqlfluff default config, in any case) gives `[]` and exit code 0, as
in sqlfluff. As in click, sqll reads all arguments before `-h`: an unknown
option or a missing value is an error also with `-h`.

For the 2306 dialect files, sqll and `sqlfluff parse --templater raw
--ignore-local-config` give the same output and exit code (status/S3.md,
T12). Differences from `sqlfluff parse`:

- sqll reads no `noqa` comment. In sqlfluff, a `noqa` comment (for example
  `-- noqa`, `-- noqa: PRS`, or `-- noqa: disable=all`) removes the lex or
  parse error of its lines. Then sqlfluff gives exit code 0 and sqll gives
  exit code 1. The output is the same.
- sqll reads no in-file config line (`-- sqlfluff:...`). sqlfluff applies
  them, also with `--ignore-local-config`. A line can change the dialect,
  `max_parse_depth`, or another setting, so the tree and the exit code can
  be different. Only 1 dialect file has such a line, with no effect
  (`harness/not-reproduced.md`).
- sqll reads no config file and no `.sqlfluffignore` file. sqlfluff gives
  `[]` for a file that a `.sqlfluffignore` file ignores.
- `-f` has only `json`, and it is the default.
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
  or a delimiter) has its own count of iterations, with the limit 3000000
  (`rust_parser_max_iterations`). When a sub-parse reaches the limit, the
  full parse stops with `PRS: Parser exceeded maximum iteration limit
  (3000000)...`, `"segments": null`, and exit code 1. A probe that reaches
  a parser limit (iterations, depth, or nodes) also stops the full parse:
  the parse does not continue after it. The sqlfluff Python parser has no
  iteration limit. A long flat expression can reach the limit in a small
  file. Examples: `select a=a=...=a` with 7853 `=a` (15715 bytes; 7852 give
  the tree) reaches it in the main parse, and `select a from t order by
  a=a=...=a` with 7854 `=a` (15735 bytes; 7853 give the tree) reaches it
  in a probe. For the two examples, the sqlfluff Python parser gives the
  tree with exit code 0, and sqlfluff with the Rust parser stops with a
  `PanicException` and exit code 1. No dialect file reaches the limit.
- An argument that is not UTF-8 (for example a file name) gives
  `unsupported: non-UTF-8 argument` and exit code 2. sqlfluff reads it.
- sqll reads UTF-8 only (with or without a byte order mark). sqlfluff also
  detects other encodings.
- sqll has no file size limit. With the default config
  (`large_file_skip_byte_limit = 20000`), sqlfluff skips a larger file: it
  gives `[]` and exit code 0. sqll parses the file. Such a file can reach
  the iteration limit (above).
- PATH is one file, or `-` (stdin). A folder gives `unsupported: folder`.

## Adapter

`sqll_harness/adapters/sqll.py`. `parse()` runs `sqll parse -f json` with
`-c` and `-m` as asked, and `--max-parse-depth` for the setting
`core.max_parse_depth`. Each other setting gives `unsupported: setting
<section>.<key>`. The other items fail before a run of the binary:

| Suite | Reason | Why |
|---|---|---|
| `rules` | `unsupported: lint` | sqll has no lint command (`Adapter.lints` is False). This includes the 2 CV06 cases with an empty `pass_str`, which the sqlfluff test does not check. |
| `autofix`, `templater` | `unsupported: templater` | The suite parses as a user does (`parse_file`): with the config files and the templater of the config (default jinja). sqll has neither. |

`known_failures/sqll.txt` lists these 2631 cases.

## Tool check

`sqll-harness tools --tool sqll` and each `sqll-harness run` with sqll
check the binary (`tools.check_sqll`). The check fails if:

- the binary does not exist;
- its version is not that of the worktree (`expected_version`);
- its source hash is not that of the worktree (a stale build). The hash is
  the sha256 of `Cargo.toml`, `Cargo.lock`, `rust-toolchain.toml`, and each
  file under `crates/`: for each file, sorted by path, the path, a NUL byte,
  the size, a NUL byte, and the bytes. `crates/sqll/build.rs` and
  `source_hash` compute it the same way;
- `readelf -d` cannot read it, or it needs `libpython`;
- `sqll parse` of `select 1` gives no tree.

The details in the report (`preflight`) are `fresh_build`,
`needs_libpython`, and `parse`. They and the version are the same for each
commit with the same tables, so `results/s1/summary.json` does not change
for each commit.

The lint job checks only the tools of `scripts/setup` (`--tool sqlfluff
--tool sqlfluff-rs --tool sqruff`), because it has no sqll build.
