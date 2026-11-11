// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_rules/src/capitalisation.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.
// sqll changed this file. crates/ported.json gives the reason.

//! Shared detection logic for the capitalisation rule bundle (CP01/CP03/CP04
//! today; CP02/CP05 have extra logic — ancestor-based policy applicability and
//! a container-scanning crawl shape, respectively — and are not yet ported).
//!
//! All three rules subclass `Rule_CP01` in Python and share its `_eval`/
//! `_handle_segment` state machine: refute capitalisation cases inconsistent
//! with what's been seen so far, resolve a concrete policy under `consistent`,
//! apply it, and compare. This module holds that state machine once; each
//! rule differs only in which segment types it targets/excludes.
//!
//! sqll: the rules run over the typed view of the `SyntaxTree` through the
//! rule interface of `sqll_lint` (S3b C12), not over the parse arena. The
//! crawl of the interface gives the target nodes; [`eval`] is the
//! `Rule_CP01._eval` of one node, with the state machine in the memory of
//! the crawl. A result has the sqlfluff description and a replace fix.

use std::collections::HashSet;

use sqll_lint::{Fix, LintError, LintResult, RuleConfig, RuleContext};
use sqll_tree::{NodeRef, SegmentType};

/// `capitalisation_policy`/`extended_capitalisation_policy` options minus
/// "consistent", in validation order. Only these three are ever inferred under
/// `consistent` — pascal/camel/snake are refuted unconditionally in the Python
/// rule (`refuted_cases.update(["camel", "pascal", "snake"])`) and so are only
/// reachable via an explicit (non-"consistent") policy.
const POLICY_OPTS: [&str; 3] = ["upper", "lower", "capitalise"];

fn is_capitalizable(c: char) -> bool {
    c.to_lowercase().to_string() != c.to_uppercase().to_string()
}

/// The four Unicode digraph letters (Dz, Dž, Lj, Nj) whose titlecase mapping
/// differs from their simple uppercase mapping — e.g. lowercase "dž" (U+01C6)
/// uppercases to "DŽ" (U+01C4) but title-cases to "Dž" (U+01C5). Python's
/// `str.capitalize()` uses the Unicode titlecase mapping for the first
/// character; Rust's `char::to_uppercase()` only exposes the uppercase one.
/// This table bridges that gap for exact parity on these (exceedingly rare in
/// practice) code points.
fn to_titlecase_char(c: char) -> String {
    let title = match c {
        '\u{01C4}' | '\u{01C6}' => '\u{01C5}',
        '\u{01C7}' | '\u{01C9}' => '\u{01C8}',
        '\u{01CA}' | '\u{01CC}' => '\u{01CB}',
        '\u{01F1}' | '\u{01F3}' => '\u{01F2}',
        _ => return c.to_uppercase().collect::<String>(),
    };
    title.to_string()
}

/// Python's `str.capitalize`: first char title-cased, the rest lower.
fn to_capitalise(raw: &str) -> String {
    let mut chars = raw.chars();
    match chars.next() {
        None => String::new(),
        Some(first) => to_titlecase_char(first) + &chars.as_str().to_lowercase(),
    }
}

/// Shared shape of Python's Pascal/Camel regexes: split on runs of non-alnum
/// (ASCII `[a-zA-Z0-9]`, matching the Python character class exactly) chars,
/// and transform only the first alnum char of each run — the rest of the run
/// is left untouched (so `PascalCase` isn't "corrected", and `under_score`
/// only gets its per-word first letters cased).
fn to_word_case(raw: &str, upper_first: bool) -> String {
    let mut out = String::with_capacity(raw.len());
    let mut prev_alnum = false;
    for c in raw.chars() {
        let is_alnum = c.is_ascii_alphanumeric();
        if is_alnum && !prev_alnum {
            if upper_first {
                out.extend(c.to_uppercase());
            } else {
                out.extend(c.to_lowercase());
            }
        } else {
            out.push(c);
        }
        prev_alnum = is_alnum;
    }
    out
}

/// Python's `str.isupper()`: true only if there's at least one cased char and
/// none of them are lowercase (so e.g. "123" is *not* upper).
fn python_isupper(raw: &str) -> bool {
    let mut has_cased = false;
    for c in raw.chars() {
        if c.is_lowercase() {
            return false;
        }
        if c.is_uppercase() {
            has_cased = true;
        }
    }
    has_cased
}

