"""S3b task C11: the sqlfluff answers for the config of sqll
(docs/interfaces/config.md).

Run it with the harness Python from the repository root:

    uv run --frozen --project harness python scripts/s3b/config_oracle.py record
    uv run --frozen --project harness python scripts/s3b/config_oracle.py check

Both run the pinned sqlfluff of the tool venv (tools/sqlfluff, pure Python)
and make the data of RECORD_FILE:

- defaults: each setting of the default config (load_config_resource).
- base: each setting of FluffConfig() with no file (the defaults and the
  values that FluffConfig makes from them).
- coerce: coerce_value of each text of COERCE.
- ini and toml: the dict of load_ini_string and of load_toml_file_config
  for each case (an invented text, or a file of the submodule), or the
  error.
- load: for each scenario of LOAD (config files in folders, a working
  folder, a home folder, XDG_CONFIG_HOME, a path, --config,
  --ignore-local-config, and overrides), the settings of
  FluffConfig.from_path that are not those of base, or the error.
- cli: for each scenario of CLI, the stdout, the exit code, and the
  warning lines of stderr (with no color codes) of "sqlfluff parse" (with
  -m: the tree with no position keys).
- jinja_as_raw: for each dialect fixture that is not empty and has no
  Jinja delimiter, the templated file of the Jinja templater (default
  settings) is that of the raw templater (text, sliced file, raw slices).
  For an empty text it is not: the raw templater gives an empty literal
  slice.

Each scenario runs in a new temporary folder; "<root>" stands for it. The
"sqll" field of a scenario says what sqll must do: null (the same result),
"unsupported" (sqll fails closed: exit code 2, "unsupported:"), or
"exit2" (sqlfluff stops with a Python error, sqll with exit code 2). The
interface test crates/sqll_interfaces/tests/config.rs and the test
crates/sqll/tests/cli_config.rs read RECORD_FILE.

record: write RECORD_FILE. check (CI job build): make the data again; it
must be the text of RECORD_FILE, and the counts must be those of COUNTS.

Exit code: 0 pass, 1 a failure.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQLFLUFF_ROOT = ROOT / "third_party" / "sqlfluff"
RECORD_FILE = ROOT / "results" / "S3b" / "C11-config.json"
KIND = "sqll-s3b-c11-config"
FORMAT = 2
COMMAND = "uv run --frozen --project harness python scripts/s3b/config_oracle.py"
DIALECT_DIR = "test/fixtures/dialects"
JINJA_DELIMITERS = ("{{", "{%", "{#")
POSITION_KEYS = (
    "start_line_no",
    "start_line_pos",
    "start_file_pos",
    "end_line_no",
    "end_line_pos",
    "end_file_pos",
)


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def warning_lines(stderr: str, root: str) -> list:
    """The lines of the sqlfluff log at level WARNING, with no color."""
    lines = ANSI.sub("", stderr).replace(root, "<root>").splitlines()
    return [line for line in lines if line.startswith("WARNING")]


class DataError(Exception):
    """A step failed, or the data do not agree."""


COERCE = (
    "1",
    "-12",
    "+7",
    "1_000",
    "007",
    " 5 ",
    "1__0",
    "_1",
    "1_",
    "0x10",
    "1.5",
    "7.698",
    ".5",
    "5.",
    "1e3",
    "1E-2",
    "1_0.5",
    "inf",
    "-Infinity",
    "e3",
    ".",
    "1e",
    "True",
    "FALSE",
    "tRuE",
    "none",
    "None ",
    "jinja",
    "",
    ".sql,.sql.j2",
    "1.0",
    "100000",
    "-0",
    "0.0001",
    "1e-05",
    "nan_x",
    "yes",
    "on",
    "0",
    "4.4.0",
)

# [name, text]; a text "@path" is the file of the submodule.
INI = (
    [
        "sections",
        "[sqlfluff]\ndialect=mysql\ntesting_int=4\n\n[sqlfluff:bar]\nfoo=barbar\n",
    ],
    ["fixture inheritance_a", "@test/fixtures/config/inheritance_a/.sqlfluff"],
    ["fixture setup.cfg", "@test/fixtures/config/inheritance_a/nested/setup.cfg"],
    ["fixture tox.ini", "@test/fixtures/config/inheritance_a/nested/tox.ini"],
    [
        "fixture extra",
        "@test/fixtures/config/inheritance_a/extra/this_can_have_any_name.cfg",
    ],
    ["fixture placeholder", "@test/fixtures/config/placeholder/.sqlfluff-placeholder"],
    ["fixture rules_set_to_none", "@test/fixtures/config/rules_set_to_none/.sqlfluff"],
    ["fixture glob_include", "@test/fixtures/config/glob_include/.sqlfluff"],
    ["sqlfluff tox.ini", "@tox.ini"],
    ["default config", "@src/sqlfluff/core/default_config.cfg"],
    [
        "multiline and comments",
        "# c\n[sqlfluff:layout:type:orderby_clause]\nkeyword_line_position_exclusions =\n"
        "    window_specification,\n    ; a comment\n\n    aggregate_order_by\n\n"
        "line_position = leading\n  ; indented comment\n",
    ],
    [
        "default section",
        "[DEFAULT]\nshared = 1\n[tool]\nx = 2\n[sqlfluff:templater:jinja:context]\n"
        "namespace.projectname=test\nshared = 3\n",
    ],
    ["colon delimiter is text", "[sqlfluff]\na: b = c\nd = e: f\n"],
    ["header with text after it", "[sqlfluff:a]b] ; c\nk = v\n"],
    ["spaces in keys", "[sqlfluff]\n  key with space   =   value with space  \n"],
    ["empty value", '[sqlfluff]\nmax_parse_depth =\nx = ""\n'],
    ["tabs", "[sqlfluff]\n\tdialect\t=\tansi\n"],
    ["no section", "x = 1\n"],
    ["duplicate section", "[a]\nx = 1\n[a]\n"],
    ["duplicate option", "[sqlfluff]\nx = 1\nx = 2\n"],
    ["no delimiter", "[sqlfluff]\nno delimiter\n"],
    ["empty option name", "[sqlfluff]\n= 1\n"],
    ["byte order mark", "﻿[sqlfluff]\ndialect = ansi\n"],
    ["value and section", "[sqlfluff:x]\ny = 1\n[sqlfluff:x:y]\nz = 2\n"],
    ["section then value", "[sqlfluff:x:y]\nz = 2\n[sqlfluff:x]\ny = 1\n"],
    ["empty", ""],
)

TOML = (
    ["fixture toml", "@test/fixtures/config/toml/pyproject.toml"],
    ["fixture nested", "@test/fixtures/config/inheritance_a/nested/pyproject.toml"],
    ["sqlfluff pyproject", "@pyproject.toml"],
    ["no tool", "[project]\nname = 'x'\n"],
    ["other tool", "[tool.black]\nline-length = 88\n"],
    [
        "values",
        '[tool.sqlfluff.core]\ndialect = "ansi"\nmax_parse_depth = 0x10\n'
        'a = 1_000\nb = -2.5e-3\nc = \'lit\\\'\nd = """\nx\\\n   y"""\ne = true\n'
        "f = [1, 2.5, true, 'x']\ng = { h = 1, i.j = 'k' }\n",
    ],
    [
        "rules",
        "[tool.sqlfluff.rules]\nallow_scalar = false\n"
        "[tool.sqlfluff.rules.capitalisation.keywords]\ncapitalisation_policy = 'upper'\n"
        "[tool.sqlfluff.rules.LT01]\nx = 1\n",
    ],
    [
        "context lists",
        "[tool.sqlfluff.templater.jinja.context]\nv = [1, '2', true, [3], {a = 1}]\n",
    ],
    ["array of tables in a list", "[tool.sqlfluff.core]\nx = [[1], [2]]\n"],
    ["rules not a table", '[tool.sqlfluff]\nrules = "all"\n'],
    ["bad syntax", "[tool.sqlfluff.core]\nrules = [1,,2]\n"],
    ["duplicate key", "[tool.sqlfluff.core]\na = 1\na = 2\n"],
    ["unterminated string", '[tool.sqlfluff.core]\na = "x\n'],
    ["byte order mark", '﻿[tool.sqlfluff.core]\ndialect = "ansi"\n'],
    ["date", "[tool.sqlfluff.core]\nd = 1979-05-27\n"],
    ["table redefined", "[tool.sqlfluff.core]\na = 1\n[tool.sqlfluff.core]\nb = 2\n"],
    ["array of tables", "[[tool.sqlfluff.x]]\na = 1\n[[tool.sqlfluff.x]]\na = 2\n"],
    ["crlf", '[tool.sqlfluff.core]\r\ndialect = "ansi"\r\n'],
    ["big int", "[tool.sqlfluff.core]\na = 99999999999999999999\n"],
    [
        "date in another tool",
        "[tool.other]\nx = 1979-05-27T07:32:00Z\ny = [07:32:00, 2000-02-29]\n"
        '[tool.sqlfluff.core]\ndialect = "ansi"\n',
    ],
    ["invalid date", "[tool.other]\nx = 1979-02-29\n"],
)

# The config of a folder: name -> text, or {"fixture": path} (a file of the
# submodule), or {"dir": true} (a folder).
INHERITANCE_A = {
    "a/.sqlfluff": {"fixture": "test/fixtures/config/inheritance_a/.sqlfluff"},
    "a/nested/tox.ini": {
        "fixture": "test/fixtures/config/inheritance_a/nested/tox.ini"
    },
    "a/nested/setup.cfg": {
        "fixture": "test/fixtures/config/inheritance_a/nested/setup.cfg"
    },
    "a/nested/pyproject.toml": {
        "fixture": "test/fixtures/config/inheritance_a/nested/pyproject.toml"
    },
    "a/extra/this_can_have_any_name.cfg": {
        "fixture": "test/fixtures/config/inheritance_a/extra/this_can_have_any_name.cfg"
    },
}


def scenario(
    name,
    files,
    path,
    cwd="w",
    home="h",
    xdg=None,
    extra=None,
    ignore_local=False,
    overrides=None,
    sqll=None,
):
    return {
        "name": name,
        "files": files,
        "cwd": cwd,
        "home": home,
        "xdg": xdg,
        "path": path,
        "extra": extra,
        "ignore_local": ignore_local,
        "overrides": overrides or {},
        "sqll": sqll,
    }


ORDER = {
    "w/setup.cfg": "[sqlfluff]\nk1 = setup\nk2 = setup\nk3 = setup\nk4 = setup\nk5 = setup\n",
    "w/tox.ini": "[sqlfluff]\nk2 = tox\nk3 = tox\nk4 = tox\nk5 = tox\n",
    "w/pep8.ini": "[sqlfluff]\nk3 = pep8\nk4 = pep8\nk5 = pep8\n",
    "w/.sqlfluff": "[sqlfluff]\nk4 = sqlfluff\nk5 = sqlfluff\n",
    "w/pyproject.toml": "[tool.sqlfluff.core]\nk5 = 'pyproject'\n",
}
NEST = {
    "h/.sqlfluff": "[sqlfluff]\nn1 = home\nn2 = home\nn3 = home\nn4 = home\nn5 = home\n",
    "h/p/.sqlfluff": "[sqlfluff]\nn2 = parent\nn3 = parent\nn4 = parent\nn5 = parent\n",
    "h/p/w/.sqlfluff": "[sqlfluff]\nn3 = cwd\nn4 = cwd\nn5 = cwd\n",
    "h/p/w/s/.sqlfluff": "[sqlfluff]\nn4 = sub\nn5 = sub\n",
    "h/p/w/s/f/.sqlfluff": "[sqlfluff]\nn5 = file\n",
    "h/p/w/s/f/a.sql": "select 1\n",
    "x.cfg": "[sqlfluff]\nn5 = extra\nn6 = extra\n",
}

LOAD = (
    scenario("files of a folder in order", ORDER, "a.sql"),
    scenario("nested folders from home to the file", NEST, "s/f/a.sql", cwd="h/p/w"),
    scenario("extra file last", NEST, "s/f/a.sql", cwd="h/p/w", extra="../../../x.cfg"),
    scenario(
        "overrides after the extra file",
        NEST,
        "s/f/a.sql",
        cwd="h/p/w",
        extra="../../../x.cfg",
        overrides={"n6": "override", "dialect": "ansi"},
    ),
    scenario("ignore local config", NEST, "s/f/a.sql", cwd="h/p/w", ignore_local=True),
    scenario(
        "ignore local config with an extra file",
        NEST,
        "s/f/a.sql",
        cwd="h/p/w",
        extra="../../../x.cfg",
        ignore_local=True,
    ),
    scenario(
        "a path outside the working folder",
        {**NEST, "h/p/q/.sqlfluff": "[sqlfluff]\nn5 = q\n", "h/p/q/b.sql": "x\n"},
        "../../q/b.sql",
        cwd="h/p/w/s",
    ),
    scenario("a path in a folder that does not exist", NEST, "nope/a.sql", cwd="h/p/w"),
    scenario("a folder as the path", NEST, "s/f", cwd="h/p/w"),
    scenario(
        "home outside the path",
        {**NEST, "o/.sqlfluff": "[sqlfluff]\nn1 = other\n"},
        "../../o",
        cwd="h/p/w",
    ),
    scenario(
        "sqlfluff fixture inheritance_a (test__config__load_nested)",
        INHERITANCE_A,
        "nested/blah.sql",
        cwd="a",
        extra="extra/this_can_have_any_name.cfg",
    ),
    scenario(
        "sqlfluff fixture inheritance_a from the nested folder (test__config__load_parent)",
        INHERITANCE_A,
        "blah.sql",
        cwd="a/nested",
    ),
    scenario(
        "user config folder ~/.config/sqlfluff",
        {
            "h/.config/sqlfluff/.sqlfluff": "[sqlfluff]\nu = appdir\nv = appdir\n",
            "h/.sqlfluff": "[sqlfluff]\nv = home\n",
            "w/a.sql": "x\n",
        },
        "a.sql",
    ),
    scenario(
        "user config folder of XDG_CONFIG_HOME",
        {"x/sqlfluff/tox.ini": "[sqlfluff]\nu = xdg\n", "w/a.sql": "x\n", "h/k": "x\n"},
        "a.sql",
        xdg="x",
    ),
    scenario(
        "a relative XDG_CONFIG_HOME is not used",
        {
            "x/sqlfluff/tox.ini": "[sqlfluff]\nu = xdg\n",
            "h/.config/x/sqlfluff/.sqlfluff": "[sqlfluff]\nu = relative\n",
            "w/a.sql": "x\n",
        },
        "a.sql",
        xdg=".config/x",
    ),
    scenario(
        "a folder named .sqlfluff",
        {
            "w/.sqlfluff": {"dir": True},
            "w/pyproject.toml": "[tool.sqlfluff.core]\ndialect = 'ansi'\n",
        },
        "a.sql",
    ),
    scenario(
        "path settings",
        {
            "w/.sqlfluff": "[sqlfluff:templater:jinja]\nlibrary_path = lib\nother_dir = missing\n"
            "load_macros_from_path = m1, missing, m2\n[sqlfluff:templater:jinja:context]\n"
            "my_path = lib\n",
            "w/lib": {"dir": True},
            "w/m1": {"dir": True},
            "w/m2/x.sql": "x\n",
        },
        "a.sql",
    ),
    scenario(
        "a glob path setting",
        {
            "w/.sqlfluff": "[sqlfluff:templater:jinja]\nload_macros_from_path = m*\n",
            "w/m1": {"dir": True},
        },
        "a.sql",
        sqll="unsupported",
    ),
    scenario(
        "extra file in the home folder with ~",
        {"h/e.cfg": "[sqlfluff]\ndialect = tsql\n", "w/a.sql": "x\n"},
        "a.sql",
        extra="~/e.cfg",
        ignore_local=True,
    ),
    scenario(
        "extra file pyproject.toml",
        {
            "e/pyproject.toml": "[tool.sqlfluff.core]\ndialect = 'bigquery'\n",
            "w/a.sql": "x\n",
        },
        "a.sql",
        extra="../e/pyproject.toml",
    ),
    scenario(
        "extra file that does not exist",
        {"w/a.sql": "x\n"},
        "a.sql",
        extra="nope.cfg",
    ),
    scenario(
        "extra file that is a folder",
        {"w/d": {"dir": True}},
        "a.sql",
        extra="d",
    ),
    scenario(
        "removed setting",
        {"w/.sqlfluff": "[sqlfluff]\nrecurse = 1\n"},
        "a.sql",
    ),
    scenario(
        "moved setting",
        {"w/.sqlfluff": "[sqlfluff:rules]\ntab_space_size = 2\n"},
        "a.sql",
        sqll="unsupported",
    ),
    scenario(
        "invalid layout",
        {"w/.sqlfluff": "[sqlfluff:layout:type:comma]\nbad = 1\n"},
        "a.sql",
    ),
    scenario(
        "parse limits",
        {
            "w/.sqlfluff": "[sqlfluff]\nmax_parse_depth =\nmax_parse_nodes = None\n"
            "rust_parser_max_iterations = 0\n"
        },
        "a.sql",
    ),
    scenario(
        "invalid max_parse_depth",
        {"w/.sqlfluff": "[sqlfluff]\nmax_parse_depth = deep\n"},
        "a.sql",
    ),
    scenario(
        "comma separated lists",
        {
            "w/.sqlfluff": "[sqlfluff]\nrules = LT01, CP01,,\nexclude_rules = CP01\n"
            "ignore = parsing\nwarnings = PRS, LXR\nnocolor = True\n"
        },
        "a.sql",
    ),
    scenario(
        "toml lists",
        {
            "w/pyproject.toml": "[tool.sqlfluff.core]\nrules = ['LT01', 'CP01']\nignore = []\n"
        },
        "a.sql",
    ),
    scenario(
        "unknown templater",
        {"w/.sqlfluff": "[sqlfluff]\ntemplater = dbt\n"},
        "a.sql",
    ),
    scenario(
        "rust rules without the rust parser",
        {"w/.sqlfluff": "[sqlfluff]\nuse_rust_rules = True\nuse_rust_parser = False\n"},
        "a.sql",
    ),
    scenario(
        "a value and a section of the same name in two files",
        {
            "w/.sqlfluff": "[sqlfluff]\nx = 1\n",
            "w/s/.sqlfluff": "[sqlfluff:core:x]\ny = 2\n",
            "w/s/a.sql": "x\n",
        },
        "s/a.sql",
    ),
    scenario(
        "a section and a value of the same name in two files",
        {
            "w/.sqlfluff": "[sqlfluff:core:x]\ny = 2\n",
            "w/s/.sqlfluff": "[sqlfluff]\nx = 1\n",
            "w/s/a.sql": "x\n",
        },
        "s/a.sql",
    ),
    scenario(
        "indentation",
        {
            "w/.sqlfluff": "[sqlfluff:indentation]\nindented_joins = True\ntab_space_size = 0\n"
            "my_key = x\n"
        },
        "a.sql",
    ),
)

SQL = "select a from b join c on a = c\n"
CLI = (
    # [name, files, cwd, args, sqll, stdin]
    [
        "dialect of the working folder",
        {"w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n", "w/a.sql": SQL},
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "dialect of the file folder",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n",
            "w/s/.sqlfluff": "[sqlfluff]\ndialect = tsql\n",
            "w/s/a.sql": "select [a] from b\n",
        },
        "w",
        ["s/a.sql"],
        None,
        None,
    ],
    [
        "--dialect over the config",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = tsql\n",
            "w/a.sql": "select `a` from b\n",
        },
        "w",
        ["--dialect", "mysql", "a.sql"],
        None,
        None,
    ],
    [
        "--config over the folders",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = tsql\n",
            "e.cfg": "[sqlfluff]\ndialect = mysql\n",
            "w/a.sql": "select `a` from b\n",
        },
        "w",
        ["--config", "../e.cfg", "a.sql"],
        None,
        None,
    ],
    [
        "--ignore-local-config with no dialect",
        {"w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n", "w/a.sql": SQL},
        "w",
        ["--ignore-local-config", "a.sql"],
        None,
        None,
    ],
    [
        "--ignore-local-config with --config",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = tsql\n",
            "w/e.toml": "[sqlfluff]\ndialect = ansi\n",
            "w/a.sql": SQL,
        },
        "w",
        ["--ignore-local-config", "--config", "e.toml", "a.sql"],
        None,
        None,
    ],
    [
        "pyproject.toml",
        {
            "w/pyproject.toml": "[tool.sqlfluff.core]\ndialect = 'ansi'\n"
            "[tool.sqlfluff.indentation]\nindented_joins = true\n",
            "w/a.sql": SQL,
        },
        "w",
        ["-m", "a.sql"],
        None,
        None,
    ],
    [
        "setup.cfg and tox.ini",
        {
            "w/setup.cfg": "[sqlfluff]\ndialect = tsql\n",
            "w/tox.ini": "[sqlfluff]\ndialect = ansi\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "home config",
        {"h/.sqlfluff": "[sqlfluff]\ndialect = ansi\n", "w/a.sql": SQL},
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "user config folder",
        {
            "h/.config/sqlfluff/.sqlfluff": "[sqlfluff]\ndialect = ansi\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "max_parse_depth",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nmax_parse_depth = 5\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "max_parse_nodes",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nmax_parse_nodes = 3\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "indented_joins with -m",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n"
            "[sqlfluff:indentation]\nindented_joins = True\n",
            "w/a.sql": SQL,
        },
        "w",
        ["-m", "a.sql"],
        None,
        None,
    ],
    [
        "indented_joins off with -m",
        {"w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n", "w/a.sql": SQL},
        "w",
        ["-m", "a.sql"],
        None,
        None,
    ],
    [
        "large_file_skip_byte_limit",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n"
            "large_file_skip_byte_limit = 10\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "large_file_skip_char_limit",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n"
            "large_file_skip_char_limit = 10\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "default byte limit",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n",
            "w/a.sql": "select 1;\n" * 2001,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "sql_file_exts",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nsql_file_exts = .txt\n",
            "w/a.txt": SQL,
        },
        "w",
        ["a.txt"],
        None,
        None,
    ],
    [
        "another extension",
        {"w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n", "w/a.txt": SQL},
        "w",
        ["a.txt"],
        None,
        None,
    ],
    [
        "raw templater with a Jinja tag",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\ntemplater = raw\n",
            "w/a.sql": "select {{ x }}\n",
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "--templater raw",
        {"w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n", "w/a.sql": "select {{ x }}\n"},
        "w",
        ["--templater", "raw", "a.sql"],
        None,
        None,
    ],
    [
        "jinja templater with a Jinja tag",
        {"w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n", "w/a.sql": "select {{ 1 }}\n"},
        "w",
        ["a.sql"],
        "unsupported",
        None,
    ],
    [
        "jinja templater with no Jinja tag",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n",
            "w/a.sql": "select '{' as x, 5 % 2 # 1\n",
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "templater of a subfolder",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n",
            "w/s/.sqlfluff": "[sqlfluff]\ntemplater = raw\n",
            "w/s/a.sql": SQL,
        },
        "w",
        ["s/a.sql"],
        None,
        None,
    ],
    [
        "ignore parsing",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nignore = parsing\n",
            "w/a.sql": "select (\n",
        },
        "w",
        ["a.sql"],
        "unsupported",
        None,
    ],
    [
        "use_rust_parser False",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nuse_rust_parser = False\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        "unsupported",
        None,
    ],
    [
        "a rule setting",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n"
            "[sqlfluff:rules:capitalisation.keywords]\n"
            "capitalisation_policy = upper\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        "unsupported",
        None,
    ],
    [
        "an invalid rule setting",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n"
            "[sqlfluff:rules:capitalisation.keywords]\n"
            "capitalisation_policy = bogus\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        "unsupported",
        None,
    ],
    [
        ".sqlfluffignore",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n",
            "w/.sqlfluffignore": "a.sql\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        "unsupported",
        None,
    ],
    [
        "encoding utf-8 keeps the byte order mark",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nencoding = utf-8\n",
            "w/a.sql": "﻿select 1\n",
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "verbose",
        {"w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nverbose = 1\n", "w/a.sql": SQL},
        "w",
        ["a.sql"],
        "unsupported",
        None,
    ],
    [
        "an unknown dialect in the config",
        {"w/.sqlfluff": "[sqlfluff]\ndialect = nope\n", "w/a.sql": SQL},
        "w",
        ["a.sql"],
        "exit2",
        None,
    ],
    [
        "a config file with no section header",
        {"w/.sqlfluff": "dialect = ansi\n", "w/a.sql": SQL},
        "w",
        ["--dialect", "ansi", "a.sql"],
        "exit2",
        None,
    ],
    [
        "--config of a folder",
        {"w/d": {"dir": True}, "w/a.sql": SQL},
        "w",
        ["--dialect", "ansi", "--config", "d", "a.sql"],
        None,
        None,
    ],
    [
        "invalid max_parse_depth",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nmax_parse_depth = deep\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "a removed setting",
        {"w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nrecurse = 1\n", "w/a.sql": SQL},
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "a moved setting",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n[sqlfluff:rules]\n"
            "tab_space_size = 2\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        "unsupported",
        None,
    ],
    [
        "stdin with the dialect of the config",
        {"w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n"},
        "w",
        ["-"],
        None,
        SQL,
    ],
    # sqlfluff reads stdin with sys.stdin.read(): no encoding setting, and
    # the byte order mark stays.
    [
        "stdin keeps the byte order mark",
        {"w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n"},
        "w",
        ["-"],
        None,
        "\ufeffselect 1\n",
    ],
    [
        "stdin with encoding utf-8-sig keeps the byte order mark",
        {"w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nencoding = utf-8-sig\n"},
        "w",
        ["-"],
        None,
        "\ufeffselect 1\n",
    ],
    [
        "stdin with an encoding that is not UTF-8",
        {"w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nencoding = latin-1\n"},
        "w",
        ["-"],
        None,
        SQL,
    ],
    # Only the PATH argument "-" is stdin (parse in src/sqlfluff/cli/commands.py
    # compares the raw argument): "./-" is the file "-", although its
    # normalised path is "-".
    [
        "a file named - given as ./-",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nsql_file_exts =\n",
            "w/-": SQL,
        },
        "w",
        ["./-"],
        None,
        "selec ( ( (\n",
    ],
    # paths_from_path loads the config files of the folders (as ignore
    # files) before it applies the extensions.
    [
        "another extension under an invalid config",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n",
            "w/s/.sqlfluff": "[sqlfluff]\nmax_parse_depth = -3\n",
            "w/s/a.txt": SQL,
        },
        "w",
        ["s/a.txt"],
        None,
        None,
    ],
    [
        "another extension under an invalid pyproject.toml",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n",
            "w/s/pyproject.toml": "[tool.sqlfluff.core]\nmax_parse_depth = -3\n",
            "w/s/a.txt": SQL,
        },
        "w",
        ["s/a.txt"],
        None,
        None,
    ],
    [
        "a TOML date in another tool",
        {
            "w/pyproject.toml": "[tool.other]\nx = 1979-05-27\n"
            '[tool.sqlfluff.core]\ndialect = "ansi"\n',
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "no-effect settings",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nnocolor = True\n"
            "processes = 4\nmax_line_length = 10\n"
            "output_line_length = 5\nunknown = x\n"
            "[sqlfluff:templater:python:context]\nx = 1\n"
            "[sqlfluff:bar]\nfoo = 1\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "a path with .. and a config in the folder it leaves",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n",
            "w/t/.sqlfluff": "[sqlfluff]\nmax_parse_depth = 3\n",
            "w/a.sql": SQL,
        },
        "w",
        ["t/../a.sql"],
        None,
        None,
    ],
    [
        "a path with .. and the dialect only in the folder it leaves",
        {"w/t/.sqlfluff": "[sqlfluff]\ndialect = ansi\n", "w/a.sql": SQL},
        "w",
        ["t/../a.sql"],
        None,
        None,
    ],
    [
        "a path with .. into another subfolder",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\n",
            "w/t/.sqlfluff": "[sqlfluff]\nmax_parse_depth = 3\n",
            "w/s/a.sql": SQL,
        },
        "w",
        ["t/../s/a.sql"],
        None,
        None,
    ],
    # load_raw_file_and_config converts the byte limit with int().
    [
        "a TOML text byte limit",
        {
            "w/pyproject.toml": '[tool.sqlfluff.core]\ndialect = "ansi"\n'
            'large_file_skip_byte_limit = " +1_0 "\n',
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "a TOML text byte limit of 0",
        {
            "w/pyproject.toml": '[tool.sqlfluff.core]\ndialect = "ansi"\n'
            'large_file_skip_byte_limit = "0"\n',
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        "unsupported",
        None,
    ],
    [
        "a path with .. over the byte limit",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nlarge_file_skip_byte_limit = 5\n",
            "w/t/.sqlfluff": "[sqlfluff]\nlarge_file_skip_byte_limit = 0\n",
            "w/a.sql": SQL,
        },
        "w",
        ["t/../a.sql"],
        None,
        None,
    ],
    # Python codecs.lookup finds an alias with the name after "." to "_",
    # but not a module name with a ".": "utf.8" is a LookupError (exit 1).
    [
        "encoding utf.8 is not a Python codec name",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nencoding = utf.8\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        "unsupported",
        None,
    ],
    [
        "encoding utf_8.sig in TOML is not a Python codec name",
        {
            "w/pyproject.toml": '[tool.sqlfluff.core]\ndialect = "ansi"\n'
            'encoding = "utf_8.sig"\n',
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        "unsupported",
        None,
    ],
    [
        "encoding utf8.ucs2 is a Python alias of utf-8",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nencoding = utf8.ucs2\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    # The skip warnings write the file name with repr() ({fname!r}).
    [
        "byte limit warning for a file name with a quote",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nlarge_file_skip_byte_limit = 3\n",
            "w/it's.sql": SQL,
        },
        "w",
        ["it's.sql"],
        None,
        None,
    ],
    [
        "byte limit warning for a file name with quotes, a backslash, and a tab",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nlarge_file_skip_byte_limit = 3\n",
            "w/a'b\"c\\d\te\u00ad.sql": SQL,
        },
        "w",
        ["a'b\"c\\d\te\u00ad.sql"],
        None,
        None,
    ],
    [
        "char limit warning for a file name with a quote",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nlarge_file_skip_char_limit = 3\n",
            "w/it's.sql": SQL,
        },
        "w",
        ["it's.sql"],
        None,
        None,
    ],
    # large_file_check decorates process_with_variants and the process that
    # it calls (src/sqlfluff/core/templaters/base.py): a file that is not
    # skipped gets the deprecation warning two times.
    [
        "char limit with a file under the limit",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nlarge_file_skip_char_limit = 500\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "char limit with a file under the limit and the raw templater",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\ntemplater = raw\n"
            "large_file_skip_char_limit = 500\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "char limit with stdin under the limit",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nlarge_file_skip_char_limit = 500\n"
        },
        "w",
        ["-"],
        None,
        SQL,
    ],
    [
        "char limit with an empty file and the raw templater",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\ntemplater = raw\n"
            "large_file_skip_char_limit = 5\n",
            "w/a.sql": "",
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "char limit with an empty file and the jinja templater",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nlarge_file_skip_char_limit = 5\n",
            "w/a.sql": "",
        },
        "w",
        ["a.sql"],
        "unsupported",
        None,
    ],
    # The warning writes f"{limit}": the bool True is "True" (and is 1 in
    # len(in_str) > limit).
    [
        "an INI char limit of True",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\nlarge_file_skip_char_limit = True\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "a TOML char limit of true",
        {
            "w/pyproject.toml": '[tool.sqlfluff.core]\ndialect = "ansi"\n'
            "large_file_skip_char_limit = true\n",
            "w/a.sql": SQL,
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
    [
        "a char limit of True and a file of one character",
        {
            "w/.sqlfluff": "[sqlfluff]\ndialect = ansi\ntemplater = raw\n"
            "large_file_skip_char_limit = True\n",
            "w/a.sql": "\n",
        },
        "w",
        ["a.sql"],
        None,
        None,
    ],
)


def enc(value):
    """A config value as JSON with its Python type: an int and a float as
    {"int": text} and {"float": repr}, a dict as {"dict": {...}}."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return {"int": str(value)}
    if isinstance(value, float):
        return {"float": repr(value)}
    if isinstance(value, list):
        return [enc(v) for v in value]
    if isinstance(value, dict):
        return {"dict": {k: enc(v) for k, v in value.items()}}
    raise DataError(f"a config value of the type {type(value).__name__}")


