//! The segment kinds of the dialect tables (S3b task C6). build.rs runs it
//! and writes OUT_DIR/kinds.rs, which src/kinds.rs includes.
//!
//! A kind is one distinct static data of a parser node: the node variant,
//! the class, the type, the instance types, the class types (a set), the
//! segment kwargs of a leaf, and the meta data of a meta node
//! (docs/decisions/s3b-core.md, Q1 and Q7). The text and the position are
//! not static.
//!
//! The kinds are a superset of the kinds that the parser can make. Each rule
//! below is the rule of the parser code that makes the node:
//!
//! - lexer leaf: a token of a lexer matcher (token_to_node, match_result.rs).
//! - parser leaf: a terminal grammar (StringParser, MultiStringParser,
//!   TypedParser, RegexParser) or a bracket symbol, for each token kwargs of
//!   the lexers of the dialect (the retag in MatchResult::apply, and the
//!   handlers in core.rs).
//! - segment: a Ref grammar with a class or a type (build_ref_wrap,
//!   ref_grammar.rs), the root, the bracketed and the unparsable segment
//!   (MatchedClass::root, MatchResult::bracketed, MatchedClass::unparsable).
//! - meta: indent and dedent (implicit or not), a template placeholder for
//!   each slice type, the template loop, and the end of the file.
//!
//! Parts of this file are a port of sqlfluff 4.4.0 code (sqlfluffrs): the
//! node construction rules of sqlfluffrs_parser (src/parser/match_result.rs,
//! src/parser/core.rs, src/parser/table_driven/ref_grammar.rs), as
//! crates/sqll_parser has them. Source: https://github.com/sqlfluff/sqlfluff,
//! tag 4.4.0, commit 0348222a3bcdb0226563f7349c5a39beb0641955.
//! Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
//! crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write as _;
use std::str::FromStr;
use std::sync::Arc;

use sqll_dialects::Dialect;
use sqll_types::{
    GrammarContext, GrammarId, GrammarTables, GrammarVariant, LexMatcher, LexMatcherConfig,
    PositionMarker, RegexModeGroup, Slice, TemplatedFile, Token,
};

const NONE: u32 = 0xFFFF_FFFF;

/// The slice types of a template placeholder (MetaType::Template
/// block_type): the slice types of the sqlfluff templaters, and
/// "skipped_source" of the lexer.
pub const BLOCK_TYPES: &[&str] = &[
    "block_end",
    "block_mid",
    "block_start",
    "comment",
    "escaped",
    "literal",
    "skipped_source",
    "templated",
];

/// The node variant. The order is the order of the kinds.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Variant {
    Raw,
    Segment,
    Meta,
    Unparsable,
    Empty,
}

/// The data of a meta node. The order is the order of the kinds.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Meta {
    Indent { implicit: bool },
    Dedent { implicit: bool },
    Template { block_type: String },
    TemplateLoop,
    EndOfFile,
}

/// One kind. The field order is the sort order of the kinds; the runtime
/// lookup (src/kinds.rs) compares in the same order.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Kind {
    pub variant: Variant,
    pub class: String,
    pub ty: String,
    pub instance_types: Vec<String>,
    pub trim_chars: Option<Vec<String>>,
    pub quoted_value: Option<(String, String)>,
    pub escape_replacements: Option<Vec<(String, String)>>,
    pub meta: Option<Meta>,
    /// A set: sorted, with no duplicate.
    pub class_types: Vec<String>,
}

impl Kind {
    fn new(variant: Variant, class: &str, ty: &str) -> Self {
        Kind {
            variant,
            class: class.to_string(),
            ty: ty.to_string(),
            instance_types: Vec::new(),
            trim_chars: None,
            quoted_value: None,
            escape_replacements: None,
            meta: None,
            class_types: Vec::new(),
        }
    }

    fn meta(ty: &str, meta: Meta) -> Self {
        Kind {
            meta: Some(meta),
            ..Kind::new(Variant::Meta, "", ty)
        }
    }

    fn with_class_types<'a>(mut self, types: impl IntoIterator<Item = &'a str>) -> Self {
        let set: BTreeSet<&str> = types.into_iter().collect();
        self.class_types = set.into_iter().map(str::to_string).collect();
        self
    }
}

/// The kwargs that a parser leaf takes from its token
/// (segment_kwargs_from_token): quoted_value and escape_replacements.
type TokenKwargs = (Option<(String, String)>, Option<Vec<(String, String)>>);

