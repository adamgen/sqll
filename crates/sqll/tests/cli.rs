// Parts of this file are a port of sqlfluff 4.4.0 code: process_struct of
// test/conftest.py (the check tuple of a parse tree, and the text of a
// scalar).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

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
fn short_options_can_be_in_a_group() {
    let file = dialects_dir().join("ansi/select_simple_a.sql");
    let file = file.to_str().unwrap();
    let apart = sqll(&["parse", "--dialect", "ansi", "-c", "-m", "-f", "json", file]);
    assert_eq!(code(&apart), 0, "{}", stderr(&apart));
    for group in [&["-cm"][..], &["-mc"], &["-cmfjson"], &["-cmf", "json"]] {
        let mut args = vec!["parse", "--dialect", "ansi"];
        args.extend(group);
        args.push(file);
        let out = sqll(&args);
        assert_eq!(code(&out), 0, "{group:?}: {}", stderr(&out));
        assert_eq!(out.stdout, apart.stdout, "{group:?}");
    }
    let cases: &[(&[&str], &str)] = &[
        (&["-cx"], "No such option: -x"),
        (&["-cf"], "Option '-f' requires an argument"),
        (&["-cfyaml"], "unsupported: format yaml"),
    ];
    for (group, message) in cases {
        let mut args = vec!["parse", "--dialect", "ansi", file];
        args.extend(*group);
        let out = sqll(&args);
        assert_eq!(code(&out), 2, "{group:?}");
        assert!(
            stderr(&out).contains(message),
            "{group:?}: {}",
            stderr(&out)
        );
    }
}

/// As click: all arguments are read first, so an unknown option or a missing
/// value is an error also with "-h". Then the help has priority over each
/// check of a value.
#[test]
fn the_help_comes_after_all_arguments_are_read() {
    let file = dialects_dir().join("ansi/select_simple_a.sql");
    let file = file.to_str().unwrap();
    let errors: &[(&[&str], &str)] = &[
        (&["-hx"], "No such option: -x"),
        (&["-h", "--bad"], "No such option: --bad"),
        (&["--bad", "-h"], "No such option: --bad"),
        (
            &["-h", "--dialect"],
            "Option '--dialect' requires an argument",
        ),
        (&["-hf"], "Option '-f' requires an argument"),
        (&["-fh"], "unsupported: format h"),
    ];
    for (group, message) in errors {
        let mut args = vec!["parse", "--dialect", "ansi"];
        args.extend(*group);
        let out = sqll(&args);
        assert_eq!(code(&out), 2, "{group:?}");
        assert!(out.stdout.is_empty(), "{group:?}");
        assert!(
            stderr(&out).contains(message),
            "{group:?}: {}",
            stderr(&out)
        );
    }
    let helps: &[&[&str]] = &[
        &["-h"],
        &["-ch"],
        &["--help", "-f", "yaml"],
        &["-f", "yaml", "--help"],
        &["--max-parse-depth", "x", "-h"],
        &["--help", file, file],
    ];
    for group in helps {
        let mut args = vec!["parse", "--dialect", "ansi"];
        args.extend(*group);
        let out = sqll(&args);
        assert_eq!(code(&out), 0, "{group:?}: {}", stderr(&out));
        let text = String::from_utf8(out.stdout).unwrap();
        assert!(text.starts_with("Usage: sqll parse"), "{group:?}: {text}");
    }
}

#[test]
fn a_flag_does_not_take_a_value() {
    let file = dialects_dir().join("ansi/select_simple_a.sql");
    let file = file.to_str().unwrap();
    for flag in ["--code-only", "--include-meta", "--help"] {
        let option = format!("{flag}=1");
        let out = sqll(&["parse", "--dialect", "ansi", &option, file]);
        assert_eq!(code(&out), 2, "{flag}");
        assert!(out.stdout.is_empty(), "{flag}");
        assert!(
            stderr(&out).contains(&format!("Option '{flag}' does not take a value.")),
            "{flag}: {}",
            stderr(&out)
        );
    }
}

fn filepath(out: &Output) -> String {
    let text = String::from_utf8(out.stdout.clone()).expect("UTF-8 output");
    let value: Value = serde_yaml_ng::from_str(&text).expect("JSON output");
    value[0]["filepath"]
        .as_str()
        .expect("a filepath")
        .to_string()
}

/// A new empty folder for the files of one test.
fn scratch(name: &str) -> PathBuf {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join(name);
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("sub")).unwrap();
    dir
}

