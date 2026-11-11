//! The interface tests of sqll. The tests are in tests/, one file for each
//! frozen interface (docs/interfaces/). This library has their shared parts:
//! the dialects and the dialect fixtures, the parse of `sqll parse`
//! ([`parse`]), and the check of a `SyntaxTree` against its parser tree
//! ([`tree_check`]).

pub mod parse;
pub mod tree_check;

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::str::FromStr;

use sqll_dialects::Dialect;

/// The dialects of generated.json.
pub const DIALECTS: usize = 28;
/// The dialect fixtures of the pinned sqlfluff (S1: 2306 parse cases).
pub const FIXTURES: usize = 2306;
/// The stack of the command thread of crates/sqll/src/main.rs: the parser
/// recurses.
pub const STACK_SIZE: usize = 256 * 1024 * 1024;

/// The repository root.
pub fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

/// The dialects of the tables: "dialect/<name>/mod.rs" under the prefix of
/// generated.json (the rule of sqll_tree/build.rs).
pub fn dialects() -> Vec<(String, Dialect)> {
    let manifest = std::fs::read_to_string(root().join("crates/sqll_dialects/generated.json"))
        .expect("read generated.json");
    let json: serde_json::Value = serde_json::from_str(&manifest).expect("generated.json is JSON");
    let prefix = json["prefix"].as_str().expect("generated.json: prefix");
    let mut names = BTreeSet::new();
    for file in json["files"].as_array().expect("generated.json: files") {
        let path = file["path"].as_str().expect("generated.json: path");
        let rel = path.strip_prefix(prefix).expect("a path under the prefix");
        if let Some(name) = rel
            .strip_prefix("dialect/")
            .and_then(|r| r.strip_suffix("/mod.rs"))
        {
            names.insert(name.to_string());
        }
    }
    assert_eq!(names.len(), DIALECTS, "the dialects of generated.json");
    names
        .into_iter()
        .map(|n| {
            let d = Dialect::from_str(&n).unwrap_or_else(|_| panic!("unknown dialect {n}"));
            (n, d)
        })
        .collect()
}

/// The dialect fixture files (`*.sql`) of the pinned sqlfluff, in the order
/// of the dialect names and the file names.
pub fn dialect_fixtures() -> Vec<(String, Dialect, PathBuf)> {
    let folder = root().join("third_party/sqlfluff/test/fixtures/dialects");
    let mut out = Vec::new();
    for (name, dialect) in dialects() {
        let mut paths: Vec<PathBuf> = std::fs::read_dir(folder.join(&name))
            .unwrap_or_else(|e| panic!("{name}: {e}"))
            .map(|e| e.unwrap().path())
            .filter(|p| p.extension().is_some_and(|x| x == "sql"))
            .collect();
        paths.sort();
        out.extend(paths.into_iter().map(|p| (name.clone(), dialect, p)));
    }
    out
}

/// Run `f` on a thread with the stack of `sqll parse`, and return its value.
pub fn with_parse_stack<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> T {
    std::thread::Builder::new()
        .stack_size(STACK_SIZE)
        .spawn(f)
        .expect("start a thread")
        .join()
        .unwrap_or_else(|e| std::panic::resume_unwind(e))
}
