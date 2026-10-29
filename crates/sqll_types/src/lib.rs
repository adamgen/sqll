// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_types/src/lib.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.

pub mod config;
pub mod grammar_api;
pub mod grammar_inst;
pub mod grammar_tables;
pub mod identity;
pub mod marker;
pub mod matcher;
pub mod parser;
pub mod regex;
pub mod slice;
pub mod string;
pub mod templater;
pub mod token;
pub use config::fluffconfig::FluffConfig;
pub use grammar_api::{patterns as grammar_patterns, GrammarContext};
pub use grammar_inst::{GrammarFlags, GrammarId, GrammarInst, GrammarVariant};
pub use grammar_tables::{
    ChildrenIter, GrammarInstExt, GrammarTables, SimpleHintData, TableMemoryStats, TerminatorsIter,
};
pub use marker::PositionMarker;
pub use matcher::{BracketPairEntry, BracketPairSet, LexMatcher, LexMatcherConfig};
pub use parser::{ParseMode, RootGrammar, SimpleHint};
pub use regex::{RegexMode, RegexModeGroup};
pub use slice::Slice;
pub use templater::fileslice::{RawFileSlice, TemplatedFileSlice};
pub use templater::templatefile::TemplatedFile;
pub use token::{config::TokenConfig, Token};
