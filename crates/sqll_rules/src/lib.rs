// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_rules/src/lib.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.
// sqll changed this file. crates/ported.json gives the reason.

//! Rust-native lint rules, run over the rule interface of `sqll_lint`.
//!
//! ## STATUS: early — the capitalisation bundle's CP01/CP03/CP04 are wired up
//! (CP02/CP05 still Python-only)
//!
//! sqll (S3b C12): each rule implements `sqll_lint::Rule` over the typed view
//! of the `SyntaxTree`, and gives its fixes as text edits; the fix loop of
//! `sqll_lint` applies them. [`rules`] gives the rules for the registry.
//! The Python bindings of the base are not ported.

pub mod capitalisation;
pub mod cp01;
pub mod cp03;
pub mod cp04;

use sqll_lint::Rule;

/// The rules of this crate, for `sqll_lint::Registry::new`.
pub fn rules() -> Vec<Box<dyn Rule>> {
    vec![
        Box::new(cp01::RuleCP01),
        Box::new(cp03::RuleCP03),
        Box::new(cp04::RuleCP04),
    ]
}
