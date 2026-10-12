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

## Tools

`scripts/setup` installs the pinned tools in `SQLL_TOOLS_DIR` (default
`.tools/`; `/opt/sqll/tools` in the CI image). The harness reads the same
setting. Needs: uv, Python 3.13 with a shared libpython, and cargo.

| Tool | Pin | Installed as |
|---|---|---|
| `sqlfluff` | `tools/sqlfluff/uv.lock` | `<dir>/sqlfluff` (venv) |
| `sqlfluff-rs` | `tools/sqlfluff-rs/uv.lock` | `<dir>/sqlfluff-rs` (venv with `sqlfluffrs`) |
| `sqruff` | `tools/sqruff/uv.lock` | `<dir>/sqruff/bin/sqruff` and `<dir>/sqruff/python` |

`tools/sqruff/install.sh` builds sqruff with `cargo install --locked
--features parser,python`. The `parser` feature adds the `parse` command. The
`python` feature adds the jinja, python, dbt, and sqlmesh templaters. They
import the `sqruff` Python package. The interpreter in sqruff finds it through
the first `python3` on `PATH`, so run sqruff with `tools.sqruff_env()`. The
binary links to the libpython of the Python that it was built with.

`sqll-harness tools` prints each tool as JSON: name, version, pin, binary, and
checks. It fails if a version is not the pin, if `sqlfluffrs` does not import
in the `sqlfluff-rs` venv, or if `sqruff parse` or its jinja templater does not
work. `sqll-harness run` makes the same check for the tools that it runs.

## Shards and CI

`sqll-harness run --shard K/N` runs only the cases in shard K. The shard of a
case is a hash of its id. `sqll-harness merge REPORT...` merges shard reports
into `out/report.json` and does the known-failure check again on all results.
Thus it reports a listed id that no shard ran. It fails if a shard report is
missing or is in two reports.

CI (`.github/workflows/ci.yml`):

1. `image`: `ci/image_tag.py` hashes all inputs of `ci/Dockerfile`. If
   `ghcr.io/adamgen/sqll-ci:<hash>` does not exist, CI builds and pushes it.
2. `lint`: `sqll-harness tools`, ruff, and the unit tests, in the image.
3. `test`: one job for each suite, tool, and shard in `ci/matrix.json`.
4. `report`: `sqll-harness merge --expect ci/matrix.json`. It uploads
   `out/report.json`.

To add a suite or a tool to CI, add an entry to `ci/matrix.json`.

## Suites

| Suite | Fixtures | Checks |
|---|---|---|
| `dialects` | `test/fixtures/dialects/<d>/*.sql` with `.yml` or `_nc.yml` | `exact`, `no_unparsable` |

Dialect case id: `dialects/<dialect>/<stem>` (`<stem>_nc` for `_nc.yml`).

- `exact`: the tree is equal to the YAML tree, with the sqlfluff rules
  (`process_struct`). Two trees with no children are equal. Parity uses this
  check.
- `no_unparsable`: the tree has no `unparsable` node, and the tool gave no
  error and exit code 0. `sqlfluff parse -f json` gives no violation codes; a
  PRS, LXR, or TMP violation gives exit code 1.

A case passes only if all its checks pass.

The sqlfluff adapter uses `--templater raw`, because the sqlfluff test does not
use a templater. Extra config goes in a temporary file named `pyproject.toml`,
because sqlfluff reads a config file as TOML only with that name. It also uses
`--ignore-local-config`, because the sqlfluff test reads no config file. Without
it the CLI reads the `.sqlfluff` files in `test/fixtures/dialects/<d>/`.

## Checks that are not reproduced

These checks exist only as Python internals:

- `validate_segment_with_reparse` in `test__dialect__base_file_parse`.
- The `_hash` field of the dialect YAML files. It only makes contributors use
  the generator script. The tree check is sufficient.
- `test__dialect__base_broad_fix`. It has no expected result in data.

## Report: `out/report.json`

```json
{
  "sqlfluff_ref": "<commit of third_party/sqlfluff>",
  "scope": {"suites": [], "tools": [], "filter": null, "shard": "K/N"},
  "tools": {"<tool>": {"version": "<version>"}},
  "summary": {"<suite>": {"<tool>": {
    "total": 0, "passed": 0, "failed": 0, "<check>": 0}}},
  "known_failures": {"<tool>": {"new_failures": [], "unexpected_passes": []}},
  "cases": [{"id": "", "suite": "", "tool": "", "status": "pass|fail|error",
             "checks": {"<check>": true}, "reason": "", "duration_ms": 0}]
}
```

`scope` is what the run tried to run. A merged report has `"scope": null` and
a `parts` list with the scope of each merged report. `<check>` is the number
of cases where that check is true. For `dialects`, the
checks are `exact` and `no_unparsable`. `error` means that the case did not
complete.
