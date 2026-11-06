// S3b task C4: the measurement tool of the tree decision
// (docs/decisions/s3b-core.md). This is not sqll and not a harness tool.
//
// Parts of this file are a port of sqlfluff 4.4.0 code (its sqlfluffrs
// crates), through crates/sqll/src/parse.rs: the lexer and parser calls of
// sqlfluffrs/src/test_harness.rs (FixtureTest::run) and the parser limits of
// sqlfluffrs/sqlfluffrs_parser/src/parser/python.rs (PyParser). The limits
// and the indentation values are the defaults of
// src/sqlfluff/core/default_config.cfg.
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.
//
// Usage:
//   sqll-s3b-tree-cost parse   (stdin: one "DIALECT<TAB>FILE" line each)
//   sqll-s3b-tree-cost tables DIALECT...
//
// parse: for each line, one JSON object on stdout with the counts of the
// tree that sqll parse makes for the file (the settings of
// crates/sqll/src/parse.rs), and the heap blocks and bytes of:
// - parse: the allocations of Parser::root_parse (a second parse, after a
//   first parse that makes the lazy values of the dialect);
// - node_tree: the blocks and bytes that a clone of the Node tree keeps;
// - arena: the blocks and bytes that Arena::from_node keeps.
// tables: one JSON object with the distinct strings of the grammar tables
// of the dialects.
// Bytes are the sizes that the program asks for, not the sizes that the
// memory allocator gives. Exit code 1: a file does not parse, or its leaves
// do not give the file again.

use std::alloc::{GlobalAlloc, Layout, System};
use std::collections::BTreeSet;
use std::io::{self, BufRead, Write};
use std::process::ExitCode;
use std::str::FromStr;
use std::sync::atomic::{AtomicI64, AtomicU64, Ordering::Relaxed};

use serde_json::json;
use sqll_dialects::Dialect;
use sqll_lexer::{LexInput, Lexer};
use sqll_parser::parser::{Node, Parser};
use sqll_parser::Arena;

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
// The stack of the command thread of crates/sqll/src/main.rs.
const STACK_SIZE: usize = 256 * 1024 * 1024;

struct Counting;

static ALLOCS: AtomicU64 = AtomicU64::new(0);
static ALLOC_BYTES: AtomicU64 = AtomicU64::new(0);
static LIVE_BLOCKS: AtomicI64 = AtomicI64::new(0);
static LIVE_BYTES: AtomicI64 = AtomicI64::new(0);
static PEAK_BYTES: AtomicI64 = AtomicI64::new(0);

fn grow(delta: i64) {
    let live = LIVE_BYTES.fetch_add(delta, Relaxed) + delta;
    PEAK_BYTES.fetch_max(live, Relaxed);
}

unsafe impl GlobalAlloc for Counting {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        ALLOCS.fetch_add(1, Relaxed);
        ALLOC_BYTES.fetch_add(layout.size() as u64, Relaxed);
        LIVE_BLOCKS.fetch_add(1, Relaxed);
        grow(layout.size() as i64);
        unsafe { System.alloc(layout) }
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        ALLOCS.fetch_add(1, Relaxed);
        ALLOC_BYTES.fetch_add(layout.size() as u64, Relaxed);
        LIVE_BLOCKS.fetch_add(1, Relaxed);
        grow(layout.size() as i64);
        unsafe { System.alloc_zeroed(layout) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        LIVE_BLOCKS.fetch_sub(1, Relaxed);
        LIVE_BYTES.fetch_sub(layout.size() as i64, Relaxed);
        unsafe { System.dealloc(ptr, layout) }
    }

    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        // A realloc is not a new block. Its growth counts as asked bytes.
        let delta = new_size as i64 - layout.size() as i64;
        if delta > 0 {
            ALLOC_BYTES.fetch_add(delta as u64, Relaxed);
        }
        grow(delta);
        unsafe { System.realloc(ptr, layout, new_size) }
    }
}

#[global_allocator]
static GLOBAL: Counting = Counting;

