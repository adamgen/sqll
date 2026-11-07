//! The interface test of the source map and the templater interface
//! (docs/interfaces/source-map.md, S3b task C8).
//!
//! - The signatures of the interface are those of the document (a change
//!   does not compile).
//! - The raw templater: the map is the identity, also with multi-byte UTF-8
//!   and CRLF, and so are the source positions of the syntax tree.
//! - A hand-built `TemplatedFile` with templated sections: the slices that
//!   the pinned sqlfluff Jinja templater gives for the templater fixture
//!   test/fixtures/templater/jinja_a/jinja.sql (with the context of
//!   jinja_a/.sqlfluff: testing_schema=sch1, testing_table=tbl2). The test
//!   reads the source text from the submodule; it keeps no copy of it. It
//!   checks source ranges, points, positions, and the literal check.
//! - The data of the pinned sqlfluff (results/S3b/C8-source-map.json,
//!   scripts/s3b/source_map_oracle.py) for jinja_a, jinja_b (a loop), and
//!   the empty dialect fixture test/fixtures/dialects/ansi/empty_file.sql
//!   (the Jinja templater gives no slices for it):
//!   the map gives the sqlfluff answer for each templated range and each
//!   source offset, and the syntax tree of the sqll parse of the templated
//!   file gives the type, the ranges, the literal flag, and the source
//!   position of each sqlfluff segment.
//! - The 54 templater fixtures of the pinned sqlfluff: each SQL file
//!   directly in a folder of test/fixtures/templater/, and each file of the
//!   case table of test/core/templaters/jinja_test.py (one is in a
//!   subfolder). The same check (ignored by default;
//!   `scripts/s3b/source_map_oracle.py check` makes the data and runs it).
//! - Random invented files (multi-byte characters, CR and LF, parts of raw
//!   slices, overlapping and empty source slices): the map gives the
//!   answers of the pinned sqlfluff `TemplatedFile` for each templated
//!   range and each source offset (ignored by default; the same check
//!   makes the data).
//! - An invented file with source slices out of order: no call panics, and
//!   the answers are those of sqlfluff.
//! - An invented file where the parser puts a meta node before its place:
//!   the conversion fails.

use std::collections::BTreeMap;
use std::ops::Range;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Arc;

use serde_json::Value;
use sqll_dialects::Dialect;
use sqll_interfaces::parse::{parse, parse_file};
use sqll_interfaces::tree_check::check;
use sqll_interfaces::{root, with_parse_stack};
use sqll_source::{
    LineIndex, LinePos, RawFileSlice, Slice, SourceMap, SourceMapError, TemplatedFile,
    TemplatedFileSlice, Templater, TemplaterConfig, TemplaterError,
};
use sqll_syntax::{from_node, from_node_with_source, ConvertError, Converted};
use sqll_templater::RawTemplater;
use sqll_tree::{NodeId, SyntaxTree, TreeBuilder, TreeError};

/// The record of the sqlfluff data.
const RECORD: &str = "results/S3b/C8-source-map.json";
/// The variable of the data file of the ignored test of the fixtures.
const ORACLE_ENV: &str = "SQLL_SOURCE_MAP_ORACLE";
/// The variable of the data file of the ignored test of the random files.
const RANDOM_ENV: &str = "SQLL_SOURCE_MAP_RANDOM";

/// The fixture of the hand-built example (in the sqlfluff submodule).
const JINJA_A: &str = "test/fixtures/templater/jinja_a/jinja.sql";
/// The templated text and the slices (type, source code points, templated
/// code points) that the pinned sqlfluff JinjaTemplater gives for JINJA_A.
/// The record has them too; `the_hand_built_example_is_the_sqlfluff_data`
/// compares.
const JINJA_A_TEMPLATED: &str = "SELECT 56 FROM sch1.tbl2\n";
const JINJA_A_SLICES: [(&str, Range<usize>, Range<usize>); 5] = [
    ("literal", 0..15, 0..15),
    ("templated", 15..35, 15..19),
    ("literal", 35..36, 19..20),
    ("templated", 36..55, 20..24),
    ("literal", 55..56, 24..25),
];

