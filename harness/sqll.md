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
such option. The other parser limits are the sqlfluff defaults. Exit
codes: 0; 1 for a lex error, a parse error, or an unparsable segment (the
error lines go to stderr); 2 for a usage, input, or output error. Only a
panic (a sqll bug) gives another exit code (101). The output has the bytes
of the sqlfluff output (Python `json.dumps`) and a new line. The
`filepath` is the path as `os.path.normpath` gives it (`stdin` for `-`). A
file with an extension that is not `.sql`, `.sql.j2`, `.dml`, `.ddl`, or
`.pkb` (`sql_file_exts` of the sqlfluff default config, in any case) gives
`[]` and exit code 0, as in sqlfluff. As in click, sqll reads all
arguments before `-h`: an unknown option or a missing value is an error
also with `-h`.

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
  code 1. The limit keeps the tree in the stack of the command thread
  (256 MiB): at the limit, the deepest trees that were measured need about
  10 MiB (33 MiB in a debug build). sqlfluff has no such
  limit, but a deep tree stops it with a `RecursionError` and exit code 1
  (for example 800 nested brackets with `max_parse_depth = 0`). The
  sqlfluff test gives each dialect file the depth 600, or 2000 for
  `ansi/expression_recursion.sql`.
- An argument that is not UTF-8 (for example a file name) gives
  `unsupported: non-UTF-8 argument` and exit code 2. sqlfluff reads it.
- sqll reads UTF-8 only (with or without a byte order mark). sqlfluff also
  detects other encodings.
- sqll has no file size limit (as `large_file_skip_byte_limit = 0`).
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
