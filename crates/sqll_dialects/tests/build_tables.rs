//! Tests of the table check of build.rs (build/tables.rs): it fails closed.

#[path = "../build/tables.rs"]
mod tables;

use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

const PREFIX: &str = "sqlfluffrs/sqlfluffrs_dialects/src/";
const FILES: [(&str, &[u8]); 2] = [
    ("dialect/mod.rs", b"pub mod ansi;\n"),
    ("dialect/ansi/mod.rs", b"pub const X: u8 = 1;\n"),
];

fn hex(data: &[u8]) -> String {
    Sha256::digest(data)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// A new folder with the test files, and the manifest of these files.
fn setup(name: &str) -> (PathBuf, String) {
    let dir = std::env::temp_dir().join(format!("sqll-tables-{}-{name}", std::process::id()));
    if dir.exists() {
        fs::remove_dir_all(&dir).unwrap();
    }
    let mut files = Vec::new();
    for (rel, data) in FILES {
        let path = dir.join(rel);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, data).unwrap();
        files.push(serde_json::json!({
            "path": format!("{PREFIX}{rel}"),
            "bytes": data.len(),
            "sha256": hex(data),
        }));
    }
    let manifest = serde_json::json!({"prefix": PREFIX, "files": files}).to_string();
    (dir, manifest)
}

fn problems(manifest: &str, dir: &Path) -> String {
    match tables::check(manifest, dir) {
        Ok(_) => panic!("the check passed"),
        Err(problems) => problems.join("\n"),
    }
}

#[test]
fn equal_files_pass() {
    let (dir, manifest) = setup("equal");
    let checked = tables::check(&manifest, &dir).unwrap_or_else(|p| panic!("{p:?}"));
    let got: Vec<(&str, &[u8])> = checked
        .iter()
        .map(|t| (t.rel.as_str(), t.data.as_slice()))
        .collect();
    assert_eq!(got, FILES.to_vec());
}

#[test]
fn a_changed_byte_fails() {
    let (dir, manifest) = setup("byte");
    fs::write(dir.join("dialect/ansi/mod.rs"), b"pub const X: u8 = 2;\n").unwrap();
    let text = problems(&manifest, &dir);
    assert!(text.contains("dialect/ansi/mod.rs: sha256 "), "{text}");
}

#[test]
fn a_changed_size_fails() {
    let (dir, manifest) = setup("size");
    fs::write(dir.join("dialect/mod.rs"), b"pub mod ansi;\n\n").unwrap();
    let text = problems(&manifest, &dir);
    assert!(
        text.contains("dialect/mod.rs: 15 bytes, generated.json: 14"),
        "{text}"
    );
}

#[test]
fn a_missing_file_fails() {
    let (dir, manifest) = setup("missing");
    fs::remove_file(dir.join("dialect/ansi/mod.rs")).unwrap();
    let text = problems(&manifest, &dir);
    assert!(
        text.contains("dialect/ansi/mod.rs: cannot read the file"),
        "{text}"
    );
}

#[test]
fn an_extra_file_fails() {
    let (dir, manifest) = setup("extra");
    fs::write(dir.join("dialect/ansi/extra.rs"), b"").unwrap();
    let text = problems(&manifest, &dir);
    assert!(
        text.contains("dialect/ansi/extra.rs: the file is not in generated.json"),
        "{text}"
    );
}

#[test]
fn a_missing_folder_fails() {
    let (dir, manifest) = setup("folder");
    fs::remove_dir_all(&dir).unwrap();
    let text = problems(&manifest, &dir);
    assert!(text.contains("the folder does not exist"), "{text}");
}

#[test]
fn a_bad_manifest_fails() {
    let (dir, manifest) = setup("manifest");
    let cases = [
        ("not json".to_string(), "not valid JSON"),
        (
            r#"{"prefix": "x/", "files": []}"#.to_string(),
            "the \"files\" list is empty",
        ),
        (
            manifest.replace(&format!("\"path\":\"{PREFIX}"), "\"path\":\"other/"),
            "the path does not start with the prefix",
        ),
        (
            manifest.replace("dialect/ansi/mod.rs", "dialect/../../x.rs"),
            "not a relative path in the folder",
        ),
        (
            manifest.replace("dialect/ansi/mod.rs", "dialect/mod.rs"),
            "the path occurs 2 times",
        ),
        (
            manifest.replace("\"sha256\":\"", "\"sha256\":\"x"),
            "no \"sha256\" of 64 hex digits",
        ),
    ];
    for (text, want) in cases {
        let got = problems(&text, &dir);
        assert!(
            got.starts_with("generated.json: ") && got.contains(want),
            "{got}"
        );
    }
}

#[test]
fn the_committed_manifest_has_the_85_generated_files() {
    let text = fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/generated.json")).unwrap();
    let value: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(value["prefix"], PREFIX);
    let files = value["files"].as_array().unwrap();
    assert_eq!(files.len(), 85);
    assert!(files
        .iter()
        .any(|f| f["path"] == format!("{PREFIX}dialect/mod.rs")));
}
