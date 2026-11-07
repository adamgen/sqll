//! The interface test of the typed view (docs/interfaces/typed-view.md, S3b
//! task C10).
//!
//! - The signatures of the interface are those of the document (a change
//!   does not compile).
//! - The crawl: for each case of the record `results/S3b/C10-crawl.json`
//!   (scripts/s3b/crawl_oracle.py), `NodeRef::crawl` on the sqll tree of the
//!   dialect fixture gives the segments of the sqlfluff `recursive_crawl`
//!   (type and raw, in order). For each YAML case, the same crawl on the
//!   fixture YAML gives the code segments of the sqll crawl: these expected
//!   values come from the YAML file, with no sqlfluff run.
//! - The typed nodes: the accessors on the trees of the cited fixtures give
//!   the kinds and raws of their YAML files (in the comments), and the
//!   placeholders of a Jinja fixture give the sqlfluff data of the record
//!   of C8.

use std::str::FromStr;

use serde_json::Value;
use serde_yaml_ng::Value as Yaml;
use sqll_dialects::Dialect;
use sqll_interfaces::{root, with_parse_stack};
use sqll_source::{
    RawFileSlice, Slice, TemplatedFile, TemplatedFileSlice, Templater, TemplaterConfig,
};
use sqll_syntax::{parse, ParseOptions};
use sqll_templater::RawTemplater;
use sqll_tree::view::nodes::{
    AliasExpression, ColumnReference, File, FromClause, FromExpression, FromExpressionElement,
    Identifier, Keyword, Literal, Placeholder, SelectClause, SelectClauseElement, SelectStatement,
    Statement, TableReference,
};
use sqll_tree::{AstNode, Crawl, NodeId, NodeRef, SegmentKind, SegmentType, SyntaxTree};

const RECORD: &str = "results/S3b/C10-crawl.json";
const KIND: &str = "sqll-s3b-c10-crawl";
/// The record of C8 (docs/interfaces/source-map.md) and its Jinja fixture
/// with placeholders.
const C8_RECORD: &str = "results/S3b/C8-source-map.json";
const JINJA_B: &str = "test/fixtures/templater/jinja_b/jinja.sql";