#[derive(Clone, Copy)]
struct Snapshot {
    allocs: u64,
    alloc_bytes: u64,
    live_blocks: i64,
    live_bytes: i64,
}

fn snapshot() -> Snapshot {
    Snapshot {
        allocs: ALLOCS.load(Relaxed),
        alloc_bytes: ALLOC_BYTES.load(Relaxed),
        live_blocks: LIVE_BLOCKS.load(Relaxed),
        live_bytes: LIVE_BYTES.load(Relaxed),
    }
}

#[derive(Default)]
struct Counts {
    nodes: u64,
    raw: u64,
    segment: u64,
    meta: u64,
    unparsable: u64,
    empty: u64,
    max_depth: u64,
    text: String,
    types: BTreeSet<String>,
}

fn walk(node: &Node, depth: u64, c: &mut Counts) {
    c.max_depth = c.max_depth.max(depth);
    match node {
        Node::Raw {
            segment_type,
            raw,
            instance_types,
            class_types,
            ..
        } => {
            c.nodes += 1;
            c.raw += 1;
            c.text.push_str(raw);
            c.types.insert(segment_type.to_string());
            c.types.extend(instance_types.iter().cloned());
            c.types.extend(class_types.iter().cloned());
        }
        Node::Segment {
            segment_type,
            class_types,
            children,
            ..
        } => {
            c.nodes += 1;
            c.segment += 1;
            if let Some(t) = segment_type {
                c.types.insert(t.to_string());
            }
            c.types.extend(class_types.iter().cloned());
            for child in children {
                walk(child, depth + 1, c);
            }
        }
        Node::Meta { .. } => {
            c.nodes += 1;
            c.meta += 1;
        }
        Node::Unparsable { children, .. } => {
            c.nodes += 1;
            c.unparsable += 1;
            for child in children {
                walk(child, depth + 1, c);
            }
        }
        Node::Empty => c.empty += 1,
    }
}

fn lexer(dialect: &Dialect) -> Lexer {
    Lexer::new(None, dialect.get_lexers().clone())
        .with_bracket_pairs(dialect.get_bracket_pairs().clone())
}

fn parse_once(tokens: &[sqll_types::Token], dialect: Dialect) -> Result<Node, String> {
    let indentation = INDENTATION.iter().copied().collect();
    let mut parser =
        Parser::new_with_max_parse_depth(tokens, dialect, indentation, MAX_PARSE_DEPTH)
            .with_parser_limits(MAX_PARSER_ITERATIONS, PARSER_WARN_THRESHOLD)
            .with_node_limit(MAX_PARSE_NODES);
    parser.root_parse().map_err(|e| e.message)
}

fn measure(dialect_name: &str, path: &str) -> Result<serde_json::Value, String> {
    let dialect =
        Dialect::from_str(dialect_name).map_err(|_| format!("unknown dialect {dialect_name}"))?;
    let sql = std::fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
    let lexer = lexer(&dialect);
    let (tokens, lex_errors) = lexer.lex(LexInput::String(sql.clone()), true);
    if !lex_errors.is_empty() {
        return Err(format!("{path}: {} lex errors", lex_errors.len()));
    }
    // The first parse makes the lazy values of the dialect (for example
    // the regexes of the grammar). The second parse is the measured one.
    drop(parse_once(&tokens, dialect).map_err(|e| format!("{path}: {e}"))?);

    let before = snapshot();
    PEAK_BYTES.store(before.live_bytes, Relaxed);
    let root = parse_once(&tokens, dialect).map_err(|e| format!("{path}: {e}"))?;
    let after = snapshot();
    let parse_peak = PEAK_BYTES.load(Relaxed) - before.live_bytes;

    let c0 = snapshot();
    let copy = root.clone();
    let c1 = snapshot();
    drop(copy);

    let a0 = snapshot();
    let arena = Arena::from_node(&root);
    let a1 = snapshot();
    let arena_len = arena.len();
    drop(arena);

    let mut counts = Counts::default();
    walk(&root, 0, &mut counts);
    if counts.text != sql {
        return Err(format!("{path}: the leaves do not give the file again"));
    }
    Ok(json!({
        "dialect": dialect_name,
        "file": path,
        "bytes": sql.len(),
        "lines": sql.lines().count(),
        "tokens": tokens.len(),
        "nodes": counts.nodes,
        "raw": counts.raw,
        "segment": counts.segment,
        "meta": counts.meta,
        "unparsable": counts.unparsable,
        "empty": counts.empty,
        "max_depth": counts.max_depth,
        "lossless": true,
        "types": counts.types.into_iter().collect::<Vec<_>>(),
        "arena_nodes": arena_len,
        "parse": {
            "blocks": after.allocs - before.allocs,
            "bytes": after.alloc_bytes - before.alloc_bytes,
            "peak_bytes": parse_peak,
        },
        "node_tree": {
            "blocks": c1.live_blocks - c0.live_blocks,
            "bytes": c1.live_bytes - c0.live_bytes,
        },
        "arena": {
            "blocks": a1.live_blocks - a0.live_blocks,
            "bytes": a1.live_bytes - a0.live_bytes,
        },
    }))
}

