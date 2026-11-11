//! The config crate of sqll (docs/interfaces/config.md; S3b task C11).
//!
//! - [`Value`] and [`Table`]: the config model. Each value has the Python
//!   type that sqlfluff gives it ([`coerce_value`] for an INI value).
//! - [`defaults`]: the sqlfluff default config (`default_config.cfg`).
//! - [`Loader`]: the reader of the sqlfluff config files (`setup.cfg`,
//!   `tox.ini`, `pep8.ini`, `.sqlfluff`, `pyproject.toml`), in the
//!   sqlfluff order, and of the `--config` file.
//! - [`Config`]: a loaded config (`FluffConfig`): the defaults, the files,
//!   and the command line overrides.
//! - [`ParseSettings`]: the settings of `sqll parse`. A setting that sqll
//!   cannot do yet fails closed ([`ConfigError::Unsupported`]).

pub mod config;
pub mod defaults;
pub mod dict;
pub mod ini;
pub mod loader;
pub mod parse;
pub mod toml;
pub mod validate;
pub mod value;

use std::fmt;

pub use config::{Config, LoadOptions, TEMPLATERS};
pub use defaults::{default_table, defaults};
pub use loader::{Env, Loader, CONFIG_FILES};
pub use parse::{Encoding, ParseSettings, TemplaterName};
pub use value::{coerce_value, Table, Value};

/// An error of the config.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ConfigError {
    /// A config that sqlfluff refuses: an invalid file or value
    /// (`SQLFluffUserError`, or an error of the Python reader).
    Invalid(String),
    /// A file that cannot be read.
    Io(String),
    /// A setting, a value, or a form that sqll cannot do yet. sqll stops
    /// with "unsupported: ..." (fail closed).
    Unsupported(String),
}

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ConfigError::Invalid(m) | ConfigError::Io(m) => f.write_str(m),
            ConfigError::Unsupported(m) => write!(f, "unsupported: {m}"),
        }
    }
}

impl std::error::Error for ConfigError {}
