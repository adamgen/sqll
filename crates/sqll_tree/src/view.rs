//! The typed view of a [`SyntaxTree`] (docs/interfaces/typed-view.md, S3b
//! task C10).
//!
//! - [`NodeRef`]: a node and its tree, with navigation and the query helpers
//!   of the sqlfluff `BaseSegment`: `child` (`get_child`), `children_of`
//!   (`get_children`), `first_descendant`, and `crawl` (`recursive_crawl`).
//! - [`AstNode`]: a typed node. `cast` gives the typed node if the kind of the
//!   node agrees. [`typed_node!`](crate::typed_node) declares one, by type
//!   (the sqlfluff `is_type`) or by a function of the kind.
//! - The typed nodes of the core set ([`nodes`]), with accessors.

use std::fmt;
use std::ops::Range;

use crate::kinds::{SegmentKind, SegmentType, Variant};
use crate::tree::{NodeId, SyntaxTree};

/// A node of a tree. It is `Copy`: two words.
#[derive(Clone, Copy)]
pub struct NodeRef<'t> {
    tree: &'t SyntaxTree,
    id: NodeId,
}

impl PartialEq for NodeRef<'_> {
    fn eq(&self, other: &Self) -> bool {
        std::ptr::eq(self.tree, other.tree) && self.id == other.id
    }
}

impl Eq for NodeRef<'_> {}

impl fmt::Debug for NodeRef<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "NodeRef({}, {:?}, {:?})",
            self.id.index(),
            self.ty().name(),
            self.raw()
        )
    }
}

/// True if the raw kind is code: not whitespace, a newline, or a comment
/// (the sqlfluff `WhitespaceSegment`, `NewlineSegment`, and `CommentSegment`
/// and their subclasses: their class types have the type of the class).
fn raw_is_code(kind: SegmentKind) -> bool {
    let class_types = kind.data().class_types;
    ![
        SegmentType::WHITESPACE,
        SegmentType::NEWLINE,
        SegmentType::COMMENT,
    ]
    .iter()
    .any(|t| class_types.binary_search(t).is_ok())
}

impl<'t> NodeRef<'t> {
    /// The node `id` of `tree`. It panics if the tree has no such node.
    pub fn new(tree: &'t SyntaxTree, id: NodeId) -> Self {
        assert!(id.index() < tree.node_count(), "a node of the tree");
        NodeRef { tree, id }
    }

