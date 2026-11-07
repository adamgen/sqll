// Parts of this file are a port of sqlfluff 4.4.0 code, through
// crates/sqll/src/parse.rs: the lexer and parser calls of
// sqlfluffrs/src/test_harness.rs (FixtureTest::run), the parser limits of
// sqlfluffrs/sqlfluffrs_parser/src/parser/python.rs (PyParser), and the
// parse limits and indentation defaults of
// src/sqlfluff/core/default_config.cfg.
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The lex and parse of `sqll parse` (crates/sqll/src/parse.rs), for the
//! tests. The settings are a copy; the test
//! `the_parse_settings_are_those_of_sqll_parse` (tests/segment_kinds.rs)
//! fails if they are not the same. C9 (the frozen parse interface) removes
//! the copy.

use std::sync::Arc;

use sqll_dialects::Dialect;
use sqll_lexer::{LexInput, Lexer};
use sqll_parser::parser::{Node, Parser};
use sqll_types::TemplatedFile;

// The values of crates/sqll/src/parse.rs.
pub const MAX_PARSE_DEPTH: usize = 600;
pub const MAX_PARSE_NODES: usize = 100_000;
pub const MAX_PARSER_ITERATIONS: usize = 3_000_000;
pub const PARSER_WARN_THRESHOLD: usize = 2_000_000;
pub const INDENTATION: &[(&str, bool)] = &[
    ("indent_unit", true),
    ("tab_space_size", true),
    ("indented_joins", false),
    ("indented_ctes", false),
    ("indented_using_on", true),
    ("indented_on_contents", true),
    ("indented_then", true),
    ("indented_then_contents", true),
    ("implicit_indents", true),
    ("template_blocks_indent", true),
    ("skip_indentation_in", true),
    ("skip_implicit_indents_in", true),
    ("trailing_comments", true),
    ("ignore_comment_lines", false),
];

/// The lexer of the dialect, as `sqll parse` makes it.
pub fn lexer(dialect: Dialect) -> Lexer {
    Lexer::new(None, dialect.get_lexers().clone())
        .with_bracket_pairs(dialect.get_bracket_pairs().clone())
}

/// The parse of the tokens, as `sqll parse` does it.
pub fn parse_tokens(dialect: Dialect, tokens: &[sqll_types::Token]) -> Result<Node, String> {
    let indentation = INDENTATION.iter().copied().collect();
    let mut parser =
        Parser::new_with_max_parse_depth(tokens, dialect, indentation, MAX_PARSE_DEPTH)
            .with_parser_limits(MAX_PARSER_ITERATIONS, PARSER_WARN_THRESHOLD)
            .with_node_limit(MAX_PARSE_NODES);
    parser.root_parse().map_err(|e| e.message)
}

/// Lex and parse the SQL as `sqll parse` does with no option. As in `sqll
/// parse`, a lex error does not stop the parse (the lexer makes an
/// unlexable token); only a parse error is an error.
pub fn parse(dialect: Dialect, sql: String) -> Result<Node, String> {
    let (tokens, _) = lexer(dialect).lex(LexInput::String(sql), true);
    parse_tokens(dialect, &tokens)
}

/// Lex and parse the templated text of a `TemplatedFile` as `parse` does
/// (S3b C8; the lexer input of the parse interface of C9).
pub fn parse_file(dialect: Dialect, file: Arc<TemplatedFile>) -> Result<Node, String> {
    let (tokens, _) = lexer(dialect).lex(LexInput::TemplatedFile(file), true);
    parse_tokens(dialect, &tokens)
}
