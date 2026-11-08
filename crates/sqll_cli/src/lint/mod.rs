// Parts of this file are a port of sqlfluff 4.4.0 code:
// src/sqlfluff/cli/commands.py (lint, fix and their helpers),
// src/sqlfluff/cli/outputstream.py, src/sqlfluff/cli/formatters.py, and
// src/sqlfluff/core/linter (lint_paths, the counts, persist_tree).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The commands `sqll lint` and `sqll fix` (S3b C13): a port of the
//! commands `lint` and `fix` of sqlfluff 4.4.0 (src/sqlfluff/cli/
//! commands.py `get_config`, `lint`, `fix`, `_paths_fix`, `_stdin_fix`,
//! `_handle_unparsable`, `do_fixes`; src/sqlfluff/cli/outputstream.py
//! `OutputPolicy`; src/sqlfluff/core/linter/linter.py `lint_paths`;
//! src/sqlfluff/core/linter/linted_dir.py and linting_result.py, the stats
//! and the counts; src/sqlfluff/core/linter/linted_file.py `persist_tree`
//! and `_safe_create_replace_file`; MIT, see THIRD_PARTY.md).
//!
//! harness/sqll.md lists the options and each difference from sqlfluff.
//! A rule that the config selects and sqll does not have gives
//! "unsupported" and exit code 2 (the default `rules = all` selects all 79
//! rules of sqlfluff; sqll has CP01, CP03, and CP04).

pub mod file;
pub mod files;
pub mod record;
pub mod yaml;

use std::fs::File;
use std::io::{BufWriter, Write};
use std::os::unix::fs::PermissionsExt;

use sqll_config::parse::sql_file_exts;
use sqll_config::{Config, Env, LoadOptions, Table, Value};

use crate::args::{self, Kind as ArgKind, Opt, Parsed};
use crate::color::{Color, Painter};
use crate::info::{
    config_error as root_config_error, nocolor_option, output_line_length, painter_of,
};
use crate::parse::steps;
use crate::{unsupported, Error, EXIT_FAIL, EXIT_OK};
use file::{Issue, Kind, Linted, Outcome, Run};
use record::{format_file_violations, format_filename, format_violation, Rec, ViolationText};

/// The options of `lint` and `fix` that sqlfluff has: the core options and
/// the lint options. `-f` is `--format` in `lint` and `--force` in `fix`.
macro_rules! common_opts {
    ($($extra:expr),* $(,)?) => {
        &[
            args::not_yet(&["-v", "--verbose"], ArgKind::Flag),
            args::flag(&["-n", "--nocolor"], "nocolor"),
            args::flag(&["--color"], "color"),
            args::not_yet(&["--version"], ArgKind::Flag),
            args::value(&["-d", "--dialect"], "dialect"),
            args::value(&["-t", "--templater"], "templater"),
            args::value(&["-r", "--rules"], "rules"),
            args::value(&["-e", "--exclude-rules"], "exclude_rules"),
            args::value(&["--config"], "config"),
            args::flag(&["--ignore-local-config"], "ignore_local_config"),
            args::value(&["--encoding"], "encoding"),
            args::value(&["-i", "--ignore"], "ignore"),
            args::not_yet(&["--bench"], ArgKind::Flag),
            args::not_yet(&["--logger"], ArgKind::Value),
            args::flag(&["--disable-noqa"], "disable_noqa"),
            args::value(&["--disable-noqa-except"], "disable_noqa_except"),
            args::not_yet(&["--library-path"], ArgKind::Value),
            args::not_yet(&["--stdin-filename"], ArgKind::Value),
            args::flag(&["-q", "--quiet"], "quiet"),
            args::value(&["-p", "--processes"], "processes"),
            args::flag(&["--disable-progress-bar"], "disable_progress_bar"),
            args::not_yet(&["--persist-timing"], ArgKind::Value),
            args::flag(&["--warn-unused-ignores"], "warn_unused_ignores"),
            args::flag(&["--disregard-sqlfluffignores"], "disregard_sqlfluffignores"),
            args::not_yet(&["--recursion-limit"], ArgKind::Value),
            $($extra),*
        ]
    };
}

const LINT_OPTS: &[Opt] = common_opts!(
    args::value(&["-f", "--format"], "format"),
    args::value(&["--write-output"], "write_output"),
    args::value(&["--annotation-level"], "annotation_level"),
    args::flag(&["--nofail"], "nofail"),
);

