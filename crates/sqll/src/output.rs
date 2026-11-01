//! The JSON output of "sqlfluff parse -f json", byte for byte.
//!
//! sqlfluff prints json.dumps(records) of Python and a newline. json.dumps
//! puts ", " between items and ": " after a key, keeps the key order, and
//! escapes each character that is not printable ASCII (ensure_ascii):
//! "\uXXXX", with a surrogate pair above U+FFFF.
//!
//! The writer walks the parse tree and writes the JSON of its record
//! (Node::as_record of sqll_parser, with show_raw) with no record value
//! between them (S3 T15). The tests compare the two.

use std::io::{self, Write};

use sqll_parser::parser::{MetaType, Node};

/// Write the text as a JSON string of Python json.dumps (ensure_ascii).
pub fn write_json_str<W: Write>(w: &mut W, text: &str) -> io::Result<()> {
    w.write_all(b"\"")?;
    let bytes = text.as_bytes();
    let mut start = 0;
    for (i, c) in text.char_indices() {
        let escape: &[u8] = match c {
            '"' => b"\\\"",
            '\\' => b"\\\\",
            '\n' => b"\\n",
            '\r' => b"\\r",
            '\t' => b"\\t",
            '\u{8}' => b"\\b",
            '\u{c}' => b"\\f",
            ' '..='~' => continue,
            _ => b"",
        };
        w.write_all(&bytes[start..i])?;
        if escape.is_empty() {
            let mut units = [0u16; 2];
            for unit in c.encode_utf16(&mut units) {
                write!(w, "\\u{unit:04x}")?;
            }
        } else {
            w.write_all(escape)?;
        }
        start = i + c.len_utf8();
    }
    w.write_all(&bytes[start..])?;
    w.write_all(b"\"")
}

/// The options of the record (sqlfluff parse --code-only, --include-meta).
#[derive(Clone, Copy)]
pub struct RecordOptions {
    pub code_only: bool,
    pub include_meta: bool,
}

/// The key of a node in the record: Node::get_type, with no copy.
fn key(node: &Node) -> &str {
    match node {
        Node::Raw { segment_type, .. } => segment_type,
        Node::Segment { segment_type, .. } => segment_type.as_deref().unwrap_or_default(),
        Node::Meta { meta_type, .. } => match meta_type {
            MetaType::Indent { .. } => "indent",
            MetaType::Dedent { .. } => "dedent",
            MetaType::Template { .. } => "placeholder",
            MetaType::TemplateLoop => "template_loop",
            MetaType::EndOfFile => "end_of_file",
        },
        Node::Unparsable { .. } => "unparsable",
        Node::Empty => "empty",
    }
}

/// True if two of the keys are equal.
fn has_duplicates(keys: &[&str]) -> bool {
    if keys.len() <= 16 {
        keys.iter()
            .enumerate()
            .any(|(i, k)| keys[i + 1..].contains(k))
    } else {
        let mut seen = std::collections::HashSet::with_capacity(keys.len());
        !keys.iter().all(|k| seen.insert(*k))
    }
}

/// The writer of one record. `unparsable` becomes true if the record has
/// the key "unparsable" (an unparsable segment).
struct RecordWriter<'w, W: Write> {
    w: &'w mut W,
    options: RecordOptions,
    unparsable: bool,
}

