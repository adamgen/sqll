// Parts of this file are a port of sqlfluff 4.4.0 code:
// src/sqlfluff/cli/commands.py (rules, dialects) and
// src/sqlfluff/cli/formatters.py (format_rules, _format_rule_description,
// format_dialects).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The commands `sqll rules` and `sqll dialects` (S3b C13): the output of
//! `sqlfluff rules` and `sqlfluff dialects` (src/sqlfluff/cli/commands.py
//! `rules` and `dialects`, src/sqlfluff/cli/formatters.py `format_rules`,
//! `_format_rule_description`, and `format_dialects`, sqlfluff 4.4.0; MIT,
//! see THIRD_PARTY.md).
//!
//! `sqll rules` shows the rules that the config selects. If the config
//! selects a rule that sqll does not have (also with the default `rules =
//! all`), it fails closed: "unsupported: rules ...", exit code 2.

use sqll_config::{Config, ConfigError, Env, LoadOptions, Loader, Table, Value};
use sqll_lint::{Registry, RULES};

use crate::args::{self, Opt};
use crate::color::{Color, Painter};
use crate::text::cli_table;
use crate::{Error, EXIT_OK};

/// The dialects of sqlfluff 4.4.0 (`dialect_readout`): the label, the
/// formatted name, and the dialect it inherits from.
pub const DIALECTS: [(&str, &str, &str); 28] = [
    ("ansi", "ANSI", "nothing"),
    ("athena", "AWS Athena", "ansi"),
    ("bigquery", "Google BigQuery", "ansi"),
    ("clickhouse", "ClickHouse", "ansi"),
    ("databricks", "Databricks", "sparksql"),
    ("db2", "IBM Db2", "ansi"),
    ("doris", "Apache Doris", "mysql"),
    ("duckdb", "DuckDB", "postgres"),
    ("exasol", "Exasol", "ansi"),
    ("flink", "Apache Flink SQL", "ansi"),
    ("greenplum", "Greenplum", "postgres"),
    ("hive", "Apache Hive", "ansi"),
    ("impala", "Apache Impala", "hive"),
    ("mariadb", "MariaDB", "mysql"),
    ("materialize", "Materialize", "postgres"),
    ("mysql", "MySQL", "ansi"),
    ("oracle", "Oracle", "ansi"),
    ("postgres", "PostgreSQL", "ansi"),
    ("redshift", "AWS Redshift", "postgres"),
    ("snowflake", "Snowflake", "ansi"),
    ("soql", "Salesforce Object Query Language (SOQL)", "ansi"),
    ("sparksql", "Apache Spark SQL", "ansi"),
    ("sqlite", "SQLite", "ansi"),
    ("starrocks", "StarRocks", "mysql"),
    ("teradata", "Teradata", "ansi"),
    ("trino", "Trino", "ansi"),
    ("tsql", "Microsoft T-SQL", "ansi"),
    ("vertica", "Vertica", "ansi"),
];

/// The common options of sqlfluff (`common_options`).
const OPTS: &[Opt] = &[
    args::flag(&["-v", "--verbose"], "verbose"),
    args::flag(&["-n", "--nocolor"], "nocolor"),
    args::flag(&["--color"], "color"),
    args::not_yet(&["--version"], args::Kind::Flag),
];

const RULES_USAGE: &str = "\
Usage: sqll rules [OPTIONS]

  Show the rules that the config selects (the dialect is ansi). A rule
  that sqll does not have gives \"unsupported\" and exit code 2.

Options:
  -v, --verbose        Verbosity. No effect on this command.
  -n, --nocolor        No color in the output.
  --color              Color in the output.
  -h, --help           Show this message and exit.
";

const DIALECTS_USAGE: &str = "\
Usage: sqll dialects [OPTIONS]

  Show the dialects of sqll.

Options:
  -v, --verbose        Verbosity. No effect on this command.
  -n, --nocolor        No color in the output.
  --color              Color in the output.
  -h, --help           Show this message and exit.
";

/// `--nocolor` and `--color` as sqlfluff reads them: the last one wins.
pub fn nocolor_option(parsed: &args::Parsed) -> Option<bool> {
    match parsed.last(&["nocolor", "color"]) {
        Some("nocolor") => Some(true),
        Some(_) => Some(false),
        None => None,
    }
}

/// An error of `get_config`: "Error loading config: ..." on stdout, or
/// "unsupported" on stderr.
pub fn config_error(e: ConfigError) -> Error {
    match e {
        ConfigError::Unsupported(_) => Error::new(e.to_string()),
        other => Error::stdout(format!("Error loading config: {other}")),
    }
}

/// The root config with the overrides of the common options.
fn root_config(parsed: &args::Parsed, dialect: Option<&str>) -> Result<Config, Error> {
    let mut overrides = Table::new();
    if let Some(d) = dialect {
        overrides.insert("dialect".to_string(), Value::str(d));
    }
    if let Some(n) = nocolor_option(parsed) {
        overrides.insert("nocolor".to_string(), Value::Bool(n));
    }
    let verbose = parsed.count("verbose");
    if verbose > 0 {
        overrides.insert("verbose".to_string(), Value::Int(verbose as i64));
    }
    let env = Env::from_process().map_err(config_error)?;
    let mut loader = Loader::new(&env);
    let options = LoadOptions {
        extra_config_path: None,
        ignore_local_config: false,
        overrides,
    };
    Config::from_root(&mut loader, &options).map_err(config_error)
}

