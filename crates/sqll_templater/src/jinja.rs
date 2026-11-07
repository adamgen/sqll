//! The part of the Jinja templater that sqll can do before S11: a text
//! with no Jinja delimiter. This file is new sqll code.

/// The delimiters of the sqlfluff Jinja environment with its default
/// settings: the start of a variable, a block, and a comment. sqlfluff sets
/// no line statement or line comment prefix.
pub const JINJA_DELIMITERS: [&str; 3] = ["{{", "{%", "{#"];

/// True if the text is not empty and has no Jinja delimiter. Then the
/// sqlfluff Jinja templater with its default settings gives the templated
/// file of the raw templater: the same text and one literal slice (S3b
/// C11; the proof is `scripts/s3b/config_oracle.py`, `jinja_as_raw` in
/// `results/S3b/C11-config.json`). For an empty text the Jinja templater
/// gives no slice, and the raw templater one empty literal slice.
pub fn jinja_is_literal(text: &str) -> bool {
    !text.is_empty() && !JINJA_DELIMITERS.iter().any(|d| text.contains(d))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_text_with_a_delimiter_is_not_literal() {
        for text in ["select 1\n", " ", "select '{' || '}'", "a % b", "# x"] {
            assert!(jinja_is_literal(text), "{text:?}");
        }
        for text in ["", "select {{ x }}", "{% if %}", "{# c #}", "'{{'"] {
            assert!(!jinja_is_literal(text), "{text:?}");
        }
    }
}
