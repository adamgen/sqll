# The checks in this file are a port of sqlfluff 4.4.0 code:
# test/core/templaters/jinja_test.py (get_parsed, assert_structure,
# test__templater_full). Copyright (c) 2018-2026 Alan Cruickshank.
# MIT License. See THIRD_PARTY.md.
"""Templater suite: the cases of test__templater_full in sqlfluff.

The case table is the parametrize list of test__templater_full in
test/core/templaters/jinja_test.py. The harness reads it from the submodule
with the ast module. See harness/templater.md.
"""

import ast
import configparser
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..adapters import Adapter
from ..cases import ERROR, FAIL, PASS, CaseResult
from ..compare import has_node, load_yaml, record_to_test_tuple, strip_positions

NAME = "templater"
TEST_FILE = Path("test") / "core" / "templaters" / "jinja_test.py"
TEST_NAME = "test__templater_full"
ARGNAMES = "subpath,code_only,include_meta"
FIXTURE_DIR = Path("test") / "fixtures" / "templater"
NEEDS_PYTHON = "needs_python"
# The config files that sqlfluff reads in each folder, in the order of
# load_config_at_path. A later file overrides an earlier one.
CONFIG_FILES = ("setup.cfg", "tox.ini", "pep8.ini", ".sqlfluff", "pyproject.toml")
# Templaters that run Python code of the user or need a Python package.
PYTHON_TEMPLATERS = ("python", "dbt")


class TableError(Exception):
    """The case table of the sqlfluff test is not as the harness expects."""


@dataclass(frozen=True)
class TemplaterCase:
    """One row of the table: the test parses <subpath>.sql and compares the
    tree with <subpath>.yml. tags has "needs_python" if the case needs a
    Python runtime (see python_needs)."""

    id: str
    subpath: str
    code_only: bool
    include_meta: bool
    tags: tuple[str, ...] = field(default=())

    @property
    def sql(self) -> Path:
        return FIXTURE_DIR / f"{self.subpath}.sql"

    @property
    def yml(self) -> Path:
        return FIXTURE_DIR / f"{self.subpath}.yml"


def _is_parametrize(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "parametrize"
        and ast.unparse(node.func) == "pytest.mark.parametrize"
    )


def read_table(test_file: Path) -> list[tuple[str, bool, bool]]:
    """Return the parametrize list of test__templater_full in test_file.

    Only literal Python is evaluated. Each other form is a TableError: an
    entry that is not a literal, another decorator, ids, or other argnames.
    """
    where = str(test_file)
    tree = ast.parse(test_file.read_text(encoding="utf8"), filename=where)
    funcs = [
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == TEST_NAME
    ]
    if len(funcs) != 1:
        raise TableError(f"{where}: {len(funcs)} functions named {TEST_NAME}")
    decorators = funcs[0].decorator_list
    if len(decorators) != 1 or not _is_parametrize(decorators[0]):
        raise TableError(f"{where}: {TEST_NAME} must have only one parametrize")
    call = decorators[0]
    assert isinstance(call, ast.Call)
    if call.keywords or len(call.args) != 2:
        raise TableError(f"{where}:{call.lineno}: parametrize has other arguments")
    argnames, values = call.args
    if not (isinstance(argnames, ast.Constant) and argnames.value == ARGNAMES):
        raise TableError(f"{where}:{call.lineno}: argnames are not {ARGNAMES!r}")
    if not isinstance(values, ast.List):
        raise TableError(f"{where}:{values.lineno}: the values are not a list")
    rows = []
    for elt in values.elts:
        try:
            row = ast.literal_eval(elt)
        except ValueError as exc:
            raise TableError(
                f"{where}:{elt.lineno}: entry is not a literal: {ast.unparse(elt)}"
            ) from exc
        if not (
            isinstance(row, tuple)
            and len(row) == 3
            and isinstance(row[0], str)
            and all(type(x) is bool for x in row[1:])
        ):
            raise TableError(f"{where}:{elt.lineno}: entry is not (str, bool, bool)")
        rows.append(row)
    return rows


def discover(sqlfluff_root: Path) -> list[TemplaterCase]:
    """Return one case for each row of the table, in the order of the table."""
    cases = []
    for subpath, code_only, include_meta in read_table(sqlfluff_root / TEST_FILE):
        needs = python_needs(sqlfluff_root, FIXTURE_DIR / f"{subpath}.sql")
        cases.append(
            TemplaterCase(
                id=f"{NAME}/{subpath}",
                subpath=subpath,
                code_only=code_only,
                include_meta=include_meta,
                tags=(NEEDS_PYTHON,) if needs else (),
            )
        )
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        raise TableError(f"{sqlfluff_root / TEST_FILE}: two rows give one case id")
    return cases


