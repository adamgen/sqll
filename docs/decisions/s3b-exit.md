# S3b exit record

Status: S3b awaiting approval. The orchestrator approves S3b (Core: the
shared syntax tree, source map, frozen interfaces, and the sqll binary
skeleton) by the standing delegation (CONSTITUTION.md, section 5) after an
independent check. A goal in parentheses is a short form of the goal in
AGENTS.md, "Names". Each task (C1 to C17) is a task of S3b.

## Data

Each number in this record is a value of
[`results/S3b/exit.json`](../../results/S3b/exit.json), from
`scripts/s3b/exit.py` (C17: S3b exit: proof, exit record, and the
request for approval). The inputs: the CI record
`results/S3b/exit-ci.json`, the speed check
`results/S3b/speed/C17.json`, and frozen copies
(`results/S3b/exit-inputs/`) of `results/s1/summary.json`,
`docs/interfaces/README.md`, and `tracks.yml`. `--check` makes the record
and the ownership probe again, on the frozen and the live `tracks.yml`
(CI job build; `harness/tests/test_s3b_exit.py`).

The exit head is main `a77e821`, the merge of the last task before this
task. This task changes no file under `crates/`, `Cargo.toml`, or
`Cargo.lock`, so its sqll is that of the exit head.

## Exit 1: the test harness and the benchmarks run sqll

The harness of S1 (binary test harness: run the sqlfluff test fixtures
through a binary) and the benchmarks of S2 (benchmarks: a benchmark for
each command and each dialect) run sqll through its adapters.
CI run 42986804942 (push on main, head `a77e821`): conclusion success, 77
jobs. Lines of the job logs:

```text
report:
sqll rules: 2527 cases, 38 pass, 38 of them pass in the oracle
sqll autofix: 61 cases, 0 pass, 0 of them pass in the oracle
sqll templater: 43 cases, 0 pass, 0 of them pass in the oracle
results/s1/summary.json is equal to the summary.
dialect-oracle (sqlfluff):
sqll dialects: 2306 cases, 2306 pass, 2306 of them pass in the oracle
bench-merge (the full benchmark profile of all tools, sqll included):
out/bench.json: no schema error; complete for its scope.
The stable data of 1120 results is that of the baseline results/s2/baseline.json.
The report has the profile and each result of the baseline.
build:
base native tests: PASS: 162 base tests pass in the base; sqll: 362 tests, 358 passed, 0 failed, 4 ignored; 0 problems
tree guard: 84 of 84 inputs, 2 runs each: same output as the record
```

The CI record also has the PASS line of each oracle check of the build
job.

The summary of sqll in the test harness: dialects 2306 of 2306 exact
(2306 with no unparsable segment), rules 38 of 2527, autofix 0 of 61,
templater 0 of 43; parity 2344 of 4937; 0 new failures and 0 unexpected
passes. The adapters:
[harness/sqll.md](../../harness/sqll.md), "Adapter" and "Benchmark
adapter" (C14: harness adapters).

## Exit 2: the interfaces are documented

The index [docs/interfaces/README.md](../interfaces/README.md) has 8 rows.
Each has its document and its test in `crates/sqll_interfaces/tests/`. The
4 frozen interfaces of STONES.md map to the rows:

| STONES interface | Rows (task) |
|---|---|
| lexer to parser to tree | Segment kinds (C6), Syntax tree (C7), Parse (C9), Typed view (C10) |
| tree to rules to fixes | Config (C11), Rules and fixes (C12) |
| templater to source map | Source map (C8) |
| tree to schema for code generation | Tree to schema (C15) |

Config is in "tree to rules to fixes": a rule reads its settings from
it. `harness/tests/test_s3b_interfaces.py` checks the index.

## Exit 3: each change to the core goes through the Core track

`tracks.yml` (C16: package ownership of the later tracks and the
interface index) gives each later track only `src/**` and `tests/**` of
its packages. Core keeps each interface, each `Cargo.toml` and `build.rs`,
`Cargo.lock`, and `crates/sqll_interfaces` (tests:
`harness/tests/test_ownership.py`).

The probe: in a new git repository, a pull request of each of the 7 later
tracks (the table below) changes one of 6 Core paths
(`docs/interfaces/parse.md`, `crates/sqll_interfaces/tests/parse.rs`,
`crates/sqll_syntax/src/lib.rs`,
`crates/sqll_parser/Cargo.toml`, `crates/sqll_dialects/build.rs`,
`Cargo.lock`), and `ci/ownership.py` runs on the merge commit. Of the 42
runs, 42 fail without the label and 42 pass with the label
`cross-track`. The 7 control runs (the status file of the track) pass.

