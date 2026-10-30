"""The S9 corpus parse run, shard merge, and baseline check
(docs/decisions/s9-corpus.md, "Parse check and report").

Stub tools in the bench registry parse a tiny local manifest. A first line
"-- mode: M" (or "-- mode: TOOL=M,TOOL=M") in a corpus file tells the stub
what to do. The files are in the fetch cache, so no test uses the network.
The real tools are in the last tests.
"""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
from conftest import needs_all_tools

from sqll_harness import tools as s1_tools
from sqll_harness.adapters.base import EmptyHome, isolated_env
from sqll_harness.bench import registry
from sqll_harness.bench.adapter import BenchAdapter
from sqll_harness.bench.timer import Policy, Sample, sample_stats
from sqll_harness.bench.tools import SqlfluffBench, SqlfluffRsBench, SqruffBench
from sqll_harness.corpus import __main__ as corpus_main
from sqll_harness.corpus import baseline, report
from sqll_harness.corpus import manifest as m
from sqll_harness.corpus import run as corpus_run
from sqll_harness.tools import ToolInfo

COMMIT = "0123456789abcdef0123456789abcdef01234567"
KIB = 1024
LICENSE = b"MIT License\n\nCopyright (c) Example Holder\n"

STUB = r"""
import json, os, sys, time
config_path, sql = sys.argv[1:]
tool = os.environ["STUB_TOOL"]
with open(config_path, encoding="utf8") as f:
    core = json.load(f)["core"]
if core.get("max_parse_nodes") != 0 or not core.get("dialect"):
    sys.exit(2)
with open(sql, "rb") as f:
    text = f.read().decode("utf8")
first = text.split("\n", 1)[0]
mode = "ok"
if first.startswith("-- mode: "):
    spec = first[len("-- mode: "):].strip()
    if "=" in spec:
        mode = dict(p.split("=") for p in spec.split(",")).get(tool, "ok")
    else:
        mode = spec
if core["templater"] == "jinja":
    text = text.replace("{{ n }}", "1")
lines = text.replace("\r\n", "\n").splitlines(keepends=True)
tree = [{"line": line} for line in lines]
code = 0
if mode in ("unparsable", "unparsable0"):
    tree[0] = {"unparsable": [{"word": lines[0]}, {"unparsable": [{"word": ""}]}]}
    tree[1] = {"unparsable": {"word": lines[1]}}
    code = 1 if mode == "unparsable" else 0
if mode == "panic":
    sys.stderr.write("thread 'main' panicked at src/parser.rs:1:1:\nboom\n")
    sys.exit(101)
if mode == "timeout":
    time.sleep(60)
if mode == "traceback":
    sys.stderr.write("Traceback (most recent call last):\n  oops\n")
    code = 1
if mode == "drop":
    tree = tree[:-1]
if mode == "exit1":
    code = 1
if mode == "exit2":
    sys.exit(2)
if mode == "garbage":
    print("not json")
    sys.exit(0)
if mode in ("null0", "null1"):
    print("null")
    sys.exit(0 if mode == "null0" else 1)
print(json.dumps({"file": tree}))
sys.exit(code)
"""


class Stub(BenchAdapter):
    """A stub tool. no: the dialects that it does not support."""

    name = "stub"
    no: frozenset[str] = frozenset()
    script: Path | None = None

    def version(self) -> str:
        return "1.0"

    def unsupported(self, config):
        dialect = config["core"]["dialect"]
        return f"dialect {dialect}" if dialect in self.no else None

    def write_config(self, config, folder):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "stub.json"
        path.write_text(json.dumps(config), encoding="utf8")
        return path

    def argv(self, command, config_file, sql):
        assert command == "parse"
        return [sys.executable, "-I", str(self.script), str(config_file), sql]

    def env(self):
        env = isolated_env(EmptyHome.path())
        env["STUB_TOOL"] = self.name
        return env

    def read_tree(self, stdout, sql):
        return json.loads(stdout)

    def read_violations(self, stdout, sql):
        raise AssertionError("not used")


class StubSqlfluff(Stub):
    name = "sqlfluff"


class StubSqruff(Stub):
    name = "sqruff"
    no = frozenset({"soql"})


class StubSqll(Stub):
    """The test double of a new tool (sqll after S3b)."""

    name = "sqll"


def sql(size: int, mode=None, line=b"SELECT 1;\n", tag="") -> bytes:
    """Return a file of complete lines with at least size bytes. tag makes
    the content of each file different."""
    head = f"-- mode: {mode}\n" if mode else "-- corpus file\n"
    data = (head + f"-- {tag}\n").encode()
    count = max(0, size - len(data) + len(line) - 1) // len(line)
    return data + line * count