const FIX_OPTS: &[Opt] = common_opts!(
    args::flag(&["-f", "--force"], "force"),
    args::flag(&["--check"], "check"),
    args::value(&["-x", "--fixed-suffix"], "fixed_suffix"),
    args::flag(&["--FIX-EVEN-UNPARSABLE"], "fix_even_unparsable"),
    args::not_yet(&["--show-lint-violations"], ArgKind::Flag),
);

const COMMON_HELP: &str = "\
  -n, --nocolor / --color  No color, or color, in the output.
  -d, --dialect TEXT       The dialect of the SQL.
  -t, --templater TEXT     The templater (default: jinja). sqll has raw, and
                           jinja only for a file with no Jinja tag.
  -r, --rules TEXT         Only these rules (comma separated).
  -e, --exclude-rules TEXT Not these rules (comma separated).
  --config PATH            An extra config file, read last.
  --ignore-local-config    Read no config file of a folder or of the user.
  --encoding TEXT          The encoding of the files (UTF-8 only).
  -i, --ignore TEXT        Ignore these kinds of errors (for example
                           parsing,lexing).
  --disable-noqa           Read no noqa comments.
  --disable-noqa-except TEXT
                           Read only these rules in noqa comments.
  -q, --quiet              Write no status lines.
  -p, --processes INTEGER  sqll lints one file at a time: only 1.
  --disable-progress-bar   No effect: sqll has no progress bar.
  --warn-unused-ignores    Warn about unused noqa comments.
  --disregard-sqlfluffignores
                           Read no ignore files.
  -h, --help               Show this message and exit.
";

fn lint_usage() -> String {
    format!(
        "Usage: sqll lint [OPTIONS] [PATHS]...

  Lint SQL files. PATH is a file, a folder, or \"-\" (stdin).

Options:
  -f, --format [human|json|yaml|github-annotation|github-annotation-native|none]
                           The output format (default: human).
  --write-output PATH      Write the output to this file.
  --annotation-level [notice|warning|failure|error]
                           The level of a github annotation (default:
                           warning).
  --nofail                 Exit code 0 also for violations.
{COMMON_HELP}"
    )
}

fn fix_usage() -> String {
    format!(
        "Usage: sqll fix [OPTIONS] [PATHS]...

  Fix SQL files in place. PATH is a file, a folder, or \"-\" (stdin: the
  fixed SQL goes to stdout).

Options:
  -f, --force              Deprecated: this is the default.
  --check                  Ask before the fixes are applied.
  -x, --fixed-suffix TEXT  Write each fixed file to a new file with this
                           suffix.
  --FIX-EVEN-UNPARSABLE    Not supported yet (fails closed).
{COMMON_HELP}"
    )
}

/// The kinds of output of sqlfluff `OutputKind`.
#[derive(Clone, Copy, PartialEq, Eq)]
enum OutKind {
    Diagnostic,
    Action,
    Status,
}

/// Where the formatter writes.
enum Stream {
    Stdout,
    File(BufWriter<File>),
    Null,
}

/// The output of a command: the formatter stream (sqlfluff
/// `OutputStream` with an `OutputPolicy`), the log lines, and stdout.
struct Out {
    stream: Stream,
    log_to_stdout: bool,
    painter: Painter,
    quiet: bool,
    machine: bool,
    stdout: BufWriter<std::io::Stdout>,
}

impl Out {
    fn allows(&self, kind: OutKind) -> bool {
        if self.machine {
            return false;
        }
        match kind {
            OutKind::Diagnostic | OutKind::Action => true,
            OutKind::Status => !self.quiet,
        }
    }

    /// `dispatch_message`: an empty message is not written.
    fn dispatch(&mut self, kind: OutKind, text: &str) {
        if !self.allows(kind) || text.trim_matches([' ', '\n', '\t']).is_empty() {
            return;
        }
        let _ = match &mut self.stream {
            Stream::Stdout => writeln!(self.stdout, "{text}"),
            Stream::File(f) => writeln!(f, "{text}"),
            Stream::Null => Ok(()),
        };
    }

    /// A warning of the sqlfluff log.
    fn log(&mut self, message: &str) {
        let line = self.painter.warning(message);
        if self.log_to_stdout {
            let _ = writeln!(self.stdout, "{line}");
        } else {
            self.err(&line);
        }
    }

