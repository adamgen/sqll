# S2 benchmark design

The S2 benchmarks (STONES.md S2; CONSTITUTION.md G3, G4.4), tasks T2 to
T8. "Measured" facts: runs of the `scripts/setup` tools on 2026-10-19 (4
CPUs); PR #12 has the commands and the output.

## Benchmarks

| Id | Command and input |
|---|---|
| `start/<dialect>` | `parse` of `SELECT 1;` with the dialect set |
| `<parse\|lint\|fix>/<dialect>/<small\|medium\|large>` | the command on the built input |

`<dialect>`: each of the 28 dialect folders of the pinned fixtures (280
benchmarks for each tool). Reason: STONES.md asks for 3 sizes of each
command for each dialect; start time does not depend on the input size.
`start` includes the config and dialect load, because a user feels it
(G3.1).

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
4. It is not in the frozen list `sqll_harness/bench/exclusions.txt` (a
   reason for each file): the 139 dialect cases with `unparsable segment` in
   `known_failures/sqruff.txt` (sqlfluff and `sqlfluff[rs]` have none), and
   `ansi/bracket_in_comment` ("Join"). A new tool does not change the list.
5. The tree has a leaf. Measured: 3 files have none (`ansi/comments`,
   `ansi/empty_file`, `sqlite/block_comment_end_of_input`). The last is an
   unclosed comment: without this rule, 86% of sqlite large is comment.

Measured: 2161 of 2306 files remain. Reason: one unparsable file makes the
input invalid for a tool; S3 needs valid sqruff timings. Bias: the inputs
are SQL that sqruff parses (soql: unsupported, kept).

**Join.** The builder adds a missing new line. If the last tree leaf is not
a terminator (`statement_terminator`, `function_script_terminator`, or
`slash`), it adds `;` and a new line. Measured:

- Plain concatenation of ansi files (16374 bytes): `sqlfluff parse` gives 1
  unparsable node of 13977 bytes. Joined ansi large: none.
- `;` after a `/` line is unparsable for all 3 tools (exasol, oracle).
- `ansi/bracket_in_comment` with `;` added (`)` on its own line in a block
  comment): only `sqlfluff[rs]` gives an unparsable `;`. On one line, no
  tool does. The fixture has no `;`, so S1 passes.

**Fill.** Targets: small 1024, medium 4096, large 16384 bytes. In sorted
path order, the builder adds each file that keeps the input at or below the
target. It does this again until a pass adds no file. Thus files repeat in
34 of 84 inputs: each input whose target is more than the bytes of all used
files of its dialect, and some others. Measured sizes: small 985 to 1024,
medium 4017 to 4096, large 16350 to 16383 bytes.
Large is below the 20000-byte default skip limit of sqlfluff and sqruff;
larger inputs make a full run too long ("Time budget"). The definitions
(`definitions.json`, same folder) store for each input its bytes, lines,
and sha256, and the sqlfluff reference (G1): the rule codes of `lint`,
and if `fix` changes the file. `sqll-harness bench reference` makes it with
the sqlfluff adapter; each run must pass the checks of "Validity".

## Settings

All tools get the same settings, in the sqlfluff config structure: the
dialect, `templater = raw`, `rules = all` (the sqlfluff default), and
`large_file_skip_byte_limit = 0` and `large_file_skip_char_limit = 0` (no
size limit). The S1 adapters translate them (`sqlfluff[rs]`: also
`use_rust_parser` and `use_rust_rules`; sqruff: one `.sqruff` file). An
unsupported setting gives the status `unsupported`. Reason: the same input
and work for each tool (G3.3).

Measured on 24575 bytes of ansi with the default limit (20000 bytes), all
with exit code 0: sqlfluff `parse` and `lint` give `[]`, `fix` changes
nothing (log: `over the limit`); sqruff `lint` gives `{}` (no log), `fix`
logs `SKIP`, `parse` has no limit.

## Validity

A timing is valid only if the warmup run passes the check of its command,
and each timed run has the exit code of the warmup run:

