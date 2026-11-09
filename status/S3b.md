# S3b status (Core track)

S3b (STONES.md) is in work in the Core track. S3 is approved (human
owner, 2026-11-06). The plan: one pull request for each task, C3 to C17.
The S3 code paths are Core paths since C3 (`tracks.yml`).
The design of C6 to C16 is in the C4 record
[docs/decisions/s3b-core.md](../docs/decisions/s3b-core.md). It adds
these details to the task list: a kind is the full static data of a node
(C6), C6 makes the crate `sqll_interfaces`, C7 makes the crate
`sqll_syntax` (the conversion; C9 adds `parse`), C8 makes the crate
`sqll_source`, C13 makes the crate `sqll_cli`, and C16 gives
`docs/decisions/s3b-*.md` to Core. C8 changed the C4 design (C8 task
text; the record has the change in Q2 and Q5): the raw templater is in
the S6 package `sqll_templater`, not in `sqll_source` (Core owns
`crates/**` until C16). The interface documents are in
`docs/interfaces/` (a Core path since C6).

## Tasks

| Task | Description | State |
|---|---|---|
| C1 | Record the S3 approval and the standing delegation; freeze the inputs of the S3 exit record | Merged (PR #57) |
| C2 | `bench compare`: a table for each benchmark when it compares tools of one report | Merged (PR #58) |
| C3 | Record the S3b plan and move the S3 code paths to the Core track | Merged (PR #59) |
| C4 | Decision record: the S3b core design (answers to the 7 open interface questions): [docs/decisions/s3b-core.md](../docs/decisions/s3b-core.md) | Merged (PR #61) |
| C5 | Speed check tool for each Core change (G3.6): `scripts/speed-check`, `results/S3b/speed/C5.json` | Merged (PR #63) |
| C6 | Typed segment kinds from the frozen dialect tables: one kind for each distinct static data of a node (variant, class, type, instance types, class types, segment kwargs); the build fails if the kinds do not fit in a `u16`: [docs/interfaces/segment-kinds.md](../docs/interfaces/segment-kinds.md) | Merged (PR #64) |
| C7 | Lossless syntax tree (`sqll_tree`) and the conversion from the parser tree (`sqll_syntax::from_node`): [docs/interfaces/tree.md](../docs/interfaces/tree.md) | Merged (PR #65) |
| C8 | Source map (`sqll_source`): `TemplatedFile` as the frozen templater interface, raw templater (`sqll_templater`), source ranges of the tree. Fix of the C7 finding: the newline index of the ported `TemplatedFile` has code point offsets: [docs/interfaces/source-map.md](../docs/interfaces/source-map.md) | Merged (PR #66) |
| C9 | Frozen parse interface (lexer to parser to tree; `sqll_syntax::parse`) and `sqll parse` output from `SyntaxTree`. The copy of the parse settings in `crates/sqll_interfaces/src/parse.rs` is gone: the tests use the steps of the interface. The lexer input is a `TemplatedFile` (C8). The caller changes "\r\n" and "\r" to "\n" before the templater, as sqlfluff (`Linter.render_string`); `sqll parse` does it when it reads the file: [docs/interfaces/parse.md](../docs/interfaces/parse.md) | Merged (PR #67) |
| C10 | Typed view of the tree (`sqll_tree::view`): `NodeRef`, the sqlfluff query helpers (`child`, `children_of`, `first_descendant`, `crawl` as `recursive_crawl`), `AstNode`, `typed_node!`, and the typed nodes of the core set. Fix of C6: the meta kinds have the class types of their sqlfluff class: [docs/interfaces/typed-view.md](../docs/interfaces/typed-view.md) | Merged (PR #68) |
| C11 | Config skeleton (`sqll_config`) and its use in `sqll parse`: the config model, the sqlfluff defaults, the reader of the config files in the sqlfluff order, `--config`, `--ignore-local-config`, and the overrides; a setting that sqll cannot do fails closed: [docs/interfaces/config.md](../docs/interfaces/config.md) | Merged (PR #69) |
| C12 | Rule and fix interface (`sqll_lint`) with CP01, CP03, CP04 as the proof: the `Rule` trait, the lint results and fixes (source edits through the source map; a fix in a templated range is refused), the fix loop, and the rule registry. CP01, CP03, CP04 of `sqll_rules` implement it: [docs/interfaces/rules.md](../docs/interfaces/rules.md) | Merged (PR #71) |
| C13 | CLI skeleton (`sqll_cli`): lint, fix, rules, dialects, and the output formats; `EXIT_ERROR` is in `crates/sqll_cli/src/lib.rs` (`scripts/s3b/core_design.py` reads it there): [harness/sqll.md](../harness/sqll.md) | Merged (PR #72) |
| C14 | Harness adapters: `sqll lint` and `fix` in the S1 harness and the S2 benchmarks; the jinja as raw record (`results/S3b/C14-jinja-raw.json`); the oracle check of each sqll pass (`--passes-of sqll`). The path for a base binary from before C11 in `harness/sqll_harness/bench/sqll.py` is removed: [harness/sqll.md](../harness/sqll.md), "Adapter" | In review |
| C15 | Code generation interface: tree to schema | Not started |
| C16 | Package ownership of the later tracks and the interface index; `docs/decisions/s3b-*.md` to the Core paths | Not started |
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

## C7: syntax tree proof and conversion cost

Interface: [docs/interfaces/tree.md](../docs/interfaces/tree.md). The test
output (`crates/sqll_interfaces/tests/tree.rs`, with `--nocapture`):

```text
tree: 2306 of 2306 dialect fixtures: lossless and node for node equal (685224 nodes: 432300 raw, 182196 segment, 70728 meta, 0 unparsable; 685224 with a position, 5938 with another ported line position; 1468552 bytes, 57623 lines)
tree: 84 of 84 S2 parse inputs: lossless and node for node equal (280339 nodes: 183383 raw, 71856 segment, 25100 meta, 0 unparsable; 280339 with a position, 5737 with another ported line position; 601133 bytes, 22766 lines)
```

"Another ported line position": the ported `get_line_pos_of_char_pos` of
`TemplatedFile` gave another line position after a multi-byte character.
C8 fixed it; now the test fails if the ported line position is another
one (C8 section).

The conversion cost (`scripts/s3b/tree_check.py measure`, record
[results/S3b/C7-conversion.json](../results/S3b/C7-conversion.json); the
sqll allocator and release profile, the median of 21 runs, with the
machine lock). The conversion includes the copy of the text and the kind
lookup (with a cache for each conversion). C9 uses these numbers in its
speed plan:

| Item | Value |
|---|---|
| Inputs | 28 large S2 parse inputs, 458473 bytes, 215024 nodes |
| Conversion time / parse time | 4.1% (for each input: min 2.6%, median 4.2%, max 5.6%) |
| Conversion time / (lex + parse) time | 3.6% |
| Conversion time for each node | 121.6 ns |
| Conversion heap bytes / parse heap bytes | 0.7% |
| Conversion peak / parse peak | 2.5% |
| SyntaxTree bytes / live bytes that the parse keeps (the Node tree) | 4.0% |

The sqll binary does not link `sqll_tree` or `sqll_syntax` (`cargo tree -p
sqll -e normal,build`), so C7 has no speed check (G3 rule above).

## C8: source map proof

Interface: [docs/interfaces/source-map.md](../docs/interfaces/source-map.md).
The sqlfluff data: `scripts/s3b/source_map_oracle.py` (record
[results/S3b/C8-source-map.json](../results/S3b/C8-source-map.json);
`check` in the CI job build). The test output (with `--nocapture`):

```text
source map: 20000 of 20000 random files: as sqlfluff (211080 ranges, 17415 of them ValueError; 193773 source offsets)
source map: 54 of 54 templater fixtures: as sqlfluff (776608 ranges, 1345 of them ValueError; 6711 source offsets; 3121 segments, 4 of them with a wider templated slice)
source map: 3 of 3 recorded fixtures: as sqlfluff (1678 ranges, 15 of them ValueError; 212 source offsets; 96 segments, 0 of them with a wider templated slice)
tree: 2306 of 2306 dialect fixtures: lossless and node for node equal (685224 nodes: 432300 raw, 182196 segment, 70728 meta, 0 unparsable; 685224 with a position, 0 with another source range; 1468552 bytes, 57623 lines)
tree: 2306 of 2306 dialect fixtures through the raw templater: lossless and node for node equal (685224 nodes: 432300 raw, 182196 segment, 70728 meta, 0 unparsable; 685224 with a position, 0 with another source range; 1468552 bytes, 57623 lines)
```

- The 54 templater fixtures (53 SQL files directly in the fixture folders
  and the subfolder case of the sqlfluff Jinja test table): the sqll lexer
  and parser give the sqlfluff tree of each templated file, segment for
  segment, with the source ranges, the literal flags, and the source
  positions of sqlfluff.
- Fixes of ported code (`crates/ported.json`; the interface document has
  the details): the newline index and `raw_slices_spanning_source_slice`
  count code points; `templated_slice_to_source_slice` does not panic for
  source slices out of order; the parser keeps the `end_of_file` of an
  empty templated text (the record has the empty file). `check` compares
  20000 random invented files (seed 8) with the pinned sqlfluff: 0
  differences. For the newline fix, the output of `sqll parse` (with and
  without `-m`) of the 2306 dialect fixtures and the 84 S2 parse inputs
  did not change (9560 runs).
- G4: S1 dialect suite of sqll 2306 of 2306 exact; the known failures of
  sqll (dialects, rules, autofix, templater) did not change; tree guard: 84
  of 84 the same; native base tests 162 of 162; the syntax tree check of
  the 84 S2 parse inputs passes.
- The sqll binary links the fixes (`sqll_types`, `sqll_parser`), but not
  `sqll_source` or `sqll_templater` (`cargo tree -p sqll -e
  normal,build`). Speed check
  ([results/S3b/speed/C8.json](../results/S3b/speed/C8.json), base
  `ee2434a356fe`, head `265e52cdc39b`): 112 benchmarks, 0 slower, 0
  failures; total wall time head / base 0.998; head faster than sqruff on
  108 of 108 pairs and faster than sqlfluff on 112 of 112.

## C9: parse interface proof

Interface: [docs/interfaces/parse.md](../docs/interfaces/parse.md). The
test output (`crates/sqll_interfaces/tests/parse.rs`, with `--nocapture`):

```text
parse: 2306 dialect fixtures, 685224 nodes
parse: 2306 of 2306 dialect fixtures: the tree of the steps
```

- `sqll parse` calls `sqll_syntax::parse` with the file of the raw
  templater; the JSON writer reads the `SyntaxTree`. The sqll binary links
  only `sqll_source`, `sqll_syntax`, `sqll_templater`, and `sqll_tree` of
  the sqll crates directly (`cargo tree -p sqll -e normal --depth 1`).
- The output did not change: the tree guard record is unchanged (84 of 84,
  2 runs each). A local run compared the binaries of base `dddab8d` and of
  C9 on the 2306 dialect fixtures, the 84 S2 parse inputs, and 9220
  invented changed fixtures (cuts, deletions, copies, and added text; many
  with lex errors and unparsable sections), each with no option, `-m`,
  `-c`, and `-c -m`: 46440 runs, 0 differences in stdout, stderr, and
  exit code, no exit code 2.
- G4: native base tests 162 of 162 (`scripts/s3/base_native_tests.py
  check`); the syntax tree check of the 84 S2 parse inputs and the source
  map check pass. The S3 hint check patch moved to the parse interface
  (cross-track, S3): `scripts/s3/hint_check.py` gives the T17 summary
  again (2390 inputs, 974128 exclusions, 0 probe matches, 0 probe limits,
  0 different runs).
- Speed check ([results/S3b/speed/C9.json](../results/S3b/speed/C9.json),
  base `dddab8dcf646`, head `5f4f1f476509`): 112 benchmarks, 0 slower, 0
  failures; total wall time head / base 1.028 (start 1.024, parse/small
  1.035, parse/medium 1.032, parse/large 1.026); head faster than sqruff
  on 108 of 108 pairs and faster than sqlfluff on 112 of 112.
- Reason of the remaining slowdown (G3.6): the conversion of the parser
  tree to the `SyntaxTree` (C7: 4.1% of the parse time) and the source map
  of the file. The writer that reads the `SyntaxTree` is faster than the
  writer of the `Node` tree.
  A cheaper hash and compare in the kind cache of the conversion gave no
  gain. The next step is a parser that builds the `SyntaxTree` with no
  `Node` tree (S4).

## C10: typed view proof

Interface: [docs/interfaces/typed-view.md](../docs/interfaces/typed-view.md).
The test output (`crates/sqll_interfaces/tests/typed_view.rs`, with
`--nocapture`) and the check of the sqlfluff data
(`scripts/s3b/crawl_oracle.py check`, record
[results/S3b/C10-crawl.json](../results/S3b/C10-crawl.json)):

```text
typed view: 135 of 135 crawl cases as sqlfluff (6 fixtures, 1182 segments; 111 cases also as the fixture YAML)
crawl check: PASS: 6 fixtures, 135 cases (111 YAML cases), 1182 segments
```

- Fix of C6: the meta kinds have the class types of their sqlfluff class
  (a dedent is also an indent). With the meta kinds of C6, the test fails.
  The type ids, the kind ids, and the kind counts did not change.
- G4: native base tests 162 of 162 (`scripts/s3/base_native_tests.py
  check`: 284 tests, 281 passed, 3 ignored); tree guard: 84 of 84 the same;
  the syntax tree check of the 84 S2 parse inputs and the source map check
  pass.
- The sqll binary links `sqll_tree` and `sqll_syntax` (the kind data and
  the conversion changed). Speed check
  ([results/S3b/speed/C10.json](../results/S3b/speed/C10.json), base
  `75f8ea231c4a`, head `b2502f889bec`): 112 benchmarks, 0 slower, 0
  failures; total wall time head / base 1.006; head faster than sqruff on
  108 of 108 pairs and faster than sqlfluff on 112 of 112.

## C11: config proof

Interface: [docs/interfaces/config.md](../docs/interfaces/config.md).
The check of the sqlfluff data (`scripts/s3b/config_oracle.py check`,
record [results/S3b/C11-config.json](../results/S3b/C11-config.json)):

```text
config check: PASS: 208 defaults, 40 coerce, 26 INI, 21 TOML, 34 load and 66 CLI scenarios; jinja as raw: 2303 of 2303 dialect fixtures that are not empty and have no Jinja delimiter
```

- `crates/sqll_config/tests/defaults.rs` reads `default_config.cfg` of the
  submodule: the 208 defaults are equal. The interface test
  (`crates/sqll_interfaces/tests/config.rs`, 6 tests) and
  `crates/sqll/tests/cli_config.rs` (4 tests) give the sqlfluff answer of
  each case (in the CLI scenarios also the warning lines of stderr), or
  fail closed where the record says so.
- `sqll parse` reads the config. The jinja templater (the default) is done
  only for a text that is not empty and has no Jinja delimiter; then
  sqlfluff gives the file of the raw templater (`jinja_as_raw`). For an
  empty text it does not (the raw templater gives an empty literal slice).
- G4: S1 dialect suite of sqll 2306 of 2306 exact; the known failures of
  sqll did not change (2631; 0 new, 0 unexpected); tree guard: 84 of 84 the
  same; the syntax tree check of the 84 S2 parse inputs passes; native base
  tests 162 of 162 (`scripts/s3/base_native_tests.py check`: 318 tests,
  315 passed, 3 ignored). Run again on the head after the review fixes
  (round 5: `ba3cb5c`, the same sqll source as the speed check head
  `9bfbed7`; the S1 suite and the known failures: CI job report on
  `ba3cb5c`, `results/s1/summary.json` is equal).
- Speed check ([results/S3b/speed/C11.json](../results/S3b/speed/C11.json),
  base `3104d473b8f1`, head `9bfbed79736e`, after the review fixes of
  round 5): 112 benchmarks, 0 slower, 0 failures; total wall time head /
  base 1.018 (start 1.082, max 1.205; parse/small 1.047, parse/medium
  1.029, parse/large 1.000); head faster than sqruff on 108 of 108 pairs and
  faster than sqlfluff on 112 of 112. The speed check also compares the
  sqll version, settings, and statuses with `results/s2/baseline.json`:
  the same.
- Reason of the start change (G3.6; no benchmark is slower than the noise
  limit): the config is in the start path. The benchmark gives the
  settings as a `--config` file (`pyproject.toml`), as for sqlfluff; sqll
  reads and checks it and makes the root and the file config (about 0.4
  ms for each start). The default table is made one time in a run
  (`default_table`).

## C12: rule interface proof

Interface: [docs/interfaces/rules.md](../docs/interfaces/rules.md). The
check of the sqlfluff data (`scripts/s3b/rules_oracle.py check`, record
[results/S3b/C12-rules.json](../results/S3b/C12-rules.json)) and the
test output (`crates/sqll_rules/tests/fixtures.rs`, with `--nocapture`):

```text
rules check: PASS: 79 rules, 37 validated config keywords, 51 rule fixture cases
rule fixtures (CP01, CP03, CP04), config: 25 passed, 0 failed, 7 unsupported, 0 not run
rule fixtures (CP01, CP03, CP04), default: 13 passed, 0 failed, 0 unsupported, 0 not run
rule fixtures (CP01, CP03, CP04), jinja: 0 passed, 0 failed, 0 unsupported, 6 not run
```

- The cases are read from the submodule. "default": only the raw
  templater and the default config (13 of 13 pass). "config": a rule
  setting or a dialect; the 7 unsupported cases set `ignore_words_regex`
  (fail closed). "jinja": a Jinja delimiter; not run (S11). A case passes
  if the `rules__test_helper` checks pass and each violation (code, lines,
  positions, description, fixable) and fixed text is that of sqlfluff.
- The 12 cases of `crates/sqll_rules/tests/rules.rs` (S3 T18; now
  `tests/capitalisation.rs`) pass on the new interface, through the fix
  loop. New: 3 cases of a target with
  children (the expected texts are sqlfluff output).
- Interface test (`crates/sqll_interfaces/tests/rules.rs`, 11 tests): a
  test templater gives the C8 hand-built map of `jinja_a`; a test rule
  fixes the literal keywords through the fix loop and keeps the tags; a
  fix of the output of a tag is refused (with `ignore_templated_areas`
  false, the violation is not fixable).
- The sqll binary does not link `sqll_lint` or `sqll_rules` (`cargo tree
  -p sqll -e normal,build`: 0 lines), and C12 changes no code that it
  links. Thus C12 has no speed check (G3 rule above). C13 links it.


## C13: CLI proof

Commands: [harness/sqll.md](../harness/sqll.md), "Lint and fix". The crate
`sqll_cli` has the commands and the output formats; `crates/sqll` keeps
main, the allocator, the license text, the version, and the dispatch.

- `scripts/s3b/cli_oracle.py` records the output of sqlfluff 4.4.0 for
  144 scenarios (record
  [results/S3b/C13-cli.json](../results/S3b/C13-cli.json); `check` in the
  CI job build). `crates/sqll/tests/cli.rs` runs sqll on each: 120 give
  the same stdout, stderr, exit code, and changed files; 22 fail closed
  (`unsupported`, exit code 2; sqlfluff runs them); 2 are usage errors
  (exit code 2 for both). Each command, each format, and the exit codes
  0, 1, and 2 have scenarios. The rules table of each of the 79 sqlfluff
  rules is that of `sqlfluff rules` (the record keeps that output of the
  scenario "rules default").
- Fail closed: the default `rules = all` (79 rules) and each selection
  with a rule that sqll does not have give `unsupported: rules ...` and
  exit code 2, in `lint`, `fix`, and `rules`. An in-file config line
  (`-- sqlfluff` or `--sqlfluff`) fails closed. A file that fails closed
  stops the command after the earlier files (`fix` has written their
  fixes; harness/sqll.md, "Fail closed").
- Memory (the allocator note of S3 T17; `scripts/s3b/memory_check.py`,
  record [results/S3b/C13-memory.json](../results/S3b/C13-memory.json)):
  the peak RSS (VmHWM) of 3, 30, 300, and 3000 files in one process
  (copies of the 3 ansi S2 parse inputs; the binary of commit `bb082d7`,
  as in the speed check): lint 26.1 to 27.0 MiB, fix 27.5 to
  28.5 MiB (3000 / 300 files: 1.015 and 1.023). The allocator
  needs no change: the free lists give the blocks of a file to the next
  file. The json format keeps the output of each file until the end
  (214 MiB for 3000 files; `stdout_bytes` 131437810). Core issue #38 is
  not needed: VmHWM is read from `/proc`.
- G4: `cargo test --workspace --locked` passes; tree guard: 84 of 84 the
  same (local, 2 runs each). The S1 suites, the native base tests, and
  the bench check: CI on the pull request.
- Speed check ([results/S3b/speed/C13.json](../results/S3b/speed/C13.json),
  base `0b57b6cddabe`, head `bb082d76f4b0`, after the review fixes of
  round 5): 112 benchmarks, 0 slower, 0 failures; total wall time head /
  base 0.9914 (start 1.0136, parse/small 1.0005, parse/medium 0.997,
  parse/large 0.9846); head faster than sqruff on 108 of 108 pairs and
  faster than sqlfluff on 112 of 112. No benchmark is slower than the
  noise limit (harness/bench.md, "Slowdowns"), so G3.6 needs no reason.
  The start total (1.0136) is likely from the size of the binary: it
  links the lint and fix code and is 3.9% larger (16666152 to 17313664
  bytes).
- The review fixes of round 6 (after `bb082d7`) change only the Ctrl-C
  or Ctrl-D answer of `fix --check`, the visibility of 2 functions of
  `sqll_config`, and the format of 2 lines. They do not change the code
  that `parse`, `lint`, or `fix` run on a file, so the memory and speed
  records stay.

## C14: harness adapter proof

Adapter: [harness/sqll.md](../harness/sqll.md), "Adapter" and "Benchmark
adapter". The jinja as raw check (`scripts/s3b/jinja_raw_oracle.py check`,
record [results/S3b/C14-jinja-raw.json](../results/S3b/C14-jinja-raw.json)):

```text
jinja as raw check: PASS: 3422 inputs (3361 rule, 61 autofix), 3178 equal (2522 texts), 244 with a Jinja delimiter, 0 notes
```

- S1 results of sqll (local run of the 4 suites, `sqll-harness run --tool
  sqll`; `results/s1/summary.json`): dialects 2306 of 2306 exact; rules 38
  of 2527 pass (CP01, CP03, CP04; 24 with a fix check), autofix 0 of 61,
  templater 0 of 43. The parity number is 2344 of 4937 (was 2306). Each of
  the 2593 other cases is `unsupported` (`known_failures/sqll.txt`, was
  2631): rules `rule` 2476, `setting` 7 (`ignore_words_regex`), `templater`
  6 (a Jinja tag); autofix `rule` 36, `setting` 4, `templater` 21;
  templater 43 `templater`. 0 new failures, 0 unexpected passes. No autofix
  case gets a fix from sqll: the adapter stops 54 before `sqll fix` (a rule
  that sqll does not have, or a Jinja tag or setting), and sqll refuses 7 (the
  default rule set in 3, a setting in 4). Each autofix case also needs
  `sqll fix --show-lint-violations` (the second run of the suite), so
  autofix stays at 0 of 61 until the S7 sqll part (CLI parity) adds this
  option.
- CI run 42536058890 (head `c0e8c75`, all jobs pass): the report job gives
  the same summary (`results/s1/summary.json is equal to the summary`), so
  the known-failure check has 0 new failures and 0 unexpected passes. The
  sqll rule and autofix cases that run and pass: rules 38, autofix 0.
- Each sqll pass is a pass of the sqlfluff test. In the CI report job, the
  oracles with `--passes-of sqll` give `sqll rules: 2527 cases, 38 pass, 38
  of them pass in the oracle`, `sqll autofix: 61 cases, 0 pass, 0 of them
  pass in the oracle`, and `sqll templater: 43 cases, 0 pass, 0 of them pass
  in the oracle`. The job dialect-oracle (sqlfluff) gives `sqll dialects:
  2306 cases, 2306 pass, 2306 of them pass in the oracle`.
- CI run 42536058890 also passes the S2 smoke bench check against
  `results/s2/baseline.json`, the build job (the tree guard, the native base
  tests, and the jinja as raw check), and the S1 dialect suite of sqll
  (2306 of 2306).
- S2: `lint` and `fix` of sqll are `unsupported: rule ...` with no run (the
  settings select all rules), so the statuses of
  `results/s2/baseline.json` do not change.
- C14 changes no file under `crates/` (no code of the sqll binary), so it
  has no speed check (G3 rule above), and the tree guard and the native
  base tests are those of C13.
