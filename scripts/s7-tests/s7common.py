"""Helpers of the S7-tests scripts (inventory and config-readers)."""

import contextlib
import os
import sys


def last_error_line(text: str) -> str:
    """The last "E" line of a pytest error text, without the "E" mark."""
    lines = [x[1:].strip() for x in text.splitlines() if x.startswith("E ")]
    return lines[-1] if lines else text.strip().splitlines()[-1]


@contextlib.contextmanager
def stdout_to_stderr():
    """Send file descriptor 1 to stderr. pytest writes to the descriptor."""
    sys.stdout.flush()
    saved = os.dup(1)
    os.dup2(2, 1)
    try:
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)
