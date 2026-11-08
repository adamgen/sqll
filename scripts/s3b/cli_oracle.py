"""S3b task C13: the sqlfluff answers for the commands of sqll (lint, fix,
rules, dialects; harness/sqll.md).

Run it with the harness Python from the repository root:

    uv run --frozen --project harness python scripts/s3b/cli_oracle.py record
    uv run --frozen --project harness python scripts/s3b/cli_oracle.py check

Both run the pinned sqlfluff of the tool venv (tools/sqlfluff, pure Python)
on each scenario of SCENARIOS and make the data of RECORD_FILE. A scenario
runs in a new temporary folder ("<root>" stands for it) with its files, a
working folder, the arguments of the command, and stdin. HOME is
"<root>/h", XDG_CONFIG_HOME and NO_COLOR are not set, and
PYTHONHASHSEED is 0. With "tty", stdin is a terminal
(a pseudo terminal): the script types the answer when the command waits
for a key in raw mode (fix --check).

The record has, for each scenario: the stdout, the stderr, the exit code,
and each file that the command made or changed ("after"); for an
"unsupported" scenario only the exit code. The paths of
the folder are "<root>", and each time value of a lint record (the
"timings" of json and yaml, also in a file) is 0.0.

The "sqll" field says what sqll must do:

- null: the same stdout, stderr, exit code, and files;
- "unsupported": exit code 2 and "unsupported:" on stderr; no file
  changes (sqll fails closed);
- "usage": exit code 2 for both (a usage error: the texts differ).

For the scenarios of KEEP_OUTPUT, the record also keeps the stdout of an
"unsupported" scenario: the rules table of each sqlfluff rule
(crates/sqll/tests/cli.rs compares the table of sqll with it).

crates/sqll/tests/cli.rs runs sqll on each scenario.

record: write RECORD_FILE. check (CI job build): make the data again; it
must be the text of RECORD_FILE.

Exit code: 0 pass, 1 a failure.
"""

import argparse
import json
import os
import pty
import re
import select
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQLFLUFF_ROOT = ROOT / "third_party" / "sqlfluff"
RECORD_FILE = ROOT / "results" / "S3b" / "C13-cli.json"
KIND = "sqll-s3b-c13-cli"
FORMAT = 1
COMMAND = "uv run --frozen --project harness python scripts/s3b/cli_oracle.py"


class DataError(Exception):
    """A step failed, or the data do not agree."""


A = "select A from t\nUNION select b From t2\n"
B = "SELECT 1\n"
PRS = "SELECT a FROM t WHERE\n"
LXR = "select a ` from t\n"
LIT = "select NULL, true, False from t\n"
FUN = "SELECT max(a), Min(b) FROM t\n"
FILES = {"a.sql": A, "b.sql": B, "e.sql": PRS, "l.sql": LXR}
FOLDER = {
    "d/a.sql": A,
    "d/sub/c.SQL": FUN,
    "d/sub/n.txt": "not sql\n",
    "d/b.sql": B,
    "d/z/e.sql": PRS,
}
OVERLAP = {"a.sql": A, "s/b.sql": "select a from t where x = 1 1\n"}
# A file is in the LintedDir of the last path that reaches it.
LAST_PRS = {"m.sql": OVERLAP["s/b.sql"], "s/b.sql": OVERLAP["s/b.sql"]}
LAST_FIX = {"m.sql": "select a FROM t\n", "s/b.sql": "select a FROM t\n"}
# A pinned dialect fixture of sqlfluff (MIT, THIRD_PARTY.md).
SELECT_DIV = (
    SQLFLUFF_ROOT / "test/fixtures/dialects/sparksql/select_div.sql"
).read_text(encoding="utf-8")
CP = ["--dialect", "ansi", "--rules", "CP01,CP03,CP04"]
LONG_PRS = "SELECT a FROM t, ORDER a b c d e f g h i j k l m n o p q r s t u v w x y z aa bb cc dd ee\n"
LONG = "SELECT a, b, c FROM t WHERE a = 1 AND b = 2 AND c = 3 AND d = 4 OR e = 5 AND f = 6\n"


