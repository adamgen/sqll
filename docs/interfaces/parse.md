# Parse

Status: frozen (Core track, task C9). Package: `sqll_syntax`
(`src/parse.rs`). Interface test: `crates/sqll_interfaces/tests/parse.rs`.
Design: [s3b-core.md](../decisions/s3b-core.md), Q3.

## The interface

```rust
pub fn parse(file: &TemplatedFile, dialect: Dialect, options: &ParseOptions)
    -> Result<Parsed, ParseError>
```

`parse` lexes the templated text of the file, parses the tokens, and
converts the parser tree to a `SyntaxTree` ([tree.md](tree.md)) with the
source map of the file ([source-map.md](source-map.md)). The rules, the
code generation, and the CLI call only this function. `sqll parse` calls
it with the file of the raw templater.

- `ParseOptions` (`default()`, then set the fields; later tasks can add
  fields): `max_parse_depth` (the sqlfluff value, default 600; 0 is no
  limit; `depth_limit` gives at most `MAX_PARSE_DEPTH_LIMIT`, 10000) and
  `free_memory` (default true). The other settings are the sqlfluff
  defaults: `MAX_PARSE_NODES`, `MAX_PARSER_ITERATIONS`,
  `PARSER_WARN_THRESHOLD`, and `INDENTATION`.
- `Parsed`:
  - `tree: Option<SyntaxTree>`: `None` only if the parser stopped (a limit).
    Then `sqll parse` prints `"segments": null`.
  - `errors: Vec<Diagnostic>`: the lex errors, then the parser stop or the
    unparsable sections, as sqlfluff gives them. They do not stop the parse.
  - `times: ParseTimes`: the time of `setup` (source map and lexer), `lex`,
    `parse`, and `convert`, and the token count (`sqll parse --timings`).
- `Diagnostic`: `code` (`Code::Lex` "LXR" or `Code::Parse` "PRS"),
  `message` (the sqlfluff description), `templated` and `source` (a
  `Location`: byte, line, and position from 1, in characters), `node` (the
  unparsable node), and `expected` (the expected text of the parser, if it
  gives one; the ported parser gives none for an unparsable section). `Display` gives the error line of `sqll parse`:
  `LXR L<line> P<pos>: <message>` (source position) or `PRS: <message>`.
  - Lex error: `Unable to lex characters: <repr>`, at the unlexable token.
  - Unparsable section: each node of the type `unparsable` that is not in
    another one (the sqlfluff `iter_unparsables`): `Line L, Position P:
    Found unparsable section: <repr>` (the first 40 characters and `...` for
    a longer text), as the sqlfluff `Linter.parse_rendered`.
  - Parser stop: the message of the parser, with no place.
- `ParseError`: `parse` fails closed. `SourceMap` if the source map refuses
  the file, `Convert` if the conversion refuses the parser tree (a sqll bug,
  or a templated case that the tree cannot hold: source-map.md,
  `NotAtPosition`). `sqll parse` prints it and gives exit code 2.

Change to the C4 design (Q3 of [s3b-core.md](../decisions/s3b-core.md)): `tree` is an `Option`, and
`parse` returns a `Result`. Reason: a parser stop gives no tree, and the
conversion can refuse a tree; neither may be a silent skip.

## Newlines

`parse` does not change the text. sqlfluff changes "\r\n" and "\r" to
"\n" before the templater (`Linter.render_string`). Thus the caller does it
before the templater: `sqll parse` does it when it reads the file
(`read_sql` of `crates/sqll/src/main.rs`). A `TemplatedFile` with "\r" is
valid: the "\r" of "\r\n" is the last character of its line
([tree.md](tree.md)).

## Memory and stack

- `free_memory` false: the lexer, the tokens, the parser, and the parser
  tree are not dropped. Use it only in a command that exits after its
  output (S3 T15): the operating system frees the memory at less cost.
  `sqll parse` uses false.
- The drop of the parser tree recurses once for each level. Call `parse`
  on a thread with a large stack (`sqll parse`: 256 MiB).

## The steps

`sqll_syntax::parse::steps` (`lexer`, `lex`, `parser`, `parse_tokens`,
`parse_node`) are the steps of `parse`. The interface tests and the tree
check use them to compare the tree with the parser tree. They are not part
of the frozen interface; new code calls `parse`.

## Proof (C9)

- `tests/parse.rs`: for each of the 2306 dialect fixtures, `parse` gives
  no diagnostic and the tree of the steps, node for node (685224 nodes),
  with an identity map. A templated file gives the source ranges of its
  map. The places and messages of a lex error and an unparsable section
  are those of `sqlfluff lint` of the pinned sqlfluff. A parser stop, a
  refused file, and a refused tree.
- `sqll parse` output: the tree guard record did not change. Before and
  after C9, the output (stdout, stderr, exit code) is the same for the
  2306 fixtures, the 84 S2 parse inputs, and invented changed fixtures,
  each with no option, `-m`, `-c`, and `-c -m` ([status/S3b.md](../../status/S3b.md), C9).
- The writer of the JSON output reads the `SyntaxTree`. Its tests compare
  it with the record of the parser tree (`Node::as_record`, the output
  before C9) for each fixture and option set.

## Rules for a change

- A change of a signature fails the interface test (`signatures`). Change
  the test and this document in the same Core pull request.
- A parser change (S4) changes the tree of the steps and of `parse` in the
  same way; the tree guard and the S1 dialect suite show a change of the
  output.
