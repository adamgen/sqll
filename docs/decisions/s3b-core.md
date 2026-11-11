# S3b core design

Status: decided (Core track, task C4). It answers the "Open interface
questions for S3b" of [s3-exit.md](s3-exit.md).

## Data

Each number is in a sentence ("claims") of
[`results/S3b/C4-record.json`](../../results/S3b/C4-record.json), with
the source file and key of each value
(`scripts/s3b/core_design.py record`; drift test
`harness/tests/test_s3b_core.py`). The tree numbers are from
[`results/S3b/C4-tree-cost.json`](../../results/S3b/C4-tree-cost.json)
(`scripts/s3b/core_design.py measure`; `--check` makes them again): the
tool `scripts/s3b/tree-cost` parses the 84 S2 parse inputs as
`sqll parse` does and counts heap blocks and bytes.

The 84 inputs have 601133 bytes of SQL and 280339 tree nodes:

| Tree | Heap blocks | MB |
|---|---|---|
| `Node` tree of the parser (a clone, a lower bound) | 1806330 | 100.7 |
| `Arena`, made from the `Node` tree | 1989881 | 196.3 |
| Flat tree, estimate with a 24-byte node record | 4 for each tree | 8.5 |

- The `Node` tree uses 359 bytes and 6.4 heap blocks for each node (167
  bytes for each byte of SQL); it keeps text and static data as strings.
- The flat tree is 12 times smaller (an estimate; C7 measures it).
- The tree has 12% of the 14455867 heap blocks that the parse asks for.
- A kind is one distinct static data of a node: variant, class, type,
  instance types, class types, and segment kwargs. The 84 trees have 790
  kinds: 177 leaf, 609 segment, and 4 meta kinds.
- 65 type names have more than one kind (for example `quoted_literal`),
  and 5119 leaves have segment kwargs. Thus a type name is not a kind.

## Answers

### Q1. Tree type

Decision: a new crate `sqll_tree` with a flat, immutable, lossless
`SyntaxTree`:

- All nodes are in one `Vec`, in source order. A node id is an index.
- Each node has a `SegmentKind` (`u16`, one kind), a byte range into one
  buffer of the templated text, its parent, and its child range. A leaf
  holds no `String`. A line index gives the line and position of a byte.
- A static table, not the node record, keeps the data of each kind.
- A template placeholder has no templated bytes: the source map keeps its
  source text (`source_str`). The expected text of an unparsable node
  goes to `Parsed.errors`.
- `sqll_syntax` makes it from the `Node` tree; the base parser does not
  change. `Node` and `Arena` stay: 8 of the 162 native base tests test
  the `Arena`. New code does not use it.

Reason: the data above; kinds keep all static data and give the typed
view that G2 needs. The leaves of each of the 84 trees give their input
again (the tool checks this), so one text buffer keeps each byte. Limit:
the inputs use the raw templater (0 template meta nodes); C8 tests
placeholders. Risk: the conversion adds work; C7 measures it (C5).

### Q2. Source map

Decision: the ported `TemplatedFile` (`sqll_types`) is the frozen
interface from the templater to the source map. The Core crate
`sqll_source` has a `Templater` trait that gives a `TemplatedFile`, and
the source map. Change (C8 task text, 2026-11-07): the raw templater is
in `sqll_templater`.

Reason: the lexer already takes `TemplatedFile`, a port of the sqlfluff
type; S6 needs no new type.

### Q3. Lexer to parser to tree

Decision: one function in the Core crate `sqll_syntax`:
`parse(&TemplatedFile, Dialect, &ParseOptions) -> Parsed { tree, errors }`.
It lexes, parses, and makes the `SyntaxTree`. `sqll parse` prints the
sqlfluff tree format from it with no output change. Change (C9):
`Result<Parsed, ParseError>`; `tree` is an `Option`
([parse.md](../interfaces/parse.md)).

Reason: the rules, the code generation, and the CLI call one function;
S4 can change the parser with no change to them.

