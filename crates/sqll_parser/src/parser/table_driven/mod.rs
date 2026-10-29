// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_parser/src/parser/table_driven/mod.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.

pub mod anynumberof;
pub mod bracketed;
pub mod contexts;
pub mod delimited;
pub mod frame;
pub mod iterative;
mod match_algorithms;
pub mod oneof;
pub(crate) mod parity;
pub mod ref_grammar;
pub mod sequence;
