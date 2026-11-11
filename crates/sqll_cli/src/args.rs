//! The options of `lint`, `fix`, `rules`, and `dialects`, read as click
//! reads them: first all arguments (an unknown option or a missing value is
//! an error), then `-h`/`--help` has priority over each other check.

use crate::{unsupported, Error};

/// How an option takes its value.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    /// No value.
    Flag,
    /// One value (the next argument, the rest of a short group, or
    /// `--name=value`).
    Value,
}

/// An option of a command.
#[derive(Clone, Copy, Debug)]
pub struct Opt {
    /// The names, for example `["-f", "--format"]`.
    pub names: &'static [&'static str],
    /// The key that the command reads.
    pub key: &'static str,
    pub kind: Kind,
    /// False for an option of sqlfluff that sqll does not have yet: it
    /// fails closed (`unsupported: option ...`).
    pub supported: bool,
}

pub const fn flag(names: &'static [&'static str], key: &'static str) -> Opt {
    Opt {
        names,
        key,
        kind: Kind::Flag,
        supported: true,
    }
}

pub const fn value(names: &'static [&'static str], key: &'static str) -> Opt {
    Opt {
        names,
        key,
        kind: Kind::Value,
        supported: true,
    }
}

pub const fn not_yet(names: &'static [&'static str], kind: Kind) -> Opt {
    Opt {
        names,
        key: "",
        kind,
        supported: false,
    }
}

/// The options and the paths that the command line gives, in their order.
#[derive(Debug, Default)]
pub struct Parsed {
    /// (key, value) of each option, in order. A flag has no value.
    pub options: Vec<(&'static str, Option<String>)>,
    pub paths: Vec<String>,
    pub help: bool,
}

impl Parsed {
    /// The value of the last use of the option.
    pub fn value(&self, key: &str) -> Option<&str> {
        self.options
            .iter()
            .rev()
            .find(|(k, _)| *k == key)
            .and_then(|(_, v)| v.as_deref())
    }

    /// True if the flag is given.
    pub fn flag(&self, key: &str) -> bool {
        self.options.iter().any(|(k, _)| *k == key)
    }

    /// The count of uses of a flag.
    pub fn count(&self, key: &str) -> usize {
        self.options.iter().filter(|(k, _)| *k == key).count()
    }

    /// The position of the last use of the key, if any.
    pub fn last(&self, keys: &[&str]) -> Option<&'static str> {
        self.options
            .iter()
            .rev()
            .find(|(k, _)| keys.contains(k))
            .map(|(k, _)| *k)
    }
}

fn find<'o>(opts: &'o [Opt], name: &str) -> Option<&'o Opt> {
    opts.iter().find(|o| o.names.contains(&name))
}

fn no_such(name: &str, usage: &str) -> Error {
    Error::new(format!("No such option: {name}\n\n{usage}"))
}

fn check(opt: &Opt, name: &str) -> Result<(), Error> {
    if opt.supported {
        Ok(())
    } else {
        Err(unsupported(
            &format!("option {name}"),
            "sqll does not have this option of sqlfluff yet (S7)",
        ))
    }
}

/// Read the arguments of a command.
pub fn read(args: &[String], opts: &[Opt], usage: &str) -> Result<Parsed, Error> {
    let mut out = Parsed::default();
    let mut it = args.iter();
    let mut only_paths = false;
    // An unsupported option fails after all arguments are read, so that an
    // unknown option or --help has priority (as a usage error in click).
    let mut first_unsupported: Option<Error> = None;
    while let Some(arg) = it.next() {
        if only_paths || arg == "-" || !arg.starts_with('-') {
            out.paths.push(arg.clone());
            continue;
        }
        if arg == "--" {
            only_paths = true;
            continue;
        }
        if arg == "-h" || arg == "--help" {
            out.help = true;
            continue;
        }
        if let Some(long) = arg.strip_prefix("--") {
            let (name, inline) = match long.split_once('=') {
                Some((n, v)) => (format!("--{n}"), Some(v.to_string())),
                None => (arg.clone(), None),
            };
            let opt = find(opts, &name).ok_or_else(|| no_such(&name, usage))?;
            let value =
                match (opt.kind, inline) {
                    (Kind::Flag, Some(_)) => {
                        return Err(Error::new(format!(
                            "Option '{name}' does not take a value."
                        )))
                    }
                    (Kind::Flag, None) => None,
                    (Kind::Value, Some(v)) => Some(v),
                    (Kind::Value, None) => Some(it.next().cloned().ok_or_else(|| {
                        Error::new(format!("Option '{name}' requires an argument."))
                    })?),
                };
            if let Err(e) = check(opt, &name) {
                first_unsupported.get_or_insert(e);
            }
            out.options.push((opt.key, value));
            continue;
        }
        // A group of short options: "-qn", "-fjson", "-f json".
        let group = &arg[1..];
        for (i, c) in group.char_indices() {
            let name = format!("-{c}");
            if c == 'h' {
                out.help = true;
                continue;
            }
            let opt = find(opts, &name).ok_or_else(|| no_such(&name, usage))?;
            if let Err(e) = check(opt, &name) {
                first_unsupported.get_or_insert(e);
            }
            if opt.kind == Kind::Flag {
                out.options.push((opt.key, None));
                continue;
            }
            let tail = &group[i + c.len_utf8()..];
            let value = if tail.is_empty() {
                it.next()
                    .cloned()
                    .ok_or_else(|| Error::new(format!("Option '{name}' requires an argument.")))?
            } else {
                tail.to_string()
            };
            out.options.push((opt.key, Some(value)));
            break;
        }
    }
    if out.help {
        return Ok(out);
    }
    if let Some(e) = first_unsupported {
        return Err(e);
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    const OPTS: &[Opt] = &[
        value(&["-f", "--format"], "format"),
        flag(&["-q", "--quiet"], "quiet"),
        flag(&["-n", "--nocolor"], "nocolor"),
        not_yet(&["-v", "--verbose"], Kind::Flag),
    ];

    fn read_args(args: &[&str]) -> Result<Parsed, Error> {
        let args: Vec<String> = args.iter().map(|s| s.to_string()).collect();
        read(&args, OPTS, "usage")
    }

    #[test]
    fn options_are_read_as_click_reads_them() {
        let p = read_args(&["-qnfjson", "a.sql", "--format=yaml", "-", "--", "-x"]).unwrap();
        assert_eq!(p.paths, ["a.sql", "-", "-x"]);
        assert_eq!(p.value("format"), Some("yaml"));
        assert!(p.flag("quiet") && p.flag("nocolor"));
        assert!(read_args(&["--nope"])
            .unwrap_err()
            .text
            .contains("No such option: --nope"));
        assert!(read_args(&["-f"])
            .unwrap_err()
            .text
            .contains("requires an argument"));
        assert!(read_args(&["-v"])
            .unwrap_err()
            .text
            .contains("unsupported: option -v"));
        assert!(read_args(&["-v", "-h"]).unwrap().help);
        assert!(read_args(&["-v", "--nope", "-h"]).is_err());
    }
}
