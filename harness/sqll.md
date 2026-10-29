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

`sqll parse` is `sqlfluff parse --templater raw --ignore-local-config`: it
reads no config file, no in-file config line, and no other setting.
`max_parse_depth` has its option (default 600, 0: no limit); the other
parser limits are the sqlfluff defaults. Exit codes are those of
`sqlfluff parse`: 0; 1 for a lex error, a parse error, or an unparsable
segment (the error lines go to stderr); 2 for a usage or input error. The
output has the bytes of the sqlfluff output (Python `json.dumps`) and a new
line. Differences from `sqlfluff parse`:

- `-f` has only `json`, and it is the default.
- With `-m`, sqlfluff also adds the source position keys to each record.
  sqll gives the meta segments but no position keys.
- sqll reads UTF-8 only (with or without a byte order mark). sqlfluff also
  detects other encodings.
- sqll has no file size limit (as `large_file_skip_byte_limit = 0`).
- PATH is one file, or `-` (stdin).

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
