// This file is a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/config/fluffconfig.py (FluffConfig.__init__,
// _handle_comma_separated_values, get_templater_class,
// _verify_rust_config, from_root, from_path, get, get_section) and
// src/sqlfluff/core/helpers/string.py (split_comma_separated_string).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.
// Changes: the dialect name is not checked here (the caller knows the
// dialects); no plugin templaters.

//! A loaded config: the sqlfluff defaults, the config files, and the
//! command line overrides of the `core` section.

use crate::defaults::default_table;
use crate::dict::{get, nested_combine};
use crate::loader::Loader;
use crate::validate::validate_config_dict;
use crate::value::{py_strip, Table, Value};
use crate::ConfigError;

/// The templaters of sqlfluff 4.4.0 with no plugin, in the order of its
/// message.
pub const TEMPLATERS: [&str; 4] = ["raw", "jinja", "python", "placeholder"];

/// How to load a config (the sqlfluff command line options).
#[derive(Clone, Debug, Default)]
pub struct LoadOptions {
    /// `--config`: an extra config file, read last.
    pub extra_config_path: Option<String>,
    /// `--ignore-local-config`: read no config file of the user or of a
    /// folder, only the extra file.
    pub ignore_local_config: bool,
    /// The overrides of the `core` section (for example `--dialect`).
    pub overrides: Table,
}

/// A loaded config.
#[derive(Clone, Debug, PartialEq)]
pub struct Config {
    table: Table,
}

impl Config {
    /// `FluffConfig(configs, overrides=...)`: check the configs and the
    /// overrides, and combine them with the defaults. `require_dialect`
    /// is false here: [`Config::dialect`] gives `None` if no dialect is
    /// set.
    pub fn new(configs: Table, overrides: &Table) -> Result<Config, ConfigError> {
        let mut wrapped = Table::new();
        if !overrides.is_empty() {
            wrapped.insert("core".to_string(), Value::Table(overrides.clone()));
            validate_config_dict(&mut wrapped, "<provided overrides>")?;
        }
        let mut configs = configs;
        if configs.is_empty() {
            configs.insert("core".to_string(), Value::Table(Table::new()));
        } else {
            validate_config_dict(&mut configs, "<provided configs>")?;
        }
        let mut table = nested_combine(&[default_table(), &configs, &wrapped])?;
        let core = match table.get_mut("core") {
            Some(Value::Table(core)) => core,
            _ => {
                return Err(ConfigError::Invalid(
                    "the core section is not a section".into(),
                ))
            }
        };
        let color = match core.get("nocolor") {
            Some(Value::Bool(true)) => Value::Bool(false),
            Some(Value::Bool(false)) => Value::Bool(true),
            _ => Value::None,
        };
        core.insert("color".to_string(), color);
        for (key, out) in [
            ("ignore", "ignore"),
            ("warnings", "warnings"),
            ("rules", "rule_allowlist"),
            ("exclude_rules", "rule_denylist"),
        ] {
            let list = match core.get(key) {
                Some(v) if v.is_truthy() => split_comma_separated(v, key)?,
                _ => Value::List(Vec::new()),
            };
            core.insert(out.to_string(), list);
        }
        match core.get("dialect") {
            None | Some(Value::None) | Some(Value::Str(_)) => {}
            Some(v) => {
                return Err(ConfigError::Invalid(format!(
                    "the config value dialect must be a string, not {v}"
                )))
            }
        }
        let config = Config { table };
        config.check_templater()?;
        config.verify_rust_config()?;
        Ok(config)
    }

    /// `FluffConfig.from_path`: the config files up to `path` (a file or a
    /// folder) and the extra file, then [`Config::new`].
    pub fn from_path(
        loader: &mut Loader,
        path: &str,
        options: &LoadOptions,
    ) -> Result<Config, ConfigError> {
        let configs = loader.load_up_to_path(
            path,
            options.extra_config_path.as_deref(),
            options.ignore_local_config,
        )?;
        Config::new(configs, &options.overrides)
    }

    /// `FluffConfig.from_root`: the config of the working folder.
    pub fn from_root(loader: &mut Loader, options: &LoadOptions) -> Result<Config, ConfigError> {
        Config::from_path(loader, ".", options)
    }

    /// The whole config.
    pub fn table(&self) -> &Table {
        &self.table
    }

    /// The value or section at a key path, for example
    /// `["rules", "capitalisation.keywords", "capitalisation_policy"]`.
    pub fn get(&self, path: &[&str]) -> Option<&Value> {
        get(&self.table, path)
    }

    /// A value of the `core` section (`[sqlfluff]`).
    pub fn core(&self, key: &str) -> Option<&Value> {
        self.get(&["core", key])
    }

    /// A section, for example `["templater", "jinja"]`.
    pub fn section(&self, path: &[&str]) -> Option<&Table> {
        self.get(path)?.as_table()
    }

    /// The dialect name, if one is set.
    pub fn dialect(&self) -> Option<&str> {
        self.core("dialect")?.as_str()
    }

    /// The templater name. [`Config::new`] checks it.
    pub fn templater(&self) -> &str {
        self.core("templater")
            .and_then(Value::as_str)
            .expect("Config::new checks the templater")
    }

