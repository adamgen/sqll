# S9 decision: the external corpus

Status: design (T1); run and report (T3); untemplated content (T4);
templated content (T5); recorded results (T6); CI (T7). Scope: STONES.md S9;
CONSTITUTION.md G1.3, G3, G4.2, G4.3, G4.5. "Measured": `parse` runs of
the `scripts/setup` tools on 2026-10-28 (4 CPUs, 16 GiB, machine lock),
in a new folder with no config file above it. PR #29 (T1) and the T3 pull
request have the commands and the output.

## Licenses

- **Allowlist.** Use a source only if its license is permissive and
  allows redistribution: MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause,
  PostgreSQL, ISC, or CC0-1.0. Reason: S9 redistributes the files. The CI
  cache, the CI artifacts (public), the report, and the failure reasons
  keep copies or parts of them.
- **No SQL in the repository.** The manifest in `corpus/` records the
  source, the pinned commit, the path, the license (G4.3), and the sha256
  of each file. The harness fetches each file at run time by the commit
  and checks the sha256. A missing file or another sha256 stops the run
  (fail closed). Reason: a small repository; the commit and the sha256
  make the input fixed.
- **Attribution** (CONSTITUTION 2.6). MIT and BSD need the notice with
  each copy; Apache-2.0 4(a) needs a copy of the license. Thus:
  1. T2 (schema), T4 and T5 (data): for each source, the manifest records
     each copyright holder and the path and sha256 of each license or
     notice file ("Content"). Example: `jOOQ/sakila` has "jOOQ Object
     Oriented Querying" (`LICENSE`) and "DB Software Laboratory"
     (`README.md`).
  2. T2 (fetch), T3 (report), T7 (CI): the fetch gets and checks these
     files too. Each cache or artifact with corpus text also has them and
     the manifest.
  3. T4 (cross-track): a THIRD_PARTY.md entry that points to the `corpus/`
     manifest.
- **Out: copyleft.** Example: `mysql/mysql-server` (commit `06bcb0e`,
  `LICENSE`): "This software is released under version 2 of the GNU
  General Public License".
- **Out: TPC-H and TPC-DS query sets.** Both kits have the same TPC
  EULA (`EULA.txt` of `gregrahn/tpch-kit` commit `852ad0a` and
  `gregrahn/tpcds-kit` commit `5a3a817`; only the line ends differ).
  Clause 4.a: "You may not: (1) use, copy, ... distribute ... the
  Materials ... except as expressly permitted under this Agreement".
  Clause 9 allows distribution only "under this Agreement". Clause 4.c
  limits the disclosure of "performance results"; S9 publishes times.

## Sources

A source is a public git repository that a run can read with no login,
pinned to a full commit sha, with an allowlist license file at that
commit. Kinds: database regression SQL, sample databases in many
dialects, and warehouse and dbt projects. Reason: real SQL that people
use. Measured candidates:

| Source (commit) | License | Files |
|---|---|---|
| `postgres/postgres` (`7885b94`, REL_17_6) `src/test/regress/sql/` | PostgreSQL | 224; 70 of 16 KiB or more |
| `lerocha/chinook-database` (`7f67772`) | MIT | 11 of 558 to 614 kB, 6 dialects |
| `jOOQ/sakila` (`e089a5b`) | BSD-2-Clause | SQL 0.7 to 51 kB; data 2.5 to 9.1 MB |
| `gnosischain/dbt-cerebro` (`b5e7f2a`), `admindio/simple_ga4_dbt` (`6452a9b`) | MIT | dbt models |

`gitlab-data/analytics` is out: it needs a login (HTTP 302 to `sign_in`).
T4 chose the untemplated sources, T5 the templated sources ("Content").

## Selection

The rules use only the manifest data and the file bytes, never a tool
result (no tool bias); a tool failure is data. No file is changed: no
edit, join, or strip (G4.5). A file is in if its source passes
"Sources", its path matches a manifest glob of the source, its size is
in the range ("Size"), its bytes are UTF-8, and no earlier file (sorted
by source and path) has its sha256.

**Dialect.** The manifest gives one sqlfluff dialect name for each file,
from the database of the source (`Chinook_SqlServer.sql`: `tsql`). All
tools get it. CockroachDB and YugabyteDB files get `postgres`.

