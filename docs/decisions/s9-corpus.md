# S9 decision: the external corpus

Status: design (T1); run and report (T3); untemplated content (T4);
templated content (T5); recorded results (T6); CI (T7); exit (T8); the
plan of the sqll results ("sqll results"). Scope: STONES.md S9;
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
sqruff gives a tree for both. All 3 tools give no tree on
`stg_crawlers_data__ipinfo.sql`, as in the T5 smoke run: the same message. The setting stays 600 in T6. Reasons: 600 is
the default of the pinned sqlfluff, a guard against deep input, and not a
limit of the file size as `max_parse_nodes`; and a change of a setting
needs a new full run. T8 decides if S9 lifts it. No other setting changes.

T8 decision: S9 keeps `max_parse_depth = 600`. Reasons: the T6 reasons
above; the S9 rule that a failure is data, not a reason to change the
input or the settings for some files; and the same settings for all tools
and files. `max_parse_nodes` and `rust_parser_max_iterations` are not the
same: their defaults stop the parse because of the file size only
("Settings"). The 7 `invalid` results that stop at `max_parse_depth` stay
in the baseline: sqlfluff and `sqlfluff[rs]` on `DatabaseBackup.sql` and
`MaintenanceSolution.sql`, and all 3 tools on
`stg_crawlers_data__ipinfo.sql`. The S3 track gets them as input
(status/S9.md, "Input for S3").

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
  the corpus files. T3 proves this with a test-double tool. The bench
  registry has sqll from S3 (T13), so the corpus run leaves it out by
  default until then (`LATER` in `corpus/run.py`). The sqll task of S9
  removes it from `LATER` and records a new baseline.

## sqll results

This section is the plan and design record of T9 (plan and design record
of the sqll results: the sqll settings layer, the Jinja files, the
baseline rule for sqll, the speed tables, and the CI wiring), a task of S9
(External corpus: large, complex SQL files from public sources, with their
source and license; the report shows parse success and speed for each
file, for each tool). It has 6 decisions. "Tasks" at the end gives the
task of each decision.

**Measured** on 2026-11-11, on main `0fb9cdb`, on the host (not the CI
image): Intel(R) Xeon(R) Processor @ 2.10GHz, 4 CPUs, 15.7 GiB. Runs A
and B had the machine lock. The `iter.py` output below is from
2026-11-12, on the same host, sqll binary, and harness code (the head of
this pull request changes only documents). Each of the 3 `iter.py`
commands had the machine lock. `flock /tmp/sqll-machine.lock sh -c 'scripts/setup &&
scripts/build-sqll'`: exit code 0, "build-sqll: wrote out/sqll/build.json".
The sqll version is
`0.1.0+tables.5371ded8ae219be1a62cd34b1b793d36c41bc9fa432f344de5d84f48d2d059e8`,
the version of `results/s2/baseline.json`. `python -m sqll_harness.corpus
fetch`: 164 files and 19 license files, sha256 checked. The sqlfluff and
sqruff results here are those of `results/S9/baseline.json` (2026-10-28,
CI image). The body of the pull request of this task has each script
below (`iter.py`, `layer_run.py`, `parity.py`, `pairs.py`, `maxratio.py`,
`shards.py`). It has the full output of `iter.py`, `parity.py`,
`pairs.py`, `maxratio.py`, and `shards.py`. Of runs A and B, it has only a
summary: the tool table, `compared`, the `invalid` lines (with 1 of the
19 Jinja lines), and the times. It does not have the uv warning line,
the progress line of each file, the 104 `unparsable` reasons, and 18 of
the 19 Jinja lines. Here, the output shows only the lines of the files
that a decision uses. `...` replaces the long sqll version and the end
of a repeated message, and the column spaces are shorter.

Run A, the harness of main (no corpus layer for sqll):

```
$ time flock /tmp/sqll-machine.lock uv run --frozen --project harness \
    python -m sqll_harness.corpus run --profile full --tool sqll --out sqll-full.json
tool  version  ok  unparsable  no_reference  invalid  unsupported  error
sqll  ...      34  104         0             26       0            0
real 1m36.139s
```

Run B, the same command through `layer_run.py`. That script changes no
file. It only adds a corpus layer for a tool and then calls the corpus
command (`from sqll_harness.corpus import run as cr` and
`from sqll_harness.corpus.__main__ import main`):

