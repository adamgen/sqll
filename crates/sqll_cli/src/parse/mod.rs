//! The command `sqll parse` (S3, S3b C9 and C11; moved from crates/sqll
//! by S3b C13). It prints the record of "sqlfluff parse -f json". It reads
//! the sqlfluff config files, the --config file, and the options as
//! sqlfluff does (sqll_config, docs/interfaces/config.md); a setting that
//! sqll cannot do yet fails closed. It reads no .sqlfluffignore file (one
//! fails closed), no in-file config line, and no noqa comment.
//! harness/sqll.md lists each difference from "sqlfluff parse". PATH "-"
//! reads stdin.
//!
//! Exit codes: 0, no error; 1, a lex error, a parse error (also at the
//! parse depth limit or the parser iteration limit), or an unparsable
//! segment; 2, a usage, input, or output error, or a parse tree that the
//! syntax tree refuses (a sqll bug; sqll_syntax::ParseError).

pub mod config;
pub mod output;
pub mod steps;
pub mod timings;

use std::time::Instant;

use crate::{normpath, read_sql, unsupported, Error, Source, EXIT_FAIL, EXIT_OK};

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

pub struct ParseArgs {
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
                        .ok_or_else(|| Error::new(format!("Option '-{c}' requires an argument.")))?
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
            other => {
                return Err(Error::new(format!(
                    "No such option: -{other}\n\n{PARSE_USAGE}"
                )))
            }
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
                    .ok_or_else(|| Error::new(format!("Option '{name}' requires an argument."))),
            }
        };
        let flag = |name: &str| -> Result<(), Error> {
            match inline {
                Some(_) => Err(Error::new(format!(
                    "Option '{name}' does not take a value."
                ))),
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
            _ => {
                return Err(Error::new(format!(
                    "No such option: {name}\n\n{PARSE_USAGE}"
                )))
            }
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
            Error::new(format!(
                "Invalid value for '--max-parse-depth': '{text}' is not a valid integer."
            ))
        })?),
    };
    if let Some(extra) = raw.paths.get(1) {
        return Err(Error::new(format!(
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

/// The command `sqll parse`.
pub fn command(args: &[String], start: Instant) -> Result<u8, Error> {
    let Some(args) = parse_args(args)? else {
        return Ok(EXIT_OK);
    };
    // sqlfluff checks the dialect of --dialect before it reads the config.
    if let Some(name) = &args.dialect {
        steps::dialect(name).ok_or_else(|| {
            Error::new(format!("Error loading dialect '{name}': no such dialect."))
        })?;
    }
    let path = args
        .path
        .clone()
        .ok_or_else(|| Error::new("Missing argument 'PATH'.".to_string()))?;
    let input = match config::load(&args, &path)? {
        config::Input::Skip(output) => {
            print!("{output}");
            return Ok(EXIT_OK);
        }
        config::Input::Parse(input) => input,
    };
    let settings = &input.settings;
    let name = settings.dialect.clone().ok_or_else(|| {
        Error::new(
            "No dialect was specified. You must configure a dialect or specify one on the \
             command line using --dialect after the command."
                .to_string(),
        )
    })?;
    let dialect = steps::dialect(&name)
        .ok_or_else(|| Error::new(format!("Error loading dialect '{name}': no such dialect.")))?;
    // sqlfluff reads the file at the normalised path (as the config).
    let (source, filepath) = if path == "-" {
        (Source::Stdin, "stdin".to_string())
    } else {
        let fname = normpath(&path);
        (Source::File(fname.clone()), fname)
    };
    let sql = read_sql(&source, settings.encoding)?.text;
    if let Some(warning) = &settings.templater_warning {
        config::warn(warning);
    }
    let record_options = output::RecordOptions {
        code_only: args.code_only,
        include_meta: args.include_meta,
    };
    if config::skip_by_chars(settings, &sql, &filepath) {
        output::write_parse_json(std::io::stdout().lock(), &filepath, None, record_options)
            .map_err(|e| Error::new(format!("cannot write the output: {e}")))?;
        return Ok(EXIT_OK);
    }
    config::check_templater(settings, &sql)?;
    let mut timer = timings::Timer::new(start);
    timer.mark("init");
    let parsed = steps::parse(sql, &filepath, dialect, settings, &mut timer, false)
        .map_err(|e| Error::new(format!("cannot parse {path}: {e}")))?;
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
    let unparsable = written.map_err(|e| Error::new(format!("cannot write the output: {e}")))?;
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
    use super::PARSE_USAGE;

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
