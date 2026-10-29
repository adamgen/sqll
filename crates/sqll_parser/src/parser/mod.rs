// This file is a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_parser/src/parser/mod.rs
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md and crates/ported.json.
// sqll changed this file. crates/ported.json gives the reason.

//! Iterative parser implementation for SQLFluff
//!
//! This module contains an iterative (non-recursive) parser that uses an
//! explicit stack of frames to parse SQL grammar without stack overflow risks.

/// Verbose debug logging macro - only compiles logging code when verbose-debug feature is enabled.
/// This eliminates runtime overhead of debug logging in production builds.
#[macro_export]
macro_rules! vdebug {
    ($($arg:tt)*) => {
        #[cfg(feature = "verbose-debug")]
        log::debug!($($arg)*);
    };
}

pub(crate) mod arena;
mod cache;
mod core;
mod frame;
mod helpers; // Utility methods for Parser
mod match_result;
mod table_driven;
pub(crate) mod types;

// Re-export public types
pub use core::Parser;
pub use match_result::{MatchResult, MatchedClass, MetaSegment};
pub use sqlfluffrs_types::ParseMode;
pub use table_driven::ref_grammar::MISSING_REF_PREFIX;
pub use types::{MetaType, Node, ParseError, ParseErrorType, RawSegmentKwargs};

// Internal re-exports for submodules
pub(crate) use frame::{
    AnyNumberOfState, BracketedPhase, BracketedState, DelimitedPhase, DelimitedState, FrameContext,
    FrameState, OneOfState, RefState, SequenceState,
};
