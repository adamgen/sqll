//! The interface test of the rule and fix interface (`sqll_lint`;
//! docs/interfaces/rules.md; S3b task C12).
//!
//! - The signatures of the interface (`signatures`).
//! - The rule manifest and the config validation of `sqll_lint` are those of
//!   the pinned sqlfluff (record results/S3b/C12-rules.json,
//!   scripts/s3b/rules_oracle.py).
//! - The registry: the check of the rule metadata, and the selection of the
//!   rules of a config as sqlfluff, which fails closed for a rule that sqll
//!   does not have.
//! - A test rule and its fixes through a templated source map: a test
//!   templater that gives the C8 hand-built map of jinja_a (the slices of
//!   the pinned sqlfluff Jinja templater), a fix that round-trips through
//!   it, and a fix in a templated range that the source map refuses.
//! - The fix loop: the runaway limit, conflicting and overlapping fixes, a
//!   fix that makes the file unparsable, the post phase, and the noqa check.

use std::ops::Range;
use std::str::FromStr;
use std::sync::Mutex;

use serde_json::Value as Json;
use sqll_config::{Config, Table, Value};
use sqll_interfaces::root;
use sqll_lint::fix::{check_anchors, result_edits};
use sqll_lint::{
    apply_edits, CrawlBehaviour, Edit, Fix, FixRefusal, LintError, LintPhase, LintResult,
    LintSettings, LintedFile, Linter, Memory, Registry, Rule, RuleConfig, RuleContext, RulePack,
    SourceEdit, SourceParser, SqlfluffRule, TemplaterParser, Valid, Validation, Violation,
    CONFIG_VALIDATION, RULES,
};
use sqll_source::{
    LinePos, RawFileSlice, Slice, SourceMap, Templater, TemplatedFile, TemplatedFileSlice,
    TemplaterConfig, TemplaterError,
};
use sqll_syntax::{Dialect, ParseOptions, Parsed};
use sqll_tree::{NodeId, NodeRef, SegmentType, SyntaxTree};

const RECORD: &str = "results/S3b/C12-rules.json";

