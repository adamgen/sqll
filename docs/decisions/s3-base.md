# S3 decision: the base of sqll

Status: data collection. No recommendation yet.

## Question

STONES.md, S3: which base do we use to make the sqll binary? The S1 and S2
data and the data of this record give the answer. A human owner chooses
the base. Phase A (this record) collects the data and gives a
recommendation. Phase B (the sqll binary) starts only after the human
owner chooses the base.

## Bases

All versions are the pinned versions. This record does not change them.

| Option | Base | Version and source |
|---|---|---|
| 1 | sqruff | sqruff `0.41.0`: the crates.io crates of the `sqruff` binary (`tools/sqruff/install.sh`, features `parser,python`). Apache-2.0. Its parser is a manual port of the sqlfluff grammar. |
| 2 | sqlfluffrs | sqlfluffrs `4.4.0`: the Rust workspace in `third_party/sqlfluff/sqlfluffrs` (submodule at sqlfluff tag `4.4.0`). MIT. Its dialect grammars are generated from the Python dialects of sqlfluff. Today it is a Python extension, not a standalone tool. |
| 3 | New parser | A new parser with a grammar generated from the sqlfluff `4.4.0` dialects (`third_party/sqlfluff/src/sqlfluff/dialects/`). No implementation exists. |

## Criteria

A criterion that maps to a goal or a stone measures the work or the risk
to get to that goal or stone from the base.

| Id | Criterion | Goals | Stones |
|---|---|---|---|
| C1 | Parse parity: exact tree match and no unparsable segments, per dialect | G1 | S3, S4 |
| C2 | Cost to fix the parse tree mismatches: how systematic they are | G1 | S4 |
| C3 | Rule, fix, and templater parity, and the coupling of the rules to tree shapes | G1 | S3, S5, S6 |
| C4 | Standalone binary: build without Python, native parse, reuse of the grammar generator | G1, G4 | S3, S4 |
| C5 | Speed: start, parse, lint, fix, and the distance to the G3 targets | G3 | S3 |
| C6 | License, attribution duties, code size, and structure | G1 (CONSTITUTION 2.6) | S3 |
| C7 | Capabilities: templaters, CLI and config, and the data that code generation needs | G1, G2 | S6, S7 |
| C8 | Work estimate for each base to the exit of S3 to S7 | G1 to G4 | S3 to S7 |

## Method

Each task writes its raw data as JSON under `results/s3/`. A task that
derives a file from committed data (not from timings) adds a drift test in
`harness/tests/`. Timings for the probe and for sqruff come from one
session on the baseline machine setup (`harness/bench.md`, "Baseline"):
the CI image in docker, serial, no other load. Comparisons use ratios
inside that session. The lint and fix times of sqruff and sqlfluff come
from the S2 baseline (`results/s2/baseline.json`). An estimate that uses
both sessions takes only ratios inside each session (T6).

Option 3 has no implementation. Each value for option 3 is an estimate. It
comes from the sqlfluffrs generator and engine and from the sqruff rule
sizes. The record labels each such value as an estimate.

| Criterion | Data | File | Task | Kind |
|---|---|---|---|---|
| C1 | S1 results of options 1 and 2 by suite and by dialect. sqruff: a new local run of the 4 suites (`results/s3/sqruff-cases.json`); sqlfluff-rs: `results/s1/summary.json` and the pinned fixtures | `results/s3/s1-by-base.json` | T2 | Measurement (options 1, 2); no data (option 3; T9 gives the estimate) |
| C2 | Classes of the sqruff tree mismatches: count of cases and dialects for each class; groups by segment type and the share of the top groups; hand check of a sample. Inputs: `results/s3/sqruff-tree-hunks.json` (a new sqruff run) and `results/s3/sqruff-tree-handcheck.json` | `results/s3/sqruff-tree-diffs.json` | T3 | Measurement |
| C3 | Classes of the sqruff rule, autofix, and templater failures (unsupported item, parse cause, rule logic); for each rule, the tree types that it reads and the count that differ from sqlfluff 4.4.0. Inputs: `results/s3/sqruff-rule-parses.json` (a new sqruff and sqlfluff parse) and `results/s3/sqruff-rule-types.json` (names from the sqruff 0.41.0 rule sources and the sqlfluff grammar) | `results/s3/sqruff-rule-diffs.json` | T4 | Measurement; the cause of a parse_cause case and the helper module names are estimates |
| C4 | sqlfluffrs probe (`scripts/s3/probe-sqlfluffrs/`, research code, not sqll; made and run by `scripts/s3/sqlfluffrs_probe.py`): build without Python, exact trees of the dialect fixtures in a native binary, the generator outside the submodule, and the start and parse times of the probe, sqruff, and sqlfluff in one session. Inputs: `results/s3/sqlfluffrs-probe-build.json`, `results/s3/sqlfluffrs-probe-cases.json`, and `results/s3/sqlfluffrs-probe-bench.json` | `results/s3/sqlfluffrs-probe.json` | T5 | Measurement; the reuse of the generator by option 3 is a judgement |
| C5 | For each base and benchmark (start, parse, lint, fix): the time, the ratios to sqlfluff and to sqruff, and the G3 result; the totals and the counts that miss a target (from `scripts/s3/speed_by_base.py`). Inputs: `results/s2/baseline.json` and `results/s3/sqlfluffrs-probe.json`; no new timing run | `results/s3/speed-by-base.json` | T6 | Measurement (option 1; option 2 start and parse); estimate with its formula (option 2 lint and fix; option 3, low and high bound) |
| C6 | License and attribution duties, lines of code, crates and modules of each base | `results/s3/license-size.json` | T7 | Measurement |
| C7 | For each base: templaters, CLI commands, config, parameter styles, and type data for code generation | `results/s3/capabilities.json` | T8 | List from the code (options 1, 2); estimate (option 3) |
| C8 | Work for each base and stone, from C1 to C7 | `results/s3/estimates.json` | T9 | Estimate |

T9 adds the data, the estimates, and the recommendation to this record.
