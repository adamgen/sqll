// This file is a port of two sources:
//
// 1. sqlfluff 4.4.0 code: src/sqlfluff/core/config/ini.py
//    (load_ini_string). Source: https://github.com/sqlfluff/sqlfluff, tag
//    4.4.0, commit 0348222a3bcdb0226563f7349c5a39beb0641955.
//    Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
//    crates/LICENSE-sqlfluffrs.md.
// 2. The reader of RawConfigParser in Lib/configparser.py of CPython
//    (https://github.com/python/cpython), tag v3.13.16, commit
//    cbc944f4bc59639a444dd971c737788ba2283a91 (_read_inner,
//    _handle_continuation_line, _handle_rest, _handle_header,
//    _handle_option, _join_multiline_values, items, _Line).
//    Copyright (c) 2001-2024 Python Software Foundation; All Rights
//    Reserved. PSF License Version 2: see crates/LICENSE-cpython.txt.
//
// See THIRD_PARTY.md. Changes: Rust in place of Python; only the settings
// that sqlfluff uses (delimiter "=", comment prefixes "#" and ";", no
// inline comments, strict, empty lines in values, no interpolation, the
// option names keep their case); an error stops the read.

//! The INI reader of sqlfluff (`.sqlfluff`, `setup.cfg`, `tox.ini`,
//! `pep8.ini`, and each `--config` file that is not `pyproject.toml`).

use std::collections::HashSet;

use crate::dict::{records_to_nested_dict, Record};
use crate::value::{coerce_value, py_isspace, py_rstrip, py_strip, Table};
use crate::ConfigError;

const DEFAULT_SECTION: &str = "DEFAULT";

/// The options of a section, in the order of their first line. `None` is
/// not possible: sqlfluff does not allow an option with no value.
type Options = Vec<(String, Vec<String>)>;

struct Parsed {
    defaults: Options,
    sections: Vec<(String, Options)>,
}

fn error(name: &str, lineno: usize, what: &str) -> ConfigError {
    ConfigError::Invalid(format!("{name}, line {lineno}: {what}"))
}

/// Read the text as RawConfigParser of sqlfluff does. `name` names the
/// source in messages.
fn read(text: &str, name: &str) -> Result<Parsed, ConfigError> {
    let mut parsed = Parsed {
        defaults: Vec::new(),
        sections: Vec::new(),
    };
    // None: no section yet. Some(None): DEFAULT. Some(Some(i)): section i.
    let mut cursect: Option<Option<usize>> = None;
    let mut sectname = String::new();
    let mut optname: Option<String> = None;
    let mut indent_level = 0usize;
    let mut added: HashSet<(String, Option<String>)> = HashSet::new();
    let mut errors = Vec::new();

    for (index, line) in text.split_inclusive('\n').enumerate() {
        let lineno = index + 1;
        let stripped = py_strip(line);
        let comment = stripped.starts_with('#') || stripped.starts_with(';');
        let clean = if comment { "" } else { stripped };
        if clean.is_empty() {
            // An empty line (not a comment) is part of a value.
            if !comment {
                if let (Some(sect), Some(opt)) = (cursect, optname.as_deref()) {
                    if !opt.is_empty() {
                        options_mut(&mut parsed, sect)
                            .iter_mut()
                            .find(|(k, _)| k == opt)
                            .expect("the current option exists")
                            .1
                            .push(String::new());
                    }
                }
            }
            continue;
        }
        let cur_indent_level = line.chars().take_while(|c| py_isspace(*c)).count();

        // A continuation line?
        if let (Some(sect), Some(opt)) = (cursect, optname.as_deref()) {
            if !opt.is_empty() && cur_indent_level > indent_level {
                options_mut(&mut parsed, sect)
                    .iter_mut()
                    .find(|(k, _)| k == opt)
                    .expect("the current option exists")
                    .1
                    .push(clean.to_string());
                continue;
            }
        }

        indent_level = cur_indent_level;
        let header = section_header(clean);
        if header.is_none() && cursect.is_none() {
            return Err(error(
                name,
                lineno,
                &format!("File contains no section headers: {line:?}"),
            ));
        }
        if let Some(header) = header {
            sectname = header.to_string();
            if parsed.sections.iter().any(|(s, _)| *s == sectname) {
                return Err(error(
                    name,
                    lineno,
                    &format!("section {sectname:?} already exists"),
                ));
            }
            if sectname == DEFAULT_SECTION {
                cursect = Some(None);
            } else {
                parsed.sections.push((sectname.clone(), Vec::new()));
                cursect = Some(Some(parsed.sections.len() - 1));
                added.insert((sectname.clone(), None));
            }
            optname = None;
            continue;
        }

        // An option line.
        let sect = cursect.expect("a section");
        let Some(eq) = clean.find('=') else {
            errors.push(error(
                name,
                lineno,
                &format!("Source contains parsing errors: {line:?}"),
            ));
            continue;
        };
        let opt = py_rstrip(&clean[..eq]).to_string();
        if opt.is_empty() {
            errors.push(error(
                name,
                lineno,
                &format!("Source contains parsing errors: {line:?}"),
            ));
        }
        let key = (sectname.clone(), Some(opt.clone()));
        if added.contains(&key) {
            return Err(error(
                name,
                lineno,
                &format!("option {opt:?} in section {sectname:?} already exists"),
            ));
        }
        added.insert(key);
        let value = py_strip(&clean[eq + 1..]).to_string();
        let options = options_mut(&mut parsed, sect);
        match options.iter_mut().find(|(k, _)| *k == opt) {
            Some(entry) => entry.1 = vec![value],
            None => options.push((opt.clone(), vec![value])),
        }
        optname = Some(opt);
    }
    if let Some(e) = errors.into_iter().next() {
        return Err(e);
    }
    Ok(parsed)
}

