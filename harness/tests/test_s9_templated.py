"""The S9 templated corpus files (docs/decisions/s9-corpus.md, "Templated
files"): the Jinja rule of the selection, the render settings, and the
parse check of the runner, which compares the leaf text with the render of
the pinned sqlfluff, not with the input.
"""

import hashlib
import json
from pathlib import Path

import pytest
from conftest import needs_all_tools

from sqll_harness.bench.timer import Run, Sample
from sqll_harness.bench.tools import SqlfluffBench, SqlfluffRsBench, SqruffBench
from sqll_harness.corpus import __main__ as corpus_main
from sqll_harness.corpus import jinja_names as j
from sqll_harness.corpus import manifest as m
from sqll_harness.corpus import report
from sqll_harness.corpus import run as corpus_run
from sqll_harness.corpus.reference import SqlfluffRender

KIB = 1024
COMMIT = "0123456789abcdef0123456789abcdef01234567"
LICENSE = b"MIT License\n\nCopyright (c) Example Holder\n"


# The Jinja rule.


def test_the_dbt_builtins_are_those_of_the_pinned_sqlfluff():
    assert j.dbt_builtins() == {
        "ref",
        "source",
        "function",
        "config",
        "var",
        "is_incremental",
        "this",
        "zip_strict",
        "zip",
        "return",
    }
    assert j.allowed() == j.dbt_builtins() | j.GLOBALS


@pytest.mark.parametrize(
    "text, reads",
    [
        (
            "{{ config(materialized='incremental', unique_key=['a']) }}\n"
            "select * from {{ ref('a') }} join {{ source('s', 't') }}\n"
            "{% if is_incremental() %} where x > (select max(x) from {{ this }})"
            "{% endif %}",
            {"config", "ref", "source", "is_incremental", "this"},
        ),
        ("{{ var('x', 'y') | upper }} {{ this.schema }}", {"var", "this"}),
        (
            "{% set cols = ['a', 'b'] %}{% for c in cols %}{{ c }}"
            "{% if not loop.last %},{% endif %}{% endfor %}",
            {"loop"},
        ),
        ("{% for c in ['a', 'b'] if c != 'a' %}{{ c }}{% endfor %}", set()),
        ("{% macro m(a, b=1) %}{{ a }}{{ b }}{% endmacro %}{{ m(ref('t')) }}", {"ref"}),
        ("{% set ns = namespace(x=0) %}{% set ns.x = 1 %}{{ ns.x }}", {"namespace"}),
        ("{% set q %}select 1{% endset %}{{ q }}", set()),
        ("{% with a = var('x') %}{{ a }}{% endwith %}", {"var"}),
        ("{% set x = 1 %}{% if x is not none and x is number %}{% endif %}", set()),
        ("{# {{ dbt_utils.star() }} #}{{ ref('a') }}", {"ref"}),
        ("{% raw %}{{ anything }}{% endraw %}{{ ref('a') }}", {"ref"}),
        ("{{ ref('a}}b') }} {{ \"it's\" ~ var('x') }}", {"ref", "var"}),
        ("{{ {'a': {'b': 1}} }}", set()),
        ("{%- if true -%} x {%+ endif -%}", set()),
        (
            "{% if is_incremental() %}a{% elif true %}b{% else %}c{% endif %}",
            {"is_incremental"},
        ),
    ],
)
def test_the_rule_takes_code_that_reads_only_allowed_names(text, reads):
    found = j.scan(text)
    assert found.ok, found.reason()
    assert found.reads == reads
    assert found.reason() == ""


