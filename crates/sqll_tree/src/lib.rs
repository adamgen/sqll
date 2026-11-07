//! The syntax tree of sqll (docs/decisions/s3b-core.md, Q1). Task C6 adds
//! the segment types and kinds; C7 adds the tree.

pub mod kinds;

pub use kinds::{KindData, KindKey, Meta, SegmentKind, SegmentType, Variant};
