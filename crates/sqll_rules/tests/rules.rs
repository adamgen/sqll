//! Tests of the ported rules CP01, CP03, and CP04 on sqll parse trees (S3
//! T18). New sqll code: the base has no tests of these rules in Rust.
//!
//! Each expected text is the output of the pinned sqlfluff 4.4.0 (the tool
//! venv) for the same SQL and policy:
//! `sqlfluff fix --rules <code> --dialect ansi`, with the policy in the
//! `[sqlfluff:rules:capitalisation.keywords]`, `.functions`, or `.literals`
//! section of the config file.

use std::collections::HashSet;
use std::str::FromStr;

use sqlfluffrs_dialects::Dialect;
use sqlfluffrs_lexer::{LexInput, Lexer};
use sqlfluffrs_parser::parser::Parser;
use sqlfluffrs_parser::{Arena, NodeId};
use sqll_rules::{cp01, cp03, cp04};

type Detect = fn(&Arena, &str, &HashSet<String>, bool) -> Vec<(usize, String)>;

fn arena(sql: &str) -> Arena {
    let dialect = Dialect::from_str("ansi").unwrap();
    let lexer = Lexer::new(None, dialect.get_lexers().clone())
        .with_bracket_pairs(dialect.get_bracket_pairs().clone());
    let (tokens, errors) = lexer.lex(LexInput::String(sql.to_string()), false);
    assert!(errors.is_empty(), "{errors:?}");
    let mut parser = Parser::new(&tokens, dialect, hashbrown::HashMap::new());
    let node = parser
        .call_rule_as_root()
        .expect("parse")
        .apply_as_root(&tokens, &[], &[]);
    Arena::from_node(&node)
}

/// The leaves in depth-first order: the order of the leaf index of a rule.
fn leaves(arena: &Arena, id: NodeId, out: &mut Vec<NodeId>) {
    let children = arena.children(id);
    if children.is_empty() {
        out.push(id);
    }
    for &child in children {
        leaves(arena, child, out);
    }
}

/// The SQL after each fix of the rule.
fn fix(detect: Detect, policy: &str, ignore: &[&str], sql: &str) -> String {
    let arena = arena(sql);
    let ignore: HashSet<String> = ignore.iter().map(|w| w.to_string()).collect();
    let fixes = detect(&arena, policy, &ignore, false);
    let mut ids = Vec::new();
    leaves(&arena, arena.root(), &mut ids);
    assert_eq!(arena.raw_segments(arena.root()), ids);
    let mut text: Vec<String> = ids.iter().map(|&id| arena.raw(id)).collect();
    assert_eq!(text.concat(), sql);
    for (leaf, raw) in fixes {
        assert_ne!(text[leaf], raw, "a fix must change the text");
        text[leaf] = raw;
    }
    text.concat()
}

#[test]
fn cp01_keywords() {
    let cases: [(&str, &[&str], &str, &str); 7] = [
        ("consistent", &[], "SELECT a from t\n", "SELECT a FROM t\n"),
        ("consistent", &[], "select a FROM t\n", "select a from t\n"),
        ("consistent", &[], "SELECT a FROM t\n", "SELECT a FROM t\n"),
        (
            "lower",
            &[],
            "SELECT a FROM t WHERE a = 1 AND b = 2\n",
            "select a from t where a = 1 and b = 2\n",
        ),
        ("capitalise", &[], "select a from t\n", "Select a From t\n"),
        ("upper", &["from"], "select a from t\n", "SELECT a from t\n"),
        // The data type keyword "int" is not a target (parent data_type).
        (
            "upper",
            &[],
            "select cast(a as int) from t\n",
            "SELECT cast(a AS int) FROM t\n",
        ),
    ];
    for (policy, ignore, sql, want) in cases {
        assert_eq!(fix(cp01::cp01_violations, policy, ignore, sql), want, "{policy} {sql:?}");
    }
}

#[test]
fn cp03_functions() {
    let cases: [(&str, &str, &str); 3] = [
        (
            "consistent",
            "SELECT MAX(a), min(b) FROM t\n",
            "SELECT MAX(a), MIN(b) FROM t\n",
        ),
        (
            "lower",
            "SELECT MAX(a), COUNT(*) FROM t\n",
            "SELECT max(a), count(*) FROM t\n",
        ),
        ("pascal", "SELECT max(a) FROM t\n", "SELECT Max(a) FROM t\n"),
    ];
    for (policy, sql, want) in cases {
        assert_eq!(fix(cp03::cp03_violations, policy, &[], sql), want, "{policy} {sql:?}");
    }
}

#[test]
fn cp04_literals() {
    let cases: [(&str, &str, &str); 2] = [
        (
            "consistent",
            "SELECT NULL, true FROM t\n",
            "SELECT NULL, TRUE FROM t\n",
        ),
        (
            "lower",
            "SELECT NULL, TRUE, False FROM t\n",
            "SELECT null, true, false FROM t\n",
        ),
    ];
    for (policy, sql, want) in cases {
        assert_eq!(fix(cp04::cp04_violations, policy, &[], sql), want, "{policy} {sql:?}");
    }
}
