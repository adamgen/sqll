# S5 decision: the rule parity design

Status: written on 2026-11-17 in T1 (goal of the task: the plan, the
parity path, the rule source, the case classes, the gap rule, the speed
rule, and the start data are recorded; this track owns its records,
scripts, and harness tests) of S5 (rule parity: sqll passes 100% of the
rule fixtures, lint and fix; cases that need the Jinja templater move to
the Jinja templater stone). Plan, tasks, and parity numbers:
[status/S5.md](../../status/S5.md). In this record, "this stone" is S5
(rule parity: sqll passes 100% of the rule fixtures, lint and fix; cases
that need the Jinja templater move to the Jinja templater stone), and
"this track" is its track.

This stone needs S3b (core: the shared syntax tree, source map, frozen
interfaces, and the sqll binary skeleton (CLI, config, output) with the
sqll adapters of the test harness and the benchmarks; the test harness
and the benchmarks run sqll through its adapters, the interfaces are
documented, and after this stone, each change to the core goes through
the track that owns the core). The orchestrator approved it on 2026-11-11.
For each dialect, this stone also needs the trees of S4 (parser parity:
sqll passes 100% of the dialect parse fixtures with an exact tree match).
The orchestrator approved that stone on 2026-11-17, for all 28
dialects (STATUS.md).

Names in this record and their goals (AGENTS.md, "Names"):

| Name | Goal |
|---|---|
| S6 | Templater parity: sqll passes 100% of the placeholder and Python format-string templater fixtures that do not need a Python runtime |
| S11 | Jinja templater: the last stone; decision of the human owner (2026-11-07): do not write a Jinja engine in sqll; decide with data how sqll supports Jinja; sqll passes 100% of the Jinja cases that the decision keeps, and the code generation stone supports Jinja if kept; each other Jinja case is in a known-failure list with its reason |
| core (track) | The track that does S3b (core: the shared syntax tree, source map, frozen interfaces, and the sqll binary skeleton (CLI, config, output) with the sqll adapters of the test harness and the benchmarks; the test harness and the benchmarks run sqll through its adapters, the interfaces are documented, and after this stone, each change to the core goes through the track that owns the core) and owns the shared core |
| S7-sqll (track) | The track that makes sqll pass the converted cases of S7 (CLI and config parity: the sqlfluff CLI, config, and Python rule tests as black-box cases; sqll passes 100% of the converted cases; cases that need the Jinja templater move to the Jinja templater stone) (the sqll part of that stone) |
| G3 | Speed: each command, start time included, is as fast as reasonably possible and has a benchmark that measures sqlfluff, sqruff, and sqll on the same input. sqll is faster than sqlfluff on each benchmark, not slower than sqruff on any benchmark, and faster than sqruff on the total of all benchmarks. A change that makes a benchmark slower gives the reason. Correctness is more important than speed: do not make a result wrong to make it fast |
| G4 | Verification first: each behavior has an automated test; tests come from external sources (sqlfluff first, then large, complex public SQL files); external test data has its source, version, and license, and does not change to make a test pass; one command runs all tests and benchmarks, and the output is machine-readable; each known failure is in a list |

## 1. The parity path

Parity uses only this path: the test harness and the sqll adapter.

1. The `rules` suite (`harness/sqll_harness/suites/rules.py`): each
   top-level key of each file `test/fixtures/rules/std_rule_cases/*.yml`
   of the pinned sqlfluff, other than `rule` and `configs`, is one case:
   2527 cases in 92 files. The checks are those of `rules__test_helper`:
   `pass_str`, `fail_str` and `violations`, `fix_str`, and
   `violations_after_fix` ([harness/rules.md](../../harness/rules.md)).
2. The `autofix` suite (`harness/sqll_harness/suites/autofix.py`): each
   folder `test/fixtures/linter/autofix/<dialect>/<case>/` is one case: 61
   cases in 8 dialects. The checks are those of `auto_fix_test`
   ([harness/autofix.md](../../harness/autofix.md)).