def sc(name, args, files=None, *, cwd=".", stdin=None, tty=None, sqll=None):
    """A scenario."""
    return {
        "name": name,
        "files": FILES if files is None else files,
        "cwd": cwd,
        "args": args,
        "stdin": stdin,
        "tty": tty,
        "sqll": sqll,
    }


SCENARIOS = [
    # lint: the human format.
    sc("lint human", ["lint", *CP, "a.sql", "b.sql", "e.sql", "l.sql"]),
    sc("lint human folder", ["lint", *CP, "d"], FOLDER),
    sc("lint human dot", ["lint", *CP, "."], FOLDER, cwd="d"),
    sc("lint human no path", ["lint", *CP], FOLDER, cwd="d/sub"),
    sc("lint stdin", ["lint", *CP, "-"], {}, stdin=A),
    sc("lint stdin parse error", ["lint", *CP, "-"], {}, stdin=PRS),
    sc("lint clean file", ["lint", *CP, "b.sql"]),
    sc("lint no files", ["lint", *CP, "d/sub/n.txt"], FOLDER),
    sc("lint quiet", ["lint", *CP, "-q", "a.sql", "b.sql"]),
    sc("lint nofail", ["lint", *CP, "--nofail", "a.sql"]),
    sc("lint color", ["lint", *CP, "--color", "a.sql", "e.sql", "l.sql"]),
    sc("lint nocolor", ["lint", *CP, "--nocolor", "a.sql"]),
    sc("lint literals", ["lint", *CP, "lit.sql"], {"lit.sql": LIT}),
    sc("lint functions", ["lint", *CP, "f.sql"], {"f.sql": FUN}),
    sc(
        "lint long description",
        ["lint", *CP, "x.sql"],
        {"x.sql": LONG.lower() + "UNION SELECT 1\n"},
    ),
    sc("lint crlf", ["lint", *CP, "c.sql"], {"c.sql": "select a\r\nFROM t\r\n"}),
    sc(
        "lint byte order mark",
        ["lint", *CP, "-f", "json", "bom.sql"],
        {"bom.sql": "﻿select a\nFROM t\n"},
    ),
    sc(
        "lint non-ASCII",
        ["lint", *CP, "-f", "json", "u.sql"],
        {"u.sql": "select 'é€😀' as x\nFROM t\n"},
    ),
    sc(
        "lint output_line_length",
        ["lint", *CP, "a.sql"],
        {"a.sql": A, ".sqlfluff": "[sqlfluff]\noutput_line_length = 60\n"},
    ),
    # A node of a raw class with one leaf child (binary_operator "div"):
    # sqlfluff counts one segment.
    sc(
        "lint json sparksql div",
        [
            "lint",
            "--dialect",
            "sparksql",
            "--rules",
            "CP01",
            "-f",
            "json",
            "select_div.sql",
        ],
        {"select_div.sql": SELECT_DIV},
    ),
    sc(
        "lint yaml sparksql div",
        ["lint", "--dialect", "sparksql", "--rules", "CP01", "-f", "yaml", "-"],
        {},
        stdin="SELECT 3 div 2\n",
    ),
    # lint: the other formats.
    sc("lint json", ["lint", *CP, "-f", "json", "a.sql", "b.sql", "e.sql", "l.sql"]),
    sc("lint json folder", ["lint", *CP, "--format", "json", "d"], FOLDER),
    sc("lint json no files", ["lint", *CP, "-f", "json", "d/sub/n.txt"], FOLDER),
    sc("lint yaml", ["lint", *CP, "-f", "yaml", "a.sql", "b.sql", "e.sql", "l.sql"]),
    sc("lint yaml long", ["lint", *CP, "-f", "yaml", "y.sql"], {"y.sql": LONG_PRS}),
    sc("lint human long", ["lint", *CP, "y.sql"], {"y.sql": LONG_PRS}),
    sc(
        "lint unclosed bracket",
        ["lint", *CP, "y.sql"],
        {"y.sql": "SELECT a FROM t WHERE (a = 1\n"},
        sqll="unsupported",
    ),
    sc(
        "lint yaml and json non-ASCII",
        ["lint", *CP, "-f", "yaml", "y.sql"],
        {"y.sql": "SELECT a FROM t WHERE 'é€😀\\' :\n"},
    ),
    sc(
        "lint json non-ASCII parse error",
        ["lint", *CP, "-f", "json", "y.sql"],
        {"y.sql": "SELECT a FROM t WHERE 'é€😀\\' :\n"},
    ),
    sc(
        "lint postgres",
        ["lint", "--dialect", "postgres", "--rules", "CP01,CP03,CP04", "p.sql"],
        {"p.sql": "select a::INT, now() FROM t WHERE b IS NULL\n"},
    ),
    sc(
        "fix tsql",
        ["fix", "--dialect", "tsql", "--rules", "CP01,CP03,CP04", "t.sql"],
        {"t.sql": "SELECT TOP 10 a, getdate() from t where b is null\nGO\n"},
    ),
    sc(
        "fix capitalise policy",
        ["fix", "x.sql"],
        {
            "x.sql": "select a FROM t\n",
            ".sqlfluff": "[sqlfluff]\ndialect = ansi\nrules = CP01,CP04\n\n[sqlfluff:rules:capitalisation.keywords]\ncapitalisation_policy = capitalise\n",
        },
    ),
    sc(
        "lint yaml stdin",
        ["lint", *CP, "-f", "yaml", "-"],
        {},
        stdin="SELECT 'it''s: #x' from t\n",
    ),
    sc(
        "lint github-annotation",
        ["lint", *CP, "-f", "github-annotation", "a.sql", "e.sql", "l.sql"],
    ),
    sc(
        "lint github-annotation error",
        [
            "lint",
            *CP,
            "-f",
            "github-annotation",
            "--annotation-level",
            "error",
            "a.sql",
        ],
    ),
    sc(
        "lint github-annotation-native",
        ["lint", *CP, "-f", "github-annotation-native", "a.sql", "b.sql", "e.sql"],
    ),
    sc(
        "lint github-annotation-native failure",
        [
            "lint",
            *CP,
            "-f",
            "github-annotation-native",
            "--annotation-level",
            "FAILURE",
            "a.sql",
        ],
    ),
    sc(
        "lint github-annotation-native notice",
        [
            "lint",
            *CP,
            "-f",
            "github-annotation-native",
            "--annotation-level",
            "notice",
            "a.sql",
        ],
    ),
    sc(
        "lint github-annotation-native clean",
        ["lint", *CP, "-f", "github-annotation-native", "b.sql"],
    ),
    sc("lint none", ["lint", *CP, "-f", "none", "a.sql"]),
    sc(
        "lint write-output json",
        ["lint", *CP, "-f", "json", "--write-output", "out.json", "a.sql"],
    ),
    sc(
        "lint write-output human",
        ["lint", *CP, "--write-output", "out.txt", "a.sql", "e.sql"],
    ),
    # lint: the rules and the config.
    sc(
        "lint one rule",
        ["lint", "--dialect", "ansi", "--rules", "CP03", "f.sql"],
        {"f.sql": FUN},
    ),
    sc(
        "lint rule name",
        ["lint", "--dialect", "ansi", "--rules", "capitalisation.keywords", "a.sql"],
    ),
    sc("lint rule alias", ["lint", "--dialect", "ansi", "--rules", "L010", "a.sql"]),
    sc("lint rule glob", ["lint", "--dialect", "ansi", "--rules", "CP0[134]", "a.sql"]),
    sc(
        "lint exclude rules",
        [
            "lint",
            "--dialect",
            "ansi",
            "--rules",
            "capitalisation",
            "--exclude-rules",
            "CP02,CP05",
            "a.sql",
        ],
    ),
    sc(
        "lint unknown rule reference",
        ["lint", "--dialect", "ansi", "--rules", "CP01,XYZ", "a.sql", "b.sql"],
    ),
    sc(
        "lint unknown rule reference json",
        ["lint", "--dialect", "ansi", "--rules", "CP01,XYZ", "-f", "json", "a.sql"],
    ),
    sc(
        "lint default rules", ["lint", "--dialect", "ansi", "a.sql"], sqll="unsupported"
    ),
    sc(
        "lint a rule that sqll does not have",
        ["lint", "--dialect", "ansi", "--rules", "CP01,LT01", "a.sql"],
        sqll="unsupported",
    ),
    sc(
        "lint a group with rules that sqll does not have",
        ["lint", "--dialect", "ansi", "--rules", "capitalisation", "a.sql"],
        sqll="unsupported",
    ),
    sc(
        "lint config file",
        ["lint", "a.sql"],
        {
            "a.sql": A,
            ".sqlfluff": "[sqlfluff]\ndialect = ansi\nrules = CP01\n\n[sqlfluff:rules:capitalisation.keywords]\ncapitalisation_policy = upper\n",
        },
    ),
    sc(
        "lint config in a folder",
        ["lint", "--dialect", "ansi", "x"],
        {"x/a.sql": A, "x/.sqlfluff": "[sqlfluff]\nrules = CP01\n", "b.sql": B},
    ),
    sc(
        "lint pyproject",
        ["lint", "a.sql"],
        {
            "a.sql": A,
            "pyproject.toml": "[tool.sqlfluff.core]\ndialect = 'ansi'\nrules = 'CP01'\n",
        },
    ),
    sc(
        "lint --config",
        ["lint", "--config", "c.cfg", "a.sql"],
        {"a.sql": A, "c.cfg": "[sqlfluff]\ndialect = ansi\nrules = CP01,CP04\n"},
    ),
    sc(
        "lint ignore-local-config",
        ["lint", "--rules", "CP01", "--ignore-local-config", "a.sql"],
        {"a.sql": A, ".sqlfluff": "[sqlfluff]\ndialect = ansi\n"},
    ),
    sc(
        "lint warnings setting",
        ["lint", "a.sql", "e.sql"],
        {
            **FILES,
            ".sqlfluff": "[sqlfluff]\ndialect = ansi\nrules = CP01\nwarnings = CP01,PRS\n",
        },
    ),
    sc(
        "lint warnings json",
        ["lint", "-f", "json", "a.sql"],
        {
            **FILES,
            ".sqlfluff": "[sqlfluff]\ndialect = ansi\nrules = CP01\nwarnings = capitalisation.keywords\n",
        },
    ),
    sc("lint ignore parsing", ["lint", *CP, "-i", "parsing", "e.sql", "l.sql"]),
    sc(
        "lint ignore lexing and parsing json",
        ["lint", *CP, "--ignore", "lexing,parsing", "-f", "json", "l.sql"],
    ),
    sc("lint ignore linting", ["lint", *CP, "-i", "linting", "a.sql"]),
    sc(
        "lint unexpected rule section",
        ["lint", "a.sql"],
        {
            "a.sql": A,
            ".sqlfluff": "[sqlfluff]\ndialect = ansi\nrules = CP01\n\n[sqlfluff:rules:CP01]\ncapitalisation_policy = upper\n\n[sqlfluff:rules:nope]\nx = 1\n",
        },
    ),
    sc(
        "lint invalid rule setting",
        ["lint", "a.sql"],
        {
            "a.sql": A,
            ".sqlfluff": "[sqlfluff]\ndialect = ansi\nrules = CP01\n\n[sqlfluff:rules:capitalisation.keywords]\ncapitalisation_policy = sideways\n",
        },
    ),
    sc(
        "lint large file",
        ["lint", *CP, "a.sql", "b.sql"],
        {**FILES, ".sqlfluff": "[sqlfluff]\nlarge_file_skip_byte_limit = 20\n"},
    ),
    sc(
        "lint large file fail",
        ["lint", *CP, "a.sql", "b.sql"],
        {
            **FILES,
            ".sqlfluff": "[sqlfluff]\nlarge_file_skip_byte_limit = 20\nlarge_file_skip_fail = True\n",
        },
    ),
    sc(
        "lint large file json",
        ["lint", *CP, "-f", "json", "a.sql", "b.sql"],
        {**FILES, ".sqlfluff": "[sqlfluff]\nlarge_file_skip_byte_limit = 20\n"},
    ),
    sc(
        "lint sql_file_exts",
        ["lint", *CP, "."],
        {
            "a.sql": A,
            "b.ddl": B,
            "c.foo": A,
            ".sqlfluff": "[sqlfluff]\nsql_file_exts = .ddl,.foo\n",
        },
    ),
    sc("lint templater raw", ["lint", *CP, "--templater", "raw", "a.sql"]),
    sc("lint processes 1", ["lint", *CP, "-p", "1", "a.sql", "b.sql"]),
    sc(
        "lint disable-noqa",
        ["lint", *CP, "--disable-noqa", "q.sql"],
        {"q.sql": "SELECT a from t -- noqa\n"},
    ),
    # lint: errors.
    sc("lint no dialect", ["lint", "--rules", "CP01", "a.sql"]),
    sc(
        "lint unknown dialect",
        ["lint", "--dialect", "nope", "--rules", "CP01", "a.sql"],
    ),
    sc("lint path that does not exist", ["lint", *CP, "a.sql", "nope.sql"]),
    sc(
        "lint noqa comment",
        ["lint", *CP, "q.sql"],
        {"q.sql": "SELECT a from t -- noqa\n"},
        sqll="unsupported",
    ),
    sc(
        "lint in-file config",
        ["lint", *CP, "i.sql"],
        {
            "i.sql": "-- sqlfluff:rules:capitalisation.keywords:capitalisation_policy:upper\nselect a from t\n"
        },
        sqll="unsupported",
    ),
    sc(
        "lint in-file config no space",
        ["lint", *CP, "i.sql"],
        {
            "i.sql": "--sqlfluff:rules:capitalisation.keywords:capitalisation_policy:upper\nselect a from t\n"
        },
        sqll="unsupported",
    ),
    sc(
        "lint in-file config no space rules",
        ["lint", "--dialect", "ansi", "--rules", "CP01", "i.sql"],
        {"i.sql": "select 1\r\n--sqlfluff:rules:LT01\r\nSELECT a from t\r\n"},
        sqll="unsupported",
    ),
    sc(
        "lint jinja tag",
        ["lint", *CP, "j.sql"],
        {"j.sql": "SELECT {{ 1 }} from t\n"},
        sqll="unsupported",
    ),
    sc("lint format sarif", ["lint", *CP, "-f", "sarif", "a.sql"], sqll="unsupported"),
    sc(
        "lint ignore file",
        ["lint", *CP, "."],
        {"a.sql": A, ".sqlfluffignore": "b.sql\n", "b.sql": B},
        sqll="unsupported",
    ),
    sc(
        "lint processes 2",
        ["lint", *CP, "-p", "2", "a.sql", "b.sql"],
        sqll="unsupported",
    ),
    sc("lint verbose", ["lint", *CP, "-v", "a.sql"], sqll="unsupported"),
    sc("lint unknown option", ["lint", *CP, "--nope", "a.sql"], sqll="usage"),
    sc("lint bad format", ["lint", *CP, "-f", "xml", "a.sql"], sqll="usage"),
    # fix.
    sc("fix files", ["fix", *CP, "a.sql", "b.sql", "e.sql", "l.sql"]),
    sc("fix folder", ["fix", *CP, "d"], FOLDER),
    sc(
        "fix literals and functions",
        ["fix", *CP, "lit.sql", "f.sql"],
        {"lit.sql": LIT, "f.sql": FUN},
    ),
    sc("fix no violations", ["fix", *CP, "b.sql"]),
    sc("fix only a parse error", ["fix", *CP, "e.sql"]),
    sc("fix stdin", ["fix", *CP, "-"], {}, stdin=A),
    sc("fix stdin clean", ["fix", *CP, "-"], {}, stdin=B),
    sc("fix stdin parse error", ["fix", *CP, "-"], {}, stdin="SELECT a from t WHERE\n"),
    sc("fix stdin crlf", ["fix", *CP, "-"], {}, stdin="select a\r\nFROM t\r\n"),
    sc("fix stdin crlf clean", ["fix", *CP, "-"], {}, stdin="select a\r\nfrom t\r\n"),
    sc("fix stdin cr clean", ["fix", *CP, "-"], {}, stdin="select a\rfrom t\r"),
    sc("fix stdin cr", ["fix", *CP, "-"], {}, stdin="SELECT a\rfrom t\r"),
    sc(
        "fix fixed-suffix",
        ["fix", *CP, "-x", "_fixed", "a.sql", "f.sql"],
        {"a.sql": A, "f.sql": FUN},
    ),
    sc("fix force", ["fix", *CP, "-f", "a.sql"]),
    sc("fix quiet", ["fix", *CP, "-q", "a.sql", "e.sql"]),
    sc("fix color", ["fix", *CP, "--color", "a.sql", "e.sql"]),
    sc(
        "fix crlf and byte order mark",
        ["fix", *CP, "c.sql", "bom.sql"],
        {"c.sql": "select a\r\nFROM t\r\n", "bom.sql": "﻿select a\nFROM t\n"},
    ),
    sc(
        "fix ignore parsing",
        ["fix", *CP, "-i", "parsing", "e.sql", "x.sql"],
        {"e.sql": "select a FROM t WHERE\n", "x.sql": A},
    ),
    sc(
        "fix warnings",
        ["fix", "a.sql", "e.sql"],
        {
            **FILES,
            ".sqlfluff": "[sqlfluff]\ndialect = ansi\nrules = CP01\nwarnings = CP01,PRS\n",
        },
    ),
    sc(
        "fix config policy",
        ["fix", "a.sql"],
        {
            "a.sql": A,
            ".sqlfluff": "[sqlfluff]\ndialect = ansi\nrules = CP01\n\n[sqlfluff:rules:capitalisation.keywords]\ncapitalisation_policy = upper\n",
        },
    ),
    sc(
        "fix large file",
        ["fix", *CP, "a.sql", "b.sql"],
        {**FILES, ".sqlfluff": "[sqlfluff]\nlarge_file_skip_byte_limit = 20\n"},
    ),
    sc("fix check yes", ["fix", *CP, "--check", "a.sql", "b.sql", "e.sql"], tty="y"),
    sc("fix check enter", ["fix", *CP, "--check", "a.sql"], tty="\r"),
    sc("fix check no", ["fix", *CP, "--check", "a.sql"], tty="n"),
    sc("fix check other key", ["fix", *CP, "--check", "a.sql"], tty="x"),
    sc("fix check no fixes", ["fix", *CP, "--check", "b.sql"]),
    sc("fix default rules", ["fix", "--dialect", "ansi", "a.sql"], sqll="unsupported"),
    sc(
        "fix even unparsable",
        ["fix", *CP, "--FIX-EVEN-UNPARSABLE", "e.sql", "a.sql"],
        sqll="unsupported",
    ),
    sc(
        "fix in-file config no space",
        ["fix", *CP, "i.sql"],
        {"i.sql": "--sqlfluff:rules:CP01\nselect a FROM t\n"},
        sqll="unsupported",
    ),
    sc(
        "lint invalid config value",
        ["lint", *CP, "a.sql"],
        {**FILES, ".sqlfluff": "[sqlfluff]\nrunaway_limit = 0\n"},
    ),
    # The ignore file check loads a sub folder config as a Path.
    sc(
        "lint invalid config value in a sub folder",
        ["lint", *CP, "."],
        {"a.sql": A, "d/b.sql": B, "d/.sqlfluff": "[sqlfluff]\nrunaway_limit = 0\n"},
    ),
    sc(
        "fix invalid config value in a sub folder no ignore files",
        ["fix", *CP, "--disregard-sqlfluffignores", "."],
        {"a.sql": A, "d/b.sql": B, "d/.sqlfluff": "[sqlfluff]\nrunaway_limit = 0\n"},
    ),
    sc(
        "lint invalid config text value",
        ["lint", *CP, "a.sql"],
        {**FILES, ".sqlfluff": "[sqlfluff:indentation]\nimplicit_indents = maybe\n"},
    ),
    sc(
        "lint invalid layout key",
        ["lint", *CP, "a.sql"],
        {**FILES, ".sqlfluff": "[sqlfluff:layout:type:comma]\nfoo = bar\n"},
    ),
    sc(
        "lint invalid templater",
        ["lint", *CP, "a.sql"],
        {**FILES, ".sqlfluff": "[sqlfluff]\ntemplater = foo\n"},
    ),
    # Two paths reach s/b.sql: one residual error entry for each file.
    sc("fix overlapping paths", ["fix", *CP, ".", "s"], OVERLAP),
    sc(
        "fix check overlapping paths",
        ["fix", *CP, "--check", ".", "s/b.sql"],
        OVERLAP,
        tty="y",
    ),
    sc("fix last path file", ["fix", *CP, "s/b.sql", "m.sql", "s/b.sql"], LAST_PRS),
    sc("fix last path folder", ["fix", *CP, "s", "m.sql", "s"], LAST_PRS),
    sc("fix last path dot", ["fix", *CP, "s", ".", "s/b.sql"], LAST_PRS),
    sc(
        "fix check last path parse errors",
        ["fix", *CP, "--check", "s/b.sql", "m.sql", "s/b.sql"],
        LAST_PRS,
    ),
    sc(
        "fix check last path fixable",
        ["fix", *CP, "--check", "s", "m.sql", "s"],
        LAST_FIX,
        tty="y",
    ),
    sc("fix no dialect", ["fix", "--rules", "CP01", "a.sql"]),
    sc("fix path that does not exist", ["fix", *CP, "nope.sql"]),
    # rules and dialects.
    sc(
        "rules selected",
        ["rules"],
        {".sqlfluff": "[sqlfluff]\nrules = CP01,CP03,CP04\n"},
    ),
    sc("rules one", ["rules"], {".sqlfluff": "[sqlfluff]\nrules = CP04\n"}),
    sc(
        "rules color",
        ["rules", "--color"],
        {".sqlfluff": "[sqlfluff]\nrules = capitalisation.keywords,CP03,L040\n"},
    ),
    sc("rules default", ["rules"], {}, sqll="unsupported"),
    sc(
        "rules not in sqll",
        ["rules"],
        {".sqlfluff": "[sqlfluff]\nrules = CP01,LT01\n"},
        sqll="unsupported",
    ),
    sc(
        "rules line length",
        ["rules"],
        {".sqlfluff": "[sqlfluff]\nrules = CP01,CP03,CP04\noutput_line_length = 40\n"},
    ),
    sc("dialects", ["dialects"], {}),
    sc("dialects color", ["dialects", "--color"], {}),
    sc("dialects nocolor", ["dialects", "-n"], {}),
]

