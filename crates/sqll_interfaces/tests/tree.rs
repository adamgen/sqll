//! The interface test of the syntax tree (docs/interfaces/tree.md, S3b task
//! C7).
//!
//! - The signatures of the interface are those of the document (a change
//!   does not compile).
//! - Small trees: navigation, `is_type`, positions with multi-byte UTF-8
//!   and CRLF, an unparsable node.
//! - Each of the 2306 dialect fixtures: the conversion of its parser tree
//!   is lossless and equal to the parser tree, node for node
//!   (`sqll_interfaces::tree_check`). Also through the raw templater
//!   (`parse_file`, `from_node_with_source`): the same check, an identity
//!   source map, and the same tree as with no map.
//! - Each of the 84 S2 parse inputs: the same check (ignored by default;
//!   `scripts/s3b/tree_check.py check` builds the inputs and runs it).

use std::ops::Range;
use std::path::PathBuf;
use std::sync::Arc;

use sqll_dialects::Dialect;
use sqll_interfaces::parse::{parse, parse_file};
use sqll_interfaces::tree_check::{check, Counts};
use sqll_interfaces::{dialect_fixtures, dialects, with_parse_stack, FIXTURES};
use sqll_parser::parser::Node;
use sqll_source::{SourceMap, Templater, TemplaterConfig};
use sqll_syntax::{from_node, from_node_with_source, kind_of, ConvertError, Converted};
use sqll_templater::RawTemplater;
use sqll_tree::{
    Children, LineIndex, LinePos, NodeId, SegmentKind, SegmentType, SyntaxTree, TreeBuilder,
    TreeError, Variant,
};

/// The nodes of the trees of the dialect fixtures (also in
/// tests/segment_kinds.rs).
const FIXTURE_NODES: usize = 685224;
/// The S2 parse inputs (harness/bench.md, "Inputs") and the nodes of their
/// trees (results/S3b/C4-tree-cost.json).
const S2_PARSE_INPUTS: usize = 84;
const S2_NODES: usize = 280339;
/// The folder of the S2 inputs: `<dialect>/<size>.sql`.
const S2_INPUTS_ENV: &str = "SQLL_S2_PARSE_INPUTS";

/// The signatures of the interface. A change of one of them is a change of
/// the frozen interface: this function does not compile.
#[allow(dead_code)]
fn signatures(tree: &SyntaxTree, c: Converted) {
    let _: fn(String) -> Result<TreeBuilder, TreeError> = TreeBuilder::new;
    let _: fn(String, usize) -> Result<TreeBuilder, TreeError> = TreeBuilder::with_capacity;
    let _: fn(&mut TreeBuilder, SegmentKind) -> Result<NodeId, TreeError> = TreeBuilder::start_node;
    let _: fn(&mut TreeBuilder) -> Result<NodeId, TreeError> = TreeBuilder::finish_node;
    let _: fn(&mut TreeBuilder, SegmentKind, &str) -> Result<NodeId, TreeError> = TreeBuilder::leaf;
    let _: fn(&mut TreeBuilder, SegmentKind) -> Result<NodeId, TreeError> = TreeBuilder::meta;
    let _: fn(&TreeBuilder) -> usize = TreeBuilder::cursor;
    let _: fn(TreeBuilder) -> Result<SyntaxTree, TreeError> = TreeBuilder::finish;

    let _: fn(&SyntaxTree) -> &str = SyntaxTree::text;
    let _: fn(&SyntaxTree) -> usize = SyntaxTree::node_count;
    let _: fn(&SyntaxTree) -> NodeId = SyntaxTree::root;
    let _: fn(&SyntaxTree, NodeId) -> SegmentKind = SyntaxTree::kind;
    let _: fn(&SyntaxTree, NodeId) -> SegmentType = SyntaxTree::ty;
    let _: fn(&SyntaxTree, NodeId) -> Variant = SyntaxTree::variant;
    let _: fn(&SyntaxTree, NodeId, SegmentType) -> bool = SyntaxTree::is_type;
    let _: fn(&SyntaxTree, NodeId) -> &'static [SegmentType] = SyntaxTree::class_types;
    let _: fn(&SyntaxTree, NodeId) -> bool = SyntaxTree::is_meta;
    let _: fn(&SyntaxTree, NodeId) -> Range<usize> = SyntaxTree::range;
    let _: fn(&SyntaxTree, NodeId) -> &str = SyntaxTree::raw;
    let _: fn(&SyntaxTree, NodeId) -> Option<NodeId> = SyntaxTree::parent;
    let _: fn(&SyntaxTree, NodeId) -> Children<'_> = SyntaxTree::children;
    let _: fn(&SyntaxTree) -> &LineIndex = SyntaxTree::line_index;
    let _: fn(&SyntaxTree, usize) -> Option<LinePos> = SyntaxTree::line_pos;
    let _: fn(&SyntaxTree, NodeId) -> LinePos = SyntaxTree::start_pos;
    let _: fn(&SyntaxTree) -> usize = SyntaxTree::heap_bytes;
    let _: fn(&SyntaxTree) -> Result<(), TreeError> = SyntaxTree::verify;
    let _: Vec<NodeId> = tree.nodes().collect();
    let _: Vec<NodeId> = tree.descendants(tree.root()).collect();
    let _: Vec<NodeId> = tree
        .descendants_of_kind(tree.root(), tree.kind(NodeId::ROOT))
        .collect();
    let _: Vec<NodeId> = tree
        .descendants_of_type(tree.root(), SegmentType::KEYWORD)
        .collect();
    let _: Vec<NodeId> = tree.raw_segments(tree.root()).collect();

    let _: fn(&LineIndex) -> usize = LineIndex::line_count;
    let _: fn(&LineIndex, usize) -> Option<usize> = LineIndex::line_start;
    let _: fn(&LineIndex, &str, usize) -> Option<LinePos> = LineIndex::line_pos;
    let _: fn(NodeId) -> usize = NodeId::index;

    let _: fn(&Node, String) -> Result<Converted, ConvertError> = from_node;
    let _: fn(&Node) -> Option<SegmentKind> = kind_of;
    let _: (SyntaxTree, Vec<(NodeId, String)>, Vec<(NodeId, String)>) =
        (c.tree, c.expected, c.placeholders);
}

