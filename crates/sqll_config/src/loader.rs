// This file is a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/config/loader.py (_get_user_config_dir_path,
// load_config_at_path, _load_user_appdir_config, load_config_up_to_path),
// src/sqlfluff/core/config/file.py (_load_raw_file_as_dict, _resolve_path,
// _resolve_paths_in_config, load_config_file_as_dict), and
// src/sqlfluff/core/helpers/file.py (iter_intermediate_paths).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.
//
// The path functions follow Python 3.13 os.path (posixpath: expanduser,
// join, dirname, commonpath, realpath) and pathlib (absolute), and
// platformdirs 4.13.0 (the user config folder of the sqlfluff tool venv).
// Changes: Rust in place of Python; a glob pattern in a path setting fails
// closed; only UTF-8 paths.

//! The reader of the sqlfluff config files: which files, in which order,
//! and the paths in them.

use std::collections::HashMap;
use std::ffi::OsString;
use std::fs;
use std::path::{Component, Path, PathBuf};

use crate::dict::nested_combine;
use crate::ini::load_ini_string;
use crate::toml::load_toml_string;
use crate::validate::validate_config_dict;
use crate::value::{Table, Value};
use crate::ConfigError;

/// The config files of a folder. A later file has priority.
pub const CONFIG_FILES: [&str; 5] = [
    "setup.cfg",
    "tox.ini",
    "pep8.ini",
    ".sqlfluff",
    "pyproject.toml",
];
const PYPROJECT: &str = "pyproject.toml";
const COMMA_SEPARATED_PATH_KEYS: [&str; 3] = [
    "load_macros_from_path",
    "loader_search_path",
    "exclude_macros_from_path",
];
const OPAQUE_SECTION: [&str; 3] = ["templater", "jinja", "context"];

/// The process facts that the reader uses: the working folder, `HOME`,
/// the home folder of the password database, and `XDG_CONFIG_HOME`.
#[derive(Clone, Debug)]
pub struct Env {
    pub cwd: String,
    pub home_var: Option<String>,
    pub passwd_home: Option<String>,
    pub xdg_config_home: Option<String>,
}

fn utf8(path: OsString, what: &str) -> Result<String, ConfigError> {
    path.into_string()
        .map_err(|p| ConfigError::Unsupported(format!("{what} {p:?}: sqll reads only UTF-8 paths")))
}

impl Env {
    /// The facts of this process.
    pub fn from_process() -> Result<Env, ConfigError> {
        let cwd = std::env::current_dir()
            .map_err(|e| ConfigError::Invalid(format!("cannot read the working folder: {e}")))?;
        let home_var = std::env::var_os("HOME")
            .map(|h| utf8(h, "HOME"))
            .transpose()?;
        // Rust home_dir, as platformdirs: HOME if it is not empty, else the
        // password database.
        let passwd_home = match &home_var {
            Some(h) if !h.is_empty() => None,
            _ => std::env::home_dir()
                .map(|h| utf8(h.into_os_string(), "the home folder"))
                .transpose()?,
        };
        let xdg_config_home = std::env::var_os("XDG_CONFIG_HOME")
            .map(|x| utf8(x, "XDG_CONFIG_HOME"))
            .transpose()?;
        Ok(Env {
            cwd: utf8(cwd.into_os_string(), "the working folder")?,
            home_var,
            passwd_home,
            xdg_config_home,
        })
    }

    /// Python `os.path.expanduser` (only "~" and "~/..."; "~user" fails
    /// closed).
    pub fn expanduser(&self, path: &str) -> Result<String, ConfigError> {
        let Some(rest) = path.strip_prefix('~') else {
            return Ok(path.to_string());
        };
        if !(rest.is_empty() || rest.starts_with('/')) {
            return Err(ConfigError::Unsupported(format!(
                "the path {path:?}: sqll does not read \"~user\""
            )));
        }
        let home = match (&self.home_var, &self.passwd_home) {
            (Some(h), _) => h.clone(),
            (None, Some(h)) => h.clone(),
            (None, None) => return Ok(path.to_string()),
        };
        let joined = format!("{}{rest}", home.trim_end_matches('/'));
        Ok(if joined.is_empty() {
            "/".to_string()
        } else {
            joined
        })
    }

