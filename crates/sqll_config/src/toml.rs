// This file is a port of two sources:
//
// 1. Lib/tomllib (_parser.py and _re.py) of CPython
//    (https://github.com/python/cpython), tag v3.13.16, commit
//    cbc944f4bc59639a444dd971c737788ba2283a91.
//    SPDX-License-Identifier: MIT. SPDX-FileCopyrightText: 2021 Taneli
//    Hukkinen. Licensed to PSF under a Contributor Agreement. The MIT
//    license text: crates/LICENSE-tomli.txt.
// 2. sqlfluff 4.4.0 code: src/sqlfluff/core/config/toml.py
//    (load_toml_file_config, _validate_structure, _validate_value,
//    _condense_rule_record, _format_toml_parse_error).
//    Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
//    commit 0348222a3bcdb0226563f7349c5a39beb0641955.
//    Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
//    crates/LICENSE-sqlfluffrs.md.
//
// See THIRD_PARTY.md. Changes: Rust in place of Python; the parser works on
// the characters of the text; a date or time value is checked but not kept,
// and it fails closed in `[tool.sqlfluff]` (sqlfluff makes it a str); an int
// must fit in an i64.

//! The TOML reader of sqlfluff (`pyproject.toml`, `[tool.sqlfluff]`).

use std::collections::{HashMap, HashSet};

use crate::dict::{records_to_nested_dict, Record};
use crate::value::{Table, Value};
use crate::ConfigError;

/// A TOML value as tomllib gives it. A table keeps the order of its keys.
#[derive(Clone, Debug, PartialEq)]
enum TVal {
    Str(String),
    Int(i64),
    Float(f64),
    Bool(bool),
    Array(Vec<TVal>),
    Table(OMap),
    /// A date, a date and time, or a time. sqll does not keep its value.
    DateTime,
}

type OMap = Vec<(String, TVal)>;
type Key = Vec<String>;

/// The error of a parse: a TOML error at a place, or a value that sqll
/// cannot read.
#[derive(Debug)]
enum TomlError {
    Decode(String),
    Unsupported(String),
}

type Res<T> = Result<T, TomlError>;

const MAX_KEY_PARTS: usize = 1000;
const FROZEN: u8 = 1;
const EXPLICIT_NEST: u8 = 2;

fn is_ascii_ctrl(c: char) -> bool {
    (c as u32) < 32 || c as u32 == 127
}
fn illegal_basic(c: char) -> bool {
    is_ascii_ctrl(c) && c != '\t'
}
fn illegal_multiline(c: char) -> bool {
    is_ascii_ctrl(c) && c != '\t' && c != '\n'
}
fn is_ws(c: char) -> bool {
    c == ' ' || c == '\t'
}
fn is_ws_nl(c: char) -> bool {
    c == ' ' || c == '\t' || c == '\n'
}
fn is_bare_key(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '-' || c == '_'
}

#[derive(Default)]
struct FlagNode {
    flags: u8,
    recursive: u8,
    nested: HashMap<String, FlagNode>,
}

#[derive(Default)]
struct Flags {
    root: HashMap<String, FlagNode>,
    pending: HashSet<(Key, u8)>,
}

impl Flags {
    fn add_pending(&mut self, key: Key, flag: u8) {
        self.pending.insert((key, flag));
    }

    fn finalize_pending(&mut self) {
        for (key, flag) in std::mem::take(&mut self.pending) {
            self.set(&key, flag, false);
        }
    }

    fn unset_all(&mut self, key: &[String]) {
        let (stem, parent) = key.split_last().expect("a key");
        let mut cont = &mut self.root;
        for k in parent {
            match cont.get_mut(k) {
                Some(node) => cont = &mut node.nested,
                None => return,
            }
        }
        cont.remove(stem);
    }

    fn set(&mut self, key: &[String], flag: u8, recursive: bool) {
        let mut cont = &mut self.root;
        let (stem, parent) = key.split_last().expect("a key");
        for k in parent {
            cont = &mut cont.entry(k.clone()).or_default().nested;
        }
        let node = cont.entry(stem.clone()).or_default();
        if recursive {
            node.recursive |= flag;
        } else {
            node.flags |= flag;
        }
    }

    fn is(&self, key: &[String], flag: u8) -> bool {
        let Some((stem, parent)) = key.split_last() else {
            return false;
        };
        let mut cont = &self.root;
        for k in parent {
            let Some(inner) = cont.get(k) else {
                return false;
            };
            if inner.recursive & flag != 0 {
                return true;
            }
            cont = &inner.nested;
        }
        cont.get(stem)
            .is_some_and(|n| (n.flags | n.recursive) & flag != 0)
    }
}

fn lookup<'a>(map: &'a mut OMap, k: &str) -> Option<&'a mut TVal> {
    map.iter_mut().find(|(n, _)| n == k).map(|(_, v)| v)
}

/// `NestedDict.get_or_create_nest`: Err is the KeyError of tomllib.
fn get_or_create_nest<'a>(
    root: &'a mut OMap,
    key: &[String],
    access_lists: bool,
) -> Result<&'a mut OMap, ()> {
    let mut cont = root;
    for k in key {
        if !cont.iter().any(|(n, _)| n == k) {
            cont.push((k.clone(), TVal::Table(Vec::new())));
        }
        let v = lookup(cont, k).expect("added");
        let is_list = matches!(v, TVal::Array(_));
        let v = if access_lists && is_list {
            match v {
                TVal::Array(items) => items.last_mut().ok_or(())?,
                _ => unreachable!(),
            }
        } else {
            v
        };
        match v {
            TVal::Table(t) => cont = t,
            _ => return Err(()),
        }
    }
    Ok(cont)
}

