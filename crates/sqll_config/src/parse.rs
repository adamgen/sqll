//! The settings of `sqll parse` (S3b task C11): the settings that change
//! the output of `sqlfluff parse -f json`, as sqll can do them. A setting
//! that sqll cannot do yet fails closed with [`ConfigError::Unsupported`];
//! a setting with no effect on the output of a parse is accepted with any
//! value. docs/interfaces/config.md lists each setting.
//!
//! sqlfluff takes the templater, `sql_file_exts`, `verbose`, and
//! `recursion_limit` from the config of the working folder (the "root"
//! config), and each other setting from the config of the file.

use crate::config::{rust_parser_enabled, Config};
use crate::defaults::default_table;
use crate::loader::{intermediate_paths, Loader};
use crate::value::Value;
use crate::ConfigError;

/// The templater of a parse.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TemplaterName {
    Raw,
    /// The Jinja templater with its default settings. sqll can do it only
    /// for a text with no Jinja delimiter (`sqll_templater::jinja_is_literal`).
    Jinja,
}

/// The `encoding` setting of a file.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Encoding {
    /// `autodetect`: sqll reads UTF-8 with or without a byte order mark.
    Autodetect,
    /// `utf-8`: a byte order mark stays in the text.
    Utf8,
    /// `utf-8-sig`: a byte order mark is removed.
    Utf8Sig,
}

/// The settings of a parse.
#[derive(Clone, Debug, PartialEq)]
pub struct ParseSettings {
    pub dialect: Option<String>,
    pub templater: TemplaterName,
    /// The warning of sqlfluff if the file config has another templater:
    /// sqlfluff uses the templater of the root config.
    pub templater_warning: Option<String>,
    /// `max_parse_depth` (0: no limit).
    pub max_parse_depth: u64,
    /// `max_parse_nodes` (0: no limit).
    pub max_parse_nodes: u64,
    /// `rust_parser_max_iterations` (None: the default).
    pub max_parser_iterations: Option<u64>,
    /// `rust_parser_warn_threshold` (None: the default).
    pub parser_warn_threshold: Option<u64>,
    /// The `indentation` section as the parser gets it.
    pub indentation: Vec<(String, bool)>,
    /// `large_file_skip_byte_limit` (0: no limit).
    pub large_file_skip_byte_limit: i64,
    /// `large_file_skip_char_limit` (0: no limit).
    pub large_file_skip_char_limit: i64,
    pub encoding: Encoding,
}

fn unsupported(path: &str, value: &Value, why: &str) -> ConfigError {
    ConfigError::Unsupported(format!("setting {path} = {value}. {why}"))
}

/// An int setting from 0: `None` (and each value that Python sees as
/// false) is the default.
fn optional_count(path: &str, value: &Value) -> Result<Option<u64>, ConfigError> {
    match value {
        v if !v.is_truthy() => Ok(None),
        Value::Int(i) if *i > 0 => Ok(Some(*i as u64)),
        v => Err(unsupported(
            path,
            v,
            "sqll reads only a positive int or nothing",
        )),
    }
}

/// The root config gives the templater; check it.
pub fn root_templater(root: &Config) -> Result<TemplaterName, ConfigError> {
    match root.templater() {
        "raw" => Ok(TemplaterName::Raw),
        "jinja" => Ok(TemplaterName::Jinja),
        other => Err(unsupported(
            "core:templater",
            &Value::str(other),
            "sqll has only the raw templater, and the jinja templater for a file with no Jinja tag (S6, S11)",
        )),
    }
}

/// `sql_file_exts` of the root config, lowercase, split on ",".
pub fn sql_file_exts(root: &Config) -> Result<Vec<String>, ConfigError> {
    match root.core("sql_file_exts") {
        Some(Value::Str(s)) => Ok(s.to_lowercase().split(',').map(str::to_string).collect()),
        Some(v) => Err(unsupported(
            "core:sql_file_exts",
            v,
            "sqll reads only a comma separated text",
        )),
        None => Ok(vec![".sql".to_string()]),
    }
}

/// True if the path has one of the extensions (in any case).
pub fn has_sql_extension(path: &str, exts: &[String]) -> bool {
    let lower = path.to_lowercase();
    exts.iter().any(|e| lower.ends_with(e.as_str()))
}