@pytest.mark.parametrize(
    "text, reason",
    [
        ("{{ dbt_utils.star(ref('a')) }}", "it reads dbt_utils"),
        ("{{ adapter.quote('x') }} {{ target.name }}", "it reads adapter, target"),
        ("{% if x is defined %}{% endif %}", "it reads x"),
        ("{{ x }}{% set x = 1 %}", "it reads x"),
        ("{% if is_incremental() %}{% set x = 1 %}{% endif %}{{ x }}", "it reads x"),
        ("{% for c in [1] %}{% endfor %}{{ c }}", "it reads c"),
        ("{% macro m(a=target) %}{% endmacro %}", "it reads target"),
        ("{% macro m(a) %}{% endmacro %}{{ a }}", "it reads a"),
        ("{% import 'x.sql' as h %}", "statement 'import'"),
        ("{% include 'x.sql' %}", "statement 'include'"),
        ("{% call m() %}{% endcall %}", "statement 'call'; statement 'endcall'"),
        ("{{ ref('a')", "a tag has no '}}'"),
        ("{{ ref('a) }}", "a string in a tag has no end"),
        ("{{ a ! b }}", "unknown character '!' in a tag"),
        ("{{ f(a] }}", "unbalanced ']' in a tag"),
        ("{# a comment", "a comment has no '#}'"),
        ("{% if true %}", "the 'if' block has no end"),
        ("{% endif %}", "'endif' does not end the open block"),
        ("{% for a in [] %}{% endif %}", "'endif' does not end the open block"),
        ("{% else %}", "'else' is not in an if or for block"),
        ("{% raw %}x", "a raw block has no endraw"),
        ("select 1 -- no tag", "no Jinja tag"),
    ],
)
def test_the_rule_refuses_other_code(text, reason):
    found = j.scan(text)
    assert not found.ok
    assert found.reason() == reason


# The render settings.


def test_templated_files_get_the_jinja_templater_and_the_dbt_builtins():
    jinja = corpus_run.settings(m.JINJA)
    assert jinja["core"]["templater"] == "jinja"
    assert jinja["templater"] == {"jinja": {"apply_dbt_builtins": True}}
    raw = corpus_run.settings(m.RAW)
    assert raw["core"]["templater"] == "raw" and "templater" not in raw
    # The rest is the same for both templaters.
    del jinja["templater"]
    jinja["core"]["templater"] = "raw"
    assert jinja == raw


@pytest.mark.parametrize("adapter", [SqlfluffBench, SqlfluffRsBench, SqruffBench])
def test_each_tool_and_the_reference_get_the_render_settings(adapter):
    config = corpus_run.tool_config(adapter(), m.JINJA, "clickhouse")
    assert config["core"]["templater"] == "jinja"
    assert config["templater"]["jinja"] == {"apply_dbt_builtins": True}
    entry = m.CorpusFile(
        "s/a.sql", "s", "a.sql", "clickhouse", m.JINJA, 9000, 9, "0" * 64, True, "x"
    )
    ref = corpus_run.reference_config(entry)
    assert ref["core"]["dialect"] == "clickhouse"
    assert ref["templater"] == {"jinja": {"apply_dbt_builtins": True}}


# The parse check: the leaf text is the render, not the input.


def fake_run(tmp_path: Path, leaf_text: str, code: int = 0) -> Run:
    """A run of sqlfluff that printed a tree with this leaf text."""
    folder = tmp_path / "run"
    folder.mkdir()
    tree = [{"filepath": "input.sql", "segments": {"file": [{"raw": leaf_text}]}}]
    (folder / "stdout").write_text(json.dumps(tree), encoding="utf8")
    (folder / "stderr").write_bytes(b"")
    sample = Sample("warmup", 0.1, 0.1, 0.0, 1000, code, False)
    run = Run(sample, folder)
    assert run.stdout == folder / "stdout" and run.stderr == folder / "stderr"
    return run


TEMPLATE = "select {{ 1 + 1 }} from {{ ref('t') }}\n"
RENDER = "select 2 from t\n"


def test_a_tree_of_the_render_is_ok(tmp_path):
    what = "render of the pinned sqlfluff"
    run = fake_run(tmp_path, RENDER.replace("\n", "\r\n"))
    reason, found = corpus_run.check_run(SqlfluffBench(), run, RENDER, what)
    assert reason is None
    assert (found.status, found.unparsable) == ("ok", {"count": 0, "bytes": 0})


