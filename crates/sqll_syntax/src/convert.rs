//! The conversion from the parser tree (`sqll_parser` `Node`) to the
//! [`SyntaxTree`] (docs/interfaces/tree.md, S3b task C7).
//!
//! Each `Node` gives one tree node, in pre-order. The kind of a node is the
//! kind of its static data ([`kind_of`]). The tree keeps no text of its own
//! for a node: the leaves are ranges of the templated text, and the builder
//! refuses a leaf that is not the next text. The data that is not in the
//! tree goes to [`Converted`]: the expected text of an unparsable node and
//! the source text of a template placeholder.
//!
//! The lookup of a kind (`SegmentKind::find`) compares many strings. One
//! conversion keeps the kind of each distinct static data that it found
//! ([`KindCache`]): most nodes of a file repeat the static data of an
//! earlier node.

use std::fmt;
use std::hash::{BuildHasher, Hash, Hasher};

use hashbrown::{DefaultHashBuilder, HashTable};
use sqll_parser::parser::{MetaType, Node};
use sqll_tree::{KindKey, Meta, NodeId, SegmentKind, SyntaxTree, TreeBuilder, TreeError, Variant};

/// The result of [`from_node`].
#[derive(Debug)]
pub struct Converted {
    pub tree: SyntaxTree,
    /// The expected text of each `Node::Unparsable`, in pre-order.
    pub expected: Vec<(NodeId, String)>,
    /// The source text of each template placeholder, in pre-order.
    pub placeholders: Vec<(NodeId, String)>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ConvertError {
    /// No kind has the static data of the node at this pre-order index.
    NoKind { node: usize, data: String },
    /// The tree builder refused the node at this pre-order index.
    Tree { node: usize, error: TreeError },
}

impl fmt::Display for ConvertError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ConvertError::NoKind { node, data } => write!(f, "node {node} has no kind: {data}"),
            ConvertError::Tree { node, error } => write!(f, "node {node}: {error}"),
        }
    }
}

impl std::error::Error for ConvertError {}

/// The kind of the static data of a node, or `None` if no kind has it.
pub fn kind_of(node: &Node) -> Option<SegmentKind> {
    let none: &[String] = &[];
    let base = KindKey {
        variant: Variant::Empty,
        class: "",
        ty: "",
        instance_types: none,
        trim_chars: None,
        quoted_value: None,
        escape_replacements: None,
        meta: None,
        class_types: none,
    };
    let quoted;
    let key = match node {
        Node::Raw {
            segment_class,
            segment_type,
            instance_types,
            class_types,
            segment_kwargs: k,
            ..
        } => {
            quoted = k
                .quoted_value
                .as_ref()
                .map(|(a, b)| (a.as_str(), b.as_str()));
            KindKey {
                variant: Variant::Raw,
                class: segment_class,
                ty: segment_type,
                instance_types,
                trim_chars: k.trim_chars.as_deref().map(Vec::as_slice),
                quoted_value: quoted,
                escape_replacements: k.escape_replacements.as_deref().map(Vec::as_slice),
                class_types,
                ..base
            }
        }
        Node::Segment {
            segment_class,
            segment_type,
            class_types,
            ..
        } => KindKey {
            variant: Variant::Segment,
            class: segment_class,
            ty: segment_type.as_deref()?,
            class_types,
            ..base
        },
        Node::Meta { meta_type, .. } => {
            let (ty, meta) = match meta_type {
                MetaType::Indent { is_implicit } => (
                    "indent",
                    Meta::Indent {
                        implicit: *is_implicit,
                    },
                ),
                MetaType::Dedent { is_implicit } => (
                    "dedent",
                    Meta::Dedent {
                        implicit: *is_implicit,
                    },
                ),
                MetaType::Template { block_type, .. } => {
                    ("placeholder", Meta::Template { block_type })
                }
                MetaType::TemplateLoop => ("template_loop", Meta::TemplateLoop),
                MetaType::EndOfFile => ("end_of_file", Meta::EndOfFile),
            };
            KindKey {
                variant: Variant::Meta,
                ty,
                meta: Some(meta),
                ..base
            }
        }
        Node::Unparsable { .. } => KindKey {
            variant: Variant::Unparsable,
            ty: "unparsable",
            ..base
        },
        Node::Empty => KindKey {
            ty: "empty",
            ..base
        },
    };
    SegmentKind::find(&key)
}

