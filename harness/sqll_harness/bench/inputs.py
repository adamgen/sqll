"""Benchmark inputs, built at run time from the sqlfluff dialect fixtures.

The selection, join, and fill rules are in harness/bench.md ("Inputs"). The
builder reads the fixtures in place. It writes only to the output folder,
never to the fixtures or to the repository (except below out/).
"""

import hashlib
import json
import os
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .. import known_failures
from ..compare import Struct, load_yaml
from ..paths import OUT_DIR, REPO_ROOT, sqlfluff_ref
from ..suites.dialects import DEEP_PARSE_DEPTH_OVERRIDES, FIXTURE_DIR

SIZES = {"small": 1024, "medium": 4096, "large": 16384}
START = "start"
START_SQL = b"SELECT 1;\n"
TERMINATORS = frozenset({"statement_terminator", "function_script_terminator", "slash"})
EXCLUSIONS = Path(__file__).with_name("exclusions.txt")
MANIFEST = "manifest.json"
MANIFEST_KIND = "sqll-bench-inputs"
DEFAULT_OUT = OUT_DIR / "bench" / "inputs"

# sqlfluff reads a line that starts with "-- sqlfluff" or "--sqlfluff" as
# config (FluffConfig.process_raw_file_for_config). This pattern also finds
# leading white space and other letter case, so it finds more, not fewer.
_IN_FILE_CONFIG = re.compile(rb"^[ \t]*--[ \t]*sqlfluff", re.IGNORECASE | re.MULTILINE)

# Skip reasons in the sequence of the selection rules of harness/bench.md.
NO_TREE = "no_tree"
UNPARSABLE_TREE = "unparsable_tree"
IN_FILE_CONFIG = "in_file_config"
CONFIG_OVERRIDE = "config_override"
EXCLUDED = "excluded"
NO_LEAF = "no_leaf"
SKIP_REASONS = (
    NO_TREE,
    UNPARSABLE_TREE,
    IN_FILE_CONFIG,
    CONFIG_OVERRIDE,
    EXCLUDED,
    NO_LEAF,
)
ADDED_NEWLINE = "newline"
ADDED_TERMINATOR = "terminator"


class BuildError(Exception):
    """The inputs cannot be built as harness/bench.md specifies."""


@dataclass(frozen=True)
class Piece:
    """One selected fixture file with the text that the join adds."""

    path: str  # relative to test/fixtures/dialects/, for example "ansi/a.sql"
    data: bytes
    added: tuple[str, ...]


@dataclass(frozen=True)
class Selection:
    files: int
    pieces: dict[str, list[Piece]]  # dialect -> pieces in sorted path order
    skipped: dict[str, list[str]]  # skip reason -> paths


@dataclass(frozen=True)
class Input:
    name: str  # "start" or "<dialect>/<size>"
    data: bytes
    files: tuple[str, ...]  # the fixture files in input order, with repeats
    passes: int

    @property
    def file(self) -> str:
        return f"{self.name}.sql"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def lines(self) -> int:
        return self.data.count(b"\n")

    @property
    def repeats(self) -> int:
        return len(self.files) - len(set(self.files))


@dataclass(frozen=True)
class Build:
    sqlfluff_ref: str
    selection: Selection
    inputs: dict[str, Input]

    @property
    def dialects(self) -> list[str]:
        return sorted(self.selection.pieces)


def fixture_dir(sqlfluff_root: Path) -> Path:
    return sqlfluff_root / FIXTURE_DIR


def dialect_folders(sqlfluff_root: Path) -> list[str]:
    """Return the names of the dialect folders of the fixtures, sorted."""
    base = fixture_dir(sqlfluff_root)
    return sorted(name for name in os.listdir(base) if (base / name).is_dir())


def load_exclusions(path: Path, sqlfluff_root: Path) -> dict[str, str]:
    """Return {path: reason} of the exclusion file.

    Each entry must have a reason and must be a SQL file of the fixtures.
    """
    try:
        entries = known_failures.parse(path.read_text(encoding="utf8"), str(path))
    except known_failures.KnownFailuresError as exc:
        raise BuildError(str(exc)) from None
    base = fixture_dir(sqlfluff_root)
    for entry, reason in entries.items():
        if not reason:
            raise BuildError(f"{path}: {entry} has no reason")
        if not entry.endswith(".sql") or not (base / entry).is_file():
            raise BuildError(f"{path}: {entry} is not a SQL file of the fixtures")
    return entries


def _nodes(tree: Struct) -> Iterator[tuple[str, Struct]]:
    """Yield the (name, value) nodes of a tree in document order."""
    stack = [tree]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node[1], tuple):
            stack.extend(reversed(node[1]))


def _leaves(tree: Struct) -> list[str]:
    return [name for name, value in _nodes(tree) if isinstance(value, str)]


def _piece(path: str, data: bytes, last_leaf: str) -> Piece:
    added = []
    if not data.endswith(b"\n"):
        data += b"\n"
        added.append(ADDED_NEWLINE)
    if last_leaf not in TERMINATORS:
        data += b";\n"
        added.append(ADDED_TERMINATOR)
    return Piece(path, data, tuple(added))


