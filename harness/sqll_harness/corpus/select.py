"""Make the corpus manifest from the source list and the cache
(docs/decisions/s9-corpus.md, "Selection"; corpus/README.md, "Selection").

download() reads the pinned commit of each source with git (a shallow,
blobless fetch), and writes to the cache the listing of the files that the
source list names (path, size, git blob id) and the bytes of each license
file and each candidate file in the size range. build() uses only the
source list and the cache, never a tool result: a file is in if its path
matches an include glob, its size is in the range of its templater, its
bytes are UTF-8, no earlier file (sorted by source and path) has its
sha256, and the source list does not exclude it. No file is changed. build()
also checks the license text of each source and finds each copyright holder
in its files. Each copyright notice and license text in a selected file must
be that of the record of its source (notice_errors), and a selected file
must have no TPC material (tpc_errors).
"""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from ..paths import REPO_ROOT
from . import fetch as fetch_module
from .manifest import FORMAT, MAX_BYTES, MIN_BYTES, RAW, SMOKE_MAX_BYTES
from .manifest import parse as parse_manifest

SOURCES = REPO_ROOT / "corpus" / "select.json"
# A source id cannot start with "_" (manifest.py), so no source uses it.
LISTINGS_DIR = "_listings"

SOURCE_KEYS = frozenset(
    {"repository", "commit", "license", "copyright", "license_files", "include"}
)
SOURCE_OPTIONAL = frozenset({"note", "exclude"})
INCLUDE_KEYS = frozenset({"glob", "dialect"})
INCLUDE_OPTIONAL = frozenset({"templater"})

# The license text check: the first license file of a source must have each
# phrase of its SPDX id (case and white space are ignored). BSD-2-Clause must
# not have the third clause of BSD-3-Clause.
_REDISTRIBUTION = (
    "redistribution and use in source and binary forms, with or without "
    "modification, are permitted provided that the following conditions are met",
    "redistributions of source code must retain the above copyright notice",
    "redistributions in binary form must reproduce the above copyright notice",
)
BSD3_CLAUSE = "neither the name of"
LICENSE_PHRASES: dict[str, tuple[str, ...]] = {
    "MIT": (
        "permission is hereby granted, free of charge, to any person obtaining "
        "a copy of this software",
        'the software is provided "as is", without warranty of any kind',
    ),
    "Apache-2.0": (
        "apache license",
        "version 2.0, january 2004",
        "terms and conditions for use, reproduction, and distribution",
    ),
    "BSD-2-Clause": _REDISTRIBUTION,
    "BSD-3-Clause": (*_REDISTRIBUTION, BSD3_CLAUSE),
    "PostgreSQL": (
        "permission to use, copy, modify, and distribute this software and its "
        "documentation for any purpose, without fee, and without a written "
        "agreement is hereby granted",
    ),
    "ISC": (
        "permission to use, copy, modify, and/or distribute this software for "
        "any purpose with or without fee is hereby granted",
    ),
    "CC0-1.0": ("cc0 1.0 universal",),
}