fn ansi() -> Dialect {
    dialects()
        .into_iter()
        .find(|(n, _)| n == "ansi")
        .expect("ansi")
        .1
}

/// Parse, convert, and check one text.
fn convert(dialect: Dialect, sql: &str) -> Result<(Converted, Counts), String> {
    let root = parse(dialect, sql.to_string())?;
    let converted = from_node(&root, sql.to_string()).map_err(|e| e.to_string())?;
    let counts = check(&root, sql, &converted)?;
    Ok((converted, counts))
}

/// Template one text with the raw templater, parse and convert it with its
/// source map, and check the tree (also the source ranges and positions).
/// It must be the tree of `convert`, with each source range and position
/// the templated one.
fn convert_raw(dialect: Dialect, sql: &str, plain: &SyntaxTree) -> Result<Counts, String> {
    let file = RawTemplater
        .process(sql, "fixture.sql", &TemplaterConfig::new())
        .map_err(|e| e.to_string())?;
    let map = Arc::new(SourceMap::new(Arc::new(file)).map_err(|e| e.to_string())?);
    if !map.is_identity() {
        return Err("the raw templater map is not the identity".into());
    }
    let root = parse_file(dialect, Arc::clone(map.file()))?;
    let converted = from_node_with_source(&root, map).map_err(|e| e.to_string())?;
    let counts = check(&root, sql, &converted)?;
    let tree = &converted.tree;
    if tree.node_count() != plain.node_count() {
        return Err(format!(
            "raw templater: {} nodes, not {}",
            tree.node_count(),
            plain.node_count()
        ));
    }
    for (id, other) in tree.nodes().zip(plain.nodes()) {
        let got = (tree.kind(id), tree.range(id), tree.source_range(id));
        let want = (plain.kind(other), plain.range(other), plain.range(other));
        if got != want || tree.source_pos(id) != tree.start_pos(id) || !tree.is_literal(id) {
            return Err(format!(
                "raw templater: node {}: {got:?}, not {want:?}",
                id.index()
            ));
        }
    }
    Ok(counts)
}

fn convert_ok(sql: &'static str) -> Converted {
    with_parse_stack(move || convert(ansi(), sql).map(|(c, _)| c)).unwrap()
}

fn at(line: usize, pos: usize) -> LinePos {
    LinePos { line, pos }
}