/// The signatures of the interface. A change of one of them is a change of
/// the frozen interface: this function does not compile.
#[allow(dead_code)]
fn signatures(t: &dyn Templater, map: &SourceMap, tree: &SyntaxTree) {
    let _: &'static str = t.name();
    let _: Result<TemplatedFile, TemplaterError> = t.process("", "", &TemplaterConfig::new());
    let _: fn() -> TemplaterConfig = TemplaterConfig::new;
    let _: fn(&mut TemplaterConfig, &str, &str, &str) = TemplaterConfig::set;
    let _: for<'a> fn(&'a TemplaterConfig, &str, &str) -> Option<&'a str> = TemplaterConfig::get;
    let _: for<'a> fn(&'a TemplaterConfig, &str) -> Option<&'a BTreeMap<String, String>> =
        TemplaterConfig::section;
    let config = TemplaterConfig::new();
    let _: Vec<&str> = config.section_names().collect();
    let _ = TemplaterError::Template {
        message: String::new(),
        source_byte: Some(0),
    };
    let _ = TemplaterError::Unsupported {
        message: String::new(),
    };

    let _: fn(Arc<TemplatedFile>) -> Result<SourceMap, SourceMapError> = SourceMap::new;
    let _: fn(String, String) -> Result<SourceMap, SourceMapError> = SourceMap::identity;
    let _: fn(&SourceMap) -> &Arc<TemplatedFile> = SourceMap::file;
    let _: fn(&SourceMap) -> &str = SourceMap::source_text;
    let _: fn(&SourceMap) -> &str = SourceMap::templated_text;
    let _: fn(&SourceMap) -> bool = SourceMap::is_identity;
    let _: fn(&SourceMap) -> &LineIndex = SourceMap::source_lines;
    let _: fn(&SourceMap, Range<usize>) -> Result<Range<usize>, SourceMapError> =
        SourceMap::source_range;
    let _: fn(&SourceMap, usize) -> Result<usize, SourceMapError> = SourceMap::source_byte;
    let _: fn(&SourceMap, usize) -> Option<LinePos> = SourceMap::source_line_pos;
    let _: fn(&SourceMap, usize) -> Result<LinePos, SourceMapError> = SourceMap::source_pos;
    let _: fn(&SourceMap, Range<usize>) -> Result<bool, SourceMapError> =
        SourceMap::is_source_literal;
    let _: fn(&SourceMap, Range<usize>) -> Result<bool, SourceMapError> = SourceMap::is_literal;
    let _: fn(&SourceMap, usize) -> Option<usize> = SourceMap::source_byte_of_char;
    let _: fn(&SourceMap, usize) -> Result<usize, SourceMapError> = SourceMap::source_char_of_byte;
    let _: fn(&SourceMap, usize) -> Option<usize> = SourceMap::templated_byte_of_char;
    let _: fn(&SourceMap, usize) -> Result<usize, SourceMapError> =
        SourceMap::templated_char_of_byte;
    let _ = map;

    let _: fn(Arc<SourceMap>, usize) -> Result<TreeBuilder, TreeError> = TreeBuilder::with_source;
    let _: fn(
        &mut TreeBuilder,
        sqll_tree::SegmentKind,
        &str,
        Range<usize>,
    ) -> Result<NodeId, TreeError> = TreeBuilder::leaf_at;
    let _: fn(&mut TreeBuilder, sqll_tree::SegmentKind, Range<usize>) -> Result<NodeId, TreeError> =
        TreeBuilder::meta_at;
    let _: fn(&SyntaxTree) -> Option<&Arc<SourceMap>> = SyntaxTree::source_map;
    let _: fn(&SyntaxTree) -> &str = SyntaxTree::source_text;
    let _: fn(&SyntaxTree, NodeId) -> Range<usize> = SyntaxTree::source_range;
    let _: fn(&SyntaxTree, NodeId) -> LinePos = SyntaxTree::source_pos;
    let _: fn(&SyntaxTree, NodeId) -> bool = SyntaxTree::is_literal;
    let _ = tree;

    let _: fn(
        &sqll_parser::parser::Node,
        Arc<SourceMap>,
    ) -> Result<Converted, sqll_syntax::ConvertError> = from_node_with_source;
    let _: fn(&str) -> Option<Box<dyn Templater>> = sqll_templater::by_name;
    let _: &[&str] = sqll_templater::NAMES;

    let _: fn(&str) -> Option<LineIndex> = LineIndex::new;
    let _: fn(&LineIndex) -> usize = LineIndex::line_count;
    let _: fn(&LineIndex, usize) -> Option<usize> = LineIndex::line_start;
    let _: fn(&LineIndex, &str, usize) -> Option<LinePos> = LineIndex::line_pos;
}

