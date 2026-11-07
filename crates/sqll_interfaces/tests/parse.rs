//! The interface test of the parse interface (docs/interfaces/parse.md, S3b
//! task C9).
//!
//! - The signatures of the interface are those of the document (a change
//!   does not compile).
//! - Each dialect fixture of the pinned sqlfluff: `parse` of the file of the
//!   raw templater gives no diagnostic and the tree of the steps (the
//!   parser tree of `steps::parse_node`, converted with its source map),
//!   node for node, with an identity source map. `free_memory` false gives
//!   the same tree. The steps are those that `parse` calls, so this check
//!   proves the conversion and the options, not the parser tree. The
//!   independent proof of the tree is the fixture test of
//!   `crates/sqll/src/output.rs` (against `Node::as_record`), the tree
//!   guard, and the S1 report.
//! - A templated file: the tree has the source ranges of the source map.
//! - The diagnostics: a lex error, an unparsable section, and a parser stop
//!   give the code, the message, and the places of sqlfluff (the values of
//!   `sqlfluff lint` of the pinned sqlfluff, in the comments).
//! - Fail closed: a file that the source map refuses, and a parse tree that
//!   the conversion refuses, give a `ParseError`.

use std::ops::Range;
use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;

use sqll_dialects::Dialect;
use sqll_interfaces::{dialect_fixtures, with_parse_stack, FIXTURES};
use sqll_source::{
    RawFileSlice, Slice, SourceMap, SourceMapError, TemplatedFile, TemplatedFileSlice, Templater,
    TemplaterConfig,
};
use sqll_syntax::parse::steps::parse_node;
use sqll_syntax::parse::{
    INDENTATION, MAX_PARSER_ITERATIONS, MAX_PARSE_NODES, PARSER_WARN_THRESHOLD,
};
use sqll_syntax::{
    depth_limit, from_node_with_source, parse, Code, ConvertError, Diagnostic, Location,
    ParseError, ParseOptions, ParseTimes, Parsed, MAX_PARSE_DEPTH, MAX_PARSE_DEPTH_LIMIT,
};
use sqll_templater::RawTemplater;
use sqll_tree::{NodeId, SegmentType, SyntaxTree};

/// The signatures of the interface. A change of one of them is a change of
/// the frozen interface: this function does not compile.
#[allow(dead_code)]
fn signatures(p: Parsed, d: Diagnostic, t: ParseTimes) {
    let _: fn(&TemplatedFile, Dialect, &ParseOptions) -> Result<Parsed, ParseError> = parse;
    let _: fn(usize) -> usize = depth_limit;
    let _: (usize, usize) = (MAX_PARSE_DEPTH, MAX_PARSE_DEPTH_LIMIT);
    let mut o = ParseOptions::default();
    o.max_parse_depth = 0;
    o.free_memory = false;
    let _: (Option<SyntaxTree>, Vec<Diagnostic>, ParseTimes) = (p.tree, p.errors, p.times);
    let _: (Code, String, Option<Location>, Option<Location>) =
        (d.code, d.message, d.templated, d.source);
    let _: (Option<NodeId>, Option<String>) = (d.node, d.expected);
    let _: fn(Code) -> &'static str = Code::as_str;
    let _ = [Code::Lex, Code::Parse];
    let at = Location {
        byte: 0,
        line: 1,
        pos: 1,
    };
    let _: (usize, usize, usize) = (at.byte, at.line, at.pos);
    let _: (Duration, Duration, Duration, Duration, usize) =
        (t.setup, t.lex, t.parse, t.convert, t.tokens);
    let _ = |e: ParseError| match e {
        ParseError::SourceMap(e) => e.to_string(),
        ParseError::Convert(e) => e.to_string(),
    };
}

fn ansi() -> Dialect {
    Dialect::from_str("ansi").expect("ansi")
}

fn raw_file(sql: &str) -> TemplatedFile {
    RawTemplater
        .process(sql, "f.sql", &TemplaterConfig::new())
        .expect("the raw templater")
}

/// `parse` on a thread with the stack of `sqll parse`.
fn parse_on_stack(
    file: TemplatedFile,
    dialect: Dialect,
    options: ParseOptions,
) -> Result<Parsed, ParseError> {
    with_parse_stack(move || parse(&file, dialect, &options))
}

