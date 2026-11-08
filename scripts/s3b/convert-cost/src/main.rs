// S3b task C7: the measurement tool of the conversion cost (the parser tree
// to the SyntaxTree, docs/interfaces/tree.md). This is not sqll and not a
// harness tool.
//
// Parts of this file are a port of sqlfluff 4.4.0 code (its sqlfluffrs
// crates), through crates/sqll/src/parse.rs (S3b C9 moved these calls to
// crates/sqll_syntax/src/parse.rs): the lexer and parser calls of
// sqlfluffrs/src/test_harness.rs (FixtureTest::run) and the parser limits of
// sqlfluffrs/sqlfluffrs_parser/src/parser/python.rs (PyParser). The limits
// and the indentation values are the defaults of
// src/sqlfluff/core/default_config.cfg.
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.
//
// Usage: sqll-s3b-convert-cost RUNS   (stdin: one "DIALECT<TAB>FILE" line each)
//
// For each line, one JSON object on stdout. The memory allocator is that of
// the sqll binary (crates/sqll/src/alloc.rs), with a count of each block
// while a memory step runs:
// - memory: one lex, parse, and conversion with the counts on: the blocks
//   and the asked bytes of each step, the peak of the live bytes above the
//   live bytes before the step, and the live bytes that the step keeps.
//   "parse" keeps the Node tree; "convert" keeps the SyntaxTree and the side
//   lists of the conversion.
// - times: RUNS runs of lex, parse, and conversion with the counts off,
//   after one run that makes the lazy values of the dialect. Each time is
//   the wall time of the step alone, in nanoseconds.
// Bytes are the sizes that the program asks for, not the sizes that the
// allocator gives. Exit code 1: a file does not parse or does not convert.

#[path = "../../../../crates/sqll/src/alloc.rs"]
#[allow(dead_code)]
mod alloc;

use std::alloc::{GlobalAlloc, Layout};
use std::io::{self, BufRead, Write};
use std::process::ExitCode;
use std::str::FromStr;
use std::sync::atomic::{AtomicBool, AtomicI64, AtomicU64, Ordering::Relaxed};
use std::time::Instant;

use serde_json::json;
use sqll_dialects::Dialect;
use sqll_lexer::{LexInput, Lexer};
use sqll_parser::parser::{Node, Parser};
use sqll_types::Token;

// The default values of sqll parse (crates/sqll_config/src/defaults.rs,
// crates/sqll_cli/src/parse/steps.rs).
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

static ON: AtomicBool = AtomicBool::new(false);
static ALLOCS: AtomicU64 = AtomicU64::new(0);
static ALLOC_BYTES: AtomicU64 = AtomicU64::new(0);
static LIVE_BYTES: AtomicI64 = AtomicI64::new(0);
static PEAK_BYTES: AtomicI64 = AtomicI64::new(0);

fn grow(delta: i64) {
    let live = LIVE_BYTES.fetch_add(delta, Relaxed) + delta;
    PEAK_BYTES.fetch_max(live, Relaxed);
}

fn count_alloc(size: usize) {
    if ON.load(Relaxed) {
        ALLOCS.fetch_add(1, Relaxed);
        ALLOC_BYTES.fetch_add(size as u64, Relaxed);
        grow(size as i64);
    }
}

unsafe impl GlobalAlloc for Counting {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        count_alloc(layout.size());
        unsafe { alloc::Allocator.alloc(layout) }
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        count_alloc(layout.size());
        unsafe { alloc::Allocator.alloc_zeroed(layout) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        if ON.load(Relaxed) {
            LIVE_BYTES.fetch_sub(layout.size() as i64, Relaxed);
        }
        unsafe { alloc::Allocator.dealloc(ptr, layout) }
    }

    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        // A realloc is not a new block. Its growth counts as asked bytes.
        if ON.load(Relaxed) {
            let delta = new_size as i64 - layout.size() as i64;
            if delta > 0 {
                ALLOC_BYTES.fetch_add(delta as u64, Relaxed);
            }
            grow(delta);
        }
        unsafe { alloc::Allocator.realloc(ptr, layout, new_size) }
    }
}

#[global_allocator]
static GLOBAL: Counting = Counting;

/// The counts of one step: from the start of the step to its end.
struct Step {
    allocs: u64,
    alloc_bytes: u64,
    live: i64,
}

impl Step {
    fn start() -> Step {
        let live = LIVE_BYTES.load(Relaxed);
        PEAK_BYTES.store(live, Relaxed);
        Step {
            allocs: ALLOCS.load(Relaxed),
            alloc_bytes: ALLOC_BYTES.load(Relaxed),
            live,
        }
    }

    fn end(self) -> serde_json::Value {
        json!({
            "blocks": ALLOCS.load(Relaxed) - self.allocs,
            "bytes": ALLOC_BYTES.load(Relaxed) - self.alloc_bytes,
            "peak_bytes": PEAK_BYTES.load(Relaxed) - self.live,
            "kept_bytes": LIVE_BYTES.load(Relaxed) - self.live,
        })
    }
}