fn append_nest_to_list(root: &mut OMap, key: &[String]) -> Result<(), ()> {
    let (last, parent) = key.split_last().expect("a key");
    let cont = get_or_create_nest(root, parent, true)?;
    match lookup(cont, last) {
        Some(TVal::Array(items)) => items.push(TVal::Table(Vec::new())),
        Some(_) => return Err(()),
        None => cont.push((last.clone(), TVal::Array(vec![TVal::Table(Vec::new())]))),
    }
    Ok(())
}

struct Parser {
    src: Vec<char>,
}

impl Parser {
    fn at(&self, pos: usize) -> Option<char> {
        self.src.get(pos).copied()
    }

    fn starts_with(&self, pos: usize, text: &str) -> bool {
        let mut i = pos;
        for c in text.chars() {
            if self.at(i) != Some(c) {
                return false;
            }
            i += 1;
        }
        true
    }

    fn err(&self, pos: usize, msg: &str) -> TomlError {
        let coord = if pos >= self.src.len() {
            "end of document".to_string()
        } else {
            let before = &self.src[..pos];
            let line = before.iter().filter(|c| **c == '\n').count() + 1;
            let column = match before.iter().rposition(|c| *c == '\n') {
                None => pos + 1,
                Some(nl) => pos - nl,
            };
            format!("line {line}, column {column}")
        };
        TomlError::Decode(format!("{msg} (at {coord})"))
    }

    fn skip_chars(&self, mut pos: usize, chars: fn(char) -> bool) -> usize {
        while self.at(pos).is_some_and(chars) {
            pos += 1;
        }
        pos
    }

    fn skip_until(
        &self,
        pos: usize,
        expect: &str,
        error_on: fn(char) -> bool,
        error_on_eof: bool,
    ) -> Res<usize> {
        let mut new_pos = pos;
        let found = loop {
            if new_pos >= self.src.len() {
                break false;
            }
            if self.starts_with(new_pos, expect) {
                break true;
            }
            new_pos += 1;
        };
        if !found {
            new_pos = self.src.len();
            if error_on_eof {
                return Err(self.err(new_pos, &format!("Expected {expect:?}")));
            }
        }
        if let Some(i) = (pos..new_pos).find(|i| error_on(self.src[*i])) {
            return Err(self.err(i, &format!("Found invalid character {:?}", self.src[i])));
        }
        Ok(new_pos)
    }

    fn skip_comment(&self, pos: usize) -> Res<usize> {
        if self.at(pos) == Some('#') {
            return self.skip_until(pos + 1, "\n", illegal_basic, false);
        }
        Ok(pos)
    }

    fn skip_comments_and_array_ws(&self, mut pos: usize) -> Res<usize> {
        loop {
            let before = pos;
            pos = self.skip_chars(pos, is_ws_nl);
            pos = self.skip_comment(pos)?;
            if pos == before {
                return Ok(pos);
            }
        }
    }

    fn loads(&self) -> Res<OMap> {
        let mut pos = 0;
        let mut data: OMap = Vec::new();
        let mut flags = Flags::default();
        let mut header: Key = Vec::new();
        loop {
            pos = self.skip_chars(pos, is_ws);
            let Some(c) = self.at(pos) else { break };
            if c == '\n' {
                pos += 1;
                continue;
            }
            if is_bare_key(c) || c == '"' || c == '\'' {
                pos = self.key_value_rule(pos, &mut data, &mut flags, &header)?;
                pos = self.skip_chars(pos, is_ws);
            } else if c == '[' {
                flags.finalize_pending();
                let (p, h) = if self.at(pos + 1) == Some('[') {
                    self.create_list_rule(pos, &mut data, &mut flags)?
                } else {
                    self.create_dict_rule(pos, &mut data, &mut flags)?
                };
                header = h;
                pos = self.skip_chars(p, is_ws);
            } else if c != '#' {
                return Err(self.err(pos, "Invalid statement"));
            }
            pos = self.skip_comment(pos)?;
            let Some(c) = self.at(pos) else { break };
            if c != '\n' {
                return Err(self.err(pos, "Expected newline or end of document after a statement"));
            }
            pos += 1;
        }
        Ok(data)
    }

    fn create_dict_rule(
        &self,
        pos: usize,
        data: &mut OMap,
        flags: &mut Flags,
    ) -> Res<(usize, Key)> {
        let pos = self.skip_chars(pos + 1, is_ws);
        let (pos, key) = self.parse_key(pos)?;
        if flags.is(&key, EXPLICIT_NEST) || flags.is(&key, FROZEN) {
            return Err(self.err(pos, &format!("Cannot declare {} twice", key_repr(&key))));
        }
        flags.set(&key, EXPLICIT_NEST, false);
        if get_or_create_nest(data, &key, true).is_err() {
            return Err(self.err(pos, "Cannot overwrite a value"));
        }
        if !self.starts_with(pos, "]") {
            return Err(self.err(pos, "Expected ']' at the end of a table declaration"));
        }
        Ok((pos + 1, key))
    }