fn options_mut(parsed: &mut Parsed, sect: Option<usize>) -> &mut Options {
    match sect {
        None => &mut parsed.defaults,
        Some(i) => &mut parsed.sections[i].1,
    }
}

/// The header of a section line (`\[(?P<header>.+)\]`, matched at the
/// start): the text from the first "[" to the last "]".
fn section_header(clean: &str) -> Option<&str> {
    let rest = clean.strip_prefix('[')?;
    let end = rest.rfind(']')?;
    (end > 0).then(|| &rest[..end])
}

/// A value of several lines: the lines joined with "\n", with no space at
/// the end.
fn join(lines: &[String]) -> String {
    py_rstrip(&lines.join("\n")).to_string()
}

/// The records of an INI text as sqlfluff reads them (`load_ini_string`):
/// `[sqlfluff]` is `core`, `[sqlfluff:a:b]` is the section path `a`, `b`,
/// an option name is split on ".", and each value is coerced
/// ([`coerce_value`]). The options of `[DEFAULT]` are in each section.
pub fn ini_records(text: &str, name: &str) -> Result<Vec<Record>, ConfigError> {
    if text.is_empty() {
        return Ok(Vec::new());
    }
    let parsed = read(text, name)?;
    let mut records = Vec::new();
    for (section, options) in &parsed.sections {
        let prefix: Vec<String> = if section == "sqlfluff" {
            vec!["core".to_string()]
        } else if let Some(rest) = section.strip_prefix("sqlfluff:") {
            rest.split(':').map(str::to_string).collect()
        } else {
            continue;
        };
        // RawConfigParser.items: the defaults, then the options of the
        // section (an option of the section replaces a default).
        let mut items: Vec<(&str, &[String])> = parsed
            .defaults
            .iter()
            .map(|(k, v)| (k.as_str(), v.as_slice()))
            .collect();
        for (k, v) in options {
            match items.iter_mut().find(|(name, _)| name == k) {
                Some(item) => item.1 = v,
                None => items.push((k, v)),
            }
        }
        for (option, lines) in items {
            let mut path = prefix.clone();
            path.extend(option.split('.').map(str::to_string));
            records.push((path, coerce_value(&join(lines))?));
        }
    }
    Ok(records)
}

/// Read an INI text as sqlfluff does (`load_ini_string`).
pub fn load_ini_string(text: &str, name: &str) -> Result<Table, ConfigError> {
    records_to_nested_dict(ini_records(text, name)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::value::Value;

    fn get<'a>(t: &'a Table, path: &[&str]) -> Option<&'a Value> {
        crate::dict::get(t, path)
    }

    #[test]
    fn sections_options_and_types() {
        let t = load_ini_string(
            "[sqlfluff]\ndialect=mysql\ntesting_val=foobar\ntesting_int=4\n\n[sqlfluff:bar]\nfoo=barbar\n",
            "x",
        )
        .unwrap();
        assert_eq!(get(&t, &["core", "dialect"]), Some(&Value::str("mysql")));
        assert_eq!(get(&t, &["core", "testing_int"]), Some(&Value::Int(4)));
        assert_eq!(get(&t, &["bar", "foo"]), Some(&Value::str("barbar")));
    }

    #[test]
    fn multiline_values_comments_and_empty_lines() {
        let text = "# c\n[sqlfluff:layout:type:orderby_clause]\nkeyword_line_position_exclusions =\n    window_specification,\n    ; a comment\n\n    aggregate_order_by\n\nline_position = leading\n";
        let t = load_ini_string(text, "x").unwrap();
        assert_eq!(
            get(
                &t,
                &[
                    "layout",
                    "type",
                    "orderby_clause",
                    "keyword_line_position_exclusions"
                ]
            ),
            Some(&Value::str("\nwindow_specification,\n\naggregate_order_by"))
        );
        assert_eq!(
            get(&t, &["layout", "type", "orderby_clause", "line_position"]),
            Some(&Value::str("leading"))
        );
    }

    #[test]
    fn dotted_names_default_section_and_other_sections() {
        let text = "[DEFAULT]\nshared = 1\n[tool]\nx = 2\n[sqlfluff:templater:jinja:context]\nnamespace.projectname=test\nshared = 3\n";
        let t = load_ini_string(text, "x").unwrap();
        assert_eq!(
            get(
                &t,
                &["templater", "jinja", "context", "namespace", "projectname"]
            ),
            Some(&Value::str("test"))
        );
        assert_eq!(
            get(&t, &["templater", "jinja", "context", "shared"]),
            Some(&Value::Int(3))
        );
        assert!(t.get("tool").is_none());
    }

    #[test]
    fn errors_of_configparser() {
        for text in [
            "x = 1\n",
            "[a]\nx = 1\n[a]\n",
            "[a]\nx = 1\nx = 2\n",
            "[a]\nno delimiter\n",
            "[a]\n= 1\n",
            "\u{feff}[sqlfluff]\n",
        ] {
            assert!(load_ini_string(text, "x").is_err(), "{text:?}");
        }
        assert_eq!(load_ini_string("", "x").unwrap(), Table::new());
        // A header ends at the last "]".
        let t = load_ini_string("[sqlfluff:a]b] # c\nk = v\n", "x").unwrap();
        assert_eq!(get(&t, &["a]b", "k"]), Some(&Value::str("v")));
    }
}
