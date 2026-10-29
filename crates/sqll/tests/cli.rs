//! Tests of the sqll command line: the parse record of fixture files, the
//! exit codes, and the commands that sqll does not support yet.
//!
//! The fixture files are the sqlfluff 4.4.0 dialect fixtures of the
//! submodule (third_party/sqlfluff), read in place.

use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};

use serde_yaml_ng::Value;

const SQLL: &str = env!("CARGO_BIN_EXE_sqll");

fn dialects_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../third_party/sqlfluff/test/fixtures/dialects")
}

fn sqll(args: &[&str]) -> Output {
    Command::new(SQLL).args(args).output().expect("run sqll")
}

fn sqll_stdin(args: &[&str], input: &str) -> Output {
    use std::io::Write;
    let mut child = Command::new(SQLL)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("run sqll");
    child
        .stdin
        .take()
        .unwrap()
        .write_all(input.as_bytes())
        .unwrap();
    child.wait_with_output().expect("wait for sqll")
}

fn code(out: &Output) -> i32 {
    out.status.code().expect("an exit code")
}

fn stderr(out: &Output) -> String {
    String::from_utf8_lossy(&out.stderr).into_owned()
}

/// The check tuple of sqlfluff test/conftest.py (process_struct): a mapping
/// is a list of (key, value) pairs, a list of 1-key mappings is the list of
/// their pairs, a scalar is its text.
#[derive(Debug, PartialEq)]
enum Struct {
    Null,
    Text(String),
    Pairs(Vec<(String, Struct)>),
}

fn scalar(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        Value::Bool(b) => if *b { "True" } else { "False" }.to_string(),
        other => panic!("not a scalar: {other:?}"),
    }
}

fn process_struct(value: &Value) -> Struct {
    match value {
        Value::Null => Struct::Null,
        Value::Mapping(map) => Struct::Pairs(
            map.iter()
                .map(|(k, v)| (scalar(k), process_struct(v)))
                .collect(),
        ),
        Value::Sequence(items) => Struct::Pairs(
            items
                .iter()
                .map(|item| match process_struct(item) {
                    Struct::Pairs(mut pairs) if pairs.len() == 1 => pairs.remove(0),
                    other => panic!("not a 1-key mapping: {other:?}"),
                })
                .collect(),
        ),
        other => Struct::Text(scalar(other)),
    }
}

/// The root (name, children) of the fixture YAML, without its _hash.
fn fixture_tree(yml: &Path) -> (String, Struct) {
    let text = std::fs::read_to_string(yml).expect("read the fixture YAML");
    let mut value: Value = serde_yaml_ng::from_str(&text).expect("YAML");
    value.as_mapping_mut().unwrap().remove("_hash");
    root(process_struct(&value))
}

fn root(s: Struct) -> (String, Struct) {
    match s {
        Struct::Pairs(mut pairs) if !pairs.is_empty() => pairs.remove(0),
        other => panic!("no root segment: {other:?}"),
    }
}

/// The "segments" value of the parse output. JSON is YAML, and the YAML
/// mapping keeps the key order.
fn segments(out: &Output) -> Value {
    let text = String::from_utf8(out.stdout.clone()).expect("UTF-8 output");
    let value: Value = serde_yaml_ng::from_str(&text).expect("JSON output");
    let records = value.as_sequence().expect("a list of records");
    assert_eq!(records.len(), 1);
    records[0]["segments"].clone()
}

/// The raw text of each leaf of a full record, in order.
fn raws(value: &Value, out: &mut String) {
    match value {
        Value::Mapping(map) => {
            for (_, v) in map {
                match v {
                    Value::String(s) => out.push_str(s),
                    other => raws(other, out),
                }
            }
        }
        Value::Sequence(items) => items.iter().for_each(|i| raws(i, out)),
        _ => {}
    }
}

/// Dialect fixtures, with the max_parse_depth of the sqlfluff test
/// (DEEP_PARSE_DEPTH_OVERRIDES in test/conftest.py).
const FIXTURES: &[(&str, &str, Option<&str>)] = &[
    ("ansi", "expression_recursion", Some("2000")),
    ("postgres", "create_table", None),
    ("tsql", "create_table", None),
];

#[test]
fn the_code_only_record_of_3_fixture_files_is_the_fixture_tree() {
    for (dialect, stem, depth) in FIXTURES {
        let sql = dialects_dir().join(dialect).join(format!("{stem}.sql"));
        let mut args = vec!["parse", "-f", "json", "--dialect", dialect, "-c"];
        if let Some(depth) = depth {
            args.extend(["--max-parse-depth", depth]);
        }
        args.push(sql.to_str().unwrap());
        let out = sqll(&args);
        assert_eq!(code(&out), 0, "{stem}: {}", stderr(&out));
        let want = fixture_tree(&sql.with_extension("yml"));
        let got = root(process_struct(&segments(&out)));
        assert_eq!(got.0, "file");
        assert_eq!(got, want, "{dialect}/{stem}");
    }
}

#[test]
fn the_full_record_has_each_byte_of_the_file() {
    for (dialect, stem, depth) in FIXTURES {
        let sql = dialects_dir().join(dialect).join(format!("{stem}.sql"));
        let mut args = vec!["parse", "--dialect", dialect];
        if let Some(depth) = depth {
            args.extend(["--max-parse-depth", depth]);
        }
        args.push(sql.to_str().unwrap());
        let out = sqll(&args);
        assert_eq!(code(&out), 0, "{stem}: {}", stderr(&out));
        let mut text = String::new();
        raws(&segments(&out), &mut text);
        assert_eq!(
            text,
            std::fs::read_to_string(&sql).unwrap(),
            "{dialect}/{stem}"
        );
    }
}