/// The tree of the steps: the parser tree, converted with the source map.
fn tree_of_steps(file: &TemplatedFile, dialect: Dialect) -> Result<SyntaxTree, String> {
    let file = Arc::new(file.clone());
    let root = parse_node(Arc::clone(&file), dialect, &ParseOptions::default())?;
    let map = Arc::new(SourceMap::new(file).map_err(|e| e.to_string())?);
    let converted = from_node_with_source(&root, map).map_err(|e| e.to_string())?;
    Ok(converted.tree)
}

/// The two trees are the same, node for node: kind, ranges, parent, and
/// source range.
fn same_tree(a: &SyntaxTree, b: &SyntaxTree) -> Result<(), String> {
    if a.text() != b.text() || a.source_text() != b.source_text() {
        return Err("another text".into());
    }
    if a.node_count() != b.node_count() {
        return Err(format!("{} nodes, not {}", a.node_count(), b.node_count()));
    }
    for id in a.nodes() {
        let same = a.kind(id) == b.kind(id)
            && a.range(id) == b.range(id)
            && a.parent(id) == b.parent(id)
            && a.source_range(id) == b.source_range(id)
            && a.is_literal(id) == b.is_literal(id);
        if !same {
            return Err(format!("node {} is not the same", id.index()));
        }
    }
    Ok(())
}

#[test]
fn the_settings_are_the_sqlfluff_defaults() {
    assert_eq!(MAX_PARSE_DEPTH, 600);
    assert_eq!(MAX_PARSE_DEPTH_LIMIT, 10_000);
    assert_eq!(MAX_PARSE_NODES, 100_000);
    assert_eq!(MAX_PARSER_ITERATIONS, 3_000_000);
    assert_eq!(PARSER_WARN_THRESHOLD, 2_000_000);
    // The [sqlfluff:indentation] section of the default_config.cfg of the
    // pinned sqlfluff, each value as bool(value) of the config value
    // (sqlfluff reads True and False as booleans and 4 as a number; the
    // other values are non-empty strings, thus true).
    assert_eq!(
        INDENTATION,
        &[
            ("indent_unit", true),              // space
            ("tab_space_size", true),           // 4
            ("indented_joins", false),          // False
            ("indented_ctes", false),           // False
            ("indented_using_on", true),        // True
            ("indented_on_contents", true),     // True
            ("indented_then", true),            // True
            ("indented_then_contents", true),   // True
            ("implicit_indents", true),         // forbid
            ("template_blocks_indent", true),   // True
            ("skip_indentation_in", true),      // script_content
            ("skip_implicit_indents_in", true), // case_expression
            ("trailing_comments", true),        // before
            ("ignore_comment_lines", false),    // False
        ]
    );
    let o = ParseOptions::default();
    assert_eq!((o.max_parse_depth, o.free_memory), (600, true));
    for (value, want) in [(0, 10_000), (1, 1), (600, 600), (10_001, 10_000)] {
        assert_eq!(depth_limit(value), want);
    }
}

#[test]
fn each_dialect_fixture_parses_to_the_tree_of_the_steps() {
    let files = dialect_fixtures();
    assert_eq!(files.len(), FIXTURES);
    let problems = with_parse_stack(move || {
        let mut problems = Vec::new();
        let mut nodes = 0;
        for (i, (name, dialect, path)) in files.iter().enumerate() {
            let sql = std::fs::read_to_string(path).expect("read a fixture");
            let file = raw_file(&sql);
            let mut options = ParseOptions::default();
            // The memory of a parse with free_memory false stays until the
            // test exits: only every 100th file.
            options.free_memory = i % 100 != 0;
            let result = parse(&file, *dialect, &options).map_err(|e| e.to_string());
            let check = result.and_then(|parsed| {
                if !parsed.errors.is_empty() {
                    return Err(format!("diagnostics: {:?}", parsed.errors));
                }
                let tree = parsed.tree.ok_or("no tree")?;
                tree.verify().map_err(|e| e.to_string())?;
                if !tree.source_map().is_some_and(|m| m.is_identity()) {
                    return Err("the source map is not the identity".into());
                }
                if parsed.times.tokens == 0 {
                    return Err("no tokens".into());
                }
                nodes += tree.node_count();
                same_tree(&tree, &tree_of_steps(&file, *dialect)?)
            });
            if let Err(e) = check {
                problems.push(format!("{name}/{}: {e}", path.display()));
            }
        }
        eprintln!("parse: {FIXTURES} dialect fixtures, {nodes} nodes");
        assert_eq!(nodes, 685224, "the nodes of the fixture trees (tree.md)");
        problems
    });
    assert_eq!(problems, Vec::<String>::new());
    eprintln!("parse: {FIXTURES} of {FIXTURES} dialect fixtures: the tree of the steps");
}

