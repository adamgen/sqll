"""The S9 corpus selection (corpus/select.json to corpus/sources.json).

A local git repository is the source. No test uses the network.
"""

import json
import subprocess
from pathlib import Path

import pytest

from sqll_harness.corpus import __main__ as corpus_main
from sqll_harness.corpus import manifest as m
from sqll_harness.corpus import select as s

KIB = 1024
MIT = (
    "MIT License\n\nCopyright (c) 2024 Example Holder\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a\n"
    "copy of this software and associated documentation files.\n\n"
    'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.\n'
)


def sql(size: int, fill: str) -> bytes:
    line = ("SELECT " + fill * 70 + ";\n").encode()
    data = line * (size // len(line) + 1)
    return data[: size - 1] + b"\n"


FILES = {
    "LICENSE": MIT.encode(),
    "sql/a.sql": sql(20 * KIB, "a"),
    "sql/b_copy.sql": sql(20 * KIB, "a"),
    "sql/big.sql": sql(40 * KIB, "b"),
    "sql/latin1.sql": sql(20 * KIB, "c")[:-2] + b"\xe9\n",
    "sql/small.sql": sql(2 * KIB, "d"),
    "sql/sub/deep.sql": sql(20 * KIB, "e"),
    "models/m.sql": sql(9 * KIB, "f"),
    "other/x.sql": sql(20 * KIB, "g"),
}


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "uploadpack.allowFilter", "true")
    git(root, "config", "uploadpack.allowAnySHA1InWant", "true")
    for path, data in FILES.items():
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    git(root, "add", ".")
    git(root, "commit", "-qm", "files")
    return root, git(root, "rev-parse", "HEAD")


def source_list(commit: str, **change) -> dict:
    source = {
        "repository": "https://github.com/example/demo-sql",
        "commit": commit,
        "license": "MIT",
        "copyright": ["Example Holder"],
        "license_files": ["LICENSE"],
        "include": [
            {"glob": "sql/*.sql", "dialect": "postgres"},
            {"glob": "models/*.sql", "dialect": "snowflake", "templater": "jinja"},
        ],
        "note": "A test source.",
    }
    source.update(change)
    return {"format": 1, "sources": {"demo": source}}


def write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "select.json"
    path.write_text(json.dumps(data), encoding="utf8")
    return path


@pytest.fixture
def cache(tmp_path) -> Path:
    return tmp_path / "cache"


def download(tmp_path, repo, cache, **change) -> list[s.SourceSpec]:
    root, commit = repo
    specs = s.load_sources(write(tmp_path, source_list(commit, **change)))
    for spec in specs:
        s.download(spec, cache, url=root.as_uri())
    return specs


def test_select_applies_the_rules(tmp_path, repo, cache):
    specs = download(tmp_path, repo, cache)
    text, summary = s.build(specs, cache)
    man = m.parse(text)
    assert [f.path for f in man.files] == ["models/m.sql", "sql/a.sql", "sql/big.sql"]
    assert summary["sources"]["demo"] == {
        "candidates": 6,
        "selected": 3,
        "out_of_range": 1,
        "not_utf8": ["sql/latin1.sql"],
        "duplicates": {"demo/sql/b_copy.sql": "demo/sql/a.sql"},
    }
    models, a, big = man.files
    assert (models.dialect, models.templater, models.smoke) == (
        "snowflake",
        "jinja",
        True,
    )
    assert (big.dialect, big.templater, big.smoke) == ("postgres", "raw", False)
    assert a.bytes == len(FILES["sql/a.sql"])
    assert a.lines == FILES["sql/a.sql"].count(b"\n")
    assert a.selection == (
        "glob sql/*.sql (dialect postgres); 16384 <= bytes <= 2097152; UTF-8; "
        "first file with its sha256"
    )
    source = man.sources["demo"]
    assert source.globs == ("sql/*.sql", "models/*.sql")
    assert [b.path for b in source.license_files] == ["LICENSE"]
    assert source.license_files[0].bytes == len(FILES["LICENSE"])
    assert summary["totals"]["files"] == 3
    assert summary["totals"]["smoke_files"] == 2


