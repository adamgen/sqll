// Parts of this file are a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/rules/fix.py (LintFix: the edit types and
// has_template_conflicts), src/sqlfluff/core/rules/base.py
// (BaseRule.discard_unsafe_fixes), and src/sqlfluff/core/linter/fix.py
// (AnchorEditInfo, compute_anchor_edit_info).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.
// Change: a fix is a text edit of the templated text of its anchor. The
// source map changes it to a source edit; an edit that is not in literal
// source text is refused.

//! Fixes, their source edits, and the application of source edits.

use std::collections::BTreeSet;
use std::fmt;
use std::ops::Range;

use sqll_source::{Slice, SourceMap, SourceMapError};
use sqll_tree::{NodeId, SyntaxTree};

/// A fix of a lint result (the sqlfluff `LintFix`). The text replaces, or
/// goes next to, the templated text of the anchor.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Fix {
    /// Replace the anchor with the text.
    Replace { anchor: NodeId, text: String },
    /// Put the text before the anchor.
    CreateBefore { anchor: NodeId, text: String },
    /// Put the text after the anchor.
    CreateAfter { anchor: NodeId, text: String },
    /// Delete the anchor.
    Delete { anchor: NodeId },
}

/// An edit of the templated text: replace a byte range with a text. An
/// empty range is an insertion.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Edit {
    pub range: Range<usize>,
    pub text: String,
}

/// An edit of the source text: replace a byte range with a text.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct SourceEdit {
    pub range: Range<usize>,
    pub text: String,
}

/// Why a fix cannot change the source.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FixRefusal {
    /// The edit touches source text that is not literal (the output of a
    /// template tag): the source map cannot change it safely.
    Templated { templated: Range<usize> },
    /// The fixes of one result touch more than one template block (sqlfluff
    /// issue 3079).
    MultipleBlocks,
    /// The source map refused the range.
    SourceMap(SourceMapError),
}

impl fmt::Display for FixRefusal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            FixRefusal::Templated { templated } => write!(
                f,
                "the edit of the templated bytes {}..{} is not in literal source text",
                templated.start, templated.end
            ),
            FixRefusal::MultipleBlocks => f.write_str("the fixes touch more than one template block"),
            FixRefusal::SourceMap(e) => write!(f, "the source map refused the edit: {e}"),
        }
    }
}

impl From<SourceMapError> for FixRefusal {
    fn from(e: SourceMapError) -> Self {
        FixRefusal::SourceMap(e)
    }
}

impl Fix {
    pub fn anchor(&self) -> NodeId {
        match self {
            Fix::Replace { anchor, .. }
            | Fix::CreateBefore { anchor, .. }
            | Fix::CreateAfter { anchor, .. }
            | Fix::Delete { anchor } => *anchor,
        }
    }

    /// The sqlfluff edit type.
    pub fn edit_type(&self) -> &'static str {
        match self {
            Fix::Replace { .. } => "replace",
            Fix::CreateBefore { .. } => "create_before",
            Fix::CreateAfter { .. } => "create_after",
            Fix::Delete { .. } => "delete",
        }
    }

    /// The edit of the templated text.
    pub fn edit(&self, tree: &SyntaxTree) -> Edit {
        let r = tree.range(self.anchor());
        match self {
            Fix::Replace { text, .. } => Edit {
                range: r,
                text: text.clone(),
            },
            Fix::CreateBefore { text, .. } => Edit {
                range: r.start..r.start,
                text: text.clone(),
            },
            Fix::CreateAfter { text, .. } => Edit {
                range: r.end..r.end,
                text: text.clone(),
            },
            Fix::Delete { .. } => Edit {
                range: r,
                text: String::new(),
            },
        }
    }

    /// The edit of the source text. `Ok(None)`: the fix changes no source
    /// (the delete of a node with no text, for example a meta node).
    ///
    /// - The anchor is literal if its source range (the sqlfluff source slice
    ///   of the node) is literal source text and is its templated text.
    /// - A replace or a delete changes the source range of a literal anchor.
    ///   Else it is refused.
    /// - An insertion next to a literal anchor goes to the start or the end
    ///   of its source range. Next to another anchor, it goes before the
    ///   source of the next character if that character is literal, else
    ///   after the source of the character before it if that one is
    ///   literal. Else it is refused.
    pub fn source_edit(&self, tree: &SyntaxTree) -> Result<Option<SourceEdit>, FixRefusal> {
        let edit = self.edit(tree);
        if edit.range.is_empty() && edit.text.is_empty() {
            return Ok(None);
        }
        let Some(map) = tree.source_map().filter(|m| !m.is_identity()) else {
            return Ok(Some(SourceEdit {
                range: edit.range,
                text: edit.text,
            }));
        };
        let anchor = self.anchor();
        let literal = !tree.range(anchor).is_empty() && literal_node(tree, anchor);
        let source = tree.source_range(anchor);
        let range = match self {
            Fix::Replace { .. } | Fix::Delete { .. } if !edit.range.is_empty() => {
                if !literal {
                    return Err(FixRefusal::Templated {
                        templated: edit.range,
                    });
                }
                source
            }
            Fix::CreateBefore { .. } if literal => source.start..source.start,
            Fix::CreateAfter { .. } if literal => source.end..source.end,
            _ => insertion_point(map, edit.range.start)?,
        };
        Ok(Some(SourceEdit {
            range,
            text: edit.text,
        }))
    }
}

/// True if the source range of the node is literal source text and is the
/// templated text of the node.
fn literal_node(tree: &SyntaxTree, id: NodeId) -> bool {
    tree.is_literal(id) && tree.source_text().get(tree.source_range(id)) == Some(tree.raw(id))
}

