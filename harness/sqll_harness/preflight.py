"""Fail if a parent folder of the repository, or the temp folder or one of
its parents, has a sqlfluff config file.

sqlfluff reads the config files in each folder above a SQL file (also above
the user home), and the harness does the same for sqruff. Some suites write
cases to the temp folder (tempfile.gettempdir(), set by TMPDIR). Such a file
outside the repository changes the results of a local run. CI has no such
file. scripts/test and scripts/verify run this check first.

Usage: python -m sqll_harness.preflight [ROOT]. Exit code 2 if a file is
found.
"""

import re
import sys
import tempfile
import tomllib
from pathlib import Path

from .paths import REPO_ROOT

INI_FILES = ("setup.cfg", "tox.ini", "pep8.ini")
# A [sqlfluff] or [sqlfluff:...] section. This can find more than sqlfluff
# reads, never less.
_INI_SECTION = re.compile(r"^\s*\[\s*sqlfluff\s*(:[^\]\n]*)?\]", re.MULTILINE)


def _reason(path: Path) -> str | None:
    """Return why sqlfluff can read config from path, or None."""
    if not path.is_file():
        return None
    if path.name == ".sqlfluff":
        return "a .sqlfluff file"
    text = path.read_bytes().decode("utf8", errors="replace")
    if path.name == "pyproject.toml":
        try:
            tool = tomllib.loads(text).get("tool", {})
        except tomllib.TOMLDecodeError:
            return "a pyproject.toml file that is not valid TOML"
        return "a [tool.sqlfluff] table" if "sqlfluff" in tool else None
    return "a [sqlfluff] section" if _INI_SECTION.search(text) else None


def _configs(folders: list[Path]) -> list[tuple[Path, str]]:
    found = []
    for folder in dict.fromkeys(folders):
        for name in (*INI_FILES, ".sqlfluff", "pyproject.toml"):
            reason = _reason(folder / name)
            if reason:
                found.append((folder / name, reason))
    return found


def parent_configs(root: Path) -> list[tuple[Path, str]]:
    """Return each sqlfluff config file in a parent folder of root.

    The parents of the path as given and of the resolved path are examined.
    """
    return _configs([*Path(root).absolute().parents, *Path(root).resolve().parents])


def temp_configs() -> list[tuple[Path, str]]:
    """Return each sqlfluff config file in the temp folder or a parent of it."""
    temp = Path(tempfile.gettempdir())
    folders = []
    for path in (temp.absolute(), temp.resolve()):
        folders += [path, *path.parents]
    return _configs(folders)


def find(root: Path) -> list[tuple[Path, str]]:
    """Return parent_configs(root) and temp_configs(), each file one time."""
    return list(dict.fromkeys([*parent_configs(root), *temp_configs()]))


def message(found: list[tuple[Path, str]]) -> str:
    lines = [
        "error: a parent folder of the repository, or the temp folder or one of "
        "its parents, has a sqlfluff config file:",
        *(f"  {path}: {reason}" for path, reason in found),
        "sqlfluff and the harness read these files, so the results are not "
        "the CI results.",
        "Move these files, or use a checkout and a TMPDIR with no such file above "
        "them.",
    ]
    return "\n".join(lines)


def check(root: Path = REPO_ROOT) -> int:
    """Print an error and return 2 if a parent config file exists, else 0."""
    found = find(root)
    if found:
        print(message(found), file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]) if args else REPO_ROOT
    # Also the location of this module: the harness that runs.
    return check(root) or (check(REPO_ROOT) if root != REPO_ROOT else 0)


if __name__ == "__main__":
    sys.exit(main())
