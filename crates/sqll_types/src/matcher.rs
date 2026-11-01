// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_types/src/matcher.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.
// sqll changed this file. crates/ported.json gives the reason.

use std::fmt::Display;
use std::sync::{Arc, OnceLock};

use fancy_regex::{Regex as FancyRegex, RegexBuilder as FancyRegexBuilder};
use hashbrown::HashSet;
use regex::{Regex, RegexBuilder};

use crate::{token::CaseFold, PositionMarker, RegexModeGroup, Token, TokenConfig};

// use sqlfluffrs_dialects::Dialect;

/// Function pointer type for token generation: one of `Token::{kind}_token`.
pub type TokenGenerator = fn(String, PositionMarker, TokenConfig) -> Token;

/// A single bracket pair recognised by a dialect. See
/// `utils/build_lexers.py::generate_bracket_pairs` for how these are derived.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BracketPairEntry {
    pub open: &'static str,
    pub close: &'static str,
    pub start_type: &'static str,
    pub end_type: &'static str,
    pub persists: bool,
}

/// A dialect's full set of recognised bracket pairs (round/square/curly plus
/// any dialect-specific additions, e.g. snowflake's exclude `{-`/`-}`).
#[derive(Debug, Clone, Default)]
pub struct BracketPairSet(pub Vec<BracketPairEntry>);

impl BracketPairSet {
    pub fn find_by_open(&self, raw: &str) -> Option<&BracketPairEntry> {
        self.0.iter().find(|p| p.open == raw)
    }

    pub fn is_open(&self, raw: &str) -> bool {
        self.0.iter().any(|p| p.open == raw)
    }

    pub fn is_close(&self, raw: &str) -> bool {
        self.0.iter().any(|p| p.close == raw)
    }

    pub fn position_by_open(&self, raw: &str) -> Option<usize> {
        self.0.iter().position(|p| p.open == raw)
    }

    pub fn position_by_close(&self, raw: &str) -> Option<usize> {
        self.0.iter().position(|p| p.close == raw)
    }

    pub fn iter(&self) -> impl Iterator<Item = &BracketPairEntry> {
        self.0.iter()
    }

    /// Pre-compute `matching_bracket_idx` for every bracket token via LIFO
    /// nesting order (Python parity: `resolve_bracket`, match_algorithms.py).
    /// Only code tokens are considered, so bracket characters inside a
    /// comment can't pair with real brackets in the SQL.
    pub fn compute_matching_indices(&self, tokens: &mut [Token]) {
        let mut bracket_stack: Vec<(usize, usize)> = Vec::new();

        for idx in 0..tokens.len() {
            tokens[idx].matching_bracket_idx = None;

            if !tokens[idx].is_code() {
                continue;
            }

            let raw = tokens[idx].raw();

            if let Some(pair_idx) = self.position_by_open(raw) {
                bracket_stack.push((idx, pair_idx));
            } else if let Some(expected_idx) = self.position_by_close(raw) {
                // Only the most-recently-opened bracket may be closed next
                // (LIFO), matching `resolve_bracket`'s own recursion.
                if let Some(&(open_idx, top_idx)) = bracket_stack.last() {
                    if top_idx == expected_idx {
                        bracket_stack.pop();
                        tokens[open_idx].matching_bracket_idx = Some(idx);
                        tokens[idx].matching_bracket_idx = Some(open_idx);
                    } else {
                        // Type mismatch: unwind the whole stack, as Python's
                        // resolve_bracket does when it raises.
                        bracket_stack.clear();
                    }
                }
                // Empty stack: a stray closer with no open bracket - leave as None.
            }
        }
        // Any remaining openers on the stack are unmatched - leave as None.
    }
}

#[derive(Debug, Clone)]
pub enum LexerMode {
    String(String),                           // Match a literal string
    Regex(Regex, fn(&str) -> bool),           // Match using a regex
    FancyRegex(FancyRegex, fn(&str) -> bool), // Match using a regex
    Function(fn(&str) -> Option<&str>),
    /// A regex that compiles at its first use (LazyRegex). The clones of a
    /// matcher share it.
    Lazy(Arc<LazyRegex>, fn(&str) -> bool),
}

impl Display for LexerMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LexerMode::Regex(_, _) => write!(f, "RegexMatcher"),
            LexerMode::FancyRegex(_, _) => write!(f, "FancyRegexMatcher"),
            LexerMode::String(_) => write!(f, "StringMatcher"),
            LexerMode::Function(_) => write!(f, "FunctionMatcher"),
            LexerMode::Lazy(lazy, _) => match lazy.get() {
                CompiledRegex::Regex(_) => write!(f, "RegexMatcher"),
                CompiledRegex::FancyRegex(_) => write!(f, "FancyRegexMatcher"),
                CompiledRegex::Function(_) => write!(f, "FunctionMatcher"),
            },
        }
    }
}

