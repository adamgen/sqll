//! The dependency license check and the dependency notice list of the sqll
//! binary (S3 T19). build.rs runs it on the output of "cargo metadata";
//! tests/notices.rs tests it. It fails closed: a dependency without a
//! license that the allow list permits, or without the text of its chosen
//! license, is an error.

use std::collections::{BTreeSet, HashMap};
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;

/// The license of sqll and of each crate of its workspace.
pub const SQLL_LICENSE: &str = "MIT";

/// The licenses that a dependency can have, in the order of choice: MIT
/// (the license of sqll) first. Each one is permissive. A new license needs
/// a review before it goes into this list (THIRD_PARTY.md, "Rust crates").
pub const ALLOWED: &[&str] = &[
    "MIT",
    "Apache-2.0",
    "BSL-1.0",
    "BSD-3-Clause",
    "Zlib",
    "Unicode-3.0",
    "Unlicense",
    "Apache-2.0 WITH LLVM-exception",
];

/// For each allowed license: words that the name of its license file can
/// have, and the phrases that its text must have (whitespace collapsed).
const TEXTS: &[(&str, &[&str], &[&str])] = &[
    (
        "MIT",
        &["MIT"],
        &["Permission is hereby granted, free of charge, to any person obtaining a copy"],
    ),
    (
        "Apache-2.0",
        &["APACHE"],
        &["Apache License", "Version 2.0"],
    ),
    (
        "BSL-1.0",
        &["BOOST", "BSL"],
        &["Boost Software License - Version 1.0"],
    ),
    (
        "BSD-3-Clause",
        &["BSD"],
        &[
            "Redistribution and use in source and binary forms",
            "Neither the name",
        ],
    ),
    (
        "Zlib",
        &["ZLIB"],
        &["This software is provided 'as-is', without any express or implied warranty"],
    ),
    ("Unicode-3.0", &["UNICODE"], &["UNICODE LICENSE V3"]),
    (
        "Unlicense",
        &["UNLICENSE"],
        &["This is free and unencumbered software released into the public domain"],
    ),
    (
        "Apache-2.0 WITH LLVM-exception",
        &["APACHE", "LLVM"],
        &["Apache License", "LLVM Exceptions"],
    ),
];

/// The license files that a package can have in its root folder.
const LICENSE_FILE_PREFIXES: &[&str] = &["LICENSE", "LICENCE", "COPYING", "UNLICENSE", "COPYRIGHT"];

/// The source of the crates.io packages.
pub const CRATES_IO: &str = "registry+https://github.com/rust-lang/crates.io-index";

/// A license expression in disjunctive normal form: a list of choices, each
/// choice a list of licenses that all apply.
pub type Choices = Vec<Vec<String>>;

fn tokens(expr: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut word = String::new();
    for c in expr.chars() {
        if c == '(' || c == ')' || c == '/' || c.is_whitespace() {
            if !word.is_empty() {
                out.push(std::mem::take(&mut word));
            }
            if !c.is_whitespace() {
                // The old cargo form "MIT/Apache-2.0" is "MIT OR Apache-2.0".
                out.push(if c == '/' {
                    "OR".to_string()
                } else {
                    c.to_string()
                });
            }
        } else {
            word.push(c);
        }
    }
    if !word.is_empty() {
        out.push(word);
    }
    out
}

struct Parser {
    tokens: Vec<String>,
    pos: usize,
}

impl Parser {
    fn peek(&self) -> Option<&str> {
        self.tokens.get(self.pos).map(String::as_str)
    }

    fn next(&mut self) -> Option<String> {
        let t = self.tokens.get(self.pos).cloned();
        self.pos += 1;
        t
    }

    fn or(&mut self) -> Result<Choices, String> {
        let mut choices = self.and()?;
        while self.peek() == Some("OR") {
            self.pos += 1;
            choices.extend(self.and()?);
        }
        Ok(choices)
    }

    fn and(&mut self) -> Result<Choices, String> {
        let mut choices = self.atom()?;
        while self.peek() == Some("AND") {
            self.pos += 1;
            let right = self.atom()?;
            let mut product = Vec::new();
            for a in &choices {
                for b in &right {
                    let mut both = a.clone();
                    both.extend(b.iter().cloned());
                    product.push(both);
                }
            }
            choices = product;
        }
        Ok(choices)
    }