**Globs.** A glob names folders of SQL of one database. The choice of a
glob uses only the paths, sizes, and kind of the files, never a tool
result. No TPC material. A folder with megabytes of data or text rows of
one schema, or with too many files for the time budget of one dialect,
gets a narrower glob or none. A file can be excluded by its path. The
source note gives the reason.

## Content

T4 (untemplated files). `scripts/s9/select` makes `corpus/sources.json`
from `corpus/select.json` and the cache with these rules. It fails closed
on a license, copyright notice, or TPC text that the record does not
cover (the list: corpus/README.md, "Selection"). Thus a holder or license
that a selected file names is part of the record. A file with other terms
goes to its own source (`sakila-mysql`), or it or its glob is removed;
the source note gives the reason. The counts of each source: the output
of `scripts/s9/select --check`. Smoke: the files of 32 KiB or less.
Limit (test): 2 MiB and 100 files.

T5 (templated files): the `models/` globs of `dbt-cerebro` (ClickHouse)
and `simple_ga4_dbt` (BigQuery), with the Jinja rule ("Templated files").
Measured on 201 `.sql` files of 8 KiB or more in 55 candidate
repositories. Out: `dbt-labs/jaffle_shop` (no file of 8 KiB or more); 44
`fivetran/dbt_*` packages (each supports more than one database, so no one
dialect; 2 of their 62 models of 8 KiB or more pass the rule);
`tuva-health/tuva` (no model passes the rule); macro packages such as
`dbt-labs/dbt-utils` (a macro file renders to almost no SQL);
`duneanalytics/spellbook` (Business Source License), `cal-itp/data-infra`
(AGPL-3.0), `prefeitura-rio/queries-rj-smtr` (GPL-3.0),
`snowplow-incubator/dbt-snowplow-identities` (Snowplow license),
`wnl-icb-analytics/dbt-analytics` (Open Government Licence v3).

Out: `pthom/northwind_psql` (Ms-PL); `OHDSI/CommonDataModel`,
`GoogleCloudPlatform/data-analytics-golden-demo` (no root license file);
`duckdb/duckdb` v1.5.6 (only TPC-DS queries in range); `trinodb/trino`
484 (no `.sql` file in range).

## Templated files

The manifest marks the templated (Jinja or dbt) files. The tools render
them with the jinja templater and its dbt builtins
(`apply_dbt_builtins = True`, the default of sqlfluff and sqruff). The
dbt templater is out (G1.3). Their leaf text is the render: on
`jaffle_shop/models/customers.sql` (1195 bytes) each tool gives a tree
of 1156 characters (measured). Thus the check compares the leaf text
with the render of the pinned sqlfluff (the reference, as in S2). If
that render fails, the file stays, and each tool gets the status `no
reference` with its parse data: no tool gets a success on it.

**Jinja rule** (T5, `harness/sqll_harness/corpus/jinja_names.py`). A
templated file is in only if its Jinja code reads only the dbt builtins of
the pinned sqlfluff
(`DBT_BUILTINS`), the Jinja globals, `loop` in a `for` block, `varargs` and
`kwargs` in a `macro` block, and names that it sets before in the same
block or an outer block. Each tag must be complete. Each statement must be
`if`, `for`, `set`, `macro`, `with`, `filter`, `do`, `raw`, or an end.
Thus no `import`, `include`, `extends`, or `call`, and no `break` or
`continue` (the pinned sqlfluff loads only the `do` extension). The scan reads
only the file text, with no tool and no Jinja library. Reason: then the
file is the only render input, and its sha256 pins the render. The
`selection` of each file gives the names that it reads. On the 201 files
of "Content", the rule and `jinja2.meta.find_undeclared_variables` agree
on 200. On 1 file, Jinja also names a variable that a `set` block in an
`if` block sets, but the file does not read it (measured).

**Render settings** (all tools and the reference): `templater = jinja`
and `apply_dbt_builtins = True`. No template variable, macro path, or
library path. The builtins give `ref('a')` = `a`, `var(...)` = `item`, and
`is_incremental()` = true.

## Size

- **Untemplated: 16 KiB to 2 MiB.** S2 inputs stop at 16,383 bytes.
- **Templated: 8 KiB to 2 MiB.** S2 has no templated inputs. Of the 1395
  `.sql` files of the 7 fivetran packages, 34 have 8 KiB or more and 2
  have 16 KiB or more (measured).
- **Limit: 2 MiB (2,097,152 bytes)**, from memory. Measured with lifted
  limits (see "Settings"):