```
cr.TOOL_LAYERS[sys.argv[1]] = json.loads(sys.argv[2])
sys.exit(main(sys.argv[3:]))
```

```
$ time flock /tmp/sqll-machine.lock uv run --frozen --project harness python -I layer_run.py \
    sqll '{"core": {"rust_parser_max_iterations": 1000000000000, "max_parse_depth": 600}}' \
    run --profile full --tool sqll --out sqll-layer.json
tool  version  ok  unparsable  no_reference  invalid  unsupported  error
sqll  ...      39  104         0             21       0            0
real 2m25.419s
```

### 1. Settings

Decision: sqll gets a corpus layer in `TOOL_LAYERS`, as `sqlfluff-rs`:
`rust_parser_max_iterations = 1000000000000`. It gets no other layer. sqll
gets the benchmark settings (`harness/bench.md`, "Settings") and the
corpus settings ("Settings" above: `max_parse_nodes = 0`, and the render
settings for a templated file) through its bench adapter
(`harness/sqll_harness/bench/sqll.py`, `SqllBench`; its `layer` adds
nothing). `max_parse_depth` stays the default, 600, as for the other 3
tools ("Profiles").

Data:

- sqll has the iteration limit of its base. `crates/ported.json`: "Above
  the iteration limit (rust_parser_max_iterations), the parser returns a
  ParseError, not a panic. Each sub-parse (the main parse and each probe)
  has its own count of iterations." The default is 3000000
  (`crates/sqll_config/src/defaults.rs`).
- Run A: 5 Chinook files are `invalid` ("warmup run: no parse tree (exit
  code 1)"), and sqlfluff gives `ok` on each. `iter.py` parses each file
  one time with the config of the harness (`run.tool_config`, then
  `SqllBench.write_config`, `argv`, and `env`). With no layer, and then
  with the layer of run B:

```
$ flock /tmp/sqll-machine.lock uv run --frozen --project harness python -I iter.py Chinook_ '{}'
Chinook_MySql.sql (600574 B): exit 1, 0.768 s, -; stderr: PRS: Parser exceeded maximum iteration limit (3000000). This may be caused by runaway parser logic or a very complex SQL query.
Chinook_MySql_AutoIncrementPKs.sql (563074 B): exit 1, 0.734 s, -; stderr: PRS: Parser exceeded maximum iteration limit (3000000). ...
Chinook_PostgreSql.sql (600200 B): exit 1, 0.702 s, -; stderr: PRS: Parser exceeded maximum iteration limit (3000000). ...
Chinook_PostgreSql_AutoIncrementPKs.sql (562854 B): exit 1, 0.739 s, -; stderr: PRS: Parser exceeded maximum iteration limit (3000000). ...
Chinook_PostgreSql_SerialPKs.sql (562563 B): exit 1, 0.722 s, -; stderr: PRS: Parser exceeded maximum iteration limit (3000000). ...
$ flock /tmp/sqll-machine.lock uv run --frozen --project harness python -I iter.py Chinook_ '{"core": {"rust_parser_max_iterations": 1000000000000}}'
Chinook_MySql.sql (600574 B): exit 0, 1.233 s, tree 599801 chars, unparsable 0 (0 B); stderr:
Chinook_MySql_AutoIncrementPKs.sql (563074 B): exit 0, 1.228 s, tree 562301 chars, unparsable 0 (0 B); stderr:
Chinook_PostgreSql.sql (600200 B): exit 0, 2.325 s, tree 599427 chars, unparsable 0 (0 B); stderr:
Chinook_PostgreSql_AutoIncrementPKs.sql (562854 B): exit 0, 2.196 s, tree 562081 chars, unparsable 0 (0 B); stderr:
Chinook_PostgreSql_SerialPKs.sql (562563 B): exit 0, 2.153 s, tree 561790 chars, unparsable 0 (0 B); stderr:
```

- With the layer, the sqll result (status, unparsable count and bytes) is
  the sqlfluff result on each of the 145 untemplated files. `parity.py`
  counts the files by templater:

```
$ python3 -I parity.py results/S9/baseline.json sqll-full.json
[(('jinja', 'other'), 18), (('jinja', 'same'), 1), (('raw', 'other'), 5), (('raw', 'same'), 140)]
$ python3 -I parity.py results/S9/baseline.json sqll-layer.json
[(('jinja', 'other'), 18), (('jinja', 'same'), 1), (('raw', 'same'), 145)]
```

