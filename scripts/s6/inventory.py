#!/usr/bin/env python3
"""Make the S6 fixture set from the data of the pinned sqlfluff
(docs/decisions/s6-templaters.md, "Set").

S6 (templater parity: sqll passes 100% of the placeholder and Python
format-string templater fixtures that do not need a Python runtime).

  uv run --frozen --project harness python scripts/s6/inventory.py          # JSON to stdout
  uv run --frozen --project harness python scripts/s6/inventory.py --write  # results/S6/scope.json

It reads the submodule in place. It does not copy or change a file. It runs
scripts/s6/unit_nodes.py with the Python of the sqlfluff oracle tools
(--python, default: <tools>/sqlfluff-oracle/bin/python) for the pytest
nodes of the placeholder and Python templater tests. Each other part comes
from the files:

  templater_suite  the S1 templater suite (sqll_harness.suites.templater):
                   each case, its templater, and its needs_python reasons
  nodes            each pytest node of the placeholder and Python templater
                   tests (scripts/s6/unit_nodes.py)
  rule_cases       each S1 rule fixture case that sets the placeholder or
                   python templater (sqll_harness.suites.rules)
  fixtures         each file in test/fixtures/templater/ that is not in a
                   Jinja folder, with its users
  fixture_configs  each other fixture file that sets these templaters
  other_tests      each other test file that names these templaters, with
                   its owner (OTHER_TESTS)

The exit code is 1 if a check fails (see "problems" in scope()): for
example a test file that names these templaters and has no owner in
OTHER_TESTS, or an owner of a file that does not name them.
"""

import argparse
import ast
import configparser
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT, sqlfluff_ref, tools_dir
from sqll_harness.suites import rules, templater

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s6common import runtime_needs  # noqa: E402

RECORDED = REPO_ROOT / "results" / "S6" / "scope.json"
UNIT_NODES = Path(__file__).resolve().parent / "unit_nodes.py"
FORMAT = 1
S6_TEMPLATERS = ("placeholder", "python")
JINJA_TEST = Path("test") / "core" / "templaters" / "jinja_test.py"
DEFAULT_CONFIG = Path("src") / "sqlfluff" / "core" / "default_config.cfg"
FIXTURES = Path("test") / "fixtures"
TEMPLATER_FIXTURES = FIXTURES / "templater"
# The reason of each templater suite case in the S6 known-failure list.
JINJA_REASON = "jinja: S11"

# A Python test file names the placeholder or python templater if one of
# these patterns is in its text.
TEST_PATTERNS = {
    "class": r"\b(PlaceholderTemplater|PythonTemplater)\b",
    "module": r"\btemplaters\.(placeholder|python)\b",
    "templater value": r"""["']templater["']\s*:\s*["'](placeholder|python)["']""",
    "config text": r"""templater(\s*=\s*|:)(placeholder|python)\b""",
    "config section": r"""["'](placeholder|python)["']\s*:\s*\{""",
    "templater option": r"""\.get\(\s*["']templater["']\s*\)""",
}
# A fixture file sets the placeholder or python templater if this pattern
# is in its text.
FIXTURE_PATTERN = re.compile(r"""templater(\s*[=:]\s*["']?|:)(placeholder|python)\b""")
S6_TEST_FILES = (
    "test/core/templaters/placeholder_test.py",
    "test/core/templaters/python_test.py",
)

