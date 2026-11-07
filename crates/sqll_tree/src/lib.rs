//! The syntax tree of sqll (docs/decisions/s3b-core.md, Q1). Task C6 adds
//! the segment types and kinds; C7 adds the tree; C8 adds the source map
//! of a tree; C10 adds the typed view.

pub mod kinds;
pub mod tree;
pub mod view;

pub use kinds::{KindData, KindKey, Meta, SegmentKind, SegmentType, Variant};
pub use tree::{Children, LineIndex, LinePos, NodeId, SyntaxTree, TreeBuilder, TreeError};
pub use view::{AstNode, Crawl, NodeRef};