3. The sqll adapter (`harness/sqll_harness/adapters/sqll.py`) runs
   `sqll lint -f json --nofail` and `sqll fix` with the rules, the
   dialect, and the case config as a `--config` file, as the sqlfluff
   adapter runs sqlfluff. For autofix, it runs `sqll fix --nocolor
   --dialect D [--rules R] testing.sql` in a copy of the case folder. It
   fails closed (`unsupported: <item>`, no run) for a rule that sqll does
   not have, for a templater that is not raw or the Jinja as raw record
   (`results/S3b/C14-jinja-raw.json`), and for an in-file config line. sqll
   fails closed itself (exit code 2) on a setting that it cannot do
   ([harness/sqll.md](../../harness/sqll.md)).
4. `sqll lint` and `sqll fix` (`crates/sqll_cli/src/`) run the linter of
   `sqll_lint` with the rules of `sqll_rules` (the frozen rule interface,
   [rules.md](../interfaces/rules.md)).
5. The rule oracle runs the pinned sqlfluff test on each case. Each case
   that sqll passes must pass there. The CI report job runs both commands:

   ```
   scripts/sqlfluff-rule-oracle --report out/report.json \
       --out out/oracle.jsonl --passes-of sqll
   scripts/sqlfluff-autofix-oracle --report out/report.json \
       --out out/autofix-oracle.jsonl --passes-of sqll
   ```

The parity number of this stone is the pass count of the tool `sqll` in
the suites `rules` and `autofix` (steps 1 to 3), with step 5. A Rust test
in `crates/sqll_rules/tests/` can help to find a gap, but it does not
count for parity.

## 2. The rule source

- Each rule is a port of its sqlfluff 4.4.0 Python rule
  (`src/sqlfluff/rules/<group>/<code>.py`; Copyright (c) 2018-2026 Alan
  Cruickshank; MIT License) onto the frozen rule interface (`Rule`,
  `RuleContext`, `LintResult`, `Fix`; [rules.md](../interfaces/rules.md))
  in `crates/sqll_rules/src/`. sqlfluff has 79 rules in 11 groups (about
  15600 lines of Python). The rule metadata must be that of sqlfluff:
  `Registry::new` refuses other metadata.
- The shared helpers of the Python rules are ports in
  `crates/sqll_rules/src/` too: the functional segments
  (`src/sqlfluff/utils/functional/`, 662 lines), the select and query
  analysis (`src/sqlfluff/utils/analysis/`, 912 lines), and reflow
  (`src/sqlfluff/utils/reflow/`, 6611 lines). Their Rust tests use the
  data of the pinned sqlfluff tests of these helpers
  (`test/core/rules/functional/`, `test/utils/analysis/`,
  `test/utils/reflow/`).
- CP01, CP03, and CP04 exist: ports of the sqlfluffrs rules
  ([rules.md](../interfaces/rules.md), "Proof"). CP02 and CP05 use the
  same `capitalisation.rs`.
- No sqruff code is copied (sqruff is Apache-2.0; THIRD_PARTY.md,
  "sqruff"). The harness runs sqruff only as a tool.
- Each ported file has the header of the files of `crates/sqll_rules/src/`:
  the source file, the tag, the commit, the copyright, and the license.
  A new file or the first change of a ported file also changes the port
  record `crates/ported.json`, a path of the track that owns the shared
  core. Thus that pull request has the label `cross-track`, and the
  track that owns the shared core reviews the record
  ([docs/interfaces/README.md](../interfaces/README.md), "Ownership").
- A rule does not change `sqll_lint` ([rules.md](../interfaces/rules.md),
  "Rules for a change"). A change of the interface, of the fix loop, or of
  a dependency goes through the track that owns the shared core.

## 3. The case classes

Each case has one class. The data come from the pinned fixtures, with the
case loader of the harness (`rules.load_file`, `autofix.discover`). The
templater of a rule case is `core.templater` of its `configs` (default
`jinja`). The templater of an autofix case is that of the `.sqlfluff` file
of its folder (default `jinja`).