    /// The `[sqlfluff:indentation]` section as the parser gets it: the
    /// Python `bool` of each value (`ParseContext.from_config`), in key
    /// order.
    pub fn indentation(&self) -> Vec<(String, bool)> {
        self.section(&["indentation"])
            .map(|t| t.iter().map(|(k, v)| (k.clone(), v.is_truthy())).collect())
            .unwrap_or_default()
    }

    /// The section of a rule, by its config name (for example
    /// `capitalisation.keywords`).
    pub fn rule_section(&self, name: &str) -> Option<&Table> {
        self.section(&["rules", name])
    }

    /// The section of a templater (for example `jinja`).
    pub fn templater_section(&self, name: &str) -> Option<&Table> {
        self.section(&["templater", name])
    }

    fn check_templater(&self) -> Result<(), ConfigError> {
        match self.core("templater") {
            Some(Value::Str(name)) if TEMPLATERS.contains(&name.as_str()) => Ok(()),
            Some(Value::Str(name)) => Err(ConfigError::Invalid(format!(
                "Requested templater {} which is not currently available. Try one of {}",
                crate::value::py_repr(name),
                TEMPLATERS.join(", ")
            ))),
            Some(v) => Err(ConfigError::Invalid(format!(
                "Config value `templater` expected to be a string. Not: {v}"
            ))),
            None => Err(ConfigError::Invalid(
                "Requested templater '<no value set>' which is not currently available.".into(),
            )),
        }
    }

    /// `_verify_rust_config`: `use_rust_rules` on needs the Rust parser.
    fn verify_rust_config(&self) -> Result<(), ConfigError> {
        let parser_enabled = self
            .core("use_rust_parser")
            .is_some_and(rust_parser_enabled);
        let rules_on = self.core("use_rust_rules").is_some_and(|v| {
            matches!(v, Value::Str(s) if s == "True" || s == "true") || v.py_eq(&Value::Bool(true))
        });
        if rules_on && !parser_enabled {
            return Err(ConfigError::Invalid(
                "use_rust_rules is enabled but use_rust_parser is disabled. Rust-native rules \
                 require the Rust parser (they read its parse arena), so this combination does \
                 nothing. Set use_rust_parser to 'auto' or 'True', or disable use_rust_rules."
                    .into(),
            ));
        }
        Ok(())
    }
}

/// The values of `use_rust_parser` that run the Rust parser (the linter
/// test of sqlfluff: "auto", "Auto", "AUTO", True, "True", "true", 1).
pub fn rust_parser_enabled(value: &Value) -> bool {
    match value {
        Value::Str(s) => ["auto", "Auto", "AUTO", "True", "true"].contains(&s.as_str()),
        v => v.py_eq(&Value::Bool(true)),
    }
}

/// `split_comma_separated_string`: a text is split on "," with the space
/// around each part removed and no empty part; a list stays.
fn split_comma_separated(value: &Value, key: &str) -> Result<Value, ConfigError> {
    match value {
        Value::Str(s) => Ok(Value::List(
            s.split(',')
                .map(py_strip)
                .filter(|p| !p.is_empty())
                .map(Value::str)
                .collect(),
        )),
        Value::List(_) => Ok(value.clone()),
        other => Err(ConfigError::Invalid(format!(
            "the config value {key} must be a comma separated text or a list, not {other}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn overrides(pairs: &[(&str, Value)]) -> Table {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.clone()))
            .collect()
    }

    #[test]
    fn new_combines_defaults_configs_and_overrides() {
        let configs = crate::ini::load_ini_string(
            "[sqlfluff]\ndialect = mysql\nrules = LT01, CP01,\n[sqlfluff:indentation]\nindented_joins = True\n",
            "x",
        )
        .unwrap();
        let c = Config::new(configs, &overrides(&[("dialect", Value::str("ansi"))])).unwrap();
        assert_eq!(c.dialect(), Some("ansi"));
        assert_eq!(c.templater(), "jinja");
        assert_eq!(
            c.core("rule_allowlist"),
            Some(&Value::List(vec![Value::str("LT01"), Value::str("CP01")]))
        );
        assert_eq!(c.core("ignore"), Some(&Value::List(vec![])));
        assert_eq!(c.core("color"), Some(&Value::None));
        assert!(c
            .indentation()
            .contains(&("indented_joins".to_string(), true)));
        assert!(c.indentation().contains(&("indent_unit".to_string(), true)));
        assert_eq!(
            c.get(&["rules", "capitalisation.keywords", "capitalisation_policy"]),
            Some(&Value::str("consistent"))
        );
    }

    #[test]
    fn errors_of_fluffconfig() {
        let bad = |pairs: &[(&str, Value)]| Config::new(Table::new(), &overrides(pairs)).is_err();
        assert!(bad(&[("templater", Value::str("dbt"))]));
        assert!(bad(&[("templater", Value::Int(1))]));
        assert!(bad(&[("dialect", Value::Int(1))]));
        assert!(bad(&[("max_parse_depth", Value::Int(-1))]));
        assert!(bad(&[("ignore", Value::Int(3))]));
        assert!(bad(&[
            ("use_rust_rules", Value::Bool(true)),
            ("use_rust_parser", Value::Bool(false))
        ]));
        assert!(!bad(&[
            ("use_rust_rules", Value::str("true")),
            ("use_rust_parser", Value::str("AUTO"))
        ]));
    }
}
