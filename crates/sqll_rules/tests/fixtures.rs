//! The CP01, CP03, and CP04 cases of the sqlfluff rule fixtures (S3b C12;
//! docs/interfaces/rules.md, "Proof"). New sqll code.
//!
//! The test reads the YAML of the submodule
//! (test/fixtures/rules/std_rule_cases/CP0{1,3,4}.yml) and runs each case
//! as the sqlfluff rule test helper does (sqlfluff.utils.testing.rules,
//! rules__test_helper): the config of the case with `rules = <code>` and
//! the dialect ansi if the case sets none; pass_str has no violation of the
//! rule; fail_str has one or more, and its fix gives fix_str (or no change
//! if the case has no fix_str); fix_str has no violation. Also, each list of
//! violations (code, start and end line and position, description, fixable)
//! and each fixed text must be those of the pinned sqlfluff
//! (results/S3b/C12-rules.json, scripts/s3b/rules_oracle.py).
//!
//! Classes of cases:
//! - default: no config, and no Jinja delimiter: only the raw templater
//!   and the default config.
//! - config: a config (the rule settings, the dialect), and no Jinja
//!   delimiter. A setting that sqll does not have is "unsupported".
//! - jinja: a text with a Jinja delimiter; not run (the Jinja templater is
//!   S11; templated areas are S6).

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::str::FromStr;

use serde_json::Value as Json;
use serde_yaml_ng::Value as Yaml;
use sqll_config::{Config, Table, Value};
use sqll_lint::{LintError, LintSettings, LintedFile, Linter, Registry, TemplaterParser};
use sqll_source::TemplaterConfig;
use sqll_syntax::{Dialect, ParseOptions};
use sqll_templater::{jinja_is_literal, RawTemplater};

const FIXTURES: [&str; 3] = [
    "test/fixtures/rules/std_rule_cases/CP01.yml",
    "test/fixtures/rules/std_rule_cases/CP03.yml",
    "test/fixtures/rules/std_rule_cases/CP04.yml",
];
const RECORD: &str = "results/S3b/C12-rules.json";

/// The expected result: (class, passed, failed, unsupported, not run).
/// status/S3b.md (C12) has these numbers.
const EXPECTED: [(&str, usize, usize, usize, usize); 3] = [
    ("default", 13, 0, 0, 0),
    ("config", 25, 0, 7, 0),
    ("jinja", 0, 0, 0, 6),
];

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

/// A config value of a YAML value (the types that PyYAML gives).
fn value(y: &Yaml) -> Value {
    match y {
        Yaml::Null => Value::None,
        Yaml::Bool(b) => Value::Bool(*b),
        Yaml::Number(n) => match n.as_i64() {
            Some(i) => Value::Int(i),
            None => Value::Float(n.as_f64().expect("a number")),
        },
        Yaml::String(s) => Value::str(s),
        Yaml::Sequence(items) => Value::List(items.iter().map(value).collect()),
        Yaml::Mapping(m) => Value::Table(table(m)),
        Yaml::Tagged(t) => value(&t.value),
    }
}

fn table(m: &serde_yaml_ng::Mapping) -> Table {
    m.iter()
        .map(|(k, v)| (k.as_str().expect("a text key").to_string(), value(v)))
        .collect()
}

struct Case {
    rule: String,
    name: String,
    configs: Option<Table>,
    pass: Option<String>,
    fail: Option<String>,
    fix: Option<String>,
    line_numbers: Option<Vec<usize>>,
}

fn text(case: &serde_yaml_ng::Mapping, key: &str) -> Option<String> {
    case.get(key).map(|v| v.as_str().expect("a text").to_string())
}

/// The cases of the fixtures, in order, with the global configs of a file
/// (load_test_cases).
fn cases() -> Vec<Case> {
    let mut out = Vec::new();
    for rel in FIXTURES {
        let path = root().join("third_party/sqlfluff").join(rel);
        let data = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{rel}: {e}"));
        let y: Yaml = serde_yaml_ng::from_str(&data).expect("YAML");
        let m = y.as_mapping().expect("a mapping");
        let rule = m.get("rule").and_then(Yaml::as_str).expect("rule").to_string();
        let global = m.get("configs").and_then(Yaml::as_mapping).map(table);
        for (k, v) in m {
            let name = k.as_str().expect("a case name");
            if name == "rule" || name == "configs" {
                continue;
            }
            let c = v.as_mapping().expect("a case");
            let known = [
                "desc",
                "pass_str",
                "fail_str",
                "fix_str",
                "configs",
                "line_numbers",
            ];
            for key in c.keys() {
                let key = key.as_str().unwrap();
                assert!(known.contains(&key), "{name}: the key {key} is new");
            }
            out.push(Case {
                rule: rule.clone(),
                name: name.to_string(),
                configs: c
                    .get("configs")
                    .and_then(Yaml::as_mapping)
                    .map(table)
                    .or_else(|| global.clone()),
                pass: text(c, "pass_str"),
                fail: text(c, "fail_str"),
                fix: text(c, "fix_str"),
                line_numbers: c.get("line_numbers").map(|l| {
                    l.as_sequence()
                        .expect("a list")
                        .iter()
                        .map(|n| n.as_u64().expect("a line") as usize)
                        .collect()
                }),
            });
        }
    }
    out
}

fn class(case: &Case) -> &'static str {
    let texts = [&case.pass, &case.fail, &case.fix];
    if texts.iter().any(|t| t.as_deref().is_some_and(|t| !jinja_is_literal(t))) {
        "jinja"
    } else if case.configs.is_none() {
        "default"
    } else {
        "config"
    }
}

