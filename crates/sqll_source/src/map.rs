// Parts of this file are a port of sqlfluff 4.4.0 code (sqlfluffrs):
// sqlfluffrs/sqlfluffrs_types/src/templater/templatefile.rs (the slice
// search of find_slice_indices_of_templated_pos and the rule for an empty
// slice of templated_slice_to_source_slice, in SourceMap::point_maps).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The source map (docs/interfaces/source-map.md): byte offsets of the
//! templated text to byte offsets, lines, and positions of the source
//! text, over the ported [`TemplatedFile`].
//!
//! The `TemplatedFile` of sqlfluff counts code points (Python `str`
//! offsets). The map takes and gives byte offsets, as the syntax tree does,
//! and converts them. It uses the ported `templated_slice_to_source_slice`
//! and `is_source_slice_literal`, so it gives the answers of sqlfluff. It
//! checks each input first, so that no call panics: [`SourceMap::new`]
//! refuses a file that breaks a rule of its slices, and an offset must be
//! at a character of its text.

use std::fmt;
use std::ops::Range;
use std::sync::Arc;

use sqll_types::{Slice, TemplatedFile, TemplatedFileSlice};

use crate::lines::{LineIndex, LinePos};

/// The slice type of the text that the templater did not change.
const LITERAL: &str = "literal";

/// An error of the source map.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SourceMapError {
    /// The byte offset is after the end of its text (`len` bytes).
    OutOfRange { at: usize, len: usize },
    /// The byte offset is inside a character.
    NotCharBoundary { at: usize },
    /// The range starts after its end.
    Reversed { start: usize, end: usize },
    /// A point (an empty range) at this templated byte is inside the output
    /// of a template tag, so no source point agrees with it. sqlfluff raises
    /// a ValueError for it.
    InTemplatedSection { at: usize },
    /// The `TemplatedFile` breaks a rule of its slices.
    InvalidFile(String),
}

impl fmt::Display for SourceMapError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SourceMapError::OutOfRange { at, len } => {
                write!(f, "byte {at} is after the end of the text ({len} bytes)")
            }
            SourceMapError::NotCharBoundary { at } => {
                write!(f, "byte {at} is inside a character")
            }
            SourceMapError::Reversed { start, end } => {
                write!(f, "the range {start}..{end} starts after its end")
            }
            SourceMapError::InTemplatedSection { at } => write!(
                f,
                "the templated point at byte {at} is inside a templated section"
            ),
            SourceMapError::InvalidFile(why) => write!(f, "invalid templated file: {why}"),
        }
    }
}

impl std::error::Error for SourceMapError {}

/// The byte offset of each code point of a text and of its end. An ASCII
/// text keeps no table: a code point offset is a byte offset.
#[derive(Clone, Debug)]
struct Chars {
    bytes: usize,
    count: usize,
    offsets: Option<Box<[u32]>>,
}

impl Chars {
    /// The text must be shorter than 4 GiB (`SourceMap::new` checks it).
    fn new(text: &str) -> Self {
        if text.is_ascii() {
            return Chars {
                bytes: text.len(),
                count: text.len(),
                offsets: None,
            };
        }
        let offsets: Box<[u32]> = text
            .char_indices()
            .map(|(b, _)| b as u32)
            .chain(std::iter::once(text.len() as u32))
            .collect();
        Chars {
            bytes: text.len(),
            count: offsets.len() - 1,
            offsets: Some(offsets),
        }
    }

    fn byte(&self, char_index: usize) -> Option<usize> {
        if char_index > self.count {
            return None;
        }
        Some(match &self.offsets {
            None => char_index,
            Some(o) => o[char_index] as usize,
        })
    }

    fn char_index(&self, byte: usize) -> Result<usize, SourceMapError> {
        if byte > self.bytes {
            return Err(SourceMapError::OutOfRange {
                at: byte,
                len: self.bytes,
            });
        }
        match &self.offsets {
            None => Ok(byte),
            Some(o) => o
                .binary_search(&(byte as u32))
                .map_err(|_| SourceMapError::NotCharBoundary { at: byte }),
        }
    }