| Input | sqlfluff | `sqlfluff[rs]` | sqruff |
|---|---|---|---|
| 11 Chinook files, 0.56 to 0.61 MB: wall s/MB | 27 to 187 | 13 to 54 | 1 to 9 |
| Same: max RSS MiB/MB | 962 to 1901 | 1885 to 3368 | 290 to 995 |
| `postgres-sakila-insert-data.sql`, 7.96 MB | 3089 s (388 s/MB), 6634 MiB | abort at the 11 GiB address limit | 102.6 s, 4120 MiB |

At 3368 MiB/MB, a 2 MiB file needs about 7 GiB for `sqlfluff[rs]`, less
than half of a 16 GB GitHub runner. The limit is a rule on the size only.

## Settings

All tools get the S2 settings (`harness/bench.md`, "Settings": the
dialect, `templater = raw`, `rules = all`, no large-file skip). S9 adds
`templater = jinja` for the templated files, and `max_parse_nodes = 0`
(no limit) for all files. The `sqlfluff[rs]` layer also gets
`rust_parser_max_iterations = 1000000000000`. `max_parse_depth` stays
600. Reason: the defaults stop the parse of large files with no tree; the
result then measures the limit, not the parser. Measured on 87 files of
16 to 614 kB (70 PostgreSQL regression, 6 Sakila schema, 11 Chinook):

- Default `max_parse_nodes = 100000`: sqlfluff, `sqlfluff[rs]`, and
  sqruff give exit code 1 and no tree on each of the 11 Chinook files.
  Message: "Maximum parse node count exceeded (limit 100000)". The
  largest file with no failure has 305,102 bytes.
- `sqlfluff[rs]` with `max_parse_nodes = 0` and the default
  `rust_parser_max_iterations = 3000000`: a panic, "Parser exceeded
  maximum iteration limit (3000000)", on 5 of the 11 files. With
  30,000,000, `Chinook_PostgreSql.sql` passes. The 3,000,000 limit stops
  it after 6.7 s, so the timeout, not 10^12, stops a runaway parse.
- Lifted: each tool gives a tree on each file, but sqruff panics on
  `strings.sql` (`parsers.rs:333`) with the defaults and with lifted
  limits. No run of these 87 files stops at `max_parse_depth`.
- T5 smoke run: each tool gives no tree (exit code 1) on the templated
  `dbt-cerebro/models/p2p/staging/stg_crawlers_data__ipinfo.sql`.
  `sqlfluff lint` and `sqlfluff[rs]` lint of its render say "Maximum parse
  depth exceeded (limit 600)". The setting stays; T6 records the result.

## Parse check and report

A parse is a success if: exit code 0, a tree that is not null, no
unparsable segment, and leaf text = input (untemplated files; templated:
"Templated files"). The report also records, for each file and tool: the
count and bytes of unparsable segments, the reason, wall and CPU time, max
RSS (an upper bound: "Report"), and bytes per second. Totals and ratios
use only the files where each compared tool succeeds (as S2).

Line ends: the compare removes a first byte order mark and changes each
`\r\n` and `\r` to `\n` in both texts. Reason: the pinned sqlfluff does
this before it lexes, and each of the 3 tools gives a tree of 17
characters for a 19-byte `\r\n` file (measured). The render of a
templated file is the output of `sqlfluff render` with
`render_variant_limit = 1`: the tree is that of the first variant, and the
output then has no variant headers. The corpus check reads
the tree with the adapter `read_tree` and the S2 problem messages, not
with `check_tree`: it needs the unparsable count and this compare.

## Report

`python -m sqll_harness.corpus run` writes `out/corpus.json` (`kind`
`sqll-corpus-report`, `format` 1). As S2: `sqlfluff_ref`, `harness`,
`profile`, `policy`, `machine`, `timer`, and `parts` (the shards of a
merged report). Also: `manifest_sha256`; `scope` (`tools`, `shard`);
`tools` (version, and the settings for `raw` and `jinja`); `inputs` (the
manifest record of each file, and `reference`: the status and sha256 of
the sqlfluff render of a templated file).

