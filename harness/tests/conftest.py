"""Shared test helpers.

Tests that need an installed tool skip when it is not installed. With
SQLL_REQUIRE_TOOLS=1 (scripts/test and CI) such a skip is a failure, so a
missing tool cannot hide a test.
"""

import os

import pytest

from sqll_harness.paths import tools_dir


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


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    rep = yield
    if rep.skipped and os.environ.get("SQLL_REQUIRE_TOOLS") == "1":
        rep.outcome = "failed"
        rep.longrepr = f"skipped, but SQLL_REQUIRE_TOOLS=1: {rep.longrepr}"
    return rep
