# sqll harness

The harness runs the sqlfluff test fixtures through tool binaries. It does not
import the tools. Each tool is in its own virtual environment.

## Run

```sh
git submodule update --init
scripts/test                       # all tools, all suites
scripts/test --tool sqlfluff --suite dialects --jobs 8
scripts/test --filter dialects/ansi/   # only ids that start with this text
```

`scripts/test` runs `scripts/setup`, writes `out/tools.json` with
`sqll-harness tools`, runs `pytest harness/tests`, then runs the suites. The
exit code is not 0 if a result is different from `known_failures/<tool>.txt`.
`scripts/check-submodule` fails if `third_party/sqlfluff` has a change or an
untracked or ignored file. `scripts/test` runs it before the tests and after
the run. CI runs it after the tests and after each shard.

## Tools

`scripts/setup` installs the pinned tools in `SQLL_TOOLS_DIR` (default
`.tools/`; `/opt/sqll/tools` in the CI image). The harness reads the same
setting. Needs: uv, Python 3.13 with a shared libpython, and cargo.

| Tool | Pin | Installed as |
|---|---|---|
| `sqlfluff` | `tools/sqlfluff/uv.lock` | `<dir>/sqlfluff` (venv) |
| `sqlfluff-rs` | `tools/sqlfluff-rs/uv.lock` | `<dir>/sqlfluff-rs` (venv with `sqlfluffrs`) |
| `sqruff` | `tools/sqruff/uv.lock` | `<dir>/sqruff/bin/sqruff` and `<dir>/sqruff/python` |

It also installs `<dir>/sqlfluff-oracle` for the oracle scripts
(`scripts/sqlfluff-rule-oracle`, `scripts/sqlfluff-autofix-oracle`,
`scripts/sqlfluff-templater-oracle`), and `<dir>/sqlfluff-rs-oracle` for the
same scripts with `--rust`.

`tools/sqruff/install.sh` builds sqruff with `cargo install --locked
--features parser,python`. The `parser` feature adds the `parse` command. The
`python` feature adds the jinja, python, dbt, and sqlmesh templaters. They
import the `sqruff` Python package. The interpreter in sqruff finds it through
the first `python3` on `PATH`, so run sqruff with `tools.sqruff_env()`. The
binary links to the libpython of the Python that it was built with.

`sqll-harness tools` prints each tool as JSON: name, version, pin, binary, and
checks. It fails if a version is not the pin, if `sqlfluffrs` does not import
in the `sqlfluff-rs` venv, if `sqlfluff-rs` does not log that it uses the Rust
parser, or if `sqruff parse` or its jinja templater does not work.
`sqll-harness run` makes the same check for the tools that it runs, before
the first case.

The `sqlfluff-rs` adapter is the `sqlfluff` adapter with the Rust parser and
rules forced on. See [sqlfluff-rs.md](sqlfluff-rs.md).

## Shards and CI

`sqll-harness run --shard K/N` runs only the cases in shard K. The shard of a
case is a hash of its id. `sqll-harness merge REPORT...` merges shard reports
into `out/report.json` and does the known-failure check again on all results.
Thus it reports a listed id that no shard ran. It fails if a shard report is
missing or is in two reports, or if 2 reports have a different record of a
tool.

CI (`.github/workflows/ci.yml`):

1. `image`: `ci/image_tag.py` hashes all inputs of `ci/Dockerfile`. If
   `ghcr.io/adamgen/sqll-ci:<hash>` does not exist, CI builds and pushes it.
2. `lint`: `sqll-harness tools`, ruff, the unit tests, and the oracles on
   the harness rule, autofix, and templater fixtures (also with `--rust`), in
   the image.
3. `test`: one job for each suite, tool, and shard in `ci/matrix.json`.
4. `report`: `sqll-harness merge --expect ci/matrix.json`, then the 3
   oracle scripts on the merged report for `sqlfluff`, and again with
   `--rust` for `sqlfluff-rs`. It uploads `out/report.json` and the
   `out/*oracle.jsonl` files.

