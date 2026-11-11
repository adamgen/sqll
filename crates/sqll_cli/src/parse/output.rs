//! The JSON output of "sqlfluff parse -f json", byte for byte.
//!
//! sqlfluff prints json.dumps(records) of Python and a newline. json.dumps
//! puts ", " between items and ": " after a key, keeps the key order, and
//! escapes each character that is not printable ASCII (ensure_ascii):
//! "\uXXXX", with a surrogate pair above U+FFFF.
//!
//! The writer walks the syntax tree (the parse interface, S3b C9) and
//! writes the JSON of its record (Node::as_record of sqll_parser, with
//! show_raw) with no record value between them (S3 T15). The tests compare
//! the two.

use std::io::{self, Write};

use sqll_tree::{NodeId, SegmentKind, SegmentType, SyntaxTree, Variant};

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

/// The static facts of a kind for the record, computed at the first use of
/// the kind (`KindFacts::of`).
#[derive(Clone, Copy)]
struct KindFacts {
    /// `Node::is_code` of a leaf: no instance type, type, or class type of
    /// whitespace, a newline, or a comment.
    leaf_code: bool,
    /// A leaf of this kind is code in its own value (`Node::to_tuple`): no
    /// instance type "whitespace", "newline", or "comment".
    value_code: bool,
    /// The class types have "raw".
    raw_class: bool,
}

impl KindFacts {
    fn of(kind: SegmentKind) -> Self {
        let data = kind.data();
        let ty = data.ty.name();
        let instance = |names: &[&str]| {
            data.instance_types
                .iter()
                .any(|t| names.contains(&t.name()))
        };
        let class = |name: &str| data.class_types.iter().any(|t| t.name() == name);
        let non_code = instance(&[
            "whitespace",
            "newline",
            "comment",
            "inline_comment",
            "block_comment",
            "trailing_newline",
        ]) || ty.contains("comment")
            || matches!(ty, "whitespace" | "newline")
            || class("comment");
        KindFacts {
            leaf_code: !non_code,
            value_code: !instance(&["whitespace", "newline", "comment"]),
            raw_class: class("raw"),
        }
    }
}

