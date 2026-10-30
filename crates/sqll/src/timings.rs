//! The phase times of "sqll parse --timings" (S3 T14, the parse speed work).
//!
//! Each phase is the time from the end of the phase before it (or the start
//! of main) to its end. With --timings, the last line of stderr is one JSON
//! object: each phase in seconds, "total_s" (the sum), and "tokens".

use std::time::Instant;

/// The phases in their order:
///
/// - init: from the start of main to the end of the file read (the
///   arguments, the command thread, the dialect name, and the file);
/// - setup: the lexer of the dialect (the lazy lexer tables and regexes);
/// - lex: the lexer;
/// - parse: the parser (also the lazy regexes of the grammar);
/// - record: the record of the tree and the check for unparsable segments;
/// - write: the JSON output;
/// - free: the drop of the parser, the tokens, the tree, and the record.
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
        let i = PHASES
            .iter()
            .position(|p| *p == phase)
            .expect("a known phase");
        self.seconds[i] += now.duration_since(self.last).as_secs_f64();
        self.last = now;
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
