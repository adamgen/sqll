//! The YAML output of `sqll lint -f yaml`: `yaml.dump(records,
//! sort_keys=False, allow_unicode=True)` of PyYAML 6.0.3 (the version in
//! the tool venv of sqlfluff 4.4.0).
//!
//! Port of parts of PyYAML 6.0.3 (https://github.com/yaml/pyyaml, tag
//! 6.0.3): yaml/emitter.py (`Emitter`: the block and flow states that a
//! record uses, `increase_indent`, `write_indicator`, `write_indent`,
//! `write_line_break`, `analyze_scalar`, `choose_scalar_style`,
//! `write_plain`, `write_single_quoted`, `write_double_quoted`),
//! yaml/resolver.py (the implicit resolvers of a plain scalar), and
//! yaml/representer.py (`represent_float`, `represent_bool`,
//! `represent_int`). Copyright (c) 2017-2021 Ingy döt Net, Copyright (c)
//! 2006-2016 Kirill Simonov. MIT License: see crates/LICENSE-pyyaml.txt.
//! See THIRD_PARTY.md. Changes: Rust in place of Python; only the values of
//! a record (no anchor, tag, alias, folded or literal scalar, no canonical
//! form); recursion in place of the state stack.

use std::sync::OnceLock;

use regex::Regex;

use crate::lint::record::Rec;
use crate::pyfmt::float_repr;

const BEST_INDENT: usize = 2;
const BEST_WIDTH: usize = 80;

