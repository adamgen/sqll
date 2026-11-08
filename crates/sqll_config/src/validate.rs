// This file is a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/config/validate.py (validate_config_dict and its
// checks) and src/sqlfluff/core/config/removed.py (REMOVED_CONFIGS,
// validate_config_dict_for_removed).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.
// Changes: a removed setting that sqlfluff moves to its new key (with a
// warning) fails closed in sqll.

//! The checks of a config dict that sqlfluff does when it loads a file.
//! Some of them change the dict (an empty `max_parse_depth` is 0).

use crate::value::{py_repr, Table, Value};
use crate::ConfigError;

/// A removed setting: its old key path, and its new key path if sqlfluff
/// moves its value there.
const REMOVED: &[(&[&str], Option<&[&str]>, &str)] = &[
    (
        &["rules", "L003", "hanging_indents"],
        None,
        "Hanging indents are no longer supported in SQLFluff from version 2.0.0 onwards. See https://docs.sqlfluff.com/en/stable/perma/hanging_indents.html",
    ),
    (&["rules", "max_line_length"], Some(&["core", "max_line_length"]), ""),
    (&["rules", "tab_space_size"], Some(&["indentation", "tab_space_size"]), ""),
    (&["rules", "L002", "tab_space_size"], Some(&["indentation", "tab_space_size"]), ""),
    (&["rules", "L003", "tab_space_size"], Some(&["indentation", "tab_space_size"]), ""),
    (&["rules", "L004", "tab_space_size"], Some(&["indentation", "tab_space_size"]), ""),
    (&["rules", "L016", "tab_space_size"], Some(&["indentation", "tab_space_size"]), ""),
    (&["rules", "indent_unit"], Some(&["indentation", "indent_unit"]), ""),
    (
        &["rules", "LT03", "operator_new_lines"],
        Some(&["layout", "type", "binary_operator", "line_position"]),
        "",
    ),
    (&["rules", "comma_style"], Some(&["layout", "type", "comma", "line_position"]), ""),
    (
        &["rules", "LT04", "comma_style"],
        Some(&["layout", "type", "comma", "line_position"]),
        "",
    ),
    (&["rules", "L003", "lint_templated_tokens"], None, "No longer used."),
    (
        &["core", "recurse"],
        None,
        "Removed as unused in production and unnecessary for debugging.",
    ),
    (
        &["rules", "references.quoting", "force_enable"],
        None,
        "No longer used. The dialects which used to block this rule, no longer do.",
    ),
    (
        &["indentation", "allow_implicit_indents"],
        Some(&["indentation", "implicit_indents"]),
        "",
    ),
    (
        &["rules", "L052", "semicolon_newline"],
        Some(&["rules", "convention.terminator", "multiline_newline"]),
        "",
    ),
    (
        &["rules", "convention.terminator", "semicolon_newline"],
        Some(&["rules", "convention.terminator", "multiline_newline"]),
        "",
    ),
];

const LAYOUT_KEYS: &[&str] = &[
    "spacing_before",
    "spacing_after",
    "spacing_within",
    "line_position",
    "align_within",
    "align_scope",
    "keyword_line_position",
    "keyword_line_position_exclusions",
    "alignment_coordinate_space",
];

const IMPLICIT_INDENTS: &[&str] = &["forbid", "allow", "require"];

fn invalid(reference: &str, what: String) -> ConfigError {
    ConfigError::Invalid(format!("Config file {} set {what}", py_repr(reference)))
}

/// The checks of `validate_config_dict`, in its order.
pub fn validate_config_dict(config: &mut Table, reference: &str) -> Result<(), ConfigError> {
    removed(config, reference)?;
    layout(config, reference)?;
    indentation(config, reference)?;
    parse_limit(config, "max_parse_depth", reference)?;
    parse_limit(config, "max_parse_nodes", reference)?;
    int_at_least(config, "render_variant_limit", 1, reference)?;
    int_at_least(config, "runaway_limit", 1, reference)?;
    Ok(())
}

