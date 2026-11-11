"""The S7 scope (docs/decisions/s7-tests-design.md, "Scope").

results/S7-tests/scope.json must be the output of scripts/s7-tests/inventory
on the pinned submodule, and the counts in the documents must be its
counts. results/S7-tests/config-readers.json and config-readers-rs.json (the run
checks of the config_fixtures rule, with sqlfluff and with sqlfluff[rs])
must name only nodes in scope.
"""

import json
import os
import re
import subprocess
import textwrap
from collections import Counter
from pathlib import Path

import pytest
import yaml
from conftest import needs

from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT, tools_dir

INVENTORY = REPO_ROOT / "scripts" / "s7-tests" / "inventory"
CONFIG_READERS = REPO_ROOT / "scripts" / "s7-tests" / "config-readers"
RESULTS = REPO_ROOT / "results" / "S7-tests"
SCOPE_FILE = RESULTS / "scope.json"
SCOPE = json.loads(SCOPE_FILE.read_text("utf8"))
READERS = json.loads((RESULTS / "config-readers.json").read_text("utf8"))
READERS_RS = json.loads((RESULTS / "config-readers-rs.json").read_text("utf8"))
DESIGN = (REPO_ROOT / "docs" / "decisions" / "s7-tests-design.md").read_text("utf8")
STATUS = (REPO_ROOT / "status" / "S7-tests.md").read_text("utf8")
INDEX = (REPO_ROOT / "STATUS.md").read_text("utf8")

# The S7 scope of sqlfluff 4.4.0.
COUNTS = {"cli": 295, "rules": 208, "config": 137, "config_fixtures": 3}
RUST_DISPATCH = 102
ENGINE_COMPARISON = 87  # the fix_parity nodes of the Rust dispatch tests
oracle = needs("sqlfluff-oracle/bin/python")