/// The signatures of the interface. A change of one of them is a change of
/// the frozen interface: this function does not compile.
#[allow(dead_code)]
fn signatures(
    rule: &dyn Rule,
    ctx: &mut RuleContext<'_, '_>,
    tree: &SyntaxTree,
    registry: &Registry,
    config: &Config,
    pack: &RulePack<'_>,
) {
    let _: (&'static str, &'static str, &'static str) =
        (rule.code(), rule.name(), rule.description());
    let _: (&'static [&'static str], &'static [&'static str]) = (rule.groups(), rule.aliases());
    let _: &'static [&'static str] = rule.config_keywords();
    let _: (LintPhase, bool, bool) = (
        rule.lint_phase(),
        rule.is_fix_compatible(),
        rule.targets_templated(),
    );
    let _: CrawlBehaviour = rule.crawl_behaviour();
    let _: Result<(), LintError> = rule.check_config(&RuleConfig::new(config, "x"));
    let _: Result<Vec<LintResult>, LintError> = rule.eval(ctx);

    let _: (NodeRef<'_>, Dialect, &RuleConfig) = (ctx.segment, ctx.dialect, ctx.config);
    let _: &mut Memory = ctx.memory;
    let _: Option<NodeRef<'_>> = ctx.parent();
    let _: Vec<NodeRef<'_>> = ctx.parent_stack();
    let _: &SyntaxTree = ctx.tree();
    let _: &mut u8 = Memory::default().get_or_default::<u8>();

    let _: fn(&'static [SegmentType]) -> CrawlBehaviour = CrawlBehaviour::seeker;
    let _: fn() -> CrawlBehaviour = CrawlBehaviour::root_only;
    let _: fn(&CrawlBehaviour, &SyntaxTree) -> Vec<NodeId> = CrawlBehaviour::crawl;
    let _: fn(&CrawlBehaviour, NodeRef<'_>) -> bool = CrawlBehaviour::passes_filter;

    let r: LintResult = LintResult::new(NodeId::ROOT)
        .with_description("d")
        .with_fix(Fix::Delete {
            anchor: NodeId::ROOT,
        });
    let _: (NodeId, Option<String>, Vec<Fix>) = (r.anchor, r.description, r.fixes);
    let f = Fix::Replace {
        anchor: NodeId::ROOT,
        text: String::new(),
    };
    let _: (NodeId, &'static str, Edit) = (f.anchor(), f.edit_type(), f.edit(tree));
    let _: Result<Option<SourceEdit>, FixRefusal> = f.source_edit(tree);
    let _: fn(&str, &[(SourceEdit, bool)]) -> Option<String> = apply_edits;

    let _: fn(Vec<Box<dyn Rule>>) -> Result<Registry, String> = Registry::new;
    let _: Result<RulePack<'_>, LintError> = registry.select(config);
    let _: Option<&dyn Rule> = registry.get("CP01");
    let _: &Vec<(&dyn Rule, RuleConfig)> = &pack.rules;
    let _: fn(&Config, &str) -> RuleConfig = RuleConfig::new;
    let _: fn(&Config) -> Result<LintSettings, LintError> = LintSettings::from_config;
    let s = LintSettings::default();
    let _: (i64, bool, bool) = (s.runaway_limit, s.ignore_templated_areas, s.reads_noqa);

    let linter = Linter {
        pack,
        settings: s,
        dialect: Dialect::from_str("ansi").unwrap(),
    };
    let mut parser = TemplaterParser {
        templater: &sqll_templater::RawTemplater,
        config: TemplaterConfig::new(),
        fname: String::new(),
        dialect: linter.dialect,
        options: ParseOptions::default(),
    };
    let _: Result<Parsed, LintError> = parser.parse("");
    let out: Result<LintedFile, LintError> = linter.lint("", &mut parser, true);
    let out = out.unwrap();
    let _: (String, Vec<Violation>, Vec<String>) = (out.fixed, out.violations, out.warnings);
    let v = &out_violation();
    let _: (&str, &str, &String, &Range<usize>, LinePos, LinePos) =
        (v.code, v.name, &v.description, &v.source_range, v.start, v.end);
    let _: (&Vec<SourceEdit>, bool, bool) = (&v.fixes, v.literal, v.fixable());
    let _: &[SqlfluffRule] = RULES;
    let _: &[(&str, Validation)] = CONFIG_VALIDATION;
}

#[allow(dead_code)]
fn out_violation() -> Violation {
    unreachable!()
}

// The record of the sqlfluff data.

fn record() -> Json {
    let text = std::fs::read_to_string(root().join(RECORD)).expect("read the record");
    serde_json::from_str(&text).expect("JSON")
}

fn strs(v: &Json) -> Vec<&str> {
    v.as_array()
        .expect("a list")
        .iter()
        .map(|s| s.as_str().expect("a text"))
        .collect()
}

#[test]
fn the_manifest_is_that_of_sqlfluff() {
    let record = record();
    let rules = record["rules"].as_array().expect("rules");
    assert_eq!(rules.len(), RULES.len(), "the rule count");
    for (r, m) in rules.iter().zip(RULES) {
        let phase = match m.lint_phase {
            LintPhase::Main => "main",
            LintPhase::Post => "post",
        };
        assert_eq!(r["code"].as_str(), Some(m.code));
        assert_eq!(r["name"].as_str(), Some(m.name), "{}", m.code);
        assert_eq!(r["description"].as_str(), Some(m.description), "{}", m.code);
        assert_eq!(strs(&r["groups"]), m.groups, "{}", m.code);
        assert_eq!(strs(&r["aliases"]), m.aliases, "{}", m.code);
        assert_eq!(r["lint_phase"].as_str(), Some(phase), "{}", m.code);
        assert_eq!(r["is_fix_compatible"].as_bool(), Some(m.is_fix_compatible));
        assert_eq!(strs(&r["config_keywords"]), m.config_keywords, "{}", m.code);
        assert_eq!(r["targets_templated"].as_bool(), Some(m.targets_templated));
    }
    let info = record["config_info"].as_object().expect("config_info");
    assert_eq!(info.len(), CONFIG_VALIDATION.len());
    for ((key, want), (k, got)) in info.iter().zip(CONFIG_VALIDATION) {
        assert_eq!(key, k);
        let got = match got {
            Validation::Range(a, b) => serde_json::json!({"range": [a, b]}),
            Validation::Values(values) => Json::Array(
                values
                    .iter()
                    .map(|v| match v {
                        Valid::Bool(b) => Json::Bool(*b),
                        Valid::Str(s) => Json::String(s.to_string()),
                    })
                    .collect(),
            ),
        };
        assert_eq!(*want, got, "{key}");
    }
    // The crawler of each rule of sqll is that of sqlfluff.
    let registry = Registry::new(sqll_rules::rules()).expect("the rules");
    for rule in registry.rules() {
        let r = rules
            .iter()
            .find(|r| r["code"].as_str() == Some(rule.code()))
            .expect("a recorded rule");
        let CrawlBehaviour::SegmentSeeker {
            types,
            allow_recurse,
            works_on_unparsable,
        } = rule.crawl_behaviour()
        else {
            panic!("{}: a SegmentSeekerCrawler in sqlfluff", rule.code());
        };
        let mut names: Vec<&str> = types.iter().map(|t| t.name()).collect();
        names.sort_unstable();
        let crawler = &r["crawler"];
        assert_eq!(crawler["type"].as_str(), Some("SegmentSeekerCrawler"));
        assert_eq!(strs(&crawler["types"]), names, "{}", rule.code());
        assert_eq!(crawler["allow_recurse"].as_bool(), Some(allow_recurse));
        assert_eq!(crawler["works_on_unparsable"].as_bool(), Some(works_on_unparsable));
    }
}

// A test rule: the metadata of a sqlfluff rule, and an eval function.

type EvalFn = fn(&mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError>;

struct TestRule {
    m: &'static SqlfluffRule,
    crawl: CrawlBehaviour,
    eval: EvalFn,
}

impl TestRule {
    fn new(code: &str, crawl: CrawlBehaviour, eval: EvalFn) -> Box<dyn Rule> {
        let m = RULES.iter().find(|r| r.code == code).expect("a sqlfluff rule");
        Box::new(TestRule { m, crawl, eval })
    }
}

impl Rule for TestRule {
    fn code(&self) -> &'static str {
        self.m.code
    }
    fn name(&self) -> &'static str {
        self.m.name
    }
    fn description(&self) -> &'static str {
        self.m.description
    }
    fn groups(&self) -> &'static [&'static str] {
        self.m.groups
    }
    fn aliases(&self) -> &'static [&'static str] {
        self.m.aliases
    }
    fn config_keywords(&self) -> &'static [&'static str] {
        self.m.config_keywords
    }
    fn lint_phase(&self) -> LintPhase {
        self.m.lint_phase
    }
    fn is_fix_compatible(&self) -> bool {
        self.m.is_fix_compatible
    }
    fn targets_templated(&self) -> bool {
        self.m.targets_templated
    }
    fn crawl_behaviour(&self) -> CrawlBehaviour {
        self.crawl
    }
    fn eval(&self, context: &mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError> {
        (self.eval)(context)
    }
}