def test_build_uses_only_the_cache(tmp_path, repo, cache, monkeypatch):
    specs = download(tmp_path, repo, cache)
    first, _ = s.build(specs, cache)

    def no_git(*args, **kwargs):
        raise AssertionError("git was called")

    monkeypatch.setattr(s, "_git", no_git)
    again, _ = s.build(specs, cache)
    assert again == first


def test_cache_has_the_listing_and_only_the_needed_files(tmp_path, repo, cache):
    specs = download(tmp_path, repo, cache)
    spec = specs[0]
    listing = json.loads(s.listing_path(cache, spec).read_text())
    assert sorted(listing["files"]) == [
        "LICENSE",
        "models/m.sql",
        "sql/a.sql",
        "sql/b_copy.sql",
        "sql/big.sql",
        "sql/latin1.sql",
        "sql/small.sql",
    ]
    assert listing["files"]["sql/small.sql"]["bytes"] == 2 * KIB
    root = cache / "demo" / spec.commit
    assert not (root / "sql/small.sql").exists()
    assert not (root / "other/x.sql").exists()
    assert (root / "sql/a.sql").read_bytes() == FILES["sql/a.sql"]


def test_changed_cache_file_fails(tmp_path, repo, cache):
    specs = download(tmp_path, repo, cache)
    (cache / "demo" / specs[0].commit / "sql/a.sql").write_bytes(b"x" * 20 * KIB)
    with pytest.raises(s.SelectError, match="not the blob of the commit"):
        s.build(specs, cache)


def test_missing_cache_file_fails(tmp_path, repo, cache):
    specs = download(tmp_path, repo, cache)
    (cache / "demo" / specs[0].commit / "sql/big.sql").unlink()
    with pytest.raises(s.SelectError, match="not in the cache"):
        s.build(specs, cache)


def test_listing_of_other_globs_fails(tmp_path, repo, cache):
    download(tmp_path, repo, cache)
    root, commit = repo
    include = [{"glob": "sql/**/*.sql", "dialect": "postgres"}]
    specs = s.load_sources(write(tmp_path, source_list(commit, include=include)))
    with pytest.raises(s.SelectError, match="--download"):
        s.build(specs, cache)


def test_no_listing_fails(tmp_path, repo, cache):
    _, commit = repo
    specs = s.load_sources(write(tmp_path, source_list(commit)))
    with pytest.raises(s.SelectError, match="no listing"):
        s.build(specs, cache)


def test_path_that_matches_2_globs_fails(tmp_path, repo, cache):
    include = [
        {"glob": "sql/*.sql", "dialect": "postgres"},
        {"glob": "sql/a*.sql", "dialect": "mysql"},
    ]
    with pytest.raises(s.SelectError, match="more than one glob"):
        download(tmp_path, repo, cache, include=include)


def test_missing_license_file_fails(tmp_path, repo, cache):
    with pytest.raises(s.SelectError, match="no license file"):
        download(tmp_path, repo, cache, license_files=["COPYING"])


def test_wrong_license_text_fails(tmp_path, repo, cache):
    specs = download(tmp_path, repo, cache, license="Apache-2.0")
    with pytest.raises(s.SelectError, match="no phrase 'apache license'"):
        s.build(specs, cache)


def test_unknown_copyright_holder_fails(tmp_path, repo, cache):
    specs = download(tmp_path, repo, cache, copyright=["Somebody Else"])
    with pytest.raises(s.SelectError, match="Somebody Else"):
        s.build(specs, cache)


def test_source_with_no_selected_file_fails(tmp_path, repo, cache):
    include = [{"glob": "none/*.sql", "dialect": "postgres"}]
    specs = download(tmp_path, repo, cache, include=include)
    with pytest.raises(s.SelectError, match="no file is selected"):
        s.build(specs, cache)


