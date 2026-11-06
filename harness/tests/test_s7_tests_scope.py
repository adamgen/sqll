"""The S7 scope (docs/decisions/s7-tests-design.md, "Scope").

results/S7-tests/scope.json must be the output of scripts/s7-tests/inventory
on the pinned submodule, and the counts in the documents must be its
counts. results/S7-tests/config-readers.json (the run check of the
config_fixtures rule) must name only nodes in scope.
"""

import json
import os
import re
import subprocess
import textwrap
from collections import Counter
from pathlib import Path

import pytest
from conftest import needs

from sqll_harness.paths import REPO_ROOT, SQLFLUFF_ROOT, tools_dir

INVENTORY = REPO_ROOT / "scripts" / "s7-tests" / "inventory"
CONFIG_READERS = REPO_ROOT / "scripts" / "s7-tests" / "config-readers"
RESULTS = REPO_ROOT / "results" / "S7-tests"
SCOPE_FILE = RESULTS / "scope.json"
SCOPE = json.loads(SCOPE_FILE.read_text("utf8"))
READERS = json.loads((RESULTS / "config-readers.json").read_text("utf8"))
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
    assert "--write needs the pinned submodule and the recorded run" in proc.stderr


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


def test_config_readers_are_in_scope():
    run = {n["id"] for n in SCOPE["nodes"] if "run" in n.get("by", [])}
    assert set(READERS["readers"]) == run
    assert READERS["sqlfluff"] == SCOPE["sqlfluff"]
    assert READERS["skipped_folders"] == ["test/cli", "test/rules", "test/core/config"]
    assert READERS["collection_errors"] == {
        e["file"]: e["error"] for e in SCOPE["collection_errors"]
    }
    assert READERS["outcomes"] == {"failed": 8, "passed": 8263, "skipped": 2529}


def test_config_readers_collection_lists_each_folder():
    # In the collection, pytest lists each folder of the tree.
    config = SQLFLUFF_ROOT / "test" / "fixtures" / "config"
    folders = [config, *(p for p in config.rglob("*") if p.is_dir())]
    want = sorted(p.relative_to(SQLFLUFF_ROOT).as_posix() for p in folders)
    assert READERS["collection_lists"] == want


def test_failed_nodes_of_the_run_do_not_name_the_folder():
    # A node that fails can stop before a read. These nodes fail because the
    # oracle tools have no example plugin and no diff_cover.
    files = sorted({n.split("::")[0] for n in READERS["failed"]})
    assert files == ["test/core/plugin_test.py", "test/diff_quality_plugin_test.py"]
    for file in files:
        text = (SQLFLUFF_ROOT / file).read_text("utf8")
        assert "fixtures/config" not in text
        assert not re.search(r"[\"']config[\"']", text)


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


def test_status_has_each_task():
    for n in range(1, 17):
        assert re.search(rf"^\| T{n} \| ", STATUS, re.M), f"T{n}"


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


@oracle
def test_config_readers_write_needs_the_pinned_submodule(tmp_path):
    proc = run_script(CONFIG_READERS, "--write", "--root", str(tmp_path))
    assert proc.returncode == 2
    assert "--write needs the pinned submodule" in proc.stderr
