//! The build script of the sqll binary. It runs no Python.
//!
//! It gives the binary 2 build facts:
//!
//! - SQLL_TABLES_SHA256: the sha256 of crates/sqll_dialects/generated.json,
//!   the manifest of the generated dialect tables. The version of sqll is the
//!   crate version and this hash, so it is the same for each commit that has
//!   the same tables.
//! - SQLL_SOURCE_SHA256 and SQLL_SOURCE_FILES: the hash of the source files
//!   of the workspace (SOURCE_FILES and each file under SOURCE_DIRS). The
//!   harness computes the same hash from the worktree
//!   (harness/sqll_harness/adapters/sqll.py, source_hash) and refuses a
//!   binary with another hash (a stale build).

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

const SOURCE_FILES: &[&str] = &["Cargo.toml", "Cargo.lock", "rust-toolchain.toml"];
const SOURCE_DIRS: &[&str] = &["crates"];
const MANIFEST: &str = "crates/sqll_dialects/generated.json";

fn hex(digest: &[u8]) -> String {
    digest.iter().map(|b| format!("{b:02x}")).collect()
}

/// Each file under dir, as (path relative to root with "/", absolute path).
fn walk(root: &Path, dir: &Path, out: &mut Vec<(String, PathBuf)>) {
    let entries =
        fs::read_dir(dir).unwrap_or_else(|e| panic!("cannot read {}: {e}", dir.display()));
    for entry in entries {
        let path = entry.expect("a folder entry").path();
        let meta = fs::metadata(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
        if meta.is_dir() {
            walk(root, &path, out);
        } else if meta.is_file() {
            let rel = path.strip_prefix(root).expect("a path under the root");
            let parts: Vec<&str> = rel
                .components()
                .map(|c| c.as_os_str().to_str().expect("a UTF-8 file name"))
                .collect();
            out.push((parts.join("/"), path));
        }
    }
}

/// sha256 over each file, sorted by path: path, NUL, size, NUL, content.
fn source_hash(root: &Path) -> (String, usize) {
    let mut files: Vec<(String, PathBuf)> = SOURCE_FILES
        .iter()
        .map(|f| (f.to_string(), root.join(f)))
        .collect();
    for dir in SOURCE_DIRS {
        walk(root, &root.join(dir), &mut files);
    }
    files.sort();
    let mut hasher = Sha256::new();
    for (rel, path) in &files {
        let data = fs::read(path).unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
        hasher.update(rel.as_bytes());
        hasher.update(b"\0");
        hasher.update(data.len().to_string().as_bytes());
        hasher.update(b"\0");
        hasher.update(&data);
    }
    (hex(&hasher.finalize()), files.len())
}

fn main() {
    let crate_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let root = crate_dir
        .join("../..")
        .canonicalize()
        .expect("the workspace root");

    for f in SOURCE_FILES {
        println!("cargo:rerun-if-changed={}", root.join(f).display());
    }
    // Cargo scans a folder for a change of each file in it.
    for d in SOURCE_DIRS {
        println!("cargo:rerun-if-changed={}", root.join(d).display());
    }

    let manifest = fs::read(root.join(MANIFEST)).expect("read the table manifest");
    println!(
        "cargo:rustc-env=SQLL_TABLES_SHA256={}",
        hex(&Sha256::digest(&manifest))
    );
    let (hash, count) = source_hash(&root);
    println!("cargo:rustc-env=SQLL_SOURCE_SHA256={hash}");
    println!("cargo:rustc-env=SQLL_SOURCE_FILES={count}");
}