| Class | Rule cases | Autofix cases | When | Exit |
|---|---|---|---|---|
| pass | 38 | 0 | sqll passes the case, and the oracle passes it | This stone |
| `jinja: S11` | 169 | 21 | A SQL text has a Jinja tag (a start string of the case config; default `{{`, `{%`, `{#`), or the config has a Jinja templater setting (a `templater` section, or `library_path`) | S11 (Jinja templater: the last stone; decision of the human owner (2026-11-07): do not write a Jinja engine in sqll; decide with data how sqll supports Jinja; sqll passes 100% of the Jinja cases that the decision keeps, and the code generation stone supports Jinja if kept; each other Jinja case is in a known-failure list with its reason) |
| templater of S6 | 13 | 0 | `core.templater` is `placeholder` (12) or `python` (1) | This stone, after S6 (templater parity: sqll passes 100% of the placeholder and Python format-string templater fixtures that do not need a Python runtime) has the templaters |
| gap | 2307 | 40 | Each other case | This stone |

- The Jinja class: each of the 169 rule cases has a tag; 16 of them also
  have a `templater` section (11 with no `core.templater`, 5 with an
  explicit `core.templater: jinja`). 20 autofix cases have a tag in
  `before.sql`. 1 autofix case has only a setting:
  `ansi/macro_file_jinja_include_undefined_variable`
  (`load_macros_from_path`). The rule files with Jinja cases: AL01 1, AL02
  1, AL07 1, AM04 7, CP01 3, CP03 3, CV03 1, CV06 1, CV09 3, CV10 11,
  CV11 1, CV12 3, JJ01 11, LT01-alignment 4, LT01-brackets 2,
  LT01-commas 4, LT01-excessive 2, LT01-operators 1, LT01-trailing 3,
  LT02-indent 43, LT03 3, LT04 4, LT05 17, LT07 7, LT12 9, LT13 6, LT14
  1, LT15 7, RF03 2, ST02 1, ST03 1, ST04 1, ST05 1, ST07 1, ST09 2. The
  autofix folders: ansi 16, bigquery 5.
- The templater class: AM04 3, AM07 1, CP02 4, CP02_LT01 1, RF03 1, ST10
  1, ST11 1 (`placeholder`), and JJ01 1 (`python`,
  `test_pass_python_templater`). Item 1 of the design record of S6
  (templater parity: sqll passes 100% of the placeholder and Python
  format-string templater fixtures that do not need a Python runtime;
  [s6-templaters.md](s6-templaters.md)) gives their exit to this stone.
  That stone checks their templated text and source slices.
- A gap case does not need the Jinja templater. Proof: the Jinja as raw
  record (`results/S3b/C14-jinja-raw.json`, sqlfluff 4.4.0) has 3422
  inputs of the 2 suites with the `jinja` templater. For each input, the
  Jinja templater gives the file of the raw templater if, and only if,
  the input has no Jinja delimiter (`notes` is empty).
- The exit of this stone: sqll passes each case that is not in the Jinja
  class, that is, 2358 rule cases and 40 autofix cases, and each of these
  passes in the oracle. The 169 rule cases and 21 autofix cases of the
  Jinja class stay in `known_failures/sqll.txt` with their reason.
- The parity check of this track (`scripts/s5/parity`; status/S5.md
  gives its task) makes these data again from the fixtures and fails
  closed if a class count changes.

## 4. The gap rule

A gap is a case of the gap class or of the templater class that sqll
does not pass, or a sqll pass that the oracle does not pass.

- No fixture changes, and the pinned sqlfluff version does not change.
  This is G4 (verification first: each behavior has an automated test;
  tests come from external sources (sqlfluff first, then large, complex
  public SQL files); external test data has its source, version, and
  license, and does not change to make a test pass; one command runs all
  tests and benchmarks, and the output is machine-readable; each known
  failure is in a list). Only the human owner can change the pinned
  version.
- During the work, `known_failures/sqll.txt` lists each case that sqll
  does not pass, with the reason of the harness. At the exit, it has no
  `rules` or `autofix` line of a gap case or a templater case.
- This track closes a gap in its own paths: `crates/sqll_rules/src/**`,
  with tests in `crates/sqll_rules/tests/**`.