### Q4. Rule and fix interface

Decision: a new Core crate `sqll_lint`:

- A `Rule` trait: code, name, groups, config keys, and a `lint` function
  over the typed view.
- A `LintResult`: an anchor node, a description, and fixes. A fix is a
  list of edits (a templated byte range and its new text). The source map
  changes each edit to a source edit, or refuses it.
- A fix loop: fix, parse, and lint again, up to the sqlfluff
  `runaway_limit` (10 loops).
- Fail closed: a rule or a setting that sqll does not have gives
  "unsupported" and exit code 2.

C12 moves CP01, CP03, and CP04 (`sqll_rules`) to it as the proof.

Reason: the rules read kinds, not type strings. Byte range edits let
the source map handle templated files (S6) with no rule change.

### Q5. Ownership

Decision: a track owns `src/**` and `tests/**` of its packages (table).
Core keeps each `Cargo.toml`, `build.rs`, `Cargo.lock`, and the interface
tests (`crates/sqll_interfaces`). C16 writes this into `tracks.yml`;
until then, Core owns `crates/**` (C3).

Reason: a later track changes its own code without Core review, but not an
interface, a dependency, or a build step (S3b exit).

| Package | Owner | Content |
|---|---|---|
| `sqll_types` | core | tokens, `TemplatedFile` |
| `sqll_lexer` | core | lexer |
| `sqll_tree` | core | kinds, `SyntaxTree`, typed view (C6, C7, C10) |
| `sqll_source` | core | `Templater`, source map (C8) |
| `sqll_syntax` | core | `parse` (C9) |
| `sqll_config` | core | config (C11) |
| `sqll_lint` | core | `Rule`, fix loop (C12) |
| `sqll_schema` | core | schema interface (C15) |
| `sqll_interfaces` | core | interface tests (C8) |
| `sqll` | core | binary |
| `sqll_base_tests` | core | native base tests |
| `sqll_parser` | S4 | parser, `Node`, `Arena` |
| `sqll_dialects` | S4 | generated tables |
| `sqll_rules` | S5 | rules |
| `sqll_templater` | S6 | templaters (raw: C8) |
| `sqll_cli` | S7-sqll | commands (C13) |
| `sqll_codegen` | S8 | code generation |
| `sqll_plpgsql` | S10 | PL/pgSQL bodies |

### Q6. CLI and config

Decision: the CLI extends the S3 CLI (`sqll parse`, `sqll version`,
`sqll --license`) with lint, fix, rules, and dialects. C13 moves the
commands and the output formats to `sqll_cli`; the binary `sqll` keeps
main, the allocator, and the license. C11 puts the config model and
reader in `sqll_config`.

Reason: the S1 and S2 adapters use the S3 commands and flags.

### Q7. Table format

Decision: the sqlfluffrs table format of `scripts/build-sqll` is frozen.
The generator in `third_party/` does not change. A build step (C6) makes
the `SegmentKind` enum from the tables and the lexers, one value for each
kind. The build fails if the kinds do not fit in a `u16`.

Reason: the sha256 of the manifest of the 85 generated files
(`generated.json`, `5371ded8ae21`) is part of the sqll version. A new
emitter changes the tables, the version, and the S2 baseline. The tool
checks that each type name in the trees is a table string or a lexer
name. The trees have 790 kinds; a `u16` holds 65536 kinds.

## Proof for each task

- G4: CI passes on a head with origin/main merged. S1 dialect suite of
  sqll: 2306 of 2306 exact, no new failure, no unexpected pass. The tree
  guard record does not change. Native base tests: 162 of 162.
- G3: from C5, a task that changes code of the sqll binary records the
  speed check (base, head, and sqruff; S2 method) in
  `results/S3b/speed/<task>.json`, with the reason for each slower
  benchmark (G3.6). Code that the binary does not link: `cargo tree`
  proof.
- Each frozen interface has one short document in `docs/interfaces/` and
  one test in `crates/sqll_interfaces/tests/`. C16 adds the index.