    fn create_list_rule(
        &self,
        pos: usize,
        data: &mut OMap,
        flags: &mut Flags,
    ) -> Res<(usize, Key)> {
        let pos = self.skip_chars(pos + 2, is_ws);
        let (pos, key) = self.parse_key(pos)?;
        if flags.is(&key, FROZEN) {
            return Err(self.err(
                pos,
                &format!("Cannot mutate immutable namespace {}", key_repr(&key)),
            ));
        }
        flags.unset_all(&key);
        flags.set(&key, EXPLICIT_NEST, false);
        if append_nest_to_list(data, &key).is_err() {
            return Err(self.err(pos, "Cannot overwrite a value"));
        }
        if !self.starts_with(pos, "]]") {
            return Err(self.err(pos, "Expected ']]' at the end of an array declaration"));
        }
        Ok((pos + 2, key))
    }

    fn key_value_rule(
        &self,
        pos: usize,
        data: &mut OMap,
        flags: &mut Flags,
        header: &Key,
    ) -> Res<usize> {
        let (pos, key, value) = self.parse_key_value_pair(pos)?;
        let (stem, parent) = key.split_last().expect("a key");
        let mut abs_parent = header.clone();
        abs_parent.extend(parent.iter().cloned());
        for i in 1..key.len() {
            let mut cont_key = header.clone();
            cont_key.extend(key[..i].iter().cloned());
            if flags.is(&cont_key, EXPLICIT_NEST) {
                return Err(self.err(
                    pos,
                    &format!("Cannot redefine namespace {}", key_repr(&cont_key)),
                ));
            }
            flags.add_pending(cont_key, EXPLICIT_NEST);
        }
        if flags.is(&abs_parent, FROZEN) {
            return Err(self.err(
                pos,
                &format!(
                    "Cannot mutate immutable namespace {}",
                    key_repr(&abs_parent)
                ),
            ));
        }
        let Ok(nest) = get_or_create_nest(data, &abs_parent, true) else {
            return Err(self.err(pos, "Cannot overwrite a value"));
        };
        if nest.iter().any(|(n, _)| n == stem) {
            return Err(self.err(pos, "Cannot overwrite a value"));
        }
        if matches!(value, TVal::Table(_) | TVal::Array(_)) {
            let mut full = header.clone();
            full.extend(key.iter().cloned());
            flags.set(&full, FROZEN, true);
        }
        nest.push((stem.clone(), value));
        Ok(pos)
    }

    fn parse_key_value_pair(&self, pos: usize) -> Res<(usize, Key, TVal)> {
        let (pos, key) = self.parse_key(pos)?;
        if self.at(pos) != Some('=') {
            return Err(self.err(pos, "Expected '=' after a key in a key/value pair"));
        }
        let pos = self.skip_chars(pos + 1, is_ws);
        let (pos, value) = self.parse_value(pos)?;
        Ok((pos, key, value))
    }

    fn parse_key(&self, pos: usize) -> Res<(usize, Key)> {
        let (mut pos, part) = self.parse_key_part(pos)?;
        let mut key = vec![part];
        pos = self.skip_chars(pos, is_ws);
        loop {
            if self.at(pos) != Some('.') {
                return Ok((pos, key));
            }
            pos = self.skip_chars(pos + 1, is_ws);
            let (p, part) = self.parse_key_part(pos)?;
            key.push(part);
            if key.len() > MAX_KEY_PARTS {
                return Err(TomlError::Decode(format!(
                    "TOML key has more than the allowed {MAX_KEY_PARTS} parts"
                )));
            }
            pos = self.skip_chars(p, is_ws);
        }
    }

    fn parse_key_part(&self, pos: usize) -> Res<(usize, String)> {
        match self.at(pos) {
            Some(c) if is_bare_key(c) => {
                let end = self.skip_chars(pos, is_bare_key);
                Ok((end, self.src[pos..end].iter().collect()))
            }
            Some('\'') => self.parse_literal_str(pos),
            Some('"') => self.parse_basic_str(pos + 1, false),
            _ => Err(self.err(pos, "Invalid initial character for a key part")),
        }
    }

    fn parse_array(&self, pos: usize) -> Res<(usize, TVal)> {
        let mut pos = self.skip_comments_and_array_ws(pos + 1)?;
        let mut array = Vec::new();
        if self.starts_with(pos, "]") {
            return Ok((pos + 1, TVal::Array(array)));
        }
        loop {
            let (p, val) = self.parse_value(pos)?;
            array.push(val);
            pos = self.skip_comments_and_array_ws(p)?;
            match self.at(pos) {
                Some(']') => return Ok((pos + 1, TVal::Array(array))),
                Some(',') => {}
                _ => return Err(self.err(pos, "Unclosed array")),
            }
            pos = self.skip_comments_and_array_ws(pos + 1)?;
            if self.starts_with(pos, "]") {
                return Ok((pos + 1, TVal::Array(array)));
            }
        }
    }

    fn parse_inline_table(&self, pos: usize) -> Res<(usize, TVal)> {
        let mut pos = self.skip_chars(pos + 1, is_ws);
        let mut table: OMap = Vec::new();
        let mut flags = Flags::default();
        if self.starts_with(pos, "}") {
            return Ok((pos + 1, TVal::Table(table)));
        }
        loop {
            let (p, key, value) = self.parse_key_value_pair(pos)?;
            pos = p;
            let (stem, parent) = key.split_last().expect("a key");
            if flags.is(&key, FROZEN) {
                return Err(self.err(
                    pos,
                    &format!("Cannot mutate immutable namespace {}", key_repr(&key)),
                ));
            }
            let Ok(nest) = get_or_create_nest(&mut table, parent, false) else {
                return Err(self.err(pos, "Cannot overwrite a value"));
            };
            if nest.iter().any(|(n, _)| n == stem) {
                return Err(self.err(pos, &format!("Duplicate inline table key {stem:?}")));
            }
            let nested = matches!(value, TVal::Table(_) | TVal::Array(_));
            nest.push((stem.clone(), value));
            pos = self.skip_chars(pos, is_ws);
            match self.at(pos) {
                Some('}') => return Ok((pos + 1, TVal::Table(table))),
                Some(',') => {}
                _ => return Err(self.err(pos, "Unclosed inline table")),
            }
            if nested {
                flags.set(&key, FROZEN, true);
            }
            pos = self.skip_chars(pos + 1, is_ws);
        }
    }