def records(config: dict, prefix=()) -> list:
    out = []
    for key, value in config.items():
        if isinstance(value, dict):
            out += records(value, prefix + (key,))
        else:
            out.append([list(prefix + (key,)), enc(value)])
    return out


def text_of(spec: str) -> str:
    if spec.startswith("@"):
        return (SQLFLUFF_ROOT / spec[1:]).read_text(encoding="utf8")
    return spec


def error_of(exc: BaseException, root: str | None = None) -> dict:
    message = str(exc)
    if root:
        message = message.replace(root, "<root>")
    return {"error": type(exc).__name__, "message": message[:300]}


def make_files(root: Path, files: dict) -> None:
    for rel, content in files.items():
        path = root / rel
        if isinstance(content, dict) and content.get("dir"):
            path.mkdir(parents=True, exist_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict):
            path.write_bytes((SQLFLUFF_ROOT / content["fixture"]).read_bytes())
        else:
            path.write_bytes(content.encode("utf8"))


def rooted(value, root: str):
    """Each string with <root> in place of the scenario folder."""
    if isinstance(value, str):
        return value.replace(root, "<root>")
    if isinstance(value, list):
        return [rooted(v, root) for v in value]
    if isinstance(value, dict):
        return {k: rooted(v, root) for k, v in value.items()}
    return value


