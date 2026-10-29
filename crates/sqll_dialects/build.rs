//! The build script of sqll_dialects. It runs no Python.
//!
//! scripts/build-sqll generates the dialect tables with the pinned sqlfluff
//! generator into target/sqll-tables (or $SQLL_TABLES_DIR). This script
//! checks each file against generated.json (size and sha256), copies the
//! checked bytes to OUT_DIR, and writes OUT_DIR/dialect.rs, which src/lib.rs
//! includes. If a file is missing or different, the build fails.

#[path = "build/tables.rs"]
mod tables;

use std::env;
use std::fs;
use std::path::PathBuf;

fn main() {
    let crate_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let out_dir = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR"));
    let tables_dir = env::var_os("SQLL_TABLES_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| crate_dir.join("../../target/sqll-tables"));
    let manifest_path = crate_dir.join("generated.json");

    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=build/tables.rs");
    println!("cargo:rerun-if-changed={}", manifest_path.display());
    println!("cargo:rerun-if-env-changed=SQLL_TABLES_DIR");
    println!("cargo:rerun-if-changed={}", tables_dir.display());

    let manifest = fs::read_to_string(&manifest_path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", manifest_path.display()));
    let checked = tables::check(&manifest, &tables_dir).unwrap_or_else(|problems| {
        panic!(
            "\n\nsqll_dialects: the generated dialect tables in {} are missing or \
             not equal to generated.json:\n  {}\n\nRun scripts/build-sqll: it \
             generates the tables with the pinned sqlfluff generator and checks \
             them.\n",
            tables_dir.display(),
            problems.join("\n  ")
        )
    });

    let copy_dir = out_dir.join("tables");
    if copy_dir.exists() {
        fs::remove_dir_all(&copy_dir).expect("remove the old copy of the tables");
    }
    for table in &checked {
        let path = copy_dir.join(&table.rel);
        fs::create_dir_all(path.parent().expect("a parent folder")).expect("create a folder");
        fs::write(&path, &table.data).expect("write a table");
    }
    let mod_rs = copy_dir.join("dialect").join("mod.rs");
    let mod_rs = mod_rs.to_str().expect("OUT_DIR is not valid UTF-8");
    fs::write(
        out_dir.join("dialect.rs"),
        format!("#[path = {mod_rs:?}]\npub mod dialect;\n"),
    )
    .expect("write dialect.rs");
}
