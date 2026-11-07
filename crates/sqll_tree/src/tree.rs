//! The lossless syntax tree (docs/interfaces/tree.md, S3b task C7).
//!
//! A [`SyntaxTree`] keeps one buffer of the templated text and a flat list
//! of node records in pre-order, that is, in source order. A node id is an
//! index into the list; the root is node 0. A leaf is a byte range of the
//! buffer and holds no string. Each node has one [`SegmentKind`], which
//! gives its static data: the type, the class types (a sorted set of type
//! ids, for `is_type`), and the other data of
//! docs/interfaces/segment-kinds.md. A meta node (indent, dedent,
//! placeholder, template loop, end of file) has zero length.
//!
//! Only a [`TreeBuilder`] makes a tree. It refuses a leaf that is not the
//! next text of the buffer and a tree whose leaves do not cover the buffer.
//! Thus the texts of the leaves, in order, are the templated text, with each
//! byte one time. [`SyntaxTree::verify`] checks this again.

use std::fmt;
use std::ops::Range;

use crate::kinds::{SegmentKind, SegmentType, Variant};

const NONE: u32 = u32::MAX;

/// The id of a node: its index in the pre-order of its tree.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct NodeId(u32);

impl NodeId {
    /// The root of each tree.
    pub const ROOT: NodeId = NodeId(0);

    pub fn index(self) -> usize {
        self.0 as usize
    }
}

/// One node: 20 bytes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Record {
    kind: SegmentKind,
    /// The templated byte range.
    start: u32,
    end: u32,
    /// The parent, or NONE for the root.
    parent: u32,
    /// The index after the last descendant. The descendants of node i are
    /// the nodes i + 1 to next - 1.
    next: u32,
}

/// A line and a position in the line, both from 1. The position counts
/// characters (Unicode scalar values), as sqlfluff does. Only "\n" ends a
/// line: the "\r" of "\r\n" is the last character of its line.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct LinePos {
    pub line: usize,
    pub pos: usize,
}

/// The byte offset of the start of each line of a text.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LineIndex {
    starts: Box<[u32]>,
}

impl LineIndex {
    /// The text must be shorter than 4 GiB ([`TreeBuilder::new`] checks it).
    fn new(text: &str) -> Self {
        let mut starts = vec![0u32];
        starts.extend(
            text.bytes()
                .enumerate()
                .filter(|&(_, b)| b == b'\n')
                .map(|(i, _)| (i + 1) as u32),
        );
        LineIndex {
            starts: starts.into_boxed_slice(),
        }
    }

    /// The number of lines: the number of "\n" and 1.
    pub fn line_count(&self) -> usize {
        self.starts.len()
    }

    /// The byte offset of the start of a line (from 1), or `None` if the
    /// text has no such line.
    pub fn line_start(&self, line: usize) -> Option<usize> {
        let i = line.checked_sub(1)?;
        self.starts.get(i).map(|&s| s as usize)
    }

    /// The line and position of the character at a byte offset of `text`
    /// (the text of this index). The offset `text.len()` is the position
    /// after the last character. `None` if the offset is after the end or
    /// not at the start of a character.
    pub fn line_pos(&self, text: &str, byte: usize) -> Option<LinePos> {
        if !text.is_char_boundary(byte) {
            return None;
        }
        let line = self.starts.partition_point(|&s| s as usize <= byte);
        let start = self.starts[line - 1] as usize;
        let before = &text.as_bytes()[start..byte];
        // Count the first byte of each character (not 0b10xxxxxx).
        let chars = before.iter().filter(|&&b| b & 0xC0 != 0x80).count();
        Some(LinePos {
            line,
            pos: chars + 1,
        })
    }
}

