"""S3b C14: the lint and fix path of the sqll adapter
(harness/sqll_harness/adapters/sqll.py; harness/sqll.md, "Adapter").

The tests use a fake sqll binary (a Python script), so they need no build.
They give each reason of Unsupported (the adapter stops before a run) and
the run path (the command lines and the reading of the output).
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import needs

from sqll_harness import cli
from sqll_harness.adapters import sqll as sqll_adapter
from sqll_harness.adapters.base import Unsupported
from sqll_harness.cases import FAIL, PASS
from sqll_harness.paths import REPO_ROOT, tools_dir
from sqll_harness.suites import rules as rules_suite

EVERY = ("AL01", "CP01", "CP03", "CP04", "LT01")
HAVE = ("CP01", "CP03", "CP04")
FAKE = """#!{python} -I
import json, os, sys
args = sys.argv[1:]
have, every = {have!r}, {every!r}
with open({log!r}, "a", encoding="utf8") as f:
    f.write(json.dumps([os.getcwd(), args]) + "\\n")
if args[:1] == ["rules"]:
    excluded = []
    if os.path.exists(".sqlfluff"):
        with open(".sqlfluff", encoding="utf8") as f:
            excluded = f.read().split("=")[1].strip().split(",")
    missing = [c for c in every if c not in have and c not in excluded]
    if missing:
        print("Error: unsupported: rules " + ", ".join(missing)
              + ": sqll does not have them yet (S5).", file=sys.stderr)
        sys.exit(2)
    print("==== sqlfluff - rules ====")
    for c in every:
        if c not in excluded:
            print(c + ": [name] A rule.\\n      groups: all")
    sys.exit(0)
files = [a for a in args if a.endswith(".sql")]
texts = {{p: open(p, encoding="utf8").read() for p in files}}
for text in texts.values():
    if "FAIL_CLOSED" in text:
        print("Error: unsupported: setting core:x = 1. sqll cannot do it.",
              file=sys.stderr)
        sys.exit(2)
    if "CRASH" in text:
        print("Error: cannot read the file", file=sys.stderr)
        sys.exit(3)
if args[0] == "lint":
    out = []
    for p, text in texts.items():
        found = [{{"code": "CP01", "start_line_no": 1, "start_line_pos": 1,
                   "description": "Keywords must be consistently upper case.",
                   "name": "capitalisation.keywords", "warning": False,
                   "fixes": [{{"type": "replace"}}]}}] if "select" in text else []
        out.append({{"filepath": p, "violations": found}})
    print(json.dumps(out))
    sys.exit(0)
