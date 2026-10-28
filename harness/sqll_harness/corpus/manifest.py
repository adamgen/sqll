"""The corpus manifest: corpus/sources.json (corpus/README.md).

load() reads a manifest and validate() examines it. Each error stops the
load (fail closed): an unknown or missing key, a value of the wrong type, a
license that is not in the allowlist of docs/decisions/s9-corpus.md, a
dialect that the pinned sqlfluff does not have, a bad sha256, commit, URL,
or path, a duplicate id or sha256, a file that is not in the size range of
its templater, or a smoke flag that is not that of the smoke profile.
"""

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path, PurePosixPath
from typing import Any

from ..paths import REPO_ROOT, SQLFLUFF_ROOT

MANIFEST = REPO_ROOT / "corpus" / "sources.json"
FORMAT = 1

# docs/decisions/s9-corpus.md, "Licenses": permissive licenses that allow
# redistribution, as SPDX ids.
LICENSES = frozenset(
    {
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "PostgreSQL",
        "ISC",
        "CC0-1.0",
    }
)
RAW = "raw"
JINJA = "jinja"
KIB = 1024
MAX_BYTES = 2 * KIB * KIB
# docs/decisions/s9-corpus.md, "Size": the range of each templater.
MIN_BYTES = {RAW: 16 * KIB, JINJA: 8 * KIB}
# docs/decisions/s9-corpus.md, "Profiles": the smoke files.
SMOKE_MAX_BYTES = 32 * KIB

TOP_KEYS = frozenset({"format", "sources", "files"})
SOURCE_KEYS = frozenset(
    {"repository", "commit", "license", "copyright", "license_files", "globs"}
)
SOURCE_OPTIONAL = frozenset({"note"})
BLOB_KEYS = frozenset({"path", "bytes", "sha256"})
FILE_KEYS = frozenset(
    {
        "id",
        "source",
        "path",
        "dialect",
        "templater",
        "bytes",
        "lines",
        "sha256",
        "smoke",
        "selection",
    }
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9_.-]*")
_NAME = r"[A-Za-z0-9_.-]+"
_REPOSITORY = re.compile(rf"https://github\.com/({_NAME})/({_NAME})")
_DIALECT_FILE = SQLFLUFF_ROOT / "src" / "sqlfluff" / "core" / "dialects" / "__init__.py"