# Names or texts of licenses that are not on the allowlist (copyleft and
# others), in a _fold() text.
OTHER_LICENSES = {
    "GPL": re.compile(r"\bgnu\b|general public license|\b[al]?gpl(?:v?\d[\w.]*)?\b"),
    "MPL": re.compile(r"mozilla public license|\bmpl-\d"),
    "EPL": re.compile(r"eclipse public license|\bepl-\d"),
    "CDDL": re.compile(r"common development and distribution license|\bcddl\b"),
    "EUPL": re.compile(r"european union public licen[cs]e|\beupl\b"),
    "CC": re.compile(r"creative commons|\bcc[- ]by\b"),
}
_SPDX = re.compile(r"spdx-license-identifier:\s*([\w.+-]+)")
# A copyright notice (case is ignored): "Copyright" followed by "(c)", "©",
# or white space (or ":", ".", ",") and a word that is not one of
# _NOT_HOLDER; "(c) 2021"; or "©". Not "the above copyright notice",
# "COPYRIGHT HOLDERS", "copyright ownership", 'name="Copyright"', or the
# psql command "\copyright". A notice must be on one line.
_NOT_HOLDER = (
    r"(?:notices?|holders?|owners?|ownership|laws?|statement|and|or|of|to|is|in)\b"
)
_NOTICE = re.compile(
    r"(?<![\\\w])(?i:copyright(?:\s*(?:\(c\)|©)|[:.,]?\s+(?!"
    + _NOT_HOLDER
    + r")\S)|\(c\)\s*\d{4}|©)"
)
# The words of a notice that are not a holder name.
_NOTICE_WORDS = re.compile(
    r"copyright|\(c\)|©|all rights reserved|\bportions\b|\bby\b|\band\b|[\W\d_]"
)
# TPC-H and TPC-DS material (docs/decisions/s9-corpus.md, "Licenses"): the
# kit names, and the TPC-DS and TPC-H table names that other schemas do not
# use. Case is ignored.
_TPC = re.compile(
    r"tpc[-_ ]?(?:h|ds)|\b(?:store_sales|store_returns|catalog_sales|"
    r"catalog_returns|catalog_page|web_sales|web_returns|date_dim|time_dim|"
    r"customer_demographics|household_demographics|lineitem|partsupp)\b",
    re.IGNORECASE,
)
_SPACE = re.compile(r"\s+")


class SelectError(RuntimeError):
    """The selection cannot complete. Each problem is in errors."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Include:
    glob: str
    dialect: str
    templater: str = RAW


@dataclass(frozen=True)
class SourceSpec:
    id: str
    repository: str
    commit: str
    license: str
    copyright: tuple[str, ...]
    license_files: tuple[str, ...]
    include: tuple[Include, ...]
    note: str | None = None
    # (path, reason): the files that the selection leaves out.
    exclude: tuple[tuple[str, str], ...] = ()

    @property
    def globs(self) -> list[str]:
        return [i.glob for i in self.include]


def _keys(where: str, value: Any, keys: frozenset, optional=frozenset()) -> list:
    if not isinstance(value, dict):
        return [f"{where}: not an object"]
    errors = []
    unknown = sorted(set(value) - keys - optional)
    missing = sorted(keys - set(value))
    if unknown:
        errors.append(f"{where}: unknown keys {unknown}")
    if missing:
        errors.append(f"{where}: missing keys {missing}")
    return errors


def _texts(value: Any) -> bool:
    return (
        isinstance(value, list)
        and value != []
        and all(isinstance(v, str) and v.strip() for v in value)
    )


def load_sources(path: Path = SOURCES) -> list[SourceSpec]:
    """Read the source list. Raise SelectError. The values that the manifest
    also has are checked when build() validates the manifest."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SelectError([f"cannot read {path}: {e}"]) from e
    errors = _keys("source list", data, frozenset({"format", "sources"}))
    if errors:
        raise SelectError(errors)
    if data["format"] != FORMAT or not isinstance(data["sources"], dict):
        raise SelectError([f"source list: format is not {FORMAT}, or no sources"])
    specs = []
    for sid, s in data["sources"].items():
        where = f"sources[{sid!r}]"
        problems = _keys(where, s, SOURCE_KEYS, SOURCE_OPTIONAL)
        if problems:
            errors += problems
            continue
        for key in ("copyright", "license_files"):
            if not _texts(s[key]):
                errors.append(f"{where}.{key}: not a list of texts")
        includes = []
        if not isinstance(s["include"], list) or not s["include"]:
            errors.append(f"{where}.include: not a list")
        else:
            for i, inc in enumerate(s["include"]):
                p = _keys(f"{where}.include[{i}]", inc, INCLUDE_KEYS, INCLUDE_OPTIONAL)
                if p:
                    errors += p
                    continue
                includes.append(Include(**inc))
            globs = [i.glob for i in includes]
            if len(set(globs)) != len(globs):
                errors.append(f"{where}.include: duplicate glob")
            bad = [i.templater for i in includes if i.templater not in MIN_BYTES]
            if bad:
                errors.append(f"{where}.include: unknown templater {bad}")
        exclude = s.get("exclude", {})
        if "exclude" in s and (
            not isinstance(exclude, dict)
            or not exclude
            or not _texts([*exclude, *exclude.values()])
        ):
            errors.append(f"{where}.exclude: not an object of paths and reasons")
            exclude = {}
        if s["license"] not in LICENSE_PHRASES:
            errors.append(
                f"{where}.license: {s['license']!r} has no license text check"
            )
        specs.append(
            SourceSpec(
                id=sid,
                repository=s["repository"],
                commit=s["commit"],
                license=s["license"],
                copyright=tuple(s["copyright"]),
                license_files=tuple(s["license_files"]),
                include=tuple(includes),
                note=s.get("note"),
                exclude=tuple(sorted(exclude.items())),
            )
        )
    if errors:
        raise SelectError(errors)
    return sorted(specs, key=lambda s: s.id)