    /// `click.echo` to stdout.
    fn echo(&mut self, text: &str) {
        let _ = writeln!(self.stdout, "{text}");
    }

    /// `click.echo(..., err=True)`.
    fn err(&mut self, text: &str) {
        let _ = self.stdout.flush();
        eprintln!("{text}");
    }

    fn flush(&mut self) -> Result<(), Error> {
        let a = self.stdout.flush();
        let b = match &mut self.stream {
            Stream::File(f) => f.flush(),
            _ => Ok(()),
        };
        a.and(b)
            .map_err(|e| Error::new(format!("cannot write the output: {e}")))
    }
}

/// The overrides of the `core` section that the options give (sqlfluff
/// `get_config`: each option that is set).
fn overrides(p: &Parsed, fix: bool) -> Result<Table, Error> {
    let mut t = Table::new();
    let text_keys = [
        "dialect",
        "templater",
        "rules",
        "exclude_rules",
        "encoding",
        "ignore",
        "disable_noqa_except",
    ];
    for key in text_keys {
        if let Some(v) = p.value(key) {
            t.insert(key.to_string(), Value::str(v));
        }
    }
    for key in ["disable_noqa", "warn_unused_ignores"] {
        if p.flag(key) {
            t.insert(key.to_string(), Value::Bool(true));
        }
    }
    if fix && p.flag("fix_even_unparsable") {
        t.insert("fix_even_unparsable".to_string(), Value::Bool(true));
    }
    if let Some(n) = nocolor_option(p) {
        t.insert("nocolor".to_string(), Value::Bool(n));
    }
    if let Some(v) = p.value("processes") {
        let n: i64 = v.trim().parse().map_err(|_| {
            Error::new(format!(
                "Invalid value for '-p' / '--processes': '{v}' is not a valid integer."
            ))
        })?;
        t.insert("processes".to_string(), Value::Int(n));
    }
    Ok(t)
}

/// The steps before the files: the options, the config, and the output.
struct Setup {
    env: Env,
    options: LoadOptions,
    root: Config,
    painter: Painter,
    line_length: usize,
}

fn setup(p: &Parsed, fix: bool) -> Result<Setup, Error> {
    let cli_painter = Painter::new(nocolor_option(p));
    if let Some(d) = p.value("dialect") {
        if steps::dialect(d).is_none() {
            return Err(Error::stdout(
                cli_painter.paint(&format!("Error: Unknown dialect '{d}'"), Some(Color::Red)),
            ));
        }
    }
    let overrides = overrides(p, fix)?;
    let env = Env::from_process().map_err(root_config_error)?;
    let options = LoadOptions {
        extra_config_path: p.value("config").map(str::to_string),
        ignore_local_config: p.flag("ignore_local_config"),
        overrides,
    };
    let root = {
        let mut loader = sqll_config::Loader::new(&env);
        Config::from_root(&mut loader, &options).map_err(|e| match e {
            sqll_config::ConfigError::Unsupported(_) => Error::new(e.to_string()),
            other => Error::stdout(
                cli_painter.paint(&format!("Error loading config: {other}"), Some(Color::Red)),
            ),
        })?
    };
    if let Some(v) = root.core("verbose") {
        if !v.py_eq(&Value::Int(0)) {
            return Err(unsupported(
                &format!("setting core:verbose = {v}"),
                "sqll lint and fix write no verbose output (verbose 0 only)",
            ));
        }
    }
    let painter = painter_of(&root);
    let line_length = output_line_length(&root)?;
    Ok(Setup {
        env,
        options,
        root,
        painter,
        line_length,
    })
}

/// The effective processes of a lint of `files` files (sqlfluff
/// `lint_paths` and `get_runner`): sqll lints one file at a time.
fn check_processes(root: &Config, files: usize) -> Result<(), Error> {
    if files <= 1 {
        return Ok(());
    }
    let n = match root.core("processes") {
        None | Some(Value::None) => 1,
        Some(Value::Int(n)) => *n,
        Some(v) => {
            return Err(unsupported(
                &format!("setting core:processes = {v}"),
                "sqll reads only an int",
            ))
        }
    };
    let cpus = std::thread::available_parallelism().map_or(1, |c| c.get() as i64);
    let effective = if n > 0 { n } else { (cpus + n).max(1) };
    if effective != 1 {
        return Err(unsupported(
            &format!("{effective} processes"),
            "sqll lints one file at a time (processes 1)",
        ));
    }
    Ok(())
}

