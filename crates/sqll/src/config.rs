//! The config of "sqll parse" (S3b C11): the steps of "sqlfluff parse" for
//! one path, from the options to the settings of the parse
//! (sqll_config, docs/interfaces/config.md).
//!
//! The steps and their order follow sqlfluff 4.4.0 (src/sqlfluff/cli/
//! commands.py parse and get_config, src/sqlfluff/core/linter/linter.py
//! parse_path, load_raw_file_and_config, render_string, and the
//! large_file_check of src/sqlfluff/core/templaters/base.py; MIT, see
//! THIRD_PARTY.md). This file is new sqll code.

use sqll_config::parse::{check_ignore_files, has_sql_extension, sql_file_exts};
use sqll_config::{
    Config, ConfigError, Env, LoadOptions, Loader, ParseSettings, Table, TemplaterName, Value,
};

use crate::{normpath, unsupported, Error, ParseArgs};

/// What "sqll parse" does with the path.
pub enum Input {
    /// No parse: print this output and exit with code 0 (a file with
    /// another extension, or a file over the byte limit).
    Skip(String),
    Parse(Box<ParseInput>),
}

pub struct ParseInput {
    pub settings: ParseSettings,
}

fn config_error(e: ConfigError) -> Error {
    match e {
        ConfigError::Unsupported(_) => Error(e.to_string()),
        other => Error(format!("Error loading config: {other}")),
    }
}

/// A warning of the sqlfluff log on stderr (the format of the sqlfluff
/// CLI with no color: "%(levelname)-10s %(message)s" and a space).
pub fn warn(message: &str) {
    eprintln!("WARNING    {message} ");
}

/// The command line overrides of the core section, as sqlfluff makes them
/// from its options.
fn overrides(args: &ParseArgs) -> Table {
    let mut t = Table::new();
    if let Some(d) = &args.dialect {
        t.insert("dialect".to_string(), Value::str(d));
    }
    if let Some(name) = &args.templater {
        t.insert("templater".to_string(), Value::str(name));
    }
    if let Some(depth) = args.max_parse_depth {
        let depth = i64::try_from(depth).unwrap_or(i64::MAX);
        t.insert("max_parse_depth".to_string(), Value::Int(depth));
    }
    t
}

/// Load the root config and the config of the path, and make the settings
/// of the parse.
pub fn load(args: &ParseArgs, path: &str) -> Result<Input, Error> {
    let env = Env::from_process().map_err(config_error)?;
    let mut loader = Loader::new(&env);
    let options = LoadOptions {
        extra_config_path: args.config.clone(),
        ignore_local_config: args.ignore_local_config,
        overrides: overrides(args),
    };
    let root = Config::from_root(&mut loader, &options).map_err(config_error)?;
    if path == "-" {
        let settings = ParseSettings::for_stdin(&root).map_err(config_error)?;
        return Ok(Input::Parse(Box::new(ParseInput { settings })));
    }
    let meta = std::fs::metadata(path).map_err(|e| Error(format!("cannot read {path}: {e}")))?;
    if meta.is_dir() {
        return Err(unsupported(
            &format!("folder {path}"),
            "sqll parses one file",
        ));
    }
    let exts = sql_file_exts(&root).map_err(config_error)?;
    // sqlfluff loads the ignore files of the folders (and with them, each
    // .sqlfluff and pyproject.toml file, with their checks) before it
    // applies the extensions (paths_from_path in
    // src/sqlfluff/core/linter/discovery.py).
    check_ignore_files(&mut loader, path).map_err(config_error)?;
    if !has_sql_extension(path, &exts) {
        return Ok(Input::Skip("[]\n".to_string()));
    }
    // From here sqlfluff uses the normalised path (`_process_exact_path`
    // returns os.path.normpath(path)): the config of the file comes from the
    // folders of that path, not from a folder that ".." leaves.
    let fname = normpath(path);
    let file = Config::from_path(&mut loader, &fname, &options).map_err(config_error)?;
    let settings = ParseSettings::new(&root, &file).map_err(config_error)?;
    let limit = settings.large_file_skip_byte_limit;
    if limit != 0 {
        let size = if fname == path {
            meta.len()
        } else {
            std::fs::metadata(&fname)
                .map_err(|e| Error(format!("cannot read {fname}: {e}")))?
                .len()
        };
        if i128::from(size) > i128::from(limit) {
            warn(&format!(
                "Length of file {} is {size} bytes which is over the limit of {limit} \
                 bytes. Skipping to avoid parser lock. Users can increase this limit in their \
                 config by setting the 'large_file_skip_byte_limit' value, or disable by \
                 setting it to zero.",
                py_repr(&fname)
            ));
            return Ok(Input::Skip("[]\n".to_string()));
        }
    }
    Ok(Input::Parse(Box::new(ParseInput { settings })))
}

