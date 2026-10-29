// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_dialects/src/lib.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.
// sqll changed this file. crates/ported.json gives the reason.

pub mod block_comment;
// The generated dialect tables: build.rs checks them against
// generated.json and writes this file.
include!(concat!(env!("OUT_DIR"), "/dialect.rs"));

pub use block_comment::extract_nested_block_comment;
pub use dialect::*;