fn lexer(dialect: &Dialect) -> Lexer {
    Lexer::new(None, dialect.get_lexers().clone())
        .with_bracket_pairs(dialect.get_bracket_pairs().clone())
}

fn lex(lexer: &Lexer, sql: &str) -> Vec<Token> {
    lexer.lex(LexInput::String(sql.to_string()), true).0
}

fn parse(tokens: &[Token], dialect: Dialect) -> Result<Node, String> {
    let indentation = INDENTATION.iter().copied().collect();
    let mut parser =
        Parser::new_with_max_parse_depth(tokens, dialect, indentation, MAX_PARSE_DEPTH)
            .with_parser_limits(MAX_PARSER_ITERATIONS, PARSER_WARN_THRESHOLD)
            .with_node_limit(MAX_PARSE_NODES);
    parser.root_parse().map_err(|e| e.message)
}

fn convert(root: &Node, sql: &str) -> Result<sqll_syntax::Converted, String> {
    sqll_syntax::from_node(root, sql.to_string()).map_err(|e| e.to_string())
}

fn median(mut v: Vec<u128>) -> u128 {
    v.sort_unstable();
    v[v.len() / 2]
}

fn measure(dialect_name: &str, path: &str, runs: usize) -> Result<serde_json::Value, String> {
    let dialect =
        Dialect::from_str(dialect_name).map_err(|_| format!("unknown dialect {dialect_name}"))?;
    let sql = std::fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
    let lexer = lexer(&dialect);
    let fail = |e: String| format!("{path}: {e}");

    // A first run makes the lazy values of the dialect.
    let tokens = lex(&lexer, &sql);
    let root = parse(&tokens, dialect).map_err(fail)?;
    let converted = convert(&root, &sql).map_err(fail)?;
    converted
        .tree
        .verify()
        .map_err(|e| fail(format!("verify: {e}")))?;
    let nodes = converted.tree.node_count();
    let tree_heap_bytes = converted.tree.heap_bytes();
    drop((converted, root, tokens));

    // The memory run.
    ON.store(true, Relaxed);
    let step = Step::start();
    let tokens = lex(&lexer, &sql);
    let lex_memory = step.end();
    let step = Step::start();
    let root = parse(&tokens, dialect).map_err(fail)?;
    let parse_memory = step.end();
    let step = Step::start();
    let converted = convert(&root, &sql).map_err(fail)?;
    let convert_memory = step.end();
    drop((converted, root, tokens));
    ON.store(false, Relaxed);

    // The timed runs.
    let (mut lex_ns, mut parse_ns, mut convert_ns) = (Vec::new(), Vec::new(), Vec::new());
    for _ in 0..runs {
        let t0 = Instant::now();
        let tokens = lex(&lexer, &sql);
        let t1 = Instant::now();
        let root = parse(&tokens, dialect).map_err(fail)?;
        let t2 = Instant::now();
        let converted = convert(&root, &sql).map_err(fail)?;
        let t3 = Instant::now();
        lex_ns.push((t1 - t0).as_nanos());
        parse_ns.push((t2 - t1).as_nanos());
        convert_ns.push((t3 - t2).as_nanos());
        drop((converted, root, tokens));
    }
    Ok(json!({
        "dialect": dialect_name,
        "file": path,
        "bytes": sql.len(),
        "nodes": nodes,
        "tree_heap_bytes": tree_heap_bytes,
        "memory": {
            "lex": lex_memory,
            "parse": parse_memory,
            "convert": convert_memory,
        },
        "runs": runs,
        "median_ns": {
            "lex": median(lex_ns.clone()),
            "parse": median(parse_ns.clone()),
            "convert": median(convert_ns.clone()),
        },
        "min_ns": {
            "lex": lex_ns.iter().min(),
            "parse": parse_ns.iter().min(),
            "convert": convert_ns.iter().min(),
        },
    }))
}

fn run(args: Vec<String>) -> Result<(), String> {
    let runs: usize = match args.as_slice() {
        [n] => n
            .parse()
            .map_err(|_| format!("RUNS is not a number: {n}"))?,
        _ => return Err("usage: sqll-s3b-convert-cost RUNS".into()),
    };
    if runs == 0 {
        return Err("RUNS must be 1 or more".into());
    }
    let out = io::stdout();
    let mut out = out.lock();
    for line in io::stdin().lock().lines() {
        let line = line.map_err(|e| e.to_string())?;
        let (dialect, path) = line
            .split_once('\t')
            .ok_or_else(|| format!("not DIALECT<TAB>FILE: {line:?}"))?;
        let value = measure(dialect, path, runs)?;
        writeln!(out, "{value}").map_err(|e| e.to_string())?;
    }
    Ok(())
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
            eprintln!("sqll-s3b-convert-cost: {e}");
            ExitCode::FAILURE
        }
    }
}
