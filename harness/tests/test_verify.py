"""scripts/verify must run each check of CI (harness/sqll_harness/verify.py).

If CI gets a new step, add a check for it to verify.checks(), or add it to
verify.CI_ONLY if it is CI mechanics only.
"""

from collections import defaultdict

import pytest

from sqll_harness import verify

STEPS = verify.ci_steps()
KEYS = [key for key, _, _ in STEPS]
CHECKS = verify.checks()


def _local_words() -> dict[str, set[str]]:
    out = defaultdict(set)
    for check in CHECKS:
        for key in check.ci:
            out[key] |= verify.words(check.command) | set(check.ci_only_words)
    return out


def test_ci_step_names_are_unique():
    assert len(KEYS) == len(set(KEYS))


@pytest.mark.parametrize("key", KEYS)
def test_each_ci_step_is_verified_or_ci_only(key):
    covered = {k for c in CHECKS for k in c.ci}
    assert (key in covered) != (key in verify.CI_ONLY), (
        f"CI step {key!r}: add it to one of verify.checks() or verify.CI_ONLY"
    )


def test_no_stale_names():
    names = set(KEYS)
    assert not set(verify.CI_ONLY) - names
    assert not {k for c in CHECKS for k in c.ci} - names


def test_each_ci_command_word_is_in_the_local_commands():
    local = _local_words()
    for key, step, job in STEPS:
        if key in verify.CI_ONLY:
            continue
        for text in verify.ci_commands(step, job):
            missing = verify.words(text) - local[key]
            assert not missing, f"{key}: {sorted(missing)}"


def test_word_check_finds_a_change():
    step = {"run": "scripts/x --a\n  --b $V", "env": {"V": "--c"}}
    assert verify.words(verify.ci_commands(step, {})[0]) == {
        "scripts/x",
        "--a",
        "--b",
        "--c",
    }
    job = {"strategy": {"matrix": {"include": [{"a": "1"}, {"a": ""}]}}}
    assert verify.ci_commands({"run": "x ${{ matrix.a }} ${{ y }}"}, job) == [
        "x 1 {}",
        "x  {}",
    ]


def test_check_names_are_unique_and_local_only_checks_are_few():
    names = [c.name for c in CHECKS]
    assert len(names) == len(set(names))
    assert [c.name for c in CHECKS if not c.ci] == ["setup", "submodule-before"]


def test_quick_has_no_run_or_report_check():
    for check in CHECKS:
        if check.quick:
            assert verify.REPORT_FILE not in check.needs
            assert check.name != "run"


def test_jobs_goes_to_the_run_only():
    changed = [c for a, c in zip(CHECKS, verify.checks(3), strict=True) if a != c]
    assert [c.name for c in changed] == ["run"]
    assert " --jobs 3 " in changed[0].command
