// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_types/src/token/path.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.

use super::Token;
use std::sync::Arc;

#[derive(Debug, Clone)]
pub struct PathStep {
    pub segment: Arc<Token>,
    pub idx: usize,
    pub len: usize,
    pub code_idxs: Vec<usize>,
}
