//! The templaters of sqll (the S6 package; docs/interfaces/source-map.md).
//! Each one implements `sqll_source::Templater`. S3b task C8 adds the raw
//! templater. S6 adds the placeholder and Python format-string templaters,
//! S11 the Jinja templater. S3b task C11 adds [`jinja_is_literal`]: the
//! texts that the Jinja templater gives as the raw templater does.

pub mod jinja;
pub mod raw;

pub use jinja::{jinja_is_literal, JINJA_DELIMITERS};
pub use raw::RawTemplater;

use sqll_source::Templater;

/// The names of the templaters that sqll has, sorted.
pub const NAMES: &[&str] = &["raw"];

/// The templater of a config name, or `None` if sqll does not have it (the
/// caller fails closed: "unsupported", exit code 2).
pub fn by_name(name: &str) -> Option<Box<dyn Templater>> {
    match name {
        "raw" => Some(Box::new(RawTemplater)),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn each_name_gives_its_templater() {
        for &name in NAMES {
            assert_eq!(by_name(name).map(|t| t.name()), Some(name));
        }
        for name in ["jinja", "placeholder", "python", "dbt", "Raw", ""] {
            assert!(by_name(name).is_none(), "{name}");
        }
    }
}
