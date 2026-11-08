// Parts of this file are a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/rules/base.py (RuleSet.rule_reference_map,
// RuleSet._expand_rule_refs, RuleSet.get_rulepack) and the Python fnmatch
// rules of a glob (fnmatch.filter on POSIX: case-sensitive).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The rule registry and the selection of the rules of a config.

use std::collections::{BTreeMap, BTreeSet};

use sqll_config::{Config, Value};

use crate::config::{validate_options, RuleConfig};
use crate::rule::Rule;
use crate::sqlfluff::{SqlfluffRule, RULES};
use crate::LintError;

/// The rules of sqll. Each one is a rule of sqlfluff with its metadata.
pub struct Registry {
    rules: Vec<Box<dyn Rule>>,
}

/// The selected rules of a config, in code order, with their config.
pub struct RulePack<'r> {
    pub rules: Vec<(&'r dyn Rule, RuleConfig)>,
    /// The sqlfluff reference map: a code, a name, a group, or an alias to
    /// the codes.
    pub reference_map: BTreeMap<String, BTreeSet<String>>,
}

impl std::fmt::Debug for RulePack<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let codes: Vec<&str> = self.rules.iter().map(|(r, _)| r.code()).collect();
        f.debug_struct("RulePack").field("rules", &codes).finish()
    }
}

/// The manifest of a sqlfluff rule, by code.
pub fn sqlfluff_rule(code: &str) -> Option<&'static SqlfluffRule> {
    RULES.iter().find(|r| r.code == code)
}

/// The differences between the metadata of a rule and the sqlfluff
/// manifest of its code.
fn metadata_problems(rule: &dyn Rule) -> Vec<String> {
    let code = rule.code();
    let Some(m) = sqlfluff_rule(code) else {
        return vec![format!("{code}: not a rule of sqlfluff 4.4.0")];
    };
    let mut out = Vec::new();
    let mut check = |what: &str, same: bool| {
        if !same {
            out.push(format!("{code}: the {what} is not that of sqlfluff"));
        }
    };
    check("name", rule.name() == m.name);
    check("description", rule.description() == m.description);
    check("groups", rule.groups() == m.groups);
    check("aliases", rule.aliases() == m.aliases);
    check("lint phase", rule.lint_phase() == m.lint_phase);
    check("fix flag", rule.is_fix_compatible() == m.is_fix_compatible);
    check(
        "config keywords",
        rule.config_keywords() == m.config_keywords,
    );
    check(
        "targets_templated flag",
        rule.targets_templated() == m.targets_templated,
    );
    out
}

