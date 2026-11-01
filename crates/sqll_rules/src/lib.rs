// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_rules/src/lib.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.
// sqll changed this file. crates/ported.json gives the reason.

//! Rust-native lint rules, run over the parse arena's public read API.
//!
//! ## STATUS: early — the capitalisation bundle's CP01/CP03/CP04 are wired up
//! (CP02/CP05 still Python-only), gated by `core.use_rust_rules`
//!
//! Each rule's *detection* runs entirely in Rust over [`sqlfluffrs_parser::Arena`]
//! (read-only) and returns a compact result; *fix application* stays on the
//! Python side for now (the linter anchors a `LintFix` from the returned data).
//! Moving fixing into Rust waits on the arena's mutation milestone.
//!
//! Each rule's PyO3 binding lives next to its logic, gated behind the optional
//! `python` feature, and is registered on the module by [`python::register`].
//! Rule *detection* stays pure Rust (no feature needed) and unit-testable.

pub mod capitalisation;
pub mod cp01;
pub mod cp03;
pub mod cp04;

