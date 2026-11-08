// Parts of this file are a port of sqlfluff 4.4.0 code: the lexer and parser
// calls of sqlfluffrs/src/test_harness.rs (FixtureTest::run), the parser
// limits of sqlfluffrs/sqlfluffrs_parser/src/parser/python.rs (PyParser),
// the parse limits and indentation defaults of
// src/sqlfluff/core/default_config.cfg, and the message of an unparsable
// section of src/sqlfluff/core/linter/linter.py (Linter.parse_rendered).
// sqll took the first three from the S3 T5 probe
// (scripts/s3/probe-sqlfluffrs/src/main.rs) by way of
// crates/sqll/src/parse.rs (S3b C9 moved them here).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The frozen parse interface (docs/interfaces/parse.md, S3b task C9): one
//! function, [`parse`], from a [`TemplatedFile`] to a [`SyntaxTree`]. It
//! lexes the templated text, parses the tokens, and converts the parser
//! tree ([`crate::convert`]).
//!
//! The [`steps`] module has the steps of `parse` for the tests and tools
//! that compare the tree with the parser tree. It is not part of the frozen
//! interface.

use std::fmt;
use std::sync::Arc;
use std::time::{Duration, Instant};

use sqll_dialects::Dialect;
use sqll_lexer::{LexInput, Lexer};
use sqll_parser::parser::{Node, Parser};
use sqll_source::{LineIndex, LinePos, SourceMap, SourceMapError};
use sqll_tree::{NodeId, SegmentType, SyntaxTree};
use sqll_types::{TemplatedFile, Token};

use crate::convert::{from_node_with_source, ConvertError};

/// The sqlfluff core default of `max_parse_depth`.
pub const MAX_PARSE_DEPTH: usize = 600;
/// The largest parse depth of sqll. A deeper tree can overflow the stack of
/// the caller ([`parse`], "Stack"). sqlfluff stops such a parse with a
/// RecursionError; sqll stops it with a parse error.
pub const MAX_PARSE_DEPTH_LIMIT: usize = 10_000;
/// The sqlfluff core default of `max_parse_nodes`.
pub const MAX_PARSE_NODES: usize = 100_000;
/// The sqlfluff core default of `rust_parser_max_iterations`.
pub const MAX_PARSER_ITERATIONS: usize = 3_000_000;
/// The sqlfluff core default of `rust_parser_warn_threshold`.
pub const PARSER_WARN_THRESHOLD: usize = 2_000_000;

/// The `[sqlfluff:indentation]` defaults, each as `bool(value)`, as the
/// Python RustParser gives them to the Rust parser.
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

/// The parse depth of a `max_parse_depth` value: the value, but 0 (no limit
/// in sqlfluff) and each value above [`MAX_PARSE_DEPTH_LIMIT`] give the
/// limit.
pub fn depth_limit(max_parse_depth: usize) -> usize {
    if max_parse_depth == 0 {
        MAX_PARSE_DEPTH_LIMIT
    } else {
        max_parse_depth.min(MAX_PARSE_DEPTH_LIMIT)
    }
}

/// The settings of a parse. `ParseOptions::default()` gives the sqlfluff
/// defaults. Later tasks can add fields, so make a value with `default()`
/// and then set the fields. Since S3b C11, `sqll parse` sets them from the
/// config (`sqll_config::ParseSettings`).
#[derive(Clone, Debug, PartialEq, Eq)]
#[non_exhaustive]
pub struct ParseOptions {
    /// The sqlfluff `max_parse_depth`: 0 is no limit. [`depth_limit`] gives
    /// the depth that the parser uses.
    pub max_parse_depth: usize,
    /// If false, the lexer, the tokens, the parser, and the parser tree are
    /// not dropped: their memory stays until the process exits. A command
    /// that exits after its output uses false, because the operating system
    /// frees the memory at less cost (S3 T15). Default: true.
    pub free_memory: bool,
    /// The sqlfluff `max_parse_nodes`: 0 is no limit (C11).
    pub max_parse_nodes: usize,
    /// The sqlfluff `rust_parser_max_iterations` (C11).
    pub max_parser_iterations: usize,
    /// The sqlfluff `rust_parser_warn_threshold` (C11).
    pub parser_warn_threshold: usize,
    /// The `[sqlfluff:indentation]` section, each value as `bool(value)`
    /// (C11). A conditional indent of the grammar reads its key; a missing
    /// key is false.
    pub indentation: Vec<(String, bool)>,
}