/// Python `repr(text)` (for example the `{fname!r}` of the sqlfluff
/// warnings): `'` quotes, or `"` quotes for a text with `'` and no `"`; an
/// escape for `\`, the quote, `\t`, `\n`, `\r`, and the characters below
/// U+0100 that Python does not print. sqll writes a character from U+0100 up
/// as it is (Python writes an escape for some of them;
/// docs/interfaces/config.md).
pub fn py_repr(text: &str) -> String {
    let quote = if text.contains('\'') && !text.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(text.len() + 2);
    out.push(quote);
    for c in text.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            '\0'..='\x1f' | '\x7f'..='\u{a0}' | '\u{ad}' => {
                out.push_str(&format!("\\x{:02x}", u32::from(c)));
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// Python `fnmatch.fnmatchcase`: `*`, `?`, `[seq]`, and `[!seq]`.
pub fn fnmatch(name: &str, pattern: &str) -> bool {
    let n: Vec<char> = name.chars().collect();
    let p: Vec<char> = pattern.chars().collect();
    glob(&n, &p)
}

fn glob(n: &[char], p: &[char]) -> bool {
    match p.first() {
        None => n.is_empty(),
        Some('*') => (0..=n.len()).any(|i| glob(&n[i..], &p[1..])),
        Some('?') => !n.is_empty() && glob(&n[1..], &p[1..]),
        Some('[') => match class(p) {
            Some((matches, len)) => !n.is_empty() && matches(n[0]) && glob(&n[1..], &p[len..]),
            None => n.first() == Some(&'[') && glob(&n[1..], &p[1..]),
        },
        Some(&c) => n.first() == Some(&c) && glob(&n[1..], &p[1..]),
    }
}

type ClassFn = Box<dyn Fn(char) -> bool>;

/// A `[...]` class at the start of the pattern: the test of a character
/// and the length of the class. `None` if the class has no end (Python
/// then matches a `[`).
fn class(p: &[char]) -> Option<(ClassFn, usize)> {
    let mut i = 1;
    let negate = p.get(i) == Some(&'!');
    if negate {
        i += 1;
    }
    let start = i;
    // A "]" first in the class is a character of the class.
    if p.get(i) == Some(&']') {
        i += 1;
    }
    while i < p.len() && p[i] != ']' {
        i += 1;
    }
    if i >= p.len() {
        return None;
    }
    let body: Vec<char> = p[start..i].to_vec();
    let mut ranges: Vec<(char, char)> = Vec::new();
    let mut j = 0;
    while j < body.len() {
        if j + 2 < body.len() && body[j + 1] == '-' {
            ranges.push((body[j], body[j + 2]));
            j += 3;
        } else {
            ranges.push((body[j], body[j]));
            j += 1;
        }
    }
    let test = move |c: char| ranges.iter().any(|&(a, b)| a <= c && c <= b) != negate;
    Some((Box::new(test), i + 1))
}

impl Registry {
    /// The registry of the rules. It fails if two rules have one code, or
    /// if the metadata of a rule is not that of the sqlfluff rule.
    pub fn new(rules: Vec<Box<dyn Rule>>) -> Result<Registry, String> {
        let mut problems = Vec::new();
        let mut codes = BTreeSet::new();
        for rule in &rules {
            if !codes.insert(rule.code()) {
                problems.push(format!("{}: two rules have this code", rule.code()));
            }
            problems.extend(metadata_problems(rule.as_ref()));
        }
        if !problems.is_empty() {
            return Err(problems.join("; "));
        }
        let mut rules = rules;
        rules.sort_by_key(|r| r.code());
        Ok(Registry { rules })
    }

    /// The rules of sqll, in code order.
    pub fn rules(&self) -> impl Iterator<Item = &dyn Rule> {
        self.rules.iter().map(|r| r.as_ref())
    }

    /// True if sqll has the rule with this code.
    pub fn has(&self, code: &str) -> bool {
        self.rules.iter().any(|r| r.code() == code)
    }

    /// The sqlfluff `rule_reference_map` of the sqlfluff rules (codes >
    /// names > groups > aliases). The references of sqll are those of
    /// sqlfluff, also for the rules that sqll does not have.
    pub fn reference_map() -> BTreeMap<String, BTreeSet<String>> {
        let one = |code: &str| BTreeSet::from([code.to_string()]);
        let mut map: BTreeMap<String, BTreeSet<String>> = RULES
            .iter()
            .map(|r| (r.code.to_string(), one(r.code)))
            .collect();
        for r in RULES {
            if !r.name.is_empty() && !map.contains_key(r.name) {
                map.insert(r.name.to_string(), one(r.code));
            }
        }
        let mut groups: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        for r in RULES {
            for g in r.groups {
                if !map.contains_key(*g) {
                    groups
                        .entry(g.to_string())
                        .or_default()
                        .insert(r.code.to_string());
                }
            }
        }
        map.extend(groups);
        let mut aliases: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        for r in RULES {
            for a in r.aliases {
                if !map.contains_key(*a) {
                    aliases
                        .entry(a.to_string())
                        .or_default()
                        .insert(r.code.to_string());
                }
            }
        }
        map.extend(aliases);
        map
    }

    /// The sqlfluff `_expand_rule_refs`: the codes of the references (a
    /// reference, or a glob over all references).
    pub fn expand(refs: &[String], map: &BTreeMap<String, BTreeSet<String>>) -> BTreeSet<String> {
        let mut out = BTreeSet::new();
        for r in refs {
            match map.get(r) {
                Some(codes) => out.extend(codes.iter().cloned()),
                None => {
                    for (key, codes) in map {
                        if fnmatch(key, r) {
                            out.extend(codes.iter().cloned());
                        }
                    }
                }
            }
        }
        out
    }

    /// The warnings of the sqlfluff `get_rulepack` for a config, in its
    /// order: each rule section for no rule (and its match by reference),
    /// and the references of `rules` and of `exclude_rules` that match no
    /// reference. sqlfluff logs them each time that it makes a rule pack.
    pub fn selection_warnings(config: &Config) -> Vec<String> {
        let map = Registry::reference_map();
        let mut out = Vec::new();
        if let Some(rules) = config.section(&["rules"]) {
            for (key, value) in rules {
                if !matches!(value, Value::Table(_)) || RULES.iter().any(|r| r.name == key) {
                    continue;
                }
                out.push(format!(
                    "Rule configuration contain a section for unexpected rule {}. \
                     These values will be ignored.",
                    py_repr(key)
                ));
                let Some(codes) = map.get(key) else {
                    continue;
                };
                if codes.len() == 1 {
                    let code = codes.iter().next().expect("one code");
                    let name = sqlfluff_rule(code).map_or("", |r| r.name);
                    out.push(format!(
                        "The reference was however found as a match for rule {code} with name \
                         {}. SQLFluff assumes configuration for this rule will be specified \
                         in 'sqlfluff:rules:{name}'.",
                        py_repr(name)
                    ));
                } else if !codes.is_empty() {
                    let set: Vec<String> = codes.iter().map(|c| py_repr(c)).collect();
                    out.push(format!(
                        "The reference was found as a match for multiple rules: {{{}}}. Config \
                         should be specified by the name of the relevant rule e.g. \
                         'sqlfluff:rules:capitalisation.keywords'.",
                        set.join(", ")
                    ));
                }
            }
        }
        let list = |key: &str| -> Vec<String> {
            match config.core(key) {
                Some(Value::List(items)) => items.iter().filter_map(Value::py_str).collect(),
                _ => Vec::new(),
            }
        };
        let unknown = |refs: Vec<String>| -> Vec<String> {
            refs.into_iter()
                .filter(|r| !map.keys().any(|k| fnmatch(k, r)))
                .collect()
        };
        let py_list = |items: &[String]| -> String {
            let parts: Vec<String> = items.iter().map(|i| py_repr(i)).collect();
            format!("[{}]", parts.join(", "))
        };
        let allow = unknown(list("rule_allowlist"));
        if !allow.is_empty() {
            out.push(format!(
                "Tried to allowlist unknown rule references: {}",
                py_list(&allow)
            ));
        }
        let deny = unknown(list("rule_denylist"));
        if !deny.is_empty() {
            out.push(format!(
                "Tried to denylist unknown rules references: {}",
                py_list(&deny)
            ));
        }
        out
    }

    /// The codes of the sqlfluff rules that the config selects (`rules` and
    /// `exclude_rules`, as the sqlfluff `get_rulepack`), in code order. Also
    /// the rules that sqll does not have.
    fn selected_codes(config: &Config) -> Vec<&'static str> {
        let map = Registry::reference_map();
        let list = |key: &str| -> Vec<String> {
            match config.core(key) {
                Some(Value::List(items)) => items.iter().filter_map(Value::py_str).collect(),
                _ => Vec::new(),
            }
        };
        let mut allow = list("rule_allowlist");
        if allow.is_empty() {
            allow = RULES.iter().map(|r| r.code.to_string()).collect();
        }
        let deny = list("rule_denylist");
        let allowed = Registry::expand(&allow, &map);
        let denied = Registry::expand(&deny, &map);
        RULES
            .iter()
            .map(|r| r.code)
            .filter(|c| allowed.contains(*c) && !denied.contains(*c))
            .collect()
    }

    /// The sqlfluff `get_rulepack`: the rules that the config selects, with
    /// their config. It fails closed if it selects a rule that sqll does
    /// not have, and fails as sqlfluff for an invalid rule config value.
    pub fn select(&self, config: &Config) -> Result<RulePack<'_>, LintError> {
        let rules_section = config.section(&["rules"]).cloned().unwrap_or_default();
        validate_options(&rules_section)?;
        let map = Registry::reference_map();
        let codes = Registry::selected_codes(config);
        let missing: Vec<&str> = codes.iter().copied().filter(|c| !self.has(c)).collect();
        if !missing.is_empty() {
            return Err(LintError::Unsupported(format!(
                "rules {}: sqll does not have them yet (S5)",
                missing.join(", ")
            )));
        }
        let mut rules = Vec::new();
        for code in codes {
            let m = sqlfluff_rule(code).expect("a code of RULES");
            if let Some(section) = config.rule_section(m.name) {
                validate_options(section)?;
            }
            let rule = self.get(code).expect("the registry has the rule");
            let rule_config = RuleConfig::new(config, m.name);
            for key in rule.config_keywords() {
                if rule_config.get(key).is_none() {
                    return Err(LintError::Invalid(format!(
                        "Unrecognized config '{key}' for Rule {code}. If this is a new \
                         option, please add it to `default_config.cfg` or plugin specific \
                         config."
                    )));
                }
            }
            rule.check_config(&rule_config)?;
            rules.push((rule, rule_config));
        }
        Ok(RulePack {
            rules,
            reference_map: map,
        })
    }

    /// The rule with this code.
    pub fn get(&self, code: &str) -> Option<&dyn Rule> {
        self.rules().find(|r| r.code() == code)
    }
}

#[cfg(test)]
mod tests {
    use super::py_repr;

    #[test]
    fn a_text_is_written_as_python_repr() {
        // Python 3.13: repr() of each name.
        for (name, want) in [
            ("a.sql", "'a.sql'"),
            ("it's.sql", "\"it's.sql\""),
            ("a\"b.sql", "'a\"b.sql'"),
            ("a'b\"c.sql", "'a\\'b\"c.sql'"),
            ("a\\b.sql", "'a\\\\b.sql'"),
            ("a\tb\nc\rd.sql", "'a\\tb\\nc\\rd.sql'"),
            ("a\x01\x1f\x7f.sql", "'a\\x01\\x1f\\x7f.sql'"),
            ("a\u{85}\u{a0}\u{ad}.sql", "'a\\x85\\xa0\\xad.sql'"),
            ("\u{e9}\u{ff}\u{a1}.sql", "'\u{e9}\u{ff}\u{a1}.sql'"),
            ("\u{1f600}.sql", "'\u{1f600}.sql'"),
        ] {
            assert_eq!(py_repr(name), want, "{name:?}");
        }
    }
}
