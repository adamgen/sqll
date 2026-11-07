//! The interface test of the segment kinds (docs/interfaces/segment-kinds.md,
//! S3b task C6).
//!
//! - Each type name of the tables of each dialect has one segment type, and
//!   the type gives the name again. Each segment type of a grammar has a
//!   kind.
//! - Each kind gives its data again: the lookup of its data gives the kind.
//! - Each node of the parse tree of each dialect fixture of the pinned
//!   sqlfluff has a kind. The parse settings are those of `sqll parse`
//!   (crates/sqll/src/parse.rs).
//! - The counts are the recorded counts. A change of the tables or of the
//!   kind rules must change the counts here and in the document.
//!
//! Parts of this file are a port of sqlfluff 4.4.0 code, through
//! crates/sqll/src/parse.rs: the lexer and parser calls of
//! sqlfluffrs/src/test_harness.rs (FixtureTest::run), the parser limits of
//! sqlfluffrs/sqlfluffrs_parser/src/parser/python.rs (PyParser), and the
//! parse limits and indentation defaults of
//! src/sqlfluff/core/default_config.cfg.
//! Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
//! commit 0348222a3bcdb0226563f7349c5a39beb0641955.
//! Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
//! crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::str::FromStr;

use sqll_dialects::Dialect;
use sqll_lexer::{LexInput, Lexer};
use sqll_parser::parser::{MetaType, Node, Parser};
use sqll_tree::{KindKey, Meta, SegmentKind, SegmentType, Variant};
use sqll_types::{GrammarContext, GrammarId, GrammarVariant};

/// The recorded counts (docs/interfaces/segment-kinds.md).
const TYPES: usize = 1329;
const KINDS: usize = 3214;
const KINDS_BY_VARIANT: [(Variant, usize); 5] = [
    (Variant::Raw, 1918),
    (Variant::Segment, 1280),
    (Variant::Meta, 14),
    (Variant::Unparsable, 1),
    (Variant::Empty, 1),
];
/// The dialect fixtures of the pinned sqlfluff (S1: 2306 parse cases).
const FIXTURES: usize = 2306;

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

/// The dialects of the tables: the folders of the generated tables.
fn dialects() -> Vec<(String, Dialect)> {
    let manifest = std::fs::read_to_string(root().join("crates/sqll_dialects/generated.json"))
        .expect("read generated.json");
    let mut names = BTreeSet::new();
    for part in manifest.split("\"path\": \"").skip(1) {
        let path = part.split('"').next().unwrap();
        if let Some(rest) = path.split("/src/dialect/").nth(1) {
            if let Some(name) = rest.strip_suffix("/mod.rs") {
                names.insert(name.to_string());
            }
        }
    }
    assert_eq!(names.len(), 28, "the dialects of generated.json");
    names
        .into_iter()
        .map(|n| {
            let d = Dialect::from_str(&n).unwrap_or_else(|_| panic!("unknown dialect {n}"));
            (n, d)
        })
        .collect()
}

/// The type names of the tables and the lexers of a dialect: the segment
/// types and the class types of the grammars, the lexer names and their
/// types, and the bracket types. The second set is the segment types of the
/// grammars that make a node.
fn table_types(dialect: Dialect) -> (BTreeSet<String>, BTreeSet<String>) {
    let tables = dialect.get_root_grammar().tables;
    let ctx = GrammarContext::new(tables);
    let mut all = BTreeSet::new();
    let mut segment = BTreeSet::new();
    for id in 0..tables.instructions.len() as u32 {
        let gid = GrammarId(id);
        if let Some(t) = ctx.segment_type(gid) {
            all.insert(t.to_string());
            // A Token grammar is a bare class (for example BaseSegment): a
            // Ref to it keeps the token, so it makes no node of its type
            // (build_ref_wrap of sqll_parser).
            if !t.is_empty() && ctx.variant(gid) != GrammarVariant::Token {
                segment.insert(t.to_string());
            }
        }
        all.extend(ctx.segment_class_types(gid).unwrap_or_default());
    }
    let mut stack: Vec<_> = dialect.get_lexers().iter().collect();
    while let Some(m) = stack.pop() {
        all.insert(m.name.clone());
        all.extend(m.kwarg_type.iter().cloned());
        stack.extend(m.subdivider.as_deref());
        stack.extend(m.trim_post_subdivide.as_deref());
    }
    for pair in dialect.get_bracket_pairs().iter() {
        all.insert(pair.start_type.to_string());
        all.insert(pair.end_type.to_string());
    }
    (all, segment)
}

