//! The description of a query: the data that [`crate::Describe`] gives and
//! [`crate::write_json_schema`] writes.

use std::fmt;

use sqll_tree::view::nodes::Statement;
use sqll_tree::{NodeId, NodeRef, SegmentType, SyntaxTree};

/// The kind of a statement.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum StatementKind {
    Select,
    Insert,
    Update,
    Delete,
    Merge,
    /// Another statement, for example DDL.
    Other,
}

impl StatementKind {
    /// The name in the JSON Schema (`x-sqll-statement`).
    pub fn as_str(self) -> &'static str {
        match self {
            StatementKind::Select => "select",
            StatementKind::Insert => "insert",
            StatementKind::Update => "update",
            StatementKind::Delete => "delete",
            StatementKind::Merge => "merge",
            StatementKind::Other => "other",
        }
    }

    /// The kind of a statement of the tree: the type of its statement
    /// segment. A `with_compound_statement` has the kind of its last
    /// statement segment (the statement after the common table
    /// expressions).
    pub fn of(statement: Statement<'_>) -> StatementKind {
        match statement.inner() {
            Some(inner) => Self::of_segment(inner),
            None => StatementKind::Other,
        }
    }

    fn of_segment(node: NodeRef<'_>) -> StatementKind {
        const MAIN: &[SegmentType] = &[
            SegmentType::SELECT_STATEMENT,
            SegmentType::SET_EXPRESSION,
            SegmentType::INSERT_STATEMENT,
            SegmentType::UPDATE_STATEMENT,
            SegmentType::DELETE_STATEMENT,
            SegmentType::MERGE_STATEMENT,
        ];
        if node.is_type(SegmentType::WITH_COMPOUND_STATEMENT) {
            return match node.children_of(MAIN).last() {
                Some(main) => Self::of_segment(main),
                None => StatementKind::Other,
            };
        }
        if node.is_any_type(&[SegmentType::SELECT_STATEMENT, SegmentType::SET_EXPRESSION]) {
            StatementKind::Select
        } else if node.is_type(SegmentType::INSERT_STATEMENT) {
            StatementKind::Insert
        } else if node.is_type(SegmentType::UPDATE_STATEMENT) {
            StatementKind::Update
        } else if node.is_type(SegmentType::DELETE_STATEMENT) {
            StatementKind::Delete
        } else if node.is_type(SegmentType::MERGE_STATEMENT) {
            StatementKind::Merge
        } else {
            StatementKind::Other
        }
    }
}

/// A parameter style: the `param_style` names of the sqlfluff placeholder
/// templater (`KNOWN_STYLES`). S6 makes the templater; S8 finds the
/// parameters.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum ParamStyle {
    /// `:name`
    Colon,
    /// `:name`, `:'name'`, or `:"name"`
    ColonOptionalQuotes,
    /// `:name`, also after a word character
    ColonNoSpaces,
    /// `:1`
    NumericColon,
    /// `%(name)s`
    Pyformat,
    /// `$name` or `${name}`
    Dollar,
    /// `$name$`
    DollarSurround,
    /// `${flyway:name}`
    FlywayVar,
    /// `?`
    QuestionMark,
    /// `$1` or `${1}`
    NumericDollar,
    /// `%s`
    Percent,
    /// `&name` or `&{name}`
    Ampersand,
}

impl ParamStyle {
    pub const ALL: [ParamStyle; 12] = [
        ParamStyle::Colon,
        ParamStyle::ColonOptionalQuotes,
        ParamStyle::ColonNoSpaces,
        ParamStyle::NumericColon,
        ParamStyle::Pyformat,
        ParamStyle::Dollar,
        ParamStyle::DollarSurround,
        ParamStyle::FlywayVar,
        ParamStyle::QuestionMark,
        ParamStyle::NumericDollar,
        ParamStyle::Percent,
        ParamStyle::Ampersand,
    ];

    /// The sqlfluff `param_style` name.
    pub fn name(self) -> &'static str {
        match self {
            ParamStyle::Colon => "colon",
            ParamStyle::ColonOptionalQuotes => "colon_optional_quotes",
            ParamStyle::ColonNoSpaces => "colon_nospaces",
            ParamStyle::NumericColon => "numeric_colon",
            ParamStyle::Pyformat => "pyformat",
            ParamStyle::Dollar => "dollar",
            ParamStyle::DollarSurround => "dollar_surround",
            ParamStyle::FlywayVar => "flyway_var",
            ParamStyle::QuestionMark => "question_mark",
            ParamStyle::NumericDollar => "numeric_dollar",
            ParamStyle::Percent => "percent",
            ParamStyle::Ampersand => "ampersand",
        }
    }

    /// The style of a sqlfluff `param_style` name.
    pub fn from_name(name: &str) -> Option<ParamStyle> {
        Self::ALL.into_iter().find(|s| s.name() == name)
    }

    /// True if the parameters are given by position (a JSON array), not
    /// by name (a JSON object): `?`, `%s`, `:1`, and `$1`.
    pub fn is_positional(self) -> bool {
        matches!(
            self,
            ParamStyle::QuestionMark
                | ParamStyle::Percent
                | ParamStyle::NumericColon
                | ParamStyle::NumericDollar
        )
    }

    /// True if a parameter of the style has a name: all but `?` and `%s`.
    /// The name of a numeric style is its number.
    pub fn has_name(self) -> bool {
        !matches!(self, ParamStyle::QuestionMark | ParamStyle::Percent)
    }
}