def _read_config(path: Path) -> dict[tuple[str, ...], Any]:
    """Return {(section, ..., key): value} of a sqlfluff config file.

    Sections are as sqlfluff reads them: [sqlfluff] is ("core",) and
    [sqlfluff:a:b] is ("a", "b"). In pyproject.toml, tool.sqlfluff is core.
    """
    flat: dict[tuple[str, ...], Any] = {}
    if path.name == "pyproject.toml":

        def walk(prefix: tuple[str, ...], data: dict) -> None:
            for key, value in data.items():
                if isinstance(value, dict):
                    walk(prefix + (key,), value)
                else:
                    flat[(prefix or ("core",)) + (key,)] = value

        data = tomllib.loads(path.read_text(encoding="utf8"))
        walk((), data.get("tool", {}).get("sqlfluff", {}))
        return flat
    parser = configparser.ConfigParser(delimiters="=", interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read_string(path.read_text(encoding="utf8"))
    for section in parser.sections():
        if section == "sqlfluff":
            prefix: tuple[str, ...] = ("core",)
        elif section.startswith("sqlfluff:"):
            prefix = tuple(section[len("sqlfluff:") :].split(":"))
        else:
            continue
        for key, value in parser.items(section):
            flat[prefix + (key,)] = value
    return flat


def _inline_config(sql: str) -> dict[tuple[str, ...], str]:
    """Return the in-file config lines of a SQL file, for example
    "-- sqlfluff:templater:jinja:library_path:libs".

    As in sqlfluff (process_raw_file_for_config), a config line starts with
    "-- sqlfluff" or "--sqlfluff", with no space before it.
    """
    flat: dict[tuple[str, ...], str] = {}
    for line in sql.splitlines():
        if not line.startswith(("-- sqlfluff", "--sqlfluff")):
            continue
        text = line[2:].strip()
        if not text.startswith("sqlfluff:"):
            continue
        *keys, value = (part.strip() for part in text[len("sqlfluff:") :].split(":"))
        if keys:
            flat[(("core",) if len(keys) == 1 else ()) + tuple(keys)] = value
    return flat


def python_needs(sqlfluff_root: Path, sql: Path) -> list[str]:
    """Return why the case needs a Python runtime, or an empty list.

    The harness reads the config files in each folder between sqlfluff_root
    and the folder of sql, as the tool does when sqlfluff_root is its current
    folder, then the in-file config lines of sql. A later file overrides an
    earlier one. A case needs Python if it sets
    library_path (Python modules for the jinja templater), or uses the
    python or dbt templater.
    """
    config: dict[tuple[str, ...], Any] = {}
    folder = sqlfluff_root
    for part in (None, *sql.parent.parts):
        if part is not None:
            folder = folder / part
        for name in CONFIG_FILES:
            if (folder / name).is_file():
                config.update(_read_config(folder / name))
    if (sqlfluff_root / sql).is_file():
        config.update(_inline_config((sqlfluff_root / sql).read_text(encoding="utf8")))
    needs = []
    library_paths = [
        str(v)
        for k, v in config.items()
        if k[-1] == "library_path" and (k[0] == "core" or k[0] == "templater")
    ]
    if any(v.strip() and v.strip().lower() != "none" for v in library_paths):
        needs.append("library_path")
    templater = str(config.get(("core", "templater"), "")).strip().lower()
    if templater in PYTHON_TEMPLATERS:
        needs.append(f"templater {templater}")
    return needs


def _result(case: TemplaterCase, adapter: Adapter, status: str, **kw) -> CaseResult:
    return CaseResult(case.id, NAME, adapter.name, status, **kw)


def run(adapter: Adapter, case: TemplaterCase, sqlfluff_root: Path) -> CaseResult:
    """Run one case as test__templater_full in sqlfluff does.

    The test parses the file with Linter() and parse_path, with the sqlfluff
    root as the current folder. The tool reads the config files as for a
    user, with the same current folder and the same relative path. The
    harness gives no dialect and no templater.

    The test fails if the full tree has an unparsable segment, or if the tree
    (code_only, include_meta) is not equal to the YAML tree. With code_only
    the tool output does not show all segments, so the harness parses again
    with no -c for the unparsable check.
    """
    if not (sqlfluff_root / case.sql).is_file():
        return _result(case, adapter, FAIL, reason=f"the test fails: no {case.sql}")
    parsed = adapter.parse_file(
        case.sql,
        None,
        sqlfluff_root,
        code_only=case.code_only,
        include_meta=case.include_meta,
    )
    full = parsed
    if case.code_only:
        full = adapter.parse_file(case.sql, None, sqlfluff_root)
    errors = [f"parse: {e}" for e in parsed.errors]
    if full is not parsed:
        errors += [f"parse with no -c: {e}" for e in full.errors]
    if errors:
        return _result(case, adapter, ERROR, reason="; ".join(errors))
    if (parsed.tree is None) != (full.tree is None):
        return _result(
            case, adapter, ERROR, reason="only one of the 2 parse runs gave a tree"
        )
    if parsed.tree is None:
        return _result(
            case,
            adapter,
            FAIL,
            checks={"exact": False, "no_unparsable": False},
            reason="no tree; the test fails ('tree' is None)",
        )

    no_unparsable = not has_node(full.tree, "unparsable")
    checks = {"exact": False, "no_unparsable": no_unparsable}
    reasons = [] if no_unparsable else ["unparsable segment"]
    try:
        _, expected = load_yaml(sqlfluff_root / case.yml)
    except (
        OSError,
        ValueError,
        TypeError,
        IndexError,
        AttributeError,
        yaml.YAMLError,
    ) as exc:
        reasons.append(f"the test fails: {case.yml}: {type(exc).__name__}: {exc}")
        return _result(case, adapter, FAIL, checks=checks, reason="; ".join(reasons))
    try:
        record = strip_positions(parsed.tree) if case.include_meta else parsed.tree
        actual = record_to_test_tuple(record)
    except (ValueError, TypeError, IndexError) as exc:
        return _result(
            case, adapter, ERROR, reason=f"cannot read the tree: {exc}", checks={}
        )
    checks["exact"] = actual == expected
    if not checks["exact"]:
        reasons.append("tree differs")
    status = PASS if all(checks.values()) else FAIL
    return _result(case, adapter, status, checks=checks, reason="; ".join(reasons))