/// The compiled form of a lexer regex: the mode that the source
/// (base_regex_lexer) gives to the pattern.
#[derive(Debug)]
pub enum CompiledRegex {
    Regex(Regex),
    FancyRegex(FancyRegex),
    Function(fn(&str) -> Option<&str>),
}

/// A lexer regex that compiles at its first use, so that a run compiles
/// only the regexes that it uses. The source compiles each regex of the
/// dialect when it makes the matchers. The compile is the same: first the
/// regex crate, then fancy_regex, then the fallback function. A pattern
/// that does not compile and has no fallback panics at its first use, not
/// when the matchers are made.
#[derive(Debug)]
pub struct LazyRegex {
    pattern: String,
    fallback: Option<fn(&str) -> Option<&str>>,
    compiled: OnceLock<CompiledRegex>,
    prefixes: OnceLock<Option<Vec<Vec<u8>>>>,
}

/// The prefixes of the matches of a regex: each match starts with one of
/// them. None if a match can start with any text, or if regex_syntax does
/// not parse the pattern (for example a pattern for fancy_regex).
/// regex_syntax gives the prefixes (literal extraction, which the regex
/// crate uses to find the start of a match), and parses the pattern with
/// the syntax config of the regex crate (its defaults).
pub fn match_prefixes(pattern: &str) -> Option<Vec<Vec<u8>>> {
    let hir = regex_syntax::ParserBuilder::new()
        .build()
        .parse(pattern)
        .ok()?;
    let seq = regex_syntax::hir::literal::Extractor::new().extract(&hir);
    let literals = seq.literals()?;
    if literals.iter().any(|l| l.as_bytes().is_empty()) {
        return None;
    }
    Some(literals.iter().map(|l| l.as_bytes().to_vec()).collect())
}

impl LazyRegex {
    pub fn new(pattern: String, fallback: Option<fn(&str) -> Option<&str>>) -> Self {
        Self {
            pattern,
            fallback,
            compiled: OnceLock::new(),
            prefixes: OnceLock::new(),
        }
    }

    /// False if no match can start at the start of the input: the input
    /// does not start with a prefix of match_prefixes. The lexer regexes
    /// match only at the start of the input (`\A`). Thus the lexer does not
    /// compile a regex that cannot match there.
    pub fn may_match_at_start(&self, input: &str) -> bool {
        match self.prefixes.get_or_init(|| match_prefixes(&self.pattern)) {
            None => true,
            Some(prefixes) => prefixes.iter().any(|p| input.as_bytes().starts_with(p)),
        }
    }

    pub fn has_fallback(&self) -> bool {
        self.fallback.is_some()
    }

    /// The compiled regex. It compiles the pattern at the first call.
    pub fn get(&self) -> &CompiledRegex {
        self.compiled
            .get_or_init(|| match RegexBuilder::new(&self.pattern).build() {
                Ok(regex) => CompiledRegex::Regex(regex),
                Err(_) => match FancyRegexBuilder::new(&self.pattern).build() {
                    Ok(regex) => CompiledRegex::FancyRegex(regex),
                    Err(_) => {
                        if let Some(fallback) = self.fallback {
                            CompiledRegex::Function(fallback)
                        } else {
                            panic!(
                                "Unable to compile regex {} and no fallback function provided",
                                self.pattern
                            )
                        }
                    }
                },
            })
    }

    /// True if the pattern is compiled.
    pub fn is_compiled(&self) -> bool {
        self.compiled.get().is_some()
    }
}

pub struct LexedElement<'a> {
    pub raw: &'a str,
    pub matcher: &'a LexMatcher,
}

impl<'a> LexedElement<'a> {
    pub fn new(raw: &'a str, matcher: &'a LexMatcher) -> Self {
        Self { raw, matcher }
    }
}

#[derive(Debug, Clone)]
pub struct LexMatcher {
    // pub dialect: Dialect,
    pub name: String,
    pub mode: LexerMode,
    pub token_class_func: TokenGenerator,
    pub subdivider: Option<Box<LexMatcher>>,
    pub trim_post_subdivide: Option<Box<LexMatcher>>,
    pub trim_start: Option<Vec<String>>,
    pub trim_chars: Option<Vec<String>>,
    pub quoted_value: Option<(String, RegexModeGroup)>,
    // Shared via `Arc` so cloning a matcher into a token (`construct_token`,
    // once per lexed token) is a refcount bump rather than a deep copy of the
    // `(pattern, replacement)` pairs.
    pub escape_replacements: Option<Arc<Vec<(String, String)>>>,
    pub casefold: CaseFold,
    pub kwarg_type: Option<String>,
}