# The owner of each other test file that names these templaters.
OTHER_TESTS = {
    "test/core/config/fluffconfig_test.py": (
        "S7 test conversion",
        "test/core/config/ is the S7 group config (results/S7-tests/scope.json);"
        " it checks the templater selection by name",
    ),
    "test/core/config/loader_test.py": (
        "S7 test conversion",
        "test/core/config/ is the S7 group config (results/S7-tests/scope.json);"
        " it checks the config loader and the context values of each templater",
    ),
    "test/core/linter/linter_test.py": (
        "out of scope",
        "python-internal: Linter.render_string with FluffConfig objects and a"
        " log capture; python is only the name of the other templater in the"
        " warning",
    ),
    "test/core/parser/lexer_test.py": (
        "out of scope",
        "python-internal: the PyRsLexer of sqlfluff[rs] lexes a TemplatedFile"
        " object; the placeholder templater only makes its input",
    ),
    "test/utils/reflow/respace_test.py": (
        "out of scope",
        "the key placeholder is the layout type of the Jinja placeholder"
        " segment, not the placeholder templater; Jinja is S11",
    ),
    "test/core/parser/parity/cases_test.py": (
        "out of scope",
        "engine-comparison of the Python and Rust engines of sqlfluff (the"
        " owner decision of S1, the binary test harness, on"
        " test/fixtures/parity/); the case option templater is only jinja",
    ),
    "test/core/parser/parity/compare.py": (
        "out of scope",
        "the helper of the parity tests: engine-comparison; it sets only the"
        " jinja templater",
    ),
}
# The owner of each other fixture file that sets these templaters, by path
# prefix.
FIXTURE_OWNERS = {
    "test/fixtures/rules/std_rule_cases/": (
        "S5",
        "rule fixture cases (rule_cases): their exit is S5; S6 checks their"
        " templated text and source slices",
    ),
    "test/fixtures/config/": (
        "S7 test conversion",
        "test__config__load_placeholder_cfg of test/core/config/loader_test.py"
        " reads it",
    ),
}


def run_unit_nodes(root: Path, python: Path) -> tuple[list[dict], list[str]]:
    if not python.exists():
        return [], [f"no oracle Python: {python} (run scripts/setup)"]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [str(python), str(UNIT_NODES), str(root)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        lines = [x for x in proc.stderr.splitlines() if x.startswith("error:")]
        return [], lines or [f"unit_nodes.py: exit code {proc.returncode}"]
    return json.loads(proc.stdout), []


def test_templater(root: Path) -> tuple[str | None, list[str]]:
    """The templater of the templater suite test: get_parsed uses Linter()
    with no argument, thus the default templater of sqlfluff."""
    tree = ast.parse((root / JINJA_TEST).read_text("utf8"))
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    get_parsed = [f for f in funcs if f.name == "get_parsed"]
    if len(get_parsed) != 1:
        return None, [f"{JINJA_TEST}: {len(get_parsed)} functions get_parsed"]
    calls = [
        n
        for n in ast.walk(get_parsed[0])
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "Linter"
    ]
    if len(calls) != 1 or calls[0].args or calls[0].keywords:
        return None, [f"{JINJA_TEST}: get_parsed does not call Linter() once"]
    cfg = configparser.ConfigParser()
    cfg.read_string((root / DEFAULT_CONFIG).read_text("utf8"))
    return cfg.get("sqlfluff", "templater", fallback=None), []


def suite_cases(root: Path) -> tuple[list[dict], list[str]]:
    name, problems = test_templater(root)
    out = []
    for case in templater.discover(root):
        out.append(
            {
                "id": case.id,
                "templater": name,
                "needs_python": templater.python_needs(root, case.sql),
                "known_failure": JINJA_REASON if name == "jinja" else None,
            }
        )
    return out, problems


def context_values(configs: dict | None, name: str) -> list:
    section = ((configs or {}).get("templater") or {}).get(name) or {}
    core = (configs or {}).get("core") or {}
    return [section, {k: v for k, v in core.items() if k == "library_path"}]


def rule_cases(root: Path) -> list[dict]:
    out = []
    for case in rules.discover(root):
        core = (case.configs or {}).get("core") or {}
        name = str(core.get("templater", "")).strip().lower()
        if name not in S6_TEMPLATERS:
            continue
        out.append(
            {
                "id": case.id,
                "rule": case.rule,
                "templater": name,
                "fix": case.fix_str is not None,
                "needs_python_runtime": runtime_needs(
                    context_values(case.configs, name)
                ),
                "owner": "S5",
            }
        )
    return out


def python_files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in (root / "test").rglob("*.py"))


