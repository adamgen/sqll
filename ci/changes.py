#!/usr/bin/env python3
"""Tell if CI must run the full jobs: test shards, report, dialect oracles.

Only a pull request can skip the full jobs: if each file that the pull
request changes is a document in DOCS. The image and lint jobs always run:
the unit tests read some documents (for example STATUS.md). Each other
change runs all jobs. A push or another event always runs all jobs. Thus
each push to main gets a full run, also if GitHub cancels a pending run of
an earlier push. If git fails, CI runs all jobs.

Usage: ci/changes.py EVENT
EVENT is the GitHub event name.
Output: the changed files and the result, also in GITHUB_STEP_SUMMARY if
set. With GITHUB_OUTPUT set, it adds "full=true" or "full=false" to it.
CI runs the full jobs unless the output is "full=false".
"""

import os
import subprocess
import sys
from fnmatch import fnmatchcase

# The paths of the documents. A "*" does not match "/". Do not add a path
# that a harness, script, tool, or CI command reads, other than the unit
# tests of the lint job.
DOCS = ("*.md", "harness/*.md")


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


def changed_files(event: str, cwd: str | None = None) -> list[str] | None:
    """Return the files that a pull request changes, or None.

    None: the event is not pull_request, or git fails. In a pull_request
    run, HEAD is the merge commit; its first parent is the base.
    """
    if event != "pull_request":
        return None
    parents = (_git("rev-list", "--parents", "-n", "1", "HEAD", cwd=cwd) or "").split()
    if len(parents) != 3:
        return None
    out = _git("diff", "--no-renames", "--name-only", parents[1], "HEAD", cwd=cwd)
    return None if out is None else out.splitlines()


def main(argv: list[str]) -> int:
    event = (argv + [""])[0]
    paths = changed_files(event)
    full = full_run(paths)
    if event != "pull_request":
        text = [f"Event {event}: not a pull request. CI does not compare files."]
    elif paths is None:
        text = ["Changed files: not known (git failed)."]
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
