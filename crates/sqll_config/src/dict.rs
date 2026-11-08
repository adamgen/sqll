// This file is a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/helpers/dict.py (nested_combine,
// records_to_nested_dict, iter_records_from_nested_dict).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The nested dict helpers of the sqlfluff config.

use crate::value::{Table, Value};
use crate::ConfigError;

/// A setting: its key path and its value.
pub type Record = (Vec<String>, Value);

/// Combine the tables in order: a later value replaces an earlier one, and
/// two sections of the same key are combined. A section in an earlier
/// table and a value in a later one is an error (sqlfluff raises
/// ValueError).
pub fn nested_combine(tables: &[&Table]) -> Result<Table, ConfigError> {
    let mut out = Table::new();
    for table in tables {
        combine_into(&mut out, table)?;
    }
    Ok(out)
}

fn combine_into(out: &mut Table, table: &Table) -> Result<(), ConfigError> {
    for (key, value) in table {
        match (out.get_mut(key), value) {
            (Some(Value::Table(have)), Value::Table(add)) => combine_into(have, add)?,
            (Some(Value::Table(_)), other) => {
                return Err(ConfigError::Invalid(format!(
                    "Key {} is a dict in one config but not another! PANIC: {other}",
                    crate::value::py_repr(key)
                )))
            }
            _ => {
                out.insert(key.clone(), value.clone());
            }
        }
    }
    Ok(())
}

/// Make a nested table from records, in order. A record whose path goes
/// through a value is an error (sqlfluff fails an assert); a record whose
/// key is a section replaces the section.
pub fn records_to_nested_dict(
    records: impl IntoIterator<Item = Record>,
) -> Result<Table, ConfigError> {
    let mut out = Table::new();
    for (path, value) in records {
        let (last, parents) = path.split_last().expect("a record has a key");
        let mut table = &mut out;
        for step in parents {
            let entry = table
                .entry(step.clone())
                .or_insert_with(|| Value::Table(Table::new()));
            table = match entry {
                Value::Table(t) => t,
                _ => {
                    return Err(ConfigError::Invalid(format!(
                        "the config key {step:?} has a value and a section ({})",
                        path.join(":")
                    )))
                }
            };
        }
        table.insert(last.clone(), value);
    }
    Ok(out)
}

/// Each value of a nested table with its key path, in key order. A nested
/// table is a section; its values give records.
pub fn iter_records(table: &Table) -> Vec<Record> {
    let mut out = Vec::new();
    walk(table, &mut Vec::new(), &mut out);
    out
}

fn walk(table: &Table, path: &mut Vec<String>, out: &mut Vec<Record>) {
    for (key, value) in table {
        path.push(key.clone());
        match value {
            Value::Table(t) => walk(t, path, out),
            v => out.push((path.clone(), v.clone())),
        }
        path.pop();
    }
}

/// The value or section at a key path.
pub fn get<'a>(table: &'a Table, path: &[&str]) -> Option<&'a Value> {
    let (last, parents) = path.split_last()?;
    let mut t = table;
    for step in parents {
        t = t.get(*step)?.as_table()?;
    }
    t.get(*last)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn t(pairs: &[(&str, Value)]) -> Table {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.clone()))
            .collect()
    }

    #[test]
    fn nested_combine_is_that_of_sqlfluff() {
        // The doctests of nested_combine.
        let a = t(&[("a", Value::Table(t(&[("b", Value::str("c"))])))]);
        let b = t(&[("a", Value::Table(t(&[("d", Value::str("e"))])))]);
        let c = t(&[("a", Value::Table(t(&[("b", Value::str("e"))])))]);
        let ab = nested_combine(&[&a, &b]).unwrap();
        assert_eq!(
            ab,
            t(&[(
                "a",
                Value::Table(t(&[("b", Value::str("c")), ("d", Value::str("e"))]))
            )])
        );
        assert_eq!(nested_combine(&[&a, &c]).unwrap(), c);
        // A value after a section is an error; a section after a value
        // replaces it.
        let v = t(&[("a", Value::Int(1))]);
        assert!(nested_combine(&[&a, &v]).is_err());
        assert_eq!(nested_combine(&[&v, &a]).unwrap(), a);
    }

    #[test]
    fn records_to_nested_dict_is_that_of_sqlfluff() {
        let r = |p: &[&str], v: Value| (p.iter().map(|s| s.to_string()).collect(), v);
        let out = records_to_nested_dict([
            r(&["foo", "bar", "baz"], Value::str("a")),
            r(&["foo", "bar", "biz"], Value::str("b")),
        ])
        .unwrap();
        assert_eq!(
            iter_records(&out),
            vec![
                r(&["foo", "bar", "baz"], Value::str("a")),
                r(&["foo", "bar", "biz"], Value::str("b")),
            ]
        );
        assert!(records_to_nested_dict([
            r(&["x", "y"], Value::Int(1)),
            r(&["x", "y", "z"], Value::Int(2)),
        ])
        .is_err());
        let replaced = records_to_nested_dict([
            r(&["x", "y", "z"], Value::Int(2)),
            r(&["x", "y"], Value::Int(1)),
        ])
        .unwrap();
        assert_eq!(get(&replaced, &["x", "y"]), Some(&Value::Int(1)));
    }
}
