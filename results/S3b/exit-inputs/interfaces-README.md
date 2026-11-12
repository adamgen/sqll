# Frozen interfaces

The shared core of sqll (S3b) has these frozen interfaces. Each has one
document in this folder and one test in `crates/sqll_interfaces/tests/`.
Design: [s3b-core.md](../decisions/s3b-core.md).

| Interface | Task | Packages | Document | Test |
|---|---|---|---|---|
| Segment kinds | C6 | `sqll_tree` | [segment-kinds.md](segment-kinds.md) | `crates/sqll_interfaces/tests/segment_kinds.rs` |
| Syntax tree | C7 | `sqll_tree`, `sqll_syntax` | [tree.md](tree.md) | `crates/sqll_interfaces/tests/tree.rs` |
| Source map | C8 | `sqll_source`, `sqll_templater` (S6, templater parity) | [source-map.md](source-map.md) | `crates/sqll_interfaces/tests/source_map.rs` |
| Parse | C9 | `sqll_syntax` | [parse.md](parse.md) | `crates/sqll_interfaces/tests/parse.rs` |
| Typed view | C10 | `sqll_tree` | [typed-view.md](typed-view.md) | `crates/sqll_interfaces/tests/typed_view.rs` |
| Config | C11 | `sqll_config` | [config.md](config.md) | `crates/sqll_interfaces/tests/config.rs` |
| Rules and fixes | C12 | `sqll_lint`, `sqll_rules` (S5, rule parity) | [rules.md](rules.md) | `crates/sqll_interfaces/tests/rules.rs` |
| Tree to schema | C15 | `sqll_schema`, `sqll_codegen` (S8, code generation) | [schema.md](schema.md) | `crates/sqll_interfaces/tests/schema.rs` |

## Ownership

`tracks.yml` gives the owner of each path (PROCESS.md, "Tracks"; design
Q5):

- The Core track (S3b, the shared core) owns this folder,
  `crates/sqll_interfaces/`, each `Cargo.toml` and `build.rs`, the other
  files of the table generator of `sqll_dialects` (`build/` and
  `generated.json`), the port record `crates/ported.json`, and the Core
  packages.
- A later track owns `src/**` and `tests/**` of its packages: S4 (parser
  parity) `sqll_parser` and `sqll_dialects`, S5 (rule parity)
  `sqll_rules`, S6 (templater parity) `sqll_templater`, S7-sqll (CLI and
  config parity, the sqll part) `sqll_cli`, S8 (code generation)
  `sqll_codegen`, and S10 (PL/pgSQL bodies) `sqll_plpgsql`.

Thus a change to an interface, a dependency, or a build step needs a Core
track pull request. A later track asks for it with an issue.

A later track also changes the Core file `crates/ported.json` when it adds
a file to its package or changes a ported file for the first time
(`harness/tests/test_sqll_ported.py` checks that each file under
`crates/` is in the record, and it lists each changed ported file). That pull request needs the label
`cross-track` and a Core review of the record. The reason: the record
keeps the license and attribution of the ported code (CONSTITUTION.md,
"Rules for agents"). This is a limit of design Q5 (C16, the package
ownership of the later tracks and the interface index).

## Rules for a change

- Change the document and the test of an interface in the same Core pull
  request.
- A new frozen interface adds its row to the table above.
  `harness/tests/test_s3b_interfaces.py` checks that each document and
  test in the table exists, that each document names its test, and that
  each document and test file of the interfaces is in the table.
  `harness/tests/test_ownership.py` checks that the Core track owns them.
