// Parts of this file are a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/linter/linter.py, runner.py, linted_file.py, and
// src/sqlfluff/core/errors.py.
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The lint (and the fix) of one file: a port of the steps of sqlfluff
//! 4.4.0 for one path (src/sqlfluff/core/linter/linter.py
//! `load_raw_file_and_config`, `render_string`, `parse_rendered`,
//! `lint_parsed`; src/sqlfluff/core/linter/runner.py `iter_rendered` and
//! `iter_partials`; src/sqlfluff/core/errors.py `to_dict`,
//! `ignore_if_in`, `warning_if_in`; src/sqlfluff/core/linter/linted_file.py
//! `deduplicate_in_source_space`; MIT, see THIRD_PARTY.md).
//!
//! The parse is that of `sqll parse` (the raw templater, and the jinja
//! templater for a text with no Jinja tag); the lint is the fix loop of
//! sqll_lint. A form that sqll cannot do yet fails closed.

use std::ops::Range;
use std::time::{Duration, Instant};

use sqll_config::{
    Config, ConfigError, Env, LoadOptions, Loader, ParseSettings, TemplaterName, Value,
};
use sqll_lint::{LintError, LintSettings, Linter, Registry, SourceParser};
use sqll_source::{LineIndex, Templater, TemplaterConfig, TemplaterError};
use sqll_syntax::{Code, Dialect, ParseOptions, Parsed};
use sqll_templater::RawTemplater;
use sqll_tree::SyntaxTree;

use crate::parse::steps;
use crate::{read_sql, unsupported, Error, Source, SqlText};

/// The kind of a violation (the sqlfluff error class).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    /// `SQLLintError` (identifier `linting`).
    Lint,
    /// `SQLParseError` (`PRS`, identifier `parsing`).
    Parse,
    /// `SQLLexError` (`LXR`, identifier `lexing`).
    Lex,
}

impl Kind {
    fn identifier(self) -> &'static str {
        match self {
            Kind::Lint => "linting",
            Kind::Parse => "parsing",
            Kind::Lex => "lexing",
        }
    }
}

/// The source positions of a span (the sqlfluff `to_source_dict`): line and
/// position from 1, and the character offset of the start and of the end.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Span {
    pub start_line: usize,
    pub start_pos: usize,
    pub start_file: usize,
    pub end_line: usize,
    pub end_pos: usize,
    pub end_file: usize,
}

/// A fix in the output (the sqlfluff `LintFix.to_dict`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FixOut {
    pub edit_type: &'static str,
    pub edit: String,
    pub span: Span,
}

/// A violation of a file in the output (the sqlfluff `SQLBaseError`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Issue {
    pub kind: Kind,
    pub code: String,
    /// The rule name (empty for a lex or parse error).
    pub name: String,
    pub description: String,
    pub line: usize,
    pub pos: usize,
    /// The source span, if the anchor is literal source text.
    pub span: Option<Span>,
    pub fixes: Vec<FixOut>,
    pub ignore: bool,
    pub warning: bool,
}

impl Issue {
    pub fn fixable(&self) -> bool {
        !self.fixes.is_empty()
    }

    /// The sqlfluff `rule_name`: the rule name, or `????`.
    fn rule_name(&self) -> &str {
        if self.kind == Kind::Lint {
            &self.name
        } else {
            "????"
        }
    }
}

/// The statistics of a record (sqlfluff `LintedDir.add`).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Stats {
    pub source_chars: usize,
    pub templated_chars: usize,
    pub segments: usize,
    pub raw_segments: usize,
}

/// The result of one file.
#[derive(Debug)]
pub struct Linted {
    /// The path of the record (normalized, or `stdin`).
    pub path: String,
    /// The violations, with no duplicate, sorted by line and position.
    pub issues: Vec<Issue>,
    pub stats: Stats,
    /// The step times and the rule times, in seconds.
    pub timings: Vec<(String, f64)>,
    /// The source text (universal newlines, no byte order mark).
    pub source: String,
    /// The source text after the fixes (fix only).
    pub fixed: String,
    pub bom: bool,
}

impl Linted {
    /// The sqlfluff `get_violations` with the default filters (no ignored
    /// violation; no warning if `filter_warning`).
    pub fn violations(&self, filter_warning: bool) -> impl Iterator<Item = &Issue> {
        self.issues
            .iter()
            .filter(move |i| !i.ignore && !(filter_warning && i.warning))
    }

    /// The sqlfluff `num_violations()`: no ignored violation, no warning.
    pub fn num_violations(&self) -> usize {
        self.violations(true).count()
    }

    /// The templating and parsing errors (`TMP_PRS_ERROR_TYPES`): all
    /// (`unfiltered`), or with the default filters.
    pub fn tmp_prs(&self, unfiltered: bool) -> usize {
        self.issues
            .iter()
            .filter(|i| i.kind == Kind::Parse && (unfiltered || (!i.ignore && !i.warning)))
            .count()
    }
}

