//! The parse of "sqll parse": the raw templater (sqll_templater) and the
//! frozen parse interface of sqll_syntax (docs/interfaces/parse.md, S3b
//! C9). Since S3b C11 the parse options come from the config
//! (sqll_config::ParseSettings).

use std::str::FromStr;

use sqll_config::ParseSettings;
use sqll_source::{Templater, TemplaterConfig};
use sqll_syntax::{Dialect, ParseOptions, Parsed};
use sqll_templater::RawTemplater;

use crate::timings::Timer;

/// Return the dialect with this sqlfluff name.
pub fn dialect(name: &str) -> Option<Dialect> {
    Dialect::from_str(name).ok()
}

/// The parse options of the settings of the config.
pub fn options(settings: &ParseSettings, free: bool) -> ParseOptions {
    let count = |v: u64| usize::try_from(v).unwrap_or(usize::MAX);
    let mut o = ParseOptions::default();
    o.max_parse_depth = count(settings.max_parse_depth);
    o.max_parse_nodes = count(settings.max_parse_nodes);
    if let Some(n) = settings.max_parser_iterations {
        o.max_parser_iterations = count(n);
    }
    if let Some(n) = settings.parser_warn_threshold {
        o.parser_warn_threshold = count(n);
    }
    o.indentation = settings.indentation.clone();
    o.free_memory = free;
    o
}

/// Template the SQL with the raw templater, then lex, parse, and convert
/// it. The jinja templater gives the same file for a text with no Jinja
/// tag (config::check_templater). If free is false, the parse keeps its
/// memory until the process exits: the command exits after the output,
/// and the operating system frees the memory at less cost (S3 T15). An
/// error is a file that the parse interface cannot give a tree for
/// (`sqll_syntax::ParseError`).
pub fn parse(
    sql: String,
    fname: &str,
    dialect: Dialect,
    settings: &ParseSettings,
    timer: &mut Timer,
    free: bool,
) -> Result<Parsed, String> {
    let file = RawTemplater
        .process(&sql, fname, &TemplaterConfig::new())
        .map_err(|e| e.to_string())?;
    let parse_options = options(settings, free);
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
