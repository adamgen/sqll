# sqll Status

- Current stone: S1. In progress.
- sqlfluff reference: tag `4.4.0`, commit `0348222a3bcdb0226563f7349c5a39beb0641955`.

## S1 tasks

| Task | Description | State |
|---|---|---|
| T1 | Harness foundation: submodule, CI, `scripts/test`, sqlfluff parse adapter, dialect suite | Done (PR #3) |
| T2 | CI image in GHCR, all 3 tools pinned, sharded CI matrix | Done (PR #4) |
| T3 | Rule case suite (`std_rule_cases`), sqlfluff lint and fix | Done (PR #5) |
| T4 | Autofix suite (`linter/autofix`) for sqlfluff | Done (PR #6) |
| T5 | Templater suite (`test__templater_full`) for sqlfluff | Done (PR #7) |
| T6 | `sqlfluff[rs]` adapter on all 4 suites, results recorded | Done (PR #8) |
| T7 | sqruff adapter on all 4 suites, results recorded | In review |
| T8 | S1 exit: full run, recorded baseline, status | Open |

## Tools

sqlfluff 4.4.0, `sqlfluff[rs]` 4.4.0 with sqlfluffrs 4.4.0, sqruff 0.41.0
(features `parser,python`). See `harness/README.md`.

## Parity

| Suite | Tool | Total | Passed | Skipped | Checks |
|---|---|---|---|---|---|
| dialects | sqlfluff 4.4.0 | 2306 | 2306 | 0 | exact 2306, no_unparsable 2306 |
| rules | sqlfluff 4.4.0 | 2527 | 2527 | 0 | after_fix 851, fail_str 1193, fix 1193, pass_str 1332 |
| autofix | sqlfluff 4.4.0 | 61 | 61 | 0 | fix 61, non_linting 61, tree 61, violations 1 |
| templater | sqlfluff 4.4.0 | 43 | 43 | 0 | exact 43, no_unparsable 43 |
| dialects | sqlfluff-rs 4.4.0 | 2306 | 2306 | 0 | exact 2306, no_unparsable 2306 |
| rules | sqlfluff-rs 4.4.0 | 2527 | 2527 | 0 | after_fix 851, fail_str 1193, fix 1193, pass_str 1332 |
| autofix | sqlfluff-rs 4.4.0 | 61 | 61 | 0 | fix 61, non_linting 61, tree 61, violations 1 |
| templater | sqlfluff-rs 4.4.0 | 43 | 43 | 0 | exact 43, no_unparsable 43 |
| dialects | sqruff 0.41.0 | 2306 | 1548 | 0 | exact 1548, no_unparsable 2164 |
| rules | sqruff 0.41.0 | 2527 | 2185 | 0 | after_fix 758, fail_str 1044, fix 1001, pass_str 1207 |
| autofix | sqruff 0.41.0 | 61 | 45 | 0 | fix 45, non_linting 54, tree 54, violations 1 |
| templater | sqruff 0.41.0 | 43 | 28 | 0 | exact 28, no_unparsable 33 |

The sqlfluff tests pass the same cases, with 0 differences
(`scripts/sqlfluff-dialect-oracle`: 2306 dialect cases;
`scripts/sqlfluff-rule-oracle`: 2527 rule cases;
`scripts/sqlfluff-autofix-oracle`: 61 autofix cases;
`scripts/sqlfluff-templater-oracle`: 43 templater cases). With `--rust` the
same is true for sqlfluff-rs; for dialects this includes the sqlfluff
Python-vs-Rust parity test. CI checks this. sqlfluff-rs is sqlfluff with
`use_rust_parser` and `use_rust_rules` set to true (see
`harness/sqlfluff-rs.md`).
3 templater cases need a Python runtime (`needs_python`, see
`harness/templater.md`).

sqruff has no code-only parse output. The harness filters its full tree.
The `code_only` suite proves the filter with sqlfluff: 2306 of 2306 dialect
cases (`harness/sqruff.md`). No sqlfluff test runs sqruff, so sqruff has no
oracle.

## Known failures

- sqlfluff: none.
- sqlfluff-rs: none.
- sqruff: 1131 cases in `known_failures/sqruff.txt` (7 `error`, all sqruff
  panics; the others `fail`). Counts for each reason prefix:

| Reason prefix | autofix | dialects | rules | templater |
|---|---|---|---|---|
| after_fix | 0 | 0 | 1 | 0 |
| fail_str | 0 | 0 | 45 | 0 |
| fix mismatch | 9 | 0 | 67 | 0 |
| lint | 0 | 0 | 7 | 0 |
| no tree | 0 | 0 | 0 | 1 |
| pass_str | 0 | 0 | 57 | 0 |
| the tool has no parse tree for the file | 1 | 0 | 0 | 0 |
| tree differs | 0 | 755 | 0 | 5 |
| unsupported: comment character | 0 | 0 | 4 | 0 |
| unsupported: dialect | 0 | 3 | 1 | 0 |
| unsupported: layout type | 0 | 0 | 1 | 0 |
| unsupported: output field | 0 | 0 | 21 | 0 |
| unsupported: rule | 0 | 0 | 24 | 0 |
| unsupported: setting | 6 | 0 | 109 | 7 |
| unsupported: upper-case key | 0 | 0 | 5 | 2 |