/// The signatures of the interface. A change of one of them is a change of
/// the frozen interface: this function does not compile.
#[allow(dead_code)]
fn signatures<'t>(tree: &'t SyntaxTree, n: NodeRef<'t>, types: &'t [SegmentType]) {
    let _: fn(&'t SyntaxTree, NodeId) -> NodeRef<'t> = NodeRef::new;
    let _: NodeRef<'t> = tree.node(NodeId::ROOT);
    let _: NodeRef<'t> = tree.root_node();
    let _: (&SyntaxTree, NodeId, SegmentKind, SegmentType) = (n.tree(), n.id(), n.kind(), n.ty());
    let _: (bool, bool, bool, bool) = (
        n.is_type(SegmentType::KEYWORD),
        n.is_any_type(types),
        n.is_code(),
        n.is_meta(),
    );
    let _: (&'t str, std::ops::Range<usize>) = (n.raw(), n.range());
    let _: Option<NodeRef<'t>> = n.parent();
    let _: Vec<NodeRef<'t>> = n.children().chain(n.descendants()).collect();
    let _: Option<NodeRef<'t>> = n.child(types);
    let _: Vec<NodeRef<'t>> = n.children_of(types).collect();
    let _: Option<NodeRef<'t>> = n.first_descendant(types);
    let _: Option<NodeRef<'t>> = n.first_code_child();
    let c: Crawl<'t, 't> = n.crawl(types);
    let _: Vec<NodeRef<'t>> = c
        .recurse_into(false)
        .no_recursive(types)
        .allow_self(false)
        .collect();
    let _: Option<File<'t>> = n.cast();
    let _: Option<Keyword<'t>> = n.child_as();
    let _: Vec<Statement<'t>> = n.children_as().collect();
    let _: Vec<Literal<'t>> = n.descendants_as().collect();
    let _: fn(SegmentKind) -> bool = <Placeholder<'t> as AstNode<'t>>::can_cast;
    let _: fn(NodeRef<'t>) -> Option<Identifier<'t>> = <Identifier<'t> as AstNode<'t>>::cast;
    let _: fn(Keyword<'t>) -> NodeRef<'t> = <Keyword<'t> as AstNode<'t>>::node;
}

/// The signatures of the typed nodes of the core set.
#[allow(dead_code)]
fn node_signatures<'t>(
    (file, st, sel, sc): (
        File<'t>,
        Statement<'t>,
        SelectStatement<'t>,
        SelectClause<'t>,
    ),
    (el, fc, fe, fel): (
        SelectClauseElement<'t>,
        FromClause<'t>,
        FromExpression<'t>,
        FromExpressionElement<'t>,
    ),
    (tr, cr, al, kw, id, ph): (
        TableReference<'t>,
        ColumnReference<'t>,
        AliasExpression<'t>,
        Keyword<'t>,
        Identifier<'t>,
        Placeholder<'t>,
    ),
) {
    let _: Vec<Statement<'t>> = file.statements().collect();
    let _: (Option<NodeRef<'t>>, Option<SelectStatement<'t>>) = (st.inner(), st.select_statement());
    let _: (Option<SelectClause<'t>>, Option<FromClause<'t>>) =
        (sel.select_clause(), sel.from_clause());
    let _: Vec<SelectClauseElement<'t>> = sc.elements().collect();
    let _: (
        Option<AliasExpression<'t>>,
        Option<NodeRef<'t>>,
        Option<ColumnReference<'t>>,
    ) = (el.alias(), el.value(), el.column_reference());
    let _: Vec<FromExpression<'t>> = fc.from_expressions().collect();
    let _: Vec<FromExpressionElement<'t>> = fe.elements().collect();
    let _: (Option<TableReference<'t>>, Option<AliasExpression<'t>>) =
        (fel.table_reference(), fel.alias());
    let _: Vec<Identifier<'t>> = tr.parts().chain(cr.parts()).collect();
    let _: (
        Option<Identifier<'t>>,
        Option<NodeRef<'t>>,
        Option<Keyword<'t>>,
    ) = (al.identifier(), al.operator(), al.as_keyword());
    let _: bool = kw.is("AS") && id.is_quoted();
    let _: (&'static str, &'t str) = (ph.block_type(), ph.source_str());
}

/// The text of a file of the sqlfluff submodule.
fn sqlfluff_file(rel: &str) -> String {
    let path = root().join("third_party/sqlfluff").join(rel);
    std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

fn read_json(rel: &str) -> Value {
    let text = std::fs::read_to_string(root().join(rel)).unwrap_or_else(|e| panic!("{rel}: {e}"));
    serde_json::from_str(&text).expect("JSON")
}

/// The dialect of a dialect fixture: its folder.
fn dialect_of(path: &str) -> Dialect {
    let name = path.rsplit('/').nth(1).expect("a folder");
    Dialect::from_str(name).unwrap_or_else(|_| panic!("no dialect {name}"))
}

/// The sqll tree of a templated file (the parse interface).
fn parse_file(file: TemplatedFile, dialect: Dialect) -> SyntaxTree {
    with_parse_stack(move || {
        let parsed = parse(&file, dialect, &ParseOptions::default()).expect("a parse");
        assert!(parsed.errors.is_empty(), "{:?}", parsed.errors);
        parsed.tree.expect("a tree")
    })
}

/// The sqll tree of a dialect fixture (`test/fixtures/dialects/...`),
/// through the raw templater, as `sqll parse`.
fn fixture_tree(path: &str) -> SyntaxTree {
    let sql = sqlfluff_file(path);
    let file = RawTemplater
        .process(&sql, path, &TemplaterConfig::new())
        .expect("the raw templater");
    parse_file(file, dialect_of(path))
}

fn ty(name: &str) -> SegmentType {
    SegmentType::from_name(name).unwrap_or_else(|| panic!("no type {name}"))
}

fn types(v: &Value) -> Vec<SegmentType> {
    v.as_array()
        .expect("a list")
        .iter()
        .map(|t| ty(t.as_str().expect("a type")))
        .collect()
}

/// The start node of a case: the root, or the n-th code node of a type in
/// pre-order.
fn start_node<'t>(tree: &'t SyntaxTree, start: &Value) -> Option<NodeRef<'t>> {
    if start.is_null() {
        return Some(tree.root_node());
    }
    let t = ty(start[0].as_str().expect("a type"));
    let n = start[1].as_u64().expect("a number") as usize;
    std::iter::once(tree.root_node())
        .chain(tree.root_node().descendants())
        .filter(|d| d.ty() == t && d.is_code())
        .nth(n)
}

/// The raw of the code leaves of a node (as the YAML shows them).
fn code_raw(n: NodeRef<'_>) -> String {
    std::iter::once(n)
        .chain(n.descendants())
        .filter(|d| d.children().next().is_none() && d.is_code())
        .map(|d| d.raw())
        .collect()
}

/// A node of the fixture YAML: its type, and its raw (a leaf) or its
/// children.
enum YamlNode {
    Leaf(String, String),
    Segment(String, Vec<YamlNode>),
}

impl YamlNode {
    fn key(&self) -> &str {
        match self {
            YamlNode::Leaf(k, _) | YamlNode::Segment(k, _) => k,
        }
    }

    fn raw(&self) -> String {
        match self {
            YamlNode::Leaf(_, raw) => raw.clone(),
            YamlNode::Segment(_, children) => children.iter().map(YamlNode::raw).collect(),
        }
    }

    fn preorder<'a>(&'a self, out: &mut Vec<&'a YamlNode>) {
        out.push(self);
        if let YamlNode::Segment(_, children) = self {
            for c in children {
                c.preorder(out);
            }
        }
    }

    /// The sqlfluff `recursive_crawl` on the YAML tree: the key is the type.
    fn crawl<'a>(
        &'a self,
        types: &[&str],
        recurse_into: bool,
        no_recursive: &[&str],
        allow_self: bool,
        out: &mut Vec<&'a YamlNode>,
    ) {
        let matched = allow_self && types.contains(&self.key());
        if matched {
            out.push(self);
        }
        if let YamlNode::Segment(_, children) = self {
            if matched && !recurse_into {
                return;
            }
            for c in children {
                if !no_recursive.contains(&c.key()) {
                    c.crawl(types, recurse_into, no_recursive, true, out);
                }
            }
        }
    }
}