- If the cause is in a path of another track, the pull request has the
  label `cross-track`, and the owner track reviews it (PROCESS.md,
  "Tracks"). Or this track opens an issue for the owner track.
  `tracks.yml` gives the owner of each path:

  | Path | Owner track | Goal of the owner track | Example of a cause |
  |---|---|---|---|
  | `crates/sqll_lint/**`, `crates/sqll_config/**`, each `Cargo.toml`, `Cargo.lock`, `crates/ported.json`, `known_failures/**`, `results/s1/summary.json`, `harness/**` | core | The track that does S3b (core: the shared syntax tree, source map, frozen interfaces, and the sqll binary skeleton (CLI, config, output) with the sqll adapters of the test harness and the benchmarks; the test harness and the benchmarks run sqll through its adapters, the interfaces are documented, and after this stone, each change to the core goes through the track that owns the core) and owns the shared core | `noqa` comments; the fix loop; a rule or layout setting that is not the default; a new dependency (for example a regular expression engine with the rules of Python `re`); a new port record; the known-failure list and the summary |
  | `crates/sqll_dialects/src/**`, `crates/sqll_parser/src/**` | S4 | Parser parity: sqll passes 100% of the dialect parse fixtures with an exact tree match | A tree that is not the sqlfluff tree |
  | `crates/sqll_cli/src/**` | S7-sqll | The track that makes sqll pass the converted cases of S7 (CLI and config parity: the sqlfluff CLI, config, and Python rule tests as black-box cases; sqll passes 100% of the converted cases; cases that need the Jinja templater move to the Jinja templater stone) (the sqll part of that stone) | An option or an output field of `sqll lint` or `sqll fix` |
  | `crates/sqll_templater/src/**` | S6 | Templater parity: sqll passes 100% of the placeholder and Python format-string templater fixtures that do not need a Python runtime | The placeholder and python templaters of the templater class |

- A pull request that makes more cases pass removes their lines from
  `known_failures/sqll.txt` and records the new `results/s1/summary.json`
  (the CI checks of each test job and of the report job). These are core
  paths, so that pull request has the label `cross-track`.
- The causes at the start (section 6): a rule that sqll does not have
  (2300 gap rule cases, 33 gap autofix cases, and 3 autofix cases with
  `rules = all`), `ignore_words_regex` (7 rule cases of CP01 and CP03:
  sqll does not have the Python regular expressions), and a setting that
  sqll cannot do yet (4 autofix cases: 3 rule or layout settings and
  `core:exclude_rules`).

## 5. The speed rule for each pull request

G3 (speed: each command, start time included, is as fast as reasonably
possible and has a benchmark that measures sqlfluff, sqruff, and sqll on
the same input. sqll is faster than sqlfluff on each benchmark, not
slower than sqruff on any benchmark, and faster than sqruff on the total
of all benchmarks. A change that makes a benchmark slower gives the
reason. Correctness is more important than speed: do not make a result
wrong to make it fast) applies to each pull request of this track.

- The lint and fix path is each file that `sqll lint` and `sqll fix` run:
  the package of this track, and the other packages that they link.
- The benchmarks of S2 (benchmarks: a benchmark for each command (start,
  parse, lint, fix) with small, medium, and large inputs for each
  dialect; one command gives a machine-readable report for sqlfluff,
  `sqlfluff[rs]`, and sqruff, and the baseline is recorded) select all
  rules (`rules = all`). sqll fails closed on a rule that it does not
  have, so its `lint` and `fix` benchmarks are `unsupported` until the 79
  rules exist ([harness/bench.md](../../harness/bench.md), "Add a tool").
- Thus this track makes a speed script, `scripts/s5/speed` (status/S5.md
  gives its task), before the first rule. A pull request that changes
  the lint and fix path runs it (it takes the machine lock, PROCESS.md,
  "Tracks", rule 7). It gives, for the `lint` and `fix` benchmark inputs
  and only the rules that sqll has at BASE: HEAD / BASE, HEAD / sqlfluff,
  and HEAD / sqruff, with the same rules for each tool. The pull request
  gives these ratios and the reason for each slower benchmark (PROCESS.md,
  rule 8; `harness/bench.md`, "Slowdowns"). If the script needs a change
  of the benchmark harness, that change goes through the track that owns
  the shared core.
