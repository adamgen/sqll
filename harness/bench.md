# S2 benchmark design

The S2 benchmarks (STONES.md S2; CONSTITUTION.md G3, G4.4), tasks T2 to
T8. "Measured" facts come from serial runs of the `scripts/setup` tools on
2026-10-19 (4 CPUs); PR #12 has the commands and the output.

## Benchmarks

| Id | Command and input |
|---|---|
| `start/<dialect>` | `parse` of `SELECT 1;` with the dialect set |
| `<parse\|lint\|fix>/<dialect>/<small\|medium\|large>` | the command on the built input |

`<dialect>` is each of the 28 dialect folders of the pinned fixtures: 280
benchmarks for each tool. Reason: STONES.md asks for 3 sizes of each
command for each dialect; start time does not depend on the input size.
`start` includes the config and dialect load, because a user feels it
(G3.1). The report also has the `--version` time as process start only
(measured: sqlfluff 0.59 s, sqruff 0.012 s).

## Inputs

Source: `test/fixtures/dialects/<dialect>/*.sql` of the submodule (sqlfluff
4.4.0, MIT, THIRD_PARTY.md), read in place. The harness builds each input at
run time; the repository has no copy. External corpora are S9.

**Selection.** A file is used only if it has its `.yml` tree and:

1. The tree has no `unparsable` node (measured: no file has one).
2. It has no in-file config line (`-- sqlfluff`), because all tools get the
   same settings (measured: 1 file, `clickhouse/create_user.sql`).
3. The sqlfluff test gives it no config override (`ansi/expression_recursion`,
   `DEEP_PARSE_DEPTH_OVERRIDES`).
4. It is not in the frozen exclusion list. The list gives a reason for each
   file that a baseline tool parses with an unparsable segment: the 139
   sqruff dialect cases with `unparsable segment` in
   `known_failures/sqruff.txt` (sqlfluff and `sqlfluff[rs]` have none), and
   `ansi/bracket_in_comment` (see "Join"). The list does not change when a
   tool is added. An unsupported dialect (sqruff: soql) is not in the list;
   it gets the status `unsupported`.
5. The tree has a leaf. Measured: 3 files have none (`ansi/comments`,
   `ansi/empty_file`, `sqlite/block_comment_end_of_input`). The last is an
   unclosed comment: without this rule, 86% of sqlite large is comment.

Measured: 2161 of 2306 files remain. Reason: one unparsable file makes the
input invalid for that tool, and S3 needs valid sqruff timings. Bias: the
inputs are SQL that sqruff parses (soql: unsupported, kept).

**Join.** The builder adds a missing new line. If the last leaf of the tree
is not a terminator (`statement_terminator`, `function_script_terminator`,
or `slash`), it adds `;` and a new line. Measured:

- Plain concatenation of ansi files (16374 bytes): `sqlfluff parse` gives 1
  unparsable node of 13977 bytes. Joined ansi large: none.
- `;` after a `/` line is unparsable for all 3 tools (exasol, oracle).
- `select a /* ) */ from b;`: `sqlfluff[rs]` gives an unparsable `;`;
  sqlfluff and sqruff do not. The fixture has no `;`, so S1 passes.

**Fill.** Targets: small 1024, medium 4096, large 16384 bytes. In sorted
path order, the builder adds each file that keeps the input at or below the
target. It does this again until a pass adds no file, so a dialect with few
bytes repeats its files. Measured sizes: small 985 to 1024, medium 4017 to
4096, large 16350 to 16383 bytes.
Large is below the 20000-byte default skip limit of sqlfluff and sqruff;
larger inputs make a full run too long ("Time budget"). The definitions
store the sha256 of each input, so a change of the inputs is visible.

## Settings

All tools get the same settings, in the sqlfluff config structure: the
dialect, `templater = raw`, `rules = all` (the sqlfluff default), and
`large_file_skip_byte_limit = 0` (other size limits off). The S1 adapters
translate them (sqruff: one `.sqruff` file). A setting that a tool does not
support gives the status `unsupported`. Reason: the same input and the same
work for each tool (G3.3).

Measured on 24575 bytes of ansi with the default limit (20000 bytes), all
with exit code 0: sqlfluff `parse` and `lint` give `[]` and `fix` changes
nothing (log: `over the limit`); sqruff `lint` gives `{}` (no log), `fix`
logs `SKIP`, and `parse` has no limit. With the limit 0, `lint` gives 1176
(sqlfluff) and 1189 (sqruff) violations.

## Validity

A timing is valid only if the warmup run passes the check of its command,
and each timed run has the expected exit code:

