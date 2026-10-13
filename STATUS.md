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
| T5 | Templater suite (`test__templater_full`) for sqlfluff | In review |
| T6 | `sqlfluff[rs]` adapter on all 4 suites, results recorded | Open |
| T7 | sqruff adapter on all 4 suites, results recorded | Open |
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

The sqlfluff tests pass the same cases, with 0 differences
(`scripts/sqlfluff-rule-oracle`: 2527 rule cases;
`scripts/sqlfluff-autofix-oracle`: 61 autofix cases;
`scripts/sqlfluff-templater-oracle`: 43 templater cases). CI checks this.
3 templater cases need a Python runtime (`needs_python`, see
`harness/templater.md`).

## Known failures

- sqlfluff: none.
