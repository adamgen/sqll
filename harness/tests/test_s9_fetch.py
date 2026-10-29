"""The S9 corpus fetcher: pinned download, sha256 checks, cache, retries.

A local fake source gives the files. No test uses the network.
"""

import hashlib
import json
import urllib.error
from pathlib import Path

import pytest

from sqll_harness.corpus import __main__ as corpus_main
from sqll_harness.corpus import fetch as f
from sqll_harness.corpus import manifest as m

COMMIT = "0123456789abcdef0123456789abcdef01234567"
RAW = f"https://raw.githubusercontent.com/example/demo-sql/{COMMIT}/"
KIB = 1024


def sql(size: int, fill: str = "x") -> bytes:
    """Return SQL text of exactly size bytes (with some newlines)."""
    line = ("SELECT " + fill * 70 + ";\n").encode()
    data = line * (size // len(line) + 1)
    return data[: size - 1] + b"\n"


class FakeSource:
    """A download function that reads files from a local folder. It records
    each URL; fail gives errors to raise first for a path."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[str] = []
        self.fail: dict[str, list[Exception]] = {}

    def put(self, path: str, data: bytes) -> None:
        dest = self.root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def __call__(self, url: str, limit: int) -> bytes:
        self.calls.append(url)
        assert url.startswith(RAW), url
        path = url[len(RAW) :]
        errors = self.fail.get(path)
        if errors:
            raise errors.pop(0)
        file = self.root / path
        if not file.is_file():
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return file.read_bytes()[: limit + 1]


FILES = {
    "LICENSE": b"MIT License\n\nCopyright (c) Example Holder\n",
    "NOTICE": b"Example notice.\n",
    "models/small.sql": sql(9 * KIB, "m"),
    "sql/a/big.sql": sql(40 * KIB, "b"),
    "sql/z.sql": sql(17 * KIB, "z"),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def entry(path: str, data: bytes, templater: str = "raw") -> dict:
    return {
        "id": f"demo/{path}",
        "source": "demo",
        "path": path,
        "dialect": "postgres",
        "templater": templater,
        "bytes": len(data),
        "lines": data.count(b"\n"),
        "sha256": sha(data),
        "smoke": len(data) <= 32 * KIB,
        "selection": "test",
    }


def manifest_data(files: dict[str, bytes] = FILES) -> dict:
    return {
        "format": 1,
        "sources": {
            "demo": {
                "repository": "https://github.com/example/demo-sql",
                "commit": COMMIT,
                "license": "MIT",
                "copyright": ["Example Holder"],
                "license_files": [
                    {"path": p, "bytes": len(files[p]), "sha256": sha(files[p])}
                    for p in ("LICENSE", "NOTICE")
                ],
                "globs": ["models/*.sql", "sql/**/*.sql"],
            }
        },
        "files": [
            entry("models/small.sql", files["models/small.sql"], "jinja"),
            entry("sql/a/big.sql", files["sql/a/big.sql"]),
            entry("sql/z.sql", files["sql/z.sql"]),
        ],
    }


def make_manifest(data: dict | None = None) -> m.Manifest:
    return m.parse(json.dumps(data or manifest_data()).encode())


@pytest.fixture
def source(tmp_path) -> FakeSource:
    src = FakeSource(tmp_path / "upstream")
    for path, data in FILES.items():
        src.put(path, data)
    return src


@pytest.fixture
def cache(tmp_path) -> Path:
    return tmp_path / "cache"


def run(man, cache, source, smoke=False, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    return f.fetch(man, cache, smoke=smoke, download=source, sleep=sleeps.append)


def files_in(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())


def test_fetch_downloads_each_file_by_commit(cache, source):
    man = make_manifest()
    result = run(man, cache, source)
    assert sorted(source.calls) == sorted(RAW + p for p in FILES)
    assert result.downloaded == 5 and result.cached == 0
    for fid, path in result.files.items():
        rel = fid.split("/", 1)[1]
        assert path == cache / "demo" / COMMIT / rel
        assert path.read_bytes() == FILES[rel]
    assert sorted(result.license_files) == ["demo/LICENSE", "demo/NOTICE"]
    copy = cache / "_manifests" / f"{man.sha256}.json"
    assert result.manifest_copy == copy and copy.read_bytes() == man.text
    assert files_in(cache) == sorted(
        [f"demo/{COMMIT}/{p}" for p in FILES] + [f"_manifests/{man.sha256}.json"]
    )


def test_cached_file_with_right_sha256_is_used_with_no_download(cache, source):
    man = make_manifest()
    run(man, cache, source)
    source.calls.clear()
    result = run(man, cache, source)
    assert source.calls == []
    assert result.downloaded == 0 and result.cached == 5


def test_cached_file_with_wrong_data_is_downloaded_again(cache, source):
    man = make_manifest()
    run(man, cache, source)
    stale = cache / "demo" / COMMIT / "sql" / "z.sql"
    stale.write_bytes(b"changed")
    source.calls.clear()
    result = run(man, cache, source)
    assert source.calls == [RAW + "sql/z.sql"]
    assert result.downloaded == 1 and stale.read_bytes() == FILES["sql/z.sql"]


def test_wrong_sha256_fails_and_keeps_no_file(cache, source):
    man = make_manifest()
    other = bytearray(FILES["sql/a/big.sql"])
    other[100:101] = b"y"
    source.put("sql/a/big.sql", bytes(other))
    with pytest.raises(f.FetchError, match="sha256"):
        run(man, cache, source)
    dest = cache / "demo" / COMMIT / "sql" / "a" / "big.sql"
    assert not dest.exists()
    assert not [p for p in files_in(cache) if p.endswith(".part")]
    assert "sql/a/big.sql" not in " ".join(files_in(cache))


def test_wrong_sha256_removes_a_stale_cached_file(cache, source):
    man = make_manifest()
    dest = cache / "demo" / COMMIT / "sql" / "a" / "big.sql"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"old data")
    source.put("sql/a/big.sql", b"x" * len(FILES["sql/a/big.sql"]))
    with pytest.raises(f.FetchError, match="sha256"):
        run(man, cache, source)
    assert not dest.exists()


def test_wrong_license_file_fails(cache, source):
    source.put("NOTICE", b"Another notice.\n")
    with pytest.raises(f.FetchError, match="sha256"):
        run(make_manifest(), cache, source)
    assert not (cache / "demo" / COMMIT / "NOTICE").exists()


@pytest.mark.parametrize("extra", [b"", b"more"])
def test_wrong_size_fails(cache, source, extra):
    data = FILES["sql/z.sql"]
    source.put("sql/z.sql", data[:-10] if not extra else data + extra)
    with pytest.raises(f.FetchError, match="bytes, the manifest has"):
        run(make_manifest(), cache, source)
    assert not (cache / "demo" / COMMIT / "sql" / "z.sql").exists()


def test_missing_file_fails_with_no_retry(cache, source):
    (source.root / "sql" / "z.sql").unlink()
    sleeps = []
    with pytest.raises(f.FetchError, match="404"):
        run(make_manifest(), cache, source, sleeps=sleeps)
    assert sleeps == []
    assert source.calls.count(RAW + "sql/z.sql") == 1


def test_transient_errors_are_retried(cache, source):
    source.fail["sql/z.sql"] = [
        urllib.error.URLError("connection reset"),
        urllib.error.HTTPError(RAW, 503, "Unavailable", {}, None),
        TimeoutError("timed out"),
    ]
    sleeps = []
    result = run(make_manifest(), cache, source, sleeps=sleeps)
    assert sleeps == [2, 4, 8]
    assert source.calls.count(RAW + "sql/z.sql") == 4
    assert result.files["demo/sql/z.sql"].read_bytes() == FILES["sql/z.sql"]


def test_retries_stop_after_4_attempts(cache, source):
    source.fail["sql/z.sql"] = [urllib.error.URLError("down") for _ in range(4)]
    sleeps = []
    with pytest.raises(f.FetchError, match="down"):
        run(make_manifest(), cache, source, sleeps=sleeps)
    assert sleeps == [2, 4, 8]
    assert source.calls.count(RAW + "sql/z.sql") == 4
    assert not (cache / "demo" / COMMIT / "sql" / "z.sql").exists()


def test_smoke_fetches_only_smoke_files_and_their_license_files(cache, source):
    result = run(make_manifest(), cache, source, smoke=True)
    assert sorted(result.files) == ["demo/models/small.sql", "demo/sql/z.sql"]
    assert sorted(result.license_files) == ["demo/LICENSE", "demo/NOTICE"]
    assert RAW + "sql/a/big.sql" not in source.calls


def test_file_that_is_not_utf8_fails(cache, source):
    files = dict(FILES)
    data = bytearray(files["sql/z.sql"])
    data[50:51] = b"\xff"
    files["sql/z.sql"] = bytes(data)
    source.put("sql/z.sql", files["sql/z.sql"])
    with pytest.raises(f.FetchError, match="not UTF-8"):
        run(make_manifest(manifest_data(files)), cache, source)
    assert not (cache / "demo" / COMMIT / "sql" / "z.sql").exists()


def test_wrong_line_count_fails(cache, source):
    data = manifest_data()
    data["files"][2]["lines"] += 1
    with pytest.raises(f.FetchError, match="lines, the manifest has"):
        run(make_manifest(data), cache, source)


@pytest.mark.parametrize(
    "name, text",
    [
        (".sqlfluff", "[sqlfluff]\n"),
        (".sqruff", "[sqruff]\n"),
        ("setup.cfg", "[sqlfluff]\ndialect = ansi\n"),
        ("pyproject.toml", "[tool.sqlfluff.core]\ndialect = 'ansi'\n"),
    ],
)
def test_cache_with_a_config_file_above_is_refused(tmp_path, source, name, text):
    (tmp_path / name).write_text(text)
    with pytest.raises(f.FetchError, match="config"):
        run(make_manifest(), tmp_path / "cache", source)
    assert source.calls == []
    assert not (tmp_path / "cache").exists()


def test_cache_with_a_config_file_in_it_is_refused(tmp_path, source):
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / ".sqlfluff").write_text("[sqlfluff]\n")
    with pytest.raises(f.FetchError, match="config"):
        run(make_manifest(), tmp_path / "cache", source)
    assert source.calls == []


def test_cache_dir_order(monkeypatch, tmp_path):
    monkeypatch.delenv(f.CACHE_ENV, raising=False)
    assert f.cache_dir() == f.DEFAULT_CACHE
    assert f.DEFAULT_CACHE.parent.parent.name == "out"
    monkeypatch.setenv(f.CACHE_ENV, str(tmp_path / "env"))
    assert f.cache_dir() == tmp_path / "env"
    assert f.cache_dir(tmp_path / "arg") == tmp_path / "arg"


def test_raw_url_quotes_the_path():
    man = make_manifest()
    url = f.raw_url(man.sources["demo"], "a b/c#.sql")
    assert url == RAW + "a%20b/c%23.sql"


def test_http_download_reads_at_most_limit_plus_1(tmp_path):
    path = tmp_path / "x.sql"
    path.write_bytes(b"0123456789")
    assert f.http_download(path.as_uri(), 4) == b"01234"
    assert f.http_download(path.as_uri(), 20) == b"0123456789"


def write_manifest(tmp_path, data: dict) -> Path:
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(data))
    return path


def test_cli_fetch(tmp_path, source, monkeypatch, capsys):
    monkeypatch.setattr(f, "http_download", source)
    path = write_manifest(tmp_path, manifest_data())
    cache = tmp_path / "cache"
    argv = ["fetch", "--smoke", "--manifest", str(path), "--cache", str(cache)]
    assert corpus_main.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["files"] == 2 and out["license_files"] == 2
    assert out["downloaded"] == 4 and out["cached"] == 0
    assert out["cache"] == str(cache) and out["smoke"] is True
    assert corpus_main.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["downloaded"] == 0 and out["cached"] == 4


def test_cli_fetch_fails_on_a_wrong_sha256(tmp_path, source, monkeypatch, capsys):
    monkeypatch.setattr(f, "http_download", source)
    source.put("sql/z.sql", b"y" * len(FILES["sql/z.sql"]))
    path = write_manifest(tmp_path, manifest_data())
    argv = ["fetch", "--manifest", str(path), "--cache", str(tmp_path / "c")]
    assert corpus_main.main(argv) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "sha256" in captured.err


def test_cli_validate(tmp_path, capsys):
    path = write_manifest(tmp_path, manifest_data())
    assert corpus_main.main(["validate", "--manifest", str(path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["files"] == 3 and out["smoke_files"] == 2 and out["sources"] == 1
    bad = manifest_data()
    bad["sources"]["demo"]["license"] = "GPL-3.0-only"
    path = write_manifest(tmp_path, bad)
    assert corpus_main.main(["validate", "--manifest", str(path)]) == 2
    assert "allowlist" in capsys.readouterr().err


def test_cli_validate_repository_manifest(capsys):
    assert corpus_main.main(["validate"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["manifest_sha256"] == m.load().sha256


def test_notices_has_the_manifest_and_each_license_file(tmp_path, cache, source):
    man = make_manifest()
    out = tmp_path / "notices"
    result = f.notices(man, cache, out, download=source, sleep=[].append)
    assert files_in(out) == ["_sources.json", "demo/LICENSE", "demo/NOTICE"]
    assert (out / "_sources.json").read_bytes() == man.text
    assert (out / "demo" / "NOTICE").read_bytes() == FILES["NOTICE"]
    assert result["license_files"] == 2 and result["downloaded"] == 2
    assert sorted(source.calls) == [RAW + "LICENSE", RAW + "NOTICE"]
    source.calls.clear()
    (out / "demo" / "old").write_text("x")
    result = f.notices(man, cache, out, download=source, sleep=[].append)
    assert source.calls == [] and result["cached"] == 2
    assert files_in(out) == ["_sources.json", "demo/LICENSE", "demo/NOTICE"]
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".notices.")]


def test_notices_checks_the_sha256(tmp_path, cache, source):
    source.put("NOTICE", b"Another notice.\n")
    out = tmp_path / "notices"
    with pytest.raises(f.FetchError, match="sha256"):
        f.notices(make_manifest(), cache, out, download=source, sleep=[].append)
    assert not out.exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".notices.")]


@pytest.mark.parametrize("kind", ["file", "other folder"])
def test_notices_does_not_replace_another_folder(tmp_path, cache, source, kind):
    out = tmp_path / "notices"
    if kind == "file":
        out.write_text("x")
    else:
        out.mkdir()
        (out / "keep.txt").write_text("x")
    with pytest.raises(f.FetchError, match="not a notices folder"):
        f.notices(make_manifest(), cache, out, download=source, sleep=[].append)
    assert source.calls == []
    assert out.exists()


def test_cli_notices(tmp_path, source, monkeypatch, capsys):
    monkeypatch.setattr(f, "http_download", source)
    path = write_manifest(tmp_path, manifest_data())
    out = tmp_path / "n"
    argv = ["notices", "--manifest", str(path), "--cache", str(tmp_path / "c")]
    assert corpus_main.main([*argv, "--out", str(out)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["out"] == str(out) and result["license_files"] == 2
    assert files_in(out) == ["_sources.json", "demo/LICENSE", "demo/NOTICE"]
    source.put("LICENSE", b"y" * len(FILES["LICENSE"]))
    (tmp_path / "c" / "demo" / COMMIT / "LICENSE").unlink()
    assert corpus_main.main([*argv, "--out", str(out)]) == 2
    assert "sha256" in capsys.readouterr().err
    assert (out / "demo" / "LICENSE").read_bytes() == FILES["LICENSE"]


def test_cli_notices_default_folder():
    args = corpus_main._parser().parse_args(["notices"])
    assert args.out == f.DEFAULT_NOTICES
    assert f.DEFAULT_NOTICES.parent.name == "out"


def test_notices_manifest_name_is_not_a_source_id():
    assert not m._SOURCE_ID.fullmatch(f.NOTICES_MANIFEST)