    fn parse_basic_str_escape(&self, mut pos: usize, multiline: bool) -> Res<(usize, String)> {
        let first = self.at(pos + 1);
        pos += 2;
        if multiline && matches!(first, Some(' ' | '\t' | '\n')) {
            if first != Some('\n') {
                pos = self.skip_chars(pos, is_ws);
                match self.at(pos) {
                    None => return Ok((pos, String::new())),
                    Some('\n') => pos += 1,
                    Some(_) => return Err(self.err(pos, "Unescaped '\\' in a string")),
                }
            }
            pos = self.skip_chars(pos, is_ws_nl);
            return Ok((pos, String::new()));
        }
        let replacement = match first {
            Some('u') => return self.parse_hex_char(pos, 4),
            Some('U') => return self.parse_hex_char(pos, 8),
            Some('b') => '\u{8}',
            Some('t') => '\t',
            Some('n') => '\n',
            Some('f') => '\u{c}',
            Some('r') => '\r',
            Some('"') => '"',
            Some('\\') => '\\',
            _ => return Err(self.err(pos, "Unescaped '\\' in a string")),
        };
        Ok((pos, replacement.to_string()))
    }

    fn parse_hex_char(&self, pos: usize, len: usize) -> Res<(usize, String)> {
        let end = (pos + len).min(self.src.len());
        let hex: String = self.src[pos..end].iter().collect();
        if hex.chars().count() != len || !hex.chars().all(|c| c.is_ascii_hexdigit()) {
            return Err(self.err(pos, "Invalid hex value"));
        }
        let pos = pos + len;
        let value = u32::from_str_radix(&hex, 16).expect("hex digits");
        match char::from_u32(value) {
            Some(c) => Ok((pos, c.to_string())),
            None => Err(self.err(pos, "Escaped character is not a Unicode scalar value")),
        }
    }

    fn parse_literal_str(&self, pos: usize) -> Res<(usize, String)> {
        let start = pos + 1;
        let end = self.skip_until(start, "'", illegal_basic, true)?;
        Ok((end + 1, self.src[start..end].iter().collect()))
    }

    fn parse_multiline_str(&self, pos: usize, literal: bool) -> Res<(usize, TVal)> {
        let mut pos = pos + 3;
        if self.starts_with(pos, "\n") {
            pos += 1;
        }
        let (delim, mut result);
        if literal {
            delim = '\'';
            let end = self.skip_until(pos, "'''", illegal_multiline, true)?;
            result = self.src[pos..end].iter().collect::<String>();
            pos = end + 3;
        } else {
            delim = '"';
            let (p, r) = self.parse_basic_str(pos, true)?;
            pos = p;
            result = r;
        }
        for _ in 0..2 {
            if self.at(pos) != Some(delim) {
                break;
            }
            pos += 1;
            result.push(delim);
        }
        Ok((pos, TVal::Str(result)))
    }

    fn parse_basic_str(&self, mut pos: usize, multiline: bool) -> Res<(usize, String)> {
        let error_on = if multiline {
            illegal_multiline
        } else {
            illegal_basic
        };
        let mut result = String::new();
        let mut start = pos;
        loop {
            let Some(c) = self.at(pos) else {
                return Err(self.err(pos, "Unterminated string"));
            };
            if c == '"' {
                if !multiline {
                    result.extend(&self.src[start..pos]);
                    return Ok((pos + 1, result));
                }
                if self.starts_with(pos, "\"\"\"") {
                    result.extend(&self.src[start..pos]);
                    return Ok((pos + 3, result));
                }
                pos += 1;
                continue;
            }
            if c == '\\' {
                result.extend(&self.src[start..pos]);
                let (p, escaped) = self.parse_basic_str_escape(pos, multiline)?;
                result.push_str(&escaped);
                pos = p;
                start = pos;
                continue;
            }
            if error_on(c) {
                return Err(self.err(pos, &format!("Illegal character {c:?}")));
            }
            pos += 1;
        }
    }