/// The files of the paths (sqlfluff `lint_paths`): all paths first.
fn expand_paths(
    run: &mut Run<'_>,
    paths: &[String],
    ignore_files: bool,
) -> Result<Vec<String>, Error> {
    let exts = sql_file_exts(&run.root).map_err(file::config_error)?;
    let paths: Vec<String> = if paths.is_empty() {
        vec![std::env::current_dir()
            .map_err(|e| Error::new(format!("cannot read the working folder: {e}")))?
            .to_str()
            .ok_or_else(|| {
                unsupported(
                    "a working folder that is not UTF-8",
                    "sqll reads only UTF-8 paths",
                )
            })?
            .to_string()]
    } else {
        paths.to_vec()
    };
    let mut out = Vec::new();
    for path in &paths {
        out.extend(files::files_of(&mut run.loader, path, &exts, ignore_files)?);
    }
    Ok(out)
}

/// The counts of a lint (sqlfluff `LintedDir` stats).
#[derive(Default)]
struct Counts {
    files: usize,
    violations: usize,
    skipped: usize,
}

fn large_file_skip_fail(root: &Config) -> bool {
    root.core("large_file_skip_fail")
        .is_some_and(Value::is_truthy)
}

/// The dialect warning after the violations of a file with a parse error.
fn dialect_warning(out: &mut Out, config_dialect: &str) {
    let text = out.painter.paint(
        &format!(
            "WARNING: Parsing errors found and dialect is set to '{config_dialect}'. Have you \
             configured your dialect correctly?"
        ),
        Some(Color::Light),
    );
    out.dispatch(OutKind::Diagnostic, &text);
}

/// The dialect of a file for the dialect warning: that of its config.
fn dialect_of(run: &mut Run<'_>, path: &str) -> String {
    if path == "stdin" {
        return run.root.dialect().unwrap_or("None").to_string();
    }
    Config::from_path(&mut run.loader, path, &run.options)
        .ok()
        .and_then(|c| c.dialect().map(str::to_string))
        .unwrap_or_else(|| "None".to_string())
}