- All: no crash, traceback, or panic; no size-limit skip message; no
  unknown-rule message; no `CRITICAL` log; no timeout (120 s; see "Time
  budget"). `sqlfluff[rs]`: no message that it used the Python parser.
- `parse`: exit code 0, a tree with no unparsable segment, and the text of
  its leaves is the input (measured: true for each tool on each of the 84
  inputs that it parses with exit code 0).
- `lint` and `fix`: the `parse` check of the same tool on the same input
  passes; the output has no parse error (`PRS`, `Unparsable section`). If
  no run checked the `parse` (or for `fix`, the `lint`) of the input, the
  check does one run of it, not timed.
- `lint`: exit code 0 or 1, a result for the input file, and the set of
  rule codes of the sqlfluff reference.
- `fix`: exit code 0 or 1, no `CRITICAL` log, a fresh copy of the input for
  each run. The `lint` check passes. The file changes if, and only if, it
  changes in the reference.

Else the status is `invalid`, `unsupported`, or `error`, with a reason. No
comparison or total uses its samples. Reasons (measured): the skips above
have exit code 0. sqruff `lint` has `--parsing-errors` (as in S1): without
it, an unparsable input gives exit code 0 and an empty result. A setting
that a tool ignores gives less work. On ansi large, sqlfluff `lint` gives
661 violations in 5.4 s; with `rules = LT01`, 85 in 1.9 s; with an unknown
rule, only a warning, exit code 0, no violations. Limit: the `parse`,
`lint`, and `fix` checks do not prove the same tree, violations, or fixes;
S1 parity measures that.

Measured valid results (of 28 `start` and 84 for each command): sqlfluff
and `sqlfluff[rs]` all; sqruff 27 `start`, 81 `parse`, 55 `lint`, 53
`fix`. Causes for sqruff: soql is `unsupported` (`unsupported: dialect
soql`; the adapter refuses the dialect, thus sqruff does not run); rule
panics, exit code 1 (mysql large, oracle medium and large, `fix` of tsql
large); `fix` of ansi large did not stop in 120 s (timeout); 23 inputs
have rule codes that are not those of sqlfluff (S1 rule differences). The
inputs stay the same. G3: an invalid or missing result of the tool under
test fails its comparison; skip a pair only if the other tool is invalid.
A total uses the same pairs for both tools.

## Time budget

Wall time of one run, median of the 28 dialects (measured):

| Command | Size | sqlfluff | `sqlfluff[rs]` | sqruff |
|---|---|---|---|---|
| start | | 0.52 s | 0.48 s | 0.020 s |
| parse | large | 1.32 s | 0.81 s | 0.080 s |
| lint | large | 3.80 s | 3.41 s | 0.36 s |
| fix | large | 13.3 s | 13.3 s | 1.21 s |

Slowest valid run: `sqlfluff[rs] fix` of ansi large, 33.7 s. On 18431
bytes of ansi, sqlfluff took 1.87 s (`parse`), 6.92 s (`lint`), and 41.7 s
(`fix`). One serial run of all 840 benchmarks took 1626 s (with the
timeout); `start` and `small` took 141 s. Thus a full run (1 warmup, at
least 3 timed runs) takes about 2 hours, and the time budget of
"Measurement" adds less than 28 min.

## Measurement

A Python timer in the harness (`sqll_harness/bench/timer.py`:
`subprocess`, `os.wait4`) gives wall time, user and system CPU time, and
max RSS. A prepare step (for `fix`: a fresh copy of the input) runs before
each run, outside the timed part. Each benchmark has 1 warmup run (the
validity run), then timed runs:

- `full`: at least 3 and at most 20 timed runs. Between these limits, it
  does more runs while their wall time is less than 2 s in total. Thus the
  budget adds less than 2 s to each of the 840 series (a benchmark and
  a tool).
- `smoke`: 1 timed run.

Statistics of the timed runs (not the warmup run): n, median, min, max, and
MAD of wall and CPU (user and system) time. The report records the timer
overhead: `/bin/true`, 10 runs (measured: median 1.4 ms). Not hyperfine:
one more binary to pin, and it does not examine the output of each run.

## Noise control

- The baseline is a controlled run: the CI image in docker on one
  machine, serial, no other load.
- The tools run in turn for each repeat, so drift has the same effect on
  each tool. Comparisons use ratios between tools of the same run.
- CI gates only on data that does not change between runs (ids, input
  hashes, tool versions, settings, statuses), not on timings of shared
  runners.

## Report

`out/bench.json`; `harness/README.md` has the schema. Top level: `kind`,
`format`, `sqlfluff_ref`, `harness` (commit), `profile`, `policy`,
`machine`, `timer`, `scope`, `tools` (version, settings), `inputs` (bytes,
lines, sha256), `results`, `totals`, `pairs`, `parts` (the shards of a
merged report). One result for each benchmark and tool: `id`, `command`,
`dialect`, `size`, `input`, `tool`, `status`, `reason`, `runs`, `work`
(`lint`: violation count and rule codes; `fix`: if the file changed, and
its sha256), `samples` (wall, CPU, max RSS, exit code), `stats` (only if
`valid`), and `ratio` (to `sqlfluff` on the same benchmark; only if both
are `valid`).

## Baseline

`results/s2/baseline.json` is the report of one controlled run of
`scripts/bench --profile full`, as recorded (the machine record and the
harness commit are in it). CI compares the stable data of each smoke run
and each full run with it, fail closed (`sqll-harness bench check
--baseline`; for a full run also `--full`: each result of the baseline
must be in the report): the sqlfluff ref, the tool versions and settings,
the input records, and the status of each result (and the `work` of a
result that is `valid` in both). Not the timings, reasons, or machine. A
new tool (sqll in S3) or tool version needs a new baseline.

Controlled run (2026-10-20): the CI image, built from `ci/Dockerfile` on
the local machine (4 CPUs, no other load), one container, serial. The
egress proxy of that machine blocks `deb.debian.org` and the registry
blobs, so the build used `PYTHON_IMAGE` `python:3.13.16-trixie` (the same
Python, with git and gcc, thus no apt step) and the proxy CA. The tools
have the pinned versions (`sqll-harness tools` passes).

## Add a tool

The definitions have no tool entry; they store the reference data of the
pinned sqlfluff. A tool is a benchmark adapter (`BenchAdapter`: config
file, command lines, env, and the readers of its tree and lint output) and
a registry entry (`sqll_harness/bench/registry.py`). The validity checks
are the same for each tool. sqll (S3) needs no change to the definitions.
Proof: through the registry, a test-double tool runs all 280 benchmarks,
valid, and the definitions do not change.

## CI and slowdowns

- Pull request (not documents only): the smoke profile (`start` and
  `small`, the validity run and 1 timed run; a valid result needs stats).
  Its stable data ("Noise control") must be equal to the baseline
  ("Baseline").
- Push to main and `workflow_dispatch`: the full profile, sharded by
  dialect. The merged report goes to an artifact. Its stable data must be
  equal to the baseline, with each result of it.
- `scripts/verify` runs the smoke profile; the drift test covers the new
  CI steps. `scripts/verify --full-bench` also runs the full profile (one
  report, no shards) and its baseline check.
- CI does not run `sqll-harness bench compare` ("Slowdowns").
- `scripts/bench` writes the full report for the 3 tools in one command
  (the S2 exit). G4.4 (all tests and benchmarks in one command):
  `scripts/verify --full-bench`.

## Slowdowns

`sqll-harness bench compare BASE NEW` (G3.6; output and exit codes in
`harness/README.md`, "Benchmark compare") compares each benchmark and tool
that both reports have. For the median wall time and the median CPU time,
the ratio is NEW / BASE. A metric is slower if its ratio is more than 1 +
the noise limit. The limit is the largest of: 25% for wall time and 10% for
CPU time; 3 times the sum of the relative MADs (MAD / median) of the 2
results; and 5 ms divided by the BASE median. A benchmark is slower if a
metric is slower. PROCESS.md (rule 8): the pull request body must give the
reason.

Measured (2026-10-20, full profile, postgres and tsql, 3 runs of the same
commit, serial, compared in 3 pairs): the wall time ratios were 0.82 to
1.22, the CPU time ratios 0.90 to 1.09. With the limit, no benchmark is
slower. With 10% for both, 1 to 3 of 57 were slower in each pair. The
smoke profile (1 timed run) is not usable: 2 smoke runs in sequence gave
wall time ratios 0.46 to 2.18, and 23 of 336 benchmarks slower. Thus
compare 2 `full` reports from the same machine ("Noise control"); compare
gives a warning for a report with 1 timed run.

- It refuses (exit code 2) reports with a different input (`sha256`) or
  different settings of a compared tool. A different tool version gives
  only a warning: a new version of the tool under test is what it
  measures.
- A change from `valid` to another status is a failure (exit code 1).
  Other status changes are listed.
- It also compares the tools of NEW (G3.4, G3.5). The totals use only
  the benchmarks that are valid for all compared tools.
