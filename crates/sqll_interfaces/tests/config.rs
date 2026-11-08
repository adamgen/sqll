//! The interface test of the config (docs/interfaces/config.md; S3b task
//! C11). It compares `sqll_config` with the answers of the pinned sqlfluff
//! in `results/S3b/C11-config.json` (`scripts/s3b/config_oracle.py`; the
//! CI job build checks the record): the defaults, the coercion of INI
//! values, the INI and TOML readers, and the config of each load scenario
//! (config files in folders, the user config folder, `--config`,
//! `--ignore-local-config`, and the overrides). The test of `sqll parse`
//! with each CLI scenario is `crates/sqll/tests/cli_config.rs`.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde_json::Value as Json;
use sqll_config::dict::iter_records;
use sqll_config::ini::load_ini_string;
use sqll_config::parse::{ParseSettings, TemplaterName};
use sqll_config::toml::load_toml_string;
use sqll_config::value::float_repr;
use sqll_config::{
    coerce_value, default_table, defaults, Config, ConfigError, Env, LoadOptions, Loader, Table,
    Value,
};

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn sqlfluff() -> PathBuf {
    repo().join("third_party/sqlfluff")
}

fn record() -> Json {
    let text = std::fs::read_to_string(repo().join("results/S3b/C11-config.json"))
        .expect("read results/S3b/C11-config.json");
    serde_json::from_str(&text).expect("the record is JSON")
}

/// The signatures of the interface. A change of one of them is a change of
/// the frozen interface: this function does not compile.
#[allow(dead_code)]
fn signatures(c: &Config, l: &mut Loader, o: &LoadOptions, s: ParseSettings) {
    let _: fn(Table, &Table) -> Result<Config, ConfigError> = Config::new;
    let _: Result<Config, ConfigError> = Config::from_path(l, "a.sql", o);
    let _: Result<Config, ConfigError> = Config::from_root(l, o);
    let _: Option<&Value> = c.get(&["core", "dialect"]);
    let _: Option<&Value> = c.core("dialect");
    let _: Option<&Table> = c.section(&["indentation"]);
    let _: (Option<&str>, &str) = (c.dialect(), c.templater());
    let _: Vec<(String, bool)> = c.indentation();
    let _: (Option<&Table>, Option<&Table>) = (c.rule_section("x"), c.templater_section("raw"));
    let _: fn(&Config, &Config) -> Result<ParseSettings, ConfigError> = ParseSettings::new;
    let _: fn(&Config) -> Result<ParseSettings, ConfigError> = ParseSettings::for_stdin;
    // S3b C13: the settings of the parse of a lint or a fix, and the ignore
    // file check of one folder.
    let _: fn(&Config, &Config, bool) -> Result<ParseSettings, ConfigError> =
        ParseSettings::for_lint;
    let _: Result<(), ConfigError> = sqll_config::parse::check_ignore_folder(l, ".");
    let _: (Option<String>, TemplaterName, u64, u64) =
        (s.dialect, s.templater, s.max_parse_depth, s.max_parse_nodes);
    let _: (Option<u64>, Option<u64>, Vec<(String, bool)>) = (
        s.max_parser_iterations,
        s.parser_warn_threshold,
        s.indentation,
    );
    let _: fn(&str) -> Result<Value, ConfigError> = coerce_value;
    let _: fn() -> Table = defaults;
    let _: fn() -> &'static Table = default_table;
    let _ = LoadOptions {
        extra_config_path: None,
        ignore_local_config: false,
        overrides: Table::new(),
    };
}

/// True if the sqll value is the recorded sqlfluff value (a value keeps
/// its Python type: {"int": text}, {"float": repr}, {"dict": {...}}).
fn same(want: &Json, got: &Value) -> bool {
    match (want, got) {
        (Json::Null, Value::None) => true,
        (Json::Bool(a), Value::Bool(b)) => a == b,
        (Json::String(a), Value::Str(b)) => a == b,
        (Json::Array(a), Value::List(b)) => {
            a.len() == b.len() && a.iter().zip(b).all(|(x, y)| same(x, y))
        }
        (Json::Object(o), v) => match (o.get("int"), o.get("float"), o.get("dict"), v) {
            (Some(Json::String(t)), _, _, Value::Int(i)) => *t == i.to_string(),
            (_, Some(Json::String(r)), _, Value::Float(f)) => *r == float_repr(*f),
            (_, _, Some(Json::Object(d)), Value::Table(t)) => {
                d.len() == t.len() && d.iter().all(|(k, w)| t.get(k).is_some_and(|g| same(w, g)))
            }
            _ => false,
        },
        _ => false,
    }
}

type Records = BTreeMap<Vec<String>, Json>;

fn recorded(list: &Json) -> Records {
    list.as_array()
        .expect("a list of records")
        .iter()
        .map(|r| {
            let path = r[0]
                .as_array()
                .unwrap()
                .iter()
                .map(|p| p.as_str().unwrap().to_string())
                .collect();
            (path, r[1].clone())
        })
        .collect()
}

