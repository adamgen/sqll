// Parts of this file are a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/types.py (Color) and src/sqlfluff/cli/formatters.py
// (should_produce_plain_output, colorize_helper), src/sqlfluff/cli/commands.py
// (the log line of set_logging_level).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The colors of the sqlfluff CLI (src/sqlfluff/core/types.py `Color`, the
//! colorama codes, and `OutputStreamFormatter.should_produce_plain_output`
//! and `colorize_helper` of src/sqlfluff/cli/formatters.py, sqlfluff 4.4.0).

/// A color of the output.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Color {
    Red,
    Green,
    Blue,
    /// The sqlfluff `light`: yellow.
    Light,
}

impl Color {
    fn code(self) -> &'static str {
        match self {
            Color::Red => "\x1b[31m",
            Color::Green => "\x1b[32m",
            Color::Blue => "\x1b[34m",
            Color::Light => "\x1b[33m",
        }
    }
}

const RESET_ALL: &str = "\x1b[0m";

/// The colors of one command: plain output has none.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Painter {
    pub plain: bool,
}

impl Painter {
    /// sqlfluff `should_produce_plain_output`: `--nocolor` gives plain
    /// output, `--color` colored output; else the output is plain if stdout
    /// is not a terminal or `NO_COLOR` is set and not empty.
    pub fn new(nocolor: Option<bool>) -> Painter {
        let plain = match nocolor {
            Some(n) => n,
            None => {
                !crate::tty::stdout_is_terminal()
                    || std::env::var_os("NO_COLOR").is_some_and(|v| !v.is_empty())
            }
        };
        Painter { plain }
    }

    /// sqlfluff `colorize`.
    pub fn paint(&self, text: &str, color: Option<Color>) -> String {
        match color {
            Some(c) if !self.plain => format!("{}{text}{RESET_ALL}", c.code()),
            _ => text.to_string(),
        }
    }

    /// A warning line of the sqlfluff log (the handler of
    /// `set_logging_level`): "WARNING    <message> ", with the message in
    /// red and a reset code first if the output is not plain.
    pub fn warning(&self, message: &str) -> String {
        if self.plain {
            format!("WARNING    {message} ")
        } else {
            format!(
                "{RESET_ALL}WARNING    {} ",
                self.paint(message, Some(Color::Red))
            )
        }
    }
}