/// The ignore files of sqlfluff for a path (`.sqlfluffignore`, and
/// `ignore_paths` in a `.sqlfluff` or `pyproject.toml` file) in the folders
/// from the working folder to the path. sqll does not read them yet: one
/// that can ignore a file fails closed.
pub fn check_ignore_files(loader: &mut Loader, path: &str) -> Result<(), ConfigError> {
    let env = loader.env().clone();
    for folder in intermediate_paths(&env, path, &env.cwd) {
        let ignore = crate::loader::join(&folder, ".sqlfluffignore");
        if std::path::Path::new(&ignore).is_file() {
            return Err(ConfigError::Unsupported(format!(
                "the ignore file {ignore}: sqll does not read .sqlfluffignore files yet (S7)"
            )));
        }
        // The order of `ignore_file_loaders` (discovery.py).
        for name in ["pyproject.toml", ".sqlfluff"] {
            let file = crate::loader::join(&folder, name);
            if !std::path::Path::new(&file).is_file() {
                continue;
            }
            let config = loader.load_file(&env.realpath(&file))?;
            let patterns = crate::dict::get(&config, &["core", "ignore_paths"]);
            let any = match patterns {
                Some(Value::Str(_)) => true,
                Some(Value::List(l)) => !l.is_empty(),
                _ => false,
            };
            if any {
                return Err(ConfigError::Unsupported(format!(
                    "setting core:ignore_paths in {file}: sqll does not read ignore patterns yet (S7)"
                )));
            }
        }
    }
    Ok(())
}

impl ParseSettings {
    /// The settings of a parse of a file: `root` is the config of the
    /// working folder, `file` the config of the file.
    pub fn new(root: &Config, file: &Config) -> Result<ParseSettings, ConfigError> {
        ParseSettings::build(root, file, false)
    }

    /// The settings of a parse of stdin (the root config). sqlfluff reads
    /// stdin with `sys.stdin.read()` (src/sqlfluff/cli/commands.py,
    /// parse): it does not read the `encoding` setting, and a byte order
    /// mark stays in the text. Thus the encoding is [`Encoding::Utf8`] and
    /// the `encoding` setting has no effect.
    pub fn for_stdin(root: &Config) -> Result<ParseSettings, ConfigError> {
        ParseSettings::build(root, root, true)
    }