const KEYWORDS: [SegmentType; 1] = [SegmentType::KEYWORD];

/// The test rule: each keyword that is not in upper case gets a replace
/// fix to upper case. The memory counts the calls.
fn upper_keywords(ctx: &mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError> {
    *ctx.memory.get_or_default::<usize>() += 1;
    let node = ctx.segment;
    let upper = node.raw().to_uppercase();
    if upper == node.raw() {
        return Ok(Vec::new());
    }
    Ok(vec![LintResult::new(node.id())
        .with_description(format!("{} must be upper case.", node.raw()))
        .with_fix(Fix::Replace {
            anchor: node.id(),
            text: upper,
        })])
}

fn upper_rule() -> Box<dyn Rule> {
    TestRule::new("CP01", CrawlBehaviour::seeker(&KEYWORDS), upper_keywords)
}

fn table(items: &[(&str, Value)]) -> Table {
    items
        .iter()
        .map(|(k, v)| (k.to_string(), v.clone()))
        .collect()
}

/// A config with these core overrides (the dialect is ansi).
fn config(core: &[(&str, Value)]) -> Config {
    let mut overrides = table(core);
    overrides.insert("dialect".into(), Value::str("ansi"));
    Config::new(Table::new(), &overrides).expect("a valid config")
}

#[test]
fn the_registry_checks_the_rule_metadata() {
    assert!(Registry::new(vec![upper_rule()]).is_ok());
    let err = Registry::new(vec![upper_rule(), upper_rule()]).err().unwrap();
    assert!(err.contains("CP01: two rules have this code"), "{err}");

    struct Wrong;
    impl Rule for Wrong {
        fn code(&self) -> &'static str {
            "CP01"
        }
        fn name(&self) -> &'static str {
            "capitalisation.other"
        }
        fn description(&self) -> &'static str {
            "Inconsistent capitalisation of keywords."
        }
        fn groups(&self) -> &'static [&'static str] {
            &["all"]
        }
        fn crawl_behaviour(&self) -> CrawlBehaviour {
            CrawlBehaviour::root_only()
        }
        fn eval(&self, _: &mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError> {
            Ok(Vec::new())
        }
    }
    let err = Registry::new(vec![Box::new(Wrong)]).err().unwrap();
    for what in ["name", "groups", "aliases", "lint phase", "fix flag", "config keywords"] {
        assert!(err.contains(&format!("CP01: the {what} is not")), "{what}: {err}");
    }
    assert!(!err.contains("the description"), "{err}");

    struct Unknown;
    impl Rule for Unknown {
        fn code(&self) -> &'static str {
            "XX01"
        }
        fn name(&self) -> &'static str {
            "x.y"
        }
        fn description(&self) -> &'static str {
            ""
        }
        fn groups(&self) -> &'static [&'static str] {
            &["all"]
        }
        fn crawl_behaviour(&self) -> CrawlBehaviour {
            CrawlBehaviour::root_only()
        }
        fn eval(&self, _: &mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError> {
            Ok(Vec::new())
        }
    }
    let err = Registry::new(vec![Box::new(Unknown)]).err().unwrap();
    assert_eq!(err, "XX01: not a rule of sqlfluff 4.4.0");
}