/// A short text of the static data of a node, for an error.
fn describe(node: &Node) -> String {
    match node {
        Node::Raw {
            segment_class,
            segment_type,
            instance_types,
            class_types,
            ..
        } => format!("raw {segment_class} {segment_type} {instance_types:?} {class_types:?}"),
        Node::Segment {
            segment_class,
            segment_type,
            class_types,
            ..
        } => format!("segment {segment_class} {segment_type:?} {class_types:?}"),
        Node::Meta { meta_type, .. } => format!("meta {meta_type:?}"),
        Node::Unparsable { .. } => "unparsable".to_string(),
        Node::Empty => "empty".to_string(),
    }
}

/// A part of the static data of a node, for a hash: the variant, the class,
/// the type, and the number of types. Nodes with the same part can have
/// other static data; `same_static` compares all of it.
struct StaticData<'a>(&'a Node);

impl Hash for StaticData<'_> {
    fn hash<H: Hasher>(&self, h: &mut H) {
        match self.0 {
            Node::Raw {
                segment_class,
                segment_type,
                instance_types,
                class_types,
                ..
            } => {
                0u8.hash(h);
                segment_class.hash(h);
                segment_type.hash(h);
                h.write_usize(instance_types.len() << 16 | class_types.len());
            }
            Node::Segment {
                segment_class,
                segment_type,
                class_types,
                ..
            } => {
                1u8.hash(h);
                segment_class.hash(h);
                segment_type.hash(h);
                h.write_usize(class_types.len());
            }
            Node::Meta { meta_type, .. } => {
                2u8.hash(h);
                match meta_type {
                    MetaType::Indent { is_implicit } => (0u8, is_implicit).hash(h),
                    MetaType::Dedent { is_implicit } => (1u8, is_implicit).hash(h),
                    MetaType::Template { block_type, .. } => (2u8, block_type).hash(h),
                    MetaType::TemplateLoop => 3u8.hash(h),
                    MetaType::EndOfFile => 4u8.hash(h),
                }
            }
            Node::Unparsable { .. } => 3u8.hash(h),
            Node::Empty => 4u8.hash(h),
        }
    }
}

/// True if the two nodes have the same static data (`StaticData`).
fn same_static(a: &Node, b: &Node) -> bool {
    match (a, b) {
        (
            Node::Raw {
                segment_class: c1,
                segment_type: t1,
                instance_types: i1,
                class_types: ct1,
                segment_kwargs: k1,
                ..
            },
            Node::Raw {
                segment_class: c2,
                segment_type: t2,
                instance_types: i2,
                class_types: ct2,
                segment_kwargs: k2,
                ..
            },
        ) => c1 == c2 && t1 == t2 && i1 == i2 && ct1 == ct2 && k1 == k2,
        (
            Node::Segment {
                segment_class: c1,
                segment_type: t1,
                class_types: ct1,
                ..
            },
            Node::Segment {
                segment_class: c2,
                segment_type: t2,
                class_types: ct2,
                ..
            },
        ) => c1 == c2 && t1 == t2 && ct1 == ct2,
        (Node::Meta { meta_type: m1, .. }, Node::Meta { meta_type: m2, .. }) => match (m1, m2) {
            (
                MetaType::Template { block_type: b1, .. },
                MetaType::Template { block_type: b2, .. },
            ) => b1 == b2,
            _ => m1 == m2,
        },
        (Node::Unparsable { .. }, Node::Unparsable { .. }) | (Node::Empty, Node::Empty) => true,
        _ => false,
    }
}