/// The YAML tree of a value of the sqlfluff `as_record` format (the
/// structure of `process_struct` of the sqlfluff test/conftest.py).
fn yaml_node(key: &str, value: &Yaml) -> YamlNode {
    match value {
        Yaml::String(raw) => YamlNode::Leaf(key.into(), raw.clone()),
        Yaml::Null => YamlNode::Segment(key.into(), Vec::new()),
        Yaml::Mapping(m) => YamlNode::Segment(
            key.into(),
            m.iter()
                .map(|(k, v)| yaml_node(k.as_str().expect("a key"), v))
                .collect(),
        ),
        Yaml::Sequence(items) => YamlNode::Segment(
            key.into(),
            items
                .iter()
                .map(|item| {
                    let m = item.as_mapping().expect("a mapping");
                    assert_eq!(m.len(), 1, "one key in a list item");
                    let (k, v) = m.iter().next().unwrap();
                    yaml_node(k.as_str().expect("a key"), v)
                })
                .collect(),
        ),
        other => panic!("a YAML value that is not a string: {other:?}"),
    }
}

/// The YAML tree of a dialect fixture (`<name>.yml` next to `<name>.sql`).
fn fixture_yaml(path: &str) -> YamlNode {
    let yml = format!("{}.yml", path.strip_suffix(".sql").expect("a .sql path"));
    let value: Yaml = serde_yaml_ng::from_str(&sqlfluff_file(&yml)).expect("YAML");
    let m = value.as_mapping().expect("a mapping");
    let mut items = m.iter().filter(|(k, _)| k.as_str() != Some("_hash"));
    let (k, v) = items.next().expect("the root");
    assert!(items.next().is_none(), "one root");
    yaml_node(k.as_str().expect("a key"), v)
}

/// The counts of the checked cases.
#[derive(Default, Debug, PartialEq)]
struct Counts {
    cases: usize,
    yaml_cases: usize,
    segments: usize,
}

