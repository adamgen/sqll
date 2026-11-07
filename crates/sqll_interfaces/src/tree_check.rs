//! The check of a converted `SyntaxTree` against its parser tree (S3b C7
//! and C8, docs/interfaces/tree.md and source-map.md). The interface tests
//! of the tree and of the source map run it on the dialect fixtures, the S2
//! parse inputs, and templated files.
//!
//! The check does not use the conversion code: it reads the `Node` tree and
//! the tree side by side, in pre-order, and compares each node.

use std::collections::BTreeSet;

use sqll_parser::parser::{MetaType, Node};
use sqll_syntax::Converted;
use sqll_tree::{LinePos, Meta, NodeId, SegmentType, SyntaxTree, Variant};
use sqll_types::PositionMarker;

/// The counts of one checked tree.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Counts {
    pub nodes: usize,
    pub raw: usize,
    pub segment: usize,
    pub meta: usize,
    pub unparsable: usize,
    pub empty: usize,
    /// The nodes with a position marker: their byte range, line position,
    /// source range, source position, and literal flag are those of the
    /// marker.
    pub positioned: usize,
    /// The positioned nodes whose source range is not their templated
    /// range.
    pub source_differs: usize,
    /// The positioned nodes of a templated file whose marker has a wider
    /// templated slice than their range (`Check::position`).
    pub split: usize,
    pub bytes: usize,
    pub lines: usize,
}

impl std::ops::AddAssign for Counts {
    fn add_assign(&mut self, o: Counts) {
        self.nodes += o.nodes;
        self.raw += o.raw;
        self.segment += o.segment;
        self.meta += o.meta;
        self.unparsable += o.unparsable;
        self.empty += o.empty;
        self.positioned += o.positioned;
        self.source_differs += o.source_differs;
        self.split += o.split;
        self.bytes += o.bytes;
        self.lines += o.lines;
    }
}

/// Type names that the check also asks `is_type` for on each node.
const PROBE_TYPES: &[&str] = &[
    "keyword",
    "statement",
    "whitespace",
    "newline",
    "comment",
    "identifier",
    "literal",
    "symbol",
    "raw",
    "base",
    "expression",
];

fn pos_marker(node: &Node) -> Option<&PositionMarker> {
    match node {
        Node::Raw { pos_marker, .. }
        | Node::Segment { pos_marker, .. }
        | Node::Meta { pos_marker, .. }
        | Node::Unparsable { pos_marker, .. } => pos_marker.as_ref(),
        Node::Empty => None,
    }
}

fn children(node: &Node) -> &[Node] {
    match node {
        Node::Segment { children, .. } | Node::Unparsable { children, .. } => children,
        _ => &[],
    }
}

fn names(types: &[SegmentType]) -> Vec<&'static str> {
    types.iter().map(|t| t.name()).collect()
}

fn set(types: &[String]) -> Vec<&str> {
    let s: BTreeSet<&str> = types.iter().map(String::as_str).collect();
    s.into_iter().collect()
}

fn sorted(mut v: Vec<&'static str>) -> Vec<&'static str> {
    v.sort_unstable();
    v
}

fn meta_of(meta_type: &MetaType) -> Meta<'_> {
    match meta_type {
        MetaType::Indent { is_implicit } => Meta::Indent {
            implicit: *is_implicit,
        },
        MetaType::Dedent { is_implicit } => Meta::Dedent {
            implicit: *is_implicit,
        },
        MetaType::Template { block_type, .. } => Meta::Template { block_type },
        MetaType::TemplateLoop => Meta::TemplateLoop,
        MetaType::EndOfFile => Meta::EndOfFile,
    }
}

/// For each code point offset of the text, and for its end: the byte offset,
/// and the line and position of sqlfluff (Python `str` offsets: a "\n" is
/// the last character of its line).
fn code_points(text: &str) -> Vec<(usize, LinePos)> {
    let mut v = Vec::with_capacity(text.len() + 1);
    let (mut line, mut pos) = (1, 1);
    for (b, c) in text.char_indices() {
        v.push((b, LinePos { line, pos }));
        if c == '\n' {
            line += 1;
            pos = 1;
        } else {
            pos += 1;
        }
    }
    v.push((text.len(), LinePos { line, pos }));
    v
}

/// The lossless rule: the leaves, in order, are the text, each byte one
/// time; a meta node has zero length at its place.
pub fn check_lossless(tree: &SyntaxTree, text: &str) -> Result<(), String> {
    if tree.text() != text {
        return Err("the tree text is not the templated text".into());
    }
    let mut joined = String::with_capacity(text.len());
    let mut cursor = 0;
    for id in tree.raw_segments(tree.root()) {
        let r = tree.range(id);
        if r.start != cursor {
            return Err(format!(
                "leaf {} starts at byte {}, not at byte {cursor}",
                id.index(),
                r.start
            ));
        }
        if tree.is_meta(id) && !r.is_empty() {
            return Err(format!("meta node {} has a length", id.index()));
        }
        joined.push_str(tree.raw(id));
        cursor = r.end;
    }
    if joined != text {
        return Err("the leaf texts are not the templated text".into());
    }
    Ok(())
}

