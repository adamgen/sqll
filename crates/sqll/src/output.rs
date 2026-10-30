//! The JSON output of "sqlfluff parse -f json", byte for byte.
//!
//! sqlfluff prints json.dumps(records) of Python and a newline. json.dumps
//! puts ", " between items and ": " after a key, keeps the key order, and
//! escapes each character that is not printable ASCII (ensure_ascii):
//! "\uXXXX", with a surrogate pair above U+FFFF.

use std::io::{self, Write};

use serde::Serialize;
use serde_json::ser::{CharEscape, Formatter, Serializer};
use serde_yaml_ng::Value;

/// A serde_json formatter with the output of Python json.dumps.
#[derive(Default)]
pub struct PythonFormatter;

impl Formatter for PythonFormatter {
    fn begin_array_value<W: ?Sized + Write>(&mut self, w: &mut W, first: bool) -> io::Result<()> {
        if first {
            Ok(())
        } else {
            w.write_all(b", ")
        }
    }

    fn begin_object_key<W: ?Sized + Write>(&mut self, w: &mut W, first: bool) -> io::Result<()> {
        if first {
            Ok(())
        } else {
            w.write_all(b", ")
        }
    }

    fn begin_object_value<W: ?Sized + Write>(&mut self, w: &mut W) -> io::Result<()> {
        w.write_all(b": ")
    }

    fn write_string_fragment<W: ?Sized + Write>(
        &mut self,
        w: &mut W,
        fragment: &str,
    ) -> io::Result<()> {
        let mut start = 0;
        for (i, c) in fragment.char_indices() {
            if c <= '~' {
                continue;
            }
            w.write_all(fragment[start..i].as_bytes())?;
            let mut units = [0u16; 2];
            for unit in c.encode_utf16(&mut units) {
                write!(w, "\\u{unit:04x}")?;
            }
            start = i + c.len_utf8();
        }
        w.write_all(fragment[start..].as_bytes())
    }

    fn write_char_escape<W: ?Sized + Write>(
        &mut self,
        w: &mut W,
        escape: CharEscape,
    ) -> io::Result<()> {
        let text = match escape {
            CharEscape::Quote => "\\\"",
            CharEscape::ReverseSolidus => "\\\\",
            CharEscape::Solidus => "\\/",
            CharEscape::Backspace => "\\b",
            CharEscape::FormFeed => "\\f",
            CharEscape::LineFeed => "\\n",
            CharEscape::CarriageReturn => "\\r",
            CharEscape::Tab => "\\t",
            CharEscape::AsciiControl(byte) => return write!(w, "\\u{byte:04x}"),
        };
        w.write_all(text.as_bytes())
    }
}

/// Serialize a value as Python json.dumps does.
pub fn to_python_json<T: Serialize + ?Sized>(value: &T) -> Vec<u8> {
    let mut out = Vec::new();
    let mut ser = Serializer::with_formatter(&mut out, PythonFormatter);
    value.serialize(&mut ser).expect("a value serializes");
    out
}

/// Write [{"filepath": PATH, "segments": RECORD}] and a newline.
pub fn write_parse_json<W: Write>(out: W, filepath: &str, record: &Value) -> io::Result<()> {
    let mut out = io::BufWriter::new(out);
    out.write_all(b"[{\"filepath\": ")?;
    out.write_all(&to_python_json(filepath))?;
    out.write_all(b", \"segments\": ")?;
    out.write_all(&to_python_json(record))?;
    out.write_all(b"}]\n")?;
    out.flush()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_separators_and_escapes() {
        let mut map = serde_yaml_ng::Mapping::new();
        let text = "x\u{e9}\u{1f600}\"\\/".to_string();
        map.insert("b".into(), Value::Sequence(vec!["x".into(), text.into()]));
        map.insert("a".into(), "\t\u{1}\u{7f}~".into());
        let got = String::from_utf8(to_python_json(&Value::Mapping(map))).unwrap();
        // The output of Python json.dumps for the same value.
        let want = r#"{"b": ["x", "x\u00e9\ud83d\ude00\"\\/"], "a": "\t\u0001\u007f~"}"#;
        assert_eq!(got, want);
    }
}
