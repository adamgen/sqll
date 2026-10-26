"""S3 phase A, task T4: the classes of the sqruff rule, autofix, and
templater failures, and the coupling of the sqruff rules to tree shapes.

Commands. Run them with the harness Python:

    uv run --frozen --project harness python scripts/s3/sqruff_rules.py collect
    uv run --frozen --project harness python scripts/s3/sqruff_rules.py sources
    uv run --frozen --project harness python scripts/s3/sqruff_rules.py build [--check]

"collect" parses the SQL of each failure that is not an unsupported item
with sqruff and with sqlfluff, through the harness adapters and with the
config of the case, and writes the tree differences to PARSES_FILE.
"sources" reads the sqruff-lib and sqruff-lib-core 0.41.0 crates from the
cargo cache (tools/sqruff/install.sh fills it) and the grammar of the
pinned sqlfluff, and writes only names to TYPES_FILE: for each sqruff rule,
the segment types that its source and its helper modules name; and the
segment types of the sqlfluff 4.4.0 dialects. "build" reads only committed
files (PARSES_FILE, TYPES_FILE, the T2 and T3 files, and
known_failures/sqruff.txt) and writes OUT_FILE. With --check it writes
nothing and fails if OUT_FILE is not the new text.

Each command stops with exit code 1 if the data do not agree (DataError).
"""

import argparse
import concurrent.futures
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

from sqll_harness import known_failures
from sqll_harness.adapters.base import EmptyHome, Unsupported, isolated_env
from sqll_harness.adapters.sqlfluff import SqlfluffAdapter, sqlfluff_toml
from sqll_harness.adapters.sqlfluff import _parse_file_output as sqlfluff_output
from sqll_harness.adapters.sqruff import SqruffAdapter
from sqll_harness.code_only import META_TYPES, NON_CODE_TYPES
from sqll_harness.compare import load_yaml, record_to_test_tuple, strip_positions
from sqll_harness.paths import SQLFLUFF_ROOT, sqlfluff_ref, tools_dir
from sqll_harness.suites import autofix, rules, templater

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sqruff_trees as st  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "s3"
PARSES_FILE = RESULTS / "sqruff-rule-parses.json"
TYPES_FILE = RESULTS / "sqruff-rule-types.json"
OUT_FILE = RESULTS / "sqruff-rule-diffs.json"
CASES_FILE = RESULTS / "sqruff-cases.json"
TREES_FILE = RESULTS / "sqruff-tree-diffs.json"
KNOWN_FAILURES = ROOT / "known_failures"