#[test]
fn the_selection_is_that_of_sqlfluff_and_fails_closed() {
    let registry = Registry::new(sqll_rules::rules()).expect("the rules");
    let codes = |core: &[(&str, Value)]| -> Result<Vec<&str>, LintError> {
        registry
            .select(&config(core))
            .map(|p| p.rules.iter().map(|(r, _)| r.code()).collect())
    };
    let unsupported = |core: &[(&str, Value)]| match codes(core) {
        Err(LintError::Unsupported(m)) => m,
        other => panic!("{other:?}"),
    };
    // The default (rules = all) selects each sqlfluff rule.
    let m = unsupported(&[]);
    assert!(m.starts_with("rules AL01, AL02, "), "{m}");
    assert!(!m.contains("CP01") && m.contains("CP02") && m.contains("ST11"), "{m}");
    // Codes, names, aliases, globs, and the deny list.
    let s = Value::str;
    assert_eq!(codes(&[("rules", s("CP01"))]).unwrap(), ["CP01"]);
    assert_eq!(codes(&[("rules", s("capitalisation.functions"))]).unwrap(), ["CP03"]);
    assert_eq!(codes(&[("rules", s("L040,L010"))]).unwrap(), ["CP01", "CP04"]);
    assert_eq!(codes(&[("rules", s("CP0[134]"))]).unwrap(), ["CP01", "CP03", "CP04"]);
    assert_eq!(codes(&[("rules", s("CP0[!25]"))]).unwrap(), ["CP01", "CP03", "CP04"]);
    assert_eq!(codes(&[("rules", s("capitalisation.?iterals"))]).unwrap(), ["CP04"]);
    assert_eq!(
        codes(&[("rules", s("capitalisation")), ("exclude_rules", s("CP02,CP05"))]).unwrap(),
        ["CP01", "CP03", "CP04"]
    );
    // A group with a rule that sqll does not have.
    assert_eq!(unsupported(&[("rules", s("capitalisation"))]), "rules CP02, CP05: sqll does not have them yet (S5)");
    // An unknown reference selects nothing (sqlfluff warns).
    assert_eq!(codes(&[("rules", s("XX99"))]).unwrap(), Vec::<&str>::new());

    // A config value that sqlfluff refuses.
    let configs = table(&[(
        "rules",
        Value::Table(table(&[(
            "capitalisation.keywords",
            Value::Table(table(&[("capitalisation_policy", s("title"))])),
        )])),
    )]);
    let overrides = table(&[("rules", s("CP01")), ("dialect", s("ansi"))]);
    let c = Config::new(configs, &overrides).unwrap();
    assert_eq!(
        registry.select(&c).err(),
        Some(LintError::Invalid(
            "Invalid option 'title' for capitalisation_policy configuration. Must be one of \
             ['consistent', 'upper', 'lower', 'capitalise']"
                .into()
        ))
    );
    // A setting that the rule cannot do fails closed.
    let configs = table(&[(
        "rules",
        Value::Table(table(&[(
            "capitalisation.keywords",
            Value::Table(table(&[("ignore_words_regex", s("^S"))])),
        )])),
    )]);
    let c = Config::new(configs, &overrides).unwrap();
    assert!(matches!(registry.select(&c), Err(LintError::Unsupported(m)) if m.contains("ignore_words_regex")));
    // A linter setting that sqll cannot do fails closed.
    let c = config(&[("fix_even_unparsable", Value::Bool(true))]);
    assert!(matches!(LintSettings::from_config(&c), Err(LintError::Unsupported(_))));
    assert_eq!(
        LintSettings::from_config(&config(&[])).unwrap(),
        LintSettings::default()
    );
}

#[test]
fn the_validation_is_python_membership() {
    let v = Validation::Values(&[Valid::Bool(true), Valid::Bool(false)]);
    assert!(v.accepts(&Value::Bool(true)) && v.accepts(&Value::Int(1)) && v.accepts(&Value::Float(0.0)));
    assert!(!v.accepts(&Value::str("True")) && !v.accepts(&Value::Int(2)));
    let r = Validation::Range(0, 1000);
    assert!(r.accepts(&Value::Int(0)) && r.accepts(&Value::Int(999)) && r.accepts(&Value::Bool(true)));
    assert!(r.accepts(&Value::Float(5.0)) && !r.accepts(&Value::Float(5.5)));
    assert!(!r.accepts(&Value::Int(1000)) && !r.accepts(&Value::Int(-1)) && !r.accepts(&Value::str("5")));
}

// A test templater: `{{ name }}` gives the value of the context (section
// "templater:jinja:context"), and `{% ... %}` gives no text and starts a
// new block, as the sqlfluff Jinja templater slices them.

struct VarTemplater;

impl Templater for VarTemplater {
    fn name(&self) -> &'static str {
        "jinja"
    }

    fn process(
        &self,
        source: &str,
        fname: &str,
        config: &TemplaterConfig,
    ) -> Result<TemplatedFile, TemplaterError> {
        let mut templated = String::new();
        let mut sliced = Vec::new();
        let mut raws = Vec::new();
        let (mut at, mut src_cp, mut tpl_cp, mut block) = (0usize, 0usize, 0usize, 0usize);
        let mut push = |ty: &str, raw: &str, out: &str, block: usize, templated: &mut String| {
            let (n_src, n_tpl) = (raw.chars().count(), out.chars().count());
            sliced.push(TemplatedFileSlice::new(
                ty.to_string(),
                Slice::from(src_cp..src_cp + n_src),
                Slice::from(tpl_cp..tpl_cp + n_tpl),
            ));
            raws.push(RawFileSlice::new(raw.to_string(), ty.to_string(), src_cp, Some(block), None));
            templated.push_str(out);
            src_cp += n_src;
            tpl_cp += n_tpl;
        };
        while at < source.len() {
            let next = ["{{", "{%"]
                .iter()
                .filter_map(|d| source[at..].find(d).map(|i| at + i))
                .min();
            let Some(start) = next else {
                push("literal", &source[at..], &source[at..], block, &mut templated);
                break;
            };
            if start > at {
                push("literal", &source[at..start], &source[at..start], block, &mut templated);
            }
            let close = if source[start..].starts_with("{{") { "}}" } else { "%}" };
            let end = source[start..]
                .find(close)
                .map(|i| start + i + 2)
                .ok_or_else(|| TemplaterError::Template {
                    message: "no end of a tag".into(),
                    source_byte: Some(start),
                })?;
            let tag = &source[start..end];
            if close == "}}" {
                let name = tag[2..tag.len() - 2].trim();
                let value = config
                    .get("templater:jinja:context", name)
                    .ok_or_else(|| TemplaterError::Template {
                        message: format!("'{name}' is undefined"),
                        source_byte: Some(start),
                    })?
                    .to_string();
                push("templated", tag, &value, block, &mut templated);
            } else {
                push("block_start", tag, "", block, &mut templated);
                block += 1;
            }
            at = end;
        }
        Ok(TemplatedFile::new(
            source.to_string(),
            fname.to_string(),
            Some(templated),
            Some(sliced),
            Some(raws),
        ))
    }
}