    fn range(&self, r: &Range<usize>) -> Result<Slice, SourceMapError> {
        if r.start > r.end {
            return Err(SourceMapError::Reversed {
                start: r.start,
                end: r.end,
            });
        }
        Ok(Slice::from(
            self.char_index(r.start)?..self.char_index(r.end)?,
        ))
    }
}

/// The map between the templated text and the source text of one
/// [`TemplatedFile`].
#[derive(Clone)]
pub struct SourceMap {
    file: Arc<TemplatedFile>,
    identity: bool,
    source_chars: Chars,
    templated_chars: Chars,
    source_lines: LineIndex,
}

impl fmt::Debug for SourceMap {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SourceMap")
            .field("fname", &self.file.fname)
            .field("identity", &self.identity)
            .field("source_bytes", &self.file.source_str.len())
            .field("templated_bytes", &self.file.templated_str.len())
            .field("slices", &self.file.sliced_file.len())
            .finish()
    }
}

fn invalid<T>(why: String) -> Result<T, SourceMapError> {
    Err(SourceMapError::InvalidFile(why))
}

/// The code point length of a text.
fn char_count(text: &str) -> usize {
    text.chars().count()
}

/// Check the rules of the slices of a file (code point offsets): the
/// templated slices are in order and cover the templated text; each source
/// slice is in the source text; a literal slice has the same text in the
/// source and in the templated text, or no templated text (sqlfluff:
/// whitespace that a tag removes, or a branch that the render does not
/// reach); the raw slices cover the source text, in order, each with its
/// text.
fn check_file(
    file: &TemplatedFile,
    source: &Chars,
    templated: &Chars,
) -> Result<(), SourceMapError> {
    let (src, tpl) = (&file.source_str, &file.templated_str);
    if file.sliced_file.is_empty() {
        return invalid("no templated slice".into());
    }
    let mut at = 0;
    for (i, s) in file.sliced_file.iter().enumerate() {
        let (t, o) = (s.templated_codepoint_slice, s.source_codepoint_slice);
        if t.start != at || t.stop < t.start {
            return invalid(format!("templated slice {i} ({t}) does not follow at {at}"));
        }
        at = t.stop;
        if o.stop < o.start || o.stop > source.count {
            return invalid(format!("source slice {i} ({o}) is not in the source text"));
        }
        if s.slice_type == LITERAL {
            let text = |chars: &Chars, text: &'_ str, sl: Slice| -> Option<String> {
                let (a, b) = (chars.byte(sl.start)?, chars.byte(sl.stop)?);
                text.get(a..b).map(str::to_string)
            };
            let same = t.is_empty()
                || (t.len() == o.len()
                    && t.stop <= templated.count
                    && text(source, src, o) == text(templated, tpl, t));
            if !same {
                return invalid(format!(
                    "literal slice {i} ({o} to {t}) is not the same text and not empty"
                ));
            }
        }
    }
    if at != templated.count {
        return invalid(format!(
            "the templated slices end at {at}, not at the end of the templated text ({})",
            templated.count
        ));
    }
    if file.raw_sliced.is_empty() {
        return invalid("no raw slice".into());
    }
    let mut at = 0;
    for (i, r) in file.raw_sliced.iter().enumerate() {
        if r.source_idx != at {
            return invalid(format!("raw slice {i} does not start at {at}"));
        }
        let len = char_count(&r.raw);
        let same = source
            .byte(at)
            .zip(source.byte(at + len))
            .and_then(|(a, b)| src.get(a..b))
            .is_some_and(|t| t == r.raw);
        if !same {
            return invalid(format!("raw slice {i} is not the source text at {at}"));
        }
        at += len;
    }
    if at != source.count {
        return invalid(format!(
            "the raw slices end at {at}, not at the end of the source text ({})",
            source.count
        ));
    }
    Ok(())
}

/// True if the file does not change its text: the same text, and only
/// literal slices that map each offset to itself.
fn is_identity(file: &TemplatedFile) -> bool {
    file.source_str == file.templated_str
        && file.sliced_file.iter().all(|s| {
            s.slice_type == LITERAL && s.source_codepoint_slice == s.templated_codepoint_slice
        })
        && file.raw_sliced.iter().all(|r| r.slice_type == LITERAL)
}

