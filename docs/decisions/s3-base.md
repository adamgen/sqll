# S3 decision: the base of sqll

Status: decided. The human owner chose option 2 (sqlfluffrs) on 2026-10-29.

## Question

STONES.md, S3: which base do we use to make the sqll binary? This record
compares 3 bases with the S1 and S2 data and the data of tasks T2 to T8.

## Bases

All versions are the pinned versions. This record does not change them.

| Option | Base | Version and source |
|---|---|---|
| 1 | sqruff | sqruff `0.41.0`: the crates.io crates of the `sqruff` binary (`tools/sqruff/install.sh`, features `parser,python`). Apache-2.0. Its parser is a manual port of the sqlfluff grammar. |
| 2 | sqlfluffrs | sqlfluffrs `4.4.0`: the Rust workspace in `third_party/sqlfluff/sqlfluffrs` (submodule at sqlfluff tag `4.4.0`). MIT. Its dialect grammars are generated from the Python dialects of sqlfluff. Today it is a Python extension, not a standalone tool. |
| 3 | New parser | A new parser with a grammar generated from the sqlfluff `4.4.0` dialects (`third_party/sqlfluff/src/sqlfluff/dialects/`). No implementation exists. |

## Recommendation

**Option 2, sqlfluffrs.** The reasons are in "Reasons" below. In short: it
gives the sqlfluff trees now, without Python, and the trees are the base of
the parity number and of the rules. Its largest work is the rules (S5), the
CLI and config (S7), and parse speed (G3).

## Decision

The human owner chose option 2, sqlfluffrs, on 2026-10-29.

- Phase B (the sqll binary) starts with the parse speed work of risk 1
  ("Main risks"). The other phase B work comes after it.
- If the data of "Data that would change the recommendation" occurs, the
  S3 track does not change the base. It gives the data to the human owner,
  and the human owner decides.

## Data

Each number in this record is a value of
[`results/s3/decision-data.json`](../../results/s3/decision-data.json) (from
`scripts/s3/decision_data.py`). Each value names its file and key in a T2 to
T8 file or in the S1 summary, or it is a formula over such values. The
record labels each estimate.

### C1. S1 results by base

| Base | Dialects: exact tree | Dialects: no unparsable | Rule cases | Autofix | Templater | How it runs |
|---|---|---|---|---|---|---|
| sqlfluff 4.4.0 (reference) | 2306 of 2306 | 2306 of 2306 | 2527 of 2527 | 61 of 61 | 43 of 43 | Python |
| 1 sqruff | 1548 of 2306 | 2164 of 2306 | 2185 of 2527 | 45 of 61 | 28 of 43 | native; Jinja in Python |
| 2 sqlfluffrs in S1 (`sqlfluff-rs`) | 2306 of 2306 | 2306 of 2306 | 2527 of 2527 | 61 of 61 | 43 of 43 | Python sqlfluff calls the Rust parser; 76 of 79 rules in Python |
| 2 sqlfluffrs native (T5 probe) | 2306 of 2306 | 2306 of 2306 | no data | no data | no data | native, no Python |
| 3 new parser | no data | no data | no data | no data | no data | no implementation |

sqruff gives all trees exact in 1 of 28 dialects (flink); the lowest is
oracle with 0 of 103. sqruff has 77 of the 79 rule codes of the fixtures
(not CV13, TQ01). In S1, Python sqlfluff drives sqlfluffrs, so S1 does not
show a standalone sqlfluffrs. The T5 probe does: a native binary gives 2306
of 2306 exact trees. sqlfluffrs has 3 Rust rules (CP01, CP03, CP04); they
give only violations.

### C2 and C3. sqruff failures and the rule coupling

| sqruff failures | Cases | Classes (T3, T4) |
|---|---|---|
| Tree mismatches (dialects, templater) | 763 | extra_wrapper 359, renamed 316, missing_wrapper 183, unparsable 139, leaf_type 137 (a case can have more than one class) |
| Rule, autofix, and templater failures | 373 | unsupported_item 180, parse_cause 69, rule_logic 124 |

