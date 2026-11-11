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
//!
//! A tree can have a [`SourceMap`] (docs/interfaces/source-map.md, task C8).
//! Then each node also has a source byte range: a leaf and a meta node get
//! theirs from the builder (the lexer position of sqlfluff), and a node with
//! children spans the source ranges of its children, as the sqlfluff
//! `PositionMarker.from_child_markers`. A tree with no source map, or with
//! an identity map, has the templated range as the source range.

use std::fmt;
use std::ops::Range;
use std::sync::Arc;

use sqll_source::SourceMap;
pub use sqll_source::{LineIndex, LinePos};

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

    /// The id of an index that the caller knows to be in its tree.
    pub(crate) fn from_usize(index: usize) -> NodeId {
        NodeId(index as u32)
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
    /// A call with a source range on a builder with no source map.
    NoSourceMap,
    /// A leaf with no source range on a builder whose source map is not
    /// the identity.
    NoSourceRange,
    /// The source range is not a range of characters of the source text,
    /// or, for an identity map, not the templated range (at this templated
    /// byte).
    BadSourceRange { at: usize },
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
            TreeError::NoSourceMap => {
                write!(f, "a source range, but the builder has no source map")
            }
            TreeError::NoSourceRange => write!(f, "a leaf needs a source range"),
            TreeError::BadSourceRange { at } => {
                write!(f, "the source range at byte {at} is not valid")
            }
        }
    }
}

impl std::error::Error for TreeError {}

/// The source of a tree with a source map.
#[derive(Clone)]
struct Source {
    map: Arc<SourceMap>,
    /// The source byte range of each node, or `None` if the map is the
    /// identity.
    ranges: Option<Box<[(u32, u32)]>>,
}

/// A flat, immutable, lossless syntax tree.
#[derive(Clone)]
pub struct SyntaxTree {
    text: Box<str>,
    nodes: Box<[Record]>,
    lines: LineIndex,
    source: Option<Source>,
}

/// True if the range is in the text and starts and ends at a character.
fn char_range(text: &str, start: usize, end: usize) -> bool {
    start <= end && end <= text.len() && text.is_char_boundary(start) && text.is_char_boundary(end)
}

impl fmt::Debug for SyntaxTree {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SyntaxTree")
            .field("nodes", &self.nodes.len())
            .field("bytes", &self.text.len())
            .field("lines", &self.lines.line_count())
            .field("source_map", &self.source.as_ref().map(|s| &s.map))
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

    /// The source map, or `None` if the tree has none (the templated text is
    /// the source text).
    pub fn source_map(&self) -> Option<&Arc<SourceMap>> {
        self.source.as_ref().map(|s| &s.map)
    }

    /// The source text: the text before the templater.
    pub fn source_text(&self) -> &str {
        match &self.source {
            Some(s) => s.map.source_text(),
            None => &self.text,
        }
    }

    /// The source byte range of the node. It is the templated range if the
    /// tree has no source map or an identity map.
    pub fn source_range(&self, id: NodeId) -> Range<usize> {
        match self.source.as_ref().and_then(|s| s.ranges.as_ref()) {
            Some(ranges) => {
                let (start, end) = ranges[id.index()];
                start as usize..end as usize
            }
            None => self.range(id),
        }
    }

    /// The source line and position of the start of the node.
    pub fn source_pos(&self, id: NodeId) -> LinePos {
        match &self.source {
            Some(s) => s
                .map
                .source_line_pos(self.source_range(id).start)
                .expect("a source range starts at a character"),
            None => self.start_pos(id),
        }
    }

    /// True if the source range of the node has only literal source text
    /// (`SourceMap::is_source_literal`, the sqlfluff `is_literal` of a
    /// position marker): a fix can change the node.
    pub fn is_literal(&self, id: NodeId) -> bool {
        match &self.source {
            Some(s) if s.ranges.is_some() => s
                .map
                .is_source_literal(self.source_range(id))
                .unwrap_or(false),
            _ => true,
        }
    }

    /// The heap bytes of the tree: the text, the node records, the line
    /// index, and the source ranges. The source map is shared and is not
    /// part of it.
    pub fn heap_bytes(&self) -> usize {
        let ranges = self
            .source
            .as_ref()
            .and_then(|s| s.ranges.as_ref())
            .map_or(0, |r| r.len() * std::mem::size_of::<(u32, u32)>());
        self.text.len()
            + self.nodes.len() * std::mem::size_of::<Record>()
            + self.lines.line_count() * std::mem::size_of::<u32>()
            + ranges
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
        if Some(&self.lines) != LineIndex::new(&self.text).as_ref() {
            return invalid(0, "the line index is not that of the text");
        }
        self.verify_source()
    }

