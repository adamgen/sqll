# S3b status (Core track)

S3b (STONES.md) is in work in the Core track. S3 is approved (human
owner, 2026-11-06). The Core track work comes first: C1 and C2.

## Tasks

| Task | Description | State |
|---|---|---|
| C1 | Record the S3 approval and the standing delegation; freeze the inputs of the S3 exit record | Merged (PR #57) |
| C2 | `bench compare`: a table for each benchmark when it compares tools of one report | In review |

Open: the plan of the other S3b parts (the lossless tree, the source map,
the interfaces, the CLI skeleton, and the code layout).

## C2: sqll and sqlfluff in the S2 baseline

`sqll-harness bench compare results/s2/baseline.json --tool sqll --tool
sqlfluff` (`harness/bench.md`, "Back-to-back comparison"). The ratio is
sqlfluff / sqll of the median wall times. sqll has only `start` and
`parse`: 168 benchmarks are left out (`unsupported`).

| Group | Benchmarks | sqll (s) | sqlfluff (s) | Ratio of the sums | Min | Median | Max | sqll faster |
|---|---|---|---|---|---|---|---|---|
| start | 28 | 0.1650 | 15.7311 | 95.330 | 71.628 | 101.515 | 130.030 | 28 |
| parse/small | 28 | 0.2606 | 17.1020 | 65.629 | 48.641 | 67.258 | 87.298 | 28 |
| parse/medium | 28 | 0.4505 | 21.8629 | 48.529 | 37.079 | 48.637 | 65.636 | 28 |
| parse/large | 28 | 1.2630 | 43.5264 | 34.463 | 30.741 | 34.522 | 40.207 | 28 |
| total | 112 | 2.1391 | 98.2224 | 45.918 | 30.741 | 57.270 | 130.030 | 112 |

`harness/tests/test_bench_compare.py` makes this table again from the
baseline and compares it with this file.
