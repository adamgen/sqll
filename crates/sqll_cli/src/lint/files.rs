// Parts of this file are a port of sqlfluff 4.4.0 code:
// src/sqlfluff/core/linter/discovery.py (paths_from_path).
// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,
// commit 0348222a3bcdb0226563f7349c5a39beb0641955.
// Copyright (c) 2018-2026 Alan Cruickshank. MIT License: see
// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.

//! The files of the paths of a lint or a fix: a port of `paths_from_path`
//! of src/sqlfluff/core/linter/discovery.py (sqlfluff 4.4.0; MIT, see
//! THIRD_PARTY.md). Change: sqll reads no ignore file yet. A
//! `.sqlfluffignore` file or an `ignore_paths` setting in a folder that
//! sqlfluff reads for the path fails closed (sqll_config
//! `check_ignore_files` and `check_ignore_folder`), unless the option
//! `--disregard-sqlfluffignores` is given (then sqlfluff reads no ignore
//! file).

use std::fs;
use std::path::Path;

use sqll_config::parse::{check_ignore_files, check_ignore_folder, has_sql_extension};
use sqll_config::{ConfigError, Loader};

use crate::{normpath, Error};

/// An error of an ignore file check.
pub fn ignore_error(e: ConfigError) -> Error {
    match e {
        ConfigError::Unsupported(_) => Error::new(e.to_string()),
        other => Error::user(other.to_string()),
    }
}

/// Python `os.path.join`.
fn join(a: &str, b: &str) -> String {
    sqll_config::loader::join(a, b)
}

/// The SQL files of a path (sqlfluff `paths_from_path`), in the sqlfluff
/// order: the normalized path of a file, or the sorted files of a folder.
pub fn files_of(
    loader: &mut Loader,
    path: &str,
    exts: &[String],
    ignore_files: bool,
) -> Result<Vec<String>, Error> {
    if !Path::new(path).exists() {
        return Err(Error::user(format!(
            "Specified path does not exist. Check it/they exist(s): {path}."
        )));
    }
    if ignore_files {
        check_ignore_files(loader, path).map_err(ignore_error)?;
    }
    if Path::new(path).is_file() {
        if !has_sql_extension(path, exts) {
            return Ok(Vec::new());
        }
        return Ok(vec![normpath(path)]);
    }
    let mut out = Vec::new();
    walk(loader, path, exts, ignore_files, &mut out)?;
    out.sort();
    Ok(out)
}

/// Python `os.walk(path, topdown=True)` with no link to a folder followed:
/// the SQL files of each folder.
fn walk(
    loader: &mut Loader,
    dir: &str,
    exts: &[String],
    ignore_files: bool,
    out: &mut Vec<String>,
) -> Result<(), Error> {
    let Ok(entries) = fs::read_dir(dir) else {
        // os.walk ignores a folder that it cannot read.
        return Ok(());
    };
    if ignore_files {
        check_ignore_folder(loader, dir).map_err(ignore_error)?;
    }
    let mut subdirs = Vec::new();
    for entry in entries.flatten() {
        let Some(name) = entry.file_name().to_str().map(str::to_string) else {
            return Err(crate::unsupported(
                &format!("a file name that is not UTF-8 in {dir}"),
                "sqll reads only UTF-8 file names",
            ));
        };
        let Ok(kind) = entry.file_type() else {
            continue;
        };
        let full = join(dir, &name);
        // os.walk: a link to a folder is a folder, but it is not walked.
        let is_dir = kind.is_dir() || (kind.is_symlink() && Path::new(&full).is_dir());
        if is_dir {
            if !kind.is_symlink() {
                subdirs.push(full);
            }
            continue;
        }
        if has_sql_extension(&name, exts) {
            out.push(normpath(&full));
        }
    }
    for sub in subdirs {
        walk(loader, &sub, exts, ignore_files, out)?;
    }
    Ok(())
}
