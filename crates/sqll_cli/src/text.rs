// Parts of this file are a port of sqlfluff 4.4.0 code:
// src/sqlfluff/cli/helpers.py (wrap_field, pad_line) and
// src/sqlfluff/cli/formatters.py (cli_table_row, cli_table,
// split_string_on_spaces). The file also ports CPython code (below).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The text layout of the sqlfluff CLI: the tables of `rules` and
//! `dialects`, and the lines of a violation.
//!
//! Ports:
//!
//! - `wrap`: Python `textwrap.wrap(text, width)` with the default settings
//!   (Lib/textwrap.py of CPython, https://github.com/python/cpython, tag
//!   v3.13.16, commit cbc944f4bc59639a444dd971c737788ba2283a91: `_munge_whitespace`,
//!   `wordsep_re`, `_split`, `_wrap_chunks`, `_handle_long_word`).
//!   Copyright (c) 2001-2024 Python Software Foundation; All Rights
//!   Reserved. PSF License Version 2: see crates/LICENSE-cpython.txt.
//! - `wrap_field`, `pad_line` (src/sqlfluff/cli/helpers.py), `cli_table_row`,
//!   `cli_table`, `split_string_on_spaces` (src/sqlfluff/cli/formatters.py)
//!   of sqlfluff 4.4.0 (https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
//!   commit 0348222a3bcdb0226563f7349c5a39beb0641955). Copyright (c)
//!   2018-2026 Alan Cruickshank. MIT License: see crates/LICENSE-sqlfluffrs.md.
//!
//! See THIRD_PARTY.md. Changes: Rust in place of Python. A length is a
//! count of characters (Unicode scalar values), as Python `len`.

use std::sync::OnceLock;

use fancy_regex::Regex;

use crate::color::{Color, Painter};

/// The whitespace of Python textwrap (`_whitespace`).
const WHITESPACE: &str = "\t\n\u{b}\u{c}\r ";

/// `TextWrapper.wordsep_re` (verbose mode removed; `\Z` is `\z`).
fn wordsep_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        let wp = r#"[\w!"'&.,?]"#;
        let lt = r"[^\d\W]";
        let ws = r"[\t\n\x0b\x0c\r ]";
        let nws = r"[^\t\n\x0b\x0c\r ]";
        let pattern = format!(
            "({ws}+|(?<={wp})-{{2,}}(?=\\w)|{nws}+?(?:-(?:(?<={lt}{{2}}-)|(?<={lt}-{lt}-))(?={lt}-?{lt})|(?={ws}|\\z)|(?<={wp})(?=-{{2,}}\\w)))"
        );
        Regex::new(&pattern).expect("the textwrap regex")
    })
}

fn len(s: &str) -> usize {
    s.chars().count()
}

/// Python `str.expandtabs(8)`.
fn expandtabs(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut column = 0;
    for c in text.chars() {
        match c {
            '\t' => {
                let n = 8 - column % 8;
                out.extend(std::iter::repeat_n(' ', n));
                column += n;
            }
            '\n' | '\r' => {
                out.push(c);
                column = 0;
            }
            c => {
                out.push(c);
                column += 1;
            }
        }
    }
    out
}

/// The chunks of `_split`: whitespace, words, and the parts of hyphenated
/// words.
fn split_chunks(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut last = 0;
    for m in wordsep_re().find_iter(text) {
        let m = m.expect("the textwrap regex runs");
        if m.start() > last {
            out.push(text[last..m.start()].to_string());
        }
        out.push(m.as_str().to_string());
        last = m.end();
    }
    if last < text.len() {
        out.push(text[last..].to_string());
    }
    out.retain(|c| !c.is_empty());
    out
}

fn is_blank(chunk: &str) -> bool {
    chunk.chars().all(char::is_whitespace)
}

/// Python `textwrap.wrap(text, width)`.
pub fn wrap(text: &str, width: usize) -> Vec<String> {
    let munged: String = expandtabs(text)
        .chars()
        .map(|c| if WHITESPACE.contains(c) { ' ' } else { c })
        .collect();
    let mut chunks = split_chunks(&munged);
    chunks.reverse();
    let mut lines: Vec<String> = Vec::new();
    while !chunks.is_empty() {
        let mut cur_line: Vec<String> = Vec::new();
        let mut cur_len = 0;
        if is_blank(chunks.last().expect("a chunk")) && !lines.is_empty() {
            chunks.pop();
        }
        while let Some(chunk) = chunks.last() {
            let l = len(chunk);
            if cur_len + l <= width {
                cur_len += l;
                cur_line.push(chunks.pop().expect("a chunk"));
            } else {
                break;
            }
        }
        if chunks.last().is_some_and(|c| len(c) > width) {
            handle_long_word(&mut chunks, &mut cur_line, cur_len, width);
        }
        if cur_line.last().is_some_and(|c| is_blank(c)) {
            cur_line.pop();
        }
        if !cur_line.is_empty() {
            lines.push(cur_line.concat());
        }
    }
    lines
}

