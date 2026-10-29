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
//! "sqll parse" prints the record of "sqlfluff parse -f json". It reads no
//! config file and uses no templater (as "sqlfluff parse --templater raw
//! --ignore-local-config"). PATH "-" reads stdin.
//!
//! Exit codes, as "sqlfluff parse": 0, no error; 1, a lex error, a parse
//! error, or an unparsable segment; 2, a usage or input error. A command
//! that sqll does not support yet prints "unsupported: <item>" and gives
//! exit code 2.

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
                           The maximum parse depth. Default: 600. 0: no limit.
  -h, --help               Show this message and exit.
";

const EXIT_OK: u8 = 0;
const EXIT_FAIL: u8 = 1;
const EXIT_ERROR: u8 = 2;

/// An error that stops a command with exit code 2.
struct Error(String);

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match run(&args) {
        Ok(code) => ExitCode::from(code),
        Err(Error(message)) => {
            eprintln!("Error: {message}");
            ExitCode::from(EXIT_ERROR)
        }
    }
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

/// Split "--name=value" into ("--name", Some("value")).
fn split_option(arg: &str) -> (&str, Option<&str>) {
    match arg.split_once('=') {
        Some((name, value)) if arg.starts_with("--") => (name, Some(value)),
        _ => (arg, None),
    }
}

fn parse_args(args: &[String]) -> Result<Option<ParseArgs>, Error> {
    let mut out = ParseArgs {
        dialect: None,
        path: None,
        options: parse::Options {
            code_only: false,
            include_meta: false,
            max_parse_depth: parse::MAX_PARSE_DEPTH,
        },
    };
    let mut it = args.iter();
    let mut only_paths = false;
    while let Some(arg) = it.next() {
        if only_paths || arg == "-" || !arg.starts_with('-') {
            if out.path.is_some() {
                return Err(Error(format!(
                    "Got unexpected extra argument ({arg}). sqll parses one file."
                )));
            }
            out.path = Some(arg.clone());
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
        match name {
            "--" => only_paths = true,
            "-h" | "--help" => {
                print!("{PARSE_USAGE}");
                return Ok(None);
            }
            "--dialect" => out.dialect = Some(value(name)?),
            "-f" | "--format" => {
                let format = value(name)?;
                if format != "json" {
                    return Err(unsupported(
                        &format!("format {format}"),
                        "sqll parse has only the json format",
                    ));
                }
            }
            "-c" | "--code-only" => out.options.code_only = true,
            "-m" | "--include-meta" => out.options.include_meta = true,
            "--max-parse-depth" => {
                let text = value(name)?;
                out.options.max_parse_depth = text.parse().map_err(|_| {
                    Error(format!(
                        "Invalid value for '--max-parse-depth': '{text}' is not a valid integer."
                    ))
                })?;
            }
            _ => return Err(Error(format!("No such option: {name}\n\n{PARSE_USAGE}"))),
        }
    }
    Ok(Some(out))
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
    let sql = read_sql(&path)?;
    let parsed = parse::parse(sql, dialect, &args.options);
    for e in &parsed.errors {
        eprintln!("{e}");
    }

    let filepath = if path == "-" { "stdin" } else { path.as_str() };
    let written = output::write_parse_json(std::io::stdout().lock(), filepath, &parsed.record);
    written.map_err(|e| Error(format!("cannot write the output: {e}")))?;
    Ok(if parsed.ok() { EXIT_OK } else { EXIT_FAIL })
}