/// The command `sqll lint`.
pub fn lint_command(args: &[String]) -> Result<u8, Error> {
    let usage = lint_usage();
    let p = args::read(args, LINT_OPTS, &usage)?;
    if p.help {
        print!("{usage}");
        return Ok(EXIT_OK);
    }
    let format = p.value("format").unwrap_or("human").to_lowercase();
    match format.as_str() {
        "human" | "json" | "yaml" | "github-annotation" | "github-annotation-native" | "none" => {}
        "sarif" | "gitlab" => {
            return Err(unsupported(
                &format!("format {format}"),
                "sqll lint does not have this format yet (S7)",
            ))
        }
        other => {
            return Err(Error::new(format!(
                "Invalid value for '-f' / '--format': '{other}' is not one of 'human', 'json', \
                 'yaml', 'sarif', 'github-annotation', 'github-annotation-native', 'gitlab', \
                 'none'."
            )))
        }
    }
    let level = p
        .value("annotation_level")
        .unwrap_or("warning")
        .to_lowercase();
    if !["notice", "warning", "failure", "error"].contains(&level.as_str()) {
        return Err(Error::new(format!(
            "Invalid value for '--annotation-level': '{level}' is not one of 'notice', \
             'warning', 'failure', 'error'."
        )));
    }
    let write_output = p.value("write_output").map(str::to_string);
    let human = format == "human";
    let non_human = !human || write_output.is_some();
    let s = setup(&p, false)?;
    let stream = if human {
        match &write_output {
            None => Stream::Stdout,
            Some(path) => Stream::File(BufWriter::new(
                File::create(path).map_err(|e| Error::new(format!("cannot write {path}: {e}")))?,
            )),
        }
    } else {
        Stream::Null
    };
    let mut out = Out {
        stream,
        log_to_stdout: !non_human,
        painter: s.painter,
        quiet: p.flag("quiet"),
        machine: !human,
        stdout: BufWriter::new(std::io::stdout()),
    };
    let mut run = Run::new(&s.env, s.options.clone(), s.root.clone(), false)?;
    let mut counts = Counts::default();
    // The output text of each file record (sorted by path at the end), not
    // the record: the memory of a json run grows only with its output.
    let mut pieces: Vec<(String, String)> = Vec::new();
    let stdin = p.paths == ["-"];
    let files = if stdin {
        Vec::new()
    } else {
        let f = expand_paths(&mut run, &p.paths, !p.flag("disregard_sqlfluffignores"))?;
        check_processes(&s.root, f.len())?;
        f
    };
    let mut lint_one =
        |run: &mut Run<'_>, out: &mut Out, path: Option<&str>| -> Result<(), Error> {
            let outcome = match path {
                None => file::lint_stdin(run)?,
                Some(f) => file::lint_file(run, f)?,
            };
            let (linted, warnings) = match outcome {
                Outcome::Skipped(w) => {
                    out.log(&w);
                    counts.skipped += 1;
                    return Ok(());
                }
                Outcome::Linted(l, w) => (l, w),
            };
            for w in &warnings {
                out.log(w);
            }
            let shown: Vec<&Issue> = linted.violations(false).collect();
            let text = format_file_violations(&out.painter, &linted.path, &shown, s.line_length);
            out.dispatch(OutKind::Diagnostic, &text);
            if linted.violations(true).any(|i| i.kind == Kind::Parse) {
                let d = dialect_of(run, &linted.path);
                dialect_warning(out, &d);
            }
            counts.files += 1;
            counts.violations += linted.num_violations();
            if !human {
                let rec = record::file_record(&linted);
                let piece = match format.as_str() {
                    "json" => record::json(&rec),
                    "yaml" => yaml::dump(&Rec::List(vec![rec])),
                    "github-annotation" => record::github_annotation_items(&rec, &level),
                    "github-annotation-native" => {
                        record::github_annotation_native(std::slice::from_ref(&rec), &level)
                    }
                    _ => String::new(),
                };
                pieces.push((linted.path.clone(), piece));
            }
            Ok(())
        };
    if stdin {
        lint_one(&mut run, &mut out, None)?;
    } else {
        for f in &files {
            lint_one(&mut run, &mut out, Some(f))?;
        }
    }
    // as_records: sorted by path (a stable sort, as Python sorted).
    pieces.sort_by(|a, b| a.0.cmp(&b.0));
    let texts: Vec<&str> = pieces.iter().map(|(_, t)| t.as_str()).collect();
    let nonempty: Vec<&str> = texts.iter().copied().filter(|t| !t.is_empty()).collect();
    // The payload in parts, so that the output is not copied once more.
    let parts: Vec<&str> = match format.as_str() {
        "json" => framed("[", &texts, ", ", "]"),
        "yaml" if texts.is_empty() => vec!["[]\n"],
        "yaml" => texts.clone(),
        "github-annotation" => framed("[", &nonempty, ", ", "]"),
        "github-annotation-native" => framed("", &nonempty, "\n", ""),
        _ => Vec::new(),
    };
    if parts.iter().any(|p| !p.is_empty()) {
        match &write_output {
            Some(path) => {
                let fail = |e: std::io::Error| Error::new(format!("cannot write {path}: {e}"));
                let mut f = BufWriter::new(File::create(path).map_err(fail)?);
                for part in &parts {
                    f.write_all(part.as_bytes()).map_err(fail)?;
                }
                f.flush().map_err(fail)?;
            }
            None => {
                for part in &parts {
                    let _ = out.stdout.write_all(part.as_bytes());
                }
                out.echo("");
            }
        }
    }
    let code = if p.flag("nofail") {
        EXIT_OK
    } else {
        if !non_human {
            completion(&mut out);
        }
        let mut code = if counts.violations > 0 {
            EXIT_FAIL
        } else {
            EXIT_OK
        };
        if counts.skipped > 0 && large_file_skip_fail(&s.root) {
            code = code.max(EXIT_FAIL);
        }
        code
    };
    out.flush()?;
    Ok(code)
}

