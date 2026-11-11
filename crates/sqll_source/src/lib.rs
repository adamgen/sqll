//! The source map crate of sqll (docs/interfaces/source-map.md; S3b task
//! C8). The ported `TemplatedFile` (`sqll_types`) is the frozen interface
//! from a templater to the lexer and to the source map. This crate has the
//! [`Templater`] trait, the [`SourceMap`] over a `TemplatedFile`, and the
//! lines and positions of a text. The templaters are in `sqll_templater`.

pub mod lines;
pub mod map;
pub mod templater;

pub use lines::{LineIndex, LinePos};
pub use map::{SourceMap, SourceMapError};
pub use sqll_types::{RawFileSlice, Slice, TemplatedFile, TemplatedFileSlice};
pub use templater::{Templater, TemplaterConfig, TemplaterError};