/// The fixture of the C8 hand-built map, and its context.
const JINJA_A: &str = "test/fixtures/templater/jinja_a/jinja.sql";
const CONTEXT: [(&str, &str); 3] = [
    ("testing_schema", "sch1"),
    ("testing_table", "tbl2"),
    ("kw", "from"),
];

fn context() -> TemplaterConfig {
    let mut c = TemplaterConfig::new();
    for (k, v) in CONTEXT {
        c.set("templater:jinja:context", k, v);
    }
    c
}

fn ansi() -> Dialect {
    Dialect::from_str("ansi").unwrap()
}

fn var_parser() -> TemplaterParser<'static> {
    TemplaterParser {
        templater: &VarTemplater,
        config: context(),
        fname: "test.sql".into(),
        dialect: ansi(),
        options: ParseOptions::default(),
    }
}

fn tree_of(source: &str) -> SyntaxTree {
    let parsed = var_parser().parse(source).expect("a parse");
    assert!(parsed.errors.is_empty(), "{:?}", parsed.errors);
    parsed.tree.expect("a tree")
}

#[test]
fn the_test_templater_gives_the_c8_hand_built_map() {
    let source = std::fs::read_to_string(root().join("third_party/sqlfluff").join(JINJA_A)).unwrap();
    let file = VarTemplater.process(&source, JINJA_A, &context()).unwrap();
    // JINJA_A_TEMPLATED and JINJA_A_SLICES of tests/source_map.rs: the
    // slices of the pinned sqlfluff JinjaTemplater.
    assert_eq!(file.templated_str, "SELECT 56 FROM sch1.tbl2\n");
    let slices: Vec<(&str, Range<usize>, Range<usize>)> = file
        .sliced_file
        .iter()
        .map(|s| {
            (
                s.slice_type.as_str(),
                s.source_codepoint_slice.start..s.source_codepoint_slice.stop,
                s.templated_codepoint_slice.start..s.templated_codepoint_slice.stop,
            )
        })
        .collect();
    assert_eq!(
        slices,
        [
            ("literal", 0..15, 0..15),
            ("templated", 15..35, 15..19),
            ("literal", 35..36, 19..20),
            ("templated", 36..55, 20..24),
            ("literal", 55..56, 24..25),
        ]
    );
    let map = SourceMap::new(std::sync::Arc::new(file)).expect("a valid map");
    assert!(!map.is_identity());
}

/// The node of the first leaf with this text.
fn leaf(tree: &SyntaxTree, raw: &str) -> NodeId {
    tree.nodes()
        .find(|&id| tree.children(id).next().is_none() && tree.raw(id) == raw)
        .unwrap_or_else(|| panic!("no leaf {raw:?}"))
}

#[test]
fn a_fix_maps_to_the_source_or_is_refused() {
    // jinja_a: "SELECT 56 FROM {{ testing_schema }}.{{ testing_table }}\n"
    let source = std::fs::read_to_string(root().join("third_party/sqlfluff").join(JINJA_A)).unwrap();
    let tree = tree_of(&source);
    let edit = |fix: Fix| fix.source_edit(&tree);
    let at = |range: Range<usize>, text: &str| {
        Ok(Some(SourceEdit {
            range,
            text: text.to_string(),
        }))
    };
    let from = leaf(&tree, "FROM");
    let sch1 = leaf(&tree, "sch1");
    let tbl2 = leaf(&tree, "tbl2");
    // A literal range maps exactly.
    assert_eq!(
        edit(Fix::Replace { anchor: from, text: "from".into() }),
        at(10..14, "from")
    );
    assert_eq!(edit(Fix::Delete { anchor: from }), at(10..14, ""));
    // A templated range is refused.
    assert_eq!(
        edit(Fix::Replace { anchor: sch1, text: "x".into() }),
        Err(FixRefusal::Templated { templated: 15..19 })
    );
    assert_eq!(
        edit(Fix::Delete { anchor: tbl2 }),
        Err(FixRefusal::Templated { templated: 20..24 })
    );
    // An insertion next to a templated range goes next to its literal
    // neighbour: before the tag, or after it.
    assert_eq!(
        edit(Fix::CreateBefore { anchor: sch1, text: "a".into() }),
        at(15..15, "a")
    );
    assert_eq!(
        edit(Fix::CreateAfter { anchor: sch1, text: "b".into() }),
        at(35..35, "b")
    );
    assert_eq!(
        edit(Fix::CreateAfter { anchor: tbl2, text: "c".into() }),
        at(55..55, "c")
    );
    // A node with no text and an empty fix changes nothing.
    let meta = tree
        .nodes()
        .find(|&id| tree.is_meta(id))
        .expect("a meta node");
    assert_eq!(edit(Fix::Delete { anchor: meta }), Ok(None));

    // The fixes of one result must not touch two template blocks.
    let tree = tree_of("select 1 {% if x %}from t\n");
    let select = leaf(&tree, "select");
    let from = leaf(&tree, "from");
    let up = |anchor, text: &str| Fix::Replace {
        anchor,
        text: text.into(),
    };
    assert_eq!(result_edits(&tree, &[up(select, "SELECT")]).unwrap().len(), 1);
    assert_eq!(result_edits(&tree, &[up(from, "FROM")]).unwrap().len(), 1);
    assert_eq!(
        result_edits(&tree, &[up(select, "SELECT"), up(from, "FROM")]),
        Err(FixRefusal::MultipleBlocks)
    );
    // An insertion counts the block of its literal neighbour.
    let before_from = Fix::CreateBefore {
        anchor: from,
        text: "x ".into(),
    };
    assert_eq!(
        result_edits(&tree, &[before_from.clone()]),
        Ok(vec![SourceEdit {
            range: 19..19,
            text: "x ".into()
        }])
    );
    assert_eq!(
        result_edits(&tree, &[up(select, "SELECT"), before_from]),
        Err(FixRefusal::MultipleBlocks)
    );
    let after_one = Fix::CreateAfter {
        anchor: leaf(&tree, "1"),
        text: " y".into(),
    };
    assert_eq!(
        result_edits(&tree, &[up(select, "SELECT"), after_one]).map(|e| e.len()),
        Ok(2)
    );
}

