// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_types/src/config/fluffconfig.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.

#[derive(Clone)]
pub struct FluffConfig {
    pub dialect: Option<String>,
    pub template_blocks_indent: bool,
    /// Maximum number of parser iterations before aborting (default: 3_000_000).
    pub max_parser_iterations: Option<usize>,
    /// Iteration count at which a warning is emitted (default: 2_000_000).
    pub parser_warn_threshold: Option<usize>,
}

impl FluffConfig {
    pub fn new(dialect: Option<String>, template_blocks_indent: bool) -> Self {
        Self {
            dialect,
            template_blocks_indent,
            max_parser_iterations: None,
            parser_warn_threshold: None,
        }
    }

    pub fn with_parser_limits(
        mut self,
        max_parser_iterations: Option<usize>,
        parser_warn_threshold: Option<usize>,
    ) -> Self {
        self.max_parser_iterations = max_parser_iterations;
        self.parser_warn_threshold = parser_warn_threshold;
        self
    }
}