    /// platformdirs `_expand_user`: an empty HOME is unset.
    fn expand_user_platformdirs(&self, path: &str) -> Result<String, ConfigError> {
        match &self.home_var {
            Some(h) if h.is_empty() => match &self.passwd_home {
                Some(home) => {
                    let joined = format!("{}{}", home.trim_end_matches('/'), &path[1..]);
                    Ok(if joined.is_empty() {
                        "/".to_string()
                    } else {
                        joined
                    })
                }
                None => Ok(path.to_string()),
            },
            _ => self.expanduser(path),
        }
    }

    pub fn home(&self) -> Result<String, ConfigError> {
        self.expanduser("~")
    }

    /// pathlib `Path(path).absolute()`: joined to the working folder, with
    /// no "." part and no repeated "/".
    pub fn absolute(&self, path: &str) -> String {
        let joined = if path.starts_with('/') {
            path.to_string()
        } else {
            join(&self.cwd, path)
        };
        normalize_parts(&joined)
    }

    /// Python `os.path.realpath` (strict=False): each symbolic link is
    /// followed, ".." is applied after it, and a missing part stays.
    pub fn realpath(&self, path: &str) -> String {
        let abs = if path.starts_with('/') {
            PathBuf::from(path)
        } else {
            PathBuf::from(&self.cwd).join(path)
        };
        let mut rest: Vec<OsString> = abs
            .components()
            .filter_map(|c| match c {
                Component::Normal(n) => Some(n.to_os_string()),
                Component::ParentDir => Some(OsString::from("..")),
                _ => None,
            })
            .collect();
        rest.reverse();
        let mut out = PathBuf::from("/");
        let mut links = 0;
        while let Some(part) = rest.pop() {
            if part == ".." {
                out.pop();
                continue;
            }
            let next = out.join(&part);
            let is_link = fs::symlink_metadata(&next).is_ok_and(|m| m.file_type().is_symlink());
            if is_link && links < 40 {
                if let Ok(target) = fs::read_link(&next) {
                    links += 1;
                    if target.is_absolute() {
                        out = PathBuf::from("/");
                    }
                    for c in target.components().rev() {
                        match c {
                            Component::Normal(n) => rest.push(n.to_os_string()),
                            Component::ParentDir => rest.push(OsString::from("..")),
                            _ => {}
                        }
                    }
                    continue;
                }
            }
            out = next;
        }
        out.to_string_lossy().into_owned()
    }
}

/// Python `os.path.join` of two parts.
pub fn join(a: &str, b: &str) -> String {
    if b.starts_with('/') || a.is_empty() {
        b.to_string()
    } else if a.ends_with('/') {
        format!("{a}{b}")
    } else {
        format!("{a}/{b}")
    }
}

/// Python `os.path.dirname`.
pub fn dirname(path: &str) -> &str {
    match path.rfind('/') {
        None => "",
        Some(i) => {
            let head = &path[..=i];
            if head.chars().all(|c| c == '/') {
                head
            } else {
                head.trim_end_matches('/')
            }
        }
    }
}

fn normalize_parts(path: &str) -> String {
    let parts: Vec<&str> = path
        .split('/')
        .filter(|p| !p.is_empty() && *p != ".")
        .collect();
    format!("/{}", parts.join("/"))
}

fn parts(path: &str) -> Vec<&str> {
    path.split('/')
        .filter(|p| !p.is_empty() && *p != ".")
        .collect()
}

fn is_dir(path: &str) -> bool {
    Path::new(path).is_dir()
}

/// `iter_intermediate_paths`: the common path of inner and outer, then each
/// folder down to inner (the folder of inner if it is not a folder), each
/// as `realpath` gives it.
pub fn intermediate_paths(env: &Env, inner: &str, outer: &str) -> Vec<String> {
    let mut inner = env.absolute(inner);
    let outer = env.absolute(outer);
    if !is_dir(&inner) {
        inner = match dirname(&inner) {
            "" => "/".to_string(),
            d => d.to_string(),
        };
    }
    let inner_parts = parts(&inner);
    let outer_parts = parts(&outer);
    let common = inner_parts
        .iter()
        .zip(&outer_parts)
        .take_while(|(a, b)| a == b)
        .count();
    let mut out = Vec::new();
    for n in common..inner_parts.len() {
        out.push(env.realpath(&format!("/{}", inner_parts[..n].join("/"))));
    }
    out.push(env.realpath(&inner));
    out
}

/// The reader of the config files of one run. It reads each file and each
/// folder one time (sqlfluff caches them).
pub struct Loader<'e> {
    env: &'e Env,
    folders: HashMap<String, Table>,
}