def fixtures(root: Path, suite_ids: set[str]) -> tuple[list[dict], list[str]]:
    """Each file in a folder of test/fixtures/templater/ that is not a Jinja
    folder, with the test files that name its folder."""
    texts = {
        p.relative_to(root).as_posix(): p.read_text("utf8", errors="replace")
        for p in (root / "test").rglob("*")
        if p.is_file() and p.suffix in (".py", ".yml", ".yaml")
    }
    out, problems = [], []
    for folder in sorted((root / TEMPLATER_FIXTURES).iterdir()):
        if not folder.is_dir() or folder.name.startswith("jinja"):
            continue
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            rel = path.relative_to(root).as_posix()
            sub = path.relative_to(root / TEMPLATER_FIXTURES).with_suffix("")
            users = sorted(f for f, t in texts.items() if folder.name in t)
            in_suite = f"{templater.NAME}/{sub.as_posix()}" in suite_ids
            expected = path.with_suffix(".yml").exists()
            entry = {
                "path": rel,
                "in_suite": in_suite,
                "expected_output": expected,
                "users": users,
            }
            if not (in_suite or users or expected):
                entry["reason"] = (
                    "no test of sqlfluff 4.4.0 uses it, and it has no expected output"
                )
            else:
                problems.append(f"{rel}: a fixture with a user; give it an owner")
            out.append(entry)
    return out, problems


def fixture_configs(root: Path) -> tuple[list[dict], list[str]]:
    out, problems = [], []
    for path in sorted((root / FIXTURES).rglob("*")):
        rel = path.relative_to(root).as_posix()
        if (
            not path.is_file()
            or path.suffix == ".py"
            or rel.startswith("test/fixtures/dialects/")
        ):
            continue
        text = path.read_text("utf8", errors="replace")
        found = sorted({m.group(2) for m in FIXTURE_PATTERN.finditer(text)})
        if not found:
            continue
        owners = [v for k, v in FIXTURE_OWNERS.items() if rel.startswith(k)]
        if len(owners) != 1:
            problems.append(f"{rel}: sets the templater {found} and has no owner")
            continue
        owner, reason = owners[0]
        out.append({"path": rel, "templaters": found, "owner": owner, "reason": reason})
    return out, problems


def other_tests(root: Path) -> tuple[list[dict], list[str]]:
    out, problems = [], []
    for rel in python_files(root):
        if rel in S6_TEST_FILES:
            continue
        text = (root / rel).read_text("utf8")
        hits = sorted(k for k, p in TEST_PATTERNS.items() if re.search(p, text))
        if not hits:
            continue
        if rel not in OTHER_TESTS:
            problems.append(f"{rel}: names the templaters {hits} and has no owner")
            continue
        owner, reason = OTHER_TESTS[rel]
        out.append({"file": rel, "patterns": hits, "owner": owner, "reason": reason})
    found = {e["file"] for e in out}
    problems += [
        f"{f}: has an owner and does not name the templaters"
        for f in sorted(set(OTHER_TESTS) - found)
    ]
    return out, problems


def version(root: Path) -> str:
    text = (root / "pyproject.toml").read_text("utf8")
    match = re.search(r'^version = "([^"]+)"', text, re.M)
    return match.group(1) if match else "unknown"


