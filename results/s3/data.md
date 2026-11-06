# S3 data

The data and the method of each S3 task, and the phase A task table (at
the end). The state and the phase B task table are in
[status/S3.md](../../status/S3.md).

## S3 phase B data

- T11: the Rust workspace (`Cargo.toml`, `crates/`). `crates/sqll_types`,
  `sqll_lexer`, `sqll_parser`, and `sqll_dialects` are a port of the
  sqlfluffrs 4.4.0 crates, without the Python bindings and pyo3
  (`crates/ported.json`: 54 ported files, 10 of them changed with a reason,
  7 source files not ported). `scripts/build-sqll` generates the dialect
  tables in a scratch copy with the pinned generator: 85 files, 414352
  lines, each equal to `crates/sqll_dialects/generated.json` and to the T5
  record. The release build has 0 Python calls, no pyo3 in `cargo tree`
  (68 packages), and Rust 1.97.0. `cargo test --locked`: 62 tests pass (54
  ported unit tests, 8 tests of the table check). CI job `build`.
- T12: the sqll binary (`crates/sqll`; `harness/sqll.md`). `sqll parse
  --dialect D` prints the record of `sqlfluff parse -f json` with the raw
  templater and the default config (the differences: `harness/sqll.md`).
  `sqll lint` and `sqll fix` stop with `unsupported: lint` (or `fix`) and
  exit code 2. The version is `0.1.0+tables.` and the sha256 of
  `generated.json`; the tool check refuses a stale binary (source hash) and
  a binary that needs libpython. S1 (`results/s1/summary.json`): dialects
  2306 of 2306 exact and no_unparsable; the 2527 rule cases fail with
  `unsupported: lint`, the 61 autofix and 43 templater cases with
  `unsupported: templater` (`known_failures/sqll.txt`). A local comparison
  of `sqlfluff parse -f json --templater raw --ignore-local-config` and
  `sqll parse` on the 2306 dialect files: the same stdout bytes and exit
  code in 2306 of 2306, with and without `-c`. With `-m` (run on the
  parser code of `ebac08e`), the same tree in 2306 of 2306 after the
  position keys are removed from the sqlfluff record and the sqll record
  has the sqlfluff list shape (`harness/sqll.md`). CI: 5 sqll test jobs
  with the binary of the build job. The phase A scripts read frozen copies of
  their S1 and S2 inputs (`results/s3/phase-a/`, `scripts/s3/phase_a.py`);
  their outputs do not change. T12 changed 3 ported files (now 13 of 54 in
  `crates/ported.json`): in `iterative.rs` and `core.rs`, the iteration
  limit gives a parse error, not a panic, a parser limit (iterations,
  depth, or nodes) that a probe reaches also stops the parse, and a probe
  starts at the parse depth of its caller (so that the depth limit also
  limits the stack); in `helpers.rs`, only a comment. For the 2306 dialect
  files, the probe depth change gives the same stdout, stderr, and exit
  code as the parser code of `20d82f1`, with no option, `-c`, and `-m`. The feature `verbose-debug` of
  `sqll_parser` does not build (a borrow error that is also in the
  source).
- T13: the S2 adapter `harness/sqll_harness/bench/sqll.py`. The new
  `results/s2/baseline.json` (controlled run, `status/S2.md`): sqll is
  valid on 28 of 28 `start` and 84 of 84 `parse` benchmarks; `lint` and
  `fix` are `unsupported`. The other 3 tools have the statuses of the S2
  exit baseline. Wall time sums (median of each benchmark) on the 108
  benchmarks where sqll and sqruff are valid: sqll 4.7 s, sqruff 3.7 s
  (ratio 1.256). T14 measures this again and sets the target. The S9
  corpus runs sqll only after S3b (`LATER`).
- T14: `results/s3/speed-profile.json` (from `scripts/s3/speed_profile.py`;
  drift test `harness/tests/test_s3_speed_profile.py`). Inputs: 5 sessions
  of sqll and sqruff on the 28 start and 84 parse benchmarks (S2 baseline
  method, `results/s3/speed-profile-sessions.json`) and a callgrind
  profile of each benchmark (`results/s3/speed-profile-callgrind.json`).
  Each value is measured, or derived or estimated with a formula in the
  JSON. The new `sqll parse --timings` gives the phase times.
  - Noise: the sqll/sqruff ratio R of a benchmark changes by up to 25.5%
    between sessions (median 8% to 12% for each group); the median time of
    one tool changes by up to 54%. Thus m = 0.26.
  - Phase shares of the sqll time (mean): start: dialect table setup 0.42,
    outside main 0.37, parse 0.16. parse/large: parse 0.54, lex 0.15, drop
    at exit 0.13, record 0.08, setup 0.04.
  - Profile (Ir) of the parse phase of the 5 worst parse benchmarks: copy
    (memcpy, clone) 28% to 30%, malloc and free 24% to 27%, the parser's own
    code 37% to 39%. The lex phase of ansi large: allocation 41%, regex 15%.
  - The lex and parse factor of T6 (median 1.75, at most 3.82 on 44 parse
    benchmarks) is now median 1.93, at most 3.64 on 50 (no margin); 3.02
    and 7.29 on 63 with the margin.
  - 9 improvement classes (T15: drop at exit, direct JSON output, lexer
    tables, process start, command start; T16: allocation and copy, and
    hashing of the parser; allocation and copy, and regex of the lexer).
    Each gain is r times the removable cost; r = 1 for the drop at exit and
    the direct output, else r = 0.5 (an assumption). Result: the target is
    in reach on 78 of 108 benchmarks; with r = 1 for each class, on 108;
    each class must remove at least 86% (`break_even_r`). With m = 0, on
    100 of 108. The parser's own code has no estimate.
  - Tree guard: `scripts/s3/tree_guard.py` and `results/s3/tree-guard.json`
    (CI job build). The sqll output of each of the 84 parse inputs, with no
    option and with `-m`, must be that of main at `1a2219c` (the T11 port
    with the T12 limit changes, before any speed change). That output equals the sqlfluff 4.4.0 output on 84 of
    84 (stdout bytes; with `-m`, the tree without the position keys).