/// The implicit resolvers of `Resolver` (YAML 1.1): a plain text that one
/// of them matches is not a string.
fn resolvers() -> &'static [(&'static str, Regex)] {
    static RE: OnceLock<Vec<(&'static str, Regex)>> = OnceLock::new();
    RE.get_or_init(|| {
        let r = |chars: &'static str, p: &str| (chars, Regex::new(p).expect("a resolver regex"));
        vec![
            r(
                "yYnNtTfFoO",
                r"^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)\n?\z",
            ),
            r(
                "-+0123456789.",
                r"^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))\n?\z",
            ),
            r(
                "-+0123456789",
                r"^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)\n?\z",
            ),
            r("<", r"^(?:<<)\n?\z"),
            r("~nN", r"^(?:~|null|Null|NULL|)\n?\z"),
            r(
                "0123456789",
                r"^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)\n?\z",
            ),
            r("=", r"^(?:=)\n?\z"),
            r("!&*", r"^(?:!|&|\*)\n?\z"),
        ]
    })
}

/// True if a plain scalar of the text is a string (`resolve` gives the
/// default tag): the `implicit[0]` of a string.
fn plain_is_str(text: &str) -> bool {
    let first = text.chars().next();
    for (chars, re) in resolvers() {
        let applies = match first {
            None => chars.contains('~'),
            Some(c) => chars.contains(c),
        };
        if applies && re.is_match(text) {
            return false;
        }
    }
    true
}

#[derive(Default)]
struct Analysis {
    empty: bool,
    multiline: bool,
    allow_flow_plain: bool,
    allow_block_plain: bool,
    allow_single_quoted: bool,
}

const SPACE_OR_BREAK: &str = "\0 \t\r\n\u{85}\u{2028}\u{2029}";
const BREAKS: &str = "\n\u{85}\u{2028}\u{2029}";

/// `Emitter.analyze_scalar` (allow_unicode).
fn analyze(scalar: &str) -> Analysis {
    if scalar.is_empty() {
        return Analysis {
            empty: true,
            multiline: false,
            allow_flow_plain: false,
            allow_block_plain: true,
            allow_single_quoted: true,
        };
    }
    let chars: Vec<char> = scalar.chars().collect();
    let mut block_indicators = false;
    let mut flow_indicators = false;
    let mut line_breaks = false;
    let mut special_characters = false;
    let mut leading_space = false;
    let mut leading_break = false;
    let mut trailing_space = false;
    let mut trailing_break = false;
    let mut break_space = false;
    let mut space_break = false;
    if scalar.starts_with("---") || scalar.starts_with("...") {
        block_indicators = true;
        flow_indicators = true;
    }
    let mut preceded_by_whitespace = true;
    let mut followed_by_whitespace = chars.len() == 1 || SPACE_OR_BREAK.contains(chars[1]);
    let mut previous_space = false;
    let mut previous_break = false;
    let n = chars.len();
    for index in 0..n {
        let ch = chars[index];
        if index == 0 {
            if "#,[]{}&*!|>'\"%@`".contains(ch) {
                flow_indicators = true;
                block_indicators = true;
            }
            if "?:".contains(ch) {
                flow_indicators = true;
                if followed_by_whitespace {
                    block_indicators = true;
                }
            }
            if ch == '-' && followed_by_whitespace {
                flow_indicators = true;
                block_indicators = true;
            }
        } else {
            if ",?[]{}".contains(ch) {
                flow_indicators = true;
            }
            if ch == ':' {
                flow_indicators = true;
                if followed_by_whitespace {
                    block_indicators = true;
                }
            }
            if ch == '#' && preceded_by_whitespace {
                flow_indicators = true;
                block_indicators = true;
            }
        }
        if BREAKS.contains(ch) {
            line_breaks = true;
        }
        if !(ch == '\n' || ('\x20'..='\x7e').contains(&ch)) {
            let unicode = (ch == '\u{85}'
                || ('\u{a0}'..='\u{d7ff}').contains(&ch)
                || ('\u{e000}'..='\u{fffd}').contains(&ch)
                || ('\u{10000}'..'\u{10ffff}').contains(&ch))
                && ch != '\u{feff}';
            if !unicode {
                special_characters = true;
            }
        }
        if ch == ' ' {
            if index == 0 {
                leading_space = true;
            }
            if index == n - 1 {
                trailing_space = true;
            }
            if previous_break {
                break_space = true;
            }
            previous_space = true;
            previous_break = false;
        } else if BREAKS.contains(ch) {
            if index == 0 {
                leading_break = true;
            }
            if index == n - 1 {
                trailing_break = true;
            }
            if previous_space {
                space_break = true;
            }
            previous_space = false;
            previous_break = true;
        } else {
            previous_space = false;
            previous_break = false;
        }
        preceded_by_whitespace = SPACE_OR_BREAK.contains(ch);
        followed_by_whitespace = index + 2 >= n || SPACE_OR_BREAK.contains(chars[index + 2]);
    }
    let mut a = Analysis {
        empty: false,
        multiline: line_breaks,
        allow_flow_plain: true,
        allow_block_plain: true,
        allow_single_quoted: true,
    };
    if leading_space || leading_break || trailing_space || trailing_break {
        a.allow_flow_plain = false;
        a.allow_block_plain = false;
    }
    if break_space {
        a.allow_flow_plain = false;
        a.allow_block_plain = false;
        a.allow_single_quoted = false;
    }
    if space_break || special_characters {
        a.allow_flow_plain = false;
        a.allow_block_plain = false;
        a.allow_single_quoted = false;
    }
    if line_breaks {
        a.allow_flow_plain = false;
        a.allow_block_plain = false;
    }
    if flow_indicators {
        a.allow_flow_plain = false;
    }
    if block_indicators {
        a.allow_block_plain = false;
    }
    a
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Style {
    Plain,
    Single,
    Double,
}

struct Emitter {
    out: String,
    column: usize,
    whitespace: bool,
    indention: bool,
    indent: Option<usize>,
    indents: Vec<Option<usize>>,
    flow_level: usize,
}

impl Emitter {
    fn write(&mut self, data: &str) {
        self.column += data.chars().count();
        self.out.push_str(data);
    }

    fn increase_indent(&mut self, flow: bool, indentless: bool) {
        self.indents.push(self.indent);
        match self.indent {
            None => self.indent = Some(if flow { BEST_INDENT } else { 0 }),
            Some(i) if !indentless => self.indent = Some(i + BEST_INDENT),
            Some(_) => {}
        }
    }

    fn pop_indent(&mut self) {
        self.indent = self.indents.pop().expect("an indent");
    }

    fn write_indicator(
        &mut self,
        indicator: &str,
        need_whitespace: bool,
        whitespace: bool,
        indention: bool,
    ) {
        let data = if self.whitespace || !need_whitespace {
            indicator.to_string()
        } else {
            format!(" {indicator}")
        };
        self.whitespace = whitespace;
        self.indention = self.indention && indention;
        self.write(&data);
    }

    fn write_indent(&mut self) {
        let indent = self.indent.unwrap_or(0);
        if !self.indention || self.column > indent || (self.column == indent && !self.whitespace) {
            self.write_line_break(None);
        }
        if self.column < indent {
            self.whitespace = true;
            let data = " ".repeat(indent - self.column);
            self.out.push_str(&data);
            self.column = indent;
        }
    }

    fn write_line_break(&mut self, data: Option<char>) {
        self.whitespace = true;
        self.indention = true;
        self.column = 0;
        self.out.push(data.unwrap_or('\n'));
    }

    /// `expect_node` of a value.
    fn node(&mut self, value: &Rec, mapping: bool, simple_key: bool) {
        match value {
            Rec::List(items) if !items.is_empty() && self.flow_level == 0 => {
                let indentless = mapping && !self.indention;
                self.increase_indent(false, indentless);
                for item in items {
                    self.write_indent();
                    self.write_indicator("-", true, false, true);
                    self.node(item, false, false);
                }
                self.pop_indent();
            }
            Rec::Map(items) if !items.is_empty() && self.flow_level == 0 => {
                self.increase_indent(false, false);
                for (k, v) in items {
                    self.write_indent();
                    // Each key of a record is a short simple key.
                    self.node(&Rec::Str(k.clone()), true, true);
                    self.write_indicator(":", false, false, false);
                    self.node(v, true, false);
                }
                self.pop_indent();
            }
            Rec::List(items) => self.flow(items.is_empty(), "[", "]"),
            Rec::Map(items) => self.flow(items.is_empty(), "{", "}"),
            scalar => {
                self.increase_indent(true, false);
                self.scalar(scalar, simple_key);
                self.pop_indent();
            }
        }
    }

    /// An empty flow collection (each other value of a record has block
    /// style).
    fn flow(&mut self, empty: bool, open: &str, close: &str) {
        assert!(empty, "a record has no flow collection with items");
        self.write_indicator(open, true, true, false);
        self.flow_level += 1;
        self.increase_indent(true, false);
        self.pop_indent();
        self.flow_level -= 1;
        self.write_indicator(close, false, false, false);
    }

    fn scalar(&mut self, value: &Rec, simple_key: bool) {
        let (text, implicit_plain) = match value {
            Rec::Str(s) => (s.clone(), plain_is_str(s)),
            Rec::Int(i) => (i.to_string(), true),
            Rec::Bool(b) => ((if *b { "true" } else { "false" }).to_string(), true),
            Rec::Float(f) => (represent_float(*f), true),
            _ => unreachable!("a scalar"),
        };
        let a = analyze(&text);
        let style = if implicit_plain
            && !(simple_key && (a.empty || a.multiline))
            && ((self.flow_level > 0 && a.allow_flow_plain)
                || (self.flow_level == 0 && a.allow_block_plain))
        {
            Style::Plain
        } else if a.allow_single_quoted && !(simple_key && a.multiline) {
            Style::Single
        } else {
            Style::Double
        };
        let split = !simple_key;
        match style {
            Style::Plain => self.write_plain(&text, split),
            Style::Single => self.write_single_quoted(&text, split),
            Style::Double => self.write_double_quoted(&text, split),
        }
    }

    fn write_plain(&mut self, text: &str, split: bool) {
        if text.is_empty() {
            return;
        }
        if !self.whitespace {
            self.write(" ");
        }
        self.whitespace = false;
        self.indention = false;
        let chars: Vec<char> = text.chars().collect();
        let mut spaces = false;
        let mut breaks = false;
        let (mut start, mut end) = (0, 0);
        while end <= chars.len() {
            let ch = chars.get(end).copied();
            if spaces {
                if ch != Some(' ') {
                    if start + 1 == end && self.column > BEST_WIDTH && split {
                        self.write_indent();
                        self.whitespace = false;
                        self.indention = false;
                    } else {
                        let data: String = chars[start..end].iter().collect();
                        self.write(&data);
                    }
                    start = end;
                }
            } else if breaks {
                if !ch.is_some_and(|c| BREAKS.contains(c)) {
                    if chars[start] == '\n' {
                        self.write_line_break(None);
                    }
                    for &br in &chars[start..end] {
                        self.write_line_break(Some(br));
                    }
                    self.write_indent();
                    self.whitespace = false;
                    self.indention = false;
                    start = end;
                }
            } else if ch.is_none_or(|c| c == ' ' || BREAKS.contains(c)) {
                let data: String = chars[start..end].iter().collect();
                self.write(&data);
                start = end;
            }
            if let Some(c) = ch {
                spaces = c == ' ';
                breaks = BREAKS.contains(c);
            }
            end += 1;
        }
    }

    fn write_single_quoted(&mut self, text: &str, split: bool) {
        self.write_indicator("'", true, false, false);
        let chars: Vec<char> = text.chars().collect();
        let mut spaces = false;
        let mut breaks = false;
        let (mut start, mut end) = (0, 0);
        while end <= chars.len() {
            let ch = chars.get(end).copied();
            if spaces {
                if ch != Some(' ') {
                    if start + 1 == end
                        && self.column > BEST_WIDTH
                        && split
                        && start != 0
                        && end != chars.len()
                    {
                        self.write_indent();
                    } else {
                        let data: String = chars[start..end].iter().collect();
                        self.write(&data);
                    }
                    start = end;
                }
            } else if breaks {
                if !ch.is_some_and(|c| BREAKS.contains(c)) {
                    if chars[start] == '\n' {
                        self.write_line_break(None);
                    }
                    for &br in &chars[start..end] {
                        self.write_line_break(Some(br));
                    }
                    self.write_indent();
                    start = end;
                }
            } else if ch.is_none_or(|c| c == ' ' || BREAKS.contains(c) || c == '\'') && start < end
            {
                let data: String = chars[start..end].iter().collect();
                self.write(&data);
                start = end;
            }
            if ch == Some('\'') {
                self.write("''");
                start = end + 1;
            }
            if let Some(c) = ch {
                spaces = c == ' ';
                breaks = BREAKS.contains(c);
            }
            end += 1;
        }
        self.write_indicator("'", false, false, false);
    }

    fn write_double_quoted(&mut self, text: &str, split: bool) {
        self.write_indicator("\"", true, false, false);
        let chars: Vec<char> = text.chars().collect();
        let (mut start, mut end) = (0, 0);
        while end <= chars.len() {
            let ch = chars.get(end).copied();
            let escape = match ch {
                None => true,
                Some(c) => {
                    "\"\\\u{85}\u{2028}\u{2029}\u{feff}".contains(c)
                        || !(('\x20'..='\x7e').contains(&c)
                            || ('\u{a0}'..='\u{d7ff}').contains(&c)
                            || ('\u{e000}'..='\u{fffd}').contains(&c))
                }
            };
            if escape {
                if start < end {
                    let data: String = chars[start..end].iter().collect();
                    self.write(&data);
                    start = end;
                }
                if let Some(c) = ch {
                    let data = match c {
                        '\0' => "\\0".to_string(),
                        '\x07' => "\\a".to_string(),
                        '\x08' => "\\b".to_string(),
                        '\x09' => "\\t".to_string(),
                        '\x0a' => "\\n".to_string(),
                        '\x0b' => "\\v".to_string(),
                        '\x0c' => "\\f".to_string(),
                        '\x0d' => "\\r".to_string(),
                        '\x1b' => "\\e".to_string(),
                        '"' => "\\\"".to_string(),
                        '\\' => "\\\\".to_string(),
                        '\u{85}' => "\\N".to_string(),
                        '\u{a0}' => "\\_".to_string(),
                        '\u{2028}' => "\\L".to_string(),
                        '\u{2029}' => "\\P".to_string(),
                        c if (c as u32) <= 0xff => format!("\\x{:02X}", c as u32),
                        c if (c as u32) <= 0xffff => format!("\\u{:04X}", c as u32),
                        c => format!("\\U{:08X}", c as u32),
                    };
                    self.write(&data);
                    start = end + 1;
                }
            }
            if end > 0
                && end + 1 < chars.len()
                && (ch == Some(' ') || start >= end)
                && self.column + (end.saturating_sub(start)) > BEST_WIDTH
                && split
            {
                let mut data: String = chars[start..end.max(start)].iter().collect();
                data.push('\\');
                if start < end {
                    start = end;
                }
                self.write(&data);
                self.write_indent();
                self.whitespace = false;
                self.indention = false;
                if chars.get(start) == Some(&' ') {
                    self.write("\\");
                }
            }
            end += 1;
        }
        self.write_indicator("\"", false, false, false);
    }
}

/// `represent_float`.
fn represent_float(f: f64) -> String {
    if f.is_nan() {
        return ".nan".to_string();
    }
    if f.is_infinite() {
        return if f > 0.0 { ".inf" } else { "-.inf" }.to_string();
    }
    let value = float_repr(f).to_lowercase();
    if !value.contains('.') && value.contains('e') {
        value.replacen('e', ".0e", 1)
    } else {
        value
    }
}

/// `yaml.dump(value, sort_keys=False, allow_unicode=True)`.
pub fn dump(value: &Rec) -> String {
    let mut e = Emitter {
        out: String::new(),
        column: 0,
        whitespace: true,
        indention: true,
        indent: None,
        indents: Vec::new(),
        flow_level: 0,
    };
    e.node(value, false, false);
    // expect_document_end: write_indent.
    e.write_indent();
    e.out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn m(items: Vec<(&str, Rec)>) -> Rec {
        Rec::Map(items.into_iter().map(|(k, v)| (k.to_string(), v)).collect())
    }

    #[test]
    fn a_record_is_dumped_as_pyyaml_dumps_it() {
        // The text of PyYAML 6.0.3 yaml.dump(..., sort_keys=False,
        // allow_unicode=True) of the same value.
        let value = Rec::List(vec![m(vec![
            ("filepath", Rec::Str("a.sql".into())),
            (
                "violations",
                Rec::List(vec![m(vec![
                    ("code", Rec::Str("PRS".into())),
                    (
                        "description",
                        Rec::Str("Line 1, Position 17: Found unparsable section: 'WHERE'".into()),
                    ),
                    ("name", Rec::Str(String::new())),
                    ("warning", Rec::Bool(false)),
                    ("fixes", Rec::List(vec![])),
                    ("n", Rec::Str("true".into())),
                    ("f", Rec::Float(1.5e-5)),
                ])]),
            ),
            ("timings", m(vec![])),
        ])]);
        let want = "- filepath: a.sql\n  violations:\n  - code: PRS\n    description: 'Line 1, Position 17: Found unparsable section: ''WHERE'''\n    name: ''\n    warning: false\n    fixes: []\n    n: 'true'\n    f: 1.5e-05\n  timings: {}\n";
        assert_eq!(dump(&value), want);
        assert_eq!(dump(&Rec::List(vec![])), "[]\n");
        // A list is the text of each item: the output of lint writes each
        // record when the file is done.
        let Rec::List(items) = value else {
            unreachable!()
        };
        let two = Rec::List(vec![items[0].clone(), items[0].clone()]);
        assert_eq!(dump(&two), want.repeat(2));
    }
}
