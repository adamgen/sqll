"""A small test tree for the templater map of the S6 trace oracle.

S6: templater parity (sqll passes 100% of the placeholder and Python
format-string templater fixtures that do not need a Python runtime).
harness/tests/test_s6_harness.py copies this file to a new sqlfluff root and
runs scripts/s7-tests/trace-nodes --templaters on its nodes. The test_map_*
nodes use the process() calls that the map knows. The test_refuse_* nodes
use calls that the map must refuse (fail closed). It is not a test of the
harness (harness/tests/conftest.py ignores the fixtures).
"""

import datetime

import pytest
from sqlfluff.core import FluffConfig
from sqlfluff.core.errors import SQLFluffSkipFile, SQLTemplaterError
from sqlfluff.core.templaters import (
    JinjaTemplater,
    PlaceholderTemplater,
    PythonTemplater,
)

ANSI = {"dialect": "ansi"}


def test_map_placeholder():
    t = PlaceholderTemplater(override_context=dict(param_style="colon", a="1"))
    out, _ = t.process(
        in_str="SELECT :a FROM t\n", fname="test", config=FluffConfig(overrides=ANSI)
    )
    assert str(out) == "SELECT 1 FROM t\n"


def test_map_python_no_config():
    t = PythonTemplater(override_context=dict(tbl="my_table"))
    out, _ = t.process(in_str="SELECT * FROM {tbl}", fname="test")
    assert str(out) == "SELECT * FROM my_table"


def test_map_value_error():
    t = PlaceholderTemplater(override_context=dict(param_style="nope"))
    with pytest.raises(ValueError, match="Unknown param_style"):
        t.process(in_str="SELECT 1", fname="test")


def test_map_templater_error():
    t = PythonTemplater(override_context=dict(other="x"))
    with pytest.raises(SQLTemplaterError):
        t.process(in_str="SELECT {missing}", fname="test")


def test_map_skip_file():
    config = FluffConfig(overrides={**ANSI, "large_file_skip_char_limit": 2})
    with pytest.raises(SQLFluffSkipFile) as excinfo:
        PythonTemplater().process(in_str="SELECT 1", fname="test", config=config)
    assert "Length of file" in str(excinfo.value)


def test_refuse_jinja():
    config = FluffConfig(overrides=ANSI)
    out, _ = JinjaTemplater().process(in_str="SELECT 1", fname="test", config=config)
    assert str(out) == "SELECT 1"


def test_refuse_not_a_literal():
    context = dict(param_style="colon", d=datetime.date(2020, 1, 1))
    out, _ = PlaceholderTemplater(override_context=context).process(
        in_str="SELECT :d", fname="test"
    )
    assert str(out) == "SELECT 2020-01-01"


def test_refuse_config_from_kwargs():
    t = PythonTemplater(override_context=dict(tbl="t"))
    config = FluffConfig.from_kwargs(dialect="ansi")
    out, _ = t.process(in_str="SELECT * FROM {tbl}", fname="test", config=config)
    assert str(out) == "SELECT * FROM t"


def test_refuse_untraced_method():
    context = PythonTemplater(override_context=dict(a=1)).get_context("test", None)
    assert context["a"] == 1