struct Check<'a> {
    tree: &'a SyntaxTree,
    text: &'a str,
    converted: &'a Converted,
    code_points: Vec<(usize, LinePos)>,
    /// The code points of the source text.
    source_points: Vec<(usize, LinePos)>,
    expected: usize,
    placeholders: usize,
    counts: Counts,
}

impl Check<'_> {
    fn node(&mut self, node: &Node, id: NodeId, parent: Option<NodeId>) -> Result<(), String> {
        let tree = self.tree;
        let kind = tree.kind(id);
        let data = kind.data();
        let ty = node.get_type();
        if tree.ty(id).name() != ty {
            return Err(format!("type {:?}, not {ty:?}", tree.ty(id).name()));
        }
        if tree.raw(id) != node.raw() {
            return Err(format!("raw {:?}, not {:?}", tree.raw(id), node.raw()));
        }
        if tree.parent(id) != parent {
            return Err(format!("parent {:?}, not {parent:?}", tree.parent(id)));
        }
        if tree.children(id).count() != children(node).len() {
            return Err("the children are not those of the node".into());
        }
        if tree.class_types(id) != data.class_types {
            return Err("the class types are not those of the kind".into());
        }
        let class_types = sorted(names(data.class_types));
        self.counts.nodes += 1;
        match node {
            Node::Raw {
                segment_class,
                instance_types,
                class_types: node_class_types,
                segment_kwargs: k,
                ..
            } => {
                self.counts.raw += 1;
                let same = data.variant == Variant::Raw
                    && data.class == segment_class.as_ref()
                    && names(data.instance_types) == *instance_types
                    && class_types == set(node_class_types)
                    && data.trim_chars.map(<[&str]>::to_vec)
                        == k.trim_chars
                            .as_deref()
                            .map(|v| v.iter().map(String::as_str).collect())
                    && data.quoted_value
                        == k.quoted_value
                            .as_ref()
                            .map(|(a, b)| (a.as_str(), b.as_str()))
                    && data.escape_replacements.map(<[(&str, &str)]>::to_vec)
                        == k.escape_replacements
                            .as_deref()
                            .map(|v| v.iter().map(|(a, b)| (a.as_str(), b.as_str())).collect())
                    && data.meta.is_none();
                if !same {
                    return Err(format!("the leaf data {data:?} is not that of the node"));
                }
                for t in instance_types.iter().chain(node_class_types) {
                    self.is_type(node, id, t)?;
                }
            }
            Node::Segment {
                segment_class,
                class_types: node_class_types,
                ..
            } => {
                self.counts.segment += 1;
                if data.variant != Variant::Segment
                    || data.class != segment_class.as_ref()
                    || class_types != set(node_class_types)
                {
                    return Err(format!("the segment data {data:?} is not that of the node"));
                }
                for t in node_class_types {
                    self.is_type(node, id, t)?;
                }
            }
            Node::Meta { meta_type, .. } => {
                self.counts.meta += 1;
                if data.variant != Variant::Meta
                    || data.meta != Some(meta_of(meta_type))
                    || !data.class.is_empty()
                {
                    return Err(format!("the meta data {data:?} is not that of the node"));
                }
                if let MetaType::Template { source_str, .. } = meta_type {
                    let want = (id, source_str.clone());
                    if self.converted.placeholders.get(self.placeholders) != Some(&want) {
                        return Err("the placeholder source text is not that of the node".into());
                    }
                    self.placeholders += 1;
                }
            }
            Node::Unparsable { expected, .. } => {
                self.counts.unparsable += 1;
                if data.variant != Variant::Unparsable {
                    return Err("an unparsable node has another kind".into());
                }
                let want = (id, expected.clone());
                if self.converted.expected.get(self.expected) != Some(&want) {
                    return Err("the expected text is not that of the node".into());
                }
                self.expected += 1;
            }
            Node::Empty => {
                self.counts.empty += 1;
                if data.variant != Variant::Empty {
                    return Err("an empty node has another kind".into());
                }
            }
        }
        self.is_type(node, id, &ty)?;
        for t in PROBE_TYPES {
            self.is_type(node, id, t)?;
        }
        if let Some(pm) = pos_marker(node) {
            self.position(id, pm)?;
        }
        Ok(())
    }

    /// The tree and the node agree on `is_type` for the type name.
    fn is_type(&self, node: &Node, id: NodeId, name: &str) -> Result<(), String> {
        let want = node.is_type(name);
        let got = SegmentType::from_name(name).is_some_and(|t| self.tree.is_type(id, t));
        if got != want {
            return Err(format!("is_type({name:?}) is {got}, not {want}"));
        }
        Ok(())
    }

    /// The byte range and the line position of the node are those of its
    /// position marker (code point offsets of the templated text), and so
    /// are the source range, the source line position, and the literal
    /// flag (code point offsets of the source text).
    ///
    /// The line positions of sqlfluff come from the code points
    /// (`code_points`). The ported `get_line_pos_of_char_pos` must give
    /// them too (S3b C8: its newline index has code point offsets).
    fn position(&mut self, id: NodeId, pm: &PositionMarker) -> Result<(), String> {
        if pm.templated_file.templated_str != self.text {
            return Err("the position marker has another templated text".into());
        }
        if pm.templated_file.source_str != self.tree.source_text() {
            return Err("the position marker has another source text".into());
        }
        let points =
            |v: &[(usize, LinePos)], start: usize, stop: usize| match (v.get(start), v.get(stop)) {
                (Some(&a), Some(&b)) => Ok((a, b)),
                _ => Err(format!(
                    "the slice {start}..{stop} is after the end of the text"
                )),
            };
        let slice = pm.templated_slice;
        let (start, stop) = points(&self.code_points, slice.start, slice.stop)?;
        let range = self.tree.range(id);
        let templated = self.tree.source_map().is_some_and(|m| !m.is_identity());
        if (start.0, stop.0) != (range.start, range.end) {
            // The lexer of sqlfluff can split a lexed element at the edge of
            // a template slice; each part keeps the templated slice of the
            // element. The tree keeps the lossless range of each part.
            if !(templated && start.0 <= range.start && range.end <= stop.0) {
                return Err(format!(
                    "byte range {range:?}, not that of the templated slice {}..{} ({}..{})",
                    slice.start, slice.stop, start.0, stop.0
                ));
            }
            self.counts.split += 1;
        } else {
            let got = self.tree.start_pos(id);
            if got != start.1 {
                return Err(format!("line position {got:?}, not {:?}", start.1));
            }
            let ported = pm
                .templated_file
                .get_line_pos_of_char_pos(slice.start, false);
            if ported != (got.line, got.pos) {
                return Err(format!(
                    "line position {got:?}, but the ported position is {ported:?}"
                ));
            }
        }

        let source = pm.source_slice;
        let (start, stop) = points(&self.source_points, source.start, source.stop)?;
        let range = self.tree.source_range(id);
        if (start.0, stop.0) != (range.start, range.end) {
            return Err(format!(
                "source range {range:?}, not that of the source slice {}..{} ({}..{})",
                source.start, source.stop, start.0, stop.0
            ));
        }
        let got = self.tree.source_pos(id);
        let ported = pm.source_position();
        if got != start.1 || ported != (got.line, got.pos) {
            return Err(format!(
                "source position {got:?}, not {:?} (ported {ported:?})",
                start.1
            ));
        }
        if self.tree.is_literal(id) != pm.is_literal() {
            return Err(format!(
                "is_literal is {}, not {}",
                self.tree.is_literal(id),
                pm.is_literal()
            ));
        }
        if range != self.tree.range(id) {
            self.counts.source_differs += 1;
        }
        self.counts.positioned += 1;
        Ok(())
    }
}

