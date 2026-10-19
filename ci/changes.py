#!/usr/bin/env python3
"""Tell if CI must run the full jobs: test shards, report, dialect oracles.

If each changed file is a document in DOCS, CI skips the full jobs. The
image and lint jobs always run: the unit tests read some documents (for
example STATUS.md). Each other change runs all jobs. If the changed files
are not known (git fails, a new branch, workflow_dispatch), CI runs all jobs.

Usage: ci/changes.py EVENT [BEFORE]
EVENT is the GitHub event name. BEFORE is the commit before a push.
Output: the changed files and the result, also in GITHUB_STEP_SUMMARY if
set. With GITHUB_OUTPUT set, it adds "full=true" or "full=false" to it.
"""

import os
import re
import subprocess
import sys
from fnmatch import fnmatchcase

# The paths of the documents. A "*" does not match "/". Do not add a path
# that a harness, script, tool, or CI command reads, other than the unit
# tests of the lint job.
DOCS = ("*.md", "harness/*.md")

_SHA = re.compile(r"[0-9a-f]{40}")


def is_doc(path: str) -> bool:
    parts = path.split("/")
    for pattern in DOCS:
        words = pattern.split("/")
        if len(words) == len(parts) and all(
            fnmatchcase(p, w) for p, w in zip(parts, words, strict=True)
        ):
            return True
    return False


def full_run(paths: list[str] | None) -> bool:
    """Return True if CI must run all jobs for these changed files."""
    return not paths or not all(is_doc(p) for p in paths)


def _git(*args: str, cwd: str | None = None) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
    except OSError:
        return None
    return out.stdout if out.returncode == 0 else None


def base_commit(event: str, before: str = "", cwd: str | None = None) -> str | None:
    """Return the commit to compare HEAD with, or None if it is not known.

    pull_request: HEAD is the merge commit; its first parent is the base.
    push: the commit before the push.
    """
    if event == "pull_request":
        parents = (
            _git("rev-list", "--parents", "-n", "1", "HEAD", cwd=cwd) or ""
        ).split()
        return parents[1] if len(parents) == 3 else None
    if event == "push" and _SHA.fullmatch(before) and before != "0" * 40:
        if _git("cat-file", "-e", f"{before}^{{commit}}", cwd=cwd) is not None:
            return before
    return None


def changed_files(
    event: str, before: str = "", cwd: str | None = None
) -> list[str] | None:
    base = base_commit(event, before, cwd)
    if base is None:
        return None
    out = _git("diff", "--no-renames", "--name-only", base, "HEAD", cwd=cwd)
    return None if out is None else out.splitlines()


def main(argv: list[str]) -> int:
    event, before = (argv + [""])[:2]
    paths = changed_files(event, before)
    full = full_run(paths)
    if paths is None:
        text = [f"Changed files: not known (event {event})."]
    else:
        text = [f"Changed files ({len(paths)}):"]
        text += [f"- {'doc' if is_doc(p) else 'code'}: {p}" for p in paths]
    if full:
        text.append("Result: full run. CI runs all jobs.")
    else:
        text.append(
            "Result: documents only. CI runs the image and lint jobs and skips"
            " the test shards, the report, and the dialect oracles."
        )
    print("\n".join(text))
    for name, line in (
        ("GITHUB_OUTPUT", f"full={'true' if full else 'false'}"),
        ("GITHUB_STEP_SUMMARY", "\n".join(text)),
    ):
        if os.environ.get(name):
            with open(os.environ[name], "a", encoding="utf8") as fh:
                fh.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
