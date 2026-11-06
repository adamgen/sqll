# S3b status (Core track)

S3b (STONES.md) is in work in the Core track. S3 is approved (human
owner, 2026-11-06). The plan: one pull request for each task, C3 to C17.
The S3 code paths are Core paths since C3 (`tracks.yml`).

## Tasks

| Task | Description | State |
|---|---|---|
| C1 | Record the S3 approval and the standing delegation; freeze the inputs of the S3 exit record | Merged (PR #57) |
| C2 | `bench compare`: a table for each benchmark when it compares tools of one report | Merged (PR #58) |
| C3 | Record the S3b plan and move the S3 code paths to the Core track | In review |
| C4 | Decision record: the S3b core design (answers to the 7 open interface questions) | Not started |
| C5 | Speed check tool for each Core change (G3.6) | Not started |
| C6 | Typed segment kinds from the frozen dialect tables | Not started |
| C7 | Lossless syntax tree (`sqll_tree`) and the conversion from the parser tree | Not started |
| C8 | Source map: `TemplatedFile` as the frozen templater interface, raw templater | Not started |
| C9 | Frozen parse interface (lexer to parser to tree) and `sqll parse` output from `SyntaxTree` | Not started |
| C10 | Typed view of the tree | Not started |
| C11 | Config skeleton (`sqll_config`) and its use in `sqll parse` | Not started |
| C12 | Rule and fix interface (`sqll_lint`) with CP01, CP03, CP04 as the proof | Not started |
| C13 | CLI skeleton: lint, fix, rules, dialects, and output formats | Not started |
| C14 | Harness adapters: `sqll lint` and `fix` in the S1 harness and the S2 benchmarks | Not started |
| C15 | Code generation interface: tree to schema | Not started |
| C16 | Package ownership of the later tracks and the interface index | Not started |
| C17 | S3b exit: proof, exit record, and STATUS "S3b awaiting human approval" | Not started |

Rules for each task:

- G4: CI passes on a head with origin/main merged. S1: 2306 of 2306
  exact for sqll, 0 new failures, 0 unexpected passes. The tree guard
  record and the `sqll parse` output do not change. Native base tests:
  162 of 162.
- G3: from C5, a task that changes code of the sqll binary records
  `results/S3b/speed/<task>.json`. A task that adds code that the binary
  does not link gives `cargo tree` proof.
- `sqll lint` and `fix` fail closed: a rule or setting that sqll does not
  have gives "unsupported" and exit code 2.

## C2: sqll and sqlfluff in the S2 baseline

`sqll-harness bench compare results/s2/baseline.json --tool sqll --tool
sqlfluff` (`harness/bench.md`, "Back-to-back comparison"). The ratio is
sqlfluff / sqll of the median wall times. sqll has only `start` and
`parse`: 168 benchmarks are left out (`unsupported`).

| Group | Benchmarks | sqll (s) | sqlfluff (s) | Ratio of the sums | Min | Median | Max | sqll faster |
|---|---|---|---|---|---|---|---|---|
| start | 28 | 0.1650 | 15.7311 | 95.330 | 71.628 | 101.515 | 130.030 | 28 |
| parse/small | 28 | 0.2606 | 17.1020 | 65.629 | 48.641 | 67.258 | 87.298 | 28 |
| parse/medium | 28 | 0.4505 | 21.8629 | 48.529 | 37.079 | 48.637 | 65.636 | 28 |
| parse/large | 28 | 1.2630 | 43.5264 | 34.463 | 30.741 | 34.522 | 40.207 | 28 |
| total | 112 | 2.1391 | 98.2224 | 45.918 | 30.741 | 57.270 | 130.030 | 112 |

`harness/tests/test_bench_compare.py` makes this table again from the
baseline and compares it with this file.