- The method of `scripts/s5/speed` (T3 (goal of the task: each pull
  request of this track that changes the lint and fix path gives the HEAD
  / BASE, HEAD / sqlfluff, and HEAD / sqruff ratios of the lint and fix
  benchmarks for the rules that sqll has) of this stone; the docstring of
  the script has the full method). It uses the benchmark harness as it is
  (no change of a path of the track that owns the shared core):
  1. The machine lock: the script takes it, or a parent `flock` command
     holds it. If another process holds it, the script stops (exit code
     2). The session in the container stops if the lock is free.
  2. The builds and the session: as `scripts/speed-check` (the CI image,
     one container, serial, no network, the full profile). If the
     checkout is HEAD with no change of a tracked file, the HEAD binary is
     the binary of `scripts/build-sqll` in the checkout when its source
     hash and version are those of HEAD (else a new build there). If BASE
     and HEAD have the same build inputs (`git diff` of `Cargo.toml`,
     `Cargo.lock`, `rust-toolchain.toml`, `LICENSE`, `crates`,
     `third_party/sqlfluff`, and `scripts/build-sqll`), the BASE binary
     is a copy of the HEAD binary. Else each is a new worktree build, as
     in `scripts/speed-check`.
  3. The rules: each rule that `sqll rules` of the BASE binary gives. sqll
     at HEAD (`sqll rules`), sqlfluff (`sqlfluff rules`), and sqruff
     (`sqruff rules`) must have each of them, else the script stops (exit
     code 2). Each tool gets the S2 settings with `core.rules` = these
     rules. Known limit: the pinned sqruff has no CV13 and no TQ01. When
     sqll has one of them at BASE, the script stops, and this track
     records a decision before the next speed run of a lint and fix
     change.
  4. The reference: the sqlfluff reference of the S2 definitions has all
     rules. Thus the script makes it again with the rules (sqlfluff lints
     and fixes each input once, with the checks of `harness/bench.md`,
     "Validity"). Each lint and fix run of each tool must give the rule
     codes and the fix change of this reference. A sqlfluff run that is
     not valid, or a code of another rule, stops the script.
  5. `sqll parse` refuses a `core.rules` setting that is not the default
     (`crates/sqll_config/src/parse.rs`). A parse runs no rule. Thus the
     parse check of a lint or fix run of sqll (`harness/bench.md`,
     "Validity") runs `sqll parse` with the S2 settings (`rules = all`),
     as the S2 parse benchmarks do. The lint and fix runs have the rules.
  6. The record: `results/S5/speed/<label>.json`. For each of the 168
     lint and fix benchmarks (28 dialects, 3 sizes): the median wall time
     of each tool and the 3 ratios (the median wall time of HEAD / that of
     the other tool). HEAD / BASE also has the compare entry of
     `sqll-harness bench compare` (the noise limit). The lists of slower
     benchmarks: HEAD slower than BASE, HEAD not valid, HEAD / sqlfluff
     1 or more, HEAD / sqruff more than 1, and HEAD / sqruff of the total
     1 or more. Exit code 1 if a list is not empty: the pull request gives
     the reason.
- A pull request that also changes the parse path runs
  `scripts/speed-check` (the start and parse benchmarks). Its record goes
  to `results/S3b/speed/`, a path of the track that owns the shared core,
  so that pull request has the label `cross-track`.
- After the 79 rules exist, one task runs the full lint and fix
  benchmarks of all dialects (`scripts/bench`, the full profile, with the
  machine lock; in CI the jobs `bench-full` and `bench-merge`) and
  records them. sqll must be faster than sqlfluff on each lint and fix
  benchmark, not slower than sqruff on any, and faster than sqruff on the
  total of all benchmarks.
- A pull request that does not change the lint and fix path gives
  `git diff --name-only` of its change as the proof, and needs no speed
  data.

## 6. The start data

Local run on main `d780036` (2026-11-17), with the machine lock, the
pinned tools, and a fresh build (`scripts/build-sqll`: exit code 0):

