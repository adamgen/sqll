//! The commands and the output formats of the sqll command line (S3b task
//! C13). The binary crate `sqll` keeps main, the allocator, the license
//! text, and the dispatch: it calls [`run`] for each command of this crate.
//!
//! The commands have the shape of the sqlfluff 4.4.0 CLI
//! (harness/sqll.md):
//!
//! - `parse`: the record of `sqlfluff parse -f json` ([`parse`]).
//! - `lint` and `fix` ([`lint`]): the output formats `human`, `json`,
//!   `yaml`, `github-annotation`, `github-annotation-native`, and `none`;
//!   the exit codes of sqlfluff.
//! - `rules` and `dialects` ([`info`]).
//!
//! Exit codes: 0, no error; 1, a violation (lint, fix) or a lex or parse
//! error (parse); 2, a usage, input, config, or output error. A rule, a
//! setting, an option, or an input that sqll does not support yet gives
//! "unsupported: <item>" and exit code 2 (fail closed), never a silent
//! skip.

pub mod args;
pub mod color;
pub mod info;
pub mod lint;
pub mod parse;
pub mod pyfmt;
pub mod text;
pub mod tty;

use std::io::{Read, Write};
use std::time::Instant;

use sqll_config::Encoding;

pub const EXIT_OK: u8 = 0;
pub const EXIT_FAIL: u8 = 1;
pub const EXIT_ERROR: u8 = 2;

/// The commands of this crate.
pub const COMMANDS: [&str; 5] = ["parse", "lint", "fix", "rules", "dialects"];

/// An error that stops a command with exit code 2. The text goes to stderr
/// (or to stdout, where sqlfluff writes it there), with a new line.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Error {
    pub text: String,
    pub stdout: bool,
}

impl Error {
    /// "Error: <message>" on stderr.
    pub fn new(message: impl Into<String>) -> Error {
        Error {
            text: format!("Error: {}", message.into()),
            stdout: false,
        }
    }

    /// The text as it is, on stderr.
    pub fn raw(text: impl Into<String>) -> Error {
        Error {
            text: text.into(),
            stdout: false,
        }
    }

    /// The text as it is, on stdout.
    pub fn stdout(text: impl Into<String>) -> Error {
        Error {
            text: text.into(),
            stdout: true,
        }
    }

    /// The sqlfluff `SQLFluffUserError` of a command: "\nUser Error: <message>"
    /// on stderr.
    pub fn user(message: impl Into<String>) -> Error {
        Error::raw(format!("\nUser Error: {}", message.into()))
    }

    /// Write the error.
    pub fn print(&self) {
        if self.stdout {
            let mut out = std::io::stdout().lock();
            let _ = writeln!(out, "{}", self.text);
            let _ = out.flush();
        } else {
            eprintln!("{}", self.text);
        }
    }
}

/// "unsupported: <item>. <why>." (fail closed).
pub fn unsupported(item: &str, why: &str) -> Error {
    Error::new(format!("unsupported: {item}. {why}."))
}

/// Run a command of this crate with its arguments: the exit code. An error
/// is written before the return.
pub fn run(command: &str, args: &[String], start: Instant) -> u8 {
    let result = match command {
        "parse" => parse::command(args, start),
        "lint" => lint::lint_command(args),
        "fix" => lint::fix_command(args),
        "rules" => info::rules_command(args),
        "dialects" => info::dialects_command(args),
        other => Err(Error::new(format!("No such command '{other}'."))),
    };
    match result {
        Ok(code) => code,
        Err(e) => {
            e.print();
            EXIT_ERROR
        }
    }
}