The tree mismatches are not systematic. The 593 groups (a group is a proxy
for one grammar fix) have 344 groups with one case. The top 10, 20, and 50
groups cover 21.2%, 24.6%, and 34.7% of the 763 cases. 230 cases need a fix
that no other case needs. The hand check agrees in 60 of 60 cases.

The sqruff rules read 188 segment type names. 54 are in a T3 rename group
and 8 are not in the sqlfluff grammar. 66 of 77 rules read a name that
differs. Estimate (an upper bound): if sqruff gives the sqlfluff trees, 75
of 77 rules see a changed tree (not CV09, JJ01).

### C4. Standalone build and generator (T5)

The sqlfluffrs lexer, parser, dialect, and rule crates build with 0 Python
calls and run with no libpython. Python is needed only to generate the
tables: 85 files, 414352 lines, in 23 s, with the same output each time. No
dialect has its own match code (0 files), so the tables hold the full
grammar. The generator reads 11 private sqlfluff attributes. Option 3 can
reuse the generator (T5 judgement): keep the table format, or write a new
emitter (178 of the 1606 lines of the table builder).

### C5. Speed (S2 and T6)

The table gives the ratios of the sums to sqruff, over the benchmarks where
sqruff is valid. Below 1, the base is faster. Options 2 and 3 have no rules,
so their lint and fix times are estimates (T6 formula `rule_time`).

| Base | start / sqruff | parse / sqruff | lint / sqruff | fix / sqruff | all / sqruff | Faster than sqlfluff (G3.4) | Slower than sqruff (G3.5, pairs) | Kind |
|---|---|---|---|---|---|---|---|---|
| 1 sqruff | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 216 of 280 | 0 of 216 | measured |
| 2 sqlfluffrs | 0.588 | 1.267 | 1.078 | 1.029 | 1.069 | 220 of 280 | 94 of 216 | start, parse: measured; lint, fix, all: estimate |
| 3 low | 0.326 | 1.153 | 1.036 | 1.010 | 1.026 | 220 of 280 | 67 of 216 | estimate |
| 3 high | 0.588 | 1.267 | 1.078 | 1.029 | 1.069 | 220 of 280 | 94 of 216 | estimate |

In S2, sqruff over sqlfluff has median ratios of 0.032 (start), 0.041
(parse), 0.052 (lint), and 0.058 (fix). The probe over sqlfluff has 0.018
(start) and 0.040 (parse). Thus each base is faster than sqlfluff on each
benchmark with a valid result or an estimate (G3.4). sqruff has 64 results
that are not valid. No base meets G3.5: option 1 is sqruff, so its total is
1.000 by definition. On large parse inputs the probe is faster than sqruff
in 1 of 27 (median ratio 1.505); parse is 0.67 of its phase time there. At
start, 0.68 of the probe time is the setup of the dialect tables.

### C6. License, size, and structure (T7)

| Base | License | Hand-written lines | Generated lines | Dependencies |
|---|---|---|---|---|
| 1 sqruff | Apache-2.0 | 176917 | 705 | 113 packages, all permissive |
| 2 sqlfluffrs | MIT | 27123 | 414352 | 54 packages, all permissive |
| 3 new parser | MIT (the input) | 19464 engine and 18655 rules (estimate) | 414352 (estimate) | no implementation |

Options 2 and 3 have the sqlfluff license: one MIT notice covers sqlfluff
and the generated tables. Option 1 adds the Apache-2.0 duties: give the
license, mark changed files, and keep the notices. The sqruff crates ship
2041 files that are equal to sqlfluff fixtures, but no sqlfluff MIT notice.
T7 lists 7 open legal questions for a human; sqll has no license file yet.
sqruff dialects are hand-written Rust (1615 node matchers). sqlfluffrs
dialects are generated tables that a hand-written engine of 12744 lines
reads.

### C7. Capabilities (T8)

