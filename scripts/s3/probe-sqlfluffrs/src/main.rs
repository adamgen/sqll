// S3 research probe (task T5). This is not sqll and not a harness tool.
//
// Parts of this file follow sqlfluffrs 4.4.0 code: src/test_harness.rs
// (FixtureTest::run: the lexer and parser calls) and
// sqlfluffrs_parser/src/parser/python.rs (PyParser: the parser limits).
// The limits and the indentation values are the defaults of sqlfluff 4.4.0
// src/sqlfluff/core/default_config.cfg.
// Source: https://github.com/sqlfluff/sqlfluff
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License.
// See THIRD_PARTY.md for the full attribution.
//
// Usage: probe-sqlfluffrs --dialect D [--code-only] [--include-meta]
//                         [--max-parse-depth N] [--timings] FILE
//
// Output: [{"filepath": FILE, "segments": RECORD}], as "sqlfluff parse -f
// json". RECORD is null if the parser gives an error. Exit code 0: a tree
// with no lex error and no unparsable segment. 1: a lex error, a parse
// error, or an unparsable segment (as "sqlfluff parse"). 2: a usage or
// input error. With --timings, the last stderr line is a JSON object with
// the seconds of each phase.

use std::io::Write;
use std::process::ExitCode;
use std::str::FromStr;
use std::time::Instant;

use serde_yaml_ng::Value;
use sqlfluffrs_dialects::Dialect;
use sqlfluffrs_lexer::{LexInput, Lexer};
use sqlfluffrs_parser::parser::Parser;

// sqlfluff core defaults: max_parse_depth, max_parse_nodes,
// rust_parser_max_iterations, rust_parser_warn_threshold.
const MAX_PARSE_DEPTH: usize = 600;
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

struct Args {
    dialect: String,
    file: String,
    code_only: bool,
    include_meta: bool,
    max_parse_depth: usize,
    timings: bool,
}

fn parse_args() -> Result<Args, String> {
    let mut dialect = None;
    let mut file = None;
    let mut code_only = false;
    let mut include_meta = false;
    let mut timings = false;
    let mut max_parse_depth = MAX_PARSE_DEPTH;
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--dialect" => dialect = Some(it.next().ok_or("--dialect needs a value")?),
            "--code-only" => code_only = true,
            "--include-meta" => include_meta = true,
            "--timings" => timings = true,
            "--max-parse-depth" => {
                let v = it.next().ok_or("--max-parse-depth needs a value")?;
                max_parse_depth = v.parse().map_err(|_| format!("bad depth {v:?}"))?;
            }
            _ if arg.starts_with("--") => return Err(format!("unknown option {arg}")),
            _ if file.is_none() => file = Some(arg),
            _ => return Err("only one file".to_string()),
        }
    }
    Ok(Args {
        dialect: dialect.ok_or("--dialect is required")?,
        file: file.ok_or("a file is required")?,
        code_only,
        include_meta,
        max_parse_depth,
        timings,
    })
}

fn has_unparsable(value: &Value) -> bool {
    match value {
        Value::Mapping(map) => map
            .iter()
            .any(|(k, v)| k.as_str() == Some("unparsable") || has_unparsable(v)),
        Value::Sequence(items) => items.iter().any(has_unparsable),
        _ => false,
    }
}

fn run(args: &Args, start: Instant) -> Result<bool, String> {
    let dialect = Dialect::from_str(&args.dialect)
        .map_err(|_| format!("unknown dialect {:?}", args.dialect))?;
    let sql = std::fs::read_to_string(&args.file)
        .map_err(|e| format!("cannot read {}: {e}", args.file))?;

    let lexer = Lexer::new(None, dialect.get_lexers().clone())
        .with_bracket_pairs(dialect.get_bracket_pairs().clone());
    let t_setup = start.elapsed();
    let (tokens, lex_errors) = lexer.lex(LexInput::String(sql), true);
    let t_lex = start.elapsed();
    for e in &lex_errors {
        eprintln!(
            "LXR L{} P{}: {}",
            e.line_no,
            e.line_pos,
            e.description.as_deref().unwrap_or("lex error")
        );
    }

    let indentation = INDENTATION.iter().copied().collect();
    let mut parser =
        Parser::new_with_max_parse_depth(&tokens, dialect, indentation, args.max_parse_depth)
            .with_parser_limits(MAX_PARSER_ITERATIONS, PARSER_WARN_THRESHOLD)
            .with_node_limit(MAX_PARSE_NODES);
    let parsed = parser.root_parse();
    let t_parse = start.elapsed();
    let (record, parse_ok) = match parsed {
        Ok(node) => {
            let record = node
                .as_record(args.code_only, true, args.include_meta)
                .unwrap_or(Value::Null);
            let ok = !has_unparsable(&record);
            (record, ok)
        }
        Err(e) => {
            eprintln!("PRS: {}", e.message);
            (Value::Null, false)
        }
    };
    let t_record = start.elapsed();

    // Not through serde_json::Value: its map sorts the keys, and the key
    // order of a record is the order of the segments.
    let mut out = std::io::BufWriter::new(std::io::stdout().lock());
    let write = |out: &mut std::io::BufWriter<_>| -> Result<(), Box<dyn std::error::Error>> {
        out.write_all(b"[{\"filepath\":")?;
        serde_json::to_writer(&mut *out, &args.file)?;
        out.write_all(b",\"segments\":")?;
        serde_json::to_writer(&mut *out, &record)?;
        out.write_all(b"}]\n")?;
        out.flush()?;
        Ok(())
    };
    write(&mut out).map_err(|e| format!("cannot write: {e}"))?;
    let t_write = start.elapsed();
    if args.timings {
        let s = |d: std::time::Duration| d.as_secs_f64();
        eprintln!(
            "{{\"setup_s\":{:.6},\"lex_s\":{:.6},\"parse_s\":{:.6},\"record_s\":{:.6},\"write_s\":{:.6},\"tokens\":{}}}",
            s(t_setup),
            s(t_lex - t_setup),
            s(t_parse - t_lex),
            s(t_record - t_parse),
            s(t_write - t_record),
            tokens.len()
        );
    }
    Ok(parse_ok && lex_errors.is_empty())
}

fn main() -> ExitCode {
    let start = Instant::now();
    let args = match parse_args() {
        Ok(args) => args,
        Err(e) => {
            eprintln!("error: {e}");
            return ExitCode::from(2);
        }
    };
    match run(&args, start) {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::from(1),
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::from(2)
        }
    }
}