/// The character limit of the templater (`large_file_check`): true if the
/// file is skipped. sqlfluff then prints the record with no segments.
pub fn skip_by_chars(settings: &ParseSettings, sql: &str, filepath: &str) -> bool {
    let limit = settings.large_file_skip_char_limit;
    if limit == 0 {
        return false;
    }
    warn(
        "The config value large_file_skip_char_limit was found set. This feature will be \
         removed in a future release, please use the more efficient \
         'large_file_skip_byte_limit' instead.",
    );
    let chars = sql.chars().count();
    if i128::try_from(chars).unwrap_or(i128::MAX) > i128::from(limit) {
        warn(&format!(
            "Length of file {} is over {limit} characters. Skipping to avoid parser \
             lock. Users can increase this limit in their config by setting the \
             'large_file_skip_char_limit' value, or disable by setting it to zero.",
            py_repr(filepath)
        ));
        return true;
    }
    false
}

/// Python `repr(text)` (the `{fname!r}` of the sqlfluff warnings): `'`
/// quotes, or `"` quotes for a text with `'` and no `"`; an escape for `\`,
/// the quote, `\t`, `\n`, `\r`, and the characters below U+0100 that Python
/// does not print. sqll writes a character from U+0100 up as it is (Python
/// writes an escape for some of them; docs/interfaces/config.md).
fn py_repr(text: &str) -> String {
    let quote = if text.contains('\'') && !text.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(text.len() + 2);
    out.push(quote);
    for c in text.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            // Cc, the no-break space (Zs), and the soft hyphen (Cf).
            '\0'..='\x1f' | '\x7f'..='\u{a0}' | '\u{ad}' => {
                out.push_str(&format!("\\x{:02x}", u32::from(c)));
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// The jinja templater: sqll can do it only for a text that is not empty
/// and has no Jinja delimiter (then it gives the file of the raw
/// templater).
pub fn check_templater(settings: &ParseSettings, sql: &str) -> Result<(), Error> {
    if settings.templater == TemplaterName::Jinja && !sqll_templater::jinja_is_literal(sql) {
        return Err(unsupported(
            "templater jinja for an empty file or a file with a Jinja tag (\"{{\", \"{%\", or \"{#\")",
            "sqll has no Jinja templater yet (S11). Use the raw templater (--templater raw)",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::py_repr;

    #[test]
    fn a_file_name_is_written_as_python_repr() {
        // Python 3.13: repr() of each name.
        for (name, want) in [
            ("a.sql", "'a.sql'"),
            ("it's.sql", "\"it's.sql\""),
            ("a\"b.sql", "'a\"b.sql'"),
            ("a'b\"c.sql", "'a\\'b\"c.sql'"),
            ("a\\b.sql", "'a\\\\b.sql'"),
            ("a\tb\nc\rd.sql", "'a\\tb\\nc\\rd.sql'"),
            ("a\x01\x1f\x7f.sql", "'a\\x01\\x1f\\x7f.sql'"),
            ("a\u{85}\u{a0}\u{ad}.sql", "'a\\x85\\xa0\\xad.sql'"),
            ("\u{e9}\u{ff}\u{a1}.sql", "'\u{e9}\u{ff}\u{a1}.sql'"),
            ("\u{1f600}.sql", "'\u{1f600}.sql'"),
        ] {
            assert_eq!(py_repr(name), want, "{name:?}");
        }
    }
}
