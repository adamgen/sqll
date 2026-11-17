# S4 exit record

Stone: S4 (parser parity: sqll passes 100% of the dialect parse fixtures
with an exact tree match). In this record, "this stone" is that stone, and
"this track" is its track.

Task: T5 (the exit record gives the CI proof that sqll passes 100% of the
dialect parse fixtures with an exact tree match, and the orchestrator can
approve this stone) of S4 (parser parity: sqll passes 100% of the dialect
parse fixtures with an exact tree match).

Date: 2026-11-17. State: **Awaiting approval**. Design record:
[s4-parity.md](s4-parity.md). Status file:
[status/S4.md](../../status/S4.md).

## Result

The exit rule of STONES.md, S4: "sqll passes 100% of the dialect parse
fixtures with an exact tree match". Each item below is met. The exit
check `scripts/s4/exit.py` gives exit code 0 and writes
[results/S4/exit.json](../../results/S4/exit.json).

| Item | Rule | Result | Proof |
|---|---|---|---|
| a | 2306 of 2306 dialect cases in 28 dialects pass with `exact` and `no_unparsable` through the shared syntax tree and the sqll adapter (design record section 1) | Met | CI push run on main [44073788566](https://github.com/adamgen/sqll/actions/runs/44073788566), conclusion success, the job `dialect-oracle (sqlfluff)`, step 7 "Check the S4 parser parity"; `results/s1/summary.json` |
| b | `known_failures/sqll.txt` has 0 `dialects` lines | Met | 2593 lines, 0 `dialects` lines (command output below) |
| c | Each sqll pass also passes in the sqlfluff dialect oracle | Met | Step 6 of the same job: `sqll dialects: 2306 cases, 2306 pass, 2306 of them pass in the oracle` |
| d | The pinned sqlfluff commit is `0348222a3bcdb0226563f7349c5a39beb0641955` (tag `4.4.0`), and the submodule is clean | Met | Command output below |
| e | The CI gate fails closed | Met | The injected-gap proofs of T3 (CI fails on each gap of this stone) of S4 (parser parity: sqll passes 100% of the dialect parse fixtures with an exact tree match), [results/S4/gate.json](../../results/S4/gate.json) |
| f | The corpus information, as information only | Met | [results/S4/corpus-diff.json](../../results/S4/corpus-diff.json); it does not change the parity number |
| g | Speed: no parse-path change in this stone (section g) | Met | `git diff --name-only 0fb9cdb 6df6a6a`: 77 files, 0 files of the parse path |

Parity of this stone: **2306 of 2306 (100%)** dialect cases in 28
dialects, with an exact tree match. Gaps: 0.

## The tasks of this stone

| Task | Goal of the task | Pull request |
|---|---|---|
| T1 | The plan, the tree path, the gap rule, the CI gate design, the corpus rule, the speed rule, and the start data are recorded; this track owns its records, scripts, and harness tests | #85 |
| T2 | Each dialect fixture of the pinned sqlfluff is one harness case, and the check fails closed on each gap | #97 |
| T3 | CI fails on each gap of this stone | #98 |
| T4 | The parse status of sqll and sqlfluff on each corpus file is recorded, and each difference has a row | #103 |
| T5 | The exit record gives the CI proof that sqll passes 100% of the dialect parse fixtures with an exact tree match, and the orchestrator can approve this stone | This pull request |

The stone of each task is S4 (parser parity: sqll passes 100% of the
dialect parse fixtures with an exact tree match).

## a, c: the CI proof

The newest push run on main with conclusion success when this task
started. Data from the GitHub Actions API (`get_workflow_run`,
`list_workflow_jobs`, `get_job_logs`) on 2026-11-17. Record:
[results/S4/exit-ci.json](../../results/S4/exit-ci.json).

| Item | Value |
|---|---|
| Run | [44073788566](https://github.com/adamgen/sqll/actions/runs/44073788566) (workflow `CI`, run number 423, attempt 1) |
| Event and branch | `push` on `main` |
| Head | `6df6a6a1c284da67949829d3ec05fe9b83be7c7a` (`6df6a6a`, the merge of PR #103) |
| Conclusion | success; 87 jobs, 87 with conclusion success |
| Job | [`dialect-oracle (sqlfluff)`](https://github.com/adamgen/sqll/actions/runs/44073788566/job/134024330140) (job 134024330140), conclusion success |
| Step 6 | "Compare the dialect results with the sqlfluff tests", conclusion success |
| Step 7 | "Check the S4 parser parity", conclusion success |
| Other matrix entry | `dialect-oracle (sqlfluff-rs)` (job 134024329994), conclusion success; step 7 is skipped (`if: matrix.tool == 'sqlfluff'`) |

The log lines of step 6 (the timestamps removed):

```
oracle cases: 2306, harness cases: 2306
oracle: {'pass': 2306}
harness: {'pass': 2306}
only in oracle: 0 []
only in harness: 0 []
different status: 0
sqll dialects: 2306 cases, 2306 pass, 2306 of them pass in the oracle
```

The log lines of step 7 (`scripts/s4/parity`; the summary line, and the
start of its JSON output; the record has all 217 lines):

```
S4 parity: pass: sqll dialects 2306 of 2306 discovered cases pass in 28 dialects (exact 2306, no_unparsable 2306, 2306 pass in the oracle); gaps 0
{
 "format": 1,
 "check": "S4 parity (docs/decisions/s4-parity.md, section 3)",
 "status": "pass",
 "exit_code": 0,
 "commit": "6df6a6a1c284da67949829d3ec05fe9b83be7c7a",
 "pinned_commit": "0348222a3bcdb0226563f7349c5a39beb0641955",
 "report_sqlfluff_ref": "0348222a3bcdb0226563f7349c5a39beb0641955",
 ...
 "counts": {
  "discovered_cases": 2306,
  "discovered_dialects": 28,
  "report_cases": 2306,
  "report_dialects": 28,
  "passed": 2306,
  "failed": 0,
  "skipped": 0,
  "exact": 2306,
  "no_unparsable": 2306,
  "oracle_cases": 2306,
  "oracle_passed": 2306,
  "passed_in_oracle": 2306,
  "known_failures_lines": 2593,
  "known_failures_dialects_lines": 0,
  "gaps": 0
 },
```

The 5 items of design record section 3 have `"ok": true`, and each gap
list is empty. Each of the 28 dialects has each case passed (for example
`ansi` 208 of 208, `snowflake` 250 of 250, `mariadb` 223 of 223).

The tree path (design record section 1): the `dialects` suite of the
harness finds each case in the pinned fixtures, the sqll adapter runs
`sqll parse -f json -c --templater raw`, `sqll parse` calls
`sqll_syntax::parse` (the frozen parse interface of S3b (core: the shared
syntax tree, source map, frozen interfaces, and the sqll binary skeleton
(CLI, config, output) with the sqll adapters of the S1 harness and the S2
benchmarks; the S1 harness and the S2 benchmarks run sqll through its
adapters, the interfaces are documented, and after S3b, each change to
the core goes through the Core track)) and writes the record from the
`SyntaxTree`, and the harness compares the trees exactly. The recorded
summary `results/s1/summary.json` agrees: sqll `dialects` total 2306,
passed 2306, failed 0, error 0, skipped 0, `exact` 2306,
`no_unparsable` 2306, and the sqll adapter preflight `parse` is true.

The local run record of T2 (each dialect fixture of the pinned sqlfluff
is one harness case, and the check fails closed on each gap) of S4
(parser parity: sqll passes 100% of the dialect parse fixtures with an
exact tree match), [results/S4/parity.json](../../results/S4/parity.json)
(main `816b4d7`), has the same counts and exit code 0.

## b: the known failures

```
$ wc -l < known_failures/sqll.txt
2593
$ grep -c '^dialects/' known_failures/sqll.txt
0
```

`grep -c` gives exit code 1 when it finds no line. The exit check parses
the file with the known failures parser of the harness: 2593 lines, 0
`dialects` lines. The output of step 7 of the CI run also has
`"known_failures_dialects_lines": 0`. A dialect fixture never goes into
this list (design record section 2).

## d: the pinned sqlfluff and a clean submodule

On the head of this pull request:

```
$ git rev-parse HEAD:third_party/sqlfluff
0348222a3bcdb0226563f7349c5a39beb0641955
$ git -C third_party/sqlfluff rev-parse HEAD
0348222a3bcdb0226563f7349c5a39beb0641955
$ git -C third_party/sqlfluff describe --tags
4.4.0
$ scripts/check-submodule "for the S4 exit record"; echo "exit $?"
exit 0
$ git -C third_party/sqlfluff status --porcelain --ignored | wc -l
0
```

The `sqlfluff_ref` of `results/s1/summary.json` and the `pinned_commit`
and `report_sqlfluff_ref` of the CI output are the same commit. Only the
human owner can change the pinned version.

## e: the CI gate fails closed

T3 (CI fails on each gap of this stone) of S4 (parser parity: sqll passes
100% of the dialect parse fixtures with an exact tree match) added the
step "Check the S4 parser parity" to the job `dialect-oracle (sqlfluff)`
and the check `s4-parity` to `scripts/verify` (PR #98). The record
[results/S4/gate.json](../../results/S4/gate.json) has the injected-gap
proofs, with copies of real inputs:

| Run | Injected | Exit code | Gap |
|---|---|---|---|
| control | none (the real inputs) | 0 | none |
| known-failures-dialects-line | a `dialects` line in a copy of `known_failures/sqll.txt` (item 3) | 1 | `known_failures_dialects` |
| report-case-removed | the sqll case `dialects/ansi/select_a` removed from a copy of the report (item 1) | 1 | `missing` |
| no-oracle-output | no oracle output | 2 | none (input error) |

The step ran with conclusion success in the pull request run
[43698880672](https://github.com/adamgen/sqll/actions/runs/43698880672)
and in each push run on main after it, for example
[43815910761](https://github.com/adamgen/sqll/actions/runs/43815910761)
(head `49dd60c`) and the run of item a.

## f: the corpus information

T4 (the parse status of sqll and sqlfluff on each corpus file is
recorded, and each difference has a row) of S4 (parser parity: sqll
passes 100% of the dialect parse fixtures with an exact tree match).
Record: [results/S4/corpus-diff.json](../../results/S4/corpus-diff.json)
(merged report of 24 shards on the clean commit `c5896d3`; details in
[status/S4.md](../../status/S4.md), "Corpus information").

| Item | Value |
|---|---|
| Files | 164 (145 raw, 19 Jinja) |
| Same status and unparsable count | 146 |
| Rows | 18: settings 0, templater 18, parser gap 0 |
| sqlfluff | ok 57, unparsable 104, invalid 3 |
| sqll | ok 39, unparsable 104, invalid 21 |

Each of the 18 rows is a Jinja file that sqll fails closed on, because
sqll does not have the Jinja templater of S11 (Jinja templater: the last
stone; decision of the human owner (2026-11-07): do not write a Jinja
engine in sqll; decide with data how sqll supports Jinja; sqll passes
100% of the Jinja cases that the decision keeps, and S8 (code generation:
types of query parameters and result columns as JSON Schema; the JSON
Schema output is valid and correct for each parameter style, code made
from the schema by one existing tool compiles, and the harness shows one
parse for each file when one command lints and generates code) supports
Jinja if kept; each other Jinja case is in a known-failure list with its reason).
On each of the 145 raw files, sqll gives the status and the unparsable
count of sqlfluff. The corpus is S9 (external corpus: large, complex SQL
files from public sources, with their source and license; the report
shows parse success and speed for each file, for each tool).

This result is information only (design record section 4). It does not
change the parity number of this stone (2306 of 2306), and it does not
block the exit. The exit check fails item f only if the corpus record is
not a passing record, or a row has no class.

## g: speed, no parse-path change

G3 (speed: each command, start time included, is as fast as reasonably
possible and has a benchmark that measures sqlfluff, sqruff, and sqll on
the same input. sqll is faster than sqlfluff on each benchmark, not
slower than sqruff on any benchmark, and faster than sqruff on the total
of all benchmarks. A change that makes a benchmark slower gives the
reason. Correctness is more important than speed: do not make a result
wrong to make it fast).

The parse path (design record section 5) is each file that `sqll parse`
runs or that changes how it is built: `crates/**`, `Cargo.toml`,
`Cargo.lock`, `rust-toolchain.toml`, `.cargo/**`, `scripts/build-sqll`,
and the pinned grammar `third_party/sqlfluff` (the tables are made from
it). The start of this stone is main `0fb9cdb` (the merge of PR #84;
status/S4.md, "Start data").

```
$ git merge-base --is-ancestor 0fb9cdb 6df6a6a; echo "exit $?"
exit 0
$ git diff --name-only 0fb9cdb 6df6a6a | wc -l
77
$ git diff --name-only 0fb9cdb 6df6a6a -- crates Cargo.toml Cargo.lock \
    rust-toolchain.toml scripts/build-sqll third_party/sqlfluff .cargo | wc -l
0
```

No task of this stone changed the parse path, so no task has a speed-check
record, and the speed of sqll at the exit is the speed at the start. The
exit check also lists the parse-path files from `0fb9cdb` to the head of
this pull request: none. This pull request changes only the files of this
track: `scripts/s4/exit.py`, `harness/tests/test_s4_exit.py`,
`results/S4/exit-ci.json`, `results/S4/exit.json`, this record, and
`status/S4.md`.

## The exit check

```
uv run --frozen --project harness python scripts/s4/exit.py [--check]
```

It reads `results/S4/exit-ci.json`, `results/S4/parity.json`,
`results/S4/gate.json`, `results/S4/corpus-diff.json`,
`results/s1/summary.json`, and `known_failures/sqll.txt`, and runs the git
commands of items d and g. It writes
[results/S4/exit.json](../../results/S4/exit.json): each item, each
check of the item, and the values with the command output. Exit code 0 if
each item is met, 1 if an item is not met, and 2 if an input is missing or
not valid (then it writes no record). A shallow clone has no history, so
the git commands need the full history of main.

The output on the head of this pull request:

```
S4 exit: pass: items met 7 of 7; failed items: none; state: Awaiting approval; wrote results/S4/exit.json
```

`harness/tests/test_s4_exit.py` proves each exit code: exit code 0 on the
real inputs; exit code 1 for each failed check of each item (a changed CI
record, recorded summary, parity record, gate record, corpus record, known
failures list, and git facts); exit code 2 for each missing input, each
input that is not valid JSON, a known failures list that is not valid, a
missing key, and a missing git commit. A test also runs the real git
commands in a new git repository.

## Approval

This record asks for the approval of this stone. The orchestrator approves
it by the standing delegation (CONSTITUTION.md, section 5) only after an
independent check finds no blocking gap. It records the approval with its
data and date in `status/S4.md` and STATUS.md.
