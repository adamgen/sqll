// Parts of this file are a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/errors.py, src/sqlfluff/core/rules/fix.py,
// src/sqlfluff/core/linter/linted_dir.py, src/sqlfluff/cli/commands.py, and
// src/sqlfluff/cli/formatters.py.
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The records of a lint (sqlfluff `LintingResult.as_records`,
//! `SQLBaseError.to_dict`, `SQLLintError.to_dict`, `LintFix.to_dict`) and
//! the output formats of `sqll lint`: human, json, yaml,
//! github-annotation, github-annotation-native (src/sqlfluff/cli/
//! commands.py `lint`, src/sqlfluff/cli/formatters.py `format_filename`,
//! `format_violation`, `_format_file_violations`; sqlfluff 4.4.0, MIT, see
//! THIRD_PARTY.md).

use crate::color::{Color, Painter};
use crate::lint::file::{Issue, Kind, Linted, Span};
use crate::pyfmt::float_repr;
use crate::text::split_string_on_spaces;

/// A value of a record (the Python types of `json.dumps` and
/// `yaml.dump`).
#[derive(Clone, Debug, PartialEq)]
pub enum Rec {
    Int(i64),
    Float(f64),
    Bool(bool),
    Str(String),
    List(Vec<Rec>),
    Map(Vec<(String, Rec)>),
}

fn int(n: usize) -> Rec {
    Rec::Int(n as i64)
}

fn s(text: &str) -> Rec {
    Rec::Str(text.to_string())
}

fn span_keys(out: &mut Vec<(String, Rec)>, span: &Span, start: bool) {
    if start {
        out.push(("start_line_no".into(), int(span.start_line)));
        out.push(("start_line_pos".into(), int(span.start_pos)));
    }
    out.push(("start_file_pos".into(), int(span.start_file)));
    out.push(("end_line_no".into(), int(span.end_line)));
    out.push(("end_line_pos".into(), int(span.end_pos)));
    out.push(("end_file_pos".into(), int(span.end_file)));
}

/// The record of a violation (`to_dict`).
pub fn violation(i: &Issue) -> Rec {
    let mut m = vec![
        ("start_line_no".to_string(), int(i.line)),
        ("start_line_pos".to_string(), int(i.pos)),
        ("code".to_string(), s(&i.code)),
        ("description".to_string(), s(&i.description)),
        ("name".to_string(), s(&i.name)),
        ("warning".to_string(), Rec::Bool(i.warning)),
    ];
    if i.kind == Kind::Lint {
        let fixes = i
            .fixes
            .iter()
            .map(|f| {
                let mut d = vec![
                    ("type".to_string(), s(f.edit_type)),
                    ("edit".to_string(), s(&f.edit)),
                ];
                span_keys(&mut d, &f.span, true);
                Rec::Map(d)
            })
            .collect();
        m.push(("fixes".to_string(), Rec::List(fixes)));
    }
    if let Some(span) = &i.span {
        // The start keys are there already (with the same values).
        span_keys(&mut m, span, false);
    }
    Rec::Map(m)
}

/// The violations of a record: no ignored violation, sorted by line,
/// position, and code.
pub fn record_violations(l: &Linted) -> Vec<&Issue> {
    let mut v: Vec<&Issue> = l.violations(false).collect();
    v.sort_by(|a, b| (a.line, a.pos, &a.code).cmp(&(b.line, b.pos, &b.code)));
    v
}

/// The record of a file (`LintedDir.add`).
pub fn file_record(l: &Linted) -> Rec {
    let stats = Rec::Map(vec![
        ("source_chars".into(), int(l.stats.source_chars)),
        ("templated_chars".into(), int(l.stats.templated_chars)),
        ("segments".into(), int(l.stats.segments)),
        ("raw_segments".into(), int(l.stats.raw_segments)),
    ]);
    let timings = Rec::Map(
        l.timings
            .iter()
            .map(|(k, t)| (k.clone(), Rec::Float(*t)))
            .collect(),
    );
    Rec::Map(vec![
        ("filepath".into(), s(&l.path)),
        (
            "violations".into(),
            Rec::List(record_violations(l).into_iter().map(violation).collect()),
        ),
        ("statistics".into(), stats),
        ("timings".into(), timings),
    ])
}

/// Python `json.dumps(value)`.
pub fn json(value: &Rec) -> String {
    let mut out = Vec::new();
    write_json(&mut out, value);
    String::from_utf8(out).expect("JSON is UTF-8")
}

fn write_json(out: &mut Vec<u8>, value: &Rec) {
    match value {
        Rec::Int(i) => out.extend_from_slice(i.to_string().as_bytes()),
        Rec::Float(f) => out.extend_from_slice(float_repr(*f).as_bytes()),
        Rec::Bool(b) => out.extend_from_slice(if *b { b"true" } else { b"false" }),
        Rec::Str(text) => {
            crate::parse::output::write_json_str(out, text).expect("a write to memory")
        }
        Rec::List(items) => {
            out.push(b'[');
            for (n, item) in items.iter().enumerate() {
                if n > 0 {
                    out.extend_from_slice(b", ");
                }
                write_json(out, item);
            }
            out.push(b']');
        }
        Rec::Map(items) => {
            out.push(b'{');
            for (n, (k, v)) in items.iter().enumerate() {
                if n > 0 {
                    out.extend_from_slice(b", ");
                }
                crate::parse::output::write_json_str(out, k).expect("a write to memory");
                out.extend_from_slice(b": ");
                write_json(out, v);
            }
            out.push(b'}');
        }
    }
}

fn get<'r>(map: &'r Rec, key: &str) -> Option<&'r Rec> {
    match map {
        Rec::Map(items) => items.iter().find(|(k, _)| k == key).map(|(_, v)| v),
        _ => None,
    }
}