/// An error of the [`TreeBuilder`] or of [`SyntaxTree::verify`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TreeError {
    /// The text or the node count does not fit in a `u32`.
    TooLarge,
    /// The kind has the wrong variant for the call: for example a segment
    /// kind for a leaf.
    WrongVariant {
        kind: SegmentKind,
        call: &'static str,
    },
    /// A node after the root.
    SecondRoot,
    /// `finish_node` with no open node.
    NoOpenNode,
    /// The leaf text is not the next text of the buffer (at this byte).
    NotNextText { at: usize },
    /// `finish` with this number of open nodes.
    OpenNodes(usize),
    /// `finish` with no node.
    NoNode,
    /// The leaves end at this byte, before the end of the text.
    TextLeft { at: usize },
    /// `verify` found a node that does not obey a rule of the tree.
    Invalid { node: usize, rule: &'static str },
}

impl fmt::Display for TreeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            TreeError::TooLarge => write!(f, "the text or the nodes do not fit in a u32"),
            TreeError::WrongVariant { kind, call } => {
                write!(f, "{call} cannot take the kind {kind:?}")
            }
            TreeError::SecondRoot => write!(f, "a node after the root"),
            TreeError::NoOpenNode => write!(f, "finish_node with no open node"),
            TreeError::NotNextText { at } => {
                write!(f, "the leaf text is not the next text at byte {at}")
            }
            TreeError::OpenNodes(n) => write!(f, "{n} nodes are open at the end"),
            TreeError::NoNode => write!(f, "the tree has no node"),
            TreeError::TextLeft { at } => {
                write!(f, "the leaves end at byte {at}, before the end of the text")
            }
            TreeError::Invalid { node, rule } => write!(f, "node {node}: {rule}"),
        }
    }
}

impl std::error::Error for TreeError {}

/// A flat, immutable, lossless syntax tree.
#[derive(Clone)]
pub struct SyntaxTree {
    text: Box<str>,
    nodes: Box<[Record]>,
    lines: LineIndex,
}

impl fmt::Debug for SyntaxTree {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SyntaxTree")
            .field("nodes", &self.nodes.len())
            .field("bytes", &self.text.len())
            .field("lines", &self.lines.line_count())
            .finish()
    }
}

impl SyntaxTree {
    /// The templated text.
    pub fn text(&self) -> &str {
        &self.text
    }

    /// The number of nodes (1 or more).
    pub fn node_count(&self) -> usize {
        self.nodes.len()
    }

    pub fn root(&self) -> NodeId {
        NodeId::ROOT
    }

    /// Each node id, in pre-order.
    pub fn nodes(&self) -> impl ExactSizeIterator<Item = NodeId> {
        (0..self.nodes.len() as u32).map(NodeId)
    }

    /// The record of a node. It panics for an id of another tree that is
    /// not in this tree.
    fn record(&self, id: NodeId) -> &Record {
        &self.nodes[id.index()]
    }

    pub fn kind(&self, id: NodeId) -> SegmentKind {
        self.record(id).kind
    }

    /// The type: the key of the node in the sqlfluff tree format.
    pub fn ty(&self, id: NodeId) -> SegmentType {
        self.kind(id).ty()
    }

    pub fn variant(&self, id: NodeId) -> Variant {
        self.kind(id).data().variant
    }

    /// The sqlfluff `is_type`: the type or a class type of the node is `ty`.
    pub fn is_type(&self, id: NodeId, ty: SegmentType) -> bool {
        self.kind(id).is_type(ty)
    }