    /// The source rules: the text is the templated text of the map; with a
    /// map that is not the identity, each node has a source range of
    /// characters, and a node with children spans the source ranges of its
    /// children (an empty one at the source end of the leaf or meta node
    /// before it, if it has no child).
    fn verify_source(&self) -> Result<(), TreeError> {
        let invalid = |node: usize, rule: &'static str| Err(TreeError::Invalid { node, rule });
        let Some(source) = &self.source else {
            return Ok(());
        };
        if source.map.templated_text() != &*self.text {
            return invalid(0, "the text is not the templated text of the source map");
        }
        let Some(ranges) = &source.ranges else {
            return Ok(());
        };
        if ranges.len() != self.nodes.len() {
            return invalid(0, "the tree does not have one source range for each node");
        }
        let text = source.map.source_text();
        let mut source_cursor = 0u32;
        for (i, &(start, end)) in ranges.iter().enumerate() {
            if !char_range(text, start as usize, end as usize) {
                return invalid(i, "the source range is not a range of characters");
            }
            if matches!(
                self.nodes[i].kind.data().variant,
                Variant::Segment | Variant::Unparsable
            ) {
                let want = span(&self.nodes, ranges, i).unwrap_or((source_cursor, source_cursor));
                if (start, end) != want {
                    return invalid(i, "the source range does not span the children");
                }
            } else {
                source_cursor = end;
            }
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

/// The smallest start and the largest end of the source ranges of the
/// children of node `i`, or `None` if it has no child.
fn span(nodes: &[Record], ranges: &[(u32, u32)], i: usize) -> Option<(u32, u32)> {
    let mut child = i + 1;
    let mut out: Option<(u32, u32)> = None;
    while child < nodes[i].next as usize {
        let (s, e) = ranges[child];
        out = Some(out.map_or((s, e), |(a, b)| (a.min(s), b.max(e))));
        child = nodes[child].next as usize;
    }
    out
}

/// The source part of a builder with a source map.
#[derive(Debug)]
struct BuildSource {
    map: Arc<SourceMap>,
    /// The source range of each node, if the map is not the identity.
    ranges: Option<Vec<(u32, u32)>>,
    /// The source end of the last leaf or meta node.
    cursor: u32,
}

/// Makes a [`SyntaxTree`] in pre-order: `start_node` and `finish_node` for a
/// node with children, `leaf` for a leaf, and `meta` for a meta node. With a
/// source map ([`TreeBuilder::with_source`]), `leaf_at` and `meta_at` also
/// take the source range of the node.
#[derive(Debug)]
pub struct TreeBuilder {
    text: String,
    nodes: Vec<Record>,
    open: Vec<u32>,
    cursor: usize,
    source: Option<BuildSource>,
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
            source: None,
        })
    }

