# S7 asserts that the cases do not reproduce

Track S7-tests. Scope: STONES.md S7 (CLI and config parity: the sqlfluff
CLI, config, and Python rule tests as black-box cases). The trace oracle
(T3: each case agrees with a trace of its original pytest node) reads this
record. See [s7-tests-design.md](s7-tests-design.md), "Trace oracle".

Each assert of the source test of a converted node must have a check of a
case that cites it (the `asserts` map of the node), or a row in "Records".
A row gives the reason why no black-box check can reproduce the assert.

This record is not yet part of the not-reproduced record of PROCESS.md
rule 7. It becomes part of it when the pointer section in
`harness/not-reproduced.md` merges (decision 4: the cross-track T4 or T5
pull request). Before that, no case may use a row. The oracle
(`scripts/s7-tests/oracle`) fails if this file has a row and
`harness/not-reproduced.md` does not point to this file.

## Records

One row for each assert: the pytest node id, the assert id (`L<line>` or
`L<line>:<check>`, `harness/sqll_harness/s7_tests/asserts.py`), and the
reason.

| Node | Assert | Reason |
|---|---|---|

No row yet.