/// Check a conversion of the parser tree `root` of the templated text
/// `text`: the tree obeys its rules (`verify`) and the lossless rule, and
/// each node, in pre-order, has the type, the raw text, the parent, the
/// number of children, the static data, the `is_type` answers, the byte
/// range, the line position, the source range, the source position, and the
/// literal flag of its `Node`. The expected texts and the placeholder source
/// texts are those of the nodes.
pub fn check(root: &Node, text: &str, converted: &Converted) -> Result<Counts, String> {
    let tree = &converted.tree;
    tree.verify().map_err(|e| format!("verify: {e}"))?;
    check_lossless(tree, text)?;
    let mut c = Check {
        tree,
        text,
        converted,
        code_points: code_points(text),
        source_points: code_points(tree.source_text()),
        expected: 0,
        placeholders: 0,
        counts: Counts::default(),
    };
    let mut ids = tree.nodes();
    // A stack of (children left, tree id of the parent).
    let mut stack: Vec<(std::slice::Iter<'_, Node>, NodeId)> = Vec::new();
    let root_id = ids.next().ok_or("the tree has no node")?;
    c.node(root, root_id, None)
        .map_err(|e| format!("node 0: {e}"))?;
    stack.push((children(root).iter(), root_id));
    while let Some((iter, parent)) = stack.last_mut() {
        let parent = *parent;
        match iter.next() {
            Some(node) => {
                let id = ids
                    .next()
                    .ok_or("the tree has fewer nodes than the Node tree")?;
                c.node(node, id, Some(parent))
                    .map_err(|e| format!("node {}: {e}", id.index()))?;
                stack.push((children(node).iter(), id));
            }
            None => {
                stack.pop();
            }
        }
    }
    if ids.next().is_some() {
        return Err("the tree has more nodes than the Node tree".into());
    }
    if c.expected != converted.expected.len() || c.placeholders != converted.placeholders.len() {
        return Err("the conversion has more expected or placeholder texts".into());
    }
    c.counts.bytes = text.len();
    c.counts.lines = tree.line_index().line_count();
    Ok(c.counts)
}