- sqll accepts `max_parse_nodes = 0` (no limit) and `max_parse_depth =
  600`: runs A and B have no `unsupported` and no `error` result. sqll
  stops on the 2 files where sqlfluff stops, with the same limit:

```
$ flock /tmp/sqll-machine.lock uv run --frozen --project harness python -I iter.py sql-server-maintenance-solution/ '{"core": {"rust_parser_max_iterations": 1000000000000}}'
DatabaseBackup.sql (267445 B): exit 1, 0.180 s, -; stderr: PRS: Maximum parse depth exceeded (limit 600). This may indicate deeply nested SQL or a malicious input.
MaintenanceSolution.sql (595994 B): exit 1, 0.328 s, -; stderr: PRS: Maximum parse depth exceeded (limit 600). This may indicate deeply nested SQL or a malicious input.
```

Reasons: the reason of the `sqlfluff-rs` layer ("Settings"). The default
iteration limit stops the parse of a large file because of its size, and
the result then measures the limit, not the parser. The timeout (1200 s)
stops a runaway parse. The layer of run B has `max_parse_depth = 600` only
to show that sqll accepts it. The corpus layer does not set it, so each
tool uses the default.

Also: the harness reason of the 5 results of run A has no tool message.
The code task (T11) adds the "PRS: " line of sqll to the reason, so that
the reason names the limit. It adds the line in the corpus code
(`harness/sqll_harness/corpus/run.py`, where the reason of an `invalid`
result reads the warmup stderr). It does not change the problem messages
of the bench adapters (`harness/sqll_harness/bench/sqll.py` and
`bench/adapter.py`, core paths).

### 2. The 19 Jinja files

Decision: the expected status of sqll on each of the 19 templated files is
`unsupported`, until S11 (Jinja templater: the last stone; decision of the
human owner (2026-11-07): do not write a Jinja engine in sqll; decide with
data how sqll supports Jinja; sqll passes 100% of the Jinja cases that the
decision keeps, and the code generation stone supports Jinja if kept; each
other Jinja case is in a known-failure list with its reason). This result
is expected. It is not a known failure to hide: the report counts the 19
results, and status/S9.md lists them with their reason.

Data: in runs A and B, sqll gives exit code 2 on each of the 19 files,
with this stderr: "Error: unsupported: templater jinja for an empty file or
a file with a Jinja tag ("{{", "{%", or "{#"). sqll has no Jinja templater
yet (S11). Use the raw templater (--templater raw)." The harness of main
gives `invalid`, because exit code 2 is not a parse exit code (0 or 1).
sqlfluff gives `ok` on 18 of these files, and `invalid`
(`max_parse_depth`) on `stg_crawlers_data__ipinfo.sql`.

Change (code task): when sqll fails closed (exit code 2 and a line
"Error: unsupported: "), the harness gives `unsupported`, not `invalid`.
The reason is the sqll message. As the schema says, an `unsupported`
result has no samples and no stats. Reason: sqll does not ignore a setting
that it cannot do; `invalid` is for a crash, a timeout, no tree, or a
wrong tree. An `unsupported` result of sqll on an untemplated file is a
gap of sqll: status/S9.md lists it with an issue to the owning track.
Runs A and B have no such result.

### 3. The baseline rule for sqll

S4 (parser parity: sqll passes 100% of the dialect parse fixtures with an
exact tree match) and changes to the core paths can change the sqll parser
after the new baseline. Thus a sqll result can change on main. The rule of
`check --baseline` for the sqll results:

1. The check of sqlfluff, `sqlfluff[rs]`, and sqruff does not change. Each
   change of their stable data fails ("Report").
2. The check of sqll compares the same stable data: the tool version and
   settings, and the status and the unparsable count and bytes of each
   result. Each change fails, in each direction: a worse result fails, and
   a better result fails until the baseline has it. This applies to the
   smoke check of each pull request that is not documents only and to the
   full check on main.
3. The check message gives the direction ("worse" or "better") and says
   if the new sqll result is the sqlfluff result of the file. The order of
   the statuses, from better to worse: `ok`, `unparsable`, `no_reference`,
   `unsupported`, `invalid`, `error`. Of 2 `unparsable` results, the one
   with fewer bytes is better; with the same bytes, fewer segments.