/// True if two of the keys are equal.
fn has_duplicates(keys: &[SegmentType]) -> bool {
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
struct RecordWriter<'w, 't, W: Write> {
    w: &'w mut W,
    tree: &'t SyntaxTree,
    options: RecordOptions,
    unparsable: bool,
    /// The facts of each kind that the writer found, by kind index.
    facts: Vec<Option<KindFacts>>,
    /// `Node::is_code` of each node, only for `code_only`.
    code: Vec<bool>,
    /// The relevant children of the open nodes, one range for each.
    stack: Vec<NodeId>,
    keys: Vec<SegmentType>,
}

impl<'w, 't, W: Write> RecordWriter<'w, 't, W> {
    fn new(w: &'w mut W, tree: &'t SyntaxTree, options: RecordOptions) -> Self {
        let mut writer = RecordWriter {
            w,
            tree,
            options,
            unparsable: false,
            facts: vec![None; SegmentKind::COUNT],
            code: Vec::new(),
            stack: Vec::new(),
            keys: Vec::new(),
        };
        if options.code_only {
            writer.code = writer.code_flags();
        }
        writer
    }

    fn facts(&mut self, kind: SegmentKind) -> KindFacts {
        let slot = &mut self.facts[kind.index() as usize];
        *slot.get_or_insert_with(|| KindFacts::of(kind))
    }

    /// `Node::is_code` of each node: a leaf by its kind, an unparsable node
    /// always, a segment if one of its children is code, else false. The
    /// children of a node come after it, so one pass from the end sets each
    /// segment from its children.
    fn code_flags(&mut self) -> Vec<bool> {
        let tree = self.tree;
        let mut code: Vec<bool> = tree
            .nodes()
            .map(|id| match tree.variant(id) {
                Variant::Raw => self.facts(tree.kind(id)).leaf_code,
                Variant::Unparsable => true,
                Variant::Segment | Variant::Meta | Variant::Empty => false,
            })
            .collect();
        let ids: Vec<NodeId> = tree.nodes().collect();
        for &id in ids.iter().rev() {
            if !code[id.index()] {
                continue;
            }
            if let Some(p) = tree.parent(id) {
                if tree.variant(p) == Variant::Segment {
                    code[p.index()] = true;
                }
            }
        }
        code
    }

    fn is_code(&self, id: NodeId) -> bool {
        self.code[id.index()]
    }

    /// Write {"key": value} of the node: structural_simplify(to_tuple(node)).
    fn entry(&mut self, id: NodeId) -> io::Result<()> {
        self.w.write_all(b"{")?;
        self.pair(id)?;
        self.w.write_all(b"}")
    }

    /// Write "key": value of the node.
    fn pair(&mut self, id: NodeId) -> io::Result<()> {
        let ty = self.tree.ty(id);
        if ty == SegmentType::UNPARSABLE {
            self.unparsable = true;
        }
        write_json_str(self.w, ty.name())?;
        self.w.write_all(b": ")?;
        self.value(id)
    }

    /// The value of the node in its 1-key mapping. This follows
    /// Node::to_tuple and Node::structural_simplify of sqll_parser
    /// (parser/types.rs) with show_raw: a raw text is a string, a tuple with
    /// no children is null, and a tuple with children is a mapping, or a
    /// list of 1-key mappings if 2 children have the same key.
    fn value(&mut self, id: NodeId) -> io::Result<()> {
        let RecordOptions {
            code_only,
            include_meta,
        } = self.options;
        let tree = self.tree;
        match tree.variant(id) {
            Variant::Raw => {
                if code_only && !self.facts(tree.kind(id)).value_code {
                    self.w.write_all(b"null")
                } else {
                    write_json_str(self.w, tree.raw(id))
                }
            }
            Variant::Meta => {
                if include_meta {
                    self.w.write_all(b"\"\"")
                } else {
                    self.w.write_all(b"null")
                }
            }
            Variant::Segment => {
                let start = self.stack.len();
                for c in tree.children(id) {
                    if !(code_only && !self.is_code(c)) && (include_meta || !tree.is_meta(c)) {
                        self.stack.push(c);
                    }
                }
                if self.stack.len() - start == 1
                    && self.facts(tree.kind(id)).raw_class
                    && tree.variant(self.stack[start]) == Variant::Raw
                {
                    let only = self.stack[start];
                    self.stack.truncate(start);
                    return write_json_str(self.w, tree.raw(only));
                }
                self.children(start)
            }
            Variant::Unparsable => {
                let start = self.stack.len();
                for c in tree.children(id) {
                    if !(code_only && !self.is_code(c)) {
                        self.stack.push(c);
                    }
                }
                self.children(start)
            }
            Variant::Empty => self.w.write_all(b"null"),
        }
    }

    /// Write the children `stack[start..]` and remove them from the stack.
    fn children(&mut self, start: usize) -> io::Result<()> {
        let end = self.stack.len();
        if start == end {
            return self.w.write_all(b"null");
        }
        self.keys.clear();
        for i in start..end {
            let ty = self.tree.ty(self.stack[i]);
            self.keys.push(ty);
        }
        let list = has_duplicates(&self.keys);
        self.w.write_all(if list { b"[" } else { b"{" })?;
        for i in start..end {
            if i > start {
                self.w.write_all(b", ")?;
            }
            let child = self.stack[i];
            if list {
                self.entry(child)?;
            } else {
                self.pair(child)?;
            }
        }
        self.stack.truncate(start);
        self.w.write_all(if list { b"]" } else { b"}" })
    }
}

/// Write [{"filepath": PATH, "segments": RECORD}] and a newline. RECORD is
/// the record of the root of the tree, or null if there is no tree (a
/// parse error). Return true if the record has an unparsable segment.
pub fn write_parse_json<W: Write>(
    out: W,
    filepath: &str,
    tree: Option<&SyntaxTree>,
    options: RecordOptions,
) -> io::Result<bool> {
    let mut out = io::BufWriter::with_capacity(1 << 16, out);
    out.write_all(b"[{\"filepath\": ")?;
    write_json_str(&mut out, filepath)?;
    out.write_all(b", \"segments\": ")?;
    let unparsable = match tree {
        Some(tree) => {
            let mut writer = RecordWriter::new(&mut out, tree, options);
            writer.entry(tree.root())?;
            writer.unparsable
        }
        None => {
            out.write_all(b"null")?;
            false
        }
    };
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
    use std::sync::Arc;

    use sqll_parser::parser::{MetaType, Node, RawSegmentKwargs};
    use sqll_tree::KindData;

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

    fn names(types: &[SegmentType]) -> Vec<String> {
        types.iter().map(|t| t.name().to_string()).collect()
    }

    /// The first kind of the variant and type for which `pick` is true.
    fn kind(variant: Variant, ty: &str, pick: impl Fn(&KindData) -> bool) -> SegmentKind {
        let ty = SegmentType::from_name(ty).expect("a type");
        *ty.kinds()
            .iter()
            .find(|k| k.data().variant == variant && pick(k.data()))
            .unwrap_or_else(|| panic!("no {variant:?} kind of {ty:?}"))
    }

    /// The first kind of the variant for which `pick` is true.
    fn kind_where(variant: Variant, pick: impl Fn(&KindData) -> bool) -> SegmentKind {
        SegmentKind::all()
            .find(|k| k.data().variant == variant && pick(k.data()))
            .unwrap_or_else(|| panic!("no {variant:?} kind"))
    }

    fn has(types: &[SegmentType], name: &str) -> bool {
        types.iter().any(|t| t.name() == name)
    }

    /// A parser leaf with the static data of the kind.
    fn leaf(kind: SegmentKind, text: &str) -> Node {
        let d = kind.data();
        Node::Raw {
            segment_class: Cow::Borrowed(d.class),
            segment_type: Cow::Borrowed(d.ty.name()),
            raw: text.to_string(),
            pos_marker: None,
            instance_types: names(d.instance_types),
            class_types: names(d.class_types),
            segment_kwargs: RawSegmentKwargs {
                trim_chars: d
                    .trim_chars
                    .map(|t| Arc::new(t.iter().map(|s| s.to_string()).collect())),
                quoted_value: d.quoted_value.map(|(a, b)| (a.to_string(), b.to_string())),
                escape_replacements: d.escape_replacements.map(|e| {
                    Arc::new(
                        e.iter()
                            .map(|(a, b)| (a.to_string(), b.to_string()))
                            .collect(),
                    )
                }),
            },
        }
    }

    /// A parser segment with the static data of the kind.
    fn segment(kind: SegmentKind, children: Vec<Node>) -> Node {
        let d = kind.data();
        Node::Segment {
            segment_class: Cow::Borrowed(d.class),
            segment_type: Some(Cow::Borrowed(d.ty.name())),
            pos_marker: None,
            class_types: names(d.class_types),
            children,
        }
    }

    fn meta(meta_type: MetaType) -> Node {
        Node::Meta {
            meta_type,
            pos_marker: None,
        }
    }

    /// The templated text of a parser tree: the texts of its leaves.
    fn text(node: &Node, out: &mut String) {
        match node {
            Node::Raw { raw, .. } => out.push_str(raw),
            Node::Segment { children, .. } | Node::Unparsable { children, .. } => {
                children.iter().for_each(|c| text(c, out))
            }
            Node::Meta { .. } | Node::Empty => {}
        }
    }

    /// Trees with each case of the record: duplicate keys (a list), unique
    /// keys (a mapping), a segment of the class "raw" with 1 child, empty
    /// children, meta segments, comments and whitespace (code_only), an
    /// unparsable segment, an empty node, and escapes. Each node has the
    /// static data of a kind, so that the conversion takes it.
    fn trees() -> Vec<Node> {
        let any = |_: &KindData| true;
        let ws = || leaf(kind(Variant::Raw, "whitespace", any), " ");
        let nl = || leaf(kind(Variant::Raw, "newline", any), "\n");
        let kw_kind = kind(Variant::Raw, "keyword", |d| {
            has(d.instance_types, "keyword")
        });
        let kw = |t: &str| leaf(kw_kind, t);
        let comment = leaf(
            kind_where(Variant::Raw, |d| has(d.instance_types, "comment")),
            "-- \u{e9}\"x\\",
        );
        let inline = leaf(kind(Variant::Raw, "inline_comment", any), "-- i");
        let block = leaf(kind(Variant::Raw, "block_comment", any), "/* b */");
        let file = kind(Variant::Segment, "file", any);
        let raw_segment = kind_where(Variant::Segment, |d| has(d.class_types, "raw"));
        let not_raw = kind(Variant::Segment, "column_reference", |d| {
            !has(d.class_types, "raw")
        });
        let statement = kind(Variant::Segment, "select_statement", any);
        let named = |ty: &str| segment(kind(Variant::Segment, ty, any), vec![]);
        let literal = segment(raw_segment, vec![kw("1")]);
        let literal_ws = segment(raw_segment, vec![ws(), kw("2")]);
        let literal_meta = segment(
            raw_segment,
            vec![meta(MetaType::Indent { is_implicit: false }), kw("4")],
        );
        let column = segment(not_raw, vec![kw("3")]);
        let unparsable = Node::Unparsable {
            expected: "x".to_string(),
            pos_marker: None,
            children: vec![
                kw("BAD"),
                ws(),
                meta(MetaType::Indent { is_implicit: false }),
                comment.clone(),
                segment(statement, vec![comment.clone()]),
            ],
        };
        let select = segment(
            statement,
            vec![
                kw("SELECT"),
                meta(MetaType::Indent { is_implicit: true }),
                ws(),
                literal,
                literal_ws,
                literal_meta,
                column,
                leaf(kind(Variant::Raw, "comma", any), ","),
                kw("FROM"),
                meta(MetaType::Dedent { is_implicit: false }),
                comment.clone(),
                block.clone(),
                Node::Empty,
                segment(statement, vec![]),
                segment(statement, vec![ws(), comment.clone()]),
                segment(raw_segment, vec![meta(MetaType::TemplateLoop)]),
            ],
        );
        let unique = segment(
            file,
            vec![
                select.clone(),
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
            file,
            vec![select.clone(), nl(), select, nl(), unparsable.clone()],
        );
        let many: Vec<Node> = (0..40)
            .map(|i| kw(if i == 39 { "k0" } else { "k" }))
            .collect();
        let many_unique: Vec<Node> = [
            "select_statement",
            "column_reference",
            "from_clause",
            "where_clause",
            "join_clause",
            "table_reference",
            "expression",
            "function",
        ]
        .iter()
        .map(|t| named(t))
        .collect();
        let many_types: Vec<Node> = ["expression", "function", "expression"]
            .iter()
            .cycle()
            .take(20)
            .map(|t| named(t))
            .chain([named("from_clause")])
            .collect();
        vec![
            unique,
            duplicates,
            segment(file, many),
            segment(file, many_unique),
            segment(file, many_types),
            segment(file, vec![]),
            segment(file, vec![comment.clone(), inline, block, ws()]),
            segment(file, vec![unparsable]),
            Node::Empty,
            meta(MetaType::EndOfFile),
            kw("\t\u{1}\u{1f600}"),
            comment,
        ]
    }

    #[test]
    fn the_writer_gives_the_output_of_the_record() {
        for (i, node) in trees().iter().enumerate() {
            let mut sql = String::new();
            text(node, &mut sql);
            let converted = sqll_syntax::from_node(node, sql).expect("the conversion");
            for code_only in [false, true] {
                for include_meta in [false, true] {
                    let options = RecordOptions {
                        code_only,
                        include_meta,
                    };
                    let mut got = Vec::new();
                    let unparsable =
                        write_parse_json(&mut got, "d/\u{e9}.sql", Some(&converted.tree), options)
                            .unwrap();
                    let (want, want_unparsable) =
                        oracle::parse_json("d/\u{e9}.sql", Some(node), code_only, include_meta);
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

    /// The facts of each kind are those of `Node::is_code` and of the
    /// record of a leaf of the kind.
    #[test]
    fn the_facts_of_each_kind_are_those_of_the_parser_node() {
        let mut leaves = 0;
        for k in SegmentKind::all() {
            let facts = KindFacts::of(k);
            assert_eq!(facts.raw_class, has(k.data().class_types, "raw"), "{k:?}");
            if k.data().variant != Variant::Raw {
                continue;
            }
            leaves += 1;
            let node = leaf(k, "x");
            assert_eq!(facts.leaf_code, node.is_code(), "{k:?}");
            let value = node.as_record(true, true, false);
            let value_code = !matches!(
                value,
                Some(serde_yaml_ng::Value::Mapping(ref m))
                    if m.values().all(serde_yaml_ng::Value::is_null)
            );
            assert_eq!(facts.value_code, value_code, "{k:?}");
        }
        assert!(leaves > 1000);
    }
}

#[cfg(test)]
mod fixture_tests {
    use std::path::{Path, PathBuf};
    use std::sync::Arc;
    use std::time::Instant;

    use sqll_syntax::parse::steps::parse_node;
    use sqll_syntax::{ParseOptions, TemplatedFile};

    use super::*;
    use crate::parse::steps as parse;
    use crate::parse::timings::Timer;

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

    /// For each dialect fixture file of the pinned sqlfluff (2306 files),
    /// with each option set: the writer over the tree of `sqll parse` gives
    /// the output and the unparsable flag of the record of the parser tree
    /// (Node::as_record, the output of sqll before C9).
    #[test]
    fn the_writer_gives_the_output_of_the_record_for_each_fixture() {
        let files = fixture_files();
        assert_eq!(files.len(), 2306);
        // The settings of the default config (max_parse_depth 600).
        let config = sqll_config::Config::new(Default::default(), &Default::default()).unwrap();
        let options = sqll_config::ParseSettings::new(&config, &config).unwrap();
        let mut unparsable = 0;
        for (name, path) in &files {
            let dialect = parse::dialect(name).expect("a dialect");
            let text = std::fs::read_to_string(path).unwrap();
            let file = Arc::new(TemplatedFile::from(text.clone()));
            let root = parse_node(file, dialect, &ParseOptions::default()).expect("a tree");
            let mut timer = Timer::new(Instant::now());
            let parsed = parse::parse(text, "f.sql", dialect, &options, &mut timer, true)
                .expect("the parse");
            assert!(parsed.errors.is_empty(), "{}", path.display());
            for code_only in [false, true] {
                for include_meta in [false, true] {
                    let record_options = RecordOptions {
                        code_only,
                        include_meta,
                    };
                    let mut got = Vec::new();
                    let flag =
                        write_parse_json(&mut got, "f.sql", parsed.tree.as_ref(), record_options)
                            .unwrap();
                    let (want, want_flag) =
                        oracle::parse_json("f.sql", Some(&root), code_only, include_meta);
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
