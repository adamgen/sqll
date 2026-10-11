# sqll Stones

Stones are milestones. Do them in sequence. Each stone has exit criteria.
A stone is complete only when the harness shows that all exit criteria are true.

## S1. Binary test harness

Run the sqlfluff test suite through a binary, not through function calls.

- Pin one sqlfluff version.
- Extract the dialect parse fixtures and the rule fixtures (lint and fix) into a format that does not need Python.
- Define the binary interface: input SQL, configuration, dialect. Output: parse tree, violations, fixed SQL.
- Write an adapter for sqlfluff and an adapter for sqruff.
- Exit: sqlfluff passes 100% of the extracted cases through the harness. The sqruff result is recorded.

## S2. Benchmarks

- Make a benchmark for each command: start, parse, lint, fix.
- Use small, medium, and large inputs for each dialect.
- Exit: one command gives a machine-readable report for sqlfluff and sqruff. The baseline is recorded.

## S3. Port sqruff

- Make the sqll binary from sqruff. Keep its license and attribution.
- Exit: sqll passes all cases that sqruff passes. sqll is not slower than sqruff on any benchmark.

## S4. Parser parity

- Exit: sqll passes 100% of the dialect parse fixtures.

## S5. Rule parity

- Exit: sqll passes 100% of the rule fixtures, lint and fix.

## S6. Templater parity

- Support the Jinja, placeholder, and Python format-string templaters.
- Exit: sqll passes 100% of the templater fixtures that do not need a Python runtime.

Full parity (G1) is S4, S5, and S6 complete.

## S7. Code generation

- Read the schema from DDL files.
- Find the types of query parameters and result columns.
- Support each parameter style and templater from S6.
- Generate code for a first target language.
- Lint and code generation in one command parse each file one time.
- Exit: generated code compiles and passes tests for each parameter style.
- Exit: the harness shows one parse for each file when one command lints and generates code.

## S8. External corpus

- Collect large, complex SQL files from public sources. Record source and license.
- Exit: the report shows parse success and speed for each file, for sqlfluff, sqruff, and sqll.

## S9. PL/pgSQL bodies

sqlfluff does not parse the body of PostgreSQL functions. sqll will.

- Parse and lint SQL in PL/pgSQL function bodies.
- Exit: a test set of PL/pgSQL functions parses with no unparsable segments.