    /// The class types of the node: a set, sorted by type id.
    pub fn class_types(&self, id: NodeId) -> &'static [SegmentType] {
        self.kind(id).data().class_types
    }

    /// True for an indent, a dedent, a placeholder, a template loop, and the
    /// end of the file.
    pub fn is_meta(&self, id: NodeId) -> bool {
        self.variant(id) == Variant::Meta
    }

    /// The templated byte range of the node. A meta node has an empty range.
    pub fn range(&self, id: NodeId) -> Range<usize> {
        let r = self.record(id);
        r.start as usize..r.end as usize
    }

    /// The templated text of the node: the texts of its leaves.
    pub fn raw(&self, id: NodeId) -> &str {
        &self.text[self.range(id)]
    }

    pub fn parent(&self, id: NodeId) -> Option<NodeId> {
        let p = self.record(id).parent;
        (p != NONE).then_some(NodeId(p))
    }

    /// The children of the node, in order.
    pub fn children(&self, id: NodeId) -> Children<'_> {
        Children {
            nodes: &self.nodes,
            next: id.0 + 1,
            end: self.record(id).next,
        }
    }

    /// The descendants of the node in pre-order, without the node.
    pub fn descendants(&self, id: NodeId) -> impl ExactSizeIterator<Item = NodeId> {
        (id.0 + 1..self.record(id).next).map(NodeId)
    }

    /// The descendants of the node that have this kind, in pre-order.
    pub fn descendants_of_kind(
        &self,
        id: NodeId,
        kind: SegmentKind,
    ) -> impl Iterator<Item = NodeId> + '_ {
        self.descendants(id).filter(move |&d| self.kind(d) == kind)
    }

    /// The descendants of the node that have this type as their type or a
    /// class type (`is_type`), in pre-order.
    pub fn descendants_of_type(
        &self,
        id: NodeId,
        ty: SegmentType,
    ) -> impl Iterator<Item = NodeId> + '_ {
        self.descendants(id).filter(move |&d| self.is_type(d, ty))
    }

    /// The raw segments of the node in order, as the sqlfluff
    /// `raw_segments`: each leaf and meta node in the node, and the node if
    /// it is a leaf or a meta node.
    pub fn raw_segments(&self, id: NodeId) -> impl Iterator<Item = NodeId> + '_ {
        (id.0..self.record(id).next)
            .map(NodeId)
            .filter(move |&d| matches!(self.variant(d), Variant::Raw | Variant::Meta))
    }

    pub fn line_index(&self) -> &LineIndex {
        &self.lines
    }

    /// The line and position of a templated byte offset (see
    /// [`LineIndex::line_pos`]).
    pub fn line_pos(&self, byte: usize) -> Option<LinePos> {
        self.lines.line_pos(&self.text, byte)
    }

    /// The line and position of the start of the node.
    pub fn start_pos(&self, id: NodeId) -> LinePos {
        self.line_pos(self.range(id).start)
            .expect("a node starts at a character")
    }

    /// The heap bytes of the tree: the text, the node records, and the line
    /// index.
    pub fn heap_bytes(&self) -> usize {
        self.text.len()
            + self.nodes.len() * std::mem::size_of::<Record>()
            + self.lines.starts.len() * std::mem::size_of::<u32>()
    }

    /// Check each rule of the tree again: one root; each parent and
    /// descendant range agrees with the pre-order; a leaf or a meta node has
    /// no child; the leaves, in order, cover the text with each byte one
    /// time, and each starts and ends at a character; a meta node has zero
    /// length at its place; a node with children spans its leaves.
    pub fn verify(&self) -> Result<(), TreeError> {
        let n = self.nodes.len();
        if n == 0 {
            return Err(TreeError::NoNode);
        }
        let invalid = |node: usize, rule: &'static str| Err(TreeError::Invalid { node, rule });
        let mut open: Vec<usize> = Vec::new();
        let mut cursor = 0usize;
        for (i, r) in self.nodes.iter().enumerate() {
            while let Some(&top) = open.last() {
                if self.nodes[top].next as usize > i {
                    break;
                }
                open.pop();
                if self.nodes[top].end as usize != cursor {
                    return invalid(top, "the node does not end at its last leaf");
                }
            }
            match open.last() {
                None if i > 0 => return invalid(i, "a node after the root"),
                None if r.parent != NONE => return invalid(i, "the root has a parent"),
                Some(&p) if r.parent as usize != p => {
                    return invalid(i, "the parent is not the open node");
                }
                _ => {}
            }
            if (r.next as usize) <= i || (r.next as usize) > n {
                return invalid(i, "the descendant range is not in the tree");
            }
            if let Some(&p) = open.last() {
                if r.next > self.nodes[p].next {
                    return invalid(i, "the descendants leave the parent");
                }
            }
            if r.start as usize != cursor {
                return invalid(i, "the node does not start at the next text");
            }
            let (start, end) = (r.start as usize, r.end as usize);
            match r.kind.data().variant {
                Variant::Raw | Variant::Meta | Variant::Empty => {
                    if r.next as usize != i + 1 {
                        return invalid(i, "a leaf or a meta node has children");
                    }
                    if r.kind.data().variant != Variant::Raw && end != start {
                        return invalid(i, "a meta node has a length");
                    }
                    if end < start
                        || end > self.text.len()
                        || !self.text.is_char_boundary(start)
                        || !self.text.is_char_boundary(end)
                    {
                        return invalid(i, "the leaf is not a range of characters");
                    }
                    cursor = end;
                }
                Variant::Segment | Variant::Unparsable => open.push(i),
            }
        }
        while let Some(top) = open.pop() {
            if self.nodes[top].end as usize != cursor {
                return invalid(top, "the node does not end at its last leaf");
            }
        }
        if self.nodes[0].next as usize != n {
            return invalid(0, "the root does not contain each node");
        }
        if cursor != self.text.len() {
            return Err(TreeError::TextLeft { at: cursor });
        }
        if self.lines != LineIndex::new(&self.text) {
            return invalid(0, "the line index is not that of the text");
        }
        Ok(())
    }
}

