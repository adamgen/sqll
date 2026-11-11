# S3b exit record

Status: S3b awaiting approval. The orchestrator approves S3b (Core: the
shared syntax tree, source map, frozen interfaces, and the sqll binary
skeleton) by the standing delegation (CONSTITUTION.md, section 5) after an
independent check.

## Data

Each number in this record is a value of
[`results/S3b/exit.json`](../../results/S3b/exit.json), from
`scripts/s3b/exit.py` (task C17: S3b exit: proof, exit record, and the
request for approval). Each value names its file and key, a CI log line,
or a formula. The inputs: the CI record `results/S3b/exit-ci.json`, the
speed check `results/S3b/speed/C17.json`, and frozen copies
(`results/S3b/exit-inputs/`) of `results/s1/summary.json`,
`docs/interfaces/README.md`, and `tracks.yml`. `--check` makes the record
again and runs the ownership probe again on the frozen and on the live
`tracks.yml` (CI job build; `harness/tests/test_s3b_exit.py`).

The exit head is main `a77e821` (C16 merged). C17 changes no file under
`crates/`, `Cargo.toml`, or `Cargo.lock`, so its sqll is that of the exit
head.

## Exit 1: the S1 harness and the S2 benchmarks run sqll

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
bench-merge (the full S2 profile of all tools, sqll included):
out/bench.json: no schema error; complete for its scope.
The stable data of 1120 results is that of the baseline results/s2/baseline.json.
The report has the profile and each result of the baseline.
build:
base native tests: PASS: 162 base tests pass in the base; sqll: 362 tests, 358 passed, 0 failed, 4 ignored; 0 problems
tree guard: 84 of 84 inputs, 2 runs each: same output as the record
```

The build job also gives the PASS line of each oracle check of S3b: tree,
source map, crawl, config, rules, CLI, jinja as raw, and schema (the CI
record has each line).

The S1 summary of sqll: dialects 2306 of 2306 exact (2306 with no
unparsable segment), rules 38 of 2527, autofix 0 of 61, templater 0 of 43;
parity 2344 of 4937; 0 new failures and 0 unexpected passes. The adapters:
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

Config is in "tree to rules to fixes": a rule reads its settings from the
config. `harness/tests/test_s3b_interfaces.py` checks the index.

## Exit 3: each change to the core goes through the Core track

`tracks.yml` (C16: package ownership of the later tracks and the interface
index) gives each later track only `src/**` and `tests/**` of its packages.
Core keeps each interface, each `Cargo.toml` and `build.rs`, `Cargo.lock`,
and `crates/sqll_interfaces`. `harness/tests/test_ownership.py` tests the
owner of each path.

The probe: in a new git repository, a pull request of each of the 7 later
tracks (S4 to S11) changes one of 6 Core paths (`docs/interfaces/parse.md`,
`crates/sqll_interfaces/tests/parse.rs`, `crates/sqll_syntax/src/lib.rs`,
`crates/sqll_parser/Cargo.toml`, `crates/sqll_dialects/build.rs`,
`Cargo.lock`), and `ci/ownership.py` runs on the merge commit. Of the 42
runs, 42 fail without the label and 42 pass with the label `cross-track`
with a Core review. The 7 control runs (the status file of the track)
pass. Output of one run (S4, parser parity):

```text
Branch claude/s4: track S4.
- docs/interfaces/parse.md: owned by core (another track)
Result: fail. The pull request changes files of the tracks core. Ask the owning track for the change (an issue), or add the label 'cross-track' and get a review from the owning track.
Result: fail.
```

## G3: keep the S3 speed

G3 (speed: sqll faster than sqlfluff, not slower than sqruff). The speed
check `results/S3b/speed/C17.json` (`scripts/speed-check`, with the machine
lock): base `319b7d6` (the S3 exit; the C5 base has the same sqll source),
head `a77e821`. Thus it measures the sum of the S3b changes.

- 112 benchmarks: 0 slower than the noise limit, 0 failures.
- HEAD / BASE of the wall time: start 1.096, parse/small 1.068,
  parse/medium 1.031, parse/large 1.043, total 1.048.
- HEAD is faster than sqlfluff on 112 of 112 (total ratio 0.023) and faster
  than sqruff on 108 of 108 pairs (total ratio 0.552).

No benchmark is slower than the noise limit, so G3.6 needs no reason. The
known costs of the change: C9 (parse interface: the conversion to the
`SyntaxTree` and the source map; total 1.028 in its check) and C11
(config: sqll reads the config in each start; start 1.081 in its check).

The S3 binary reads no config file. Thus the speed check gives the base
binary the settings as options (`legacy_options` of
`harness/sqll_harness/bench/sqll.py`, only for `sqll-base`).

## Each S3b bullet

| Bullet of STONES.md | Tasks | Documents | Tests |
|---|---|---|---|
| One lossless syntax tree | C6 (segment kinds), C7 (syntax tree), C9 (parse interface), C10 (typed view) | `docs/interfaces/segment-kinds.md`, `docs/interfaces/tree.md`, `docs/interfaces/parse.md`, `docs/interfaces/typed-view.md` | `crates/sqll_interfaces/tests/segment_kinds.rs`, `crates/sqll_interfaces/tests/tree.rs`, `crates/sqll_interfaces/tests/parse.rs`, `crates/sqll_interfaces/tests/typed_view.rs`, `scripts/s3/tree_guard.py`, `scripts/s3b/tree_check.py` |
| The source map | C8 (source map) | `docs/interfaces/source-map.md` | `crates/sqll_interfaces/tests/source_map.rs`, `scripts/s3b/source_map_oracle.py` |
| Frozen interfaces | C6 to C12, C15 (tree to schema), C16 (package ownership) | `docs/interfaces/README.md`, `docs/decisions/s3b-core.md` | `harness/tests/test_s3b_interfaces.py`, `crates/sqll_interfaces/tests/rules.rs`, `crates/sqll_interfaces/tests/schema.rs` |
| The sqll binary skeleton | C11 (config), C13 (CLI), C14 (harness adapters) | `docs/interfaces/config.md`, `harness/sqll.md` | `crates/sqll_interfaces/tests/config.rs`, `crates/sqll/tests/cli.rs`, `crates/sqll/tests/cli_config.rs`, `scripts/s3b/cli_oracle.py`, `harness/tests/test_sqll_tool.py`, `harness/tests/test_sqll_bench.py` |
| A code layout with one package for each part | C4 (core design), C16 (package ownership) | `docs/decisions/s3b-core.md`, `docs/interfaces/README.md` | `harness/tests/test_s3b_core.py`, `harness/tests/test_ownership.py` |

## Not met yet

These are for later stones. They do not block S3b.

- G3.4 and G3.5 on lint and fix: the S2 settings select all rules, and
  sqll has only CP01, CP03, and CP04 (S5, rule parity).
- Autofix stays at 0 until the S7 sqll part (CLI and config parity) adds
  `sqll fix --show-lint-violations`.
- The sqll results of the S9 corpus (external corpus) come after S3b.