/// The result: the kinds, and the type names of the tables.
pub struct Kinds {
    pub kinds: BTreeSet<Kind>,
    /// Each type name of the tables and the lexers: segment types, class
    /// types, terminal types and instance types, lexer names. Each type of a
    /// kind is also in it.
    pub types: BTreeSet<String>,
}

/// Make the kinds of the named dialects.
pub fn kinds(dialect_names: &[String]) -> Result<Kinds, String> {
    let mut out = Kinds {
        kinds: BTreeSet::new(),
        types: BTreeSet::new(),
    };
    fixed_kinds(&mut out.kinds);
    for name in dialect_names {
        let dialect = Dialect::from_str(name).map_err(|_| format!("unknown dialect {name}"))?;
        dialect_kinds(dialect, &mut out)?;
    }
    for kind in &out.kinds {
        out.types.insert(kind.ty.clone());
        out.types.extend(kind.instance_types.iter().cloned());
        out.types.extend(kind.class_types.iter().cloned());
    }
    Ok(out)
}

/// The kinds that do not come from the tables.
fn fixed_kinds(kinds: &mut BTreeSet<Kind>) {
    // MatchedClass::root, MatchedClass::unparsable, MatchResult::bracketed.
    for (class, ty) in [
        ("Root", "file"),
        ("UnparsableSegment", "unparsable"),
        ("BracketedSegment", "bracketed"),
    ] {
        kinds.insert(Kind::new(Variant::Segment, class, ty).with_class_types(["base", ty]));
    }
    for implicit in [false, true] {
        kinds.insert(Kind::meta("indent", Meta::Indent { implicit }));
        kinds.insert(Kind::meta("dedent", Meta::Dedent { implicit }));
    }
    for block_type in BLOCK_TYPES {
        let block_type = block_type.to_string();
        kinds.insert(Kind::meta("placeholder", Meta::Template { block_type }));
    }
    kinds.insert(Kind::meta("template_loop", Meta::TemplateLoop));
    kinds.insert(Kind::meta("end_of_file", Meta::EndOfFile));
    // The parser does not make these two, but a Node can have them.
    kinds.insert(Kind::new(Variant::Unparsable, "", "unparsable"));
    kinds.insert(Kind::new(Variant::Empty, "", "empty"));
}

/// Each lexer matcher of the dialect, with its subdividers, and the last
/// resort lexer of sqll_lexer (Lexer::new with None).
fn matchers(dialect: Dialect) -> Vec<LexMatcher> {
    let mut stack: Vec<LexMatcher> = dialect.get_lexers().clone();
    stack.push(LexMatcher::regex_lexer(
        "<unlexable>",
        r#"[^\t\n\ ]*"#,
        Token::unlexable_token,
        None,
        |_| true,
        LexMatcherConfig::default(),
    ));
    let mut all = Vec::new();
    while let Some(m) = stack.pop() {
        stack.extend(m.subdivider.as_deref().cloned());
        stack.extend(m.trim_post_subdivide.as_deref().cloned());
        all.push(m);
    }
    all
}

fn group(g: &RegexModeGroup) -> String {
    match g {
        RegexModeGroup::Index(i) => i.to_string(),
        RegexModeGroup::Name(n) => n.clone(),
    }
}

