//! The syntax crate of sqll (docs/decisions/s3b-core.md, Q1 and Q3). Task
//! C7 adds the conversion from the parser tree (`Node`) to the
//! [`SyntaxTree`](sqll_tree::SyntaxTree); C9 adds the parse interface.

pub mod convert;

pub use convert::{from_node, kind_of, ConvertError, Converted};