# id path, mode, templater, size, dialect.
CASES = [
    ("models/bad_render.sql", "ok", "jinja", 9 * KIB, "ansi"),
    ("models/tmpl.sql", "ok", "jinja", 9 * KIB, "ansi"),
    ("sql/crlf.sql", None, "raw", 17 * KIB, "ansi"),
    ("sql/drop.sql", "drop", "raw", 17 * KIB, "ansi"),
    ("sql/exit1.sql", "exit1", "raw", 17 * KIB, "ansi"),
    ("sql/exit2.sql", "exit2", "raw", 17 * KIB, "ansi"),
    ("sql/garbage.sql", "garbage", "raw", 17 * KIB, "ansi"),
    ("sql/large.sql", None, "raw", 40 * KIB, "postgres"),
    ("sql/null0.sql", "null0", "raw", 17 * KIB, "ansi"),
    ("sql/null1.sql", "null1", "raw", 17 * KIB, "ansi"),
    ("sql/ok.sql", None, "raw", 17 * KIB, "ansi"),
    ("sql/panic.sql", "sqruff=panic", "raw", 17 * KIB, "ansi"),
    ("sql/soql.sql", None, "raw", 17 * KIB, "soql"),
    ("sql/timeout.sql", "sqlfluff=timeout", "raw", 17 * KIB, "ansi"),
    ("sql/traceback.sql", "traceback", "raw", 17 * KIB, "ansi"),
    ("sql/unparsable.sql", "unparsable", "raw", 17 * KIB, "ansi"),
    ("sql/unparsable0.sql", "unparsable0", "raw", 17 * KIB, "ansi"),
]


def file_data(path: str, mode, size: int) -> bytes:
    if path == "sql/crlf.sql":
        return sql(size, line=b"SELECT 1;\r\n", tag=path)
    if path.startswith("models/"):
        data = sql(size, mode, line=b"SELECT {{ n }};\n", tag=path)
        if "bad_render" in path:
            data = b"-- render: fail\n" + data
        return data
    return sql(size, mode, tag=path)


FILES = {path: file_data(path, mode, size) for path, mode, _, size, _ in CASES}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_data(cases=CASES, data_of=FILES) -> dict:
    files = []
    for path, _, templater, _, dialect in cases:
        data = data_of[path]
        files.append(
            {
                "id": f"demo/{path}",
                "source": "demo",
                "path": path,
                "dialect": dialect,
                "templater": templater,
                "bytes": len(data),
                "lines": data.count(b"\n"),
                "sha256": sha(data),
                "smoke": len(data) <= 32 * KIB,
                "selection": "test",
            }
        )
    return {
        "format": 1,
        "sources": {
            "demo": {
                "repository": "https://github.com/example/demo-sql",
                "commit": COMMIT,
                "license": "MIT",
                "copyright": ["Example Holder"],
                "license_files": [
                    {"path": "LICENSE", "bytes": len(LICENSE), "sha256": sha(LICENSE)}
                ],
                "globs": ["models/*.sql", "sql/*.sql"],
            }
        },
        "files": files,
    }


def stub_render(entry, data, config, folder):
    """The reference render of the stub tools."""
    assert config["core"]["templater"] == "jinja"
    assert config["core"]["dialect"] == entry.dialect
    text = data.decode("utf8")
    if text.startswith("-- render: fail"):
        return None, "stub render failed"
    return text.replace("{{ n }}", "1"), None


def _ok(name):
    return lambda root, specs: ToolInfo(name, "binary", "1.0", "1.0")


class Env:
    """A tiny manifest with its files in a fetch cache, and stub tools."""

    def __init__(self, tmp: Path, mp: pytest.MonkeyPatch, tools=(StubSqlfluff,)):
        self.tmp = tmp
        script = tmp / "stub.py"
        script.write_text(STUB, encoding="utf8")
        self.registry = {}
        for cls in tools:
            self.registry[cls.name] = type(cls.__name__, (cls,), {"script": script})
        self.patch(mp)
        self.manifest = tmp / "sources.json"
        self.manifest.write_text(json.dumps(manifest_data(), indent=1))
        self.cache = tmp / "cache"
        source = self.cache / "demo" / COMMIT
        for path, data in [("LICENSE", LICENSE), *FILES.items()]:
            (source / path).parent.mkdir(parents=True, exist_ok=True)
            (source / path).write_bytes(data)

    def patch(self, mp: pytest.MonkeyPatch) -> None:
        """Use the stub tools, the stub render, and quick profiles."""
        mp.setattr(registry, "REGISTRY", dict(self.registry))
        mp.setattr(corpus_run, "LATER", frozenset())
        mp.setattr(s1_tools, "CHECKS", {n: _ok(n) for n in self.registry})
        mp.setattr(corpus_main, "make_render", lambda: stub_render)
        mp.setattr(corpus_run, "PROFILES", QUICK)

    def main(self, *args) -> int:
        argv = [str(a) for a in args]
        return corpus_main.main([argv[0], "--manifest", str(self.manifest), *argv[1:]])

    def run(self, out: str, *args) -> int:
        return self.main("run", "--cache", self.cache, "--out", self.tmp / out, *args)

    def load(self, name: str) -> dict:
        return report.load(self.tmp / name)


