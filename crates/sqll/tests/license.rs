//! Tests of "sqll --license" and of the dependency license check
//! (build/notices.rs, S3 T19). The check fails closed.

#[path = "../build/notices.rs"]
mod notices;

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::{json, Value};

const SQLL: &str = env!("CARGO_BIN_EXE_sqll");

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn license_output() -> String {
    let out = Command::new(SQLL)
        .arg("--license")
        .output()
        .expect("run sqll");
    assert_eq!(
        out.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).expect("UTF-8 output")
}

fn read(rel: &str) -> String {
    fs::read_to_string(root().join(rel)).unwrap_or_else(|e| panic!("{rel}: {e}"))
}

#[test]
fn the_license_has_the_sqlfluff_mit_copyright_and_permission_notice() {
    let text = license_output();
    // The notice of the pinned sqlfluff (the submodule), not of a copy.
    let sqlfluff = read("third_party/sqlfluff/LICENSE.md");
    let copyright = sqlfluff
        .lines()
        .find(|l| l.starts_with("Copyright (c) 2018-2026 "))
        .expect("the sqlfluff copyright line");
    assert!(text.contains(copyright), "{copyright}");
    assert!(
        text.contains(sqlfluff.trim_end()),
        "the sqlfluff MIT license text"
    );
    assert!(text.contains(
        "The above copyright notice and this permission notice shall be included in all\n\
         copies or substantial portions of the Software."
    ));
    assert!(text.contains("tag 4.4.0, commit 0348222a3bcdb0226563f7349c5a39beb0641955"));
}

#[test]
fn the_license_has_the_sqll_license_and_the_other_notices() {
    let text = license_output();
    let sqll = read("LICENSE");
    assert!(sqll.starts_with("MIT License\n\nCopyright (c) 2026 The sqll authors\n"));
    assert!(text.contains(sqll.trim_end()), "the sqll license");
    assert!(text.starts_with("sqll, version "));
    assert!(
        text.contains(read("crates/LICENSE-cpython.txt").trim_end()),
        "CPython"
    );
    assert!(text.contains("tag v3.13.16, commit cbc944f4bc59639a444dd971c737788ba2283a91"));
    // The tomllib port of sqll_config (S3b C11).
    let tomli = read("crates/LICENSE-tomli.txt");
    assert!(tomli.starts_with("MIT License\n\nCopyright (c) 2021 Taneli Hukkinen\n"));
    assert!(text.contains(tomli.trim_end()), "the tomli MIT license");
    // The changes of the port are those of THIRD_PARTY.md ("tomllib").
    let words = |s: &str| {
        s.replace('`', "")
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ")
    };
    let changes = "Changes: Rust in place of Python; the parser works on characters; a date or \
                   time value is checked but not kept, and it fails closed in [tool.sqlfluff]; \
                   an int over 64 bits fails closed.";
    assert!(
        text.contains(changes),
        "the tomllib changes in sqll --license"
    );
    let third_party = words(&read("THIRD_PARTY.md"));
    let tomllib = &third_party[third_party.find("## tomllib").expect("## tomllib")..];
    assert!(
        tomllib.contains(changes),
        "the tomllib changes in THIRD_PARTY.md"
    );
    let rust = read("crates/LICENSE-rust-MIT.txt");
    assert!(rust.starts_with("Copyright (c) The Rust Project Contributors\n"));
    assert!(text.contains(rust.trim_end()), "the Rust MIT notice");
    // The Rust notice is of the tag of the pinned toolchain.
    let toolchain = read("rust-toolchain.toml");
    assert!(
        toolchain.contains("channel = \"1.97.0\""),
        "rust-toolchain.toml"
    );
    assert!(text.contains("(rustc 1.97.0 "), "the rustc of the build");
    assert!(text.contains("https://github.com/rust-lang/rust, tag 1.97.0."));
}

fn cargo_metadata(args: &[&str]) -> notices::Metadata {
    let cargo = std::env::var("CARGO").unwrap_or_else(|_| "cargo".to_string());
    let out = Command::new(cargo)
        .args([
            "metadata",
            "--format-version",
            "1",
            "--locked",
            "--manifest-path",
        ])
        .arg(root().join("Cargo.toml"))
        .args(args)
        .output()
        .expect("run cargo metadata");
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    notices::read_metadata(&String::from_utf8(out.stdout).unwrap()).unwrap()
}