/// What the lint of a path gives.
pub enum Outcome {
    Linted(Box<Linted>, Vec<String>),
    /// The file is over `large_file_skip_byte_limit`: the warning.
    Skipped(String),
}

/// The state of a lint run: the config reader, the root config, and the
/// rules.
pub struct Run<'e> {
    pub loader: Loader<'e>,
    pub options: LoadOptions,
    pub root: Config,
    pub registry: Registry,
    pub fix: bool,
}

impl<'e> Run<'e> {
    pub fn new(env: &'e Env, options: LoadOptions, root: Config, fix: bool) -> Result<Self, Error> {
        Ok(Run {
            loader: Loader::new(env),
            options,
            root,
            registry: Registry::new(sqll_rules::rules()).map_err(Error::new)?,
            fix,
        })
    }
}

/// A config error in a lint: `unsupported`, or a user error.
pub fn config_error(e: ConfigError) -> Error {
    match e {
        ConfigError::Unsupported(_) => Error::new(e.to_string()),
        other => Error::user(other.to_string()),
    }
}

fn lint_error(e: LintError) -> Error {
    match e {
        LintError::Unsupported(_) => Error::new(e.to_string()),
        LintError::Invalid(m) => Error::user(m),
        LintError::Parse(m) => Error::new(m),
    }
}

/// Python `repr()` of a file name (the `{fname!r}` of sqlfluff).
pub fn py_repr(text: &str) -> String {
    sqll_lint::registry::py_repr(text)
}

/// Lint a file (a path of the file list).
pub fn lint_file(run: &mut Run<'_>, fname: &str) -> Result<Outcome, Error> {
    let file = Config::from_path(&mut run.loader, fname, &run.options).map_err(config_error)?;
    let settings = ParseSettings::for_lint(&run.root, &file, false).map_err(config_error)?;
    let limit = settings.large_file_skip_byte_limit;
    if limit != 0 {
        let size = std::fs::metadata(fname)
            .map_err(|e| Error::new(format!("cannot read {fname}: {e}")))?
            .len();
        if i128::from(size) > i128::from(limit) {
            return Ok(Outcome::Skipped(format!(
                "Length of file {} is {size} bytes which is over the limit of {limit} bytes. \
                 Skipping to avoid parser lock. Users can increase this limit in their config by \
                 setting the 'large_file_skip_byte_limit' value, or disable by setting it to \
                 zero.",
                py_repr(fname)
            )));
        }
    }
    let sql = read_sql(&Source::File(fname.to_string()), settings.encoding)?;
    lint_text(run, fname, sql, &file, &settings)
}

/// Lint stdin (the path `stdin`, the root config).
pub fn lint_stdin(run: &mut Run<'_>) -> Result<Outcome, Error> {
    let root = run.root.clone();
    let settings = ParseSettings::for_lint(&root, &root, true).map_err(config_error)?;
    let sql = read_sql(&Source::Stdin, settings.encoding)?;
    lint_text(run, "stdin", sql, &root, &settings)
}

/// The line separators of Python `str.splitlines`.
fn is_line_break(c: char) -> bool {
    matches!(
        c,
        '\n' | '\r'
            | '\u{b}'
            | '\u{c}'
            | '\u{1c}'
            | '\u{1d}'
            | '\u{1e}'
            | '\u{85}'
            | '\u{2028}'
            | '\u{2029}'
    )
}

/// The first line (from 1) that starts with "-- sqlfluff" (an in-file
/// config line of `process_raw_file_for_config`), if any.
fn config_line(text: &str) -> Option<usize> {
    let mut line = 1;
    let mut at_start = true;
    for (i, c) in text.char_indices() {
        if at_start && text[i..].starts_with("-- sqlfluff") {
            return Some(line);
        }
        at_start = is_line_break(c);
        if at_start {
            line += 1;
        }
    }
    None
}

/// The facts of the first parse that the output needs.
#[derive(Default)]
struct First {
    stats: Stats,
    /// For each diagnostic: the source range of its node and true if the
    /// node is literal source text.
    spans: Vec<Option<(Range<usize>, bool)>>,
    templating: Duration,
    lexing: Duration,
    parsing: Duration,
}

/// The templater and the parse of the lint, which records the facts of the
/// first parse.
struct Recorder<'a> {
    templater: &'a dyn Templater,
    fname: String,
    dialect: Dialect,
    options: ParseOptions,
    first: Option<First>,
    parse_time: Duration,
}

