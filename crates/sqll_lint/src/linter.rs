// Parts of this file are a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/linter/linter.py (Linter.lint_fix_parsed,
// Linter.remove_templated_errors), src/sqlfluff/core/rules/base.py
// (BaseRule.crawl, BaseRule._process_lint_result), and
// src/sqlfluff/core/linter/linted_file.py
// (LintedFile.deduplicate_in_source_space).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.
// Change: a fix changes the source text (source edits), and the loop
// parses the fixed source again, instead of a change of the tree.

//! The linter and the fix loop.

use std::collections::HashSet;
use std::ops::Range;
use std::time::{Duration, Instant};

use sqll_source::{LinePos, Templater, TemplaterConfig, TemplaterError};
use sqll_syntax::{Diagnostic, Dialect, ParseOptions, Parsed};
use sqll_tree::{NodeId, SegmentType, SyntaxTree};

use crate::config::{LintSettings, RuleConfig};
use crate::fix::{apply_edits, check_anchors, result_edits, Fix, FixRecord, SourceEdit};
use crate::registry::RulePack;
use crate::rule::{LintPhase, Memory, Rule, RuleContext};
use crate::LintError;

/// The templater and the parse of a source text, for the fix loop: the
/// loop parses each fixed source again.
pub trait SourceParser {
    fn parse(&mut self, source: &str) -> Result<Parsed, LintError>;
}

/// A [`SourceParser`] with a templater and the parse interface
/// (`sqll_syntax::parse`).
pub struct TemplaterParser<'a> {
    pub templater: &'a dyn Templater,
    pub config: TemplaterConfig,
    pub fname: String,
    pub dialect: Dialect,
    pub options: ParseOptions,
}

impl SourceParser for TemplaterParser<'_> {
    fn parse(&mut self, source: &str) -> Result<Parsed, LintError> {
        let file = self
            .templater
            .process(source, &self.fname, &self.config)
            .map_err(|e| match e {
                TemplaterError::Unsupported { message } => LintError::Unsupported(message),
                e @ TemplaterError::Template { .. } => LintError::Parse(format!("TMP: {e}")),
            })?;
        sqll_syntax::parse(&file, self.dialect, &self.options)
            .map_err(|e| LintError::Parse(e.to_string()))
    }
}

/// A violation of a rule (the sqlfluff `SQLLintError`), in the source.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Violation {
    pub code: &'static str,
    pub name: &'static str,
    pub description: String,
    /// The source byte range of the anchor.
    pub source_range: Range<usize>,
    /// The source line and position of the start and of the end of the
    /// anchor (the sqlfluff `start_line_no`, `start_line_pos`,
    /// `end_line_no`, `end_line_pos`).
    pub start: LinePos,
    pub end: LinePos,
    /// The source edits of the fixes. Empty: the violation is not fixable.
    pub fixes: Vec<SourceEdit>,
    /// The output records of the fixes (the sqlfluff `fixes` of the
    /// violation record), in the order of the rule. Empty if `fixes` is.
    pub fix_records: Vec<FixRecord>,
    /// The anchor is in literal source text (not templated).
    pub literal: bool,
    targets_templated: bool,
}

impl Violation {
    pub fn fixable(&self) -> bool {
        !self.fixes.is_empty()
    }

    /// Make the violation not fixable.
    pub fn clear_fixes(&mut self) {
        self.fixes.clear();
        self.fix_records.clear();
    }
}

/// The result of a lint or a fix of one file.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LintedFile {
    /// The source text after the fixes (the input if no fix applies).
    pub fixed: String,
    /// The violations of the input source, sorted by line and position.
    pub violations: Vec<Violation>,
    /// The lex and parse errors of the input source.
    pub parse_errors: Vec<Diagnostic>,
    /// The notes of the fix loop (the sqlfluff warnings of the linter).
    pub warnings: Vec<String>,
    /// The time of each rule in the loops, by code, in the order of the
    /// first run (the sqlfluff `get_rule_timing_dict`).
    pub rule_times: Vec<(&'static str, Duration)>,
}

/// The line and position of a source byte of the tree.
fn source_line_pos(tree: &SyntaxTree, byte: usize) -> LinePos {
    match tree.source_map() {
        Some(map) => map.source_line_pos(byte),
        None => tree.line_pos(byte),
    }
    .expect("a source byte of a node is at a character")
}

/// The sqlfluff `is_templated` of a node: its source is not empty and not
/// literal.
pub fn is_templated(tree: &SyntaxTree, id: NodeId) -> bool {
    !tree.source_range(id).is_empty() && !tree.is_literal(id)
}

/// The result of one crawl of one rule: the violations and the fixes.
struct Crawled {
    violations: Vec<Violation>,
    /// The fixes of the results that can change the source, in order.
    fixes: Vec<Fix>,
}

