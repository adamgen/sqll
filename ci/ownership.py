#!/usr/bin/env python3
"""Check that a pull request changes only paths that its track can change.

tracks.yml gives the tracks, their branches, and the paths that each track
owns (PROCESS.md, "Tracks"). The branch of the pull request gives its
track. A branch that no track has gets the rules of the Core track. The
check fails if the pull request changes a path that another track owns,
unless the pull request has the label LABEL. With the label, the check
passes and names the tracks that must review the pull request.

The rules come from the tracks.yml of the base commit (the first parent of
the merge commit HEAD). Thus a pull request cannot give its track more
paths: tracks.yml is a Core path. If the pull request changes tracks.yml,
the check also uses the new tracks.yml, and both checks must pass. Only if
the base has no tracks.yml (the pull request that adds it), the check uses
the tracks.yml of the pull request.

A pull request from a fork gets no track: each owned path that it changes
needs the label. The check coordinates the tracks; it is not a security
gate. As with ci/changes.py, a pull request that changes this file or
ci/changes.py runs its own version of them. Thus reviewers must examine
each change to ci/ and to harness/tests/test_ownership.py carefully.

The check fails closed: if git fails, if a tracks.yml is not correct, if
two tracks have the branch, or if PyYAML is not available, it fails. The
workflow runs it with the python3 of the runner image (ubuntu-latest has
PyYAML); the unit tests run it with the harness environment.

Usage: ci/ownership.py EVENT
EVENT is the GitHub event name. Only pull_request is checked. Env: BRANCH
(the head branch), LABELS (a JSON list of the label names), REPO (this
repository), and HEAD_REPO (the repository of the head branch).
Output: the changed files with their owners and the result, also in
GITHUB_STEP_SUMMARY if set. Exit code 0: pass, 1: fail.
"""

import json
import os
import sys
from fnmatch import fnmatchcase
from pathlib import Path

from changes import _git, base_commit, changed_files

ROOT = Path(__file__).resolve().parents[1]
TRACKS_FILE = ROOT / "tracks.yml"
CORE = "core"
LABEL = "cross-track"


class TracksError(Exception):
    """tracks.yml is not correct, or the branch is in two tracks."""


def matches(pattern: str, path: str) -> bool:
    """Return True if the path matches the glob. "*" does not match "/".
    "**" matches zero or more folders."""

    def match(words: list[str], parts: list[str]) -> bool:
        if not words:
            return not parts
        if words[0] == "**":
            return any(match(words[1:], parts[i:]) for i in range(len(parts) + 1))
        return (
            bool(parts)
            and fnmatchcase(parts[0], words[0])
            and match(words[1:], parts[1:])
        )

    return match(pattern.split("/"), path.split("/"))


def parse(text: str, source: str) -> dict[str, dict]:
    """Return {track: {"branches": [...], "paths": [...]}} from the text of
    a tracks.yml."""
    try:
        import yaml
    except ImportError:
        raise TracksError("PyYAML is not available") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise TracksError(f"{source}: cannot read: {exc}") from None
    return validate(data)


def load(path: Path = TRACKS_FILE) -> dict[str, dict]:
    """Return the tracks of a tracks.yml file."""
    try:
        text = path.read_text(encoding="utf8")
    except OSError as exc:
        raise TracksError(f"{path}: cannot read: {exc}") from None
    return parse(text, str(path))


def tracks_text(commit: str, cwd: str | None = None) -> str | None:
    """Return the text of tracks.yml in a commit, or None if it has none."""
    listed = _git(
        "ls-tree", "--full-tree", "--name-only", commit, "--", "tracks.yml", cwd=cwd
    )
    text = _git("show", f"{commit}:tracks.yml", cwd=cwd) if listed else ""
    if listed is None or text is None:
        raise ValueError(f"cannot read the tracks.yml of {commit} (git failed)")
    return text if listed.strip() else None


def rule_sets(cwd: str | None = None) -> list[tuple[str, dict[str, dict]]]:
    """Return the tracks.yml files that the check uses, with a name for each.

    The tracks.yml of the base commit, and the tracks.yml of HEAD if it is
    different. Only the tracks.yml of HEAD if the base has none."""
    base = base_commit(cwd)
    if base is None:
        raise ValueError("the base commit is not known (git failed)")
    base_text = tracks_text(base, cwd)
    head_text = tracks_text("HEAD", cwd)
    if head_text is None:
        raise TracksError("the pull request has no tracks.yml")
    head = ("the pull request", parse(head_text, "HEAD:tracks.yml"))
    if base_text is None:
        return [(f"{head[0]} (the base has no tracks.yml)", head[1])]
    sets = [(f"the base {base[:12]}", parse(base_text, f"{base[:12]}:tracks.yml"))]
    if head_text != base_text:
        sets.append((f"{head[0]} (it changes tracks.yml)", head[1]))
    return sets


