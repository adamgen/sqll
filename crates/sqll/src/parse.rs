//! The parse of "sqll parse": the raw templater (sqll_templater) and the
//! frozen parse interface of sqll_syntax (docs/interfaces/parse.md, S3b
//! C9). The lexer and parser settings are in sqll_syntax.

use std::str::FromStr;

use sqll_source::{Templater, TemplaterConfig};
use sqll_syntax::{Dialect, ParseOptions, Parsed};
use sqll_templater::RawTemplater;

use crate::timings::Timer;

pub use sqll_syntax::MAX_PARSE_DEPTH;

pub struct Options {
    pub code_only: bool,
    pub include_meta: bool,
    /// The sqlfluff `max_parse_depth` (0: no limit). The parse interface
    /// gives the parser at most `sqll_syntax::MAX_PARSE_DEPTH_LIMIT`.
    pub max_parse_depth: usize,
}

/// Return the dialect with this sqlfluff name.
pub fn dialect(name: &str) -> Option<Dialect> {
    Dialect::from_str(name).ok()
}

/// Template the SQL with the raw templater, then lex, parse, and convert
/// it. If free is false, the parse keeps its memory until the process
/// exits: the command exits after the output, and the operating system
/// frees the memory at less cost (S3 T15). An error is a file that the
/// parse interface cannot give a tree for (`sqll_syntax::ParseError`).
pub fn parse(
    sql: String,
    fname: &str,
    dialect: Dialect,
    options: &Options,
    timer: &mut Timer,
    free: bool,
) -> Result<Parsed, String> {
    let file = RawTemplater
        .process(&sql, fname, &TemplaterConfig::new())
        .map_err(|e| e.to_string())?;
    let mut parse_options = ParseOptions::default();
    parse_options.max_parse_depth = options.max_parse_depth;
    parse_options.free_memory = free;
    timer.mark("setup");
    let parsed = sqll_syntax::parse(&file, dialect, &parse_options).map_err(|e| e.to_string())?;
    if !free {
        std::mem::forget(file);
        std::mem::forget(sql);
    }
    let t = &parsed.times;
    timer.tokens = t.tokens;
    timer.add("setup", t.setup);
    timer.add("lex", t.lex);
    timer.add("parse", t.parse);
    timer.add("record", t.convert);
    timer.restart();
    Ok(parsed)
}