def test_a_tree_of_the_template_text_is_invalid(tmp_path):
    what = "render of the pinned sqlfluff"
    run = fake_run(tmp_path, TEMPLATE)
    reason, found = corpus_run.check_run(SqlfluffBench(), run, RENDER, what)
    assert found is None
    assert reason == (
        f"the tree text ({len(TEMPLATE)} characters) is not the render of the "
        f"pinned sqlfluff ({len(RENDER)} characters)"
    )


# The real tools.


HEAD = (
    "{{ config(materialized='incremental', unique_key='id') }}\n"
    "{% set cols = ['a', 'b', 'c'] %}\n"
    "{% macro total(xs) %}{% for x in xs %}{{ x }}"
    "{% if not loop.last %} + {% endif %}{% endfor %}{% endmacro %}\n"
)
STATEMENT = (
    'select id, {{ total(cols) }} as t, \'{{ var("region", "eu") }}\' as r\n'
    "from {{ source('raw', 'items') }} join {{ ref('other') }} using (id)\n"
    "{% if is_incremental() %}where id > (select max(id) from {{ this }})"
    "{% endif %};\n"
)


def templated_case(tmp: Path) -> tuple[Path, bytes]:
    """A manifest of one synthetic templated file of 8 KiB or more (ansi),
    in a fetch cache."""
    data = (HEAD + STATEMENT * (8 * KIB // len(STATEMENT) + 1)).encode()
    found = j.scan(data.decode())
    assert found.ok and found.reads == {
        "config",
        "var",
        "source",
        "ref",
        "is_incremental",
        "this",
        "loop",
    }
    sha = hashlib.sha256(data).hexdigest()
    manifest = {
        "format": 1,
        "sources": {
            "demo": {
                "repository": "https://github.com/example/demo-dbt",
                "commit": COMMIT,
                "license": "MIT",
                "copyright": ["Example Holder"],
                "license_files": [
                    {
                        "path": "LICENSE",
                        "bytes": len(LICENSE),
                        "sha256": hashlib.sha256(LICENSE).hexdigest(),
                    }
                ],
                "globs": ["models/*.sql"],
            }
        },
        "files": [
            {
                "id": "demo/models/m.sql",
                "source": "demo",
                "path": "models/m.sql",
                "dialect": "ansi",
                "templater": "jinja",
                "bytes": len(data),
                "lines": data.count(b"\n"),
                "sha256": sha,
                "smoke": True,
                "selection": "test",
            }
        ],
    }
    path = tmp / "sources.json"
    path.write_text(json.dumps(manifest, indent=1))
    root = tmp / "cache" / "demo" / COMMIT
    (root / "models").mkdir(parents=True)
    (root / "LICENSE").write_bytes(LICENSE)
    (root / "models" / "m.sql").write_bytes(data)
    return path, data


@needs_all_tools
def test_each_tool_parses_the_render_of_a_templated_file(tmp_path, capsys):
    path, data = templated_case(tmp_path)
    out = tmp_path / "templated.json"
    argv = ["run", "--manifest", path, "--cache", tmp_path / "cache"]
    code = corpus_main.main([*map(str, argv), "--profile", "smoke", "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 0, text
    rep = report.load(out)
    assert report.check(rep) == []
    entry = m.load(path).files[0]
    render, why = SqlfluffRender()(
        entry, data, corpus_run.reference_config(entry), tmp_path / "ref"
    )
    assert why is None
    # The dbt builtins: source, ref, this, var, and is_incremental() is true.
    assert "from raw_items join other using (id)" in render
    assert "a + b + c as t, 'item' as r" in render
    assert "where id > (select max(id) from this_model);" in render
    assert "{" not in render and render != data.decode()
    ref = rep["inputs"]["demo/models/m.sql"]["reference"]
    assert ref == {
        "status": "ok",
        "sha256": hashlib.sha256(render.encode()).hexdigest(),
        "reason": None,
    }
    for tool in ("sqlfluff", "sqlfluff-rs", "sqruff"):
        assert rep["tools"][tool]["settings"]["jinja"]["templater"] == {
            "jinja": {"apply_dbt_builtins": True}
        }
        (result,) = [r for r in rep["results"] if r["tool"] == tool]
        assert result["status"] == "ok", text
