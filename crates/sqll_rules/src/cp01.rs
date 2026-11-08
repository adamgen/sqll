// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_rules/src/cp01.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.
// sqll changed this file. crates/ported.json gives the reason.

//! CP01 (keyword capitalisation) over the rule interface of `sqll_lint`.
//!
//! Thin wrapper over the shared state machine in [`crate::capitalisation`];
//! this module only supplies CP01's target/exclude sets. See that module for
//! the walk/refute/apply logic shared with CP03 and CP04.
//!
//! Mirrors `Rule_CP01` for the `consistent`/`upper`/`lower`/`capitalise`
//! policies (the only options `capitalisation_policy` accepts). Word-ignore and
//! templated-area handling are applied in the shared walk so the `consistent`
//! inference sees exactly the segments stock CP01 would.
//!
//! sqll: the anchor of a result is the node of the `SyntaxTree` (S3b C12),
//! not a leaf index into the Python `raw_segments`.

use sqll_lint::{CrawlBehaviour, LintError, LintPhase, LintResult, Rule, RuleConfig, RuleContext};
use sqll_tree::SegmentType;

use crate::capitalisation::{eval, settings, Targets};

// Binary operators behave like keywords too.
const TARGET_TYPES: [SegmentType; 3] = [SegmentType::KEYWORD, SegmentType::BINARY_OPERATOR, SegmentType::DATE_PART];
// Literals are also keywords but have their own rule (CP04).
const EXCLUDE_TYPES: [SegmentType; 1] = [SegmentType::LITERAL];
const EXCLUDE_PARENT_TYPES: [SegmentType; 3] = [SegmentType::DATA_TYPE, SegmentType::DATETIME_TYPE_IDENTIFIER, SegmentType::PRIMITIVE_TYPE];

const TARGETS: Targets = Targets {
    code: "CP01",
    target_types: &TARGET_TYPES,
    exclude_types: &EXCLUDE_TYPES,
    exclude_parent_types: &EXCLUDE_PARENT_TYPES,
    policy_key: "capitalisation_policy",
    description_elem: "Keywords",
};

/// The rule `CP01` (`capitalisation.keywords`).
pub struct RuleCP01;

impl Rule for RuleCP01 {
    fn code(&self) -> &'static str {
        "CP01"
    }
    fn name(&self) -> &'static str {
        "capitalisation.keywords"
    }
    fn description(&self) -> &'static str {
        "Inconsistent capitalisation of keywords."
    }
    fn groups(&self) -> &'static [&'static str] {
        &["all", "core", "capitalisation"]
    }
    fn aliases(&self) -> &'static [&'static str] {
        &["L010"]
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
