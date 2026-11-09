//! The interface test of the code generation interface (`sqll_schema`;
//! docs/interfaces/schema.md; S3b task C15).
//!
//! - The signatures of the interface (`signatures`).
//! - The minimal case end to end: the raw templater, `sqll_syntax::parse`,
//!   `describe_file` with the S8 stub `sqll_codegen::LiteralSelect`, and the
//!   JSON Schema writer.
//! - The stub and `describe_file` fail closed for each other form.
//! - The writer: hand-built descriptions with parameters and each type, and
//!   the descriptions that it refuses.
//! - The record: results/S3b/C15-schema.json and the schema files in
//!   results/S3b/C15-schema/ are the output of this test.
//!   scripts/s3b/schema_check.py validates each schema against the JSON
//!   Schema meta-schema (draft 2020-12) and each example row against its
//!   schema.

use std::path::PathBuf;
use std::str::FromStr;

use serde_json::{json, Value as Json};
use sqll_codegen::LiteralSelect;
use sqll_interfaces::{root, with_parse_stack};
use sqll_schema::{
    describe_file, write_json_schema, Catalog, CatalogColumn, Column, Describe, DescribeError,
    DescribeInput, Description, Nullability, ParamStyle, Parameter, SchemaError, SourceSpan,
    SqlType, StatementKind, Table, DRAFT_2020_12,
};
use sqll_source::{
    RawFileSlice, Slice, SourceMap, TemplatedFile, TemplatedFileSlice, Templater, TemplaterConfig,
    TemplaterError,
};
use sqll_syntax::{Dialect, ParseOptions, Parsed};
use sqll_tree::view::nodes::{File, Statement};
use sqll_tree::{NodeId, NodeRef, SyntaxTree};

const RECORD: &str = "results/S3b/C15-schema.json";
const RECORD_DIR: &str = "results/S3b/C15-schema";
const RECORD_KIND: &str = "sqll-s3b-c15-schema";
const WRITE_COMMAND: &str =
    "uv run --frozen --project harness python scripts/s3b/schema_check.py write";
/// The folder of `write_the_record` (scripts/s3b/schema_check.py).
const OUT_ENV: &str = "SQLL_SCHEMA_OUT";

/// The minimal case of the stub.
const MINIMAL: &str = "SELECT 1 AS id, 'x' AS \"Name\", TRUE AS ok, NULL AS note\n";