One result for each file and tool: `status` (`ok`, `unparsable`,
`no_reference`, `invalid`, `unsupported`, `error`), `reason`, `exit_code`
(warmup run), `unparsable` (`count` and `bytes` of the outer unparsable
segments), `runs`, `samples`, `stats` (wall and CPU: n, median, min, max,
MAD), `max_rss_kib`, and `bytes_per_s` (input bytes / median wall).
`max_rss_kib` comes from the S2 timer (`os.wait4()`). On Linux it is the
larger of the tool RSS and the RSS of the harness process when it starts
the tool, so a value at or below the harness RSS is only an upper bound.
Core issue [#38](https://github.com/adamgen/sqll/issues/38). Only `ok`,
`unparsable`, and `no_reference` have stats. `unparsable`: a tree with all
the text and unparsable segments, exit code 0 or 1. `invalid`: a crash,
panic, timeout, no tree, other leaf text, or another exit code.

`totals`: the count of each status for each tool. `compared`: for the
files where each tool is `ok`, the count, the bytes, and for each tool the
sums of the median times, the bytes per second, and the ratios to
sqlfluff. The schema check calculates each derived number again.

`merge` fails on a missing or repeated shard, or another run record.
`check --baseline FILE [--full]` compares the stable data, fail closed:
the sqlfluff ref, the tool versions and settings, the input records (with
the render sha256), and the status and unparsable count and bytes of each
result. Not the timings, reasons, exit codes, or machine. A reason can
have parts of a corpus file, so an artifact with a report also has the
manifest and the license files (T7).

## Profiles

| Profile | Files | Runs | Timeout |
|---|---|---|---|
| smoke | 32 KiB or less | 1 warmup, 1 timed | 1200 s |
| full | all | 1 warmup, 1 to 5 timed, more while their sum is less than 10 s | 1200 s |

The warmup run is the check run (as S2). Measured: one run of the 40
files of 16 to 32 KiB took 49 s (sqlfluff), 32 s (`sqlfluff[rs]`), and
2.7 s (sqruff). Max/min wall ratio of 2 runs of the same work: median
1.11, max 2.27 (206 pairs under 1 s); median 1.12, max 1.68 (101 pairs of
1 to 10 s). Long runs get 1 timed run for the time budget (up to 105 s for a
Chinook file with sqlfluff); short runs get more to decrease the noise.
sqlfluff takes more time per MB on larger files (187 s/MB at 0.6 MB,
388 at 8 MB). At 388 s/MB a 2 MiB file takes 814 s, less than the
timeout (1200 s). T6 confirms these values in the controlled run.

T6 (controlled full run, `results/S9/baseline.json`): no run has a
timeout. The longest run is 109.6 s (sqlfluff, `Chinook_PostgreSql.sql`).
Max RSS: 1141 MiB (sqlfluff), 2022 MiB (`sqlfluff[rs]`), 590 MiB (sqruff).
These are tool values: they are above the harness RSS of the run (251232
KiB). 438 of the 492 results have exactly 251232 KiB, so they do not give
the tool RSS ("Report").

T6, `max_parse_depth = 600`: sqlfluff and `sqlfluff[rs]` give no tree
(`invalid`) on 2 tsql files of `sql-server-maintenance-solution`:
`DatabaseBackup.sql` and `MaintenanceSolution.sql`. A lint with the run
settings says "Maximum parse depth exceeded (limit 600)" (status/S9.md).
sqruff gives a tree for both. The setting stays 600 in T6. Reasons: 600 is
the default of the pinned sqlfluff, a guard against deep input, and not a
limit of the file size as `max_parse_nodes`; and a change of a setting
needs a new full run. T8 decides if S9 lifts it. No other setting changes.

## Code, CI, and sqll

- Reuse: the S2 timer and `Policy`, the bench adapters and registry, the
  validity checks, and the report, merge, and baseline-check patterns.
  Code: `harness/sqll_harness/corpus/`, run as `python -m
  sqll_harness.corpus` and from `scripts/s9/`. No change to
  `harness/sqll_harness/cli.py` or the bench core.
- `ci/matrix.d/S9.json` is not used: `ci/matrix.py` reads each entry as
  an S1 suite. The shard count is in a file in `corpus/`.
- CI (T7, cross-track): smoke on each pull request that is not documents
  only (a small download, a baseline check, no timing gate). Full on push
  to main and `workflow_dispatch`, sharded by file, with a merge job and a
  baseline check, as `bench-full`. A download cache keyed by a hash of the
  manifest. `corpus/ci-shards.json` has 6 shards: with the T6 times, the
  longest shard has 849 s of tool runs (4 shards: 1177 s; 8: 626 s).
  Each artifact with a report also has the manifest and the license files
  (`notices`).
- sqll joins after S3b with its bench registry entry, with no change to
  the corpus files. T3 proves this with a test-double tool.
