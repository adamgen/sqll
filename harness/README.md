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

`scripts/test` installs the tool environments (`tools/<tool>/` to
`.tools/<tool>/`), runs `pytest harness/tests`, then runs the suites. The exit
code is not 0 if a result is different from `known_failures/<tool>.txt`.

## Layout

- `sqll_harness/adapters/`: one adapter for each tool. An adapter starts the tool
  as a subprocess. The current directory is `third_party/sqlfluff`. `HOME` and
  `XDG_CONFIG_HOME` point to an empty directory.
- `sqll_harness/suites/`: one module for each fixture type.
- `sqll_harness/compare.py`: tree comparison, ported from sqlfluff.
- `known_failures/<tool>.txt`: one case id on each line, sorted. Text after `#`
  is the reason.

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
because sqlfluff reads a config file as TOML only with that name.

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
  "tools": {"<tool>": {"version": "<version>"}},
  "summary": {"<suite>": {"<tool>": {
    "total": 0, "passed": 0, "failed": 0, "<check>": 0}}},
  "known_failures": {"<tool>": {"new_failures": [], "unexpected_passes": []}},
  "cases": [{"id": "", "suite": "", "tool": "", "status": "pass|fail|error",
             "checks": {"<check>": true}, "reason": "", "duration_ms": 0}]
}
```

`<check>` is the number of cases where that check is true. For `dialects`, the
checks are `exact` and `no_unparsable`. `error` means that the case did not
complete.