| Item | 1 sqruff | 2 sqlfluffrs | 3 new parser |
|---|---|---|---|
| S6 native templaters (raw, placeholder, python, jinja) | 2 of 4: raw, placeholder | 0 of 4 | 0 of 4 (estimate) |
| S6, G2.3 placeholder styles of sqlfluff | 11 of 12 | 0 of 12 | 0 of 12 (estimate) |
| S7 sqlfluff commands | 5 of 8 | no CLI | no CLI |
| S7 option names of the shared commands | 42 of 97 | no CLI | no CLI |
| S7 sqlfluff config files, default keys | 2 of 5; 197 of 208 | no config reader | no config reader |
| G2 segment type | `SyntaxKind` enum (1359 kinds) | string | enum from the generator (estimate) |
| G2.2 schema output | no | no | no |

The sqruff Jinja and Python templaters need a Python runtime (pyo3). S6
counts only the cases that do not need Python, and G1.3 excludes features
that need it. Thus each base needs native Jinja and Python templaters. With
the templaters in Python, sqruff passes 27 of the 40 templater cases that do
not need Python. 122 S1 cases fail in sqruff with an unsupported setting.

## Work estimates (C8)

All cells are estimates. They count work items with the data that each cell
names; they give no time. One item can need much more work than another.

| Goal or stone | 1 sqruff | 2 sqlfluffrs | 3 new parser |
|---|---|---|---|
| S4 trees | 758 dialect cases in 593 groups; top 50 groups: 34.7% of the cases; 230 cases need their own fix; by hand in 1615 node matchers | 0 cases (2306 of 2306 native) | an engine of about 19464 lines; 2306 cases to pass; generator reuse with 0 or 178 new lines |
| S5 rules | 342 rule and 16 autofix failures; 2 rules to add (CV13, TQ01); after S4, 75 of 77 rules see a changed tree | 76 of 79 rules and the fixes; a rule layer of about 35950 lines | 79 of 79 rules and the fixes; else as option 2 |
| S6 templaters | 2 native templaters to write (jinja, python) | 4 native templaters to write; the source map exists | 4 native templaters to write; the source map of option 2 |
| S7 CLI and config | 3 commands, 55 option names, 11 default keys | 8 commands, 97 option names, 208 default keys | as option 2 |
| G2 code generation | typed node view, schema output | segment enum, typed node view, schema output | typed node view, schema output |
| G3 speed | all / sqruff 1.000 must go below 1; 64 results not valid | lex and parse faster by a median 1.75 (at most 3.82) on 44 parse benchmarks | low bound: 1.58 (at most 3.44) on 35 parse benchmarks |
| G1.2, G4 new sqlfluff version | port the grammar by hand; the port is 124 commits before the pin | generate the tables again (85 files in 23 s) | as option 2 |

How each base gets to the goals:

- G1 (S4 to S7): option 1 must change its hand-written grammar for 758
  cases, and then most rules see new trees. Option 2 has the S4 trees. It
  must write the rules, the fixes, the templaters, and the CLI. Option 3
  must first write an engine that gives the trees of option 2.
- G2: no base has a typed node view or a schema output. sqruff has a segment
  enum, sqlfluffrs has strings, and option 3 can get an enum from the
  generator (estimate).
- G3: all bases need speed work to get below 1 on the total. Start is
  already below for options 2 and 3. Lint and fix follow parse under
  `rule_time`.
- G4: the same harness runs all bases. For a new sqlfluff version (G1.2, a
  human decision), options 2 and 3 generate the tables again; option 1 ports
  the grammar by hand. Its port is already 124 commits before the pin.

## Reasons

1. Trees are on the path of each later stone. S1 parity uses the exact tree,
   and S5 needs the S4 trees. Option 2 has 2306 of 2306 now. Option 1 has
   1548, and its other 758 dialect cases spread over 593 groups.
2. The rule lead of option 1 is smaller than it looks. Its rules pass 2185
   of 2527 cases on sqruff trees. After S4, 75 of 77 rules see a changed
   tree (estimate), so most rules need a new check.
3. Option 1 is ahead in S6 and S7 (C7 table). S6 and S7 do not need the S4
   trees (STONES.md), so this lead does not change the S4 and S5 work.
