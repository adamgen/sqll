//! The JSON Schema (draft 2020-12) of a description
//! (docs/interfaces/schema.md, "JSON Schema").

use std::collections::BTreeSet;
use std::fmt;

use crate::description::{Column, Description, Nullability, Parameter, SourceSpan, SqlType};

/// The meta-schema URI of JSON Schema draft 2020-12.
pub const DRAFT_2020_12: &str = "https://json-schema.org/draft/2020-12/schema";

/// A description that the writer refuses: it cannot give a correct schema
/// of it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SchemaError {
    /// Two columns have the same name: a JSON object cannot keep both.
    DuplicateColumn(String),
    /// A column has an empty name.
    EmptyColumnName,
    /// The parameters do not all have the same style.
    MixedStyles,
    /// The positions of the parameters are not 1, 2, ..., n in order.
    Positions,
    /// A parameter of a named style has no name or an empty name, a
    /// parameter of `:1` or `$1` does not have its position as its name, or
    /// a parameter of `?` or `%s` has a name.
    ParameterName { position: usize },
    /// Two named parameters have the same name.
    DuplicateParameter(String),
    /// A parameter has no source.
    NoParameterSource { position: usize },
}

impl fmt::Display for SchemaError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SchemaError::DuplicateColumn(name) => write!(f, "two columns have the name {name:?}"),
            SchemaError::EmptyColumnName => write!(f, "a column has an empty name"),
            SchemaError::MixedStyles => write!(f, "the parameters have different styles"),
            SchemaError::Positions => {
                write!(f, "the parameter positions are not 1 to n in order")
            }
            SchemaError::ParameterName { position } => {
                write!(
                    f,
                    "parameter {position}: the name does not agree with its style"
                )
            }
            SchemaError::DuplicateParameter(name) => {
                write!(f, "two parameters have the name {name:?}")
            }
            SchemaError::NoParameterSource { position } => {
                write!(f, "parameter {position} has no source")
            }
        }
    }
}

impl std::error::Error for SchemaError {}

/// The JSON Schema of the description, with the title `title`: an object
/// with `parameters` (an object by name, or an array by position) and
/// `row` (one row of the result; no `row` if the statement gives no rows).
/// The text is JSON with an indent of 2 spaces and a newline at the end;
/// the object members keep the order of the columns and the parameters.
pub fn write_json_schema(description: &Description, title: &str) -> Result<String, SchemaError> {
    check(description)?;
    let mut properties = vec![("parameters".to_string(), reference("parameters"))];
    let mut required = vec![Json::from("parameters")];
    let mut defs = vec![(
        "parameters".to_string(),
        parameters(&description.parameters),
    )];
    if let Some(columns) = &description.columns {
        properties.push(("row".into(), reference("row")));
        required.push(Json::from("row"));
        defs.push(("row".into(), row(columns)));
    }
    let schema = Json::Object(vec![
        ("$schema".into(), Json::from(DRAFT_2020_12)),
        ("title".into(), Json::from(title)),
        ("type".into(), Json::from("object")),
        ("properties".into(), Json::Object(properties)),
        ("required".into(), Json::Array(required)),
        ("additionalProperties".into(), Json::Bool(false)),
        ("$defs".into(), Json::Object(defs)),
        (
            "x-sqll-statement".into(),
            Json::from(description.kind.as_str()),
        ),
        ("x-sqll-source".into(), span(&description.source)),
    ]);
    let mut out = String::new();
    schema.write(&mut out, 0);
    out.push('\n');
    Ok(out)
}

