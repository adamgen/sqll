// Parts of this file are a port of sqlfluff 4.4.0 code: the lexer and parser
// calls of sqlfluffrs/src/test_harness.rs (FixtureTest::run), the parser
// limits of sqlfluffrs/sqlfluffrs_parser/src/parser/python.rs (PyParser),
// and the parse limits and indentation defaults of
// src/sqlfluff/core/default_config.cfg. sqll took them from the S3 T5 probe
// (scripts/s3/probe-sqlfluffrs/src/main.rs).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! Lex and parse one SQL text for "sqlfluff parse".

use std::str::FromStr;

use sqll_dialects::Dialect;
use sqll_lexer::{LexInput, Lexer};
use sqll_parser::parser::{Node, Parser};

use crate::timings::Timer;

/// The sqlfluff core default of max_parse_depth.
pub const MAX_PARSE_DEPTH: usize = 600;
/// The largest parse depth of sqll. A deeper tree can overflow the stack
/// (main.rs, STACK_SIZE). sqlfluff stops such a parse with a RecursionError
/// and exit code 1; sqll stops it with a parse error and exit code 1.
pub const MAX_PARSE_DEPTH_LIMIT: usize = 10_000;
// The sqlfluff core defaults: max_parse_nodes, rust_parser_max_iterations,
// rust_parser_warn_threshold.
const MAX_PARSE_NODES: usize = 100_000;
const MAX_PARSER_ITERATIONS: usize = 3_000_000;
const PARSER_WARN_THRESHOLD: usize = 2_000_000;

// The [sqlfluff:indentation] defaults, each as bool(value), as the Python
// RustParser gives them to the Rust parser.
const INDENTATION: &[(&str, bool)] = &[
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

pub struct Options {
    pub code_only: bool,
    pub include_meta: bool,
    pub max_parse_depth: usize,
}

pub struct Parsed {
    /// The root segment, or None if the parser gave an error.
    pub root: Option<Node>,
    /// The lex and parse errors, one line each, as "LXR ..." or "PRS ...".
    pub errors: Vec<String>,
}

/// The parse depth for a max_parse_depth value: the value, but 0 (no limit
/// in sqlfluff) and each value above MAX_PARSE_DEPTH_LIMIT give the limit.
pub fn depth_limit(max_parse_depth: usize) -> usize {
    if max_parse_depth == 0 {
        MAX_PARSE_DEPTH_LIMIT
    } else {
        max_parse_depth.min(MAX_PARSE_DEPTH_LIMIT)
    }
}

/// Return the dialect with this sqlfluff name.
pub fn dialect(name: &str) -> Option<Dialect> {
    Dialect::from_str(name).ok()
}

/// Lex and parse the SQL. If free is false, the lexer, the tokens, and the
/// parser are not dropped: the command exits after the output, and the
/// operating system frees the memory at less cost (S3 T15).
pub fn parse(
    sql: String,
    dialect: Dialect,
    options: &Options,
    timer: &mut Timer,
    free: bool,
) -> Parsed {
    let lexer = Lexer::new(None, dialect.get_lexers().clone())
        .with_bracket_pairs(dialect.get_bracket_pairs().clone());
    timer.mark("setup");
    let (tokens, lex_errors) = lexer.lex(LexInput::String(sql), true);
    timer.tokens = tokens.len();
    timer.mark("lex");
    let mut errors: Vec<String> = lex_errors
        .iter()
        .map(|e| {
            format!(
                "LXR L{} P{}: {}",
                e.line_no,
                e.line_pos,
                e.description.as_deref().unwrap_or("lex error")
            )
        })
        .collect();

    let indentation = INDENTATION.iter().copied().collect();
    let mut parser =
        Parser::new_with_max_parse_depth(&tokens, dialect, indentation, options.max_parse_depth)
            .with_parser_limits(MAX_PARSER_ITERATIONS, PARSER_WARN_THRESHOLD)
            .with_node_limit(MAX_PARSE_NODES);
    let root = match parser.root_parse() {
        Ok(node) => Some(node),
        Err(e) => {
            errors.push(format!("PRS: {}", e.message));
            None
        }
    };
    timer.mark("parse");
    if !free {
        std::mem::forget(parser);
        std::mem::forget(tokens);
        std::mem::forget(lexer);
    }
    Parsed { root, errors }
}