#[test]
fn each_type_name_of_the_tables_has_a_type_and_gives_the_name_again() {
    let mut checked = 0;
    for (name, dialect) in dialects() {
        let (all, segment) = table_types(dialect);
        for t in &all {
            let ty = SegmentType::from_name(t)
                .unwrap_or_else(|| panic!("{name}: the type name {t:?} has no segment type"));
            assert_eq!(ty.name(), t);
            checked += 1;
        }
        for t in &segment {
            let ty = SegmentType::from_name(t).unwrap();
            assert!(
                !ty.kinds().is_empty(),
                "{name}: the segment type {t:?} has no kind"
            );
        }
    }
    assert!(checked > 0);
}

#[test]
fn each_type_gives_its_name_and_its_kinds_again() {
    assert_eq!(SegmentType::COUNT, TYPES);
    let mut kinds = 0;
    let mut previous: Option<&str> = None;
    for ty in SegmentType::all() {
        assert_eq!(SegmentType::from_name(ty.name()), Some(ty));
        assert_eq!(SegmentType::from_index(ty.index()), Some(ty));
        assert!(previous < Some(ty.name()), "the type names are in order");
        previous = Some(ty.name());
        for kind in ty.kinds() {
            assert_eq!(kind.ty(), ty);
            assert_eq!(kind.name(), ty.name());
        }
        kinds += ty.kinds().len();
    }
    assert_eq!(kinds, SegmentKind::COUNT, "each kind has one type");
    assert_eq!(SegmentType::from_index(TYPES as u16), None);
    assert_eq!(SegmentType::from_name("no such type"), None);
    assert_eq!(SegmentType::KEYWORD.name(), "keyword");
    assert_eq!(SegmentType::SELECT_STATEMENT.name(), "select_statement");
    assert_eq!(SegmentType::T_UNLEXABLE_.name(), "<unlexable>");
}

/// The key of the data of a kind, with the names of its types.
struct Names {
    instance_types: Vec<&'static str>,
    class_types: Vec<&'static str>,
}

fn names(types: &[SegmentType]) -> Vec<&'static str> {
    types.iter().map(|t| t.name()).collect()
}

#[test]
fn each_kind_gives_its_data_again() {
    assert_eq!(SegmentKind::COUNT, KINDS);
    let mut by_variant = BTreeMap::new();
    for kind in SegmentKind::all() {
        let d = kind.data();
        *by_variant.entry(d.variant).or_insert(0) += 1;
        assert_eq!(SegmentKind::from_index(kind.index()), Some(kind));
        assert!(kind.is_type(d.ty));
        for t in d.class_types {
            assert!(kind.is_type(*t));
        }
        assert!(
            d.class_types.windows(2).all(|w| w[0] < w[1]),
            "a sorted set"
        );
        let n = Names {
            instance_types: names(d.instance_types),
            class_types: names(d.class_types),
        };
        // The class types in another order give the same kind.
        let mut reversed = n.class_types.clone();
        reversed.reverse();
        for class_types in [&n.class_types, &reversed] {
            let key = KindKey {
                variant: d.variant,
                class: d.class,
                ty: d.ty.name(),
                instance_types: &n.instance_types,
                trim_chars: d.trim_chars,
                quoted_value: d.quoted_value,
                escape_replacements: d.escape_replacements,
                meta: d.meta,
                class_types,
            };
            assert_eq!(SegmentKind::find(&key), Some(kind), "{d:?}");
        }
        // Other data gives no kind or another kind.
        let mut more = n.class_types.clone();
        more.push("no such type");
        let key = KindKey {
            variant: d.variant,
            class: d.class,
            ty: d.ty.name(),
            instance_types: &n.instance_types,
            trim_chars: d.trim_chars,
            quoted_value: d.quoted_value,
            escape_replacements: d.escape_replacements,
            meta: d.meta,
            class_types: &more,
        };
        assert_eq!(SegmentKind::find(&key), None);
    }
    let want: BTreeMap<Variant, usize> = KINDS_BY_VARIANT.into_iter().collect();
    assert_eq!(by_variant, want);
    assert_eq!(SegmentKind::from_index(KINDS as u16), None);
}

