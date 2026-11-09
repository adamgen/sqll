//! The code generation interface of sqll (docs/interfaces/schema.md; S3b
//! task C15): tree to schema.
//!
//! - [`Description`]: the description of one query: the statement kind, the
//!   input parameters, the output columns, and the source range of each.
//! - [`Describe`]: makes a description from a statement of the typed view,
//!   the source map of its tree, and a [`Catalog`] (read from DDL by S8).
//!   A query that an implementation cannot describe fails closed
//!   ([`DescribeError::Unsupported`]).
//! - [`write_json_schema`]: the JSON Schema (draft 2020-12) of a
//!   description. Other tools make code in each language from it (G2.2).

pub mod catalog;
pub mod describe;
pub mod description;
pub mod json;

pub use catalog::{Catalog, CatalogColumn, Table};
pub use describe::{describe_file, Describe, DescribeError, DescribeInput};
pub use description::{
    Column, Description, Nullability, ParamStyle, Parameter, SourceSpan, SqlType, StatementKind,
};
pub use json::{write_json_schema, SchemaError, DRAFT_2020_12};