| Later track | Goal |
|---|---|
| S4 | Parser parity: each dialect parse fixture with an exact tree match |
| S5 | Rule parity: each rule fixture, lint and fix |
| S6 | Templater parity: the placeholder and Python format-string templaters |
| S7-sqll | CLI and config parity, the sqll part: the converted black-box cases |
| S8 | Code generation: types of query parameters and result columns as JSON Schema |
| S10 | PL/pgSQL bodies: parse and lint SQL in PostgreSQL function bodies |
| S11 | Jinja templater: the last stone; decide with data how sqll supports Jinja |

3 lines of the output of track S4 (the table above), no label:

```text
Branch claude/s4: track S4.
- docs/interfaces/parse.md: owned by core (another track)
Result: fail.
```

## Speed: keep the speed of the base

G3 (speed: sqll is faster than sqlfluff on each benchmark and not slower
than sqruff on any benchmark). The speed check
`results/S3b/speed/C17.json` (`scripts/speed-check`, with the machine
lock): base `319b7d6`, the exit of S3 (choose the base and make
the sqll binary from it), and head `a77e821`. The base of C5 (speed
check tool for each Core change) has the same sqll source. It measures
all S3b changes together.

- 112 benchmarks: 0 slower than the noise limit, 0 failures.
- HEAD / BASE of the wall time: start 1.096, parse/small 1.068,
  parse/medium 1.031, parse/large 1.043, total 1.048.
- HEAD is faster than sqlfluff on 112 of 112 (total ratio 0.023) and faster
  than sqruff on 108 of 108 pairs (total ratio 0.552).

No benchmark is slower than the noise limit, so G3.6 (a change that makes a
benchmark slower gives the reason) needs no reason. The known costs:
C9 (parse interface: the conversion to the `SyntaxTree` and the source
map; total 1.028 in its check) and C11 (config skeleton: sqll reads the
config in each start; start 1.081 in its check). The base binary reads
no config file, so it gets the settings as options (`legacy_options` of
`harness/sqll_harness/bench/sqll.py`, only for `sqll-base`).

## Each S3b bullet

| Bullet of STONES.md | Tasks | Documents | Tests |
|---|---|---|---|
| One lossless syntax tree | C6 (segment kinds), C7 (syntax tree), C9 (parse interface), C10 (typed view) | `docs/interfaces/segment-kinds.md`, `docs/interfaces/tree.md`, `docs/interfaces/parse.md`, `docs/interfaces/typed-view.md` | `crates/sqll_interfaces/tests/segment_kinds.rs`, `crates/sqll_interfaces/tests/tree.rs`, `crates/sqll_interfaces/tests/parse.rs`, `crates/sqll_interfaces/tests/typed_view.rs`, `scripts/s3/tree_guard.py`, `scripts/s3b/tree_check.py` |
| The source map | C8 (source map) | `docs/interfaces/source-map.md` | `crates/sqll_interfaces/tests/source_map.rs`, `scripts/s3b/source_map_oracle.py` |
| Frozen interfaces | C6 to C12 (the interfaces of Exit 2), C15 (tree to schema), C16 (package ownership) | `docs/interfaces/README.md`, `docs/decisions/s3b-core.md` | `harness/tests/test_s3b_interfaces.py`, `crates/sqll_interfaces/tests/rules.rs`, `crates/sqll_interfaces/tests/schema.rs` |
| The sqll binary skeleton | C11 (config), C13 (CLI), C14 (harness adapters) | `docs/interfaces/config.md`, `harness/sqll.md` | `crates/sqll_interfaces/tests/config.rs`, `crates/sqll/tests/cli.rs`, `crates/sqll/tests/cli_config.rs`, `scripts/s3b/cli_oracle.py`, `harness/tests/test_sqll_tool.py`, `harness/tests/test_sqll_bench.py` |
| A code layout with one package for each part | C4 (core design), C16 (package ownership) | `docs/decisions/s3b-core.md`, `docs/interfaces/README.md` | `harness/tests/test_s3b_core.py`, `harness/tests/test_ownership.py` |

## Not met yet

For later stones; they do not block S3b.

- G3.4 and G3.5 (faster than sqlfluff on each benchmark, not slower than
  sqruff on any benchmark) on lint and fix: the benchmark settings select
  all rules; sqll has only CP01, CP03, and CP04 until S5 (rule parity:
  each rule fixture, lint and fix).
- Autofix stays at 0 until the sqll part of S7 (CLI and config parity:
  the sqlfluff CLI, config, and Python rule tests as black-box cases)
  adds `sqll fix --show-lint-violations`.
- The sqll results of S9 (external corpus: the report shows parse success
  and speed for each file, for each tool) come after S3b.
