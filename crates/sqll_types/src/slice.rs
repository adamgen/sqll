// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_types/src/slice.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.

use std::{fmt::Display, ops::Range};

use serde::{Deserialize, Serialize};

#[derive(Debug, PartialEq, Hash, Eq, Clone, Copy, Serialize, Deserialize)]
pub struct Slice {
    pub start: usize,
    pub stop: usize,
}

impl From<Range<usize>> for Slice {
    fn from(value: Range<usize>) -> Self {
        Self {
            start: value.start,
            stop: value.end,
        }
    }
}

impl Slice {
    pub fn slice_is_point(test_slice: &Range<usize>) -> bool {
        test_slice.start == test_slice.end
    }

    pub fn len(&self) -> usize {
        self.stop - self.start
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

impl Display for Slice {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "slice({}, {}, None)", self.start, self.stop)
    }
}