def by_key(rep: dict) -> dict[tuple[str, str], dict]:
    return {(r["file"].removeprefix("demo/"), r["tool"]): r for r in rep["results"]}


TOOLS3 = (StubSqlfluff, StubSqruff, StubSqll)
QUICK = {
    "smoke": Policy(min_runs=1, max_runs=1, budget_s=0.0, timeout_s=2.0),
    "full": Policy(min_runs=2, max_runs=2, budget_s=0.0, timeout_s=2.0),
}


@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    """One smoke run of 3 stub tools on all smoke files of the manifest."""
    tmp = tmp_path_factory.mktemp("smoke")
    with pytest.MonkeyPatch.context() as mp:
        env = Env(tmp, mp, TOOLS3)
        before = env.manifest.read_bytes()
        code = env.run("smoke.json", "--profile", "smoke")
        after = env.manifest.read_bytes()
        rep = env.load("smoke.json")
        man = m.load(env.manifest)
        errors = report.check(rep) + corpus_run.incomplete(rep, man)
    return {
        "code": code,
        "rep": rep,
        "manifest": man,
        "same": before == after,
        "errors": errors,
    }


# Settings.


def test_the_profiles_are_those_of_the_design_record():
    assert corpus_run.PROFILES == {
        "smoke": Policy(min_runs=1, max_runs=1, budget_s=0.0, timeout_s=1200.0),
        "full": Policy(min_runs=1, max_runs=5, budget_s=10.0, timeout_s=1200.0),
    }


def test_each_tool_gets_the_corpus_settings_and_its_layers():
    core = {
        "templater": "raw",
        "rules": "all",
        "large_file_skip_byte_limit": 0,
        "large_file_skip_char_limit": 0,
        "max_parse_nodes": 0,
    }
    fluff = corpus_run.tool_config(SqlfluffBench(), "raw", "tsql")
    assert fluff == {"core": {"dialect": "tsql", **core}}
    rs = corpus_run.tool_config(SqlfluffRsBench(), "jinja", "ansi")["core"]
    assert rs["templater"] == "jinja" and rs["max_parse_nodes"] == 0
    assert rs["use_rust_parser"] is True and rs["use_rust_rules"] is True
    assert rs["rust_parser_max_iterations"] == 10**12
    sq = corpus_run.tool_config(SqruffBench(), "raw", None)
    assert sq["core"] == {**core, "templater": "raw"}
    assert "rust_parser_max_iterations" not in sq["core"]
    assert "rust_parser_max_iterations" not in fluff["core"]
    # The layers do not change the S2 settings of the bench adapters.
    assert SqlfluffRsBench().config("ansi")["core"]["templater"] == "raw"
    assert "max_parse_nodes" not in SqlfluffBench().config("ansi")["core"]


# The parse check.


def test_tree_facts_counts_the_outer_unparsable_segments_and_their_bytes():
    record = {
        "file": [
            {"keyword": "SELECT"},
            {"unparsable": [{"word": "é"}, {"unparsable": {"word": "ab"}}]},
            {"statement": {"newline": "\n", "empty": None}},
            {"unparsable": {"word": "x"}},
        ]
    }
    assert corpus_run.tree_facts(record) == ("SELECTéab\nx", 2, 5)
    assert corpus_run.tree_facts({"file": None}) == ("", 0, 0)


def test_tree_facts_reads_a_deep_tree():
    record: dict = {"word": "x"}
    for _ in range(5000):
        record = {"bracketed": [record, {"word": "y"}]}
    text, count, size = corpus_run.tree_facts({"file": record})
    assert text == "x" + "y" * 5000 and count == size == 0


@pytest.mark.parametrize(
    "record",
    [None, "text", {"file": 3}, {"file": ["word"]}, {"file": [{"a": "1", "b": "2"}]}],
)
def test_tree_facts_refuses_a_value_that_is_not_a_tree(record):
    with pytest.raises(ValueError):
        corpus_run.tree_facts(record)