impl<W: Write> RecordWriter<'_, W> {
    /// Write {"key": value} of the node: structural_simplify(to_tuple(node)).
    fn entry(&mut self, node: &Node) -> io::Result<()> {
        self.w.write_all(b"{")?;
        self.pair(node)?;
        self.w.write_all(b"}")
    }

    /// Write "key": value of the node.
    fn pair(&mut self, node: &Node) -> io::Result<()> {
        let k = key(node);
        if k == "unparsable" {
            self.unparsable = true;
        }
        write_json_str(self.w, k)?;
        self.w.write_all(b": ")?;
        self.value(node)
    }

    /// The value of the node in its 1-key mapping. This follows
    /// Node::to_tuple and Node::structural_simplify of sqll_parser
    /// (parser/types.rs) with show_raw: a raw text is a string, a tuple with
    /// no children is null, and a tuple with children is a mapping, or a
    /// list of 1-key mappings if 2 children have the same key.
    fn value(&mut self, node: &Node) -> io::Result<()> {
        let RecordOptions {
            code_only,
            include_meta,
        } = self.options;
        match node {
            Node::Raw {
                raw,
                instance_types,
                ..
            } => {
                let is_code = !instance_types
                    .iter()
                    .any(|t| matches!(t.as_str(), "whitespace" | "newline" | "comment"));
                if code_only && !is_code {
                    self.w.write_all(b"null")
                } else {
                    write_json_str(self.w, raw)
                }
            }
            Node::Meta { .. } => {
                if include_meta {
                    self.w.write_all(b"\"\"")
                } else {
                    self.w.write_all(b"null")
                }
            }
            Node::Segment {
                children,
                class_types,
                ..
            } => {
                let relevant: Vec<&Node> = children
                    .iter()
                    .filter(|c| !(code_only && !c.is_code()) && (include_meta || !c.is_meta()))
                    .collect();
                if relevant.len() == 1 && class_types.iter().any(|t| t == "raw") {
                    if let Node::Raw { raw, .. } = relevant[0] {
                        return write_json_str(self.w, raw);
                    }
                }
                self.children(&relevant)
            }
            Node::Unparsable { children, .. } => {
                let relevant: Vec<&Node> = children
                    .iter()
                    .filter(|c| !(code_only && !c.is_code()))
                    .collect();
                self.children(&relevant)
            }
            Node::Empty => self.w.write_all(b"null"),
        }
    }

    fn children(&mut self, children: &[&Node]) -> io::Result<()> {
        if children.is_empty() {
            return self.w.write_all(b"null");
        }
        let keys: Vec<&str> = children.iter().map(|c| key(c)).collect();
        let list = has_duplicates(&keys);
        self.w.write_all(if list { b"[" } else { b"{" })?;
        for (i, child) in children.iter().enumerate() {
            if i > 0 {
                self.w.write_all(b", ")?;
            }
            if list {
                self.entry(child)?;
            } else {
                self.pair(child)?;
            }
        }
        self.w.write_all(if list { b"]" } else { b"}" })
    }
}

/// Write [{"filepath": PATH, "segments": RECORD}] and a newline. RECORD is
/// the record of the root, or null if there is no root (a parse error).
/// Return true if the record has an unparsable segment.
pub fn write_parse_json<W: Write>(
    out: W,
    filepath: &str,
    root: Option<&Node>,
    options: RecordOptions,
) -> io::Result<bool> {
    let mut out = io::BufWriter::with_capacity(1 << 16, out);
    out.write_all(b"[{\"filepath\": ")?;
    write_json_str(&mut out, filepath)?;
    out.write_all(b", \"segments\": ")?;
    let mut writer = RecordWriter {
        w: &mut out,
        options,
        unparsable: false,
    };
    match root {
        Some(node) => writer.entry(node)?,
        None => writer.w.write_all(b"null")?,
    }
    let unparsable = writer.unparsable;
    out.write_all(b"}]\n")?;
    out.flush()?;
    Ok(unparsable)
}

#[cfg(test)]
pub mod oracle {
    //! The output of sqll before S3 T15: the record value of
    //! Node::as_record, serialized by serde_json with the separators and
    //! escapes of Python json.dumps. The tests compare the writer with it.

    use std::io::{self, Write};

    use serde::Serialize;
    use serde_json::ser::{CharEscape, Formatter, Serializer};
    use serde_yaml_ng::Value;
    use sqll_parser::parser::Node;

    #[derive(Default)]
    pub struct PythonFormatter;

    impl Formatter for PythonFormatter {
        fn begin_array_value<W: ?Sized + Write>(
            &mut self,
            w: &mut W,
            first: bool,
        ) -> io::Result<()> {
            if first {
                Ok(())
            } else {
                w.write_all(b", ")
            }
        }

        fn begin_object_key<W: ?Sized + Write>(
            &mut self,
            w: &mut W,
            first: bool,
        ) -> io::Result<()> {
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

    pub fn to_python_json<T: Serialize + ?Sized>(value: &T) -> Vec<u8> {
        let mut out = Vec::new();
        let mut ser = Serializer::with_formatter(&mut out, PythonFormatter);
        value.serialize(&mut ser).expect("a value serializes");
        out
    }

    fn has_unparsable(value: &Value) -> bool {
        match value {
            Value::Mapping(map) => map
                .iter()
                .any(|(k, v)| k.as_str() == Some("unparsable") || has_unparsable(v)),
            Value::Sequence(items) => items.iter().any(has_unparsable),
            _ => false,
        }
    }

    /// The output and the unparsable flag of sqll before T15.
    pub fn parse_json(
        filepath: &str,
        root: Option<&Node>,
        code_only: bool,
        include_meta: bool,
    ) -> (Vec<u8>, bool) {
        let record = root
            .and_then(|node| node.as_record(code_only, true, include_meta))
            .unwrap_or(Value::Null);
        let mut out = b"[{\"filepath\": ".to_vec();
        out.extend(to_python_json(filepath));
        out.extend(b", \"segments\": ");
        out.extend(to_python_json(&record));
        out.extend(b"}]\n");
        (out, has_unparsable(&record))
    }
}

#[cfg(test)]
mod tests {
    use std::borrow::Cow;