def listing_path(cache: Path, spec: SourceSpec) -> Path:
    return cache / LISTINGS_DIR / spec.id / f"{spec.commit}.json"


def file_path(cache: Path, spec: SourceSpec, path: str) -> Path:
    dest = cache / spec.id / spec.commit / path
    if not dest.resolve().is_relative_to(cache.resolve()):
        raise SelectError([f"{dest} is not in the cache {cache}"])
    return dest


def git_blob_id(data: bytes) -> str:
    """Return the git object id (sha1) of a blob with these bytes."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def matches(path: str, glob: str) -> bool:
    return PurePosixPath(path).full_match(glob)


def _wanted(spec: SourceSpec, path: str) -> bool:
    return path in spec.license_files or any(matches(path, g) for g in spec.globs)


def _in_range(size: int, templater: str) -> bool:
    return MIN_BYTES[templater] <= size <= MAX_BYTES


def _git(args: list[str], cwd: Path, data: bytes | None = None) -> bytes:
    cmd = ["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", *args]
    try:
        out = subprocess.run(cmd, cwd=cwd, input=data, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf8", "replace").strip()
        raise SelectError([f"git {' '.join(args[:2])} failed: {err}"]) from e
    return out.stdout


def _read_blobs(work: Path, oids: list[str]) -> dict[str, bytes]:
    """Return the bytes of each blob, with git cat-file --batch."""
    out = _git(["cat-file", "--batch"], work, "".join(f"{o}\n" for o in oids).encode())
    blobs: dict[str, bytes] = {}
    pos = 0
    for oid in oids:
        end = out.index(b"\n", pos)
        header = out[pos:end].decode().split()
        if len(header) != 3 or header[0] != oid or header[1] != "blob":
            raise SelectError([f"git cat-file: unexpected header {header}"])
        size = int(header[2])
        blobs[oid] = out[end + 1 : end + 1 + size]
        pos = end + 2 + size
    return blobs


def download(spec: SourceSpec, cache: Path, url: str | None = None) -> dict:
    """Read the pinned commit of spec with git (from url, default the
    repository). Write the listing and the license and candidate files to the
    cache. Return the listing."""
    url = url or spec.repository + ".git"
    with tempfile.TemporaryDirectory(prefix="sqll-select-") as tmp:
        work = Path(tmp)
        _git(["init", "-q"], work)
        fetch = ["fetch", "-q", "--no-tags", "--depth", "1", "--filter=blob:none"]
        _git([*fetch, url, spec.commit], work)
        tree = _git(["ls-tree", "-r", "-z", spec.commit], work)
        entries: dict[str, str] = {}
        errors: list[str] = []
        for item in tree.split(b"\0"):
            if not item:
                continue
            try:
                meta, path = item.decode("utf8").split("\t", 1)
            except UnicodeDecodeError:
                errors.append(f"{spec.id}: a path is not UTF-8: {item!r}")
                continue
            mode, kind, oid = meta.split()
            if kind == "blob" and mode in ("100644", "100755") and _wanted(spec, path):
                entries[path] = oid
        missing = [p for p in spec.license_files if p not in entries]
        if missing:
            errors.append(f"{spec.id}: no license file {missing} at the commit")
        if errors:
            raise SelectError(errors)
        oids = sorted(set(entries.values()))
        _git(
            [
                "-c",
                "fetch.negotiationAlgorithm=noop",
                "fetch",
                "-q",
                "--no-tags",
                "--no-write-fetch-head",
                "--recurse-submodules=no",
                "--filter=blob:none",
                "--stdin",
                url,
            ],
            work,
            "".join(f"{o}\n" for o in oids).encode(),
        )
        blobs = _read_blobs(work, oids)
    files = {}
    for path, oid in sorted(entries.items()):
        data = blobs[oid]
        files[path] = {"bytes": len(data), "git_blob": oid}
        include = _include(spec, path)
        if path in spec.license_files or (
            include and _in_range(len(data), include.templater)
        ):
            fetch_module.write_file(file_path(cache, spec, path), data)
    listing = {
        "repository": spec.repository,
        "commit": spec.commit,
        "globs": spec.globs,
        "license_files": list(spec.license_files),
        "files": files,
    }
    dest = listing_path(cache, spec)
    text = json.dumps(listing, indent=2, ensure_ascii=False) + "\n"
    fetch_module.write_file(dest, text.encode("utf8"))
    return listing


def _include(spec: SourceSpec, path: str) -> Include | None:
    hits = [i for i in spec.include if matches(path, i.glob)]
    if len(hits) > 1:
        globs = [i.glob for i in hits]
        raise SelectError([f"{spec.id}/{path}: matches more than one glob {globs}"])
    return hits[0] if hits else None


def _listing(cache: Path, spec: SourceSpec) -> dict:
    path = listing_path(cache, spec)
    try:
        listing = json.loads(path.read_text(encoding="utf8"))
    except (OSError, ValueError) as e:
        raise SelectError(
            [f"{spec.id}: no listing in the cache ({e}). Run select --download."]
        ) from e
    same = (
        listing.get("repository") == spec.repository
        and listing.get("commit") == spec.commit
        and listing.get("globs") == spec.globs
        and listing.get("license_files") == list(spec.license_files)
    )
    if not same:
        raise SelectError(
            [
                f"{spec.id}: the listing in the cache is for other globs or another "
                "commit. Run select --download."
            ]
        )
    return listing


def _cached(cache: Path, spec: SourceSpec, path: str, entry: dict) -> bytes:
    """Return the cached bytes of path. They must be the blob of the commit."""
    dest = file_path(cache, spec, path)
    try:
        data = dest.read_bytes()
    except OSError as e:
        raise SelectError(
            [f"{spec.id}/{path}: not in the cache. Run select --download."]
        ) from e
    if git_blob_id(data) != entry["git_blob"]:
        raise SelectError(
            [f"{spec.id}/{path}: the cached bytes are not the blob of the commit"]
        )
    return data


def _fold(text: str) -> str:
    return _SPACE.sub(" ", text).casefold()


def license_errors(spdx: str, text: str) -> list[str]:
    """Return why text is not a license text of spdx (empty if it is).
    load_sources() refuses an spdx with no entry in LICENSE_PHRASES."""
    folded = _fold(text)
    errors = [f"no phrase {p!r}" for p in LICENSE_PHRASES[spdx] if p not in folded]
    if spdx == "BSD-2-Clause" and BSD3_CLAUSE in folded:
        errors.append("the text has the third clause of BSD-3-Clause")
    return errors


def licenses_in(folded: str) -> set[str]:
    """Return the licenses whose text, name, or SPDX id is in folded (a
    _fold() text). An allowlist license is found by its text or SPDX id."""
    found = {
        spdx
        for spdx, phrases in LICENSE_PHRASES.items()
        if all(p in folded for p in phrases)
    }
    if "BSD-3-Clause" in found:
        found.discard("BSD-2-Clause")
    found |= {
        name for name, pattern in OTHER_LICENSES.items() if pattern.search(folded)
    }
    allow = {spdx.casefold(): spdx for spdx in LICENSE_PHRASES}
    for spdx in _SPDX.findall(folded):
        found.add(allow.get(spdx, f"SPDX {spdx}"))
    return found


def _residue(notice: str, holders: list[str]) -> str:
    """Return the words of notice (a _fold() text) that are not a holder."""
    for holder in sorted(holders, key=len, reverse=True):
        notice = notice.replace(holder, " ")
    return _SPACE.sub(" ", _NOTICE_WORDS.sub(" ", notice)).strip()


def notice_errors(spec: SourceSpec, path: str, text: str, folded: str) -> list[str]:
    """Return each copyright notice of text that names no copyright holder of
    spec or also names another holder, and each license text in it that is
    not the license of spec. The notice forms: see _NOTICE."""
    holders = [_fold(h) for h in spec.copyright]
    errors = []
    for number, line in enumerate(text.splitlines(), 1):
        match = _NOTICE.search(line)
        if not match:
            continue
        notice = _fold(line[match.start() :])
        named = any(h in notice for h in holders)
        other = _residue(notice, holders)
        if named and not other:
            continue
        problem = (
            f"also names {other[:80]!r}, which is not a copyright holder"
            if named
            else "names no copyright holder"
        )
        errors.append(
            f"{spec.id}/{path}:{number}: the copyright notice "
            f"{line.strip()[:120]!r} {problem} of the source"
        )
    other = sorted(licenses_in(folded) - {spec.license})
    if other:
        errors.append(
            f"{spec.id}/{path}: has the license text {other}, not {spec.license}"
        )
    return errors


def tpc_errors(spec: SourceSpec, path: str, text: str) -> list[str]:
    """Return an error if text has TPC-H or TPC-DS material (_TPC)."""
    for number, line in enumerate(text.splitlines(), 1):
        match = _TPC.search(line)
        if match:
            return [
                f"{spec.id}/{path}:{number}: TPC material ({match.group()!r}). "
                "Exclude the file and give the reason"
            ]
    return []


@dataclass
class SourceResult:
    """The counts of the selection of one source."""

    candidates: int = 0
    selected: int = 0
    out_of_range: int = 0
    excluded: list[str] = field(default_factory=list)
    not_utf8: list[str] = field(default_factory=list)
    duplicates: dict[str, str] = field(default_factory=dict)


def _decode(data: bytes) -> str | None:
    try:
        return data.decode("utf8")
    except UnicodeDecodeError:
        return None


def build(specs: list[SourceSpec], cache: Path) -> tuple[bytes, dict]:
    """Return the manifest text and a summary. Use only specs and the cache.
    Raise SelectError."""
    cache = Path(cache).absolute()
    errors: list[str] = []
    sources: dict[str, dict] = {}
    files: list[dict] = []
    summary: dict[str, dict] = {}
    seen: dict[str, str] = {}
    for spec in specs:
        listing = _listing(cache, spec)
        result = SourceResult()
        folded_texts: list[str] = []
        blobs = []
        for path in spec.license_files:
            entry = listing["files"].get(path)
            if entry is None:
                raise SelectError([f"{spec.id}: no license file {path} in the listing"])
            data = _cached(cache, spec, path, entry)
            folded_texts.append(_fold(data.decode("utf8", "replace")))
            sha = hashlib.sha256(data).hexdigest()
            blobs.append({"path": path, "bytes": len(data), "sha256": sha})
        errors += [
            f"{spec.id}: {spec.license_files[0]}: {e}"
            for e in license_errors(spec.license, folded_texts[0])
        ]
        excluded = dict(spec.exclude)
        for path, entry in sorted(listing["files"].items()):
            include = _include(spec, path)
            if include is None:
                continue
            result.candidates += 1
            if path in excluded:
                result.excluded.append(path)
                continue
            if not _in_range(entry["bytes"], include.templater):
                result.out_of_range += 1
                continue
            data = _cached(cache, spec, path, entry)
            text = _decode(data)
            if text is None:
                result.not_utf8.append(path)
                continue
            sha = hashlib.sha256(data).hexdigest()
            fid = f"{spec.id}/{path}"
            if sha in seen:
                result.duplicates[fid] = seen[sha]
                continue
            seen[sha] = fid
            folded = _fold(text)
            folded_texts.append(folded)
            errors += notice_errors(spec, path, text, folded)
            errors += tpc_errors(spec, path, text)
            result.selected += 1
            files.append(_record(spec, path, include, data, sha))
        for holder in spec.copyright:
            if not any(_fold(holder) in t for t in folded_texts):
                errors.append(
                    f"{spec.id}: the copyright holder {holder!r} is in no license "
                    "file and no selected file"
                )
        for path in sorted(set(excluded) - set(result.excluded)):
            errors.append(f"{spec.id}: the excluded path {path} matches no glob")
        if result.selected == 0:
            errors.append(f"{spec.id}: no file is selected")
        sources[spec.id] = _source(spec, blobs)
        summary[spec.id] = {
            "candidates": result.candidates,
            "selected": result.selected,
            "out_of_range": result.out_of_range,
            "excluded": result.excluded,
            "not_utf8": result.not_utf8,
            "duplicates": result.duplicates,
        }
    if errors:
        raise SelectError(errors)
    manifest = {"format": FORMAT, "sources": sources, "files": files}
    text = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf8")
    parsed = parse_manifest(text)
    smoke = parsed.selected(smoke=True)
    totals = {
        "sources": len(sources),
        "files": len(files),
        "bytes": sum(f["bytes"] for f in files),
        "smoke_files": len(smoke),
        "smoke_bytes": sum(f.bytes for f in smoke),
        "manifest_sha256": parsed.sha256,
    }
    return text, {"totals": totals, "sources": summary}


def source_note(spec: SourceSpec) -> str:
    """Return the manifest note of spec: its note and each excluded path with
    the reason."""
    excluded = [f"Excluded: {path}: {reason}" for path, reason in spec.exclude]
    return " ".join([*([spec.note] if spec.note else []), *excluded])


def _source(spec: SourceSpec, blobs: list[dict]) -> dict:
    out = {
        "repository": spec.repository,
        "commit": spec.commit,
        "license": spec.license,
        "copyright": list(spec.copyright),
        "license_files": blobs,
        "globs": spec.globs,
    }
    if note := source_note(spec):
        out["note"] = note
    return out


def _record(
    spec: SourceSpec, path: str, include: Include, data: bytes, sha: str
) -> dict:
    size = len(data)
    low = MIN_BYTES[include.templater]
    return {
        "id": f"{spec.id}/{path}",
        "source": spec.id,
        "path": path,
        "dialect": include.dialect,
        "templater": include.templater,
        "bytes": size,
        "lines": data.count(b"\n"),
        "sha256": sha,
        "smoke": size <= SMOKE_MAX_BYTES,
        "selection": (
            f"glob {include.glob} (dialect {include.dialect}); "
            f"{low} <= bytes <= {MAX_BYTES}; UTF-8; first file with its sha256"
        ),
    }


def download_all(specs: list[SourceSpec], cache: Path) -> None:
    cache = Path(cache).absolute()
    fetch_module.check_folder(cache)
    for spec in specs:
        print(f"git: {spec.repository} {spec.commit}", file=sys.stderr)
        download(spec, cache)