fn dialect_kinds(dialect: Dialect, out: &mut Kinds) -> Result<(), String> {
    let file = Arc::new(TemplatedFile::new(
        "x".to_string(),
        "<kinds>".to_string(),
        None,
        None,
        None,
    ));
    let pos = PositionMarker::new(
        Slice::from(0..1),
        Slice::from(0..1),
        &file,
        Some(1),
        Some(1),
    );

    // Lexer leaves (token_to_node) and the token kwargs.
    let mut token_kwargs: BTreeSet<TokenKwargs> = BTreeSet::new();
    token_kwargs.insert((None, None));
    for m in matchers(dialect) {
        out.types.insert(m.name.clone());
        out.types.extend(m.kwarg_type.iter().cloned());
        let tok = m.construct_token("x", pos.clone());
        let ty = tok
            .instance_types
            .first()
            .cloned()
            .unwrap_or_else(|| tok.token_type.to_string());
        let mut kind = Kind::new(Variant::Raw, &tok.class_name, &ty);
        kind.instance_types = tok.instance_types.clone();
        let types = tok.instance_types.iter().map(String::as_str);
        let types = types.chain([ty.as_str()]);
        let types = types.chain(tok.class_types.iter().map(String::as_str));
        out.kinds.insert(kind.with_class_types(types));
        token_kwargs.insert((
            tok.quoted_value().map(|(p, g)| (p.clone(), group(g))),
            tok.escape_replacements().cloned(),
        ));
    }

    let root = dialect.get_root_grammar();
    let tables: &'static GrammarTables = root.tables;
    let ctx = GrammarContext::new(tables);
    for id in 0..tables.instructions.len() as u32 {
        let gid = GrammarId(id);
        if let Some(t) = ctx.segment_type(gid) {
            out.types.insert(t.to_string());
        }
        out.types
            .extend(ctx.segment_class_types(gid).unwrap_or_default());
        match ctx.variant(gid) {
            GrammarVariant::Ref => {
                // build_ref_wrap: a class or a non-empty type gives a segment.
                let class = ctx.segment_class(gid);
                let ty = ctx.segment_type(gid);
                if ty.is_some_and(|t| !t.is_empty()) || class.is_some() {
                    let ct = ctx.segment_class_types(gid).unwrap_or_default();
                    let kind = Kind::new(
                        Variant::Segment,
                        class.unwrap_or_default(),
                        ty.unwrap_or_default(),
                    );
                    out.kinds
                        .insert(kind.with_class_types(ct.iter().map(String::as_str)));
                }
            }
            GrammarVariant::StringParser
            | GrammarVariant::MultiStringParser
            | GrammarVariant::TypedParser
            | GrammarVariant::RegexParser => {
                let leaf = terminal(dialect, &ctx, gid)?;
                out.types.extend(leaf.instance_types.iter().cloned());
                out.types.extend(leaf.raw_class_types.iter().cloned());
                out.types.insert(leaf.ty.clone());
                for kwargs in &token_kwargs {
                    out.kinds.insert(leaf.kind(kwargs));
                }
            }
            _ => {}
        }
    }

    // The bracket symbols of match_bracket_recursively (core.rs).
    for pair in dialect.get_bracket_pairs().iter() {
        for ty in [pair.start_type, pair.end_type] {
            let leaf = Leaf {
                class: "SymbolSegment".to_string(),
                ty: ty.to_string(),
                instance_types: vec![ty.to_string()],
                raw_class_types: Vec::new(),
                trim_chars: None,
            };
            out.kinds.insert(leaf.kind(&(None, None)));
        }
    }
    Ok(())
}

/// The static data of a parser leaf before the token kwargs.
struct Leaf {
    class: String,
    ty: String,
    instance_types: Vec<String>,
    raw_class_types: Vec<String>,
    trim_chars: Option<Vec<String>>,
}

impl Leaf {
    /// The retag of MatchResult::apply: the instance types (or the type if
    /// there is none), and class types = instance types, type, and the class
    /// types of the raw class (Node::new_raw_with_class_types).
    fn kind(&self, (quoted, escapes): &TokenKwargs) -> Kind {
        let mut instance_types = self.instance_types.clone();
        if instance_types.is_empty() {
            instance_types.push(self.ty.clone());
        }
        let mut kind = Kind::new(Variant::Raw, &self.class, &self.ty);
        let types = instance_types.iter().map(String::as_str);
        let types = types.chain([self.ty.as_str()]);
        let types = types.chain(self.raw_class_types.iter().map(String::as_str));
        kind = kind.with_class_types(types);
        kind.instance_types = instance_types;
        kind.trim_chars = self.trim_chars.clone();
        kind.quoted_value = quoted.clone();
        kind.escape_replacements = escapes.clone();
        kind
    }
}

/// The aux data block of a grammar (aux_block_bounds, core.rs).
fn aux_bounds(tables: &GrammarTables, id: u32) -> (usize, usize) {
    let idx = id as usize;
    let start = tables.aux_data_offsets[idx] as usize;
    let next = tables
        .aux_data_offsets
        .get(idx + 1)
        .map(|&o| o as usize)
        .unwrap_or(tables.aux_data.len());
    let end = if next > start {
        next
    } else {
        tables.aux_data.len()
    };
    (start, end)
}

/// A count and the string ids after it (read_string_ids_from_aux, core.rs).
fn ids_after(tables: &GrammarTables, offset: usize, end: usize) -> Vec<u32> {
    if offset >= end {
        return Vec::new();
    }
    let count = tables.aux_data[offset] as usize;
    let start = offset + 1;
    let stop = start.saturating_add(count);
    if stop > end {
        return Vec::new();
    }
    tables.aux_data[start..stop]
        .iter()
        .copied()
        .filter(|&i| i != NONE)
        .collect()
}