fn removed(config: &Table, reference: &str) -> Result<(), ConfigError> {
    for (old, new, warning) in REMOVED {
        let mut table = config;
        let mut found = true;
        for (i, step) in old.iter().enumerate() {
            let last = i + 1 == old.len();
            match table.get(*step) {
                None => {
                    found = false;
                    break;
                }
                Some(Value::Table(t)) if !last => table = t,
                Some(_) if !last => {
                    // sqlfluff asserts that the parent is a section.
                    return Err(ConfigError::Invalid(format!(
                        "Config file {}: expected `{step}` to be a section not a value.",
                        py_repr(reference)
                    )));
                }
                Some(_) => {}
            }
        }
        if !found {
            continue;
        }
        let key = old.join(":");
        match new {
            None => {
                return Err(invalid(
                    reference,
                    format!(
                        "an outdated config value {key}.\n\n{warning}\n\nSee https://docs.sqlfluff.com/en/stable/perma/configuration.html for more details."
                    ),
                ))
            }
            Some(new) => {
                return Err(ConfigError::Unsupported(format!(
                    "setting {key} in {reference:?}: a deprecated sqlfluff setting; sqlfluff moves it to {}",
                    new.join(":")
                )))
            }
        }
    }
    Ok(())
}

fn layout(config: &Table, reference: &str) -> Result<(), ConfigError> {
    let Some(section) = config.get("layout").filter(|v| v.is_truthy()) else {
        return Ok(());
    };
    let err = |what: String| {
        ConfigError::Invalid(format!(
            "Config file {} set an invalid `layout` option. {what}See https://docs.sqlfluff.com/en/stable/perma/layout.html#configuring-layout for more details.",
            py_repr(reference)
        ))
    };
    let Value::Table(section) = section else {
        return Err(err(format!(
            "Found value {section} instead of a valid layout section. "
        )));
    };
    let types = section.get("type");
    let other_keys = section.keys().any(|k| k != "type");
    let Some(Value::Table(types)) = types.filter(|t| t.is_truthy()) else {
        return Err(err(
            "Only sections of the form `sqlfluff:layout:type:...` are valid. ".to_string(),
        ));
    };
    if other_keys {
        return Err(err(
            "Only sections of the form `sqlfluff:layout:type:...` are valid. ".to_string(),
        ));
    }
    for (name, value) in types {
        let Value::Table(t) = value else {
            return Err(err(format!(
                "Layout config for {name:?} is invalid. Expected a section. "
            )));
        };
        let bad: Vec<&String> = t
            .keys()
            .filter(|k| !LAYOUT_KEYS.contains(&k.as_str()))
            .collect();
        if !bad.is_empty() {
            return Err(err(format!(
                "Layout config for type {name:?} is invalid. Found the following invalid keys: {bad:?}. "
            )));
        }
        if let Some(k) = t
            .iter()
            .find(|(_, v)| matches!(v, Value::Table(_)))
            .map(|(k, _)| k)
        {
            return Err(err(format!(
                "Layout config for type {name:?} is invalid. Found the an unexpected section rather than value for {k}. "
            )));
        }
    }
    Ok(())
}

fn indentation(config: &Table, reference: &str) -> Result<(), ConfigError> {
    let Some(section) = config.get("indentation").filter(|v| v.is_truthy()) else {
        return Ok(());
    };
    let Value::Table(section) = section else {
        return Err(invalid(
            reference,
            "an `indentation` value that is not a section".into(),
        ));
    };
    match section.get("implicit_indents") {
        None | Some(Value::None) => Ok(()),
        Some(Value::Str(s)) if IMPLICIT_INDENTS.contains(&s.as_str()) => Ok(()),
        Some(v) => Err(invalid(
            reference,
            format!(
                "an invalid value for `implicit_indents`: {v}. Valid options are: forbid, allow, require. See https://docs.sqlfluff.com/en/stable/perma/configuration.html for more details."
            ),
        )),
    }
}

fn core_mut<'a>(
    config: &'a mut Table,
    reference: &str,
) -> Result<Option<&'a mut Table>, ConfigError> {
    match config.get_mut("core") {
        None => Ok(None),
        Some(v) if !v.is_truthy() => Ok(None),
        Some(Value::Table(t)) => Ok(Some(t)),
        Some(_) => Err(invalid(
            reference,
            "a `core` value that is not a section".into(),
        )),
    }
}