/// The children of a node (see [`SyntaxTree::children`]).
#[derive(Clone)]
pub struct Children<'a> {
    nodes: &'a [Record],
    next: u32,
    end: u32,
}

impl Iterator for Children<'_> {
    type Item = NodeId;

    fn next(&mut self) -> Option<NodeId> {
        if self.next >= self.end {
            return None;
        }
        let id = self.next;
        self.next = self.nodes[id as usize].next;
        Some(NodeId(id))
    }
}

/// Makes a [`SyntaxTree`] in pre-order: `start_node` and `finish_node` for a
/// node with children, `leaf` for a leaf, and `meta` for a meta node.
#[derive(Debug)]
pub struct TreeBuilder {
    text: String,
    nodes: Vec<Record>,
    open: Vec<u32>,
    cursor: usize,
}

impl TreeBuilder {
    /// A builder for the templated text. Its leaves must give the text.
    pub fn new(text: String) -> Result<Self, TreeError> {
        Self::with_capacity(text, 0)
    }

    /// A builder with space for this number of nodes.
    pub fn with_capacity(text: String, nodes: usize) -> Result<Self, TreeError> {
        if text.len() >= NONE as usize {
            return Err(TreeError::TooLarge);
        }
        Ok(TreeBuilder {
            text,
            nodes: Vec::with_capacity(nodes),
            open: Vec::new(),
            cursor: 0,
        })
    }

    /// The byte offset of the next leaf.
    pub fn cursor(&self) -> usize {
        self.cursor
    }

    fn check(kind: SegmentKind, call: &'static str, variants: &[Variant]) -> Result<(), TreeError> {
        if variants.contains(&kind.data().variant) {
            Ok(())
        } else {
            Err(TreeError::WrongVariant { kind, call })
        }
    }

    /// Add a node at the cursor and return its id.
    fn push(&mut self, kind: SegmentKind, len: usize) -> Result<NodeId, TreeError> {
        if self.open.is_empty() && !self.nodes.is_empty() {
            return Err(TreeError::SecondRoot);
        }
        let index = self.nodes.len();
        if index + 1 >= NONE as usize {
            return Err(TreeError::TooLarge);
        }
        let index = index as u32;
        self.nodes.push(Record {
            kind,
            start: self.cursor as u32,
            end: (self.cursor + len) as u32,
            parent: self.open.last().copied().unwrap_or(NONE),
            next: index + 1,
        });
        Ok(NodeId(index))
    }

    /// Open a node with children (a segment or an unparsable node). Its
    /// children follow until `finish_node`.
    pub fn start_node(&mut self, kind: SegmentKind) -> Result<NodeId, TreeError> {
        Self::check(kind, "start_node", &[Variant::Segment, Variant::Unparsable])?;
        let id = self.push(kind, 0)?;
        self.open.push(id.0);
        Ok(id)
    }

