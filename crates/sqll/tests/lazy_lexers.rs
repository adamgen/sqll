//! The lexer regexes compile at their first use (S3 T15, LexerMode::Lazy of
//! sqll_types). The tests are in one function, because the compiled
//! regexes are global state of the process.

use std::path::Path;
use std::str::FromStr;

use sqll_dialects::Dialect;
use sqll_lexer::{LexInput, Lexer};
use sqll_types::matcher::{CompiledRegex, LexMatcher, LexerMode};

/// The names of the dialects: the fixture folders of the pinned sqlfluff.
fn dialect_names() -> Vec<String> {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../third_party/sqlfluff/test/fixtures/dialects");
    let mut names: Vec<String> = std::fs::read_dir(dir)
        .expect("the sqlfluff submodule")
        .map(|e| e.unwrap().file_name().into_string().unwrap())
        .filter(|name| Dialect::from_str(name).is_ok())
        .collect();
    names.sort();
    names
}

/// Each matcher and the matchers in it (subdivider, trim_post_subdivide).
fn all_matchers<'a>(matchers: &'a [LexMatcher], out: &mut Vec<&'a LexMatcher>) {
    for m in matchers {
        out.push(m);
        for inner in [&m.subdivider, &m.trim_post_subdivide]
            .into_iter()
            .flatten()
        {
            all_matchers(std::slice::from_ref(inner.as_ref()), out);
        }
    }
}

fn compiled(m: &LexMatcher) -> Option<bool> {
    match &m.mode {
        LexerMode::Lazy(lazy, _) => Some(lazy.is_compiled()),
        _ => None,
    }
}

#[test]
fn a_run_compiles_only_the_regexes_that_it_uses_and_each_regex_compiles() {
    let names = dialect_names();
    assert_eq!(names.len(), 28);

    // 1. Before a lex, no regex of ansi is compiled. A lex of "SELECT 1"
    // compiles the regexes of the matchers that it tries, and not those
    // after the matchers that match.
    let ansi = Dialect::from_str("ansi").unwrap();
    let mut matchers = Vec::new();
    all_matchers(ansi.get_lexers(), &mut matchers);
    assert!(matchers.iter().all(|m| compiled(m) != Some(true)));
    let lexer = Lexer::new(None, ansi.get_lexers().clone());
    let (tokens, errors) = lexer.lex(LexInput::String("SELECT 1\n".to_string()), true);
    assert!(errors.is_empty());
    let raws: Vec<&str> = tokens.iter().map(|t| t.raw()).collect();
    assert_eq!(raws, ["SELECT", " ", "1", "\n", ""]);
    let names_of = |done: bool| -> Vec<&str> {
        ansi.get_lexers()
            .iter()
            .filter(|m| compiled(m) == Some(done))
            .map(|m| m.name.as_str())
            .collect()
    };
    let used = names_of(true);
    let unused = names_of(false);
    assert!(
        used.contains(&"whitespace") && used.contains(&"word"),
        "{used:?}"
    );
    assert!(!unused.is_empty(), "{used:?}");
    // The clones of a matcher (the lexer has a clone of the list) share the
    // compiled regex.
    for (a, b) in ansi
        .get_lexers()
        .iter()
        .zip(ansi.get_lexers().clone().iter())
    {
        assert_eq!(compiled(a), compiled(b), "{}", a.name);
    }

    // 2. Each lexer regex of each dialect compiles, as the source compiles
    // it when it makes the matchers: to a regex, or with a fallback
    // function, to that function. No pattern panics at its first use.
    let mut total = 0;
    for name in &names {
        let dialect = Dialect::from_str(name).unwrap();
        let mut matchers = Vec::new();
        all_matchers(dialect.get_lexers(), &mut matchers);
        for m in matchers {
            if let LexerMode::Lazy(lazy, _) = &m.mode {
                let kind = lazy.get();
                if let CompiledRegex::Function(_) = kind {
                    assert!(lazy.has_fallback(), "{name} {}", m.name);
                }
                assert!(lazy.is_compiled());
                total += 1;
            }
        }
    }
    assert!(total > 500, "{total}");
}