/// Each package of the workspace, for each platform and each kind of
/// dependency (normal, build, dev), has a license in the allow list.
#[test]
fn each_dependency_of_the_workspace_has_an_allowed_license() {
    let meta = cargo_metadata(&[]);
    assert!(meta.packages.len() > 50, "{}", meta.packages.len());
    assert_eq!(notices::check(&meta), Vec::<String>::new());
    for id in &meta.members {
        assert_eq!(meta.packages[id].license.as_deref(), Some("MIT"), "{id}");
    }
}

/// The binary prints the notice list of the cargo metadata of its platform.
#[test]
fn the_license_has_the_dependency_notice_list() {
    let host = Command::new(std::env::var("RUSTC").unwrap_or_else(|_| "rustc".to_string()))
        .arg("-vV")
        .output()
        .expect("run rustc");
    let host = String::from_utf8(host.stdout).unwrap();
    let host = host
        .lines()
        .find_map(|l| l.strip_prefix("host: "))
        .expect("the host platform");
    let meta = cargo_metadata(&["--filter-platform", host]);
    let list = notices::notice_list(&meta, "sqll").expect("the notice list");
    let text = license_output();
    assert!(
        text.trim_end().ends_with(list.trim_end()),
        "the dependency notice list"
    );
    // A record of each OR choice.
    for (p, _) in notices::binary_packages(&meta, "sqll").unwrap() {
        let expr = p.license.as_deref().unwrap();
        let chosen = notices::choose(expr).unwrap().join(" AND ");
        let head = format!("---- {} {} ----\n", p.name, p.version);
        let at = text.find(&head).unwrap_or_else(|| panic!("{head}"));
        let entry = &text[at..];
        assert!(
            entry.contains(&format!("License: {expr}\nChosen: {chosen}\n")),
            "{head}"
        );
    }
    for (name, linked) in [("regex", "yes"), ("serde_derive", "no"), ("syn", "no")] {
        let at = text.find(&format!("\n---- {name} ")).expect(name);
        let entry = &text[at..];
        assert!(
            entry.contains(&format!("Linked into the binary: {linked}")),
            "{name}"
        );
    }
}

#[test]
fn choose_takes_the_first_allowed_choice() {
    let cases = [
        ("MIT", "MIT"),
        ("MIT OR Apache-2.0", "MIT"),
        ("Apache-2.0 OR MIT", "MIT"),
        ("MIT/Apache-2.0", "MIT"),
        ("Unlicense OR MIT", "MIT"),
        ("Zlib", "Zlib"),
        ("Apache-2.0 OR BSL-1.0", "Apache-2.0"),
        ("(MIT OR Apache-2.0) AND Unicode-3.0", "MIT AND Unicode-3.0"),
        ("Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT", "MIT"),
        (
            "Apache-2.0 WITH LLVM-exception",
            "Apache-2.0 WITH LLVM-exception",
        ),
        // A copyleft option in an OR: sqll takes the permissive one.
        ("MIT OR Apache-2.0 OR LGPL-2.1-or-later", "MIT"),
        ("GPL-3.0-only OR BSD-3-Clause", "BSD-3-Clause"),
    ];
    for (expr, want) in cases {
        assert_eq!(
            notices::choose(expr).map(|c| c.join(" AND ")),
            Ok(want.to_string()),
            "{expr}"
        );
    }
}

#[test]
fn choose_fails_for_copyleft_and_unknown_licenses() {
    for expr in [
        "GPL-3.0-only",
        "LGPL-2.1-or-later",
        "AGPL-3.0-or-later",
        "MPL-2.0",
        "MIT AND GPL-3.0-only",
        "(MIT OR Apache-2.0) AND GPL-2.0-only",
        "GPL-2.0-only WITH Classpath-exception-2.0",
        "Apache-2.0 WITH Some-exception",
        "Proprietary",
        "",
        "MIT OR",
        "(MIT",
        "MIT)",
        "MIT AND",
        "Apache-2.0 WITH",
    ] {
        assert!(notices::choose(expr).is_err(), "{expr:?}");
    }
}

