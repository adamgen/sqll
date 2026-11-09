//! The `Describe` trait: from a statement of the typed tree, the source map,
//! and the catalog to a [`Description`].

use std::fmt;

use sqll_source::SourceMap;
use sqll_syntax::{Diagnostic, Dialect, Parsed};
use sqll_tree::view::nodes::{File, Statement};
use sqll_tree::{NodeRef, SegmentType, SyntaxTree};

use crate::catalog::Catalog;
use crate::description::{Description, ParamStyle, SourceSpan};

/// The input of [`Describe::describe`]: one statement and its context.
#[derive(Clone, Copy)]
pub struct DescribeInput<'t> {
    /// The statement (a node of the typed view). `statement.tree()` gives
    /// its tree.
    pub statement: Statement<'t>,
    /// The source map of the tree: the source ranges, the source text, and
    /// the templated slices (for example the parameters of a placeholder
    /// templater).
    pub source: &'t SourceMap,
    pub catalog: &'t Catalog,
    pub dialect: Dialect,
    /// The parameter style of the placeholder templater, if the config
    /// gives one.
    pub param_style: Option<ParamStyle>,
}

impl<'t> DescribeInput<'t> {
    pub fn tree(&self) -> &'t SyntaxTree {
        self.statement.tree()
    }
}

/// A query that sqll cannot describe. sqll fails closed: it gives no
/// schema, never a schema that can be wrong.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DescribeError {
    /// A statement, a form, a type, or a dialect that the implementation
    /// cannot describe yet. `source` is the node that it cannot describe.
    Unsupported { reason: String, source: SourceSpan },
    /// A lex or parse error of the file (the first one): a file with an
    /// error gives no description.
    Parse(Diagnostic),
    /// The parse gave no tree.
    NoTree,
    /// The tree has no source map (`SyntaxTree::source_map`).
    NoSourceMap,
}

impl DescribeError {
    /// `Unsupported` at a node.
    pub fn unsupported(node: NodeRef<'_>, reason: impl Into<String>) -> DescribeError {
        DescribeError::Unsupported {
            reason: reason.into(),
            source: SourceSpan::of_node(node),
        }
    }
}

impl fmt::Display for DescribeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            DescribeError::Unsupported { reason, source } => {
                write!(f, "unsupported: {reason} ({source})")
            }
            DescribeError::Parse(error) => write!(f, "a parse error: {error}"),
            DescribeError::NoTree => write!(f, "the parse gave no tree"),
            DescribeError::NoSourceMap => write!(f, "the syntax tree has no source map"),
        }
    }
}

impl std::error::Error for DescribeError {}

/// An implementation of the code generation (S8 `sqll_codegen`).
pub trait Describe: Send + Sync {
    /// The description of the statement, or an error. It must not give a
    /// description that can be wrong: a form that it does not know gives
    /// [`DescribeError::Unsupported`].
    fn describe(&self, input: &DescribeInput<'_>) -> Result<Description, DescribeError>;
}

const UNPARSABLE: &[SegmentType] = &[SegmentType::UNPARSABLE];

/// Describe each statement of a parse, in order (`File::statements`). A
/// parse with an error (a lex error, an unparsable section, or a parser
/// stop) gives no description: the error is the first error of the parse.
/// The tree must have a source map and a `file` root.
pub fn describe_file(
    describer: &dyn Describe,
    parsed: &Parsed,
    catalog: &Catalog,
    dialect: Dialect,
    param_style: Option<ParamStyle>,
) -> Result<Vec<Result<Description, DescribeError>>, DescribeError> {
    if let Some(error) = parsed.errors.first() {
        return Err(DescribeError::Parse(error.clone()));
    }
    let tree = parsed.tree.as_ref().ok_or(DescribeError::NoTree)?;
    let source = tree.source_map().ok_or(DescribeError::NoSourceMap)?;
    let root = tree.root_node();
    if let Some(bad) = root.crawl(UNPARSABLE).next() {
        return Err(DescribeError::unsupported(bad, "an unparsable section"));
    }
    let file: File<'_> = root
        .cast()
        .ok_or_else(|| DescribeError::unsupported(root, "a tree with no file root"))?;
    Ok(file
        .statements()
        .map(|statement| {
            describer.describe(&DescribeInput {
                statement,
                source,
                catalog,
                dialect,
                param_style,
            })
        })
        .collect())
}