/// The signatures of the interface. A change of one of them is a change of
/// the frozen interface: this function does not compile.
#[allow(dead_code)]
fn signatures(
    describer: &dyn Describe,
    input: &DescribeInput<'_>,
    parsed: &Parsed,
    tree: &SyntaxTree,
    catalog: &Catalog,
    description: &Description,
) {
    let _: Result<Description, DescribeError> = describer.describe(input);
    let _: (
        Statement<'_>,
        &SourceMap,
        &Catalog,
        Dialect,
        Option<ParamStyle>,
    ) = (
        input.statement,
        input.source,
        input.catalog,
        input.dialect,
        input.param_style,
    );
    let _: &SyntaxTree = input.tree();
    let _: fn(
        &dyn Describe,
        &Parsed,
        &Catalog,
        Dialect,
        Option<ParamStyle>,
    ) -> Result<Vec<Result<Description, DescribeError>>, DescribeError> = describe_file;
    let _: DescribeError = DescribeError::unsupported(tree.root_node(), "a reason");

    let _: (
        StatementKind,
        SourceSpan,
        &Vec<Parameter>,
        &Option<Vec<Column>>,
    ) = (
        description.kind,
        description.source,
        &description.parameters,
        &description.columns,
    );
    let _: fn(Statement<'_>) -> StatementKind = StatementKind::of;
    let _: fn(StatementKind) -> &'static str = StatementKind::as_str;
    let p = &description.parameters[0];
    let _: (
        &Option<String>,
        usize,
        ParamStyle,
        &SqlType,
        Nullability,
        &Vec<SourceSpan>,
    ) = (
        &p.name,
        p.position,
        p.style,
        &p.ty,
        p.nullability,
        &p.sources,
    );
    let c = &description.columns.as_ref().unwrap()[0];
    let _: (&String, &SqlType, Nullability, SourceSpan) = (&c.name, &c.ty, c.nullability, c.source);
    let s = c.source;
    let _: (usize, usize, usize, usize) = (s.start, s.end, s.line, s.pos);
    let _: fn(&SyntaxTree, NodeId) -> SourceSpan = SourceSpan::of;
    let _: fn(NodeRef<'_>) -> SourceSpan = SourceSpan::of_node;
    let _: [ParamStyle; 12] = ParamStyle::ALL;
    let _: fn(ParamStyle) -> &'static str = ParamStyle::name;
    let _: fn(&str) -> Option<ParamStyle> = ParamStyle::from_name;
    let _: fn(ParamStyle) -> bool = ParamStyle::is_positional;
    let _: fn(ParamStyle) -> bool = ParamStyle::has_name;
    let _: fn(&SqlType) -> String = SqlType::name;
    let _: fn(Nullability) -> &'static str = Nullability::as_str;
    let _: fn(Nullability) -> bool = Nullability::permits_null;

    let _: &Vec<Table> = &catalog.tables;
    let _: fn() -> Catalog = Catalog::new;
    let _: Option<&Table> = catalog.table(Some("s"), "t");
    let t = &catalog.tables[0];
    let _: (&Option<String>, &String, &Vec<CatalogColumn>) = (&t.schema, &t.name, &t.columns);
    let _: Option<&CatalogColumn> = t.column("c");
    let cc = &t.columns[0];
    let _: (&String, &SqlType, Nullability) = (&cc.name, &cc.ty, cc.nullability);

    let _: fn(&Description, &str) -> Result<String, SchemaError> = write_json_schema;
    let _: &str = DRAFT_2020_12;
    let _ = (parsed, tree);
}

/// A test templater: each `{{name}}` is a templated slice with the value
/// of `name` in VALUES. ASCII only (a code point is a byte).
struct TagTemplater;

const VALUES: [(&str, &str); 2] = [("v", "1"), ("empty", "")];

impl Templater for TagTemplater {
    fn name(&self) -> &'static str {
        "tag"
    }

    fn process(
        &self,
        source: &str,
        fname: &str,
        _config: &TemplaterConfig,
    ) -> Result<TemplatedFile, TemplaterError> {
        assert!(source.is_ascii());
        let mut templated = String::new();
        let mut sliced = Vec::new();
        let mut raws = Vec::new();
        let mut push = |ty: &str, raw: &str, out: &str, src: usize, templated: &mut String| {
            let tpl = templated.len();
            sliced.push(TemplatedFileSlice::new(
                ty.to_string(),
                Slice::from(src..src + raw.len()),
                Slice::from(tpl..tpl + out.len()),
            ));
            raws.push(RawFileSlice::new(
                raw.to_string(),
                ty.to_string(),
                src,
                Some(0),
                None,
            ));
            templated.push_str(out);
        };
        let mut at = 0;
        while at < source.len() {
            let Some(start) = source[at..].find("{{").map(|i| at + i) else {
                push("literal", &source[at..], &source[at..], at, &mut templated);
                break;
            };
            if start > at {
                push(
                    "literal",
                    &source[at..start],
                    &source[at..start],
                    at,
                    &mut templated,
                );
            }
            let end = start + source[start..].find("}}").expect("an end of the tag") + 2;
            let name = source[start + 2..end - 2].trim();
            let value = VALUES
                .iter()
                .find(|(k, _)| *k == name)
                .map(|(_, v)| *v)
                .expect("a known name");
            push(
                "templated",
                &source[start..end],
                value,
                start,
                &mut templated,
            );
            at = end;
        }
        Ok(TemplatedFile::new(
            source.to_string(),
            fname.to_string(),
            Some(templated),
            Some(sliced),
            Some(raws),
        ))
    }
}

fn parse(templater: &dyn Templater, source: &str, dialect: Dialect) -> Parsed {
    let file = templater
        .process(source, "query.sql", &TemplaterConfig::new())
        .expect("a templated file");
    sqll_syntax::parse(&file, dialect, &ParseOptions::default()).expect("a parse")
}

type Described = Result<Vec<Result<Description, DescribeError>>, DescribeError>;

/// Parse the source with the templater and the dialect, and describe it
/// with the stub.
fn describe_with(tag: bool, source: &str, dialect: &str) -> Described {
    let source = source.to_string();
    let dialect = Dialect::from_str(dialect).expect("a dialect");
    with_parse_stack(move || {
        let parsed = if tag {
            parse(&TagTemplater, &source, dialect)
        } else {
            parse(&sqll_templater::RawTemplater, &source, dialect)
        };
        describe_file(&LiteralSelect, &parsed, &Catalog::new(), dialect, None)
    })
}

fn describe(source: &str, dialect: &str) -> Described {
    describe_with(false, source, dialect)
}

/// The one description of a source with one statement.
fn one(source: &str) -> Result<Description, DescribeError> {
    let mut all = describe(source, "ansi").expect("a clean parse");
    assert_eq!(all.len(), 1, "{source:?}");
    all.remove(0)
}

fn span(start: usize, end: usize, line: usize, pos: usize) -> SourceSpan {
    SourceSpan {
        start,
        end,
        line,
        pos,
    }
}

#[test]
fn the_minimal_case_is_described_end_to_end() {
    let d = one(MINIMAL).expect("a description");
    assert_eq!(d.kind, StatementKind::Select);
    assert_eq!(d.source, span(0, MINIMAL.len() - 1, 1, 1));
    assert!(d.parameters.is_empty());
    let columns = d.columns.expect("columns");
    let got: Vec<(&str, &SqlType, Nullability, &str)> = columns
        .iter()
        .map(|c| {
            (
                c.name.as_str(),
                &c.ty,
                c.nullability,
                &MINIMAL[c.source.start..c.source.end],
            )
        })
        .collect();
    assert_eq!(
        got,
        [
            ("ID", &SqlType::Integer, Nullability::NotNull, "1 AS id"),
            (
                "Name",
                &SqlType::Text,
                Nullability::NotNull,
                "'x' AS \"Name\""
            ),
            ("OK", &SqlType::Boolean, Nullability::NotNull, "TRUE AS ok"),
            (
                "NOTE",
                &SqlType::Unknown,
                Nullability::Nullable,
                "NULL AS note"
            ),
        ]
    );
    assert_eq!(columns[1].source, span(16, 29, 1, 17));
}

#[test]
fn the_largest_integer_of_the_stub_is_the_largest_i64() {
    let d = one("SELECT 9223372036854775807 AS big\n").expect("a description");
    let column = &d.columns.expect("columns")[0];
    assert_eq!(
        (column.name.as_str(), &column.ty),
        ("BIG", &SqlType::Integer)
    );
}

#[test]
fn each_statement_of_a_file_is_described_in_order() {
    let source = "SELECT 1 AS a;\n\nSELECT b AS c FROM t;\nSELECT 'q' AS \"x\"\"y\"\n";
    let all = describe(source, "ansi").expect("a clean parse");
    assert_eq!(all.len(), 3);
    let first = all[0].as_ref().expect("a description");
    assert_eq!(first.source, span(0, 13, 1, 1));
    assert_eq!(
        all[1],
        Err(DescribeError::Unsupported {
            reason: "a segment of the type from_clause".into(),
            source: span(30, 36, 3, 15),
        })
    );
    let third = all[2].as_ref().expect("a description");
    assert_eq!(third.source.line, 4);
    assert_eq!(third.columns.as_ref().unwrap()[0].name, "x\"y");
}

#[test]
fn the_source_ranges_come_from_the_source_map() {
    // The tag renders to no text: the templated statement starts at 0, its
    // source at 11.
    let source = "{{ empty }}SELECT 1 AS a\n";
    let all = describe_with(true, source, "ansi").expect("a clean parse");
    let d = all[0].as_ref().expect("a description");
    assert_eq!(d.source, span(11, 24, 1, 12));
    assert_eq!(d.columns.as_ref().unwrap()[0].source, span(18, 24, 1, 19));
}

#[test]
fn the_stub_fails_closed() {
    let cases: [(&str, &str, &str); 14] = [
        (
            "SELECT 1\n",
            "ansi",
            "a select element that is not a literal and an alias",
        ),
        (
            "SELECT 1.5 AS a\n",
            "ansi",
            "the literal 1.5 (numeric_literal)",
        ),
        (
            "SELECT 9223372036854775808 AS a\n",
            "ansi",
            "the integer 9223372036854775808 is not in the range of a 64-bit integer",
        ),
        (
            "SELECT 1 AS a, 2 AS b,\n",
            "ansi",
            "a comma at the end of the select clause",
        ),
        (
            "SELECT -1 AS a\n",
            "ansi",
            "a segment of the type numeric_literal",
        ),
        (
            "SELECT x AS a\n",
            "ansi",
            "a segment of the type column_reference",
        ),
        (
            "SELECT 1 + 1 AS a\n",
            "ansi",
            "a segment of the type expression",
        ),
        (
            "SELECT DISTINCT 1 AS a\n",
            "ansi",
            "a segment of the type select_clause_modifier",
        ),
        (
            "SELECT 1 AS a FROM t\n",
            "ansi",
            "a segment of the type from_clause",
        ),
        (
            "SELECT 1 AS a ORDER BY 1\n",
            "ansi",
            "a segment of the type orderby_clause",
        ),
        (
            "SELECT 1 AS a UNION SELECT 2 AS a\n",
            "ansi",
            "a segment of the type set_expression",
        ),
        (
            "INSERT INTO t VALUES (1)\n",
            "ansi",
            "a segment of the type insert_statement",
        ),
        ("SELECT 1 AS a\n", "postgres", "the dialect postgres"),
        ("SELECT 'x' AS a\n", "bigquery", "the dialect bigquery"),
    ];
    for (source, dialect, reason) in cases {
        let all = describe(source, dialect).expect("a clean parse");
        match &all[..] {
            [Err(DescribeError::Unsupported { reason: got, .. })] => {
                assert_eq!(got, reason, "{source:?}")
            }
            other => panic!("{source:?}: {other:?}"),
        }
    }
    // A value from a template tag.
    let all = describe_with(true, "SELECT {{ v }} AS a\n", "ansi").expect("a clean parse");
    match &all[..] {
        [Err(DescribeError::Unsupported { reason, source })] => {
            assert_eq!(reason, "a value from a template tag");
            assert_eq!((source.start, source.end), (7, 14));
        }
        other => panic!("{other:?}"),
    }
}

#[test]
fn a_parse_error_gives_no_description() {
    match describe("SELECT 1 AS a FROM\n", "ansi") {
        Err(DescribeError::Parse(e)) => assert!(e.message.contains("unparsable"), "{e}"),
        other => panic!("{other:?}"),
    }
    match describe("SELECT 1 AS a ~~~ ;\n", "ansi") {
        Err(DescribeError::Parse(_)) => {}
        other => panic!("{other:?}"),
    }
}

#[test]
fn the_statement_kind_is_the_type_of_the_statement_segment() {
    let cases = [
        ("SELECT 1", StatementKind::Select),
        ("SELECT 1 UNION SELECT 2", StatementKind::Select),
        (
            "WITH c AS (SELECT 1) SELECT * FROM c",
            StatementKind::Select,
        ),
        ("INSERT INTO t VALUES (1)", StatementKind::Insert),
        ("UPDATE t SET a = 1", StatementKind::Update),
        ("DELETE FROM t", StatementKind::Delete),
        (
            "MERGE INTO t USING s ON t.a = s.a WHEN MATCHED THEN DELETE",
            StatementKind::Merge,
        ),
        ("CREATE TABLE t (a INT)", StatementKind::Other),
    ];
    for (sql, kind) in cases {
        let sql = sql.to_string();
        let got = with_parse_stack(move || {
            let parsed = parse(&sqll_templater::RawTemplater, &sql, Dialect::Ansi);
            assert!(parsed.errors.is_empty(), "{sql:?}: {:?}", parsed.errors);
            let tree = parsed.tree.expect("a tree");
            let file: File<'_> = tree.root_node().cast().expect("a file");
            let kinds: Vec<StatementKind> = file.statements().map(StatementKind::of).collect();
            kinds
        });
        assert_eq!(got, [kind]);
    }
}

#[test]
fn each_param_style_is_a_sqlfluff_param_style() {
    // KNOWN_STYLES of the pinned sqlfluff placeholder templater.
    let text = std::fs::read_to_string(
        root().join("third_party/sqlfluff/src/sqlfluff/core/templaters/placeholder.py"),
    )
    .expect("placeholder.py");
    let block = text
        .split("KNOWN_STYLES = {")
        .nth(1)
        .and_then(|t| t.split("\n}\n").next())
        .expect("KNOWN_STYLES");
    let mut known: Vec<&str> = block
        .lines()
        .filter_map(|l| l.trim().strip_prefix('"'))
        .filter_map(|l| l.split_once("\":").map(|(name, _)| name))
        .collect();
    known.sort();
    let mut ours: Vec<&str> = ParamStyle::ALL.iter().map(|s| s.name()).collect();
    ours.sort();
    assert_eq!(ours, known);
    for style in ParamStyle::ALL {
        assert_eq!(ParamStyle::from_name(style.name()), Some(style));
    }
    assert_eq!(ParamStyle::from_name("named"), None);
}

#[test]
fn the_catalog_finds_tables_and_columns_by_exact_name() {
    let column = |name: &str| CatalogColumn {
        name: name.into(),
        ty: SqlType::Integer,
        nullability: Nullability::NotNull,
    };
    let catalog = Catalog {
        tables: vec![
            Table {
                schema: Some("a".into()),
                name: "t".into(),
                columns: vec![column("x")],
            },
            Table {
                schema: Some("b".into()),
                name: "t".into(),
                columns: vec![column("y")],
            },
        ],
    };
    assert_eq!(
        catalog.table(None, "t").unwrap().schema.as_deref(),
        Some("a")
    );
    assert_eq!(catalog.table(Some("b"), "t").unwrap().columns[0].name, "y");
    assert!(catalog.table(Some("c"), "t").is_none());
    assert!(catalog.table(None, "T").is_none());
    assert!(catalog.tables[0].column("x").is_some());
    assert!(catalog.tables[0].column("X").is_none());
}

// The writer.

fn parameter(name: Option<&str>, position: usize, style: ParamStyle, ty: SqlType) -> Parameter {
    Parameter {
        name: name.map(str::to_string),
        position,
        style,
        ty,
        nullability: Nullability::NotNull,
        sources: vec![span(
            27 + 3 * position,
            28 + 3 * position,
            1,
            28 + 3 * position,
        )],
    }
}

fn column(name: &str, ty: SqlType, nullability: Nullability, at: usize) -> Column {
    Column {
        name: name.into(),
        ty,
        nullability,
        source: span(at, at + 4, 1, at + 1),
    }
}

/// A hand-built description with named parameters (`:id` two times) and a
/// column of each type.
fn named() -> Description {
    let mut id = parameter(Some("id"), 1, ParamStyle::Colon, SqlType::Integer);
    id.sources.push(span(60, 63, 2, 5));
    let mut name = parameter(Some("name"), 2, ParamStyle::Colon, SqlType::Text);
    name.nullability = Nullability::Nullable;
    let types = [
        ("id", SqlType::Integer, Nullability::NotNull),
        ("ok", SqlType::Boolean, Nullability::Unknown),
        ("price", SqlType::Decimal, Nullability::NotNull),
        ("ratio", SqlType::Float, Nullability::Nullable),
        ("name", SqlType::Text, Nullability::NotNull),
        ("blob", SqlType::Bytes, Nullability::Nullable),
        ("day", SqlType::Date, Nullability::NotNull),
        ("at", SqlType::Time, Nullability::NotNull),
        ("at_tz", SqlType::TimeTz, Nullability::NotNull),
        ("local", SqlType::Timestamp, Nullability::NotNull),
        ("created", SqlType::TimestampTz, Nullability::Nullable),
        ("span", SqlType::Interval, Nullability::NotNull),
        ("uid", SqlType::Uuid, Nullability::NotNull),
        ("doc", SqlType::Json, Nullability::NotNull),
        (
            "tags",
            SqlType::Array(Box::new(SqlType::Text)),
            Nullability::NotNull,
        ),
        ("mood", SqlType::Named("mood".into()), Nullability::Nullable),
        ("other", SqlType::Unknown, Nullability::Unknown),
        ("Quote \"q\"", SqlType::Text, Nullability::NotNull),
    ];
    Description {
        kind: StatementKind::Select,
        source: span(0, 80, 1, 1),
        parameters: vec![id, name],
        columns: Some(
            types
                .into_iter()
                .enumerate()
                .map(|(i, (n, t, z))| column(n, t, z, 7 + 5 * i))
                .collect(),
        ),
    }
}

/// A hand-built description of an `INSERT` with `?` parameters: no rows.
fn question_mark() -> Description {
    let mut b = parameter(None, 2, ParamStyle::QuestionMark, SqlType::Text);
    b.nullability = Nullability::Unknown;
    Description {
        kind: StatementKind::Insert,
        source: span(0, 40, 1, 1),
        parameters: vec![
            parameter(None, 1, ParamStyle::QuestionMark, SqlType::Integer),
            b,
        ],
        columns: None,
    }
}

/// A hand-built description of an `UPDATE ... RETURNING` with `$1` and
/// `$2`.
fn numeric_dollar() -> Description {
    Description {
        kind: StatementKind::Update,
        source: span(0, 60, 1, 1),
        parameters: vec![
            parameter(Some("1"), 1, ParamStyle::NumericDollar, SqlType::Uuid),
            parameter(Some("2"), 2, ParamStyle::NumericDollar, SqlType::Date),
        ],
        columns: Some(vec![column(
            "n",
            SqlType::Integer,
            Nullability::NotNull,
            50,
        )]),
    }
}

/// A case of the record: a description, its schema file, and example
/// values that the schema must accept (`valid`) and refuse (`invalid`).
struct Case {
    name: &'static str,
    origin: &'static str,
    sql: Option<&'static str>,
    dialect: Option<&'static str>,
    description: Description,
    valid: Vec<Json>,
    invalid: Vec<Json>,
}

const UUID: &str = "1b4e28ba-2fa1-11d2-883f-0016d3cca427";

fn named_row() -> Json {
    json!({
        "id": 1, "ok": null, "price": "12.50", "ratio": null, "name": "a",
        "blob": "AAE=", "day": "2026-11-09", "at": "10:00:00",
        "at_tz": "10:00:00+02:00",
        "local": "2026-11-09 10:00:00", "created": "2026-11-09T10:00:00Z",
        "span": "1 day", "uid": UUID,
        "doc": {"k": [1, null]}, "tags": ["a", null], "mood": "happy",
        "other": 3, "Quote \"q\"": "",
    })
}

fn with(mut value: Json, key: &str, item: Json) -> Json {
    value[key] = item;
    value
}

fn without(mut value: Json, key: &str) -> Json {
    value.as_object_mut().unwrap().remove(key);
    value
}

fn cases() -> Vec<Case> {
    let minimal = one(MINIMAL).expect("a description");
    let row = json!({"ID": 1, "Name": "x", "OK": true, "NOTE": null});
    let named_params = json!({"id": 7, "name": null});
    let full = json!({"parameters": named_params, "row": named_row()});
    vec![
        Case {
            name: "minimal",
            origin:
                "sqll_codegen::LiteralSelect (raw templater, sqll_syntax::parse, describe_file)",
            sql: Some(MINIMAL),
            dialect: Some("ansi"),
            description: minimal,
            valid: vec![
                json!({"parameters": {}, "row": row}),
                json!({"parameters": {}, "row": with(row.clone(), "NOTE", json!("any"))}),
            ],
            invalid: vec![
                json!({"parameters": {}, "row": with(row.clone(), "ID", json!("1"))}),
                json!({"parameters": {}, "row": with(row.clone(), "ID", json!(1.5))}),
                json!({"parameters": {}, "row": with(row.clone(), "OK", json!(null))}),
                json!({"parameters": {}, "row": without(row.clone(), "Name")}),
                json!({"parameters": {}, "row": with(row.clone(), "name", json!("x"))}),
                json!({"parameters": {"a": 1}, "row": row}),
                json!({"row": row}),
            ],
        },
        Case {
            name: "named",
            origin: "hand-built description (writer test)",
            sql: None,
            dialect: None,
            description: named(),
            valid: vec![
                full.clone(),
                with(full.clone(), "parameters", json!({"id": 7, "name": "n"})),
                with(
                    full.clone(),
                    "row",
                    with(named_row(), "at_tz", json!("10:00:00Z")),
                ),
            ],
            invalid: vec![
                with(full.clone(), "parameters", json!({"id": null, "name": "n"})),
                with(full.clone(), "parameters", json!({"id": 7})),
                with(full.clone(), "parameters", json!([7, "n"])),
                with(full.clone(), "row", with(named_row(), "price", json!(12.5))),
                with(full.clone(), "row", with(named_row(), "doc", json!(null))),
                with(full.clone(), "row", with(named_row(), "tags", json!("a"))),
                with(full.clone(), "row", with(named_row(), "tags", json!([1]))),
                with(full.clone(), "row", with(named_row(), "blob", json!(1))),
                // Each of these fails only by its format.
                with(
                    full.clone(),
                    "row",
                    with(named_row(), "day", json!("09.11.2026")),
                ),
                with(
                    full.clone(),
                    "row",
                    with(named_row(), "at_tz", json!("10:00:00")),
                ),
                with(
                    full.clone(),
                    "row",
                    with(named_row(), "created", json!("2026-11-09T10:00:00")),
                ),
                with(
                    full.clone(),
                    "row",
                    with(named_row(), "uid", json!("1b4e28ba")),
                ),
                with(full, "extra", json!(1)),
            ],
        },
        Case {
            name: "question_mark",
            origin: "hand-built description (writer test)",
            sql: None,
            dialect: None,
            description: question_mark(),
            valid: vec![
                json!({"parameters": [1, "x"]}),
                json!({"parameters": [1, null]}),
            ],
            invalid: vec![
                json!({"parameters": [1]}),
                json!({"parameters": [1, "x", 3]}),
                json!({"parameters": [null, "x"]}),
                json!({"parameters": {"1": 1, "2": "x"}}),
                json!({"parameters": [1, "x"], "row": {}}),
            ],
        },
        Case {
            name: "numeric_dollar",
            origin: "hand-built description (writer test)",
            sql: None,
            dialect: None,
            description: numeric_dollar(),
            valid: vec![json!({
                "parameters": [UUID, "2026-11-09"],
                "row": {"n": 3}
            })],
            invalid: vec![
                json!({"parameters": [UUID, "2026-11-09"]}),
                json!({"parameters": [UUID, "2026-11-09"], "row": {"n": "3"}}),
                // Each of these fails only by its format.
                json!({"parameters": ["u", "2026-11-09"], "row": {"n": 3}}),
                json!({"parameters": [UUID, "d"], "row": {"n": 3}}),
            ],
        },
    ]
}

/// The record files: (path under results/S3b/, text).
fn record_files() -> Vec<(String, String)> {
    let mut files = Vec::new();
    let mut manifest = Vec::new();
    for case in cases() {
        let file = format!("C15-schema/{}.json", case.name);
        let schema = write_json_schema(&case.description, case.name).expect("a schema");
        files.push((file.clone(), schema));
        manifest.push(json!({
            "name": case.name,
            "origin": case.origin,
            "sql": case.sql,
            "dialect": case.dialect,
            "schema": file,
            "valid": case.valid,
            "invalid": case.invalid,
        }));
    }
    let record = json!({
        "kind": RECORD_KIND,
        "command": WRITE_COMMAND,
        "meta_schema": DRAFT_2020_12,
        "cases": manifest,
    });
    let mut text = serde_json::to_string_pretty(&record).expect("JSON");
    text.push('\n');
    files.push(("C15-schema.json".into(), text));
    files
}

#[test]
fn the_record_is_the_output_of_the_writer() {
    let folder = root().join("results/S3b");
    let files = record_files();
    for (path, text) in &files {
        let recorded = std::fs::read_to_string(folder.join(path))
            .unwrap_or_else(|e| panic!("{path}: {e}; run: {WRITE_COMMAND}"));
        assert!(
            recorded == *text,
            "{path} is not the writer output; run: {WRITE_COMMAND}"
        );
    }
    let mut on_disk: Vec<String> = std::fs::read_dir(root().join(RECORD_DIR))
        .expect("the record folder")
        .map(|e| format!("C15-schema/{}", e.unwrap().file_name().to_string_lossy()))
        .collect();
    on_disk.sort();
    let mut ours: Vec<String> = files.iter().map(|(p, _)| p.clone()).collect();
    ours.retain(|p| p.starts_with("C15-schema/"));
    ours.sort();
    assert_eq!(on_disk, ours, "the files of {RECORD_DIR}");
    assert!(root().join(RECORD).is_file());
}

/// Write the record files to the folder of OUT_ENV
/// (scripts/s3b/schema_check.py runs it).
#[test]
#[ignore]
fn write_the_record() {
    let out = PathBuf::from(std::env::var_os(OUT_ENV).expect("SQLL_SCHEMA_OUT"));
    for (path, text) in record_files() {
        let path = out.join(path);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, text).unwrap();
    }
    println!("schema: wrote the record to {}", out.display());
}