impl<'e> Loader<'e> {
    pub fn new(env: &'e Env) -> Self {
        Loader {
            env,
            folders: HashMap::new(),
        }
    }

    pub fn env(&self) -> &Env {
        self.env
    }

    /// `load_config_file_as_dict`: read one file (TOML if its name is
    /// `pyproject.toml`, else INI), make its path settings relative to its
    /// folder, and check it.
    pub fn load_file(&self, filepath: &str) -> Result<Table, ConfigError> {
        let data = fs::read(filepath).map_err(|e| ConfigError::Io(format!("{filepath}: {e}")))?;
        let text = String::from_utf8(data).map_err(|_| {
            ConfigError::Invalid(format!("{filepath}: the config file is not UTF-8"))
        })?;
        // Python text mode: universal newlines.
        let text = text.replace("\r\n", "\n").replace('\r', "\n");
        let name = filepath.rsplit('/').next().unwrap_or(filepath);
        let mut config = if name == PYPROJECT {
            load_toml_string(&text, filepath)?
        } else {
            load_ini_string(&text, filepath)?
        };
        resolve_paths(&mut config, filepath, &mut Vec::new())?;
        validate_config_dict(&mut config, filepath)?;
        Ok(config)
    }

    /// `load_config_at_path`: the config files of a folder (or of the
    /// folder of a file), combined in the order of [`CONFIG_FILES`].
    pub fn load_folder(&mut self, path: &str) -> Result<Table, ConfigError> {
        if let Some(t) = self.folders.get(path) {
            return Ok(t.clone());
        }
        let folder = if is_dir(path) { path } else { dirname(path) };
        let folder = self.env.expanduser(folder)?;
        let names: Vec<OsString> = fs::read_dir(&folder)
            .map_err(|e| ConfigError::Invalid(format!("cannot list the folder {folder}: {e}")))?
            .filter_map(|e| e.ok().map(|e| e.file_name()))
            .collect();
        let mut config = Table::new();
        for name in CONFIG_FILES {
            let file = join(&folder, name);
            if names.iter().any(|n| n == name) && Path::new(&file).is_file() {
                config = nested_combine(&[&config, &self.load_file(&file)?])?;
            }
        }
        self.folders.insert(path.to_string(), config.clone());
        Ok(config)
    }

    /// `_get_user_config_dir_path` and `_load_user_appdir_config`.
    pub fn user_config_dir(&self) -> Result<String, ConfigError> {
        let cross = self.env.expanduser("~/.config/sqlfluff")?;
        if Path::new(&cross).exists() {
            return Ok(cross);
        }
        let xdg = self
            .env
            .xdg_config_home
            .as_deref()
            .map(crate::value::py_strip)
            .filter(|x| x.starts_with('/'));
        let unix = match xdg {
            Some(x) => join(x, "sqlfluff"),
            None => join(&self.env.expand_user_platformdirs("~/.config")?, "sqlfluff"),
        };
        if cfg!(target_os = "macos") {
            if Path::new(&self.env.expanduser(&unix)?).exists() {
                return Ok(unix);
            }
            return Ok(join(
                &self
                    .env
                    .expand_user_platformdirs("~/Library/Application Support")?,
                "sqlfluff",
            ));
        }
        Ok(unix)
    }

    /// `load_config_up_to_path`: the user config (the user config folder
    /// and the home folder), the folders between the home folder and path,
    /// the folders from the working folder to path, then the extra file
    /// (`--config`). `ignore_local_config` reads only the extra file.
    pub fn load_up_to_path(
        &mut self,
        path: &str,
        extra_config_path: Option<&str>,
        ignore_local_config: bool,
    ) -> Result<Table, ConfigError> {
        let mut stack: Vec<Table> = Vec::new();
        if !ignore_local_config {
            let appdir = self.user_config_dir()?;
            if Path::new(&appdir).exists() {
                stack.push(self.load_folder(&appdir)?);
            } else {
                stack.push(Table::new());
            }
            let home = self.env.home()?;
            stack.push(self.load_folder(&home)?);
            let mut parents = intermediate_paths(self.env, path, &home);
            parents.pop();
            for p in parents.iter().skip(1) {
                let p = self.env.realpath(p);
                stack.push(self.load_folder(&p)?);
            }
            let cwd = self.env.cwd.clone();
            for p in intermediate_paths(self.env, path, &cwd) {
                let p = self.env.realpath(&p);
                stack.push(self.load_folder(&p)?);
            }
        }
        if let Some(extra) = extra_config_path {
            let expanded = self.env.expanduser(extra)?;
            if is_dir(&join(&self.env.cwd, &expanded)) {
                return Err(ConfigError::Invalid(format!(
                    "Extra config path '{extra}' is a directory, not a config file."
                )));
            }
            let resolved = self.env.realpath(&expanded);
            match self.load_file(&resolved) {
                Err(ConfigError::Io(_)) if fs::symlink_metadata(&resolved).is_err() => {
                    return Err(ConfigError::Invalid(format!(
                        "Extra config path '{extra}' does not exist."
                    )))
                }
                other => stack.push(other?),
            }
        }
        let refs: Vec<&Table> = stack.iter().collect();
        nested_combine(&refs)
    }
}