def counts(out: dict) -> dict:
    suite = out["templater_suite"]
    by_templater = Counter(c["templater"] for c in suite)
    result = {
        "templater_suite": {
            "total": len(suite),
            "jinja": by_templater["jinja"],
            "placeholder": by_templater["placeholder"],
            "python": by_templater["python"],
            "needs_python": sum(1 for c in suite if c["needs_python"]),
        }
    }
    for name in S6_TEMPLATERS:
        nodes = [n for n in out["nodes"] if n["templater"] == name]
        result[f"{name}_nodes"] = {
            "total": len(nodes),
            "black_box": sum(1 for n in nodes if n["kind"] == "black_box"),
            "internal": sum(1 for n in nodes if n["kind"] == "internal"),
            "needs_python_runtime": sum(1 for n in nodes if n["needs_python_runtime"]),
        }
    rc = out["rule_cases"]
    result["rule_cases"] = {"total": len(rc)} | {
        name: sum(1 for c in rc if c["templater"] == name) for name in S6_TEMPLATERS
    }
    result["fixtures_not_in_set"] = sum(1 for f in out["fixtures"] if "reason" in f)
    result["fixture_configs"] = len(out["fixture_configs"])
    result["other_tests"] = len(out["other_tests"])
    kept = [n for n in out["nodes"] if not n["needs_python_runtime"]]
    result["s6_black_box"] = sum(1 for n in kept if n["kind"] == "black_box")
    result["s6_internal"] = sum(1 for n in kept if n["kind"] == "internal")
    return result


def scope(root: Path, python: Path) -> tuple[dict, list[str]]:
    problems: list[str] = []
    suite, p = suite_cases(root)
    problems += p
    nodes, p = run_unit_nodes(root, python)
    problems += p
    rc = rule_cases(root)
    fx, p = fixtures(root, {c["id"] for c in suite})
    problems += p
    fc, p = fixture_configs(root)
    problems += p
    ot, p = other_tests(root)
    problems += p
    rule_files = {
        f"{rules.FIXTURE_DIR.as_posix()}/{c['id'].split('/')[1]}.yml" for c in rc
    }
    config_rule_files = {f["path"] for f in fc if f["owner"] == "S5"}
    if rule_files != config_rule_files:
        problems.append(
            f"the rule case files {sorted(rule_files)} are not the rule fixture"
            f" files that set the templater {sorted(config_rule_files)}"
        )
    functions: dict[str, dict] = {}
    for n in nodes:
        key = f"{n['file']}::{n['function']}"
        entry = functions.setdefault(
            key,
            {
                "templater": n["templater"],
                "kind": n["kind"],
                "calls": n["calls"],
                "nodes": 0,
            },
        )
        if (entry["kind"], entry["calls"]) != (n["kind"], n["calls"]):
            problems.append(f"{key}: the nodes of one function have different kinds")
        entry["nodes"] += 1
    out = {
        "about": (
            "S6 (templater parity): the fixture set from the data of the pinned"
            " sqlfluff. Output of scripts/s6/inventory.py; see"
            " docs/decisions/s6-templaters.md, 'Set'."
        ),
        "format": FORMAT,
        "sqlfluff": version(root),
        "commit": sqlfluff_ref(root),
        "counts": {},
        "functions": functions,
        "templater_suite": suite,
        "nodes": nodes,
        "rule_cases": rc,
        "fixtures": fx,
        "fixture_configs": fc,
        "other_tests": ot,
    }
    out["counts"] = counts(out)
    return out, problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="inventory.py")
    parser.add_argument("--write", action="store_true", help=f"write {RECORDED}")
    parser.add_argument(
        "--root",
        type=Path,
        default=SQLFLUFF_ROOT,
        help="a sqlfluff checkout (for the unit tests; not with --write)",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=tools_dir() / "sqlfluff-oracle" / "bin" / "python",
        help="the Python of the sqlfluff oracle tools",
    )
    args = parser.parse_args(argv)
    if args.write and args.root.resolve() != SQLFLUFF_ROOT.resolve():
        parser.error("--write needs the pinned submodule")
    out, problems = scope(args.root.resolve(), args.python)
    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    if problems:
        return 1
    print(json.dumps(out["counts"]), file=sys.stderr)
    text = json.dumps(out, ensure_ascii=False, indent=1) + "\n"
    if args.write:
        RECORDED.parent.mkdir(parents=True, exist_ok=True)
        RECORDED.write_text(text, "utf8")
        print(f"wrote {RECORDED.relative_to(REPO_ROOT)}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
