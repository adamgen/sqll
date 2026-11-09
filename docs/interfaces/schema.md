# Tree to schema (code generation)

Status: frozen (Core track, task C15). Package: `sqll_schema`. Interface
test: `crates/sqll_interfaces/tests/schema.rs`. Design:
[s3b-core.md](../decisions/s3b-core.md), Q5. Goal: G2.2. The code
generation of S8 (`sqll_codegen`) implements `Describe`.

## The interface

- `Description`: one query. `kind` (`StatementKind`: `Select`, `Insert`,
  `Update`, `Delete`, `Merge`, `Other`; `StatementKind::of` gives it from
  the statement segment), `source`, `parameters`, and `columns` (`None` if
  the statement gives no rows).
- `Parameter`: `name` (`None` for `?` and `%s`; the number for `:1` and
  `$1`), `position` (from 1), `style`, `ty`, `nullability`, and `sources`
  (each use).
- `Column`: `name` (as the database gives it), `ty`, `nullability`, and
  `source` (the select element).
- `SourceSpan`: `start` and `end` (source bytes, through the source map),
  and the `line` and `pos` of the start (from 1). `SourceSpan::of(tree,
  id)` gives it for a node ([source-map.md](source-map.md)).
- `ParamStyle`: the 12 `param_style` names of the sqlfluff placeholder
  templater (`name`, `from_name`, `is_positional`, `has_name`).
- `SqlType`: `Boolean`, `Integer`, `Decimal`, `Float`, `Text`, `Bytes`,
  `Date`, `Time`, `Timestamp`, `TimestampTz`, `Interval`, `Uuid`, `Json`,
  `Array(item)`, `Named(name)`, `Unknown`. `Nullability`: `NotNull`,
  `Nullable`, `Unknown`.
- `Catalog`: `tables` (`Table`: `schema`, `name`, `columns` of
  `CatalogColumn`), `table(schema, name)` and `column(name)` (exact names;
  the DDL reader of S8 applies the case rules of the dialect).
- `Describe::describe(&DescribeInput) -> Result<Description,
  DescribeError>`. `DescribeInput`: `statement` (a `Statement` of the typed
  view, [typed-view.md](typed-view.md)), `source` (the `SourceMap` of the
  tree), `catalog`, `dialect`, and `param_style`.
- `describe_file(describer, &Parsed, catalog, dialect, param_style)`: each
  statement of a parse ([parse.md](parse.md)) in order.
- `write_json_schema(&Description, title) -> Result<String, SchemaError>`.

## Fail closed

sqll gives no schema if it can be wrong:

- `describe_file`: a parse error (`DescribeError::Parse`, the first error
  of `Parsed.errors`), no tree, no source map, or an unparsable node.
- An implementation gives `DescribeError::Unsupported { reason, source }`
  for each form that it does not know.
- The writer refuses (`SchemaError`) two columns with one name, an empty
  column name, parameters of different styles, positions that are not 1 to
  n in order, a name that does not agree with the style, two parameters
  with one name, and a parameter with no source.

## JSON Schema

The writer gives one schema (draft 2020-12) for each query: a closed object
with `parameters` and `row` (`$ref` to `$defs`; no `row` if `columns` is
`None`).

- `parameters`: a closed object by name, or for `?`, `%s`, `:1`, and `$1`
  an array (`prefixItems`, `items: false`, `minItems` and `maxItems` =
  n). No parameters: an empty closed object.
- `row`: a closed object; the properties are the columns in order, and
  `required` has each column in order.
- Types: `Boolean` boolean, `Integer` integer, `Float` number, `Decimal`
  string (a JSON number can lose digits), `Text`, `Timestamp`, and
  `Interval` string, `Bytes` string with `contentEncoding: base64`, `Date`,
  `Time`, `TimestampTz`, and `Uuid` string with the `format` `date`,
  `time`, `date-time`, and `uuid`, `Array` array (items can be null).
  `Json`, `Named`, and `Unknown` permit each JSON value.
- NULL: `Nullable` and `Unknown` add `"null"` to the type. `NotNull` with
  no JSON type gives `not: {type: null}`.
- Annotations (JSON Schema ignores them in a validation): `x-sqll-type`,
  `x-sqll-nullability`, `x-sqll-source` (a column, the statement),
  `x-sqll-name`, `x-sqll-position`, `x-sqll-style`, `x-sqll-sources` (a
  parameter), and `x-sqll-statement`.

## The stub (S8)

`sqll_codegen::LiteralSelect` describes only an ANSI `SELECT` of literals,
each with an alias, and nothing else: an integer (digits only), a string
in single quotes, `TRUE`, `FALSE`, and `NULL`. A naked alias is in upper
case (the ANSI rule); a quoted alias has no quotes. Each other form, a
value from a template tag, and each other dialect give `Unsupported`. Not
in C15 (S8): type inference, the DDL reader, the parameters, and the code
generation.

## Proof (C15)

- The interface test runs the minimal case end to end (raw templater,
  `parse`, `describe_file`, the stub, the writer), the source ranges
  through a test templater, 13 forms that the stub refuses (one is a value
  from a template tag), the parse errors, the statement kinds, the 12
  sqlfluff `param_style` names (read from the submodule), the catalog, and
  the writer refusals.
- The record `results/S3b/C15-schema.json` and the schemas in
  `results/S3b/C15-schema/` are the writer output of 4 cases: the minimal
  case of the stub, and 3 hand-built descriptions (named parameters and
  each type; `?` and no rows; `$1`). Each case has example values that its
  schema must accept or refuse.
- `scripts/s3b/schema_check.py check` (CI job build) writes the record
  again with cargo, compares it, and validates it with the `jsonschema`
  package: each schema against the draft 2020-12 meta-schema, and each
  example against its schema.

## Rules for a change

- A change of a signature fails the interface test (`signatures`). Change
  the test, the record, and this document in the same Core pull request.
- S8 implements `Describe` in `sqll_codegen` and must not change
  `sqll_schema`.