    pub fn tree(self) -> &'t SyntaxTree {
        self.tree
    }

    pub fn id(self) -> NodeId {
        self.id
    }

    fn at(self, id: NodeId) -> Self {
        NodeRef {
            tree: self.tree,
            id,
        }
    }

    pub fn kind(self) -> SegmentKind {
        self.tree.kind(self.id)
    }

    /// The type: the key of the node in the sqlfluff tree format.
    pub fn ty(self) -> SegmentType {
        self.tree.ty(self.id)
    }

    /// The sqlfluff `is_type` of one type.
    pub fn is_type(self, ty: SegmentType) -> bool {
        self.kind().is_type(ty)
    }

    /// The sqlfluff `is_type(*types)`: true if `is_type` is true for one of
    /// the types.
    pub fn is_any_type(self, types: &[SegmentType]) -> bool {
        let kind = self.kind();
        types.iter().any(|&t| kind.is_type(t))
    }

    /// The templated text of the node.
    pub fn raw(self) -> &'t str {
        self.tree.raw(self.id)
    }

    /// The templated byte range of the node.
    pub fn range(self) -> Range<usize> {
        self.tree.range(self.id)
    }

    /// True for an indent, a dedent, a placeholder, a template loop, and the
    /// end of the file.
    pub fn is_meta(self) -> bool {
        self.tree.is_meta(self.id)
    }

    /// The sqlfluff `is_code`: a leaf that is not whitespace, a newline, or a
    /// comment; or a node with children of which one is code. A meta node is
    /// not code.
    pub fn is_code(self) -> bool {
        match self.kind().data().variant {
            Variant::Raw => raw_is_code(self.kind()),
            Variant::Meta | Variant::Empty => false,
            Variant::Segment | Variant::Unparsable => self
                .tree
                .descendants(self.id)
                .any(|d| self.tree.variant(d) == Variant::Raw && raw_is_code(self.tree.kind(d))),
        }
    }

    pub fn parent(self) -> Option<NodeRef<'t>> {
        self.tree.parent(self.id).map(|p| self.at(p))
    }

    /// The children, in order.
    pub fn children(self) -> impl Iterator<Item = NodeRef<'t>> + Clone {
        let tree = self.tree;
        tree.children(self.id).map(move |id| NodeRef { tree, id })
    }

    /// The descendants in pre-order, without the node.
    pub fn descendants(self) -> impl Iterator<Item = NodeRef<'t>> + Clone {
        let tree = self.tree;
        (self.id.index() + 1..self.end()).map(move |i| NodeRef {
            tree,
            id: NodeId::from_usize(i),
        })
    }

    /// The index after the last descendant.
    fn end(self) -> usize {
        self.id.index() + self.tree.descendants(self.id).len() + 1
    }

    /// The sqlfluff `get_child(*types)`: the first child of one of the types.
    pub fn child(self, types: &[SegmentType]) -> Option<NodeRef<'t>> {
        self.children().find(|c| c.is_any_type(types))
    }

    /// The sqlfluff `get_children(*types)`: each child of one of the types,
    /// in order.
    pub fn children_of<'a>(
        self,
        types: &'a [SegmentType],
    ) -> impl Iterator<Item = NodeRef<'t>> + Clone + 'a
    where
        't: 'a,
    {
        self.children().filter(move |c| c.is_any_type(types))
    }

    /// The first descendant of one of the types, in pre-order, without the
    /// node.
    pub fn first_descendant(self, types: &[SegmentType]) -> Option<NodeRef<'t>> {
        self.descendants().find(|d| d.is_any_type(types))
    }

    /// The first code child: for example the statement segment in a
    /// `statement`.
    pub fn first_code_child(self) -> Option<NodeRef<'t>> {
        self.children().find(|c| c.is_code())
    }

    /// The sqlfluff `recursive_crawl(*types)`, with its defaults: recurse
    /// into a match, no stop types, and the node can be a match. Change them
    /// with [`Crawl::recurse_into`], [`Crawl::no_recursive`], and
    /// [`Crawl::allow_self`].
    pub fn crawl<'a>(self, types: &'a [SegmentType]) -> Crawl<'t, 'a> {
        Crawl {
            tree: self.tree,
            from: self.id.index(),
            next: self.id.index(),
            end: self.end(),
            types,
            no_recursive: &[],
            recurse_into: true,
            allow_self: true,
        }
    }

    /// The typed node, if the kind agrees.
    pub fn cast<N: AstNode<'t>>(self) -> Option<N> {
        N::cast(self)
    }

    /// The first child that casts to `N`.
    pub fn child_as<N: AstNode<'t>>(self) -> Option<N> {
        self.children().find_map(N::cast)
    }

    /// Each child that casts to `N`, in order.
    pub fn children_as<N: AstNode<'t>>(self) -> impl Iterator<Item = N> + Clone + use<'t, N> {
        self.children().filter_map(N::cast)
    }

    /// Each descendant that casts to `N`, in pre-order, without the node.
    pub fn descendants_as<N: AstNode<'t>>(self) -> impl Iterator<Item = N> + Clone + use<'t, N> {
        self.descendants().filter_map(N::cast)
    }
}

impl SyntaxTree {
    /// The node `id` as a [`NodeRef`].
    pub fn node(&self, id: NodeId) -> NodeRef<'_> {
        NodeRef::new(self, id)
    }

    /// The root as a [`NodeRef`].
    pub fn root_node(&self) -> NodeRef<'_> {
        NodeRef::new(self, NodeId::ROOT)
    }
}

/// The sqlfluff `recursive_crawl` (see [`NodeRef::crawl`]). It gives the
/// nodes of the types in pre-order:
///
/// - The start node is a match if `allow_self` is true and it has one of the
///   types.
/// - The crawl does not go into a match if `recurse_into` is false.
/// - The crawl does not go to a node below the start node that has one of
///   the `no_recursive` types, or to its descendants. Such a node is not a
///   match, also if it has one of the types (as in sqlfluff).
#[derive(Clone)]
pub struct Crawl<'t, 'a> {
    tree: &'t SyntaxTree,
    from: usize,
    next: usize,
    end: usize,
    types: &'a [SegmentType],
    no_recursive: &'a [SegmentType],
    recurse_into: bool,
    allow_self: bool,
}