def _classify(sql: Path, path: str, exclusions: dict[str, str]):
    """Return (skip reason, None) or (None, piece) for one fixture file."""
    yml = sql.with_suffix(".yml")
    if not yml.is_file():
        return NO_TREE, None
    _, tree = load_yaml(yml)
    names = [] if tree is None else [name for name, _ in _nodes(tree)]
    if "unparsable" in names:
        return UNPARSABLE_TREE, None
    data = sql.read_bytes()
    if _IN_FILE_CONFIG.search(data):
        return IN_FILE_CONFIG, None
    dialect, name = path.split("/")
    if (dialect, name) in DEEP_PARSE_DEPTH_OVERRIDES:
        return CONFIG_OVERRIDE, None
    if path in exclusions:
        return EXCLUDED, None
    leaves = [] if tree is None else _leaves(tree)
    if not leaves:
        return NO_LEAF, None
    return None, _piece(path, data, leaves[-1])


def select(sqlfluff_root: Path, exclusions: dict[str, str]) -> Selection:
    """Apply the selection and join rules to each dialect SQL file."""
    base = fixture_dir(sqlfluff_root)
    pieces: dict[str, list[Piece]] = {}
    skipped: dict[str, list[str]] = {reason: [] for reason in SKIP_REASONS}
    files = 0
    for dialect in dialect_folders(sqlfluff_root):
        pieces[dialect] = []
        for name in sorted(os.listdir(base / dialect)):
            if not name.endswith(".sql"):
                continue
            files += 1
            path = f"{dialect}/{name}"
            reason, piece = _classify(base / path, path, exclusions)
            if reason:
                skipped[reason].append(path)
            else:
                pieces[dialect].append(piece)
    return Selection(files, pieces, skipped)


def fill(pieces: list[Piece], target: int) -> tuple[list[Piece], int]:
    """Return the pieces of one input and the number of passes that added one.

    In each pass, add each piece (in sorted path order) that keeps the input
    at or below target bytes. Stop after a pass that adds no piece.
    """
    out: list[Piece] = []
    size = 0
    passes = 0
    while True:
        added = False
        for piece in pieces:
            if size + len(piece.data) <= target:
                out.append(piece)
                size += len(piece.data)
                added = True
        if not added:
            return out, passes
        passes += 1


def build(sqlfluff_root: Path, exclusions_path: Path = EXCLUSIONS) -> Build:
    """Build all inputs in memory."""
    if not fixture_dir(sqlfluff_root).is_dir():
        raise BuildError(
            f"{sqlfluff_root} has no dialect fixtures. Run: git submodule update --init"
        )
    exclusions = load_exclusions(exclusions_path, sqlfluff_root)
    selection = select(sqlfluff_root, exclusions)
    inputs = {START: Input(START, START_SQL, (), 0)}
    for dialect, pieces in selection.pieces.items():
        for size, target in SIZES.items():
            chosen, passes = fill(pieces, target)
            if not chosen:
                raise BuildError(f"{dialect}/{size}: no selected file fits")
            name = f"{dialect}/{size}"
            data = b"".join(p.data for p in chosen)
            inputs[name] = Input(name, data, tuple(p.path for p in chosen), passes)
    return Build(sqlfluff_ref(sqlfluff_root), selection, inputs)


def manifest(result: Build) -> dict:
    """Return the manifest: how each input was built."""
    sel = result.selection
    used = [p for pieces in sel.pieces.values() for p in pieces]
    return {
        "kind": MANIFEST_KIND,
        "format": 1,
        "sqlfluff_ref": result.sqlfluff_ref,
        "fixtures": FIXTURE_DIR.as_posix(),
        "sizes": SIZES,
        "selection": {
            "files": sel.files,
            "used": len(used),
            "skipped": sel.skipped,
            "added": {
                kind: [p.path for p in used if kind in p.added]
                for kind in (ADDED_NEWLINE, ADDED_TERMINATOR)
            },
        },
        "inputs": {
            name: {
                "file": i.file,
                "bytes": len(i.data),
                "lines": i.lines,
                "sha256": i.sha256,
                "passes": i.passes,
                "repeats": i.repeats,
                "files": list(i.files),
            }
            for name, i in result.inputs.items()
        },
    }


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def check_out_dir(out: Path, sqlfluff_root: Path) -> str | None:
    """Return why the inputs must not go to out, or None if they can."""
    out = out.resolve()
    if _inside(out, sqlfluff_root.resolve()):
        return f"{out} is in the sqlfluff checkout"
    out_root = OUT_DIR.resolve()
    if _inside(out, REPO_ROOT.resolve()) and not (
        out != out_root and _inside(out, out_root)
    ):
        return f"{out} is in the repository. Use a folder below {out_root}"
    if out.exists() and not out.is_dir():
        return f"{out} is not a folder"
    if out.is_dir() and any(out.iterdir()) and not _is_old_build(out):
        return f"{out} is not empty and has no {MANIFEST} of an earlier build"
    return None


def _is_old_build(out: Path) -> bool:
    try:
        old = json.loads((out / MANIFEST).read_text(encoding="utf8"))
    except (OSError, ValueError):
        return False
    return isinstance(old, dict) and old.get("kind") == MANIFEST_KIND


def manifest_text(result: Build) -> str:
    return json.dumps(manifest(result), indent=1) + "\n"


def write(result: Build, out: Path) -> None:
    """Write the inputs and the manifest to out. Call check_out_dir first.

    An earlier build in out is removed, so out has only this build.
    """
    if out.is_dir() and _is_old_build(out):
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for i in result.inputs.values():
        path = out / i.file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(i.data)
    (out / MANIFEST).write_text(manifest_text(result), encoding="utf8")
