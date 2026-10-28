# S9 decision: the external corpus

Status: design (T1). Scope: STONES.md S9; CONSTITUTION.md G1.3, G3,
G4.2, G4.3, G4.5. "Measured": `parse` runs of the `scripts/setup` tools
on 2026-10-28 (4 CPUs, 16 GiB, machine lock, other tracks active), in a
new folder with no config file above it. The T1 pull request has the
commands and the output.

## Licenses

- **Allowlist.** Use a source only if its license is permissive and
  allows redistribution: MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause,
  PostgreSQL, ISC, or CC0-1.0. Reason: the CI download cache, the report,
  and the failure reasons keep copies or parts of the files.
- **No SQL in the repository.** The manifest in `corpus/` records the
  source, the pinned commit, the path, the license (G4.3), and the sha256
  of each file. The harness fetches each file at run time by the commit
  and checks the sha256. A missing file or another sha256 stops the run
  (fail closed). Reason: a small repository; the commit and the sha256
  make the input fixed.
- **Out: copyleft.** Example: `mysql/mysql-server` (commit `06bcb0e`,
  `LICENSE`): "This software is released under version 2 of the GNU
  General Public License".
- **Out: TPC-H and TPC-DS query sets.** The TPC EULA
  (`gregrahn/tpcds-kit`, commit `5a3a817`, `EULA.txt`), clause 4.a: "You
  may not: (1) use, copy, ... distribute ... the Materials ... except as
  expressly permitted under this Agreement". Clause 9 allows distribution
  only "under this Agreement". Clause 4.c limits the disclosure of
  "performance results", and S9 publishes parse times.

## Sources

A source is a public git repository that a run can read with no login,
pinned to a full commit sha, with a license file at that commit in the
allowlist. Kinds: regression SQL of a database (for example PostgreSQL),
sample databases in many dialects, and open-source warehouse and dbt
projects. Reason: real SQL that people use. Measured candidates:

| Source (commit) | License | Files |
|---|---|---|
| `postgres/postgres` (`7885b94`, REL_17_6) `src/test/regress/sql/` | PostgreSQL | 224; 70 of 16 KiB or more |
| `lerocha/chinook-database` (`7f67772`) | MIT | 11 of 558 to 614 kB, 6 dialects |
| `jOOQ/sakila` (`e089a5b`) | BSD-2-Clause | SQL 0.7 to 51 kB; data 2.5 to 9.1 MB |
| `dbt-labs/jaffle_shop` (`fd7bfac`), 7 `fivetran/dbt_*` packages | Apache-2.0 | dbt models |

`gitlab-data/analytics` is out: it needs a login (HTTP 302 to `sign_in`).
T4 and T5 choose the final sources with these rules.

## Selection

The rules use only the manifest data and the bytes of each file, never
a tool result (no tool bias). A tool failure is data, not a reason to
remove a file. No file is changed: no edit, join, or strip (G4.5).

1. The source passes "Sources".
2. The path matches a glob of the source in the manifest.
3. The size is in the range ("Size").
4. The bytes are UTF-8.
5. A file with the sha256 of an earlier file (sorted by source and path)
   is a duplicate. Use it only one time.

**Dialect.** The manifest gives one sqlfluff dialect name for each file,
from the database that the source names (for example
`Chinook_SqlServer.sql`: `tsql`). All tools get it. CockroachDB and
YugabyteDB files get `postgres` (no own sqlfluff dialect).

## Templated files

The manifest marks the templated (Jinja or dbt) files. The tools render
them with the jinja templater and its dbt builtins
(`apply_dbt_builtins = True`, the default of sqlfluff and sqruff). The
dbt templater is out (G1.3). Their leaf text is the rendered text, not
the input. Measured on `jaffle_shop/models/customers.sql` (1195 bytes):
each tool gives a tree of 1156 characters. Thus for these files the check
compares the leaf text with the render of the pinned sqlfluff (the
reference, as in S2). T5 gives the render settings of each source.

## Size

- **Untemplated: 16 KiB to 2 MiB.** S2 inputs stop at 16,383 bytes.
- **Templated: 8 KiB to 2 MiB.** S2 has no templated inputs. Measured: of
  the 1395 `.sql` files of the 7 fivetran packages, 34 have 8 KiB or more
  and 2 have 16 KiB or more.
- **Limit: 2 MiB (2,097,152 bytes)**, from memory. Measured with lifted
  limits (see "Settings"):

