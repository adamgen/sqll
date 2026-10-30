//! sqll: a SQL toolchain.
//!
//! The commands follow the shape of the sqlfluff CLI, so that later stones
//! can add to them:
//!
//!   sqll --version                 sqll, version VERSION
//!   sqll version [--build]         VERSION, or the build record (JSON)
//!   sqll parse --dialect D [-f json] [-c|--code-only] [-m|--include-meta]
//!              [--max-parse-depth N] PATH
//!   sqll lint ..., sqll fix ...    not supported yet (stone S5)
//!
//! "sqll parse" prints the record of "sqlfluff parse -f json" with the raw
//! templater and the default config. It reads no config file, no
//! .sqlfluffignore file, no in-file config line, and no noqa comment.
//! harness/sqll.md lists each difference from "sqlfluff parse". PATH "-"
//! reads stdin.
//!
//! Exit codes: 0, no error; 1, a lex error, a parse error, or an
//! unparsable segment; 2, a usage, input, or output error. A command or
//! input that sqll does not support yet (for example an argument that is not
//! UTF-8) prints "unsupported: <item>" and gives exit code 2. Only a panic
//! (a sqll bug) gives another exit code (101).

mod output;
mod parse;

use std::io::Read;
use std::process::ExitCode;

const VERSION: &str = concat!(
    env!("CARGO_PKG_VERSION"),
    "+tables.",
    env!("SQLL_TABLES_SHA256")
);
const TABLES_SHA256: &str = env!("SQLL_TABLES_SHA256");
const SOURCE_SHA256: &str = env!("SQLL_SOURCE_SHA256");
const SOURCE_FILES: &str = env!("SQLL_SOURCE_FILES");

const USAGE: &str = "\
Usage: sqll [OPTIONS] COMMAND [ARGS]...

Options:
  --version  Show the version and exit.
  -h, --help Show this message and exit.

Commands:
  parse    Parse a SQL file and print the parse tree (JSON).
  version  Show the version of sqll.
  lint     Not supported yet.
  fix      Not supported yet.
";

const PARSE_USAGE: &str = "\
Usage: sqll parse [OPTIONS] PATH

  Parse a SQL file and print the record of \"sqlfluff parse -f json\".
  PATH \"-\" reads stdin.

Options:
  --dialect TEXT           The dialect of the SQL (required).
  -f, --format [json]      The output format. Only json.
  -c, --code-only          Show only the code segments.
  -m, --include-meta       Show the meta segments (indents and dedents).
  --max-parse-depth INTEGER
                           The maximum parse depth. Default: 600. 0 and each
                           value above 10000 give 10000.
  -h, --help               Show this message and exit.
";

const EXIT_OK: u8 = 0;
const EXIT_FAIL: u8 = 1;
const EXIT_ERROR: u8 = 2;

/// An error that stops a command with exit code 2.
struct Error(String);

/// The stack of the thread that runs the command. The parser is iterative,
/// but the record, the output, and the drop of the tree recurse once for
/// each level of the tree. At the parse depth limit
/// (parse::MAX_PARSE_DEPTH_LIMIT), the deepest trees that were measured
/// need about 10 MiB in a release build and 33 MiB in a debug build
/// (tests/cli.rs, the_parse_depth_has_a_limit_that_the_stack_can_hold).
/// Linux reserves the stack, but uses memory only for the pages that the
/// thread touches.
const STACK_SIZE: usize = 256 * 1024 * 1024;

fn main() -> ExitCode {
    let result = utf8_args(std::env::args_os().skip(1)).and_then(|args| {
        std::thread::Builder::new()
            .stack_size(STACK_SIZE)
            .spawn(move || run(&args))
            .map_err(|e| Error(format!("cannot start the command thread: {e}")))?
            .join()
            .unwrap_or_else(|panic| std::panic::resume_unwind(panic))
    });
    match result {
        Ok(code) => ExitCode::from(code),
        Err(Error(message)) => {
            eprintln!("Error: {message}");
            ExitCode::from(EXIT_ERROR)
        }
    }
}

fn utf8_args(args: impl Iterator<Item = std::ffi::OsString>) -> Result<Vec<String>, Error> {
    args.map(|arg| {
        arg.into_string().map_err(|arg| {
            unsupported(
                &format!("non-UTF-8 argument {arg:?}"),
                "sqll reads only UTF-8 arguments",
            )
        })
    })
    .collect()
}

fn run(args: &[String]) -> Result<u8, Error> {
    let Some(first) = args.first() else {
        print!("{USAGE}");
        return Ok(EXIT_ERROR);
    };
    let rest = &args[1..];
    match first.as_str() {
        "--version" => {
            println!("sqll, version {VERSION}");
            Ok(EXIT_OK)
        }
        "-h" | "--help" => {
            print!("{USAGE}");
            Ok(EXIT_OK)
        }
        "version" => version(rest),
        "parse" => parse_command(rest),
        "lint" | "fix" => Err(unsupported(first, "sqll has no rules until stone S5")),
        other => Err(Error(format!("No such command '{other}'.\n\n{USAGE}"))),
    }
}