To add a suite or a tool to CI, add an entry to `ci/matrix.json`.

## Suites

| Suite | Fixtures | Checks |
|---|---|---|
| `dialects` | `test/fixtures/dialects/<d>/*.sql` with `.yml` or `_nc.yml` | `exact`, `no_unparsable` |
| `rules` | each case key in `test/fixtures/rules/std_rule_cases/*.yml` | `pass_str`, `fail_str`, `fix`, `after_fix` |
| `autofix` | each entry `test/fixtures/linter/autofix/<d>/<case>` | `tree`, `non_linting`, `violations`, `fix` |
| `templater` | each row of `test__templater_full` (`test/fixtures/templater/<subpath>.sql`) | `exact`, `no_unparsable` |

Dialect case id: `dialects/<dialect>/<stem>` (`<stem>_nc` for `_nc.yml`).

- `exact`: the tree is equal to the YAML tree, with the sqlfluff rules
  (`process_struct`). Two trees with no children are equal. Parity uses this
  check.
- `no_unparsable`: the tree has no `unparsable` node, and the tool gave no
  error and exit code 0. `sqlfluff parse -f json` gives no violation codes; a
  PRS, LXR, or TMP violation gives exit code 1.

A case passes only if all its checks pass.

In the dialects suite the sqlfluff adapter uses `--templater raw`, because the sqlfluff
test does not use a templater. Extra config goes in a temporary file named `pyproject.toml`,
because sqlfluff reads a config file as TOML only with that name. It also uses
`--ignore-local-config`, because the sqlfluff test reads no config file. Without
it the CLI reads the `.sqlfluff` files in `test/fixtures/dialects/<d>/`.

## Rule cases

Rule case id: `rules/<file stem>/<key>`. [rules.md](rules.md) gives the
checks, the lists of violations that each check uses, and the comparison with
the sqlfluff test (`scripts/sqlfluff-rule-oracle`).
[not-reproduced.md](not-reproduced.md) gives the checks of the sqlfluff tests
that the harness does not reproduce.

## Autofix cases

Autofix case id: `autofix/<dialect>/<case>`. [autofix.md](autofix.md) gives
the checks and the comparison with the sqlfluff test
(`scripts/sqlfluff-autofix-oracle`). In this suite the tool reads the config
files of the case as for a user, with the sqlfluff root as the current
folder.

## Templater cases

Templater case id: `templater/<subpath>`. [templater.md](templater.md)
gives the checks, the `needs_python` tag, the fixture files that are not
cases, and the comparison with the sqlfluff test
(`scripts/sqlfluff-templater-oracle`). As in the autofix suite, the tool
reads the config files as for a user, with the sqlfluff root as the current
folder.

## Report: `out/report.json`

```json
{
  "sqlfluff_ref": "<commit of third_party/sqlfluff>",
  "scope": {"suites": [], "tools": [], "filter": null, "shard": "K/N"},
  "tools": {"<tool>": {"version": "<version>", "config": {}, "preflight": {}}},
  "summary": {"<suite>": {"<tool>": {
    "total": 0, "passed": 0, "failed": 0, "skipped": 0, "<check>": 0}}},
  "known_failures": {"<tool>": {"new_failures": [], "unexpected_passes": []}},
  "cases": [{"id": "", "suite": "", "tool": "", "status": "pass|fail|error|skip",
             "checks": {"<check>": true}, "reason": "", "duration_ms": 0,
             "tags": []}]
}
```

`config` is the config layer that the adapter adds to each case, and
`preflight` the details of the tool check. A tool has them only if they are
not empty. `scope` is what the run tried to run. A merged report has `"scope": null` and
a `parts` list with the scope of each merged report. `<check>` is the number
of cases where that check is true. A case has only the checks that apply to
it. `failed` counts `fail` and `error`. `error` means that the case did not
complete, or that the harness cannot know the result of a check. `skip`
means that the fixture skips the case; a skipped case must not be in
`known_failures/`. `tags` give facts about a case that are not results:
`needs_python` (templater suite) means that the case needs a Python
runtime.