def test_license_not_in_the_allowlist_fails(tmp_path, repo):
    _, commit = repo
    with pytest.raises(s.SelectError, match="no license text check"):
        s.load_sources(write(tmp_path, source_list(commit, license="GPL-2.0-only")))


@pytest.mark.parametrize(
    "change, message",
    [
        ({"extra": 1}, "unknown keys"),
        ({"include": [{"glob": "a/*.sql"}]}, "missing keys"),
        ({"include": [{"glob": "a/*.sql", "dialect": "x", "templater": "dbt"}]}, "dbt"),
        ({"copyright": []}, "copyright"),
        (
            {
                "include": [
                    {"glob": "a/*.sql", "dialect": "postgres"},
                    {"glob": "a/*.sql", "dialect": "mysql"},
                ]
            },
            "duplicate glob",
        ),
    ],
)
def test_bad_source_list_fails(tmp_path, change, message):
    with pytest.raises(s.SelectError, match=message):
        s.load_sources(write(tmp_path, source_list("0" * 40, **change)))


def test_build_validates_the_manifest(tmp_path, repo, cache):
    include = [{"glob": "sql/*.sql", "dialect": "no-such-dialect"}]
    specs = download(tmp_path, repo, cache, include=include)
    with pytest.raises(m.ManifestError, match="no-such-dialect"):
        s.build(specs, cache)


@pytest.mark.parametrize("spdx", sorted(m.LICENSES))
def test_license_text_check_needs_each_phrase(spdx):
    text = "\n".join(s.LICENSE_PHRASES[spdx]).upper()
    assert s.license_errors(spdx, text) == []
    for phrase in s.LICENSE_PHRASES[spdx]:
        assert s.license_errors(spdx, text.replace(phrase.upper(), ""))


def test_license_text_check_ignores_case_and_white_space():
    text = (
        "Permission  is hereby granted,\n free of CHARGE, to any person obtaining a\n"
    )
    text += "copy of this software\n" + 'The Software is provided "AS IS", without\n'
    text += "warranty of any kind"
    assert s.license_errors("MIT", text) == []


def test_bsd_2_clause_text_must_not_have_the_third_clause():
    text = " ".join(s.LICENSE_PHRASES["BSD-3-Clause"])
    assert s.license_errors("BSD-2-Clause", text) != []
    assert s.license_errors("BSD-3-Clause", text) == []


def test_git_blob_id():
    assert s.git_blob_id(b"hi\n") == "45b983be36b73c0788dc9cbcb76cbb80fc7bb057"


def test_cli_select_writes_and_checks(tmp_path, repo, cache, capsys):
    root, commit = repo
    sources = write(tmp_path, source_list(commit))
    for spec in s.load_sources(sources):
        s.download(spec, cache, url=root.as_uri())
    out = tmp_path / "sources.json"
    base = ["select", "--sources", str(sources), "--cache", str(cache)]
    assert corpus_main.main([*base, "--manifest", str(out)]) == 0
    assert m.load(out).files
    capsys.readouterr()
    assert corpus_main.main([*base, "--manifest", str(out), "--check"]) == 0
    assert json.loads(capsys.readouterr().out)["same_as_manifest"] is True
    out.write_bytes(out.read_bytes().replace(b"A test source.", b"Changed."))
    assert corpus_main.main([*base, "--manifest", str(out), "--check"]) == 1
    assert json.loads(capsys.readouterr().out)["same_as_manifest"] is False


def test_cli_select_fails_with_no_cache(tmp_path, repo, capsys):
    _, commit = repo
    sources = write(tmp_path, source_list(commit))
    argv = ["select", "--sources", str(sources), "--cache", str(tmp_path / "c")]
    assert corpus_main.main([*argv, "--check"]) == 2
    assert "select --download" in capsys.readouterr().err


def test_committed_source_list_loads():
    specs = s.load_sources()
    assert specs and [x.id for x in specs] == sorted(x.id for x in specs)