fn unsupported(item: &str, why: &str) -> Error {
    Error(format!("unsupported: {item}. {why}."))
}

fn version(args: &[String]) -> Result<u8, Error> {
    match args {
        [] => println!("{VERSION}"),
        [flag] if flag == "--build" => println!(
            "{{\"version\": {}, \"tables_sha256\": {}, \"source_sha256\": {}, \"source_files\": {}}}",
            json_string(VERSION),
            json_string(TABLES_SHA256),
            json_string(SOURCE_SHA256),
            SOURCE_FILES
        ),
        _ => return Err(Error(format!("Usage: sqll version [--build]. Got: {args:?}"))),
    }
    Ok(EXIT_OK)
}

fn json_string(text: &str) -> String {
    serde_json::to_string(text).expect("a string serializes")
}

struct ParseArgs {
    dialect: Option<String>,
    path: Option<String>,
    options: parse::Options,
}

/// The arguments as they are read, before the values are checked.
struct RawParseArgs {
    help: bool,
    dialect: Option<String>,
    paths: Vec<String>,
    format: Option<String>,
    max_parse_depth: Option<String>,
    code_only: bool,
    include_meta: bool,
}

/// Split "--name=value" into ("--name", Some("value")).
fn split_option(arg: &str) -> (&str, Option<&str>) {
    match arg.split_once('=') {
        Some((name, value)) if arg.starts_with("--") && name != "--" => (name, Some(value)),
        _ => (arg, None),
    }
}

/// Read a group of short options, as click does: "-cm" is "-c -m", and
/// "-fjson" or "-cf json" gives the value of "-f".
fn short_options<'a>(
    group: &str,
    rest: &mut impl Iterator<Item = &'a String>,
    raw: &mut RawParseArgs,
) -> Result<(), Error> {
    for (i, c) in group.char_indices() {
        match c {
            'c' => raw.code_only = true,
            'm' => raw.include_meta = true,
            'h' => raw.help = true,
            'f' => {
                let tail = &group[i + 1..];
                let format = if tail.is_empty() {
                    rest.next()
                        .ok_or_else(|| Error("Option '-f' requires an argument.".to_string()))?
                        .as_str()
                } else {
                    tail
                };
                raw.format = Some(format.to_string());
                return Ok(());
            }
            other => return Err(Error(format!("No such option: -{other}\n\n{PARSE_USAGE}"))),
        }
    }
    Ok(())
}

/// Read the arguments as click does: first read all of them (an unknown
/// option or a missing value is an error), then "--help" has priority over
/// each other check.
fn parse_args(args: &[String]) -> Result<Option<ParseArgs>, Error> {
    let mut raw = RawParseArgs {
        help: false,
        dialect: None,
        paths: Vec::new(),
        format: None,
        max_parse_depth: None,
        code_only: false,
        include_meta: false,
    };
    let mut it = args.iter();
    let mut only_paths = false;
    while let Some(arg) = it.next() {
        if only_paths || arg == "-" || !arg.starts_with('-') {
            raw.paths.push(arg.clone());
            continue;
        }
        if !arg.starts_with("--") {
            short_options(&arg[1..], &mut it, &mut raw)?;
            continue;
        }
        let (name, inline) = split_option(arg);
        let mut value = |name: &str| -> Result<String, Error> {
            match inline {
                Some(v) => Ok(v.to_string()),
                None => it
                    .next()
                    .cloned()
                    .ok_or_else(|| Error(format!("Option '{name}' requires an argument."))),
            }
        };
        let flag = |name: &str| -> Result<(), Error> {
            match inline {
                Some(_) => Err(Error(format!("Option '{name}' does not take a value."))),
                None => Ok(()),
            }
        };
        match name {
            "--" => only_paths = true,
            "--help" => {
                flag(name)?;
                raw.help = true;
            }
            "--dialect" => raw.dialect = Some(value(name)?),
            "--format" => raw.format = Some(value(name)?),
            "--code-only" => {
                flag(name)?;
                raw.code_only = true;
            }
            "--include-meta" => {
                flag(name)?;
                raw.include_meta = true;
            }
            "--max-parse-depth" => raw.max_parse_depth = Some(value(name)?),
            _ => return Err(Error(format!("No such option: {name}\n\n{PARSE_USAGE}"))),
        }
    }
    if raw.help {
        print!("{PARSE_USAGE}");
        return Ok(None);
    }
    if let Some(format) = &raw.format {
        if format != "json" {
            return Err(unsupported(
                &format!("format {format}"),
                "sqll parse has only the json format",
            ));
        }
    }
    let max_parse_depth = match &raw.max_parse_depth {
        None => parse::MAX_PARSE_DEPTH,
        Some(text) => parse::depth_limit(text.parse().map_err(|_| {
            Error(format!(
                "Invalid value for '--max-parse-depth': '{text}' is not a valid integer."
            ))
        })?),
    };
    if let Some(extra) = raw.paths.get(1) {
        return Err(Error(format!(
            "Got unexpected extra argument ({extra}). sqll parses one file."
        )));
    }
    Ok(Some(ParseArgs {
        dialect: raw.dialect,
        path: raw.paths.into_iter().next(),
        options: parse::Options {
            code_only: raw.code_only,
            include_meta: raw.include_meta,
            max_parse_depth,
        },
    }))
}