/// Grouped optional parameters shared by [`LexMatcher::string_lexer`],
/// [`LexMatcher::regex_lexer`], and [`LexMatcher::regex_subdivider`].
#[derive(Debug, Clone, Default)]
pub struct LexMatcherConfig {
    pub subdivider: Option<Box<LexMatcher>>,
    pub trim_post_subdivide: Option<Box<LexMatcher>>,
    pub trim_start: Option<Vec<String>>,
    pub trim_chars: Option<Vec<String>>,
    pub quoted_value: Option<(String, RegexModeGroup)>,
    pub escape_replacements: Option<Arc<Vec<(String, String)>>>,
    pub casefold: CaseFold,
    pub kwarg_type: Option<String>,
}

impl Display for LexMatcher {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "<{}: {}>", self.mode, self.name)
    }
}

impl LexMatcher {
    pub fn string_lexer(
        // dialect: Dialect,
        name: &str,
        template: &str,
        token_class_func: TokenGenerator,
        config: LexMatcherConfig,
    ) -> Self {
        Self {
            // dialect,
            name: name.to_string(),
            mode: LexerMode::String(template.to_string()),
            token_class_func,
            subdivider: config.subdivider,
            trim_post_subdivide: config.trim_post_subdivide,
            trim_start: config.trim_start,
            trim_chars: config.trim_chars,
            quoted_value: config.quoted_value,
            escape_replacements: config.escape_replacements,
            casefold: config.casefold,
            kwarg_type: config.kwarg_type,
        }
    }

    fn base_regex_lexer(
        // dialect: Dialect,
        name: &str,
        pattern: &str,
        token_class_func: TokenGenerator,
        fallback_lexer: Option<fn(&str) -> Option<&str>>,
        precheck: fn(&str) -> bool,
        config: LexMatcherConfig,
    ) -> Self {
        let mode = LexerMode::Lazy(
            Arc::new(LazyRegex::new(pattern.to_string(), fallback_lexer)),
            precheck,
        );

        Self {
            // dialect,
            name: name.to_string(),
            mode,
            token_class_func,
            subdivider: config.subdivider,
            trim_post_subdivide: config.trim_post_subdivide,
            trim_start: config.trim_start,
            trim_chars: config.trim_chars,
            quoted_value: config.quoted_value,
            escape_replacements: config.escape_replacements,
            casefold: config.casefold,
            kwarg_type: config.kwarg_type,
        }
    }

    pub fn regex_lexer(
        // dialect: Dialect,
        name: &str,
        template: &str,
        token_class_func: TokenGenerator,
        fallback_lexer: Option<fn(&str) -> Option<&str>>,
        precheck: fn(&str) -> bool,
        config: LexMatcherConfig,
    ) -> Self {
        let pattern = format!(r"(?s)\A(?:{})", template);
        Self::base_regex_lexer(
            // dialect,
            name,
            &pattern,
            token_class_func,
            fallback_lexer,
            precheck,
            config,
        )
    }

    pub fn regex_subdivider(
        // dialect: Dialect,
        name: &str,
        template: &str,
        token_class_func: TokenGenerator,
        fallback_lexer: Option<fn(&str) -> Option<&str>>,
        precheck: fn(&str) -> bool,
        config: LexMatcherConfig,
    ) -> Self {
        let pattern = format!(r"(?:{})", template);
        Self::base_regex_lexer(
            // dialect,
            name,
            &pattern,
            token_class_func,
            fallback_lexer,
            precheck,
            config,
        )
    }

