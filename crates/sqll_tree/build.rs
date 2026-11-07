//! The build script of sqll_tree. It runs no Python.
//!
//! It makes the segment kinds from the dialect tables and the lexers of
//! sqll_dialects (build/kinds.rs) and writes OUT_DIR/kinds.rs, which
//! src/kinds.rs includes. The dialect names are the dialects of
//! crates/sqll_dialects/generated.json. The build fails if a dialect name is
//! not known, if the kinds or the type names do not fit in a u16, if a type
//! name is empty, or if two type names have one constant name.

#[path = "build/kinds.rs"]
mod kinds;

use std::collections::BTreeSet;
use std::env;
use std::fs;
use std::path::PathBuf;

/// The dialect names of the table manifest: "dialect/<name>/mod.rs".
fn dialect_names(manifest: &str) -> Vec<String> {
    let json: serde_json::Value = serde_json::from_str(manifest).expect("generated.json is JSON");
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
    assert!(!names.is_empty(), "generated.json has no dialect");
    names.into_iter().collect()
}

fn main() {
    let crate_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let out_dir = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR"));
    let manifest_path = crate_dir.join("../sqll_dialects/generated.json");
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=build/kinds.rs");
    println!("cargo:rerun-if-changed={}", manifest_path.display());

    let manifest = fs::read_to_string(&manifest_path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", manifest_path.display()));
    let names = dialect_names(&manifest);
    let made = kinds::kinds(&names).unwrap_or_else(|e| panic!("sqll_tree: segment kinds: {e}"));
    let code = kinds::code(&made).unwrap_or_else(|e| panic!("sqll_tree: segment kinds: {e}"));
    fs::write(out_dir.join("kinds.rs"), code).expect("write kinds.rs");
}