```
$ sqll-harness run --tool sqll --suite rules --suite autofix --out out/s5-start.json
autofix/sqll: total=61 passed=0 failed=61 skipped=0 (0.00% pass)
rules/sqll: total=2527 passed=38 failed=2489 skipped=0 after_fix=24 fail_str=24 fix=24 pass_str=14 (1.50% pass)
```

- The 38 passes: CP01 23, CP03 10, CP04 5.
- The rule oracle and the autofix oracle (`--out`, then the check of
  `--passes-of sqll` on this report): rules 2527 of 2527 pass, autofix 61
  of 61 pass. `sqll rules: 2527 cases, 38 pass, 38 of them pass in the
  oracle`; `sqll autofix: 61 cases, 0 pass, 0 of them pass in the
  oracle`.
- The 2550 failed case ids are the 2550 `rules` and `autofix` lines of
  `known_failures/sqll.txt`.
- The reasons of the 2550 failures: `unsupported: rule <code>` 2509
  (the rules that sqll does not have); the Jinja templater 27 (all in the
  Jinja class: 19 texts that are not in the Jinja as raw record, 13
  autofix and 6 rule cases, and 8 autofix cases with a Jinja setting);
  `ignore_words_regex` 7; `rules = all` 3; another setting 4.

The case count of each rule file (columns: all cases of the group,
Jinja class, templater class, other, pass at the start):

| Group | Cases of each file | All | Jinja | Templater | Other | Pass |
|---|---|---|---|---|---|---|
| AL | AL01 18, AL02 10, AL02_LT01 3, AL03 22, AL04 10, AL05 137, AL05_CV12 2, AL06 5, AL07 19, AL08 8, AL09 15, AL10 15 | 264 | 3 | 0 | 261 | 0 |
| AM | AM01 2, AM02 11, AM03 8, AM04 69, AM05 38, AM06 51, AM07 39, AM08 28, AM09 7 | 253 | 7 | 4 | 242 | 0 |
| CP | CP01 29, CP02 48, CP02_LT01 5, CP03 17, CP04 5, CP05 22 | 126 | 6 | 5 | 115 | 38 |
| CV | CV01 23, CV02 4, CV03 5, CV04 15, CV05 15, CV06 62, CV07 10, CV08 13, CV09 24, CV10 35, CV11 60, CV12 38, CV13 17 | 321 | 20 | 0 | 301 | 0 |
| JJ | JJ01 12 | 12 | 11 | 1 | 0 | 0 |
| LT | LT01-alignment 33, LT01-brackets 16, LT01-commas 10, LT01-excessive 42, LT01-functions 5, LT01-literals 20, LT01-missing 29, LT01-operators 28, LT01-trailing 5, LT02-indent-oracle 32, LT02-indent 178, LT02-tab-space 9, LT03 55, LT04 22, LT05 57, LT06 5, LT07 14, LT08 22, LT09 46, LT10 5, LT11 11, LT12 12, LT13 13, LT14 34, LT15 48 | 751 | 113 | 0 | 638 | 0 |
| OR | OR01 10 | 10 | 0 | 0 | 10 | 0 |
| PG | PG01 16, PG02 7 | 23 | 0 | 0 | 23 | 0 |
| RF | RF01 114, RF02 82, RF03 60, RF04 28, RF05 60, RF06 69, RF07 14 | 427 | 2 | 1 | 424 | 0 |
| ST | ST01 5, ST02 44, ST03 33, ST04 17, ST05 44, ST06 49, ST07 18, ST08 11, ST09 30, ST10 23, ST11 33, ST12 2 | 309 | 7 | 2 | 300 | 0 |
| TQ | TQ01 7, TQ02 9, TQ03 8, TQ04 7 | 31 | 0 | 0 | 31 | 0 |
| Total | 92 files | 2527 | 169 | 13 | 2345 | 38 |

The autofix cases of each dialect: ansi 40, bigquery 7, clickhouse 1,
oracle 2, snowflake 4, sparksql 1, sqlite 5, tsql 1.

The rule groups (sqlfluff folders): AL aliasing, AM ambiguous, CP
capitalisation, CV convention, JJ jinja, LT layout, OR oracle, PG
postgres, RF references, ST structure, TQ tsql.
