# S2 benchmark design

The S2 benchmarks (STONES.md S2; CONSTITUTION.md G3, G4.4), made by tasks
T2 to T8. "Measured" facts come from serial runs of the `scripts/setup`
tools on 2026-10-19 (4 CPUs); PR #12 has the commands and the output.

## Benchmarks

| Id | Command and input |
|---|---|
| `start/<dialect>` | `parse` of `SELECT 1;` with the dialect set |
| `<parse\|lint\|fix>/<dialect>/<small\|medium\|large>` | the command on the built input |

`<dialect>` is each of the 28 dialect folders of the pinned fixtures: 280
benchmarks for each tool. Reason: STONES.md asks for each command and 3
sizes for each dialect; start time does not change with the input size.
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
   file that a baseline tool parses with an unparsable segment or an error:
   the 139 sqruff dialect cases with `unparsable segment` in
   `known_failures/sqruff.txt` (sqlfluff and `sqlfluff[rs]` have none), and
   `ansi/bracket_in_comment` (see "Join"). The list does not change when a
   tool is added.

Measured: 2164 of 2306 files remain. Reason: one unparsable file makes the
full input invalid for that tool, and S3 needs valid sqruff timings. Correct
trees are the job of S1. Bias: the inputs are SQL that sqruff parses.

**Join.** Each file ends with a new line. If the last leaf of its tree is
not a terminator (`statement_terminator`, `function_script_terminator`, or
`slash`), the builder adds `;` and a new line. Measured:

- Plain concatenation of ansi files (16374 bytes): `sqlfluff parse` gives 1
  unparsable node of 13977 bytes. Joined ansi large: none.
- `;` after a `/` line is unparsable for all 3 tools (exasol, oracle).
- `select a /* ) */ from b;`: `sqlfluff[rs]` gives an unparsable `;`;
  sqlfluff and sqruff do not. The fixture has no `;`, so S1 passes.

**Fill.** Targets: small 1024, medium 4096, large 16384 bytes. The builder
goes through the files in sorted path order and adds each file that keeps
the input at or below the target. It goes through the list again until a
pass adds no file, so a dialect with few bytes repeats its files. Measured
sizes: small 985 to 1024, medium 4017 to 4096, large 16350 to 16384 bytes.
Large is below the 20000-byte default skip limit of sqlfluff and sqruff.
Larger inputs make a full run too long ("Time budget"). The definitions
store the sha256 of each input, so a change of the fixtures or of the
builder is visible.

## Settings

All tools get the same settings, in the sqlfluff config structure: the
dialect, `templater = raw`, `rules = all` (the sqlfluff default), and
`large_file_skip_byte_limit = 0` (other size limits off). The S1 adapters
translate them (`sqlfluff[rs]` adds `use_rust_parser` and `use_rust_rules`;
sqruff gets one `.sqruff` file). A setting that a tool does not support
gives the status `unsupported`. Reason: the same input and the same work for
each tool (G3.3).

Measured on 24575 bytes of ansi with the default limit (20000 bytes), all
with exit code 0: sqlfluff `parse` and `lint` give `[]`, and `fix` does not
change the file; each logs `... over the limit of 20000 bytes. Skipping
...`. sqruff `lint` gives `{}` with no message; sqruff `fix` logs `SKIP:
File is 24575 bytes ...`; sqruff `parse` gives a tree (no limit). With the
limit 0, `lint` gives 1176 (sqlfluff) and 1189 (sqruff) violations.

## Validity

A timing is valid only if the warmup run passes the check of its command,
and each timed run has the expected exit code:

- All: no crash, traceback, or panic; no size-limit skip message; no
  timeout (120 s, about 3 times the slowest valid run).
- `parse`: exit code 0, a tree with no unparsable segment.
- `lint`: exit code 0 or 1 (violations), a result for the input file.
- `fix`: exit code 0 or 1 (violations remain), no `CRITICAL` log, a fresh
  copy of the input for each run.

Else the status is `invalid`, `unsupported`, or `error`, with a reason. No
comparison or total uses its samples. Reason: a failed command is not a
valid timing, and the skips above have exit code 0.

Measured valid results (of 28 `start`, 84 for each command):

| Tool | start | parse | lint | fix |
|---|---|---|---|---|
| sqlfluff | 28 | 84 | 84 | 84 |
| `sqlfluff[rs]` | 28 | 84 | 84 | 84 |
| sqruff | 27 | 81 | 78 | 76 |

sqruff: no soql dialect (panic, exit code 101); `lint` and `fix` panic in
a rule but give exit code 1 and an output (mysql large, oracle medium and
large, tsql large); `fix` of ansi large did not stop in 902 s. These
failures do not change the inputs: the inputs must not depend on rule bugs.

## Time budget

Measured wall time of one run, median over the 28 dialects:

| Command | Size | sqlfluff | `sqlfluff[rs]` | sqruff |
|---|---|---|---|---|
| start | | 0.55 s | 0.52 s | 0.023 s |
| parse | large | 1.40 s | 0.83 s | 0.075 s |
| lint | large | 3.91 s | 3.68 s | 0.38 s |
| fix | large | 14.1 s | 14.4 s | 1.26 s |

The slowest valid run: `sqlfluff[rs] fix` of ansi large, 37.7 s. On 18431
bytes of ansi, sqlfluff took 1.87 s (`parse`), 6.92 s (`lint`), and 41.7 s
(`fix`). One run of all 840 benchmarks took 2506 s, of which 903 s was the
sqruff `fix` that did not stop: about 1720 s with the timeout. A full run (1
warmup and at least 3 timed runs) is thus about 2 hours. `start` and `small`
took 157 s.

## Measurement

A Python timer in the harness (`subprocess` and `os.wait4`) gives wall
time, user and system CPU time, and max RSS. Each benchmark has 1 warmup run
(the validity run), then timed runs with a minimum count and a time budget.
Statistics: median, min, max, and MAD of wall and CPU time. The report
records the timer overhead (measured: `/bin/true` 2.5 ms, median of 10).
Not hyperfine: it is one more binary to pin, it does not examine the output
of each run, and it gives no CPU time and RSS, which help to find the cause
of a slowdown (G3.6).

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
`harness/README.md`, next to the S1 report. Top level: `format`,
`sqlfluff_ref`, `profile` (`smoke` or `full`), `machine`, `timer` (overhead),
and `tools` (version, config, `--version` time). One entry for each
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
  `small`, validity run only). Its ids, input hashes, tool versions,
  settings, and statuses must be equal to the baseline.
- Push to main and `workflow_dispatch`: the full profile, sharded by
  dialect. The report goes to an artifact.
- `scripts/verify` runs the smoke profile as CI does; the drift test covers
  the new CI steps.
- `sqll-harness bench compare OLD NEW` flags a benchmark that is slower by
  more than a noise limit. It refuses 2 reports with different inputs,
  settings, or tool versions. PROCESS.md will require the reason in the pull
  request body when it flags a slowdown (G3.6).
- `scripts/bench` writes the full report for sqlfluff, `sqlfluff[rs]`, and
  sqruff in one command (the S2 exit, G4.4).