#[test]
fn the_anchor_check_and_the_edits_are_those_of_sqlfluff() {
    let a = NodeId::ROOT;
    let replace = Fix::Replace { anchor: a, text: "x".into() };
    let before = Fix::CreateBefore { anchor: a, text: "x".into() };
    let after = Fix::CreateAfter { anchor: a, text: "y".into() };
    assert_eq!(check_anchors(&[replace.clone(), replace.clone()]), Some(vec![replace.clone()]));
    assert_eq!(check_anchors(&[before.clone(), after.clone()]).map(|v| v.len()), Some(2));
    assert_eq!(check_anchors(&[replace.clone(), after.clone()]), None);
    assert_eq!(check_anchors(&[before.clone(), before, after]), Some(vec![
        Fix::CreateBefore { anchor: a, text: "x".into() },
        Fix::CreateAfter { anchor: a, text: "y".into() },
    ]));

    let e = |r: Range<usize>, t: &str| SourceEdit { range: r, text: t.into() };
    let src = "abcdef";
    // Insertions at one point: after an anchor, then before an anchor, then
    // the change of a range; each kind keeps its order.
    assert_eq!(
        apply_edits(src, &[
            (e(2..4, "X"), false),
            (e(2..2, "b1"), false),
            (e(2..2, "a1"), true),
            (e(2..2, "b2"), false),
            (e(4..4, "Z"), true),
        ]),
        Some("aba1b1b2XZef".into())
    );
    // Overlaps fail.
    assert_eq!(apply_edits(src, &[(e(1..3, ""), false), (e(2..4, ""), false)]), None);
    assert_eq!(apply_edits(src, &[(e(1..4, ""), false), (e(2..2, "x"), false)]), None);
    assert_eq!(apply_edits(src, &[(e(1..3, ""), false), (e(1..3, "y"), false)]), None);
    assert_eq!(apply_edits(src, &[(e(5..9, ""), false)]), None);
}

/// Lint a source with these rules and core settings.
fn lint(
    rules: Vec<Box<dyn Rule>>,
    core: &[(&str, Value)],
    source: &str,
    fix: bool,
) -> Result<LintedFile, LintError> {
    let registry = Registry::new(rules).expect("the rules");
    let mut core = core.to_vec();
    if !core.iter().any(|(k, _)| *k == "rules") {
        let codes: Vec<&str> = registry.rules().map(|r| r.code()).collect();
        core.push(("rules", Value::str(&codes.join(","))));
    }
    let config = config(&core);
    let pack = registry.select(&config)?;
    let linter = Linter {
        pack: &pack,
        settings: LintSettings::from_config(&config)?,
        dialect: ansi(),
    };
    linter.lint(source, &mut var_parser(), fix)
}

fn at(line: usize, pos: usize) -> LinePos {
    LinePos { line, pos }
}

#[test]
fn a_fix_round_trips_through_the_templated_source_map() {
    // The source of jinja_a in lower case: the fix changes the literal
    // keywords in the source and keeps the template tags.
    let source = "select 56 from {{ testing_schema }}.{{ testing_table }}\n";
    let linted = lint(vec![upper_rule()], &[], source, true).unwrap();
    assert_eq!(
        linted.fixed,
        "SELECT 56 FROM {{ testing_schema }}.{{ testing_table }}\n"
    );
    assert!(linted.warnings.is_empty(), "{:?}", linted.warnings);
    let got: Vec<(&str, LinePos, LinePos, &str, bool)> = linted
        .violations
        .iter()
        .map(|v| (v.code, v.start, v.end, v.description.as_str(), v.fixable()))
        .collect();
    assert_eq!(
        got,
        [
            ("CP01", at(1, 1), at(1, 7), "select must be upper case.", true),
            ("CP01", at(1, 11), at(1, 15), "from must be upper case.", true),
        ]
    );
    assert_eq!(linted.violations[1].fixes, [SourceEdit { range: 10..14, text: "FROM".into() }]);
    // A lint gives the same violations and no fix.
    let linted = lint(vec![upper_rule()], &[], source, false).unwrap();
    assert_eq!(linted.fixed, source);
    assert_eq!(linted.violations.len(), 2);
}