#[test]
fn the_filepath_is_the_normalized_path_as_sqlfluff_gives_it() {
    let dir = scratch("filepath");
    std::fs::write(dir.join("d.sql"), "select 1\n").unwrap();
    let cases = [
        ("d.sql", "d.sql"),
        ("./d.sql", "d.sql"),
        (".//d.sql", "d.sql"),
        ("sub/../d.sql", "d.sql"),
        ("sub/./../d.sql", "d.sql"),
    ];
    for (path, want) in cases {
        let out = Command::new(SQLL)
            .args(["parse", "--dialect", "ansi", path])
            .current_dir(&dir)
            .output()
            .unwrap();
        assert_eq!(code(&out), 0, "{path}: {}", stderr(&out));
        assert_eq!(filepath(&out), want, "{path}");
    }
    let absolute = format!("{}/sub/../d.sql", dir.display());
    let out = sqll(&["parse", "--dialect", "ansi", &absolute]);
    assert_eq!(filepath(&out), format!("{}/d.sql", dir.display()));
}

#[test]
fn a_file_with_no_sql_extension_gives_an_empty_list() {
    let dir = scratch("extension");
    // Not UTF-8: sqll must not read the file.
    std::fs::write(dir.join("d.txt"), b"\xff\xfe").unwrap();
    std::fs::write(dir.join("d.DDL"), "select 1\n").unwrap();
    std::fs::write(dir.join("d.pkb"), "select 1\n").unwrap();
    let out = sqll(&[
        "parse",
        "--dialect",
        "ansi",
        dir.join("d.txt").to_str().unwrap(),
    ]);
    assert_eq!(code(&out), 0, "{}", stderr(&out));
    assert_eq!(out.stdout, b"[]\n");
    let out = sqll(&[
        "parse",
        "--dialect",
        "ansi",
        dir.join("d.DDL").to_str().unwrap(),
    ]);
    assert_eq!(code(&out), 0, "{}", stderr(&out));
    assert!(filepath(&out).ends_with("/d.DDL"));
    let out = sqll(&[
        "parse",
        "--dialect",
        "ansi",
        dir.join("d.pkb").to_str().unwrap(),
    ]);
    assert_eq!(code(&out), 0, "{}", stderr(&out));
    assert!(filepath(&out).ends_with("/d.pkb"));
    let out = sqll(&[
        "parse",
        "--dialect",
        "ansi",
        dir.join("sub").to_str().unwrap(),
    ]);
    assert_eq!(code(&out), 2);
    assert!(
        stderr(&out).contains("unsupported: folder"),
        "{}",
        stderr(&out)
    );
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

#[test]
fn an_argument_that_is_not_utf8_gives_exit_code_2() {
    use std::ffi::OsStr;
    use std::os::unix::ffi::OsStrExt;
    let file = OsStr::from_bytes(b"\xff.sql");
    let dialect = OsStr::from_bytes(b"\xff");
    let cases: [Vec<&OsStr>; 3] = [
        vec![
            "parse".as_ref(),
            "--dialect".as_ref(),
            "ansi".as_ref(),
            file,
        ],
        vec!["parse".as_ref(), "--dialect".as_ref(), dialect, file],
        vec![file],
    ];
    for args in cases {
        let out = Command::new(SQLL).args(&args).output().expect("run sqll");
        assert_eq!(code(&out), 2, "{args:?}");
        assert!(out.stdout.is_empty(), "{args:?}");
        assert!(
            stderr(&out).starts_with("Error: unsupported: non-UTF-8 argument \""),
            "{args:?}: {}",
            stderr(&out)
        );
    }
}

/// The JSON readers of the tests stop at 128 levels, so a deep tree is
/// checked by its start.
fn stdout_starts(out: &Output, prefix: &str) -> bool {
    out.stdout.starts_with(prefix.as_bytes())
}

/// "select" and n nested function calls around 1: "select f(f(1))".
fn nested_calls(n: usize) -> String {
    format!("select {}1{}\n", "f(".repeat(n), ")".repeat(n))
}

/// 474 nested calls need a parse depth of 9986: the deepest nesting that
/// the parse depth limit (10000) lets through. Of the nested forms that were
/// measured (brackets, subqueries, function calls, CASE, bracketed
/// additions, arrays, bracketed joins), it needs the most stack. The parse
/// must give a tree or a parse error, not a stack overflow, for each
/// --max-parse-depth value.
#[test]
fn the_parse_depth_has_a_limit_that_the_stack_can_hold() {
    let deepest = nested_calls(474);
    for depth in ["0", "10000", "100000"] {
        let out = sqll_stdin(
            &[
                "parse",
                "--dialect",
                "ansi",
                "--max-parse-depth",
                depth,
                "-",
            ],
            &deepest,
        );
        assert_eq!(code(&out), 0, "{depth}: {}", stderr(&out));
        assert!(stdout_starts(
            &out,
            r#"[{"filepath": "stdin", "segments": {"file": "#
        ));
    }
    let deeper = nested_calls(475);
    for depth in ["0", "100000"] {
        let out = sqll_stdin(
            &[
                "parse",
                "--dialect",
                "ansi",
                "--max-parse-depth",
                depth,
                "-",
            ],
            &deeper,
        );
        assert_eq!(code(&out), 1, "{depth}: {}", stderr(&out));
        assert!(
            stderr(&out).starts_with("PRS: Maximum parse depth exceeded (limit 10000)."),
            "{depth}: {}",
            stderr(&out)
        );
        assert_eq!(
            out.stdout,
            b"[{\"filepath\": \"stdin\", \"segments\": null}]\n"
        );
    }
    let out = sqll_stdin(
        &[
            "parse",
            "--dialect",
            "ansi",
            "--max-parse-depth",
            "9985",
            "-",
        ],
        &deepest,
    );
    assert_eq!(code(&out), 1, "{}", stderr(&out));
    assert!(stderr(&out).contains("(limit 9985)"), "{}", stderr(&out));
}

/// "select" and n nested brackets around 1.
fn nested_brackets(n: usize) -> String {
    format!("select {}1{}\n", "(".repeat(n), ")".repeat(n))
}

/// sqll counts the parse depth in frames of the Rust parser. sqlfluff 4.4.0
/// (Python parser) stops first at 35 brackets with the depth 600, sqll at 40
/// (harness/sqll.md).
#[test]
fn the_parse_depth_is_that_of_the_rust_parser() {
    let args = [
        "parse",
        "--dialect",
        "ansi",
        "--max-parse-depth",
        "600",
        "-",
    ];
    let out = sqll_stdin(&args, &nested_brackets(39));
    assert_eq!(code(&out), 0, "{}", stderr(&out));
    assert!(stdout_starts(
        &out,
        r#"[{"filepath": "stdin", "segments": {"file": "#
    ));
    let out = sqll_stdin(&args, &nested_brackets(40));
    assert_eq!(code(&out), 1, "{}", stderr(&out));
    assert!(
        stderr(&out).starts_with("PRS: Maximum parse depth exceeded (limit 600)."),
        "{}",
        stderr(&out)
    );
    assert_eq!(
        out.stdout,
        b"[{\"filepath\": \"stdin\", \"segments\": null}]\n"
    );
}

/// "select 1 from" and n nested bracketed joins: "(t join (t join u on true)
/// on true)". The parser matches each level in a probe sub-parse.
fn nested_joins(n: usize) -> String {
    format!(
        "select 1 from {}u{}\n",
        "(t join ".repeat(n),
        " on true)".repeat(n)
    )
}

fn assert_depth_limit(out: &Output, limit: &str) {
    assert_eq!(code(out), 1, "{}", stderr(out));
    assert!(
        stderr(out).starts_with(&format!(
            "PRS: Maximum parse depth exceeded (limit {limit})."
        )),
        "{}",
        stderr(out)
    );
    assert_eq!(
        out.stdout,
        b"[{\"filepath\": \"stdin\", \"segments\": null}]\n"
    );
}

/// A probe sub-parse starts at the parse depth of its caller. sqlfluff
/// 4.4.0 (Python parser) stops first at 37 joins with the depth 600, sqll at
/// 47 (harness/sqll.md).
#[test]
fn the_parse_depth_counts_the_frames_of_probes() {
    let args = ["parse", "--dialect", "ansi", "-"];
    let out = sqll_stdin(&args, &nested_joins(46));
    assert_eq!(code(&out), 0, "{}", stderr(&out));
    assert!(stdout_starts(
        &out,
        r#"[{"filepath": "stdin", "segments": {"file": "#
    ));
    assert_depth_limit(&sqll_stdin(&args, &nested_joins(47)), "600");
}

/// 36000 nested joins (612 KB) overflowed the stack of a release build when
/// the depth of each probe started at 0. Now they stop at the depth limit.
#[test]
fn deep_nesting_through_probes_stops_at_the_depth_limit() {
    let sql = nested_joins(36000);
    let out = sqll_stdin(&["parse", "--dialect", "ansi", "-"], &sql);
    assert_depth_limit(&out, "600");
    let out = sqll_stdin(
        &["parse", "--dialect", "ansi", "--max-parse-depth", "0", "-"],
        &sql,
    );
    assert_depth_limit(&out, "10000");
    let out = sqll_stdin(
        &["parse", "--dialect", "ansi", "--max-parse-depth", "0", "-"],
        &nested_joins(829),
    );
    assert_eq!(code(&out), 0, "{}", stderr(&out));
    assert!(stdout_starts(
        &out,
        r#"[{"filepath": "stdin", "segments": {"file": "#
    ));
    let out = sqll_stdin(
        &["parse", "--dialect", "ansi", "--max-parse-depth", "0", "-"],
        &nested_joins(830),
    );
    assert_depth_limit(&out, "10000");
}

/// "select a=a=a...": n comparisons. sqlfluff 4.4.0 (Python parser) gives a
/// tree for each n. The Rust parser stops above rust_parser_max_iterations
/// (3000000): first at n = 7853 (15715 bytes), in the main parse.
fn comparisons(n: usize) -> String {
    format!("select a{}\n", "=a".repeat(n))
}

/// "... order by a=a=a...": the limit is first at n = 7854 (15735 bytes), in
/// a probe for a terminator. A probe drops its error, but the parse must stop.
fn order_by_comparisons(n: usize) -> String {
    format!("select a from t order by a{}\n", "=a".repeat(n))
}

fn assert_iteration_limit(sql: &str, limit: bool) {
    let out = sqll_stdin(&["parse", "--dialect", "ansi", "-"], sql);
    if !limit {
        assert_eq!(code(&out), 0, "{}", stderr(&out));
        assert!(stdout_starts(
            &out,
            r#"[{"filepath": "stdin", "segments": {"file": "#
        ));
        return;
    }
    assert_eq!(code(&out), 1, "{}", stderr(&out));
    assert_eq!(
        stderr(&out),
        "PRS: Parser exceeded maximum iteration limit (3000000). This may be \
         caused by runaway parser logic or a very complex SQL query.\n"
    );
    assert_eq!(
        out.stdout,
        b"[{\"filepath\": \"stdin\", \"segments\": null}]\n"
    );
}

#[test]
fn the_parser_iteration_limit_gives_a_parse_error() {
    assert_iteration_limit(&comparisons(7852), false);
    assert_iteration_limit(&comparisons(7853), true);
}

#[test]
fn the_parser_iteration_limit_in_a_terminator_probe_gives_a_parse_error() {
    assert_iteration_limit(&order_by_comparisons(7853), false);
    assert_iteration_limit(&order_by_comparisons(7854), true);
    assert_iteration_limit(&order_by_comparisons(8200), true);
}

/// --timings adds one JSON line to the end of stderr. The output and the
/// exit code do not change.
#[test]
fn timings_add_only_the_last_stderr_line() {
    let inputs = [
        ("select a from b;\n", 0),
        ("select 1 from t where ~~~ x\n", 1),
        ("select 'abc\n", 1),
    ];
    for (sql, want) in inputs {
        let plain = sqll_stdin(&["parse", "--dialect", "ansi", "-"], sql);
        let timed = sqll_stdin(&["parse", "--dialect", "ansi", "--timings", "-"], sql);
        assert_eq!(code(&plain), want, "{sql}");
        assert_eq!(code(&timed), want, "{sql}");
        assert_eq!(plain.stdout, timed.stdout, "{sql}");
        let text = stderr(&timed);
        let (before, last) = match text.trim_end_matches('\n').rsplit_once('\n') {
            Some((before, last)) => (format!("{before}\n"), last.to_string()),
            None => (String::new(), text.trim_end_matches('\n').to_string()),
        };
        assert_eq!(before, stderr(&plain), "{sql}");
        let record: serde_json::Value = serde_json::from_str(&last).expect("a JSON line");
        let keys = [
            "init_s", "setup_s", "lex_s", "parse_s", "record_s", "write_s", "free_s",
        ];
        // The keys in the order of the phases (serde_json sorts the keys).
        let order: Vec<&str> = last.split('"').skip(1).step_by(2).collect::<Vec<_>>();
        assert_eq!(order[..7], keys, "{sql}");
        assert_eq!(order[7..], ["total_s", "tokens"], "{sql}");
        assert_eq!(record.as_object().unwrap().len(), 9, "{sql}");
        let sum: f64 = keys.iter().map(|k| record[*k].as_f64().unwrap()).sum();
        let total = record["total_s"].as_f64().unwrap();
        assert!((sum - total).abs() < 1e-5, "{sql}: {sum} {total}");
        assert!(record["tokens"].as_u64().unwrap() > 0, "{sql}");
    }
}