impl Default for ParseOptions {
    fn default() -> Self {
        ParseOptions {
            max_parse_depth: MAX_PARSE_DEPTH,
            free_memory: true,
            max_parse_nodes: MAX_PARSE_NODES,
            max_parser_iterations: MAX_PARSER_ITERATIONS,
            parser_warn_threshold: PARSER_WARN_THRESHOLD,
            indentation: INDENTATION
                .iter()
                .map(|(k, v)| (k.to_string(), *v))
                .collect(),
        }
    }
}

/// A `&'static str` for an indentation key: the parser keeps its config
/// keys as `&'static str`. A key that is not a default key is kept one time
/// for the process.
fn static_key(key: &str) -> &'static str {
    use std::collections::HashSet;
    use std::sync::{Mutex, OnceLock};
    if let Some((k, _)) = INDENTATION.iter().find(|(k, _)| *k == key) {
        return k;
    }
    static KEYS: OnceLock<Mutex<HashSet<&'static str>>> = OnceLock::new();
    let mut keys = KEYS
        .get_or_init(Default::default)
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    if let Some(k) = keys.get(key) {
        return k;
    }
    let k: &'static str = Box::leak(key.to_string().into_boxed_str());
    keys.insert(k);
    k
}

/// The code of a [`Diagnostic`], as sqlfluff gives it.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Code {
    /// `LXR`: the lexer found text that no lexer matcher matches.
    Lex,
    /// `PRS`: the parser stopped (a limit), or it made an unparsable
    /// section.
    Parse,
}

impl Code {
    /// "LXR" or "PRS".
    pub fn as_str(self) -> &'static str {
        match self {
            Code::Lex => "LXR",
            Code::Parse => "PRS",
        }
    }
}

/// A place in a text: the byte offset, and its line and position (both from
/// 1, in characters; [`LinePos`]).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Location {
    pub byte: usize,
    pub line: usize,
    pub pos: usize,
}

impl Location {
    fn new(byte: usize, at: LinePos) -> Self {
        Location {
            byte,
            line: at.line,
            pos: at.pos,
        }
    }
}

/// A lex or parse error of a file.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Diagnostic {
    pub code: Code,
    /// The sqlfluff description. For a lex error: `Unable to lex characters:
    /// <repr>`. For an unparsable section: `Line L, Position P: Found
    /// unparsable section: <repr>` (L and P of `templated`).
    pub message: String,
    /// The start of the problem in the templated text, if it has a place.
    /// A parser stop (a limit) has none.
    pub templated: Option<Location>,
    /// The start of the problem in the source text, if it has a place.
    pub source: Option<Location>,
    /// The node of an unparsable section (a node of the type
    /// `unparsable`), or `None`.
    pub node: Option<NodeId>,
    /// The expected text of the parser for an unparsable section (the
    /// sqlfluff `UnparsableSegment.expected`), if the parser gives it. The
    /// ported parser gives it only for a `Node::Unparsable`; it makes each
    /// unparsable section as a segment of the class `UnparsableSegment`,
    /// with no expected text (`None`).
    pub expected: Option<String>,
}