/// Check one case of the record on the tree and the YAML of its fixture.
fn check_case(
    tree: &SyntaxTree,
    yaml: &YamlNode,
    case: &Value,
    counts: &mut Counts,
) -> Result<(), String> {
    let want = &case["crawl"];
    let wanted_types = types(&case["types"]);
    let stops = types(&case["no_recursive"]);
    let recurse_into = case["recurse_into"].as_bool().expect("recurse_into");
    let allow_self = case["allow_self"].as_bool().expect("allow_self");

    // The YAML flag: no node has one of the types only as a class type.
    let class_only = tree
        .root_node()
        .descendants()
        .chain([tree.root_node()])
        .any(|n| {
            wanted_types
                .iter()
                .chain(&stops)
                .any(|&t| n.is_type(t) && n.ty() != t)
        });
    let yaml_case = case["yaml"].as_bool().expect("yaml");
    if yaml_case == class_only {
        return Err(format!(
            "the YAML flag is {yaml_case}, but class only is {class_only}"
        ));
    }

    let Some(start) = start_node(tree, &case["start"]) else {
        return match want {
            Value::Null => Ok(()),
            _ => Err("no start node".into()),
        };
    };
    if want.is_null() {
        return Err(format!("a start node {start:?}, but sqlfluff has none"));
    }
    let got: Vec<NodeRef> = start
        .crawl(&wanted_types)
        .recurse_into(recurse_into)
        .no_recursive(&stops)
        .allow_self(allow_self)
        .collect();
    let got_json: Vec<Value> = got
        .iter()
        .map(|n| serde_json::json!([n.ty().name(), n.raw()]))
        .collect();
    if &Value::Array(got_json.clone()) != want {
        return Err(format!("the crawl is {got_json:?}, not {want}"));
    }
    counts.cases += 1;
    counts.segments += got.len();
    if !yaml_case {
        return Ok(());
    }
    counts.yaml_cases += 1;

    // The crawl on the YAML tree, from the same start node.
    let names = |v: &Value| -> Vec<String> {
        v.as_array()
            .unwrap()
            .iter()
            .map(|t| t.as_str().unwrap().to_string())
            .collect()
    };
    let (type_names, stop_names) = (names(&case["types"]), names(&case["no_recursive"]));
    let type_refs: Vec<&str> = type_names.iter().map(String::as_str).collect();
    let stop_refs: Vec<&str> = stop_names.iter().map(String::as_str).collect();
    let mut all = Vec::new();
    yaml.preorder(&mut all);
    let ystart = match &case["start"] {
        Value::Null => Some(yaml),
        s => {
            let t = s[0].as_str().unwrap();
            all.iter()
                .filter(|n| n.key() == t)
                .nth(s[1].as_u64().unwrap() as usize)
                .copied()
        }
    };
    let ystart = ystart.ok_or("no YAML start node")?;
    let mut ycrawl = Vec::new();
    ystart.crawl(
        &type_refs,
        recurse_into,
        &stop_refs,
        allow_self,
        &mut ycrawl,
    );
    let from_yaml: Vec<(String, String)> = ycrawl
        .iter()
        .map(|n| (n.key().to_string(), n.raw()))
        .collect();
    let from_sqll: Vec<(String, String)> = got
        .iter()
        .filter(|n| n.is_code())
        .map(|n| (n.ty().name().to_string(), code_raw(*n)))
        .collect();
    if from_yaml != from_sqll {
        return Err(format!(
            "the YAML crawl is {from_yaml:?}, the sqll crawl {from_sqll:?}"
        ));
    }
    Ok(())
}