/// The instance type ids and the raw class type ids of a terminal: the
/// "new schema" of the aux data (count, ids, count, ids) at `inst_at`, or
/// `default` for the old schema.
fn type_ids(
    tables: &GrammarTables,
    inst_at: usize,
    end: usize,
    default: Vec<u32>,
) -> (Vec<u32>, Vec<u32>) {
    if end > inst_at {
        let count = tables.aux_data[inst_at] as usize;
        let start = inst_at + 1;
        let stop = start.saturating_add(count);
        let inst = if stop <= end {
            tables.aux_data[start..stop]
                .iter()
                .copied()
                .filter(|&i| i != NONE)
                .collect()
        } else {
            default
        };
        (inst, ids_after(tables, stop, end))
    } else {
        (default, Vec::new())
    }
}

fn string(tables: &GrammarTables, id: u32) -> Result<String, String> {
    tables
        .strings
        .get(id as usize)
        .map(|s| s.to_string())
        .ok_or_else(|| format!("string id {id} is not in the table"))
}

fn strings(tables: &GrammarTables, ids: &[u32]) -> Result<Vec<String>, String> {
    ids.iter().map(|&i| string(tables, i)).collect()
}

/// The leaf of a terminal grammar (handle_string_parser,
/// handle_multi_string_parser, typed_parser_match, and the RegexParser
/// handler of core.rs).
fn terminal(dialect: Dialect, ctx: &GrammarContext, gid: GrammarId) -> Result<Leaf, String> {
    let tables = ctx.tables();
    let id = gid.0;
    let (start, end) = aux_bounds(tables, id);
    let aux = |i: usize| tables.aux_data[start + i];
    let variant = ctx.variant(gid);
    // The layout: StringParser and TypedParser [template, type, class, ...]
    // with the types at 3; MultiStringParser and RegexParser [x, y, type,
    // class, ...] with the types at 4.
    let (type_id, class_id, inst_at) = match variant {
        GrammarVariant::StringParser | GrammarVariant::TypedParser => (aux(1), aux(2), 3),
        _ => (aux(2), aux(3), 4),
    };
    let ty = if type_id == NONE {
        String::new()
    } else {
        string(tables, type_id)?
    };
    let class = match (variant, class_id) {
        (GrammarVariant::MultiStringParser, NONE) => "RawSegment".to_string(),
        _ => string(tables, class_id)?,
    };
    let default = match (variant, type_id) {
        (GrammarVariant::RegexParser, NONE) => Vec::new(),
        _ => vec![type_id],
    };
    let (inst_ids, ct_ids) = type_ids(tables, start + inst_at, end, default);
    let mut instance_types = strings(tables, &inst_ids)?;
    let raw_class_types = strings(tables, &ct_ids)?;
    let mut leaf_type = ty.clone();
    if variant == GrammarVariant::TypedParser {
        // The type and the instance types of typed_parser_match.
        let template = string(tables, aux(0))?;
        if instance_types.is_empty() {
            instance_types.push(ty.clone());
        }
        match dialect.get_segment_type(&class) {
            Some(cls_type) => {
                if !instance_types.iter().any(|t| t == cls_type) {
                    instance_types.push(cls_type.to_string());
                }
                if template != cls_type && !instance_types.iter().any(|t| *t == template) {
                    instance_types.push(template);
                }
            }
            None => {
                if template != ty && !instance_types.iter().any(|t| *t == template) {
                    instance_types.push(template);
                }
            }
        }
        leaf_type = instance_types.first().cloned().unwrap_or(ty);
    }
    Ok(Leaf {
        class,
        ty: leaf_type,
        instance_types,
        raw_class_types,
        trim_chars: ctx.trim_chars(gid),
    })
}

/// The Rust name of the constant of a type name: upper case, and "_" for
/// each other character.
pub fn const_name(name: &str) -> String {
    let mut out: String = name
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() {
                c.to_ascii_uppercase()
            } else {
                '_'
            }
        })
        .collect();
    if out.is_empty() {
        out = "EMPTY_NAME".to_string();
    }
    if out.starts_with(|c: char| c.is_ascii_digit() || c == '_') {
        out.insert_str(0, "T");
    }
    out
}

fn lit(s: &str) -> String {
    format!("{s:?}")
}

fn opt_strs(v: &Option<Vec<String>>) -> String {
    match v {
        None => "None".to_string(),
        Some(v) => format!(
            "Some(&[{}])",
            v.iter().map(|s| lit(s)).collect::<Vec<_>>().join(", ")
        ),
    }
}