if args[0] == "fix":
    for p, text in texts.items():
        with open(p, "w", encoding="utf8") as f:
            f.write(text.replace("select", "SELECT"))
    if any("GATE" in t for t in texts.values()):
        print("  [1 templating/parsing errors found]", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
if args[0] == "parse":
    print(json.dumps([{{"filepath": files[0], "segments": {{"file": {{}}}}}}]))
    sys.exit(0)
sys.exit(2)
"""


def fake_sqll(tmp_path: Path, have=HAVE, every=EVERY) -> tuple[Path, Path]:
    """Return (binary, log). The log has one line for each run: [cwd, args]."""
    log = tmp_path / "calls.jsonl"
    binary = tmp_path / "bin" / "sqll"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(
        FAKE.format(python=sys.executable, log=str(log), have=have, every=every)
    )
    binary.chmod(0o755)
    return binary, log


def calls(log: Path, command: str | None = None) -> list[list[str]]:
    if not log.exists():
        return []
    runs = [json.loads(line)[1] for line in log.read_text().splitlines()]
    return [r for r in runs if command is None or r[:1] == [command]]


def record(tmp_path: Path, *texts: str) -> Path:
    """A jinja as raw record with these texts."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "jinja-raw.json"
    equal = sorted(hashlib.sha256(t.encode("utf8")).hexdigest() for t in texts)
    path.write_text(json.dumps({"kind": sqll_adapter.JINJA_RAW_KIND, "equal": equal}))
    return path


def write(folder: Path, name: str, text: str | bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf8")
    return path


SQL = "select a from b\n"


@pytest.fixture
def adapter(tmp_path):
    binary, log = fake_sqll(tmp_path)
    a = sqll_adapter.SqllAdapter(binary, record(tmp_path, SQL))
    a.log = log
    return a


# The rules of sqll.


def test_the_rules_come_from_sqll_rules(adapter, tmp_path):
    have, every = adapter.rules()
    assert (sorted(have), sorted(every)) == (sorted(HAVE), sorted(EVERY))
    # The first run fails closed and names the rules that sqll does not
    # have; the second excludes them. The result is kept.
    adapter.rules()
    assert calls(adapter.log) == [["rules", "--nocolor"]] * 2
    # A sqll with each rule: one run.
    binary, log = fake_sqll(tmp_path / "all", have=EVERY)
    assert sqll_adapter.SqllAdapter(binary).rules() == (
        frozenset(EVERY),
        frozenset(EVERY),
    )
    assert len(calls(log)) == 1


def test_a_failed_rules_command_is_an_error(tmp_path):
    bad = write(tmp_path / "bin", "sqll", "#!/bin/sh\necho 'Error: no' >&2\nexit 2\n")
    bad.chmod(0o755)
    with pytest.raises(RuntimeError, match="sqll rules: exit code 2: Error: no"):
        sqll_adapter.SqllAdapter(bad).rules()


# Each reason of Unsupported. No lint, fix, or parse runs.


def test_a_rule_that_sqll_does_not_have(adapter, tmp_path):
    sql = write(tmp_path / "w", "a.sql", SQL)
    with pytest.raises(Unsupported) as exc:
        adapter.lint([sql], ["CP01", "LT01", "AL01"], "ansi", None, tmp_path / "w")
    assert exc.value.item == "rule LT01, AL01"
    with pytest.raises(Unsupported) as exc:
        adapter.fix(sql, ["LT01"], "ansi", None, tmp_path / "w")
    assert exc.value.item == "rule LT01"
    with pytest.raises(Unsupported) as exc:
        adapter.fix_file(sql, ["LT01"], "ansi", tmp_path / "w")
    assert exc.value.item == "rule LT01"
    with pytest.raises(Unsupported) as exc:
        adapter.check_case_rules(["CV06"])
    assert exc.value.item == "rule CV06"
    assert calls(adapter.log) == calls(adapter.log, "rules")


def test_a_case_with_no_string_needs_the_rule(adapter):
    # The sqlfluff test checks nothing for an empty pass_str (CV06). The
    # case is still unsupported: sqll does not have the rule.
    case = rules_suite.RuleCase(id="rules/CV06/x", rule="LT01", pass_str="")
    with pytest.raises(Unsupported) as exc:
        rules_suite.run(adapter, case, REPO_ROOT)
    assert exc.value.item == "rule LT01"
    case = rules_suite.RuleCase(id="rules/CP01/x", rule="CP01", pass_str="")
    assert rules_suite.run(adapter, case, REPO_ROOT).status == PASS


@pytest.mark.parametrize(
    "config, item",
    [
        ({"core": {"templater": "placeholder"}}, "templater placeholder"),
        ({"core": {"templater": "python"}}, "templater python"),
        (
            {"templater": {"jinja": {"context": {"a": 1}}}},
            "templater jinja with settings (the jinja as raw record has only the "
            "default settings)",
        ),
        (
            {"core": {"library_path": "libs"}},
            "templater jinja with settings (the jinja as raw record has only the "
            "default settings)",
        ),
    ],
)
def test_a_templater_that_can_give_another_file(adapter, tmp_path, config, item):
    sql = write(tmp_path / "w", "a.sql", SQL)
    with pytest.raises(Unsupported) as exc:
        adapter.lint([sql], ["CP01"], "ansi", config, tmp_path / "w")
    assert exc.value.item == item
    assert calls(adapter.log, "lint") == []


def test_a_jinja_text_that_is_not_in_the_record(adapter, tmp_path):
    work = tmp_path / "w"
    good = write(work, "good.sql", SQL)
    other = write(work, "other.sql", "select b from c\n")
    for config in (None, {"core": {"templater": "jinja"}}):
        with pytest.raises(Unsupported) as exc:
            adapter.lint([good, other], ["CP01"], "ansi", config, work)
        assert exc.value.item == (
            "templater jinja: other.sql is not a text of the jinja as raw record "
            "(results/S3b/C14-jinja-raw.json)"
        )
    # A text of the record with another newline is another text.
    crlf = write(work, "crlf.sql", SQL.replace("\n", "\r\n").encode())
    with pytest.raises(Unsupported, match="crlf.sql is not a text"):
        adapter.fix(crlf, ["CP01"], "ansi", None, work)
    bad = write(work, "bad.sql", b"select \xff\n")
    with pytest.raises(Unsupported) as exc:
        adapter.fix(bad, ["CP01"], "ansi", None, work)
    assert exc.value.item == "templater jinja: bad.sql is not UTF-8"
    # The raw templater gives the file of sqll: no record needed.
    assert adapter.lint([other], ["CP01"], "ansi", {"core": {"templater": "raw"}}, work)
    assert len(calls(adapter.log, "lint")) == 1


@pytest.mark.parametrize(
    "content", ["", "{}", '{"kind": "other", "equal": []}', '{"kind": "x"']
)
def test_with_no_valid_record_each_jinja_case_is_unsupported(tmp_path, content):
    binary, log = fake_sqll(tmp_path)
    path = write(tmp_path, "record.json", content)
    adapter = sqll_adapter.SqllAdapter(binary, path)
    sql = write(tmp_path / "w", "a.sql", SQL)
    with pytest.raises(Unsupported, match="a.sql is not a text"):
        adapter.lint([sql], ["CP01"], "ansi", None, tmp_path / "w")
    missing = sqll_adapter.SqllAdapter(binary, tmp_path / "no-record.json")
    with pytest.raises(Unsupported, match="a.sql is not a text"):
        missing.lint([sql], ["CP01"], "ansi", None, tmp_path / "w")
    assert calls(log, "lint") == []


def test_an_in_file_config_line(tmp_path):
    binary, log = fake_sqll(tmp_path)
    text = "select a\n--sqlfluff:dialect:tsql\n"
    adapter = sqll_adapter.SqllAdapter(binary, record(tmp_path, text))
    sql = write(tmp_path / "w", "a.sql", text)
    with pytest.raises(Unsupported) as exc:
        adapter.lint([sql], ["CP01"], "ansi", None, tmp_path / "w")
    assert exc.value.item == "in-file config line 2 of a.sql"
    with pytest.raises(Unsupported, match="in-file config line 2"):
        adapter.parse_file(sql, "ansi", tmp_path / "w")
    assert calls(log, "lint") == calls(log, "parse") == []


def test_a_setting_that_sqll_cannot_do(tmp_path):
    # sqll checks the settings itself: exit code 2 and "unsupported: ...".
    binary, log = fake_sqll(tmp_path)
    text = "select 1 -- FAIL_CLOSED\n"
    adapter = sqll_adapter.SqllAdapter(binary, record(tmp_path, text))
    work, user = tmp_path / "w", tmp_path / "user"
    sql = write(work, "a.sql", text)
    own = write(user, "a.sql", text)
    runs = [
        lambda: adapter.lint([sql], ["CP01"], "ansi", {"core": {"x": 1}}, work),
        lambda: adapter.fix(sql, ["CP01"], "ansi", None, work),
        lambda: adapter.parse_file(own, "ansi", user),
        lambda: adapter.fix_file(own, ["CP01"], "ansi", user),
    ]
    for run in runs:
        with pytest.raises(Unsupported) as exc:
            run()
        assert exc.value.item == "setting core:x = 1"
    assert [r[0] for r in calls(log) if r[0] != "rules"] == [
        "lint",
        "fix",
        "parse",
        "fix",
    ]


def test_an_output_that_sqll_does_not_give(adapter, tmp_path):
    sql = write(tmp_path / "w", "a.sql", SQL)
    with pytest.raises(Unsupported) as exc:
        adapter.fix_file(sql, ["CP01"], "ansi", tmp_path / "w", show_violations=True)
    assert exc.value.item == (
        "output field violations of a fix (sqll fix has no --show-lint-violations)"
    )
    with pytest.raises(Unsupported) as exc:
        adapter.parse_file(sql, "ansi", tmp_path / "w", include_meta=True)
    assert exc.value.item == "output field source positions (sqll parse -m gives none)"
    assert calls(adapter.log, "fix") == calls(adapter.log, "parse") == []


def test_the_user_config_of_a_run_as_a_user(adapter, tmp_path):
    cwd = tmp_path / "cwd"
    sql = write(tmp_path / "case", "a.sql", SQL)
    write(cwd, ".sqlfluff", "[sqlfluff]\ndialect = ansi\n")
    # The templater of the file config is not that of the working folder.
    write(tmp_path / "case", ".sqlfluff", "[sqlfluff]\ntemplater = raw\n")
    with pytest.raises(Unsupported) as exc:
        adapter.parse_file(sql, "ansi", cwd)
    assert exc.value.item == (
        "templater raw in the config of the file (sqlfluff uses jinja, the "
        "templater of the working folder)"
    )
    write(
        tmp_path / "case",
        ".sqlfluff",
        "[sqlfluff:templater:jinja]\napply_dbt_builtins = False\n",
    )
    with pytest.raises(Unsupported, match="templater jinja with settings"):
        adapter.fix_file(sql, ["CP01"], "ansi", cwd)
    write(tmp_path / "case", ".sqlfluff", "")
    write(
        tmp_path / "case", "pyproject.toml", '[tool.sqlfluff.core]\ndialect = "ansi"\n'
    )
    with pytest.raises(Unsupported, match="^setting: .*tool.sqlfluff"):
        adapter.parse_file(sql, "ansi", cwd)
    write(cwd, ".sqlfluff", "[sqlfluff]\ntemplater = placeholder\n")
    (tmp_path / "case" / "pyproject.toml").unlink()
    with pytest.raises(Unsupported) as exc:
        adapter.parse_file(sql, "ansi", cwd)
    assert exc.value.item == "templater placeholder"
    assert calls(adapter.log, "fix") == calls(adapter.log, "parse") == []


# The run path.


def test_lint_runs_sqll_lint_as_the_sqlfluff_adapter(adapter, tmp_path):
    work = tmp_path / "w"
    a = write(work, "a.sql", SQL)
    b = write(work, "b.sql", SQL)
    config = {"core": {"dialect": "ansi"}, "rules": {"capitalisation.keywords": {}}}
    result = adapter.lint([a, b], ["CP01", "CP03"], None, config, work)
    (args,) = calls(adapter.log, "lint")
    assert args == [
        "lint",
        "-f",
        "json",
        "--nofail",
        "--ignore-local-config",
        "--encoding",
        "utf-8",
        "--rules",
        "CP01,CP03",
        "--config",
        str(work / "pyproject.toml"),
        "a.sql",
        "b.sql",
    ]
    assert (work / "pyproject.toml").read_text().startswith("[tool.sqlfluff.core]\n")
    assert result.errors == [] and result.rc == 0
    assert set(result.violations) == {a, b}
    assert [v["code"] for v in result.violations[a]] == ["CP01"]
    # With no config: --dialect and no --config file.
    adapter.lint([a], ["CP01"], "tsql", None, work)
    args = calls(adapter.log, "lint")[-1]
    assert args[-4:] == ["CP01", "--dialect", "tsql", "a.sql"]


def test_fix_runs_sqll_fix_and_reads_the_file(adapter, tmp_path):
    work = tmp_path / "w"
    sql = write(work, "fix.sql", SQL)
    result = adapter.fix(sql, ["CP01"], "ansi", None, work)
    assert calls(adapter.log, "fix")[-1] == [
        "fix",
        "--ignore-local-config",
        "--encoding",
        "utf-8",
        "--rules",
        "CP01",
        "--dialect",
        "ansi",
        "fix.sql",
    ]
    assert result.fixed == "SELECT a from b\n"
    assert (result.errors, result.critical, result.rc) == ([], [], 0)


def test_a_failed_run_is_an_error_not_a_pass(tmp_path):
    binary, _ = fake_sqll(tmp_path)
    text = "select 1 -- CRASH\n"
    adapter = sqll_adapter.SqllAdapter(binary, record(tmp_path, text))
    work = tmp_path / "w"
    sql = write(work, "a.sql", text)
    lint = adapter.lint([sql], ["CP01"], "ansi", None, work)
    assert lint.violations is None
    assert lint.errors == [
        "no JSON lint output",
        "exit code 3: Error: cannot read the file",
    ]
    fix = adapter.fix(sql, ["CP01"], "ansi", None, work)
    assert fix.fixed is None and fix.errors == [
        "exit code 3: Error: cannot read the file"
    ]
    result = adapter.fix_file(sql, ["CP01"], "ansi", work)
    assert result.errors == ["exit code 3: Error: cannot read the file"]


def test_parse_file_and_fix_file_run_as_a_user(adapter, tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    sql = write(tmp_path / "case", "testing.sql", SQL)
    parsed = adapter.parse_file(sql, "ansi", cwd, code_only=True)
    assert calls(adapter.log, "parse")[-1] == [
        "parse",
        "-f",
        "json",
        "-c",
        "--dialect",
        "ansi",
        str(sql),
    ]
    assert parsed.tree == {"file": {}} and parsed.errors == []
    result = adapter.fix_file(sql, ["CP01", "CP04"], "ansi", cwd)
    assert calls(adapter.log, "fix")[-1] == [
        "fix",
        "--nocolor",
        "--dialect",
        "ansi",
        "--rules",
        "CP01,CP04",
        str(sql),
    ]
    assert result.errors == [] and not result.unparsable_gate
    assert sql.read_text() == "SELECT a from b\n"
    # With no rules: the rules of the config files; sqll fails closed on a
    # rule that it does not have.
    sql.write_text(SQL, encoding="utf8")
    adapter.fix_file(sql, None, "ansi", cwd)
    assert "--rules" not in calls(adapter.log, "fix")[-1]


def test_fix_file_reads_the_unparsable_gate(tmp_path):
    binary, _ = fake_sqll(tmp_path)
    text = "select 1 -- GATE\n"
    adapter = sqll_adapter.SqllAdapter(binary, record(tmp_path, text))
    sql = write(tmp_path / "case", "a.sql", text)
    result = adapter.fix_file(sql, ["CP01"], "ansi", tmp_path)
    assert result.unparsable_gate and result.errors == []


def test_a_rule_case_runs_through_the_suite(adapter, tmp_path):
    # The rules suite with an invented CP01 case: the fake gives a CP01
    # violation for "select" and fixes it.
    case = rules_suite.RuleCase(
        id="rules/CP01/invented",
        rule="CP01",
        fail_str=SQL,
        fix_str="SELECT a from b\n",
    )
    adapter.jinja_record = record(tmp_path, SQL, "SELECT a from b\n")
    sqll_adapter.jinja_raw_texts.cache_clear()
    result = cli._run_one(rules_suite, adapter, case, REPO_ROOT)
    assert (result.status, result.reason) == (PASS, "")
    assert result.checks == {"fail_str": True, "fix": True, "after_fix": True}
    # lint of fail.sql and fixed.sql, then fix of fix.sql.
    assert [r[0] for r in calls(adapter.log) if r[0] != "rules"] == ["lint", "fix"]
    # Another fixed text: the fix check fails.
    other = rules_suite.RuleCase(
        id="rules/CP01/other", rule="CP01", fail_str=SQL, fix_str=SQL.upper()
    )
    adapter.jinja_record = record(tmp_path / "r2", SQL, SQL.upper())
    result = cli._run_one(rules_suite, adapter, other, REPO_ROOT)
    assert (result.status, result.checks["fix"]) == (FAIL, False)
    assert result.reason.startswith("fix mismatch")


# The oracle check of the sqll passes (scripts/sqlfluff_oracle.py).


@needs("sqlfluff-oracle/bin/python")
def test_the_oracle_checks_each_pass_of_a_tool(tmp_path):
    report = tmp_path / "report.json"
    cases = [
        {"id": "rules/CP01/a", "suite": "rules", "tool": "sqll", "status": "pass"},
        {"id": "rules/CP01/b", "suite": "rules", "tool": "sqll", "status": "fail"},
        {"id": "rules/CP01/c", "suite": "rules", "tool": "sqll", "status": "pass"},
    ]
    report.write_text(json.dumps({"cases": cases}))
    code = (
        "import json, sys; sys.path.insert(0, 'scripts');"
        "from sqlfluff_oracle import check_passes;"
        "oracle = json.loads(sys.argv[2]);"
        "oracle = {k: tuple(v) for k, v in oracle.items()};"
        "tools = json.loads(sys.argv[3]);"
        "sys.exit(check_passes(oracle, __import__('pathlib').Path(sys.argv[1]),"
        " 'rules', tools))"
    )
    python = tools_dir() / "sqlfluff-oracle" / "bin" / "python"

    def run(oracle: dict, tools: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                code,
                str(report),
                json.dumps(oracle),
                json.dumps(tools),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    ok = {i: ["pass", ""] for i in ("rules/CP01/a", "rules/CP01/b", "rules/CP01/c")}
    proc = run(ok, ["sqll"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "sqll rules: 3 cases, 2 pass, 2 of them pass in the oracle\n"
    # A pass of sqll that the oracle does not pass.
    proc = run({**ok, "rules/CP01/c": ["fail", "AssertionError: x"]}, ["sqll"])
    assert proc.returncode == 1
    assert "  rules/CP01/c: sqll pass, oracle fail (AssertionError: x)\n" in proc.stdout
    # A tool with no case in the report fails; no tool checks nothing.
    assert run(ok, ["sqruff"]).returncode == 1
    assert run(ok, []).returncode == 0
