# S4 decision: the parity design

Status: written in T1 (start the S4 track: the status file, this design
record, and the S4 paths in `tracks.yml`) of S4 (parser parity: sqll
passes 100% of the dialect parse fixtures with an exact tree match), on
2026-11-11. This stone needs S3b (core: the shared syntax tree, source
map, frozen interfaces, and the sqll binary skeleton), and the
orchestrator approved S3b (core: the shared syntax tree, source map,
frozen interfaces, and the sqll binary skeleton) on 2026-11-11
(STATUS.md). Plan, tasks, and start data:
[status/S4.md](../../status/S4.md). In this record, "this stone" and
"this track" are S4 (parser parity: sqll passes 100% of the dialect
parse fixtures with an exact tree match).

## The start

At the start, sqll passes 2306 of 2306 dialect cases with an exact tree
match ([status/S4.md](../../status/S4.md), "Start data"). The sqll parser
is a port of the sqlfluff Rust parser, with tables made from the sqlfluff
grammar ([s3-base.md](s3-base.md)). Thus this stone starts with no gap.
The work is to make the result a gate that fails closed, to get data
from other SQL, and to prove the exit. A gap that a later change makes is
closed by the gap rule (section 2).

## 1. The tree path

"Through the S3b (core: the shared syntax tree, source map, frozen
interfaces, and the sqll binary skeleton) tree and adapters" means this
path. Parity uses no other path.

1. The `dialects` suite of the harness
   (`harness/sqll_harness/suites/dialects.py`) finds each SQL file in
   `test/fixtures/dialects/<dialect>/` of the pinned sqlfluff that has a
   `.yml` file with the same name (or a `_nc.yml` file). Each pair is one
   case.
2. The sqll adapter (`harness/sqll_harness/adapters/sqll.py`) runs the
   binary: `sqll parse -f json -c --templater raw --dialect D
   --ignore-local-config PATH`. It adds a `--config` file only for the
   depth of the sqlfluff test (`ansi/expression_recursion.sql`:
   `max_parse_depth` 2000).
3. `sqll parse` (`crates/sqll_cli/src/parse/steps.rs`) makes the file
   with the raw templater and calls `sqll_syntax::parse`, the frozen parse
   interface ([parse.md](../interfaces/parse.md)). `parse` lexes the text,
   parses the tokens with `sqll_parser` and the tables of `sqll_dialects`,
   and converts the parser tree to the `SyntaxTree`.
4. The JSON writer (`crates/sqll_cli/src/parse/output.rs`) writes the
   record of `sqlfluff parse -f json` from the `SyntaxTree`. This is the
   design of C9 (frozen parse interface and `sqll parse` output from the
   `SyntaxTree`) of S3b (core: the shared syntax tree, source map, frozen
   interfaces, and the sqll binary skeleton).
5. The harness changes the record and the YAML fixture with the
   `process_struct` function of the sqlfluff test, and compares the two
   trees exactly (`harness/sqll_harness/compare.py`). A case passes only
   if the tree is an exact match, and the output has no unparsable
   segment, no error, and exit code 0.
6. `scripts/sqlfluff-dialect-oracle --passes-of sqll` runs the sqlfluff
   dialect tests of the pinned sqlfluff on each case. Each case that sqll
   passes must also pass there.

The parity number of this stone is the result of step 5 for the tool
`sqll` in the suite `dialects`. A Rust test in `crates/sqll_parser/tests/`
or `crates/sqll_dialects/tests/` can help to find a gap, but it does not
count for parity.

## 2. The gap rule

A gap is a dialect case that sqll does not pass in step 5, or that the
oracle does not pass in step 6.

- A dialect fixture never goes into `known_failures/sqll.txt`. The
  `dialects` part of that list stays empty.
- No fixture changes, and the pinned sqlfluff version does not change.
  This is G4 (verification first: each behavior has an automated test
  from external sources; external test data does not change to make a
  test pass; each known failure is in a list). Only the human owner can
  change the pinned version.
- This track closes a gap in its own paths: `crates/sqll_parser/src/**`
  and `crates/sqll_dialects/src/**`, with tests in the `tests/**` folders
  of the 2 packages.
- If the cause is in a path of another track, this track opens an issue
  for that track and does not change the path. The core track (the track
  that does S3b and owns the shared core; S3b: the shared syntax tree,
  source map, frozen interfaces, and the sqll binary skeleton) owns the
  lexer (`sqll_lexer`), the tree and the parse interface (`sqll_tree`,
  `sqll_syntax`), the table generator and the tables
  (`crates/sqll_dialects/build.rs`, `build/`, `generated.json`), each
  `Cargo.toml`, `crates/ported.json`, the harness, and
  `known_failures/`. The JSON writer and `sqll parse` are in
  `crates/sqll_cli/src/`, a path of the S7-sqll track (the track that
  makes sqll pass the converted cases of S7: CLI and config parity, the
  sqlfluff CLI, config, and Python rule tests as black-box cases). The
  raw templater is in `crates/sqll_templater/src/`, a path of the track
  of S6 (templater parity: 100% of the placeholder and Python
  format-string templater fixtures that do not need a Python runtime). A
  pull request that must change such a path has the label `cross-track`,
  and the owner track reviews it (PROCESS.md, "Tracks").

