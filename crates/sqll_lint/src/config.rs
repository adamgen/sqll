// Parts of this file are a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/rules/base.py (RuleSet._validate_config_options and
// the rule keyword arguments of RuleSet.get_rulepack) and
// src/sqlfluff/core/helpers/string.py (split_comma_separated_string).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The config of a rule and of the linter.

use sqll_config::{Config, Table, Value};

use crate::LintError;

/// A value of a validation list (sqlfluff `config_info`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Valid {
    Bool(bool),
    Str(&'static str),
}

/// The valid values of a rule config keyword.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Validation {
    /// One of the values (Python `in` a list: `1 == True`).
    Values(&'static [Valid]),
    /// Python `in range(start, stop)`.
    Range(i64, i64),
}

impl Validation {
    /// Python `value in validation`.
    pub fn accepts(&self, value: &Value) -> bool {
        match self {
            Validation::Values(values) => values.iter().any(|v| {
                let v = match v {
                    Valid::Bool(b) => Value::Bool(*b),
                    Valid::Str(s) => Value::str(s),
                };
                v.py_eq(value)
            }),
            Validation::Range(start, stop) => {
                let n = match value {
                    Value::Bool(b) => i64::from(*b) as f64,
                    Value::Int(i) => *i as f64,
                    Value::Float(f) if f.fract() == 0.0 => *f,
                    _ => return false,
                };
                (*start as f64) <= n && n < (*stop as f64)
            }
        }
    }

    /// The Python text of the list, for the message of sqlfluff.
    fn py_repr(&self) -> String {
        match self {
            Validation::Values(values) => {
                let items: Vec<String> = values
                    .iter()
                    .map(|v| match v {
                        Valid::Bool(true) => "True".to_string(),
                        Valid::Bool(false) => "False".to_string(),
                        Valid::Str(s) => format!("'{s}'"),
                    })
                    .collect();
                format!("[{}]", items.join(", "))
            }
            Validation::Range(start, stop) => format!("range({start}, {stop})"),
        }
    }
}

/// The validation of a rule config keyword, if it has one.
pub fn validation(key: &str) -> Option<Validation> {
    crate::sqlfluff::CONFIG_VALIDATION
        .binary_search_by(|(k, _)| (*k).cmp(key))
        .ok()
        .map(|i| crate::sqlfluff::CONFIG_VALIDATION[i].1)
}

/// The sqlfluff `_validate_config_options`: each validated keyword of the
/// table (the `rules` section, or the section of one rule) has a valid
/// value, or `None`.
pub fn validate_options(section: &Table) -> Result<(), LintError> {
    for (key, valid) in crate::sqlfluff::CONFIG_VALIDATION {
        let Some(value) = section.get(*key) else {
            continue;
        };
        if matches!(value, Value::None) || valid.accepts(value) {
            continue;
        }
        let shown = value.py_str().unwrap_or_else(|| value.to_string());
        return Err(LintError::Invalid(format!(
            "Invalid option '{shown}' for {key} configuration. Must be one of {}",
            valid.py_repr()
        )));
    }
    Ok(())
}

/// The sqlfluff `split_comma_separated_string` of a text: the parts between
/// the commas, with no white space at the ends, and no empty part.
pub fn split_comma_separated(text: &str) -> Vec<String> {
    text.split(',')
        .map(sqll_config::value::py_strip)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .collect()
}

/// The config of one rule: the keyword arguments that sqlfluff gives the
/// rule (the values of the `rules` section that are not a section, then the
/// section of the rule), and the `core` section.
#[derive(Clone, Debug, PartialEq)]
pub struct RuleConfig {
    values: Table,
    core: Table,
}

impl RuleConfig {
    /// The config of the rule with this name.
    pub fn new(config: &Config, rule_name: &str) -> RuleConfig {
        let mut values = Table::new();
        if let Some(rules) = config.section(&["rules"]) {
            for (k, v) in rules {
                if !matches!(v, Value::Table(_)) {
                    values.insert(k.clone(), v.clone());
                }
            }
        }
        if let Some(section) = config.rule_section(rule_name) {
            for (k, v) in section {
                values.insert(k.clone(), v.clone());
            }
        }
        RuleConfig {
            values,
            core: config.section(&["core"]).cloned().unwrap_or_default(),
        }
    }

    /// A config of the values only, for tests.
    pub fn from_values(values: Table, core: Table) -> RuleConfig {
        RuleConfig { values, core }
    }

    /// The value of a keyword of the rule.
    pub fn get(&self, key: &str) -> Option<&Value> {
        self.values.get(key)
    }

    /// A value of the `core` section, for example `ignore_templated_areas`.
    pub fn core(&self, key: &str) -> Option<&Value> {
        self.core.get(key)
    }

    /// The Python `str()` of a scalar value of the rule, or an error for a
    /// list or a table (fail closed).
    pub fn get_str(&self, key: &str) -> Result<Option<String>, LintError> {
        match self.get(key) {
            None => Ok(None),
            Some(v) => v.py_str().map(Some).ok_or_else(|| {
                LintError::Unsupported(format!("setting {key} = {v}: a list or a section"))
            }),
        }
    }
}

/// The settings of the linter and of the fix loop.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LintSettings {
    /// `runaway_limit`: the most loops of the main phase of the fix loop.
    pub runaway_limit: i64,
    /// `ignore_templated_areas`: remove the violations in templated
    /// sections at the end.
    pub ignore_templated_areas: bool,
    /// The sqlfluff `noqa` comments are read (`disable_noqa` is false or
    /// `disable_noqa_except` is set).
    pub reads_noqa: bool,
}

impl Default for LintSettings {
    /// The sqlfluff defaults.
    fn default() -> Self {
        LintSettings {
            runaway_limit: 10,
            ignore_templated_areas: true,
            reads_noqa: true,
        }
    }
}

impl LintSettings {
    /// The settings of a config. `fix_even_unparsable` true fails closed.
    pub fn from_config(config: &Config) -> Result<LintSettings, LintError> {
        let unsupported = |key: &str, v: &Value, why: &str| {
            LintError::Unsupported(format!("setting {key} = {v}: {why}"))
        };
        let runaway_limit = match config.core("runaway_limit") {
            None => 10,
            Some(Value::Int(i)) => *i,
            Some(Value::Bool(b)) => i64::from(*b),
            Some(v) => return Err(unsupported("runaway_limit", v, "not an int")),
        };
        let ignore_templated_areas = config
            .core("ignore_templated_areas")
            .is_none_or(Value::is_truthy);
        if let Some(v) = config.core("fix_even_unparsable") {
            if v.is_truthy() {
                return Err(unsupported(
                    "fix_even_unparsable",
                    v,
                    "sqll does not fix a file with unparsable sections",
                ));
            }
        }
        let disable_noqa = config.core("disable_noqa").is_some_and(Value::is_truthy);
        let except = config
            .core("disable_noqa_except")
            .is_some_and(Value::is_truthy);
        Ok(LintSettings {
            runaway_limit,
            ignore_templated_areas,
            reads_noqa: !disable_noqa || except,
        })
    }
}
