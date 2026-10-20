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

Use a checkout with no sqlfluff config file in its parent folders, and a
temp folder (`TMPDIR`) with no such file in it or in its parent folders. The
tools read the config files in each folder above a case, as sqlfluff does,
and the autofix suite runs its cases in the temp folder. Thus `scripts/test`
and `scripts/verify` first run `sqll_harness/preflight.py`. It stops with
exit code 2 and names the file if one of these folders has `.sqlfluff`,
`pyproject.toml` with `[tool.sqlfluff]`, or `setup.cfg`, `tox.ini`, or
`pep8.ini` with a `[sqlfluff]` section. Example: a `pyproject.toml` with
`[tool.sqlfluff]` above the checkout gave 73 false sqruff failures.

`scripts/test` runs `scripts/setup`, writes `out/tools.json` with
`sqll-harness tools`, runs `pytest harness/tests`, then runs the suites. The
exit code is not 0 if a result is different from `known_failures/<tool>.txt`.
`scripts/check-submodule` fails if `third_party/sqlfluff` has a change or an
untracked or ignored file. `scripts/test` runs it before the tests and after
the run. CI runs it after the tests and after each shard.

`scripts/verify [--jobs N] [--quick]` runs each CI check locally: the lint job,
one unsharded run of all tools and suites, the report and dialect-oracle
checks, and the smoke benchmark (`out/bench.json`). Exit code 0 only if all
pass; details in `out/verify.json` and `out/verify/*.log`. `--quick` (fast
checks only) is not the full verification; it writes `out/verify-quick.json`
and `out/verify-quick/*.log`. Only one run at a time can use a checkout. A
warning line shows a worktree with changes.
CI-only steps (checkout, image, artifacts, shard merges, the full benchmark)
are in `CI_ONLY` in `sqll_harness/verify.py`. `tests/test_verify.py` fails if
a CI step is in no list, or if the command lines of a CI step (with its env
and matrix values) are not the same as those of its local checks. It also
fails if the run text or env of a CI-only step is not the text in
`CI_ONLY_RUN`, if a job `if`, `needs`, or `outputs`, or a step `if` or `id`,
is not the recorded one, or if CI uses a key that it does not know (for
example `shell`, `working-directory`, or `continue-on-error`) or
`defaults`. No local command and no CI run text can have `||`, `true`, or
`:`; no local command can have `--filter` or other words that can hide a
failure. The local copy of the full CI benchmark is `scripts/bench` (see
"Benchmark runs"); the test fails if its `bench run` command is not the CI
shard command without `--profile full --shard K/N --out FILE`.

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
(`scripts/sqlfluff-dialect-oracle`, `scripts/sqlfluff-rule-oracle`,
`scripts/sqlfluff-autofix-oracle`, `scripts/sqlfluff-templater-oracle`), and
`<dir>/sqlfluff-rs-oracle` for the same scripts with `--rust`.

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
rules forced on. See [sqlfluff-rs.md](sqlfluff-rs.md). The `sqruff` adapter
gives each config to sqruff as one translated `.sqruff` file. A case that
uses an item that sqruff does not support fails with the reason
`unsupported: <item>`. See [sqruff.md](sqruff.md).

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
2. `lint`: `sqll-harness tools`, ruff, the unit tests (also the case-count
   test, see [Case counts](#case-counts)), and the oracles on the harness
   dialect, rule, autofix, and templater fixtures (also with `--rust`), in
   the image.
3. `test`: one job for each suite, tool, and shard in `ci/matrix.json`.
4. `report`: `sqll-harness merge --expect ci/matrix.json`,
   `sqll-harness summarize`, then the rule, autofix, and templater oracles
   on the merged report for `sqlfluff`, and again with `--rust` for
   `sqlfluff-rs`. Then it compares `results/s1/summary.json` with the
   summary of the run (see [Summary](#summary-resultss1summaryjson)). It
   uploads `out/report.json`, `out/summary.json`, and the
   `out/*oracle.jsonl` files.
5. `dialect-oracle`: `scripts/sqlfluff-dialect-oracle` on the merged report,
   one job for `sqlfluff` and one for `sqlfluff-rs` (`--rust`). It takes some
   minutes.

To add a suite or a tool to CI, add an entry to `ci/matrix.json`.

The `changes` job runs `ci/changes.py` first. If each file that a pull
request changes is a document in its `DOCS` list (`*.md` and `harness/*.md`;
a `*` does not match `/`), CI does not run `test`, `report`, and
`dialect-oracle`. The `image` job (a registry lookup, because no document is
an image input) and `lint` always run: the unit tests read some documents,
for example STATUS.md. Each other change, a change that is not known, and
each push to main run all jobs. The full jobs run unless the `changes` job
output is `full=false`. A new pull request run stops the old run of the same
pull request. A push to main does not stop a run that has started.

`sqll-harness known-failures REPORT --tool T` prints the known-failures file
of a tool from a report (sorted ids, one reason each). With `--counts` it
prints the number of failures for each reason prefix and suite.

## Suites

| Suite | Fixtures | Checks |
|---|---|---|
| `dialects` | `test/fixtures/dialects/<d>/*.sql` with `.yml` or `_nc.yml` | `exact`, `no_unparsable` |
| `rules` | each case key in `test/fixtures/rules/std_rule_cases/*.yml` | `pass_str`, `fail_str`, `fix`, `after_fix` |
| `autofix` | each entry `test/fixtures/linter/autofix/<d>/<case>` | `tree`, `non_linting`, `violations`, `fix` |
| `templater` | each row of `test__templater_full` (`test/fixtures/templater/<subpath>.sql`) | `exact`, `no_unparsable` |
| `code_only` | the dialect cases; only for `sqlfluff` | `filter` |

`code_only` is a check of the harness, not a parity suite: the code-only
filter that the sqruff adapter uses must give the `parse -c` tree of
sqlfluff from its full tree (see [sqruff.md](sqruff.md)). A suite with
`TOOLS` runs only for those tools.

Dialect case id: `dialects/<dialect>/<stem>` (`<stem>_nc` for `_nc.yml`).
`scripts/sqlfluff-dialect-oracle` runs the sqlfluff dialect tests
(`test__dialect__base_parse_struct`, `test__dialect__base_file_parse`) on the
same cases and compares the status with the report.

- `exact`: the tree is equal to the YAML tree, with the sqlfluff rules
  (`process_struct`). Two trees with no children are equal. Parity uses this
  check.
- `no_unparsable`: the tree has no `unparsable` node, and the tool gave no
  error and exit code 0. `sqlfluff parse -f json` gives no violation codes; a
  PRS, LXR, or TMP violation gives exit code 1.

A case passes only if all its checks pass.

In the dialects suite the sqlfluff adapter uses `--templater raw`, because
the sqlfluff test does not use a templater. Extra config goes in a temporary
file named `pyproject.toml`, because sqlfluff reads a config file as TOML only
with that name. It also uses `--ignore-local-config`, because the sqlfluff test
reads no config file. Without it the CLI reads the `.sqlfluff` files in
`test/fixtures/dialects/<d>/`. The CLI also applies the in-file config lines
(`-- sqlfluff:...`) of the SQL file, and the test does not.
[not-reproduced.md](not-reproduced.md) records this difference.

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
complete, or that the harness cannot know the result of a check. A `fail`
with a reason that starts with `unsupported: ` means that the tool does not
support an item of the case (see [sqruff.md](sqruff.md)). `skip`
means that the fixture skips the case; a skipped case must not be in
`known_failures/`. `tags` give facts about a case that are not results:
`needs_python` (templater suite) means that the case needs a Python
runtime.

## Benchmark report: `out/bench.json`

The S2 report ([bench.md](bench.md)). `sqll_harness/bench/timer.py` measures,
`sqll_harness/bench/report.py` builds and checks it.

```json
{
  "kind": "sqll-bench-report",
  "format": 2,
  "sqlfluff_ref": "<commit of third_party/sqlfluff>",
  "harness": {"commit": "<commit>", "clean": true},
  "profile": "smoke|full",
  "policy": {"warmup_runs": 1, "min_runs": 3, "max_runs": 20,
             "budget_s": 2.0, "timeout_s": 120.0},
  "machine": {"cpu_model": "", "cpu_count": 4, "memory_kib": 0, "os": "",
              "kernel": "", "arch": "", "python": ""},
  "timer": {"clock": "time.perf_counter_ns", "rusage": "os.wait4",
            "overhead": {"argv": ["/bin/true"], "samples": [], "stats": {}}},
  "scope": {"tools": [], "dialects": [], "commands": [], "sizes": [],
            "shard": "K/N"},
  "tools": {"<tool>": {"version": "", "settings": {}}},
  "inputs": {"<input>": {"bytes": 0, "lines": 0, "sha256": ""}},
  "results": [{"id": "", "command": "", "dialect": "", "size": "", "input": "",
               "tool": "", "status": "valid|invalid|unsupported|error",
               "reason": "", "runs": {"warmup": 1, "timed": 3}, "work": {},
               "samples": [{"kind": "warmup|timed", "wall_s": 0.0,
                            "user_s": 0.0, "sys_s": 0.0, "max_rss_kib": 0,
                            "exit_code": 0, "timed_out": false}],
               "stats": {"wall_s": {"n": 3, "median": 0.0, "min": 0.0,
                                    "max": 0.0, "mad": 0.0},
                         "cpu_s": {}},
               "ratio": {"wall": 0.0, "cpu": 0.0}}],
  "totals": {"<tool>": {"valid": 0, "invalid": 0, "unsupported": 0,
                        "error": 0, "wall_s": 0.0, "cpu_s": 0.0}},
  "pairs": [{"tools": ["<a>", "<b>"], "benchmarks": 0, "skipped": 0,
             "wall_s": [0.0, 0.0], "cpu_s": [0.0, 0.0], "wall_ratio": 0.0}],
  "parts": [{"shard": "K/N", "machine": {}, "timer": {}}]
}
```

- `harness.clean`: the worktree had no change. `policy`: the policy of the
  profile. `memory_kib` can be null. `scope` is what the run tried to run
  (before the shard); `scope.shard` is null for a run of all shards.
- `id`, `command`, `dialect`, `size`, and `input` are those of the
  definitions; `size` is null for `start`. `input` is a key of `inputs`.
- Times are in seconds, `max_rss_kib` in KiB (`ru_maxrss`). CPU time
  (`cpu_s`) is user and system time. A negative `exit_code` is a signal.
- `status`: `valid` (the warmup run passed its check, and each timed run
  has its exit code); `invalid` (a check failed, an exit code is wrong, or
  a timeout; `reason` says which); `unsupported` (the tool does not
  support the benchmark); `error` (the harness could not run it).
- `stats` (n, median, min, max, MAD) are of the timed samples only, not of
  the warmup. Only a `valid` result has `stats` and no `reason`. Other
  results keep their samples (often only the warmup), with `stats` null.
- `work`: null, or the facts that the validity check of the tool found:
  `lint` `{"violations": 0, "codes": []}`, `fix` `{"changed": true,
  "fixed_sha256": ""}`.
- `totals`: for each tool, the count of each status, and the sums of the
  median times of its `valid` results. `pairs`: for each 2 tools, the sums
  over the benchmarks where both are `valid`; `skipped` counts the other
  benchmarks of the 2 tools. `wall_ratio` is the first sum divided by the
  second (null if it is 0).
- `ratio`: the median wall and CPU times of the result divided by those of
  the `sqlfluff` result of the same benchmark in the same report (null if
  the divisor is 0). It is null for `sqlfluff`, and if the result or the
  `sqlfluff` result is not `valid`.
- `parts`: null for one run. A merged report has one part for each shard,
  in order, and `scope.shard` null; its `machine` and `timer` are those of
  part 1.

`report.check()` refuses a missing or unknown field, an unknown status, a
`valid` result with no stats, a number of timed runs outside the policy,
and stats, totals, pairs, or ratios that are not those of the samples.
`write()` writes only a report with no error.

## Summary: `results/s1/summary.json`

`sqll-harness summarize out/report.json` writes the summary of a full-run
report to `out/summary.json` (or `--out`). With `--check FILE`, the exit
code is 1 if FILE does not have the same text as the new summary. The
command compares before it writes, and FILE must not be the `--out` file
(exit code 2). It refuses a report with a filter, a single shard, a repeated
case, a missing or extra suite or tool, or no known-failure check result for
a tool (exit code 2).

The summary has only counts. Thus `--check` finds a change of a count, but
not a swap of status between 2 cases or a changed case id. The run (and
`merge`) checks each case id against `known_failures/`, and the oracles
check each case id of sqlfluff and `sqlfluff-rs`.

The summary has `sqlfluff_ref`, the record of each tool from the report
(`version`, `config`, `preflight`), and for each tool:

- `parity`: `total` and `passed` over the 4 parity suites. `code_only` is a
  check of the harness and is not in it.
- `known_failures_check`: the number of new failures and unexpected passes
  of the known-failure check.
- `suites`: for each suite `total`, `passed`, `failed`, `error`, `skipped`
  (their sum is `total`; here `failed` does not include `error`), the
  number of cases where each check is true (`checks`), and for each tag the
  number of cases and of passed cases (`tags`; `needs_python` is always
  there).

To record new results, copy `out/summary.json` to
`results/s1/summary.json`. Get it from the `report` artifact of CI or from a
full local run (`scripts/verify`). `harness/tests/test_recorded_summary.py`
checks that the recorded summary, `known_failures/`, and the tables in
STATUS.md agree.

## Case counts

`harness/tests/test_case_counts.py` proves that the harness finds the cases
that the pinned sqlfluff tests collect. `scripts/sqlfluff-case-ids` (run
with the Python of `tools/sqlfluff-oracle`) runs `pytest --collect-only` on
the sqlfluff submodule and prints the parameter id of each case of these
tests. The unit test makes the same id from each harness case and compares
the 2 lists, with repeats:

| Suite | sqlfluff test | Cases in 4.4.0 |
|---|---|---|
| `dialects` | `test/dialects/dialects_test.py::test__dialect__base_parse_struct` | 2306 |
| `rules` | `test/rules/yaml_test_cases_test.py::test__rule_test_case` | 2527 |
| `autofix` | `test/rules/std_fix_auto_test.py::test__std_fix_auto` | 61 |
| `templater` | `test/core/templaters/jinja_test.py::test__templater_full` | 43 |

The total is 4937. `test__dialect__base_file_parse` also has 2306 cases,
one for each dialect SQL file. In 4.4.0 the rule test gives 3 ids to 2 cases
each (`LT01-literals.yml` and `LT01-operators.yml` have the same keys);
pytest adds `0` and `1` to them. The harness ids have the file name, so they
are unique.

## Benchmark inputs

[bench.md](bench.md) gives the S2 design.
`sqll-harness bench inputs [--out DIR]` builds the benchmark inputs from the
dialect fixtures (read in place) and writes `DIR/start.sql`,
`DIR/<dialect>/<small|medium|large>.sql`, and `DIR/manifest.json`. The
default `DIR` is `out/bench/inputs`. It refuses a folder in the repository
that is not below `out/`, and a folder that is not empty and has no earlier
build (exit code 2). It replaces an earlier build. The exit code is 1 if a
build is not equal to the definitions.

- `sqll_harness/bench/exclusions.txt`: the frozen list of fixture files that
  the inputs do not use, with a reason for each (the format of
  `known_failures/`).
- `sqll_harness/bench/definitions.json`: the definitions. They have no tool
  entry. `format`, `sqlfluff_ref`, `sizes` (target bytes), `selection`
  (file counts for each skip reason, and the number of added terminators
  and new lines), `inputs` (`bytes`, `lines`, `sha256` of each input),
  `reference` (`sqlfluff_version`, and for each input except
  `start`: `sha256`, `lint_codes`, `fix_changes`; see "Benchmark
  adapters"), and `benchmarks` (`id`, `command`, `dialect`, `size`,
  `input`). A `start`
  benchmark runs the `parse` command of the tool on the `start` input
  (`SELECT 1;`).
- `manifest.json`: the same data for each input, plus `files` (the fixture
  files in input order, with repeats), `passes`, and `repeats`, and the
  skipped and changed files of the selection.

A dialect that has no input stops the build (exit code 2). After a change
to the builder, the exclusion list, or the fixtures, the unit tests fail
until `sqll-harness bench inputs --write-definitions` writes new
definitions. A change of the fixtures needs a human approval (a new sqlfluff
pin).

## Benchmark adapters

`sqll_harness/bench/adapter.py` has the validity checks of
[bench.md](bench.md) and `BenchAdapter`; `tools.py` has the adapters, and
`registry.py` the tools. Each job runs in `<work>/<tool>/<id>/`: `config/`
has the config file, `runs/<warmup|1|2...>/` a fresh copy `input.sql` of
the input. The input must have the sha256 of the definitions.

| Tool | Command (`start` is `parse` of `start.sql`) |
|---|---|
| `sqlfluff`, `sqlfluff-rs` | `sqlfluff parse -f json`, `lint -f json`, or `fix`, then `--ignore-local-config --config config/pyproject.toml input.sql` |
| `sqruff` | `sqruff parse -f json`, `lint -f json --parsing-errors`, or `fix -f human`, then `--config config/.sqruff input.sql` |

The env is that of S1 (`isolated_env`, empty `HOME`; sqruff:
`sqruff_env`). A config file that sqlfluff or sqruff can read in the work
folder or above it stops the run (`ConfigAbove`). A dialect or setting that
the tool does not support gives `unsupported: <item>` and no run (sqruff:
`dialect soql`).

`sqll-harness bench reference [--write] [--jobs N]` builds the inputs and
runs sqlfluff `fix` (and thus `lint` and `parse`) on each input with the
checks, but with no reference comparison. It writes the rule codes and the
fix change of each input to `reference` in the definitions (`--write`), or
fails (exit code 1) if they are not the recorded ones. A run that is not
valid gives no reference (exit code 1). `bench inputs` fails if an input
has no reference for its sha256.

## Benchmark runs

```sh
scripts/bench                      # the full report of all tools: out/bench.json
scripts/bench --profile smoke      # start and small, 1 timed run
sqll-harness bench run --tool sqruff --dialect ansi --command lint --size large
sqll-harness bench run --profile smoke --shard 2/4 --out out/bench-2.json
sqll-harness bench merge out/bench-*.json --out out/bench.json
sqll-harness bench check out/bench.json
```

`sqll-harness bench run [--tool T] [--dialect D] [--command C] [--size S]
[--profile smoke|full] [--shard K/N] [--out FILE]` (each filter can repeat;
the default is all) runs the benchmarks of the definitions and writes the
report (default `out/bench.json`). The default profile is `full`; `smoke`
has only `start` and `small`. First it runs the tool check of
`sqll-harness tools`, then builds the inputs in a temp folder and compares
them with the definitions. The benchmarks run one at a time. For each
benchmark, each tool does its warmup run, then the tools do their timed
runs in turn (sorted tool names). The shards divide the dialects of the
scope (sorted; dialect `i` from 0 is in shard `i % N + 1`), so all
benchmarks of a dialect are in one shard. Each input other than `start` is
in one shard; `start` is in each shard that has a `start` benchmark. It
prints one line for each benchmark on stderr, and a summary: the status
counts of each tool, the median ratio to `sqlfluff` of each command, the
pairs, and each result that is not `valid`.

Exit code: 2 if the scope is bad, a tool check fails, the inputs are not
those of the definitions, or a config file is above the work folder (no
report); 1 if the report has a schema error (no report), or if it does not
have exactly one result for each benchmark of its scope and each tool, and
the inputs of the definitions.
A result that is not `valid` does not change the exit code. This command
does not compare the statuses with a baseline.

`sqll-harness bench merge [--expect MATRIX_JSON] REPORT...` merges the
reports of the shards of one run, as `sqll-harness merge` does for S1. It
fails (exit code 2) if a report has a schema error or is not complete, if a
shard is missing or in two reports, if 2 reports have a different sqlfluff
ref, harness, profile, scope (other than the shard), tool record, or input
record, or if the shard count is not the `shards` of `--expect`
(`{"shards": N}`, as `ci/bench-matrix.json`).
`sqll-harness bench check REPORT` runs the schema and completeness checks
(exit code 1 on an error).

`scripts/bench [ARGS]` is the one command of the S2 exit: the preflight,
`scripts/setup`, `sqll-harness tools` (`out/tools.json`),
`scripts/check-submodule`, `sqll-harness bench inputs` (an early check of
the inputs; `bench run` builds and checks them again), `sqll-harness bench
run ARGS`, and
`scripts/check-submodule` again. The exit code is not 0 if a step fails.

### Benchmarks in CI

| Job | When | Command | Artifact |
|---|---|---|---|
| `bench-smoke` | each full run (pull request with a code change, push to main, `workflow_dispatch`) | `bench run --profile smoke --out out/bench.json` | `bench-smoke` |
| `bench-full` | push to main, `workflow_dispatch` | `bench run --profile full --shard K/N`, one job for each shard of `ci/bench-matrix.json` (`ci/bench_matrix.py`) | `bench-shard-K-of-N` |
| `bench-merge` | after all `bench-full` jobs pass | `bench merge --expect ci/bench-matrix.json`, then `bench check` | `bench-full` (`out/bench.json`) |

Each job runs in the CI image. `bench-smoke` and `bench-full` run
`scripts/check-submodule` after the benchmarks. No job compares timings ("Noise control" in
[bench.md](bench.md)). Locally, `scripts/verify` runs the smoke job, and
`scripts/bench` (no arguments) is the full benchmark of all shards in one
report.