    fn parse_value(&self, pos: usize) -> Res<(usize, TVal)> {
        let c = self.at(pos);
        match c {
            Some('"') => {
                if self.starts_with(pos, "\"\"\"") {
                    return self.parse_multiline_str(pos, false);
                }
                let (p, s) = self.parse_basic_str(pos + 1, false)?;
                return Ok((p, TVal::Str(s)));
            }
            Some('\'') => {
                if self.starts_with(pos, "'''") {
                    return self.parse_multiline_str(pos, true);
                }
                let (p, s) = self.parse_literal_str(pos)?;
                return Ok((p, TVal::Str(s)));
            }
            Some('t') if self.starts_with(pos, "true") => return Ok((pos + 4, TVal::Bool(true))),
            Some('f') if self.starts_with(pos, "false") => return Ok((pos + 5, TVal::Bool(false))),
            Some('[') => return self.parse_array(pos),
            Some('{') => return self.parse_inline_table(pos),
            _ => {}
        }
        if let Some((end, valid)) = self.match_datetime(pos) {
            if !valid {
                return Err(self.err(pos, "Invalid date or datetime"));
            }
            return Ok((end, TVal::DateTime));
        }
        if let Some(end) = self.match_time(pos) {
            return Ok((end, TVal::DateTime));
        }
        if let Some(end) = self.match_number(pos) {
            let text: String = self.src[pos..end.0].iter().collect();
            return Ok((end.0, number_value(&text, end.1)?));
        }
        let three: String = self.src[pos..(pos + 3).min(self.src.len())]
            .iter()
            .collect();
        if three == "inf" || three == "nan" {
            let f = if three == "inf" {
                f64::INFINITY
            } else {
                f64::NAN
            };
            return Ok((pos + 3, TVal::Float(f)));
        }
        let four: String = self.src[pos..(pos + 4).min(self.src.len())]
            .iter()
            .collect();
        match four.as_str() {
            "-inf" => return Ok((pos + 4, TVal::Float(f64::NEG_INFINITY))),
            "+inf" => return Ok((pos + 4, TVal::Float(f64::INFINITY))),
            "-nan" | "+nan" => return Ok((pos + 4, TVal::Float(f64::NAN))),
            _ => {}
        }
        Err(self.err(pos, "Invalid value"))
    }

    fn digits(&self, pos: usize, n: usize) -> bool {
        (pos..pos + n).all(|i| self.at(i).is_some_and(|c| c.is_ascii_digit()))
    }

    fn two_digits_in(&self, pos: usize, lo: u32, hi: u32) -> bool {
        self.digits(pos, 2) && {
            let v =
                self.src[pos].to_digit(10).unwrap() * 10 + self.src[pos + 1].to_digit(10).unwrap();
            (lo..=hi).contains(&v)
        }
    }

    fn number_at(&self, pos: usize, n: usize) -> u32 {
        self.src[pos..pos + n]
            .iter()
            .fold(0, |v, c| v * 10 + c.to_digit(10).expect("a digit"))
    }

    /// A match of `RE_DATETIME` here: its end, and false if
    /// `match_to_datetime` gives a `ValueError` (a year 0, or a day after
    /// the end of the month).
    fn match_datetime(&self, pos: usize) -> Option<(usize, bool)> {
        let date = self.digits(pos, 4)
            && self.at(pos + 4) == Some('-')
            && self.two_digits_in(pos + 5, 1, 12)
            && self.at(pos + 7) == Some('-')
            && self.two_digits_in(pos + 8, 1, 31);
        if !date {
            return None;
        }
        let year = self.number_at(pos, 4);
        let month = self.number_at(pos + 5, 2);
        let day = self.number_at(pos + 8, 2);
        let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
        let days = match month {
            2 if leap => 29,
            2 => 28,
            4 | 6 | 9 | 11 => 30,
            _ => 31,
        };
        let valid = year >= 1 && day <= days;
        let mut end = pos + 10;
        if matches!(self.at(end), Some('T' | 't' | ' ')) {
            if let Some(t) = self.match_time(end + 1) {
                end = t;
                if matches!(self.at(end), Some('Z' | 'z')) {
                    end += 1;
                } else if matches!(self.at(end), Some('+' | '-'))
                    && self.two_digits_in(end + 1, 0, 23)
                    && self.at(end + 3) == Some(':')
                    && self.two_digits_in(end + 4, 0, 59)
                {
                    end += 6;
                }
            }
        }
        Some((end, valid))
    }

    /// A match of `RE_LOCALTIME` here: its end.
    fn match_time(&self, pos: usize) -> Option<usize> {
        let time = self.two_digits_in(pos, 0, 23)
            && self.at(pos + 2) == Some(':')
            && self.two_digits_in(pos + 3, 0, 59)
            && self.at(pos + 5) == Some(':')
            && self.two_digits_in(pos + 6, 0, 59);
        if !time {
            return None;
        }
        let mut end = pos + 8;
        if self.at(end) == Some('.') && self.digits(end + 1, 1) {
            end += 2;
            while self.at(end).is_some_and(|c| c.is_ascii_digit()) {
                end += 1;
            }
        }
        Some(end)
    }

    /// Digits of `digit` with single "_" between them, from pos: the end.
    fn underscored(&self, pos: usize, digit: fn(char) -> bool) -> Option<usize> {
        if !self.at(pos).is_some_and(digit) {
            return None;
        }
        let mut end = pos + 1;
        loop {
            if self.at(end).is_some_and(digit) {
                end += 1;
            } else if self.at(end) == Some('_') && self.at(end + 1).is_some_and(digit) {
                end += 2;
            } else {
                return Some(end);
            }
        }
    }