fn to_snake(raw: &str) -> String {
    if python_isupper(raw) {
        return raw.to_lowercase();
    }
    let chars: Vec<char> = raw.chars().collect();
    let mut out = String::with_capacity(raw.len() + 4);
    for (i, &c) in chars.iter().enumerate() {
        if i > 0 {
            let prev = chars[i - 1];
            let insert_underscore = (c.is_ascii_uppercase()
                && (prev.is_ascii_lowercase() || prev.is_ascii_digit()))
                || (c.is_ascii_digit() && prev.is_ascii_alphabetic())
                || (c.is_ascii_alphabetic() && prev.is_ascii_digit());
            if insert_underscore {
                out.push('_');
            }
        }
        out.push(c);
    }
    out.to_lowercase()
}

fn apply_policy(raw: &str, policy: &str) -> String {
    match policy {
        "upper" => raw.to_uppercase(),
        "lower" => raw.to_lowercase(),
        "capitalise" => to_capitalise(raw),
        "pascal" => to_word_case(raw, true),
        "camel" => to_word_case(raw, false),
        "snake" => to_snake(raw),
        _ => raw.to_string(),
    }
}

/// Refute cases inconsistent with `raw`, resolve a concrete policy, and apply
/// it. Returns `Some((fixed_raw, concrete_policy))` when a fix is needed,
/// `None` otherwise (mirrors `Rule_CP01._handle_segment`'s per-segment
/// control flow).
///
/// `camel`/`pascal`/`snake` bypass the refutation check entirely — in Python
/// they're always present in `refuted_cases` (added unconditionally), so
/// `cap_policy not in refuted_cases` is always false and the policy is always
/// applied; whether a fix is emitted depends only on whether the transform
/// changes the raw text.
fn evaluate(
    raw: &str,
    policy: &str,
    refuted: &mut HashSet<&'static str>,
    latest_possible: &mut Option<&'static str>,
) -> Option<(String, String)> {
    let first_lower = raw
        .chars()
        .find(|c| is_capitalizable(*c))
        .map(|c| c.to_string() != c.to_uppercase().to_string())
        .unwrap_or(false);
    if first_lower {
        refuted.insert("upper");
        refuted.insert("capitalise");
        if raw != raw.to_lowercase() {
            refuted.insert("lower");
        }
    } else {
        refuted.insert("lower");
        if raw != raw.to_uppercase() {
            refuted.insert("upper");
        }
        if raw != to_capitalise(raw) {
            refuted.insert("capitalise");
        }
    }

    let concrete: &str = match policy {
        "consistent" => {
            let possible: Vec<&'static str> = POLICY_OPTS
                .into_iter()
                .filter(|c| !refuted.contains(c))
                .collect();
            if let Some(first) = possible.first() {
                *latest_possible = Some(first);
                return None; // still consistent so far
            }
            latest_possible.unwrap_or("upper")
        }
        "camel" | "pascal" | "snake" => policy,
        _ => {
            if !refuted.contains(policy) {
                return None; // already conforms
            }
            policy
        }
    };

    let fixed = apply_policy(raw, concrete);
    if fixed != raw {
        Some((fixed, concrete.to_string()))
    } else {
        None
    }
}

/// Mirrors `Rule_CP01._eval`'s parent-type exclusion plus the qualified
/// function-name check (used by CP03: multi-part function names are likely
/// case-sensitive UDFs) — the latter is hardcoded in the Python `_eval`, not
/// gated by `_exclude_parent_types`, so it applies unconditionally here too.
fn is_excluded_parent(parent: Option<NodeRef<'_>>, exclude_parent_types: &[SegmentType]) -> bool {
    let Some(parent) = parent else {
        return false;
    };
    if parent.is_any_type(exclude_parent_types) {
        return true;
    }
    parent.ty() == SegmentType::FUNCTION_NAME && parent.children().count() != 1
}

/// The settings of a capitalisation rule, read one time for each crawl
/// (`Rule_CP01._init_capitalisation_policy`).
pub struct Settings {
    pub policy: String,
    pub ignore_words: HashSet<String>,
    pub ignore_templated: bool,
}