/// The parts of `open + items.join(sep) + close`.
fn framed<'a>(open: &'a str, items: &[&'a str], sep: &'a str, close: &'a str) -> Vec<&'a str> {
    let mut out = vec![open];
    for (i, item) in items.iter().enumerate() {
        if i > 0 {
            out.push(sep);
        }
        out.push(item);
    }
    out.push(close);
    out
}

/// sqlfluff `completion_message`.
fn completion(out: &mut Out) {
    let text = if out.painter.plain {
        "All Finished!"
    } else {
        "All Finished \u{1f4dc} \u{1f389}!"
    };
    out.dispatch(OutKind::Status, text);
}

/// Python `os.path.splitext`.
fn splitext(path: &str) -> (&str, &str) {
    let base_start = path.rfind('/').map_or(0, |i| i + 1);
    let base = &path[base_start..];
    let dots = base.len() - base.trim_start_matches('.').len();
    match base[dots..].rfind('.') {
        Some(i) => path.split_at(base_start + dots + i),
        None => (path, ""),
    }
}

/// sqlfluff `_safe_create_replace_file`: write a temporary file in the
/// folder, give it the mode of the input file, and move it to the output
/// path.
fn write_fixed(input: &str, output: &str, text: &str, bom: bool) -> Result<(), Error> {
    let fail = |e: std::io::Error| Error::new(format!("cannot write {output}: {e}"));
    let (dir, base) = match output.rfind('/') {
        Some(i) => (&output[..=i], &output[i + 1..]),
        None => ("", output),
    };
    let tmp = format!("{dir}{base}.sqll-{}.tmp", std::process::id());
    let result = (|| {
        let mut f = File::create(&tmp)?;
        if bom {
            f.write_all("\u{feff}".as_bytes())?;
        }
        f.write_all(text.as_bytes())?;
        f.sync_all()?;
        if let Ok(meta) = std::fs::metadata(input) {
            if meta.is_file() {
                let mode = meta.permissions().mode() & 0o7777;
                std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(mode))?;
            }
        }
        std::fs::rename(&tmp, output)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&tmp);
    }
    result.map_err(fail)
}

/// sqlfluff `persist_tree`: write the fixes of a file. The label (FIXED,
/// FAIL, or SKIP) and success.
fn persist(l: &Linted, suffix: &str) -> Result<(&'static str, bool), Error> {
    if !l.violations(false).any(Issue::fixable) {
        return Ok(("SKIP", true));
    }
    if l.fixed == l.source {
        return Ok(("FAIL", false));
    }
    let output = if suffix.is_empty() {
        l.path.clone()
    } else {
        let (root, ext) = splitext(&l.path);
        format!("{root}{suffix}{ext}")
    };
    write_fixed(&l.path, &output, &l.fixed, l.bom)?;
    Ok(("FIXED", true))
}

/// `dispatch_persist_filename`: a SKIP is written only at verbosity 2.
fn dispatch_persist(out: &mut Out, path: &str, label: &str) {
    if label != "SKIP" {
        let text = format_filename(&out.painter, path, label);
        out.dispatch(OutKind::Action, &text);
    }
}

/// The parse errors of a file for the residual error output.
fn tmp_prs_issues(issues: &[Issue], retained: bool) -> Vec<Issue> {
    issues
        .iter()
        .filter(|i| i.kind == Kind::Parse)
        .filter(|i| !i.ignore && (!retained || !i.warning))
        .map(|i| {
            let mut i = i.clone();
            if !retained {
                // From a record: a new SQLParseError (no warning flag).
                i.warning = false;
            }
            i
        })
        .collect()
}

/// sqlfluff `print_out_residual_error_counts` (stderr).
fn residual_errors(
    out: &mut Out,
    total: usize,
    filtered: usize,
    by_file: &[(String, Vec<Issue>)],
    line_length: usize,
) {
    if total == 0 {
        return;
    }
    let p = out.painter;
    out.err(&p.paint(
        &format!("  [{total} templating/parsing errors found]"),
        Some(Color::Red),
    ));
    for (path, errors) in by_file {
        out.err(&p.paint(&format!("  == [{path}] =="), Some(Color::Light)));
        for e in errors {
            let text = format_violation(&p, &ViolationText::of(e), line_length);
            out.err(&p.paint(&format!("  {text}"), Some(Color::Red)));
        }
    }
    if filtered < total {
        let color = if filtered > 0 {
            Color::Red
        } else {
            Color::Green
        };
        out.err(&p.paint(
            &format!(
                "  [{filtered} templating/parsing errors remaining after \"ignore\" & \"warning\"]"
            ),
            Some(color),
        ));
    }
}

