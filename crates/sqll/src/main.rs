//! sqll: a SQL toolchain.
//!
//! This crate keeps main, the allocator, the license text, the version, and
//! the dispatch. The commands and the output formats are in the crate
//! sqll_cli (S3b C13). The commands follow the shape of the sqlfluff CLI:
//!
//!   sqll --version                 sqll, version VERSION
//!   sqll --license                 the license of sqll and the notices of
//!                                  the code in the binary (license.rs)
//!   sqll version [--build]         VERSION, or the build record (JSON)
//!   sqll parse ...                 the record of "sqlfluff parse -f json"
//!   sqll lint ..., sqll fix ...    lint and fix (sqll_cli::lint)
//!   sqll rules, sqll dialects      the rules and the dialects of sqll
//!
//! Exit codes: 0, no error; 1, a violation or a lex or parse error; 2, a
//! usage, input, config, or output error. A command, a setting, or an input
//! that sqll does not support yet (for example an argument that is not
//! UTF-8) prints "unsupported: <item>" and gives exit code 2. Only a panic
//! (a sqll bug) gives another exit code (101).

mod alloc;
mod license;

use std::process::ExitCode;
use std::time::Instant;

use sqll_cli::{Error, EXIT_ERROR, EXIT_OK};

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
  dialects  Show the dialects of sqll.
  fix       Fix SQL files.
  lint      Lint SQL files.
  parse     Parse a SQL file and print the parse tree (JSON).
  rules     Show the rules that the config selects.
  version   Show the version of sqll.
";

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
            .map_err(|e| Error::new(format!("cannot start the command thread: {e}")))?
            .join()
            .unwrap_or_else(|panic| std::panic::resume_unwind(panic))
    });
    match result {
        Ok(code) => ExitCode::from(code),
        Err(e) => {
            e.print();
            ExitCode::from(EXIT_ERROR)
        }
    }
}

fn utf8_args(args: impl Iterator<Item = std::ffi::OsString>) -> Result<Vec<String>, Error> {
    args.map(|arg| {
        arg.into_string().map_err(|arg| {
            sqll_cli::unsupported(
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
        command if sqll_cli::COMMANDS.contains(&command) => Ok(sqll_cli::run(command, rest, start)),
        other => Err(Error::new(format!("No such command '{other}'.\n\n{USAGE}"))),
    }
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
        _ => {
            return Err(Error::new(format!(
                "Usage: sqll version [--build]. Got: {args:?}"
            )))
        }
    }
    Ok(EXIT_OK)
}

/// A JSON string of the text, as Python json.dumps writes it.
fn json_string(text: &str) -> String {
    let mut out = Vec::new();
    sqll_cli::parse::output::write_json_str(&mut out, text).expect("a write to memory");
    String::from_utf8(out).expect("JSON is UTF-8")
}