impl SourceMap {
    /// The map of a file. It fails if a text does not fit in a `u32` or if
    /// the file breaks a rule of its slices.
    pub fn new(file: Arc<TemplatedFile>) -> Result<SourceMap, SourceMapError> {
        let limit = u32::MAX as usize;
        if file.source_str.len() >= limit || file.templated_str.len() >= limit {
            return invalid("a text does not fit in a u32".into());
        }
        let source_chars = Chars::new(&file.source_str);
        let templated_chars = Chars::new(&file.templated_str);
        check_file(&file, &source_chars, &templated_chars)?;
        let source_lines = LineIndex::new(&file.source_str).expect("the length is checked");
        Ok(SourceMap {
            identity: is_identity(&file),
            file,
            source_chars,
            templated_chars,
            source_lines,
        })
    }

    /// The map of a text that no templater changed (the raw templater).
    pub fn identity(text: String, fname: String) -> Result<SourceMap, SourceMapError> {
        SourceMap::new(Arc::new(TemplatedFile::new(text, fname, None, None, None)))
    }

    pub fn file(&self) -> &Arc<TemplatedFile> {
        &self.file
    }

    pub fn source_text(&self) -> &str {
        &self.file.source_str
    }

    pub fn templated_text(&self) -> &str {
        &self.file.templated_str
    }

    /// True if the source text is the templated text and each byte maps to
    /// itself (for example the output of the raw templater).
    pub fn is_identity(&self) -> bool {
        self.identity
    }

    pub fn source_lines(&self) -> &LineIndex {
        &self.source_lines
    }

    /// The source range of a templated range, as the sqlfluff
    /// `TemplatedFile.templated_slice_to_source_slice`. A range in a literal
    /// slice maps exactly. A range that touches a templated slice takes all
    /// of the source of that slice. An empty range at the edge of slices
    /// maps to the first source point there; an empty range inside a
    /// templated slice is an error.
    pub fn source_range(&self, templated: Range<usize>) -> Result<Range<usize>, SourceMapError> {
        let slice = self.templated_chars.range(&templated)?;
        if self.identity {
            return Ok(templated);
        }
        if slice.start == slice.stop && !self.point_maps(slice.start) {
            return Err(SourceMapError::InTemplatedSection {
                at: templated.start,
            });
        }
        let out = self.file.templated_slice_to_source_slice(slice);
        match (
            self.source_chars.byte(out.start),
            self.source_chars.byte(out.stop),
        ) {
            (Some(a), Some(b)) if a <= b => Ok(a..b),
            _ => invalid(format!("the source slice {out} is not in the source text")),
        }
    }

    /// The source byte of a templated point: the start of the source range
    /// of the empty templated range at the byte.
    pub fn source_byte(&self, templated_byte: usize) -> Result<usize, SourceMapError> {
        self.source_range(templated_byte..templated_byte)
            .map(|r| r.start)
    }

    /// The line and position of a source byte, or `None` if the byte is
    /// after the end or not at the start of a character.
    pub fn source_line_pos(&self, source_byte: usize) -> Option<LinePos> {
        self.source_lines
            .line_pos(&self.file.source_str, source_byte)
    }

    /// The source line and position of a templated point
    /// ([`SourceMap::source_byte`]).
    pub fn source_pos(&self, templated_byte: usize) -> Result<LinePos, SourceMapError> {
        let byte = self.source_byte(templated_byte)?;
        self.source_line_pos(byte)
            .ok_or_else(|| SourceMapError::InvalidFile(format!("no position at byte {byte}")))
    }

    /// True if the source range has only literal source text, as the
    /// sqlfluff `TemplatedFile.is_source_slice_literal`: a fix can change it
    /// safely. An empty range is literal.
    pub fn is_source_literal(&self, source: Range<usize>) -> Result<bool, SourceMapError> {
        let slice = self.source_chars.range(&source)?;
        Ok(self.identity || self.file.is_source_slice_literal(&slice))
    }

