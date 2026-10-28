"""Download the corpus files at their pinned commits (corpus/README.md).

fetch() puts each selected file, and each license or notice file of its
source, at <cache>/<source>/<commit>/<path>, and a copy of the manifest at
<cache>/_manifests/<manifest sha256>.json. A file goes to its path only
after its size and sha256 are correct, so each file at such a path is a
correct copy. A file in the cache is used again only if its sha256 is
correct; else it is deleted and downloaded again. A wrong size or sha256,
or a download that fails after the retries, stops the fetch (FetchError).
"""

import hashlib
import http.client
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..bench.adapter import config_files_above
from ..paths import OUT_DIR
from .manifest import Blob, CorpusFile, Manifest, Source

CACHE_ENV = "SQLL_CORPUS_CACHE"
# A source id cannot start with "_" (manifest.py), so no source uses it.
MANIFESTS_DIR = "_manifests"
DEFAULT_CACHE = OUT_DIR / "corpus" / "cache"
RAW_URL = "https://raw.githubusercontent.com/{owner}/{repo}/{commit}/{path}"
# The waits in seconds before each new attempt: 4 attempts in all.
RETRY_DELAYS = (2, 4, 8)
TIMEOUT = 60
# HTTP codes that can change on a new attempt. Other HTTP errors (for
# example 404: the path is not at the commit) stop the fetch at once.
RETRY_HTTP = frozenset({408, 425, 429, 500, 502, 503, 504})

# download(url, limit) returns the body. It reads at most limit + 1 bytes,
# so a body that is too large is found without a read of all of it.
Download = Callable[[str, int], bytes]


class FetchError(RuntimeError):
    """The fetch failed. No file at a cache path has wrong data."""


def cache_dir(value: str | Path | None = None) -> Path:
    """Return the cache folder: value, else $SQLL_CORPUS_CACHE, else
    out/corpus/cache."""
    value = value or os.environ.get(CACHE_ENV)
    return Path(value).absolute() if value else DEFAULT_CACHE


def check_folder(folder: Path) -> None:
    """Raise FetchError if folder or a parent has a config file that
    sqlfluff or sqruff can read: it would change the results of a run."""
    found = config_files_above(Path(folder).absolute())
    if found:
        lines = [f"  {path}: {reason}" for path, reason in found]
        raise FetchError(
            f"{folder} or a parent folder has a sqlfluff or sqruff config "
            "file. Use another folder:\n" + "\n".join(lines)
        )


def raw_url(source: Source, path: str) -> str:
    owner, repo = source.owner_repo
    return RAW_URL.format(
        owner=owner, repo=repo, commit=source.commit, path=urllib.parse.quote(path)
    )


def http_download(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "sqll-harness"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read(limit + 1)


def _transient(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code in RETRY_HTTP
    return isinstance(
        error, urllib.error.URLError | OSError | http.client.HTTPException
    )


def _get(
    url: str, limit: int, download: Download, sleep: Callable[[float], None]
) -> bytes:
    for delay in (*RETRY_DELAYS, None):
        try:
            return download(url, limit)
        except Exception as e:
            if delay is None or not _transient(e):
                raise FetchError(f"cannot download {url}: {e!r}") from e
            print(f"retry in {delay} s: {url}: {e!r}", file=sys.stderr)
            sleep(delay)
    raise AssertionError("unreachable")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _content_error(data: bytes, entry: CorpusFile) -> str | None:
    """Return why the correct bytes of entry do not agree with the rest of
    its manifest record, or None."""
    try:
        data.decode("utf8")
    except UnicodeDecodeError as e:
        return f"not UTF-8: {e}"
    if data.count(b"\n") != entry.lines:
        return f"{data.count(b'\n')} lines, the manifest has {entry.lines}"
    return None


def _write(dest: Path, data: bytes) -> None:
    """Write data to dest. A reader never sees a part of the data at dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


@dataclass
class Fetched:
    """The result of fetch(): the local path of each file and the counts."""

    cache: Path
    manifest_copy: Path
    files: dict[str, Path] = field(default_factory=dict)
    license_files: dict[str, Path] = field(default_factory=dict)
    downloaded: int = 0
    cached: int = 0

    def summary(self, manifest: Manifest, smoke: bool) -> dict:
        return {
            "cache": str(self.cache),
            "manifest_sha256": manifest.sha256,
            "manifest_copy": str(self.manifest_copy),
            "smoke": smoke,
            "files": len(self.files),
            "license_files": len(self.license_files),
            "downloaded": self.downloaded,
            "cached": self.cached,
        }


class _Fetcher:
    def __init__(
        self, cache: Path, download: Download, sleep: Callable[[float], None]
    ) -> None:
        self.cache = cache
        self.download = download
        self.sleep = sleep
        self.downloaded = 0
        self.cached = 0

    def path(self, source: Source, path: str) -> Path:
        dest = self.cache / source.id / source.commit / path
        if not dest.resolve().is_relative_to(self.cache.resolve()):
            raise FetchError(f"{dest} is not in the cache {self.cache}")
        return dest

    def get(self, source: Source, blob: Blob, entry: CorpusFile | None = None) -> Path:
        """Return the local path of blob, with the correct data at it."""
        dest = self.path(source, blob.path)
        if dest.is_file() and not dest.is_symlink():
            data = dest.read_bytes()
            if len(data) == blob.bytes and _sha256(data) == blob.sha256:
                self._content(data, entry, dest)
                self.cached += 1
                return dest
        if os.path.lexists(dest):
            dest.unlink()
        url = raw_url(source, blob.path)
        print(f"download {url}", file=sys.stderr)
        data = _get(url, blob.bytes, self.download, self.sleep)
        if len(data) != blob.bytes:
            size = f"{blob.bytes + 1} or more" if len(data) > blob.bytes else len(data)
            raise FetchError(f"{url}: {size} bytes, the manifest has {blob.bytes}")
        if _sha256(data) != blob.sha256:
            raise FetchError(
                f"{url}: sha256 {_sha256(data)}, the manifest has {blob.sha256}"
            )
        self._content(data, entry, dest)
        _write(dest, data)
        self.downloaded += 1
        return dest

    def _content(self, data: bytes, entry: CorpusFile | None, dest: Path) -> None:
        error = entry and _content_error(data, entry)
        if error:
            raise FetchError(f"{entry.id}: {error}")


def fetch(
    manifest: Manifest,
    cache: Path,
    smoke: bool = False,
    download: Download | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Fetched:
    """Fetch the files of the profile (smoke or all) and the license and
    notice files of their sources into cache. Raise FetchError."""
    cache = Path(cache).absolute()
    check_folder(cache)
    f = _Fetcher(cache, download or http_download, sleep)
    selected = manifest.selected(smoke)
    copy = cache / MANIFESTS_DIR / f"{manifest.sha256}.json"
    result = Fetched(cache, copy)
    for sid in dict.fromkeys(e.source for e in selected):
        source = manifest.sources[sid]
        for blob in source.license_files:
            result.license_files[f"{sid}/{blob.path}"] = f.get(source, blob)
    for e in selected:
        blob = Blob(e.path, e.bytes, e.sha256)
        result.files[e.id] = f.get(manifest.sources[e.source], blob, e)
    if not (copy.is_file() and copy.read_bytes() == manifest.text):
        _write(copy, manifest.text)
    result.downloaded, result.cached = f.downloaded, f.cached
    return result
