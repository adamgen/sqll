// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_types/src/token/fix.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.

use crate::slice::Slice;

#[derive(Debug, Clone)]
pub struct SourceFix {
    edit: String,
    source_slice: Slice,
    #[allow(dead_code)]
    templated_slice: Slice,
}

impl PartialEq for SourceFix {
    fn eq(&self, other: &Self) -> bool {
        self.edit == other.edit && self.source_slice == other.source_slice
    }
}

impl std::hash::Hash for SourceFix {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.edit.hash(state);
        self.source_slice.hash(state);
    }
}