impl SourceParser for Recorder<'_> {
    fn parse(&mut self, source: &str) -> Result<Parsed, LintError> {
        let t0 = Instant::now();
        let file = self
            .templater
            .process(source, &self.fname, &TemplaterConfig::new())
            .map_err(|e| match e {
                TemplaterError::Unsupported { message } => LintError::Unsupported(message),
                e @ TemplaterError::Template { .. } => LintError::Parse(format!("TMP: {e}")),
            })?;
        let templating = t0.elapsed();
        let parsed = sqll_syntax::parse(&file, self.dialect, &self.options)
            .map_err(|e| LintError::Parse(e.to_string()))?;
        if self.first.is_none() {
            self.parse_time = t0.elapsed();
            let t = &parsed.times;
            let mut first = First {
                templating,
                lexing: t.setup + t.lex,
                parsing: t.parse + t.convert,
                ..First::default()
            };
            if let Some(tree) = &parsed.tree {
                first.stats = tree_stats(tree, source);
                first.spans = parsed
                    .errors
                    .iter()
                    .map(|d| {
                        d.node.map(|n| {
                            (
                                tree.source_range(n),
                                !sqll_lint::linter::is_templated(tree, n),
                            )
                        })
                    })
                    .collect();
            }
            self.first = Some(first);
        }
        Ok(parsed)
    }
}

fn tree_stats(tree: &SyntaxTree, source: &str) -> Stats {
    let leaves = tree
        .nodes()
        .filter(|&id| tree.descendants(id).len() == 0)
        .count();
    Stats {
        source_chars: source.chars().count(),
        templated_chars: tree.text().chars().count(),
        segments: tree.node_count(),
        raw_segments: leaves,
    }
}

/// The source positions of a text: line, position, and character offset of
/// a byte.
pub struct Positions<'t> {
    text: &'t str,
    lines: LineIndex,
    ascii: bool,
}

impl<'t> Positions<'t> {
    pub fn new(text: &'t str) -> Result<Self, Error> {
        Ok(Positions {
            text,
            lines: LineIndex::new(text).ok_or_else(|| {
                unsupported("a file of 4 GiB or more", "sqll reads smaller files")
            })?,
            ascii: text.is_ascii(),
        })
    }

    fn char_offset(&self, byte: usize) -> usize {
        if self.ascii {
            byte
        } else {
            self.text[..byte].chars().count()
        }
    }

    /// The span of a source byte range.
    pub fn span(&self, range: Range<usize>) -> Span {
        let start = self
            .lines
            .line_pos(self.text, range.start)
            .expect("a source byte of a node is at a character");
        let end = self
            .lines
            .line_pos(self.text, range.end)
            .expect("a source byte of a node is at a character");
        Span {
            start_line: start.line,
            start_pos: start.pos,
            start_file: self.char_offset(range.start),
            end_line: end.line,
            end_pos: end.pos,
            end_file: self.char_offset(range.end),
        }
    }
}

/// The values of a list setting (`ignore`, `warnings`).
fn list_of(config: &Config, key: &str) -> Vec<String> {
    match config.core(key) {
        Some(Value::List(items)) => items.iter().filter_map(Value::py_str).collect(),
        _ => Vec::new(),
    }
}