    fn build(root: &Config, file: &Config, stdin: bool) -> Result<ParseSettings, ConfigError> {
        let templater = root_templater(root)?;
        let templater_warning = (file.templater() != root.templater()).then(|| {
            format!(
                "Attempt to set templater to {} failed. Using {} templater. Templater cannot \
                 be set in a .sqlfluff file in a subdirectory of the current working \
                 directory. It can be set in a .sqlfluff in the current working directory. \
                 See Nesting section of the docs for more details.",
                file.templater(),
                root.templater()
            )
        });
        if let Some(v) = root.core("verbose") {
            if !v.py_eq(&Value::Int(0)) {
                return Err(unsupported(
                    "core:verbose",
                    v,
                    "sqll parse writes no log (verbose 0 only)",
                ));
            }
        }
        if let Some(v) = root.core("recursion_limit") {
            if *v != Value::None {
                return Err(unsupported(
                    "core:recursion_limit",
                    v,
                    "sqll has no Python recursion limit (None only)",
                ));
            }
        }
        let mut s = ParseSettings {
            dialect: file.dialect().map(str::to_string),
            templater,
            templater_warning,
            max_parse_depth: 0,
            max_parse_nodes: 0,
            max_parser_iterations: None,
            parser_warn_threshold: None,
            indentation: file.indentation(),
            large_file_skip_byte_limit: 0,
            large_file_skip_char_limit: 0,
            encoding: if stdin {
                Encoding::Utf8
            } else {
                Encoding::Autodetect
            },
        };
        let core = file
            .section(&["core"])
            .expect("a config has a core section");
        let default_table = default_table();
        for (key, value) in core {
            let path = format!("core:{key}");
            let default = crate::dict::get(&default_table, &["core", key]);
            match key.as_str() {
                "dialect" | "templater" | "sql_file_exts" | "verbose" | "recursion_limit" => {}
                "max_parse_depth" | "max_parse_nodes" => {
                    let Value::Int(i) = value else {
                        unreachable!("validate_config_dict checks {key}")
                    };
                    if key == "max_parse_depth" {
                        s.max_parse_depth = *i as u64;
                    } else {
                        s.max_parse_nodes = *i as u64;
                    }
                }
                "rust_parser_max_iterations" => {
                    s.max_parser_iterations = optional_count(&path, value)?
                }
                "rust_parser_warn_threshold" => {
                    s.parser_warn_threshold = optional_count(&path, value)?
                }
                "large_file_skip_byte_limit" | "large_file_skip_char_limit" => {
                    let limit = match value {
                        v if !v.is_truthy() => 0,
                        Value::Int(i) => *i,
                        Value::Bool(true) => 1,
                        v => return Err(unsupported(&path, v, "sqll reads only an int")),
                    };
                    if key == "large_file_skip_byte_limit" {
                        s.large_file_skip_byte_limit = limit;
                    } else {
                        s.large_file_skip_char_limit = limit;
                    }
                }
                "encoding" if stdin => {}
                "encoding" => s.encoding = encoding(&path, value)?,
                "use_rust_parser" => {
                    if !rust_parser_enabled(value) {
                        return Err(unsupported(
                            &path,
                            value,
                            "sqll has only the port of the sqlfluff Rust parser",
                        ));
                    }
                }
                "ignore" | "warnings" => {
                    if value.is_truthy() {
                        return Err(unsupported(
                            &path,
                            value,
                            "sqll parse does not ignore or warn on an error yet (S7)",
                        ));
                    }
                }
                "rules" | "exclude_rules" => {
                    if value.is_truthy() && !default.is_some_and(|d| d.py_eq(value)) {
                        return Err(unsupported(
                            &path,
                            value,
                            "sqlfluff parse reads the rule settings; sqll has no rules yet (S5)",
                        ));
                    }
                }
                "library_path" => {
                    if templater == TemplaterName::Jinja && value.is_truthy() {
                        return Err(unsupported(
                            &path,
                            value,
                            "sqll has no library path of the jinja templater (S11)",
                        ));
                    }
                }
                // Another key has no effect on a parse, or sqlfluff does
                // not read it. `ignore_paths` is checked before the parse
                // (`check_ignore_files`).
                _ => {}
            }
        }
        // sqlfluff checks the rule and layout settings in each parse
        // (get_rulepack); sqll can only do their defaults.
        for section in ["rules", "layout"] {
            let have = file.get(&[section]);
            let want = default_table.get(section);
            if !matches!((have, want), (Some(h), Some(w)) if h.py_eq(w)) {
                let path = first_difference(have, want, section);
                return Err(ConfigError::Unsupported(format!(
                    "setting {path}: sqll can only do the default rule and layout settings (S5)"
                )));
            }
        }
        if templater == TemplaterName::Jinja {
            let have = file.get(&["templater", "jinja"]);
            let want = crate::dict::get(&default_table, &["templater", "jinja"]);
            if !matches!((have, want), (Some(h), Some(w)) if h.py_eq(w)) {
                let path = first_difference(have, want, "templater:jinja");
                return Err(ConfigError::Unsupported(format!(
                    "setting {path}: sqll can only do the default jinja settings (S11)"
                )));
            }
        }
        Ok(s)
    }
}

/// The first key path where two sections differ, for messages.
fn first_difference(have: Option<&Value>, want: Option<&Value>, path: &str) -> String {
    if let (Some(Value::Table(h)), Some(Value::Table(w))) = (have, want) {
        for (k, v) in h {
            if !w.get(k).is_some_and(|x| x.py_eq(v)) {
                return first_difference(Some(v), w.get(k), &format!("{path}:{k}"));
            }
        }
        for k in w.keys() {
            if !h.contains_key(k) {
                return format!("{path}:{k}");
            }
        }
    }
    match have {
        Some(
            v @ (Value::Str(_) | Value::Int(_) | Value::Bool(_) | Value::Float(_) | Value::None),
        ) => {
            format!("{path} = {v}")
        }
        _ => path.to_string(),
    }
}