- T15: the fixed cost of each run (`crates/ported.json` gives each change).
  sqll is a position-dependent executable (74 relocations, not 73963); it
  exits with no drop of the tree; it writes the JSON from the tree (a test
  compares it with the old record on the 2306 fixtures, 4 option sets); a
  lexer regex compiles at its first use, and only if a match can start at
  the input (regex_syntax match prefixes). The output does not change: the
  tree guard passes, and the binaries before and after give the same
  stdout, stderr, and exit code on the 2306 fixtures and the 84 parse
  inputs with no option, `-c`, `-m`, and `-c -m`.
  - `results/s3/speed/T15.json` (T14 method, `speed_profile.py --task
    T15`, T14 target): 63 of 108 benchmarks are below the target (T14:
    41): start 27, parse/small 24, parse/medium 11, parse/large 1 of 27.
    Median ratio to sqruff 0.709 (T14: 0.961), at most 1.528
    (parse/hive/large).
  - New in-reach estimate: the central estimate reaches the needed factor
    on 90 of 108 (T14: 78; 12 of 27 parse/large), `break_even_r` 0.80;
    thus still no-go. The human owner decided that T16 runs and that T16b
    decides. The noise of the 5 T15 sessions is 0.30 (T14: 0.26); the
    target does not change.
  - G3.6: `bench compare` of main (`a0a7a9c`) and T15 in one session pair
    (`results/s3/speed/T15-compare.json`): 112 sqll benchmarks, 0 slower,
    95 faster, 17 same; the wall time sum 5.46 s to 4.26 s.
  - Now the largest fixed cost is the regex compile: of the lexer (lex
    phase) and of the grammar (parse phase); start: lex 0.29, parse 0.22,
    outside main 0.45 of the time.
- T16: the lexer and parser hot path, round 1 (`crates/ported.json` gives
  each change; one class for each commit). Copy: each parse frame is in a
  box (a move copies a pointer, not 312 bytes). Memo: a match result keeps
  its node count, so that the node limit check does not count each subtree
  again for each ancestor. Allocation: the type id lists of StringParser and
  TypedParser only on a match; class types with no hash set; the tree build
  with a sorted list, not a hash map, and no copy of a child that is not
  shared. Lexer allocation: each lexed element borrows its text and its
  matcher. The output does not change: `cargo test`, the tree guard, and
  9560 of 9560 runs of the binaries before and after (the 2306 fixtures and
  the 84 parse inputs, 4 option sets) with the same stdout, stderr, and exit
  code.
  - `results/s3/speed/T16.json` (T14 method and target): 76 of 108
    benchmarks are below the target (T15: 63): start 27, parse/small 25,
    parse/medium 21, parse/large 3 of 27. Median ratio to sqruff 0.641
    (T15: 0.709), at most 1.173 (parse/hive/large).
  - New in-reach estimate: the central estimate reaches the needed factor
    on 102 of 108 (T15: 90; 21 of 27 parse/large), `break_even_r` 0.63;
    thus still no-go. T16b decides. The noise of the 5 T16 sessions is
    0.38 (largest spread: start/bigquery); the target does not change.
  - G3.6: `bench compare` of main (`795104d`) and T16
    (`results/s3/speed/T16-compare.json`): 112 sqll benchmarks, 0 slower,
    30 faster, 82 same; the wall time sum 4.34 s to 3.71 s.
  - Profile for T17 (`results/s3/speed/T16-callgrind.json`, the top
    functions of the 5 worst parse benchmarks): the parse phase has 31% to
    33% fewer instructions than in T15; its shares: allocator 33% to 37%,
    copy 9% to 10%, the parser's own code 43% to 49%. The lex phase of
    the 3 parse/large has 14% to 15% fewer; lex shares: regex 23% to 55%,
    allocator 25% to 26%. A local call graph (not in the record, ansi
    large) gives the largest remaining allocations: the frame boxes and the
    strings of the tree nodes and of the matched classes.
