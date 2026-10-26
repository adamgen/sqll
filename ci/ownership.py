#!/usr/bin/env python3
"""Check that a pull request changes only paths that its track can change.

tracks.yml gives the tracks, their branches, and the paths that each track
owns (PROCESS.md, "Tracks"). The branch of the pull request gives its
track. A branch that no track has gets the rules of the Core track. The
check fails if the pull request changes a path that another track owns,
unless the pull request has the label LABEL. With the label, the check
passes and names the tracks that must review the pull request.

The check fails closed: if git fails, if tracks.yml is not correct, or if
two tracks have the branch, it fails.

Usage: ci/ownership.py EVENT
EVENT is the GitHub event name. Only pull_request is checked. Env: BRANCH
(the head branch) and LABELS (a JSON list of the label names).
Output: the changed files with their owners and the result, also in
GITHUB_STEP_SUMMARY if set. Exit code 0: pass, 1: fail.
"""

import json
import os
import sys
from fnmatch import fnmatchcase
from pathlib import Path

from changes import changed_files

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


def load(path: Path = TRACKS_FILE) -> dict[str, dict]:
    """Return {track: {"branches": [...], "paths": [...]}} from tracks.yml."""
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TracksError(f"{path}: cannot read: {exc}") from None
    return validate(data)


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
    branch: str, labels: list[str], paths: list[str], tracks: dict[str, dict]
) -> tuple[bool, list[str]]:
    """Return True if the pull request can change these paths, and the text."""
    track, known = track_of_branch(branch, tracks)
    how = "" if known else " (no track has this branch: Core track rules)"
    text = [f"Branch {branch}: track {track}{how}.", f"Changed files ({len(paths)}):"]
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
        paths = changed_files(event)
        if paths is None:
            raise ValueError("the changed files are not known (git failed)")
        ok, text = check(branch, labels, paths, load())
    except (TracksError, ValueError) as exc:
        ok, text = False, [f"error: {exc}", "Result: fail."]
    print("\n".join(text))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf8") as fh:
            fh.write("\n".join(text) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
