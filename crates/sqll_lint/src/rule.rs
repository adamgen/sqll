// Parts of this file are a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/rules/base.py (BaseRule, LintResult) and
// src/sqlfluff/core/rules/crawlers.py (RootOnlyCrawler,
// SegmentSeekerCrawler, BaseCrawler.passes_filter).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The [`Rule`] trait, its crawl, its context, and its results.

use std::any::Any;

use sqll_syntax::Dialect;
use sqll_tree::{NodeId, NodeRef, SegmentType, SyntaxTree};

use crate::config::RuleConfig;
use crate::fix::Fix;
use crate::LintError;

/// The phase of a rule in the fix loop (the sqlfluff `lint_phase`). A
/// `Post` rule (for example a capitalisation rule) does not cause other
/// fixes: it runs in the main phase and again after it.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum LintPhase {
    Main,
    Post,
}

/// The nodes that a rule examines (the sqlfluff crawlers).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CrawlBehaviour {
    /// `RootOnlyCrawler`: the root node only.
    RootOnly { works_on_unparsable: bool },
    /// `SegmentSeekerCrawler`: each node that has one of the types
    /// (`is_type`), in pre-order. If `allow_recurse` is false, the crawl does
    /// not go into a match.
    SegmentSeeker {
        types: &'static [SegmentType],
        allow_recurse: bool,
        works_on_unparsable: bool,
    },
}

impl CrawlBehaviour {
    /// `SegmentSeekerCrawler(types)` with the sqlfluff defaults.
    pub const fn seeker(types: &'static [SegmentType]) -> Self {
        CrawlBehaviour::SegmentSeeker {
            types,
            allow_recurse: true,
            works_on_unparsable: false,
        }
    }

    /// `RootOnlyCrawler()` with the sqlfluff defaults.
    pub const fn root_only() -> Self {
        CrawlBehaviour::RootOnly {
            works_on_unparsable: false,
        }
    }

    pub fn works_on_unparsable(&self) -> bool {
        match *self {
            CrawlBehaviour::RootOnly {
                works_on_unparsable,
            }
            | CrawlBehaviour::SegmentSeeker {
                works_on_unparsable,
                ..
            } => works_on_unparsable,
        }
    }

    /// The sqlfluff `passes_filter`: the rule examines the node at all. A
    /// node of the type `unparsable` does not pass, unless the crawler works
    /// on unparsable nodes.
    pub fn passes_filter(&self, node: NodeRef<'_>) -> bool {
        self.works_on_unparsable() || !node.is_type(SegmentType::UNPARSABLE)
    }

    /// The nodes to examine, in the order of the sqlfluff crawler. The
    /// crawl does not go into a node that does not pass the filter.
    pub fn crawl(&self, tree: &SyntaxTree) -> Vec<NodeId> {
        let root = tree.root_node();
        match *self {
            CrawlBehaviour::RootOnly { .. } => {
                if self.passes_filter(root) {
                    vec![root.id()]
                } else {
                    Vec::new()
                }
            }
            CrawlBehaviour::SegmentSeeker {
                types,
                allow_recurse,
                ..
            } => {
                let mut out = Vec::new();
                // The index of the next node to examine (pre-order).
                let mut next = 0;
                for id in tree.nodes() {
                    if id.index() < next {
                        continue;
                    }
                    let node = tree.node(id);
                    let after = id.index() + tree.descendants(id).len() + 1;
                    if !self.passes_filter(node) {
                        next = after;
                        continue;
                    }
                    let matched = node.is_any_type(types);
                    if matched {
                        out.push(id);
                    }
                    next = if matched && !allow_recurse {
                        after
                    } else {
                        id.index() + 1
                    };
                }
                out
            }
        }
    }
}

/// The memory of one crawl of a rule over a tree (the sqlfluff
/// `context.memory`): the rule keeps its state from one node to the next.
/// It is empty at the start of each crawl.
#[derive(Default)]
pub struct Memory(Option<Box<dyn Any>>);