/// "SELECT {{x}} FROM t" to "SELECT 1 FROM t", with a multi-byte character
/// and a lex error after the templated section.
fn small_templated_file() -> TemplatedFile {
    let source = "SELECT {{x}} FROM é 'a\n";
    let templated = "SELECT 1 FROM é 'a\n";
    let slice = |ty: &str, o: Range<usize>, t: Range<usize>| {
        TemplatedFileSlice::new(ty.into(), Slice::from(o), Slice::from(t))
    };
    let raw = |text: &str, ty: &str, at| RawFileSlice::new(text.into(), ty.into(), at, None, None);
    TemplatedFile::new(
        source.into(),
        "t.sql".into(),
        Some(templated.into()),
        Some(vec![
            slice("literal", 0..7, 0..7),
            slice("templated", 7..12, 7..8),
            slice("literal", 12..23, 8..19),
        ]),
        Some(vec![
            raw("SELECT ", "literal", 0),
            raw("{{x}}", "templated", 7),
            raw(" FROM é 'a\n", "literal", 12),
        ]),
    )
}

#[test]
fn a_templated_file_gives_the_source_ranges_of_its_map() {
    let file = small_templated_file();
    let want = tree_of_steps(&file, ansi()).expect("the tree of the steps");
    let parsed = parse_on_stack(file, ansi(), ParseOptions::default()).expect("a parse");
    let tree = parsed.tree.as_ref().expect("a tree");
    assert_eq!(same_tree(tree, &want), Ok(()));
    assert!(!tree.source_map().expect("a map").is_identity());
    let one = tree
        .raw_segments(tree.root())
        .find(|&id| tree.raw(id) == "1")
        .expect("the literal 1");
    assert_eq!(tree.range(one), 7..8);
    assert_eq!(tree.source_range(one), 7..12);
    assert!(!tree.is_literal(one));
    // The lex errors of "é" and "'a" (sqlfluff: the ansi lexer has no
    // matcher for "é").
    let got: Vec<(Code, Option<Location>, Option<Location>)> = parsed
        .errors
        .iter()
        .filter(|d| d.code == Code::Lex)
        .map(|d| (d.code, d.templated, d.source))
        .collect();
    let loc = |byte, pos| Some(Location { byte, line: 1, pos });
    assert_eq!(
        got,
        [
            (Code::Lex, loc(14, 15), loc(18, 19)),
            (Code::Lex, loc(17, 17), loc(21, 21)),
        ],
        "{:?}",
        parsed.errors
    );
    assert_eq!(
        parsed.errors[1].to_string(),
        "LXR L1 P21: Unable to lex characters: \"'a\""
    );
}

/// The diagnostics of a file, with the code, the templated line and
/// position, the source byte, the message, and the node type.
fn diagnostics(sql: &str) -> (Option<SyntaxTree>, Vec<Diagnostic>) {
    let parsed = parse_on_stack(raw_file(sql), ansi(), ParseOptions::default()).expect("a parse");
    (parsed.tree, parsed.errors)
}