    use sqll_parser::parser::RawSegmentKwargs;

    use super::*;

    fn json_str(text: &str) -> String {
        let mut out = Vec::new();
        write_json_str(&mut out, text).unwrap();
        String::from_utf8(out).unwrap()
    }

    #[test]
    fn python_separators_and_escapes() {
        let mut map = serde_yaml_ng::Mapping::new();
        let text = "x\u{e9}\u{1f600}\"\\/".to_string();
        map.insert(
            "b".into(),
            serde_yaml_ng::Value::Sequence(vec!["x".into(), text.into()]),
        );
        map.insert("a".into(), "\t\u{1}\u{7f}~".into());
        let got =
            String::from_utf8(oracle::to_python_json(&serde_yaml_ng::Value::Mapping(map))).unwrap();
        // The output of Python json.dumps for the same value.
        let want = r#"{"b": ["x", "x\u00e9\ud83d\ude00\"\\/"], "a": "\t\u0001\u007f~"}"#;
        assert_eq!(got, want);
    }

    #[test]
    fn the_string_escapes_are_those_of_the_oracle_for_each_character() {
        let all: String = (0..=0x10ffffu32).filter_map(char::from_u32).collect();
        assert_eq!(
            json_str(&all).into_bytes(),
            oracle::to_python_json(all.as_str())
        );
        for text in ["", "a", "\"", "\\", "\u{7f}", "a\u{0}b", "\u{10ffff}z"] {
            assert_eq!(json_str(text).into_bytes(), oracle::to_python_json(text));
        }
    }

    fn raw(segment_type: &'static str, text: &str, instance_types: &[&str]) -> Node {
        Node::new_raw(
            "RawSegment",
            segment_type,
            text.to_string(),
            None,
            instance_types.iter().map(|t| t.to_string()).collect(),
            RawSegmentKwargs::default(),
        )
    }

    fn segment(
        segment_type: Option<&'static str>,
        class_types: &[&str],
        children: Vec<Node>,
    ) -> Node {
        Node::Segment {
            segment_class: Cow::Borrowed("Segment"),
            segment_type: segment_type.map(Cow::Borrowed),
            pos_marker: None,
            class_types: class_types.iter().map(|t| t.to_string()).collect(),
            children,
        }
    }

    fn meta(meta_type: MetaType) -> Node {
        Node::Meta {
            meta_type,
            pos_marker: None,
        }
    }

    /// Trees with each case of the record: duplicate keys (a list), unique
    /// keys (a mapping), a segment of the class "raw" with 1 child, empty
    /// children, meta segments, comments and whitespace (code_only), an
    /// unparsable segment, an empty node, and escapes.
    fn trees() -> Vec<Node> {
        let ws = || raw("whitespace", " ", &["whitespace"]);
        let nl = || raw("newline", "\n", &["newline"]);
        let kw = |t: &str| raw("keyword", t, &["keyword"]);
        let comment = raw("comment", "-- \u{e9}\"x\\", &["comment"]);
        let block = raw("block_comment", "/* b */", &["block_comment"]);
        let literal = segment(Some("numeric_literal"), &["raw", "literal"], vec![kw("1")]);
        let literal_ws = segment(Some("numeric_literal"), &["raw"], vec![ws(), kw("2")]);
        let not_raw = segment(Some("column_index"), &["column_index"], vec![kw("3")]);
        let unparsable = Node::Unparsable {
            expected: "x".to_string(),
            pos_marker: None,
            children: vec![
                kw("BAD"),
                ws(),
                meta(MetaType::Indent { is_implicit: false }),
                comment.clone(),
            ],
        };
        let statement = segment(
            Some("select_statement"),
            &["statement"],
            vec![
                kw("SELECT"),
                meta(MetaType::Indent { is_implicit: true }),
                ws(),
                literal,
                literal_ws,
                not_raw,
                raw("comma", ",", &["comma"]),
                kw("FROM"),
                meta(MetaType::Dedent { is_implicit: false }),
                comment.clone(),
                block.clone(),
                Node::Empty,
                segment(None, &[], vec![]),
                segment(
                    Some("empty_segment"),
                    &["raw"],
                    vec![meta(MetaType::TemplateLoop)],
                ),
            ],
        );
        let unique = segment(
            Some("file"),
            &[],
            vec![
                statement.clone(),
                nl(),
                unparsable.clone(),
                meta(MetaType::EndOfFile),
                meta(MetaType::Template {
                    source_str: "{{x}}".to_string(),
                    block_type: "templated".to_string(),
                }),
            ],
        );
        let duplicates = segment(
            Some("file"),
            &[],
            vec![statement.clone(), nl(), statement, nl(), unparsable],
        );
        let many: Vec<Node> = (0..40)
            .map(|i| kw(if i == 39 { "k0" } else { "k" }))
            .collect();
        let many_unique: Vec<Node> = ["a", "b", "c", "d", "e", "f", "g", "h"]
            .iter()
            .map(|t| segment(Some(t), &[], vec![]))
            .collect();
        vec![
            unique,
            duplicates,
            segment(Some("file"), &[], many),
            segment(Some("file"), &[], many_unique),
            segment(Some("file"), &[], vec![]),
            segment(Some("file"), &[], vec![comment, block, ws()]),
            Node::Empty,
            raw("keyword", "\t\u{1}\u{1f600}", &["keyword"]),
        ]
    }

