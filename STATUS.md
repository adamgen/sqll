# sqll Status

- Current stone: S1. In progress.
- sqlfluff reference: tag `4.4.0`, commit `0348222a3bcdb0226563f7349c5a39beb0641955`.

## S1 tasks

| Task | Description | State |
|---|---|---|
| T1 | Harness foundation: submodule, CI, `scripts/test`, sqlfluff parse adapter, dialect suite | Done (PR #3) |
| T2 | CI image in GHCR, all 3 tools pinned, sharded CI matrix | In review |
| T3 | Rule case suite (`std_rule_cases`), sqlfluff lint and fix | Open |
| T4 | Autofix suite (`linter/autofix`) for sqlfluff | Open |
| T5 | Templater suite for sqlfluff | Open |
| T6 | `sqlfluff[rs]` adapter on all 4 suites, results recorded | Open |
| T7 | sqruff adapter on all 4 suites, results recorded | Open |
| T8 | S1 exit: full run, recorded baseline, status | Open |

## Tools

sqlfluff 4.4.0, `sqlfluff[rs]` 4.4.0 with sqlfluffrs 4.4.0, sqruff 0.41.0
(features `parser,python`). See `harness/README.md`.

## Parity

| Suite | Tool | Total | Passed | exact | no_unparsable |
|---|---|---|---|---|---|
| dialects | sqlfluff 4.4.0 | 2306 | 2306 | 2306 | 2306 |

## Known failures

- sqlfluff: none.