def test_normalize_removes_a_bom_and_makes_each_line_end_a_newline():
    assert corpus_run.normalize("﻿a\r\nb\rc\n") == "a\nb\nc\n"
    assert corpus_run.normalize("a﻿") == "a﻿"


# The smoke run of the stub tools.


EXPECTED = {
    # path: {tool: status}; a tool that is not given has the status of "*".
    "models/bad_render.sql": {"*": "no_reference"},
    "models/tmpl.sql": {"*": "ok"},
    "sql/crlf.sql": {"*": "ok"},
    "sql/drop.sql": {"*": "invalid"},
    "sql/exit1.sql": {"*": "invalid"},
    "sql/exit2.sql": {"*": "invalid"},
    "sql/garbage.sql": {"*": "invalid"},
    "sql/null0.sql": {"*": "invalid"},
    "sql/null1.sql": {"*": "invalid"},
    "sql/ok.sql": {"*": "ok"},
    "sql/panic.sql": {"*": "ok", "sqruff": "invalid"},
    "sql/soql.sql": {"*": "ok", "sqruff": "unsupported"},
    "sql/timeout.sql": {"*": "ok", "sqlfluff": "invalid"},
    "sql/traceback.sql": {"*": "invalid"},
    "sql/unparsable.sql": {"*": "unparsable"},
    "sql/unparsable0.sql": {"*": "unparsable"},
}


def test_the_smoke_run_gives_the_status_of_each_file_and_tool(smoke):
    assert smoke["code"] == 0
    assert smoke["errors"] == []
    rep = smoke["rep"]
    got = {k: r["status"] for k, r in by_key(rep).items()}
    want = {
        (path, tool): statuses.get(tool, statuses["*"])
        for path, statuses in EXPECTED.items()
        for tool in ("sqlfluff", "sqll", "sqruff")
    }
    assert got == want
    # The smoke profile has no file over 32 KiB.
    assert "demo/sql/large.sql" not in rep["inputs"]


@pytest.mark.parametrize(
    "path, tool, reason",
    [
        ("sql/null0.sql", "sqlfluff", "warmup run: no parse tree (exit code 0)"),
        ("sql/null1.sql", "sqlfluff", "warmup run: no parse tree (exit code 1)"),
        ("sql/garbage.sql", "sqlfluff", "warmup run: no parse tree (exit code 0): "),
        ("sql/drop.sql", "sqlfluff", "warmup run: the tree text ("),
        (
            "sql/exit1.sql",
            "sqlfluff",
            "warmup run: exit code 1, but the tree has no unparsable segment",
        ),
        ("sql/exit2.sql", "sqlfluff", "warmup run: exit code 2, expected 0, 1"),
        ("sql/traceback.sql", "sqlfluff", "warmup run: the tool crashed: Traceback"),
        ("sql/panic.sql", "sqruff", "the tool crashed (panic): thread 'main'"),
        ("sql/timeout.sql", "sqlfluff", "warmup run: timeout after 2.0 s"),
        ("sql/soql.sql", "sqruff", "unsupported: dialect soql"),
        ("models/bad_render.sql", "sqll", "no reference: stub render failed"),
        ("sql/unparsable.sql", "sqruff", "2 unparsable segments ("),
    ],
)
def test_each_status_has_its_reason(smoke, path, tool, reason):
    assert by_key(smoke["rep"])[(path, tool)]["reason"].startswith(reason)


def test_an_unparsable_tree_gives_the_count_and_bytes(smoke):
    rows = by_key(smoke["rep"])
    for path, code in (("sql/unparsable.sql", 1), ("sql/unparsable0.sql", 0)):
        r = rows[(path, "sqlfluff")]
        lines = FILES[path].split(b"\n")
        size = len(lines[0]) + len(lines[1]) + 2
        assert r["unparsable"] == {"count": 2, "bytes": size}
        assert r["exit_code"] == code
        assert r["stats"] is not None and r["bytes_per_s"] > 0
    assert rows[("sql/ok.sql", "sqlfluff")]["unparsable"] == {"count": 0, "bytes": 0}


def test_a_null_tree_with_exit_code_0_is_not_ok(smoke):
    r = by_key(smoke["rep"])[("sql/null0.sql", "sqlfluff")]
    assert r["status"] == "invalid" and r["exit_code"] == 0
    assert r["stats"] is None and r["unparsable"] is None
    assert r["runs"] == {"warmup": 1, "timed": 0}