fn check(description: &Description) -> Result<(), SchemaError> {
    if let Some(columns) = &description.columns {
        let mut names = BTreeSet::new();
        for column in columns {
            if column.name.is_empty() {
                return Err(SchemaError::EmptyColumnName);
            }
            if !names.insert(column.name.as_str()) {
                return Err(SchemaError::DuplicateColumn(column.name.clone()));
            }
        }
    }
    let params = &description.parameters;
    if let Some(first) = params.first() {
        if params.iter().any(|p| p.style != first.style) {
            return Err(SchemaError::MixedStyles);
        }
    }
    let mut names = BTreeSet::new();
    for (i, p) in params.iter().enumerate() {
        if p.position != i + 1 {
            return Err(SchemaError::Positions);
        }
        if p.sources.is_empty() {
            return Err(SchemaError::NoParameterSource {
                position: p.position,
            });
        }
        let name_ok = match (&p.name, p.style.has_name()) {
            (Some(n), true) if p.style.is_positional() => *n == p.position.to_string(),
            (Some(n), true) => !n.is_empty(),
            (None, false) => true,
            _ => false,
        };
        if !name_ok {
            return Err(SchemaError::ParameterName {
                position: p.position,
            });
        }
        if let Some(name) = &p.name {
            if !names.insert(name.as_str()) {
                return Err(SchemaError::DuplicateParameter(name.clone()));
            }
        }
    }
    Ok(())
}

fn reference(def: &str) -> Json {
    Json::Object(vec![("$ref".into(), Json::from(format!("#/$defs/{def}")))])
}

fn parameters(params: &[Parameter]) -> Json {
    let positional = params.first().is_some_and(|p| p.style.is_positional());
    if positional {
        let n = Json::Number(params.len() as u64);
        return Json::Object(vec![
            ("type".into(), Json::from("array")),
            (
                "prefixItems".into(),
                Json::Array(params.iter().map(parameter).collect()),
            ),
            ("items".into(), Json::Bool(false)),
            ("minItems".into(), n.clone()),
            ("maxItems".into(), n),
        ]);
    }
    object(
        params
            .iter()
            .map(|p| (p.name.clone().unwrap_or_default(), parameter(p)))
            .collect(),
    )
}

fn parameter(p: &Parameter) -> Json {
    let mut members = value(&p.ty, p.nullability);
    if let Some(name) = &p.name {
        members.push(("x-sqll-name".into(), Json::from(name.as_str())));
    }
    members.push(("x-sqll-position".into(), Json::Number(p.position as u64)));
    members.push(("x-sqll-style".into(), Json::from(p.style.name())));
    members.push((
        "x-sqll-sources".into(),
        Json::Array(p.sources.iter().map(span).collect()),
    ));
    Json::Object(members)
}

fn row(columns: &[Column]) -> Json {
    object(
        columns
            .iter()
            .map(|c| {
                let mut members = value(&c.ty, c.nullability);
                members.push(("x-sqll-source".into(), span(&c.source)));
                (c.name.clone(), Json::Object(members))
            })
            .collect(),
    )
}

/// A closed object: each property is required.
fn object(properties: Vec<(String, Json)>) -> Json {
    let required = properties
        .iter()
        .map(|(name, _)| Json::from(name.as_str()))
        .collect();
    Json::Object(vec![
        ("type".into(), Json::from("object")),
        ("properties".into(), Json::Object(properties)),
        ("required".into(), Json::Array(required)),
        ("additionalProperties".into(), Json::Bool(false)),
    ])
}

/// The schema members of a value of the type: the JSON type (with "null"
/// if the value can be NULL), the format, `x-sqll-type`, and
/// `x-sqll-nullability`.
fn value(ty: &SqlType, nullability: Nullability) -> Vec<(String, Json)> {
    let mut members = type_members(ty, nullability.permits_null());
    members.push(("x-sqll-type".into(), Json::from(ty.name())));
    members.push((
        "x-sqll-nullability".into(),
        Json::from(nullability.as_str()),
    ));
    members
}

/// The JSON type of a SQL type, and its other members. `None`: each JSON
/// value (the `Json`, `Named`, and `Unknown` types).
fn json_type(ty: &SqlType) -> (Option<&'static str>, Vec<(String, Json)>) {
    let format = |f: &str| vec![("format".to_string(), Json::from(f))];
    match ty {
        SqlType::Boolean => (Some("boolean"), vec![]),
        SqlType::Integer => (Some("integer"), vec![]),
        // An exact decimal is a string: a JSON number can lose digits.
        SqlType::Decimal => (Some("string"), vec![]),
        SqlType::Float => (Some("number"), vec![]),
        // A value with no time zone has no format: the RFC 3339 formats
        // "time" and "date-time" need an offset.
        SqlType::Text | SqlType::Time | SqlType::Timestamp | SqlType::Interval => {
            (Some("string"), vec![])
        }
        SqlType::Bytes => (
            Some("string"),
            vec![("contentEncoding".into(), Json::from("base64"))],
        ),
        SqlType::Date => (Some("string"), format("date")),
        SqlType::TimeTz => (Some("string"), format("time")),
        SqlType::TimestampTz => (Some("string"), format("date-time")),
        SqlType::Uuid => (Some("string"), format("uuid")),
        SqlType::Array(item) => (
            Some("array"),
            vec![("items".into(), Json::Object(type_members(item, true)))],
        ),
        SqlType::Json | SqlType::Named(_) | SqlType::Unknown => (None, vec![]),
    }
}

