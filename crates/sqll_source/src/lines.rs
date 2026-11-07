//! Lines and positions of a text (docs/interfaces/tree.md, "Positions").
//! The syntax tree uses them for the templated text and the source map for
//! the source text.

/// A line and a position in the line, both from 1. The position counts
/// characters (Unicode scalar values), as sqlfluff does. Only "\n" ends a
/// line: the "\r" of "\r\n" is the last character of its line.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct LinePos {
    pub line: usize,
    pub pos: usize,
}

/// The byte offset of the start of each line of a text.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LineIndex {
    starts: Box<[u32]>,
}

impl LineIndex {
    /// The index of a text, or `None` if the text does not fit in a `u32`.
    pub fn new(text: &str) -> Option<Self> {
        if text.len() >= u32::MAX as usize {
            return None;
        }
        let mut starts = vec![0u32];
        starts.extend(
            text.bytes()
                .enumerate()
                .filter(|&(_, b)| b == b'\n')
                .map(|(i, _)| (i + 1) as u32),
        );
        Some(LineIndex {
            starts: starts.into_boxed_slice(),
        })
    }

    /// The number of lines: the number of "\n" and 1.
    pub fn line_count(&self) -> usize {
        self.starts.len()
    }

    /// The byte offset of the start of a line (from 1), or `None` if the
    /// text has no such line.
    pub fn line_start(&self, line: usize) -> Option<usize> {
        let i = line.checked_sub(1)?;
        self.starts.get(i).map(|&s| s as usize)
    }

    /// The line and position of the character at a byte offset of `text`
    /// (the text of this index). The offset `text.len()` is the position
    /// after the last character. `None` if the offset is after the end or
    /// not at the start of a character.
    pub fn line_pos(&self, text: &str, byte: usize) -> Option<LinePos> {
        if !text.is_char_boundary(byte) {
            return None;
        }
        let line = self.starts.partition_point(|&s| s as usize <= byte);
        let start = self.starts[line - 1] as usize;
        let before = &text.as_bytes()[start..byte];
        // Count the first byte of each character (not 0b10xxxxxx).
        let chars = before.iter().filter(|&&b| b & 0xC0 != 0x80).count();
        Some(LinePos {
            line,
            pos: chars + 1,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lines(text: &str) -> (LineIndex, Vec<Option<LinePos>>) {
        let index = LineIndex::new(text).unwrap();
        let all = (0..=text.len() + 1)
            .map(|b| index.line_pos(text, b))
            .collect();
        (index, all)
    }

    fn at(line: usize, pos: usize) -> Option<LinePos> {
        Some(LinePos { line, pos })
    }

    #[test]
    fn line_pos_counts_lines_at_newlines_and_characters_in_a_line() {
        let (index, all) = lines("ab\ncd\n");
        assert_eq!(index.line_count(), 3);
        assert_eq!(
            all,
            [
                at(1, 1),
                at(1, 2),
                at(1, 3),
                at(2, 1),
                at(2, 2),
                at(2, 3),
                at(3, 1),
                None
            ]
        );
        assert_eq!(index.line_start(1), Some(0));
        assert_eq!(index.line_start(3), Some(6));
        assert_eq!(index.line_start(0), None);
        assert_eq!(index.line_start(4), None);
    }

    #[test]
    fn line_pos_counts_a_multi_byte_character_one_time() {
        // "é" has 2 bytes, "😀" has 4 bytes.
        let text = "é😀x\n€";
        let (_, all) = lines(text);
        assert_eq!(all[0], at(1, 1));
        assert_eq!(all[1], None, "inside é");
        assert_eq!(all[2], at(1, 2));
        assert_eq!(all[3..6], [None, None, None], "inside 😀");
        assert_eq!(all[6], at(1, 3));
        assert_eq!(all[7], at(1, 4), "the newline");
        assert_eq!(all[8], at(2, 1));
        assert_eq!(all[11], at(2, 2), "the end of the text");
    }

    #[test]
    fn line_pos_keeps_the_carriage_return_in_its_line() {
        let (index, all) = lines("a\r\nb\r\n\r\nc");
        assert_eq!(index.line_count(), 4);
        assert_eq!(all[1], at(1, 2), "\\r");
        assert_eq!(all[2], at(1, 3), "\\n");
        assert_eq!(all[3], at(2, 1));
        assert_eq!(all[6], at(3, 1));
        assert_eq!(all[7], at(3, 2));
        assert_eq!(all[8], at(4, 1));
        assert_eq!(all[9], at(4, 2));
    }

    #[test]
    fn an_empty_text_has_one_line() {
        let (index, all) = lines("");
        assert_eq!(index.line_count(), 1);
        assert_eq!(all, [at(1, 1), None]);
    }
}
