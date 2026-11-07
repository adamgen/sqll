//! The templater interface (docs/interfaces/source-map.md): a templater
//! takes the source text and gives a [`TemplatedFile`], the frozen input
//! of the lexer and of the source map.

use std::collections::BTreeMap;
use std::fmt;

use sqll_types::TemplatedFile;

/// The settings of the templaters: the keys and values of the sqlfluff
/// config sections under `templater`, as text. A section name has no
/// `sqlfluff:` prefix: for example `templater:placeholder` or
/// `templater:jinja:context`. The config (C11) fills it; each templater
/// reads its own sections and converts the values.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TemplaterConfig {
    sections: BTreeMap<String, BTreeMap<String, String>>,
}

impl TemplaterConfig {
    pub fn new() -> Self {
        Self::default()
    }

    /// Set a value. A later value of the same key replaces it.
    pub fn set(&mut self, section: &str, key: &str, value: &str) {
        self.sections
            .entry(section.to_string())
            .or_default()
            .insert(key.to_string(), value.to_string());
    }

    pub fn get(&self, section: &str, key: &str) -> Option<&str> {
        self.sections.get(section)?.get(key).map(String::as_str)
    }

    /// The keys and values of a section, sorted by key.
    pub fn section(&self, section: &str) -> Option<&BTreeMap<String, String>> {
        self.sections.get(section)
    }

    /// The names of the sections that have a value, sorted.
    pub fn section_names(&self) -> impl Iterator<Item = &str> {
        self.sections.keys().map(String::as_str)
    }
}

/// An error of a templater. Each one stops the work on the file.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TemplaterError {
    /// The template is not valid, or its render failed (the sqlfluff
    /// `SQLTemplaterError`, code TMP). `source_byte` is the source byte of
    /// the problem, if the templater knows it.
    Template {
        message: String,
        source_byte: Option<usize>,
    },
    /// A setting or a feature that sqll does not have. sqll fails closed:
    /// the command gives "unsupported" and exit code 2.
    Unsupported { message: String },
}

impl fmt::Display for TemplaterError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            TemplaterError::Template { message, .. } => write!(f, "{message}"),
            TemplaterError::Unsupported { message } => write!(f, "unsupported: {message}"),
        }
    }
}

impl std::error::Error for TemplaterError {}

/// A templater: the sqlfluff templater `process` (one variant).
pub trait Templater: Send + Sync {
    /// The name in the config (`templater = <name>`), for example "raw".
    fn name(&self) -> &'static str;

    /// Render the source text of the file `fname` with the settings of
    /// `config`. The `TemplatedFile` has the source text, the templated
    /// text, and the slices between them.
    fn process(
        &self,
        source: &str,
        fname: &str,
        config: &TemplaterConfig,
    ) -> Result<TemplatedFile, TemplaterError>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_config_keeps_values_by_section_and_key() {
        let mut c = TemplaterConfig::new();
        c.set("templater:placeholder", "param_style", "colon");
        c.set("templater:jinja:context", "b", "2");
        c.set("templater:jinja:context", "a", "1");
        c.set("templater:jinja:context", "a", "3");
        assert_eq!(c.get("templater:placeholder", "param_style"), Some("colon"));
        assert_eq!(c.get("templater:placeholder", "other"), None);
        assert_eq!(c.get("templater:python", "x"), None);
        let context: Vec<(&str, &str)> = c
            .section("templater:jinja:context")
            .unwrap()
            .iter()
            .map(|(k, v)| (k.as_str(), v.as_str()))
            .collect();
        assert_eq!(context, [("a", "3"), ("b", "2")]);
        assert_eq!(
            c.section_names().collect::<Vec<_>>(),
            ["templater:jinja:context", "templater:placeholder"]
        );
    }
}