#[test]
fn a_lex_error_and_unparsable_sections_are_diagnostics_as_in_sqlfluff() {
    // sqlfluff lint --dialect ansi --templater raw: PRS at line 1,
    // position 17 (file position 16): "Line 1, Position 17: Found unparsable
    // section: 'where ~~~ x'".
    let (tree, errors) = diagnostics("select 1 from t where ~~~ x\n");
    let tree = tree.expect("a tree");
    assert_eq!(errors.len(), 1, "{errors:?}");
    let d = &errors[0];
    assert_eq!(d.code, Code::Parse);
    assert_eq!(
        d.message,
        "Line 1, Position 17: Found unparsable section: 'where ~~~ x'"
    );
    let at = Location {
        byte: 16,
        line: 1,
        pos: 17,
    };
    assert_eq!((d.templated, d.source), (Some(at), Some(at)));
    let node = d.node.expect("the unparsable node");
    assert_eq!(tree.ty(node), SegmentType::UNPARSABLE);
    assert_eq!(tree.raw(node), "where ~~~ x");
    assert_eq!(d.expected, None);
    assert_eq!(
        d.to_string(),
        "PRS L1 P17: Line 1, Position 17: Found unparsable section: 'where ~~~ x'"
    );

    // sqlfluff: LXR at line 1, position 8: "Unable to lex characters:
    // \"'abc\"", then PRS at line 1, position 8 (file position 7): "Line 1,
    // Position 8: Found unparsable section: \"'abc\"". The lexer of sqll
    // keeps the newline in the unlexable text (a known difference of the
    // ported lexer, not of this interface).
    let (tree, errors) = diagnostics("select 'abc\n");
    assert!(tree.is_some());
    let got: Vec<(Code, Option<Location>, Option<Location>, bool)> = errors
        .iter()
        .map(|d| (d.code, d.templated, d.source, d.node.is_some()))
        .collect();
    let at = Location {
        byte: 7,
        line: 1,
        pos: 8,
    };
    assert_eq!(
        got,
        [
            (Code::Lex, Some(at), Some(at), false),
            (Code::Parse, Some(at), Some(at), true),
        ]
    );
    assert!(errors[0]
        .to_string()
        .starts_with("LXR L1 P8: Unable to lex characters: \"'abc"));
    assert!(errors[1]
        .message
        .starts_with("Line 1, Position 8: Found unparsable section: \"'abc"));
}

#[test]
fn a_long_unparsable_section_has_40_characters_in_its_message() {
    let quoted = format!("'{}'", "é".repeat(45));
    let (_, errors) = diagnostics(&format!("select 1 from t where ~~~ {quoted}\n"));
    assert_eq!(errors.len(), 1, "{errors:?}");
    let shown = format!("where ~~~ '{}...", "é".repeat(29));
    assert_eq!(
        errors[0].message,
        format!("Line 1, Position 17: Found unparsable section: \"{shown}\"")
    );
}

#[test]
fn a_parser_stop_gives_no_tree_and_one_diagnostic() {
    let mut options = ParseOptions::default();
    options.max_parse_depth = 5;
    let parsed = parse_on_stack(raw_file("select (((1)))\n"), ansi(), options).expect("a parse");
    assert!(parsed.tree.is_none());
    assert_eq!(parsed.errors.len(), 1);
    let d = &parsed.errors[0];
    assert_eq!(
        (d.code, d.templated, d.source, d.node),
        (Code::Parse, None, None, None)
    );
    assert!(
        d.to_string()
            .starts_with("PRS: Maximum parse depth exceeded"),
        "{d}"
    );
}

#[test]
fn a_file_that_the_source_map_refuses_is_an_error() {
    let mut file = raw_file("select 1\n");
    file.templated_str.push('x');
    let got = parse_on_stack(file, ansi(), ParseOptions::default()).map(|_| ());
    assert!(
        matches!(
            got,
            Err(ParseError::SourceMap(SourceMapError::InvalidFile(_)))
        ),
        "{got:?}"
    );
}

/// The invented Jinja file of source_map.rs
/// (`a_meta_node_before_its_place_fails_the_conversion`): "SELECT {{- 1 -}}
/// , 2" to "SELECT1, 2". The parse fails closed.
#[test]
fn a_tree_that_the_conversion_refuses_is_an_error() {
    let slice = |ty: &str, o: Range<usize>, t: Range<usize>| {
        TemplatedFileSlice::new(ty.into(), Slice::from(o), Slice::from(t))
    };
    let raw = |text: &str, ty: &str, at| RawFileSlice::new(text.into(), ty.into(), at, None, None);
    let file = TemplatedFile::new(
        "SELECT {{- 1 -}} , 2".into(),
        "f.sql".into(),
        Some("SELECT1, 2".into()),
        Some(vec![
            slice("literal", 0..6, 0..6),
            slice("literal", 6..7, 6..6),
            slice("templated", 7..16, 6..7),
            slice("literal", 16..17, 7..7),
            slice("literal", 17..20, 7..10),
        ]),
        Some(vec![
            raw("SELECT", "literal", 0),
            raw(" ", "literal", 6),
            raw("{{- 1 -}}", "templated", 7),
            raw(" ", "literal", 16),
            raw(", 2", "literal", 17),
        ]),
    );
    let got = parse_on_stack(file, ansi(), ParseOptions::default()).map(|_| ());
    assert!(
        matches!(
            got,
            Err(ParseError::Convert(ConvertError::NotAtPosition {
                node: 1,
                ..
            }))
        ),
        "{got:?}"
    );
}