| Input | sqlfluff | `sqlfluff[rs]` | sqruff |
|---|---|---|---|
| 11 Chinook files, 0.56 to 0.61 MB: wall s/MB | 27 to 187 | 13 to 54 | 1 to 9 |
| Same: max RSS MiB/MB | 962 to 1901 | 1885 to 3368 | 290 to 995 |
| `postgres-sakila-insert-data.sql`, 7.96 MB | 3089 s (388 s/MB), 6634 MiB | abort at 11,235 MiB (11 GiB address limit), 237 s | 102.6 s, 4120 MiB |

At 3368 MiB/MB, a 2 MiB file needs about 7 GiB for `sqlfluff[rs]`:
less than half of the 16 GB of a GitHub-hosted Linux runner. At 8 MB it
does not complete in 11 GiB. The limit is a rule on the size only.

## Settings

All tools get the S2 settings (`harness/bench.md`, "Settings": the
dialect, `templater = raw` or `jinja`, `rules = all`, no large-file skip)
and `max_parse_nodes = 0` (no limit). The `sqlfluff[rs]` layer also gets
`rust_parser_max_iterations = 1000000000000`. `max_parse_depth` stays
600. Reason: the defaults stop the parse of large files with no tree; the
result then measures the limit, not the parser. Measured on 87 files of
16 to 614 kB (70 PostgreSQL regression, 6 Sakila schema, 11 Chinook):

- Default `max_parse_nodes = 100000`: sqlfluff, `sqlfluff[rs]`, and
  sqruff give exit code 1 and no tree on each of the 11 Chinook files.
  Message: "Maximum parse node count exceeded (limit 100000)". The
  sqlfluff JSON output has only `"segments": null`. The largest file with
  no failure has 305,102 bytes.
- `sqlfluff[rs]` with `max_parse_nodes = 0` and the default
  `rust_parser_max_iterations = 3000000`: a panic, "Parser exceeded
  maximum iteration limit (3000000)", on 5 of the 11 files. With
  30,000,000, `Chinook_PostgreSql.sql` passes. The 3,000,000 limit stops
  that file after 6.7 s, so 10^12 iterations take much longer than the
  timeout: the timeout stops a runaway parse.
- Lifted: each tool gives a tree on each file, but sqruff panics on
  `strings.sql` (`parsers.rs:333`, also with the defaults). Thus no run
  stops at `max_parse_depth`.

## Parse check and report

A parse is a success if: exit code 0, a tree that is not null, no
unparsable segment, and leaf text = input (untemplated files; templated:
"Templated files"). The report also records, for each file and tool: the
count and bytes of unparsable segments, the reason, wall and CPU time,
max RSS, and bytes per second. Totals and ratios use only the files where
each compared tool succeeds (as S2).

## Profiles

| Profile | Files | Runs | Timeout |
|---|---|---|---|
| smoke | 32 KiB or less | 1 warmup, 1 timed | 1200 s |
| full | all | 1 warmup, 1 to 5 timed, more while their sum is less than 10 s | 1200 s |

The warmup run is the check run (as S2). Measured: one run of the 40
files of 16 to 32 KiB took 49 s (sqlfluff), 32 s (`sqlfluff[rs]`), and
2.7 s (sqruff). Two runs of the same work (2 settings of a file with
the same result) had a median max/min wall ratio of 1.11 (206 pairs
under 1 s), 1.12 (101 pairs of 1 to 10 s), and 1.08 and 1.15 (2 pairs of
10 s or more). Thus long runs get 1 timed run and short runs get more.
The time per MB of sqlfluff increases with the size (187 s/MB at 0.6 MB,
388 s/MB at 8 MB). At 388 s/MB, a 2 MiB file takes 814 s; the timeout
(1200 s) is more than that. T6 confirms these values in the controlled
run.

## Code, CI, and sqll

- Reuse: the S2 timer and `Policy`, the bench adapters and registry, the
  validity checks, and the report, merge, and baseline-check patterns.
  Code: `harness/sqll_harness/corpus/`, run as `python -m
  sqll_harness.corpus` and from `scripts/s9/`. No change to
  `harness/sqll_harness/cli.py` or the bench core.
- `ci/matrix.d/S9.json` is not used: `ci/matrix.py` reads each entry as
  an S1 suite. The shard count is in a file in `corpus/`.
- CI (T7, one cross-track pull request): smoke on each pull request that
  is not documents only (a small download, a baseline check of the stable
  data, no timing gate). Full on push to main and `workflow_dispatch`,
  sharded by file, with a merge job and a baseline check, as `bench-full`.
  A download cache keyed by the manifest sha256.
- sqll joins after S3b with its bench registry entry, with no change to
  the corpus files. T3 proves this with a test-double tool.