fn text_of(rec: Option<&Rec>) -> String {
    match rec {
        Some(Rec::Int(i)) => i.to_string(),
        Some(Rec::Str(s)) => s.clone(),
        Some(Rec::Bool(b)) => b.to_string(),
        _ => String::new(),
    }
}

/// The items of the `github-annotation` output for one record: the JSON of
/// each annotation, joined with ", " (the output is a JSON list of them).
pub fn github_annotation_items(r: &Rec, level: &str) -> String {
    let level = if level == "error" { "failure" } else { level };
    let mut out = Vec::new();
    let file = text_of(get(r, "filepath"));
    if let Some(Rec::List(vs)) = get(r, "violations") {
        for v in vs {
            let start_line = get(v, "start_line_no").cloned().expect("a start line");
            let start_pos = get(v, "start_line_pos").cloned().expect("a start position");
            let warning = matches!(get(v, "warning"), Some(Rec::Bool(true)));
            out.push(json(&Rec::Map(vec![
                ("file".into(), s(&file)),
                ("start_line".into(), start_line.clone()),
                ("start_column".into(), start_pos.clone()),
                (
                    "end_line".into(),
                    get(v, "end_line_no").cloned().unwrap_or(start_line),
                ),
                (
                    "end_column".into(),
                    get(v, "end_line_pos").cloned().unwrap_or(start_pos),
                ),
                ("title".into(), s("SQLFluff")),
                (
                    "message".into(),
                    Rec::Str(format!(
                        "{}: {}",
                        text_of(get(v, "code")),
                        text_of(get(v, "description"))
                    )),
                ),
                (
                    "annotation_level".into(),
                    s(if warning { "notice" } else { level }),
                ),
            ])));
        }
    }
    out.join(", ")
}