def plain(configs: dict) -> dict:
    out = dict(configs)
    out["core"] = {
        k: v
        for k, v in configs["core"].items()
        if k not in ("dialect_obj", "templater_obj")
    }
    return out


# The data, made with the sqlfluff Python (the "dump" command).


def dump_load(base: list) -> list:
    from sqlfluff.core import FluffConfig
    from sqlfluff.core.config import clear_config_caches

    base_set = {json.dumps(r) for r in base}
    out = []
    here = os.getcwd()
    for sc in LOAD:
        with tempfile.TemporaryDirectory(prefix="sqll-c11-") as tmp:
            root = str(Path(tmp).resolve())
            make_files(Path(root), sc["files"])
            for folder in (sc["cwd"], sc["home"]):
                (Path(root) / folder).mkdir(parents=True, exist_ok=True)
            os.environ["HOME"] = f"{root}/{sc['home']}"
            if sc["xdg"] is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            elif sc["xdg"].startswith("."):
                os.environ["XDG_CONFIG_HOME"] = sc["xdg"]
            else:
                os.environ["XDG_CONFIG_HOME"] = f"{root}/{sc['xdg']}"
            os.chdir(f"{root}/{sc['cwd']}")
            clear_config_caches()
            try:
                cfg = FluffConfig.from_path(
                    sc["path"],
                    extra_config_path=sc["extra"],
                    ignore_local_config=sc["ignore_local"],
                    overrides=dict(sc["overrides"]) or None,
                    require_dialect=False,
                )
                got = rooted(records(plain(cfg._configs)), root)
                result = {"config": [r for r in got if json.dumps(r) not in base_set]}
            except Exception as exc:  # noqa: BLE001 - each error is data
                result = error_of(exc, root)
            finally:
                os.chdir(here)
        out.append({**sc, **result})
    return out