    /// Close the last open node.
    pub fn finish_node(&mut self) -> Result<NodeId, TreeError> {
        let id = self.open.pop().ok_or(TreeError::NoOpenNode)?;
        let next = self.nodes.len() as u32;
        let r = &mut self.nodes[id as usize];
        r.end = self.cursor as u32;
        r.next = next;
        Ok(NodeId(id))
    }

    /// Add a leaf. `raw` must be the next text of the buffer.
    pub fn leaf(&mut self, kind: SegmentKind, raw: &str) -> Result<NodeId, TreeError> {
        Self::check(kind, "leaf", &[Variant::Raw])?;
        if !self.text.as_bytes()[self.cursor..].starts_with(raw.as_bytes()) {
            return Err(TreeError::NotNextText { at: self.cursor });
        }
        let id = self.push(kind, raw.len())?;
        self.cursor += raw.len();
        Ok(id)
    }

    /// Add a meta node (or an empty node) with zero length at the cursor.
    pub fn meta(&mut self, kind: SegmentKind) -> Result<NodeId, TreeError> {
        Self::check(kind, "meta", &[Variant::Meta, Variant::Empty])?;
        self.push(kind, 0)
    }

    /// The tree. It fails if a node is open, if there is no node, or if the
    /// leaves do not give the full text.
    pub fn finish(self) -> Result<SyntaxTree, TreeError> {
        if !self.open.is_empty() {
            return Err(TreeError::OpenNodes(self.open.len()));
        }
        if self.nodes.is_empty() {
            return Err(TreeError::NoNode);
        }
        if self.cursor != self.text.len() {
            return Err(TreeError::TextLeft { at: self.cursor });
        }
        let lines = LineIndex::new(&self.text);
        Ok(SyntaxTree {
            text: self.text.into_boxed_str(),
            nodes: self.nodes.into_boxed_slice(),
            lines,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn kind(variant: Variant, ty: SegmentType) -> SegmentKind {
        *ty.kinds()
            .iter()
            .find(|k| k.data().variant == variant)
            .expect("a kind")
    }

    fn lines(text: &str) -> (LineIndex, Vec<Option<LinePos>>) {
        let index = LineIndex::new(text);
        let all = (0..=text.len() + 1)
            .map(|b| index.line_pos(text, b))
            .collect();
        (index, all)
    }

    fn at(line: usize, pos: usize) -> Option<LinePos> {
        Some(LinePos { line, pos })
    }

    #[test]
    fn line_pos_counts_lines_at_newlines_and_characters_in_a_line() {
        let (index, all) = lines("ab\ncd\n");
        assert_eq!(index.line_count(), 3);
        assert_eq!(
            all,
            [
                at(1, 1),
                at(1, 2),
                at(1, 3),
                at(2, 1),
                at(2, 2),
                at(2, 3),
                at(3, 1),
                None
            ]
        );
        assert_eq!(index.line_start(1), Some(0));
        assert_eq!(index.line_start(3), Some(6));
        assert_eq!(index.line_start(0), None);
        assert_eq!(index.line_start(4), None);
    }

    #[test]
    fn line_pos_counts_a_multi_byte_character_one_time() {
        // "é" has 2 bytes, "😀" has 4 bytes.
        let text = "é😀x\n€";
        let (_, all) = lines(text);
        assert_eq!(all[0], at(1, 1));
        assert_eq!(all[1], None, "inside é");
        assert_eq!(all[2], at(1, 2));
        assert_eq!(all[3..6], [None, None, None], "inside 😀");
        assert_eq!(all[6], at(1, 3));
        assert_eq!(all[7], at(1, 4), "the newline");
        assert_eq!(all[8], at(2, 1));
        assert_eq!(all[11], at(2, 2), "the end of the text");
    }

    #[test]
    fn line_pos_keeps_the_carriage_return_in_its_line() {
        let (index, all) = lines("a\r\nb\r\n\r\nc");
        assert_eq!(index.line_count(), 4);
        assert_eq!(all[1], at(1, 2), "\\r");
        assert_eq!(all[2], at(1, 3), "\\n");
        assert_eq!(all[3], at(2, 1));
        assert_eq!(all[6], at(3, 1));
        assert_eq!(all[7], at(3, 2));
        assert_eq!(all[8], at(4, 1));
        assert_eq!(all[9], at(4, 2));
    }

    #[test]
    fn an_empty_text_has_one_line() {
        let (index, all) = lines("");
        assert_eq!(index.line_count(), 1);
        assert_eq!(all, [at(1, 1), None]);
    }

    #[test]
    fn the_record_has_20_bytes() {
        assert_eq!(std::mem::size_of::<Record>(), 20);
    }

    #[test]
    fn the_builder_refuses_a_broken_tree() {
        let file = kind(Variant::Segment, SegmentType::FILE);
        let kw = kind(Variant::Raw, SegmentType::KEYWORD);
        let eof = kind(Variant::Meta, SegmentType::END_OF_FILE);

        let mut b = TreeBuilder::new("ab".into()).unwrap();
        assert_eq!(
            b.leaf(file, "a"),
            Err(TreeError::WrongVariant {
                kind: file,
                call: "leaf"
            })
        );
        assert!(matches!(
            b.start_node(kw),
            Err(TreeError::WrongVariant { .. })
        ));
        assert!(matches!(b.meta(kw), Err(TreeError::WrongVariant { .. })));
        assert_eq!(b.finish_node(), Err(TreeError::NoOpenNode));
        b.start_node(file).unwrap();
        assert_eq!(b.leaf(kw, "b"), Err(TreeError::NotNextText { at: 0 }));
        assert_eq!(b.leaf(kw, "abc"), Err(TreeError::NotNextText { at: 0 }));
        b.leaf(kw, "a").unwrap();
        assert_eq!(b.cursor(), 1);
        b.finish_node().unwrap();
        assert_eq!(b.meta(eof), Err(TreeError::SecondRoot));
        assert_eq!(b.finish().unwrap_err(), TreeError::TextLeft { at: 1 });

        let mut b = TreeBuilder::new("a".into()).unwrap();
        b.start_node(file).unwrap();
        b.leaf(kw, "a").unwrap();
        assert_eq!(b.finish().unwrap_err(), TreeError::OpenNodes(1));
        assert_eq!(
            TreeBuilder::new(String::new())
                .unwrap()
                .finish()
                .unwrap_err(),
            TreeError::NoNode
        );
    }

    #[test]
    fn verify_finds_a_broken_record() {
        let file = kind(Variant::Segment, SegmentType::FILE);
        let kw = kind(Variant::Raw, SegmentType::KEYWORD);
        let mut b = TreeBuilder::new("ab".into()).unwrap();
        b.start_node(file).unwrap();
        b.leaf(kw, "a").unwrap();
        b.leaf(kw, "b").unwrap();
        b.finish_node().unwrap();
        let tree = b.finish().unwrap();
        assert_eq!(tree.verify(), Ok(()));
        let broken = |change: fn(&mut [Record])| {
            let mut t = tree.clone();
            let mut nodes = t.nodes.to_vec();
            change(&mut nodes);
            t.nodes = nodes.into_boxed_slice();
            t.verify().unwrap_err()
        };
        let rule = |e: TreeError| match e {
            TreeError::Invalid { rule, .. } => rule,
            other => panic!("{other:?}"),
        };
        assert_eq!(
            rule(broken(|n| n[2].start = 0)),
            "the node does not start at the next text"
        );
        assert_eq!(
            rule(broken(|n| n[1].parent = NONE)),
            "the parent is not the open node"
        );
        assert_eq!(
            rule(broken(|n| n[0].end = 1)),
            "the node does not end at its last leaf"
        );
        assert_eq!(
            rule(broken(|n| n[1].next = 3)),
            "a leaf or a meta node has children"
        );
        assert_eq!(
            rule(broken(|n| {
                n[0].next = 2;
                n[0].end = 1;
            })),
            "a node after the root"
        );
        assert_eq!(
            broken(|n| {
                n[2].end = 1;
                n[0].end = 1;
            }),
            TreeError::TextLeft { at: 1 }
        );
    }
}
