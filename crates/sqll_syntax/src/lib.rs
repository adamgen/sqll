//! The syntax crate of sqll (docs/decisions/s3b-core.md, Q1 and Q3). Task
//! C7 adds the conversion from the parser tree (`Node`) to the
//! [`SyntaxTree`](sqll_tree::SyntaxTree); C8 adds the source map of the
//! tree; C9 adds the frozen parse interface ([`parse()`],
//! docs/interfaces/parse.md).

pub mod convert;
pub mod parse;

pub use convert::{from_node, from_node_with_source, kind_of, ConvertError, Converted};
pub use parse::{
    depth_limit, parse, Code, Diagnostic, Location, ParseError, ParseOptions, ParseTimes, Parsed,
    MAX_PARSE_DEPTH, MAX_PARSE_DEPTH_LIMIT,
};
pub use sqll_dialects::Dialect;
pub use sqll_source::TemplatedFile;
