"""S3b task C12: the sqlfluff data of the rule and fix interface
(docs/interfaces/rules.md).

Run it with the harness Python from the repository root:

    uv run --frozen --project harness python scripts/s3b/rules_oracle.py record
    uv run --frozen --project harness python scripts/s3b/rules_oracle.py check

Both run the pinned sqlfluff of the tool venv (tools/sqlfluff). The data:

- rules: the manifest of each rule of the sqlfluff rule set (code, name,
  description, groups, aliases, lint phase, fix flag, config keywords,
  targets_templated, template_safe_fixes, and the crawler). The registry of
  sqll_lint (src/sqlfluff.rs) has the same table; the interface test
  crates/sqll_interfaces/tests/rules.rs compares them.
- config_info: the "validation" of each rule config keyword that has one (a
  list of values, or a range as {"range": [start, stop]}).
- cases: for each case of the rule fixtures RULE_FIXTURES (the YAML of the
  submodule), the sqlfluff answers that the rule test helper
  (sqlfluff.utils.testing.rules) uses: the violations of pass_str (lint),
  of fail_str (lint with fix), and of fix_str (lint with fix), and the
  fixed text of fail_str (fix_string). A violation is [code, start line,
  start position, end line, end position, description, fixable].

record: write RECORD_FILE.
table: print the Rust table of RULES_RS from RECORD_FILE (write it to
RULES_RS after a record).
check (CI job build): make the data again; it must be the text of
RECORD_FILE, the counts must be those of COUNTS, and RULES_RS must be the
table of the record. The Rust tests
(crates/sqll_interfaces/tests/rules.rs, crates/sqll_rules/tests/fixtures.rs)
read RECORD_FILE (cargo test).

Exit code: 0 pass, 1 a failure.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQLFLUFF_ROOT = ROOT / "third_party" / "sqlfluff"
RECORD_FILE = ROOT / "results" / "S3b" / "C12-rules.json"
RULES_RS = ROOT / "crates" / "sqll_lint" / "src" / "sqlfluff.rs"
KIND = "sqll-s3b-c12-rules"
FORMAT = 1
COMMAND = "uv run --frozen --project harness python scripts/s3b/rules_oracle.py"
RULE_FIXTURES = (
    "test/fixtures/rules/std_rule_cases/CP01.yml",
    "test/fixtures/rules/std_rule_cases/CP03.yml",
    "test/fixtures/rules/std_rule_cases/CP04.yml",
)
# The counts of the record (docs/interfaces/rules.md, "Proof").
COUNTS = {"rules": 79, "config_info": 37, "cases": 51}


class DataError(Exception):
    """A step failed, or the data do not agree."""


# The data, made with the sqlfluff Python (the "dump" command).


def crawler_data(crawler) -> dict:
    out = {
        "type": type(crawler).__name__,
        "works_on_unparsable": crawler.works_on_unparsable,
    }
    if hasattr(crawler, "types"):
        out["types"] = sorted(crawler.types)
        out["allow_recurse"] = crawler.allow_recurse
    return out


def rules_data() -> list[dict]:
    from sqlfluff.core.rules import get_ruleset

    out = []
    for code, manifest in sorted(get_ruleset()._register.items()):
        cls = manifest.rule_class
        out.append(
            {
                "code": code,
                "name": manifest.name,
                "description": manifest.description,
                "groups": list(manifest.groups),
                "aliases": list(manifest.aliases),
                "lint_phase": cls.lint_phase,
                "is_fix_compatible": cls.is_fix_compatible,
                "config_keywords": list(cls.config_keywords),
                "targets_templated": cls.targets_templated,
                "template_safe_fixes": cls.template_safe_fixes,
                "crawler": crawler_data(cls.crawl_behaviour),
            }
        )
    return out


def config_info_data() -> dict:
    from sqlfluff.core.rules.config_info import get_config_info

    out = {}
    for key, info in sorted(get_config_info().items()):
        valid = info.get("validation")
        if valid is None:
            continue
        if isinstance(valid, range):
            if valid.step != 1:
                raise DataError(f"{key}: a range with a step")
            out[key] = {"range": [valid.start, valid.stop]}
        else:
            out[key] = list(valid)
    return out


def violations(linted) -> list[list]:
    out = []
    for v in linted.get_violations():
        d = v.to_dict()
        out.append(
            [
                d["code"],
                d["start_line_no"],
                d["start_line_pos"],
                d.get("end_line_no"),
                d.get("end_line_pos"),
                d["description"],
                bool(getattr(v, "fixes", None)),
            ]
        )
    return out


def case_data(rule: str, name: str, case: dict) -> dict:
    from sqlfluff.core import Linter
    from sqlfluff.utils.testing.rules import _setup_config

    configs = case.get("configs")
    out = {"rule": rule, "name": name}
    if "pass_str" in case:
        cfg = _setup_config(rule, configs)
        out["pass"] = violations(
            Linter(config=cfg).lint_string(case["pass_str"], fname="<STR>")
        )
    if "fail_str" in case:
        cfg = _setup_config(rule, configs)
        linted = Linter(config=cfg).lint_string(case["fail_str"], fix=True)
        out["fail"] = violations(linted)
        out["fixed"] = linted.fix_string()[0]
    if "fix_str" in case:
        cfg = _setup_config(rule, configs)
        linted = Linter(config=cfg).lint_string(case["fix_str"], fix=True)
        out["after_fix"] = violations(linted)
    return out


def cases_data() -> list[dict]:
    import yaml

    out = []
    for rel in RULE_FIXTURES:
        y = yaml.safe_load((SQLFLUFF_ROOT / rel).read_text(encoding="utf8"))
        rule = y.pop("rule")
        global_config = y.pop("configs", None)
        for name, case in y.items():
            if global_config and "configs" not in case:
                case["configs"] = global_config
            out.append(case_data(rule, name, case))
    return out


def dump() -> dict:
    import sqlfluff

    return {
        "sqlfluff": sqlfluff.__version__,
        "rules": rules_data(),
        "config_info": config_info_data(),
        "cases": cases_data(),
    }


# The commands of the harness Python.


def run_dump() -> dict:
    sys.path.insert(0, str(ROOT / "harness"))
    from sqll_harness.paths import tools_dir

    python = tools_dir() / "sqlfluff" / "bin" / "python"
    if not python.is_file():
        raise DataError(f"no sqlfluff Python at {python} (scripts/setup)")
    argv = [str(python), "-I", "-B", str(Path(__file__).resolve()), "dump"]
    print(f"rules_oracle: $ {' '.join(argv)}", flush=True)
    out = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=False)
    if out.returncode != 0:
        raise DataError(f"dump: exit code {out.returncode}\n{out.stderr[-4000:]}")
    return json.loads(out.stdout)


def submodule_commit() -> str:
    out = subprocess.run(
        ["git", "-C", str(SQLFLUFF_ROOT), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    return out.stdout.strip()


def counts(data: dict) -> dict:
    return {
        "rules": len(data["rules"]),
        "config_info": len(data["config_info"]),
        "cases": len(data["cases"]),
    }


def record_data(data: dict) -> dict:
    return {
        "kind": KIND,
        "format": FORMAT,
        "about": (
            "S3b C12: the rule manifest, the config validation, and the answers "
            "of the rule test helper for the CP01, CP03, and CP04 rule fixtures "
            "of the pinned sqlfluff (scripts/s3b/rules_oracle.py; "
            "docs/interfaces/rules.md). A violation: [code, start line, start "
            "position, end line, end position, description, fixable]. pass: the "
            "violations of pass_str (lint); fail and fixed: the violations of "
            "fail_str (lint with fix) and its fixed text; after_fix: the "
            "violations of fix_str (lint with fix)."
        ),
        "command": f"{COMMAND} record",
        "sqlfluff": {"version": data["sqlfluff"], "commit": submodule_commit()},
        "fixtures": list(RULE_FIXTURES),
        "counts": counts(data),
        "config_info": data["config_info"],
        "rules": data["rules"],
        "cases": data["cases"],
    }


def dumps(record: dict) -> str:
    """JSON with one line for each rule and each case."""
    lines = ["{"]
    keys = list(record)
    for k, key in enumerate(keys):
        end = "," if k < len(keys) - 1 else ""
        if key not in ("rules", "cases"):
            lines.append(
                f" {json.dumps(key)}: {json.dumps(record[key], ensure_ascii=False)}{end}"
            )
            continue
        lines.append(f" {json.dumps(key)}: [")
        items = record[key]
        for i, item in enumerate(items):
            sep = "," if i < len(items) - 1 else ""
            lines.append(f"  {json.dumps(item, ensure_ascii=False)}{sep}")
        lines.append(" ]" + end)
    lines.append("}")
    return "\n".join(lines) + "\n"


def rust_str(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def rust_strs(items: list[str]) -> str:
    return "&[" + ", ".join(rust_str(i) for i in items) + "]"


def rust_value(v) -> str:
    if isinstance(v, bool):
        return f"Valid::Bool({'true' if v else 'false'})"
    if isinstance(v, str):
        return f"Valid::Str({rust_str(v)})"
    raise DataError(f"a validation value of the type {type(v).__name__}")


def copyright_line() -> str:
    """The sqlfluff copyright line of crates/ported.json."""
    ported = json.loads((ROOT / "crates" / "ported.json").read_text(encoding="utf8"))
    return ported["source"]["copyright"]


def table(record: dict) -> str:
    """The Rust file RULES_RS: the rule manifest and the config validation
    of the record."""
    out = [
        "// Parts of this file are a port of sqlfluff 4.4.0 code (data): the rule",
        "// manifest of src/sqlfluff/rules/ and the validation lists of the rule",
        "// config info.",
        "// Source: https://github.com/sqlfluff/sqlfluff, tag 4.4.0,",
        f"// commit {record['sqlfluff']['commit']}.",
        f"// {copyright_line()}. MIT License: see",
        "// crates/LICENSE-sqlfluffrs.md. See THIRD_PARTY.md.",
        "",
        "//! The rule manifest and the rule config validation of sqlfluff 4.4.0",
        "//! (docs/interfaces/rules.md). Made from results/S3b/C12-rules.json by",
        f"//! `{COMMAND} table`; do not edit.",
        "",
        "use crate::config::{Valid, Validation};",
        "use crate::rule::LintPhase;",
        "",
        "/// The manifest of one sqlfluff rule.",
        "#[derive(Clone, Copy, Debug, PartialEq, Eq)]",
        "pub struct SqlfluffRule {",
        "    pub code: &'static str,",
        "    pub name: &'static str,",
        "    pub description: &'static str,",
        "    pub groups: &'static [&'static str],",
        "    pub aliases: &'static [&'static str],",
        "    pub lint_phase: LintPhase,",
        "    pub is_fix_compatible: bool,",
        "    pub config_keywords: &'static [&'static str],",
        "    pub targets_templated: bool,",
        "}",
        "",
        "/// Each rule of sqlfluff 4.4.0, in code order.",
        "#[rustfmt::skip]",
        "pub const RULES: &[SqlfluffRule] = &[",
    ]
    for r in record["rules"]:
        phase = {"main": "Main", "post": "Post"}[r["lint_phase"]]
        out += [
            "    SqlfluffRule {",
            f"        code: {rust_str(r['code'])},",
            f"        name: {rust_str(r['name'])},",
            f"        description: {rust_str(r['description'])},",
            f"        groups: {rust_strs(r['groups'])},",
            f"        aliases: {rust_strs(r['aliases'])},",
            f"        lint_phase: LintPhase::{phase},",
            f"        is_fix_compatible: {str(r['is_fix_compatible']).lower()},",
            f"        config_keywords: {rust_strs(r['config_keywords'])},",
            f"        targets_templated: {str(r['targets_templated']).lower()},",
            "    },",
        ]
    out += [
        "];",
        "",
        "/// The validation of each rule config keyword that has one, in key order.",
        "#[rustfmt::skip]",
        "pub const CONFIG_VALIDATION: &[(&str, Validation)] = &[",
    ]
    for key, valid in record["config_info"].items():
        if isinstance(valid, dict):
            start, stop = valid["range"]
            v = f"Validation::Range({start}, {stop})"
        else:
            v = "Validation::Values(&[" + ", ".join(rust_value(x) for x in valid) + "])"
        out.append(f"    ({rust_str(key)}, {v}),")
    out += ["];", ""]
    return "\n".join(out)


def problems_of(data: dict) -> list[str]:
    got = counts(data)
    return [] if got == COUNTS else [f"the counts are {got}, not {COUNTS}"]


def record() -> int:
    data = run_dump()
    RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECORD_FILE.write_text(dumps(record_data(data)), encoding="utf8")
    print(f"rules_oracle: wrote {RECORD_FILE.relative_to(ROOT)}")
    problems = problems_of(data)
    for p in problems:
        print(f"rules_oracle: {p}")
    return 1 if problems else 0


def check() -> int:
    data = run_dump()
    problems = problems_of(data)
    want = dumps(record_data(data))
    if not RECORD_FILE.is_file() or RECORD_FILE.read_text(encoding="utf8") != want:
        problems.append(
            f"{RECORD_FILE.relative_to(ROOT)} is not the sqlfluff data ({COMMAND} record)"
        )
    clean = subprocess.run(
        [str(ROOT / "scripts" / "check-submodule"), "after the rules data"],
        check=False,
    )
    if clean.returncode != 0:
        problems.append("the sqlfluff run changed the submodule")
    if not RULES_RS.is_file() or RULES_RS.read_text(encoding="utf8") != table(
        record_data(data)
    ):
        problems.append(
            f"{RULES_RS.relative_to(ROOT)} is not the table of the record ({COMMAND} table)"
        )
    for p in problems:
        print(f"rules check: {p}")
    if problems:
        print(f"rules check: FAIL: {len(problems)} problems")
        return 1
    c = counts(data)
    print(
        f"rules check: PASS: {c['rules']} rules, {c['config_info']} validated "
        f"config keywords, {c['cases']} rule fixture cases"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("record", help="write the record file")
    sub.add_parser("check", help="check the record and the table")
    sub.add_parser("table", help="print the Rust table of the record")
    sub.add_parser("dump", help="(sqlfluff Python) print the data as JSON")
    args = parser.parse_args(argv)
    try:
        if args.command == "dump":
            json.dump(dump(), sys.stdout)
            return 0
        if args.command == "record":
            return record()
        if args.command == "table":
            sys.stdout.write(table(json.loads(RECORD_FILE.read_text(encoding="utf8"))))
            return 0
        return check()
    except DataError as e:
        print(f"rules_oracle: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