def test_a_timeout_and_a_panic_are_invalid(smoke):
    rows = by_key(smoke["rep"])
    timeout = rows[("sql/timeout.sql", "sqlfluff")]
    assert timeout["status"] == "invalid" and timeout["samples"][0]["timed_out"]
    panic = rows[("sql/panic.sql", "sqruff")]
    assert panic["status"] == "invalid" and panic["exit_code"] == 101


def test_a_dialect_that_a_tool_does_not_have_is_unsupported(smoke):
    r = by_key(smoke["rep"])[("sql/soql.sql", "sqruff")]
    assert r["status"] == "unsupported" and r["samples"] == []
    assert r["exit_code"] is None and r["max_rss_kib"] is None


def test_templated_files_get_the_jinja_settings_and_the_reference(smoke):
    rep = smoke["rep"]
    tmpl = rep["inputs"]["demo/models/tmpl.sql"]
    want = FILES["models/tmpl.sql"].decode().replace("{{ n }}", "1")
    assert tmpl["templater"] == "jinja"
    assert tmpl["reference"] == {
        "status": "ok",
        "sha256": sha(want.encode()),
        "reason": None,
    }
    assert rep["inputs"]["demo/models/bad_render.sql"]["reference"] == {
        "status": "failed",
        "sha256": None,
        "reason": "stub render failed",
    }
    assert rep["inputs"]["demo/sql/ok.sql"]["reference"] is None
    for tool in rep["tools"].values():
        assert tool["settings"]["jinja"]["core"]["templater"] == "jinja"
        assert tool["settings"]["raw"]["core"]["templater"] == "raw"


def test_the_compared_totals_use_only_files_where_each_tool_is_ok(smoke):
    rep = smoke["rep"]
    ok_all = [p for p, s in EXPECTED.items() if s["*"] == "ok" and set(s) == {"*"}]
    c = rep["compared"]
    assert c["files"] == len(ok_all) == 3
    assert c["bytes"] == sum(len(FILES[p]) for p in ok_all)
    rows = by_key(rep)
    for tool, t in c["results"].items():
        wall = sum(rows[(p, tool)]["stats"]["wall_s"]["median"] for p in ok_all)
        assert t["wall_s"] == round(wall, 6)
    assert c["results"]["sqlfluff"]["wall_ratio"] == 1.0
    assert rep["totals"]["sqruff"]["unsupported"] == 1


def test_a_new_tool_runs_each_file_through_the_registry_alone(smoke):
    """sqll joins after S3b with its registry entry only: the test double
    runs each file of the profile, and the manifest does not change."""
    assert smoke["same"]
    rep = smoke["rep"]
    files = [f.id for f in smoke["manifest"].selected(smoke=True)]
    got = sorted(r["file"] for r in rep["results"] if r["tool"] == "sqll")
    assert got == sorted(files) and len(files) == len(CASES) - 1
    assert rep["scope"]["tools"] == ["sqlfluff", "sqll", "sqruff"]
    assert rep["tools"]["sqll"]["version"] == "1.0"
    assert all(r["runs"]["warmup"] == 1 for r in rep["results"] if r["tool"] == "sqll")
    assert "sqll" not in smoke["manifest"].text.decode()


def test_a_tool_that_joins_later_runs_only_when_asked(tmp_path, monkeypatch):
    """The real sqll is in the bench registry from S3 T13, but the corpus
    runs it only with --tool until its results after S3b (LATER)."""
    assert corpus_run.LATER == frozenset({"sqll"})
    env = Env(tmp_path, monkeypatch, TOOLS3)
    monkeypatch.setattr(corpus_run, "LATER", frozenset({"sqll"}))
    assert corpus_run.tool_names() == ["sqlfluff", "sqruff"]
    assert env.run("default.json", "--profile", "smoke") == 0
    rep = env.load("default.json")
    assert rep["scope"]["tools"] == ["sqlfluff", "sqruff"]
    assert {r["tool"] for r in rep["results"]} == {"sqlfluff", "sqruff"}
    args = ("--profile", "smoke", "--tool", "sqll")
    assert env.run("asked.json", *args) == 0
    assert {r["tool"] for r in env.load("asked.json")["results"]} == {"sqll"}


def test_a_render_that_stops_gives_an_error_for_each_tool(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)

    def stop(entry, data, config, folder):
        raise OSError("no python")

    monkeypatch.setattr(corpus_main, "make_render", lambda: stop)
    assert env.run("r.json", "--profile", "smoke") == 0
    rep = env.load("r.json")
    assert report.check(rep) == []
    r = by_key(rep)[("models/tmpl.sql", "sqlfluff")]
    assert r["status"] == "error"
    assert r["reason"] == "harness error: OSError('no python')"
    ref = rep["inputs"]["demo/models/tmpl.sql"]["reference"]
    assert ref["status"] == "failed" and ref["reason"] == r["reason"]
    assert by_key(rep)[("sql/ok.sql", "sqlfluff")]["status"] == "ok"