def dump_jinja() -> dict:
    from sqlfluff.core import FluffConfig
    from sqlfluff.core.templaters import JinjaTemplater, RawTemplater

    files = sorted((SQLFLUFF_ROOT / DIALECT_DIR).glob("*/*.sql"))
    literal = equal = 0
    with_tags, empty = [], []
    problems = []
    for path in files:
        text = path.read_text(encoding="utf8")
        rel = path.relative_to(SQLFLUFF_ROOT / DIALECT_DIR).as_posix()
        if any(d in text for d in JINJA_DELIMITERS):
            with_tags.append(rel)
            continue
        if not text:
            # The Jinja templater gives no slice for an empty text; the raw
            # templater gives one empty literal slice (a placeholder with -m).
            empty.append(rel)
            continue
        literal += 1
        config = FluffConfig(overrides={"dialect": rel.split("/")[0]})
        raw, _ = RawTemplater().process(in_str=text, fname=rel, config=config)
        jinja, errors = JinjaTemplater().process(in_str=text, fname=rel, config=config)
        same = (
            not errors
            and jinja.templated_str == raw.templated_str
            and jinja.sliced_file == raw.sliced_file
            and jinja.raw_sliced == raw.raw_sliced
        )
        if same:
            equal += 1
        else:
            problems.append(
                f"jinja_as_raw: {rel}: the Jinja templated file is another one"
            )
    return {
        "files": len(files),
        "literal": literal,
        "equal": equal,
        "with_tags": with_tags,
        "empty": empty,
        "problems": problems,
    }