#[test]
fn a_small_tree_gives_its_text_types_and_navigation() {
    let sql = "SELECT a, b\nFROM t;\n";
    let tree = convert_ok(sql).tree;
    let root = tree.root();
    assert_eq!(tree.ty(root), SegmentType::FILE);
    assert_eq!(tree.raw(root), sql);
    assert_eq!(tree.range(root), 0..sql.len());
    assert_eq!(tree.parent(root), None);
    assert_eq!(tree.verify(), Ok(()));

    let statements: Vec<NodeId> = tree
        .descendants_of_type(root, SegmentType::STATEMENT)
        .collect();
    assert_eq!(statements.len(), 1);
    let select = tree
        .descendants_of_type(root, SegmentType::SELECT_STATEMENT)
        .next()
        .unwrap();
    assert!(tree.is_type(statements[0], SegmentType::STATEMENT));
    assert!(!tree.is_type(select, SegmentType::STATEMENT));
    assert_eq!(tree.parent(select), Some(statements[0]));
    assert_eq!(tree.raw(select), "SELECT a, b\nFROM t");
    assert_eq!(
        tree.descendants_of_kind(root, tree.kind(select)).next(),
        Some(select)
    );

    // The children of the root, and the parent of each.
    let children: Vec<NodeId> = tree.children(root).collect();
    let types: Vec<&str> = children.iter().map(|&c| tree.ty(c).name()).collect();
    assert_eq!(
        types,
        [
            "statement",
            "statement_terminator",
            "newline",
            "end_of_file"
        ]
    );
    for &c in &children {
        assert_eq!(tree.parent(c), Some(root));
    }

    // The keywords, in order, and the raw segments give the text.
    let keywords: Vec<&str> = tree
        .descendants_of_type(root, SegmentType::KEYWORD)
        .map(|k| tree.raw(k))
        .collect();
    assert_eq!(keywords, ["SELECT", "FROM"]);
    let text: String = tree.raw_segments(root).map(|r| tree.raw(r)).collect();
    assert_eq!(text, sql);
    assert!(tree.raw_segments(root).any(|r| tree.is_meta(r)));
    let eof = *children.last().unwrap();
    assert!(tree.is_meta(eof));
    assert_eq!(tree.range(eof), sql.len()..sql.len());
    assert_eq!(tree.start_pos(eof), at(3, 1));

    // The descendants are the nodes after the root, in pre-order.
    let all: Vec<NodeId> = tree.nodes().collect();
    assert_eq!(all.len(), tree.node_count());
    assert_eq!(
        tree.descendants(root).collect::<Vec<_>>(),
        all[1..].to_vec()
    );
    assert!(tree.heap_bytes() >= sql.len() + 20 * tree.node_count());
}

#[test]
fn positions_count_characters_and_keep_the_carriage_return_in_its_line() {
    // "é" has 2 bytes, "😀" has 4 bytes.
    let sql = "SELECT 'é😀' AS x\r\nFROM t\r\n";
    let tree = convert_ok(sql).tree;
    let leaf = |raw: &str| {
        tree.raw_segments(tree.root())
            .find(|&r| tree.raw(r) == raw)
            .unwrap_or_else(|| panic!("no leaf {raw:?}"))
    };
    let quoted = leaf("'é😀'");
    assert_eq!(tree.range(quoted), 7..15);
    assert_eq!(tree.start_pos(quoted), at(1, 8));
    assert_eq!(tree.start_pos(leaf("AS")), at(1, 13));
    assert_eq!(tree.start_pos(leaf("x")), at(1, 16));
    let newline = leaf("\r\n");
    assert_eq!(tree.start_pos(newline), at(1, 17));
    assert_eq!(
        tree.line_pos(tree.range(newline).start + 1),
        Some(at(1, 18))
    );
    assert_eq!(tree.start_pos(leaf("FROM")), at(2, 1));
    assert_eq!(tree.start_pos(leaf("t")), at(2, 6));
    assert_eq!(tree.line_pos(sql.len()), Some(at(3, 1)));
    assert_eq!(tree.line_pos(sql.len() + 1), None);
    assert_eq!(tree.line_pos(8), Some(at(1, 9)));
    assert_eq!(tree.line_pos(9), None, "inside é");
    assert_eq!(tree.line_index().line_count(), 3);
    assert_eq!(tree.line_index().line_start(2), Some(22));
}

#[test]
fn an_unparsable_part_is_in_the_tree_and_lossless() {
    let sql = "SELECT 1 FROM t WHERE ) ( garbage;\n";
    let tree = convert_ok(sql).tree;
    let bad: Vec<NodeId> = tree
        .descendants_of_type(tree.root(), SegmentType::UNPARSABLE)
        .collect();
    assert!(!bad.is_empty(), "the text has an unparsable part");
    for b in bad {
        assert!(tree.children(b).next().is_some());
    }
    let text: String = tree
        .raw_segments(tree.root())
        .map(|r| tree.raw(r))
        .collect();
    assert_eq!(text, sql);
}