fn lint_text(
    run: &mut Run<'_>,
    fname: &str,
    sql: SqlText,
    config: &Config,
    settings: &ParseSettings,
) -> Result<Outcome, Error> {
    let SqlText { text: source, bom } = sql;
    let mut warnings = Vec::new();
    if let Some(line) = config_line(&source) {
        return Err(unsupported(
            &format!("an in-file config line (\"-- sqlfluff\") at line {line} of {fname}"),
            "sqll does not read in-file config lines yet (S7)",
        ));
    }
    if settings.large_file_skip_char_limit != 0 {
        return Err(unsupported(
            "setting core:large_file_skip_char_limit in a lint or a fix",
            "sqll lint and fix read only large_file_skip_byte_limit",
        ));
    }
    let Some(name) = settings.dialect.clone() else {
        let labels: Vec<&str> = crate::info::DIALECTS.iter().map(|d| d.0).collect();
        return Err(Error::user(format!(
            "No dialect was specified. You must configure a dialect or specify one on the \
             command line using --dialect after the command. Available dialects:\n{}",
            labels.join(", ")
        )));
    };
    let dialect =
        steps::dialect(&name).ok_or_else(|| Error::new(format!("Unknown dialect '{name}'")))?;
    if let Some(w) = &settings.templater_warning {
        warnings.push(w.clone());
    }
    crate::parse::config::check_templater(settings, &source)?;
    debug_assert!(matches!(
        settings.templater,
        TemplaterName::Raw | TemplaterName::Jinja
    ));
    warnings.extend(Registry::selection_warnings(config));
    let pack = run.registry.select(config).map_err(lint_error)?;
    let lint_settings = LintSettings::from_config(config).map_err(lint_error)?;
    let linter = Linter {
        pack: &pack,
        settings: lint_settings,
        dialect,
    };
    let mut parser = Recorder {
        templater: &RawTemplater,
        fname: fname.to_string(),
        dialect,
        options: steps::options(settings, true),
        first: None,
        parse_time: Duration::ZERO,
    };
    let t0 = Instant::now();
    let linted = linter
        .lint(&source, &mut parser, run.fix)
        .map_err(lint_error)?;
    let lint_time = t0.elapsed().saturating_sub(parser.parse_time);
    let first = parser.first.take().unwrap_or_default();
    warnings.extend(linted.warnings.iter().cloned());

    let positions = Positions::new(&source)?;
    let mut issues = Vec::new();
    for (i, d) in linted.parse_errors.iter().enumerate() {
        let Some(at) = d.source else {
            return Err(unsupported(
                &format!("the parse error \"{}\" of {fname} in a lint", d.message),
                "it has no position in sqll (a parser limit)",
            ));
        };
        let span = first
            .spans
            .get(i)
            .and_then(|s| s.clone())
            .filter(|(_, literal)| *literal)
            .map(|(r, _)| positions.span(r));
        let kind = match d.code {
            Code::Lex => Kind::Lex,
            Code::Parse => Kind::Parse,
        };
        issues.push(Issue {
            kind,
            code: d.code.as_str().to_string(),
            name: String::new(),
            description: d.message.clone(),
            line: at.line,
            pos: at.pos,
            // A lex error has no segment: no span.
            span: if kind == Kind::Parse { span } else { None },
            fixes: Vec::new(),
            ignore: false,
            warning: false,
        });
    }
    // The parse errors with no duplicate (source_signature).
    let mut seen = Vec::new();
    issues.retain(|i| {
        let key = (i.code.clone(), i.line, i.pos, i.description.clone());
        let new = !seen.contains(&key);
        seen.push(key);
        new
    });
    for v in &linted.violations {
        let fixes: Vec<FixOut> = v
            .fix_records
            .iter()
            .map(|f| {
                let mut span = positions.span(f.anchor_source.clone());
                match f.edit_type {
                    "create_before" => {
                        span.end_line = span.start_line;
                        span.end_pos = span.start_pos;
                        span.end_file = span.start_file;
                    }
                    "create_after" => {
                        span.start_line = span.end_line;
                        span.start_pos = span.end_pos;
                        span.start_file = span.end_file;
                    }
                    _ => {}
                }
                FixOut {
                    edit_type: f.edit_type,
                    edit: f.text.clone(),
                    span,
                }
            })
            .collect();
        let mut span = v.literal.then(|| positions.span(v.source_range.clone()));
        // sqlfluff: a violation with no end takes the positions of its one
        // fix if the fix starts at the violation.
        if span.is_none() && fixes.len() == 1 {
            let f = fixes[0].span;
            if f.start_line == v.start.line && f.start_pos == v.start.pos {
                span = Some(f);
            }
        }
        issues.push(Issue {
            kind: Kind::Lint,
            code: v.code.to_string(),
            name: v.name.to_string(),
            description: v.description.clone(),
            line: v.start.line,
            pos: v.start.pos,
            span,
            fixes,
            ignore: false,
            warning: false,
        });
    }
    let ignore = list_of(config, "ignore");
    let warn = list_of(config, "warnings");
    for i in &mut issues {
        if ignore.iter().any(|x| x == i.kind.identifier()) {
            i.ignore = true;
        }
        if warn.iter().any(|x| *x == i.code || x == i.rule_name()) {
            i.warning = true;
        }
    }
    issues.sort_by_key(|i| (i.line, i.pos));

    let mut timings = vec![
        ("templating".to_string(), first.templating.as_secs_f64()),
        ("lexing".to_string(), first.lexing.as_secs_f64()),
        ("parsing".to_string(), first.parsing.as_secs_f64()),
        ("linting".to_string(), lint_time.as_secs_f64()),
    ];
    timings.extend(
        linted
            .rule_times
            .iter()
            .map(|(code, t)| (code.to_string(), t.as_secs_f64())),
    );
    let fixed = linted.fixed;
    Ok(Outcome::Linted(
        Box::new(Linted {
            path: fname.to_string(),
            issues,
            stats: first.stats,
            timings,
            source,
            fixed,
            bom,
        }),
        warnings,
    ))
}

#[cfg(test)]
mod tests {
    use super::config_line;

    #[test]
    fn an_in_file_config_line_is_found_at_the_start_of_a_line() {
        assert_eq!(config_line("select 1\n-- sqlfluff:dialect:ansi\n"), Some(2));
        assert_eq!(config_line("-- sqlfluff:x"), Some(1));
        assert_eq!(config_line("select 1 -- sqlfluff:x\n"), None);
        assert_eq!(config_line("a\u{c}-- sqlfluff"), Some(2));
        assert_eq!(config_line(" -- sqlfluff"), None);
    }
}