/// An invented workspace: the member sqll needs "good" (MIT) and "dep";
/// "devonly" is only a dev dependency.
struct Fake {
    dir: PathBuf,
    packages: Vec<Value>,
}

const CRATES_IO: &str = notices::CRATES_IO;
const MIT_TEXT: &str = "Copyright (c) 2026 Someone\n\nPermission is hereby granted, free of \
    charge, to any person obtaining a copy of this software and associated documentation \
    files (the \"Software\"), to deal in the Software without restriction.\n";
const GPL_TEXT: &str = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n";

impl Fake {
    fn new(name: &str) -> Fake {
        let dir = std::env::temp_dir().join(format!("sqll-license-{}-{name}", std::process::id()));
        if dir.exists() {
            fs::remove_dir_all(&dir).unwrap();
        }
        fs::create_dir_all(&dir).unwrap();
        Fake {
            dir,
            packages: Vec::new(),
        }
    }

    fn package(
        &mut self,
        name: &str,
        license: Option<&str>,
        source: Option<&str>,
        files: &[(&str, &str)],
    ) {
        let pdir = self.dir.join(name);
        fs::create_dir_all(&pdir).unwrap();
        for (file, text) in files {
            fs::write(pdir.join(file), text).unwrap();
        }
        let kind = if name.ends_with("_derive") {
            "proc-macro"
        } else {
            "lib"
        };
        self.packages.push(json!({
            "id": format!("{name}@1.0.0"),
            "name": name,
            "version": "1.0.0",
            "source": source,
            "license": license,
            "license_file": null,
            "manifest_path": pdir.join("Cargo.toml").to_str().unwrap(),
            "targets": [{"kind": [kind]}],
        }));
    }

    /// The cargo metadata: sqll -> good, dep, dep_derive (normal); sqll ->
    /// devonly (dev); dep_derive -> helper (normal).
    fn metadata(&self) -> notices::Metadata {
        let normal = json!([{"kind": null, "target": null}]);
        let dev = json!([{"kind": "dev", "target": null}]);
        let mut nodes = vec![json!({"id": "sqll@1.0.0", "deps": [
            {"pkg": "good@1.0.0", "dep_kinds": normal},
            {"pkg": "dep@1.0.0", "dep_kinds": normal},
            {"pkg": "dep_derive@1.0.0", "dep_kinds": normal},
            {"pkg": "devonly@1.0.0", "dep_kinds": dev},
        ]})];
        nodes.push(json!({"id": "dep_derive@1.0.0", "deps": [
            {"pkg": "helper@1.0.0", "dep_kinds": normal},
        ]}));
        for p in ["good", "dep", "devonly", "helper"] {
            nodes.push(json!({"id": format!("{p}@1.0.0"), "deps": []}));
        }
        let v = json!({
            "packages": self.packages,
            "workspace_members": ["sqll@1.0.0"],
            "resolve": {"nodes": nodes},
        });
        notices::read_metadata(&v.to_string()).unwrap()
    }
}

fn fake(name: &str, dep_license: Option<&str>, dep_files: &[(&str, &str)]) -> Fake {
    let mut f = Fake::new(name);
    let mit = [("LICENSE-MIT", MIT_TEXT)];
    f.package("sqll", Some("MIT"), None, &[]);
    f.package("good", Some("MIT OR Apache-2.0"), Some(CRATES_IO), &mit);
    f.package("dep", dep_license, Some(CRATES_IO), dep_files);
    f.package("dep_derive", Some("MIT"), Some(CRATES_IO), &mit);
    f.package("helper", Some("Unlicense OR MIT"), Some(CRATES_IO), &mit);
    f.package("devonly", Some("MIT"), Some(CRATES_IO), &mit);
    f
}

#[test]
fn an_invented_copyleft_dependency_fails_the_check() {
    let f = fake("copyleft", Some("GPL-3.0-only"), &[("COPYING", GPL_TEXT)]);
    let meta = f.metadata();
    let problems = notices::check(&meta);
    assert_eq!(problems.len(), 1, "{problems:?}");
    assert!(problems[0].starts_with("dep 1.0.0: no choice of the license \"GPL-3.0-only\""));
    let err = notices::notice_list(&meta, "sqll").unwrap_err();
    assert_eq!(err, problems);
}