## 3. The CI gate

T3 (the CI gate: CI fails on each gap of this stone) of S4 (parser
parity: sqll passes 100% of the dialect parse fixtures with an exact tree
match) adds one step to CI and to `scripts/verify`. The step runs
`scripts/s4/parity`, the check of T2 (fixture inventory and parity check:
each dialect fixture of the pinned sqlfluff is one harness case, and the
check fails closed on each gap) of S4 (parser parity: sqll passes 100%
of the dialect parse fixtures with an exact tree match). The CI workflow
and `scripts/verify` are paths of the core track (the track that does
S3b and owns the shared core; S3b: the shared syntax tree, source map,
frozen interfaces, and the sqll binary skeleton). Thus that task is
cross-track, and the core track reviews it. It also adds `scripts/s4/`
to the ruff commands of the lint job.

The step runs in the job `dialect-oracle (sqlfluff)`, after the oracle.
That job has the merged report (`out/report.json`) and the oracle output.
The check reads the report, the oracle output, the fixtures of the
pinned sqlfluff, and `known_failures/sqll.txt`. Exit code 1 (fail) if:

1. The `dialects` case ids of sqll in the report are not the cases that
   step 1 of section 1 finds in the pinned fixtures: a case is missing,
   extra, or skipped. At the start, this is 2306 cases in 28 dialects.
2. A `dialects` case of sqll does not pass, or its check `exact` or
   `no_unparsable` is false.
3. `known_failures/sqll.txt` has a line of a `dialects` case.
4. The oracle output does not have each case, or a case that sqll passes
   does not pass in the oracle.
5. The `sqlfluff_ref` of the report is not the pinned commit
   (`HEAD:third_party/sqlfluff`), or a file in the submodule has a change
   (`scripts/check-submodule`).

Exit code 2 if an input is missing or not valid. The check never passes
with no data.

The present gates already fail on a new failure (the known failures
check of each test job) and on a changed summary (the check of
`results/s1/summary.json`). Item 3 is new: without it, a pull request
can add a `dialects` line to `known_failures/sqll.txt`, record a new
summary, and pass CI. Items 1 and 2 make 100% a fixed rule, not only a
recorded number.

## 4. The external corpus

T4 (corpus information: the parse status of sqll and sqlfluff on each
corpus file is recorded) of S4 (parser parity: sqll passes 100% of the
dialect parse fixtures with an exact tree match) runs sqll on the corpus
of S9 (external corpus: large, complex SQL files from public sources,
with their source and license; the report shows parse success and speed
for each file, for each tool):
`python -m sqll_harness.corpus run --tool sqll --tool sqlfluff`.

- The result is information only. It does not change the parity number
  of this stone, and it does not block its exit.
- The result goes to `results/S4/`. This track does not change a file of
  the corpus track: `corpus/**`, `results/S9/**`,
  `harness/sqll_harness/corpus/**`, or the corpus baseline. The sqll
  results of the corpus stone are the work of its own track
  (`status/S9.md`, row LATER).
- Each file where sqll and sqlfluff give a different status or a
  different unparsable count gets a row with the difference. If this
  track changes the parser for such a row, the change follows sections 2
  and 5.

## 5. The speed rule for each task

G3 (speed: each command is as fast as reasonably possible; sqll is
faster than sqlfluff on each benchmark, not slower than sqruff on any
benchmark, and faster than sqruff on the total; a change that makes a
benchmark slower gives the reason) applies to each task of this stone.

- The parse path is each file that `sqll parse` runs: the packages of
  this track, and the other packages that it links.
- A task that changes the parse path runs `scripts/speed-check run
  --task S4-T<n>` (it takes the machine lock; PROCESS.md, "Tracks",
  rule 7). The pull request gives the HEAD / BASE ratio of the start and
  parse benchmarks, and the reason for each benchmark that the check
  finds slower (PROCESS.md, rule 8; `harness/bench.md`, "Slowdowns").
- `scripts/speed-check` writes the record to `results/S3b/speed/`, a path
  of the core track (the track that does S3b and owns the shared core;
  S3b: the shared syntax tree, source map, frozen interfaces, and the
  sqll binary skeleton). Thus such a pull request has the label
  `cross-track`.
- A task that does not change the parse path gives `git diff
  --name-only` of its pull request as the proof, and needs no speed data.
- Correctness is more important than speed. Do not make a tree wrong to
  make it fast.
