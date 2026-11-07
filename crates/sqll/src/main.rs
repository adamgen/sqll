//! sqll: a SQL toolchain.
//!
//! The commands follow the shape of the sqlfluff CLI, so that later stones
//! can add to them:
//!
//!   sqll --version                 sqll, version VERSION
//!   sqll --license                 the license of sqll and the notices of
//!                                  the code in the binary (license.rs)
//!   sqll version [--build]         VERSION, or the build record (JSON)
//!   sqll parse [--dialect D] [-t|--templater T] [--config FILE]
//!              [--ignore-local-config] [-f json] [-c|--code-only]
//!              [-m|--include-meta] [--max-parse-depth N] [--timings] PATH
//!   sqll lint ..., sqll fix ...    not supported yet (stone S5)
//!
//! "sqll parse" prints the record of "sqlfluff parse -f json". Since S3b
//! C11 it reads the sqlfluff config files, the --config file, and the
//! options as sqlfluff does (sqll_config, docs/interfaces/config.md); a
//! setting that sqll cannot do yet fails closed. It reads no
//! .sqlfluffignore file (one fails closed), no in-file config line, and no
//! noqa comment. harness/sqll.md lists each difference from "sqlfluff
//! parse". PATH "-" reads stdin.
//!
//! Exit codes: 0, no error; 1, a lex error, a parse error (also at the
//! parse depth limit or the parser iteration limit), or an unparsable
//! segment; 2, a usage, input, or output error, or a parse tree that the
//! syntax tree refuses (a sqll bug; sqll_syntax::ParseError). A command or
//! input that sqll does not support yet (for example an argument that is
//! not UTF-8) prints "unsupported: <item>" and gives exit code 2. Only a
//! panic (a sqll bug) gives another exit code (101).

mod alloc;
mod config;
mod license;
mod output;
mod parse;
mod timings;

use std::io::Read;

use sqll_config::Encoding;
use std::process::ExitCode;
use std::time::Instant;

#[global_allocator]
static ALLOCATOR: alloc::Allocator = alloc::Allocator;

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
  --license  Show the license of sqll and the notices of the code in the
             sqll binary, and exit.
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
  -d, --dialect TEXT       The dialect of the SQL. It can also come from the
                           config.
  -t, --templater TEXT     The templater (default: jinja). sqll has raw, and
                           jinja only for a file with no Jinja tag.
  --config PATH            An extra config file, read after the other config
                           files.
  --ignore-local-config    Read no config file of the user or of a folder;
                           only the --config file.
  -f, --format [json]      The output format. Only json.
  -c, --code-only          Show only the code segments.
  -m, --include-meta       Show the meta segments (indents and dedents).
  --max-parse-depth INTEGER
                           The maximum parse depth (the config value
                           max_parse_depth). Default: 600. 0 and each
                           value above 10000 give 10000.
  --timings                Write the time of each phase to stderr (one
                           JSON line, the last line).
  -h, --help               Show this message and exit.
";

const EXIT_OK: u8 = 0;
const EXIT_FAIL: u8 = 1;
const EXIT_ERROR: u8 = 2;

/// An error that stops a command with exit code 2.
struct Error(String);

/// The stack of the thread that runs the command. The parser and the
/// conversion to the syntax tree are iterative, but the output (the writer
/// of the record) and the drop of the parser tree recurse once for each
/// level of the tree. At the parse depth limit
/// (sqll_syntax::MAX_PARSE_DEPTH_LIMIT), the deepest trees that were
/// measured need about 10 MiB in a release build and 33 MiB in a debug build
/// (tests/cli.rs, the_parse_depth_has_a_limit_that_the_stack_can_hold).
/// Linux reserves the stack, but uses memory only for the pages that the
/// thread touches.
const STACK_SIZE: usize = 256 * 1024 * 1024;