# The unsupported scenarios that keep their stdout.
KEEP_OUTPUT = ("rules default",)

TIMINGS_JSON = re.compile(r'("timings": \{)([^}]*)(\})')
JSON_NUMBER = re.compile(r": -?[0-9][0-9.e+-]*")
YAML_TIMING = re.compile(r"^(    [^ :]+): -?[0-9][0-9.e+-]*$")


def mask_timings(text: str) -> str:
    """Each time value of a json or yaml lint record as 0.0."""
    text = TIMINGS_JSON.sub(
        lambda m: m.group(1) + JSON_NUMBER.sub(": 0.0", m.group(2)) + m.group(3), text
    )
    out, in_timings = [], False
    for line in text.split("\n"):
        if in_timings and line.startswith("    "):
            line = YAML_TIMING.sub(r"\1: 0.0", line)
        else:
            in_timings = line == "  timings:"
        out.append(line)
    return "\n".join(out)


def tool_bin() -> Path:
    sys.path.insert(0, str(ROOT / "harness"))
    from sqll_harness.paths import tools_dir

    return tools_dir() / "sqlfluff" / "bin" / "sqlfluff"


def make_files(root: Path, files: dict) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)


def read_files(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and not rel.startswith("h/"):
            out[rel] = path.read_bytes().decode("utf-8")
    return out


def run_tty(argv, cwd, env, answer: str):
    """Run with stdin a pseudo terminal. Type the answer when the command
    has set raw mode (no ICANON) after the prompt."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=slave,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out = b""
    deadline = time.monotonic() + 300
    typed = False
    while True:
        ready, _, _ = select.select([proc.stdout], [], [], 0.05)
        if ready:
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                break
            out += chunk
        if not typed and b"[Y/n] " in out:
            if not termios.tcgetattr(slave)[3] & termios.ICANON:
                os.write(master, answer.encode())
                typed = True
        if time.monotonic() > deadline:
            proc.kill()
            raise DataError(f"{argv}: no end")
    err = proc.stderr.read()
    proc.wait()
    os.close(master)
    os.close(slave)
    return proc.returncode, out.decode(), err.decode()


def run_scenario(binary: Path, s: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="sqll-c13-") as tmp:
        root = Path(tmp).resolve()
        make_files(root, s["files"])
        for folder in (s["cwd"], "h"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        before = read_files(root)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env.update(HOME=f"{root}/h", PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0")
        for key in ("XDG_CONFIG_HOME", "NO_COLOR"):
            env.pop(key, None)
        argv = [str(binary), *s["args"]]
        cwd = root / s["cwd"]
        if s["tty"] is not None:
            code, stdout, stderr = run_tty(argv, cwd, env, s["tty"])
        else:
            proc = subprocess.run(
                argv,
                cwd=cwd,
                env=env,
                input=(s["stdin"] or "").encode(),
                capture_output=True,
                check=False,
                timeout=300,
            )
            code = proc.returncode
            stdout, stderr = proc.stdout.decode(), proc.stderr.decode()
        after = read_files(root)
        changed = {k: mask_timings(v) for k, v in after.items() if before.get(k) != v}
        if s["sqll"] == "unsupported":
            # sqll fails closed: only the exit code of sqlfluff is kept (some
            # of these outputs have times or a process order).
            if s["name"] in KEEP_OUTPUT:
                return {**s, "exit_code": code, "stdout": stdout}
            return {**s, "exit_code": code}
        return {
            **s,
            "exit_code": code,
            "stdout": mask_timings(stdout.replace(str(root), "<root>")),
            "stderr": stderr.replace(str(root), "<root>"),
            "after": changed,
        }


def run_all() -> list:
    binary = tool_bin()
    if not binary.is_file():
        raise DataError(f"no {binary} (scripts/setup)")
    print(f"cli_oracle: {len(SCENARIOS)} sqlfluff runs", flush=True)
    return [run_scenario(binary, s) for s in SCENARIOS]


def sqlfluff_version(binary: Path) -> str:
    out = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, check=True
    )
    return out.stdout.strip().rsplit(" ", 1)[-1]


def submodule_commit() -> str:
    out = subprocess.run(
        ["git", "-C", str(SQLFLUFF_ROOT), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    return out.stdout.strip()


def record_data(cli: list) -> dict:
    return {
        "kind": KIND,
        "format": FORMAT,
        "about": (
            "S3b C13: the stdout, stderr, exit code, and changed files of the pinned "
            "sqlfluff for each scenario (scripts/s3b/cli_oracle.py; harness/sqll.md). "
            '"<root>" is the scenario folder; each time value of a lint record is 0.0. '
            "sqll: what sqll must do (null: the same; unsupported; usage)."
        ),
        "command": f"{COMMAND} record",
        "sqlfluff": {
            "version": sqlfluff_version(tool_bin()),
            "commit": submodule_commit(),
        },
        "count": len(cli),
        "scenarios": cli,
    }


def dumps(record: dict) -> str:
    """JSON with one line for each scenario."""
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


def problems_of(cli: list) -> list[str]:
    problems = []
    names = [s["name"] for s in cli]
    if len(set(names)) != len(names):
        problems.append("two scenarios have one name")
    for s in cli:
        if s["sqll"] == "unsupported" and s["exit_code"] == 2:
            problems.append(f"{s['name']}: sqlfluff fails too (not a fail-closed case)")
    return problems


def record() -> int:
    cli = run_all()
    RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECORD_FILE.write_text(dumps(record_data(cli)), encoding="utf8")
    print(f"cli_oracle: wrote {RECORD_FILE.relative_to(ROOT)}")
    for p in problems_of(cli):
        print(f"cli_oracle: {p}")
    return 1 if problems_of(cli) else 0


def check() -> int:
    cli = run_all()
    problems = problems_of(cli)
    want = dumps(record_data(cli))
    if not RECORD_FILE.is_file() or RECORD_FILE.read_text(encoding="utf8") != want:
        problems.append(
            f"{RECORD_FILE.relative_to(ROOT)} is not the sqlfluff data ({COMMAND} record)"
        )
    clean = subprocess.run(
        [str(ROOT / "scripts" / "check-submodule"), "after the CLI data"], check=False
    )
    if clean.returncode != 0:
        problems.append("the sqlfluff run changed the submodule")
    for p in problems:
        print(f"cli check: {p}")
    if problems:
        print(f"cli check: FAIL: {len(problems)} problems")
        return 1
    marks = {}
    for s in cli:
        marks[str(s["sqll"])] = marks.get(str(s["sqll"]), 0) + 1
    print(f"cli check: PASS: {len(cli)} scenarios ({marks})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("record", help="write the record file")
    sub.add_parser("check", help="make the data again and compare")
    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            return record()
        return check()
    except DataError as e:
        print(f"cli_oracle: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