    fn atom(&mut self) -> Result<Choices, String> {
        match self.next().as_deref() {
            Some("(") => {
                let inner = self.or()?;
                match self.next().as_deref() {
                    Some(")") => Ok(inner),
                    _ => Err("no closing parenthesis".to_string()),
                }
            }
            Some(op @ (")" | "AND" | "OR" | "WITH")) => Err(format!("unexpected {op}")),
            None => Err("the expression ends too early".to_string()),
            Some(id) => {
                let mut id = id.to_string();
                if self.peek() == Some("WITH") {
                    self.pos += 1;
                    match self.next() {
                        Some(e) if !["(", ")", "AND", "OR", "WITH"].contains(&e.as_str()) => {
                            id = format!("{id} WITH {e}");
                        }
                        _ => return Err("WITH needs an exception name".to_string()),
                    }
                }
                Ok(vec![vec![id]])
            }
        }
    }
}

/// Read an SPDX license expression (with AND, OR, WITH, parentheses, and
/// the old cargo form "A/B").
pub fn choices(expr: &str) -> Result<Choices, String> {
    let mut parser = Parser {
        tokens: tokens(expr),
        pos: 0,
    };
    let choices = parser.or()?;
    if parser.pos != parser.tokens.len() {
        return Err(format!("unexpected {}", parser.tokens[parser.pos]));
    }
    Ok(choices)
}

fn rank(id: &str) -> Option<usize> {
    ALLOWED.iter().position(|a| *a == id)
}

/// The licenses that sqll takes for a license expression: the choice with
/// only allowed licenses that comes first in the order of ALLOWED. An error
/// if no choice has only allowed licenses.
pub fn choose(expr: &str) -> Result<Vec<String>, String> {
    let all = choices(expr).map_err(|e| format!("cannot read the license {expr:?}: {e}"))?;
    let mut best: Option<(Vec<usize>, Vec<String>)> = None;
    for choice in all {
        let mut ids: Vec<String> = choice
            .into_iter()
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();
        let Some(mut ranks) = ids
            .iter()
            .map(|id| rank(id))
            .collect::<Option<Vec<usize>>>()
        else {
            continue;
        };
        ids.sort_by_key(|id| rank(id));
        // The highest rank first: a choice with a later license loses.
        ranks.sort_unstable_by(|a, b| b.cmp(a));
        if best.as_ref().map_or(true, |(k, _)| ranks < *k) {
            best = Some((ranks, ids));
        }
    }
    best.map(|(_, ids)| ids)
        .ok_or_else(|| format!("no choice of the license {expr:?} is in the allow list"))
}

/// One package of the cargo metadata.
#[derive(Clone, Debug)]
pub struct Package {
    pub id: String,
    pub name: String,
    pub version: String,
    pub source: Option<String>,
    pub license: Option<String>,
    pub license_file: Option<String>,
    pub dir: PathBuf,
    /// A proc-macro crate: it runs in the compiler, its code is not in a
    /// binary.
    pub proc_macro: bool,
}

/// The packages, the workspace members, and the dependency graph of the
/// output of "cargo metadata --format-version 1".
pub struct Metadata {
    pub packages: HashMap<String, Package>,
    pub members: BTreeSet<String>,
    /// For each package id: each dependency id, and true if it is a normal
    /// dependency (not only a build or dev dependency).
    pub deps: HashMap<String, Vec<(String, bool)>>,
}

fn text(v: &Value, key: &str) -> Result<String, String> {
    v[key]
        .as_str()
        .map(str::to_string)
        .ok_or_else(|| format!("cargo metadata: no {key}"))
}

fn opt_text(v: &Value, key: &str) -> Option<String> {
    v[key].as_str().map(str::to_string)
}

pub fn read_metadata(json: &str) -> Result<Metadata, String> {
    let v: Value = serde_json::from_str(json).map_err(|e| format!("cargo metadata: {e}"))?;
    let mut packages = HashMap::new();
    for p in v["packages"]
        .as_array()
        .ok_or("cargo metadata: no packages")?
    {
        let manifest = PathBuf::from(text(p, "manifest_path")?);
        let proc_macro = p["targets"]
            .as_array()
            .ok_or("cargo metadata: no targets")?
            .iter()
            .any(|t| {
                t["kind"]
                    .as_array()
                    .is_some_and(|k| k.iter().any(|k| k == "proc-macro"))
            });
        let package = Package {
            id: text(p, "id")?,
            name: text(p, "name")?,
            version: text(p, "version")?,
            source: opt_text(p, "source"),
            license: opt_text(p, "license"),
            license_file: opt_text(p, "license_file"),
            dir: manifest.parent().map(Path::to_path_buf).unwrap_or_default(),
            proc_macro,
        };
        packages.insert(package.id.clone(), package);
    }
    let members = v["workspace_members"]
        .as_array()
        .ok_or("cargo metadata: no workspace_members")?
        .iter()
        .map(|m| {
            m.as_str()
                .map(str::to_string)
                .ok_or("a workspace member id")
        })
        .collect::<Result<_, _>>()?;
    let mut deps = HashMap::new();
    let nodes = v["resolve"]["nodes"]
        .as_array()
        .ok_or("cargo metadata: no resolve graph (do not use --no-deps)")?;
    for node in nodes {
        let mut list = Vec::new();
        for d in node["deps"].as_array().ok_or("cargo metadata: no deps")? {
            let kinds = d["dep_kinds"]
                .as_array()
                .ok_or("cargo metadata: no dep_kinds")?;
            let normal = kinds.iter().any(|k| k["kind"].is_null());
            list.push((text(d, "pkg")?, normal));
        }
        deps.insert(text(node, "id")?, list);
    }
    Ok(Metadata {
        packages,
        members,
        deps,
    })
}

