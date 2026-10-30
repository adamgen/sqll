"""S3 phase A, task T8: the capabilities of each base for S6 (templaters),
S7 (CLI and config), G2 and S8 (the tree for code generation, one parse),
and the cause of the G3 start time (criterion C7 of
docs/decisions/s3-base.md).

Commands. Run them with the harness Python:

    uv run --frozen --project harness python scripts/s3/capabilities.py collect --scratch DIR
    flock /tmp/sqll-machine.lock uv run --frozen --project harness python scripts/s3/capabilities.py time --scratch DIR
    uv run --frozen --project harness python scripts/s3/capabilities.py report [--check]

"collect" makes DIR (it must not exist) and records in SOURCES_FILE:
- the help text of each command of sqlfluff 4.4.0 and sqruff 0.41.0 (the
  tools of scripts/setup), and the other commands of the tools;
- the click objects, the templaters, the placeholder styles, and the
  default config of the pinned sqlfluff (its tool venv);
- the facts from the sqruff 0.41.0 sources: the crates of the cargo cache.
  Each crate must have the checksum of the sqruff Cargo.lock, as in T7.
  Each fact cites its file, the file sha256, and its lines.

"time" runs one serial session in the CI image (harness/bench.md,
"Baseline") and records START_FILE: the start benchmarks of sqlfluff and
sqruff, the Python start and the import of the sqlfluff CLI, and
"sqruff --version".

"report" reads only the committed files and the pinned submodule, and
writes OUT_FILE. The sqlfluff and sqlfluffrs facts come from the submodule
here. With --check it writes nothing and fails if OUT_FILE is not the new
text.

Each command stops with exit code 1 if a step fails or the data do not
agree (DataError).
"""

import argparse
import ast
import configparser
import io
import json
import re
import statistics
import sys
import tokenize
from datetime import UTC, datetime
from pathlib import Path

from sqll_harness.paths import SQLFLUFF_ROOT, sqlfluff_ref, tools_dir

sys.path.insert(0, str(Path(__file__).resolve().parent))
import license_size as ls  # noqa: E402
import phase_a  # noqa: E402
import sqlfluffrs_probe as probe  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "s3"
SOURCES_FILE = RESULTS / "capabilities-sources.json"
START_FILE = RESULTS / "capabilities-start.json"
OUT_FILE = RESULTS / "capabilities.json"
T2_FILE = RESULTS / "s1-by-base.json"
T5_FILE = RESULTS / "sqlfluffrs-probe.json"
T6_FILE = RESULTS / "speed-by-base.json"
T7_FILE = RESULTS / "license-size.json"
T7_SOURCES = RESULTS / "license-size-sources.json"
S2_FILE = phase_a.read_path("results/s2/baseline.json")
KNOWN_FAILURES = ROOT / "known_failures" / "sqruff.txt"
_SCRIPT = "uv run --frozen --project harness python scripts/s3/capabilities.py"
COMMANDS = {
    "collect": f"{_SCRIPT} collect --scratch DIR",
    "time": f"flock /tmp/sqll-machine.lock {_SCRIPT} time --scratch DIR",
    "report": f"{_SCRIPT} report",
}

DataError = probe.DataError
MAX_SESSION_LOAD = probe.MAX_SESSION_LOAD
sha256_bytes = probe.sha256_bytes
sha256_file = probe.sha256_file
rel = probe.rel

SQLFLUFF_VERSION = "4.4.0"
SQRUFF_VERSION = ls.SQRUFF_VERSION
SQLFLUFFRS = "sqlfluffrs"
BASES = ("sqruff", "sqlfluffrs", "new-parser")
TOOLS = "$TOOLS"
# The help text must not depend on the terminal.
HELP_ENV = {"COLUMNS": "80", "NO_COLOR": "1", "TERM": "dumb"}
# With GITHUB_ACTIONS set, sqruff gives another default output format.
HELP_UNSET = ("GITHUB_ACTIONS",)
TEMPLATER_NAMES = ("raw", "jinja", "python", "placeholder", "dbt", "sqlmesh")
SCHEMA_SEARCH = re.compile(r"json[ _-]?schema", re.I)


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def dump(data) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


# Facts with their evidence. An entry is {"value", "evidence"}; a judgement
# also has "estimate": true and the "judgement" text. Evidence kinds:
# {"command": id} (a command of SOURCES_FILE or START_FILE), {"source": ...}
# (a file, its version or commit, its sha256, and the cited lines), and
# {"result": file, "key": dotted key} (a committed result).


def fact(value, *evidence) -> dict:
    if not evidence:
        raise DataError(f"a fact with no evidence: {value!r}")
    return {"value": value, "evidence": list(evidence)}


def estimate(value, judgement: str, *evidence) -> dict:
    if not evidence:
        raise DataError(f"an estimate with no evidence: {value!r}")
    return {
        "value": value,
        "estimate": True,
        "judgement": judgement,
        "evidence": list(evidence),
    }


def command(cid: str) -> dict:
    return {"command": cid}


def result(path: Path, key: str) -> dict:
    return {"result": rel(path), "key": key}


def get_key(data, key: str):
    for part in key.split("."):
        if isinstance(data, list):
            data = data[int(part)]
        else:
            data = data[part]
    return data


class Source:
    """A text file of a base, with line citations (line numbers from 1)."""

    def __init__(self, base: str, origin: dict, path: str, data: bytes) -> None:
        self.base = base
        self.origin = origin
        self.path = path
        self.sha256 = sha256_bytes(data)
        self.lines = data.decode("utf8").splitlines()

    def find(self, pattern: str, start: int = 1) -> int:
        rx = re.compile(pattern)
        for no in range(start, len(self.lines) + 1):
            if rx.search(self.lines[no - 1]):
                return no
        raise DataError(f"{self.path}: no line matches {pattern!r}")

    def block(self, start: str, end: str, after: int = 1) -> tuple[int, int]:
        first = self.find(start, after)
        return first, self.find(end, first + 1)

    def matches(self, pattern: str, first: int = 1, last: int | None = None):
        rx = re.compile(pattern)
        last = last or len(self.lines)
        return [
            (no, m)
            for no in range(first, last + 1)
            if (m := rx.search(self.lines[no - 1]))
        ]

    def cite(self, *line_numbers: int) -> dict:
        return {
            "source": {
                "base": self.base,
                **self.origin,
                "file": self.path,
                "sha256": self.sha256,
                "lines": {
                    str(no): self.lines[no - 1].strip()
                    for no in sorted(set(line_numbers))
                },
            }
        }


def submodule_source(path: str) -> Source:
    full = SQLFLUFF_ROOT / path
    origin = {"version": SQLFLUFF_VERSION, "commit": sqlfluff_ref(SQLFLUFF_ROOT)}
    base = SQLFLUFFRS if path.startswith("sqlfluffrs/") else "sqlfluff"
    return Source(base, origin, f"third_party/sqlfluff/{path}", full.read_bytes())


def document(path: str, text: str) -> dict:
    """A quote of a file of this repository. The check finds the text in the
    file (spaces normalized), so the quote does not depend on line numbers."""
    if " ".join(text.split()) not in " ".join((ROOT / path).read_text("utf8").split()):
        raise DataError(f"{path} does not have the text {text!r}")
    return {"document": path, "text": text}


# Help text parsers. Each fails (DataError) on an option line that it does
# not understand, so a new help format cannot drop an option.


SECTION = re.compile(r"^(\S[^:]*):\s*$")


