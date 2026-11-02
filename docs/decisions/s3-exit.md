# S3 exit record

Status: S3 awaiting human approval.

## Question

STONES.md, S3 exit: sqll passes all cases that the base passes, and sqll
is not slower than sqruff on any benchmark. This record gives the proof.
The base is sqlfluffrs (human owner, 2026-10-29;
[s3-base.md](s3-base.md)). A human approves the stone.

## Data

Each number in this record is a value of
[`results/s3/exit.json`](../../results/s3/exit.json) (from
`scripts/s3/exit.py`; drift test `harness/tests/test_s3_exit.py`). Each
value names its file and key, or a formula over other values. The inputs:
the S2 baseline with the final sqll (`results/s2/baseline.json`), the S1
summary, the T18 record of the native tests of the base, and the T14
target.

The baseline is one controlled run of `scripts/bench --profile full` on
commit `c9c72ec` (the S2 baseline method, `harness/bench.md`: the CI
image in docker, one container, no network, serial, under the machine
lock). All 4 tools ran all 280 benchmarks. Each time is the median wall
time of a benchmark in this one session.

## Exit criteria and proof

| Criterion | Result | Proof |
|---|---|---|
| Base cases: the S1 dialect suite | Met: 2306 of 2306 exact trees; 2306 with no unparsable segment; known-failure check: 0 new failures, 0 unexpected passes | `results/s1/summary.json`; the CI job report checks it on each head |
| Base cases: the native tests of the base (T18) | Met: 162 of 162 tests pass in the base, and each of them passes in sqll | `results/s3/base-native-tests.json`; the list check `scripts/s3/base_native_tests.py check` (CI job build, `scripts/verify`) |
| G3.5 on start and parse: sqll faster than sqruff | Met: 108 of 108 pairs; slower: 0 | the baseline |
| G3.4 on start and parse: sqll faster than sqlfluff | Met: 112 of 112 | the baseline |

Speed of sqll on start and parse:

- Ratio to sqruff (median wall time): median 0.506, at most 0.707
  (`parse/clickhouse/large`). 108 of 108 pairs are also below the T14
  target ratio 0.794, which keeps the result away from a tie in the
  measured noise.
- Ratio to sqlfluff: at most 0.033 (`parse/materialize/large`).
- sqruff has no soql dialect: 4 benchmarks have no sqruff pair. sqll is
  faster than sqlfluff on them.

Sums of the median wall times over the pairs (seconds):

| Benchmarks | Pairs | sqll | sqruff | sqll / sqruff |
|---|---|---|---|---|
| start | 27 | 0.16 | 0.49 | 0.328 |
| parse | 81 | 1.89 | 3.43 | 0.550 |
| start and parse | 108 | 2.05 | 3.92 | 0.522 |

## Where G3.5 applies

G3.5 applies to the benchmarks that sqll runs (start and parse). sqll has
no rules: lint and fix are unsupported until S5. In the baseline, sqll has
84 lint and 84 fix results with the status unsupported and no run.

## Base cases

The base cases are the S1 dialect suite (2306 of 2306) and the native Rust
tests of the base (162 of 162). The S1 rule cases of CP01, CP03, and CP04
are not base cases: the native base has no linter, config reader, CLI, or
fix. sqll keeps these rules as a library crate with their tests
(`crates/sqll_rules`); `sqll lint` stays unsupported until S5. The human
owner checks this reading at stone approval.

## Not met yet

These are for later stones. They do not block S3.

- G3.4 and G3.5 on lint and fix: sqll has no lint or fix until S5.
- the G3.5 total over all benchmarks: of the 280 benchmarks, sqll has 168
  results with the status unsupported. The total can be compared only when
  sqll runs lint and fix.
- The sqll results of the S9 corpus come after S3b.

## Proof

- `results/s3/exit.json` and its drift test: the test reads each copied
  value again from its file and key, and fails on a changed number.
- CI on the head of the T20 pull request: the S1 report of sqll and the
  known-failure check, the native tests, the tree guard, and the smoke
  benchmark against this baseline.
- G4.4: the CI full jobs (`bench-full`, `bench-merge` with the baseline
  check `--full`, and the corpus jobs) by `workflow_dispatch` on the head
  of the T20 pull request. `status/S3.md` gives the run. A full local run of
  `scripts/verify --full-bench` is not recorded.

## Open interface questions for S3b

1. **Tree type.** sqll keeps the tree of the base: the `Node` enum of
   `sqll_parser` with the segment types as strings, and the `Arena` (a flat,
   parent-linked arena with string types) that the rules read. S3b decides:
   an arena with string types, or an enum of the segment types from the
   generator (G2 needs a typed view).
2. **Source map.** The base has `TemplatedFile` (`sqll_types`), and the
   lexer takes it. sqll uses only the raw templater. S3b decides if
   `TemplatedFile` is the frozen interface from the templater to the source
   map (S6).
3. **Lexer to parser to tree.** `Lexer::lex` gives the tokens, the parser
   gives a `Node` tree, and `crates/sqll/src/parse.rs` connects them. S3b
   freezes this interface and the tree output for the S1 harness.
4. **Rule interface.** The port of CP01, CP03, and CP04 reads the arena read
   API (`Arena::from_node`, type strings). S3b decides the rule and fix
   interface of S5: this API or a new typed view.
5. **Ownership.** The S3 track owns `crates/**`, the Cargo files, and the
   sqll adapters until the human approves S3 (`tracks.yml`). S3b decides
   the move of these paths to the Core track, and the packages of each later
   track.
6. **CLI and config.** The S3 CLI has `sqll parse`, `sqll version`, and
   `sqll --license` in the shape of the sqlfluff commands; lint and fix are
   unsupported, and there is no config reader. S3b makes the CLI and config
   skeleton over the S3 CLI: it extends it, it does not replace it.
7. **Generated table format.** `scripts/build-sqll` generates the dialect
   tables with the sqlfluff generator in the table format of sqlfluffrs
   (`grammar_tables.rs`); a sha256 manifest checks them. S3b decides if
   this format is frozen, or if a new emitter writes another format (for
   example with a segment enum).

## Open legal questions

- The license choices of T19 (MIT, `sqll --license`) are conservative
  engineering choices, not legal advice. A lawyer can check them before a
  public release.
- Release packaging: the notices in `COPYRIGHT` of the Rust standard
  library, other than its MIT notice.
- If sqll ports sqruff code later: those files keep Apache-2.0, its full
  text and notices, and its appendix copyright line (T19, Q2 and Q7).