/// The `encoding` setting: `autodetect`, or a name of the Python UTF-8
/// codecs (after the Python name normalization).
fn encoding(path: &str, value: &Value) -> Result<Encoding, ConfigError> {
    let Value::Str(name) = value else {
        return Err(unsupported(path, value, "sqll reads only an encoding name"));
    };
    if name == "autodetect" {
        return Ok(Encoding::Autodetect);
    }
    let mut norm = String::new();
    let mut punct = false;
    for c in name.to_lowercase().chars() {
        if c.is_alphanumeric() || c == '.' {
            if punct && !norm.is_empty() {
                norm.push('_');
            }
            if c.is_ascii() {
                norm.push(c);
            }
            punct = false;
        } else {
            punct = true;
        }
    }
    match norm.replace('.', "_").as_str() {
        "utf_8" | "utf8" | "u8" | "utf" | "cp65001" => Ok(Encoding::Utf8),
        "utf_8_sig" => Ok(Encoding::Utf8Sig),
        _ => Err(unsupported(
            path,
            value,
            "sqll reads only UTF-8 (autodetect, utf-8, or utf-8-sig)",
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::value::Table;

    fn settings(text: &str) -> Result<ParseSettings, ConfigError> {
        let c = Config::new(
            crate::ini::load_ini_string(text, "x").unwrap(),
            &Table::new(),
        )?;
        ParseSettings::new(&c, &c)
    }

    #[test]
    fn the_defaults_give_the_parse_defaults() {
        let s = settings("").unwrap();
        assert_eq!(s.dialect, None);
        assert_eq!(s.templater, TemplaterName::Jinja);
        assert_eq!(s.max_parse_depth, 600);
        assert_eq!(s.max_parse_nodes, 100_000);
        assert_eq!(s.max_parser_iterations, Some(3_000_000));
        assert_eq!(s.parser_warn_threshold, Some(2_000_000));
        assert_eq!(s.large_file_skip_byte_limit, 20000);
        assert_eq!(s.large_file_skip_char_limit, 0);
        assert_eq!(s.encoding, Encoding::Autodetect);
        assert!(s
            .indentation
            .contains(&("indented_joins".to_string(), false)));
    }

    #[test]
    fn supported_settings() {
        let s = settings(
            "[sqlfluff]\ndialect = ansi\ntemplater = raw\nmax_parse_depth =\nrust_parser_max_iterations = 0\nlarge_file_skip_byte_limit = 0\nencoding = UTF-8\nnocolor = True\nunknown_key = 1\n[sqlfluff:indentation]\nindented_joins = True\n[sqlfluff:bar]\nx = 1\n",
        )
        .unwrap();
        assert_eq!(s.dialect.as_deref(), Some("ansi"));
        assert_eq!(s.templater, TemplaterName::Raw);
        assert_eq!(s.max_parse_depth, 0);
        assert_eq!(s.max_parser_iterations, None);
        assert_eq!(s.large_file_skip_byte_limit, 0);
        assert_eq!(s.encoding, Encoding::Utf8);
        assert!(s
            .indentation
            .contains(&("indented_joins".to_string(), true)));
    }

    #[test]
    fn unsupported_settings_fail_closed() {
        for text in [
            "[sqlfluff]\ntemplater = python\n",
            "[sqlfluff]\nverbose = 1\n",
            "[sqlfluff]\nrecursion_limit = 2000\n",
            "[sqlfluff]\nignore = parsing\n",
            "[sqlfluff]\nwarnings = PRS\n",
            "[sqlfluff]\nrules = CP01\n",
            "[sqlfluff]\nexclude_rules = CP01\n",
            "[sqlfluff]\nencoding = latin-1\n",
            "[sqlfluff]\nuse_rust_parser = False\n",
            "[sqlfluff]\nrust_parser_max_iterations = -1\n",
            "[sqlfluff]\nlarge_file_skip_byte_limit = big\n",
            "[sqlfluff]\nlibrary_path = libs\n",
            "[sqlfluff:rules:capitalisation.keywords]\ncapitalisation_policy = upper\n",
            "[sqlfluff:rules:XX01]\nx = 1\n",
            "[sqlfluff:layout:type:comma]\nline_position = leading\n",
            "[sqlfluff:templater:jinja]\napply_dbt_builtins = False\n",
            "[sqlfluff:templater:jinja:context]\nx = 1\n",
        ] {
            assert!(
                matches!(settings(text), Err(ConfigError::Unsupported(_))),
                "{text:?}"
            );
        }
        // With the raw templater, the jinja settings have no effect.
        assert!(settings(
            "[sqlfluff]\ntemplater = raw\n[sqlfluff:templater:jinja:context]\nx = 1\n"
        )
        .is_ok());
    }
}