Reasons: the check fails closed. The target of a sqll result is the
sqlfluff result of the same file (parser parity), so a sqll result that is
better than that of sqlfluff is also a difference that a reviewer must
see. If a better result passed, a later return to the old result would
also pass. The benchmark baseline has the same rule for sqll
(`harness/bench.md`, "Baseline").

Who updates `results/S9/baseline.json` (a path of the S9 track, the track
of S9: External corpus: large, complex SQL files from public sources, with
their source and license; the report shows parse success and speed for
each file, for each tool):

- That track records each complete baseline: one controlled full run of
  the 4 tools, with the method of the recorded baseline ("Profiles").
- A pull request of another track that changes a sqll result or the sqll
  version updates the sqll results in the same pull request. Examples: a
  pull request of S4 (parser parity: sqll passes 100% of the dialect parse
  fixtures with an exact tree match), of S10 (PL/pgSQL bodies: parse and
  lint SQL in PostgreSQL function bodies; a test set of PL/pgSQL functions
  parses with no unparsable segments), or a change to the core paths. The
  pull request has the label `cross-track`, and the owner of the corpus
  paths reviews it (PROCESS.md, "Tracks", rule 3). It uses the command of
  the code task, `python -m sqll_harness.corpus rebase --tool sqll`, on
  the full report of a `workflow_dispatch` CI run on its head. The command
  replaces only the sqll tool record and the sqll results. It fails on a
  change to another tool or to an input, and it calculates `totals`,
  `compared`, and `pairs` again. The pull request body lists each changed
  result: the file, the old and the new status and unparsable data, the
  direction, and the reason.
- A worse result that moves away from the sqlfluff result is a
  regression. The pull request fixes it, or it gives the reason and an
  issue to the owning track. The reviewer of the corpus paths accepts or
  refuses the reason.
- After such an update, the sqll times in the baseline come from another
  run than the times of the other 3 tools. The speed tables (decision 4)
  use only one controlled run of the 4 tools. Until the next complete
  baseline, status/S9.md says that the sqll times are from another run.
- If the full check on main fails after a merge (for example on a file
  that the smoke profile does not have), the track that merged the change
  updates the baseline under this rule, or reverts the change.

### 4. The speed tables

The goal is G3 (Speed: each command, start time included, is as fast as
reasonably possible and has a benchmark that measures sqlfluff, sqruff,
and sqll on the same input. sqll is faster than sqlfluff on each
benchmark, not slower than sqruff on any benchmark, and faster than sqruff
on the total of all benchmarks. A change that makes a benchmark slower
gives the reason. Correctness is more important than speed: do not make a
result wrong to make it fast).

Decision:

- `compared` stays: the files where each of sqlfluff, `sqlfluff[rs]`, and
  sqruff is `ok`, and only these 3 tools. Thus its numbers stay comparable
  with the recorded baseline (48 files, 5337294 bytes).
- New `pairs` in the report, and a new table: sqll to sqlfluff, and sqll
  to sqruff. For each pair, on the files where both tools are `ok`: the
  file count, the bytes, the sums of the median wall and CPU times of
  each tool, and the ratios sqll / other tool (wall and CPU). The schema
  check calculates each number again. The ratio of the sqll to sqruff
  pair shows the total part of the goal (less than 1 is faster).
- New list: each file where both tools of a pair are `ok`, and the median
  wall or CPU time of sqll is more than that of sqruff, or not less than
  that of sqlfluff. There is no noise margin: the list is a report, not a
  gate, and a margin can hide a file. Each file in the list has a reason
  or an issue to the owning track.
- On a file where the statuses are not the same, the speed is not
  compared (as for `compared`).
- The numbers come from one controlled run of the 4 tools (the new
  baseline).

Data. These numbers are not the speed result, because the sqll times
(run B, host, 2026-11-11) and the times of the recorded baseline (CI
image, 2026-10-28) come from 2 runs:

```
$ python3 -I pairs.py results/S9/baseline.json sqll-layer.json
sqll vs sqlfluff: 39 files, 7934578 bytes; wall sqll 15.176 s, sqlfluff 722.179 s, ratio 0.021; cpu ratio 0.021
  files where sqll is not faster than sqlfluff (wall or CPU): 0
sqll vs sqruff: 31 files, 5130517 bytes; wall sqll 12.561 s, sqruff 24.791 s, ratio 0.507; cpu ratio 0.524
  files where sqll is slower than sqruff (wall or CPU): 0
```