    /// `RE_NUMBER` at pos: the end, and true if it has a float part.
    fn match_number(&self, pos: usize) -> Option<(usize, bool)> {
        if self.at(pos) == Some('0') {
            let radix: Option<fn(char) -> bool> = match self.at(pos + 1) {
                Some('x') => Some(|c: char| c.is_ascii_hexdigit()),
                Some('b') => Some(|c: char| c == '0' || c == '1'),
                Some('o') => Some(|c: char| ('0'..='7').contains(&c)),
                _ => None,
            };
            if let Some(end) = radix.and_then(|d| self.underscored(pos + 2, d)) {
                return Some((end, false));
            }
        }
        let mut i = pos;
        if matches!(self.at(i), Some('+' | '-')) {
            i += 1;
        }
        let digit = |c: char| c.is_ascii_digit();
        i = match self.at(i) {
            Some('0') => i + 1,
            Some('1'..='9') => self.underscored(i, digit)?,
            _ => return None,
        };
        let int_end = i;
        if self.at(i) == Some('.') {
            if let Some(end) = self.underscored(i + 1, digit) {
                i = end;
            }
        }
        if matches!(self.at(i), Some('e' | 'E')) {
            let mut j = i + 1;
            if matches!(self.at(j), Some('+' | '-')) {
                j += 1;
            }
            if let Some(end) = self.underscored(j, digit) {
                i = end;
            }
        }
        Some((i, i != int_end))
    }
}

fn number_value(text: &str, float: bool) -> Res<TVal> {
    let clean: String = text.chars().filter(|c| *c != '_').collect();
    if float {
        return Ok(TVal::Float(
            clean.parse().expect("a TOML float is a Rust float"),
        ));
    }
    let (radix, digits) = match clean.get(..2) {
        Some("0x") => (16, &clean[2..]),
        Some("0b") => (2, &clean[2..]),
        Some("0o") => (8, &clean[2..]),
        _ => (10, clean.as_str()),
    };
    i64::from_str_radix(digits, radix)
        .map(TVal::Int)
        .map_err(|_| {
            TomlError::Unsupported(format!(
                "the TOML int {text}: sqll reads only an int from -2**63 to 2**63-1"
            ))
        })
}

fn key_repr(key: &[String]) -> String {
    let parts: Vec<String> = key.iter().map(|k| format!("'{k}'")).collect();
    if parts.len() == 1 {
        format!("({},)", parts[0])
    } else {
        format!("({})", parts.join(", "))
    }
}

/// The context sections, where the lists keep their nested values.
const CONTEXT_PATHS: [[&str; 3]; 3] = [
    ["templater", "jinja", "context"],
    ["templater", "python", "context"],
    ["templater", "dbt", "context"],
];

fn in_context(path: &[String]) -> bool {
    path.len() >= 3
        && CONTEXT_PATHS
            .iter()
            .any(|c| c.iter().zip(path).all(|(a, b)| a == b))
}

fn date_unsupported(path: &[String]) -> ConfigError {
    ConfigError::Unsupported(format!(
        "setting {}: a TOML date or time value: sqll does not read it (sqlfluff makes it a str)",
        path.join(":")
    ))
}

/// `_validate_value` of sqlfluff: a table is a section, a list outside a
/// context has the `str` of each item.
fn validate_value(value: &TVal, path: &[String]) -> Result<Value, ConfigError> {
    Ok(match value {
        TVal::DateTime => return Err(date_unsupported(path)),
        TVal::Table(t) => Value::Table(validate_structure(t, path)?),
        TVal::Array(items) if in_context(path) => Value::List(
            items
                .iter()
                .map(|i| validate_value(i, path))
                .collect::<Result<_, _>>()?,
        ),
        TVal::Array(items) => Value::List(
            items
                .iter()
                .map(|i| {
                    if *i == TVal::DateTime {
                        return Err(date_unsupported(path));
                    }
                    let v = scalar(i).ok_or_else(|| {
                        ConfigError::Unsupported(format!(
                            "setting {}: a TOML array or table in a list (sqlfluff makes it a str)",
                            path.join(":")
                        ))
                    })?;
                    Ok(Value::Str(v.py_str().expect("a scalar")))
                })
                .collect::<Result<_, ConfigError>>()?,
        ),
        other => scalar(other).expect("a scalar"),
    })
}

fn scalar(value: &TVal) -> Option<Value> {
    Some(match value {
        TVal::Str(s) => Value::Str(s.clone()),
        TVal::Int(i) => Value::Int(*i),
        TVal::Float(f) => Value::Float(*f),
        TVal::Bool(b) => Value::Bool(*b),
        TVal::Array(_) | TVal::Table(_) | TVal::DateTime => return None,
    })
}

fn validate_structure(table: &OMap, path: &[String]) -> Result<Table, ConfigError> {
    let mut out = Table::new();
    for (key, value) in table {
        let mut p = path.to_vec();
        p.push(key.clone());
        out.insert(key.clone(), validate_value(value, &p)?);
    }
    Ok(out)
}

/// The records of a table in order (`iter_records_from_nested_dict`),
/// each value as `_validate_value` gives it.
fn rule_records(
    table: &OMap,
    prefix: &mut Vec<String>,
    out: &mut Vec<Record>,
) -> Result<(), ConfigError> {
    for (key, value) in table {
        prefix.push(key.clone());
        match value {
            TVal::Table(t) => rule_records(t, prefix, out)?,
            v => {
                let mut full = vec!["rules".to_string()];
                full.extend(prefix.iter().cloned());
                out.push((prefix.clone(), validate_value(v, &full)?));
            }
        }
        prefix.pop();
    }
    Ok(())
}

fn decode_error(filepath: &str, raw: &str, message: &str) -> ConfigError {
    // _format_toml_parse_error: the place of the error as "at line L,
    // column C", and a hint for a byte order mark.
    let (message, location) = match message.rsplit_once(" (at line ") {
        Some((m, rest)) if rest.ends_with(')') => (
            m.to_string(),
            format!(" at line {}", &rest[..rest.len() - 1]),
        ),
        _ => (message.to_string(), String::new()),
    };
    let hint = if raw.starts_with('\u{feff}') {
        " pyproject.toml contains a UTF-8 BOM; save it as UTF-8 without BOM."
    } else {
        ""
    };
    ConfigError::Invalid(format!(
        "Failed to parse TOML config file {filepath}: {message}{location}.{hint}"
    ))
}

