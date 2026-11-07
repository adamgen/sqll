# Source map

Status: frozen (Core track, task C8). Packages: `sqll_source` (Core:
`src/templater.rs`, `src/map.rs`, `src/lines.rs`) and `sqll_templater`
(S6: the templaters). Interface test:
`crates/sqll_interfaces/tests/source_map.rs`. Design:
[s3b-core.md](../decisions/s3b-core.md), Q2. Change to the C4 design (C8
task text, recorded in Q2 and Q5): the raw templater is in the S6 package
`sqll_templater`, not in `sqll_source`.

## The interface

- `TemplatedFile` (the port of sqlfluffrs in `sqll_types`) is the frozen
  output of a templater and the input of the lexer and of the source map.
  It has the source text, the templated text, the templated slices
  (`sliced_file`), and the raw slices (`raw_sliced`), as sqlfluff. Its
  offsets are code points (Python `str` offsets).
- `Templater`: `name()` (the config name, for example `raw`) and
  `process(source, fname, &TemplaterConfig) -> Result<TemplatedFile,
  TemplaterError>`. This is the sqlfluff `process` with one variant.
- `TemplaterConfig` (`new`, `set`, `get`, `section`, `section_names`):
  the keys and values of the sqlfluff config sections under `templater`
  (for example `templater:jinja:context`), as text. The config (C11) fills
  it; each templater reads and converts its own values.
- `TemplaterError`: `Template { message, source_byte }` (sqlfluff TMP) or
  `Unsupported { message }`: a setting or a feature that sqll does not
  have. sqll fails closed: "unsupported" and exit code 2.
- `sqll_templater`: `RawTemplater` (the sqlfluff `RawTemplater`: the text
  does not change), `by_name`, and `NAMES`. S6 adds the placeholder and
  Python templaters, S11 the Jinja templater.
- `SourceMap::new(Arc<TemplatedFile>)` checks the slices and gives the map.
  It refuses a file that breaks a rule (`InvalidFile`), so no call panics.
  A file with source slices out of order is valid: it maps as sqlfluff. An
  empty text has no slices: the sqlfluff Jinja, Python, and placeholder
  templaters give no slices for an empty file, and the map gives the
  sqlfluff answers (`0..0`, literal).
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

The templated slice of the marker of each leaf and meta node must contain
the range of the node, else the conversion fails (`NotAtPosition`). Example
(invented, no pinned fixture): for `SELECT {{- 1 -}} , 2` the parser puts
the placeholder (templated 6..6) before the unparsable node (0..10), as
sqlfluff does; the tree cannot give it its range.

`LinePos` and `LineIndex` (`new`, `line_count`, `line_start`, `line_pos`)
moved from `sqll_tree` to `sqll_source`; `sqll_tree` exports them again.

## Proof (C8)

The data of the pinned sqlfluff come from its Jinja templater
(`scripts/s3b/source_map_oracle.py`). The record
[`results/S3b/C8-source-map.json`](../../results/S3b/C8-source-map.json)
has them for `jinja_a`, `jinja_b` (a loop), and an empty file. `check` (CI
job build) makes them again for 54 templater fixtures and for 20000 random invented files
(seed 8), and runs the two ignored tests. The fixtures: each SQL file
directly in a folder of `test/fixtures/templater/` (53), and each file of
the case table of `test/core/templaters/jinja_test.py` (one more, in a
subfolder). Each runs with the config of its folder, so with the Jinja
templater. A fixture with no sqlfluff parse tree fails.

| Input | Files | Result |
|---|---|---|
| Templater fixtures: each templated range, each source offset, each segment (type, ranges, literal flag, source position) | 54 | 54 of 54 as sqlfluff: 776608 ranges (1345 ValueError), 6711 source offsets, 3121 segments |
| Record (`jinja_a`, `jinja_b`, the empty dialect fixture `ansi/empty_file.sql`: no slices) | 3 | 1678 ranges, 212 source offsets, 96 segments |
| Hand-built `jinja_a` (the slices of sqlfluff, the source text from the submodule) | 1 | ranges, points, positions, literal check |
| Random invented files (multi-byte UTF-8, CR and LF, parts of raw slices, overlapping and empty source slices): each templated range and each source offset | 20000 | 20000 of 20000 as sqlfluff: 211080 ranges (17415 ValueError), 193773 source offsets |
| Invented files with source slices out of order (no fixture has them; unit tests of `map.rs`) | 1 + 3000 random | each range as sqlfluff (one file); random files: each byte range (also inside a character) gives no panic and whole source characters, and a range inside one literal slice gives the same text |
| Raw templater (multi-byte UTF-8, CRLF) | 1 | identity |
| Dialect fixtures (`tests/tree.rs`): source range and position of each node, with no map and through the raw templater | 2306 | 685224 nodes as the parser markers, both ways; identity map |

The ported `get_line_pos_of_char_pos` had a newline index with byte
offsets (C7 finding). C8 changed it to code points, as sqlfluff
(`crates/ported.json`), and also `raw_slices_spanning_source_slice` (it
added a byte length to a code point offset). The ported parser lost the
`end_of_file` of an empty templated text with no slices; C8 keeps it, as
sqlfluff (`crates/ported.json`). The output of `sqll parse` for the 2306 dialect
fixtures and the 84 S2 parse inputs did not change.

## Rules for a change

- A change of a signature fails the interface test (`signatures`). Change
  the test and this document in the same Core pull request.
- A new templater implements `Templater` in `sqll_templater` and gives a
  `TemplatedFile` that `SourceMap::new` accepts. It must not change
  `sqll_source` or `TemplatedFile`.
- The raw templater is in `sqll_templater` (S6 after C16), but the Core
  interface test checks that it gives the identity map. A change that
  breaks this fails a Core test.
- Out of scope of C8: the Jinja, placeholder, and Python templaters (S6,
  S11), and the templater config (C11).