/// The settings of the rule config. `policy_key` is the config keyword of
/// the policy (`capitalisation_policy` or `extended_capitalisation_policy`).
/// A word regex (`ignore_words_regex`) fails closed: sqll does not have the
/// Python `regex` module.
pub fn settings(config: &RuleConfig, policy_key: &str) -> Result<Settings, LintError> {
    if let Some(v) = config.get("ignore_words_regex") {
        if v.is_truthy() {
            return Err(LintError::Unsupported(format!(
                "setting ignore_words_regex = {v}: sqll does not have the Python regex module (S5)"
            )));
        }
    }
    let policy = config.get_str(policy_key)?.unwrap_or_default();
    // Use str() as CP04 uses bools which might otherwise be read as bool.
    let ignore = config.get_str("ignore_words")?.unwrap_or_default();
    let ignore_words = if !ignore.is_empty() && ignore != "None" {
        sqll_lint::config::split_comma_separated(&ignore.to_lowercase())
            .into_iter()
            .collect()
    } else {
        HashSet::new()
    };
    let ignore_templated = config
        .core("ignore_templated_areas")
        .is_some_and(sqll_config::Value::is_truthy);
    Ok(Settings {
        policy,
        ignore_words,
        ignore_templated,
    })
}

/// The memory of a crawl: the settings, the refuted cases, and the latest
/// possible case.
#[derive(Default)]
struct Memory {
    settings: Option<Settings>,
    refuted: HashSet<&'static str>,
    latest_possible: Option<&'static str>,
}

/// The target types and the exclusions of one capitalisation rule.
pub struct Targets {
    /// The code of the rule, for a message.
    pub code: &'static str,
    /// The types of the crawl.
    pub target_types: &'static [SegmentType],
    pub exclude_types: &'static [SegmentType],
    pub exclude_parent_types: &'static [SegmentType],
    /// The config keyword of the policy.
    pub policy_key: &'static str,
    /// The `_description_elem` of the rule, for example "Keywords".
    pub description_elem: &'static str,
}

/// A target with one child that is a target leaf with the same text: the
/// parser of sqll makes some sqlfluff raw segments as such a node (for
/// example the sparksql `DivBinaryOperatorSegment` around a keyword). The
/// crawl examines the child, so the node is not examined.
fn wraps_target_leaf(node: NodeRef<'_>, target_types: &[SegmentType]) -> bool {
    let mut children = node.children();
    match (children.next(), children.next()) {
        (Some(child), None) => {
            child.children().next().is_none()
                && child.range() == node.range()
                && child.is_any_type(target_types)
        }
        _ => false,
    }
}

/// `Rule_CP01._eval` and `_handle_segment` for one node of the crawl.
///
/// sqll: a target with children (for example the ansi `ConcatSegment`)
/// changes the memory, as in sqlfluff. If it needs a fix, sqlfluff raises
/// an exception (a node with children has no `edit`) and stops the rule;
/// sqll fails closed (unsupported).
pub fn eval(
    context: &mut RuleContext<'_, '_>,
    targets: &Targets,
) -> Result<Vec<LintResult>, LintError> {
    let node = context.segment;
    let has_children = node.children().next().is_some();
    if has_children && wraps_target_leaf(node, targets.target_types) {
        return Ok(Vec::new());
    }
    if node.is_any_type(targets.exclude_types)
        || is_excluded_parent(node.parent(), targets.exclude_parent_types)
    {
        return Ok(Vec::new());
    }
    let config = context.config;
    let memory = context.memory.get_or_default::<Memory>();
    if memory.settings.is_none() {
        // RulePack checks the settings (check_config) before a lint.
        memory.settings = settings(config, targets.policy_key).ok();
    }
    let Some(settings) = memory.settings.as_ref() else {
        return Ok(Vec::new());
    };
    let raw = node.raw();

    // Skips that must NOT influence the consistent-policy inference.
    if raw.is_empty()
        || settings.ignore_words.contains(&raw.to_lowercase())
        || (settings.ignore_templated && sqll_lint::linter::is_templated(node.tree(), node.id()))
    {
        return Ok(Vec::new());
    }

    let policy = settings.policy.clone();
    let Some((fixed, concrete)) = evaluate(
        raw,
        &policy,
        &mut memory.refuted,
        &mut memory.latest_possible,
    ) else {
        return Ok(Vec::new());
    };
    if has_children {
        return Err(LintError::Unsupported(format!(
            "{}: a fix of the {} node {raw:?}, which has children (sqlfluff stops the rule \
             with an exception)",
            targets.code,
            node.ty().name()
        )));
    }
    let consistency = if policy == "consistent" {
        "consistently "
    } else {
        ""
    };
    let policy_text = if concrete == "capitalise" {
        "capitalised.".to_string()
    } else {
        format!("{concrete} case.")
    };
    Ok(vec![LintResult::new(node.id())
        .with_description(format!(
            "{} must be {consistency}{policy_text}",
            targets.description_elem
        ))
        .with_fix(Fix::Replace {
            anchor: node.id(),
            text: fixed,
        })])
}
