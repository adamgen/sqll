// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_rules/src/cp03.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.
// sqll changed this file. crates/ported.json gives the reason.

//! CP03 (function-name capitalisation) over the rule interface of
//! `sqll_lint`.
//!
//! Thin wrapper over [`crate::capitalisation::eval`] — see that module for
//! the shared walk/refute/apply logic. CP03 has no target/parent exclusions of
//! its own (`Rule_CP03` sets `_exclude_types`/`_exclude_parent_types` to empty
//! tuples); the qualified-function-name skip (multi-part names are likely
//! case-sensitive UDFs) is still applied because it's unconditional in the
//! shared walk, matching `Rule_CP01._eval`.
//!
//! Unlike CP01, CP03 reads `extended_capitalisation_policy`, so `policy` may
//! additionally be `pascal`, `camel`, or `snake`.

use sqll_lint::{CrawlBehaviour, LintError, LintPhase, LintResult, Rule, RuleConfig, RuleContext};
use sqll_tree::SegmentType;

use crate::capitalisation::{eval, settings, Targets};

const TARGET_TYPES: [SegmentType; 2] = [SegmentType::FUNCTION_NAME_IDENTIFIER, SegmentType::BARE_FUNCTION];
const EXCLUDE_TYPES: [SegmentType; 0] = [];
const EXCLUDE_PARENT_TYPES: [SegmentType; 0] = [];

const TARGETS: Targets = Targets {
    code: "CP03",
    target_types: &TARGET_TYPES,
    exclude_types: &EXCLUDE_TYPES,
    exclude_parent_types: &EXCLUDE_PARENT_TYPES,
    policy_key: "extended_capitalisation_policy",
    description_elem: "Function names",
};

/// The rule `CP03` (`capitalisation.functions`).
pub struct RuleCP03;

impl Rule for RuleCP03 {
    fn code(&self) -> &'static str {
        "CP03"
    }
    fn name(&self) -> &'static str {
        "capitalisation.functions"
    }
    fn description(&self) -> &'static str {
        "Inconsistent capitalisation of function names."
    }
    fn groups(&self) -> &'static [&'static str] {
        &["all", "core", "capitalisation"]
    }
    fn aliases(&self) -> &'static [&'static str] {
        &["L030"]
    }
    fn config_keywords(&self) -> &'static [&'static str] {
        &["extended_capitalisation_policy", "ignore_words", "ignore_words_regex"]
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