- T16b: the checkpoint (result above). `speed_profile.py --task T16b`
  without a change of the script: 5 new sessions
  (`results/s3/speed/T16b-sessions.json`) and the profile
  (`T16b-callgrind.json`) of the T16 source and binary (the same sha256 as
  the T16 sessions). Drift test `harness/tests/test_s3_speed_t16b.py`.
  - Median ratio to sqruff 0.64 (T16: 0.64), at most 1.217
    (parse/hive/large; T16: 1.173).
    Below the target: start 27, parse/small 25, parse/medium 17,
    parse/large 2 of 27. Central estimate in reach: 23 of 27 parse/large;
    `break_even_r` 0.68.
  - Noise: the largest spread 0.436 (parse/impala/small); m = 0.44 with
    the T14 formula. The target keeps the T14 m; thus a benchmark below the
    target is not proof of G3.5 at the noise of these sessions.
  - The classes and their mean central gain on parse/large (sqll mean
    73 ms): parse allocation and copy 14.0 ms, lex allocation and copy 1.8
    ms, lex regex 1.7 ms, process start 1.1 ms, parse hashing 0.5 ms; the
    other 4 classes 0.2 ms or less. The parse phase is 82% to 83% of the
    time of the 3 worst parse/large.
- T17: close the gap, round 1 (`crates/ported.json` gives each change;
  one class for each commit). Terminator checks: greedy_match does not
  probe a terminator where its simple hint cannot match. The check
  `scripts/s3/hint_check.py` builds sqll with `scripts/s3/hint-check.patch`,
  which also runs each excluded probe (`results/s3/speed/T17-hint-check.json`):
  on the 2390 inputs, 974128 exclusions, no probe match, no probe at a
  parser limit, and the same output. (The message of commit `7c249ed` gives
  1344746, from a scratch build that is not recorded; this check replaces
  it.) A probe that
  is not run cannot reach a parser limit; thus sqll can give a tree where
  the sqlfluff Rust parser stops (`harness/sqll.md`). Memo: contains_unparsable. Allocation: a size-class
  allocator for the sqll binary (`crates/sqll/src/alloc.rs`). Regex: the
  pattern id is the cache key, and the anti-pattern comes last. Build
  profile: fat link-time optimization, and the profile toggles are the phase
  functions of `crates/sqll/src/parse.rs`. Copy: the class of a match result
  is in a box (88 bytes, not 296). The output does not change: `cargo
  test`, the tree guard, and for each commit 9560 of 9560 runs of the
  binaries before and after (the 2306 fixtures and the 84 parse inputs, 4
  option sets) with the same stdout, stderr, and exit code.
  - `results/s3/speed/T17.json` (T14 method and target): 108 of 108
    benchmarks below the target (T16b: 71): start 27, parse/small 27,
    parse/medium 27, parse/large 27 of 27. Median ratio to sqruff 0.513
    (T16b: 0.64), at most 0.718 (parse/db2/large). The noise of the 5
    sessions is 0.44 (largest spread: parse/sparksql/medium), but each
    session has 108 of 108 below the target.
  - The parse phase of the 3 worst parse/large of T16b (ansi, db2, hive)
    has 54% to 59% fewer instructions than in T16b; the parser's own code
    is now 76% to 79% of it.
  - soql (no sqruff pair): one session of sqll and sqlfluff on the 4 soql
    benchmarks (`results/s3/speed/T17-soql.json`): sqll/sqlfluff 0.010
    (start) to 0.028 (parse/large).
  - G3.6: `bench compare` of main (`bffc11a`) and T17
    (`results/s3/speed/T17-compare.json`): 112 sqll benchmarks, 0 slower,
    66 faster, 46 same; the wall time sum 3.44 s to 2.28 s.
- T18: the native tests of the base and the 3 rules.
  - `scripts/s3/base_native_tests.py record` copies the submodule into a
    scratch folder (git archive), generates the 85 tables there (equal to
    `crates/sqll_dialects/generated.json`), and runs `cargo test --locked
    --offline --no-fail-fast` of the packages sqlfluffrs, sqlfluffrs_types,
    sqlfluffrs_lexer, sqlfluffrs_parser, sqlfluffrs_dialects, and
    sqlfluffrs_rules (no feature "python"; Rust 1.96.1 of
    `sqlfluffrs/rust-toolchain.toml`; Python commands on PATH fail and
    record each call: 0 calls). `scripts/check-submodule` passes before
    and after. Result (`results/s3/base-native-tests.json`, the output in
    `results/s3/base-native-tests.log`): 23 units, 162 tests, 162 passed.
    Root crate: 108 (60 of `tests/fixture_tests.rs`); unit tests: types
    28, parser 21, dialects 5, lexer 0, rules 0; doc tests: 0.
  - The port (`crates/ported.json`): `crates/sqll_rules` (CP01, CP03, CP04;
    no Python bindings) and `crates/sqll_base_tests` (the library
    `src/test_harness.rs` keeps the name sqlfluffrs; the 11 files of
    `tests/`). 4 files read the fixtures from the submodule path; no other
    test change. `Arena::from_node` of `sqll_parser` is public, so that
    the rules can get an arena from a parse tree outside the parser crate.
    New: `crates/sqll_rules/tests/rules.rs` (3 tests, 12 cases: the
    output of `sqlfluff fix` 4.4.0 for the same SQL and policy).
  - The list check (`scripts/s3/base_native_tests.py check`, CI job build
    and `scripts/verify`) runs `cargo test --locked --no-fail-fast` of the
    workspace and fails if cargo fails, if the output does not agree with
    itself, or if a base test that passes in the base is not in sqll or
    does not pass there. Local run: `base native tests: PASS: 162 base
    tests pass in the base; sqll: 212 tests, 212 passed, 0 failed, 0
    ignored; 0 problems`. `harness/tests/test_s3_base_native_tests.py`:
    a removed, failed, ignored, or renamed test, a removed test binary, and
    output that does not agree with itself each fail the check.
  - The S1 dialect suite (sqll): 2306 of 2306 exact. Tree guard: `84 of 84
    inputs, 2 runs each: same output as the record`.
  - Speed (G3.6), the reason in place of a bench compare: the release
    binary of T18 and that of main (`4850a32`) have the same size
    (15655368 bytes). `cmp -l` finds 85 different bytes, all in 3 places
    of build data: the source hash (63 of its 64 bytes), the source file
    count (2 bytes), and the build ID (20 bytes). The machine code does not
    change, so no benchmark can change.