The largest wall time ratio of one file:

```
$ python3 -I maxratio.py results/S9/baseline.json sqll-layer.json
sqruff: 0.626 chinook-database/ChinookDatabase/DataSources/Chinook_MySql_AutoIncrementPKs.sql
sqlfluff: 0.036 sql-server-maintenance-solution/DatabaseIntegrityCheck.sql
```

### 5. CI

Decision: the corpus jobs that run the tools get the sqll binary of the
build job, as `bench-smoke` and `bench-full` do:

- `corpus-smoke`: `needs: [changes, image, build]`, and 2 new steps: the
  download of the artifact `sqll-build` to `out/sqll`, and `chmod +x
  out/sqll/bin/sqll`.
- `corpus-full`: `needs: [image, build]`, and the same 2 steps.
- `corpus-merge`: no change. It runs no tool.
- `harness/sqll_harness/verify.py`: the CI model gets the new needs of
  the 2 jobs and the 2 steps (artifact steps that the local `build-sqll`
  check replaces). Locally, `scripts/verify` runs `build-sqll` before the
  corpus checks, so the order does not change.

`.github/workflows/ci.yml` and `verify.py` are core paths (`tracks.yml`).
Thus this is a cross-track task: label `cross-track`, and the owner of the
core paths reviews it. It comes first, and it changes no result: sqll
stays in `LATER` until the task of the new baseline. Reason: the run
checks each tool before it starts (`bench_run.check_tools`), so with no
binary a run with sqll cannot start. Each task in "Tasks" keeps CI green.

### 6. The shard plan

Data. `shards.py` adds the wall time of all samples (warmup included) of
each shard. The 3 tools are those of the recorded baseline, and sqll is
run B:

```
$ uv run --frozen --project harness python -I shards.py results/S9/baseline.json sqll-layer.json
total: 3 tools 4225.4 s, sqll 130.8 s
4 shards: max 3 tools 1177.0 s; max sqll 36.4 s; max both 1213.4 s
6 shards: max 3 tools 849.3 s; max sqll 30.0 s; max both 879.3 s
8 shards: max 3 tools 625.7 s; max sqll 22.9 s; max both 648.6 s
```

Decision: `corpus/ci-shards.json` stays at 6 shards. sqll adds 30.0 s
(3.5%) to the longest shard: 879.3 s of tool runs. In CI run 40870016071
on main, the 6 shard jobs took 6 min 10 s to 15 min 2 s. The 849.3 s of
tool runs in the longest shard is not from that CI run: `shards.py`
calculates it from the samples of `results/S9/baseline.json`
(2026-10-28). With sqll, the estimate is less than 16 min,
under the job timeout of 60 min. The sqll times are from the host, not
from a CI runner. The task of the new baseline records the shard times of
its CI run.

### Tasks

Each task is one pull request, in this order. Each task is part of S9
(External corpus: large, complex SQL files from public sources, with their
source and license; the report shows parse success and speed for each
file, for each tool).

| Task | Goal of the task | Decisions |
|---|---|---|
| T9 | Plan and design record of the sqll results: the sqll settings layer, the Jinja files, the baseline rule for sqll, the speed tables, and the CI wiring | 1 to 6 (this section) |
| T10 | Cross-track: the corpus-smoke and corpus-full CI jobs and the local verify get the sqll binary of the build job; no result changes | 5 |
| T11 | The sqll corpus layer (`rust_parser_max_iterations = 1000000000000`), the status `unsupported` when sqll fails closed, and the "PRS: " message in the reason, with tests; sqll stays in `LATER`. Paths: only `harness/sqll_harness/corpus/**` and `harness/tests/test_s9_*.py` (paths of the S9 track); no change to the bench adapters | 1, 2 |
| T12 | The report and the check for sqll: `pairs`, the list of slower files, `compared` for the 3 tools, the direction in each sqll check message, and the `rebase --tool sqll` command, with tests; the recorded baseline stays valid | 3, 4 |
| T13 | The sqll results: remove sqll from `LATER`, one controlled full run of the 4 tools, the new `results/S9/baseline.json`, and the tables of status/S9.md (statuses, pairs, and the list of slower files with a reason or an issue for each) | 2, 3, 4, 6 |
| T14 | The exit of the stone for sqll: the proof of each exit criterion for the 4 tools, and the request for the approval | all |
