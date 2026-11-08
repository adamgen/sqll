//! The phase times of "sqll parse --timings" (S3 T14, the parse speed work).
//!
//! Each phase is the time from the end of the phase before it (or the start
//! of main) to its end. The parse interface (sqll_syntax, S3b C9) gives the
//! times of its steps, which `add` puts into their phases. With --timings,
//! the last line of stderr is one JSON object: each phase in seconds,
//! "total_s" (the sum), and "tokens".

use std::time::{Duration, Instant};

/// The phases in their order:
///
/// - init: from the start of main to the end of the file read (the
///   arguments, the command thread, the dialect name, and the file);
/// - setup: the raw templater, the source map, and the lexer of the
///   dialect (the lazy lexer tables and regexes);
/// - lex: the lexer;
/// - parse: the parser (also the lazy regexes of the grammar);
/// - record: since S3b C9, the conversion of the parser tree to the syntax
///   tree (and the unparsable sections). S3 T15 to C9: no work. Before T15:
///   the record value of the tree and the check for unparsable segments;
/// - write: the stderr error lines, and the JSON output, which the writer
///   makes from the tree (also the check for unparsable segments);
/// - free: no work since S3 T15 (before T15: the drop of the parser, the
///   tokens, the tree, and the record). The process exits with no drop.
pub const PHASES: [&str; 7] = ["init", "setup", "lex", "parse", "record", "write", "free"];

pub struct Timer {
    last: Instant,
    seconds: [f64; PHASES.len()],
    pub tokens: usize,
}

impl Timer {
    pub fn new(start: Instant) -> Self {
        Timer {
            last: start,
            seconds: [0.0; PHASES.len()],
            tokens: 0,
        }
    }

    /// Add the time since the last mark to the phase.
    pub fn mark(&mut self, phase: &str) {
        let now = Instant::now();
        self.add(phase, now.duration_since(self.last));
        self.last = now;
    }

    /// Add a time to the phase.
    pub fn add(&mut self, phase: &str, time: Duration) {
        let i = PHASES
            .iter()
            .position(|p| *p == phase)
            .expect("a known phase");
        self.seconds[i] += time.as_secs_f64();
    }

    /// Start the next phase now. Use it after `add`.
    pub fn restart(&mut self) {
        self.last = Instant::now();
    }

    pub fn json(&self) -> String {
        let mut parts: Vec<String> = PHASES
            .iter()
            .zip(self.seconds)
            .map(|(p, s)| format!("\"{p}_s\": {s:.6}"))
            .collect();
        parts.push(format!(
            "\"total_s\": {:.6}",
            self.seconds.iter().sum::<f64>()
        ));
        parts.push(format!("\"tokens\": {}", self.tokens));
        format!("{{{}}}", parts.join(", "))
    }
}