class ManifestError(ValueError):
    """The manifest is not valid. errors has each problem."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Blob:
    """A file at the pinned commit of a source: its path, size, and sha256."""

    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class Source:
    id: str
    repository: str
    commit: str
    license: str
    copyright: tuple[str, ...]
    license_files: tuple[Blob, ...]
    globs: tuple[str, ...]
    note: str | None = None

    @property
    def owner_repo(self) -> tuple[str, str]:
        m = _REPOSITORY.fullmatch(self.repository)
        assert m, self.repository
        return m.group(1), m.group(2)


@dataclass(frozen=True)
class CorpusFile:
    id: str
    source: str
    path: str
    dialect: str
    templater: str
    bytes: int
    lines: int
    sha256: str
    smoke: bool
    selection: str


@dataclass(frozen=True)
class Manifest:
    sources: dict[str, Source]
    files: tuple[CorpusFile, ...]
    # The sha256 of the manifest file. The CI cache key uses it.
    sha256: str
    text: bytes

    def selected(self, smoke: bool) -> list[CorpusFile]:
        """Return the files of the smoke profile, or all files."""
        return [f for f in self.files if f.smoke or not smoke]


@cache
def pinned_dialects(path: Path = _DIALECT_FILE) -> frozenset[str]:
    """Return the dialect names of the pinned sqlfluff (_dialect_lookup in
    sqlfluff/core/dialects/__init__.py of the submodule). The file is read as
    text, not imported."""
    try:
        tree = ast.parse(path.read_text(encoding="utf8"))
    except (OSError, SyntaxError) as e:
        raise ManifestError([f"cannot read the sqlfluff dialects: {e}"]) from e
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and [getattr(t, "id", None) for t in node.targets] == ["_dialect_lookup"]
            and isinstance(node.value, ast.Dict)
        ):
            names = [getattr(k, "value", None) for k in node.value.keys]
            if names and all(isinstance(n, str) for n in names):
                return frozenset(names)
    raise ManifestError([f"no _dialect_lookup dict in {path}"])


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ManifestError([f"duplicate key {key!r}"])
        out[key] = value
    return out


def load(path: Path = MANIFEST) -> Manifest:
    """Read and validate the manifest at path. Raise ManifestError."""
    try:
        text = Path(path).read_bytes()
    except OSError as e:
        raise ManifestError([f"cannot read {path}: {e}"]) from e
    return parse(text)


def parse(text: bytes) -> Manifest:
    """Read and validate the manifest text. Raise ManifestError."""
    try:
        data = json.loads(text.decode("utf8"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ManifestError([f"not a JSON file: {e}"]) from e
    errors = validate(data)
    if errors:
        raise ManifestError(errors)
    sources = {
        sid: Source(
            id=sid,
            repository=s["repository"],
            commit=s["commit"],
            license=s["license"],
            copyright=tuple(s["copyright"]),
            license_files=tuple(Blob(**b) for b in s["license_files"]),
            globs=tuple(s["globs"]),
            note=s.get("note"),
        )
        for sid, s in data["sources"].items()
    }
    files = tuple(CorpusFile(**f) for f in data["files"])
    return Manifest(sources, files, hashlib.sha256(text).hexdigest(), text)


class _Check:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def want(self, where: str, ok: bool, message: str) -> bool:
        if not ok:
            self.errors.append(f"{where}: {message}")
        return ok

    def keys(
        self, where: str, value: Any, keys: frozenset[str], optional=frozenset()
    ) -> bool:
        if not self.want(where, isinstance(value, dict), "not an object"):
            return False
        unknown = sorted(set(value) - keys - optional)
        missing = sorted(keys - set(value))
        self.want(where, not unknown, f"unknown keys {unknown}")
        self.want(where, not missing, f"missing keys {missing}")
        return not unknown and not missing

    def text(self, where: str, value: Any) -> bool:
        return self.want(
            where, isinstance(value, str) and value.strip() != "", "not a text"
        )

    def count(self, where: str, value: Any, minimum: int) -> bool:
        ok = isinstance(value, int) and not isinstance(value, bool)
        return self.want(where, ok and value >= minimum, f"not an integer >= {minimum}")

    def sha256(self, where: str, value: Any) -> bool:
        ok = isinstance(value, str) and _SHA256.fullmatch(value) is not None
        return self.want(where, ok, "not a sha256 (64 lowercase hex digits)")

    def path(self, where: str, value: Any) -> bool:
        if not self.text(where, value):
            return False
        parts = value.split("/")
        ok = (
            not any(ord(c) < 32 or c in '\\"' for c in value)
            and all(p not in ("", ".", "..") for p in parts)
            and value == value.strip()
        )
        return self.want(where, ok, "not a relative path with no '.' or '..' part")

    def blob(self, where: str, value: Any) -> None:
        if self.keys(where, value, BLOB_KEYS):
            self.path(f"{where}.path", value["path"])
            self.count(f"{where}.bytes", value["bytes"], 1)
            self.sha256(f"{where}.sha256", value["sha256"])


def validate(data: Any) -> list[str]:
    """Return each error of the manifest data (empty if it is valid)."""
    c = _Check()
    if not c.keys("manifest", data, TOP_KEYS):
        return c.errors
    c.want(
        "format",
        type(data["format"]) is int and data["format"] == FORMAT,
        f"not {FORMAT}",
    )
    sources = data["sources"]
    globs: dict[str, list[str]] = {}
    if c.want("sources", isinstance(sources, dict), "not an object"):
        for sid, source in sources.items():
            globs[sid] = _source(c, sid, source)
    files = data["files"]
    if not c.want("files", isinstance(files, list), "not a list"):
        return c.errors
    dialects = pinned_dialects()
    ids: set[str] = set()
    hashes: dict[str, str] = {}
    order: list[tuple[str, str]] = []
    for i, f in enumerate(files):
        if c.keys(f"files[{i}]", f, FILE_KEYS):
            _file(c, i, f, globs, dialects, ids, hashes, order)
    c.want(
        "files",
        order == sorted(set(order)),
        "not sorted by source and path, or a path is there 2 times",
    )
    return c.errors


def _file(
    c: _Check,
    i: int,
    f: dict[str, Any],
    globs: dict[str, list[str]],
    dialects: frozenset[str],
    ids: set[str],
    hashes: dict[str, str],
    order: list[tuple[str, str]],
) -> None:
    """Check one file entry. Add its id, sha256, and (source, path)."""
    fid = f["id"]
    where = f"files[{i}] {fid!r}"
    for key in ("id", "source", "dialect", "templater", "selection"):
        c.text(f"{where}.{key}", f[key])
    if isinstance(fid, str):
        c.want(where, fid not in ids, "duplicate id")
        ids.add(fid)
    source = f["source"]
    if (
        isinstance(source, str)
        and c.want(where, source in globs, f"unknown source {source!r}")
        and c.path(f"{where}.path", f["path"])
    ):
        path = f["path"]
        c.want(where, fid == f"{source}/{path}", "id is not <source>/<path>")
        c.want(
            f"{where}.path",
            any(PurePosixPath(path).full_match(g) for g in globs[source]),
            "matches no glob of its source",
        )
        order.append((source, path))
    if isinstance(f["dialect"], str):
        c.want(
            f"{where}.dialect",
            f["dialect"] in dialects,
            f"{f['dialect']!r} is not a dialect of the pinned sqlfluff",
        )
    templater = f["templater"] if isinstance(f["templater"], str) else None
    c.want(
        f"{where}.templater",
        templater in MIN_BYTES,
        f"not one of {sorted(MIN_BYTES)}",
    )
    smoke_ok = c.want(f"{where}.smoke", isinstance(f["smoke"], bool), "not a bool")
    if c.sha256(f"{where}.sha256", f["sha256"]):
        first = hashes.setdefault(f["sha256"], str(fid))
        c.want(where, first == str(fid), f"same sha256 as {first!r}")
    if not c.count(f"{where}.bytes", f["bytes"], 1):
        return
    size = f["bytes"]
    if templater in MIN_BYTES:
        low = MIN_BYTES[templater]
        c.want(
            f"{where}.bytes",
            low <= size <= MAX_BYTES,
            f"{size} is not in the range {low} to {MAX_BYTES} of {templater}",
        )
    if smoke_ok:
        c.want(
            f"{where}.smoke",
            f["smoke"] == (size <= SMOKE_MAX_BYTES),
            f"must be true if and only if bytes <= {SMOKE_MAX_BYTES}",
        )
    if c.count(f"{where}.lines", f["lines"], 0):
        c.want(f"{where}.lines", f["lines"] <= size, "more lines than bytes")


def _source(c: _Check, sid: Any, source: Any) -> list[str]:
    """Check one source. Return its globs."""
    where = f"sources[{sid!r}]"
    c.want(where, _SOURCE_ID.fullmatch(sid) is not None, "bad source id")
    if not c.keys(where, source, SOURCE_KEYS, SOURCE_OPTIONAL):
        return []
    c.want(
        f"{where}.repository",
        isinstance(source["repository"], str)
        and _REPOSITORY.fullmatch(source["repository"]) is not None,
        "not https://github.com/<owner>/<repo>",
    )
    c.want(
        f"{where}.commit",
        isinstance(source["commit"], str) and _COMMIT.fullmatch(source["commit"]),
        "not a full commit sha (40 lowercase hex digits)",
    )
    c.want(
        f"{where}.license",
        isinstance(source["license"], str) and source["license"] in LICENSES,
        f"{source['license']!r} is not in the allowlist {sorted(LICENSES)}",
    )
    if "note" in source:
        c.text(f"{where}.note", source["note"])
    holders = source["copyright"]
    if c.want(
        f"{where}.copyright",
        isinstance(holders, list) and holders != [],
        "not a list of each copyright holder",
    ):
        for i, h in enumerate(holders):
            c.text(f"{where}.copyright[{i}]", h)
    blobs = source["license_files"]
    if c.want(
        f"{where}.license_files",
        isinstance(blobs, list) and blobs != [],
        "not a list of each license or notice file",
    ):
        for i, b in enumerate(blobs):
            c.blob(f"{where}.license_files[{i}]", b)
        paths = [b.get("path") for b in blobs if isinstance(b, dict)]
        c.want(
            f"{where}.license_files", len(set(paths)) == len(paths), "duplicate path"
        )
    globs = source["globs"]
    if not c.want(
        f"{where}.globs", isinstance(globs, list) and globs != [], "not a list"
    ):
        return []
    for i, g in enumerate(globs):
        c.path(f"{where}.globs[{i}]", g)
    return [g for g in globs if isinstance(g, str) and g]