/// The command `sqll fix`.
pub fn fix_command(args: &[String]) -> Result<u8, Error> {
    let usage = fix_usage();
    let p = args::read(args, FIX_OPTS, &usage)?;
    if p.help {
        print!("{usage}");
        return Ok(EXIT_OK);
    }
    let stdin = p.paths == ["-"];
    let check = p.flag("check");
    let suffix = p.value("fixed_suffix").unwrap_or("").to_string();
    let s = setup(&p, true)?;
    let mut out = Out {
        stream: if stdin { Stream::Null } else { Stream::Stdout },
        log_to_stdout: !stdin,
        painter: s.painter,
        quiet: p.flag("quiet"),
        machine: false,
        stdout: BufWriter::new(std::io::stdout()),
    };
    if p.flag("force") {
        let text = out.painter.paint(
            "The -f/--force option is deprecated as it is now the default behaviour.",
            Some(Color::Red),
        );
        out.err(&text);
    }
    let mut run = Run::new(&s.env, s.options.clone(), s.root.clone(), true)?;
    if stdin {
        let code = stdin_fix(&mut run, &mut out, s.line_length)?;
        out.flush()?;
        return Ok(code);
    }
    out.dispatch(OutKind::Status, "==== finding fixable violations ====");
    let files = expand_paths(&mut run, &p.paths, !p.flag("disregard_sqlfluffignores"))?;
    check_processes(&s.root, files.len())?;
    // fix keeps the files only for --check (sqlfluff `retain_files`), so
    // that its memory does not grow with the number of files (status/S3b.md,
    // C13).
    let mut retained: Vec<Box<Linted>> = Vec::new();
    let mut skipped = 0;
    // The counts of _handle_unparsable and of the fixable and unfixable
    // violations, and the parse errors of each file for the residual output.
    let (mut total, mut filtered, mut unfixable, mut fixable) = (0, 0, 0, 0);
    let mut by_file: Vec<(String, Vec<Issue>)> = Vec::new();
    for f in &files {
        let (mut linted, warnings) = match file::lint_file(&mut run, f)? {
            Outcome::Skipped(w) => {
                out.log(&w);
                skipped += 1;
                continue;
            }
            Outcome::Linted(l, w) => (l, w),
        };
        for w in &warnings {
            out.log(w);
        }
        let shown: Vec<&Issue> = linted.violations(false).filter(|i| i.fixable()).collect();
        let text = format_file_violations(&out.painter, &linted.path, &shown, s.line_length);
        out.dispatch(OutKind::Status, &text);
        let prs = linted.tmp_prs(true);
        if !check && prs == 0 {
            let (label, _) = persist(&linted, &suffix)?;
            dispatch_persist(&mut out, &linted.path, label);
        }
        total += prs;
        filtered += linted.tmp_prs(false);
        unfixable += linted
            .issues
            .iter()
            .filter(|i| i.kind == Kind::Lint && !i.ignore && !i.warning && !i.fixable())
            .count();
        let fixes = linted
            .issues
            .iter()
            .filter(|i| !i.ignore && i.fixable())
            .count();
        if prs > 0 {
            // discard_fixes_for_lint_errors_in_files_with_tmp_or_prs_errors
            unfixable += fixes;
            for i in &mut linted.issues {
                i.fixes.clear();
            }
        } else {
            fixable += fixes;
        }
        let errors = tmp_prs_issues(&linted.issues, check);
        if check || !errors.is_empty() {
            by_file.push((linted.path.clone(), errors));
        }
        if check {
            retained.push(linted);
        }
    }
    residual_errors(&mut out, total, filtered, &by_file, s.line_length);
    let mut code = if filtered > 0 { EXIT_FAIL } else { EXIT_OK };
    if fixable > 0 {
        if check {
            out.dispatch(OutKind::Status, "==== fixing violations ====");
        }
        out.dispatch(
            OutKind::Action,
            &format!("{fixable} fixable linting violations found"),
        );
        if check {
            let _ = write!(
                out.stdout,
                "Are you sure you wish to attempt to fix these? [Y/n] "
            );
            out.flush()?;
            let key = crate::tty::getchar().map_err(|e| {
                Error::new(format!("cannot read the answer from the terminal: {e}"))
            })?;
            let answer = match key {
                crate::tty::Key::Abort => {
                    out.echo("");
                    out.err("Aborted!");
                    out.flush()?;
                    return Ok(EXIT_FAIL);
                }
                crate::tty::Key::Text(t) => t.to_lowercase(),
            };
            out.echo("...");
            if ["y", "\r", "\n"].contains(&answer.as_str()) {
                out.dispatch(OutKind::Status, "Attempting fixes...");
                out.dispatch(OutKind::Status, "Persisting Changes...");
                let mut all = true;
                for l in &retained {
                    let (label, ok) = persist(l, &suffix)?;
                    dispatch_persist(&mut out, &l.path, label);
                    all &= ok;
                }
                if !all {
                    out.echo("Done. Some operations failed. Please check your files to confirm.");
                    out.echo("Some errors cannot be fixed or there is another error blocking it.");
                    out.flush()?;
                    return Ok(EXIT_FAIL);
                }
                out.dispatch(OutKind::Status, "Done. Please check your files to confirm.");
                completion(&mut out);
            } else if answer == "n" {
                out.echo("Aborting...");
                code = EXIT_FAIL;
            } else {
                out.echo("Invalid input, please enter 'Y' or 'N'");
                out.echo("Aborting...");
                code = EXIT_FAIL;
            }
        }
    } else {
        out.dispatch(
            OutKind::Status,
            "==== no fixable linting violations found ====",
        );
        completion(&mut out);
    }
    if unfixable > 0 {
        out.dispatch(
            OutKind::Diagnostic,
            &format!("  [{unfixable} unfixable linting violations found]"),
        );
        code = code.max(EXIT_FAIL);
    }
    if skipped > 0 && large_file_skip_fail(&s.root) {
        code = code.max(EXIT_FAIL);
    }
    out.flush()?;
    Ok(code)
}