#[test]
fn the_minimal_schema_has_the_columns_in_order() {
    let schema = write_json_schema(&one(MINIMAL).unwrap(), "minimal").unwrap();
    let value: Json = serde_json::from_str(&schema).expect("JSON");
    assert_eq!(value["$schema"], DRAFT_2020_12);
    assert_eq!(
        value["$defs"]["row"]["required"],
        json!(["ID", "Name", "OK", "NOTE"])
    );
    let at = |key: &str| schema.find(&format!("\"{key}\": {{")).unwrap();
    assert!(at("ID") < at("Name") && at("Name") < at("OK") && at("OK") < at("NOTE"));
    assert_eq!(value["$defs"]["row"]["properties"]["ID"]["type"], "integer");
    assert_eq!(
        value["$defs"]["row"]["properties"]["NOTE"]["x-sqll-type"],
        "unknown"
    );
    assert!(value["$defs"]["row"]["properties"]["NOTE"]
        .get("type")
        .is_none());
    assert_eq!(
        value["$defs"]["row"]["properties"]["Name"]["x-sqll-source"],
        json!({"start": 16, "end": 29, "line": 1, "pos": 17})
    );
}

#[test]
fn the_writer_refuses_a_description_that_it_cannot_write() {
    let write = |d: &Description| write_json_schema(d, "t");
    let mut d = named();
    d.columns.as_mut().unwrap()[1].name = "id".into();
    assert_eq!(write(&d), Err(SchemaError::DuplicateColumn("id".into())));
    d.columns.as_mut().unwrap()[1].name = String::new();
    assert_eq!(write(&d), Err(SchemaError::EmptyColumnName));

    let mut d = named();
    d.parameters[1].style = ParamStyle::Pyformat;
    assert_eq!(write(&d), Err(SchemaError::MixedStyles));
    let mut d = named();
    d.parameters.swap(0, 1);
    assert_eq!(write(&d), Err(SchemaError::Positions));
    let mut d = named();
    d.parameters[1].position = 3;
    assert_eq!(write(&d), Err(SchemaError::Positions));
    let mut d = named();
    d.parameters[1].name = Some("id".into());
    assert_eq!(write(&d), Err(SchemaError::DuplicateParameter("id".into())));
    let mut d = named();
    d.parameters[1].name = None;
    assert_eq!(write(&d), Err(SchemaError::ParameterName { position: 2 }));
    let mut d = named();
    d.parameters[1].name = Some(String::new());
    assert_eq!(write(&d), Err(SchemaError::ParameterName { position: 2 }));
    let mut d = named();
    d.parameters[0].sources.clear();
    assert_eq!(
        write(&d),
        Err(SchemaError::NoParameterSource { position: 1 })
    );

    let mut d = question_mark();
    d.parameters[0].name = Some("1".into());
    assert_eq!(write(&d), Err(SchemaError::ParameterName { position: 1 }));
    let mut d = numeric_dollar();
    d.parameters[1].name = Some("1".into());
    assert_eq!(write(&d), Err(SchemaError::ParameterName { position: 2 }));

    // The stub describes two columns with one name; the writer refuses it.
    let d = one("SELECT 1 AS a, 2 AS A\n").expect("a description");
    assert_eq!(write(&d), Err(SchemaError::DuplicateColumn("A".into())));
}