impl fmt::Display for Diagnostic {
    /// `LXR L<line> P<pos>: <message>` with the source position, or
    /// `PRS: <message>` if there is no position: the error line of `sqll
    /// parse`.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.source {
            Some(at) => write!(
                f,
                "{} L{} P{}: {}",
                self.code.as_str(),
                at.line,
                at.pos,
                self.message
            ),
            None => write!(f, "{}: {}", self.code.as_str(), self.message),
        }
    }
}

/// The time of each step of a parse, and the token count. The steps are
/// one after the other, and their sum is the time of [`parse`] (without the
/// drop at the end if [`ParseOptions::free_memory`] is true).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct ParseTimes {
    /// The source map of the file and the lexer of the dialect.
    pub setup: Duration,
    pub lex: Duration,
    pub parse: Duration,
    /// The conversion of the parser tree to the `SyntaxTree`, and the
    /// diagnostics of the unparsable sections.
    pub convert: Duration,
    pub tokens: usize,
}

/// The result of [`parse`].
#[derive(Debug)]
pub struct Parsed {
    /// The lossless tree of the templated text, with the source map of the
    /// file. `None` if the parser stopped (a parse error in `errors`, for
    /// example at the parse depth limit).
    pub tree: Option<SyntaxTree>,
    /// The lex errors (in the order of the text), then the parser stop or
    /// the unparsable sections (in pre-order), as sqlfluff gives them.
    pub errors: Vec<Diagnostic>,
    pub times: ParseTimes,
}

/// A file that `parse` cannot give a tree for. sqll fails closed: the
/// command gives the error and exit code 2.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ParseError {
    /// The source map refuses the `TemplatedFile` (a broken templater).
    SourceMap(SourceMapError),
    /// The conversion refuses the parser tree: a sqll bug, or a templated
    /// file whose tree the `SyntaxTree` cannot hold
    /// (docs/interfaces/source-map.md, `NotAtPosition`).
    Convert(ConvertError),
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ParseError::SourceMap(e) => write!(f, "the source map refuses the file: {e}"),
            ParseError::Convert(e) => write!(f, "the syntax tree refuses the parse tree: {e}"),
        }
    }
}

impl std::error::Error for ParseError {}

/// Lex, parse, and convert the templated text of a file with the dialect.
///
/// The tree keeps a source map of the file. Each lex error, the parser
/// stop, and each unparsable section is a [`Diagnostic`]; they do not stop
/// the parse, except the parser stop, which gives no tree.
///
/// Stack: the parser is iterative, but the drop of the parser tree recurses
/// once for each level. At [`MAX_PARSE_DEPTH_LIMIT`] the drop needs about
/// 10 MiB of stack in a release build and 33 MiB in a debug build. `sqll
/// parse` runs it on a thread with a 256 MiB stack.
pub fn parse(
    file: &TemplatedFile,
    dialect: Dialect,
    options: &ParseOptions,
) -> Result<Parsed, ParseError> {
    let mut clock = Clock::new();
    let map = Arc::new(SourceMap::new(Arc::new(file.clone())).map_err(ParseError::SourceMap)?);
    let lexer = steps::lexer(dialect);
    let setup = clock.lap();
    let (tokens, mut errors) = steps::lex(&lexer, &map);
    let lex = clock.lap();
    let mut parser = steps::parser(&tokens, dialect, options);
    let root = steps::parse_tokens(&mut parser);
    let parse = clock.lap();
    let tree = match &root {
        Ok(node) => {
            let converted = from_node_with_source(node, map).map_err(ParseError::Convert)?;
            errors.extend(unparsable_sections(&converted.tree, converted.expected));
            Some(converted.tree)
        }
        Err(stop) => {
            errors.push(stop.clone());
            None
        }
    };
    let times = ParseTimes {
        setup,
        lex,
        parse,
        convert: clock.lap(),
        tokens: tokens.len(),
    };
    if options.free_memory {
        drop(parser);
        drop(root);
    } else {
        std::mem::forget(root);
        std::mem::forget(parser);
        std::mem::forget(tokens);
        std::mem::forget(lexer);
    }
    Ok(Parsed {
        tree,
        errors,
        times,
    })
}