/// The sqlfluff `_setup_config`: `rules = <code>`, and the dialect ansi if
/// the configs set none.
fn config(case: &Case) -> Result<Config, LintError> {
    let configs = case.configs.clone().unwrap_or_default();
    // The settings that the parse of this test does not read: only the
    // dialect and ignore_templated_areas of core, and the rule settings.
    for (section, v) in &configs {
        let ok = match (section.as_str(), v) {
            ("rules", _) => true,
            ("core", Value::Table(t)) => t
                .keys()
                .all(|k| k == "dialect" || k == "ignore_templated_areas"),
            _ => false,
        };
        if !ok {
            return Err(LintError::Unsupported(format!("the config section {section}")));
        }
    }
    let has_dialect = matches!(configs.get("core"), Some(Value::Table(t)) if t.contains_key("dialect"));
    let mut overrides = Table::new();
    overrides.insert("rules".into(), Value::str(&case.rule));
    if !has_dialect {
        overrides.insert("dialect".into(), Value::str("ansi"));
    }
    Ok(Config::new(configs, &overrides)?)
}

/// A violation as the record has it.
fn row(v: &sqll_lint::Violation) -> Json {
    serde_json::json!([
        v.code,
        v.start.line,
        v.start.pos,
        v.end.line,
        v.end.pos,
        v.description,
        v.fixable()
    ])
}

fn rows(linted: &LintedFile) -> Json {
    Json::Array(linted.violations.iter().map(row).collect())
}

fn fail<T>(m: String) -> Result<T, LintError> {
    Err(LintError::Invalid(m))
}

/// Run one case. `Err` is the first problem.
fn run(case: &Case, registry: &Registry, record: &Json) -> Result<(), LintError> {
    let config = config(case)?;
    let pack = registry.select(&config)?;
    let dialect_name = config.dialect().unwrap_or("ansi");
    let dialect = Dialect::from_str(dialect_name)
        .map_err(|_| LintError::Invalid(format!("unknown dialect {dialect_name}")))?;
    let linter = Linter {
        pack: &pack,
        settings: LintSettings::from_config(&config)?,
        dialect,
    };
    let mut parser = TemplaterParser {
        templater: &RawTemplater,
        config: TemplaterConfig::new(),
        fname: "<string>".into(),
        dialect,
        options: ParseOptions::default(),
    };
    let has_rule = |l: &LintedFile| l.violations.iter().any(|v| v.code == case.rule);
    let mut lint = |sql: &str, fix: bool, key: &str| -> Result<LintedFile, LintError> {
        let linted = linter.lint(sql, &mut parser, fix)?;
        if !linted.parse_errors.is_empty() {
            return fail(format!("{key}: parse errors {:?}", linted.parse_errors));
        }
        if rows(&linted) != record[key] {
            return fail(format!(
                "{key}: the violations are {}, not those of sqlfluff {}",
                rows(&linted),
                record[key]
            ));
        }
        Ok(linted)
    };
    if let Some(sql) = &case.pass {
        if has_rule(&lint(sql, false, "pass")?) {
            return fail("pass_str has a violation".into());
        }
    }
    if let Some(sql) = &case.fail {
        let linted = lint(sql, true, "fail")?;
        if !has_rule(&linted) {
            return fail("fail_str has no violation".into());
        }
        if let Some(lines) = &case.line_numbers {
            let got: Vec<usize> = linted.violations.iter().map(|v| v.start.line).collect();
            if &got != lines {
                return fail(format!("the lines are {got:?}, not {lines:?}"));
            }
        }
        if Some(linted.fixed.as_str()) != record["fixed"].as_str() {
            return fail(format!("the fixed text {:?} is not that of sqlfluff", linted.fixed));
        }
        let want = case.fix.as_deref().unwrap_or(sql);
        if linted.fixed != want {
            return fail(format!("the fixed text is {:?}, not {want:?}", linted.fixed));
        }
        if let Some(fixed) = &case.fix {
            if has_rule(&lint(fixed, true, "after_fix")?) {
                return fail("fix_str has a violation".into());
            }
        }
    }
    Ok(())
}

#[test]
fn the_rule_fixtures_pass() {
    let record: Json = serde_json::from_str(
        &std::fs::read_to_string(root().join(RECORD)).expect("read the record"),
    )
    .expect("JSON");
    let records = record["cases"].as_array().expect("cases");
    let cases = cases();
    assert_eq!(cases.len(), records.len(), "the cases of the record");
    let registry = Registry::new(sqll_rules::rules()).expect("the rules");
    // class -> [passed, failed, unsupported, not run]
    let mut counts: BTreeMap<&str, [usize; 4]> = BTreeMap::new();
    for (case, rec) in cases.iter().zip(records) {
        assert_eq!(
            (rec["rule"].as_str(), rec["name"].as_str()),
            (Some(case.rule.as_str()), Some(case.name.as_str())),
            "the order of the record"
        );
        let class = class(case);
        let c = counts.entry(class).or_default();
        if class == "jinja" {
            c[3] += 1;
            continue;
        }
        match run(case, &registry, rec) {
            Ok(()) => c[0] += 1,
            Err(LintError::Unsupported(m)) => {
                println!("unsupported: {} {}: {m}", case.rule, case.name);
                c[2] += 1;
            }
            Err(e) => {
                println!("FAIL: {} {}: {e}", case.rule, case.name);
                c[1] += 1;
            }
        }
    }
    let mut got = Vec::new();
    for (class, [passed, failed, unsupported, not_run]) in &counts {
        println!(
            "rule fixtures (CP01, CP03, CP04), {class}: {passed} passed, {failed} failed, \
             {unsupported} unsupported, {not_run} not run"
        );
        got.push((*class, *passed, *failed, *unsupported, *not_run));
    }
    got.sort_by_key(|g| EXPECTED.iter().position(|e| e.0 == g.0));
    assert_eq!(got, EXPECTED);
}