/// The key of a parser node.
fn find(node: &Node) -> Option<SegmentKind> {
    let none: &[String] = &[];
    let base = KindKey {
        variant: Variant::Empty,
        class: "",
        ty: "",
        instance_types: none,
        trim_chars: None,
        quoted_value: None,
        escape_replacements: None,
        meta: None,
        class_types: none,
    };
    let quoted;
    let key = match node {
        Node::Raw {
            segment_class,
            segment_type,
            instance_types,
            class_types,
            segment_kwargs: k,
            ..
        } => {
            quoted = k
                .quoted_value
                .as_ref()
                .map(|(a, b)| (a.as_str(), b.as_str()));
            KindKey {
                variant: Variant::Raw,
                class: segment_class,
                ty: segment_type,
                instance_types,
                trim_chars: k.trim_chars.as_deref().map(Vec::as_slice),
                quoted_value: quoted,
                escape_replacements: k.escape_replacements.as_deref().map(Vec::as_slice),
                class_types,
                ..base
            }
        }
        Node::Segment {
            segment_class,
            segment_type,
            class_types,
            ..
        } => KindKey {
            variant: Variant::Segment,
            class: segment_class,
            ty: segment_type.as_deref()?,
            class_types,
            ..base
        },
        Node::Meta { meta_type, .. } => {
            let (ty, meta) = match meta_type {
                MetaType::Indent { is_implicit } => (
                    "indent",
                    Meta::Indent {
                        implicit: *is_implicit,
                    },
                ),
                MetaType::Dedent { is_implicit } => (
                    "dedent",
                    Meta::Dedent {
                        implicit: *is_implicit,
                    },
                ),
                MetaType::Template { block_type, .. } => {
                    ("placeholder", Meta::Template { block_type })
                }
                MetaType::TemplateLoop => ("template_loop", Meta::TemplateLoop),
                MetaType::EndOfFile => ("end_of_file", Meta::EndOfFile),
            };
            KindKey {
                variant: Variant::Meta,
                ty,
                meta: Some(meta),
                ..base
            }
        }
        Node::Unparsable { .. } => KindKey {
            variant: Variant::Unparsable,
            ty: "unparsable",
            ..base
        },
        Node::Empty => KindKey {
            ty: "empty",
            ..base
        },
    };
    SegmentKind::find(&key)
}

fn children(node: &Node) -> &[Node] {
    match node {
        Node::Segment { children, .. } | Node::Unparsable { children, .. } => children,
        _ => &[],
    }
}

// The values of crates/sqll/src/parse.rs.
const MAX_PARSE_DEPTH: usize = 600;
const MAX_PARSE_NODES: usize = 100_000;
const MAX_PARSER_ITERATIONS: usize = 3_000_000;
const PARSER_WARN_THRESHOLD: usize = 2_000_000;
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

fn parse(dialect: Dialect, sql: String) -> Result<Node, String> {
    let lexer = Lexer::new(None, dialect.get_lexers().clone())
        .with_bracket_pairs(dialect.get_bracket_pairs().clone());
    let (tokens, _) = lexer.lex(LexInput::String(sql), true);
    let indentation = INDENTATION.iter().copied().collect();
    let mut parser =
        Parser::new_with_max_parse_depth(&tokens, dialect, indentation, MAX_PARSE_DEPTH)
            .with_parser_limits(MAX_PARSER_ITERATIONS, PARSER_WARN_THRESHOLD)
            .with_node_limit(MAX_PARSE_NODES);
    parser.root_parse().map_err(|e| e.message)
}

#[derive(Default)]
struct Seen {
    nodes: usize,
    kinds: BTreeSet<SegmentKind>,
    missing: BTreeSet<String>,
}

fn walk(node: &Node, seen: &mut Seen) {
    seen.nodes += 1;
    match find(node) {
        Some(kind) => {
            seen.kinds.insert(kind);
        }
        None if seen.missing.len() < 20 => {
            let mut text = format!("{node:?}");
            text.truncate(600);
            seen.missing.insert(text);
        }
        None => {}
    }
    for child in children(node) {
        walk(child, seen);
    }
}

#[test]
fn each_node_of_the_dialect_fixtures_has_a_kind() {
    // The parser recurses: the stack of crates/sqll/src/main.rs.
    let run = std::thread::Builder::new()
        .stack_size(256 * 1024 * 1024)
        .spawn(|| {
            let folder = root().join("third_party/sqlfluff/test/fixtures/dialects");
            let mut seen = Seen::default();
            let mut files = 0;
            let mut errors = Vec::new();
            for (name, dialect) in dialects() {
                let mut paths: Vec<PathBuf> = std::fs::read_dir(folder.join(&name))
                    .unwrap_or_else(|e| panic!("{name}: {e}"))
                    .map(|e| e.unwrap().path())
                    .filter(|p| p.extension().is_some_and(|x| x == "sql"))
                    .collect();
                paths.sort();
                for path in paths {
                    files += 1;
                    let sql = std::fs::read_to_string(&path).unwrap();
                    match parse(dialect, sql) {
                        Ok(tree) => walk(&tree, &mut seen),
                        Err(e) => errors.push(format!("{}: {e}", path.display())),
                    }
                }
            }
            (files, errors, seen)
        })
        .unwrap();
    let (files, errors, seen) = run.join().unwrap();
    assert_eq!(files, FIXTURES, "the dialect fixtures");
    assert!(
        seen.missing.is_empty(),
        "nodes with no kind:\n{:#?}",
        seen.missing
    );
    assert_eq!(errors, Vec::<String>::new());
    eprintln!(
        "{files} fixtures, {} nodes, {} distinct kinds",
        seen.nodes,
        seen.kinds.len()
    );
}