def dump() -> dict:
    import sqlfluff
    from sqlfluff.core import FluffConfig
    from sqlfluff.core.config import load_config_resource
    from sqlfluff.core.config.ini import coerce_value, load_ini_string
    from sqlfluff.core.config.toml import load_toml_file_config

    defaults = records(load_config_resource("sqlfluff.core", "default_config.cfg"))
    base = records(plain(FluffConfig(require_dialect=False)._configs))
    coerce = [[t, enc(coerce_value(t))] for t in COERCE]
    ini = []
    for name, spec in INI:
        try:
            ini.append(
                {
                    "name": name,
                    "text": spec,
                    "dict": enc(load_ini_string(text_of(spec))),
                }
            )
        except Exception as exc:  # noqa: BLE001
            ini.append({"name": name, "text": spec, **error_of(exc)})
    toml = []
    with tempfile.TemporaryDirectory(prefix="sqll-c11-") as tmp:
        for name, spec in TOML:
            path = Path(tmp) / "pyproject.toml"
            path.write_bytes(text_of(spec).encode("utf8"))
            try:
                got = enc(load_toml_file_config(str(path)))
                toml.append({"name": name, "text": spec, "dict": got})
            except Exception as exc:  # noqa: BLE001
                toml.append({"name": name, "text": spec, **error_of(exc, tmp)})
    return {
        "sqlfluff": sqlfluff.__version__,
        "defaults": defaults,
        "base": base,
        "coerce": coerce,
        "ini": ini,
        "toml": toml,
        "load": dump_load(base),
        "jinja_as_raw": dump_jinja(),
    }