#[test]
fn the_output_is_that_of_python_json_dumps() {
    let out = sqll_stdin(
        &["parse", "--dialect", "ansi", "-c", "-"],
        "select '\u{e9}'\n",
    );
    assert_eq!(code(&out), 0, "{}", stderr(&out));
    let want = concat!(
        r#"[{"filepath": "stdin", "segments": {"file": {"statement": "#,
        r#"{"select_statement": {"select_clause": {"keyword": "select", "#,
        r#""select_clause_element": {"quoted_literal": "'\u00e9'"}}}}}}}]"#,
        "\n"
    );
    assert_eq!(String::from_utf8(out.stdout).unwrap(), want);
}

#[test]
fn exit_code_0_for_a_tree_with_no_error() {
    let out = sqll_stdin(&["parse", "--dialect", "ansi", "-"], "select a from b;\n");
    assert_eq!(code(&out), 0);
    assert!(out.stderr.is_empty());
}

#[test]
fn exit_code_1_for_an_unparsable_segment() {
    let out = sqll_stdin(
        &["parse", "--dialect", "ansi", "-"],
        "select 1 from t where ~~~ x\n",
    );
    assert_eq!(code(&out), 1);
    let mut found = false;
    fn find(v: &Value, found: &mut bool) {
        match v {
            Value::Mapping(m) => m.iter().for_each(|(k, v)| {
                *found |= k.as_str() == Some("unparsable");
                find(v, found)
            }),
            Value::Sequence(s) => s.iter().for_each(|v| find(v, found)),
            _ => {}
        }
    }
    find(&segments(&out), &mut found);
    assert!(found);
}

#[test]
fn exit_code_1_for_a_lex_error() {
    let out = sqll_stdin(&["parse", "--dialect", "ansi", "-"], "select 'abc\n");
    assert_eq!(code(&out), 1);
    assert!(stderr(&out).starts_with("LXR L1 P8: "), "{}", stderr(&out));
    assert!(!segments(&out).is_null());
}

#[test]
fn exit_code_1_and_no_tree_for_a_parse_error() {
    let out = sqll_stdin(
        &["parse", "--dialect", "ansi", "--max-parse-depth", "5", "-"],
        "select (((1)))\n",
    );
    assert_eq!(code(&out), 1);
    assert!(stderr(&out).contains("PRS: Maximum parse depth exceeded"));
    assert!(segments(&out).is_null());
}

#[test]
fn exit_code_2_for_a_usage_or_input_error() {
    let file = dialects_dir().join("ansi/select_simple_a.sql");
    let file = file.to_str().unwrap();
    let cases: &[(&[&str], &str)] = &[
        (&["parse", file], "No dialect was specified"),
        (
            &["parse", "--dialect", "nope", file],
            "Error loading dialect 'nope'",
        ),
        (&["parse", "--dialect", "ansi"], "Missing argument 'PATH'"),
        (
            &["parse", "--dialect", "ansi", "/no/such/file.sql"],
            "cannot read",
        ),
        (
            &["parse", "--dialect", "ansi", "--bad", file],
            "No such option: --bad",
        ),
        (
            &["parse", "--dialect", "ansi", file, file],
            "unexpected extra argument",
        ),
        (
            &["parse", "--dialect", "ansi", "--max-parse-depth", "x", file],
            "not a valid integer",
        ),
        (&["parse", "--dialect"], "requires an argument"),
        (
            &["parse", "--dialect", "ansi", "-f", "yaml", file],
            "unsupported: format yaml",
        ),
        (&["nope"], "No such command 'nope'"),
        (&["version", "--bad"], "Usage: sqll version"),
    ];
    for (args, message) in cases {
        let out = sqll(args);
        assert_eq!(code(&out), 2, "{args:?}");
        assert!(out.stdout.is_empty(), "{args:?}");
        assert!(stderr(&out).contains(message), "{args:?}: {}", stderr(&out));
    }
    let out = sqll(&["parse", "--dialect=ansi", "--max-parse-depth=0", file]);
    assert_eq!(code(&out), 0, "{}", stderr(&out));
}

#[test]
fn lint_and_fix_are_not_supported_yet() {
    for command in ["lint", "fix"] {
        let out = sqll(&[command, "--dialect", "ansi", "x.sql"]);
        assert_eq!(code(&out), 2);
        assert!(out.stdout.is_empty());
        assert_eq!(
            stderr(&out),
            format!("Error: unsupported: {command}. sqll has no rules until stone S5.\n")
        );
    }
}

#[test]
fn the_version_is_the_crate_version_and_the_table_manifest_hash() {
    let out = sqll(&["--version"]);
    assert_eq!(code(&out), 0);
    let text = String::from_utf8(out.stdout).unwrap();
    let version = text
        .trim()
        .strip_prefix("sqll, version ")
        .expect("the prefix");
    let (crate_version, tables) = version.split_once("+tables.").expect("+tables.");
    assert_eq!(crate_version, env!("CARGO_PKG_VERSION"));
    assert_eq!(tables.len(), 64);
    let out = sqll(&["version"]);
    assert_eq!(String::from_utf8(out.stdout).unwrap().trim(), version);

    let out = sqll(&["version", "--build"]);
    assert_eq!(code(&out), 0);
    let record: Value = serde_yaml_ng::from_slice(&out.stdout).expect("JSON");
    assert_eq!(record["version"].as_str(), Some(version));
    assert_eq!(record["tables_sha256"].as_str(), Some(tables));
    assert_eq!(record["source_sha256"].as_str().map(str::len), Some(64));
    assert!(record["source_files"].as_u64().unwrap() > 0);
}