def validate(data: object) -> dict[str, dict]:
    tracks = data.get("tracks") if isinstance(data, dict) else None
    if not isinstance(tracks, dict) or CORE not in tracks:
        raise TracksError(f"tracks.yml: no 'tracks' map with the track {CORE!r}")
    for name, track in tracks.items():
        if not isinstance(track, dict):
            raise TracksError(f"{name}: not a map")
        for key in ("branches", "paths"):
            value = track.get(key)
            if not isinstance(value, list) or not all(
                isinstance(v, str) and v for v in value
            ):
                raise TracksError(f"{name}: {key!r} is not a list of globs")
    return tracks


def track_of_branch(branch: str, tracks: dict[str, dict]) -> tuple[str, bool]:
    """Return the track of a branch, and True if a track has the branch.

    A branch that no track has gets the Core track (False)."""
    found = [
        name
        for name, t in tracks.items()
        if any(matches(p, branch) for p in t["branches"])
    ]
    if len(found) > 1:
        raise TracksError(f"branch {branch}: in the tracks {', '.join(found)}")
    return (found[0], True) if found else (CORE, False)


def owner(path: str, tracks: dict[str, dict]) -> str | None:
    """Return the track that owns a path, or None if no track owns it."""
    found = [
        name
        for name, t in tracks.items()
        if name != CORE and any(matches(p, path) for p in t["paths"])
    ]
    if len(found) > 1:
        raise TracksError(f"{path}: owned by the tracks {', '.join(found)}")
    if found:
        return found[0]
    if any(matches(p, path) for p in tracks[CORE]["paths"]):
        return CORE
    return None


def check(
    branch: str,
    labels: list[str],
    paths: list[str],
    tracks: dict[str, dict],
    fork: bool = False,
) -> tuple[bool, list[str]]:
    """Return True if the pull request can change these paths, and the text.

    A pull request from a fork (fork=True) gets no track."""
    if fork:
        track = None
        text = [f"Branch {branch} of a fork: no track."]
    else:
        track, known = track_of_branch(branch, tracks)
        how = "" if known else " (no track has this branch: Core track rules)"
        text = [f"Branch {branch}: track {track}{how}."]
    text.append(f"Changed files ({len(paths)}):")
    others: dict[str, list[str]] = {}
    for path in paths:
        own = owner(path, tracks)
        if own is not None and own != track:
            others.setdefault(own, []).append(path)
            text.append(f"- {path}: owned by {own} (another track)")
        else:
            text.append(f"- {path}: {'owned by ' + own if own else 'no owner'}")
    if not others:
        text.append("Result: pass. Each changed file is of this track or has no owner.")
        return True, text
    names = ", ".join(sorted(others))
    if LABEL in labels:
        text.append(
            f"Result: pass with the label {LABEL!r}. These tracks must review"
            f" the pull request: {names}."
        )
        return True, text
    text.append(
        f"Result: fail. The pull request changes files of the tracks {names}."
        f" Ask the owning track for the change (an issue), or add the label"
        f" {LABEL!r} and get a review from the owning track."
    )
    return False, text


def main(argv: list[str]) -> int:
    event = (argv + [""])[0]
    if event != "pull_request":
        print(f"Event {event}: not a pull request. No ownership check.")
        return 0
    try:
        labels = json.loads(os.environ.get("LABELS") or "[]")
        if not isinstance(labels, list):
            raise ValueError("not a list")
        branch = os.environ.get("BRANCH", "")
        if not branch:
            raise ValueError("BRANCH is not set")
        repo = os.environ.get("REPO", "")
        fork = bool(repo) and os.environ.get("HEAD_REPO", "") != repo
        paths = changed_files(event)
        if paths is None:
            raise ValueError("the changed files are not known (git failed)")
        ok, text = True, []
        for name, tracks in rule_sets():
            one_ok, one_text = check(branch, labels, paths, tracks, fork)
            ok = ok and one_ok
            text += [f"Rules: the tracks.yml of {name}.", *one_text, ""]
        text.append(f"Result: {'pass' if ok else 'fail'}.")
    except (TracksError, ValueError, OSError) as exc:
        ok, text = False, [f"error: {exc}", "Result: fail."]
    print("\n".join(text))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf8") as fh:
            fh.write("\n".join(text) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