/// The path as Python os.path.normpath (POSIX) gives it. sqlfluff prints
/// this form of a file path.
///
/// Port of normpath in Lib/posixpath.py of CPython
/// (https://github.com/python/cpython), tag v3.13.16, commit
/// cbc944f4bc59639a444dd971c737788ba2283a91.
/// Copyright (c) 2001-2024 Python Software Foundation; All Rights Reserved.
/// PSF License Version 2: see crates/LICENSE-cpython.txt. See THIRD_PARTY.md.
/// Changes: Rust in place of Python; only str paths; the root slashes are
/// found here, not with splitroot.
pub fn normpath(path: &str) -> String {
    if path.is_empty() {
        return ".".to_string();
    }
    let slashes = if path.starts_with("//") && !path.starts_with("///") {
        2
    } else if path.starts_with('/') {
        1
    } else {
        0
    };
    let mut parts: Vec<&str> = Vec::new();
    for part in path.split('/') {
        match part {
            "" | "." => {}
            ".." if (slashes > 0 || !parts.is_empty()) && parts.last() != Some(&"..") => {
                parts.pop();
            }
            other => parts.push(other),
        }
    }
    let text = "/".repeat(slashes) + &parts.join("/");
    if text.is_empty() {
        ".".to_string()
    } else {
        text
    }
}

/// Where the SQL comes from. Only the PATH argument "-" is stdin: a path
/// that normpath makes "-" (for example "./-") is the file "-", as in
/// sqlfluff `parse`.
pub enum Source {
    Stdin,
    File(String),
}

/// A SQL text as sqll reads it.
pub struct SqlText {
    /// The text with universal newlines and with no removed byte order mark.
    pub text: String,
    /// True if a UTF-8 byte order mark was removed: a fix writes it again,
    /// as Python with the encoding `utf-8-sig` does.
    pub bom: bool,
}

/// Read a SQL file as sqlfluff does for a UTF-8 file: with universal
/// newlines ("\r\n" and "\r" become "\n"; sqlfluff `render_string`), and
/// with no UTF-8 byte order mark, unless the encoding is `utf-8` (Python
/// keeps the mark). For stdin, the encoding is always `utf-8`
/// (`ParseSettings::for_stdin`): sqlfluff reads `sys.stdin`, which keeps the
/// mark.
pub fn read_sql(source: &Source, encoding: Encoding) -> Result<SqlText, Error> {
    let mut data = Vec::new();
    let (path, read) = match source {
        Source::Stdin => ("stdin", std::io::stdin().read_to_end(&mut data)),
        Source::File(path) => (
            path.as_str(),
            std::fs::File::open(path).and_then(|mut f| f.read_to_end(&mut data)),
        ),
    };
    read.map_err(|e| Error::new(format!("cannot read {path}: {e}")))?;
    let (data, bom) = match encoding {
        Encoding::Utf8 => (&data[..], false),
        Encoding::Autodetect | Encoding::Utf8Sig => match data.strip_prefix(b"\xef\xbb\xbf") {
            Some(rest) => (rest, true),
            None => (&data[..], false),
        },
    };
    let text = String::from_utf8(data.to_vec()).map_err(|_| {
        unsupported(
            &format!("encoding of {path}"),
            "sqll reads only UTF-8 files",
        )
    })?;
    let text = if text.contains('\r') {
        text.replace("\r\n", "\n").replace('\r', "\n")
    } else {
        text
    };
    Ok(SqlText { text, bom })
}

#[cfg(test)]
mod tests {
    use super::normpath;

    #[test]
    fn normpath_is_that_of_python_posixpath() {
        // The values of Python 3.13 os.path.normpath.
        let cases = [
            ("", "."),
            (".", "."),
            ("./d.sql", "d.sql"),
            (".//d.sql", "d.sql"),
            ("sub/../d.sql", "d.sql"),
            ("a/./b//c/", "a/b/c"),
            ("../d.sql", "../d.sql"),
            ("../../a/../d.sql", "../../d.sql"),
            ("a/../../d.sql", "../d.sql"),
            ("/../d.sql", "/d.sql"),
            ("/a/b/../d.sql", "/a/d.sql"),
            ("//a/./d.sql", "//a/d.sql"),
            ("///a/d.sql", "/a/d.sql"),
            ("..", ".."),
            ("a/..", "."),
            ("/", "/"),
        ];
        for (path, want) in cases {
            assert_eq!(normpath(path), want, "{path:?}");
        }
    }
}
