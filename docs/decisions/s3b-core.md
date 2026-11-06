# S3b core design

Status: decided (Core track, task C4).

## Question

This record answers each question of [s3-exit.md](s3-exit.md), "Open
interface questions for S3b", with a reason.

## Data

Each number is a value of
[`results/S3b/C4-record.json`](../../results/S3b/C4-record.json) with its
source file and key (`scripts/s3b/core_design.py record`; drift test
`harness/tests/test_s3b_core.py`). The tree numbers are from
[`results/S3b/C4-tree-cost.json`](../../results/S3b/C4-tree-cost.json)
(`scripts/s3b/core_design.py measure`; `measure --check` makes them
again): the tool `scripts/s3b/tree-cost` links the sqll crates, parses the
84 S2 parse inputs (28 dialects) as `sqll parse` does, and counts the heap
blocks and bytes.

The 84 inputs have 601133 bytes of SQL and 280339 tree nodes:

| Tree | Heap blocks | MB |
|---|---|---|
| `Node` tree of the parser | 1806330 | 100.7 |
| `Arena`, made from the `Node` tree | 1989881 | 196.3 |
| Flat tree, estimate with a 24-byte node record | 4 for each tree | 8.5 |

- The `Node` tree uses 359 bytes and 6.4 heap blocks for each node (167
  bytes for each byte of SQL). Each leaf keeps its text and its type lists
  as strings.
- The flat tree is 12 times smaller (an estimate; C7 measures the real
  tree).
- The tree has 12% of the 14455867 heap blocks that the parse asks for.

## Answers

### Q1. Tree type

Decision: a new crate `sqll_tree` with a flat, immutable, lossless
`SyntaxTree`:

- All nodes are in one `Vec`, in source order. A node id is an index.
- Each node has a `SegmentKind` (`u16`), a byte range into one buffer of
  the templated text, its parent, and the range of its children. A leaf
  holds no `String`. A line index gives the line and position of a byte.
- `sqll_syntax` makes it from the parser `Node` tree. The parser of the
  base does not change. `Node` and `Arena` stay, because 8 of the 162
  native base tests (frozen S3 record) test the `Arena`. New code does
  not use the `Arena`.

Reason: the data above; the `Arena` with string types uses more memory
than the `Node` tree. Kinds give the typed view that G2 needs. The leaves
of each of the 84 trees give their input again (the tool checks this), so
one text buffer keeps each byte. Risk: the conversion adds work after the
parse. C7 measures it with the speed check of C5. Later, S4 can make the
parser write the flat tree.

### Q2. Source map

Decision: the ported `TemplatedFile` (`sqll_types`) is the frozen
interface from the templater to the source map. The Core crate
`sqll_source` has a `Templater` trait that gives a `TemplatedFile`, the
source map (templated to source byte ranges), and the raw templater. S6
writes the other templaters in `sqll_templater`.

Reason: the lexer already takes a `TemplatedFile`, a port of the sqlfluff
type. The S6 templaters need no new type.

### Q3. Lexer to parser to tree

Decision: one function in the Core crate `sqll_syntax`:
`parse(&TemplatedFile, Dialect, &ParseOptions) -> Parsed { tree, errors }`.
It lexes, parses, and makes the `SyntaxTree`. C9 moves
`crates/sqll/src/parse.rs` into it. `sqll parse` prints the sqlfluff tree
format from the `SyntaxTree`, and its output does not change (tree guard).

Reason: the rules, the code generation, and the CLI call one function. S4
can change the parser with no change to the callers.

### Q4. Rule and fix interface

Decision: a new Core crate `sqll_lint`:

- A `Rule` trait: code, name, groups, config keys, and a `lint` function
  over the typed view.
- A `LintResult` has an anchor node, a description, and fixes. A fix is a
  list of edits (a templated byte range and its new text). The source map
  changes each edit to a source edit, or refuses it if it has no source
  position (as sqlfluff does).