- T19: the license and the notices of sqll.
  - `LICENSE` (MIT, "Copyright (c) 2026 The sqll authors") is the MIT text
    of the pinned sqlfluff with the sqll copyright line. The 7 crates of the
    workspace have `license = "MIT"`.
  - The dependency notice list (`crates/sqll/build/notices.rs`, made by
    `crates/sqll/build.rs` from `cargo metadata --filter-platform` of the
    target): 45 crates.io crates that the package sqll needs, 40 linked
    into the binary (the other 5 are proc-macro crates and their
    dependencies). Chosen: MIT 42, Apache-2.0 1 (ryu: Apache-2.0 OR
    BSL-1.0), MIT AND Unicode-3.0 1 (unicode-ident), Zlib 1 (foldhash);
    40 crates have an OR choice. `cargo metadata` of the workspace (each
    platform; normal, build, and dev dependencies): 98 packages, 0
    problems (`crates/sqll/tests/license.rs`).
  - `sqll --license` (release binary): 84401 bytes. The binary is 15741720
    bytes, 86352 more than main (`d344b23`).
  - Fail closed: the build with Zlib out of the allow list stops
    ("foldhash 0.2.0: no choice of the license \"Zlib\" is in the allow
    list"). The unit tests use invented packages: a GPL-3.0-only
    dependency, an AGPL-3.0-only dev dependency, no license, a git source,
    a sqll crate without MIT, and no file with the text of the chosen
    license each fail; "LGPL-2.1-or-later OR MIT" passes with "Chosen: MIT".
  - Local runs: `base native tests: PASS: 162 base tests pass in the base;
    sqll: 223 tests, 223 passed` (212 of T18 and 11 of `tests/license.rs`);
    tree guard: 84 of 84 inputs, same output as the record.
  - G3.6: `bench compare` of main (`d344b23`) and T19 (`afb0cab`), full
    profile, sqll only (`results/s3/speed/T19-compare.json`): 112 sqll
    benchmarks, 0 slower, 0 faster, 112 same; the wall time sum 2.070 s to
    2.089 s.
- T20: the S3 exit record (`docs/decisions/s3-exit.md`).
  - The new `results/s2/baseline.json`: one controlled run of `scripts/bench
    --profile full` on a fresh clone of main (`c9c72ec`), the S2 baseline
    method (`status/S2.md`): exit code 0, 7520 s. The other 3 tools have the
    statuses of the S2 exit baseline (`test_bench_baseline.py`).
  - `results/s3/exit.json` (from `scripts/s3/exit.py`; drift test
    `harness/tests/test_s3_exit.py`). Inputs: the new baseline, the S1
    summary, the T18 record, and the T14 record. Each value is copied (file
    and key; a key part in brackets selects a list item by its fields) or
    derived (a formula). The script fails closed if the baseline is not a
    full clean baseline of all tools (the check of `bench/baseline.py`) or
    if the S1 summary has another sqll version.
  - G3.5 (start and parse): sqll is faster than sqruff on 108 of 108 pairs,
    median ratio 0.506, at most 0.707 (parse/clickhouse/large); all 108 are
    below the T14 target 0.794. Sums: start 0.328, parse 0.550, both 0.522.
    G3.4: faster than sqlfluff on 112 of 112 (at most 0.033).
  - Lint and fix: 168 sqll results unsupported (no run); thus G3.4 and G3.5
    on lint and fix and the G3.5 total are for later stones.

## Speed result (T17)

- The T14 method on the T17 code (`results/s3/speed/T17.json`, target m = 0.26 of T14): 108 of 108 start and parse benchmarks below the target, in each of the 5 sessions (largest ratio 0.751). Controlled session: median ratio to sqruff 0.513, at most 0.718 (parse/db2/large). Above the target: none.
- The 4 soql benchmarks (no sqruff pair): sqll/sqlfluff at most 0.028 (`T17-soql.json`).
- Thus T17b and T17c are not needed.

## Native tests of the base (T18)

- The base: 162 of 162 tests pass (`results/s3/base-native-tests.json`). sqll has a port of each test; the CI list check (`scripts/s3/base_native_tests.py check`) fails if a base test that passes in the base does not pass in sqll.
- The rules CP01, CP03, and CP04 are a library with 3 new tests (the output of sqlfluff 4.4.0 fix). `sqll lint` stays unsupported until S5.

## S3 phase A data

- T2: [`results/s3/s1-by-base.json`](s1-by-base.json) (from
  `scripts/s3/s1_by_base.py`): the S1 results of each base by suite,
  dialect, rule, and case group. sqruff: a new local run of the 4 suites
  (harness commit `f5841a3`, per-case list `results/s3/sqruff-cases.json`)
  agrees with the S1 summary and `known_failures/sqruff.txt`. sqruff exact
  trees by dialect: from 0 of 103 (oracle) and 0 of 3 (soql: no dialect)
  to 17 of 17 (flink). 42 of 82 rule groups pass all their cases.
  sqlfluff-rs passes all cases, but Python sqlfluff drives its generated
  parser. Option 3 has no data.
- T3: [`results/s3/sqruff-tree-diffs.json`](sqruff-tree-diffs.json)
  (from `scripts/s3/sqruff_trees.py`): the classes of the 763 sqruff tree
  mismatches (758 dialect cases, 5 templater cases). Inputs: the hunks of a
  new sqruff run (`results/s3/sqruff-tree-hunks.json`) and the hand check
  (`results/s3/sqruff-tree-handcheck.json`). The cases agree with T2 and
  `known_failures/sqruff.txt`. Each case has a class. A group is a class
  and its segment types. An unparsable group also has the dialect and the
  sqlfluff segment where sqruff fails: 593 groups. The cases that the top
  groups cover fully: top 10 groups: 162 (21.2%), top 20 groups: 188
  (24.6%), top 50 groups: 265 (34.7%). Groups with equal counts are ranked
  by key. With another order of these groups: top 10: 162 to 166, top 20:
  188, top 50: 261 to 268 (`tie_range` in the JSON). 230 cases need a fix
  that no other case needs. Limit: a group key is a proxy for the cause. The numbers change
  with the key: with one unparsable group for each case, 255 cases need a
  fix of their own (`unparsable_key_sensitivity` in the JSON). Hand check:
  60 of 60 cases agree; the author of the classifier did it.

| Class | Cases | Only this class | Dialects |
|---|---|---|---|
| unsupported_dialect | 3 | 3 | 1 |
| unparsable | 139 | 99 | 19 |
| leaf_text | 13 | 0 | 1 |
| token_split | 25 | 4 | 1 |
| nesting | 17 | 0 | 5 |
| missing_wrapper | 183 | 44 | 18 |
| extra_wrapper | 359 | 156 | 24 |
| renamed | 316 | 156 | 21 |
| keyword_vs_identifier | 37 | 1 | 10 |
| leaf_type | 137 | 20 | 18 |
| non_code_placement | 0 | 0 | 0 |
| meta | 5 | 5 | 1 |
| other | 0 | 0 | 0 |

- T4: [`results/s3/sqruff-rule-diffs.json`](sqruff-rule-diffs.json)
  (from `scripts/s3/sqruff_rules.py`): the classes of the 373 sqruff rule,
  autofix, and templater failures, and the coupling of the sqruff rules to
  tree shapes. Inputs: `results/s3/sqruff-rule-parses.json` (a new sqruff
  and sqlfluff parse of the SQL of each failure, with the case config and
  the meta segments) and `results/s3/sqruff-rule-types.json` (names only:
  the segment types that the source of each sqruff 0.41.0 rule names, and
  the types of the sqlfluff 4.4.0 grammar). Each failure has one class:
  `unsupported_item` (from the reason), else `parse_cause` (a file that a
  failed check reads has another tree in sqruff), else `rule_logic`.
  `rule_logic` has 5 config value panics (LT14 and RF05: sqruff panics on a
  `None` or `none` setting value before a rule runs). If they are
  unsupported items, the class counts are 185, 69, and 119. The sqruff
  meta type `implicit` is `indent` in sqlfluff. If it counts as a
  difference, there are 168 parse_cause cases (`sensitivity` in the JSON).
  A tree difference does not prove the cause. Estimate: of the 63
  parse_cause cases of rules and autofix, 27 have no tree or an unparsable
  node, 28 change a type that the rule reads, and 8 change no such type.
  `by_rule` counts by the rule list of a case; `by_rule_code` counts by
  each rule code. Coupling: the rules read 188 type names. 8 are not in
  the sqlfluff 4.4.0 grammar and 54 are in a T3 rename group (an upper
  bound: a rename key gives both types). 66 of 77 rules read a name that
  differs. Estimate: 75 of 77 rules see a changed tree if sqruff gives
  sqlfluff trees (not CV09, JJ01). The T3 dialect trees are code_only, so
  a change of a non-code or meta type (whitespace, newline, comments,
  indent, dedent) shows only in the T4 parses of the failed cases. 48
  rules read such a type; for these types, the changed tree count is a
  lower bound. The base
  segment module (`parser/segments.rs`) is not a helper module; with its
  names, 74 of 77 rules read a name that differs and 76 see a changed tree
  (`sensitivity_base_module`). Estimate: the names of the helper modules
  come from the `use` items, not from the calls.

| Suite | Failures | unsupported_item | parse_cause | rule_logic |
|---|---|---|---|---|
| rules | 342 | 165 | 62 | 115 |
| autofix | 16 | 6 | 1 | 9 |
| templater | 15 | 9 | 6 | 0 |
| all | 373 | 180 | 69 | 124 |

- T5: [`results/s3/sqlfluffrs-probe.json`](sqlfluffrs-probe.json)
  (from `scripts/s3/sqlfluffrs_probe.py`). Inputs: the records of the build
  (`results/s3/sqlfluffrs-probe-build.json`), the fixture check
  (`results/s3/sqlfluffrs-probe-cases.json`), and the timing session
  (`results/s3/sqlfluffrs-probe-bench.json`). Each record has its commands
  with their exit codes ($SCRATCH and $REPO for the paths). The probe
  `scripts/s3/probe-sqlfluffrs/` is research code, not sqll: it lexes and
  parses one file with the sqlfluffrs 4.4.0 crates and prints the record of
  `sqlfluff parse -f json`.
  - Build: in a scratch copy of the submodule (`git archive`), not in the
    submodule; `scripts/check-submodule` passes before and after. The pinned
    sqlfluff 4.4.0 (tool venv) generates the dialect tables:
    `utils/rustify.py build`, 23 s, 85 files, 414352 lines.
    `rustify.py check` passes with the PyPI package and with the submodule
    src. Rust 1.96.1 (`rust-toolchain.toml`). The lexer, parser, dialects,
    and rules crates build in 76 s, the probe in 80 s (release, 4 CPUs).
    Probe binary: 18.1 MB. Lines: 27123 hand-written, 414352 generated (all
    in `sqlfluffrs_dialects`).
  - No Python: the crates have no python feature, and `cargo tree` has no
    pyo3 (the control with the python feature has it). During cargo, Python
    commands on PATH fail and record each call: 0 calls. Shared libraries
    (readelf): libc, libgcc_s, and the loader only. The probe runs in the pinned Rust image of the CI, which
    has no Python. Thus Python is needed only to generate the tables.
  - Native fixture tests (`tests/fixture_tests.rs`): 60 of 60 pass. They
    check only that each parse has no error and the top-level shape.
    Exact trees (the S1 dialect check with the harness compare code):
    **2306 of 2306** dialect cases pass, in all 28 dialects. The harness
    filter on the full tree (as for sqruff) gives the same.
  - Speed: one session under the machine lock, the CI image in docker,
    serial, the harness timer and validity checks, full profile. The session
    started on an idle machine, and its load average shows no other work.
    The sqlfluff and sqruff times agree with the S2 baseline (median ratio
    1.03). Each value is a ratio of median wall times (probe / other
    tool); below 1, the probe is faster. sqruff has no soql. The parse share
    is from the probe phases (`--timings`); the rest is mostly the setup of
    the lazy dialect tables (start: 0.68), the lexer, and the record.

| Group | Benchmarks | Probe / sqruff, median | Probe faster than sqruff | Probe / sqruff, sum | Probe / sqlfluff, median | Parse share of the probe phases |
|---|---|---|---|---|---|---|
| start | 28 | 0.620 | 27 of 27 | 0.588 | 0.018 | 0.30 |
| parse/small | 28 | 0.761 | 24 of 27 | 0.732 | 0.025 | 0.49 |
| parse/medium | 28 | 1.034 | 12 of 27 | 1.054 | 0.040 | 0.59 |
| parse/large | 28 | 1.505 | 1 of 27 | 1.505 | 0.079 | 0.67 |
| all | 112 | 0.878 | 64 of 108 | 1.182 | 0.032 | 0.63 |

  - Generator: `rustify.py` lists the dialects and runs, for each dialect,
    `build_dialect.py`, `build_lexers.py`, and `build_parsers.py` in a new
    Python process. They load the dialect objects of the installed sqlfluff
    (`dialect_selector`), read the grammar objects of the dialect
    `_library` (20 grammar and segment classes, 11 private attributes), and
    write Rust statics: the `sqlfluffrs_types` grammar tables and the lexer
    matchers. An unknown grammar class fails the generation. No dialect file
    has its own match code. Judgement: option 3 can reuse the generator,
    with its table format (a new engine) or with a new emitter (178 of the
    1606 lines of its table builder). The new engine must give the meaning
    that `sqlfluffrs_parser` gives to the tables. Risk: the private
    attributes tie it to the sqlfluff version; the pin limits this.

- T6: [`results/s3/speed-by-base.json`](speed-by-base.json)
  (from `scripts/s3/speed_by_base.py`; no new timing run). Inputs:
  `results/s2/baseline.json` and `results/s3/sqlfluffrs-probe.json`. For
  each base and each of the 280 benchmarks: the time, the ratios to
  sqlfluff and to sqruff, and the G3 result. Each time is copied (`from`
  names the file) or is an estimate (`formula` names its formula in the
  JSON). Pairs: only benchmarks where sqruff is valid (`harness/bench.md`).
  No noise limit.
  - Option 1, sqruff: measured. 64 results are not valid, thus they fail
    G3.4: rule codes that are not those of sqlfluff 46, unsupported (soql)
    10, panic 7, timeout 1.
  - Option 2, sqlfluffrs: start and parse measured (T5). Lint and fix:
    estimates (`rule_time`): the sqruff time with its parse part replaced
    by that of the probe. Thus G3.5 on lint and fix follows parse.
  - Option 3: estimates. High bound: the probe time. Low bound: the probe
    time minus its setup phase. Lint and fix as option 2.
  - Sensitivity (`unscaled`) gives lint and fix totals of 1.0478 and
    1.0178 (option 2), 1.0078 and 0.9999 (option 3 low). Thus a total near 1 depends on the formula.
  - Distance: on the parse benchmarks that are slower than sqruff, lex and
    parse must be faster by a median factor of 1.75 and at most 3.82
    (option 2), or 1.58 and 3.44 (option 3 low).

| Base (280 benchmarks) | Faster than sqlfluff | Not faster or not valid | Unknown (no estimate) | Slower than sqruff (of pairs) |
|---|---|---|---|---|
| 1 sqruff | 216 | 64 | 0 | 0 of 216 |
| 2 sqlfluffrs | 220 | 0 | 60 | 94 of 216 |
| 3 low | 220 | 0 | 60 | 67 of 216 |
| 3 high | 220 | 0 | 60 | 94 of 216 |

Ratio to sqruff of the sums over the pairs (G3.5 needs below 1). "all" is
an estimate for options 2 and 3 (formula `total_all`).

| Base | start | parse | lint | fix | all |
|---|---|---|---|---|---|
| 1 sqruff | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| 2 sqlfluffrs | 0.588 | 1.267 | 1.078 | 1.029 | 1.069 |
| 3 low | 0.326 | 1.153 | 1.036 | 1.010 | 1.026 |
| 3 high | 0.588 | 1.267 | 1.078 | 1.029 | 1.069 |

- T7: [`results/s3/license-size.json`](license-size.json)
  (from `scripts/s3/license_size.py`; input
  `results/s3/license-size-sources.json`). The JSON has the license texts,
  the duties (paraphrases; the MIT condition is an exact quote), and the
  open questions for a human. The sqll repository has no license file.
  - Option 1, sqruff: Apache-2.0, `LICENSE` at tag `v0.41.0` (the commit
    of each crate), "Copyright 2024 Quary Inc.". The published crates have
    no license file. No NOTICE file. The crates carry no sqlfluff MIT
    notice, but a regex search found 62 comment lines that name sqlfluff as
    a source, and 2041 test files are byte-equal to sqlfluff 4.4.0
    fixtures. The port commit (`.sqlfluff-sha`) is 124 commits before the
    pin.
  - Option 2, sqlfluffrs: MIT, `sqlfluffrs/LICENSE.md` (the text of the
    sqlfluff `LICENSE.md`), "Copyright (c) 2018-2026 Alan Cruickshank".
  - Option 3: the input is the sqlfluff 4.4.0 dialects (MIT).

Dependencies (`cargo tree -e normal,build --target all`; licenses from
`cargo metadata`). No package is copyleft or unknown. The generator venv of
options 2 and 3 (build time only) has 2 weak-copyleft packages (MPL-2.0).

| Base | Profile | Packages | OR choice with a copyleft option |
|---|---|---|---|
| 1 sqruff | installed (parser, python) | 113 packages | configparser |
| 2 sqlfluffrs | standalone (T5 probe crates) | 54 packages | r-efi |

Lines (`line_count` of `scripts/s3/sqlfluffrs_probe.py`, all lines of each
`.rs` file). Generated: for sqruff, a mark such as "auto-generated" in the
first 3 lines (only `mariadb_keywords.rs`; the other keyword lists count as
hand-written); for sqlfluffrs, the tables that `utils/rustify.py` writes.

| Base | Hand-written | Generated |
|---|---|---|
| 1 sqruff (6 crates) | 176917 hand-written | 705 |
| 2 sqlfluffrs (8 crates) | 27123 hand-written | 414352 |
| 3 new parser (estimate) | 19464 engine and 18655 rules | 414352 |

Structure: sqruff dialects are hand-written Rust; its 77 rules read the
tree through the typed `SyntaxKind` enum. sqlfluffrs dialects are generated
tables; its 3 rules read the parse `Arena` by type strings.

- T8: [`results/s3/capabilities.json`](capabilities.json)
  (from `scripts/s3/capabilities.py`). Inputs:
  `results/s3/capabilities-sources.json` (each help command of sqlfluff
  4.4.0 and sqruff 0.41.0 with its output; the click objects, templaters,
  placeholder styles, and default config of the pinned sqlfluff; the cited
  lines of the sqruff 0.41.0 crates) and `results/s3/capabilities-start.json`
  (a start session in the CI image). The sqlfluff and sqlfluffrs facts come
  from the submodule. Each entry cites a command, a source file with its
  sha256 and lines, or a result. A judgement has `estimate` and its reason.
  The option lists are parsed from the recorded help text; for sqlfluff the
  parse must agree with the click objects.
  - S6: the sqruff Jinja, Python, dbt, and sqlmesh templaters run in Python
    (pyo3); only raw and placeholder are native. sqlfluffrs has no
    templater, only the source map (`TemplatedFile`; the lexer also takes
    it). The templater suite is all Jinja: sqruff passes 28 of 43 (27 of
    the 40 cases that do not need Python) with Jinja in Python. sqruff has
    11 of the 12 sqlfluff placeholder styles with the same regex
    (`colon_optional_quotes` differs) and 2 more.
  - S7: sqruff has 5 of the 8 sqlfluff commands (no `format`, `render`,
    `version`) and 42 of the 97 option names of the 5 shared commands.
    Config files: sqruff reads `.sqlfluff` and `pyproject.toml`, not
    `setup.cfg`, `tox.ini`, or `pep8.ini`. 197 of the 208 sqlfluff default
    keys are in the sqruff defaults. 122 S1 cases fail with an unsupported
    setting; the largest groups: `layout.type.*.align_within` (39) and
    `rules.layout.newlines.minimum_empty_lines_between_statements` (32).
    sqlfluffrs has no CLI and no config reader.
  - G2 and S8: sqruff trees have the `SyntaxKind` enum (1359 kinds);
    sqlfluffrs trees have type strings. No base has a typed node view or a
    schema output (estimate). One parse for lint and code generation is
    possible in each base (estimate).
  - G3 start (session in the CI image, 20 runs of each series; another host
    than the S2 baseline: the times are 1.629 (sqlfluff) and 1.452 (sqruff)
    of S2, so only ratios inside the session count). sqlfluff start: Python
    0.035, the import of the CLI 0.464, the rest (config, dialect, parse,
    output, all in Python) 0.501. sqruff start is native; the process start
    and the loader are 0.184 of it, and it links `libpython3.13` (the
    `python` feature). The T5 probe start is 0.62 of sqruff, 0.68 of it the
    setup of the dialect tables.

| T8 | 1 sqruff | 2 sqlfluffrs | 3 new parser (estimate) |
|---|---|---|---|
| Native templaters | raw, placeholder | none (estimate) | none |
| Templaters through Python | jinja, python, dbt, sqlmesh | none (estimate) | none |
| sqlfluff commands, option names | 5 of 8; 42 of 97 | no CLI | no CLI |
| Default config keys of sqlfluff | 197 of 208 | 4 fields (estimate) | none |
| Segment type of the tree | `SyntaxKind` enum | string | enum from the generator |
| Start cause | native | native | native |

- T9: [`results/s3/decision-data.json`](decision-data.json)
  (from `scripts/s3/decision_data.py`). Inputs: `results/s1/summary.json`
  and the T2 to T8 outputs. Each value of the decision record is copied
  (file and key), derived (a formula), or an estimate (a formula and the
  reason). The script also makes the tables of the record. The test
  `harness/tests/test_s3_decision_data.py` checks that the record has these
  tables and no number that is not a value of the file. Recommendation:
  option 2, sqlfluffrs. Main risks: parse speed (G3.5) and the rule work
  (S5).

## Speed checkpoint (T16b)

- **No-go: human decision needed.** The T14 method again on the T16 code (`results/s3/speed/T16b.json`); by the Stop rule, the S3 track stopped. The human owner decided on 2026-11-01 (below): T17.
- m: T14 0.26, T16b 0.44 (the noise of 5 sessions; the target keeps m = 0.26). Below the target: T14 41 of 108, T16b 71 of 108.
- Worst needed factor: T14 2.63 (parse/ansi/large), T16b 1.53 (parse/hive/large). Central estimate in reach: T14 78 of 108, T16b 104 of 108.
- Not in reach: parse/large of ansi, db2, hive, and teradata (needed 1.37 to 1.53, estimate 1.34 to 1.35); with m = 0, the estimate reaches 108 of 108.
- What remains for T17: the parser's own code (46% to 49% of the parse instructions, no estimate) and the parse allocation and copy (48% to 49%). The human owner chose T17, not option 3 of the decision record.

## S3 phase A tasks

| Task | Description | State |
|---|---|---|
| T1 | STATUS and the method of the decision record | Merged (PR #22) |
| T2 | S1 results by base, per suite and per dialect | Merged (PR #23) |
| T3 | Classes of the sqruff parse tree mismatches | Merged (PR #25) |
| T4 | Classes of the sqruff rule, autofix, and templater failures; rule coupling to tree shapes | Merged (PR #27) |
| T5 | sqlfluffrs standalone probe: build without Python, native parse, generator reuse | Merged (PR #30) |
| T6 | Speed by base and distance to the G3 targets (needs T5) | Merged (PR #32) |
| T7 | License, attribution duties, code size, and structure of each base | Merged (PR #37) |
| T8 | Capabilities for S6, S7, and G2 of each base | Merged (PR #40) |
| T9 | Decision record: data, work estimates, recommendation, and STATUS | Merged (PR #42) |
