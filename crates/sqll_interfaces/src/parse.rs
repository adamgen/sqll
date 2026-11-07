//! The parser tree of `sqll parse`, for the tests that compare the
//! `SyntaxTree` with it. Since S3b C9 the settings are those of the parse
//! interface (`sqll_syntax::parse::steps`); this file keeps no copy.

use std::sync::Arc;

use sqll_dialects::Dialect;
use sqll_parser::parser::Node;
use sqll_syntax::parse::steps::parse_node;
use sqll_syntax::ParseOptions;
use sqll_types::TemplatedFile;

/// Lex and parse the SQL as `sqll parse` does with no option. As in `sqll
/// parse`, a lex error does not stop the parse (the lexer makes an
/// unlexable token); only a parser stop is an error.
pub fn parse(dialect: Dialect, sql: String) -> Result<Node, String> {
    parse_file(dialect, Arc::new(TemplatedFile::from(sql)))
}

/// Lex and parse the templated text of a `TemplatedFile` as `parse` does.
pub fn parse_file(dialect: Dialect, file: Arc<TemplatedFile>) -> Result<Node, String> {
    parse_node(file, dialect, &ParseOptions::default())
}
