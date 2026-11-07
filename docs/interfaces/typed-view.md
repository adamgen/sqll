# Typed view

Status: frozen (Core track, task C10). Package: `sqll_tree`
(`src/view.rs`). Interface test: `crates/sqll_interfaces/tests/typed_view.rs`.
Design: [s3b-core.md](../decisions/s3b-core.md), Q1 and Q4. The rules (S5)
and the code generation (S8) read the tree through this view.

## The interface

- `NodeRef<'t>`: a node and its `SyntaxTree` ([tree.md](tree.md)), `Copy`.
  `tree.node(id)` and `tree.root_node()` give one. It has `kind`, `ty`,
  `is_type` (the sqlfluff `is_type`), `is_any_type` (`is_type(*types)`),
  `raw`, `range`, `is_meta`, `is_code` (the sqlfluff `is_code`: a leaf that
  is not whitespace, a newline, or a comment, or a node with a code leaf),
  `parent`, `children`, and `descendants` (pre-order, without the node).
- Query helpers, each with the sqlfluff meaning:

  | sqll | sqlfluff `BaseSegment` |
  |---|---|
  | `child(types)` | `get_child(*types)` |
  | `children_of(types)` | `get_children(*types)` |
  | `first_descendant(types)` | the first of `recursive_crawl(*types, allow_self=False)` |
  | `crawl(types)` with `.recurse_into(b)`, `.no_recursive(stop types)`, `.allow_self(b)` | `recursive_crawl(*types, recurse_into, no_recursive_seg_type, allow_self)` |

  `crawl` gives the matches in pre-order. A node below the start node that
  has a stop type is not a match, and the crawl does not go into it.
- `AstNode<'t>`: a typed node. `can_cast(kind)`, `cast(NodeRef)` (`None`
  if the kind does not agree), and `node()`. `NodeRef` also has
  `cast::<N>()`, `child_as`, `children_as`, and `descendants_as`.
- `typed_node!` declares a typed node: a newtype of `NodeRef` that derefs
  to it. By type (`is_type`, thus also a class type):
  `typed_node!(pub struct SelectStatement = SELECT_STATEMENT;)`. By kind:
  `typed_node!(pub struct Placeholder = kind |k| ...;)`.
- The core set (`view::nodes`), with their accessors:

  | Typed node | Accessors |
  |---|---|
  | `File` | `statements` (`recursive_crawl("statement", recurse_into=False)`; also in a `batch`) |
  | `Statement` | `inner` (the first code child), `select_statement` |
  | `SelectStatement` | `select_clause`, `from_clause` |
  | `SelectClause` | `elements` |
  | `SelectClauseElement` | `alias`, `value` (the first code child that is not the alias), `column_reference` |
  | `FromClause` | `from_expressions` |
  | `FromExpression` | `elements` (`recursive_crawl("from_expression_element", recurse_into=False)`) |
  | `FromExpressionElement` | `table_reference` (in the `table_expression`), `alias` |
  | `TableReference`, `ColumnReference` | `parts` (the identifiers) |
  | `AliasExpression` | `identifier`, `operator` (`alias_operator`), `as_keyword` |
  | `Keyword` | `is(word)` (no regard to case) |
  | `Identifier` (class type `identifier`) | `is_quoted` |
  | `Literal` (class type `literal`) | |
  | `Placeholder` (a template meta node) | `block_type`, `source_str` |

## Meta kinds (fix of C6)

sqlfluff gives a meta segment the class types of its class: `base`, `meta`,
`raw`, and its type; a `dedent` is also an `indent`. Before C10 the meta
kinds had no class types, thus `is_type("indent")` was false for a dedent.
Now each meta kind has this set ([segment-kinds.md](segment-kinds.md)). The
type ids, the kind ids, and the `sqll parse` output do not change.

## Proof (C10)

- `scripts/s3b/crawl_oracle.py` runs the pinned sqlfluff `recursive_crawl`
  on 6 dialect fixtures (`ansi/select_a`, `ansi/select_j`,
  `ansi/select_many_join`, `ansi/select_simple_e`, `bigquery/select_example`,
  `tsql/multi_statement`) for 23 cases (start node, types, options), and
  the placeholders of `templater/jinja_b`. Record:
  `results/S3b/C10-crawl.json` (`check` in the CI job build).
- For a case whose types are not a class type only (111 of 135), the crawl
  on the fixture YAML gives the same code segments. The interface test does
  this crawl on the YAML itself, with no sqlfluff run.
- The test: 135 of 135 crawl cases give the sqlfluff segments (1182, type
  and raw, in order), 111 of them also as the YAML. The accessors give the
  kinds and raws of the YAML of 5 fixtures, and the 7 placeholders give the
  sqlfluff `block_type` and `source_str`.

## Rules for a change

- A change of a signature fails the interface test (`signatures`). Change
  the test and this document in the same Core pull request.
- A later track adds a typed node or an accessor through a Core pull
  request, with a test on fixture trees.