struct Clock(Instant);

impl Clock {
    fn new() -> Self {
        Clock(Instant::now())
    }

    /// The time since the last lap.
    fn lap(&mut self) -> Duration {
        let now = Instant::now();
        let d = now.duration_since(self.0);
        self.0 = now;
        d
    }
}

/// The text of an unparsable section in its message: the raw text, or its
/// first 40 characters and "..." if it has 40 or more.
fn section_text(raw: &str) -> String {
    if raw.chars().nth(39).is_none() {
        return raw.to_string();
    }
    let end = raw.char_indices().nth(40).map_or(raw.len(), |(i, _)| i);
    format!("{}...", &raw[..end])
}

/// A diagnostic for each unparsable section, in pre-order: each node of the
/// type `unparsable` that is not in another one (the sqlfluff
/// `iter_unparsables`). `expected` has the expected text of each
/// `Node::Unparsable`, in pre-order.
fn unparsable_sections(tree: &SyntaxTree, expected: Vec<(NodeId, String)>) -> Vec<Diagnostic> {
    let mut expected = expected.into_iter().peekable();
    let mut out = Vec::new();
    let mut end = 0usize;
    for id in tree.nodes() {
        if id.index() < end || tree.ty(id) != SegmentType::UNPARSABLE {
            continue;
        }
        end = id.index() + 1 + tree.descendants(id).len();
        while expected.next_if(|(e, _)| *e < id).is_some() {}
        let text = expected.next_if(|(e, _)| *e == id).map(|(_, t)| t);
        let start = tree.range(id).start;
        let at = tree.start_pos(id);
        let source = tree.source_range(id).start;
        let source_at = tree.source_pos(id);
        out.push(Diagnostic {
            code: Code::Parse,
            message: format!(
                "Line {}, Position {}: Found unparsable section: {}",
                at.line,
                at.pos,
                sqll_types::token::python_repr(&section_text(tree.raw(id)))
            ),
            templated: Some(Location::new(start, at)),
            source: Some(Location::new(source, source_at)),
            node: Some(id),
            expected: text,
        });
    }
    out
}

/// The steps of [`parse`], for the tests and tools that compare the
/// `SyntaxTree` with the parser tree (`Node`). They are not part of the
/// frozen interface: new code calls `parse`.
///
/// `lexer`, `lex`, and `parse_tokens` are not inlined, so that each step
/// has a symbol for a profile also in the release build with link-time
/// optimization (the phases of `scripts/s3/speed_profile.py`).
pub mod steps {
    use super::*;

    /// The lexer of the dialect (the lazy lexer tables).
    #[inline(never)]
    pub fn lexer(dialect: Dialect) -> Lexer {
        Lexer::new(None, dialect.get_lexers().clone())
            .with_bracket_pairs(dialect.get_bracket_pairs().clone())
    }

    /// The tokens of the templated text of the map, and a diagnostic for
    /// each lex error.
    #[inline(never)]
    pub fn lex(lexer: &Lexer, map: &SourceMap) -> (Vec<Token>, Vec<Diagnostic>) {
        let (tokens, lex_errors) = lexer.lex(LexInput::TemplatedFile(Arc::clone(map.file())), true);
        if lex_errors.is_empty() {
            return (tokens, Vec::new());
        }
        // The lexer makes one error for each "unlexable" token, in order.
        let markers = tokens
            .iter()
            .filter(|t| t.token_type == "unlexable")
            .map(|t| t.pos_marker.as_ref());
        let lines = LineIndex::new(map.templated_text());
        let errors = lex_errors
            .iter()
            .zip(markers.chain(std::iter::repeat(None)))
            .map(|(e, marker)| {
                let templated = marker.and_then(|m| {
                    let byte = map.templated_byte_of_char(m.templated_slice.start)?;
                    let at = lines.as_ref()?.line_pos(map.templated_text(), byte)?;
                    Some(Location::new(byte, at))
                });
                // The line and position of the lexer (the sqlfluff source
                // position of the token), with the source byte of the token.
                let source = marker
                    .and_then(|m| map.source_byte_of_char(m.source_slice.start))
                    .map(|byte| Location {
                        byte,
                        line: e.line_no,
                        pos: e.line_pos,
                    });
                Diagnostic {
                    code: Code::Lex,
                    message: e
                        .description
                        .clone()
                        .unwrap_or_else(|| "lex error".to_string()),
                    templated,
                    source,
                    node: None,
                    expected: None,
                }
            })
            .collect();
        (tokens, errors)
    }