/// Read the `[tool.sqlfluff]` table of a pyproject.toml text as sqlfluff
/// does (`load_toml_file_config`): each table is a section, a list outside
/// a templater context has the `str` of each item, and the rule names of
/// `rules` keep their dots.
pub fn load_toml_string(text: &str, filepath: &str) -> Result<Table, ConfigError> {
    let src: Vec<char> = text.replace("\r\n", "\n").chars().collect();
    let doc = match (Parser { src }).loads() {
        Ok(doc) => doc,
        Err(TomlError::Decode(m)) => return Err(decode_error(filepath, text, &m)),
        Err(TomlError::Unsupported(m)) => return Err(ConfigError::Unsupported(m)),
    };
    let invalid = |what: &str| ConfigError::Invalid(format!("{filepath}: {what}"));
    let sqlfluff = match doc.iter().find(|(k, _)| k == "tool") {
        None => return Ok(Table::new()),
        Some((_, TVal::Table(tool))) => match tool.iter().find(|(k, _)| k == "sqlfluff") {
            None => return Ok(Table::new()),
            Some((_, TVal::Table(t))) => t,
            Some(_) => return Err(invalid("tool.sqlfluff is not a table")),
        },
        Some(_) => return Err(invalid("tool is not a table")),
    };
    let mut config = Table::new();
    for (key, value) in sqlfluff {
        if key == "rules" {
            let TVal::Table(rules) = value else {
                return Err(ConfigError::Invalid(format!(
                    "Config file {filepath} set an invalid `rules` value: {}. In \
                     `pyproject.toml`, per-rule config must be set with a table per rule, \
                     e.g. `[tool.sqlfluff.rules.<rule_name>]`, rather than as a plain value \
                     under `[tool.sqlfluff]`.",
                    scalar(value).map_or("[...]".to_string(), |v| v.to_string())
                )));
            };
            let mut records = Vec::new();
            rule_records(rules, &mut Vec::new(), &mut records)?;
            let condensed = records.into_iter().map(|(key, value)| {
                if key.len() > 2 {
                    let (last, head) = key.split_last().expect("a key");
                    (vec![head.join("."), last.clone()], value)
                } else {
                    (key, value)
                }
            });
            config.insert(
                key.clone(),
                Value::Table(records_to_nested_dict(condensed)?),
            );
        } else {
            config.insert(
                key.clone(),
                validate_value(value, std::slice::from_ref(key))?,
            );
        }
    }
    Ok(config)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(text: &str) -> Res<OMap> {
        Parser {
            src: text.chars().collect(),
        }
        .loads()
    }

    fn s(v: &str) -> TVal {
        TVal::Str(v.to_string())
    }

    #[test]
    fn values_of_tomllib() {
        let doc = parse(
            "a = 1\nb = -0x_1\nc = 0x1F\nd = 0o17\ne = 0b101\nf = 1_000.5e-1_0\ng = \"x\\ty\\u00e9\"\nh = 'lit\\'\ni = \"\"\"\nline1\\\n   line2\"\"\"\"\nj = '''a'''''\nk = [1, [2], {x = 3},]\nl = { y.z = true }\nm = -inf\nn = 1e5\n",
        );
        assert!(doc.is_err(), "b: 0x_1 is not a number");
        let doc = parse(
            "a = 1\nc = 0x1F\nd = 0o17\ne = 0b101\nf = 1_000.5e-1_0\ng = \"x\\ty\\u00e9\"\nh = 'lit\\'\ni = \"\"\"\nline1\\\n   line2\"\"\"\"\nj = '''a'''''\nk = [1, [2], {x = 3},]\nl = { y.z = true }\nm = -inf\nn = 1e5\n",
        )
        .unwrap();
        let get = |k: &str| doc.iter().find(|(n, _)| n == k).unwrap().1.clone();
        assert_eq!(get("a"), TVal::Int(1));
        assert_eq!(get("c"), TVal::Int(31));
        assert_eq!(get("d"), TVal::Int(15));
        assert_eq!(get("e"), TVal::Int(5));
        assert_eq!(get("f"), TVal::Float(1000.5e-10));
        assert_eq!(get("g"), s("x\ty\u{e9}"));
        assert_eq!(get("h"), s("lit\\"));
        assert_eq!(get("i"), s("line1line2\""));
        assert_eq!(get("j"), s("a''"));
        assert_eq!(
            get("k"),
            TVal::Array(vec![
                TVal::Int(1),
                TVal::Array(vec![TVal::Int(2)]),
                TVal::Table(vec![("x".to_string(), TVal::Int(3))])
            ])
        );
        assert_eq!(
            get("l"),
            TVal::Table(vec![(
                "y".to_string(),
                TVal::Table(vec![("z".to_string(), TVal::Bool(true))])
            )])
        );
        assert_eq!(get("m"), TVal::Float(f64::NEG_INFINITY));
        assert_eq!(get("n"), TVal::Float(1e5));
    }

    #[test]
    fn tables_and_errors_of_tomllib() {
        let doc = parse("[a.b]\nc = 1\n[a]\nd = 2\n[[e]]\nf = 1\n[[e]]\nf = 2\n").unwrap();
        assert_eq!(doc.len(), 2);
        for bad in [
            "a = 1\na = 2\n",
            "[a]\n[a]\n",
            "a = {b = 1}\n[a]\n",
            "a.b = 1\n[a]\n",
            "a = [1,,2]\n",
            "a = \"x\n",
            "a = 012\n",
            "a = 1 b = 2\n",
            "\u{feff}a = 1\n",
            "a = \"\\x\"\n",
            "= 1\n",
        ] {
            assert!(parse(bad).is_err(), "{bad:?}");
        }
    }

    #[test]
    fn sqlfluff_structure_of_the_toml_fixture() {
        // test/fixtures/config/toml/pyproject.toml of sqlfluff and the
        // expected dict of test__config__load_toml (loader_test.py).
        let text = "[tool.sqlfluff.core]\nnocolor = true\nverbose = 2\ntesting_int = 5\ntesting_bar = 7.698\ntesting_bool = false\ntesting_arr = [ \"a\", \"b\", \"c\" ]\ntesting_inline_table = { x = 1 }\nrules = [\"LT03\", \"LT09\"]\n\n[tool.sqlfluff.bar]\nfoo = \"foobar\"\n\n[tool.sqlfluff.fnarr.fnarr]\nfoo = \"foobar\"\n\n[tool.sqlfluff.rules.capitalisation.keywords]\ncapitalisation_policy = \"upper\"\n";
        let t = load_toml_string(text, "pyproject.toml").unwrap();
        let get = |p: &[&str]| crate::dict::get(&t, p).cloned();
        assert_eq!(get(&["core", "verbose"]), Some(Value::Int(2)));
        assert_eq!(get(&["core", "testing_bar"]), Some(Value::Float(7.698)));
        assert_eq!(
            get(&["core", "rules"]),
            Some(Value::List(vec![Value::str("LT03"), Value::str("LT09")]))
        );
        assert_eq!(
            get(&["core", "testing_inline_table", "x"]),
            Some(Value::Int(1))
        );
        assert_eq!(get(&["fnarr", "fnarr", "foo"]), Some(Value::str("foobar")));
        assert_eq!(
            get(&["rules", "capitalisation.keywords", "capitalisation_policy"]),
            Some(Value::str("upper"))
        );
        // Lists outside a context have the str of each item.
        let t = load_toml_string(
            "[tool.sqlfluff.core]\nrules = [1, 2.5, true]\n[tool.sqlfluff.templater.jinja.context]\nv = [1, \"2\"]\n",
            "pyproject.toml",
        )
        .unwrap();
        assert_eq!(
            crate::dict::get(&t, &["core", "rules"]),
            Some(&Value::List(vec![
                Value::str("1"),
                Value::str("2.5"),
                Value::str("True")
            ]))
        );
        assert_eq!(
            crate::dict::get(&t, &["templater", "jinja", "context", "v"]),
            Some(&Value::List(vec![Value::Int(1), Value::str("2")]))
        );
        assert!(load_toml_string("[tool.sqlfluff]\nrules = \"all\"\n", "p").is_err());
        assert_eq!(
            load_toml_string("[tool.black]\nx = 1\n", "p").unwrap(),
            Table::new()
        );
    }

    /// A date or time outside `[tool.sqlfluff]` is read as tomllib reads
    /// it; in `[tool.sqlfluff]` it fails closed. An invalid date is a
    /// decode error, as `match_to_datetime` gives a `ValueError`.
    #[test]
    fn dates_and_times() {
        let doc = parse(
            "a = 1979-05-27\nb = 1979-05-27T07:32:00Z\nc = 1979-05-27 07:32:00.999999-07:00\nd = 07:32:00.5\ne = [1979-05-27t00:00:00+23:59, 2000-02-29]\nf = 1\n",
        )
        .unwrap();
        let keys: Vec<&str> = doc.iter().map(|(k, _)| k.as_str()).collect();
        assert_eq!(keys, ["a", "b", "c", "d", "e", "f"]);
        assert_eq!(doc[0].1, TVal::DateTime);
        assert_eq!(doc[5].1, TVal::Int(1));
        for bad in [
            "a = 1979-02-29\n",
            "a = 2100-02-29\n",
            "a = 1979-04-31\n",
            "a = 0000-01-01\n",
        ] {
            let Err(TomlError::Decode(m)) = parse(bad) else {
                panic!("{bad:?}")
            };
            assert!(
                m.starts_with("Invalid date or datetime (at line 1, column 5)"),
                "{m}"
            );
        }
        // A date with text after it is not a value.
        assert!(parse("a = 1979-05-27x\n").is_err());
        let t = load_toml_string(
            "[tool.other]\nx = 1979-05-27\n[tool.sqlfluff.core]\ndialect = \"ansi\"\n",
            "pyproject.toml",
        )
        .unwrap();
        assert_eq!(
            crate::dict::get(&t, &["core", "dialect"]),
            Some(&Value::str("ansi"))
        );
        for text in [
            "[tool.sqlfluff.core]\nd = 1979-05-27\n",
            "[tool.sqlfluff.core]\nd = [07:32:00]\n",
            "[tool.sqlfluff.templater.jinja.context]\nd = [1979-05-27]\n",
            "[tool.sqlfluff.rules.x]\nd = 1979-05-27\n",
        ] {
            assert!(
                matches!(
                    load_toml_string(text, "p"),
                    Err(ConfigError::Unsupported(_))
                ),
                "{text:?}"
            );
        }
    }
}