#[test]
fn a_fix_in_a_templated_range_is_refused() {
    // The keyword "from" is the output of the tag {{ kw }}.
    let source = "SELECT 56 {{ kw }} sch1.tbl2\n";
    // ignore_templated_areas (default true): the violation is removed.
    let linted = lint(vec![upper_rule()], &[], source, true).unwrap();
    assert_eq!(linted.fixed, source);
    assert!(linted.violations.is_empty(), "{:?}", linted.violations);
    // ignore_templated_areas false: the violation is not fixable.
    let core = [("ignore_templated_areas", Value::Bool(false))];
    let linted = lint(vec![upper_rule()], &core, source, true).unwrap();
    assert_eq!(linted.fixed, source);
    assert_eq!(linted.violations.len(), 1);
    let v = &linted.violations[0];
    assert_eq!((v.start, v.literal, v.fixable()), (at(1, 11), false, false));
    assert_eq!(v.source_range, 10..18);
    // A literal fix in the same file applies; the templated one does not.
    let source = "select 56 {{ kw }} sch1.tbl2\n";
    let linted = lint(vec![upper_rule()], &core, source, true).unwrap();
    assert_eq!(linted.fixed, "SELECT 56 {{ kw }} sch1.tbl2\n");
    let fixable: Vec<bool> = linted.violations.iter().map(Violation::fixable).collect();
    assert_eq!(fixable, [true, false]);
}