- A fix loop: fix, parse, and lint again, up to the sqlfluff
  `runaway_limit` (10 loops).
- Fail closed: a rule or a setting that sqll does not have gives
  "unsupported" and exit code 2, never a silent skip.

The rules stay in `sqll_rules` (S5). C12 moves CP01, CP03, and CP04 to
this interface as the proof.

Reason: the rules read node kinds, not type strings. Byte range edits let
the source map handle templated files (S6) with no change to the rules.

### Q5. Ownership

Decision: the table below. A track owns `src/**` and `tests/**` of its
packages. Core keeps each `Cargo.toml`, `build.rs`, `Cargo.lock`, and the
interface tests (`crates/sqll_interfaces`). C16 writes this into
`tracks.yml`. Until then, Core owns `crates/**` (C3).

Reason: a later track changes its own code with no Core review, but not an
interface, a dependency, or a build step (S3b exit).

| Package | Owner | Content (task) |
|---|---|---|
| `sqll_types` | core | tokens, `TemplatedFile`, table types |
| `sqll_lexer` | core | lexer |
| `sqll_tree` | core | `SegmentKind` (C6), `SyntaxTree` (C7), typed view (C10) |
| `sqll_source` | core | `Templater`, raw templater, source map (C8) |
| `sqll_syntax` | core | `parse` (C9) |
| `sqll_config` | core | config model and reader (C11) |
| `sqll_lint` | core | `Rule`, `LintResult`, fix loop (C12) |
| `sqll_schema` | core | tree to schema interface (C15) |
| `sqll_interfaces` | core | interface tests (C8) |
| `sqll` | core | binary: main, memory allocator, license |
| `sqll_base_tests` | core | native base tests |
| `sqll_parser` | S4 | parser, `Node`, `Arena` |
| `sqll_dialects` | S4 | dialect tables (generated) |
| `sqll_rules` | S5 | rules |
| `sqll_templater` | S6 | Jinja, placeholder, Python templaters (S6) |
| `sqll_cli` | S7-sqll | commands, output formats (C13) |
| `sqll_codegen` | S8 | code generation (S8) |
| `sqll_plpgsql` | S10 | PL/pgSQL bodies (S10) |

### Q6. CLI and config

Decision: the CLI extends the S3 CLI (`sqll parse`, `sqll version`,
`sqll --license`). The commands: parse, lint, fix,
rules, dialects, and version. The binary `sqll` keeps main, the memory
allocator, and the license. C13 moves the commands and the output formats
to `sqll_cli`. C11 puts the config model and reader in `sqll_config`.

Reason: the S1 and S2 adapters use the S3 commands and flags.

### Q7. Table format

Decision: the sqlfluffrs table format of `scripts/build-sqll` is frozen.
The generator in `third_party/` does not change. A build step (C6) makes
the `SegmentKind` enum from the tables and the lexer names.

Reason: the sha256 of the manifest of the 85 generated files
(`generated.json`, `5371ded8ae21`) is part of the sqll version. A new
emitter changes the tables, the version, and the S2 baseline. The tables
and the lexers of the 28 dialects have 9929 distinct strings. Each of the
665 type names in the 84 trees is one of them, and a `u16` holds 65536
kinds.

## Proof for each task

- G4: CI passes on a head with origin/main merged. S1 dialect suite of
  sqll: 2306 of 2306 exact, no new failure, no unexpected pass. The tree
  guard record does not change. Native base tests: 162 of 162.
- G3: from C5, a task that changes code of the sqll binary records the
  speed check (base, head, sqruff; start and parse; full profile; S2
  method) in `results/S3b/speed/<task>.json`, with the reason for each
  slower benchmark (G3.6). Code that the binary does not link: `cargo
  tree` proof.
- Each frozen interface has one short document in `docs/interfaces/` and
  one test in `crates/sqll_interfaces/tests/`. C16 adds the index.