/// A copy of the static data of a node, with no text, position, or child.
fn static_copy(node: &Node) -> Node {
    match node {
        Node::Raw {
            segment_class,
            segment_type,
            instance_types,
            class_types,
            segment_kwargs,
            ..
        } => Node::Raw {
            segment_class: segment_class.clone(),
            segment_type: segment_type.clone(),
            raw: String::new(),
            pos_marker: None,
            instance_types: instance_types.clone(),
            class_types: class_types.clone(),
            segment_kwargs: segment_kwargs.clone(),
        },
        Node::Segment {
            segment_class,
            segment_type,
            class_types,
            ..
        } => Node::Segment {
            segment_class: segment_class.clone(),
            segment_type: segment_type.clone(),
            pos_marker: None,
            class_types: class_types.clone(),
            children: Vec::new(),
        },
        Node::Meta { meta_type, .. } => Node::Meta {
            meta_type: match meta_type {
                MetaType::Template { block_type, .. } => MetaType::Template {
                    source_str: String::new(),
                    block_type: block_type.clone(),
                },
                other => other.clone(),
            },
            pos_marker: None,
        },
        Node::Unparsable { .. } => Node::Unparsable {
            expected: String::new(),
            pos_marker: None,
            children: Vec::new(),
        },
        Node::Empty => Node::Empty,
    }
}

/// The kinds that one conversion found, by the static data of the node. A
/// hit needs the same static data (`same_static`), so the cache gives the
/// kind that `kind_of` gives.
#[derive(Default)]
struct KindCache {
    hasher: DefaultHashBuilder,
    table: HashTable<(u64, Node, SegmentKind)>,
}

impl KindCache {
    fn kind(&mut self, node: &Node) -> Option<SegmentKind> {
        let hash = self.hasher.hash_one(StaticData(node));
        let hit = self
            .table
            .find(hash, |(h, n, _)| *h == hash && same_static(n, node));
        if let Some(&(_, _, kind)) = hit {
            return Some(kind);
        }
        let kind = kind_of(node)?;
        self.table
            .insert_unique(hash, (hash, static_copy(node), kind), |(h, _, _)| *h);
        Some(kind)
    }
}

struct Walk<'n> {
    builder: TreeBuilder,
    kinds: KindCache,
    expected: Vec<(NodeId, String)>,
    placeholders: Vec<(NodeId, String)>,
    /// The pre-order index of the next node.
    index: usize,
    /// The children that are not added yet, for each open node.
    stack: Vec<std::slice::Iter<'n, Node>>,
}

impl<'n> Walk<'n> {
    fn add(&mut self, node: &'n Node) -> Result<(), ConvertError> {
        let index = self.index;
        self.index += 1;
        let kind = self.kinds.kind(node).ok_or_else(|| ConvertError::NoKind {
            node: index,
            data: describe(node),
        })?;
        let tree = |error| ConvertError::Tree { node: index, error };
        match node {
            Node::Raw { raw, .. } => {
                self.builder.leaf(kind, raw).map_err(tree)?;
            }
            Node::Segment { children, .. } => {
                self.builder.start_node(kind).map_err(tree)?;
                self.stack.push(children.iter());
            }
            Node::Unparsable {
                expected, children, ..
            } => {
                let id = self.builder.start_node(kind).map_err(tree)?;
                self.expected.push((id, expected.clone()));
                self.stack.push(children.iter());
            }
            Node::Meta { meta_type, .. } => {
                let id = self.builder.meta(kind).map_err(tree)?;
                if let MetaType::Template { source_str, .. } = meta_type {
                    self.placeholders.push((id, source_str.clone()));
                }
            }
            Node::Empty => {
                self.builder.meta(kind).map_err(tree)?;
            }
        }
        Ok(())
    }
}

/// Convert a parser tree. `text` is the templated text; the leaves of the
/// tree must give it, each byte one time, in order.
pub fn from_node(root: &Node, text: String) -> Result<Converted, ConvertError> {
    let builder = TreeBuilder::new(text).map_err(|error| ConvertError::Tree { node: 0, error })?;
    let mut walk = Walk {
        builder,
        kinds: KindCache::default(),
        expected: Vec::new(),
        placeholders: Vec::new(),
        index: 0,
        stack: Vec::new(),
    };
    walk.add(root)?;
    while let Some(children) = walk.stack.last_mut() {
        match children.next() {
            Some(child) => walk.add(child)?,
            None => {
                walk.stack.pop();
                walk.builder
                    .finish_node()
                    .map_err(|error| ConvertError::Tree {
                        node: walk.index,
                        error,
                    })?;
            }
        }
    }
    let tree = walk.builder.finish().map_err(|error| ConvertError::Tree {
        node: walk.index,
        error,
    })?;
    Ok(Converted {
        tree,
        expected: walk.expected,
        placeholders: walk.placeholders,
    })
}