#[test]
fn a_tree_made_with_the_builder() {
    let kind = |ty: SegmentType, v: Variant| {
        *ty.kinds()
            .iter()
            .find(|k| k.data().variant == v)
            .expect("a kind")
    };
    let mut b = TreeBuilder::new("a b".to_string()).unwrap();
    let file = b
        .start_node(kind(SegmentType::FILE, Variant::Segment))
        .unwrap();
    let a = b
        .leaf(kind(SegmentType::KEYWORD, Variant::Raw), "a")
        .unwrap();
    b.meta(kind(SegmentType::INDENT, Variant::Meta)).unwrap();
    b.leaf(kind(SegmentType::WHITESPACE, Variant::Raw), " ")
        .unwrap();
    b.leaf(kind(SegmentType::KEYWORD, Variant::Raw), "b")
        .unwrap();
    assert_eq!(b.finish_node(), Ok(file));
    let tree = b.finish().unwrap();
    assert_eq!(tree.verify(), Ok(()));
    assert_eq!(tree.node_count(), 5);
    assert_eq!(tree.children(file).count(), 4);
    assert_eq!(tree.parent(a), Some(file));
    assert_eq!(a.index(), 1);
    let indent = tree.children(file).nth(1).unwrap();
    assert_eq!(tree.range(indent), 1..1);

    let mut b = TreeBuilder::new("ab".to_string()).unwrap();
    b.start_node(kind(SegmentType::FILE, Variant::Segment))
        .unwrap();
    assert_eq!(
        b.leaf(kind(SegmentType::KEYWORD, Variant::Raw), "b"),
        Err(TreeError::NotNextText { at: 0 })
    );
}

/// The results of `run`: the files, the summed counts, and the problems
/// (one line each); for the raw templater path too, if `run` took it.
#[derive(Default)]
struct Run {
    files: usize,
    total: Counts,
    problems: Vec<String>,
    raw_total: Counts,
    raw_problems: Vec<String>,
}

/// Convert and check each file; with `raw`, also through the raw templater
/// (`convert_raw`).
fn run(files: Vec<(String, Dialect, PathBuf)>, raw: bool) -> Run {
    with_parse_stack(move || {
        let mut out = Run {
            files: files.len(),
            ..Run::default()
        };
        for (_, dialect, path) in files {
            let sql = std::fs::read_to_string(&path).unwrap();
            match convert(dialect, &sql) {
                Ok((converted, counts)) => {
                    out.total += counts;
                    if raw {
                        match convert_raw(dialect, &sql, &converted.tree) {
                            Ok(counts) => out.raw_total += counts,
                            Err(e) => out.raw_problems.push(format!("{}: {e}", path.display())),
                        }
                    }
                }
                Err(e) => out.problems.push(format!("{}: {e}", path.display())),
            }
        }
        out
    })
}

fn report(what: &str, files: usize, total: Counts, problems: &[String]) {
    let passed = files - problems.len();
    eprintln!(
        "tree: {passed} of {files} {what}: lossless and node for node equal \
         ({} nodes: {} raw, {} segment, {} meta, {} unparsable; {} with a position, \
         {} with another source range; {} bytes, {} lines)",
        total.nodes,
        total.raw,
        total.segment,
        total.meta,
        total.unparsable,
        total.positioned,
        total.source_differs,
        total.bytes,
        total.lines
    );
    for p in problems.iter().take(20) {
        eprintln!("tree: FAIL {p}");
    }
}

#[test]
fn each_dialect_fixture_converts_lossless_and_node_for_node() {
    let r = run(dialect_fixtures(), true);
    report("dialect fixtures", r.files, r.total, &r.problems);
    report(
        "dialect fixtures through the raw templater",
        r.files,
        r.raw_total,
        &r.raw_problems,
    );
    assert_eq!(r.files, FIXTURES, "the dialect fixtures");
    assert_eq!(r.problems, Vec::<String>::new());
    assert_eq!(
        r.total.nodes, FIXTURE_NODES,
        "the nodes of the fixture trees"
    );
    assert_eq!(r.raw_problems, Vec::<String>::new());
    assert_eq!(r.raw_total.nodes, FIXTURE_NODES);
    assert_eq!(r.raw_total.positioned, r.total.positioned);
    assert_eq!(r.raw_total.source_differs, 0);
}

/// The S2 parse inputs in the folder of SQLL_S2_PARSE_INPUTS:
/// `<dialect>/<size>.sql` for each size small, medium, and large.
fn s2_inputs() -> Vec<(String, Dialect, PathBuf)> {
    let folder = std::env::var_os(S2_INPUTS_ENV)
        .map(PathBuf::from)
        .unwrap_or_else(|| panic!("set {S2_INPUTS_ENV} (scripts/s3b/tree_check.py)"));
    let mut out = Vec::new();
    for (name, dialect) in dialects() {
        for size in ["small", "medium", "large"] {
            let path = folder.join(&name).join(format!("{size}.sql"));
            assert!(path.is_file(), "no input {}", path.display());
            out.push((name.clone(), dialect, path));
        }
    }
    out
}

#[test]
#[ignore = "needs the S2 inputs: scripts/s3b/tree_check.py check"]
fn each_s2_parse_input_converts_lossless_and_node_for_node() {
    let r = run(s2_inputs(), false);
    report("S2 parse inputs", r.files, r.total, &r.problems);
    assert_eq!(r.files, S2_PARSE_INPUTS, "the S2 parse inputs");
    assert_eq!(r.problems, Vec::<String>::new());
    assert_eq!(r.total.nodes, S2_NODES, "the nodes of the S2 input trees");
}