/// A rule that puts a newline after the last leaf with text: each loop
/// gives a new source and a new edit.
fn runaway(ctx: &mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError> {
    let tree = ctx.tree();
    let id = tree
        .nodes()
        .filter(|&id| tree.children(id).next().is_none() && !tree.raw(id).is_empty())
        .last()
        .expect("a leaf");
    Ok(vec![LintResult::new(id).with_fix(Fix::CreateAfter { anchor: id, text: "\n".into() })])
}

/// A rule with two fixes of one anchor (a conflict).
fn conflict(ctx: &mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError> {
    let id = ctx.segment.id();
    Ok(vec![LintResult::new(id)
        .with_fix(Fix::Replace { anchor: id, text: "X".into() })
        .with_fix(Fix::Delete { anchor: id })])
}

/// A rule that replaces each keyword and its parent (overlapping fixes).
fn overlap(ctx: &mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError> {
    let id = ctx.segment.id();
    let parent = ctx.parent().expect("a parent").id();
    Ok(vec![LintResult::new(id)
        .with_fix(Fix::Replace { anchor: id, text: "X".into() })
        .with_fix(Fix::Replace { anchor: parent, text: "Y".into() })])
}

/// A rule that breaks the SQL.
fn unparsable(ctx: &mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError> {
    let id = ctx.segment.id();
    if ctx.segment.raw() != "FROM" {
        return Ok(Vec::new());
    }
    Ok(vec![LintResult::new(id).with_fix(Fix::Replace { anchor: id, text: "FROM (".into() })])
}

/// The rules that ran (the description is the code).
static CALLS: Mutex<Vec<&'static str>> = Mutex::new(Vec::new());

fn record_call(ctx: &mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError> {
    let code: &'static str = match ctx.config.get("capitalisation_policy") {
        Some(_) => "CP01",
        None => "AL01",
    };
    CALLS.lock().unwrap().push(code);
    Ok(Vec::new())
}

#[test]
fn the_fix_loop_is_that_of_sqlfluff() {
    let root = CrawlBehaviour::root_only();
    let kw = CrawlBehaviour::seeker(&KEYWORDS);
    let source = "SELECT 56 FROM sch1.tbl2\n";

    // The runaway limit: no fix, and the original source.
    let core = [("runaway_limit", Value::Int(3))];
    let rule = TestRule::new("LT01", root, runaway);
    let linted = lint(vec![rule], &core, source, true).unwrap();
    assert_eq!(linted.fixed, source);
    assert_eq!(linted.warnings, ["Loop limit on fixes reached [3]."]);
    assert_eq!(linted.violations.len(), 1);
    assert!(!linted.violations[0].fixable());
    // A lint has no loop: the violation is fixable.
    let rule = TestRule::new("LT01", root, runaway);
    let linted = lint(vec![rule], &core, source, false).unwrap();
    assert!(linted.warnings.is_empty() && linted.violations[0].fixable());
    // The same fixes as in the loop before stop the loop (sqlfluff: "the
    // same as the previous pass"): no loop limit.
    fn same_point(ctx: &mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError> {
        let id = ctx.segment.id();
        if ctx.segment.raw() != "SELECT" {
            return Ok(Vec::new());
        }
        Ok(vec![LintResult::new(id).with_fix(Fix::CreateAfter { anchor: id, text: " ".into() })])
    }
    let rule = TestRule::new("LT01", kw, same_point);
    let linted = lint(vec![rule], &core, source, true).unwrap();
    assert_eq!(linted.fixed, "SELECT  56 FROM sch1.tbl2\n");
    assert!(linted.warnings.is_empty(), "{:?}", linted.warnings);

    // Conflicting fixes of one anchor: not applied, not fixable.
    let rule = TestRule::new("LT01", kw, conflict);
    let linted = lint(vec![rule], &[], source, true).unwrap();
    assert_eq!(linted.fixed, source);
    assert!(linted.warnings[0].starts_with("Rule LT01 returned conflicting fixes"));
    assert!(linted.violations.iter().all(|v| !v.fixable()));

    // Overlapping fixes: not applied, not fixable.
    let rule = TestRule::new("LT01", kw, overlap);
    let linted = lint(vec![rule], &[], source, true).unwrap();
    assert_eq!(linted.fixed, source);
    assert!(linted.warnings[0].starts_with("Rule LT01 returned fixes that overlap"));
    assert!(linted.violations.iter().all(|v| !v.fixable()));

    // A fix that makes the file unparsable is not applied.
    let rule = TestRule::new("LT01", kw, unparsable);
    let linted = lint(vec![rule], &[], source, true).unwrap();
    assert_eq!(linted.fixed, source);
    assert!(linted.warnings[0].contains("would result in an unparsable file"));

    // The phases: a lint runs each rule one time; a fix runs each rule in
    // the first loop, then the main rules until no change, then the post
    // rules (CP01 is a post rule) one more time.
    let rules = || vec![TestRule::new("AL01", root, record_call), TestRule::new("CP01", root, record_call)];
    CALLS.lock().unwrap().clear();
    lint(rules(), &[], source, false).unwrap();
    assert_eq!(*CALLS.lock().unwrap(), ["AL01", "CP01"]);
    CALLS.lock().unwrap().clear();
    lint(rules(), &[], source, true).unwrap();
    assert_eq!(*CALLS.lock().unwrap(), ["AL01", "CP01", "CP01"]);

    // A rule error stops the lint (fail closed).
    fn fails(_: &mut RuleContext<'_, '_>) -> Result<Vec<LintResult>, LintError> {
        Err(LintError::Unsupported("x".into()))
    }
    let rule = TestRule::new("LT01", root, fails);
    assert_eq!(lint(vec![rule], &[], source, true), Err(LintError::Unsupported("x".into())));

    // A noqa comment fails closed, unless noqa is off.
    let noqa = "SELECT 56 FROM sch1.tbl2 -- noqa: CP01\n";
    assert!(matches!(
        lint(vec![upper_rule()], &[], noqa, false),
        Err(LintError::Unsupported(m)) if m.contains("noqa")
    ));
    let off = [("disable_noqa", Value::Bool(true))];
    assert!(lint(vec![upper_rule()], &off, noqa, false).is_ok());
}

#[test]
fn the_crawl_skips_unparsable_sections_and_keeps_the_memory() {
    let parsed = var_parser().parse("SELECT 1 FROM t WHERE ) x\n").unwrap();
    assert_eq!(parsed.errors.len(), 1, "an unparsable section");
    let tree = parsed.tree.expect("a tree");
    // The types of the leaves in the unparsable section ("WHERE ) x").
    let unparsable = tree
        .nodes()
        .find(|&id| tree.node(id).is_type(SegmentType::UNPARSABLE))
        .expect("an unparsable node");
    let inside: Vec<NodeId> = tree.descendants(unparsable).collect();
    let mut types: Vec<SegmentType> = inside
        .iter()
        .filter(|&&id| tree.node(id).is_code())
        .map(|&id| tree.ty(id))
        .collect();
    types.push(SegmentType::KEYWORD);
    let types: &'static [SegmentType] = Box::leak(types.into_boxed_slice());
    let off = CrawlBehaviour::seeker(types);
    let crawled = off.crawl(&tree);
    assert!(crawled.iter().all(|id| !inside.contains(id) && *id != unparsable));
    let raws: Vec<&str> = crawled.iter().map(|&id| tree.raw(id)).collect();
    assert_eq!(raws, ["SELECT", "FROM"]);
    let on = CrawlBehaviour::SegmentSeeker {
        types,
        allow_recurse: true,
        works_on_unparsable: true,
    };
    let crawled = on.crawl(&tree);
    let code: Vec<NodeId> = inside.iter().copied().filter(|&id| tree.node(id).is_code()).collect();
    assert!(!code.is_empty() && code.iter().all(|id| crawled.contains(id)));
    // allow_recurse false: no match inside a match.
    let statement: &'static [SegmentType] = &[SegmentType::STATEMENT, SegmentType::KEYWORD];
    let flat = CrawlBehaviour::SegmentSeeker {
        types: statement,
        allow_recurse: false,
        works_on_unparsable: false,
    };
    let raws: Vec<&str> = flat.crawl(&tree).iter().map(|&id| tree.raw(id)).collect();
    assert_eq!(raws, ["SELECT 1 FROM t WHERE ) x"]);
    assert_eq!(CrawlBehaviour::root_only().crawl(&tree), [NodeId::ROOT]);

    // The memory of one crawl: upper_keywords counts its calls.
    let kw = CrawlBehaviour::seeker(&KEYWORDS);
    let crawled = kw.crawl(&tree);
    let mut memory = Memory::default();
    let config = RuleConfig::from_values(Table::new(), Table::new());
    for &id in &crawled {
        let mut ctx = RuleContext {
            segment: tree.node(id),
            dialect: ansi(),
            config: &config,
            memory: &mut memory,
        };
        upper_keywords(&mut ctx).unwrap();
        assert_eq!(ctx.parent_stack().first().map(|n| n.id()), Some(NodeId::ROOT));
    }
    assert_eq!(memory.get::<usize>(), Some(&crawled.len()));
}