    pub fn scan_match<'a>(&'a self, input: &'a str) -> Option<(Vec<LexedElement<'a>>, usize)> {
        // let t = Instant::now();
        if input.is_empty() {
            panic!("Unexpected empty string!");
        }

        // Match based on the mode
        let matched = match &self.mode {
            LexerMode::String(template) => input
                .starts_with(template)
                .then(|| LexedElement::new(template, self)),
            LexerMode::Regex(regex, is_match_valid) => {
                if !(is_match_valid)(input) {
                    return None;
                }
                regex
                    .find(input)
                    .map(|mat| LexedElement::new(mat.as_str(), self))
            }
            LexerMode::FancyRegex(regex, is_match_valid) => {
                if !(is_match_valid)(input) {
                    return None;
                }
                regex
                    .find(input)
                    .ok()
                    .flatten()
                    .map(|mat| LexedElement::new(mat.as_str(), self))
            }
            LexerMode::Function(function) => (function)(input).map(|s| LexedElement::new(s, self)),
            LexerMode::Lazy(lazy, is_match_valid) => {
                // The source applies the precheck only to a regex, not to a
                // fallback function. Only a pattern with a fallback can
                // become a function, so only such a pattern compiles before
                // the precheck.
                let checked = !lazy.has_fallback();
                if checked && !((is_match_valid)(input) && lazy.may_match_at_start(input)) {
                    return None;
                }
                match lazy.get() {
                    CompiledRegex::Regex(regex) => {
                        if !checked && !(is_match_valid)(input) {
                            return None;
                        }
                        regex
                            .find(input)
                            .map(|mat| LexedElement::new(mat.as_str(), self))
                    }
                    CompiledRegex::FancyRegex(regex) => {
                        if !checked && !(is_match_valid)(input) {
                            return None;
                        }
                        regex
                            .find(input)
                            .ok()
                            .flatten()
                            .map(|mat| LexedElement::new(mat.as_str(), self))
                    }
                    CompiledRegex::Function(function) => {
                        (function)(input).map(|s| LexedElement::new(s, self))
                    }
                }
            }
        };

        // Handle subdivision and trimming
        if let Some(matched) = matched {
            let len = matched.raw.len();
            let elements = self.subdivide(matched);
            Some((elements, len))
        } else {
            None
        }
    }

    fn search(&self, input: &str) -> Option<(usize, usize)> {
        match &self.mode {
            LexerMode::String(template) => input.find(template).map(|start| {
                let end = start + template.len();
                (start, end)
            }),
            LexerMode::Regex(regex, _) => regex.find(input).map(|mat| (mat.start(), mat.end())),
            LexerMode::FancyRegex(regex, _) => regex
                .find(input)
                .ok()
                .flatten()
                .map(|mat| (mat.start(), mat.end())),
            LexerMode::Lazy(lazy, _) => match lazy.get() {
                CompiledRegex::Regex(regex) => {
                    regex.find(input).map(|mat| (mat.start(), mat.end()))
                }
                CompiledRegex::FancyRegex(regex) => regex
                    .find(input)
                    .ok()
                    .flatten()
                    .map(|mat| (mat.start(), mat.end())),
                CompiledRegex::Function(_) => todo!(),
            },
            _ => todo!(),
        }
    }

    fn subdivide<'a>(&'a self, matched: LexedElement<'a>) -> Vec<LexedElement<'a>> {
        if let Some(subdivider) = &self.subdivider {
            let mut elements = Vec::new();
            let mut buffer = matched.raw;
            while !buffer.is_empty() {
                if let Some((start, end)) = subdivider.search(buffer) {
                    let trimmed_elems = self.trim_match(&buffer[..start]);
                    elements.extend(trimmed_elems);
                    elements.push(LexedElement {
                        raw: &buffer[start..end],
                        matcher: subdivider,
                    });
                    buffer = &buffer[end..];
                } else {
                    let trimmed_elems = self.trim_match(buffer);
                    elements.extend(trimmed_elems);
                    break;
                }
            }
            elements
        } else {
            vec![matched]
        }
    }

    fn trim_match<'a>(&'a self, raw: &'a str) -> Vec<LexedElement<'a>> {
        let mut elements = Vec::new();
        let mut buffer = raw;
        let mut content_buffer = 0..0;

        if let Some(trim_post_subdivide) = &self.trim_post_subdivide {
            while !buffer.is_empty() {
                if let Some((start, end)) = trim_post_subdivide.search(buffer) {
                    if start == 0 {
                        // Starting match
                        elements.push(LexedElement {
                            raw: &buffer[..end],
                            matcher: trim_post_subdivide,
                        });
                        buffer = &buffer[end..];
                        content_buffer = end..end;
                    } else if end == buffer.len() {
                        elements.push(LexedElement {
                            raw: &raw[content_buffer.start..content_buffer.end + start],
                            matcher: self,
                        });
                        elements.push(LexedElement {
                            raw: &buffer[start..end],
                            matcher: trim_post_subdivide,
                        });
                        return elements;
                    } else {
                        content_buffer.end += end;
                        buffer = &buffer[end..];
                    }
                } else {
                    break;
                }
            }
        }
        if !content_buffer.is_empty() || !buffer.is_empty() {
            elements.push(LexedElement::new(&raw[content_buffer.start..], self));
        }
        elements
    }

    pub fn construct_token(&self, raw: &str, pos_marker: PositionMarker) -> Token {
        let instance_types = match self.kwarg_type.clone() {
            Some(t) => vec![t],
            None => vec![self.name.clone()],
        };
        (self.token_class_func)(
            raw.to_string(),
            pos_marker,
            TokenConfig {
                class_types: HashSet::new(),
                instance_types,
                trim_start: self.trim_start.clone(),
                trim_chars: self.trim_chars.clone(),
                quoted_value: self.quoted_value.clone(),
                escape_replacements: self.escape_replacements.clone(),
                casefold: self.casefold,
            },
        )
    }
}