#[test]
fn each_crawl_is_that_of_sqlfluff_and_of_the_fixture_yaml() {
    let record = read_json(RECORD);
    assert_eq!(record["kind"], KIND);
    assert_eq!(record["sqlfluff"]["version"], "4.4.0");
    let mut counts = Counts::default();
    let mut problems = Vec::new();
    let fixtures = record["fixtures"].as_array().expect("fixtures");
    for fx in fixtures {
        let path = fx["path"].as_str().expect("a path");
        let tree = fixture_tree(path);
        let yaml = fixture_yaml(path);
        for (i, case) in fx["cases"].as_array().expect("cases").iter().enumerate() {
            if let Err(e) = check_case(&tree, &yaml, case, &mut counts) {
                problems.push(format!("{path} case {i}: {e}"));
            }
        }
    }
    assert_eq!(problems, Vec::<String>::new());
    let c = &record["counts"];
    let want = Counts {
        cases: c["cases"].as_u64().unwrap() as usize,
        yaml_cases: c["yaml_cases"].as_u64().unwrap() as usize,
        segments: c["segments"].as_u64().unwrap() as usize,
    };
    assert_eq!(counts, want);
    eprintln!(
        "typed view: {} of {} crawl cases as sqlfluff ({} fixtures, {} segments; {} cases also as the fixture YAML)",
        counts.cases,
        want.cases,
        fixtures.len(),
        counts.segments,
        counts.yaml_cases
    );
}

fn raws<'t, N: AstNode<'t>>(nodes: impl Iterator<Item = N>) -> Vec<&'t str> {
    nodes.map(|n| n.node().raw()).collect()
}

fn type_names<'t>(nodes: impl Iterator<Item = NodeRef<'t>>) -> Vec<&'static str> {
    nodes.map(|n| n.ty().name()).collect()
}