# The commands of the harness Python.


def tool_python(name: str) -> Path:
    sys.path.insert(0, str(ROOT / "harness"))
    from sqll_harness.paths import tools_dir

    return tools_dir() / name / "bin"


def strip(value):
    """The record of "sqlfluff parse -m" as (key, value) pairs, with no
    position keys (a list of one-key records is the list of its pairs)."""
    if isinstance(value, dict):
        return [[k, strip(v)] for k, v in value.items() if k not in POSITION_KEYS]
    if isinstance(value, list):
        pairs = []
        for item in value:
            pairs += strip(item)
        return pairs
    return value


def run_cli() -> list:
    out = []
    for name, files, cwd, args, sqll, stdin in CLI:
        binary = tool_python("sqlfluff") / "sqlfluff"
        if not binary.is_file():
            raise DataError(f"no {binary} (scripts/setup)")
        with tempfile.TemporaryDirectory(prefix="sqll-c11-") as tmp:
            root = str(Path(tmp).resolve())
            make_files(Path(root), files)
            for folder in (cwd, "h"):
                (Path(root) / folder).mkdir(parents=True, exist_ok=True)
            env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
            env.update(HOME=f"{root}/h", PYTHONDONTWRITEBYTECODE="1")
            env.pop("XDG_CONFIG_HOME", None)
            argv = [str(binary), "parse", "-f", "json", *args]
            proc = subprocess.run(
                argv,
                cwd=f"{root}/{cwd}",
                env=env,
                input=stdin or "",
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
        record = {
            "name": name,
            "files": files,
            "cwd": cwd,
            "args": args,
            "sqll": sqll,
            "stdin": stdin,
            "exit_code": proc.returncode,
            "warnings": warning_lines(proc.stderr, root),
        }
        if "-m" in args and proc.returncode in (0, 1):
            record["tree"] = [strip(r["segments"]) for r in json.loads(proc.stdout)]
        else:
            record["stdout"] = proc.stdout.replace(root, "<root>")
        out.append(record)
    return out


def run_dump() -> dict:
    python = tool_python("sqlfluff") / "python"
    if not python.is_file():
        raise DataError(f"no sqlfluff Python at {python} (scripts/setup)")
    argv = [str(python), "-I", "-B", str(Path(__file__).resolve()), "dump"]
    print(f"config_oracle: $ {' '.join(argv)}", flush=True)
    out = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=False)
    if out.returncode != 0:
        raise DataError(f"dump: exit code {out.returncode}\n{out.stderr[-4000:]}")
    data = json.loads(out.stdout)
    print(f"config_oracle: {len(CLI)} sqlfluff parse runs", flush=True)
    data["cli"] = run_cli()
    return data