fn type_members(ty: &SqlType, permits_null: bool) -> Vec<(String, Json)> {
    let (json, rest) = json_type(ty);
    let mut members = Vec::new();
    match (json, permits_null) {
        (Some(t), false) => members.push(("type".into(), Json::from(t))),
        (Some(t), true) => members.push((
            "type".into(),
            Json::Array(vec![Json::from(t), Json::from("null")]),
        )),
        (None, false) => members.push((
            "not".into(),
            Json::Object(vec![("type".into(), Json::from("null"))]),
        )),
        (None, true) => {}
    }
    members.extend(rest);
    members
}

fn span(s: &SourceSpan) -> Json {
    Json::Object(vec![
        ("start".into(), Json::Number(s.start as u64)),
        ("end".into(), Json::Number(s.end as u64)),
        ("line".into(), Json::Number(s.line as u64)),
        ("pos".into(), Json::Number(s.pos as u64)),
    ])
}

/// A JSON value whose objects keep the order of their members.
#[derive(Clone, Debug)]
enum Json {
    Bool(bool),
    Number(u64),
    String(String),
    Array(Vec<Json>),
    Object(Vec<(String, Json)>),
}

impl From<&str> for Json {
    fn from(s: &str) -> Json {
        Json::String(s.to_string())
    }
}

impl From<String> for Json {
    fn from(s: String) -> Json {
        Json::String(s)
    }
}

impl Json {
    fn write(&self, out: &mut String, indent: usize) {
        match self {
            Json::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            Json::Number(n) => out.push_str(&n.to_string()),
            Json::String(s) => write_string(out, s),
            Json::Array(items) if items.is_empty() => out.push_str("[]"),
            Json::Object(members) if members.is_empty() => out.push_str("{}"),
            Json::Array(items) => {
                out.push('[');
                for (i, item) in items.iter().enumerate() {
                    out.push_str(if i == 0 { "\n" } else { ",\n" });
                    push_indent(out, indent + 1);
                    item.write(out, indent + 1);
                }
                out.push('\n');
                push_indent(out, indent);
                out.push(']');
            }
            Json::Object(members) => {
                out.push('{');
                for (i, (key, item)) in members.iter().enumerate() {
                    out.push_str(if i == 0 { "\n" } else { ",\n" });
                    push_indent(out, indent + 1);
                    write_string(out, key);
                    out.push_str(": ");
                    item.write(out, indent + 1);
                }
                out.push('\n');
                push_indent(out, indent);
                out.push('}');
            }
        }
    }
}

fn push_indent(out: &mut String, indent: usize) {
    for _ in 0..indent {
        out.push_str("  ");
    }
}

/// A JSON string (RFC 8259): `"` and `\` and the control characters are
/// escaped; the other characters are UTF-8.
fn write_string(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_string_escapes_quotes_backslashes_and_control_characters() {
        let mut out = String::new();
        write_string(&mut out, "a\"b\\c\nd\u{1}e\u{7f}é");
        assert_eq!(out, "\"a\\\"b\\\\c\\nd\\u0001e\u{7f}é\"");
    }

    #[test]
    fn empty_arrays_and_objects_are_on_one_line() {
        let mut out = String::new();
        Json::Object(vec![
            ("a".into(), Json::Array(vec![])),
            ("b".into(), Json::Object(vec![])),
            (
                "c".into(),
                Json::Array(vec![Json::Number(1), Json::Bool(true)]),
            ),
        ])
        .write(&mut out, 0);
        assert_eq!(
            out,
            "{\n  \"a\": [],\n  \"b\": {},\n  \"c\": [\n    1,\n    true\n  ]\n}"
        );
    }
}