    /// The parser of the tokens, with the limits of the options.
    pub fn parser<'a>(tokens: &'a [Token], dialect: Dialect, options: &ParseOptions) -> Parser<'a> {
        let indentation = options
            .indentation
            .iter()
            .map(|(k, v)| (super::static_key(k), *v))
            .collect();
        let depth = depth_limit(options.max_parse_depth);
        Parser::new_with_max_parse_depth(tokens, dialect, indentation, depth)
            .with_parser_limits(options.max_parser_iterations, options.parser_warn_threshold)
            .with_node_limit(options.max_parse_nodes)
    }

    /// The parser tree, or the diagnostic of the parser stop.
    #[inline(never)]
    pub fn parse_tokens(parser: &mut Parser) -> Result<Node, Diagnostic> {
        parser.root_parse().map_err(|e| Diagnostic {
            code: Code::Parse,
            message: e.message,
            templated: None,
            source: None,
            node: None,
            expected: None,
        })
    }

    /// The parser tree of the templated text of the file (as [`parse`]
    /// makes it), or the diagnostic of the parser stop. The lex errors do
    /// not stop the parse.
    pub fn parse_node(
        file: Arc<TemplatedFile>,
        dialect: Dialect,
        options: &ParseOptions,
    ) -> Result<Node, String> {
        let map = SourceMap::new(file).map_err(|e| e.to_string())?;
        let (tokens, _) = lex(&lexer(dialect), &map);
        let mut parser = parser(&tokens, dialect, options);
        parse_tokens(&mut parser).map_err(|d| d.message)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_parse_depth_is_at_most_the_limit() {
        assert_eq!(MAX_PARSE_DEPTH_LIMIT, 10_000);
        for (value, want) in [
            (0, 10_000),
            (1, 1),
            (600, 600),
            (10_000, 10_000),
            (10_001, 10_000),
            (usize::MAX, 10_000),
        ] {
            assert_eq!(depth_limit(value), want, "{value}");
        }
    }

    #[test]
    fn the_section_text_is_that_of_sqlfluff() {
        let a39 = "a".repeat(39);
        let a40 = "a".repeat(40);
        let e41 = "é".repeat(41);
        assert_eq!(section_text(""), "");
        assert_eq!(section_text(&a39), a39);
        assert_eq!(section_text(&a40), format!("{a40}..."));
        assert_eq!(section_text(&e41), format!("{}...", "é".repeat(40)));
    }

    #[test]
    fn a_diagnostic_line_is_that_of_sqll_parse() {
        let at = Location {
            byte: 7,
            line: 1,
            pos: 8,
        };
        let mut d = Diagnostic {
            code: Code::Lex,
            message: "Unable to lex characters: \"'abc\\n\"".into(),
            templated: Some(at),
            source: Some(at),
            node: None,
            expected: None,
        };
        assert_eq!(
            d.to_string(),
            "LXR L1 P8: Unable to lex characters: \"'abc\\n\""
        );
        d.code = Code::Parse;
        d.source = None;
        d.message = "Maximum parse depth exceeded".into();
        assert_eq!(d.to_string(), "PRS: Maximum parse depth exceeded");
    }
}
