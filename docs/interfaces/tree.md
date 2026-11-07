# Syntax tree

Status: frozen (Core track, task C7; C8 adds the source positions).
Packages: `sqll_tree` (`src/tree.rs`) and `sqll_syntax` (`src/convert.rs`).
Interface test: `crates/sqll_interfaces/tests/tree.rs`. Design:
[s3b-core.md](../decisions/s3b-core.md), Q1.

## The interface

- `SyntaxTree`: a flat, immutable, lossless tree. It keeps one buffer of
  the templated text and one record of 20 bytes for each node, in
  pre-order (source order). A `NodeId` is the index of a node; the root is
  `NodeId::ROOT` (0).
- Each node has one `SegmentKind` ([segment-kinds.md](segment-kinds.md)):
  `kind`, `ty`, `variant`, `class_types` (a sorted set of type ids), and
  `is_type` (the sqlfluff `is_type`). The kind is the interned id of the
  static data of the node.
- `range` is the templated byte range of a node; `raw` is its text. A leaf
  is a range of the buffer and holds no string. A meta node (indent,
  dedent, placeholder, template loop, end of file) has an empty range at
  its place. An unparsable node is a node of the type `unparsable` with
  children.
- Navigation: `parent`, `children` (in order), `descendants` (pre-order,
  without the node), `descendants_of_kind`, `descendants_of_type`
  (`is_type`), `raw_segments` (each leaf and meta node, in order, as the
  sqlfluff `raw_segments`), and `nodes`.
- Positions: `line_pos(byte)` and `start_pos(node)` give a `LinePos` (line
  and position, both from 1). The position counts characters (Unicode
  scalar values), as sqlfluff does. Only "\n" ends a line, so the "\r" of
  "\r\n" is the last character of its line. A byte inside a character, or
  after the end, gives `None`. `line_index()` gives the start of each line.
  `LinePos` and `LineIndex` are in `sqll_source` since C8.
- Source positions (C8, [source-map.md](source-map.md)): `source_map`,
  `source_text`, `source_range`, `source_pos`, and `is_literal`. A tree
  with no source map has the templated range as the source range.
- `TreeBuilder` makes a tree: `start_node` and `finish_node` for a node
  with children, `leaf` for a leaf, `meta` for a meta node (with a source
  map: `with_source`, `leaf_at`, `meta_at`). It refuses a kind of the
  wrong variant, a leaf that is not the next text, a second root, a bad
  source range, and, in `finish`, open nodes or text with no leaf.
- `verify` checks each rule of the tree again, also the lossless rule.
- `sqll_syntax::from_node(&Node, text)` converts the parser tree. It gives
  `Converted`: the tree, the expected text of each `Node::Unparsable`, and
  the source text of each template placeholder (the source map, C8, uses
  it). `kind_of(&Node)` gives the kind of a parser node.
  `from_node_with_source` also keeps a source map (C8).

## The lossless rule

The texts of the leaves, in order, are the templated text, with each byte
one time. The builder makes sure of it: a leaf must be the next text, and
`finish` fails if text is left.

## Proof (C7)

| Input | Files | Nodes | Result |
|---|---|---|---|
| Dialect fixtures of the pinned sqlfluff | 2306 | 685224 | 2306 of 2306 pass |
| S2 parse inputs (`scripts/s3b/tree_check.py check`) | 84 | 280339 | 84 of 84 pass |

For each file, the test converts the parser tree and checks the lossless
rule and each node against its `Node`: the type, the raw text, the parent,
the number of children, the static data, `is_type`, the byte range of the
position marker, and the line position. The line position comes from the
code points of the text; the ported `get_line_pos_of_char_pos` must give
it too. C8 adds the source range, the source position, and the literal
flag of the marker. (In C7 the ported line position was wrong after a
multi-byte character, for 5938 nodes of the fixtures and 5737 of the S2
inputs; C8 fixed it.)

The conversion cost is in `results/S3b/C7-conversion.json` and in
[status/S3b.md](../../status/S3b.md). The sqll binary does not use the tree
before C9.

## Rules for a change

- A change of a signature fails the interface test (`signatures`). Change
  the test and this document in the same Core pull request.
- A parser change (S4) that makes new static data needs a kind (C6). Else
  the conversion fails with `NoKind`, and the fixture test fails.
- New code reads the `SyntaxTree`, not the `Node` tree.