def sections(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        m = SECTION.match(line)
        if m and not line.startswith(" "):
            current = m[1]
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return out


def usage_args(text: str) -> list[str]:
    m = re.search(r"^Usage: \S+(?: \S+)? \[OPTIONS\](.*)$", text, re.M)
    if not m:
        raise DataError(f"no usage line: {text[:80]!r}")
    return m[1].split()


def command_names(text: str) -> list[str]:
    names = []
    for line in sections(text).get("Commands", []):
        if not line.strip():
            break
        m = re.match(r"^  ([a-z][\w-]*)(?:\s{2,}|$)", line)
        if not m:
            raise DataError(f"a command line that the parser does not read: {line!r}")
        names.append(m[1])
    if not names:
        raise DataError("the help text has no commands")
    return names


CLAP_OPTION = re.compile(
    r"^(?:  (-\w), |      )(--[A-Za-z0-9][\w-]*)(\.\.\.)?(?: <([A-Z0-9_]+)>(\.\.\.)?)?$"
)
CLAP_SHORT_ONLY = re.compile(r"^  (-\w)(\.\.\.)?(?: <([A-Z0-9_]+)>)?$")


def clap_options(text: str) -> list[dict]:
    """The options of a clap help text (sqruff), in order."""
    lines = sections(text).get("Options")
    if lines is None:
        raise DataError("the help text has no Options section")
    out: list[dict] = []
    in_values = False
    for line in lines:
        if not line.strip():
            continue
        if line.startswith("  -") or line.startswith("      --"):
            m = CLAP_OPTION.match(line)
            s = None if m else CLAP_SHORT_ONLY.match(line)
            if not m and not s:
                raise DataError(
                    f"an option line that the parser does not read: {line!r}"
                )
            long, short = (m[2], m[1]) if m else (None, s[1])
            value = (m[4] if m else s[3]) or None
            out.append(
                {
                    "names": [n for n in (short, long) if n],
                    "long": long,
                    "short": short,
                    "value": value,
                    "choices": None,
                    "aliases": [],
                }
            )
            in_values = False
            continue
        if not out:
            raise DataError(f"text before the first option: {line!r}")
        body = line.strip()
        if body == "Possible values:":
            out[-1]["choices"] = []
            in_values = True
        elif in_values and (v := re.match(r"^- ([\w-]+)(?::.*)?$", body)):
            out[-1]["choices"].append(v[1])
        elif a := re.match(r"^\[alias(?:es)?: (.*)\]$", body):
            out[-1]["aliases"] = [x.strip() for x in a[1].split(",")]
            out[-1]["names"] += out[-1]["aliases"]
            in_values = False
        else:
            in_values = False
    return out


CLICK_NAMES = re.compile(r"^(-{1,2}[\w-]+(?:, -{1,2}[\w-]+)*)(?: (\S+))?$")


def click_options(text: str) -> list[dict]:
    """The options of a click help text (sqlfluff), in order."""
    lines = sections(text).get("Options")
    if lines is None:
        raise DataError("the help text has no Options section")
    out: list[dict] = []
    for line in lines:
        if not line.startswith("  -"):
            if line.strip() and not line.startswith("   "):
                raise DataError(f"a line that the parser does not read: {line!r}")
            continue
        decl = re.split(r" {2,}", line.strip(), maxsplit=1)[0]
        parts = decl.split(" / ")
        names: list[str] = []
        value = None
        for i, part in enumerate(parts):
            m = CLICK_NAMES.match(part)
            if not m:
                raise DataError(
                    f"an option line that the parser does not read: {line!r}"
                )
            names += m[1].split(", ")
            if m[2]:
                if i != 0 or len(parts) > 1:
                    raise DataError(f"a value on a flag pair: {line!r}")
                value = m[2]
        choices = None
        if value and value.startswith("[") and value.endswith("]"):
            choices = value[1:-1].split("|")
        longs = [n for n in names if n.startswith("--")]
        shorts = [n for n in names if not n.startswith("--")]
        out.append(
            {
                "names": names,
                "long": longs[0] if longs else None,
                "short": shorts[0] if shorts else None,
                "value": value,
                "choices": choices,
                "aliases": longs[1:],
            }
        )
    return out


def option_index(options: list[dict]) -> dict[str, dict]:
    """Each long name (with the aliases and the secondary flags) to its option."""
    out = {}
    for opt in options:
        for name in opt["names"]:
            if name.startswith("--"):
                out[name] = opt
    return out


# collect


PY_FACTS = r"""
import json, click, sqlfluff
from sqlfluff.cli.commands import cli
from sqlfluff.core.helpers.dict import nested_combine
from sqlfluff.core.plugin.host import get_plugin_manager
from sqlfluff.core.templaters import core_templaters
from sqlfluff.core.templaters.placeholder import KNOWN_STYLES

def flat(d, p=()):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from flat(v, p + (k,))
        else:
            yield ".".join(p + (k,))

pm = get_plugin_manager()
commands = {}
for name, cmd in sorted(cli.commands.items()):
    params = []
    for p in cmd.params:
        params.append({
            "kind": "option" if isinstance(p, click.Option) else "argument",
            "name": p.name,
            "names": list(p.opts) + list(p.secondary_opts),
            "choices": list(p.type.choices) if isinstance(p.type, click.Choice) else None,
            "hidden": bool(getattr(p, "hidden", False)),
        })
    with click.Context(cmd, parent=click.Context(cli, **cli.context_settings)) as ctx:
        help_option = cmd.get_help_option(ctx)
    if help_option is not None:
        params.append({
            "kind": "option",
            "name": help_option.name,
            "names": sorted(help_option.opts + help_option.secondary_opts),
            "choices": None,
            "hidden": bool(help_option.hidden),
        })
    commands[name] = {"hidden": cmd.hidden, "params": params}
print(json.dumps({
    "sqlfluff_version": sqlfluff.__version__,
    "sqlfluff_file": sqlfluff.__file__,
    "commands": commands,
    "core_templaters": [t.name for t in core_templaters()],
    "plugin_templaters": sorted({t.name for ts in pm.hook.get_templaters() for t in ts}),
    "placeholder_styles": {k: v.pattern for k, v in KNOWN_STYLES.items()},
    "default_config_keys": sorted(flat(nested_combine(*pm.hook.load_default_config()))),
}))
"""


class Recorder:
    """Runs the commands of collect, and keeps their output with their
    record (Steps): the tool paths are $TOOLS."""

    def __init__(self, scratch: Path) -> None:
        self.st = probe.Steps(scratch)
        self.scratch = scratch
        self.tools = tools_dir()
        self.outputs: dict[str, dict] = {}

    def run(self, cid: str, argv: list, env: dict | None = None) -> str:
        if cid in self.outputs:
            raise DataError(f"two commands with the id {cid!r}")
        proc = self.st.run(cid, argv, self.scratch, set_env=env, unset=HELP_UNSET)
        entry = self.st.entries[-1]
        shown = self.st.show(str(self.tools))
        entry["argv"] = [a.replace(shown, TOOLS) for a in entry["argv"]]
        stdout = proc.stdout.replace(str(self.tools), TOOLS)
        self.outputs[cid] = {**entry, "stdout": stdout}
        return stdout


def help_ids(tool: str, commands: list[str]) -> list[tuple[str, list[str]]]:
    out = [(f"{tool} --help", ["--help"])]
    out += [(f"{tool} {c} --help", [c, "--help"]) for c in commands]
    return out


def crate_sources(cache: Path) -> tuple[dict[str, dict[str, bytes]], dict]:
    """The files of each sqruff crate, after the checks of T7."""
    contents, meta = {}, {}
    for name in ls.SQRUFF_CRATES:
        path = cache / f"{name}-{SQRUFF_VERSION}.crate"
        if not path.exists():
            raise DataError(f"{path} does not exist; run tools/sqruff/install.sh")
        contents[name] = ls.read_crate_bytes(path)
        meta[name] = sha256_file(path)
    locked = ls.lock_checksums(contents["sqruff"]["Cargo.lock"].decode("utf8"))
    for name in ls.SQRUFF_CRATES:
        if name != "sqruff" and locked.get(f"{name}-{SQRUFF_VERSION}") != meta[name]:
            raise DataError(
                f"{name}: the crate is not the one of the sqruff Cargo.lock"
            )
    return contents, meta


def crate_source(contents, meta, crate: str, path: str) -> Source:
    origin = {"crate": crate, "version": SQRUFF_VERSION, "crate_sha256": meta[crate]}
    return Source("sqruff", origin, path, contents[crate][path])


def ini_keys(text: str, root: str) -> list[str]:
    """The setting keys of a default_config.cfg: "<section path>.<key>",
    with the section [root] as "core"."""
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(text)
    keys = []
    for section in parser.sections():
        if section == root:
            path = ["core"]
        elif section.startswith(root + ":"):
            path = section[len(root) + 1 :].split(":")
        else:
            raise DataError(f"a section that is not under [{root}]: [{section}]")
        keys += [".".join([*path, k]) for k in parser.options(section)]
    return sorted(keys)


def sqruff_facts(contents, meta) -> dict:
    """The facts of the sqruff 0.41.0 sources. Each value cites its lines."""

    def src(crate, path):
        return crate_source(contents, meta, crate, path)

    out = {}
    t = src("sqruff-lib", "src/templaters.rs")
    templaters = {}
    for feature, cfg in (
        ("python", r'^#\[cfg\(feature = "python"\)\]$'),
        ("no_python", r'^#\[cfg\(not\(feature = "python"\)\)\]$'),
    ):
        lines = [no for no, _ in t.matches(cfg)]
        found = None
        for no in lines:
            if re.match(r"^pub static TEMPLATERS: ", t.lines[no]):
                found = no + 1
        if found is None:
            raise DataError(f"src/templaters.rs: no TEMPLATERS for {feature}")
        last = found if t.lines[found - 1].endswith("];") else t.find(r"^\];$", found)
        names = [
            m.lower()
            for no in range(found, last + 1)
            for m in re.findall(r"&(\w+)_TEMPLATER", t.lines[no - 1])
        ]
        templaters[feature] = fact(names, t.cite(found - 1, found, last))
    out["templaters"] = templaters

    pyo3 = {}
    for name in TEMPLATER_NAMES + ("python_shared",):
        path = f"src/templaters/{name}.rs"
        if path not in contents["sqruff-lib"]:
            continue
        s = src("sqruff-lib", path)
        uses = [no for no, _ in s.matches(r"^use pyo3\b")]
        cfgs = [no for no, _ in s.matches(r'^#\[cfg\(feature = "python"\)\]$')]
        pyo3[name] = fact(
            {"pyo3_use_lines": len(uses), "python_feature_lines": len(cfgs)},
            s.cite(*(uses[:3] or [1])),
        )
    out["templater_pyo3"] = pyo3

    s = src("sqruff-lib", "src/templaters/types.rs")
    first, last = s.block(r"^impl PlaceholderStyle \{$", r"^\}$")
    names = {
        m[1]: (no, m[2])
        for no, m in s.matches(r'Self::(\w+) => "([a-z_]+)",$', first, last)
    }
    patterns = {
        m[1]: (no, m[3])
        for no, m in s.matches(r'Self::(\w+) => r(#?)"(.*)"\2,$', first, last)
    }
    if not names or set(names) != set(patterns):
        raise DataError("src/templaters/types.rs: the style names and regexes differ")
    out["placeholder_styles"] = fact(
        {names[v][1]: patterns[v][1] for v in names},
        s.cite(*[n for n, _ in names.values()], *[n for n, _ in patterns.values()]),
    )

    c = src("sqruff-lib", "src/core/config.rs")
    first, last = c.block(r"let filename_options = \[$", r"^\s*\];$")
    files = [(no, m[1]) for no, m in c.matches(r'^\s*"([^"]+)",\s*$', first, last)]
    comment = c.matches(r"^\s*/\*(.*)\*/", first, last)
    out["config_files"] = fact(
        {
            "read": [f for _, f in files],
            "commented_out": [
                f for _, m in comment for f in re.findall(r'"([^"]+)"', m[1])
            ],
        },
        c.cite(first, *[n for n, _ in files], *[n for n, _ in comment], last),
    )
    no = c.find(r'section == "sqlfluff" \|\| section == "sqruff"')
    no2 = c.find(r'strip_prefix\("sqlfluff:"\)', no)
    no3 = c.find(r'strip_prefix\("sqruff:"\)', no2)
    out["config_roots_ini"] = fact(
        re.findall(r'section == "(\w+)"', c.lines[no - 1]), c.cite(no, no2, no3)
    )
    tool = c.find(r'root\.get\("tool"\)')
    loop = c.find(r"for config_root in \[", tool)
    out["config_roots_toml"] = fact(
        [f"tool.{r}" for r in re.findall(r'"(\w+)"', c.lines[loop - 1])],
        c.cite(tool, loop),
    )
    no = c.find(r'starts_with\("-- sqlfluff:"\)')
    out["inline_prefixes"] = fact(
        re.findall(r'starts_with\("([^"]+)"\)', c.lines[no - 1]), c.cite(no)
    )

    ig = src("sqruff-lib", "src/ignore.rs")
    no = ig.find(r'^const IGNORE_FILE_NAME: &str = "')
    d = src("sqruff-lib", "src/core/linter/discovery.rs")
    no2 = d.find(r'String::from\("\.\w+ignore"\)')
    no3 = d.find(r"^const CONFIG_IGNORE_FILE_NAMES: ")
    out["ignore_files"] = fact(
        {
            "ignore_files": sorted(
                {
                    re.search(r'"(.+)"', ig.lines[no - 1])[1],
                    re.search(r'String::from\("(.+)"\)', d.lines[no2 - 1])[1],
                }
            ),
            "config_files_with_ignore_paths": re.findall(
                r'"([^"]+)"', d.lines[no3 - 1]
            ),
        },
        ig.cite(no),
        d.cite(no2, no3),
    )

    cfg = src("sqruff-lib", "src/core/default_config.cfg")
    out["default_config_keys"] = fact(
        ini_keys("\n".join(cfg.lines), "sqruff"), cfg.cite(1, len(cfg.lines))
    )

    syn = src("sqruff-lib-core", "src/dialects/syntax.rs")
    first, last = syn.block(r"^pub enum SyntaxKind \{$", r"^\}$")
    variants = syn.matches(r"^\s+([A-Z]\w*),$", first, last)
    out["syntax_kinds"] = fact(len(variants), syn.cite(first, last))
    seg = src("sqruff-lib-core", "src/parser/segments.rs")
    no = seg.find(r"pub fn get_type\(&self\) -> SyntaxKind")
    out["segment_type"] = fact("SyntaxKind", seg.cite(no))

    core = src("sqruff-lib", "src/core/linter/core.rs")
    p1 = core.find(r"^\s+pub fn parse_string\($")
    p2 = core.find(r"\) -> Result<ParsedString, SQLFluffUserError>", p1)
    l1 = core.find(r"^\s+pub fn lint_parsed\($")
    l2 = core.find(r"parsed_string: ParsedString,", l1)
    l3 = core.find(r"^\s+pub fn lint_string\($")
    l4 = core.find(r"parse_string_with_config\(", l3)
    l5 = core.find(r"linter\.lint_parsed\(", l4)
    com = src("sqruff-lib", "src/core/linter/common.rs")
    c1 = com.find(r"^pub struct ParsedString \{$")
    c2 = com.find(r"pub tree: Option<ErasedSegment>,", c1)
    c3 = com.find(r"pub alternate_variants: Vec<ParsedVariant>,", c1)
    out["parse_api"] = fact(
        {
            "parse": "Linter::parse_string -> ParsedString",
            "lint": "Linter::lint_parsed(ParsedString)",
            "tree": "ParsedString.tree: Option<ErasedSegment>",
            "variants": "ParsedString.alternate_variants",
        },
        core.cite(p1, p2, l1, l2, l3, l4, l5),
        com.cite(c1, c2, c3),
    )
    tf = src("sqruff-lib-core", "src/templaters.rs")
    out["templated_file"] = fact(
        "TemplatedFile", tf.cite(tf.find(r"^pub struct TemplatedFile\b"))
    )

    toml = src("sqruff", "Cargo.toml")
    first, last = toml.block(r"^python = \[$", r"^\]$")
    default = toml.find(r"^default = ")
    out["python_feature"] = fact(
        {
            "python": re.findall(r'"([^"]+)"', " ".join(toml.lines[first - 1 : last])),
            "default": re.findall(r'"([^"]+)"', toml.lines[default - 1]),
        },
        toml.cite(default, *range(first, last + 1)),
    )

    hits, scanned = [], 0
    for crate in ls.SQRUFF_CRATES:
        for path, data in sorted(contents[crate].items()):
            if not path.endswith(".rs"):
                continue
            scanned += 1
            if SCHEMA_SEARCH.search(data.decode("utf8", "replace")):
                hits.append(f"{crate}/{path}")
    out["schema_search"] = {
        "pattern": SCHEMA_SEARCH.pattern,
        "flags": "IGNORECASE",
        "files": f"the .rs files of the {len(ls.SQRUFF_CRATES)} sqruff crates",
        "scanned": scanned,
        "hits": hits,
    }
    return out


def collect(scratch: Path) -> dict:
    scratch = scratch.absolute()
    if scratch.exists():
        raise DataError(f"{scratch} exists; use a new folder")
    scratch.mkdir(parents=True)
    rec = Recorder(scratch)
    started = now()
    rec.st.run(
        "check the submodule before",
        [ROOT / "scripts" / "check-submodule", "before the T8 collect"],
        ROOT,
    )
    head = rec.st.run("sqll commit", ["git", "rev-parse", "HEAD"], ROOT).stdout.strip()
    sqlfluff = tools_dir() / "sqlfluff" / "bin" / "sqlfluff"
    python = tools_dir() / "sqlfluff" / "bin" / "python"
    sqruff = tools_dir() / "sqruff" / "bin" / "sqruff"
    for binary in (sqlfluff, sqruff):
        if not binary.exists():
            raise DataError(f"{binary} does not exist; run scripts/setup")
    rec.run("sqlfluff --version", [sqlfluff, "--version"], HELP_ENV)
    rec.run("sqruff --version", [sqruff, "--version"], HELP_ENV)
    for tool, binary in (("sqlfluff", sqlfluff), ("sqruff", sqruff)):
        top = rec.run(f"{tool} --help", [binary, "--help"], HELP_ENV)
        for cid, args in help_ids(tool, command_names(top))[1:]:
            if args[0] == "help":
                continue
            rec.run(cid, [binary, *args], HELP_ENV)
    rec.run("sqruff templaters", [sqruff, "templaters"], HELP_ENV)
    py = json.loads(rec.run("sqlfluff facts", [python, "-I", "-c", PY_FACTS]))
    if py["sqlfluff_version"] != SQLFLUFF_VERSION:
        raise DataError(f"the sqlfluff tool is {py['sqlfluff_version']}")
    rec.outputs["sqlfluff facts"]["argv"][3] = "PY_FACTS (scripts/s3/capabilities.py)"
    contents, meta = crate_sources(ls.cargo_cache())
    facts = sqruff_facts(contents, meta)
    rec.st.run(
        "check the submodule after",
        [ROOT / "scripts" / "check-submodule", "after the T8 collect"],
        ROOT,
    )
    return {
        "kind": "sqll-s3-capabilities-sources",
        "task": "T8",
        "command": COMMANDS["collect"],
        "started": started,
        "finished": now(),
        "sqll_commit": head,
        "sqlfluff_ref": sqlfluff_ref(SQLFLUFF_ROOT),
        "tools": "$TOOLS is the tools folder of scripts/setup (SQLL_TOOLS_DIR)",
        "help_env": HELP_ENV,
        "help_unset": list(HELP_UNSET),
        "commands": rec.outputs,
        "steps": rec.st.entries,
        "sqlfluff": {k: v for k, v in py.items() if k != "sqlfluff_file"},
        "sqruff": {
            "version": SQRUFF_VERSION,
            "crates": {n: {"sha256": meta[n]} for n in ls.SQRUFF_CRATES},
            "facts": facts,
        },
    }


# time: the start session in the CI image.

START_POLICY = {"min_runs": 20, "max_runs": 20, "budget_s": 0.0, "timeout_s": 120.0}
START_SERIES = {
    "python": "the Python of the sqlfluff venv: -c pass",
    "import_cli": "the Python of the sqlfluff venv: -c 'import sqlfluff.cli.commands'",
    "sqruff_version": "sqruff --version",
}


def time_inside(scratch: Path) -> dict:
    """The session, in the CI image: the start benchmarks of sqlfluff and
    sqruff (the harness, the full profile), then the 3 series of
    START_SERIES in turn."""
    from sqll_harness.adapters.base import EmptyHome, isolated_env
    from sqll_harness.adapters.sqruff import sqruff_env
    from sqll_harness.bench import definitions as bench_definitions
    from sqll_harness.bench import run as bench_run
    from sqll_harness.bench import timer
    from sqll_harness.bench.tools import SqlfluffBench, SqruffBench

    errors = bench_run.check_tools(["sqlfluff", "sqruff"])
    if errors:
        raise DataError("; ".join(errors))
    defs = bench_definitions.load()
    scope, benchmarks = bench_run.plan(
        defs, tools=["sqlfluff", "sqruff"], profile="full", commands=["start"]
    )
    report = bench_run.run(
        defs=defs,
        adapters=[SqlfluffBench(), SqruffBench()],
        profile="full",
        scope=scope,
        benchmarks=benchmarks,
        sqlfluff_root=SQLFLUFF_ROOT,
        work=scratch / "bench-work",
        progress=bench_run.progress_to_stderr,
    )
    python = str(tools_dir() / "sqlfluff" / "bin" / "python")
    sqruff = str(tools_dir() / "sqruff" / "bin" / "sqruff")
    jobs = {
        "python": timer.Job([python, "-c", "pass"], env=isolated_env(EmptyHome.path())),
        "import_cli": timer.Job(
            [python, "-c", "import sqlfluff.cli.commands"],
            env=isolated_env(EmptyHome.path()),
        ),
        "sqruff_version": timer.Job([sqruff, "--version"], env=sqruff_env()),
    }
    policy = timer.Policy(**START_POLICY)
    series = [
        timer.Series(job, policy, scratch / "series" / name)
        for name, job in jobs.items()
    ]
    measured = timer.run_in_turn(series)
    extra = {}
    for (name, job), m in zip(jobs.items(), measured, strict=True):
        if m.status != timer.VALID:
            raise DataError(f"{name}: {m.status}: {m.reason}")
        extra[name] = {
            "argv": [a.replace(str(tools_dir()), TOOLS) for a in job.argv],
            "what": START_SERIES[name],
            "samples": [s.as_dict() for s in m.samples],
            "stats": m.stats,
        }
    return {"report": report, "series": extra}


def compact_report(report: dict) -> dict:
    keep = ("kind", "format", "sqlfluff_ref", "harness", "profile", "policy")
    keep += ("machine", "timer", "tools")
    return {
        **{k: report[k] for k in keep if k in report},
        "results": [
            {
                "id": r["id"],
                "tool": r["tool"],
                "dialect": r["dialect"],
                "status": r["status"],
                "reason": r["reason"],
                "runs": r["runs"],
                "wall_s": [s["wall_s"] for s in r["samples"] if s["kind"] == "timed"],
                "stats": r.get("stats"),
            }
            for r in report["results"]
        ],
    }


def time_session(scratch: Path, image: str | None) -> dict:
    scratch = scratch.absolute()
    if scratch.exists():
        raise DataError(f"{scratch} exists; use a new folder")
    scratch.mkdir(parents=True)
    image = image or probe.ci_image()
    st = probe.Steps(scratch)
    image_id = st.run(
        "CI image id",
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        ROOT,
    ).stdout.strip()
    docker_version = st.run(
        "docker version", ["docker", "version", "--format", "{{.Server.Version}}"], ROOT
    ).stdout.strip()
    load_before, waited = probe.wait_idle()
    started = now()
    st.run(
        "timing session",
        ["docker", "run", "--rm", "--network", "none"]
        + ["-v", f"{ROOT}:/repo:ro", "-v", f"{scratch}:/scratch"]
        + ["-e", "PYTHONPATH=/repo/harness", "-w", "/repo", image]
        + ["/opt/sqll/harness-venv/bin/python", "scripts/s3/capabilities.py"]
        + ["time-inside", "--scratch", "/scratch"],
        ROOT,
        log=scratch / "logs" / "timing.log",
        timeout=3600,
    )
    load_after = probe.read_load()
    if load_after[1] > MAX_SESSION_LOAD:
        raise DataError(
            f"the 5-minute load average after the session is {load_after[1]}: "
            "other processes ran during the serial session"
        )
    inside = json.loads((scratch / "start-session.json").read_text("utf8"))
    readelf = st.run(
        "readelf of sqruff in the CI image",
        ["docker", "run", "--rm", "--network", "none", image]
        + ["readelf", "-d", "/opt/sqll/tools/sqruff/bin/sqruff"],
        ROOT,
        check=False,
    )
    return {
        "kind": "sqll-s3-capabilities-start",
        "task": "T8",
        "command": COMMANDS["time"],
        "started": started,
        "finished": now(),
        "session": {
            "image": image,
            "image_id": image_id,
            "docker": docker_version,
            "method": "harness/bench.md: the CI image in docker, one container, "
            "serial, no network, no other load. The start benchmarks: the harness, "
            "the full profile, the tools in turn. Then the 3 series of the T8 "
            "script in turn, with a policy of 20 timed runs",
            "policy": START_POLICY,
            "machine_lock": "the command ran under flock /tmp/sqll-machine.lock "
            "(PROCESS.md, rule 7)",
            "load": {"before": load_before, "after": load_after, "idle_wait_s": waited},
        },
        "steps": st.entries,
        "readelf_needed": probe.needed_libraries(readelf.stdout)
        if readelf.returncode == 0
        else None,
        "report": compact_report(inside["report"]),
        "series": inside["series"],
    }


# report


def tracked(prefix: str) -> list[str]:
    return sorted(p for p in probe.tracked_files(SQLFLUFF_ROOT) if p.startswith(prefix))


def check_sources(sources: dict, t7: dict, t7_sources: dict) -> None:
    if sources["sqlfluff_ref"] != sqlfluff_ref(SQLFLUFF_ROOT):
        raise DataError("the sources are not of the pinned sqlfluff")
    if sources["sqlfluff"]["sqlfluff_version"] != SQLFLUFF_VERSION:
        raise DataError("the sqlfluff facts are not of sqlfluff 4.4.0")
    cmds = sources["commands"]
    if (
        cmds["sqlfluff --version"]["stdout"].strip()
        != f"sqlfluff, version {SQLFLUFF_VERSION}"
    ):
        raise DataError("the sqlfluff help is not of sqlfluff 4.4.0")
    if cmds["sqruff --version"]["stdout"].strip() != f"sqruff {SQRUFF_VERSION}":
        raise DataError("the sqruff help is not of sqruff 0.41.0")
    for cid, entry in cmds.items():
        if entry["exit_code"] != 0:
            raise DataError(f"{cid}: exit code {entry['exit_code']}")
    t7_crates = t7_sources["sqruff"]["crates"]
    for name, crate in sources["sqruff"]["crates"].items():
        if t7_crates.get(name, {}).get("sha256") != crate["sha256"]:
            raise DataError(f"{name}: the crate is not the crate of T7")
    for f in walk_facts(sources["sqruff"]["facts"]):
        for ev in f["evidence"]:
            src = ev["source"]
            if (
                src["crate_sha256"]
                != sources["sqruff"]["crates"][src["crate"]]["sha256"]
            ):
                raise DataError(f"{src['file']}: not a file of the recorded crate")
    kinds = re.search(
        r"SyntaxKind enum \((\d+) variants", t7["bases"]["sqruff"]["structure"]["rules"]
    )
    if (
        not kinds
        or int(kinds[1]) != sources["sqruff"]["facts"]["syntax_kinds"]["value"]
    ):
        raise DataError("the SyntaxKind count is not the count of T7")


def walk_facts(node):
    if isinstance(node, dict):
        if "value" in node and "evidence" in node:
            yield node
        else:
            for v in node.values():
                yield from walk_facts(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_facts(v)


def help_options(sources: dict) -> dict:
    """The parsed help of each tool: {tool: {command: {"args", "options"}}}."""
    out = {}
    cmds = sources["commands"]
    for tool, parse in (("sqlfluff", click_options), ("sqruff", clap_options)):
        names = command_names(cmds[f"{tool} --help"]["stdout"])
        out[tool] = {"commands": names, "by_command": {}}
        for name in names:
            cid = f"{tool} {name} --help"
            if cid not in cmds:
                continue
            text = cmds[cid]["stdout"]
            out[tool]["by_command"][name] = {
                "args": usage_args(text),
                "options": parse(text),
            }
    return out


def check_click(parsed: dict, py: dict) -> None:
    """The sqlfluff help parse must give the options of the click objects."""
    if sorted(parsed["by_command"]) != sorted(py["commands"]):
        raise DataError("the sqlfluff help commands are not the click commands")
    for name, cmd in py["commands"].items():
        want = {}
        for p in cmd["params"]:
            if p["kind"] == "option" and not p["hidden"]:
                want[tuple(sorted(p["names"]))] = p["choices"]
        got = {
            tuple(sorted(o["names"])): o["choices"]
            for o in parsed["by_command"][name]["options"]
        }
        if got != want:
            raise DataError(f"sqlfluff {name}: the help parse is not the click options")


def cli_test_mentions(names: set[str]) -> dict[str, int]:
    """For each option name: the string literals in the sqlfluff CLI tests
    (test/cli/*.py) that are the name or start with "<name>=". A proxy of
    the use of the option in the S7 tests."""
    counts = dict.fromkeys(sorted(names), 0)
    for path in sorted((SQLFLUFF_ROOT / "test" / "cli").glob("*.py")):
        tokens = tokenize.generate_tokens(io.StringIO(path.read_text("utf8")).readline)
        for tok in tokens:
            if tok.type != tokenize.STRING:
                continue
            try:
                value = ast.literal_eval(tok.string)
            except (ValueError, SyntaxError):
                continue
            if not isinstance(value, str):
                continue
            name = value.split("=", 1)[0]
            if name in counts:
                counts[name] += 1
    return counts


def compare_options(sqlfluff_opts: list[dict], sqruff_opts: list[dict]) -> dict:
    a, b = option_index(sqlfluff_opts), option_index(sqruff_opts)
    both = sorted(set(a) & set(b))
    choices = {}
    for name in both:
        ca, cb = a[name]["choices"], b[name]["choices"]
        if ca is not None or cb is not None:
            ca, cb = set(ca or ()), set(cb or ())
            choices[name] = {
                "both": sorted(ca & cb),
                "only_sqlfluff": sorted(ca - cb),
                "only_sqruff": sorted(cb - ca),
            }

    # A short name belongs to the first long name of its option, not to a
    # secondary flag ("-n, --nocolor / --color") or an alias.
    def short(opt, name):
        return opt["short"] if opt["long"] == name else None

    shorts = {}
    for name in both:
        sa, sb = short(a[name], name), short(b[name], name)
        if sa != sb:
            shorts[name] = {"sqlfluff": sa, "sqruff": sb}
    return {
        "sqlfluff": len(a),
        "sqruff": len(b),
        "both": both,
        "only_sqlfluff": sorted(set(a) - set(b)),
        "only_sqruff": sorted(set(b) - set(a)),
        "choices": choices,
        "short_names_that_differ": shorts,
    }


def unsupported_settings() -> dict:
    """The settings of the sqruff known failures with the reason
    "unsupported: setting" (the S1 data of T2), with the case count of each."""
    by_setting: dict[str, int] = {}
    by_suite: dict[str, int] = {}
    cases = 0
    for line in KNOWN_FAILURES.read_text("utf8").splitlines():
        m = re.match(r"^(\S+)\s+# unsupported: setting (.+)$", line)
        if not m:
            continue
        cases += 1
        suite = m[1].split("/", 1)[0]
        by_suite[suite] = by_suite.get(suite, 0) + 1
        for name in {x.strip() for x in m[2].split(",")}:
            by_setting[name] = by_setting.get(name, 0) + 1
    return {"cases": cases, "by_suite": by_suite, "by_setting": by_setting}


def setting_group(name: str) -> str:
    parts = name.split(".")
    if parts[:2] == ["layout", "type"] and len(parts) == 4:
        return f"layout.type.*.{parts[3]}"
    if parts[0] == "templater" and len(parts) > 3 and parts[2] in ("macros", "context"):
        return ".".join(parts[:3]) + ".*"
    return name


def sorted_counts(counts: dict[str, int]) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def sqlfluff_sources() -> dict:
    """The facts of the sqlfluff 4.4.0 sources (the submodule)."""
    out = {}
    s = submodule_source("src/sqlfluff/core/templaters/__init__.py")
    first, last = s.block(r"^def core_templaters\(", r"^\s+\]$")
    classes = [(no, m[1]) for no, m in s.matches(r"^\s+(\w+Templater),$", first, last)]
    out["core_templaters"] = (classes, s)
    names = {}
    for path in (
        "src/sqlfluff/core/templaters/base.py",
        "src/sqlfluff/core/templaters/jinja.py",
        "src/sqlfluff/core/templaters/python.py",
        "src/sqlfluff/core/templaters/placeholder.py",
        "plugins/sqlfluff-templater-dbt/sqlfluff_templater_dbt/templater.py",
        "plugins/sqlfluff-templater-sqlmesh/sqlfluff_templater_sqlmesh/templater.py",
    ):
        src = submodule_source(path)
        no = src.find(r'^    name = "(\w+)"$')
        names[re.search(r'"(\w+)"', src.lines[no - 1])[1]] = src.cite(no)
    out["templater_names"] = names
    p = submodule_source("src/sqlfluff/core/templaters/placeholder.py")
    first, last = p.block(r"^KNOWN_STYLES = \{$", r"^\}$")
    styles = [
        (no, m[1]) for no, m in p.matches(r'^\s+"(\w+)": regex\.compile\(', first, last)
    ]
    out["placeholder_styles"] = (styles, p, first, last)
    loader = submodule_source("src/sqlfluff/core/config/loader.py")
    first, last = loader.block(r"^\s+filename_options = \[$", r"^\s+\]$")
    files = [(no, m[1]) for no, m in loader.matches(r'^\s+"([^"]+)",$', first, last)]
    out["config_files"] = fact(
        [f for _, f in files], loader.cite(first, *[n for n, _ in files], last)
    )
    ini = submodule_source("src/sqlfluff/core/config/ini.py")
    i1 = ini.find(r'if k == "sqlfluff":')
    i2 = ini.find(r'elif k\.startswith\("sqlfluff:"\):', i1)
    toml = submodule_source("src/sqlfluff/core/config/toml.py")
    t1 = toml.find(r'toml_dict\.get\("tool", \{\}\)\.get\("sqlfluff", \{\}\)')
    out["config_roots"] = fact(
        {"ini": ["sqlfluff"], "toml": ["tool.sqlfluff"]},
        ini.cite(i1, i2),
        toml.cite(t1),
    )
    fc = submodule_source("src/sqlfluff/core/config/fluffconfig.py")
    no = fc.find(r'raw_line\.startswith\(\("-- sqlfluff", "--sqlfluff"\)\)')
    out["inline_prefixes"] = fact(
        re.findall(r'"([^"]+)"', fc.lines[no - 1]), fc.cite(no)
    )
    disc = submodule_source("src/sqlfluff/core/linter/discovery.py")
    first, last = disc.block(r"^ignore_file_loaders: ", r"^\}$")
    keys = [
        (no, m[1])
        for no, m in disc.matches(r'^\s+"([^"]+)": _load_(\w+),$', first, last)
    ]
    out["ignore_files"] = fact(
        {
            "ignore_files": [k for _, k in keys if k.endswith("ignore")],
            "config_files_with_ignore_paths": [
                k for _, k in keys if not k.endswith("ignore")
            ],
        },
        disc.cite(first, *[n for n, _ in keys]),
    )
    return out


def sqlfluffrs_sources() -> dict:
    """The facts of the sqlfluffrs 4.4.0 sources (the submodule)."""
    out = {}
    ws = "sqlfluffrs/"
    files = tracked(ws)
    manifests = [f for f in files if f.endswith("Cargo.toml")]
    bins = []
    for m in manifests:
        text = (SQLFLUFF_ROOT / m).read_text("utf8")
        if "[[bin]]" in text:
            bins.append(m)
    mains = [
        f for f in files if f.endswith("/src/main.rs") or f.startswith(f"{ws}src/bin/")
    ]
    out["binaries"] = {
        "search": "the tracked Cargo.toml files of sqlfluffrs/ with [[bin]], and "
        "the tracked src/main.rs and src/bin/ files",
        "manifests": manifests,
        "bin_targets": bins,
        "main_files": mains,
    }
    out["templater_files"] = [f for f in files if "templat" in f and f.endswith(".rs")]
    tf = submodule_source(f"{ws}sqlfluffrs_types/src/templater/templatefile.rs")
    fs = submodule_source(f"{ws}sqlfluffrs_types/src/templater/fileslice.rs")
    mod = submodule_source(f"{ws}sqlfluffrs_types/src/templater/mod.rs")
    out["templated_file"] = fact(
        "TemplatedFile, RawFileSlice, TemplatedFileSlice",
        mod.cite(*range(1, len(mod.lines) + 1)),
        tf.cite(tf.find(r"^pub struct TemplatedFile \{")),
        fs.cite(
            fs.find(r"^pub struct RawFileSlice \{"),
            fs.find(r"^pub struct TemplatedFileSlice \{"),
        ),
    )
    lx = submodule_source(f"{ws}sqlfluffrs_lexer/src/lexer.rs")
    first, last = lx.block(r"^pub enum LexInput \{$", r"^\}$")
    variants = [m[1] for _, m in lx.matches(r"^\s+(\w+)\(", first, last)]
    out["lex_input"] = fact(variants, lx.cite(*range(first, last + 1)))
    ty = submodule_source(f"{ws}sqlfluffrs_parser/src/parser/types.rs")
    n1 = ty.find(r"^pub enum Node \{$")
    n2 = ty.find(r"segment_type: Cow<'static, str>,", n1)
    out["node_type"] = fact("Node.segment_type: Cow<'static, str>", ty.cite(n1, n2))
    pc = submodule_source(f"{ws}sqlfluffrs_parser/src/parser/core.rs")
    r1 = pc.find(r"pub fn root_parse\(")
    out["parse_api"] = fact("Parser::root_parse", pc.cite(r1))
    fc = submodule_source(f"{ws}sqlfluffrs_types/src/config/fluffconfig.rs")
    first, last = fc.block(r"^pub struct FluffConfig \{$", r"^\}$")
    fields = [(no, m[1]) for no, m in fc.matches(r"^\s+pub (\w+):", first, last)]
    out["config"] = fact(
        [f for _, f in fields], fc.cite(first, *[n for n, _ in fields], last)
    )
    hits, scanned = [], 0
    for f in files:
        if f.endswith(".rs"):
            scanned += 1
            if SCHEMA_SEARCH.search((SQLFLUFF_ROOT / f).read_text("utf8", "replace")):
                hits.append(f)
    out["schema_search"] = {
        "pattern": SCHEMA_SEARCH.pattern,
        "flags": "IGNORECASE",
        "files": "the tracked .rs files of sqlfluffrs/",
        "scanned": scanned,
        "hits": hits,
    }
    return out


def same_regex_text(pattern: str) -> str:
    """The sqlfluff regex text as sqruff writes it: '\\x5c' is '\\\\' and
    '\\"' is '"' (each pair means the same)."""
    return pattern.replace(r"\x5c", "\\\\").replace('\\"', '"')


def s6_section(sources: dict, sq: dict, sf: dict, rs: dict, t2: dict) -> dict:
    py = sources["sqlfluff"]
    facts = sources["sqruff"]["facts"]
    templaters_cmd = sources["commands"]["sqruff templaters"]["stdout"].split()
    with_py = facts["templaters"]["python"]["value"]
    without_py = facts["templaters"]["no_python"]["value"]
    if templaters_cmd != with_py:
        raise DataError(
            "'sqruff templaters' is not the TEMPLATERS list of the python feature"
        )
    classes, init_src = sf["core_templaters"]
    if len(classes) != len(py["core_templaters"]):
        raise DataError("the core templaters of the source and of the tool differ")
    names = sf["templater_names"]
    if set(py["core_templaters"]) - set(names):
        raise DataError("a core templater with no name line")
    s6_text = document(
        "STONES.md",
        "Support the Jinja, placeholder, and Python format-string templaters.",
    )
    g13_text = document(
        "CONSTITUTION.md",
        "Exclusions: Python plugins, and features that need a Python runtime. "
        "An example is the dbt templater.",
    )
    s6_names = {"jinja", "placeholder", "python"}

    rows = []
    for name in TEMPLATER_NAMES:
        if name in py["core_templaters"]:
            sqlfluff_kind = fact(
                "core",
                command("sqlfluff facts"),
                init_src.cite(*[n for n, _ in classes]),
                names[name],
            )
        elif name in names:
            sqlfluff_kind = fact(f"plugin (sqlfluff-templater-{name})", names[name])
        else:
            sqlfluff_kind = fact(
                "none",
                command("sqlfluff facts"),
                {
                    "search": "the plugin folders of the submodule (plugins/)",
                    "hits": sorted({f.split("/")[1] for f in tracked("plugins/")}),
                },
            )
        if name in s6_names:
            scope = fact("S6", s6_text)
        elif name == "raw":
            scope = estimate(
                "S6 (no templating; the base class of the other sqlfluff templaters)",
                "S6 does not name raw. It is the templater with no templating, and in "
                "sqlfluff the other templaters are subclasses of it, so a sqll "
                "templater set needs it.",
                names[name],
                document(
                    "third_party/sqlfluff/src/sqlfluff/core/templaters/placeholder.py",
                    "class PlaceholderTemplater(RawTemplater):",
                ),
            )
        elif name == "dbt":
            scope = fact("excluded (G1.3: needs a Python runtime)", g13_text)
        elif name in names:
            scope = estimate(
                "excluded (G1.3: needs a Python runtime)",
                "The plugin runs sqlmesh, a Python tool, as the dbt plugin runs dbt.",
                g13_text,
                names[name],
            )
        else:
            raise DataError(f"the templater {name} is not in sqlfluff 4.4.0")
        sq_present = name in with_py
        pyo3 = facts["templater_pyo3"].get(name)
        if sq_present:
            native = name in without_py
            sqruff = fact(
                {
                    "exists": True,
                    "native": native,
                    "needs_python_runtime": not native,
                    "pyo3_use_lines": pyo3["value"]["pyo3_use_lines"],
                },
                command("sqruff templaters"),
                *facts["templaters"]["python"]["evidence"],
                *facts["templaters"]["no_python"]["evidence"],
                *pyo3["evidence"],
            )
        else:
            sqruff = fact(
                {"exists": False, "native": False, "needs_python_runtime": False},
                command("sqruff templaters"),
            )
        sqlfluffrs = estimate(
            {"exists": False, "native": False, "needs_python_runtime": False},
            "The only templater files of sqlfluffrs hold the source map types "
            "(TemplatedFile and the slices). sqlfluff[rs] renders each template in "
            "Python sqlfluff.",
            {
                "search": "the tracked .rs files of sqlfluffrs/ with 'templat' in the path",
                "hits": rs["templater_files"],
            },
            *rs["templated_file"]["evidence"],
        )
        new = estimate(
            {"exists": False, "native": False, "needs_python_runtime": False},
            "Option 3 is a parser only. Its templaters are new work, as for option 2.",
            {"result": rel(T2_FILE), "key": "bases.new-parser.note"},
        )
        rows.append(
            {
                "templater": name,
                "scope": scope,
                "sqlfluff_4_4_0": sqlfluff_kind,
                "sqruff": sqruff,
                "sqlfluffrs": sqlfluffrs,
                "new-parser": new,
            }
        )

    styles, psrc, pfirst, plast = sf["placeholder_styles"]
    if [n for _, n in styles] != list(py["placeholder_styles"]):
        raise DataError("the placeholder styles of the source and of the tool differ")
    sq_styles = facts["placeholder_styles"]["value"]
    style_rows = []
    for no, name in styles:
        pattern = py["placeholder_styles"][name]
        sq = sq_styles.get(name)
        same = sq is not None and sq == same_regex_text(pattern)
        style_rows.append(
            {
                "style": name,
                "sqlfluff_pattern": fact(
                    pattern, command("sqlfluff facts"), psrc.cite(no)
                ),
                "sqruff": fact(
                    {"exists": sq is not None, "same_pattern": same},
                    *facts["placeholder_styles"]["evidence"],
                ),
            }
        )
    extra = sorted(set(sq_styles) - set(py["placeholder_styles"]))

    tpl = t2["bases"]
    suite = {}
    for base in ("sqruff", "sqlfluffrs"):
        s = tpl[base]["suites"]["templater"]
        suite[base] = fact(
            {
                "cases": s["total"],
                "pass": s["pass"],
                "needs_python": s["needs_python"]["total"],
                "needs_python_pass": s["needs_python"]["pass"],
                "no_python_cases": s["total"] - s["needs_python"]["total"],
                "no_python_pass": s["pass"] - s["needs_python"]["pass"],
                "groups": sorted(tpl[base]["templater"]),
            },
            result(T2_FILE, f"bases.{base}.suites.templater"),
            result(T2_FILE, f"bases.{base}.templater"),
        )
    if any(not g.startswith("jinja") for g in suite["sqruff"]["value"]["groups"]):
        raise DataError("a templater fixture group that is not jinja")
    suite_note = estimate(
        "All groups of the templater suite are Jinja. sqruff passes them with Jinja "
        "in Python (pyo3); sqlfluff-rs passes them with the Python templaters of "
        "sqlfluff. Thus the suite shows no native templater of a base.",
        "The pass counts are of the tools of S1, not of a standalone base.",
        result(T2_FILE, "bases.sqruff.templater"),
        result(T2_FILE, "bases.sqlfluffrs.note"),
    )

    source_map = {
        "sqruff": fact(
            "TemplatedFile (sqruff-lib-core)", *facts["templated_file"]["evidence"]
        ),
        "sqlfluffrs": fact(
            {
                "types": rs["templated_file"]["value"],
                "lexer_input": rs["lex_input"]["value"],
            },
            *rs["templated_file"]["evidence"],
            *rs["lex_input"]["evidence"],
        ),
        "new-parser": estimate(
            "none; can reuse the sqlfluffrs_types source map (MIT)",
            "Option 3 can take the sqlfluffrs source map types, as it takes the "
            "generator (T5).",
            *rs["templated_file"]["evidence"],
        ),
    }
    return {
        "templaters": rows,
        "placeholder_styles": {
            "rows": style_rows,
            "sqruff_only": fact(extra, *facts["placeholder_styles"]["evidence"]),
            "rule": "same_pattern: the sqruff regex text is the sqlfluff regex text "
            "after same_regex_text (scripts/s3/capabilities.py): '\\x5c' as '\\\\' "
            "and '\\\"' as '\"'",
        },
        "templater_suite": {**suite, "note": suite_note},
        "source_map": source_map,
    }


def s7_section(sources: dict, sq: dict, sf: dict, rs: dict, parsed: dict) -> dict:
    facts = sources["sqruff"]["facts"]
    py = sources["sqlfluff"]
    sf_cmds = parsed["sqlfluff"]["commands"]
    sq_cmds = [c for c in parsed["sqruff"]["commands"] if c != "help"]
    rows = []
    for name in sorted(set(sf_cmds) | set(sq_cmds)):
        rows.append(
            {
                "command": name,
                "sqlfluff": fact(name in sf_cmds, command("sqlfluff --help")),
                "sqruff": fact(name in sq_cmds, command("sqruff --help")),
            }
        )
    no_cli = {
        "sqlfluffrs": fact(
            {"cli": False, "bin_targets": rs["binaries"]["bin_targets"]},
            {"search": rs["binaries"]["search"], "hits": rs["binaries"]["main_files"]},
        ),
        "new-parser": estimate(
            {"cli": False},
            "Option 3 has no implementation (docs/decisions/s3-base.md).",
            {"result": rel(T2_FILE), "key": "bases.new-parser.note"},
        ),
    }
    mapping = estimate(
        {
            "version": "sqruff --version",
            "format": "none (sqruff fix with all rules is not the same)",
            "render": "none",
        },
        "A command of sqlfluff that sqruff does not have, and the nearest sqruff "
        "command. From the help text, not from a test.",
        command("sqlfluff --help"),
        command("sqruff --help"),
    )
    per_command = {}
    all_sf_names: set[str] = set()
    for name in sorted(set(sf_cmds) & set(sq_cmds)):
        a = parsed["sqlfluff"]["by_command"][name]
        b = parsed["sqruff"]["by_command"][name]
        cmp = compare_options(a["options"], b["options"])
        all_sf_names |= set(option_index(a["options"]))
        per_command[name] = fact(
            {**cmp, "args": {"sqlfluff": a["args"], "sqruff": b["args"]}},
            command(f"sqlfluff {name} --help"),
            command(f"sqruff {name} --help"),
            command("sqlfluff facts"),
        )
    for name in sf_cmds:
        all_sf_names |= set(
            option_index(parsed["sqlfluff"]["by_command"][name]["options"])
        )
    mentions = cli_test_mentions(all_sf_names)
    missing = sorted(
        {n for v in per_command.values() for n in v["value"]["only_sqlfluff"]}
    )
    only_cmds = [c for c in sf_cmds if c not in sq_cmds]
    test_use = estimate(
        {
            "only_sqlfluff_options": {n: mentions[n] for n in missing},
            "options_of_commands_that_sqruff_does_not_have": {
                c: {
                    n: mentions[n]
                    for n in sorted(
                        option_index(parsed["sqlfluff"]["by_command"][c]["options"])
                    )
                }
                for c in only_cmds
            },
        },
        "A count of string literals in test/cli/*.py that are the option name (or "
        "'<name>=...'). A literal is not a test, and a name can be of more than one "
        "command. It shows which missing options the S7 tests use.",
        submodule_source("test/cli/commands_test.py").cite(1),
    )

    sq_files = facts["config_files"]["value"]
    sf_files = sf["config_files"]["value"]
    config = {
        "files_in_each_folder": {
            "sqlfluff": sf["config_files"],
            "sqruff": facts["config_files"],
            "both": sorted(set(sf_files) & set(sq_files["read"])),
            "only_sqlfluff": sorted(set(sf_files) - set(sq_files["read"])),
            "only_sqruff": sorted(set(sq_files["read"]) - set(sf_files)),
        },
        "section_roots": {
            "sqlfluff": sf["config_roots"],
            "sqruff": fact(
                {
                    "ini": facts["config_roots_ini"]["value"],
                    "toml": facts["config_roots_toml"]["value"],
                },
                *facts["config_roots_ini"]["evidence"],
                *facts["config_roots_toml"]["evidence"],
            ),
        },
        "inline_prefixes": {
            "sqlfluff": sf["inline_prefixes"],
            "sqruff": facts["inline_prefixes"],
        },
        "ignore_files": {
            "sqlfluff": sf["ignore_files"],
            "sqruff": facts["ignore_files"],
        },
        "sqlfluffrs": estimate(
            {"fields": rs["config"]["value"], "reads_files": False},
            "The FluffConfig of sqlfluffrs has only these fields; Python sqlfluff "
            "reads the config files and gives the values to it.",
            *rs["config"]["evidence"],
        ),
        "new-parser": estimate(
            "none",
            "Option 3 has no implementation (docs/decisions/s3-base.md).",
            {"result": rel(T2_FILE), "key": "bases.new-parser.note"},
        ),
    }

    from sqll_harness.adapters import sqruff_config

    sf_keys = py["default_config_keys"]
    sq_keys = facts["default_config_keys"]["value"]
    harness_ok = [k for k in sf_keys if sqruff_config.is_supported(tuple(split_key(k)))]
    unsupported = unsupported_settings()
    groups: dict[str, int] = {}
    for name, n in unsupported["by_setting"].items():
        g = setting_group(name)
        groups[g] = groups.get(g, 0) + n
    t2_total = sum(
        load_json(T2_FILE)["bases"]["sqruff"]["failure_reasons"][
            "unsupported: setting"
        ].values()
    )
    if unsupported["cases"] != t2_total:
        raise DataError(
            f"{unsupported['cases']} cases with an unsupported setting, T2 has {t2_total}"
        )
    keys = {
        "sqlfluff_defaults": fact(len(sf_keys), command("sqlfluff facts")),
        "sqruff_defaults": fact(
            len(sq_keys), *facts["default_config_keys"]["evidence"]
        ),
        "in_both_defaults": fact(
            len(set(sf_keys) & set(sq_keys)),
            command("sqlfluff facts"),
            *facts["default_config_keys"]["evidence"],
        ),
        "only_sqlfluff_defaults": fact(
            sorted(set(sf_keys) - set(sq_keys)),
            command("sqlfluff facts"),
            *facts["default_config_keys"]["evidence"],
        ),
        "only_sqruff_defaults": fact(
            sorted(set(sq_keys) - set(sf_keys)),
            command("sqlfluff facts"),
            *facts["default_config_keys"]["evidence"],
        ),
        "harness_supported": fact(
            {
                "of_sqlfluff_defaults": len(harness_ok),
                "not_supported": sorted(set(sf_keys) - set(harness_ok)),
            },
            command("sqlfluff facts"),
            document(
                "harness/sqll_harness/adapters/sqruff_config.py", "def is_supported("
            ),
        ),
        "s1_unsupported_settings": fact(
            {
                "cases": unsupported["cases"],
                "by_suite": dict(sorted(unsupported["by_suite"].items())),
                "by_group": sorted_counts(groups),
                "by_setting": sorted_counts(unsupported["by_setting"]),
            },
            {
                "result": rel(KNOWN_FAILURES),
                "key": "lines with '# unsupported: setting'",
            },
            result(T2_FILE, "bases.sqruff.failure_reasons.unsupported: setting"),
        ),
    }
    return {
        "commands": rows,
        "no_cli": no_cli,
        "command_mapping": mapping,
        "options": per_command,
        "options_in_cli_tests": test_use,
        "config": config,
        "config_keys": keys,
    }


def split_key(key: str) -> list[str]:
    """A dotted default key as the path of sqruff_config: the rule names
    have a "." ("capitalisation.keywords")."""
    parts = key.split(".")
    if parts[0] == "rules" and len(parts) > 2:
        return ["rules", ".".join(parts[1:-1]), parts[-1]]
    return parts


def load_json(path: Path) -> dict:
    return json.loads(path.read_text("utf8"))


def g2_section(sources: dict, rs: dict, t5: dict, t7: dict) -> dict:
    facts = sources["sqruff"]["facts"]
    style_counts = {
        "sqruff": fact(
            len(facts["placeholder_styles"]["value"]),
            *facts["placeholder_styles"]["evidence"],
        ),
    }
    return {
        "typed_tree": {
            "sqruff": fact(
                {
                    "segment_type": "SyntaxKind enum",
                    "syntax_kinds": facts["syntax_kinds"]["value"],
                },
                *facts["syntax_kinds"]["evidence"],
                *facts["segment_type"]["evidence"],
            ),
            "sqlfluffrs": fact(
                {"segment_type": "string"},
                *rs["node_type"]["evidence"],
            ),
            "new-parser": estimate(
                "a type enum can come from the generator",
                "The generator reads the segment classes of each dialect (T5), so it "
                "can write a type enum. Not tried.",
                result(T5_FILE, "generator"),
            ),
            "typed_node_view": estimate(
                {"sqruff": False, "sqlfluffrs": False, "new-parser": False},
                "No base has a typed view of each node kind (for example a select "
                "statement with its columns); S3b makes it (STONES.md). A segment "
                "type tells the kind of a node, not its fields.",
                *facts["segment_type"]["evidence"],
                *rs["node_type"]["evidence"],
            ),
        },
        "one_parse": {
            "sqruff": estimate(
                "possible",
                "parse_string gives the tree, and lint_parsed takes it. A command can "
                "keep a clone of the tree for code generation. A Jinja file can have "
                "more than one rendered variant, each with its own parse.",
                *facts["parse_api"]["evidence"],
            ),
            "sqlfluffrs": estimate(
                "possible",
                "root_parse gives the tree to the caller; the caller owns the lint "
                "and code generation steps.",
                *rs["parse_api"]["evidence"],
            ),
            "new-parser": estimate(
                "possible",
                "A design choice of S3b.",
                {"result": rel(T2_FILE), "key": "bases.new-parser.note"},
            ),
        },
        "parameter_styles": {
            **style_counts,
            "sqlfluffrs": fact(0, *sources_placeholder_ev(rs)),
            "new-parser": estimate(
                0, "Option 3 is a parser only.", *sources_placeholder_ev(rs)
            ),
            "note": "The styles are those of the placeholder templater (S6 table).",
        },
        "schema_output": estimate(
            {"sqruff": False, "sqlfluffrs": False, "new-parser": False},
            "No base writes a schema of the parameters and the columns (G2.2). The "
            "search finds no JSON Schema code; code generation is new work for each "
            "base.",
            {"search": facts["schema_search"]},
            {"search": rs["schema_search"]},
        ),
    }


def sources_placeholder_ev(rs: dict) -> list[dict]:
    return [
        {
            "search": "the tracked .rs files of sqlfluffrs/ with 'templat' in the path",
            "hits": rs["templater_files"],
        }
    ]


def median(values) -> float:
    return round(statistics.median(values), 6)


def g3_section(start: dict, t5: dict, t6: dict, s2: dict) -> dict:
    results = start["report"]["results"]
    by_tool: dict[str, list[dict]] = {}
    for r in results:
        if r["status"] == "valid":
            by_tool.setdefault(r["tool"], []).append(r)
    if len(by_tool.get("sqlfluff", [])) != 28:
        raise DataError("the session needs 28 valid sqlfluff start results")
    sf_start = median([r["stats"]["wall_s"]["median"] for r in by_tool["sqlfluff"]])
    sq_start = median([r["stats"]["wall_s"]["median"] for r in by_tool["sqruff"]])
    series = {k: v["stats"]["wall_s"]["median"] for k, v in start["series"].items()}
    py, imp, ver = series["python"], series["import_cli"], series["sqruff_version"]
    s2_start = {}
    for tool in ("sqlfluff", "sqlfluff-rs", "sqruff"):
        vals = [
            r["stats"]["wall_s"]["median"]
            for r in s2["results"]
            if r["command"] == "start" and r["tool"] == tool and r["status"] == "valid"
        ]
        s2_start[tool] = median(vals)
    t5_start = t5["speed"]["summary"]["start"]
    session_ev = command("timing session")
    return {
        "session": {
            "sqlfluff_start_median_s": fact(sf_start, session_ev),
            "sqruff_start_median_s": fact(sq_start, session_ev),
            "python_start_s": fact(py, session_ev),
            "import_cli_s": fact(imp, session_ev),
            "sqruff_version_s": fact(ver, session_ev),
            "machine": fact(start["report"]["machine"], session_ev),
            "note": "Each value: the median over the dialects of the median wall time "
            "of a start benchmark, or the median of a series. Ratios inside this "
            "session only.",
        },
        "sqlfluff_reference": fact(
            {
                "python_share_of_start": round(py / sf_start, 3),
                "import_cli_share_of_start": round(imp / sf_start, 3),
                "import_only_share_of_start": round((imp - py) / sf_start, 3),
                "rest_share_of_start": round((sf_start - imp) / sf_start, 3),
            },
            session_ev,
        ),
        "s2_start_median_s": fact(s2_start, result(S2_FILE, "results")),
        "session_over_s2": fact(
            {
                "sqlfluff": round(sf_start / s2_start["sqlfluff"], 3),
                "sqruff": round(sq_start / s2_start["sqruff"], 3),
            },
            session_ev,
            result(S2_FILE, "results"),
        ),
        "bases": {
            "sqruff": fact(
                {
                    "cause": "native binary",
                    "process_share_of_start": round(ver / sq_start, 3),
                    "links_libpython": any(
                        lib.startswith("libpython")
                        for lib in (start["readelf_needed"] or [])
                    ),
                    "needed_libraries": start["readelf_needed"],
                },
                session_ev,
                command("readelf of sqruff in the CI image"),
            ),
            "sqlfluffrs": fact(
                {
                    "cause": "native binary (T5 probe)",
                    "probe_over_sqruff_start_median": t5_start["probe_over_sqruff"][
                        "median_ratio"
                    ],
                    "setup_share_of_probe_start": t5_start["probe_phases"]["share"][
                        "setup_s"
                    ],
                },
                result(T5_FILE, "speed.summary.start"),
            ),
            "new-parser": estimate(
                {
                    "cause": "native binary",
                    "low_over_sqruff_start_sum": t6["bases"]["new-parser-low"][
                        "summary"
                    ]["start"]["g3_5_total"]["ratio"],
                },
                "The T6 low bound: the probe time with no setup phase.",
                result(T6_FILE, "bases.new-parser-low.summary.start.g3_5_total"),
            ),
            "sqlfluff-rs": estimate(
                {
                    "cause": "Python start and the import of sqlfluff, as sqlfluff",
                    "s2_start_over_sqlfluff": round(
                        s2_start["sqlfluff-rs"] / s2_start["sqlfluff"], 3
                    ),
                },
                "sqlfluff-rs is the Python sqlfluff with the Rust extension; its S2 "
                "start time is near that of sqlfluff. Not measured in this session.",
                result(S2_FILE, "results"),
            ),
        },
    }


def tables(s6: dict, s7: dict, g2: dict, g3: dict, sources: dict) -> dict:
    def tpl_cell(row, base):
        v = row[base]["value"]
        if not v["exists"]:
            return "no"
        return "native" if v["native"] else "Python (pyo3)"

    s6_rows = [
        [
            r["templater"],
            r["scope"]["value"] + (" (estimate)" if r["scope"].get("estimate") else ""),
            r["sqlfluff_4_4_0"]["value"],
            tpl_cell(r, "sqruff"),
            tpl_cell(r, "sqlfluffrs") + " (estimate)",
            tpl_cell(r, "new-parser") + " (estimate)",
        ]
        for r in s6["templaters"]
    ]
    styles = s6["placeholder_styles"]["rows"]
    same = sum(r["sqruff"]["value"]["same_pattern"] for r in styles)
    s6_rows.append(
        [
            "placeholder styles",
            "S6, G2.3",
            f"{len(styles)}",
            f"{same} of {len(styles)} with the same regex (other: "
            + ", ".join(
                r["style"] for r in styles if not r["sqruff"]["value"]["same_pattern"]
            )
            + "); more: "
            + ", ".join(s6["placeholder_styles"]["sqruff_only"]["value"]),
            "0",
            "0 (estimate)",
        ]
    )
    sm = s6["source_map"]
    s6_rows.append(
        [
            "source map",
            "S6",
            "TemplatedFile",
            sm["sqruff"]["value"],
            "TemplatedFile; lexer input "
            + ", ".join(sm["sqlfluffrs"]["value"]["lexer_input"]),
            "reuse of sqlfluffrs (estimate)",
        ]
    )

    sf_cmds = [r["command"] for r in s7["commands"] if r["sqlfluff"]["value"]]
    sq_has = [
        r["command"]
        for r in s7["commands"]
        if r["sqlfluff"]["value"] and r["sqruff"]["value"]
    ]
    opts = s7["options"]
    both = sum(len(v["value"]["both"]) for v in opts.values())
    total = sum(v["value"]["sqlfluff"] for v in opts.values())
    files = s7["config"]["files_in_each_folder"]
    keys = s7["config_keys"]
    s7_rows = [
        [
            "commands of sqlfluff",
            f"{len(sq_has)} of {len(sf_cmds)} (no {', '.join(c for c in sf_cmds if c not in sq_has)})",
            "0",
            "0 (estimate)",
        ],
        [
            f"option names of the {len(opts)} shared commands (sum)",
            f"{both} of {total}",
            "0",
            "0 (estimate)",
        ],
        [
            "config files in a folder",
            f"{len(files['both'])} of {len(files['sqlfluff']['value'])} "
            f"(no {', '.join(files['only_sqlfluff'])}); +{', '.join(files['only_sqruff'])}",
            "none (Python reads them; estimate)",
            "none (estimate)",
        ],
        [
            "default config keys",
            f"{keys['in_both_defaults']['value']} of {keys['sqlfluff_defaults']['value']}",
            f"{len(s7['config']['sqlfluffrs']['value']['fields'])} fields (estimate)",
            "0 (estimate)",
        ],
        [
            "S1 cases with an unsupported setting",
            f"{keys['s1_unsupported_settings']['value']['cases']}",
            "no CLI",
            "no CLI (estimate)",
        ],
    ]
    tt = g2["typed_tree"]
    g2_rows = [
        [
            "segment type",
            f"SyntaxKind enum ({tt['sqruff']['value']['syntax_kinds']} kinds)",
            "string",
            "enum from the generator (estimate)",
        ],
        ["typed node view", "no (estimate)", "no (estimate)", "no (estimate)"],
        [
            "one parse for lint and code generation",
            g2["one_parse"]["sqruff"]["value"] + " (estimate)",
            g2["one_parse"]["sqlfluffrs"]["value"] + " (estimate)",
            g2["one_parse"]["new-parser"]["value"] + " (estimate)",
        ],
        [
            "parameter styles",
            str(g2["parameter_styles"]["sqruff"]["value"]),
            "0",
            "0 (estimate)",
        ],
        ["schema output (G2.2)", "no (estimate)", "no (estimate)", "no (estimate)"],
    ]
    b = g3["bases"]
    ref = g3["sqlfluff_reference"]["value"]
    g3_rows = [
        [
            "cause",
            b["sqruff"]["value"]["cause"],
            b["sqlfluffrs"]["value"]["cause"],
            b["new-parser"]["value"]["cause"] + " (estimate)",
            "Python",
        ],
        [
            "start / sqruff start",
            "1",
            f"{b['sqlfluffrs']['value']['probe_over_sqruff_start_median']} (median, T5)",
            f"{b['new-parser']['value']['low_over_sqruff_start_sum']} (sum, T6 low, estimate)",
            f"{round(g3['session']['sqlfluff_start_median_s']['value'] / g3['session']['sqruff_start_median_s']['value'], 1)}",
        ],
        [
            "share of start",
            f"process start and loader {b['sqruff']['value']['process_share_of_start']}",
            f"dialect table setup {b['sqlfluffrs']['value']['setup_share_of_probe_start']}",
            "no setup phase (estimate)",
            f"Python {ref['python_share_of_start']}, import of the CLI "
            f"{ref['import_only_share_of_start']}, rest {ref['rest_share_of_start']}",
        ],
    ]
    return {
        "S6": {
            "columns": [
                "item",
                "scope",
                "sqlfluff 4.4.0",
                "1 sqruff",
                "2 sqlfluffrs",
                "3 new parser",
            ],
            "rows": s6_rows,
        },
        "S7": {
            "columns": ["item", "1 sqruff", "2 sqlfluffrs", "3 new parser"],
            "rows": s7_rows,
        },
        "G2_S8": {
            "columns": ["item", "1 sqruff", "2 sqlfluffrs", "3 new parser"],
            "rows": g2_rows,
        },
        "G3_start": {
            "columns": ["item", "1 sqruff", "2 sqlfluffrs", "3 new parser", "sqlfluff"],
            "rows": g3_rows,
        },
    }


def check_evidence(out: dict, sources: dict, start: dict) -> None:
    """Each entry has evidence of a known kind; each command and result key
    exists."""
    commands = set(sources["commands"]) | {s["step"] for s in start["steps"]}
    count = 0
    for f in walk_facts(out):
        count += 1
        if not f["evidence"]:
            raise DataError(f"no evidence: {f['value']!r}")
        if f.get("estimate") and not f.get("judgement"):
            raise DataError(f"an estimate with no judgement: {f['value']!r}")
        for ev in f["evidence"]:
            if "command" in ev:
                if ev["command"] not in commands:
                    raise DataError(f"an unknown command {ev['command']!r}")
            elif "result" in ev:
                path = phase_a.read_path(ev["result"])
                if not path.exists():
                    raise DataError(f"{ev['result']} does not exist")
                if path.suffix == ".json":
                    get_key(load_json(path), ev["key"])
            elif "source" in ev:
                src = ev["source"]
                if not src["lines"] or not src["sha256"]:
                    raise DataError(f"{src['file']}: a source with no lines")
                if src["base"] != "sqruff":
                    path = ROOT / src["file"]
                    if sha256_file(path) != src["sha256"]:
                        raise DataError(f"{src['file']}: not the cited file")
            elif "document" in ev:
                document(ev["document"], ev["text"])
            elif "search" not in ev:
                raise DataError(f"an unknown evidence kind: {ev}")
    if count == 0:
        raise DataError("the report has no entries")


def make_report(
    sources_path: Path = SOURCES_FILE, start_path: Path = START_FILE
) -> dict:
    sources = load_json(sources_path)
    start = load_json(start_path)
    t2, t5, t6, t7 = (load_json(p) for p in (T2_FILE, T5_FILE, T6_FILE, T7_FILE))
    s2 = load_json(S2_FILE)
    check_sources(sources, t7, load_json(T7_SOURCES))
    parsed = help_options(sources)
    check_click(parsed["sqlfluff"], sources["sqlfluff"])
    sf = sqlfluff_sources()
    rs = sqlfluffrs_sources()
    s6 = s6_section(sources, None, sf, rs, t2)
    s7 = s7_section(sources, None, sf, rs, parsed)
    g2 = g2_section(sources, rs, t5, t7)
    g3 = g3_section(start, t5, t6, s2)
    inputs = [sources_path, start_path, T2_FILE, T5_FILE, T6_FILE, T7_FILE, T7_SOURCES]
    inputs.append(S2_FILE)
    inputs.append(KNOWN_FAILURES)
    out = {
        "kind": "sqll-s3-capabilities",
        "format": 1,
        "task": "T8",
        "criterion": "C7",
        "sqlfluff_ref": sqlfluff_ref(SQLFLUFF_ROOT),
        "versions": {
            "sqlfluff": SQLFLUFF_VERSION,
            "sqruff": SQRUFF_VERSION,
            "sqlfluffrs": SQLFLUFF_VERSION,
        },
        "commands": COMMANDS,
        "inputs": {rel(p): sha256_file(p) for p in inputs},
        "evidence": {
            "command": "a command of the sources file (help text, tool output) or "
            "of the start session; its argv, exit code, and output are there",
            "source": "a file of a base at the pinned version: the crate (sqruff) or "
            "the submodule commit (sqlfluff, sqlfluffrs), the sha256, and the cited "
            "lines",
            "result": "a committed result file and a key in it",
            "search": "a search over the files of a base; its pattern and hits",
            "document": "a quote of a file of this repository",
            "estimate": "an entry with estimate true is a judgement; 'judgement' "
            "gives the reason",
        },
        "tables": None,
        "S6": s6,
        "S7": s7,
        "G2_S8": g2,
        "G3_start": g3,
    }
    out["tables"] = tables(s6, s7, g2, g3, sources)
    check_evidence(out, sources, start)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="capabilities.py")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect", help="Record the raw data in SOURCES_FILE.")
    c.add_argument("--scratch", type=Path, required=True)
    t = sub.add_parser("time", help="Record the start session in START_FILE.")
    t.add_argument("--scratch", type=Path, required=True)
    t.add_argument("--image", default=None)
    ti = sub.add_parser("time-inside", help="The session (in the CI image).")
    ti.add_argument("--scratch", type=Path, required=True)
    r = sub.add_parser("report", help="Write OUT_FILE from the committed files.")
    r.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.command == "collect":
            SOURCES_FILE.write_text(dump(collect(args.scratch)), encoding="utf8")
            print(f"wrote {rel(SOURCES_FILE)}")
        elif args.command == "time":
            START_FILE.write_text(dump(time_session(args.scratch, args.image)), "utf8")
            print(f"wrote {rel(START_FILE)}")
        elif args.command == "time-inside":
            (args.scratch / "start-session.json").write_text(
                dump(time_inside(args.scratch)), encoding="utf8"
            )
        else:
            text = dump(make_report())
            if args.check:
                if not OUT_FILE.exists() or OUT_FILE.read_text("utf8") != text:
                    print(f"{rel(OUT_FILE)} is not the report of the inputs")
                    return 1
                print(f"{rel(OUT_FILE)} is up to date")
            else:
                OUT_FILE.write_text(text, encoding="utf8")
                print(f"wrote {rel(OUT_FILE)}")
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
