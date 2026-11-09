//! The code generation of sqll (S8). The S3b stub (task C15) proves the
//! interface of `sqll_schema` (docs/interfaces/schema.md) end to end:
//! [`LiteralSelect`] describes one minimal case, and gives `unsupported`
//! for each other query. S8 replaces it.

use sqll_schema::{
    Column, Describe, DescribeError, DescribeInput, Description, Nullability, SourceSpan, SqlType,
    StatementKind,
};
use sqll_syntax::Dialect;
use sqll_tree::view::nodes::{AliasExpression, Placeholder, SelectClause, SelectStatement};
use sqll_tree::{NodeRef, SegmentType};

/// The stub: an ANSI `SELECT` of literals, each with an alias, and nothing
/// else (no `FROM`, no modifier, no parameter, no template tag), for
/// example `SELECT 1 AS a, 'x' AS "b"`.
///
/// - A column name is the alias: a naked identifier in upper case (the
///   ANSI rule), a quoted identifier with no quotes.
/// - The literals: an integer (digits only, in the range of `i64`) is
///   `integer`, a string in single quotes is `text`, `TRUE` and `FALSE`
///   are `boolean` (each not NULL); `NULL` is NULL with an unknown type.
/// - A comma at the end of the select clause gives `Unsupported`.
/// - Each other form gives [`DescribeError::Unsupported`].
#[derive(Clone, Copy, Debug, Default)]
pub struct LiteralSelect;

impl Describe for LiteralSelect {
    fn describe(&self, input: &DescribeInput<'_>) -> Result<Description, DescribeError> {
        let statement = *input.statement;
        if input.dialect != Dialect::Ansi {
            let name = format!("{:?}", input.dialect).to_lowercase();
            return Err(DescribeError::unsupported(
                statement,
                format!("the dialect {name}"),
            ));
        }
        if let Some(tag) = statement.descendants_as::<Placeholder<'_>>().next() {
            return Err(DescribeError::unsupported(*tag, "a template tag"));
        }
        let select: SelectStatement<'_> = only_code_child(statement)?
            .cast()
            .ok_or_else(|| unsupported_type(statement.first_code_child(), statement))?;
        let clause: SelectClause<'_> = only_code_child(*select)?
            .cast()
            .ok_or_else(|| unsupported_type(select.first_code_child(), *select))?;
        let mut columns = Vec::new();
        let mut last = None;
        for (i, child) in clause.children().filter(|c| c.is_code()).enumerate() {
            last = Some(child);
            let expected = if i == 0 {
                SegmentType::KEYWORD
            } else if i % 2 == 1 {
                SegmentType::SELECT_CLAUSE_ELEMENT
            } else {
                SegmentType::COMMA
            };
            if !child.is_type(expected) {
                return Err(unsupported_type(Some(child), child));
            }
            if expected == SegmentType::SELECT_CLAUSE_ELEMENT {
                columns.push(column(child)?);
            }
        }
        if columns.is_empty() {
            return Err(DescribeError::unsupported(
                *clause,
                "a select with no column",
            ));
        }
        if let Some(comma) = last.filter(|c| c.is_type(SegmentType::COMMA)) {
            return Err(DescribeError::unsupported(
                comma,
                "a comma at the end of the select clause",
            ));
        }
        Ok(Description {
            kind: StatementKind::Select,
            source: SourceSpan::of_node(statement),
            parameters: Vec::new(),
            columns: Some(columns),
        })
    }
}

/// The only code child of the node, else `Unsupported`.
fn only_code_child(node: NodeRef<'_>) -> Result<NodeRef<'_>, DescribeError> {
    let mut code = node.children().filter(|c| c.is_code());
    match (code.next(), code.next()) {
        (Some(child), None) => Ok(child),
        (_, Some(extra)) => Err(unsupported_type(Some(extra), extra)),
        (None, None) => Err(DescribeError::unsupported(node, "an empty segment")),
    }
}

fn unsupported_type(node: Option<NodeRef<'_>>, at: NodeRef<'_>) -> DescribeError {
    let node = node.unwrap_or(at);
    DescribeError::unsupported(node, format!("a segment of the type {}", node.ty().name()))
}

/// The column of a select element: a literal and an alias.
fn column(element: NodeRef<'_>) -> Result<Column, DescribeError> {
    let code: Vec<NodeRef<'_>> = element.children().filter(|c| c.is_code()).collect();
    let [value, alias] = code[..] else {
        return Err(DescribeError::unsupported(
            element,
            "a select element that is not a literal and an alias",
        ));
    };
    let alias: AliasExpression<'_> = alias
        .cast()
        .ok_or_else(|| unsupported_type(Some(alias), alias))?;
    let (ty, nullability) = literal(value)?;
    Ok(Column {
        name: alias_name(alias)?,
        ty,
        nullability,
        source: SourceSpan::of_node(element),
    })
}

/// The type of a literal leaf.
fn literal(value: NodeRef<'_>) -> Result<(SqlType, Nullability), DescribeError> {
    if !value.tree().is_literal(value.id()) {
        return Err(DescribeError::unsupported(
            value,
            "a value from a template tag",
        ));
    }
    if value.children().next().is_some() {
        return Err(unsupported_type(Some(value), value));
    }
    let raw = value.raw();
    if value.is_type(SegmentType::NUMERIC_LITERAL)
        && !raw.is_empty()
        && raw.bytes().all(|b| b.is_ascii_digit())
    {
        // A larger literal is a NUMERIC (or an error) in the database.
        if raw.parse::<i64>().is_err() {
            return Err(DescribeError::unsupported(
                value,
                format!("the integer {raw} is not in the range of a 64-bit integer"),
            ));
        }
        Ok((SqlType::Integer, Nullability::NotNull))
    } else if value.is_type(SegmentType::QUOTED_LITERAL) && raw.starts_with('\'') {
        Ok((SqlType::Text, Nullability::NotNull))
    } else if value.is_type(SegmentType::BOOLEAN_LITERAL) {
        Ok((SqlType::Boolean, Nullability::NotNull))
    } else if value.is_type(SegmentType::NULL_LITERAL) {
        Ok((SqlType::Unknown, Nullability::Nullable))
    } else {
        Err(DescribeError::unsupported(
            value,
            format!("the literal {raw} ({})", value.ty().name()),
        ))
    }
}

/// The column name of an alias: `AS` (optional) and one identifier.
fn alias_name(alias: AliasExpression<'_>) -> Result<String, DescribeError> {
    let code: Vec<NodeRef<'_>> = alias.children().filter(|c| c.is_code()).collect();
    let ident = match code[..] {
        [ident] => ident,
        [op, ident] if op.is_type(SegmentType::ALIAS_OPERATOR) => ident,
        _ => {
            return Err(DescribeError::unsupported(
                *alias,
                "an alias that is not one identifier",
            ))
        }
    };
    let raw = ident.raw();
    if ident.is_type(SegmentType::NAKED_IDENTIFIER) {
        Ok(raw.to_uppercase())
    } else if ident.is_type(SegmentType::QUOTED_IDENTIFIER)
        && raw.len() >= 2
        && raw.starts_with('"')
        && raw.ends_with('"')
    {
        Ok(raw[1..raw.len() - 1].replace("\"\"", "\""))
    } else {
        Err(unsupported_type(Some(ident), ident))
    }
}