def test_the_run_fails_closed_on_a_changed_cache_file(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    path = env.cache / "demo" / COMMIT / "sql" / "ok.sql"
    path.write_bytes(path.read_bytes().replace(b"SELECT 1", b"SELECT 2", 1))
    # The fetch downloads it again; the test has no network, so it fails.
    monkeypatch.setattr(
        corpus_main.fetch_module, "http_download", _no_network, raising=True
    )
    assert env.run("r.json", "--profile", "smoke") == 2
    assert not (tmp_path / "r.json").exists()


def _no_network(url, limit):
    raise corpus_main.fetch_module.FetchError(f"no network in tests: {url}")


def test_a_failed_tool_check_stops_the_run(tmp_path, monkeypatch, capsys):
    env = Env(tmp_path, monkeypatch)
    monkeypatch.setitem(
        s1_tools.CHECKS,
        "sqlfluff",
        lambda root, specs: ToolInfo("sqlfluff", "b", "1.0", "0.9", errors=["v"]),
    )
    assert env.run("r.json", "--profile", "smoke") == 2
    assert "error: sqlfluff: v" in capsys.readouterr().err


# Shards, merge, and the baseline check.


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    """A full run, its 3 shards, and their merge (2 stub tools)."""
    tmp = tmp_path_factory.mktemp("full")
    with pytest.MonkeyPatch.context() as mp:
        env = Env(tmp, mp, (StubSqlfluff, StubSqruff))
        codes = {"all": env.run("all.json", "--profile", "full")}
        for k in (1, 2, 3):
            codes[k] = env.run(f"{k}.json", "--profile", "full", "--shard", f"{k}/3")
        shards = [tmp / f"{k}.json" for k in (1, 2, 3)]
        (tmp / "n.json").write_text('{"shards": 3}')
        codes["merge"] = env.main(
            "merge", *shards, "--expect", tmp / "n.json", "--out", tmp / "m.json"
        )
        return {
            "env": env,
            "codes": codes,
            "all": env.load("all.json"),
            "merged": env.load("m.json"),
            "shards": shards,
        }


@pytest.fixture
def full(full_run, monkeypatch):
    """The full run, with the stub tools and the quick profiles in use."""
    full_run["env"].patch(monkeypatch)
    return full_run


def stable(rep: dict) -> list:
    return [
        (r["file"], r["tool"], r["status"], r["unparsable"]) for r in rep["results"]
    ]


def test_the_shards_cover_each_file_once_and_merge_to_the_full_run(full):
    assert set(full["codes"].values()) == {0}
    merged, whole = full["merged"], full["all"]
    assert report.check(merged) == []
    assert stable(merged) == stable(whole)
    assert merged["inputs"] == whole["inputs"]
    assert [p["shard"] for p in merged["parts"]] == ["1/3", "2/3", "3/3"]
    assert merged["scope"]["shard"] is None
    assert "demo/sql/large.sql" in whole["inputs"]
    assert all(r["runs"]["timed"] == 2 for r in whole["results"] if r["stats"])


def _merge(full, paths, *extra) -> int:
    out = full["env"].tmp / "x.json"
    return full["env"].main("merge", *paths, *extra, "--out", out)


def test_merge_fails_on_a_missing_shard(full, capsys):
    assert _merge(full, full["shards"][:2]) == 2
    assert "no report for shard 3/3" in capsys.readouterr().err


def test_merge_fails_on_a_repeated_shard(full, capsys):
    a, b, c = full["shards"]
    assert _merge(full, [a, b, b, c]) == 2
    assert "shard 2/3 is in" in capsys.readouterr().err


def test_merge_fails_on_another_shard_count(full, tmp_path, capsys):
    (tmp_path / "n.json").write_text('{"shards": 4}')
    assert _merge(full, full["shards"], "--expect", tmp_path / "n.json") == 2
    assert "not the expected 4" in capsys.readouterr().err


def test_merge_fails_on_a_shard_of_another_run(full, tmp_path, capsys):
    rep = report.load(full["shards"][2])
    rep["tools"]["sqruff"]["version"] = "2.0"
    rep = rebuild(rep)
    other = tmp_path / "3.json"
    report.write(rep, other)
    assert _merge(full, [*full["shards"][:2], other]) == 2
    assert "the tool records differ" in capsys.readouterr().err


def rebuild(rep: dict, results=None, inputs=None) -> dict:
    """Return rep with new results or inputs, and the totals of them."""
    keys = ("sqlfluff_ref", "profile", "policy", "machine", "harness", "timer")
    return report.build(
        **{k: rep[k] for k in keys},
        manifest_sha256=rep["manifest_sha256"],
        scope=rep["scope"],
        tools=rep["tools"],
        inputs=inputs if inputs is not None else rep["inputs"],
        results=results if results is not None else rep["results"],
        parts=rep["parts"],
    )


def retime(rep: dict, factor: float) -> dict:
    """Return rep with each wall time multiplied by factor."""
    results = copy.deepcopy(rep["results"])
    for r in results:
        for s in r["samples"]:
            s["wall_s"] = round(s["wall_s"] * factor, 6)
        if r["stats"] is not None:
            r["stats"] = sample_stats([Sample(**s) for s in r["samples"]])
            size = rep["inputs"][r["file"]]["bytes"]
            r["bytes_per_s"] = round(size / r["stats"]["wall_s"]["median"], 6)
    return rebuild(rep, results=results)


@pytest.fixture
def base(full, tmp_path):
    """The full run as a recorded baseline: the registry has its 2 tools."""
    rep = copy.deepcopy(full["all"])
    rep["harness"]["clean"] = True
    path = tmp_path / "base.json"
    report.write(rep, path)
    return path


def check(full, rep: dict, base: Path, *extra) -> int:
    path = full["env"].tmp / "check.json"
    report.write(rep, path)
    return full["env"].main("check", path, "--baseline", base, *extra)


def test_check_passes_on_the_same_run_and_on_other_timings(full, base, capsys):
    assert check(full, full["merged"], base, "--full") == 0
    slower = retime(full["merged"], 3.0)
    assert slower["compared"] != full["merged"]["compared"]
    assert check(full, slower, base, "--full") == 0
    assert "is that of the baseline" in capsys.readouterr().out


def test_check_fails_on_a_changed_status(full, base, capsys):
    results = copy.deepcopy(full["merged"]["results"])
    r = next(r for r in results if r["status"] == "unparsable" and r["exit_code"] == 0)
    r["status"] = "ok"
    r["reason"] = None
    r["unparsable"] = {"count": 0, "bytes": 0}
    assert check(full, rebuild(full["merged"], results=results), base) == 1
    assert f"{r['tool']} {r['file']}: status ok" in capsys.readouterr().out


def test_check_fails_on_a_changed_unparsable_count(full, base, capsys):
    results = copy.deepcopy(full["merged"]["results"])
    r = next(r for r in results if r["status"] == "unparsable")
    r["unparsable"]["bytes"] += 1
    assert check(full, rebuild(full["merged"], results=results), base) == 1
    assert "unparsable {'count': 2" in capsys.readouterr().out


def test_check_fails_on_a_changed_sha256(full, base, capsys):
    inputs = copy.deepcopy(full["merged"]["inputs"])
    inputs["demo/sql/ok.sql"]["sha256"] = "0" * 64
    rep = rebuild(full["merged"], inputs=inputs)
    assert check(full, rep, base) == 1
    assert "input demo/sql/ok.sql: not the record of" in capsys.readouterr().out
    # drift() alone also finds it (a baseline of another manifest).
    errors = baseline.drift(rep, report.load(base))
    assert errors == [
        f"input demo/sql/ok.sql: sha256 {'0' * 64!r}, baseline "
        f"{full['merged']['inputs']['demo/sql/ok.sql']['sha256']!r}"
    ]


def test_check_fails_on_a_changed_reference_render(full, base):
    inputs = copy.deepcopy(full["merged"]["inputs"])
    inputs["demo/models/tmpl.sql"]["reference"]["sha256"] = "1" * 64
    errors = baseline.drift(rebuild(full["merged"], inputs=inputs), report.load(base))
    assert len(errors) == 1 and "reference" in errors[0]


@pytest.mark.parametrize(
    "edit, text",
    [
        (lambda r: r.update(sqlfluff_ref="other"), "sqlfluff_ref other"),
        (lambda r: r["tools"]["sqruff"].update(version="2"), "tool sqruff: version"),
        (
            lambda r: r["tools"]["sqruff"]["settings"]["raw"]["core"].update(x=1),
            "tool sqruff: the settings",
        ),
    ],
)
def test_check_fails_on_other_stable_data(full, base, edit, text):
    rep = copy.deepcopy(full["merged"])
    edit(rep)
    assert any(text in e for e in baseline.drift(rep, report.load(base)))


def test_check_full_needs_each_result_of_the_baseline(full, base, capsys):
    shard = report.load(full["shards"][0])
    assert check(full, shard, base) == 0
    assert check(full, shard, base, "--full") == 1
    assert "no result for" in capsys.readouterr().out


def test_a_baseline_must_be_a_complete_full_run(full, base, tmp_path, capsys):
    rep = copy.deepcopy(full["all"])
    rep["harness"]["clean"] = False
    path = tmp_path / "dirty.json"
    report.write(rep, path)
    assert check(full, full["merged"], path) == 1
    assert "baseline: the harness worktree had changes" in capsys.readouterr().out
    shard = tmp_path / "shard.json"
    rep = report.load(full["shards"][0])
    rep["harness"]["clean"] = True
    report.write(rep, shard)
    assert check(full, full["merged"], shard) == 1
    assert "baseline: the scope is not" in capsys.readouterr().out


def test_check_fails_on_a_report_of_another_manifest(full, capsys):
    rep = copy.deepcopy(full["merged"])
    rep["manifest_sha256"] = "2" * 64
    path = full["env"].tmp / "other.json"
    report.write(rep, path)
    assert full["env"].main("check", path) == 1
    assert "is not that of the manifest" in capsys.readouterr().out


# The real tools.


JINJA_LINE = (
    b"SELECT {{ 1 + 1 }} AS a FROM {{ ref('t') }}"
    b"{% if is_incremental() %} WHERE a > 1{% endif %};\n"
)


def real_case(tmp: Path) -> tuple[Path, dict[str, bytes]]:
    """A manifest of 3 synthetic files in a fetch cache: ansi (raw), soql
    (raw), and a jinja file with a dbt builtin."""
    raw = sql(16 * KIB, line=b"SELECT a, b FROM t WHERE a > 1;\n")
    soql = sql(16 * KIB, line=b"SELECT Id FROM Account\n")
    jinja = sql(8 * KIB, line=JINJA_LINE)
    bad = sql(8 * KIB, line=b"SELECT {{ no_such_macro() }} AS a;\n")
    files = {
        "sql/ansi.sql": raw,
        "sql/soql.sql": soql,
        "models/m.sql": jinja,
        "models/bad.sql": bad,
    }
    cases = [
        ("models/bad.sql", None, "jinja", 0, "ansi"),
        ("models/m.sql", None, "jinja", 0, "ansi"),
        ("sql/ansi.sql", None, "raw", 0, "ansi"),
        ("sql/soql.sql", None, "raw", 0, "soql"),
    ]
    data = manifest_data(cases, files)
    path = tmp / "sources.json"
    path.write_text(json.dumps(data, indent=1))
    source = tmp / "cache" / "demo" / COMMIT
    for p, d in [("LICENSE", LICENSE), *files.items()]:
        (source / p).parent.mkdir(parents=True, exist_ok=True)
        (source / p).write_bytes(d)
    return path, files


@needs_all_tools
def test_the_real_tools_give_a_report_with_no_schema_error(tmp_path, capsys):
    path, files = real_case(tmp_path)
    out = tmp_path / "real.json"
    argv = ["run", "--manifest", path, "--cache", tmp_path / "cache"]
    code = corpus_main.main([*map(str, argv), "--profile", "smoke", "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 0, text
    rep = report.load(out)
    assert report.check(rep) == []
    rows = by_key(rep)
    for tool in ("sqlfluff", "sqlfluff-rs", "sqruff"):
        assert rows[("sql/ansi.sql", tool)]["status"] == "ok", text
        assert rows[("models/m.sql", tool)]["status"] == "ok", text
    assert rows[("sql/soql.sql", "sqruff")]["status"] == "unsupported"
    assert rows[("sql/soql.sql", "sqruff")]["reason"] == "unsupported: dialect soql"
    ref = rep["inputs"]["demo/models/m.sql"]["reference"]
    # The dbt builtin is_incremental() is true.
    line = JINJA_LINE.decode()
    render = (
        files["models/m.sql"]
        .decode()
        .replace(line, "SELECT 2 AS a FROM t WHERE a > 1;\n")
    )
    assert ref["status"] == "ok" and ref["sha256"] == sha(render.encode())
    bad = rep["inputs"]["demo/models/bad.sql"]["reference"]
    assert bad["status"] == "failed"
    assert bad["reason"].startswith("the render failed: exit code 1: ")
    assert rows[("models/bad.sql", "sqlfluff")]["status"] == "no_reference"
    rs = rep["tools"]["sqlfluff-rs"]["settings"]["raw"]["core"]
    assert rs["rust_parser_max_iterations"] == 10**12
    assert corpus_main.main(["check", "--manifest", str(path), str(out)]) == 0