    /// A builder for the templated text of a source map, with space for this
    /// number of nodes. If the map is not the identity, each leaf needs its
    /// source range (`leaf_at`).
    pub fn with_source(map: Arc<SourceMap>, nodes: usize) -> Result<Self, TreeError> {
        let mut b = Self::with_capacity(map.templated_text().to_string(), nodes)?;
        let ranges = (!map.is_identity()).then(|| Vec::with_capacity(nodes));
        b.source = Some(BuildSource {
            map,
            ranges,
            cursor: 0,
        });
        Ok(b)
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

    /// The source range of a leaf or a meta node of `len` templated bytes
    /// at the cursor: `source`, or, for `None`, the templated range (no map
    /// or an identity map) or an empty range at the source cursor (a meta
    /// node). Return `None` if the builder keeps no source range.
    fn source_of(
        &self,
        len: usize,
        source: Option<Range<usize>>,
        leaf: bool,
    ) -> Result<Option<(u32, u32)>, TreeError> {
        let templated = self.cursor..self.cursor + len;
        let bad = TreeError::BadSourceRange { at: self.cursor };
        let Some(s) = &self.source else {
            return match source {
                Some(_) => Err(TreeError::NoSourceMap),
                None => Ok(None),
            };
        };
        if s.ranges.is_none() {
            return match source {
                Some(r) if r != templated => Err(bad),
                _ => Ok(None),
            };
        }
        let r = match source {
            Some(r) => r,
            None if leaf => return Err(TreeError::NoSourceRange),
            None => s.cursor as usize..s.cursor as usize,
        };
        if !char_range(s.map.source_text(), r.start, r.end) {
            return Err(bad);
        }
        Ok(Some((r.start as u32, r.end as u32)))
    }

    /// Add a node at the cursor and return its id. `source` is its source
    /// range, if the builder keeps them.
    fn push(
        &mut self,
        kind: SegmentKind,
        len: usize,
        source: Option<(u32, u32)>,
    ) -> Result<NodeId, TreeError> {
        if self.open.is_empty() && !self.nodes.is_empty() {
            return Err(TreeError::SecondRoot);
        }
        let index = self.nodes.len();
        if index + 1 >= NONE as usize {
            return Err(TreeError::TooLarge);
        }
        if let Some(BuildSource {
            ranges: Some(ranges),
            cursor,
            ..
        }) = &mut self.source
        {
            // A node with children gets its range in `finish_node`.
            ranges.push(source.unwrap_or((NONE, 0)));
            if let Some((_, end)) = source {
                *cursor = end;
            }
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
        let id = self.push(kind, 0, None)?;
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
        if let Some(BuildSource {
            ranges: Some(ranges),
            cursor,
            ..
        }) = &mut self.source
        {
            let i = id as usize;
            ranges[i] = span(&self.nodes, ranges, i).unwrap_or((*cursor, *cursor));
        }
        Ok(NodeId(id))
    }

    /// Add a leaf. `raw` must be the next text of the buffer. A builder with
    /// a source map that is not the identity refuses it: use `leaf_at`.
    pub fn leaf(&mut self, kind: SegmentKind, raw: &str) -> Result<NodeId, TreeError> {
        self.add_leaf(kind, raw, None)
    }

    /// Add a leaf with its source byte range. For an identity map, the
    /// source range must be the templated range.
    pub fn leaf_at(
        &mut self,
        kind: SegmentKind,
        raw: &str,
        source: Range<usize>,
    ) -> Result<NodeId, TreeError> {
        self.add_leaf(kind, raw, Some(source))
    }

    fn add_leaf(
        &mut self,
        kind: SegmentKind,
        raw: &str,
        source: Option<Range<usize>>,
    ) -> Result<NodeId, TreeError> {
        Self::check(kind, "leaf", &[Variant::Raw])?;
        if !self.text.as_bytes()[self.cursor..].starts_with(raw.as_bytes()) {
            return Err(TreeError::NotNextText { at: self.cursor });
        }
        let source = self.source_of(raw.len(), source, true)?;
        let id = self.push(kind, raw.len(), source)?;
        self.cursor += raw.len();
        Ok(id)
    }

    /// Add a meta node (or an empty node) with zero length at the cursor.
    /// With a source map that is not the identity, its source range is
    /// empty, at the source end of the leaf or meta node before it.
    pub fn meta(&mut self, kind: SegmentKind) -> Result<NodeId, TreeError> {
        self.add_meta(kind, None)
    }

    /// Add a meta node with its source byte range (for example the source
    /// text of a template tag for a placeholder).
    pub fn meta_at(
        &mut self,
        kind: SegmentKind,
        source: Range<usize>,
    ) -> Result<NodeId, TreeError> {
        self.add_meta(kind, Some(source))
    }

    fn add_meta(
        &mut self,
        kind: SegmentKind,
        source: Option<Range<usize>>,
    ) -> Result<NodeId, TreeError> {
        Self::check(kind, "meta", &[Variant::Meta, Variant::Empty])?;
        let source = self.source_of(0, source, false)?;
        self.push(kind, 0, source)
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
        let lines = LineIndex::new(&self.text).ok_or(TreeError::TooLarge)?;
        let source = self.source.map(|s| Source {
            map: s.map,
            ranges: s.ranges.map(Vec::into_boxed_slice),
        });
        Ok(SyntaxTree {
            text: self.text.into_boxed_str(),
            nodes: self.nodes.into_boxed_slice(),
            lines,
            source,
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

    /// "é{{x}}ü" to "éVALü" (bytes: source 0..2, 2..7, 7..9; templated
    /// 0..2, 2..5, 5..7).
    fn small_map() -> Arc<SourceMap> {
        use sqll_source::{RawFileSlice, Slice, TemplatedFile, TemplatedFileSlice};
        let slice = |ty: &str, o: Range<usize>, t: Range<usize>| {
            TemplatedFileSlice::new(ty.into(), Slice::from(o), Slice::from(t))
        };
        let raw =
            |text: &str, ty: &str, at| RawFileSlice::new(text.into(), ty.into(), at, None, None);
        let file = TemplatedFile::new(
            "é{{x}}ü".into(),
            "small.sql".into(),
            Some("éVALü".into()),
            Some(vec![
                slice("literal", 0..1, 0..1),
                slice("templated", 1..6, 1..4),
                slice("literal", 6..7, 4..5),
            ]),
            Some(vec![
                raw("é", "literal", 0),
                raw("{{x}}", "templated", 1),
                raw("ü", "literal", 6),
            ]),
        );
        Arc::new(SourceMap::new(Arc::new(file)).unwrap())
    }

    #[test]
    fn a_tree_with_a_source_map_has_source_ranges() {
        let file = kind(Variant::Segment, SegmentType::FILE);
        let stmt = kind(Variant::Segment, SegmentType::STATEMENT);
        let kw = kind(Variant::Raw, SegmentType::KEYWORD);
        let indent = kind(Variant::Meta, SegmentType::INDENT);
        let placeholder = kind(Variant::Meta, SegmentType::PLACEHOLDER);
        let mut b = TreeBuilder::with_source(small_map(), 0).unwrap();
        b.start_node(file).unwrap();
        assert_eq!(b.leaf(kw, "é"), Err(TreeError::NoSourceRange));
        let e = b.leaf_at(kw, "é", 0..2).unwrap();
        let ph = b.meta_at(placeholder, 2..7).unwrap();
        let st = b.start_node(stmt).unwrap();
        let ind = b.meta(indent).unwrap();
        let val = b.leaf_at(kw, "VAL", 2..7).unwrap();
        let empty = b.start_node(stmt).unwrap();
        b.finish_node().unwrap();
        assert_eq!(
            b.leaf_at(kw, "ü", 8..9),
            Err(TreeError::BadSourceRange { at: 5 })
        );
        assert_eq!(
            b.leaf_at(kw, "ü", 7..10),
            Err(TreeError::BadSourceRange { at: 5 })
        );
        let u = b.leaf_at(kw, "ü", 7..9).unwrap();
        b.finish_node().unwrap();
        b.finish_node().unwrap();
        let tree = b.finish().unwrap();
        assert_eq!(tree.verify(), Ok(()));
        assert_eq!(tree.source_text(), "é{{x}}ü");
        assert_eq!(tree.text(), "éVALü");
        let ranges: Vec<Range<usize>> = [NodeId::ROOT, e, ph, st, ind, val, empty, u]
            .iter()
            .map(|&n| tree.source_range(n))
            .collect();
        assert_eq!(ranges, [0..9, 0..2, 2..7, 2..9, 7..7, 2..7, 7..7, 7..9]);
        assert_eq!(tree.range(val), 2..5);
        assert_eq!(tree.source_pos(u), LinePos { line: 1, pos: 7 });
        assert_eq!(tree.start_pos(u), LinePos { line: 1, pos: 5 });
        let literal: Vec<bool> = [NodeId::ROOT, e, ph, val, u]
            .iter()
            .map(|&n| tree.is_literal(n))
            .collect();
        assert_eq!(literal, [false, true, false, false, true]);
        assert!(tree.source_map().is_some());
        assert_eq!(tree.heap_bytes(), 7 + 8 * 20 + 4 + 8 * 8);

        // A broken source range.
        let mut t = tree.clone();
        let source = t.source.as_mut().unwrap();
        let mut ranges = source.ranges.as_ref().unwrap().to_vec();
        ranges[6] = (2, 7);
        source.ranges = Some(ranges.clone().into_boxed_slice());
        assert_eq!(
            t.verify(),
            Err(TreeError::Invalid {
                node: 6,
                rule: "the source range does not span the children"
            })
        );
        ranges[6] = (7, 7);
        ranges[1] = (0, 1);
        t.source.as_mut().unwrap().ranges = Some(ranges.into_boxed_slice());
        assert_eq!(
            t.verify(),
            Err(TreeError::Invalid {
                node: 1,
                rule: "the source range is not a range of characters"
            })
        );
    }

    #[test]
    fn an_identity_map_or_no_map_gives_the_templated_ranges() {
        let file = kind(Variant::Segment, SegmentType::FILE);
        let kw = kind(Variant::Raw, SegmentType::KEYWORD);
        let map = Arc::new(SourceMap::identity("a é".into(), "a.sql".into()).unwrap());
        let mut b = TreeBuilder::with_source(map, 0).unwrap();
        b.start_node(file).unwrap();
        b.leaf(kw, "a").unwrap();
        assert_eq!(
            b.leaf_at(kw, " ", 1..3),
            Err(TreeError::BadSourceRange { at: 1 })
        );
        b.leaf_at(kw, " ", 1..2).unwrap();
        let e = b.leaf(kw, "é").unwrap();
        b.finish_node().unwrap();
        let tree = b.finish().unwrap();
        assert_eq!(tree.verify(), Ok(()));
        assert_eq!(tree.source_range(e), 2..4);
        assert_eq!(tree.source_pos(e), LinePos { line: 1, pos: 3 });
        assert!(tree.is_literal(e));
        assert_eq!(tree.heap_bytes(), 4 + 4 * 20 + 4);

        let mut b = TreeBuilder::new("a".into()).unwrap();
        b.start_node(file).unwrap();
        assert_eq!(b.leaf_at(kw, "a", 0..1), Err(TreeError::NoSourceMap));
        b.leaf(kw, "a").unwrap();
        b.finish_node().unwrap();
        let tree = b.finish().unwrap();
        assert!(tree.source_map().is_none());
        assert_eq!(tree.source_text(), "a");
        assert_eq!(tree.source_range(NodeId::ROOT), 0..1);
        assert!(tree.is_literal(NodeId::ROOT));
    }
}