/// The differences between the sqlfluff records and the sqll table.
fn compare(want: &Records, got: &[(Vec<String>, Value)], what: &str) -> Vec<String> {
    let mut problems = Vec::new();
    let got_map: BTreeMap<&Vec<String>, &Value> = got.iter().map(|(k, v)| (k, v)).collect();
    for (path, w) in want {
        match got_map.get(path) {
            Some(g) if same(w, g) => {}
            Some(g) => problems.push(format!(
                "{what}: {}: sqlfluff {w}, sqll {g:?}",
                path.join(":")
            )),
            None => problems.push(format!("{what}: {}: not in sqll", path.join(":"))),
        }
    }
    for (path, g) in got {
        if !want.contains_key(path) {
            problems.push(format!("{what}: {}: only in sqll ({g:?})", path.join(":")));
        }
    }
    problems
}

#[test]
fn the_defaults_and_the_base_config_are_those_of_sqlfluff() {
    let rec = record();
    let problems = compare(
        &recorded(&rec["defaults"]),
        &iter_records(&defaults()),
        "defaults",
    );
    assert!(problems.is_empty(), "{problems:#?}");
    let base = Config::new(Table::new(), &Table::new()).expect("the base config");
    let problems = compare(&recorded(&rec["base"]), &iter_records(base.table()), "base");
    assert!(problems.is_empty(), "{problems:#?}");
    assert_eq!(rec["defaults"].as_array().unwrap().len(), 208);
}

#[test]
fn coerce_value_is_that_of_sqlfluff() {
    let rec = record();
    for case in rec["coerce"].as_array().unwrap() {
        let text = case[0].as_str().unwrap();
        let got = coerce_value(text).expect("a value");
        assert!(
            same(&case[1], &got),
            "{text:?}: sqlfluff {}, sqll {got:?}",
            case[1]
        );
    }
}

fn text_of(spec: &str) -> String {
    match spec.strip_prefix('@') {
        Some(rel) => std::fs::read_to_string(sqlfluff().join(rel)).expect("a submodule file"),
        None => spec.to_string(),
    }
}

/// Compare a reader with the record. A case of `unsupported` must fail
/// closed.
fn check_reader(
    section: &str,
    unsupported: &[&str],
    read: impl Fn(&str) -> Result<Table, ConfigError>,
) {
    let rec = record();
    let mut problems = Vec::new();
    for case in rec[section].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let text = text_of(case["text"].as_str().unwrap());
        let got = read(&text);
        if unsupported.contains(&name) {
            if !matches!(got, Err(ConfigError::Unsupported(_))) {
                problems.push(format!("{section} {name}: sqll must fail closed: {got:?}"));
            }
            continue;
        }
        match (case.get("dict"), got) {
            (Some(want), Ok(t)) => {
                if !same(want, &Value::Table(t.clone())) {
                    problems.push(format!("{section} {name}: sqlfluff {want}, sqll {t:?}"));
                }
            }
            (None, Err(_)) => {}
            (Some(_), Err(e)) => problems.push(format!("{section} {name}: sqll error {e}")),
            (None, Ok(t)) => problems.push(format!(
                "{section} {name}: sqlfluff error {}, sqll {t:?}",
                case["error"]
            )),
        }
    }
    assert!(problems.is_empty(), "{problems:#?}");
}

#[test]
fn the_ini_reader_is_that_of_sqlfluff() {
    check_reader("ini", &[], |text| load_ini_string(text, "x"));
}

/// The TOML cases where sqll fails closed: a date (sqlfluff makes it a
/// str), an array of arrays or tables (sqlfluff makes each item a str),
/// and an int over 64 bits.
const TOML_UNSUPPORTED: &[&str] = &[
    "date",
    "array of tables in a list",
    "array of tables",
    "big int",
];

#[test]
fn the_toml_reader_is_that_of_sqlfluff() {
    // Python text mode reads "\r\n" as "\n" (Loader::load_file).
    check_reader("toml", TOML_UNSUPPORTED, |text| {
        load_toml_string(&text.replace("\r\n", "\n"), "pyproject.toml")
    });
}

/// A new empty folder (its real path) for one scenario.
fn scenario_root(name: &str, i: usize) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("sqll-c11-{}-{i}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("create a scenario folder");
    let _ = name;
    std::fs::canonicalize(&dir).expect("the real path")
}

/// Write the files of a scenario (scripts/s3b/config_oracle.py,
/// make_files).
pub fn make_files(root: &Path, files: &Json) {
    for (rel, content) in files.as_object().unwrap() {
        let path = root.join(rel);
        if content.get("dir").is_some() {
            std::fs::create_dir_all(&path).unwrap();
            continue;
        }
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        let data = match content {
            Json::String(s) => s.clone().into_bytes(),
            other => std::fs::read(sqlfluff().join(other["fixture"].as_str().unwrap())).unwrap(),
        };
        std::fs::write(&path, data).unwrap();
    }
}