    #[test]
    fn the_writer_gives_the_output_of_the_record() {
        for (i, tree) in trees().iter().enumerate() {
            for code_only in [false, true] {
                for include_meta in [false, true] {
                    let options = RecordOptions {
                        code_only,
                        include_meta,
                    };
                    let mut got = Vec::new();
                    let unparsable =
                        write_parse_json(&mut got, "d/\u{e9}.sql", Some(tree), options).unwrap();
                    let (want, want_unparsable) =
                        oracle::parse_json("d/\u{e9}.sql", Some(tree), code_only, include_meta);
                    assert_eq!(
                        String::from_utf8(got).unwrap(),
                        String::from_utf8(want).unwrap(),
                        "tree {i}, code_only {code_only}, include_meta {include_meta}"
                    );
                    assert_eq!(unparsable, want_unparsable, "tree {i}");
                }
            }
        }
        let mut got = Vec::new();
        let options = RecordOptions {
            code_only: false,
            include_meta: false,
        };
        assert!(!write_parse_json(&mut got, "stdin", None, options).unwrap());
        assert_eq!(got, oracle::parse_json("stdin", None, false, false).0);
    }
}

#[cfg(test)]
mod fixture_tests {
    use std::path::{Path, PathBuf};
    use std::time::Instant;

    use super::*;
    use crate::parse;
    use crate::timings::Timer;

    fn fixture_files() -> Vec<(String, PathBuf)> {
        let dir = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../third_party/sqlfluff/test/fixtures/dialects");
        let mut out = Vec::new();
        for entry in std::fs::read_dir(dir).expect("the sqlfluff submodule") {
            let folder = entry.unwrap().path();
            if !folder.is_dir() {
                continue;
            }
            let name = folder.file_name().unwrap().to_str().unwrap().to_string();
            for file in std::fs::read_dir(&folder).unwrap() {
                let path = file.unwrap().path();
                if path.extension().is_some_and(|e| e == "sql") {
                    out.push((name.clone(), path));
                }
            }
        }
        out.sort();
        out
    }

    /// The writer and the record give the same output and the same
    /// unparsable flag for each dialect fixture file of the pinned sqlfluff
    /// (2306 files), with each option set.
    #[test]
    fn the_writer_gives_the_output_of_the_record_for_each_fixture() {
        let files = fixture_files();
        assert_eq!(files.len(), 2306);
        let options = parse::Options {
            code_only: false,
            include_meta: false,
            max_parse_depth: parse::MAX_PARSE_DEPTH,
        };
        let mut unparsable = 0;
        for (name, path) in &files {
            let dialect = parse::dialect(name).expect("a dialect");
            let text = std::fs::read_to_string(path).unwrap();
            let mut timer = Timer::new(Instant::now());
            let parsed = parse::parse(text, dialect, &options, &mut timer, true);
            for code_only in [false, true] {
                for include_meta in [false, true] {
                    let record_options = RecordOptions {
                        code_only,
                        include_meta,
                    };
                    let mut got = Vec::new();
                    let flag =
                        write_parse_json(&mut got, "f.sql", parsed.root.as_ref(), record_options)
                            .unwrap();
                    let (want, want_flag) =
                        oracle::parse_json("f.sql", parsed.root.as_ref(), code_only, include_meta);
                    assert!(got == want, "{}", path.display());
                    assert_eq!(flag, want_flag, "{}", path.display());
                    unparsable += usize::from(flag);
                }
            }
        }
        // The fixtures have no unparsable segment (S1: 2306 of 2306
        // no_unparsable), so the flag is checked by the trees of the tests
        // module.
        assert_eq!(unparsable, 0);
    }
}