fn main() -> ExitCode {
    let start = Instant::now();
    let result = utf8_args(std::env::args_os().skip(1)).and_then(|args| {
        std::thread::Builder::new()
            .stack_size(STACK_SIZE)
            .spawn(move || run(&args, start))
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

fn run(args: &[String], start: Instant) -> Result<u8, Error> {
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
        "--license" => {
            print!("{}", license::text(VERSION));
            Ok(EXIT_OK)
        }
        "-h" | "--help" => {
            print!("{USAGE}");
            Ok(EXIT_OK)
        }
        "version" => version(rest),
        "parse" => parse_command(rest, start),
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
    templater: Option<String>,
    config: Option<String>,
    ignore_local_config: bool,
    max_parse_depth: Option<usize>,
    path: Option<String>,
    code_only: bool,
    include_meta: bool,
    timings: bool,
}

/// The arguments as they are read, before the values are checked.
struct RawParseArgs {
    help: bool,
    dialect: Option<String>,
    templater: Option<String>,
    config: Option<String>,
    ignore_local_config: bool,
    paths: Vec<String>,
    format: Option<String>,
    max_parse_depth: Option<String>,
    code_only: bool,
    include_meta: bool,
    timings: bool,
}

/// Split "--name=value" into ("--name", Some("value")).
fn split_option(arg: &str) -> (&str, Option<&str>) {
    match arg.split_once('=') {
        Some((name, value)) if arg.starts_with("--") && name != "--" => (name, Some(value)),
        _ => (arg, None),
    }
}

/// Read a group of short options, as click does: "-cm" is "-c -m", and
/// "-fjson" or "-cf json" gives the value of "-f" (also "-d" and "-t").
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
            'f' | 'd' | 't' => {
                let tail = &group[i + 1..];
                let value = if tail.is_empty() {
                    rest.next()
                        .ok_or_else(|| Error(format!("Option '-{c}' requires an argument.")))?
                        .as_str()
                } else {
                    tail
                };
                let slot = match c {
                    'f' => &mut raw.format,
                    'd' => &mut raw.dialect,
                    _ => &mut raw.templater,
                };
                *slot = Some(value.to_string());
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
        templater: None,
        config: None,
        ignore_local_config: false,
        paths: Vec::new(),
        format: None,
        max_parse_depth: None,
        code_only: false,
        include_meta: false,
        timings: false,
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
            "--templater" => raw.templater = Some(value(name)?),
            "--config" => raw.config = Some(value(name)?),
            "--ignore-local-config" => {
                flag(name)?;
                raw.ignore_local_config = true;
            }
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
            "--timings" => {
                flag(name)?;
                raw.timings = true;
            }
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
        None => None,
        Some(text) => Some(text.parse().map_err(|_| {
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
        templater: raw.templater,
        config: raw.config,
        ignore_local_config: raw.ignore_local_config,
        max_parse_depth,
        path: raw.paths.into_iter().next(),
        code_only: raw.code_only,
        include_meta: raw.include_meta,
        timings: raw.timings,
    }))
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

/// Read a SQL file as sqlfluff does for a UTF-8 file: with universal
/// newlines ("\r\n" and "\r" become "\n"; sqlfluff `render_string`), and
/// with no UTF-8 byte order mark, unless the encoding is `utf-8` (Python
/// keeps the mark). For stdin (`-`), the encoding is always `utf-8`
/// (`ParseSettings::for_stdin`): sqlfluff reads `sys.stdin`, which keeps the
/// mark.
fn read_sql(path: &str, encoding: Encoding) -> Result<String, Error> {
    let mut data = Vec::new();
    let read = if path == "-" {
        std::io::stdin().read_to_end(&mut data)
    } else {
        std::fs::File::open(path).and_then(|mut f| f.read_to_end(&mut data))
    };
    read.map_err(|e| Error(format!("cannot read {path}: {e}")))?;
    let data = match encoding {
        Encoding::Utf8 => &data[..],
        Encoding::Autodetect | Encoding::Utf8Sig => {
            data.strip_prefix(b"\xef\xbb\xbf").unwrap_or(&data)
        }
    };
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

fn parse_command(args: &[String], start: Instant) -> Result<u8, Error> {
    let Some(args) = parse_args(args)? else {
        return Ok(EXIT_OK);
    };
    // sqlfluff checks the dialect of --dialect before it reads the config.
    if let Some(name) = &args.dialect {
        parse::dialect(name)
            .ok_or_else(|| Error(format!("Error loading dialect '{name}': no such dialect.")))?;
    }
    let path = args
        .path
        .clone()
        .ok_or_else(|| Error("Missing argument 'PATH'.".to_string()))?;
    let input = match config::load(&args, &path)? {
        config::Input::Skip(output) => {
            print!("{output}");
            return Ok(EXIT_OK);
        }
        config::Input::Parse(input) => input,
    };
    let settings = &input.settings;
    let name = settings.dialect.clone().ok_or_else(|| {
        Error(
            "No dialect was specified. You must configure a dialect or specify one on the \
             command line using --dialect after the command."
                .to_string(),
        )
    })?;
    let dialect = parse::dialect(&name)
        .ok_or_else(|| Error(format!("Error loading dialect '{name}': no such dialect.")))?;
    let sql = read_sql(&path, settings.encoding)?;
    let filepath = if path == "-" {
        "stdin".to_string()
    } else {
        normpath(&path)
    };
    if let Some(warning) = &settings.templater_warning {
        config::warn(warning);
    }
    let record_options = output::RecordOptions {
        code_only: args.code_only,
        include_meta: args.include_meta,
    };
    if config::skip_by_chars(settings, &sql, &filepath) {
        output::write_parse_json(std::io::stdout().lock(), &filepath, None, record_options)
            .map_err(|e| Error(format!("cannot write the output: {e}")))?;
        return Ok(EXIT_OK);
    }
    config::check_templater(settings, &sql)?;
    let mut timer = timings::Timer::new(start);
    timer.mark("init");
    let parsed = parse::parse(sql, &filepath, dialect, settings, &mut timer, false)
        .map_err(|e| Error(format!("cannot parse {path}: {e}")))?;
    // The lex errors and the parser stop. An unparsable section has no
    // line: the record shows it, and the exit code is 1.
    let mut printed = 0;
    for e in parsed.errors.iter().filter(|e| e.node.is_none()) {
        eprintln!("{e}");
        printed += 1;
    }
    let written = output::write_parse_json(
        std::io::stdout().lock(),
        &filepath,
        parsed.tree.as_ref(),
        record_options,
    );
    let unparsable = written.map_err(|e| Error(format!("cannot write the output: {e}")))?;
    timer.mark("write");
    // "sqlfluff parse" gives exit code 1 for a lex error, a parse error, or
    // an unparsable segment.
    let ok = printed == 0 && !unparsable;
    // The tree is not dropped (parse::parse).
    std::mem::forget(parsed);
    timer.mark("free");
    if args.timings {
        eprintln!("{}", timer.json());
    }
    Ok(if ok { EXIT_OK } else { EXIT_FAIL })
}

#[cfg(test)]
mod tests {
    use super::{normpath, PARSE_USAGE};

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
    fn the_parse_depth_limit_is_that_of_the_help() {
        assert!(PARSE_USAGE.contains(&format!(
            "Default: {}. 0 and each\n                           value above {} give {}.",
            sqll_syntax::MAX_PARSE_DEPTH,
            sqll_syntax::MAX_PARSE_DEPTH_LIMIT,
            sqll_syntax::MAX_PARSE_DEPTH_LIMIT
        )));
    }
}