impl<'t, 'a> Crawl<'t, 'a> {
    /// The sqlfluff `recurse_into` (default true).
    pub fn recurse_into(mut self, recurse_into: bool) -> Self {
        self.recurse_into = recurse_into;
        self
    }

    /// The sqlfluff `no_recursive_seg_type` (default none).
    pub fn no_recursive(mut self, types: &'a [SegmentType]) -> Self {
        self.no_recursive = types;
        self
    }

    /// The sqlfluff `allow_self` (default true).
    pub fn allow_self(mut self, allow_self: bool) -> Self {
        self.allow_self = allow_self;
        self
    }

    /// The index after the last descendant of node `i`.
    fn after(&self, i: usize) -> usize {
        NodeRef::new(self.tree, NodeId::from_usize(i)).end()
    }
}

impl<'t> Iterator for Crawl<'t, '_> {
    type Item = NodeRef<'t>;

    fn next(&mut self) -> Option<NodeRef<'t>> {
        while self.next < self.end {
            let i = self.next;
            let id = NodeId::from_usize(i);
            let kind = self.tree.kind(id);
            if i != self.from && self.no_recursive.iter().any(|&t| kind.is_type(t)) {
                self.next = self.after(i);
                continue;
            }
            let matched =
                (i != self.from || self.allow_self) && self.types.iter().any(|&t| kind.is_type(t));
            self.next = if matched && !self.recurse_into {
                self.after(i)
            } else {
                i + 1
            };
            if matched {
                return Some(NodeRef {
                    tree: self.tree,
                    id,
                });
            }
        }
        None
    }
}

/// A typed node: a [`NodeRef`] of some kinds. Declare one with
/// [`typed_node!`](crate::typed_node).
pub trait AstNode<'t>: Copy {
    /// True if a node of this kind is this typed node.
    fn can_cast(kind: SegmentKind) -> bool;

    /// The typed node, if the kind of the node agrees.
    fn cast(node: NodeRef<'t>) -> Option<Self>;

    /// The node.
    fn node(self) -> NodeRef<'t>;
}

