# sqll Status

- Current stone: S1. In progress.
- sqlfluff reference: tag `4.4.0`, commit `0348222a3bcdb0226563f7349c5a39beb0641955`.

## S1 tasks

| Task | Description | State |
|---|---|---|
| T1 | Harness foundation: submodule, CI, `scripts/test`, sqlfluff parse adapter, dialect suite | In review |
| T2 | Rule case suite (`std_rule_cases`), sqlfluff lint and fix adapter | Open |
| T3 | Autofix suite (`linter/autofix`) for sqlfluff | Open |
| T4 | Templater suite for sqlfluff | Open |
| T5 | `sqlfluff[rs]` adapter and recorded results | Open |
| T6 | sqruff adapter and recorded results | Open |
| T7 | S1 exit: full run, recorded baseline, status | Open |

## Parity

| Suite | Tool | Total | Passed | exact | no_unparsable |
|---|---|---|---|---|---|
| dialects | sqlfluff 4.4.0 | 2306 | 2306 | 2306 | 2306 |

## Known failures

- sqlfluff: none.
