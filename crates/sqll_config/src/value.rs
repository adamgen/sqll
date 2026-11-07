// Parts of this file are a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/config/ini.py (coerce_value).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.
//
// The number rules of `py_int`, `py_float`, and `float_repr` give the
// results of Python 3.13 int(), float(), and repr(); no CPython code is
// copied.

//! The values of a config: the Python types that sqlfluff gives a config
//! value, and the sqlfluff coercion of an INI value ([`coerce_value`]).

use std::collections::BTreeMap;
use std::fmt;

use crate::ConfigError;

/// A section of a config: the keys and their values. A [`Value::Table`]
/// in a section is a nested section (a `dict` in sqlfluff).
pub type Table = BTreeMap<String, Value>;

/// A config value, with the Python type that sqlfluff gives it.
#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    None,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    /// A TOML array.
    List(Vec<Value>),
    /// A nested section, or a TOML table in a templater context.
    Table(Table),
}

impl Value {
    pub fn str(text: &str) -> Value {
        Value::Str(text.to_string())
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::Str(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_table(&self) -> Option<&Table> {
        match self {
            Value::Table(t) => Some(t),
            _ => None,
        }
    }

    /// The Python type name, for messages.
    pub fn type_name(&self) -> &'static str {
        match self {
            Value::None => "NoneType",
            Value::Bool(_) => "bool",
            Value::Int(_) => "int",
            Value::Float(_) => "float",
            Value::Str(_) => "str",
            Value::List(_) => "list",
            Value::Table(_) => "dict",
        }
    }

    /// Python `bool(value)`.
    pub fn is_truthy(&self) -> bool {
        match self {
            Value::None => false,
            Value::Bool(b) => *b,
            Value::Int(i) => *i != 0,
            Value::Float(f) => *f != 0.0,
            Value::Str(s) => !s.is_empty(),
            Value::List(l) => !l.is_empty(),
            Value::Table(t) => !t.is_empty(),
        }
    }

    /// Python `==`: a bool, an int, and a float are equal if their numbers
    /// are equal (`True == 1 == 1.0`).
    pub fn py_eq(&self, other: &Value) -> bool {
        match (self.number(), other.number()) {
            (Some(a), Some(b)) => return a == b,
            (Some(_), None) | (None, Some(_)) => return false,
            (None, None) => {}
        }
        match (self, other) {
            (Value::None, Value::None) => true,
            (Value::Str(a), Value::Str(b)) => a == b,
            (Value::List(a), Value::List(b)) => {
                a.len() == b.len() && a.iter().zip(b).all(|(x, y)| x.py_eq(y))
            }
            (Value::Table(a), Value::Table(b)) => {
                a.len() == b.len() && a.iter().all(|(k, v)| b.get(k).is_some_and(|w| v.py_eq(w)))
            }
            _ => false,
        }
    }

    fn number(&self) -> Option<Number> {
        match self {
            Value::Bool(b) => Some(Number::Int(i64::from(*b))),
            Value::Int(i) => Some(Number::Int(*i)),
            Value::Float(f) => Some(Number::Float(*f)),
            _ => None,
        }
    }

    /// Python `str(value)` of a scalar; `None` for a list or a table.
    pub fn py_str(&self) -> Option<String> {
        Some(match self {
            Value::None => "None".to_string(),
            Value::Bool(true) => "True".to_string(),
            Value::Bool(false) => "False".to_string(),
            Value::Int(i) => i.to_string(),
            Value::Float(f) => float_repr(*f),
            Value::Str(s) => s.clone(),
            Value::List(_) | Value::Table(_) => return None,
        })
    }
}

#[derive(Clone, Copy)]
enum Number {
    Int(i64),
    Float(f64),
}

impl PartialEq for Number {
    fn eq(&self, other: &Number) -> bool {
        match (*self, *other) {
            (Number::Int(a), Number::Int(b)) => a == b,
            (Number::Float(a), Number::Float(b)) => a == b,
            (Number::Int(a), Number::Float(b)) | (Number::Float(b), Number::Int(a)) => {
                // Python compares an int and a float exactly.
                b.fract() == 0.0 && b.abs() < 9.3e18 && (b as i64) == a
            }
        }
    }
}

/// A short form of a value for messages: a string in quotes.
impl fmt::Display for Value {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Value::Str(s) => write!(f, "{s:?}"),
            Value::List(items) => {
                f.write_str("[")?;
                for (i, item) in items.iter().enumerate() {
                    if i > 0 {
                        f.write_str(", ")?;
                    }
                    write!(f, "{item}")?;
                }
                f.write_str("]")
            }
            Value::Table(_) => f.write_str("{...}"),
            other => f.write_str(&other.py_str().unwrap_or_default()),
        }
    }
}