impl Memory {
    /// The state of the type `T`; a new default state if there is none, or
    /// if the state has another type.
    pub fn get_or_default<T: Any + Default>(&mut self) -> &mut T {
        if !self.0.as_ref().is_some_and(|b| b.is::<T>()) {
            self.0 = Some(Box::new(T::default()));
        }
        self.0
            .as_mut()
            .and_then(|b| b.downcast_mut::<T>())
            .expect("the state has the type T")
    }

    /// The state of the type `T`, if there is one.
    pub fn get<T: Any>(&self) -> Option<&T> {
        self.0.as_ref().and_then(|b| b.downcast_ref::<T>())
    }
}

/// The context of one call of [`Rule::eval`] (the sqlfluff `RuleContext`).
pub struct RuleContext<'t, 'c> {
    /// The node to examine.
    pub segment: NodeRef<'t>,
    pub dialect: Dialect,
    /// The config of the rule.
    pub config: &'c RuleConfig,
    /// The memory of the crawl.
    pub memory: &'c mut Memory,
}

impl<'t> RuleContext<'t, '_> {
    pub fn tree(&self) -> &'t SyntaxTree {
        self.segment.tree()
    }

    /// The parent of the node (the last of the sqlfluff `parent_stack`).
    pub fn parent(&self) -> Option<NodeRef<'t>> {
        self.segment.parent()
    }

    /// The sqlfluff `parent_stack`: the ancestors of the node, from the root.
    pub fn parent_stack(&self) -> Vec<NodeRef<'t>> {
        let mut out = Vec::new();
        let mut p = self.segment.parent();
        while let Some(n) = p {
            out.push(n);
            p = n.parent();
        }
        out.reverse();
        out
    }
}

/// A violation at an anchor node, with the fixes for it (the sqlfluff
/// `LintResult` with an anchor). A result with no fix is not fixable.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LintResult {
    pub anchor: NodeId,
    /// The description; `None` gives the description of the rule.
    pub description: Option<String>,
    pub fixes: Vec<Fix>,
}

impl LintResult {
    pub fn new(anchor: NodeId) -> Self {
        LintResult {
            anchor,
            description: None,
            fixes: Vec::new(),
        }
    }

    pub fn with_description(mut self, description: impl Into<String>) -> Self {
        self.description = Some(description.into());
        self
    }

    pub fn with_fix(mut self, fix: Fix) -> Self {
        self.fixes.push(fix);
        self
    }
}

/// A lint rule. The metadata must be that of the sqlfluff rule with the
/// same code ([`crate::RULES`]); [`crate::Registry::new`] checks it.
pub trait Rule: Send + Sync {
    /// The code, for example `CP01`.
    fn code(&self) -> &'static str;
    /// The name, for example `capitalisation.keywords`. The config section
    /// of the rule is `[sqlfluff:rules:<name>]`.
    fn name(&self) -> &'static str;
    /// The description: the first line of the sqlfluff docstring.
    fn description(&self) -> &'static str;
    fn groups(&self) -> &'static [&'static str];
    fn aliases(&self) -> &'static [&'static str] {
        &[]
    }
    /// The config keywords that the rule reads ([`RuleConfig::get`]).
    fn config_keywords(&self) -> &'static [&'static str] {
        &[]
    }
    fn lint_phase(&self) -> LintPhase {
        LintPhase::Main
    }
    /// True if the rule gives fixes.
    fn is_fix_compatible(&self) -> bool {
        false
    }
    /// True if the rule reports violations in templated sections also when
    /// `ignore_templated_areas` is true.
    fn targets_templated(&self) -> bool {
        false
    }
    fn crawl_behaviour(&self) -> CrawlBehaviour;
    /// Check the config of the rule before a lint. A value that the rule
    /// cannot do gives [`LintError::Unsupported`] (fail closed).
    fn check_config(&self, _config: &RuleConfig) -> Result<(), LintError> {
        Ok(())
    }
    /// Examine one node of the crawl. An error stops the lint: a case that
    /// the rule cannot do gives [`LintError::Unsupported`] (fail closed;
    /// sqlfluff gives an "Unexpected exception" violation and stops the
    /// rule).
    fn eval(&self, context: &mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError>;
}