/// The `github-annotation-native` output (workflow command lines).
pub fn github_annotation_native(records: &[Rec], level: &str) -> String {
    let level = if level == "failure" { "error" } else { level };
    let mut lines = Vec::new();
    for r in records {
        let file = text_of(get(r, "filepath"));
        let Some(Rec::List(vs)) = get(r, "violations") else {
            continue;
        };
        if !vs.is_empty() {
            lines.push(format!("::group::{file}"));
        }
        for v in vs {
            let warning = matches!(get(v, "warning"), Some(Rec::Bool(true)));
            let mut line = if warning {
                "::notice ".to_string()
            } else {
                format!("::{level} ")
            };
            line.push_str("title=SQLFluff,");
            line.push_str(&format!("file={file},"));
            line.push_str(&format!("line={},", text_of(get(v, "start_line_no"))));
            line.push_str(&format!("col={}", text_of(get(v, "start_line_pos"))));
            if let Some(e) = get(v, "end_line_no") {
                line.push_str(&format!(",endLine={}", text_of(Some(e))));
            }
            if let Some(e) = get(v, "end_line_pos") {
                line.push_str(&format!(",endColumn={}", text_of(Some(e))));
            }
            line.push_str("::");
            line.push_str(&format!(
                "{}: {}",
                text_of(get(v, "code")),
                text_of(get(v, "description"))
            ));
            let name = text_of(get(v, "name"));
            if !name.is_empty() {
                line.push_str(&format!(" [{name}]"));
            }
            lines.push(line);
        }
        if !vs.is_empty() {
            lines.push("::endgroup::".to_string());
        }
    }
    lines.join("\n")
}

/// sqlfluff `format_filename`.
pub fn format_filename(p: &Painter, filename: &str, status: &str) -> String {
    let color = match status {
        "PASS" | "FIXED" => Some(Color::Green),
        "FAIL" | "ERROR" => Some(Color::Red),
        _ => None,
    };
    format!(
        "== [{}] {}",
        p.paint(filename, Some(Color::Light)),
        p.paint(status, color)
    )
}

/// The parts of a violation for `format_violation`.
pub struct ViolationText<'a> {
    pub code: &'a str,
    pub name: &'a str,
    pub description: &'a str,
    pub line: Option<usize>,
    pub pos: Option<usize>,
    pub warning: bool,
}

impl<'a> ViolationText<'a> {
    pub fn of(i: &'a Issue) -> Self {
        ViolationText {
            code: &i.code,
            name: &i.name,
            description: &i.description,
            line: Some(i.line),
            pos: Some(i.pos),
            warning: i.warning,
        }
    }
}

/// sqlfluff `format_violation`.
pub fn format_violation(p: &Painter, v: &ViolationText<'_>, max_line_length: usize) -> String {
    let mut desc = v.description.to_string();
    if v.warning {
        desc = format!("WARNING: {desc}");
    }
    if !v.name.is_empty() {
        desc.push_str(&format!(" [{}]", p.paint(v.name, Some(Color::Light))));
    }
    let lines = split_string_on_spaces(&desc, max_line_length.saturating_sub(25));
    let elem = |x: Option<usize>| match x {
        Some(n) => format!("{n:4}"),
        None => "   -".to_string(),
    };
    let mut color = if v.warning { Color::Light } else { Color::Blue };
    let mut out = String::new();
    for (idx, line) in lines.iter().enumerate() {
        if idx == 0 {
            let code = format!("{:>4}", v.code);
            if code.contains("PRS") {
                color = Color::Red;
            }
            out.push_str(&p.paint(
                &format!("L:{} | P:{} | {code} | ", elem(v.line), elem(v.pos)),
                Some(color),
            ));
        } else {
            out.push('\n');
            out.push_str(&" ".repeat(23));
            out.push_str(&p.paint("| ", Some(color)));
        }
        out.push_str(line);
    }
    out
}

/// sqlfluff `_format_file_violations`: the file line and the violations,
/// or an empty text if the file has no violation to show.
pub fn format_file_violations(
    p: &Painter,
    fname: &str,
    violations: &[&Issue],
    max_line_length: usize,
) -> String {
    let fails = violations
        .iter()
        .filter(|v| !v.ignore && !v.warning)
        .count();
    let warns = violations.iter().filter(|v| v.warning).count();
    if fails + warns == 0 {
        return String::new();
    }
    let mut out = format_filename(p, fname, if fails == 0 { "PASS" } else { "FAIL" });
    let mut sorted: Vec<&&Issue> = violations.iter().collect();
    sorted.sort_by_key(|v| (v.line, v.pos));
    for v in sorted {
        out.push('\n');
        out.push_str(&format_violation(p, &ViolationText::of(v), max_line_length));
    }
    out
}
