//! The syntax crate of sqll (docs/decisions/s3b-core.md, Q1 and Q3). Task
//! C7 adds the conversion from the parser tree (`Node`) to the
//! [`SyntaxTree`](sqll_tree::SyntaxTree); C8 adds the source map of the
//! tree; C9 adds the parse interface.

pub mod convert;

pub use convert::{from_node, from_node_with_source, kind_of, ConvertError, Converted};
