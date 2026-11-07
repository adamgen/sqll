//! Tests of the config of "sqll parse" (S3b task C11; docs/interfaces/config.md).
//!
//! `each_cli_scenario_gives_the_sqlfluff_result` runs sqll on each CLI
//! scenario of results/S3b/C11-config.json (scripts/s3b/config_oracle.py
//! ran "sqlfluff parse -f json" of the pinned sqlfluff on it): the same
//! stdout and exit code (with -m: the same tree with no position keys), or
//! "unsupported" with exit code 2 where sqll fails closed. The other tests
//! show the settings of the Rust parser, which the pure Python sqlfluff of
//! the record does not have.

use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};

use serde_json::Value as Json;
use serde_yaml_ng::Value as Yaml;

const SQLL: &str = env!("CARGO_BIN_EXE_sqll");
const POSITION_KEYS: [&str; 6] = [
    "start_line_no",
    "start_line_pos",
    "start_file_pos",
    "end_line_no",
    "end_line_pos",
    "end_file_pos",
];

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn record() -> Json {
    let text = std::fs::read_to_string(repo().join("results/S3b/C11-config.json"))
        .expect("read results/S3b/C11-config.json");
    serde_json::from_str(&text).expect("the record is JSON")
}

/// A new empty folder (its real path).
fn new_root(i: usize) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("sqll-c11-cli-{}-{i}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("create a folder");
    std::fs::canonicalize(&dir).expect("the real path")
}

fn make_files(root: &Path, files: &Json) {
    for (rel, content) in files.as_object().unwrap() {
        let path = root.join(rel);
        if content.get("dir").is_some() {
            std::fs::create_dir_all(&path).unwrap();
            continue;
        }
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        let data = match content {
            Json::String(s) => s.clone().into_bytes(),
            other => std::fs::read(
                repo()
                    .join("third_party/sqlfluff")
                    .join(other["fixture"].as_str().unwrap()),
            )
            .unwrap(),
        };
        std::fs::write(&path, data).unwrap();
    }
}

/// Run sqll in a scenario folder: HOME is `<root>/h`, with no
/// XDG_CONFIG_HOME.
fn run(root: &Path, cwd: &str, args: &[String], stdin: Option<&str>) -> Output {
    use std::io::Write;
    let mut child = Command::new(SQLL)
        .args(args)
        .current_dir(root.join(cwd))
        .env("HOME", root.join("h"))
        .env_remove("XDG_CONFIG_HOME")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("run sqll");
    let input = stdin.unwrap_or("").to_string();
    let mut pipe = child.stdin.take().unwrap();
    let writer = std::thread::spawn(move || {
        let _ = pipe.write_all(input.as_bytes());
    });
    let out = child.wait_with_output().expect("wait for sqll");
    writer.join().unwrap();
    out
}

/// The -m record as (key, value) pairs with no position keys
/// (scripts/s3b/config_oracle.py, strip).
fn strip(value: &Yaml) -> Json {
    match value {
        Yaml::Mapping(map) => Json::Array(
            map.iter()
                .filter(|(k, _)| !POSITION_KEYS.contains(&k.as_str().unwrap()))
                .map(|(k, v)| Json::Array(vec![Json::String(k.as_str().unwrap().into()), strip(v)]))
                .collect(),
        ),
        Yaml::Sequence(items) => Json::Array(
            items
                .iter()
                .flat_map(|i| match strip(i) {
                    Json::Array(pairs) => pairs,
                    other => vec![other],
                })
                .collect(),
        ),
        Yaml::String(s) => Json::String(s.clone()),
        Yaml::Null => Json::Null,
        other => panic!("not a record value: {other:?}"),
    }
}

fn tree(stdout: &[u8]) -> Json {
    let value: Yaml = serde_yaml_ng::from_slice(stdout).expect("JSON output");
    Json::Array(
        value
            .as_sequence()
            .expect("a list of records")
            .iter()
            .map(|r| strip(&r["segments"]))
            .collect(),
    )
}