/// Declare a typed node: a newtype of [`NodeRef`] that implements
/// [`AstNode`] and derefs to its `NodeRef`.
///
/// - By type: `typed_node!(pub struct Name = SELECT_STATEMENT;)` casts a
///   node for which `is_type` of one of the [`SegmentType`] constants is
///   true (`A | B` for more than one).
/// - By kind: `typed_node!(pub struct Name = kind |k| ...;)` casts a node
///   whose kind gives true.
#[macro_export]
macro_rules! typed_node {
    ($(#[$attr:meta])* $vis:vis struct $name:ident = kind $can_cast:expr;) => {
        $(#[$attr])*
        #[derive(Clone, Copy, Debug, PartialEq, Eq)]
        $vis struct $name<'t>($crate::view::NodeRef<'t>);

        impl<'t> $crate::view::AstNode<'t> for $name<'t> {
            fn can_cast(kind: $crate::SegmentKind) -> bool {
                let can_cast: fn($crate::SegmentKind) -> bool = $can_cast;
                can_cast(kind)
            }

            fn cast(node: $crate::view::NodeRef<'t>) -> Option<Self> {
                <Self as $crate::view::AstNode<'t>>::can_cast(node.kind()).then_some($name(node))
            }

            fn node(self) -> $crate::view::NodeRef<'t> {
                self.0
            }
        }

        impl<'t> ::std::ops::Deref for $name<'t> {
            type Target = $crate::view::NodeRef<'t>;

            fn deref(&self) -> &Self::Target {
                &self.0
            }
        }
    };
    ($(#[$attr:meta])* $vis:vis struct $name:ident = $($ty:ident)|+;) => {
        $crate::typed_node!(
            $(#[$attr])*
            $vis struct $name = kind |kind| false $(|| kind.is_type($crate::SegmentType::$ty))+;
        );
    };
}

/// The typed nodes of the core set. Later tracks add more through Core.
pub mod nodes {
    use super::NodeRef;
    use crate::kinds::{Meta, SegmentType};

    crate::typed_node!(
        /// The root of a parse (`file`).
        pub struct File = FILE;
    );
    crate::typed_node!(
        /// A `statement`: one statement segment as its code child.
        pub struct Statement = STATEMENT;
    );
    crate::typed_node!(pub struct SelectStatement = SELECT_STATEMENT;);
    crate::typed_node!(pub struct SelectClause = SELECT_CLAUSE;);
    crate::typed_node!(pub struct SelectClauseElement = SELECT_CLAUSE_ELEMENT;);
    crate::typed_node!(pub struct FromClause = FROM_CLAUSE;);
    crate::typed_node!(pub struct FromExpression = FROM_EXPRESSION;);
    crate::typed_node!(pub struct FromExpressionElement = FROM_EXPRESSION_ELEMENT;);
    crate::typed_node!(pub struct TableReference = TABLE_REFERENCE;);
    crate::typed_node!(pub struct ColumnReference = COLUMN_REFERENCE;);
    crate::typed_node!(pub struct AliasExpression = ALIAS_EXPRESSION;);
    crate::typed_node!(
        /// A keyword leaf.
        pub struct Keyword = KEYWORD;
    );
    crate::typed_node!(
        /// An identifier leaf: `naked_identifier`, `quoted_identifier`, and
        /// the other types with the class type `identifier`.
        pub struct Identifier = IDENTIFIER;
    );
    crate::typed_node!(
        /// A literal: `numeric_literal`, `quoted_literal`, and the other
        /// types with the class type `literal`.
        pub struct Literal = LITERAL;
    );
    crate::typed_node!(
        /// A template placeholder (a meta node of the type `placeholder`).
        pub struct Placeholder = kind |k| matches!(k.data().meta, Some(Meta::Template { .. }));
    );

    const STATEMENT: &[SegmentType] = &[SegmentType::STATEMENT];
    const FROM_EXPRESSION_ELEMENT: &[SegmentType] = &[SegmentType::FROM_EXPRESSION_ELEMENT];

    impl<'t> File<'t> {
        /// The statements that are not in another statement, in order (the
        /// sqlfluff `recursive_crawl("statement", recurse_into=False)`). Some
        /// dialects put them in a `batch`.
        pub fn statements(self) -> impl Iterator<Item = Statement<'t>> + Clone {
            self.0
                .crawl(STATEMENT)
                .recurse_into(false)
                .filter_map(NodeRef::cast)
        }
    }

    impl<'t> Statement<'t> {
        /// The statement segment: the first code child, for example a
        /// `select_statement`.
        pub fn inner(self) -> Option<NodeRef<'t>> {
            self.0.first_code_child()
        }

        pub fn select_statement(self) -> Option<SelectStatement<'t>> {
            self.0.child_as()
        }
    }

    impl<'t> SelectStatement<'t> {
        pub fn select_clause(self) -> Option<SelectClause<'t>> {
            self.0.child_as()
        }

        pub fn from_clause(self) -> Option<FromClause<'t>> {
            self.0.child_as()
        }
    }

    impl<'t> SelectClause<'t> {
        /// The select targets, in order.
        pub fn elements(self) -> impl Iterator<Item = SelectClauseElement<'t>> + Clone {
            self.0.children_as()
        }
    }

    impl<'t> SelectClauseElement<'t> {
        pub fn alias(self) -> Option<AliasExpression<'t>> {
            self.0.child_as()
        }

        /// The value: the first code child that is not the alias, for
        /// example a `column_reference` or a `function`.
        pub fn value(self) -> Option<NodeRef<'t>> {
            self.0
                .children()
                .find(|c| c.is_code() && !c.is_type(SegmentType::ALIAS_EXPRESSION))
        }

        pub fn column_reference(self) -> Option<ColumnReference<'t>> {
            self.0.child_as()
        }
    }

    impl<'t> FromClause<'t> {
        pub fn from_expressions(self) -> impl Iterator<Item = FromExpression<'t>> + Clone {
            self.0.children_as()
        }
    }

    impl<'t> FromExpression<'t> {
        /// The elements of the expression and of its joins, but not those in
        /// an element (for example in a subquery): the sqlfluff
        /// `recursive_crawl("from_expression_element", recurse_into=False)`.
        pub fn elements(self) -> impl Iterator<Item = FromExpressionElement<'t>> + Clone {
            self.0
                .crawl(FROM_EXPRESSION_ELEMENT)
                .recurse_into(false)
                .filter_map(NodeRef::cast)
        }
    }

    impl<'t> FromExpressionElement<'t> {
        /// The table reference of the `table_expression` child, if it has
        /// one (not for a subquery or a function).
        pub fn table_reference(self) -> Option<TableReference<'t>> {
            self.0.child(&[SegmentType::TABLE_EXPRESSION])?.child_as()
        }

        pub fn alias(self) -> Option<AliasExpression<'t>> {
            self.0.child_as()
        }
    }

    impl<'t> TableReference<'t> {
        /// The identifiers of the reference, in order (for example the
        /// schema and the table).
        pub fn parts(self) -> impl Iterator<Item = Identifier<'t>> + Clone {
            self.0.children_as()
        }
    }

    impl<'t> ColumnReference<'t> {
        /// The identifiers of the reference, in order (for example the
        /// table and the column).
        pub fn parts(self) -> impl Iterator<Item = Identifier<'t>> + Clone {
            self.0.children_as()
        }
    }

    impl<'t> AliasExpression<'t> {
        /// The alias name: the identifier child (as the sqlfluff
        /// `SelectClauseElementSegment.get_alias`).
        pub fn identifier(self) -> Option<Identifier<'t>> {
            self.0.child_as()
        }

        /// The `alias_operator` child: the `AS` keyword, or `=` in some
        /// dialects (the sqlfluff rule AL02 reads it).
        pub fn operator(self) -> Option<NodeRef<'t>> {
            self.0.child(&[SegmentType::ALIAS_OPERATOR])
        }

        /// The `AS` keyword of the operator, if the alias has one.
        pub fn as_keyword(self) -> Option<Keyword<'t>> {
            self.operator()?
                .children_as::<Keyword<'t>>()
                .find(|k| k.is("AS"))
        }
    }

    impl Keyword<'_> {
        /// True if the keyword is `word`, with no regard to case.
        pub fn is(self, word: &str) -> bool {
            self.0.raw().eq_ignore_ascii_case(word)
        }
    }

    impl Identifier<'_> {
        pub fn is_quoted(self) -> bool {
            self.0.is_type(SegmentType::QUOTED_IDENTIFIER)
        }
    }

    impl<'t> Placeholder<'t> {
        /// The slice type of the templater, for example `templated` or
        /// `block_start`.
        pub fn block_type(self) -> &'static str {
            match self.0.kind().data().meta {
                Some(Meta::Template { block_type }) => block_type,
                _ => unreachable!("a placeholder kind"),
            }
        }

        /// The source text of the placeholder (the sqlfluff `source_str`).
        pub fn source_str(self) -> &'t str {
            let tree = self.0.tree();
            &tree.source_text()[tree.source_range(self.0.id())]
        }
    }
}

