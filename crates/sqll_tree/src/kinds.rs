//! Segment types and segment kinds (docs/interfaces/segment-kinds.md).
//!
//! build.rs makes both from the frozen dialect tables and the lexers of
//! sqll_dialects (build/kinds.rs):
//!
//! - [`SegmentType`]: one value for each type name of the tables and the
//!   lexers, for example `keyword` or `select_statement`. The values are in
//!   the byte order of the names.
//! - [`SegmentKind`]: one value for each distinct static data of a parser
//!   node ([`KindData`]). One type name can have many kinds. The values are
//!   in the order of the data.
//!
//! The values are stable while the tables do not change (generated.json).

use std::cmp::Ordering;
use std::fmt;

/// A type name of the tables, as a `u16`. Each type name has a constant,
/// for example [`SegmentType::KEYWORD`].
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SegmentType(u16);

/// One distinct static data of a parser node, as a `u16`.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SegmentKind(u16);

/// The variant of a parser node (`sqll_parser` `Node`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Variant {
    /// A leaf with text.
    Raw,
    /// A node with children.
    Segment,
    /// An indent, a dedent, a template placeholder, a template loop, or the
    /// end of the file.
    Meta,
    /// An unparsable node (the parser makes a segment of type `unparsable`).
    Unparsable,
    /// An empty node.
    Empty,
}

/// The static data of a meta node.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Meta<'a> {
    Indent {
        implicit: bool,
    },
    Dedent {
        implicit: bool,
    },
    /// A template placeholder. The block type is the slice type of the
    /// templater.
    Template {
        block_type: &'a str,
    },
    TemplateLoop,
    EndOfFile,
}

impl Meta<'_> {
    /// The type of a meta node.
    pub fn type_name(&self) -> &'static str {
        match self {
            Meta::Indent { .. } => "indent",
            Meta::Dedent { .. } => "dedent",
            Meta::Template { .. } => "placeholder",
            Meta::TemplateLoop => "template_loop",
            Meta::EndOfFile => "end_of_file",
        }
    }

    /// The class types of a meta node: those of its sqlfluff class
    /// (`MetaSegment` is a `RawSegment`; `Dedent` is an `Indent`). The build
    /// gives each meta kind this set (build/kinds.rs, `Kind::meta`).
    pub fn class_types(&self) -> &'static [&'static str] {
        match self {
            Meta::Indent { .. } => &["base", "indent", "meta", "raw"],
            Meta::Dedent { .. } => &["base", "dedent", "indent", "meta", "raw"],
            Meta::Template { .. } => &["base", "meta", "placeholder", "raw"],
            Meta::TemplateLoop => &["base", "meta", "raw", "template_loop"],
            Meta::EndOfFile => &["base", "end_of_file", "meta", "raw"],
        }
    }
}

/// The static data of a kind.
#[derive(Debug, PartialEq, Eq)]
pub struct KindData {
    pub variant: Variant,
    /// The class name, for example `KeywordSegment`. Empty for a meta node.
    pub class: &'static str,
    /// The type: the key of the node in the sqlfluff tree format.
    pub ty: SegmentType,
    /// The instance types of a leaf, in order.
    pub instance_types: &'static [SegmentType],
    pub trim_chars: Option<&'static [&'static str]>,
    /// The quote pattern and its group.
    pub quoted_value: Option<(&'static str, &'static str)>,
    /// The escape patterns and their replacements.
    pub escape_replacements: Option<&'static [(&'static str, &'static str)]>,
    pub meta: Option<Meta<'static>>,
    /// The class types: a set, in the order of the type values.
    pub class_types: &'static [SegmentType],
}

/// The static data of a node, borrowed from the node, to find its kind
/// ([`SegmentKind::find`]). `class_types` can be in any order.
#[derive(Debug, Clone, Copy)]
pub struct KindKey<'a, S: AsRef<str>> {
    pub variant: Variant,
    pub class: &'a str,
    pub ty: &'a str,
    pub instance_types: &'a [S],
    pub trim_chars: Option<&'a [S]>,
    pub quoted_value: Option<(&'a str, &'a str)>,
    pub escape_replacements: Option<&'a [(S, S)]>,
    pub meta: Option<Meta<'a>>,
    pub class_types: &'a [S],
}

include!(concat!(env!("OUT_DIR"), "/kinds.rs"));

impl SegmentType {
    /// The number of type names.
    pub const COUNT: usize = TYPE_COUNT;