fn rooted(v: &Value, root: &str) -> Value {
    match v {
        Value::Str(s) => Value::Str(s.replace(root, "<root>")),
        Value::List(l) => Value::List(l.iter().map(|x| rooted(x, root)).collect()),
        Value::Table(t) => Value::Table(
            t.iter()
                .map(|(k, x)| (k.clone(), rooted(x, root)))
                .collect(),
        ),
        other => other.clone(),
    }
}

#[test]
fn each_load_scenario_gives_the_config_of_sqlfluff() {
    let rec = record();
    let base = Config::new(Table::new(), &Table::new()).expect("the base config");
    let base_records = iter_records(base.table());
    let mut problems = Vec::new();
    let scenarios = rec["load"].as_array().unwrap();
    for (i, sc) in scenarios.iter().enumerate() {
        let name = sc["name"].as_str().unwrap();
        let root = scenario_root(name, i);
        let r = root.to_str().unwrap().to_string();
        make_files(&root, &sc["files"]);
        for key in ["cwd", "home"] {
            std::fs::create_dir_all(root.join(sc[key].as_str().unwrap())).unwrap();
        }
        let xdg = sc["xdg"].as_str().map(|x| {
            if x.starts_with('.') {
                x.to_string()
            } else {
                format!("{r}/{x}")
            }
        });
        let env = Env {
            cwd: format!("{r}/{}", sc["cwd"].as_str().unwrap()),
            home_var: Some(format!("{r}/{}", sc["home"].as_str().unwrap())),
            passwd_home: None,
            xdg_config_home: xdg,
        };
        let overrides: Table = sc["overrides"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| (k.clone(), Value::str(v.as_str().unwrap())))
            .collect();
        let options = LoadOptions {
            extra_config_path: sc["extra"].as_str().map(str::to_string),
            ignore_local_config: sc["ignore_local"].as_bool().unwrap(),
            overrides,
        };
        let mut loader = Loader::new(&env);
        let got = Config::from_path(&mut loader, sc["path"].as_str().unwrap(), &options);
        let expect = sc["sqll"].as_str();
        match (expect, sc.get("config"), got) {
            (Some("unsupported"), _, Err(ConfigError::Unsupported(_))) => {}
            (Some("unsupported"), _, other) => {
                problems.push(format!("{name}: sqll must fail closed, it gives {other:?}"))
            }
            (Some("exit2"), _, Err(ConfigError::Invalid(_) | ConfigError::Io(_))) => {}
            (None, Some(want), Ok(config)) => {
                let got: Vec<(Vec<String>, Value)> = iter_records(config.table())
                    .into_iter()
                    .map(|(k, v)| (k, rooted(&v, &r)))
                    .filter(|rec| !base_records.contains(rec))
                    .collect();
                problems.extend(compare(&recorded(want), &got, name));
            }
            (None, None, Err(ConfigError::Invalid(_) | ConfigError::Io(_))) => {}
            (_, _, got) => problems.push(format!(
                "{name}: sqlfluff {}, sqll {got:?}",
                sc.get("error").or(sc.get("config")).unwrap()
            )),
        }
        let _ = std::fs::remove_dir_all(&root);
    }
    assert!(problems.is_empty(), "{problems:#?}");
    eprintln!(
        "config: {} of {} load scenarios as sqlfluff",
        scenarios.len(),
        scenarios.len()
    );
}

#[test]
fn the_jinja_record_covers_the_dialect_fixtures() {
    // The proof of sqll_templater::jinja_is_literal: each dialect fixture
    // that is not empty and has no Jinja delimiter has the Jinja templated
    // file of the raw templater.
    let rec = record();
    let j = &rec["jinja_as_raw"];
    let files = j["files"].as_u64().unwrap();
    let with_tags = j["with_tags"].as_array().unwrap().len() as u64;
    let empty = j["empty"].as_array().unwrap().len() as u64;
    assert_eq!(files, 2306);
    assert_eq!(j["literal"].as_u64().unwrap(), files - with_tags - empty);
    assert_eq!(j["equal"], j["literal"]);
    let dir = sqlfluff().join("test/fixtures/dialects");
    let mut literal = 0;
    for entry in std::fs::read_dir(&dir).unwrap() {
        let folder = entry.unwrap().path();
        if !folder.is_dir() {
            continue;
        }
        for file in std::fs::read_dir(&folder).unwrap() {
            let path = file.unwrap().path();
            if path.extension().is_some_and(|e| e == "sql") {
                let text = std::fs::read_to_string(&path).unwrap();
                literal += u64::from(sqll_templater::jinja_is_literal(&text));
            }
        }
    }
    assert_eq!(literal, j["literal"].as_u64().unwrap());
}