#[cfg(test)]
mod tests {
    use super::nodes::*;
    use super::*;
    use crate::tree::TreeBuilder;

    fn kind(variant: Variant, ty: SegmentType) -> SegmentKind {
        *ty.kinds()
            .iter()
            .find(|k| k.data().variant == variant)
            .expect("a kind")
    }

    #[test]
    fn a_raw_kind_is_code_unless_its_class_is_whitespace_newline_or_comment() {
        let mut non_code = 0;
        for k in SegmentKind::all().filter(|k| k.data().variant == Variant::Raw) {
            let class = k.data().class;
            let want = !matches!(
                class,
                "WhitespaceSegment" | "NewlineSegment" | "CommentSegment"
            );
            assert_eq!(raw_is_code(k), want, "{k:?} {class}");
            non_code += usize::from(!want);
        }
        assert!(non_code > 0);
    }

    /// "a b" as file(statement(keyword "a", whitespace " ", statement(
    /// keyword "b")), end_of_file): a statement in a statement.
    fn nested() -> SyntaxTree {
        let mut b = TreeBuilder::new("a b".into()).unwrap();
        b.start_node(kind(Variant::Segment, SegmentType::FILE))
            .unwrap();
        b.start_node(kind(Variant::Segment, SegmentType::STATEMENT))
            .unwrap();
        b.leaf(kind(Variant::Raw, SegmentType::KEYWORD), "a")
            .unwrap();
        b.leaf(kind(Variant::Raw, SegmentType::WHITESPACE), " ")
            .unwrap();
        b.start_node(kind(Variant::Segment, SegmentType::STATEMENT))
            .unwrap();
        b.leaf(kind(Variant::Raw, SegmentType::KEYWORD), "b")
            .unwrap();
        b.finish_node().unwrap();
        b.finish_node().unwrap();
        b.meta(kind(Variant::Meta, SegmentType::END_OF_FILE))
            .unwrap();
        b.finish_node().unwrap();
        b.finish().unwrap()
    }