/// The file extensions of the sqlfluff default config (sql_file_exts in
/// third_party/sqlfluff/src/sqlfluff/core/default_config.cfg). sqlfluff
/// skips a file with another extension.
const SQL_FILE_EXTS: [&str; 5] = [".sql", ".sql.j2", ".dml", ".ddl", ".pkb"];

fn has_sql_extension(path: &str) -> bool {
    let lower = path.to_lowercase();
    SQL_FILE_EXTS.iter().any(|ext| lower.ends_with(ext))
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
fn normpath(path: &str) -> String {
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

/// Read a SQL file as sqlfluff does for a UTF-8 file: with no UTF-8 byte
/// order mark, and with universal newlines ("\r\n" and "\r" become "\n").
fn read_sql(path: &str) -> Result<String, Error> {
    let mut data = Vec::new();
    let read = if path == "-" {
        std::io::stdin().read_to_end(&mut data)
    } else {
        std::fs::File::open(path).and_then(|mut f| f.read_to_end(&mut data))
    };
    read.map_err(|e| Error(format!("cannot read {path}: {e}")))?;
    let data = data.strip_prefix(b"\xef\xbb\xbf").unwrap_or(&data);
    let text = String::from_utf8(data.to_vec()).map_err(|_| {
        unsupported(
            &format!("encoding of {path}"),
            "sqll reads only UTF-8 files",
        )
    })?;
    if text.contains('\r') {
        return Ok(text.replace("\r\n", "\n").replace('\r', "\n"));
    }
    Ok(text)
}

fn parse_command(args: &[String]) -> Result<u8, Error> {
    let Some(args) = parse_args(args)? else {
        return Ok(EXIT_OK);
    };
    let name = args
        .dialect
        .ok_or_else(|| Error("No dialect was specified. Give it with --dialect.".to_string()))?;
    let dialect = parse::dialect(&name)
        .ok_or_else(|| Error(format!("Error loading dialect '{name}': no such dialect.")))?;
    let path = args
        .path
        .ok_or_else(|| Error("Missing argument 'PATH'.".to_string()))?;
    if path != "-" {
        let meta =
            std::fs::metadata(&path).map_err(|e| Error(format!("cannot read {path}: {e}")))?;
        if meta.is_dir() {
            return Err(unsupported(
                &format!("folder {path}"),
                "sqll parses one file",
            ));
        }
        if !has_sql_extension(&path) {
            println!("[]");
            return Ok(EXIT_OK);
        }
    }
    let sql = read_sql(&path)?;
    let parsed = parse::parse(sql, dialect, &args.options);
    for e in &parsed.errors {
        eprintln!("{e}");
    }

    let filepath = if path == "-" {
        "stdin".to_string()
    } else {
        normpath(&path)
    };
    let written = output::write_parse_json(std::io::stdout().lock(), &filepath, &parsed.record);
    written.map_err(|e| Error(format!("cannot write the output: {e}")))?;
    Ok(if parsed.ok() { EXIT_OK } else { EXIT_FAIL })
}

#[cfg(test)]
mod tests {
    use super::{has_sql_extension, normpath, SQL_FILE_EXTS};

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

    #[test]
    fn the_parse_depth_is_at_most_the_limit() {
        use crate::parse::{depth_limit, MAX_PARSE_DEPTH_LIMIT};
        assert_eq!(MAX_PARSE_DEPTH_LIMIT, 10_000);
        for (value, want) in [
            (0, 10_000),
            (1, 1),
            (600, 600),
            (10_000, 10_000),
            (10_001, 10_000),
            (usize::MAX, 10_000),
        ] {
            assert_eq!(depth_limit(value), want, "{value}");
        }
    }

    #[test]
    fn sql_file_exts_is_the_value_of_the_pinned_default_config() {
        let cfg = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../third_party/sqlfluff/src/sqlfluff/core/default_config.cfg"
        );
        let text = std::fs::read_to_string(cfg).expect("the sqlfluff submodule");
        let value = text
            .lines()
            .find_map(|line| line.strip_prefix("sql_file_exts = "))
            .expect("sql_file_exts in the default config");
        let exts: Vec<&str> = value.trim().split(',').collect();
        assert_eq!(exts, SQL_FILE_EXTS);
    }

    #[test]
    fn the_sql_extensions_are_those_of_the_sqlfluff_default_config() {
        for path in [
            "a.sql", "A.SQL", "b.sql.j2", "c.DML", "d.ddl", "e.pkb", "E.PKB",
        ] {
            assert!(has_sql_extension(path), "{path}");
        }
        for path in ["a.txt", "a.sqlx", "a", "a.j2"] {
            assert!(!has_sql_extension(path), "{path}");
        }
    }
}
