# S3b exit record

Status: S3b awaiting approval. The goal of S3b: the shared syntax tree,
source map, frozen interfaces, and the sqll binary skeleton (CLI, config,
output) with the sqll adapters of the test harness and the benchmarks.
The exits: the test harness and the benchmarks run sqll through its
adapters, the interfaces are documented, and after this stone, each
change to the core goes through the Core track (the track that does S3b
and owns the shared core). The orchestrator approves the stone by the
standing delegation (CONSTITUTION.md, section 5) after an independent
check.

## Data

Each number in this record is a value of
[`results/S3b/exit.json`](../../results/S3b/exit.json), from
`scripts/s3b/exit.py`. The inputs: the CI record
`results/S3b/exit-ci.json`, the speed check
`results/S3b/speed/C17.json`, and frozen copies
(`results/S3b/exit-inputs/`) of `results/s1/summary.json`,
`docs/interfaces/README.md`, and `tracks.yml`. `--check` makes the record
and the ownership probe again, on the frozen and the live `tracks.yml`
(CI job build; `harness/tests/test_s3b_exit.py`).

The exit head is main `a77e821`: the merge of the pull request that gives
the package ownership of the later tracks and the interface index. After
it, main merged 3 pull requests. They change only `AGENTS.md`,
`harness/tests/test_protocol_docs.py`, and the paths of the conversion of
the CLI and config tests (`harness/sqll_harness/s7_tests/`,
`scripts/s7-tests/`, `results/S7-tests/`). They and this pull request
change no file under `crates/`, `Cargo.toml`, or `Cargo.lock`, and no
file of the harness core, so the sqll of the head is that of the exit
head.

## Exit 1: the test harness and the benchmarks run sqll

The test harness (it runs the sqlfluff test fixtures through a binary)
and the benchmarks (each command, with small, medium, and large inputs
for each dialect) run sqll through its adapters
([harness/sqll.md](../../harness/sqll.md), "Adapter" and "Benchmark
adapter"). CI run 42986804942 (push on main, head `a77e821`): conclusion
success, 77 jobs. Lines of the job logs:

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
passes.

## Exit 2: the interfaces are documented

The index [docs/interfaces/README.md](../interfaces/README.md) has 8 rows.
Each has its document and its test in `crates/sqll_interfaces/tests/`. The
4 frozen interfaces of STONES.md map to the rows:

| STONES interface | Rows |
|---|---|
| lexer to parser to tree | Segment kinds, Syntax tree, Parse, Typed view |
| tree to rules to fixes | Config, Rules and fixes |
| templater to source map | Source map |
| tree to schema for code generation | Tree to schema |

Config is in "tree to rules to fixes": a rule reads its settings from
it. `harness/tests/test_s3b_interfaces.py` checks the index.

## Exit 3: each change to the core goes through the Core track (the track that does S3b and owns the shared core)

`tracks.yml` gives each later track only `src/**` and `tests/**` of its
packages. Each interface, each `Cargo.toml` and `build.rs`, `Cargo.lock`,
and `crates/sqll_interfaces` stay Core paths (tests:
`harness/tests/test_ownership.py`).

The probe: in a new git repository, a pull request of each of the 10
tracks of `tracks.yml` that do not own the core (the closed track, the
active tracks, and the later tracks) changes one of 6 Core paths
(`docs/interfaces/parse.md`, `crates/sqll_interfaces/tests/parse.rs`,
`crates/sqll_syntax/src/lib.rs`,
`crates/sqll_parser/Cargo.toml`, `crates/sqll_dialects/build.rs`,
`Cargo.lock`), and `ci/ownership.py` runs on the merge commit. Of the 60
runs, 60 fail without the label and 60 pass with the label
`cross-track`. The 10 control runs (the status file of the track) pass.
The "probe" list of `results/S3b/exit.json` gives each run.

3 lines of the output of the branch `claude/s4`, no label:

```text
Branch claude/s4: track S4.
- docs/interfaces/parse.md: owned by core (another track)
Result: fail.
```

## Speed: keep the speed of the base

The speed check `results/S3b/speed/C17.json` (`scripts/speed-check`,
with the machine lock) has the base `319b7d6` and the head `a77e821`.
The base is the exit head of the stone that chose the base and made the
sqll binary from it. Thus the check measures all sqll changes of this
stone together.

- 112 benchmarks: 0 slower than the noise limit, 0 failures.
- HEAD / BASE of the wall time: start 1.096, parse/small 1.068,
  parse/medium 1.031, parse/large 1.043, total 1.048.
- HEAD is faster than sqlfluff on 112 of 112 (total ratio 0.023) and faster
  than sqruff on 108 of 108 pairs (total ratio 0.552).

No benchmark is slower than the noise limit, so no benchmark needs the
reason for a slowdown. The known costs: the conversion to the
`SyntaxTree` and the source map in the parse interface (total 1.028 in
`results/S3b/speed/C9.json`), and the config read in each start (start
1.081 in `results/S3b/speed/C11.json`). The base binary reads no config
file, so it gets the settings as options (`legacy_options` of
`harness/sqll_harness/bench/sqll.py`, only for `sqll-base`).

## Each S3b bullet

| Bullet of STONES.md | Documents | Tests |
|---|---|---|
| One lossless syntax tree | `docs/interfaces/segment-kinds.md`, `docs/interfaces/tree.md`, `docs/interfaces/parse.md`, `docs/interfaces/typed-view.md` | `crates/sqll_interfaces/tests/segment_kinds.rs`, `crates/sqll_interfaces/tests/tree.rs`, `crates/sqll_interfaces/tests/parse.rs`, `crates/sqll_interfaces/tests/typed_view.rs`, `scripts/s3/tree_guard.py`, `scripts/s3b/tree_check.py` |
| The source map | `docs/interfaces/source-map.md` | `crates/sqll_interfaces/tests/source_map.rs`, `scripts/s3b/source_map_oracle.py` |
| Frozen interfaces | `docs/interfaces/README.md`, `docs/decisions/s3b-core.md` | `harness/tests/test_s3b_interfaces.py`, `crates/sqll_interfaces/tests/rules.rs`, `crates/sqll_interfaces/tests/schema.rs` |
| The sqll binary skeleton | `docs/interfaces/config.md`, `harness/sqll.md` | `crates/sqll_interfaces/tests/config.rs`, `crates/sqll/tests/cli.rs`, `crates/sqll/tests/cli_config.rs`, `scripts/s3b/cli_oracle.py`, `harness/tests/test_sqll_tool.py`, `harness/tests/test_sqll_bench.py` |
| A code layout with one package for each part | `docs/decisions/s3b-core.md`, `docs/interfaces/README.md` | `harness/tests/test_s3b_core.py`, `harness/tests/test_ownership.py` |

## Not met yet

For later stones; they do not block this stone.

- Faster than sqlfluff on each benchmark and not slower than sqruff on
  any benchmark, on lint and fix: the benchmark settings select all
  rules; sqll has only CP01, CP03, and CP04 until the stone of rule
  parity.
- Autofix stays at 0 until the sqll part of the CLI and config parity
  adds `sqll fix --show-lint-violations`.
- The sqll results of the external corpus come after this stone.
