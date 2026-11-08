// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_rules/src/cp04.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.
// sqll changed this file. crates/ported.json gives the reason.

//! CP04 (boolean/null literal capitalisation) over the rule interface of
//! `sqll_lint`.
//!
//! Thin wrapper over [`crate::capitalisation::eval`] — see that module for
//! the shared walk/refute/apply logic. CP04 has no target/parent exclusions of
//! its own (`Rule_CP04` sets `_exclude_types`/`_exclude_parent_types` to empty
//! tuples) and, like CP01, reads the plain `capitalisation_policy` (not the
//! extended one) — confirmed via `default_config.cfg`, which gives CP04
//! `capitalisation_policy` rather than `extended_capitalisation_policy`.

use sqll_lint::{CrawlBehaviour, LintError, LintPhase, LintResult, Rule, RuleConfig, RuleContext};
use sqll_tree::SegmentType;

use crate::capitalisation::{eval, settings, Targets};

const TARGET_TYPES: [SegmentType; 2] = [SegmentType::NULL_LITERAL, SegmentType::BOOLEAN_LITERAL];
const EXCLUDE_TYPES: [SegmentType; 0] = [];
const EXCLUDE_PARENT_TYPES: [SegmentType; 0] = [];

const TARGETS: Targets = Targets {
    code: "CP04",
    target_types: &TARGET_TYPES,
    exclude_types: &EXCLUDE_TYPES,
    exclude_parent_types: &EXCLUDE_PARENT_TYPES,
    policy_key: "capitalisation_policy",
    description_elem: "Boolean/null literals",
};

/// The rule `CP04` (`capitalisation.literals`).
pub struct RuleCP04;

impl Rule for RuleCP04 {
    fn code(&self) -> &'static str {
        "CP04"
    }
    fn name(&self) -> &'static str {
        "capitalisation.literals"
    }
    fn description(&self) -> &'static str {
        "Inconsistent capitalisation of boolean/null literal."
    }
    fn groups(&self) -> &'static [&'static str] {
        &["all", "core", "capitalisation"]
    }
    fn aliases(&self) -> &'static [&'static str] {
        &["L040"]
    }
    fn config_keywords(&self) -> &'static [&'static str] {
        &["capitalisation_policy", "ignore_words", "ignore_words_regex"]
    }
    fn lint_phase(&self) -> LintPhase {
        LintPhase::Post
    }
    fn is_fix_compatible(&self) -> bool {
        true
    }
    fn crawl_behaviour(&self) -> CrawlBehaviour {
        CrawlBehaviour::seeker(&TARGET_TYPES)
    }
    fn check_config(&self, config: &RuleConfig) -> Result<(), LintError> {
        settings(config, TARGETS.policy_key).map(|_| ())
    }
    fn eval(&self, context: &mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError> {
        eval(context, &TARGETS)
    }
}