fn handle_long_word(
    chunks: &mut [String],
    cur_line: &mut Vec<String>,
    cur_len: usize,
    width: usize,
) {
    let space_left = if width < 1 { 1 } else { width - cur_len };
    if space_left == 0 {
        return;
    }
    let chunk: Vec<char> = chunks.last().expect("a chunk").chars().collect();
    let mut end = space_left;
    if chunk.len() > space_left {
        if let Some(hyphen) = chunk[..space_left].iter().rposition(|&c| c == '-') {
            if hyphen > 0 && chunk[..hyphen].iter().any(|&c| c != '-') {
                end = hyphen + 1;
            }
        }
    }
    let end = end.min(chunk.len());
    cur_line.push(chunk[..end].iter().collect());
    *chunks.last_mut().expect("a chunk") = chunk[end..].iter().collect();
}

/// sqlfluff `pad_line`.
pub fn pad_line(s: &str, width: usize, right: bool) -> String {
    let n = len(s);
    if n >= width {
        return s.to_string();
    }
    let gap = " ".repeat(width - n);
    if right {
        gap + s
    } else {
        s.to_string() + &gap
    }
}

/// sqlfluff `wrap_field`.
struct Field {
    labels: Vec<String>,
    values: Vec<String>,
    label_width: usize,
    value_width: usize,
}

fn wrap_field(label: &str, value: &str, width: usize, max_label_width: usize) -> Field {
    let (labels, label_width) = if len(label) > max_label_width {
        let labels = wrap(label, max_label_width);
        let w = labels.iter().map(|l| len(l)).max().unwrap_or(0);
        (labels, w)
    } else {
        (vec![label.to_string()], len(label))
    };
    // ": " is the separator of each table of sqll.
    let value_width = width.saturating_sub(2 + label_width).max(1);
    let mut values = Vec::new();
    for v in value.split('\n') {
        values.extend(wrap(v, value_width));
    }
    Field {
        labels,
        values,
        label_width,
        value_width,
    }
}

/// sqlfluff `cli_table` with one column (`cols=1`): each (label, value)
/// pair on its lines, the labels in `label_color`.
pub fn cli_table(
    painter: &Painter,
    fields: &[(String, String)],
    col_width: usize,
    max_label_width: usize,
    label_color: Color,
    value_right: bool,
) -> String {
    let mut out = String::new();
    for (i, (label, value)) in fields.iter().enumerate() {
        let f = wrap_field(label, value, col_width, max_label_width);
        let lines = f.labels.len().max(f.values.len());
        for line in 0..lines {
            let l = f.labels.get(line).map_or("", String::as_str);
            out.push_str(&painter.paint(&pad_line(l, f.label_width, false), Some(label_color)));
            out.push_str(if line == 0 { ": " } else { "  " });
            let v = f.values.get(line).map_or("", String::as_str);
            out.push_str(&pad_line(v, f.value_width, value_right));
            if line + 1 < lines {
                out.push('\n');
            }
        }
        if i + 1 < fields.len() {
            out.push('\n');
        }
    }
    out
}

/// sqlfluff `split_string_on_spaces`.
pub fn split_string_on_spaces(s: &str, line_length: usize) -> Vec<String> {
    let mut lines = Vec::new();
    let mut buff = String::new();
    for token in s.split(' ') {
        if !buff.is_empty() {
            if len(&buff) + len(token) > line_length {
                lines.push(std::mem::take(&mut buff));
                buff.push_str(token);
            } else {
                buff.push(' ');
                buff.push_str(token);
            }
        } else {
            buff.push_str(token);
        }
    }
    if !buff.is_empty() {
        lines.push(buff);
    }
    lines
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wrap_is_that_of_python_textwrap() {
        // The values of Python 3.13 textwrap.wrap.
        let cases: &[(&str, usize, &[&str])] = &[
            ("materialize", 10, &["materializ", "e"]),
            (
                "Hello there -- you goof-ball, use the -b option!",
                12,
                &[
                    "Hello there",
                    "-- you goof-",
                    "ball, use",
                    "the -b",
                    "option!",
                ],
            ),
            (
                "Microsoft T-SQL dialect [inherits from 'ansi']",
                20,
                &["Microsoft T-SQL", "dialect [inherits", "from 'ansi']"],
            ),
            ("a\tb  c", 4, &["a", "b  c"]),
            ("", 10, &[]),
            ("   ", 10, &[]),
            ("  lead", 10, &["  lead"]),
            ("x---y", 2, &["x-", "--", "y"]),
        ];
        for (text, width, want) in cases {
            assert_eq!(wrap(text, *width), *want, "{text:?} {width}");
        }
    }

    #[test]
    fn split_on_spaces_is_that_of_sqlfluff() {
        assert_eq!(split_string_on_spaces("abc", 100), ["abc"]);
        assert_eq!(split_string_on_spaces("abc def ghi", 7), ["abc def", "ghi"]);
        assert_eq!(
            split_string_on_spaces("a '   ' b c d e f", 11),
            ["a '   ' b c", "d e f"]
        );
    }
}