/// `max_parse_depth` and `max_parse_nodes`: an int from 0; `None` or an
/// empty value is 0 (no limit).
fn parse_limit(config: &mut Table, key: &str, reference: &str) -> Result<(), ConfigError> {
    let Some(core) = core_mut(config, reference)? else {
        return Ok(());
    };
    let Some(value) = core.get_mut(key) else {
        return Ok(());
    };
    match value {
        Value::None => *value = Value::Int(0),
        Value::Str(s) if s.is_empty() => *value = Value::Int(0),
        Value::Int(i) if *i >= 0 => {}
        Value::Int(i) => {
            return Err(invalid(
                reference,
                format!(
                    "an invalid value for `{key}`: {i}. This value must be 0 or a positive integer. Use 0 to disable the limit."
                ),
            ))
        }
        other => {
            return Err(invalid(
                reference,
                format!(
                    "an invalid value for `{key}`: {other}. This value must be an integer. Use 0 or an empty value to disable the limit."
                ),
            ))
        }
    }
    Ok(())
}

fn int_at_least(
    config: &mut Table,
    key: &str,
    minimum: i64,
    reference: &str,
) -> Result<(), ConfigError> {
    let Some(core) = core_mut(config, reference)? else {
        return Ok(());
    };
    match core.get(key) {
        None => Ok(()),
        Some(Value::Int(i)) if *i >= minimum => Ok(()),
        Some(Value::Int(i)) => Err(invalid(
            reference,
            format!(
                "an invalid value for `{key}`: {i}. This value must be an integer of at least {minimum}."
            ),
        )),
        Some(v) => Err(invalid(
            reference,
            format!("an invalid value for `{key}`: {v}. This value must be an integer."),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ini::load_ini_string;

    fn check(text: &str) -> Result<Table, ConfigError> {
        let mut t = load_ini_string(text, "x").unwrap();
        validate_config_dict(&mut t, "x").map(|_| t)
    }

    #[test]
    fn the_file_name_of_an_error_is_python_repr() {
        // sqlfluff validate.py: `{logging_reference!r}`.
        let mut t = load_ini_string("[sqlfluff]\nrunaway_limit = 0\n", "x").unwrap();
        let Err(ConfigError::Invalid(text)) = validate_config_dict(&mut t, "/a/.sqlfluff") else {
            panic!("no error");
        };
        assert_eq!(
            text,
            "Config file '/a/.sqlfluff' set an invalid value for `runaway_limit`: 0. \
             This value must be an integer of at least 1."
        );
    }

    #[test]
    fn checks_of_validate_config_dict() {
        // Cases of test/core/config/validate_test.py and fluffconfig_test.py.
        let t = check("[sqlfluff]\nmax_parse_depth =\nmax_parse_nodes = None\n").unwrap();
        assert_eq!(
            crate::dict::get(&t, &["core", "max_parse_depth"]),
            Some(&Value::Int(0))
        );
        assert_eq!(
            crate::dict::get(&t, &["core", "max_parse_nodes"]),
            Some(&Value::Int(0))
        );
        assert!(check("[sqlfluff]\nmax_parse_depth = -1\n").is_err());
        assert!(check("[sqlfluff]\nmax_parse_depth = True\n").is_err());
        assert!(check("[sqlfluff]\nmax_parse_nodes = abc\n").is_err());
        assert!(check("[sqlfluff]\nrunaway_limit = 0\n").is_err());
        assert!(check("[sqlfluff]\nrender_variant_limit = x\n").is_err());
        assert!(check("[sqlfluff]\nrecurse = 1\n").is_err());
        assert!(matches!(
            check("[sqlfluff:rules]\ntab_space_size = 2\n"),
            Err(ConfigError::Unsupported(_))
        ));
        assert!(check("[sqlfluff:indentation]\nimplicit_indents = sometimes\n").is_err());
        assert!(check("[sqlfluff:indentation]\nimplicit_indents = require\n").is_ok());
        assert!(check("[sqlfluff:layout:type:comma]\nnot_a_key = x\n").is_err());
        assert!(check("[sqlfluff:layout:other]\nx = 1\n").is_err());
        assert!(check("[sqlfluff:layout:type:comma]\nline_position = leading\n").is_ok());
    }
}
