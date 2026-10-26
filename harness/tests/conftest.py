"""Shared test helpers.

Tests that need an installed tool skip when it is not installed. With
SQLL_REQUIRE_TOOLS=1 (scripts/test and CI) such a skip is a failure, so a
missing tool cannot hide a test.
"""

import importlib.util
import os
import sys

import pytest

from sqll_harness.paths import REPO_ROOT, tools_dir

# The fixtures have Python files that are not tests, for example the case
# table of the templater fixtures (test/core/templaters/jinja_test.py).
collect_ignore_glob = ["fixtures/*"]


def needs(*relative_paths: str) -> pytest.MarkDecorator:
    """Skip the test if a path in the tools folder does not exist."""
    missing = [p for p in relative_paths if not (tools_dir() / p).exists()]
    return pytest.mark.skipif(
        bool(missing), reason=f"tool not installed ({missing}); run scripts/setup"
    )


needs_sqlfluff = needs("sqlfluff/bin/sqlfluff")
needs_all_tools = needs(
    "sqlfluff/bin/sqlfluff",
    "sqlfluff-rs/bin/sqlfluff",
    "sqruff/bin/sqruff",
    "sqruff/python/bin/python3",
)


def ci_module(name: str):
    """Load the CI script ci/<name>.py as a module. The ci folder goes on
    sys.path, because ci/ownership.py imports ci/changes.py."""
    ci = str(REPO_ROOT / "ci")
    if ci not in sys.path:
        sys.path.insert(0, ci)
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "ci" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def bench_inputs_dir(tmp_path_factory):
    """The benchmark inputs of the definitions, built in a temp folder."""
    from sqll_harness.bench import inputs
    from sqll_harness.paths import SQLFLUFF_ROOT

    out = tmp_path_factory.mktemp("bench") / "inputs"
    inputs.write(inputs.build(SQLFLUFF_ROOT), out)
    return out


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    rep = yield
    if rep.skipped and os.environ.get("SQLL_REQUIRE_TOOLS") == "1":
        rep.outcome = "failed"
        rep.longrepr = f"skipped, but SQLL_REQUIRE_TOOLS=1: {rep.longrepr}"
    return rep