#[test]
fn each_cli_scenario_gives_the_sqlfluff_result() {
    let rec = record();
    let mut problems = Vec::new();
    let scenarios = rec["cli"].as_array().unwrap();
    for (i, sc) in scenarios.iter().enumerate() {
        let name = sc["name"].as_str().unwrap();
        let root = new_root(i);
        make_files(&root, &sc["files"]);
        let cwd = sc["cwd"].as_str().unwrap();
        for folder in [cwd, "h"] {
            std::fs::create_dir_all(root.join(folder)).unwrap();
        }
        let mut args: Vec<String> = vec!["parse".into(), "-f".into(), "json".into()];
        args.extend(
            sc["args"]
                .as_array()
                .unwrap()
                .iter()
                .map(|a| a.as_str().unwrap().to_string()),
        );
        let out = run(&root, cwd, &args, sc["stdin"].as_str());
        let code = out.status.code().expect("an exit code");
        let stderr = String::from_utf8_lossy(&out.stderr);
        let want_code = sc["exit_code"].as_i64().unwrap() as i32;
        let r = root.to_str().unwrap();
        match sc["sqll"].as_str() {
            Some("unsupported") => {
                if code != 2 || !stderr.contains("unsupported: ") {
                    problems.push(format!("{name}: sqll must fail closed: {code} {stderr}"));
                }
            }
            Some("exit2") => {
                if code != 2 || stderr.contains("unsupported: ") {
                    problems.push(format!(
                        "{name}: sqll must give exit code 2: {code} {stderr}"
                    ));
                }
            }
            _ if want_code == 2 => {
                // sqlfluff writes the error to stdout, sqll to stderr.
                if code != 2 {
                    problems.push(format!("{name}: exit code {code}, sqlfluff 2: {stderr}"));
                }
            }
            _ => {
                if code != want_code {
                    problems.push(format!(
                        "{name}: exit code {code}, sqlfluff {want_code}: {stderr}"
                    ));
                } else if let Some(want) = sc.get("tree") {
                    let got = tree(&out.stdout);
                    if &got != want {
                        problems.push(format!("{name}: the -m tree is another one: {got}"));
                    }
                } else {
                    let got = String::from_utf8_lossy(&out.stdout).replace(r, "<root>");
                    if got != sc["stdout"].as_str().unwrap() {
                        problems.push(format!("{name}: stdout {got:?}, sqlfluff {}", sc["stdout"]));
                    }
                }
            }
        }
        let _ = std::fs::remove_dir_all(&root);
    }
    assert!(problems.is_empty(), "{problems:#?}");
    eprintln!(
        "config: {} of {} CLI scenarios as sqlfluff",
        scenarios.len(),
        scenarios.len()
    );
}

/// rust_parser_max_iterations and rust_parser_warn_threshold are settings
/// of the sqlfluff Rust parser (RustParser in
/// src/sqlfluff/core/parser/rust_parser.py: a value that Python sees as
/// false is the default). The pure Python sqlfluff of the record has no
/// iteration limit.
#[test]
fn the_parser_iteration_limit_comes_from_the_config() {
    let root = new_root(10_000);
    let sql = "select a from b join c on a = c\n";
    for (setting, code, message) in [
        (
            "rust_parser_max_iterations = 5",
            1,
            "PRS: Parser exceeded maximum iteration limit (5)",
        ),
        ("rust_parser_max_iterations = 0", 0, ""),
        ("rust_parser_max_iterations = None", 0, ""),
        (
            "rust_parser_max_iterations = -1",
            2,
            "unsupported: setting core:rust_parser_max_iterations",
        ),
        ("rust_parser_warn_threshold = 5", 0, ""),
    ] {
        let files = serde_json::json!({
            "w/.sqlfluff": format!("[sqlfluff]\ndialect = ansi\n{setting}\n"),
            "w/a.sql": sql,
        });
        make_files(&root, &files);
        std::fs::create_dir_all(root.join("h")).unwrap();
        let args: Vec<String> = ["parse", "-f", "json", "a.sql"].map(String::from).to_vec();
        let out = run(&root, "w", &args, None);
        let stderr = String::from_utf8_lossy(&out.stderr);
        assert_eq!(out.status.code(), Some(code), "{setting}: {stderr}");
        assert!(stderr.contains(message), "{setting}: {stderr}");
    }
    let _ = std::fs::remove_dir_all(&root);
}

/// --max-parse-depth (a sqll option) is an override of the config value.
#[test]
fn the_max_parse_depth_option_overrides_the_config() {
    let root = new_root(10_001);
    let files = serde_json::json!({
        "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nmax_parse_depth = 5\n",
        "w/a.sql": "select a from b join c on a = c\n",
    });
    make_files(&root, &files);
    std::fs::create_dir_all(root.join("h")).unwrap();
    let args = |extra: &[&str]| -> Vec<String> {
        let mut a: Vec<String> = ["parse", "-f", "json"].map(String::from).to_vec();
        a.extend(extra.iter().map(|s| s.to_string()));
        a.push("a.sql".into());
        a
    };
    assert_eq!(run(&root, "w", &args(&[]), None).status.code(), Some(1));
    assert_eq!(
        run(&root, "w", &args(&["--max-parse-depth", "600"]), None)
            .status
            .code(),
        Some(0)
    );
    // With --ignore-local-config the config file is not read.
    let out = run(
        &root,
        "w",
        &args(&["--ignore-local-config", "-d", "ansi"]),
        None,
    );
    assert_eq!(out.status.code(), Some(0));
    let _ = std::fs::remove_dir_all(&root);
}