fn ansi() -> Dialect {
    Dialect::from_str("ansi").expect("ansi")
}

fn at(line: usize, pos: usize) -> LinePos {
    LinePos { line, pos }
}

/// The text of a file of the sqlfluff submodule.
fn sqlfluff_file(rel: &str) -> String {
    let path = root().join("third_party/sqlfluff").join(rel);
    std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

/// A `TemplatedFile` from slices (type, source code points, templated code
/// points), the slice type and block index of each raw slice, and the
/// source text. The raw slices start where the source of a slice starts;
/// their texts are parts of the source text.
fn templated_file(
    source: String,
    fname: &str,
    templated: &str,
    slices: &[(String, Range<usize>, Range<usize>)],
    raws: &[(String, usize, usize, Option<String>)],
) -> TemplatedFile {
    let chars: Vec<char> = source.chars().collect();
    let sliced: Vec<TemplatedFileSlice> = slices
        .iter()
        .map(|(ty, o, t)| {
            TemplatedFileSlice::new(ty.clone(), Slice::from(o.clone()), Slice::from(t.clone()))
        })
        .collect();
    let raw_sliced: Vec<RawFileSlice> = raws
        .iter()
        .enumerate()
        .map(|(i, (ty, start, block, tag))| {
            let end = raws.get(i + 1).map_or(chars.len(), |r| r.1);
            let text: String = chars[*start..end].iter().collect();
            RawFileSlice::new(text, ty.clone(), *start, Some(*block), tag.clone())
        })
        .collect();
    TemplatedFile::new(
        source,
        fname.to_string(),
        Some(templated.to_string()),
        Some(sliced),
        Some(raw_sliced),
    )
}

/// The hand-built `TemplatedFile` of JINJA_A.
fn jinja_a() -> Arc<SourceMap> {
    let slices: Vec<(String, Range<usize>, Range<usize>)> = JINJA_A_SLICES
        .iter()
        .map(|(ty, o, t)| (ty.to_string(), o.clone(), t.clone()))
        .collect();
    let raws: Vec<(String, usize, usize, Option<String>)> = JINJA_A_SLICES
        .iter()
        .map(|(ty, o, _)| (ty.to_string(), o.start, 0, None))
        .collect();
    let file = templated_file(
        sqlfluff_file(JINJA_A),
        JINJA_A,
        JINJA_A_TEMPLATED,
        &slices,
        &raws,
    );
    Arc::new(SourceMap::new(Arc::new(file)).expect("a valid file"))
}

/// Parse and convert a templated file, and check the tree against the
/// parser tree (`tree_check`: also the source ranges and positions).
fn convert_file(dialect: Dialect, map: Arc<SourceMap>) -> Result<Converted, String> {
    let root = parse_file(dialect, Arc::clone(map.file()))?;
    let converted = from_node_with_source(&root, Arc::clone(&map)).map_err(|e| e.to_string())?;
    check(&root, map.templated_text(), &converted)?;
    Ok(converted)
}

#[test]
fn the_raw_templater_gives_the_identity_map() {
    let sql = "SELECT 'é😀' AS x\r\nFROM t\n";
    let file = RawTemplater
        .process(sql, "raw.sql", &TemplaterConfig::new())
        .unwrap();
    assert_eq!(
        (file.source_str.as_str(), file.templated_str.as_str()),
        (sql, sql)
    );
    let map = Arc::new(SourceMap::new(Arc::new(file)).unwrap());
    assert!(map.is_identity());
    let lines = LineIndex::new(sql).unwrap();
    for b in 0..=sql.len() + 1 {
        if sql.is_char_boundary(b) {
            assert_eq!(map.source_byte(b), Ok(b));
            assert_eq!(map.source_range(0..b), Ok(0..b));
            assert_eq!(map.is_literal(b..sql.len()), Ok(true));
            assert_eq!(map.source_line_pos(b), lines.line_pos(sql, b));
            let cp = sql[..b].chars().count();
            assert_eq!(map.source_char_of_byte(b), Ok(cp));
            assert_eq!(map.source_byte_of_char(cp), Some(b));
        } else if b <= sql.len() {
            assert_eq!(
                map.source_byte(b),
                Err(SourceMapError::NotCharBoundary { at: b })
            );
        } else {
            assert_eq!(
                map.source_byte(b),
                Err(SourceMapError::OutOfRange {
                    at: b,
                    len: sql.len()
                })
            );
        }
    }
    assert_eq!(map.source_pos(sql.find("FROM").unwrap()), Ok(at(2, 1)));
    assert_eq!(map.source_pos(sql.find("AS").unwrap()), Ok(at(1, 13)));

    // The tree: each source range and position is the templated one.
    let converted = with_parse_stack({
        let map = Arc::clone(&map);
        move || convert_file(ansi(), map)
    })
    .unwrap();
    let plain = with_parse_stack(move || {
        let root = parse(ansi(), sql.to_string()).unwrap();
        from_node(&root, sql.to_string()).unwrap()
    });
    let tree = &converted.tree;
    assert_eq!(tree.node_count(), plain.tree.node_count());
    assert!(tree.source_map().is_some_and(|m| m.is_identity()));
    assert!(plain.tree.source_map().is_none());
    for id in tree.nodes() {
        assert_eq!(tree.source_range(id), tree.range(id));
        assert_eq!(tree.source_pos(id), tree.start_pos(id));
        assert_eq!(tree.source_range(id), plain.tree.source_range(id));
        assert!(tree.is_literal(id));
    }
    assert_eq!(tree.heap_bytes(), plain.tree.heap_bytes());
}

#[test]
fn the_hand_built_jinja_example_maps_ranges_points_and_positions() {
    let map = jinja_a();
    assert!(!map.is_identity());
    assert_eq!(map.templated_text(), JINJA_A_TEMPLATED);
    // The source text is that of the fixture: "SELECT 56 FROM " (0..15),
    // "{{ testing_schema }}" (15..35), "." (35..36), "{{ testing_table }}"
    // (36..55), "\n" (55..56). ASCII: a byte is a code point.
    let src = map.source_text();
    assert_eq!(&src[15..35], "{{ testing_schema }}");
    assert_eq!(&src[36..55], "{{ testing_table }}");

    // (templated range, source range, literal, source position of the
    // start): the answers of the pinned sqlfluff (the record).
    let cases: [(Range<usize>, Range<usize>, bool, LinePos); 9] = [
        (0..6, 0..6, true, at(1, 1)),       // SELECT
        (7..9, 7..9, true, at(1, 8)),       // 56
        (15..19, 15..35, false, at(1, 16)), // sch1
        (19..20, 35..36, true, at(1, 36)),  // .
        (20..24, 36..55, false, at(1, 37)), // tbl2
        (24..25, 55..56, true, at(1, 56)),  // \n
        (15..24, 15..55, false, at(1, 16)), // sch1.tbl2
        (16..18, 15..35, false, at(1, 16)), // ch (inside sch1)
        (0..25, 0..56, false, at(1, 1)),    // the file
    ];
    for (t, s, literal, pos) in cases {
        assert_eq!(map.source_range(t.clone()), Ok(s.clone()), "{t:?}");
        assert_eq!(map.is_literal(t.clone()), Ok(literal), "{t:?}");
        assert_eq!(map.is_source_literal(s.clone()), Ok(literal), "{s:?}");
        assert_eq!(map.source_line_pos(s.start), Some(pos), "{t:?}");
    }
    // Points: at an edge of a slice, the first source point there; inside
    // a templated section, no point.
    assert_eq!(map.source_byte(15), Ok(15));
    assert_eq!(map.source_byte(19), Ok(35));
    assert_eq!(map.source_byte(20), Ok(36));
    assert_eq!(map.source_byte(24), Ok(55));
    assert_eq!(map.source_byte(25), Ok(56));
    assert_eq!(map.source_pos(25), Ok(at(2, 1)));
    for b in [16, 17, 18, 21, 22, 23] {
        assert_eq!(
            map.source_byte(b),
            Err(SourceMapError::InTemplatedSection { at: b })
        );
    }
    assert_eq!(
        map.source_range(3..26),
        Err(SourceMapError::OutOfRange { at: 26, len: 25 })
    );

    // The tree of the sqll parse of the templated text: each leaf has the
    // source slice of the lexer, each node with children spans them.
    let converted = with_parse_stack(move || convert_file(ansi(), map)).unwrap();
    let tree = &converted.tree;
    let leaf = |raw: &str| {
        tree.raw_segments(tree.root())
            .find(|&r| tree.raw(r) == raw)
            .unwrap_or_else(|| panic!("no leaf {raw:?}"))
    };
    let (sch1, dot, tbl2) = (leaf("sch1"), leaf("."), leaf("tbl2"));
    assert_eq!(tree.source_range(sch1), 15..35);
    assert_eq!(tree.source_range(dot), 35..36);
    assert_eq!(tree.source_range(tbl2), 36..55);
    assert_eq!(tree.source_pos(tbl2), at(1, 37));
    assert_eq!(tree.start_pos(tbl2), at(1, 21));
    assert!(!tree.is_literal(sch1) && tree.is_literal(dot) && !tree.is_literal(tbl2));
    let reference = tree.parent(sch1).unwrap();
    assert_eq!(tree.ty(reference).name(), "table_reference");
    assert_eq!(tree.source_range(reference), 15..55);
    assert!(!tree.is_literal(reference));
    assert_eq!(tree.source_range(tree.root()), 0..56);
    assert_eq!(tree.source_text(), sqlfluff_file(JINJA_A));
}

/// An invented file that `SourceMap::new` accepts, with the source slices
/// out of order: "ab{x--cde" to "abVcde" (the raw slice "--" is in no
/// templated slice). No pinned fixture has this pattern. The answers are
/// those of the pinned sqlfluff TemplatedFile; the unit tests of
/// crates/sqll_source/src/map.rs check each range.
#[test]
fn no_call_of_an_accepted_file_panics() {
    let slices = [
        ("literal".to_string(), 0..2, 0..2),
        ("templated".to_string(), 2..4, 2..3),
        ("literal".to_string(), 6..8, 3..5),
        ("literal".to_string(), 8..9, 5..6),
    ];
    let raws = [
        ("literal".to_string(), 0, 0, None),
        ("templated".to_string(), 2, 0, None),
        ("comment".to_string(), 4, 0, None),
        ("literal".to_string(), 6, 0, None),
        ("literal".to_string(), 8, 0, None),
    ];
    let file = templated_file("ab{x--cde".into(), "f.sql", "abVcde", &slices, &raws);
    let map = SourceMap::new(Arc::new(file)).expect("a valid file");
    assert_eq!(map.source_range(3..5), Ok(4..8));
    assert_eq!(map.is_literal(3..5), Ok(false));
    assert_eq!(map.source_range(3..3), Ok(4..4));
    assert_eq!(map.source_range(4..6), Ok(7..9));
    assert_eq!(map.is_literal(4..6), Ok(true));
}

/// An invented Jinja file (no pinned fixture has this pattern):
/// "SELECT {{- 1 -}} , 2" to "SELECT1, 2", with the slices that the pinned
/// sqlfluff JinjaTemplater gives. The templated text is unparsable. sqlfluff
/// and the sqll parser put the placeholder of "{{- 1 -}}" (templated 6..6)
/// before the unparsable node (templated 0..10). The tree cannot give the
/// placeholder its range, so the conversion fails (fail closed).
#[test]
fn a_meta_node_before_its_place_fails_the_conversion() {
    let slices = [
        ("literal".to_string(), 0..6, 0..6),
        ("literal".to_string(), 6..7, 6..6),
        ("templated".to_string(), 7..16, 6..7),
        ("literal".to_string(), 16..17, 7..7),
        ("literal".to_string(), 17..20, 7..10),
    ];
    let raws = [
        ("literal".to_string(), 0, 0, None),
        ("literal".to_string(), 6, 0, None),
        ("templated".to_string(), 7, 0, None),
        ("literal".to_string(), 16, 0, None),
        ("literal".to_string(), 17, 0, None),
    ];
    let source = "SELECT {{- 1 -}} , 2";
    let file = templated_file(source.into(), "f.sql", "SELECT1, 2", &slices, &raws);
    let map = Arc::new(SourceMap::new(Arc::new(file)).expect("a valid file"));
    let got = with_parse_stack(move || {
        let root = parse_file(ansi(), Arc::clone(map.file())).unwrap();
        from_node_with_source(&root, map).map(|_| ())
    });
    assert!(
        matches!(got, Err(ConvertError::NotAtPosition { node: 1, .. })),
        "{got:?}"
    );
}

/// The fixtures of a data file of scripts/s3b/source_map_oracle.py.
fn oracle(path: PathBuf) -> Vec<Value> {
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let json: Value = serde_json::from_str(&text).expect("JSON");
    assert_eq!(json["kind"], "sqll-s3b-c8-source-map");
    assert_eq!(json["sqlfluff"]["version"], "4.4.0");
    json["fixtures"].as_array().expect("fixtures").clone()
}

fn num(v: &Value) -> usize {
    v.as_u64().expect("a number") as usize
}

fn text(v: &Value) -> String {
    v.as_str().expect("a string").to_string()
}

/// The `TemplatedFile` of a fixture of the data.
fn fixture_file(fx: &Value) -> TemplatedFile {
    let path = text(&fx["path"]);
    data_file(fx, sqlfluff_file(&path), &path)
}

/// The `TemplatedFile` of the slices of the data and a source text.
fn data_file(fx: &Value, source: String, path: &str) -> TemplatedFile {
    let slices: Vec<(String, Range<usize>, Range<usize>)> = fx["sliced_file"]
        .as_array()
        .unwrap()
        .iter()
        .map(|s| (text(&s[0]), num(&s[1])..num(&s[2]), num(&s[3])..num(&s[4])))
        .collect();
    let raws: Vec<(String, usize, usize, Option<String>)> = fx["raw_sliced"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| {
            (
                text(&r[0]),
                num(&r[1]),
                num(&r[2]),
                r[3].as_str().map(String::from),
            )
        })
        .collect();
    templated_file(
        source,
        path,
        fx["templated_str"].as_str().unwrap(),
        &slices,
        &raws,
    )
}

/// The counts of the checked data.
#[derive(Default, Debug)]
struct Counts {
    fixtures: usize,
    ranges: usize,
    errors: usize,
    points: usize,
    segments: usize,
    /// The segments whose sqlfluff templated slice is wider than the range
    /// of their node (a lexed element that a template slice splits).
    split: usize,
}

/// Check one fixture of the data: the map gives each sqlfluff answer, and
/// the syntax tree of the sqll parse has each sqlfluff segment. A fixture
/// with no sqlfluff parse tree fails (fail closed).
fn check_fixture(fx: &Value, counts: &mut Counts) -> Result<(), String> {
    let file = fixture_file(fx);
    if file.source_str.chars().count() != num(&fx["source_chars"]) {
        return Err("the source text is not that of the data".into());
    }
    let map = check_map(fx, Arc::new(file), counts)?;
    let Some(segments) = fx["segments"].as_array() else {
        return Err("sqlfluff gave no parse tree".into());
    };
    check_tree(fx, segments, map, counts)?;
    counts.fixtures += 1;
    Ok(())
}

/// The map of a file gives each sqlfluff answer of the data: each templated
/// range and each source offset.
fn check_map(
    fx: &Value,
    file: Arc<TemplatedFile>,
    counts: &mut Counts,
) -> Result<Arc<SourceMap>, String> {
    let map = Arc::new(SourceMap::new(Arc::clone(&file)).map_err(|e| e.to_string())?);
    let tb = |cp: usize| {
        map.templated_byte_of_char(cp)
            .expect("a templated code point")
    };
    let sb = |cp: usize| map.source_byte_of_char(cp).expect("a source code point");
    for r in fx["ranges"].as_array().unwrap() {
        let (i, j) = (num(&r[0]), num(&r[1]));
        let t = tb(i)..tb(j);
        let got = map.source_range(t.clone());
        if r.as_array().unwrap().len() == 2 {
            if got != Err(SourceMapError::InTemplatedSection { at: t.start }) {
                return Err(format!("range {i}..{j}: {got:?}, not a ValueError"));
            }
            counts.errors += 1;
        } else {
            let want = sb(num(&r[2]))..sb(num(&r[3]));
            let literal = num(&r[4]) == 1;
            if got != Ok(want.clone()) || map.is_literal(t) != Ok(literal) {
                return Err(format!(
                    "range {i}..{j}: {got:?}, not {want:?} (literal {literal})"
                ));
            }
        }
        counts.ranges += 1;
    }
    for (cp, p) in fx["source_points"].as_array().unwrap().iter().enumerate() {
        let want = at(num(&p[0]), num(&p[1]));
        let got = map.source_line_pos(sb(cp));
        let ported = file.get_line_pos_of_char_pos(cp, true);
        if got != Some(want) || ported != (want.line, want.pos) {
            return Err(format!(
                "source offset {cp}: {got:?} (ported {ported:?}), not {want:?}"
            ));
        }
        counts.points += 1;
    }
    Ok(map)
}

/// The syntax tree of the sqll parse of the templated file has each
/// sqlfluff segment, in pre-order.
fn check_tree(
    fx: &Value,
    segments: &[Value],
    map: Arc<SourceMap>,
    counts: &mut Counts,
) -> Result<(), String> {
    let tb = |cp: usize| {
        map.templated_byte_of_char(cp)
            .expect("a templated code point")
    };
    let sb = |cp: usize| map.source_byte_of_char(cp).expect("a source code point");
    let dialect = Dialect::from_str(fx["dialect"].as_str().unwrap()).map_err(|_| "dialect")?;
    let converted = convert_file(dialect, Arc::clone(&map))?;
    let tree = &converted.tree;
    if tree.node_count() != segments.len() {
        return Err(format!(
            "{} nodes, but sqlfluff has {} segments",
            tree.node_count(),
            segments.len()
        ));
    }
    for (id, s) in tree.nodes().zip(segments) {
        let want = (
            text(&s[0]),
            tb(num(&s[1]))..tb(num(&s[2])),
            sb(num(&s[3]))..sb(num(&s[4])),
            num(&s[5]) == 1,
            at(num(&s[6]), num(&s[7])),
        );
        let got = (
            tree.ty(id).name().to_string(),
            tree.range(id),
            tree.source_range(id),
            tree.is_literal(id),
            tree.source_pos(id),
        );
        let wider = got.1 != want.1 && want.1.start <= got.1.start && got.1.end <= want.1.end;
        let same = got.0 == want.0
            && (got.1 == want.1 || wider)
            && (&got.2, got.3, got.4) == (&want.2, want.3, want.4);
        if !same {
            return Err(format!("node {}: {got:?}, not {want:?}", id.index()));
        }
        counts.split += usize::from(wider);
        counts.segments += 1;
    }
    Ok(())
}

fn run(fixtures: Vec<Value>) -> (Counts, Vec<String>) {
    with_parse_stack(move || {
        let mut counts = Counts::default();
        let mut problems = Vec::new();
        for fx in &fixtures {
            if let Err(e) = check_fixture(fx, &mut counts) {
                problems.push(format!("{}: {e}", text(&fx["path"])));
            }
        }
        (counts, problems)
    })
}

fn report(total: usize, what: &str, counts: &Counts, problems: &[String]) {
    eprintln!(
        "source map: {} of {total} {what}: as sqlfluff ({} ranges, {} of them \
         ValueError; {} source offsets; {} segments, {} of them with a wider templated slice)",
        total - problems.len(),
        counts.ranges,
        counts.errors,
        counts.points,
        counts.segments,
        counts.split
    );
    for p in problems.iter().take(20) {
        eprintln!("source map: FAIL {p}");
    }
}

#[test]
fn the_hand_built_example_is_the_sqlfluff_data() {
    let fixtures = oracle(root().join(RECORD));
    let fx = &fixtures[0];
    assert_eq!(fx["path"], JINJA_A);
    assert_eq!(fx["templated_str"], JINJA_A_TEMPLATED);
    let slices: Vec<(String, Range<usize>, Range<usize>)> = fx["sliced_file"]
        .as_array()
        .unwrap()
        .iter()
        .map(|s| (text(&s[0]), num(&s[1])..num(&s[2]), num(&s[3])..num(&s[4])))
        .collect();
    let hand: Vec<(String, Range<usize>, Range<usize>)> = JINJA_A_SLICES
        .iter()
        .map(|(ty, o, t)| (ty.to_string(), o.clone(), t.clone()))
        .collect();
    assert_eq!(slices, hand);
    let raws = fx["raw_sliced"].as_array().unwrap();
    assert_eq!(raws.len(), JINJA_A_SLICES.len());
    for (r, (ty, o, _)) in raws.iter().zip(&hand) {
        assert_eq!(
            (text(&r[0]), num(&r[1]), num(&r[2])),
            (ty.clone(), o.start, 0)
        );
    }
}

#[test]
fn the_recorded_fixtures_map_as_sqlfluff() {
    let fixtures = oracle(root().join(RECORD));
    let total = fixtures.len();
    assert_eq!(total, 3, "jinja_a, jinja_b, and the empty file");
    let (counts, problems) = run(fixtures);
    report(total, "recorded fixtures", &counts, &problems);
    assert_eq!(problems, Vec::<String>::new());
    // The recorded numbers: 351 + 1326 + 1 ranges; 57 + 154 + 1 source
    // offsets; 25 + 69 + 2 segments.
    assert_eq!(
        (counts.ranges, counts.errors, counts.points, counts.segments),
        (1678, 15, 212, 96)
    );
}

#[test]
#[ignore = "needs the data of each templater fixture: scripts/s3b/source_map_oracle.py check"]
fn each_templater_fixture_maps_as_sqlfluff() {
    let path = std::env::var_os(ORACLE_ENV)
        .map(PathBuf::from)
        .unwrap_or_else(|| panic!("set {ORACLE_ENV} (scripts/s3b/source_map_oracle.py)"));
    let fixtures = oracle(path);
    let total = fixtures.len();
    let (counts, problems) = run(fixtures);
    report(total, "templater fixtures", &counts, &problems);
    assert_eq!(problems, Vec::<String>::new());
}

#[test]
#[ignore = "needs the data of the random files: scripts/s3b/source_map_oracle.py check"]
fn random_files_map_as_sqlfluff() {
    let path = std::env::var_os(RANDOM_ENV)
        .map(PathBuf::from)
        .unwrap_or_else(|| panic!("set {RANDOM_ENV} (scripts/s3b/source_map_oracle.py)"));
    let text_of =
        std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let json: Value = serde_json::from_str(&text_of).expect("JSON");
    assert_eq!(json["kind"], "sqll-s3b-c8-source-map-random");
    assert_eq!(json["sqlfluff"]["version"], "4.4.0");
    let files = json["files"].as_array().expect("files");
    let mut counts = Counts::default();
    let mut problems = Vec::new();
    for (k, fx) in files.iter().enumerate() {
        let file = data_file(fx, text(&fx["source_str"]), "random.sql");
        if let Err(e) = check_map(fx, Arc::new(file), &mut counts) {
            problems.push(format!("random file {k}: {e}"));
        }
    }
    let total = files.len();
    eprintln!(
        "source map: {} of {total} random files: as sqlfluff ({} ranges, {} of them \
         ValueError; {} source offsets)",
        total - problems.len(),
        counts.ranges,
        counts.errors,
        counts.points
    );
    for p in problems.iter().take(20) {
        eprintln!("source map: FAIL {p}");
    }
    assert_eq!(problems, Vec::<String>::new());
    assert!(total > 0 && counts.errors > 0);
}