/// The Rust code of OUT_DIR/kinds.rs. It fails if a count does not fit in
/// a u16, or if two type names have the same constant name.
pub fn code(k: &Kinds) -> Result<String, String> {
    let limit = u16::MAX as usize + 1;
    if k.types.len() > limit {
        return Err(format!("{} type names do not fit in a u16", k.types.len()));
    }
    if k.kinds.len() > limit {
        return Err(format!("{} kinds do not fit in a u16", k.kinds.len()));
    }
    let index: BTreeMap<&str, usize> = k
        .types
        .iter()
        .enumerate()
        .map(|(i, t)| (t.as_str(), i))
        .collect();
    let ty = |name: &str| format!("SegmentType({})", index[name]);
    let tys = |names: &[String]| names.iter().map(|n| ty(n)).collect::<Vec<_>>().join(", ");

    let mut s = String::new();
    s.push_str("// Generated by build.rs (build/kinds.rs). Do not edit.\n\n");
    writeln!(s, "pub(crate) const TYPE_COUNT: usize = {};", k.types.len()).unwrap();
    writeln!(
        s,
        "pub(crate) const KIND_COUNT: usize = {};\n",
        k.kinds.len()
    )
    .unwrap();

    writeln!(s, "pub(crate) static TYPE_NAMES: [&str; TYPE_COUNT] = [").unwrap();
    for t in &k.types {
        writeln!(s, "    {},", lit(t)).unwrap();
    }
    s.push_str("];\n\n");

    let mut names: BTreeMap<String, &str> = BTreeMap::new();
    s.push_str("#[allow(missing_docs)]\nimpl SegmentType {\n");
    for (i, t) in k.types.iter().enumerate() {
        let name = const_name(t);
        if let Some(other) = names.insert(name.clone(), t) {
            return Err(format!(
                "the type names {other:?} and {t:?} have one constant name {name}"
            ));
        }
        writeln!(s, "    pub const {name}: SegmentType = SegmentType({i});").unwrap();
    }
    s.push_str("}\n\n");

    let mut by_type: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
    writeln!(s, "pub(crate) static KINDS: [KindData; KIND_COUNT] = [").unwrap();
    for (i, kind) in k.kinds.iter().enumerate() {
        by_type.entry(index[kind.ty.as_str()]).or_default().push(i);
        let escapes = match &kind.escape_replacements {
            None => "None".to_string(),
            Some(v) => format!(
                "Some(&[{}])",
                v.iter()
                    .map(|(a, b)| format!("({}, {})", lit(a), lit(b)))
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
        };
        let quoted = match &kind.quoted_value {
            None => "None".to_string(),
            Some((a, b)) => format!("Some(({}, {}))", lit(a), lit(b)),
        };
        let meta = match &kind.meta {
            None => "None".to_string(),
            Some(Meta::Indent { implicit }) => {
                format!("Some(Meta::Indent {{ implicit: {implicit} }})")
            }
            Some(Meta::Dedent { implicit }) => {
                format!("Some(Meta::Dedent {{ implicit: {implicit} }})")
            }
            Some(Meta::Template { block_type }) => {
                format!("Some(Meta::Template {{ block_type: {} }})", lit(block_type))
            }
            Some(Meta::TemplateLoop) => "Some(Meta::TemplateLoop)".to_string(),
            Some(Meta::EndOfFile) => "Some(Meta::EndOfFile)".to_string(),
        };
        writeln!(
            s,
            "    KindData {{ variant: Variant::{:?}, class: {}, ty: {}, instance_types: &[{}], \
             trim_chars: {}, quoted_value: {}, escape_replacements: {}, meta: {}, \
             class_types: &[{}] }},",
            kind.variant,
            lit(&kind.class),
            ty(&kind.ty),
            tys(&kind.instance_types),
            opt_strs(&kind.trim_chars),
            quoted,
            escapes,
            meta,
            tys(&kind.class_types),
        )
        .unwrap();
    }
    s.push_str("];\n\n");

    // The kinds of each type: a start offset for each type, and the kinds.
    let mut starts = Vec::with_capacity(k.types.len() + 1);
    let mut flat = Vec::with_capacity(k.kinds.len());
    for t in 0..k.types.len() {
        starts.push(flat.len());
        flat.extend(by_type.get(&t).into_iter().flatten().copied());
    }
    starts.push(flat.len());
    writeln!(
        s,
        "pub(crate) static KINDS_OF_TYPE_START: [u32; TYPE_COUNT + 1] = {starts:?};"
    )
    .unwrap();
    let flat: Vec<String> = flat.iter().map(|i| format!("SegmentKind({i})")).collect();
    writeln!(
        s,
        "pub(crate) static KINDS_OF_TYPE: [SegmentKind; KIND_COUNT] = [{}];",
        flat.join(", ")
    )
    .unwrap();
    Ok(s)
}