/// The painter of the config (`nocolor` of the config and the options).
pub fn painter_of(config: &Config) -> Painter {
    Painter::new(match config.core("nocolor") {
        Some(Value::Bool(b)) => Some(*b),
        Some(v) if !matches!(v, Value::None) => Some(v.is_truthy()),
        _ => None,
    })
}

/// `output_line_length` of the config (default 80).
pub fn output_line_length(config: &Config) -> Result<usize, Error> {
    match config.core("output_line_length") {
        None => Ok(80),
        Some(Value::Int(i)) if *i > 25 => Ok(*i as usize),
        Some(v) => Err(crate::unsupported(
            &format!("setting core:output_line_length = {v}"),
            "sqll reads only an int above 25",
        )),
    }
}

/// The text of `sqlfluff rules` for the rules with these codes.
pub fn format_rules(painter: &Painter, codes: &[&str], width: usize) -> String {
    let mut fields = Vec::new();
    for code in codes {
        let r = RULES
            .iter()
            .find(|r| r.code == *code)
            .expect("a sqlfluff rule");
        let mut d = if r.name.is_empty() {
            r.description.to_string()
        } else {
            format!(
                "[{}] {}",
                painter.paint(r.name, Some(Color::Blue)),
                r.description
            )
        };
        if !r.groups.is_empty() {
            d.push_str(&format!(
                "\ngroups: {}",
                painter.paint(&r.groups.join(", "), Some(Color::Light))
            ));
        }
        if !r.aliases.is_empty() {
            d.push_str(&format!(
                " aliases: {}",
                painter.paint(&r.aliases.join(", "), Some(Color::Light))
            ));
        }
        fields.push((r.code.to_string(), d));
    }
    let mut out = String::from("==== sqlfluff - rules ====\n");
    out.push_str(&cli_table(painter, &fields, width, 10, Color::Blue, false));
    out
}

/// The text of `sqlfluff dialects`.
pub fn format_dialects(painter: &Painter) -> String {
    let fields: Vec<(String, String)> = DIALECTS
        .iter()
        .map(|(label, name, from)| {
            (
                label.to_string(),
                format!("{name} dialect [inherits from '{from}']"),
            )
        })
        .collect();
    let mut out = String::from("==== sqlfluff - dialects ====\n");
    out.push_str(&cli_table(painter, &fields, 60, 10, Color::Blue, true));
    out
}

/// The command `sqll rules`.
pub fn rules_command(args: &[String]) -> Result<u8, Error> {
    let parsed = args::read(args, OPTS, RULES_USAGE)?;
    if parsed.help {
        print!("{RULES_USAGE}");
        return Ok(EXIT_OK);
    }
    if let Some(path) = parsed.paths.first() {
        return Err(Error::new(format!(
            "Got unexpected extra argument ({path})"
        )));
    }
    let config = root_config(&parsed, Some("ansi"))?;
    let painter = painter_of(&config);
    let width = output_line_length(&config)?;
    // sqlfluff logs these with no log handler: the message on stderr.
    for w in Registry::selection_warnings(&config) {
        eprintln!("{w}");
    }
    let registry = Registry::new(sqll_rules::rules()).map_err(Error::new)?;
    // The sqlfluff `get_rulepack`. A selected rule that sqll does not have
    // fails closed (the default `rules = all` selects each sqlfluff rule).
    let pack = registry.select(&config).map_err(|e| match e {
        sqll_lint::LintError::Unsupported(_) => Error::new(e.to_string()),
        other => {
            Error::stdout(painter.paint(&format!("Error loading rules: {other}"), Some(Color::Red)))
        }
    })?;
    let codes: Vec<&str> = pack.rules.iter().map(|(r, _)| r.code()).collect();
    println!("{}", format_rules(&painter, &codes, width));
    Ok(EXIT_OK)
}

/// The command `sqll dialects`.
pub fn dialects_command(args: &[String]) -> Result<u8, Error> {
    let parsed = args::read(args, OPTS, DIALECTS_USAGE)?;
    if parsed.help {
        print!("{DIALECTS_USAGE}");
        return Ok(EXIT_OK);
    }
    if let Some(path) = parsed.paths.first() {
        return Err(Error::new(format!(
            "Got unexpected extra argument ({path})"
        )));
    }
    let config = root_config(&parsed, None)?;
    let painter = painter_of(&config);
    println!("{}", format_dialects(&painter));
    Ok(EXIT_OK)
}

#[cfg(test)]
mod tests {
    use std::str::FromStr;

    use super::*;

    #[test]
    fn each_dialect_of_the_table_is_a_dialect_of_sqll() {
        for (label, _, from) in DIALECTS {
            assert!(sqll_syntax::Dialect::from_str(label).is_ok(), "{label}");
            assert!(from == "nothing" || DIALECTS.iter().any(|d| d.0 == from));
        }
        let mut labels: Vec<&str> = DIALECTS.iter().map(|d| d.0).collect();
        labels.sort_unstable();
        assert_eq!(labels, DIALECTS.map(|d| d.0));
    }
}