    /// The type name, for example `"keyword"`.
    pub fn name(self) -> &'static str {
        TYPE_NAMES[self.0 as usize]
    }

    /// The type of a type name, or `None` if the tables do not have it.
    pub fn from_name(name: &str) -> Option<Self> {
        TYPE_NAMES
            .binary_search(&name)
            .ok()
            .map(|i| SegmentType(i as u16))
    }

    pub fn index(self) -> u16 {
        self.0
    }

    pub fn from_index(index: u16) -> Option<Self> {
        ((index as usize) < TYPE_COUNT).then_some(SegmentType(index))
    }

    /// Each type, in order.
    pub fn all() -> impl Iterator<Item = SegmentType> {
        (0..TYPE_COUNT as u16).map(SegmentType)
    }

    /// The kinds that have this type ([`KindData::ty`]), in order.
    pub fn kinds(self) -> &'static [SegmentKind] {
        let i = self.0 as usize;
        let start = KINDS_OF_TYPE_START[i] as usize;
        let end = KINDS_OF_TYPE_START[i + 1] as usize;
        &KINDS_OF_TYPE[start..end]
    }
}

impl fmt::Debug for SegmentType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "SegmentType({:?})", self.name())
    }
}

impl SegmentKind {
    /// The number of kinds.
    pub const COUNT: usize = KIND_COUNT;

    pub fn data(self) -> &'static KindData {
        &KINDS[self.0 as usize]
    }

    pub fn ty(self) -> SegmentType {
        self.data().ty
    }

    /// The type name of the kind: the key of the node in the sqlfluff tree
    /// format.
    pub fn name(self) -> &'static str {
        self.ty().name()
    }

    /// True if the kind has the type `ty` as its type or as a class type
    /// (sqlfluff `is_type`).
    pub fn is_type(self, ty: SegmentType) -> bool {
        let data = self.data();
        data.ty == ty || data.class_types.binary_search(&ty).is_ok()
    }

    pub fn index(self) -> u16 {
        self.0
    }

    pub fn from_index(index: u16) -> Option<Self> {
        ((index as usize) < KIND_COUNT).then_some(SegmentKind(index))
    }

    /// Each kind, in order.
    pub fn all() -> impl Iterator<Item = SegmentKind> {
        (0..KIND_COUNT as u16).map(SegmentKind)
    }

    /// The kind of the static data of a node, or `None` if no kind has the
    /// data.
    pub fn find<S: AsRef<str>>(key: &KindKey<'_, S>) -> Option<SegmentKind> {
        let start = KINDS.partition_point(|d| cmp_without_class_types(d, key) == Ordering::Less);
        KINDS[start..]
            .iter()
            .take_while(|d| cmp_without_class_types(d, key) == Ordering::Equal)
            .position(|d| same_class_types(d.class_types, key.class_types))
            .map(|i| SegmentKind((start + i) as u16))
    }
}

impl fmt::Debug for SegmentKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "SegmentKind({}, {:?})", self.0, self.name())
    }
}

fn names<'a>(types: &'a [SegmentType]) -> impl Iterator<Item = &'a str> + 'a {
    types.iter().map(|t| -> &'a str { t.name() })
}

fn cmp_option<A, B>(a: Option<A>, b: Option<B>, cmp: impl FnOnce(A, B) -> Ordering) -> Ordering {
    match (a, b) {
        (None, None) => Ordering::Equal,
        (None, Some(_)) => Ordering::Less,
        (Some(_), None) => Ordering::Greater,
        (Some(a), Some(b)) => cmp(a, b),
    }
}

/// The order of the kinds (build/kinds.rs, Kind), without the class types.
fn cmp_without_class_types<S: AsRef<str>>(d: &KindData, k: &KindKey<'_, S>) -> Ordering {
    d.variant
        .cmp(&k.variant)
        .then_with(|| d.class.cmp(k.class))
        .then_with(|| d.ty.name().cmp(k.ty))
        .then_with(|| names(d.instance_types).cmp(k.instance_types.iter().map(AsRef::as_ref)))
        .then_with(|| {
            cmp_option(d.trim_chars, k.trim_chars, |a, b| {
                a.iter()
                    .map(|s| -> &str { s })
                    .cmp(b.iter().map(AsRef::as_ref))
            })
        })
        .then_with(|| cmp_option(d.quoted_value, k.quoted_value, |a, b| a.cmp(&b)))
        .then_with(|| {
            cmp_option(d.escape_replacements, k.escape_replacements, |a, b| {
                a.iter()
                    .map(|&(x, y)| -> (&str, &str) { (x, y) })
                    .cmp(b.iter().map(|(x, y)| (x.as_ref(), y.as_ref())))
            })
        })
        .then_with(|| {
            let meta: Option<Meta<'_>> = d.meta;
            meta.cmp(&k.meta)
        })
}

/// The class types of a kind and of a key are the same set.
fn same_class_types<S: AsRef<str>>(kind: &[SegmentType], key: &[S]) -> bool {
    key.iter()
        .all(|k| kind.iter().any(|t| t.name() == k.as_ref()))
        && kind
            .iter()
            .all(|t| key.iter().any(|k| k.as_ref() == t.name()))
}