4. Option 3 has all the work of option 2 and also a new engine (about 19464
   lines, estimate). Its gains are estimates too: the low speed bound, which
   T6 says option 2 can also get, and a segment enum from the generator.
5. Option 2 follows sqlfluff by generation, not by a hand port.
6. Option 2 has one license (MIT, as sqlfluff) and 27123 hand-written lines
   to keep, against 176917 for option 1.

## Main risks

1. Parse speed (G3.5). The probe parse total is 1.267 of sqruff. Lex and
   parse must get faster by a median 1.75 and at most 3.82 on 44 parse
   benchmarks. No data shows that the engine can do this.
2. Rule work (S5). 76 rules and a fix engine, about 35950 lines if they have
   the size of the sqruff rule layer (estimate). Sources: the sqlfluff
   Python rules (15601 lines, MIT) and the sqruff rules (Apache-2.0, with
   the T7 duties). This work is not measured.
3. The generator reads private sqlfluff attributes, so a new sqlfluff
   version can break it. The pin limits this risk.
4. The lint and fix speeds of options 2 and 3 are estimates. They assume
   rules as fast as the sqruff rules.

## Data that would change the recommendation

- A parse speed study of the sqlfluffrs engine that cannot reach the
  speed-up of risk 1. Then a new engine on the same tables (option 3)
  becomes the better choice.
- A sqruff study that shows a small number of grammar changes fixes most of
  the 758 cases, and that the rules still pass on the changed trees. Then
  option 1 becomes the better choice.
- A port of a sample of rules to sqlfluffrs trees that costs much more per
  rule than the sqruff rule sizes show. Then the S5 cost of options 2 and 3
  goes up.

## Criteria

A criterion that maps to a goal or a stone measures the work or the risk to
get to that goal or stone from the base.

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
`harness/tests/`. Timings for the probe and for sqruff come from one session
on the baseline machine setup (`harness/bench.md`, "Baseline"): the CI image
in docker, serial, no other load. Comparisons use ratios inside that
session. The lint and fix times of sqruff and sqlfluff come from the S2
baseline (`results/s2/baseline.json`). The T6 estimates (formulas
`rule_time` and `total_all`) take only ratios inside each session. The T6
sensitivity check (formula `unscaled`) does not: it adds a time of the probe
session to times of the baseline session. T8 uses one more session with the
same setup for the cause of the start time; it compares only times of that
session.

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
| C6 | License and copyright of each base (the files of the pinned versions), the duties if sqll ports or generates from it, the dependency licenses of each base (cargo tree and cargo metadata), the lines of each crate (hand-written and generated), and the structure (crates, dialects, rules) (from `scripts/s3/license_size.py`). Input: `results/s3/license-size-sources.json` (the sqruff 0.41.0 crates and tag, a copy of the submodule with the generated tables) | `results/s3/license-size.json` | T7 | Measurement; the duties are paraphrases of the license texts (the MIT condition is an exact quote); the size of option 3 is an estimate; the legal questions are open for a human |
| C7 | For each base: the templaters and the Python runtime that they need, the placeholder styles (also the G2 parameter styles), the CLI commands and options (parsed from the help text of sqlfluff 4.4.0 and sqruff 0.41.0), the config files and keys, the S1 cases with an unsupported setting, the segment type of the tree and the one-parse property (G2, S8), and the cause of the start time (G3). From `scripts/s3/capabilities.py`. Inputs: `results/s3/capabilities-sources.json` (the help commands and their output, the sqlfluff facts, the cited lines of the sqruff 0.41.0 crates) and `results/s3/capabilities-start.json` (a start session in the CI image) | `results/s3/capabilities.json` | T8 | Measurement (help text, cited source lines, session); each judgement has `estimate` and its reason; option 3 is an estimate |
| C8 | Work for each base and goal or stone, from C1 to C7: the values of the record with their sources and formulas, and the tables of the record (from `scripts/s3/decision_data.py`). Inputs: `results/s1/summary.json` and the T2 to T8 outputs | `results/s3/decision-data.json` | T9 | Copied and derived values; each work item and the size of option 3 are estimates |