/// True if the node and each of its ancestors pass the filter of the
/// crawler of the rule.
fn path_passes(rule: &dyn Rule, tree: &SyntaxTree, id: NodeId) -> bool {
    let crawler = rule.crawl_behaviour();
    let mut node = Some(tree.node(id));
    while let Some(n) = node {
        if !crawler.passes_filter(n) {
            return false;
        }
        node = n.parent();
    }
    true
}

/// The sqlfluff `BaseRule.crawl` and `_process_lint_result`.
fn crawl(
    rule: &dyn Rule,
    config: &RuleConfig,
    dialect: Dialect,
    tree: &SyntaxTree,
) -> Result<Crawled, LintError> {
    let mut memory = Memory::default();
    let mut out = Crawled {
        violations: Vec::new(),
        fixes: Vec::new(),
    };
    for id in rule.crawl_behaviour().crawl(tree) {
        let mut context = RuleContext {
            segment: tree.node(id),
            dialect,
            config,
            memory: &mut memory,
        };
        for result in rule.eval(&mut context)? {
            // discard_unsafe_fixes: a refused fix makes the result unfixable.
            let (fixes, edits) = match result_edits(tree, &result.fixes) {
                Ok(edits) => (result.fixes, edits),
                Err(_) => (Vec::new(), Vec::new()),
            };
            let anchors = std::iter::once(result.anchor).chain(fixes.iter().map(Fix::anchor));
            if !anchors.into_iter().all(|a| path_passes(rule, tree, a)) {
                continue;
            }
            let source_range = tree.source_range(result.anchor);
            let fix_records = fixes.iter().map(|f| f.record(tree)).collect();
            out.violations.push(Violation {
                code: rule.code(),
                name: rule.name(),
                description: result
                    .description
                    .unwrap_or_else(|| rule.description().to_string()),
                start: source_line_pos(tree, source_range.start),
                end: source_line_pos(tree, source_range.end),
                source_range,
                fixes: edits,
                fix_records,
                literal: !is_templated(tree, result.anchor),
                targets_templated: rule.targets_templated(),
            });
            out.fixes.extend(fixes);
        }
    }
    Ok(out)
}

/// The sqlfluff `noqa` comment check: sqll does not read them yet, so a
/// comment with "noqa" fails closed.
fn check_noqa(tree: &SyntaxTree) -> Result<(), LintError> {
    for id in tree.nodes() {
        if tree.node(id).is_type(SegmentType::COMMENT)
            && tree.raw(id).to_ascii_lowercase().contains("noqa")
        {
            let at = tree.source_pos(id);
            return Err(LintError::Unsupported(format!(
                "a noqa comment at line {}, position {}: sqll does not read noqa comments yet (S5)",
                at.line, at.pos
            )));
        }
    }
    Ok(())
}

/// The state of the fix loop: the current source, tree, and errors.
struct Current {
    source: String,
    tree: SyntaxTree,
    errors: usize,
}

/// The linter of one rule pack.
pub struct Linter<'p> {
    pub pack: &'p RulePack<'p>,
    pub settings: LintSettings,
    pub dialect: Dialect,
}

