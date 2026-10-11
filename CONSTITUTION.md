# sqll Constitution

sqll is a SQL toolchain. It parses, lints, fixes, and generates code from SQL.
The readers of this document are AI agents.

## 1. Goals

### G1. Lint parity with sqlfluff

1. sqll must do all that sqlfluff does: dialects, rules, fixes, configuration, and templaters.
2. The target is one pinned sqlfluff version. A human approves each version change.
3. Exclusions: Python plugins, and features that need a Python runtime.
4. Parity is a number: the percentage of sqlfluff test cases that sqll passes.
5. The harness runs each test case through a binary, not through function calls.
6. The same harness runs sqlfluff, sqruff, and sqll. Thus the results are comparable.

### G2. Code generation

1. sqll generates typed code from SQL, as sqlc does.
2. sqll must support each parameter style and templater that G1 supports.
3. Code generation and linting use the same parser.

### G3. Speed

1. Each command must be as fast as reasonably possible. This includes start time.
2. Each command has a benchmark.
3. Each benchmark measures sqlfluff, sqruff, and sqll on the same input.
4. sqll must be faster than sqlfluff and sqruff on each benchmark.
5. A change that makes a benchmark slower must give the reason in the change record.

### G4. Verification first

1. Each behavior has an automated test.
2. Take tests from external sources. Start with sqlfluff. Then add large, complex SQL files from public sources.
3. Record the source, version, and license of all external test data.
4. One command runs all tests and benchmarks. The output is machine-readable.
5. Do not change external test data to make a test pass. Record each known failure in a list.

### Conflicts

Correctness is more important than speed. Do not make a result wrong to make it fast.

## 2. Rules for agents

1. Read this document and STONES.md before you start work.
2. Use ASD-STE100 Simplified Technical English for all text: documents, commit messages, pull requests, code comments, and messages to humans.
3. Write only what the reader needs. Do not over communicate.
4. Each canonical document must be short. A human must read it in 5 minutes or less.
5. Do not say that work is complete without proof. Proof is harness output: tests pass and benchmarks do not become slower.
6. Keep the license and attribution of all ported code and test data.

## 3. References

These links show what we aim for. They are not goals.

- sqlfluff: https://sqlfluff.com/
- sqruff: https://github.com/quarylabs/sqruff
- sqlc: https://sqlc.dev/
- ASD-STE100: https://www.asd-ste100.org/

## 4. Changes to this document

This document must not change frequently.
An agent can propose a change. Only a human owner can approve it.
