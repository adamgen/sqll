//! The check of the generated dialect tables against generated.json.
//! build.rs uses it, and tests/build_tables.rs tests it.

use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fs;
use std::path::{Component, Path};

/// A generated file that agrees with the manifest. `rel` is its path in the
/// tables folder, for example "dialect/ansi/parser.rs".
pub struct Table {
    pub rel: String,
    pub data: Vec<u8>,
}

/// Read each file of the manifest from `dir` and compare its size and sha256
/// with the manifest. The folder must have no other file. Return the files,
/// or one line for each problem.
pub fn check(manifest: &str, dir: &Path) -> Result<Vec<Table>, Vec<String>> {
    let entries = entries(manifest).map_err(|e| vec![format!("generated.json: {e}")])?;
    if !dir.is_dir() {
        return Err(vec![format!(
            "{}: the folder does not exist",
            dir.display()
        )]);
    }
    let mut problems = Vec::new();
    let mut tables = Vec::new();
    for (rel, bytes, sha256) in &entries {
        let data = match fs::read(dir.join(rel)) {
            Ok(data) => data,
            Err(e) => {
                problems.push(format!("{rel}: cannot read the file ({e})"));
                continue;
            }
        };
        if data.len() as u64 != *bytes {
            problems.push(format!(
                "{rel}: {} bytes, generated.json: {bytes}",
                data.len()
            ));
            continue;
        }
        let got = hex(&Sha256::digest(&data));
        if got != *sha256 {
            problems.push(format!("{rel}: sha256 {got}, generated.json: {sha256}"));
            continue;
        }
        tables.push(Table {
            rel: rel.clone(),
            data,
        });
    }
    let expected: BTreeSet<&str> = entries.iter().map(|(rel, _, _)| rel.as_str()).collect();
    let mut found = Vec::new();
    if let Err(e) = list_files(dir, dir, &mut found) {
        problems.push(format!("{}: cannot list the folder ({e})", dir.display()));
    }
    for rel in found {
        if !expected.contains(rel.as_str()) {
            problems.push(format!("{rel}: the file is not in generated.json"));
        }
    }
    if problems.is_empty() {
        Ok(tables)
    } else {
        Err(problems)
    }
}

/// The (path in the tables folder, bytes, sha256) of each manifest file.
fn entries(manifest: &str) -> Result<Vec<(String, u64, String)>, String> {
    let value: serde_json::Value =
        serde_json::from_str(manifest).map_err(|e| format!("not valid JSON ({e})"))?;
    let prefix = value["prefix"].as_str().ok_or("no \"prefix\" string")?;
    let files = value["files"].as_array().ok_or("no \"files\" list")?;
    if files.is_empty() {
        return Err("the \"files\" list is empty".to_string());
    }
    let mut out = Vec::new();
    let mut seen = BTreeSet::new();
    for file in files {
        let path = file["path"]
            .as_str()
            .ok_or("a file has no \"path\" string")?;
        let rel = path
            .strip_prefix(prefix)
            .ok_or(format!("{path}: the path does not start with the prefix"))?;
        let safe = Path::new(rel)
            .components()
            .all(|c| matches!(c, Component::Normal(_)));
        if rel.is_empty() || !safe {
            return Err(format!("{path}: not a relative path in the folder"));
        }
        if !seen.insert(rel.to_string()) {
            return Err(format!("{path}: the path occurs 2 times"));
        }
        let bytes = file["bytes"]
            .as_u64()
            .ok_or(format!("{path}: no \"bytes\" number"))?;
        let sha256 = file["sha256"]
            .as_str()
            .filter(|s| s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()))
            .ok_or(format!("{path}: no \"sha256\" of 64 hex digits"))?;
        out.push((rel.to_string(), bytes, sha256.to_ascii_lowercase()));
    }
    Ok(out)
}

fn list_files(root: &Path, dir: &Path, out: &mut Vec<String>) -> std::io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            list_files(root, &path, out)?;
        } else {
            let rel = path.strip_prefix(root).unwrap_or(&path);
            out.push(rel.to_string_lossy().replace('\\', "/"));
        }
    }
    Ok(())
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
