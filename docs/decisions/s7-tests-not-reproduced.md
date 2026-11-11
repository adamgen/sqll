# S7 asserts that the cases do not reproduce

Track S7-tests. Scope: STONES.md S7 (CLI and config parity: the sqlfluff
CLI, config, and Python rule tests as black-box cases). The trace oracle
(T3: each case agrees with a trace of its original pytest node) reads this
record. See [s7-tests-design.md](s7-tests-design.md), "Trace oracle".

Each assert of the source test of a converted node must have a check of a
case that cites it (the `asserts` map of the node), or a row in "Records".
A row gives the reason why no black-box check can reproduce the assert.

This record is a part of the not-reproduced record of PROCESS.md rule 7:
the section "S7 test conversion" of
[harness/not-reproduced.md](../../harness/not-reproduced.md) points to it
(decision 4; T4: harness hooks for the S7 suites: the harness core runs the
3 S7 suites; S7: CLI and config parity, the sqlfluff CLI, config, and
Python rule tests as black-box cases). A row is permitted only while that
pointer section exists: the oracle (`scripts/s7-tests/oracle`) and
`sqll-harness s7 run` fail if this file has a row and
`harness/not-reproduced.md` does not point to this file. They also fail if
an assert of a converted node has no check that cites it and no row here.

## Records

One row for each assert: the pytest node id, the assert id (`L<line>` or
`L<line>:<check>`, `harness/sqll_harness/s7_tests/asserts.py`), and the
reason.

| Node | Assert | Reason |
|---|---|---|

No row yet.