def run_script(script: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    python = tools_dir() / "sqlfluff-oracle" / "bin" / "python"
    return subprocess.run(
        [str(python), str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def differences(recorded: str, output: str) -> list[str]:
    """What is different between the recorded scope and a new output."""
    if recorded == output:
        return []
    a, b = json.loads(recorded), json.loads(output)
    out = [f"key {k}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    ids_a = Counter(n["id"] for n in a.get("nodes", []))
    ids_b = Counter(n["id"] for n in b.get("nodes", []))
    out += [f"only recorded: {i}" for i in sorted((ids_a - ids_b).elements())]
    out += [f"only output: {i}" for i in sorted((ids_b - ids_a).elements())]
    return out or ["the text is different"]


# The recorded scope is the inventory output.


@oracle
def test_recorded_scope_is_the_inventory_output():
    proc = run_script(INVENTORY)
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert differences(SCOPE_FILE.read_text("utf8"), proc.stdout) == []
    check = subprocess.run(
        [str(REPO_ROOT / "scripts" / "check-submodule"), "after the inventory"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stderr


def test_a_changed_scope_is_not_the_inventory_output():
    text = SCOPE_FILE.read_text("utf8")
    assert differences(text, text) == []
    data = json.loads(text)
    dropped = dict(data, nodes=data["nodes"][1:])
    assert differences(text, json.dumps(dropped, indent=1) + "\n") == [
        "key nodes",
        f"only recorded: {data['nodes'][0]['id']}",
    ]
    moved = json.loads(text)
    moved["nodes"][0]["group"] = "config"
    assert differences(text, json.dumps(moved, indent=1) + "\n") == ["key nodes"]
    assert differences(text, text.replace("\n", "\n ", 1)) == ["the text is different"]


@oracle
@pytest.mark.parametrize("option", ["--root", "--readers"])
def test_write_needs_the_pinned_submodule(tmp_path, option):
    proc = run_script(INVENTORY, "--write", option, str(tmp_path))
    assert proc.returncode == 2
    assert "--write needs the pinned submodule and the recorded runs" in proc.stderr


# The recorded scope and its counts.


def test_counts():
    groups = Counter(n["group"] for n in SCOPE["nodes"])
    assert dict(groups) == COUNTS
    assert SCOPE["counts"] == COUNTS | {"total": sum(COUNTS.values())}
    assert SCOPE["sqlfluff"] == "4.4.0"
    files = Counter((n["file"], n["group"]) for n in SCOPE["nodes"])
    assert SCOPE["files"] == {
        f: {"group": g, "nodes": c} for (f, g), c in files.items()
    }
    assert len({n["id"] for n in SCOPE["nodes"]}) == len(SCOPE["nodes"])
    for node in SCOPE["nodes"]:
        assert node["id"].split("::")[0] == node["file"]


def test_group_folders():
    prefixes = {
        "cli": "test/cli/",
        "rules": "test/rules/",
        "config": "test/core/config/",
    }
    for node in SCOPE["nodes"]:
        prefix = prefixes.get(node["group"])
        if prefix:
            assert node["file"].startswith(prefix), node
        else:
            assert not any(node["file"].startswith(p) for p in prefixes.values()), node


def test_by_path_file_and_s1_suites():
    assert SCOPE["python_files"] == ["*_test.py"]
    assert SCOPE["collected_by_path"] == ["test/cli/test_parse_with_positions.py"]
    assert SCOPE["files"]["test/cli/test_parse_with_positions.py"]["nodes"] == 10
    # The case counts of the S1 suites (harness/tests/test_case_counts.py).
    assert SCOPE["s1_suites"] == {
        "test/rules/yaml_test_cases_test.py::test__rule_test_case": {
            "suite": "rules",
            "nodes": 2527,
        },
        "test/rules/std_fix_auto_test.py::test__std_fix_auto": {
            "suite": "autofix",
            "nodes": 61,
        },
    }
    ids = {n["id"].split("[")[0] for n in SCOPE["nodes"]}
    assert not ids & set(SCOPE["s1_suites"])


def test_rust_dispatch_nodes():
    nodes = [n["id"] for n in SCOPE["nodes"] if "_rust_dispatch_test.py" in n["file"]]
    assert len(nodes) == RUST_DISPATCH
    assert sum("_dispatch__fix_parity[" in n for n in nodes) == ENGINE_COMPARISON


def test_config_fixture_nodes():
    nodes = {
        n["id"]: n["by"] for n in SCOPE["nodes"] if n["group"] == "config_fixtures"
    }
    assert nodes == {
        "test/core/helpers/file_test.py::test__config__iter_config_paths"
        "[test/fixtures/config/inheritance_a/nested/blah.sql-test/fixtures-result0]": [
            "source"
        ],
        "test/core/helpers/file_test.py::test__config__iter_config_paths"
        "[test/fixtures-test/fixtures/config/inheritance_a-result1]": ["source"],
        "test/core/linter/discovery_test.py::test__linter__path_from_paths__dot": [
            "run"
        ],
    }
    assert all("by" not in n for n in SCOPE["nodes"] if n["group"] != "config_fixtures")
    assert SCOPE["collection_errors"] == [
        {
            "file": "test/dialects/bigquery_test.py",
            "error": "ModuleNotFoundError: No module named 'hypothesis'",
            "names_config_fixtures": False,
        }
    ]
    # The file that pytest cannot import reads no file: no name of a fixture
    # folder, and no call that opens or lists a path.
    text = (SQLFLUFF_ROOT / "test" / "dialects" / "bigquery_test.py").read_text("utf8")
    for word in ("fixtures", "open(", "listdir", "scandir", "glob", "Path("):
        assert word not in text, word


RUNS = {"sqlfluff": READERS, "sqlfluff-rs": READERS_RS}


@pytest.mark.parametrize("name", RUNS)
def test_config_readers_are_in_scope(name):
    record = RUNS[name]
    run = {n["id"] for n in SCOPE["nodes"] if "run" in n.get("by", [])}
    assert set(record["readers"]) == run
    assert record["format"] == 2
    assert record["sqlfluff"] == SCOPE["sqlfluff"]
    assert record["skipped_folders"] == ["test/cli", "test/rules", "test/core/config"]
    assert record["collection_errors"] == {
        e["file"]: e["error"] for e in SCOPE["collection_errors"]
    }


def test_config_readers_runs():
    # Without sqlfluff[rs], most skipped nodes need the Rust parser. With it,
    # they run, and the run finds the same readers.
    assert READERS["sqlfluffrs"] is None
    assert READERS["outcomes"] == {"failed": 3, "passed": 8268, "skipped": 2529}
    assert READERS_RS["sqlfluffrs"] == SCOPE["sqlfluff"]
    assert READERS_RS["outcomes"] == {"failed": 3, "passed": 10792, "skipped": 5}
    for key in ("failed", "collection_lists", "traced_processes", "readers"):
        assert READERS_RS[key] == READERS[key], key


def test_config_readers_collection_lists_each_folder():
    # In the collection, pytest lists each folder of the tree.
    config = SQLFLUFF_ROOT / "test" / "fixtures" / "config"
    folders = [config, *(p for p in config.rglob("*") if p.is_dir())]
    want = sorted(p.relative_to(SQLFLUFF_ROOT).as_posix() for p in folders)
    assert READERS["collection_lists"] == want


def test_failed_nodes_of_the_run_do_not_name_the_folder():
    # A node that fails can stop before a read. These nodes fail because the
    # example plugin (plugins/sqlfluff-plugin-example) is not installed in
    # the oracle tools.
    assert READERS["failed"] == [
        "test/core/plugin_test.py::test__plugin_default_config_read"
        "[Example_L001-forbidden_columns]",
        "test/core/plugin_test.py::test__plugin_example_rules_returned"
        "[Rule_Example_L001]",
        "test/core/plugin_test.py::test__plugin_manager_registers_example_plugin",
    ]
    text = (SQLFLUFF_ROOT / "test" / "core" / "plugin_test.py").read_text("utf8")
    assert "fixtures/config" not in text
    assert not re.search(r"[\"']config[\"']", text)


def test_config_readers_traced_processes():
    # The nodes that start a new Python process. The trace sees each of
    # them (scripts/s7-tests/config-readers fails closed on a program that
    # it does not see).
    assert READERS["traced_processes"] == {
        "test/core/linter/linter_test.py::"
        "test__linter__linting_result_get_violations[2]": 3,
        "test/core/parser/parity/special_cases_test.py::"
        "test__parity__codegen_lexer_patterns_hash_seed_stable": 3,
        **{
            "test/diff_quality_plugin_test.py::test_diff_quality_plugin"
            f"[sql_paths{i}-expected_violations_lines{i}]": 1
            for i in range(5)
        },
    }


# The documents give the counts of scope.json.


def _table(text: str, title: str) -> dict[str, int]:
    start = text.index(f"\n## {title}\n")
    end = text.find("\n## ", start + 1)
    rows = {}
    for line in text[start:end].splitlines():
        m = re.match(r"\| `?([a-z_]+)`? \| (\d+) \|", line)
        if m:
            rows[m.group(1)] = int(m.group(2))
    return rows


@pytest.mark.parametrize("name", ["design", "status"])
def test_documents_give_the_counts(name):
    text = {"design": DESIGN, "status": STATUS}[name]
    assert _table(text, "Scope") == SCOPE["counts"]
    words = " ".join(text.split())
    assert f"{RUST_DISPATCH} nodes" in words
    assert f"{ENGINE_COMPARISON} of them" in words


def _section(text: str, title: str) -> str:
    start = text.index(f"\n## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end]


def _words(text: str) -> str:
    return " ".join(text.split())


def test_status_has_each_task():
    # The plan of 2026-11-11: T1 to T15, and T15 is the exit task. Each row
    # has a goal (AGENTS.md, "Names").
    table = _section(STATUS, "S7-tests tasks").splitlines()
    rows = [r for r in table if r.startswith("|")]
    assert rows[0] == "| Task | Description | Goal | State |"
    cells = [[c.strip() for c in r.strip("|").split(" | ")] for r in rows[2:]]
    assert [c[0] for c in cells] == [f"T{n}" for n in range(1, 16)]
    assert all(len(c) == 4 and all(c) for c in cells), cells
    assert cells[-1][1].startswith("S7 test conversion exit")
    words = _words(DESIGN)
    assert "Only T1 and T15 change the S7 test conversion row" in words
    assert "At T15 (the exit task" in words
    assert "T16" not in DESIGN + STATUS


def _outcomes(record: dict) -> str:
    o = record["outcomes"]
    return f"{o['passed']} passed, {o['failed']} failed, {o['skipped']} skipped"


def _rule_cases(rule: str) -> tuple[int, int]:
    """The S1 data cases of a rule, and the cases with a fix_str."""
    path = SQLFLUFF_ROOT / "test" / "fixtures" / "rules" / "std_rule_cases"
    data = yaml.safe_load((path / f"{rule}.yml").read_text("utf8"))
    cases = [v for k, v in data.items() if k != "rule"]
    return len(cases), sum("fix_str" in case for case in cases)


@pytest.mark.parametrize("name", ["design", "status"])
def test_documents_record_the_decisions(name):
    # The 4 decisions of the orchestrator (2026-11-11) and their data.
    text = {"design": DESIGN, "status": STATUS}[name]
    decisions = _words(_section(text, "Decisions"))
    assert "on 2026-11-11 for the human owner" in decisions
    assert "(standing delegation, CONSTITUTION.md section 5)" in decisions
    counts = SCOPE["counts"]
    assert ", ".join(f"`{g}` {counts[g]}" for g in COUNTS) in decisions
    assert f"total {counts['total']}" in decisions
    assert f"sqlfluff {_outcomes(READERS)};" in decisions
    assert f"`sqlfluff[rs]` {_outcomes(READERS_RS)}." in decisions
    parity = Counter(
        n["file"].split("/")[-1][:4]
        for n in SCOPE["nodes"]
        if "_dispatch__fix_parity[" in n["id"]
    )
    assert sum(parity.values()) == ENGINE_COMPARISON
    per_file = ", ".join(f"{f} {parity[f]}" for f in ("cp01", "cp03", "cp04"))
    assert f"The {ENGINE_COMPARISON} `fix_parity` nodes ({per_file})" in decisions
    n, fixes = _rule_cases("CP01")
    assert f"`CP01.yml` {n} cases ({fixes} with `fix_str`)" in decisions
    for rule in ("CP03", "CP04"):
        n, fixes = _rule_cases(rule)
        assert f"`{rule}.yml` {n} ({fixes})" in decisions, rule
    for item in (
        "1. Scope rule: ACCEPT. Do not make `config_fixtures` wider.",
        "2. The 4 exclusion classes: ACCEPT, with these conditions",
        "its node id and its class, apart from parity",
        "`needs-python-runtime` and `environment` node has a reason of one line",
        "the in-scope total, the converted count, and the excluded count",
        "3. Rust dispatch: Option A.",
        "compares `use_rust_rules` True and False and has no expected value",
        "on 4937 cases",
        "the 3 `ignore_words_parity` nodes",
        "A mock or spy node is `python-internal`.",
        "A node with an expected value that the CLI shows is converted.",
        "4. Pointer section in `harness/not-reproduced.md`: ACCEPT.",
        "merges before an S7 case uses a not-reproduced record",
    ):
        assert item in decisions, item
    assert "open decision" not in _words(text).lower()
    assert _words(DESIGN).startswith(
        "# S7 decision: the test conversion design Status: decided (2026-11-11)."
    )


def test_status_index_row():
    rows = [r for r in INDEX.splitlines() if r.startswith("| S7 test conversion |")]
    assert rows == [
        "| S7 test conversion | S7-tests | In work (track S7-tests) "
        "| [status/S7-tests.md](status/S7-tests.md) |"
    ]


# Fail-closed checks of the inventory, with a small tree in the sqlfluff
# layout.

PYPROJECT = '[tool.pytest.ini_options]\npython_files = "*_test.py"\n'
BASE = {
    "pyproject.toml": PYPROJECT,
    "test/__init__.py": "",
    "test/cli/__init__.py": "",
    "test/cli/a_test.py": "def test_a():\n    pass\n",
    "test/cli/test_by_path.py": "def test_b():\n    pass\n",
    "test/cli/helper.py": "X = 1\n",
    "test/rules/__init__.py": "",
    "test/rules/yaml_test_cases_test.py": """
        import pytest
        @pytest.mark.parametrize("x", [1, 2])
        def test__rule_test_case(x):
            pass
        def test_other():
            pass
    """,
    "test/rules/std_fix_auto_test.py": "def test__std_fix_auto():\n    pass\n",
    "test/core/__init__.py": "",
    "test/core/config/__init__.py": "",
    "test/core/config/c_test.py": "def test_c():\n    pass\n",
    "test/core/other/__init__.py": "",
    "test/core/other/body_test.py": """
        import os
        def test_body():
            os.path.join("test", "fixtures",
                         "config", "a")
        def test_not():
            pass
    """,
    "test/core/other/param_test.py": """
        import pytest
        @pytest.mark.parametrize("p", ["test/fixtures/config/a", "test/fixtures/x"])
        def test_param(p):
            pass
    """,
}


def write_tree(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip("\n"))


def readers_file(path: Path, readers: dict | None = None) -> Path:
    """A run record of scripts/s7-tests/config-readers."""
    data = {
        "sqlfluff": SCOPE["sqlfluff"],
        "skipped_folders": ["test/cli", "test/rules", "test/core/config"],
        "readers": readers or {},
    }
    path.write_text(json.dumps(data))
    return path


def inventory(root: Path, readers: Path) -> subprocess.CompletedProcess:
    return run_script(INVENTORY, "--root", str(root), "--readers", str(readers))


@oracle
def test_inventory_rule_on_a_small_tree(tmp_path):
    write_tree(tmp_path / "root", BASE)
    run = {"test/core/other/body_test.py::test_not": ["test/fixtures/config"]}
    proc = inventory(tmp_path / "root", readers_file(tmp_path / "r.json", run))
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout)
    assert {n["id"]: (n["group"], n.get("by")) for n in out["nodes"]} == {
        "test/cli/a_test.py::test_a": ("cli", None),
        "test/cli/test_by_path.py::test_b": ("cli", None),
        "test/core/config/c_test.py::test_c": ("config", None),
        "test/core/other/body_test.py::test_body": ("config_fixtures", ["source"]),
        "test/core/other/body_test.py::test_not": ("config_fixtures", ["run"]),
        "test/core/other/param_test.py::test_param[test/fixtures/config/a]": (
            "config_fixtures",
            ["source"],
        ),
        "test/rules/yaml_test_cases_test.py::test_other": ("rules", None),
    }
    assert out["collected_by_path"] == ["test/cli/test_by_path.py"]
    assert out["s1_suites"][
        "test/rules/yaml_test_cases_test.py::test__rule_test_case"
    ] == {"suite": "rules", "nodes": 2}


@oracle
@pytest.mark.parametrize(
    ("files", "run", "error"),
    [
        (
            {"test/core/other/const_test.py": 'P = "test/fixtures/config/a"\n'},
            {},
            "test/core/other/const_test.py:1: names test/fixtures/config outside"
            " a collected test function",
        ),
        (
            {
                "test/core/other/mark_test.py": """
                    import pytest
                    @pytest.mark.skipif(False, reason="fixtures/config")
                    def test_m():
                        pass
                """
            },
            {},
            "test/core/other/mark_test.py:2: names test/fixtures/config in a"
            " decorator, but no node has it in its parameter values",
        ),
        (
            {"test/core/other/bad_test.py": 'import nothere\nP = "fixtures/config"\n'},
            {},
            "test/core/other/bad_test.py: pytest cannot import it, and it names"
            " test/fixtures/config",
        ),
        (
            {"test/core/config/bad_test.py": "import nothere\n"},
            {},
            "test/core/config/bad_test.py: collection error in a scope folder",
        ),
        (
            {"test/core/config/c_test.py": "X = 1\n"},
            {},
            "no node in group config",
        ),
        (
            {"test/rules/std_fix_auto_test.py": "X = 1\n"},
            {},
            "pytest collected no node of the S1 suite test"
            " test/rules/std_fix_auto_test.py::test__std_fix_auto",
        ),
        (
            {},
            {"test/core/other/gone_test.py::test_x": []},
            "test/core/other/gone_test.py::test_x is not a collected node outside"
            " the scope folders",
        ),
        (
            {},
            {"test/cli/a_test.py::test_a": []},
            "test/cli/a_test.py::test_a is not a collected node outside the scope"
            " folders",
        ),
    ],
)
def test_inventory_fails_closed(tmp_path, files, run, error):
    write_tree(tmp_path / "root", BASE | files)
    proc = inventory(tmp_path / "root", readers_file(tmp_path / "r.json", run))
    assert proc.returncode == 1
    assert error in proc.stderr
    assert proc.stdout == ""


@oracle
def test_inventory_checks_the_run_record(tmp_path):
    write_tree(tmp_path / "root", BASE)
    path = readers_file(tmp_path / "r.json")
    path.write_text(path.read_text().replace(SCOPE["sqlfluff"], "0.0.0"))
    proc = inventory(tmp_path / "root", path)
    assert proc.returncode == 1
    assert f"sqlfluff 0.0.0, not {SCOPE['sqlfluff']}" in proc.stderr
    path.write_text(
        json.dumps(
            {
                "sqlfluff": SCOPE["sqlfluff"],
                "skipped_folders": ["test/cli"],
                "readers": {},
            }
        )
    )
    proc = inventory(tmp_path / "root", path)
    assert proc.returncode == 1
    assert "the skipped folders are not the scope folders" in proc.stderr


READER_TEST = """
    import os
    # The inventory does not find these names of the folder.
    def test_open():
        open("test/fixtures/" + "config/a/.sqlfluff")
    def test_list():
        os.listdir("test/fixtures/" + "config")
    def test_no_read():
        os.path.exists("test/fixtures/" + "config")
"""


@oracle
def test_config_readers_finds_the_readers(tmp_path):
    root = tmp_path / "root"
    write_tree(
        root,
        BASE
        | {
            "test/fixtures/config/a/.sqlfluff": "[sqlfluff]\n",
            "test/core/other/reader_test.py": READER_TEST,
            # The scope folders do not run.
            "test/core/config/r_test.py": READER_TEST,
        },
    )
    proc = run_script(CONFIG_READERS, "--root", str(root))
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout)
    assert out["readers"] == {
        "test/core/other/reader_test.py::test_list": ["test/fixtures/config"],
        "test/core/other/reader_test.py::test_open": [
            "test/fixtures/config/a/.sqlfluff"
        ],
    }
    assert out["collection_lists"] == ["test/fixtures/config", "test/fixtures/config/a"]
    assert out["skipped_folders"] == ["test/cli", "test/rules", "test/core/config"]
    # The inventory puts the readers in scope.
    run = tmp_path / "run.json"
    run.write_text(proc.stdout)
    proc = inventory(root, run)
    assert proc.returncode == 0, proc.stderr[-3000:]
    fixtures = {n["id"]: n["by"] for n in json.loads(proc.stdout)["nodes"] if "by" in n}
    assert fixtures["test/core/other/reader_test.py::test_open"] == ["run"]
    assert fixtures["test/core/other/reader_test.py::test_list"] == ["run"]
    assert "test/core/other/reader_test.py::test_no_read" not in fixtures


@oracle
def test_config_readers_fails_on_a_read_in_the_collection(tmp_path):
    root = tmp_path / "root"
    write_tree(
        root,
        BASE
        | {
            "test/fixtures/config/a/.sqlfluff": "[sqlfluff]\n",
            "test/core/other/import_test.py": """
                TEXT = open("test/fixtures/" + "config/a/.sqlfluff").read()
                def test_x():
                    pass
            """,
        },
    )
    proc = run_script(CONFIG_READERS, "--root", str(root))
    assert proc.returncode == 1
    assert "a read in the collection that is not a folder list: [('open'," in (
        proc.stderr
    )
    assert proc.stdout == ""


CHILD_TEST = """
    import multiprocessing
    import subprocess
    import sys
    CODE = "open('test/fixtures/' + 'config/a/.sqlfluff')"
    def test_child():
        subprocess.run([sys.executable, "-c", CODE], check=True)
    def read(_):
        open("test/fixtures/" + "config/a/.sqlfluff").close()
    def test_spawn_pool():
        with multiprocessing.get_context("spawn").Pool(1) as pool:
            pool.map(read, [1])
    def test_fork():
        p = multiprocessing.get_context("fork").Process(target=read, args=(1,))
        p.start()
        p.join()
        assert p.exitcode == 0
    def test_sqlfluff_on_path():
        # The bin folder of the oracle is on PATH.
        subprocess.run(["sqlfluff", "--version"], check=True)
"""


@oracle
def test_config_readers_traces_other_processes(tmp_path):
    root = tmp_path / "root"
    files = {
        "test/fixtures/config/a/.sqlfluff": "[sqlfluff]\n",
        "test/core/other/child_test.py": CHILD_TEST,
    }
    write_tree(root, BASE | files)
    proc = run_script(CONFIG_READERS, "--root", str(root))
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout)
    name = "test/core/other/child_test.py::"
    read = ["test/fixtures/config/a/.sqlfluff"]
    assert out["readers"] == {
        name + "test_child": read,
        name + "test_fork": read,
        name + "test_spawn_pool": read,
    }
    assert out["outcomes"] == {"passed": 8}
    assert out["failed"] == []
    traced = out["traced_processes"]
    assert traced[name + "test_child"] == 1
    assert traced[name + "test_sqlfluff_on_path"] == 1
    # The pool worker; the resource tracker can also be in the count.
    assert traced[name + "test_spawn_pool"] >= 1
    assert name + "test_fork" not in traced


@oracle
def test_config_readers_fails_on_a_program_that_it_does_not_trace(tmp_path):
    root = tmp_path / "root"
    files = {
        "test/core/other/program_test.py": """
            import subprocess
            def test_x():
                subprocess.run(["cat", "test/fixtures/" + "config/a/.sqlfluff"])
        """,
    }
    write_tree(root, BASE | files)
    proc = run_script(CONFIG_READERS, "--root", str(root))
    assert proc.returncode == 1
    assert (
        "test/core/other/program_test.py::test_x: starts 1 programs, but the trace"
        " sees 0"
    ) in proc.stderr
    assert proc.stdout == ""


@oracle
def test_config_readers_write_needs_the_pinned_submodule(tmp_path):
    proc = run_script(CONFIG_READERS, "--write", "--root", str(tmp_path))
    assert proc.returncode == 2
    assert "--write needs the pinned submodule" in proc.stderr
