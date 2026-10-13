"""The case table of the harness templater fixtures.

It has the form of test__templater_full in the sqlfluff file
test/core/templaters/jinja_test.py. The harness and
scripts/sqlfluff-templater-oracle use only the table. The key prefix of each
subpath is the result of the sqlfluff test.
"""

import pytest


@pytest.mark.parametrize(
    "subpath,code_only,include_meta",
    [
        ("cases/expect_pass_basic", True, False),
        ("cases/expect_pass_empty_code_only", True, False),
        ("cases/expect_fail_empty_null", True, False),
        ("cases/expect_pass_meta", False, True),
        ("cases/expect_fail_meta_missing", False, True),
        ("cases/expect_fail_meta_positions", False, True),
        ("cases/expect_pass_tmp_violation", True, False),
        ("cases/expect_fail_unparsable", True, False),
        ("cases/expect_fail_no_yml", True, False),
    ],
)
def test__templater_full(subpath, code_only, include_meta):
    """Not a test. Only the table is used."""
