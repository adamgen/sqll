# sqll Stones

Stones are milestones. Each stone has exit criteria.
A stone is complete only when the harness shows that all exit criteria are true.
A human approves each completed stone.

Each stone lists the stones that it needs ("Needs:"). A stone starts when
each stone that it needs is approved. Stones that do not need each other
can run in parallel (PROCESS.md, "Tracks").

## S1. Binary test harness

Needs: none.

Run the sqlfluff test fixtures through a binary, not through function calls.

- Add sqlfluff as a git submodule, pinned to the tag `4.4.0`.
- Read the fixtures where they are. Do not copy or change them.
- Start with the 4 fixture types that store the expected output as data:
  - `test/fixtures/dialects/`: parse trees.
  - `test/fixtures/rules/std_rule_cases/`: lint and fix cases.
  - `test/fixtures/linter/autofix/`: fix cases.
  - `test/fixtures/templater/`: templater cases.
- A rule case is a YAML key, not a file. Write its SQL and its config to temporary files when the harness runs.
- Write adapters for sqlfluff, sqlfluff with the Rust parser (`sqlfluff[rs]`), and sqruff.
- Report 2 parse numbers: an exact tree match, and "no unparsable segments". Parity uses the exact match.
- Exit: sqlfluff passes 100% of the cases through the harness. The results of the other tools are recorded.

## S2. Benchmarks

Needs: S1.

- Make a benchmark for each command: start, parse, lint, fix.
- Use small, medium, and large inputs for each dialect.
- Exit: one command gives a machine-readable report for sqlfluff, `sqlfluff[rs]`, and sqruff. The baseline is recorded.

## S3. Choose the base

Needs: S1, S2.

Compare 3 bases with the S1 and S2 data:

- sqruff: all rules exist. Its parser is a manual port, so its trees are different.
- sqlfluffrs: its parser is generated from the sqlfluff grammar. Only 3 rules exist. It is not a standalone tool.
- A new parser with a grammar generated from the sqlfluff dialects.

Then:

- Record the decision and the data. A human approves the decision.
- Make the sqll binary from the base. Keep the license and attribution of all ported code.
- Exit: sqll passes all cases that the base passes. sqll is not slower than sqruff on any benchmark.

## S3b. Core

Needs: S3.

Make the shared core that the later stones use.

- One lossless syntax tree: each byte of the source, positions, segment
  types, and a typed view. It can print the sqlfluff tree format for the S1
  harness.
- The source map between the templated text and the source text.
- Frozen interfaces: lexer to parser to tree; tree to rules to fixes;
  templater to source map; tree to schema for code generation.
- The sqll binary skeleton: CLI, config, and output formats. The sqll
  adapters of the S1 harness and the S2 benchmarks.
- A code layout with one package for each part.
- Exit: the S1 harness and the S2 benchmarks run sqll through its adapters.
- Exit: the interfaces are documented.
- Exit: after S3b, each change to the core goes through the Core track.

## S4. Parser parity

Needs: S3b.

- Exit: sqll passes 100% of the dialect parse fixtures with an exact tree match.

## S5. Rule parity

Needs: S3b. For each dialect, also the S4 trees of that dialect before its rules.

- Exit: sqll passes 100% of the rule fixtures, lint and fix.

## S6. Templater parity

Needs: S3b.

- Support the Jinja, placeholder, and Python format-string templaters.
- Exit: sqll passes 100% of the templater fixtures that do not need a Python runtime.

## S7. CLI and config parity

Needs: the test conversion needs S1. The sqll part needs S3b.

The expected results of these tests are in Python code. Write them as black-box cases.

- Convert the tests in `test/cli/`, the config fixtures, and the Python rule tests in `test/rules/`.
- Exit: sqll passes 100% of the converted cases.

Full parity (G1) is S4, S5, S6, and S7 complete.

## S8. Code generation

Needs: S4, S6.

- Read the schema from DDL files.
- Find the types of query parameters and result columns.
- Write them as JSON Schema. Existing tools make code in each language from it.
- Support each parameter style and templater from S6.
- Lint and code generation in one command parse each file one time.
- Exit: the JSON Schema output is valid and correct for each parameter style.
- Exit: code made from the schema by one existing tool compiles.
- Exit: the harness shows one parse for each file when one command lints and generates code.

## S9. External corpus

Needs: S1. The sqll results need S3b.

- Collect large, complex SQL files from public sources. Record source and license.
- Exit: the report shows parse success and speed for each file, for each tool.

## S10. PL/pgSQL bodies

Needs: S4.

sqlfluff does not parse the body of PostgreSQL functions. sqll will.

- Parse and lint SQL in PL/pgSQL function bodies.
- Exit: a test set of PL/pgSQL functions parses with no unparsable segments.