fn tables(names: &[String]) -> Result<serde_json::Value, String> {
    let mut strings = BTreeSet::new();
    let mut segment_types = BTreeSet::new();
    let mut lexer_names = BTreeSet::new();
    let mut per_dialect = serde_json::Map::new();
    for name in names {
        let dialect = Dialect::from_str(name).map_err(|_| format!("unknown dialect {name}"))?;
        let t = dialect.get_root_grammar().tables;
        let own: BTreeSet<&str> = t.strings.iter().copied().collect();
        per_dialect.insert(name.clone(), json!(own.len()));
        strings.extend(own);
        for id in 0..t.segment_type_offsets.len() as u32 {
            if let Some(s) = t.get_segment_type(id) {
                segment_types.insert(s);
            }
        }
        for &idx in t.segment_class_types_data {
            segment_types.insert(t.get_string(idx));
        }
        for matcher in dialect.get_lexers().iter() {
            let mut next = Some(matcher);
            let mut stack = Vec::new();
            while let Some(m) = next {
                lexer_names.insert(m.name.clone());
                stack.extend(m.subdivider.as_deref());
                stack.extend(m.trim_post_subdivide.as_deref());
                next = stack.pop();
            }
        }
    }
    Ok(json!({
        "dialects": names.len(),
        "strings": strings.len(),
        "strings_per_dialect": per_dialect,
        "segment_and_class_types": segment_types.len(),
        "lexer_names": lexer_names.len(),
        "segment_class_and_lexer_names": segment_types
            .iter()
            .map(|s| s.to_string())
            .chain(lexer_names.iter().cloned())
            .collect::<BTreeSet<_>>()
            .len(),
        "all_strings": strings
            .iter()
            .map(|s| s.to_string())
            .chain(lexer_names.iter().cloned())
            .collect::<BTreeSet<_>>(),
    }))
}

fn run(args: Vec<String>) -> Result<(), String> {
    let out = io::stdout();
    let mut out = out.lock();
    match args.first().map(String::as_str) {
        Some("parse") => {
            for line in io::stdin().lock().lines() {
                let line = line.map_err(|e| e.to_string())?;
                let (dialect, path) = line
                    .split_once('\t')
                    .ok_or_else(|| format!("not DIALECT<TAB>FILE: {line:?}"))?;
                let value = measure(dialect, path)?;
                writeln!(out, "{value}").map_err(|e| e.to_string())?;
            }
            Ok(())
        }
        Some("tables") => {
            let value = tables(&args[1..])?;
            writeln!(out, "{value}").map_err(|e| e.to_string())
        }
        _ => Err("usage: sqll-s3b-tree-cost parse | tables DIALECT...".into()),
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let result = std::thread::Builder::new()
        .stack_size(STACK_SIZE)
        .spawn(move || run(args))
        .expect("start the command thread")
        .join()
        .unwrap_or_else(|_| Err("the command thread panicked".into()));
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("sqll-s3b-tree-cost: {e}");
            ExitCode::FAILURE
        }
    }
}