    /// True if the source range of the templated range is literal
    /// ([`SourceMap::source_range`], [`SourceMap::is_source_literal`]).
    pub fn is_literal(&self, templated: Range<usize>) -> Result<bool, SourceMapError> {
        let source = self.source_range(templated)?;
        self.is_source_literal(source)
    }

    /// The byte offset of a code point offset of the source text.
    pub fn source_byte_of_char(&self, char_index: usize) -> Option<usize> {
        self.source_chars.byte(char_index)
    }

    /// The code point offset of a byte offset of the source text.
    pub fn source_char_of_byte(&self, byte: usize) -> Result<usize, SourceMapError> {
        self.source_chars.char_index(byte)
    }

    /// The byte offset of a code point offset of the templated text.
    pub fn templated_byte_of_char(&self, char_index: usize) -> Option<usize> {
        self.templated_chars.byte(char_index)
    }

    /// The code point offset of a byte offset of the templated text.
    pub fn templated_char_of_byte(&self, byte: usize) -> Result<usize, SourceMapError> {
        self.templated_chars.char_index(byte)
    }

    /// False if the ported `templated_slice_to_source_slice` panics for the
    /// empty slice at the code point `pos` (sqlfluff: "Attempting a single
    /// length slice within a templated section!"). The slices that touch
    /// `pos` are those of the ported `find_slice_indices_of_templated_pos`
    /// (inclusive): from the first slice that ends at or after `pos` to the
    /// first slice that starts after `pos`.
    fn point_maps(&self, pos: usize) -> bool {
        let sliced: &[TemplatedFileSlice] = &self.file.sliced_file;
        let Some(first) = sliced
            .iter()
            .position(|s| s.templated_codepoint_slice.stop >= pos)
        else {
            return false;
        };
        let last = sliced[first..]
            .iter()
            .position(|s| s.templated_codepoint_slice.start > pos)
            .map_or(sliced.len(), |i| first + i);
        let touching = &sliced[first..last];
        self.file.get_insertion_point(touching, pos).is_some()
            || touching.first().is_some_and(|s| s.slice_type == LITERAL)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sqll_types::RawFileSlice;

    fn lit(o: Range<usize>, t: Range<usize>) -> TemplatedFileSlice {
        TemplatedFileSlice::new(LITERAL.into(), Slice::from(o), Slice::from(t))
    }

    fn tpl(o: Range<usize>, t: Range<usize>) -> TemplatedFileSlice {
        TemplatedFileSlice::new("templated".into(), Slice::from(o), Slice::from(t))
    }

    fn raw(text: &str, ty: &str, at: usize) -> RawFileSlice {
        RawFileSlice::new(text.into(), ty.into(), at, None, None)
    }

    /// "é{{x}}ü" to "éVALü": one templated section between multi-byte
    /// characters (code points: source 0..1, 1..6, 6..7; templated 0..1,
    /// 1..4, 4..5).
    fn small() -> SourceMap {
        let file = TemplatedFile::new(
            "é{{x}}ü".into(),
            "small.sql".into(),
            Some("éVALü".into()),
            Some(vec![lit(0..1, 0..1), tpl(1..6, 1..4), lit(6..7, 4..5)]),
            Some(vec![
                raw("é", LITERAL, 0),
                raw("{{x}}", "templated", 1),
                raw("ü", LITERAL, 6),
            ]),
        );
        SourceMap::new(Arc::new(file)).unwrap()
    }

    #[test]
    fn a_templated_map_gives_byte_ranges() {
        let map = small();
        assert!(!map.is_identity());
        // Bytes: source "é" 0..2, "{{x}}" 2..7, "ü" 7..9; templated "é"
        // 0..2, "VAL" 2..5, "ü" 5..7.
        assert_eq!(map.source_range(0..2), Ok(0..2));
        assert_eq!(map.source_range(5..7), Ok(7..9));
        assert_eq!(map.source_range(2..5), Ok(2..7));
        assert_eq!(map.source_range(3..4), Ok(2..7), "inside VAL");
        assert_eq!(map.source_range(0..7), Ok(0..9));
        assert_eq!(map.source_byte(2), Ok(2));
        assert_eq!(map.source_byte(5), Ok(7));
        assert_eq!(map.source_byte(7), Ok(9));
        assert_eq!(
            map.source_byte(3),
            Err(SourceMapError::InTemplatedSection { at: 3 })
        );
        assert_eq!(map.is_literal(0..2), Ok(true));
        assert_eq!(map.is_literal(5..7), Ok(true));
        assert_eq!(map.is_literal(2..5), Ok(false));
        assert_eq!(map.is_literal(0..7), Ok(false));
        assert_eq!(map.is_literal(2..2), Ok(true), "an empty range");
        assert_eq!(map.source_pos(5).map(|p| p.pos), Ok(7));
    }

    #[test]
    fn an_offset_must_be_at_a_character_of_its_text() {
        let map = small();
        assert_eq!(
            map.source_range(1..2),
            Err(SourceMapError::NotCharBoundary { at: 1 })
        );
        assert_eq!(
            map.source_range(0..8),
            Err(SourceMapError::OutOfRange { at: 8, len: 7 })
        );
        assert_eq!(
            map.source_range(2..0),
            Err(SourceMapError::Reversed { start: 2, end: 0 })
        );
        assert_eq!(
            map.is_source_literal(8..9),
            Err(SourceMapError::NotCharBoundary { at: 8 })
        );
        assert_eq!(map.source_line_pos(1), None);
        assert_eq!(map.source_char_of_byte(7), Ok(6));
        assert_eq!(map.templated_byte_of_char(4), Some(5));
        assert_eq!(map.templated_byte_of_char(6), None);
    }

    #[test]
    fn the_raw_text_maps_to_itself() {
        let map = SourceMap::identity("é\r\nab".into(), "raw.sql".into()).unwrap();
        assert!(map.is_identity());
        for b in [0, 2, 3, 4, 6] {
            assert_eq!(map.source_byte(b), Ok(b));
        }
        assert_eq!(map.source_range(2..6), Ok(2..6));
        assert_eq!(map.is_literal(0..6), Ok(true));
        assert_eq!(map.source_line_pos(4), Some(LinePos { line: 2, pos: 1 }));
        assert_eq!(map.source_line_pos(3), Some(LinePos { line: 1, pos: 3 }));
        assert_eq!(
            map.source_byte(1),
            Err(SourceMapError::NotCharBoundary { at: 1 })
        );
    }

    /// "ab{x--cde" to "abVcde": the source slices are not in order (the
    /// raw slice "--" is in no templated slice). The insertion point of the
    /// templated byte 3 is the source byte 4, and no slice starts there, so
    /// the ported search moves the start slice after the stop slice.
    fn unordered() -> SourceMap {
        let file = TemplatedFile::new(
            "ab{x--cde".into(),
            "unordered.sql".into(),
            Some("abVcde".into()),
            Some(vec![
                lit(0..2, 0..2),
                tpl(2..4, 2..3),
                lit(6..8, 3..5),
                lit(8..9, 5..6),
            ]),
            Some(vec![
                raw("ab", LITERAL, 0),
                raw("{x", "templated", 2),
                raw("--", "comment", 4),
                raw("cd", LITERAL, 6),
                raw("e", LITERAL, 8),
            ]),
        );
        SourceMap::new(Arc::new(file)).unwrap()
    }

    #[test]
    fn a_start_after_its_stop_slice_maps_as_sqlfluff() {
        let map = unordered();
        // (templated range, source range, literal): the answers of the
        // pinned sqlfluff TemplatedFile for each templated range.
        let want: [(Range<usize>, Range<usize>, bool); 28] = [
            (0..0, 0..0, true),
            (0..1, 0..1, true),
            (0..2, 0..2, true),
            (0..3, 0..4, false),
            (0..4, 0..7, false),
            (0..5, 0..8, false),
            (0..6, 0..9, false),
            (1..1, 1..1, true),
            (1..2, 1..2, true),
            (1..3, 1..4, false),
            (1..4, 1..7, false),
            (1..5, 1..8, false),
            (1..6, 1..9, false),
            (2..2, 2..2, true),
            (2..3, 2..4, false),
            (2..4, 2..7, false),
            (2..5, 2..8, false),
            (2..6, 2..9, false),
            (3..3, 4..4, true),
            (3..4, 4..7, false),
            (3..5, 4..8, false),
            (3..6, 4..9, false),
            (4..4, 7..7, true),
            (4..5, 7..8, true),
            (4..6, 7..9, true),
            (5..5, 8..8, true),
            (5..6, 8..9, true),
            (6..6, 9..9, true),
        ];
        for (t, s, literal) in want {
            assert_eq!(map.source_range(t.clone()), Ok(s), "{t:?}");
            assert_eq!(map.is_literal(t.clone()), Ok(literal), "{t:?}");
        }
    }

    /// A small random number generator (xorshift), so that the test gives
    /// the same files each run.
    struct Rng(u64);

    impl Rng {
        fn below(&mut self, n: usize) -> usize {
            self.0 ^= self.0 << 13;
            self.0 ^= self.0 >> 7;
            self.0 ^= self.0 << 17;
            (self.0 % n as u64) as usize
        }
    }

    /// Characters of 1, 2, 3, and 4 UTF-8 bytes, CR, and LF.
    const CHARS: [char; 8] = ['a', 'b', ' ', 'é', '€', '😀', '\r', '\n'];

    fn random_text(rng: &mut Rng, max: usize) -> String {
        (0..rng.below(max + 1))
            .map(|_| CHARS[rng.below(CHARS.len())])
            .collect()
    }

    /// A random range in 0..n.
    fn random_range(rng: &mut Rng, n: usize) -> Range<usize> {
        let a = rng.below(n + 1);
        a..a + rng.below(n - a + 1)
    }

    /// A random file that `SourceMap::new` accepts (code point offsets):
    /// raw slices of 0 to 5 random characters of random types; then 1 to 6
    /// templated slices. A literal slice takes a random part of one raw
    /// slice (two slices can take the same or overlapping parts), with its
    /// text or with no templated text. A templated slice takes a random
    /// source range (it can be empty) and gives 0 to 3 random characters.
    fn random_file(rng: &mut Rng) -> TemplatedFile {
        let (mut source, mut count, mut raws) = (String::new(), 0, Vec::new());
        for _ in 0..1 + rng.below(6) {
            let text = random_text(rng, 5);
            let ty = ["literal", "templated", "comment", "block_start"][rng.below(4)];
            raws.push(raw(&text, ty, count));
            count += text.chars().count();
            source.push_str(&text);
        }
        let chars: Vec<char> = source.chars().collect();
        let (mut templated, mut at, mut slices) = (String::new(), 0, Vec::new());
        for _ in 0..1 + rng.below(6) {
            let start = at;
            match rng.below(3) {
                kind @ (0 | 1) => {
                    let r: &RawFileSlice = &raws[rng.below(raws.len())];
                    let part = random_range(rng, r.raw.chars().count());
                    let o = r.source_idx + part.start..r.source_idx + part.end;
                    if kind == 0 {
                        templated.extend(&chars[o.clone()]);
                        at += o.len();
                    }
                    slices.push(lit(o, start..at));
                }
                _ => {
                    let text = random_text(rng, 3);
                    at += text.chars().count();
                    templated.push_str(&text);
                    slices.push(tpl(random_range(rng, count), start..at));
                }
            }
        }
        TemplatedFile::new(
            source,
            "random.sql".into(),
            Some(templated),
            Some(slices),
            Some(raws),
        )
    }

    /// Each byte range of the templated text of random files (also ranges
    /// that start or end inside a character): no call panics, and each
    /// answer is a range of whole characters of the source text. A range
    /// inside one literal slice maps to the same text. The answers of
    /// sqlfluff for such files: `scripts/s3b/source_map_oracle.py check`.
    #[test]
    fn no_range_of_an_accepted_file_panics() {
        let mut rng = Rng(0x5eed_c8);
        let (mut files, mut multi_byte, mut ranges, mut inside, mut not_char) = (0, 0, 0, 0, 0);
        for _ in 0..3000 {
            let file = random_file(&mut rng);
            let map = SourceMap::new(Arc::new(file)).expect("a valid file");
            let (src, tpl) = (map.source_text(), map.templated_text());
            for i in 0..=tpl.len() {
                let _ = map.source_pos(i);
                for j in i..=tpl.len() {
                    ranges += 1;
                    let Ok(s) = map.source_range(i..j) else {
                        let boundary = tpl.is_char_boundary(i) && tpl.is_char_boundary(j);
                        not_char += usize::from(!boundary);
                        continue;
                    };
                    assert!(src.get(s.clone()).is_some(), "{i}..{j}: {s:?}");
                    assert!(map.is_literal(i..j).is_ok());
                    if let Some(text) = literal_text_of(&map, i..j).filter(|_| i < j) {
                        assert_eq!(Some(text), src.get(s), "{i}..{j}");
                        inside += 1;
                    }
                }
            }
            files += 1;
            multi_byte += usize::from(!src.is_ascii() || !tpl.is_ascii());
        }
        assert!(
            files == 3000
                && multi_byte > 2000
                && ranges > 50_000
                && inside > 300
                && not_char > 20_000,
            "{files} files ({multi_byte} multi-byte), {ranges} ranges ({inside} inside a literal \
             slice, {not_char} not at a character)"
        );
    }

    /// The templated text of a byte range strictly inside one non-empty
    /// literal slice (it starts and ends inside the slice).
    fn literal_text_of(map: &SourceMap, r: Range<usize>) -> Option<&str> {
        let tpl = map.templated_text();
        let chars =
            map.templated_char_of_byte(r.start).ok()?..map.templated_char_of_byte(r.end).ok()?;
        map.file().sliced_file.iter().find_map(|s| {
            let t = s.templated_codepoint_slice;
            let inside = s.slice_type == LITERAL && t.start < chars.start && chars.end < t.stop;
            inside.then(|| &tpl[r.clone()])
        })
    }

    #[test]
    fn a_broken_file_is_refused() {
        let new = |slices: Vec<TemplatedFileSlice>, raws: Vec<RawFileSlice>| {
            let file = TemplatedFile::copy(
                "ab{{x}}".into(),
                "f.sql".into(),
                "abX".into(),
                slices,
                raws,
                vec![],
                vec![],
            );
            SourceMap::new(Arc::new(file))
        };
        let raws = || vec![raw("ab", LITERAL, 0), raw("{{x}}", "templated", 2)];
        assert!(new(vec![lit(0..2, 0..2), tpl(2..7, 2..3)], raws()).is_ok());
        // A literal slice with no templated text (a removed text).
        let removed = TemplatedFile::copy(
            "ab{{x}}".into(),
            "f.sql".into(),
            "XYZ".into(),
            vec![lit(0..2, 0..0), tpl(2..7, 0..3)],
            raws(),
            vec![],
            vec![],
        );
        assert!(SourceMap::new(Arc::new(removed)).is_ok());
        let refused =
            |r: Result<SourceMap, SourceMapError>| matches!(r, Err(SourceMapError::InvalidFile(_)));
        assert!(refused(new(vec![], raws())), "no slice");
        assert!(refused(new(vec![lit(0..2, 0..2)], raws())), "short");
        assert!(refused(new(vec![lit(0..2, 0..2), tpl(2..8, 2..3)], raws())));
        assert!(refused(new(vec![lit(0..2, 0..2), tpl(2..7, 3..3)], raws())));
        assert!(refused(new(vec![lit(0..1, 0..2), tpl(2..7, 2..3)], raws())));
        assert!(refused(new(vec![lit(1..3, 0..2), tpl(2..7, 2..3)], raws())));
        let bad_raw = vec![raw("ab", LITERAL, 0), raw("{{y}}", "templated", 2)];
        assert!(refused(new(
            vec![lit(0..2, 0..2), tpl(2..7, 2..3)],
            bad_raw
        )));
        let short_raw = vec![raw("ab", LITERAL, 0)];
        assert!(refused(new(
            vec![lit(0..2, 0..2), tpl(2..7, 2..3)],
            short_raw
        )));
    }
}