def _sqruff_version() -> str:
    """The pinned sqruff version (tools/sqruff/uv.lock)."""
    proc = subprocess.run(
        ["sh", str(ROOT / "tools" / "sqruff" / "install.sh"), "--print-version"],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


SQRUFF_VERSION = _sqruff_version()
SUITES = ("rules", "autofix", "templater")
FAILURES = {"rules": 342, "autofix": 16, "templater": 15}
IMPLICIT = ("implicit", "indent")
EQUAL_IMPLICIT = "equal with implicit as indent"
NO_RULE_CONFIG = (
    "sqruff failed with the full config; parsed with no rules and layout sections"
)
RULE_CHECKS = ("pass_str", "fail_str", "fix", "after_fix")
# The SQL file that each check of a rule case reads (rules.md).
CHECK_FILES = {
    "pass_str": "pass",
    "fail_str": "fail",
    "fix": "fail",
    "after_fix": "fixed",
}

COLLECT_COMMAND = (
    "uv run --frozen --project harness python scripts/s3/sqruff_rules.py collect"
)
SOURCES_COMMAND = (
    "uv run --frozen --project harness python scripts/s3/sqruff_rules.py sources"
)
BUILD_COMMAND = (
    "uv run --frozen --project harness python scripts/s3/sqruff_rules.py build"
)

CONFIG_VALUE_PANIC = "config value panic"
CLASSES = {
    "unsupported_item": (
        "The case uses an item that sqruff does not support: a setting, a "
        "rule, a dialect, an output field, or a value that its INI config "
        "cannot hold. The harness does not run the case (harness/sqruff.md, "
        "'Unsupported items'). This class comes first: the other causes are "
        "not known."
    ),
    "parse_cause": (
        "A SQL file that a failed check reads has another sqruff tree than "
        "the sqlfluff tree: another tree, an unparsable node, or no tree "
        "(sqruff cannot template the file). The trees are compared with the "
        "meta segments, as the rules see them."
    ),
    "rule_logic": (
        "The SQL files that the failed checks read have the same tree in "
        "sqruff and in sqlfluff. Thus the rule, fix, or config logic of "
        "sqruff gives another result (also a sqruff panic). Kind "
        f"'{CONFIG_VALUE_PANIC}': sqruff panics on a config value of the "
        "case before a rule runs: the parse of the case SQL also panics with "
        "the case config, and passes without the rules and layout sections. "
        "These cases are near to an unsupported item (a setting value); "
        "'sensitivity' gives the counts with them in unsupported_item."
    ),
}
# The groups of the unsupported items: the kind in the reason gives the group.
UNSUPPORTED_GROUPS = {
    "setting": "setting",
    "layout type": "setting",
    "rule": "rule",
    "dialect": "dialect",
    "templater": "templater",
    "output field": "output field",
    "upper-case key": "INI limit",
    "multi-line value": "INI limit",
    "comment character": "INI limit",
    "in-file config line": "in-file config line",
}


class DataError(Exception):
    """The inputs do not agree."""


# The scope: the failures of the 3 suites.


def failures() -> dict[str, dict[str, str]]:
    """Return {suite: {case id: reason}} of known_failures/sqruff.txt for
    SUITES. Raise DataError if a count is not that of FAILURES."""
    known = known_failures.load(KNOWN_FAILURES, "sqruff")
    out: dict[str, dict[str, str]] = {s: {} for s in SUITES}
    for case_id, reason in known.items():
        suite = case_id.split("/", 1)[0]
        if suite in out:
            out[suite][case_id] = reason
    for suite, n in FAILURES.items():
        if len(out[suite]) != n:
            raise DataError(
                f"known_failures/sqruff.txt has {len(out[suite])} {suite} "
                f"failures, not {n}"
            )
    return out


def unsupported_group(reason: str) -> str | None:
    """Return the group of an unsupported item, or None for another reason."""
    if not reason.startswith(known_failures.UNSUPPORTED):
        return None
    prefix = known_failures.reason_prefix(reason)
    kind = prefix[len(known_failures.UNSUPPORTED) :]
    if kind not in UNSUPPORTED_GROUPS:
        raise DataError(f"unknown unsupported item {prefix!r}")
    return UNSUPPORTED_GROUPS[kind]


# collect: sqruff and sqlfluff parses -> PARSES_FILE


def _tuple(record) -> tuple | None:
    if record is None:
        return None
    return record_to_test_tuple(strip_positions(record))


def implicit_as_indent(tree: tuple) -> tuple:
    """Return the sqruff tree with the sqlfluff name of an implicit indent.
    sqlfluff gives the type "indent" to ImplicitIndent; sqruff gives
    "implicit" to the same meta segment."""
    name, value = tree
    if isinstance(value, str):
        return (IMPLICIT[1] if (name, value) == (IMPLICIT[0], "") else name, value)
    return (name, tuple(implicit_as_indent(c) for c in value))


def compare(expected: tuple | None, actual: tuple | None, dialect: str) -> list:
    """Return [state, classes, group keys] for 2 trees."""
    if expected is None and actual is None:
        return ["no tree", [], []]
    if expected is None:
        return ["no sqlfluff tree", [], []]
    if actual is None:
        return ["no sqruff tree", [], []]
    if expected == actual:
        return ["equal", [], []]
    actual = implicit_as_indent(actual)
    if expected == actual:
        return [EQUAL_IMPLICIT, [], []]
    hunks = st.diff(expected, actual, dialect)["hunks"]
    return [
        "differs",
        sorted({h[0] for h in hunks}),
        sorted({h[1] for h in hunks}),
    ]


def sqlfluff_rule_parse(
    adapter: SqlfluffAdapter, path: Path, dialect: str | None, config, work: Path
) -> tuple | None:
    """Parse a rule case file as the lint of the rules suite reads it."""
    cmd = [str(adapter.binary), "parse", "-f", "json", "-m"]
    cmd += ["--ignore-local-config", "--encoding", "utf-8"]
    if dialect is not None:
        cmd += ["--dialect", dialect]
    config = adapter.case_config(config, [path])
    with tempfile.TemporaryDirectory(prefix="sqll-s3-") as tmp:
        if config:
            cfg = Path(tmp) / "pyproject.toml"
            cfg.write_text(sqlfluff_toml(config), encoding="utf8")
            cmd += ["--config", str(cfg)]
        proc = adapter._run([*cmd, path.name], work)
    result = sqlfluff_output(proc.stdout, proc.returncode, proc.stderr)
    if result.errors and result.tree is None and proc.returncode not in (0, 1):
        raise DataError(f"sqlfluff parse {path.name}: {result.errors}")
    return _tuple(result.tree)


def sqruff_rule_parse(
    adapter: SqruffAdapter,
    path: Path,
    dialect: str | None,
    config,
    codes: list[str],
    work: Path,
) -> tuple[tuple | None, str]:
    """Parse a rule case file with the config of the lint. Return the tree
    and a note. If sqruff fails (for example a panic on a rule or layout
    value), parse again with no "rules" and no "layout" section: they do not
    change the parse."""
    note = ""
    full = adapter._rule_config(config, codes)
    result = adapter._parse(Path(path.name), dialect, full, work, False, True)
    if result.errors:
        error = " ".join(result.errors[0].split())
        for pattern, repl in known_failures._VOLATILE:
            error = pattern.sub(repl, error)
        note = f"{NO_RULE_CONFIG}: {error[:120]}"
        rest = {k: v for k, v in (config or {}).items() if k not in ("rules", "layout")}
        full = adapter._rule_config(rest, codes)
        result = adapter._parse(Path(path.name), dialect, full, work, False, True)
    if result.errors:
        raise DataError(f"sqruff parse {path.name}: {result.errors}")
    return _tuple(result.tree), note


def rule_dialect(case: rules.RuleCase) -> str:
    dialect = rules.default_dialect(case.configs)
    return dialect or str(case.configs["core"]["dialect"]).strip()


def collect_rule(sqlfluff: SqlfluffAdapter, sqruff: SqruffAdapter, case) -> dict:
    codes = rules.rule_codes(case.rule)
    dialect = rules.default_dialect(case.configs)
    sql = {"pass": case.pass_str, "fail": case.fail_str}
    sql["fixed"] = case.fix_str if case.fail_str else None
    files = {}
    with tempfile.TemporaryDirectory(prefix="sqll-s3-rule-") as tmp:
        work = Path(tmp)
        for name, text in sql.items():
            if not text:
                continue
            path = work / f"{name}.sql"
            path.write_bytes(text.encode("utf8"))
            expected = sqlfluff_rule_parse(sqlfluff, path, dialect, case.configs, work)
            try:
                actual, note = sqruff_rule_parse(
                    sqruff, path, dialect, case.configs, codes, work
                )
            except Unsupported as exc:
                raise DataError(f"{case.id}: unsupported: {exc}") from exc
            files[name] = compare(expected, actual, rule_dialect(case))
            if note:
                files[name].append(note)
    return {"rule": ",".join(codes), "dialect": rule_dialect(case), "files": files}


def collect_autofix(sqlfluff: SqlfluffAdapter, sqruff: SqruffAdapter, case) -> dict:
    test_config = autofix.load_test_config(case.folder / "test-config.yml")
    before = autofix.read_text(case.folder / "before.sql")
    config_path = case.folder / autofix.CONFIG_NAME
    config = autofix.read_text(config_path) if config_path.exists() else ""
    trees = []
    with tempfile.TemporaryDirectory(prefix="sqll-s3-autofix-") as tmp:
        for adapter in (sqlfluff, sqruff):
            work = Path(tmp) / adapter.name
            work.mkdir()
            sql = work / autofix.SQL_NAME
            autofix.write_text(sql, before)
            autofix.write_text(work / autofix.CONFIG_NAME, config)
            result = adapter.parse_file(sql, case.dialect, SQLFLUFF_ROOT, False, True)
            if result.errors and (adapter is sqruff or result.tree is None):
                raise DataError(f"{case.id}: {adapter.name} parse: {result.errors}")
            trees.append(_tuple(result.tree))
    return {
        "rule": test_config.rules or "all",
        "dialect": case.dialect,
        "files": {"before": compare(*trees, case.dialect)},
    }


def collect_templater(sqruff: SqruffAdapter, case) -> dict:
    _, expected = load_yaml(SQLFLUFF_ROOT / case.yml)
    result = sqruff.parse_file(
        case.sql, None, SQLFLUFF_ROOT, case.code_only, case.include_meta
    )
    if result.errors:
        raise DataError(f"{case.id}: sqruff parse: {result.errors}")
    actual = None
    if result.tree is not None:
        record = strip_positions(result.tree) if case.include_meta else result.tree
        actual = record_to_test_tuple(record)
    dialect = sqruff.user_config(case.sql, None, SQLFLUFF_ROOT, None)["core"]["dialect"]
    return {
        "rule": "-",
        "dialect": dialect,
        "files": {"sql": compare(expected, actual, dialect)},
    }


def collect(jobs: int = 4) -> dict:
    sqruff = SqruffAdapter()
    sqlfluff = SqlfluffAdapter()
    if sqruff.version() != SQRUFF_VERSION:
        raise DataError(f"sqruff {sqruff.version()}, not {SQRUFF_VERSION}")
    scope = failures()

    def todo(suite: str, case_id: str) -> bool:
        reason = scope[suite].get(case_id)
        return reason is not None and not unsupported_group(reason)

    work = [
        (c.id, lambda c=c: collect_rule(sqlfluff, sqruff, c))
        for c in rules.discover(SQLFLUFF_ROOT)
        if todo("rules", c.id)
    ]
    work += [
        (c.id, lambda c=c: collect_autofix(sqlfluff, sqruff, c))
        for c in autofix.discover(SQLFLUFF_ROOT)
        if todo("autofix", c.id)
    ]
    work += [
        (c.id, lambda c=c: collect_templater(sqruff, c))
        for c in templater.discover(SQLFLUFF_ROOT)
        if todo("templater", c.id)
    ]
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        rows = list(pool.map(lambda job: (job[0], job[1]()), work))
    return {
        "kind": "sqll-s3-sqruff-rule-parses",
        "format": 1,
        "sqlfluff_ref": sqlfluff_ref(SQLFLUFF_ROOT),
        "sqruff": SQRUFF_VERSION,
        "sqlfluff": sqlfluff.version(),
        "commands": {"collect": COLLECT_COMMAND},
        "file": (
            "[state, T3 classes, T3 group keys, note]. state: equal, "
            f"'{EQUAL_IMPLICIT}' (equal if the sqruff meta type 'implicit' is "
            "'indent', the type that sqlfluff gives to ImplicitIndent), "
            "differs, no sqruff tree, no sqlfluff tree, or no tree. The "
            "sqlfluff tree is the expected tree (sqruff_trees.diff); the "
            "classes and keys are those of the trees with 'implicit' as "
            "'indent'. note (only if set): "
            f"'{NO_RULE_CONFIG}: <error>'"
        ),
        "files": (
            "rules: pass, fail, and fixed (the SQL strings of the case, "
            "parsed with the case config as the lint of the rules suite); "
            "autofix: before (before.sql with the config files of the case); "
            "templater: sql (the sqruff tree of the templater suite and the "
            "fixture tree)"
        ),
        "cases": dict(sorted(rows)),
    }


# sources: sqruff rule sources and the sqlfluff grammar -> TYPES_FILE

CRATES = ("sqruff", "sqruff-lib", "sqruff-lib-core")
# The modules of a rule: its file, and the modules that its "use" items
# name, again and again, inside these folders of the 2 crates. The base
# segment module (BASE_MODULE), the linter, the config, and the crawlers are
# not in them: each rule uses them in the same way.
HELPER_FOLDERS = {
    "sqruff-lib": ("rules/", "utils/"),
    "sqruff-lib-core": ("utils/", "parser/segments/", "dialects/common.rs"),
}
EXCLUDED_MODULES = ("sqruff-lib-core/parser/segments/test_functions.rs",)
BASE_MODULE = "sqruff-lib-core/parser/segments.rs"
# reflow/config.rs maps the layout types of the config to spacing and line
# positions. The names of these types are in default_config.cfg.
LAYOUT_CONFIG_MODULE = "sqruff-lib/utils/reflow/config.rs"
LAYOUT_SECTION = re.compile(r"^\[sqruff:layout:type:([a-z0-9_]+)\]", re.M)
SYNTAX_KIND = re.compile(r"\bSyntaxKind::([A-Z][A-Za-z0-9]*)\b")
USE_ITEM = re.compile(r"\buse\s+([^;]+);")
CFG_TEST = re.compile(r"#\[cfg\(test\)\]")


def snake_case(name: str) -> str:
    """The snake_case of strum (heck) for a SyntaxKind variant. A new word
    starts at an upper-case letter after a lower-case letter (also after
    digits that follow a lower-case letter), and at the last upper-case
    letter of a run of upper-case letters that a lower-case letter follows."""
    words: list[str] = []
    word = ""
    mode = "boundary"
    for i, c in enumerate(name):
        nxt = name[i + 1] if i + 1 < len(name) else ""
        word += c
        if not nxt:
            break
        next_mode = "lower" if c.islower() else "upper" if c.isupper() else mode
        if next_mode == "lower" and nxt.isupper():
            words.append(word)
            word = ""
            mode = "boundary"
        elif mode == "upper" and c.isupper() and nxt.islower():
            words.append(word[:-1])
            word = c
            mode = next_mode
        else:
            mode = next_mode
    words.append(word)
    return "_".join(w.lower() for w in words if w)


def strip_rust(text: str) -> str:
    """Return the code with no comments, no string or char literals, and no
    #[cfg(test)] items. Literals become empty literals."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if text.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif text.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            continue
        raw = re.match(r'b?r(#*)"', text[i:])
        if raw and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
            end = '"' + raw.group(1)
            j = text.find(end, i + raw.end())
            if j < 0:
                raise ValueError("raw string with no end")
            out.append('""')
            i = j + len(end)
            continue
        if c == '"' or (
            c == "b" and text.startswith('b"', i) and not _ident_before(text, i)
        ):
            i += 2 if c == "b" else 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            out.append('""')
            i += 1
            continue
        if c == "'":
            if text.startswith("'\\", i):
                j = text.find("'", i + 2)
                out.append("' '")
                i = j + 1
                continue
            if i + 2 < n and text[i + 2] == "'":
                out.append("' '")
                i += 3
                continue
        out.append(c)
        i += 1
    return _drop_cfg_test("".join(out))


def _ident_before(text: str, i: int) -> bool:
    return i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_")


def _drop_cfg_test(code: str) -> str:
    while True:
        m = CFG_TEST.search(code)
        if not m:
            return code
        start = code.find("{", m.end())
        semi = code.find(";", m.end())
        if start < 0 or (0 <= semi < start):
            code = code[: m.start()] + code[semi + 1 :]
            continue
        depth, j = 0, start
        while j < len(code):
            if code[j] == "{":
                depth += 1
            elif code[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        code = code[: m.start()] + code[j + 1 :]


def use_paths(code: str) -> list[list[str]]:
    """Return the paths of the "use" items: use a::{b, c::d as e} gives
    [a, b] and [a, c, d]."""
    out: list[list[str]] = []
    for m in USE_ITEM.finditer(code):
        tree = re.sub(r"\s+as\s+\w+", "", m.group(1))
        out += _expand(re.sub(r"\s+", "", tree))
    return out


def _expand(tree: str) -> list[list[str]]:
    if "{" not in tree:
        parts = [p for p in tree.split("::") if p]
        return [parts] if parts else []
    head, rest = tree.split("{", 1)
    body = rest[: rest.rfind("}")]
    items, depth, word = [], 0, ""
    for ch in body:
        if ch == "," and depth == 0:
            items.append(word)
            word = ""
            continue
        depth += ch == "{"
        depth -= ch == "}"
        word += ch
    items.append(word)
    prefix = [p for p in head.split("::") if p]
    out = []
    for item in items:
        for sub in _expand(item):
            out.append(prefix + ([] if sub == ["self"] else sub))
    return out


class Crate:
    """The .rs files of a crate, by path relative to src/."""

    def __init__(self, name: str, files: dict[str, str]) -> None:
        self.name = name
        self.files = files

    def module(self, parts: list[str]) -> str | None:
        """Return the file of the longest module prefix of the path."""
        for k in range(len(parts), 0, -1):
            stem = "/".join(parts[:k])
            for cand in (f"{stem}.rs", f"{stem}/mod.rs"):
                if cand in self.files:
                    return cand
        return None


def module_path(rel: str) -> list[str]:
    return rel[: -len(".rs")].removesuffix("/mod").split("/")


def resolve(crates: dict[str, Crate], crate: str, rel: str, path: list[str]):
    """Return (crate, file) of a use path in the file rel of crate, or None."""
    if not path:
        return None
    if path[0] == "crate":
        target, parts = crate, path[1:]
    elif path[0] == "sqruff_lib_core":
        target, parts = "sqruff-lib-core", path[1:]
    elif path[0] in ("super", "self"):
        base = module_path(rel)
        while path and path[0] in ("super", "self"):
            if path[0] == "super":
                base = base[:-1]
            path = path[1:]
        target, parts = crate, base + path
    else:
        return None
    if target not in crates:
        return None
    found = crates[target].module(parts)
    return (target, found) if found else None


def is_helper(crate: str, rel: str) -> bool:
    if f"{crate}/{rel}" in EXCLUDED_MODULES:
        return False
    return rel.startswith(HELPER_FOLDERS.get(crate, ()))


def rule_modules(crates: dict[str, Crate], rel: str) -> list[str]:
    """Return the helper modules of a rule file of sqruff-lib, as crate/path,
    sorted, without the rule file."""
    seen = {("sqruff-lib", rel)}
    todo = [("sqruff-lib", rel)]
    while todo:
        crate, file = todo.pop()
        code = strip_rust(crates[crate].files[file])
        for path in use_paths(code):
            got = resolve(crates, crate, file, path)
            if got and got not in seen and is_helper(*got):
                seen.add(got)
                todo.append(got)
    seen.discard(("sqruff-lib", rel))
    return sorted(f"{c}/{f}" for c, f in seen)


def uses_module(crates: dict[str, Crate], files: list[str], module: str) -> bool:
    """Return True if a "use" item of one of the files (crate/path) names
    the module (crate/path)."""
    for mod in files:
        crate, file = mod.split("/", 1)
        for path in use_paths(strip_rust(crates[crate].files[file])):
            got = resolve(crates, crate, file, path)
            if got and "/".join(got) == module:
                return True
    return False


def type_names(code: str) -> list[str]:
    return sorted({snake_case(v) for v in SYNTAX_KIND.findall(code)})


def read_crate(path: Path) -> dict[str, str]:
    """Return {path below the crate folder: text} of a .crate archive."""
    out = {}
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(path.read_bytes()))) as tar:
        for member in tar.getmembers():
            if member.isfile():
                name = member.name.split("/", 1)[1]
                out[name] = tar.extractfile(member).read().decode("utf8")
    return out


def cargo_cache() -> Path:
    home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))
    found = sorted((home / "registry" / "cache").glob("*/sqruff-lib-core-*.crate"))
    if not found:
        raise DataError(
            f"no sqruff crates in {home}/registry/cache; run tools/sqruff/install.sh"
        )
    return found[0].parent


def lock_checksums(lock: str) -> dict[str, str]:
    out = {}
    for block in lock.split("[[package]]"):
        name = re.search(r'^name = "([^"]+)"', block, re.M)
        version = re.search(r'^version = "([^"]+)"', block, re.M)
        checksum = re.search(r'^checksum = "([0-9a-f]+)"', block, re.M)
        if name and version and checksum:
            out[f"{name.group(1)}-{version.group(1)}"] = checksum.group(1)
    return out


SQLFLUFF_TYPES_CODE = r"""
import json, sys
from sqlfluff.core.dialects import dialect_readout, dialect_selector
from sqlfluff.core.parser.grammar.base import BaseGrammar
from sqlfluff.core.parser.parsers import BaseParser
from sqlfluff.core.parser.segments.base import BaseSegment

def is_segment(obj):
    return isinstance(obj, type) and issubclass(obj, BaseSegment)

def walk(obj, acc, seen):
    if id(obj) in seen:
        return
    seen.add(id(obj))
    if is_segment(obj):
        acc.update(obj._class_types)
        if getattr(obj, "match_grammar", None) is not None:
            walk(obj.match_grammar, acc, seen)
    elif isinstance(obj, BaseParser):
        acc.update(t for t in obj._instance_types if t)
        walk(obj.raw_class, acc, seen)
    elif isinstance(obj, BaseGrammar):
        for value in vars(obj).values():
            items = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
            for item in items:
                if is_segment(item) or isinstance(item, (BaseGrammar, BaseParser)):
                    walk(item, acc, seen)

def subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from subclasses(sub)

acc = set()
for d in dialect_readout():
    dialect = dialect_selector(d.label)
    seen = set()
    for obj in dialect._library.values():
        walk(obj, acc, seen)
    stack = list(dialect.get_lexer_matchers())
    while stack:
        m = stack.pop()
        if m is None:
            continue
        walk(m.segment_class, acc, seen)
        kw = m.segment_kwargs or {}
        if "type" in kw:
            acc.add(kw["type"])
        elif "instance_types" in kw:
            acc.update(kw["instance_types"])
        elif m.name not in m.segment_class._class_types:
            acc.add(m.name)
        stack += [m.subdivider, m.trim_post_subdivide]
for cls in subclasses(BaseSegment):
    acc.update(cls._class_types)
json.dump(sorted(acc), sys.stdout)
"""


def sqlfluff_types() -> list[str]:
    """The segment types of the pinned sqlfluff: the types and class types
    of each segment class, parser, and lexer of each dialect, and of each
    segment class of the package."""
    python = tools_dir() / "sqlfluff" / "bin" / "python"
    if not python.exists():
        raise DataError(f"{python} does not exist; run scripts/setup")
    with tempfile.TemporaryDirectory(prefix="sqll-s3-") as tmp:
        proc = subprocess.run(
            [str(python), "-I", "-c", SQLFLUFF_TYPES_CODE],
            capture_output=True,
            text=True,
            cwd=tmp,
            env=isolated_env(EmptyHome.path()),
            check=False,
        )
    if proc.returncode != 0:
        raise DataError(f"sqlfluff types: {proc.stderr.strip()[-300:]}")
    return json.loads(proc.stdout)


def sources(cache: Path | None = None) -> dict:
    cache = cache or cargo_cache()
    crates_meta = {}
    contents = {}
    for name in CRATES:
        path = cache / f"{name}-{SQRUFF_VERSION}.crate"
        if not path.exists():
            raise DataError(f"{path} does not exist; run tools/sqruff/install.sh")
        crates_meta[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        contents[name] = read_crate(path)
    locked = lock_checksums(contents["sqruff"]["Cargo.lock"])
    for name in CRATES[1:]:
        if locked.get(f"{name}-{SQRUFF_VERSION}") != crates_meta[name]:
            raise DataError(f"{name}: the crate is not the one of sqruff Cargo.lock")
    crates = {
        name: Crate(
            name,
            {
                k[len("src/") :]: v
                for k, v in contents[name].items()
                if k.startswith("src/") and k.endswith(".rs")
            },
        )
        for name in CRATES[1:]
    }
    codes = SqruffAdapter().info["rules"]
    lib = crates["sqruff-lib"]
    rule_files = {
        Path(rel).stem.upper(): rel
        for rel in lib.files
        if re.fullmatch(r"rules/[a-z_]+/[a-z]{2}\d{2}\.rs", rel)
    }
    if set(rule_files) != set(codes):
        raise DataError(
            f"rule files {sorted(set(rule_files) ^ set(codes))} do not agree "
            "with 'sqruff rules'"
        )
    modules: dict[str, dict] = {}
    rows = {}
    for code in sorted(rule_files):
        rel = rule_files[code]
        helpers = rule_modules(crates, rel)
        for mod in helpers:
            if mod not in modules:
                crate, file = mod.split("/", 1)
                names = type_names(strip_rust(crates[crate].files[file]))
                entry = {"names": names}
                if mod == LAYOUT_CONFIG_MODULE:
                    cfg = contents["sqruff-lib"]["src/core/default_config.cfg"]
                    entry["layout_config"] = sorted(set(LAYOUT_SECTION.findall(cfg)))
                modules[mod] = entry
        rows[code] = {
            "name": codes[code],
            "file": f"sqruff-lib/{rel}",
            "names": type_names(strip_rust(lib.files[rel])),
            "modules": helpers,
            "base_module": uses_module(
                crates, [f"sqruff-lib/{rel}", *helpers], BASE_MODULE
            ),
        }
    base_crate, base_file = BASE_MODULE.split("/", 1)
    return {
        "kind": "sqll-s3-sqruff-rule-types",
        "format": 1,
        "sqlfluff_ref": sqlfluff_ref(SQLFLUFF_ROOT),
        "sqruff": SQRUFF_VERSION,
        "commands": {"sources": SOURCES_COMMAND},
        "crates": {
            name: {"sha256": crates_meta[name], "source": "crates.io"}
            for name in CRATES
        },
        "method": (
            "Names only; no code. For each rule: the SyntaxKind variants that "
            "its file names, as strum snake_case strings (the segment type "
            "that sqruff gives). Comments, string literals, and #[cfg(test)] "
            "items are removed first. modules: the files that the 'use' items "
            "of the rule file name, and again of those files, inside "
            f"{HELPER_FOLDERS}, without {list(EXCLUDED_MODULES)}. For "
            f"{LAYOUT_CONFIG_MODULE}: also the layout types of "
            "sqruff-lib/src/core/default_config.cfg. The base segment module "
            f"{BASE_MODULE} is not a helper module: it has the segment type "
            "and the generic methods that each rule uses (for example "
            "is_whitespace, is_meta, is_comment), not the logic of one rule. "
            "As a helper it would add the same names (base_module.names) to "
            "most rules and hide the names that are specific to each rule. "
            "base_module of a rule: true if a 'use' item of the rule file or "
            "of a helper module names it. The crates are those of "
            "the cargo cache; their sha256 is the checksum in the Cargo.lock "
            "of the sqruff crate. sqlfluff_types: the types and class types "
            "of each segment class, parser, and lexer of the dialects of the "
            "pinned sqlfluff, and of each segment class of the package."
        ),
        "rules": rows,
        "modules": dict(sorted(modules.items())),
        "base_module": {
            "file": BASE_MODULE,
            "names": type_names(strip_rust(crates[base_crate].files[base_file])),
        },
        "sqlfluff_types": sqlfluff_types(),
    }


# build: committed files -> OUT_FILE

T3_RENAME_CLASSES = ("renamed", "leaf_type", "keyword_vs_identifier")
NOT_TYPES = frozenset({"...", "-", "()"})
TREE_STATES_EQUAL = ("equal", EQUAL_IMPLICIT)
NON_CODE_OR_META = NON_CODE_TYPES | META_TYPES | {IMPLICIT[0]}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key_types(key: str) -> tuple[str, set[str]]:
    """Return the class of a T3 group key and the segment types that it
    changes. The parent type after " in " is the place, not a changed type,
    except for an unparsable key: "unparsable: <dialect>: <statement> in
    <segment>" names 2 sqlfluff types where sqruff fails."""
    cls, rest = key.split(": ", 1)
    if cls == "unsupported_dialect":
        return cls, set()
    if cls == "unparsable":
        rest = rest.split(": ", 1)[1].replace(" in ", " ")
    elif " in " in rest:
        rest = rest.rsplit(" in ", 1)[0]
    if cls == "nesting":
        rest = rest.split(" ", 1)[1]
    names = {t for t in re.split(r"\s+|->", rest) if t and t not in NOT_TYPES}
    return cls, names


def t3_types(trees: dict) -> dict[str, set[str]]:
    """Return {class: the types that its T3 group keys change}."""
    by_class: dict[str, set[str]] = {}
    for row in trees["cases"]:
        for key in row[3]:
            cls, names = key_types(key)
            by_class.setdefault(cls, set()).update(names)
    return by_class


def rule_names(types: dict, code: str) -> tuple[list[str], list[str]]:
    """Return (names of the rule file, names with the helper modules)."""
    row = types["rules"][code]
    names = set(row["names"])
    for mod in row["modules"]:
        entry = types["modules"][mod]
        names |= set(entry["names"]) | set(entry.get("layout_config", []))
    return row["names"], sorted(names)


def parse_key_types(parses: dict) -> set[str]:
    """Return the types that the group keys of PARSES_FILE change."""
    out: set[str] = set()
    for row in parses["cases"].values():
        for state in row["files"].values():
            for key in state[2]:
                out |= key_types(key)[1]
    return out


def coupling_rows(
    types: dict, sqlfluff: set[str], renamed: set[str], changed: set[str], base=False
) -> list[dict]:
    """Return a coupling row for each rule. base: add the names of the base
    segment module to the rules that use it."""
    rows = []
    for code in sorted(types["rules"]):
        direct, names = rule_names(types, code)
        if base and types["rules"][code]["base_module"]:
            names = sorted(set(names) | set(types["base_module"]["names"]))
        missing = [n for n in names if n not in sqlfluff]
        ren = [n for n in names if n in renamed]
        differs = sorted(set(missing) | set(ren))
        rows.append(
            {
                "code": code,
                "names": names,
                "direct": len(direct),
                "not_in_sqlfluff": missing,
                "renamed_in_t3": ren,
                "differ": len(differs),
                "differ_direct": len(set(direct) & set(differs)),
                "changed": sorted((set(names) & changed) | set(missing)),
                "non_code_or_meta": sorted(set(names) & NON_CODE_OR_META),
            }
        )
    return rows


def coupling(types: dict, trees: dict, parses: dict) -> dict:
    sqlfluff = set(types["sqlfluff_types"])
    by_class = t3_types(trees)
    renamed = set().union(*(by_class.get(c, set()) for c in T3_RENAME_CLASSES))
    changed = set().union(*by_class.values()) | parse_key_types(parses)
    rows = coupling_rows(types, sqlfluff, renamed, changed)
    for r in rows:
        names = set(r["names"])
        r["t3_cases"] = sum(
            1 for row in trees["cases"] if any(key_types(k)[1] & names for k in row[3])
        )
    all_names = set().union(*(set(r["names"]) for r in rows))
    base_rows = coupling_rows(types, sqlfluff, renamed, changed, base=True)
    return {
        "method": (
            "names: the segment types that a rule reads (TYPES_FILE: the "
            "SyntaxKind names of its file and of its helper modules, and the "
            "layout config types for the reflow rules). The base segment "
            f"module {BASE_MODULE} is not a helper module (TYPES_FILE "
            "'method'); 'sensitivity_base_module' gives the counts with its "
            "names for the rules that use it. direct: the count of "
            "names in the rule file. not_in_sqlfluff: names that are not a "
            "type of the sqlfluff 4.4.0 grammar (TYPES_FILE sqlfluff_types). "
            "renamed_in_t3: names in a T3 group key of the classes "
            f"{list(T3_RENAME_CLASSES)} (sqruff gives another type than "
            "sqlfluff at the same span). A key gives the 2 sides of a rename, "
            "and some are generic types (for example keyword, expression): "
            "the renamed counts are upper bounds. differ: the count of names "
            "in one of the 2 lists; differ_direct: of these, the names in the "
            "rule file. changed: not_in_sqlfluff and the names that a group "
            "key changes, of T3 (sqruff-tree-diffs.json) or of the T4 parses "
            f"({PARSES_FILE.name}); not the parent type of a key, but the 2 "
            "sqlfluff types of an unparsable key. If sqruff gave sqlfluff "
            "trees, a rule with a name in changed sees a changed tree. "
            "non_code_or_meta: the names of non-code and meta types "
            "(whitespace, newline, comments, indent, dedent, implicit, and "
            "others). The T3 dialect trees are code_only (the sqlfluff "
            "dialect test compares to_tuple(code_only=True)), thus they show "
            "no difference of these types. The T4 parses have them, but only "
            "for the SQL of the failed rule, autofix, and templater cases. "
            "Thus for these names, changed is a lower bound. t3_cases: the "
            "T3 cases (of 763) with a group key that changes a name of the "
            "rule. Limits: the names come from the source text, not from the "
            "calls at run time; a helper module can name a type for one "
            "caller and not for another; a rule also reads the parent and "
            "child order of a segment, which a name does not show."
        ),
        "estimates": {
            "fields": [
                "names",
                "renamed_in_t3",
                "differ",
                "changed",
                "t3_cases",
                "summary",
                "sensitivity_base_module",
            ],
            "note": (
                "Estimates: the helper modules come from a static closure of "
                "the 'use' items, not from the calls. The renamed counts are "
                "upper bounds. For non-code and meta names, changed is a "
                "lower bound: the rules that see no changed tree can see one "
                "on other SQL. direct, differ_direct, and the rule file names "
                "are measurements of the source text."
            ),
        },
        "row": list(rows[0]) if rows else [],
        "rules": rows,
        "summary": coupling_summary(rows, all_names, sqlfluff, renamed),
        "sensitivity_base_module": coupling_summary(
            base_rows,
            set().union(*(set(r["names"]) for r in base_rows)),
            sqlfluff,
            renamed,
        ),
    }


def coupling_summary(
    rows: list[dict], all_names: set[str], sqlfluff: set[str], renamed: set[str]
) -> dict:
    return {
        "rules": len(rows),
        "names": len(all_names),
        "names_not_in_sqlfluff": sorted(n for n in all_names if n not in sqlfluff),
        "names_renamed_in_t3": len(all_names & renamed),
        "rules_with_a_name_that_differs": sum(1 for r in rows if r["differ"]),
        "rules_with_a_name_that_differs_in_the_rule_file": sum(
            1 for r in rows if r["differ_direct"]
        ),
        "rules_that_see_a_changed_tree": sum(1 for r in rows if r["changed"]),
        "rules_that_see_no_changed_tree": [r["code"] for r in rows if not r["changed"]],
        "rules_with_a_non_code_or_meta_name": sum(
            1 for r in rows if r["non_code_or_meta"]
        ),
        "rules_with_no_name": [r["code"] for r in rows if not r["names"]],
    }


def check_inputs(parses: dict, cases_record: dict, scope: dict) -> list[str]:
    errors = []
    need = {
        cid
        for suite in SUITES
        for cid, reason in scope[suite].items()
        if not unsupported_group(reason)
    }
    got = set(parses["cases"])
    if got != need:
        errors.append(
            f"{PARSES_FILE.name} does not have the cases of known_failures/"
            f"sqruff.txt: missing {sorted(need - got)[:5]}, extra "
            f"{sorted(got - need)[:5]}"
        )
    rows = {r[0]: r for r in cases_record["cases"]}
    for suite in SUITES:
        for cid in scope[suite]:
            if cid not in rows or rows[cid][1] == "pass":
                errors.append(f"{cid}: not a failure in {CASES_FILE.name}")
    for cid, row in rows.items():
        suite = cid.split("/", 1)[0]
        if suite in SUITES and row[1] in ("fail", "error") and cid not in scope[suite]:
            errors.append(
                f"{cid}: a failure that known_failures/sqruff.txt does not have"
            )
    if parses["sqruff"] != SQRUFF_VERSION:
        errors.append(f"{PARSES_FILE.name}: sqruff {parses['sqruff']}")
    if parses["sqlfluff_ref"] != sqlfluff_ref(SQLFLUFF_ROOT):
        errors.append(f"{PARSES_FILE.name}: another sqlfluff commit")
    return errors


def failed_checks(suite: str, values: list) -> list[str]:
    if suite != "rules":
        return []
    return [c for c, v in zip(RULE_CHECKS, values, strict=True) if v == 0]


def relevant_files(suite: str, files: dict, failed: list[str]) -> list[str]:
    """The SQL files that the failed checks read. A case with no failed
    check (status error: a tool error) reads all its files."""
    if suite != "rules" or not failed:
        return sorted(files)
    return sorted({CHECK_FILES[c] for c in failed} & set(files))


def parse_kind(states: list[list]) -> str:
    classes = {c for s in states for c in s[1]}
    if any(s[0] == "no sqruff tree" for s in states):
        return "no sqruff tree"
    if any(s[0] not in ("differs",) + TREE_STATES_EQUAL for s in states):
        return "no sqlfluff tree"
    if "unparsable" in classes:
        return "unparsable"
    if classes == {"meta"}:
        return "meta only"
    if not classes:
        return "implicit indent name"
    return "other tree shape"


def logic_kind(suite: str, reason: str, failed: list[str], states: list[list]) -> str:
    if "panicked at" in reason:
        if any(s[3:] and s[3].startswith(NO_RULE_CONFIG) for s in states):
            return CONFIG_VALUE_PANIC
        return "panic"
    if suite == "rules":
        return " and ".join(failed) if failed else "error"
    return known_failures.reason_prefix(reason)


def classify(
    suite: str,
    reason: str,
    parsed: dict | None,
    values: list,
    implicit_differs=False,
    all_files=False,
):
    """Return (class, kind, files) of one failure."""
    group = unsupported_group(reason)
    if group:
        return "unsupported_item", group, []
    failed = failed_checks(suite, values)
    names = (
        sorted(parsed["files"])
        if all_files
        else relevant_files(suite, parsed["files"], failed)
    )
    states = [parsed["files"][n] for n in names]
    equal = (
        ("equal",) if (implicit_differs or suite == "templater") else TREE_STATES_EQUAL
    )
    differ = [s for s in states if s[0] not in equal]
    if differ:
        return "parse_cause", parse_kind(differ), names
    return "rule_logic", logic_kind(suite, reason, failed, states), names


def build(parses_path: Path = PARSES_FILE, types_path: Path = TYPES_FILE) -> dict:
    parses = json.loads(parses_path.read_text("utf8"))
    types = json.loads(types_path.read_text("utf8"))
    cases_record = json.loads(CASES_FILE.read_text("utf8"))
    trees = json.loads(TREES_FILE.read_text("utf8"))
    scope = failures()
    errors = check_inputs(parses, cases_record, scope)
    if types["sqruff"] != SQRUFF_VERSION:
        errors.append(f"{TYPES_FILE.name}: sqruff {types['sqruff']}")
    if errors:
        raise DataError("; ".join(errors[:10]))
    values = {r[0]: r[2] for r in cases_record["cases"]}
    rule_of = case_rules()
    rows = []
    counts = {s: Counter() for s in SUITES}
    kinds = {s: Counter() for s in SUITES}
    per_rule: dict[str, Counter] = {}
    per_code: dict[str, Counter] = {}
    sens = {
        "implicit_differs": Counter(),
        "all_files": Counter(),
        "config_value_panic_as_unsupported": Counter(),
    }
    reads = {}
    for suite in SUITES:
        for cid in sorted(scope[suite]):
            reason = scope[suite][cid]
            parsed = parses["cases"].get(cid)
            cls, kind, files = classify(suite, reason, parsed, values[cid])
            rule = rule_of.get(cid, "-")
            if parsed and parsed["rule"] != rule:
                raise DataError(
                    f"{cid}: rule {parsed['rule']} in {PARSES_FILE.name}, "
                    f"{rule} in the fixture"
                )
            counts[suite][cls] += 1
            kinds[suite][f"{cls}: {kind}"] += 1
            per_rule.setdefault(rule, Counter())[cls] += 1
            for code in rule.split(","):
                per_code.setdefault(code, Counter())[cls] += 1
            for name, flags in (
                ("implicit_differs", {"implicit_differs": True}),
                ("all_files", {"all_files": True}),
            ):
                sens[name][
                    classify(suite, reason, parsed, values[cid], **flags)[0]
                ] += 1
            sens["config_value_panic_as_unsupported"][
                "unsupported_item" if kind == CONFIG_VALUE_PANIC else cls
            ] += 1
            keys = (
                sorted({k for f in files for k in parsed["files"][f][2]})
                if parsed
                else []
            )
            rows.append([cid, suite, rule, cls, kind, files, keys])
            if cls == "parse_cause" and suite != "templater":
                reads[cid] = (rule, keys, kind)
    total = {cls: sum(counts[s][cls] for s in SUITES) for cls in CLASSES}
    for suite in SUITES:
        if sum(counts[suite].values()) != FAILURES[suite]:
            raise DataError(f"{suite}: the classes do not add up")
    estimate = touch_estimate(reads, types)
    return {
        "kind": "sqll-s3-sqruff-rule-diffs",
        "format": 1,
        "sqlfluff_ref": sqlfluff_ref(SQLFLUFF_ROOT),
        "sqruff": SQRUFF_VERSION,
        "commands": {
            "collect": COLLECT_COMMAND,
            "sources": SOURCES_COMMAND,
            "build": BUILD_COMMAND,
        },
        "inputs": {
            str(p.relative_to(ROOT)): _sha256(p)
            for p in (
                parses_path,
                types_path,
                CASES_FILE,
                TREES_FILE,
                KNOWN_FAILURES / "sqruff.txt",
            )
        },
        "scope": {
            "failures": dict(FAILURES),
            "note": (
                "The rules, autofix, and templater failures of "
                "known_failures/sqruff.txt (the S1 sqruff run; T2 per-case "
                "list results/s3/sqruff-cases.json)."
            ),
        },
        "method": (
            "Each failure has one class, in this order. 1. unsupported_item: "
            "the reason of known_failures/sqruff.txt is 'unsupported: <item>'; "
            "the group comes from the item. 2. parse_cause: a SQL file that a "
            "failed check reads (rules: pass_str reads pass, fail_str and fix "
            "read fail, after_fix reads fixed; a case with no failed check, a "
            "tool error, reads all its files; autofix: before.sql; templater: "
            "the case file) has another tree in sqruff than in sqlfluff "
            f"({PARSES_FILE.name}: the sqruff and sqlfluff parse of the file "
            "with the case config and with the meta segments). For rules and "
            "autofix, the meta type 'implicit' of sqruff is 'indent', the type "
            "that sqlfluff gives to ImplicitIndent. For templater, the suite "
            "compares the type names, so 'implicit' is a difference. 3. "
            "rule_logic: the other failures: the trees are equal, so the "
            "rule, fix, or config logic of sqruff gives another result. A tree "
            "difference does not prove that it causes the failure: the "
            "estimate 'touch' gives how many parse_cause cases change a type "
            "that the rule reads."
        ),
        "classes": CLASSES,
        "judgement": (
            "The class of each case follows the rule of 'method'; the "
            "unsupported_item counts are measurements. The split between "
            "parse_cause and rule_logic depends on 2 choices (the meta name "
            "'implicit' and the files of the failed checks): 'sensitivity' "
            "gives the counts with the other choices. The rule_logic cases of "
            f"kind '{CONFIG_VALUE_PANIC}' fail on a config value, not in the "
            "rule; they stay in rule_logic because the harness runs them "
            "(they are not 'unsupported:' in known_failures/sqruff.txt). "
            "'sensitivity' gives the counts with them in unsupported_item. "
            "That a tree difference causes the failure is an estimate "
            "('touch')."
        ),
        "counts": {s: {c: counts[s][c] for c in CLASSES} for s in SUITES},
        "total": total,
        "kinds": {s: dict(sorted(kinds[s].items())) for s in SUITES},
        "sensitivity": {
            "note": (
                "The class counts (all suites) with another rule. "
                "implicit_differs: 'implicit' is a tree difference also for "
                "rules and autofix. all_files: each file of a rule case, not "
                "only the files of the failed checks. "
                "config_value_panic_as_unsupported: the rule_logic cases of "
                f"kind '{CONFIG_VALUE_PANIC}' are unsupported_item. Estimates: "
                "they show how much the counts depend on these choices."
            ),
            **{k: {c: v[c] for c in CLASSES} for k, v in sens.items()},
        },
        "by_rule_note": (
            "by_rule: the key is the rule list of a case: rules: the rule "
            "codes of the case (can be a list); autofix: the rules of "
            "test-config.yml, or 'all'; templater: '-'. by_rule_code: for each "
            "single code, the cases whose rule list has the code; a case with "
            "N codes counts N times."
        ),
        "by_rule": {r: {c: per_rule[r][c] for c in CLASSES} for r in sorted(per_rule)},
        "by_rule_code": {
            r: {c: per_code[r][c] for c in CLASSES} for r in sorted(per_code)
        },
        "touch": estimate,
        "coupling": coupling(types, trees, parses),
        "row": [
            "id",
            "suite",
            "rule",
            "class",
            "kind",
            "files",
            "T3 group keys of the files",
        ],
        "cases": rows,
    }


def case_rules() -> dict[str, str]:
    """Return {case id: rule list} of the rules and autofix cases of the
    pinned fixtures (autofix: the rules of test-config.yml, or 'all')."""
    out = {
        c.id: ",".join(rules.rule_codes(c.rule)) for c in rules.discover(SQLFLUFF_ROOT)
    }
    for c in autofix.discover(SQLFLUFF_ROOT):
        out[c.id] = (
            autofix.load_test_config(c.folder / "test-config.yml").rules or "all"
        )
    return out


def touch_estimate(reads: dict, types: dict) -> dict:
    """For each parse_cause case of rules and autofix: does the tree
    difference change a type that the rules of the case read?"""
    out = Counter()
    for _cid, (rule, keys, kind) in reads.items():
        codes = list(types["rules"]) if rule == "all" else rule.split(",")
        names = set()
        for code in codes:
            if code in types["rules"]:
                names |= set(rule_names(types, code)[1])
        if kind in ("no sqruff tree", "unparsable"):
            out["no tree or unparsable"] += 1
        elif any(key_types(k)[1] & names for k in keys):
            out["changes a type that the rule reads"] += 1
        else:
            out["changes no type that the rule reads"] += 1
    return {
        "estimate": True,
        "note": (
            "An estimate of the share of parse_cause cases (rules and "
            "autofix) where the tree difference is a likely cause. A rule "
            "does not see a statement that sqruff does not parse or template. "
            "A difference that changes no name that the rule reads can still "
            "change its result (for example through the position of a meta "
            "or a parent)."
        ),
        **dict(sorted(out.items())),
    }


# Output.


def text(value: dict) -> str:
    return st.dumps(value) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sqruff_rules.py")
    sub = p.add_subparsers(dest="command", required=True)
    co = sub.add_parser(
        "collect", help="Write PARSES_FILE from sqruff and sqlfluff runs."
    )
    co.add_argument("--jobs", type=int, default=4)
    co.add_argument("--out", type=Path, default=PARSES_FILE)
    so = sub.add_parser(
        "sources", help="Write TYPES_FILE from the crates and sqlfluff."
    )
    so.add_argument(
        "--cache", type=Path, default=None, help="folder of the .crate files"
    )
    so.add_argument("--out", type=Path, default=TYPES_FILE)
    bd = sub.add_parser("build", help="Write OUT_FILE from the committed inputs.")
    bd.add_argument("--parses", type=Path, default=PARSES_FILE)
    bd.add_argument("--types", type=Path, default=TYPES_FILE)
    bd.add_argument("--out", type=Path, default=OUT_FILE)
    bd.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.command == "collect":
            args.out.write_text(text(collect(args.jobs)), "utf8")
            print(f"wrote {args.out}")
            return 0
        if args.command == "sources":
            args.out.write_text(text(sources(args.cache)), "utf8")
            print(f"wrote {args.out}")
            return 0
        new = text(build(args.parses, args.types))
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.check:
        if not args.out.exists() or args.out.read_text("utf8") != new:
            print(f"error: {args.out} is not the output of the build", file=sys.stderr)
            return 1
        print(f"{args.out}: no change")
        return 0
    args.out.write_text(new, "utf8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
