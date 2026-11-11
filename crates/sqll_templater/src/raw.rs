// Parts of this file are a port of sqlfluff 4.4.0 code: RawTemplater of
// src/sqlfluff/core/templaters/base.py.
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The raw templater: the sqlfluff `RawTemplater`. It does not change the
//! text: the `TemplatedFile` has one literal slice, and its source map is
//! the identity.

use sqll_source::{TemplatedFile, Templater, TemplaterConfig, TemplaterError};

/// The templater "raw".
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct RawTemplater;

impl Templater for RawTemplater {
    fn name(&self) -> &'static str {
        "raw"
    }

    /// `TemplatedFile(in_str, fname=fname)`, as sqlfluff. The raw templater
    /// reads no setting.
    fn process(
        &self,
        source: &str,
        fname: &str,
        _config: &TemplaterConfig,
    ) -> Result<TemplatedFile, TemplaterError> {
        Ok(TemplatedFile::new(
            source.to_string(),
            fname.to_string(),
            None,
            None,
            None,
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_raw_templater_does_not_change_the_text() {
        let file = RawTemplater
            .process("SELECT 'é'\n", "a.sql", &TemplaterConfig::new())
            .unwrap();
        assert_eq!(file.source_str, "SELECT 'é'\n");
        assert_eq!(file.templated_str, file.source_str);
        assert_eq!(file.fname, "a.sql");
        assert_eq!(file.sliced_file.len(), 1);
        assert_eq!(file.sliced_file[0].slice_type, "literal");
        assert_eq!(file.sliced_file[0].source_codepoint_slice.stop, 11);
        assert_eq!(file.raw_sliced.len(), 1);
        assert_eq!(RawTemplater.name(), "raw");
    }
}