/// sqlfluff `_stdin_fix`: the fixed SQL (or the input) on stdout.
fn stdin_fix(run: &mut Run<'_>, out: &mut Out, line_length: usize) -> Result<u8, Error> {
    let mut linted = match file::lint_stdin(run)? {
        Outcome::Linted(l, warnings) => {
            for w in &warnings {
                out.log(w);
            }
            l
        }
        Outcome::Skipped(_) => unreachable!("stdin has no byte limit"),
    };
    let unfixable = linted
        .violations(true)
        .any(|i| i.kind == Kind::Lint && !i.fixable());
    let total = linted.tmp_prs(true);
    let filtered = linted.tmp_prs(false);
    if total > 0 {
        for i in &mut linted.issues {
            i.fixes.clear();
        }
    }
    let by_file = vec![(linted.path.clone(), tmp_prs_issues(&linted.issues, true))];
    residual_errors(out, total, filtered, &by_file, line_length);
    let code = if filtered > 0 { EXIT_FAIL } else { EXIT_OK };
    let fixable = linted
        .violations(true)
        .any(|i| i.kind == Kind::Lint && i.fixable());
    let text = if fixable {
        &linted.fixed
    } else {
        &linted.source
    };
    if unfixable {
        let msg = out
            .painter
            .paint("Unfixable violations detected.", Some(Color::Red));
        out.err(&msg);
    }
    let mut data = Vec::new();
    if linted.bom {
        data.extend_from_slice("\u{feff}".as_bytes());
    }
    data.extend_from_slice(text.as_bytes());
    let _ = out.stdout.write_all(&data);
    Ok(if unfixable { EXIT_FAIL } else { code })
}

#[cfg(test)]
mod tests {
    use super::splitext;

    #[test]
    fn splitext_is_that_of_python() {
        for (path, want) in [
            ("a.sql", ("a", ".sql")),
            ("d/a.b.sql", ("d/a.b", ".sql")),
            ("d.x/a", ("d.x/a", "")),
            (".hidden", (".hidden", "")),
            ("..a.sql", ("..a", ".sql")),
            ("a.", ("a", ".")),
        ] {
            assert_eq!(splitext(path), want, "{path}");
        }
    }

    #[test]
    fn exit_codes_are_those_of_sqlfluff() {
        assert_eq!(
            (crate::EXIT_OK, crate::EXIT_FAIL, crate::EXIT_ERROR),
            (0, 1, 2)
        );
    }
}
