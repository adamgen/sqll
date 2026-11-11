//! The text of "sqll --license" (S3 T19): the license of sqll and the
//! notices of the code in the sqll binary. THIRD_PARTY.md gives the sources.

/// The sqll license (MIT).
pub const SQLL: &str = include_str!("../../../LICENSE");
/// The sqlfluff MIT license: the ported sqlfluffrs crates and the generated
/// dialect tables.
pub const SQLFLUFF: &str = include_str!("../../LICENSE-sqlfluffrs.md");
/// The CPython license of the normpath and textwrap ports (sqll_cli) and of
/// the configparser port (sqll_config ini.rs).
pub const CPYTHON: &str = include_str!("../../LICENSE-cpython.txt");
/// The MIT license of tomli, of the tomllib port (sqll_config toml.rs).
pub const TOMLI: &str = include_str!("../../LICENSE-tomli.txt");
/// The MIT license of PyYAML, of the YAML emitter port (sqll_cli
/// lint/yaml.rs).
pub const PYYAML: &str = include_str!("../../LICENSE-pyyaml.txt");
/// The MIT notice of the Rust project (the Rust standard library).
pub const RUST: &str = include_str!("../../LICENSE-rust-MIT.txt");
/// The tag of rust-lang/rust that RUST comes from: the toolchain of
/// rust-toolchain.toml.
pub const RUST_TAG: &str = "1.97.0";
/// The rustc that built the binary ("rustc -V").
pub const RUSTC: &str = env!("SQLL_RUSTC_VERSION");
/// The dependency notice list that build.rs makes from cargo metadata.
pub const DEPENDENCIES: &str = include_str!(concat!(env!("OUT_DIR"), "/dependencies.txt"));

fn section(out: &mut String, title: &str, about: &str, text: &str) {
    out.push_str(&format!("\n==== {title} ====\n\n"));
    if !about.is_empty() {
        out.push_str(about);
        out.push_str("\n\n");
    }
    out.push_str(text.trim_end());
    out.push('\n');
}

pub fn text(version: &str) -> String {
    let mut out = format!(
        "sqll, version {version}\n\nsqll is free software under the MIT license (below). \
         The sqll binary also contains the code of other projects. Their \
         licenses and notices follow.\n"
    );
    section(&mut out, "sqll", "", SQLL);
    section(
        &mut out,
        "sqlfluff",
        "The sqll binary contains a port of the sqlfluffrs crates of sqlfluff and the \
         dialect tables that the sqlfluff generator makes.\n\
         Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0, commit \
         0348222a3bcdb0226563f7349c5a39beb0641955.\nLicense: MIT",
        SQLFLUFF,
    );
    section(
        &mut out,
        "CPython",
        "The sqll binary contains a port of normpath of Lib/posixpath.py, of wrap of \
         Lib/textwrap.py, and of the reader of RawConfigParser of Lib/configparser.py \
         of CPython.\n\
         Source: https://github.com/python/cpython, tag v3.13.16, commit \
         cbc944f4bc59639a444dd971c737788ba2283a91.\nLicense: PSF-2.0\n\
         Changes: Rust in place of Python; normpath: only str paths, and the root \
         slashes are found in the function, not with splitroot; textwrap: only the \
         default settings; configparser: only the settings that sqlfluff uses, and an \
         error stops the read.",
        CPYTHON,
    );
    section(
        &mut out,
        "tomllib",
        "The sqll binary contains a port of Lib/tomllib of CPython (tomli).\n\
         Source: https://github.com/python/cpython, tag v3.13.16, commit \
         cbc944f4bc59639a444dd971c737788ba2283a91, Lib/tomllib (SPDX: MIT, \
         Copyright (c) 2021 Taneli Hukkinen; licensed to PSF under a Contributor \
         Agreement).\nLicense: MIT (the text of https://github.com/hukkin/tomli, tag \
         2.0.1)\nChanges: Rust in place of Python; the parser works on characters; a date or \
         time value is checked but not kept, and it fails closed in [tool.sqlfluff]; \
         an int over 64 bits fails closed.",
        TOMLI,
    );
    section(
        &mut out,
        "PyYAML",
        "The sqll binary contains a port of parts of yaml/emitter.py, yaml/resolver.py, \
         and yaml/representer.py of PyYAML (the YAML output of sqll lint).\n\
         Source: https://github.com/yaml/pyyaml, tag 6.0.3.\nLicense: MIT\n\
         Changes: Rust in place of Python; only the values of a lint record.",
        PYYAML,
    );
    section(
        &mut out,
        "Rust standard library",
        &format!(
            "The sqll binary contains parts of the Rust standard library ({RUSTC}).\n\
             Source: https://github.com/rust-lang/rust, tag {RUST_TAG}.\n\
             License: MIT OR Apache-2.0\nChosen: MIT\n\
             The file COPYRIGHT of that tag gives the notices of the parts with \
             other licenses. The MIT notice (LICENSE-MIT of that tag):"
        ),
        RUST,
    );
    section(&mut out, "Rust crates", "", DEPENDENCIES);
    out
}
