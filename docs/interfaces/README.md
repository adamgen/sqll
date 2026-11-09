# Frozen interfaces

The shared core of sqll (S3b) has these frozen interfaces. Each has one
document in this folder and one test in `crates/sqll_interfaces/tests/`.
Design: [s3b-core.md](../decisions/s3b-core.md).

| Interface | Task | Packages | Document | Test |
|---|---|---|---|---|
| Segment kinds | C6 | `sqll_tree` | [segment-kinds.md](segment-kinds.md) | `crates/sqll_interfaces/tests/segment_kinds.rs` |
| Syntax tree | C7 | `sqll_tree`, `sqll_syntax` | [tree.md](tree.md) | `crates/sqll_interfaces/tests/tree.rs` |
| Source map | C8 | `sqll_source`, `sqll_templater` (S6) | [source-map.md](source-map.md) | `crates/sqll_interfaces/tests/source_map.rs` |
| Parse | C9 | `sqll_syntax` | [parse.md](parse.md) | `crates/sqll_interfaces/tests/parse.rs` |
| Typed view | C10 | `sqll_tree` | [typed-view.md](typed-view.md) | `crates/sqll_interfaces/tests/typed_view.rs` |
| Config | C11 | `sqll_config` | [config.md](config.md) | `crates/sqll_interfaces/tests/config.rs` |
| Rules and fixes | C12 | `sqll_lint`, `sqll_rules` (S5) | [rules.md](rules.md) | `crates/sqll_interfaces/tests/rules.rs` |
| Tree to schema | C15 | `sqll_schema`, `sqll_codegen` (S8) | [schema.md](schema.md) | `crates/sqll_interfaces/tests/schema.rs` |

## Ownership

`tracks.yml` gives the owner of each path (PROCESS.md, "Tracks"; design
Q5):

- The Core track owns this folder, `crates/sqll_interfaces/`, each
  `Cargo.toml` and `build.rs`, and the Core packages.
- A later track owns `src/**` and `tests/**` of its packages: S4
  `sqll_parser` and `sqll_dialects`, S5 `sqll_rules`, S6
  `sqll_templater`, S7-sqll `sqll_cli`, S8 `sqll_codegen`, and S10
  `sqll_plpgsql`.

Thus a change to an interface, a dependency, or a build step needs a Core
track pull request. A later track asks for it with an issue.

## Rules for a change

- Change the document and the test of an interface in the same Core pull
  request.
- A new frozen interface adds its row to the table above.
  `harness/tests/test_s3b_interfaces.py` checks that each document and
  test in the table exists, that each document names its test, and that
  each document and test file of the interfaces is in the table.
  `harness/tests/test_ownership.py` checks that the Core track owns them.
