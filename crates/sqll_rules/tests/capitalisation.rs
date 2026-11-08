//! Tests of the rules CP01, CP03, and CP04 (S3 T18; since S3b C12 on the
//! rule interface of sqll_lint). New sqll code: the base has no tests of
//! these rules in Rust.
//!
//! Each expected text is the output of the pinned sqlfluff 4.4.0 (the tool
//! venv) for the same SQL and policy:
//! `sqlfluff fix --rules <code> --dialect ansi`, with the policy in the
//! `[sqlfluff:rules:capitalisation.keywords]`, `.functions`, or `.literals`
//! section of the config file. The fix runs through the fix loop of
//! sqll_lint, with the raw templater and the parse interface.

use std::str::FromStr;

use sqll_config::{Config, Table, Value};
use sqll_lint::{LintError, LintSettings, Linter, Registry, TemplaterParser};
use sqll_source::TemplaterConfig;
use sqll_syntax::{Dialect, ParseOptions};
use sqll_templater::RawTemplater;

fn table(items: &[(&str, Value)]) -> Table {
    items
        .iter()
        .map(|(k, v)| (k.to_string(), v.clone()))
        .collect()
}

/// The SQL after the fix of the rule, with this policy and these ignore
/// words in the config section of the rule.
fn fix(code: &str, policy: &str, ignore: &[&str], sql: &str) -> String {
    try_fix(code, "ansi", policy, ignore, sql).expect("a lint")
}

fn try_fix(
    code: &str,
    dialect: &str,
    policy: &str,
    ignore: &[&str],
    sql: &str,
) -> Result<String, LintError> {
    let (name, key) = match code {
        "CP01" => ("capitalisation.keywords", "capitalisation_policy"),
        "CP03" => ("capitalisation.functions", "extended_capitalisation_policy"),
        "CP04" => ("capitalisation.literals", "capitalisation_policy"),
        _ => panic!("{code}"),
    };
    let mut section = table(&[(key, Value::str(policy))]);
    if !ignore.is_empty() {
        section.insert("ignore_words".into(), Value::str(&ignore.join(",")));
    }
    let configs = table(&[(
        "rules",
        Value::Table(table(&[(name, Value::Table(section))])),
    )]);
    let overrides = table(&[("rules", Value::str(code)), ("dialect", Value::str(dialect))]);
    let config = Config::new(configs, &overrides).expect("a valid config");
    let registry = Registry::new(sqll_rules::rules()).expect("the rules");
    let pack = registry.select(&config).expect("the rule");
    assert_eq!(pack.rules.len(), 1);
    let linter = Linter {
        pack: &pack,
        settings: LintSettings::from_config(&config).unwrap(),
        dialect: Dialect::from_str(dialect).unwrap(),
    };
    let mut parser = TemplaterParser {
        templater: &RawTemplater,
        config: TemplaterConfig::new(),
        fname: "<string>".into(),
        dialect: linter.dialect,
        options: ParseOptions::default(),
    };
    let linted = linter.lint(sql, &mut parser, true)?;
    assert!(linted.parse_errors.is_empty(), "{:?}", linted.parse_errors);
    assert!(linted.warnings.is_empty(), "{:?}", linted.warnings);
    for v in &linted.violations {
        assert_eq!(v.code, code);
        assert!(v.fixable(), "{v:?}");
        for e in &v.fixes {
            assert_ne!(&sql[e.range.clone()], e.text, "a fix must change the text");
        }
    }
    assert_eq!(linted.violations.is_empty(), linted.fixed == sql);
    Ok(linted.fixed)
}

#[test]
fn cp01_keywords() {
    let cases: [(&str, &[&str], &str, &str); 7] = [
        ("consistent", &[], "SELECT a from t\n", "SELECT a FROM t\n"),
        ("consistent", &[], "select a FROM t\n", "select a from t\n"),
        ("consistent", &[], "SELECT a FROM t\n", "SELECT a FROM t\n"),
        (
            "lower",
            &[],
            "SELECT a FROM t WHERE a = 1 AND b = 2\n",
            "select a from t where a = 1 and b = 2\n",
        ),
        ("capitalise", &[], "select a from t\n", "Select a From t\n"),
        ("upper", &["from"], "select a from t\n", "SELECT a from t\n"),
        // The data type keyword "int" is not a target (parent data_type).
        (
            "upper",
            &[],
            "select cast(a as int) from t\n",
            "SELECT cast(a AS int) FROM t\n",
        ),
    ];
    for (policy, ignore, sql, want) in cases {
        assert_eq!(fix("CP01", policy, ignore, sql), want, "{policy} {sql:?}");
    }
}

#[test]
fn cp03_functions() {
    let cases: [(&str, &str, &str); 3] = [
        (
            "consistent",
            "SELECT MAX(a), min(b) FROM t\n",
            "SELECT MAX(a), MIN(b) FROM t\n",
        ),
        (
            "lower",
            "SELECT MAX(a), COUNT(*) FROM t\n",
            "SELECT max(a), count(*) FROM t\n",
        ),
        ("pascal", "SELECT max(a) FROM t\n", "SELECT Max(a) FROM t\n"),
    ];
    for (policy, sql, want) in cases {
        assert_eq!(fix("CP03", policy, &[], sql), want, "{policy} {sql:?}");
    }
}

#[test]
fn cp04_literals() {
    let cases: [(&str, &str, &str); 2] = [
        (
            "consistent",
            "SELECT NULL, true FROM t\n",
            "SELECT NULL, TRUE FROM t\n",
        ),
        (
            "lower",
            "SELECT NULL, TRUE, False FROM t\n",
            "SELECT null, true, false FROM t\n",
        ),
    ];
    for (policy, sql, want) in cases {
        assert_eq!(fix("CP04", policy, &[], sql), want, "{policy} {sql:?}");
    }
}

/// A target with children changes the memory, as in sqlfluff (S3b C12).
/// The expected texts are the output of the pinned sqlfluff 4.4.0.
#[test]
fn a_target_with_children() {
    // The ansi ConcatSegment "||" (two pipe symbols) refutes "lower".
    assert_eq!(
        fix("CP01", "consistent", &["select"], "select a || b from t\n"),
        "select a || b FROM t\n"
    );
    // The sparksql DivBinaryOperatorSegment is a raw segment in sqlfluff; in
    // the tree of sqll it has one keyword child, which the rule fixes.
    assert_eq!(
        try_fix("CP01", "sparksql", "upper", &[], "SELECT 3 div 2\n").unwrap(),
        "SELECT 3 DIV 2\n"
    );
    // The oracle "MULTISET union" operator needs a fix: sqlfluff stops the
    // rule with an exception ("Unexpected exception"); sqll fails closed.
    let err = try_fix("CP01", "oracle", "consistent", &[], "SELECT a MULTISET union b FROM t\n");
    assert!(
        matches!(&err, Err(LintError::Unsupported(m)) if m.contains("binary_operator")),
        "{err:?}"
    );
}
