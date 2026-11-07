# Source map

Status: frozen (Core track, task C8). Packages: `sqll_source` (Core:
`src/templater.rs`, `src/map.rs`, `src/lines.rs`) and `sqll_templater`
(S6: the templaters). Interface test:
`crates/sqll_interfaces/tests/source_map.rs`. Design:
[s3b-core.md](../decisions/s3b-core.md), Q2.

## The interface

- `TemplatedFile` (the port of sqlfluffrs in `sqll_types`) is the frozen
  output of a templater and the input of the lexer and of the source map.
  It has the source text, the templated text, the templated slices
  (`sliced_file`), and the raw slices (`raw_sliced`), as sqlfluff. Its
  offsets are code points (Python `str` offsets).
- `Templater`: `name()` (the config name, for example `raw`) and
  `process(source, fname, &TemplaterConfig) -> Result<TemplatedFile,
  TemplaterError>`. This is the sqlfluff `process` with one variant.
- `TemplaterConfig`: the keys and values of the sqlfluff config sections
  under `templater` (for example `templater:jinja:context`), as text. The
  config (C11) fills it; each templater reads and converts its own values.
- `TemplaterError`: `Template { message, source_byte }` (sqlfluff TMP) or
  `Unsupported { message }`: a setting or a feature that sqll does not
  have. sqll fails closed: "unsupported" and exit code 2.
- `sqll_templater`: `RawTemplater` (the sqlfluff `RawTemplater`: the text
  does not change), `by_name`, and `NAMES`. S6 adds the placeholder and
  Python templaters, S11 the Jinja templater.
- `SourceMap::new(Arc<TemplatedFile>)` checks the slices and gives the map.
  It refuses a file that breaks a rule (`InvalidFile`), so no call panics.
  `SourceMap::identity(text, fname)` is the map of the raw templater. All
  offsets of the map are bytes:
  - `source_range(templated range)`: the sqlfluff
    `templated_slice_to_source_slice`. A range in a literal slice maps
    exactly; a range that touches a templated slice takes all of its source.
  - `source_byte(templated byte)`: the start of the source range of the
    empty range. In a templated section it is `InTemplatedSection`, where
    sqlfluff raises a ValueError.
  - `source_line_pos(source byte)` and `source_pos(templated byte)`: the
    line and position (`LinePos`, both from 1, in characters).
  - `is_literal(templated range)` and `is_source_literal(source range)`:
    the sqlfluff `is_source_slice_literal`. Only literal text is safe to fix.
  - The conversions between bytes and code points of each text.
  - An offset inside a character or after the end is an error.

## The tree

`sqll_syntax::from_node_with_source(&Node, Arc<SourceMap>)` converts the
parser tree of a templated file. The tree keeps the map:

- `source_range(node)`: for a leaf or a meta node, the source slice of its
  lexer position, as sqlfluff. A node with children spans the source ranges
  of its children (the sqlfluff `PositionMarker.from_child_markers`).
- `source_pos(node)`, `source_text()`, `is_literal(node)`, `source_map()`.
- With no map (`from_node`) or an identity map, the source range is the
  templated range and each node is literal.
- `TreeBuilder::with_source`, `leaf_at`, and `meta_at` build such a tree.

The templated range of a node is its lossless range. The lexer of sqlfluff
can split one lexed element at the edge of a template slice; then each part
keeps the templated slice of the element. The tree gives each part its own
range, inside that slice (4 segments of the templater fixtures).

`LinePos` and `LineIndex` moved from `sqll_tree` to `sqll_source`;
`sqll_tree` exports them again.

## Proof (C8)

The data of the pinned sqlfluff come from its Jinja templater
(`scripts/s3b/source_map_oracle.py`). The record
[`results/S3b/C8-source-map.json`](../../results/S3b/C8-source-map.json)
has them for `jinja_a` and `jinja_b` (a loop). `check` (CI job build) makes
them again for each templater fixture and runs the ignored test.

| Input | Files | Result |
|---|---|---|
| Templater fixtures: each templated range, each source offset, each segment (type, ranges, literal flag, source position) | 53 | 53 of 53 as sqlfluff: 775828 ranges (1341 ValueError), 6654 source offsets, 3092 segments |
| Record (`jinja_a`, `jinja_b`) | 2 | 1677 ranges, 211 source offsets, 94 segments |
| Hand-built `jinja_a` (the slices of sqlfluff, the source text from the submodule) | 1 | ranges, points, positions, literal check |
| Raw templater (multi-byte UTF-8, CRLF) | 1 | identity |
| Dialect fixtures (`tests/tree.rs`): source range and position of each node | 2306 | 685224 nodes as the parser markers |

The ported `get_line_pos_of_char_pos` had a newline index with byte
offsets (C7 finding). C8 changed it to code points, as sqlfluff
(`crates/ported.json`). The output of `sqll parse` for the 2306 dialect
fixtures and the 84 S2 parse inputs did not change.

## Rules for a change

- A change of a signature fails the interface test (`signatures`). Change
  the test and this document in the same Core pull request.
- A new templater implements `Templater` in `sqll_templater` and gives a
  `TemplatedFile` that `SourceMap::new` accepts. It must not change
  `sqll_source` or `TemplatedFile`.
- Out of scope of C8: the Jinja, placeholder, and Python templaters (S6,
  S11), and the templater config (C11).