/// The problems of the licenses of each package. A workspace member must
/// have the license of sqll. Each other package must come from crates.io
/// and have a license expression with a choice in the allow list.
pub fn check(meta: &Metadata) -> Vec<String> {
    let mut problems = Vec::new();
    let mut ids: Vec<&String> = meta.packages.keys().collect();
    ids.sort();
    for id in ids {
        let p = &meta.packages[id];
        let name = format!("{} {}", p.name, p.version);
        if meta.members.contains(id) {
            if p.license.as_deref() != Some(SQLL_LICENSE) {
                problems.push(format!(
                    "{name}: a sqll crate must have license = \"{SQLL_LICENSE}\", not {:?}",
                    p.license
                ));
            }
            continue;
        }
        if p.source.as_deref() != Some(CRATES_IO) {
            problems.push(format!(
                "{name}: the source {:?} is not crates.io",
                p.source
            ));
        }
        match &p.license {
            None => problems.push(format!(
                "{name}: no license expression (license_file {:?})",
                p.license_file
            )),
            Some(expr) => {
                if let Err(e) = choose(expr) {
                    problems.push(format!("{name}: {e}"));
                }
            }
        }
    }
    problems
}

/// The ids that a chain of normal dependencies from `start` reaches. With
/// `skip_proc_macros`, the walk does not go into a proc-macro crate.
fn reach(meta: &Metadata, start: &str, skip_proc_macros: bool) -> Result<BTreeSet<String>, String> {
    let mut seen = BTreeSet::new();
    let mut stack = vec![start.to_string()];
    while let Some(id) = stack.pop() {
        if seen.contains(&id) {
            continue;
        }
        let p = meta
            .packages
            .get(&id)
            .ok_or_else(|| format!("{id}: not in the packages"))?;
        if skip_proc_macros && p.proc_macro {
            continue;
        }
        seen.insert(id.clone());
        let deps = meta
            .deps
            .get(&id)
            .ok_or_else(|| format!("{id}: not in the resolve graph"))?;
        for (dep, normal) in deps {
            if *normal {
                stack.push(dep.clone());
            }
        }
    }
    Ok(seen)
}

/// The packages that the workspace member `root` needs to build its
/// binary: each package that a chain of normal dependencies reaches,
/// without the workspace members, sorted by name and version. With each
/// package: true if the binary links it, false if only a proc-macro
/// crate (code that runs in the compiler) uses it.
pub fn binary_packages<'a>(
    meta: &'a Metadata,
    root: &str,
) -> Result<Vec<(&'a Package, bool)>, String> {
    let start = meta
        .packages
        .values()
        .find(|p| p.name == root && meta.members.contains(&p.id))
        .ok_or_else(|| format!("no workspace member {root}"))?;
    let all = reach(meta, &start.id, false)?;
    let linked = reach(meta, &start.id, true)?;
    let mut out: Vec<(&Package, bool)> = all
        .iter()
        .filter(|id| !meta.members.contains(*id))
        .map(|id| (&meta.packages[id], linked.contains(id)))
        .collect();
    out.sort_by(|a, b| (&a.0.name, &a.0.version).cmp(&(&b.0.name, &b.0.version)));
    Ok(out)
}