/// Python `str.isspace()` for one character: the Unicode white space, and
/// also the separators U+001C to U+001F.
pub fn py_isspace(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// Python `str.strip()`.
pub fn py_strip(s: &str) -> &str {
    s.trim_matches(py_isspace)
}

/// Python `str.rstrip()`.
pub fn py_rstrip(s: &str) -> &str {
    s.trim_end_matches(py_isspace)
}

/// The sqlfluff coercion of an INI value (`coerce_value` of
/// `src/sqlfluff/core/config/ini.py`): an int, else a float, else `True`,
/// `False`, or `None` (in any case, with no space around it), else the
/// text.
///
/// Fails closed for a number with a non-ASCII digit (Python reads it, sqll
/// does not) and for an int that does not fit in an `i64`.
pub fn coerce_value(text: &str) -> Result<Value, ConfigError> {
    let s = py_strip(text);
    if s.chars().any(|c| !c.is_ascii() && c.is_numeric()) {
        return Err(ConfigError::Unsupported(format!(
            "the config value {text:?}: sqll does not read a number with a non-ASCII digit"
        )));
    }
    if let Some(i) = py_int(s)? {
        return Ok(Value::Int(i));
    }
    if let Some(f) = py_float(s) {
        return Ok(Value::Float(f));
    }
    Ok(match s.to_lowercase().as_str() {
        "true" => Value::Bool(true),
        "false" => Value::Bool(false),
        "none" => Value::None,
        _ => Value::Str(text.to_string()),
    })
}

/// The length of a run of ASCII digits with single "_" between digits (a
/// Python digit part), or 0.
fn digit_part(b: &[u8]) -> usize {
    let mut i = 0;
    while i < b.len() {
        if b[i].is_ascii_digit() {
            i += 1;
        } else if b[i] == b'_' && i > 0 && b[i - 1].is_ascii_digit() {
            if b.get(i + 1).is_some_and(u8::is_ascii_digit) {
                i += 1;
            } else {
                break;
            }
        } else {
            break;
        }
    }
    i
}

/// Python `int(s)` (base 10) of a stripped ASCII text: `None` if Python
/// gives ValueError.
fn py_int(s: &str) -> Result<Option<i64>, ConfigError> {
    let b = s.as_bytes();
    let start = usize::from(matches!(b.first(), Some(b'+' | b'-')));
    let n = digit_part(&b[start..]);
    if n == 0 || start + n != b.len() {
        return Ok(None);
    }
    let digits: String = s.chars().filter(|c| *c != '_').collect();
    digits.parse::<i64>().map(Some).map_err(|_| {
        ConfigError::Unsupported(format!(
            "the config value {s:?}: sqll reads only an int from -2**63 to 2**63-1"
        ))
    })
}

/// Python `float(s)` of a stripped ASCII text: `None` if Python gives
/// ValueError.
fn py_float(s: &str) -> Option<f64> {
    let b = s.as_bytes();
    let (negative, body) = match b.first() {
        Some(b'-') => (true, &s[1..]),
        Some(b'+') => (false, &s[1..]),
        _ => (false, s),
    };
    let special = match body.to_ascii_lowercase().as_str() {
        "inf" | "infinity" => Some(f64::INFINITY),
        "nan" => Some(f64::NAN),
        _ => None,
    };
    if let Some(v) = special {
        return Some(if negative { -v } else { v });
    }
    let b = body.as_bytes();
    let mut i = digit_part(b);
    let whole = i;
    let mut frac = 0;
    if b.get(i) == Some(&b'.') {
        i += 1;
        frac = digit_part(&b[i..]);
        i += frac;
    }
    if whole == 0 && frac == 0 {
        return None;
    }
    if matches!(b.get(i), Some(b'e' | b'E')) {
        i += 1;
        if matches!(b.get(i), Some(b'+' | b'-')) {
            i += 1;
        }
        let exp = digit_part(&b[i..]);
        if exp == 0 {
            return None;
        }
        i += exp;
    }
    if i != b.len() {
        return None;
    }
    let text: String = s.chars().filter(|c| *c != '_').collect();
    text.parse::<f64>().ok()
}

/// Python `repr(f)` of a float: the shortest digits that give the value
/// again, in fixed notation if the decimal point is from 4 places before
/// the first digit to 16 places after it, else in exponent notation.
pub fn float_repr(f: f64) -> String {
    if f.is_nan() {
        return "nan".to_string();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf" } else { "-inf" }.to_string();
    }
    let sign = if f.is_sign_negative() { "-" } else { "" };
    if f == 0.0 {
        return format!("{sign}0.0");
    }
    let e = format!("{:e}", f.abs());
    let (mantissa, exp) = e.split_once('e').expect("LowerExp has an exponent");
    let exp: i32 = exp.parse().expect("LowerExp exponent");
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let n = digits.len() as i32;
    let decpt = exp + 1;
    let body = if decpt <= -4 || decpt > 16 {
        let (first, rest) = digits.split_at(1);
        let rest = if rest.is_empty() {
            String::new()
        } else {
            format!(".{rest}")
        };
        let esign = if exp < 0 { '-' } else { '+' };
        format!("{first}{rest}e{esign}{:02}", exp.abs())
    } else if decpt <= 0 {
        format!("0.{}{digits}", "0".repeat((-decpt) as usize))
    } else if decpt >= n {
        format!("{digits}{}.0", "0".repeat((decpt - n) as usize))
    } else {
        let (a, b) = digits.split_at(decpt as usize);
        format!("{a}.{b}")
    };
    format!("{sign}{body}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn coerce_value_gives_the_python_types() {
        // The values of sqlfluff 4.4.0 coerce_value (Python 3.13).
        let cases: &[(&str, Value)] = &[
            ("1", Value::Int(1)),
            ("-12", Value::Int(-12)),
            ("+7", Value::Int(7)),
            ("1_000", Value::Int(1000)),
            ("007", Value::Int(7)),
            (" 5 ", Value::Int(5)),
            ("1__0", Value::str("1__0")),
            ("_1", Value::str("_1")),
            ("1_", Value::str("1_")),
            ("0x10", Value::str("0x10")),
            ("1.5", Value::Float(1.5)),
            ("7.698", Value::Float(7.698)),
            (".5", Value::Float(0.5)),
            ("5.", Value::Float(5.0)),
            ("1e3", Value::Float(1000.0)),
            ("1E-2", Value::Float(0.01)),
            ("1_0.5", Value::Float(10.5)),
            ("inf", Value::Float(f64::INFINITY)),
            ("-Infinity", Value::Float(f64::NEG_INFINITY)),
            ("e3", Value::str("e3")),
            (".", Value::str(".")),
            ("1e", Value::str("1e")),
            ("True", Value::Bool(true)),
            ("FALSE", Value::Bool(false)),
            ("none", Value::None),
            ("None ", Value::None),
            ("jinja", Value::str("jinja")),
            ("", Value::str("")),
            (".sql,.sql.j2", Value::str(".sql,.sql.j2")),
        ];
        for (text, want) in cases {
            assert_eq!(coerce_value(text).unwrap(), *want, "{text:?}");
        }
        assert!(matches!(coerce_value("nan").unwrap(), Value::Float(f) if f.is_nan()));
        assert!(coerce_value("\u{0663}").is_err());
        assert!(coerce_value("99999999999999999999").is_err());
    }

    #[test]
    fn float_repr_is_that_of_python() {
        let cases = [
            (7.698, "7.698"),
            (1.0, "1.0"),
            (100.0, "100.0"),
            (0.1, "0.1"),
            (1e16, "1e+16"),
            (1e15, "1000000000000000.0"),
            (0.0001, "0.0001"),
            (0.00001, "1e-05"),
            (1.5e-7, "1.5e-07"),
            (-2.5, "-2.5"),
            (-0.0, "-0.0"),
            (123456789.125, "123456789.125"),
            (1.7976931348623157e308, "1.7976931348623157e+308"),
        ];
        for (f, want) in cases {
            assert_eq!(float_repr(f), want, "{f}");
        }
    }

    #[test]
    fn py_eq_compares_numbers_as_python() {
        assert!(Value::Bool(true).py_eq(&Value::Int(1)));
        assert!(Value::Int(0).py_eq(&Value::Bool(false)));
        assert!(Value::Float(1.0).py_eq(&Value::Int(1)));
        assert!(!Value::str("1").py_eq(&Value::Int(1)));
        assert!(!Value::None.py_eq(&Value::Bool(false)));
    }
}