/// `_resolve_paths_in_config`: a key that ends with `_path` or `_dir`, and
/// the macro path keys, are relative to the folder of the config file. A
/// path that does not exist stays as it is.
fn resolve_paths(
    config: &mut Table,
    filepath: &str,
    key_path: &mut Vec<String>,
) -> Result<(), ConfigError> {
    for (key, value) in config.iter_mut() {
        let lower = key.to_lowercase();
        if let Value::Table(t) = value {
            key_path.push(lower.clone());
            if key_path
                .iter()
                .map(String::as_str)
                .ne(OPAQUE_SECTION.iter().copied())
            {
                resolve_paths(t, filepath, key_path)?;
            }
            key_path.pop();
        }
        let comma = COMMA_SEPARATED_PATH_KEYS.contains(&lower.as_str());
        if !comma && !(lower.ends_with("_path") || lower.ends_with("_dir")) {
            continue;
        }
        let Value::Str(text) = value else {
            return Err(ConfigError::Invalid(format!(
                "Value for {key} in {filepath} must be a string not {}.",
                value.type_name()
            )));
        };
        if comma {
            let mut found = Vec::new();
            for part in text
                .split(',')
                .map(crate::value::py_strip)
                .filter(|p| !p.is_empty())
            {
                found.extend(resolve_path(filepath, part, key)?);
            }
            if !found.is_empty() {
                *text = found.join(",");
            }
        } else if let Some(p) = resolve_path(filepath, text, key)? {
            *text = p;
        }
    }
    Ok(())
}

/// `_resolve_path` for a path with no glob character: the path joined to
/// the folder of the file, if it exists.
fn resolve_path(filepath: &str, value: &str, key: &str) -> Result<Option<String>, ConfigError> {
    let joined = join(dirname(filepath), value);
    if joined.contains(['*', '?', '[']) {
        return Err(ConfigError::Unsupported(format!(
            "setting {key} = {value:?} in {filepath}: sqll does not read a glob pattern in a path"
        )));
    }
    let base = joined.rsplit('/').next().unwrap_or(&joined);
    let found = if base.is_empty() {
        is_dir(dirname(&joined))
    } else {
        fs::symlink_metadata(&joined).is_ok()
    };
    Ok(found.then_some(joined))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn path_helpers_are_those_of_python() {
        assert_eq!(join("/a", "b"), "/a/b");
        assert_eq!(join("/a/", "b"), "/a/b");
        assert_eq!(join("/a", "/b"), "/b");
        assert_eq!(join("", "b"), "b");
        assert_eq!(dirname("/a/b.sql"), "/a");
        assert_eq!(dirname("b.sql"), "");
        assert_eq!(dirname("/b.sql"), "/");
        assert_eq!(dirname("a//b"), "a");
        let env = Env {
            cwd: "/w".into(),
            home_var: Some("/h/".into()),
            passwd_home: None,
            xdg_config_home: None,
        };
        assert_eq!(env.expanduser("~").unwrap(), "/h");
        assert_eq!(env.expanduser("~/x").unwrap(), "/h/x");
        assert_eq!(env.expanduser("a~").unwrap(), "a~");
        assert!(env.expanduser("~bob/x").is_err());
        assert_eq!(env.absolute("a/./b//c"), "/w/a/b/c");
        assert_eq!(env.absolute("../x"), "/w/../x");
        let empty = Env {
            home_var: Some(String::new()),
            ..env
        };
        assert_eq!(empty.expanduser("~/.config").unwrap(), "/.config");
    }
}