fn collapse(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// The text of a license file: "\r\n" becomes "\n", with no space at the end.
fn clean(text: &str) -> String {
    text.replace("\r\n", "\n").trim_end().to_string()
}

/// The license files in the root folder of a package, and its license_file.
fn license_files(p: &Package) -> Result<Vec<PathBuf>, String> {
    let entries = fs::read_dir(&p.dir).map_err(|e| {
        format!(
            "{} {}: cannot read {}: {e}",
            p.name,
            p.version,
            p.dir.display()
        )
    })?;
    let mut files = Vec::new();
    for entry in entries {
        let path = entry.map_err(|e| format!("{}: {e}", p.name))?.path();
        let upper = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("")
            .to_uppercase();
        if path.is_file() && LICENSE_FILE_PREFIXES.iter().any(|f| upper.starts_with(f)) {
            files.push(path);
        }
    }
    if let Some(f) = &p.license_file {
        let path = p.dir.join(f);
        if !files.contains(&path) {
            files.push(path);
        }
    }
    files.sort();
    Ok(files)
}

/// For each license of the choice: the name and text of the package file
/// that has it. The files with a word of the license in their name come
/// first. An error if no file has the text of a license.
pub fn license_texts(p: &Package, chosen: &[String]) -> Result<Vec<(String, String)>, String> {
    let files = license_files(p)?;
    let mut out = Vec::new();
    for id in chosen {
        let (_, words, phrases) = TEXTS
            .iter()
            .find(|(t, _, _)| t == id)
            .ok_or_else(|| format!("{id}: no text check (TEXTS)"))?;
        let mut ordered: Vec<&PathBuf> = files.iter().collect();
        ordered.sort_by_key(|f| {
            let name = f
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("")
                .to_uppercase();
            !words.iter().any(|w| name.contains(w))
        });
        let mut found = None;
        for f in ordered {
            let Ok(data) = fs::read_to_string(f) else {
                continue;
            };
            let flat = collapse(&data);
            if phrases.iter().all(|ph| flat.contains(ph)) {
                let name = f
                    .file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or("")
                    .to_string();
                found = Some((name, clean(&data)));
                break;
            }
        }
        out.push(found.ok_or_else(|| {
            format!(
                "{} {}: no license file has the text of {id} (files: {:?})",
                p.name, p.version, files
            )
        })?);
    }
    // Apache-2.0, section 4(d): the text of a NOTICE file goes with the work.
    if chosen.iter().any(|id| id.starts_with("Apache-2.0")) {
        let entries = fs::read_dir(&p.dir).map_err(|e| format!("{}: {e}", p.name))?;
        let mut notices: Vec<PathBuf> = entries
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|f| {
                f.is_file()
                    && f.file_name()
                        .and_then(|n| n.to_str())
                        .is_some_and(|n| n.to_uppercase().starts_with("NOTICE"))
            })
            .collect();
        notices.sort();
        for f in notices {
            let data = fs::read_to_string(&f).map_err(|e| format!("{}: {e}", f.display()))?;
            let name = f
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("")
                .to_string();
            out.push((name, clean(&data)));
        }
    }
    Ok(out)
}

/// The notice list of the binary of the workspace member `root`: for each
/// dependency, its name, version, source, license expression, the chosen
/// licenses (the record of each OR choice), and the license texts.
pub fn notice_list(meta: &Metadata, root: &str) -> Result<String, Vec<String>> {
    let problems = check(meta);
    if !problems.is_empty() {
        return Err(problems);
    }
    let packages = binary_packages(meta, root).map_err(|e| vec![e])?;
    let mut problems = Vec::new();
    let linked = packages.iter().filter(|(_, l)| *l).count();
    let mut out = format!(
        "The package {root} needs {} Rust crates from crates.io (its normal \
         dependencies, from cargo metadata). The binary links {linked} of them. \
         The others are proc-macro crates and their dependencies: they run in the \
         compiler. For each crate: its license expression, the license that sqll \
         chooses, and the license texts.\n",
        packages.len()
    );
    for (p, in_binary) in packages {
        let expr = p.license.as_deref().unwrap_or_default();
        let chosen = match choose(expr) {
            Ok(c) => c,
            Err(e) => {
                problems.push(format!("{} {}: {e}", p.name, p.version));
                continue;
            }
        };
        let texts = match license_texts(p, &chosen) {
            Ok(t) => t,
            Err(e) => {
                problems.push(e);
                continue;
            }
        };
        out.push_str(&format!(
            "\n---- {} {} ----\nSource: {}\nLinked into the binary: {}\nLicense: {expr}\nChosen: {}\n",
            p.name,
            p.version,
            p.source.as_deref().unwrap_or_default(),
            if in_binary { "yes" } else { "no (build time only)" },
            chosen.join(" AND ")
        ));
        for (name, text) in texts {
            out.push_str(&format!("\n[{name}]\n{text}\n"));
        }
    }
    if problems.is_empty() {
        Ok(out)
    } else {
        Err(problems)
    }
}