impl Linter<'_> {
    /// Lint a source text, and fix it if `fix` is true (the sqlfluff
    /// `lint_fix_parsed`). The parser gives the tree of the source and of
    /// each fixed source.
    pub fn lint(
        &self,
        source: &str,
        parser: &mut dyn SourceParser,
        fix: bool,
    ) -> Result<LintedFile, LintError> {
        let parsed = parser.parse(source)?;
        let mut out = LintedFile {
            fixed: source.to_string(),
            violations: Vec::new(),
            parse_errors: parsed.errors,
            warnings: Vec::new(),
            rule_times: Vec::new(),
        };
        // No tree (the parser stopped): no rule runs, as in sqlfluff.
        let Some(tree) = parsed.tree else {
            return Ok(out);
        };
        if self.settings.reads_noqa {
            check_noqa(&tree)?;
        }
        let mut current = Current {
            source: source.to_string(),
            tree,
            errors: out.parse_errors.len(),
        };
        let mut initial: Vec<Violation> = Vec::new();
        let mut previous: HashSet<String> = HashSet::from([source.to_string()]);
        let mut last_fixes: Option<Vec<SourceEdit>> = None;
        let loop_limit = if fix {
            self.settings.runaway_limit.max(0) as usize
        } else {
            1
        };
        let phases: &[LintPhase] = if fix {
            &[LintPhase::Main, LintPhase::Post]
        } else {
            &[LintPhase::Main]
        };
        for &phase in phases {
            // As sqlfluff: the rules of the phase; the first loop of the
            // main phase sets this to all the rules, and the later loops of
            // the main phase keep that.
            let mut rules: Vec<usize> = (0..self.pack.rules.len())
                .filter(|&i| phases.len() == 1 || self.pack.rules[i].0.lint_phase() == phase)
                .collect();
            let loops = if phase == LintPhase::Main {
                loop_limit
            } else {
                2
            };
            let mut stable = false;
            for n in 0..loops {
                let first = phase == phases[0] && n == 0;
                let mut changed = false;
                if first {
                    rules = (0..self.pack.rules.len()).collect();
                }
                for &i in &rules {
                    let (rule, config) = &self.pack.rules[i];
                    if fix && !first && !rule.is_fix_compatible() {
                        continue;
                    }
                    let started = Instant::now();
                    'rule: {
                        let crawled = crawl(*rule, config, self.dialect, &current.tree)?;
                        let start = initial.len();
                        if first {
                            initial.extend(crawled.violations);
                        }
                        if !fix || crawled.fixes.is_empty() {
                            break 'rule;
                        }
                        let edits = check_anchors(&crawled.fixes).and_then(|fixes| {
                            fixes
                                .iter()
                                .map(|f| {
                                    let after = matches!(f, Fix::CreateAfter { .. });
                                    f.source_edit(&current.tree)
                                        .ok()
                                        .map(|e| e.map(|e| (e, after)))
                                })
                                .collect::<Option<Vec<_>>>()
                                .map(|v| v.into_iter().flatten().collect::<Vec<_>>())
                        });
                        let Some(edits) = edits else {
                            out.warnings.push(format!(
                                "Rule {} returned conflicting fixes with the same anchor. \
                                 The fixes are not applied.",
                                rule.code()
                            ));
                            if first {
                                for v in &mut initial[start..] {
                                    v.clear_fixes();
                                }
                            }
                            break 'rule;
                        };
                        let plain: Vec<SourceEdit> = edits.iter().map(|(e, _)| e.clone()).collect();
                        if last_fixes.as_ref() == Some(&plain) {
                            break 'rule;
                        }
                        last_fixes = Some(plain);
                        let Some(new_source) = apply_edits(&current.source, &edits) else {
                            out.warnings.push(format!(
                                "Rule {} returned fixes that overlap. The fixes are not applied.",
                                rule.code()
                            ));
                            if first {
                                for v in &mut initial[start..] {
                                    v.clear_fixes();
                                }
                            }
                            break 'rule;
                        };
                        if new_source == current.source {
                            break 'rule;
                        }
                        let valid = match parser.parse(&new_source) {
                            Ok(Parsed {
                                tree: Some(tree),
                                errors,
                                ..
                            }) if errors.len() <= current.errors => Some((tree, errors.len())),
                            _ => None,
                        };
                        let Some((tree, errors)) = valid else {
                            out.warnings.push(format!(
                                "Fixes for {} not applied, as it would result in an unparsable file. \
                                 Please report this as a bug with a minimal query which \
                                 demonstrates this warning.",
                                rule.code()
                            ));
                            break 'rule;
                        };
                        if previous.contains(&new_source) {
                            out.warnings.push(format!(
                                "One fix for {} not applied, it would re-cause the same error.",
                                rule.code()
                            ));
                            break 'rule;
                        }
                        previous.insert(new_source.clone());
                        current = Current {
                            source: new_source,
                            tree,
                            errors,
                        };
                        changed = true;
                    }
                    add_time(&mut out.rule_times, rule.code(), started.elapsed());
                }
                if fix && !changed {
                    stable = true;
                    break;
                }
            }
            if fix && !stable {
                out.warnings
                    .push(format!("Loop limit on fixes reached [{loop_limit}]."));
                for v in &mut initial {
                    v.clear_fixes();
                }
                // As sqlfluff: the original source, and no removal of the
                // violations in templated sections.
                out.violations = finish(initial, false);
                return Ok(out);
            }
        }
        out.fixed = current.source;
        out.violations = finish(initial, self.settings.ignore_templated_areas);
        Ok(out)
    }
}

/// Add a time to the time of a rule.
fn add_time(times: &mut Vec<(&'static str, Duration)>, code: &'static str, time: Duration) {
    match times.iter_mut().find(|(c, _)| *c == code) {
        Some((_, t)) => *t += time,
        None => times.push((code, time)),
    }
}

/// The sqlfluff `remove_templated_errors` (if `remove_templated`), then
/// `deduplicate_in_source_space`: no duplicate, sorted by line and
/// position.
fn finish(violations: Vec<Violation>, remove_templated: bool) -> Vec<Violation> {
    let mut seen = HashSet::new();
    let mut out: Vec<Violation> = violations
        .into_iter()
        .filter(|v| !remove_templated || v.literal || v.targets_templated)
        .filter(|v| seen.insert((v.code, v.start, v.description.clone(), v.fixes.clone())))
        .collect();
    out.sort_by_key(|v| v.start);
    out
}