#[test]
fn a_copyleft_dev_dependency_also_fails_the_check() {
    let mut f = fake("copyleft-dev", Some("MIT"), &[("LICENSE", MIT_TEXT)]);
    f.packages.retain(|p| p["name"] != "devonly");
    f.package("devonly", Some("AGPL-3.0-only"), Some(CRATES_IO), &[]);
    assert_eq!(notices::check(&f.metadata()).len(), 1);
    assert!(notices::notice_list(&f.metadata(), "sqll").is_err());
}

#[test]
fn a_permissive_choice_passes_and_is_recorded() {
    let f = fake(
        "or-choice",
        Some("LGPL-2.1-or-later OR MIT"),
        &[("COPYING", GPL_TEXT), ("LICENSE", MIT_TEXT)],
    );
    let meta = f.metadata();
    assert_eq!(notices::check(&meta), Vec::<String>::new());
    let list = notices::notice_list(&meta, "sqll").unwrap();
    assert!(list.contains(
        "---- dep 1.0.0 ----\nSource: registry+https://github.com/rust-lang/crates.io-index\n\
         Linked into the binary: yes\nLicense: LGPL-2.1-or-later OR MIT\nChosen: MIT\n\n[LICENSE]\n"
    ));
    assert!(!list.contains("GNU GENERAL PUBLIC LICENSE"));
    // The dev dependency is not in the list; the proc-macro crate and its
    // dependency are, but the binary does not link them.
    assert!(!list.contains("---- devonly "));
    assert!(list.contains("---- dep_derive 1.0.0 ----\nSource: registry+https://github.com/rust-lang/crates.io-index\nLinked into the binary: no"));
    assert!(list.contains("---- helper 1.0.0 ----\nSource: registry+https://github.com/rust-lang/crates.io-index\nLinked into the binary: no"));
    assert!(list.starts_with("The package sqll needs 4 Rust crates from crates.io"));
    assert!(list.contains("The binary links 2 of them."));
}

#[test]
fn other_license_problems_fail_closed() {
    // No license expression.
    let f = fake("none", None, &[("LICENSE", MIT_TEXT)]);
    assert!(notices::check(&f.metadata())[0].starts_with("dep 1.0.0: no license expression"));
    // No file with the text of the chosen license.
    let f = fake("no-text", Some("MIT"), &[("LICENSE", GPL_TEXT)]);
    let meta = f.metadata();
    assert_eq!(notices::check(&meta), Vec::<String>::new());
    let err = notices::notice_list(&meta, "sqll").unwrap_err();
    assert!(
        err[0].starts_with("dep 1.0.0: no license file has the text of MIT"),
        "{err:?}"
    );
    // A source other than crates.io.
    let mut f = fake("git", Some("MIT"), &[("LICENSE", MIT_TEXT)]);
    f.packages.retain(|p| p["name"] != "dep");
    f.package(
        "dep",
        Some("MIT"),
        Some("git+https://example.com/dep"),
        &[("LICENSE", MIT_TEXT)],
    );
    assert!(notices::check(&f.metadata())[0].contains("is not crates.io"));
    // A sqll crate without the sqll license.
    let mut f = fake("member", Some("MIT"), &[("LICENSE", MIT_TEXT)]);
    f.packages.retain(|p| p["name"] != "sqll");
    f.package("sqll", Some("Apache-2.0"), None, &[]);
    assert!(notices::check(&f.metadata())[0]
        .starts_with("sqll 1.0.0: a sqll crate must have license = \"MIT\""));
}

#[test]
fn the_apache_notice_file_goes_with_the_apache_text() {
    let apache = "Apache License\nVersion 2.0, January 2004\n";
    let f = fake(
        "apache",
        Some("Apache-2.0"),
        &[
            ("LICENSE-APACHE", apache),
            ("NOTICE", "Dep\nCopyright 2026 Dep authors\n"),
        ],
    );
    let list = notices::notice_list(&f.metadata(), "sqll").unwrap();
    assert!(list.contains("Chosen: Apache-2.0\n\n[LICENSE-APACHE]\nApache License\nVersion 2.0, January 2004\n\n[NOTICE]\nDep\nCopyright 2026 Dep authors\n"));
}