def submodule_commit() -> str:
    out = subprocess.run(
        ["git", "-C", str(SQLFLUFF_ROOT), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    return out.stdout.strip()


def counts(data: dict) -> dict:
    j = data["jinja_as_raw"]
    return {
        "defaults": len(data["defaults"]),
        "coerce": len(data["coerce"]),
        "ini": len(data["ini"]),
        "toml": len(data["toml"]),
        "load": len(data["load"]),
        "cli": len(data["cli"]),
        "dialect_fixtures": j["files"],
        "jinja_as_raw": j["equal"],
    }


COUNTS = {
    "defaults": 208,
    "coerce": len(COERCE),
    "ini": len(INI),
    "toml": len(TOML),
    "load": len(LOAD),
    "cli": len(CLI),
    "dialect_fixtures": 2306,
    "jinja_as_raw": 2303,
}


def record_data(data: dict) -> dict:
    return {
        "kind": KIND,
        "format": FORMAT,
        "about": (
            "S3b C11: the config answers of the pinned sqlfluff "
            "(scripts/s3b/config_oracle.py; docs/interfaces/config.md). A value "
            'keeps its Python type: {"int": text}, {"float": repr}, {"dict": '
            "{...}}. defaults and base: [key path, value] of each setting. load: "
            "the settings that are not those of base, or the error. cli: the stdout "
            "(with -m: the tree with no position keys), the exit code, and the "
            'warning lines of stderr with no color of "sqlfluff parse -f json". sqll: what sqll must do (null: the same; '
            "unsupported; exit2). jinja_as_raw: the dialect fixtures that are not "
            "empty and have no Jinja delimiter, whose Jinja templated file is that of "
            "the raw templater (text, sliced file, raw slices)."
        ),
        "command": f"{COMMAND} record",
        "sqlfluff": {"version": data["sqlfluff"], "commit": submodule_commit()},
        "counts": counts(data),
        "jinja_as_raw": {
            k: v for k, v in data["jinja_as_raw"].items() if k != "problems"
        },
        "defaults": data["defaults"],
        "base": data["base"],
        "coerce": data["coerce"],
        "ini": data["ini"],
        "toml": data["toml"],
        "load": data["load"],
        "cli": data["cli"],
    }


def dumps(record: dict) -> str:
    """JSON with one line for each item of a list section."""
    lines = ["{"]
    keys = list(record)
    for k, key in enumerate(keys):
        end = "," if k < len(keys) - 1 else ""
        value = record[key]
        if not isinstance(value, list):
            lines.append(
                f" {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}{end}"
            )
            continue
        lines.append(f" {json.dumps(key)}: [")
        for i, item in enumerate(value):
            sep = "," if i < len(value) - 1 else ""
            lines.append(f"  {json.dumps(item, ensure_ascii=False)}{sep}")
        lines.append(" ]" + end)
    lines.append("}")
    return "\n".join(lines) + "\n"


def problems_of(data: dict) -> list[str]:
    problems = list(data["jinja_as_raw"]["problems"])
    got = counts(data)
    if got != COUNTS:
        problems.append(f"the counts are {got}, not {COUNTS}")
    return problems


def record() -> int:
    data = run_dump()
    RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECORD_FILE.write_text(dumps(record_data(data)), encoding="utf8")
    print(f"config_oracle: wrote {RECORD_FILE.relative_to(ROOT)}")
    for p in problems_of(data):
        print(f"config_oracle: {p}")
    return 1 if problems_of(data) else 0


def check() -> int:
    data = run_dump()
    problems = problems_of(data)
    want = dumps(record_data(data))
    if not RECORD_FILE.is_file() or RECORD_FILE.read_text(encoding="utf8") != want:
        problems.append(
            f"{RECORD_FILE.relative_to(ROOT)} is not the sqlfluff data ({COMMAND} record)"
        )
    clean = subprocess.run(
        [str(ROOT / "scripts" / "check-submodule"), "after the config data"],
        check=False,
    )
    if clean.returncode != 0:
        problems.append("the sqlfluff run changed the submodule")
    for p in problems:
        print(f"config check: {p}")
    if problems:
        print(f"config check: FAIL: {len(problems)} problems")
        return 1
    c = counts(data)
    print(
        f"config check: PASS: {c['defaults']} defaults, {c['coerce']} coerce, "
        f"{c['ini']} INI, {c['toml']} TOML, {c['load']} load and {c['cli']} CLI "
        f"scenarios; jinja as raw: {c['jinja_as_raw']} of "
        f"{data['jinja_as_raw']['literal']} dialect fixtures that are not empty and "
        "have no Jinja delimiter"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("record", help="write the record file")
    sub.add_parser("check", help="make the data again and compare")
    sub.add_parser("dump", help="(sqlfluff Python) print the data as JSON")
    args = parser.parse_args(argv)
    try:
        if args.command == "dump":
            json.dump(dump(), sys.stdout)
            return 0
        if args.command == "record":
            return record()
        return check()
    except DataError as e:
        print(f"config_oracle: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