/// The first statement of a fixture as a select statement.
fn first_select(file: File<'_>) -> SelectStatement<'_> {
    file.statements()
        .next()
        .expect("a statement")
        .select_statement()
        .expect("a select statement")
}

#[test]
fn the_typed_nodes_of_select_a() {
    // ansi/select_a.yml: file > statement > select_statement > select_clause
    // (keyword select, three select_clause_element with a column_reference
    // naked_identifier a, b, c) and from_clause (keyword from,
    // from_expression > from_expression_element > table_expression >
    // table_reference: naked_identifier sch, dot, quoted_identifier "blah").
    let tree = fixture_tree("test/fixtures/dialects/ansi/select_a.sql");
    let file: File = tree.root_node().cast().expect("a file");
    assert_eq!(file.statements().count(), 1);
    let statement = file.statements().next().unwrap();
    assert_eq!(
        statement.inner().unwrap().ty(),
        SegmentType::SELECT_STATEMENT
    );
    let select = first_select(file);
    let clause = select.select_clause().expect("a select clause");
    assert!(clause.child_as::<Keyword>().unwrap().is("SELECT"));
    assert_eq!(raws(clause.elements()), ["a", "b", "c"]);
    for element in clause.elements() {
        assert!(element.alias().is_none());
        let column = element.column_reference().expect("a column reference");
        assert_eq!(Some(column.node()), element.value());
        let parts: Vec<_> = column.parts().map(|p| p.ty().name()).collect();
        assert_eq!(parts, ["naked_identifier"]);
    }
    let from = select.from_clause().expect("a from clause");
    let expressions: Vec<FromExpression> = from.from_expressions().collect();
    assert_eq!(raws(expressions.iter().copied()), ["sch.\"blah\""]);
    let elements: Vec<_> = expressions[0].elements().collect();
    assert_eq!(raws(elements.iter().copied()), ["sch.\"blah\""]);
    let table = elements[0].table_reference().expect("a table reference");
    let parts: Vec<(&str, &str, bool)> = table
        .parts()
        .map(|p| (p.ty().name(), p.raw(), p.is_quoted()))
        .collect();
    assert_eq!(
        parts,
        [
            ("naked_identifier", "sch", false),
            ("quoted_identifier", "\"blah\"", true)
        ]
    );
    // dot is not an identifier.
    assert_eq!(
        type_names(table.children().filter(|c| c.is_code())),
        ["naked_identifier", "dot", "quoted_identifier"]
    );
    assert!(elements[0].alias().is_none());
    assert_eq!(tree.root_node().descendants_as::<Literal>().count(), 0);
}

#[test]
fn the_typed_nodes_of_select_simple_e() {
    // ansi/select_simple_e.yml: two select_clause_element, each with an
    // expression > cast_expression (column_reference my_var, or
    // numeric_literal 123) and an alias_expression (alias_operator > keyword
    // as, naked_identifier casted_variable or another_casted_number); the
    // table_reference boo.
    let tree = fixture_tree("test/fixtures/dialects/ansi/select_simple_e.sql");
    let file: File = tree.root_node().cast().unwrap();
    let select = first_select(file);
    let elements: Vec<SelectClauseElement> = select.select_clause().unwrap().elements().collect();
    assert_eq!(
        raws(elements.iter().copied()),
        [
            "my_var::date as casted_variable",
            "123::bigint as another_casted_number"
        ]
    );
    assert_eq!(
        type_names(elements.iter().filter_map(|e| e.value())),
        ["expression", "expression"]
    );
    assert!(elements.iter().all(|e| e.column_reference().is_none()));
    let aliases: Vec<(&str, &str, &str)> = elements
        .iter()
        .map(|e| {
            let alias = e.alias().expect("an alias");
            (
                alias.operator().unwrap().ty().name(),
                alias.as_keyword().unwrap().raw(),
                alias.identifier().unwrap().raw(),
            )
        })
        .collect();
    assert_eq!(
        aliases,
        [
            ("alias_operator", "as", "casted_variable"),
            ("alias_operator", "as", "another_casted_number")
        ]
    );
    let literals: Vec<(&str, &str)> = tree
        .root_node()
        .descendants_as::<Literal>()
        .map(|l| (l.ty().name(), l.raw()))
        .collect();
    assert_eq!(literals, [("numeric_literal", "123")]);
    let columns: Vec<ColumnReference> = tree.root_node().descendants_as().collect();
    assert_eq!(raws(columns.into_iter()), ["my_var"]);
    let table = select
        .from_clause()
        .unwrap()
        .from_expressions()
        .next()
        .unwrap();
    let table = table.elements().next().unwrap().table_reference().unwrap();
    assert_eq!(raws(table.parts()), ["boo"]);
}

#[test]
fn the_typed_nodes_of_select_many_join() {
    // ansi/select_many_join.yml, the first statement: from_clause with three
    // from_expression (a as foo JOIN b JOIN c as foobar JOIN d; e as bar JOIN
    // f JOIN g('blah') as tbl_func JOIN h; baz as buzz). Each join_clause has
    // one from_expression_element; g('blah') is a function in the
    // table_expression, not a table_reference.
    let tree = fixture_tree("test/fixtures/dialects/ansi/select_many_join.sql");
    let file: File = tree.root_node().cast().unwrap();
    assert_eq!(file.statements().count(), 2);
    let select = first_select(file);
    let element = select.select_clause().unwrap().elements().next().unwrap();
    assert_eq!(
        element.value().unwrap().ty(),
        SegmentType::WILDCARD_EXPRESSION
    );
    let expressions: Vec<FromExpression> =
        select.from_clause().unwrap().from_expressions().collect();
    let elements: Vec<Vec<(&str, Option<&str>, Option<&str>)>> = expressions
        .iter()
        .map(|e| {
            e.elements()
                .map(|el| {
                    (
                        el.raw(),
                        el.table_reference().map(|t| t.raw()),
                        el.alias().and_then(|a| a.identifier()).map(|i| i.raw()),
                    )
                })
                .collect()
        })
        .collect();
    assert_eq!(
        elements,
        [
            vec![
                ("a as foo", Some("a"), Some("foo")),
                ("b", Some("b"), None),
                ("c as foobar", Some("c"), Some("foobar")),
                ("d", Some("d"), None),
            ],
            vec![
                ("e as bar", Some("e"), Some("bar")),
                ("f", Some("f"), None),
                ("g('blah') as tbl_func", None, Some("tbl_func")),
                ("h", Some("h"), None),
            ],
            vec![("baz as buzz", Some("baz"), Some("buzz"))],
        ]
    );
    let literals: Vec<Literal> = tree.root_node().descendants_as().collect();
    assert_eq!(raws(literals.into_iter()), ["'blah'"]);
}

#[test]
fn the_statements_of_a_batch() {
    // tsql/multi_statement.yml: file > batch with statement_terminator,
    // statement_terminator, statement (SELECT * FROM my_table),
    // statement_terminator.
    let tree = fixture_tree("test/fixtures/dialects/tsql/multi_statement.sql");
    let file: File = tree.root_node().cast().unwrap();
    assert_eq!(
        type_names(file.children().filter(|c| c.is_code())),
        ["batch"]
    );
    assert_eq!(raws(file.statements()), ["SELECT * FROM my_table"]);
    // bigquery/select_example.yml: one statement, a with_compound_statement.
    let tree = fixture_tree("test/fixtures/dialects/bigquery/select_example.sql");
    let file: File = tree.root_node().cast().unwrap();
    let statements: Vec<Statement> = file.statements().collect();
    assert_eq!(statements.len(), 1);
    assert_eq!(
        statements[0].inner().unwrap().ty(),
        SegmentType::WITH_COMPOUND_STATEMENT
    );
    assert!(statements[0].select_statement().is_none());
}

/// The `TemplatedFile` of a fixture of the C8 record (offsets in code
/// points), with the source text of the fixture file.
fn record_file(fx: &Value) -> TemplatedFile {
    let num = |v: &Value| v.as_u64().expect("a number") as usize;
    let path = fx["path"].as_str().unwrap();
    let source = sqlfluff_file(path);
    let chars: Vec<char> = source.chars().collect();
    let slices = fx["sliced_file"]
        .as_array()
        .unwrap()
        .iter()
        .map(|s| {
            TemplatedFileSlice::new(
                s[0].as_str().unwrap().into(),
                Slice::from(num(&s[1])..num(&s[2])),
                Slice::from(num(&s[3])..num(&s[4])),
            )
        })
        .collect();
    let raws = fx["raw_sliced"].as_array().unwrap();
    let raw_sliced = raws
        .iter()
        .enumerate()
        .map(|(i, r)| {
            let start = num(&r[1]);
            let end = raws.get(i + 1).map_or(chars.len(), |n| num(&n[1]));
            RawFileSlice::new(
                chars[start..end].iter().collect(),
                r[0].as_str().unwrap().into(),
                start,
                Some(num(&r[2])),
                r[3].as_str().map(String::from),
            )
        })
        .collect();
    TemplatedFile::new(
        source,
        path.into(),
        Some(fx["templated_str"].as_str().unwrap().into()),
        Some(slices),
        Some(raw_sliced),
    )
}

#[test]
fn the_placeholders_of_a_jinja_file_are_those_of_sqlfluff() {
    // sqlfluff: the block_type and the source_str of each placeholder of
    // the Jinja fixture (the record of this task).
    let record = read_json(RECORD);
    let templated = &record["templated"];
    assert_eq!(templated["path"], JINJA_B);
    assert_eq!(templated["templater"], "jinja");
    assert_eq!(templated["dialect"], "ansi");
    let want: Vec<(String, String)> = templated["placeholders"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| (p[0].as_str().unwrap().into(), p[1].as_str().unwrap().into()))
        .collect();
    assert_eq!(want.len(), 7);
    // The templated file: the slices of the record of C8.
    let c8 = read_json(C8_RECORD);
    let fx = c8["fixtures"]
        .as_array()
        .unwrap()
        .iter()
        .find(|f| f["path"] == JINJA_B)
        .expect("the jinja_b fixture");
    let tree = parse_file(record_file(fx), Dialect::from_str("ansi").unwrap());
    let got: Vec<(String, String)> = tree
        .root_node()
        .descendants_as::<Placeholder>()
        .map(|p| (p.block_type().to_string(), p.source_str().to_string()))
        .collect();
    assert_eq!(got, want);
    // A placeholder is a meta node: not code, and no templated text. Its
    // class types are those of the sqlfluff TemplateSegment.
    for p in tree.root_node().descendants_as::<Placeholder>() {
        assert!(p.is_meta() && !p.is_code() && p.raw().is_empty());
        let names: Vec<&str> = p
            .kind()
            .data()
            .class_types
            .iter()
            .map(|t| t.name())
            .collect();
        assert_eq!(names, ["base", "meta", "placeholder", "raw"]);
    }
    let crawled = tree.root_node().crawl(&[SegmentType::PLACEHOLDER]).count();
    assert_eq!(crawled, 7);
}