/// The source range of a templated range whose source is literal and the
/// same text, or a refusal.
fn literal_source(map: &SourceMap, templated: Range<usize>) -> Result<Range<usize>, FixRefusal> {
    let source = map.source_range(templated.clone())?;
    let same = map.source_text().get(source.clone()) == map.templated_text().get(templated.clone());
    if same && map.is_source_literal(source.clone())? {
        Ok(source)
    } else {
        Err(FixRefusal::Templated { templated })
    }
}

/// The source point of an insertion at a templated byte.
fn insertion_point(map: &SourceMap, at: usize) -> Result<Range<usize>, FixRefusal> {
    let text = map.templated_text();
    if let Some(c) = text.get(at..).and_then(|s| s.chars().next()) {
        if let Ok(source) = literal_source(map, at..at + c.len_utf8()) {
            return Ok(source.start..source.start);
        }
    }
    if let Some(c) = text.get(..at).and_then(|s| s.chars().next_back()) {
        if let Ok(source) = literal_source(map, at - c.len_utf8()..at) {
            return Ok(source.end..source.end);
        }
    }
    Err(FixRefusal::Templated {
        templated: at..at,
    })
}

/// The block index of each raw slice that a literal source edit touches
/// (for an insertion: the character next to it, as `insertion_point`).
fn blocks_of(map: &SourceMap, edit: &SourceEdit, out: &mut BTreeSet<usize>) {
    let file = map.file();
    if file.raw_sliced.is_empty() {
        return;
    }
    let source = map.source_text();
    let range = if edit.range.is_empty() {
        let at = edit.range.start;
        let next = source
            .get(at..)
            .and_then(|s| s.chars().next())
            .map(|c| at..at + c.len_utf8());
        let before = source
            .get(..at)
            .and_then(|s| s.chars().next_back())
            .map(|c| at - c.len_utf8()..at);
        let literal = |r: &Range<usize>| map.is_source_literal(r.clone()).unwrap_or(false);
        match next.filter(literal).or(before.filter(literal)) {
            Some(r) => r,
            None => return,
        }
    } else {
        edit.range.clone()
    };
    let (Ok(start), Ok(end)) = (
        map.source_char_of_byte(range.start),
        map.source_char_of_byte(range.end),
    ) else {
        return;
    };
    for raw in file.raw_slices_spanning_source_slice(Slice::from(start..end)) {
        out.insert(raw.block_idx);
    }
}

/// The source edits of the fixes of one result (the sqlfluff
/// `discard_unsafe_fixes`): all of them, or a refusal. The fixes of a result
/// must not touch more than one template block.
pub fn result_edits(tree: &SyntaxTree, fixes: &[Fix]) -> Result<Vec<SourceEdit>, FixRefusal> {
    let mut edits = Vec::new();
    for fix in fixes {
        if let Some(e) = fix.source_edit(tree)? {
            edits.push(e);
        }
    }
    if let Some(map) = tree.source_map().filter(|m| !m.is_identity()) {
        let mut blocks = BTreeSet::new();
        for e in &edits {
            blocks_of(map, e, &mut blocks);
        }
        if blocks.len() > 1 {
            return Err(FixRefusal::MultipleBlocks);
        }
    }
    Ok(edits)
}

/// The sqlfluff `compute_anchor_edit_info` check: each anchor has one fix,
/// or one `CreateBefore` and one `CreateAfter`. Equal fixes count once. It
/// gives the fixes with no duplicate, in order, or `None` if an anchor has
/// a conflict.
pub fn check_anchors(fixes: &[Fix]) -> Option<Vec<Fix>> {
    let mut out: Vec<Fix> = Vec::new();
    for fix in fixes {
        if !out.contains(fix) {
            out.push(fix.clone());
        }
    }
    let anchors: BTreeSet<NodeId> = out.iter().map(Fix::anchor).collect();
    for anchor in anchors {
        let of: Vec<&Fix> = out.iter().filter(|f| f.anchor() == anchor).collect();
        let valid = match of.as_slice() {
            [_] => true,
            [a, b] => {
                let mut types = [a.edit_type(), b.edit_type()];
                types.sort_unstable();
                types == ["create_after", "create_before"]
            }
            _ => false,
        };
        if !valid {
            return None;
        }
    }
    Some(out)
}

/// The order of edits at one source point: an insertion after an anchor,
/// then an insertion before an anchor, then a change of a range.
fn rank(edit: &SourceEdit, after: bool) -> u8 {
    match (edit.range.is_empty(), after) {
        (true, true) => 0,
        (true, false) => 1,
        (false, _) => 2,
    }
}

/// Apply source edits to a source text. Each edit is a pair of the edit
/// and true if it is an insertion after an anchor. Edits at one point keep
/// their order. It fails (`None`) if two edits overlap: two changes of
/// ranges that share a byte, or an insertion inside a changed range.
pub fn apply_edits(source: &str, edits: &[(SourceEdit, bool)]) -> Option<String> {
    let mut order: Vec<&(SourceEdit, bool)> = edits.iter().collect();
    order.sort_by_key(|(e, after)| (e.range.start, rank(e, *after)));
    let mut out = String::with_capacity(source.len());
    let mut at = 0;
    for (e, _) in order {
        if e.range.start < at || e.range.end > source.len() {
            return None;
        }
        if !source.is_char_boundary(e.range.start) || !source.is_char_boundary(e.range.end) {
            return None;
        }
        out.push_str(&source[at..e.range.start]);
        out.push_str(&e.text);
        at = e.range.end;
    }
    out.push_str(&source[at..]);
    Some(out)
}
