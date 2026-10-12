#!/usr/bin/env python3
"""Print the tag of the CI image: a hash of all inputs of ci/Dockerfile.

The inputs are the files in INPUTS (folders recursively), with their path,
content, and executable bit. The Dockerfile pins the base images, the Rust
toolchain, and uv, so a change to any of them changes the tag too.
.dockerignore keeps the build context equal to INPUTS.

Usage: ci/image_tag.py [--list]
"""

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = b"sqll-ci-image 1\n"
TAG_LENGTH = 20

INPUTS = (
    ".dockerignore",
    "ci/Dockerfile",
    "ci/image_tag.py",
    "ci/uv-requirements.txt",
    "harness/pyproject.toml",
    "harness/uv.lock",
    "scripts/setup",
    "tools",
)
# Local state that is not an input. .dockerignore excludes the same names.
IGNORED_NAMES = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}


def input_files(root: Path = ROOT) -> list[str]:
    """Return the input files as sorted paths relative to root."""
    files = []
    for name in INPUTS:
        path = root / name
        if path.is_file():
            files.append(name)
            continue
        if not path.is_dir():
            raise FileNotFoundError(f"image input {name} does not exist")
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_NAMES)
            for f in filenames:
                if f.endswith(".pyc"):
                    continue
                files.append((Path(dirpath) / f).relative_to(root).as_posix())
    return sorted(files)


def compute(entries: dict[str, tuple[bytes, bool]]) -> str:
    """Return the tag for {path: (content, executable)}."""
    h = hashlib.sha256(SCHEMA)
    for path in sorted(entries):
        content, executable = entries[path]
        digest = hashlib.sha256(content).hexdigest()
        h.update(f"{path}\0{int(executable)}\0{digest}\n".encode())
    return h.hexdigest()[:TAG_LENGTH]


def read_inputs(root: Path = ROOT) -> dict[str, tuple[bytes, bool]]:
    entries = {}
    for name in input_files(root):
        path = root / name
        entries[name] = (path.read_bytes(), os.access(path, os.X_OK))
    return entries


def main(argv: list[str]) -> int:
    if argv == ["--list"]:
        print("\n".join(input_files()))
        return 0
    if argv:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    print(compute(read_inputs()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
