# Segment kinds

Status: frozen (Core track, task C6). Package: `sqll_tree`
(`src/kinds.rs`). Interface test:
`crates/sqll_interfaces/tests/segment_kinds.rs`. Design:
[s3b-core.md](../decisions/s3b-core.md), Q1 and Q7.

## The interface

- `SegmentType` (`u16`): one value for each type name of the dialect
  tables and the lexers, for example `keyword`. Each name has a constant,
  for example `SegmentType::SELECT_STATEMENT`: the name in upper case, with
  `_` for each other character, and the prefix `T` before `_` or a digit
  (`<unlexable>` is `T_UNLEXABLE_`). `name()` gives the name;
  `from_name()` gives the type of a name; `kinds()` gives the kinds of the
  type.
- `SegmentKind` (`u16`): one value for each distinct static data of a
  parser node (`KindData`): the node variant, the class, the type, the
  instance types, the class types (a set), the segment kwargs of a leaf
  (`trim_chars`, `quoted_value`, `escape_replacements`), and the meta data.
  `data()`, `ty()`, and `name()` (the key of the node in the sqlfluff tree
  format) read it. `is_type()` is the sqlfluff `is_type`. `find()` gives the
  kind of the data of a node (`KindKey`); the order of the class types is
  not important.
- The values are in a fixed order (the type names in byte order, the kinds
  in the order of their data). They change only when the tables change.

## How the build makes them

`build.rs` of `sqll_tree` reads the tables and the lexers of each dialect
of `crates/sqll_dialects/generated.json` through `sqll_dialects`
(`build/kinds.rs`). It uses the rules of the parser code that makes a node:

| Node | Rule |
|---|---|
| Lexer leaf | Each lexer matcher, with its subdividers and the last resort lexer |
| Parser leaf | Each terminal grammar and bracket symbol, for each token kwargs of the lexers of the dialect |
| Segment | Each `Ref` grammar with a class or a type; the root, bracketed, and unparsable segments |
| Meta | Indent and dedent (implicit or not), a placeholder for each of 8 slice types, the template loop, the end of the file |

Thus the kinds are a superset of the kinds that the parser makes. The
build fails if the types or the kinds do not fit in a `u16`, or if two
names have one constant. The table generator, the table format,
`generated.json`, and the sqll version do not change. The parser does not
use the kinds; C7 converts the parser tree.

## Numbers (C6)

| Item | Count |
|---|---|
| Dialects | 28 |
| Types | 1329 |
| Kinds | 3214 (raw 1918, segment 1280, meta 14, unparsable 1, empty 1) |
| Dialect fixtures parsed by the test | 2306 |
| Nodes in their trees | 685224, each with a kind |
| Distinct kinds in their trees | 1525 |

The test fails if a type name of the tables has no type, if a segment type
of a grammar that makes a node has no kind, if a kind does not give its
data again, if a node of a fixture has no kind, or if a count is not the
count above.

## Rules for a change

- A change of the tables or of the kind rules changes the counts. Change
  the test and this document in the same Core pull request.
- A change in the parser that makes new static data (S4) needs a change of
  `build/kinds.rs` (Core). Else the fixture test fails.
- A templater (S6) that gives a slice type outside the 8 types has no
  placeholder kind: `find()` gives `None`.