- All: no crash, traceback, or panic; no size-limit skip message; no
  timeout (120 s; the slowest valid run took 34 s).
- `parse`: exit code 0, a tree with no unparsable segment.
- `lint` and `fix`: the `parse` check of the same tool on the same input
  passes, and the output has no parse error (`PRS`, `Unparsable section`).
- `lint`: exit code 0 or 1 (violations), a result for the input file.
- `fix`: exit code 0 or 1 (violations remain), no `CRITICAL` log, a fresh
  copy of the input for each run.

Else the status is `invalid`, `unsupported`, or `error`, with a reason. No
comparison or total uses its samples. Reason: a failed command is not a
valid timing, and the skips above have exit code 0. On an unparsable
input, sqruff `lint` gives exit code 0 and an empty result (measured); only
the `parse` check shows it.

Measured valid results (of 28 `start`, 84 for each command):

| Tool | start | parse | lint | fix |
|---|---|---|---|---|
| sqlfluff | 28 | 84 | 84 | 84 |
| `sqlfluff[rs]` | 28 | 84 | 84 | 84 |
| sqruff | 27 | 81 | 78 | 76 |

sqruff: no soql dialect (panic, exit code 101); a rule panics, but the exit
code is 1 and there is an output (`lint` and `fix`: mysql large, oracle
medium and large; `fix` only: tsql large); `fix` of ansi large did not stop
in 902 s. The inputs do not change for these rule bugs.

## Time budget

Wall time of one run, median of the 28 dialects (measured):

| Command | Size | sqlfluff | `sqlfluff[rs]` | sqruff |
|---|---|---|---|---|
| start | | 0.52 s | 0.48 s | 0.020 s |
| parse | large | 1.32 s | 0.81 s | 0.080 s |
| lint | large | 3.80 s | 3.41 s | 0.36 s |
| fix | large | 13.3 s | 13.3 s | 1.21 s |

The slowest valid run: `sqlfluff[rs] fix` of ansi large, 33.7 s. On 18431
bytes of ansi, sqlfluff took 1.87 s (`parse`), 6.92 s (`lint`), and 41.7 s
(`fix`). One serial run of all 840 benchmarks took 1626 s (with the
timeout); `start` and `small` took 141 s. A full run (1 warmup and at least
3 timed runs) is thus about 2 hours.

## Measurement

A Python timer in the harness (`subprocess` and `os.wait4`) gives wall
time, user and system CPU time, and max RSS. Each benchmark has 1 warmup run
(the validity run), then timed runs with a minimum count and a time budget.
Statistics: median, min, max, and MAD of wall and CPU time. The report
records the timer overhead (measured: `/bin/true` 2.5 ms, median of 10).
Not hyperfine: it is one more binary to pin, and it does not examine the
output of each run.

## Noise control

- The baseline is a controlled run: the CI image through docker on one
  machine, serial, no other load. The report has the machine record.
- The tools run in turn for each repeat, so drift has the same effect on
  each tool. Comparisons use ratios between tools of the same run.
- CI gates only on data that does not change between runs (ids, input
  hashes, tool versions, settings, statuses), not on timings of shared
  runners.

## Report

`out/bench.json`, with a format version. T3 documents the schema in
`harness/README.md`. Top level: `format`, `sqlfluff_ref`, `profile`
(`smoke`, `full`), `machine`, `timer` (overhead), and `tools` (version,
config, `--version` time). One entry for each
benchmark and tool: `id`, `tool`, `input` (bytes, sha256), `status`
(`valid`, `invalid`, `unsupported`, `error`), `reason`, `samples` (wall,
CPU, max RSS, exit code), and `stats`. The recorded baseline is
`results/s2/baseline.json`, as `results/s1/summary.json` is for S1.

## Add a tool

The definitions do not name a tool. A tool is a benchmark adapter (command
lines, settings translation, validity check) and a registry entry. sqll
(S3) needs no change to the definitions. A test-double tool in the unit
tests proves this.

## CI and slowdowns

- Pull request (not documents only): the smoke profile (`start` and
  `small`, validity run only). Its stable data (see "Noise control") must
  be equal to the baseline.
- Push to main and `workflow_dispatch`: the full profile, sharded by
  dialect. The report goes to an artifact.
- `scripts/verify` runs the smoke profile as CI does; the drift test covers
  the new CI steps.
- `sqll-harness bench compare OLD NEW` flags a benchmark that is slower by
  more than a noise limit. It refuses 2 reports with different inputs,
  settings, or tool versions. PROCESS.md will require the reason of a
  flagged slowdown in the pull request body (G3.6).
- `scripts/bench` writes the full report for the 3 tools in one command
  (the S2 exit, G4.4).