    fn ids<'t>(it: impl Iterator<Item = NodeRef<'t>>) -> Vec<usize> {
        it.map(|n| n.id().index()).collect()
    }

    #[test]
    fn the_crawl_has_the_options_of_recursive_crawl() {
        let tree = nested();
        let root = tree.root_node();
        let st = &[SegmentType::STATEMENT];
        let kw = &[SegmentType::KEYWORD];
        assert_eq!(ids(root.crawl(st)), [1, 4]);
        assert_eq!(ids(root.crawl(st).recurse_into(false)), [1]);
        assert_eq!(ids(root.crawl(kw)), [2, 5]);
        // A stop type: no match in it, and the stop node is no match.
        assert_eq!(ids(root.crawl(kw).no_recursive(st)), Vec::<usize>::new());
        assert_eq!(ids(root.crawl(st).no_recursive(st)), Vec::<usize>::new());
        let outer = tree.node(NodeId::from_usize(1));
        // The start node is not a stop node.
        assert_eq!(ids(outer.crawl(kw).no_recursive(st)), [2]);
        assert_eq!(ids(outer.crawl(st).allow_self(false)), [4]);
        // allow_self false: the start node is no match, thus the crawl goes
        // into it also with recurse_into false.
        assert_eq!(
            ids(outer.crawl(st).allow_self(false).recurse_into(false)),
            [4]
        );
        assert_eq!(ids(outer.crawl(st).recurse_into(false)), [1]);
        assert_eq!(
            ids(root.crawl(&[SegmentType::KEYWORD, SegmentType::END_OF_FILE])),
            [2, 5, 6]
        );
        let leaf = tree.node(NodeId::from_usize(5));
        assert_eq!(ids(leaf.crawl(kw)), [5]);
        assert_eq!(ids(leaf.crawl(kw).allow_self(false)), Vec::<usize>::new());
    }

    #[test]
    fn the_helpers_and_the_casts() {
        let tree = nested();
        let root = tree.root_node();
        assert_eq!(root.ty(), SegmentType::FILE);
        assert_eq!(ids(root.children()), [1, 6]);
        assert_eq!(ids(root.descendants()), [1, 2, 3, 4, 5, 6]);
        let outer = root.child(&[SegmentType::STATEMENT]).unwrap();
        assert_eq!(ids(outer.children_of(&[SegmentType::KEYWORD])), [2]);
        assert_eq!(
            outer
                .first_descendant(&[SegmentType::STATEMENT])
                .unwrap()
                .raw(),
            "b"
        );
        assert_eq!(root.first_descendant(&[SegmentType::FILE]), None);
        assert_eq!(outer.first_code_child().unwrap().raw(), "a");
        assert_eq!(outer.parent(), Some(root));
        assert!(outer.is_code());
        assert!(!tree.node(NodeId::from_usize(3)).is_code());
        assert!(!tree.node(NodeId::from_usize(6)).is_code());
        assert!(tree.node(NodeId::from_usize(6)).is_meta());

        let file: File = root.cast().unwrap();
        assert_eq!(file.raw(), "a b");
        assert_eq!(ids(file.statements().map(|s| s.node())), [1]);
        assert!(root.cast::<Statement>().is_none());
        assert_eq!(ids(outer.children_as::<Keyword>().map(|k| k.node())), [2]);
        assert_eq!(
            ids(root.descendants_as::<Statement>().map(|k| k.node())),
            [1, 4]
        );
        assert!(outer.child_as::<Keyword>().unwrap().is("A"));
        assert!(<Keyword as AstNode>::can_cast(kind(
            Variant::Raw,
            SegmentType::KEYWORD
        )));
        assert!(!<Placeholder as AstNode>::can_cast(kind(
            Variant::Meta,
            SegmentType::END_OF_FILE
        )));
        assert_eq!(format!("{root:?}"), "NodeRef(0, \"file\", \"a b\")");
    }
}
