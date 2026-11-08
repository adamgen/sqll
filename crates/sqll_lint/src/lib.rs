//! The rule and fix interface of sqll (docs/interfaces/rules.md; S3b task
//! C12).
//!
//! - [`Rule`]: the code, the name, the groups, the aliases, the config
//!   keywords, the crawl behaviour, and `eval` over the typed view with a
//!   [`RuleContext`] (the node, the rule config, and the memory of the
//!   crawl).
//! - [`LintResult`] and [`Fix`]: a violation at an anchor node, with fixes.
//!   A fix changes the templated text of its anchor; the source map changes
//!   it to a [`SourceEdit`], or refuses it in a templated range.
//! - [`Registry`] and [`RulePack`]: the rules of sqll, and the selection of
//!   the rules of a config, as sqlfluff (`rules`, `exclude_rules`, codes,
//!   names, groups, aliases, globs). A selected rule that sqll does not have
//!   fails closed ([`LintError::Unsupported`]).
//! - [`Linter`]: the lint and the fix loop of sqlfluff (`lint_fix_parsed`):
//!   apply the source edits, parse again, and lint again, up to the
//!   `runaway_limit` of the config.

pub mod config;
pub mod fix;
pub mod linter;
pub mod registry;
pub mod rule;
pub mod sqlfluff;

use std::fmt;

pub use config::{LintSettings, RuleConfig, Valid, Validation};
pub use fix::{apply_edits, Edit, Fix, FixRefusal, SourceEdit};
pub use linter::{LintedFile, Linter, SourceParser, TemplaterParser, Violation};
pub use registry::{Registry, RulePack};
pub use rule::{CrawlBehaviour, LintPhase, LintResult, Memory, Rule, RuleContext};
pub use sqlfluff::{SqlfluffRule, CONFIG_VALIDATION, RULES};

/// An error of a lint or a fix.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LintError {
    /// A config that sqlfluff refuses (`SQLFluffUserError`).
    Invalid(String),
    /// A rule, a setting, or a form that sqll cannot do yet. sqll stops
    /// with "unsupported: ..." and exit code 2 (fail closed).
    Unsupported(String),
    /// The templater or the parse interface refused the file.
    Parse(String),
}

impl fmt::Display for LintError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            LintError::Invalid(m) | LintError::Parse(m) => f.write_str(m),
            LintError::Unsupported(m) => write!(f, "unsupported: {m}"),
        }
    }
}

impl std::error::Error for LintError {}

impl From<sqll_config::ConfigError> for LintError {
    fn from(e: sqll_config::ConfigError) -> Self {
        match e {
            sqll_config::ConfigError::Unsupported(m) => LintError::Unsupported(m),
            sqll_config::ConfigError::Invalid(m) | sqll_config::ConfigError::Io(m) => {
                LintError::Invalid(m)
            }
        }
    }
}