/// The type of a value. S8 finds the types (type inference); the writer
/// gives each one a JSON Schema (docs/interfaces/schema.md, "Types").
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum SqlType {
    Boolean,
    Integer,
    /// An exact number with a fraction, for example `NUMERIC(10, 2)`.
    Decimal,
    /// An approximate number, for example `DOUBLE PRECISION`.
    Float,
    Text,
    Bytes,
    Date,
    Time,
    /// A timestamp with no time zone.
    Timestamp,
    /// A timestamp with a time zone.
    TimestampTz,
    Interval,
    Uuid,
    Json,
    Array(Box<SqlType>),
    /// A type of the catalog that has no other `SqlType`, by its name (for
    /// example an enum type).
    Named(String),
    /// The type is not known.
    Unknown,
}

impl SqlType {
    /// The name in the JSON Schema (`x-sqll-type`), for example `integer`
    /// or `array<text>`.
    pub fn name(&self) -> String {
        match self {
            SqlType::Boolean => "boolean".into(),
            SqlType::Integer => "integer".into(),
            SqlType::Decimal => "decimal".into(),
            SqlType::Float => "float".into(),
            SqlType::Text => "text".into(),
            SqlType::Bytes => "bytes".into(),
            SqlType::Date => "date".into(),
            SqlType::Time => "time".into(),
            SqlType::Timestamp => "timestamp".into(),
            SqlType::TimestampTz => "timestamptz".into(),
            SqlType::Interval => "interval".into(),
            SqlType::Uuid => "uuid".into(),
            SqlType::Json => "json".into(),
            SqlType::Array(item) => format!("array<{}>", item.name()),
            SqlType::Named(name) => format!("named<{name}>"),
            SqlType::Unknown => "unknown".into(),
        }
    }
}

/// Can a value be NULL?
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Nullability {
    NotNull,
    Nullable,
    /// Not known. The JSON Schema permits NULL, as for `Nullable`.
    Unknown,
}

impl Nullability {
    /// The name in the JSON Schema (`x-sqll-nullability`).
    pub fn as_str(self) -> &'static str {
        match self {
            Nullability::NotNull => "not_null",
            Nullability::Nullable => "nullable",
            Nullability::Unknown => "unknown",
        }
    }

    /// True if the value can be NULL, or if this is not known.
    pub fn permits_null(self) -> bool {
        self != Nullability::NotNull
    }
}

/// A range of the source text (the text before the templater): byte
/// offsets, and the line and position (from 1, in characters) of the
/// start.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct SourceSpan {
    pub start: usize,
    pub end: usize,
    pub line: usize,
    pub pos: usize,
}

impl SourceSpan {
    /// The source range of a node, through the source map of its tree.
    pub fn of(tree: &SyntaxTree, id: NodeId) -> SourceSpan {
        let range = tree.source_range(id);
        let at = tree.source_pos(id);
        SourceSpan {
            start: range.start,
            end: range.end,
            line: at.line,
            pos: at.pos,
        }
    }

    /// The source range of a node of the typed view.
    pub fn of_node(node: NodeRef<'_>) -> SourceSpan {
        Self::of(node.tree(), node.id())
    }
}

impl fmt::Display for SourceSpan {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "line {}, position {}", self.line, self.pos)
    }
}

/// An input parameter of a query.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Parameter {
    /// The name: `None` for `?` and `%s`; the number for `:1` and `$1`.
    pub name: Option<String>,
    /// The position in the parameter list, from 1. For `:1` and `$1` it is
    /// the number; for the other styles, the order of the first use.
    pub position: usize,
    pub style: ParamStyle,
    pub ty: SqlType,
    pub nullability: Nullability,
    /// Each use of the parameter in the source, in order (one or more).
    pub sources: Vec<SourceSpan>,
}

/// An output column of a query.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Column {
    /// The column name that the database gives.
    pub name: String,
    pub ty: SqlType,
    pub nullability: Nullability,
    /// The source of the column: its select element.
    pub source: SourceSpan,
}

/// The description of one query.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Description {
    pub kind: StatementKind,
    /// The source of the statement.
    pub source: SourceSpan,
    /// The input parameters, in the order of `position`.
    pub parameters: Vec<Parameter>,
    /// The output columns in order, or `None` if the statement gives no
    /// rows (for example an `INSERT` with no `RETURNING`).
    pub columns: Option<Vec<Column>>,
}
