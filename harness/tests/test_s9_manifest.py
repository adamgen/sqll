"""The S9 corpus manifest: schema, loader, and validator (fail closed)."""

import copy
import json

import pytest

from sqll_harness.corpus import manifest as m
from sqll_harness.paths import SQLFLUFF_ROOT

SHA_A = "a" * 64
SHA_B = "b" * 64
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def tiny() -> dict:
    """A valid manifest with one source and 2 files."""
    return {
        "format": 1,
        "sources": {
            "demo": {
                "repository": "https://github.com/example/demo-sql",
                "commit": COMMIT,
                "license": "MIT",
                "copyright": ["Example Holder"],
                "license_files": [{"path": "LICENSE", "bytes": 10, "sha256": SHA_A}],
                "globs": ["sql/**/*.sql", "models/*.sql"],
                "note": "A test source.",
            }
        },
        "files": [
            {
                "id": "demo/models/m.sql",
                "source": "demo",
                "path": "models/m.sql",
                "dialect": "postgres",
                "templater": "jinja",
                "bytes": 8 * 1024,
                "lines": 100,
                "sha256": SHA_A,
                "smoke": True,
                "selection": "glob models/*.sql",
            },
            {
                "id": "demo/sql/a/big.sql",
                "source": "demo",
                "path": "sql/a/big.sql",
                "dialect": "tsql",
                "templater": "raw",
                "bytes": 40000,
                "lines": 900,
                "sha256": SHA_B,
                "smoke": False,
                "selection": "glob sql/**/*.sql",
            },
        ],
    }


def errors_of(data) -> list[str]:
    return m.validate(data)


def text_of(data) -> bytes:
    return json.dumps(data).encode()


def test_tiny_manifest_loads():
    man = m.parse(text_of(tiny()))
    assert list(man.sources) == ["demo"]
    src = man.sources["demo"]
    assert src.owner_repo == ("example", "demo-sql")
    assert src.copyright == ("Example Holder",)
    assert src.license_files == (m.Blob("LICENSE", 10, SHA_A),)
    assert [f.id for f in man.files] == ["demo/models/m.sql", "demo/sql/a/big.sql"]
    assert [f.id for f in man.selected(smoke=True)] == ["demo/models/m.sql"]
    assert len(man.selected(smoke=False)) == 2


def test_repository_manifest_is_valid():
    man = m.load()
    assert man.text == m.MANIFEST.read_bytes()
    for f in man.files:
        assert f.source in man.sources


def test_pinned_dialects_are_the_fixture_dialects():
    folders = {
        p.name
        for p in (SQLFLUFF_ROOT / "test" / "fixtures" / "dialects").iterdir()
        if p.is_dir()
    }
    assert m.pinned_dialects() == folders
    assert "tsql" in m.pinned_dialects()


def test_no_dialect_table_fails(tmp_path):
    path = tmp_path / "x.py"
    path.write_text("other = {}\n")
    with pytest.raises(m.ManifestError, match="no _dialect_lookup"):
        m.pinned_dialects.__wrapped__(path)
    with pytest.raises(m.ManifestError, match="cannot read"):
        m.pinned_dialects.__wrapped__(tmp_path / "missing.py")


def change(edit) -> list[str]:
    data = tiny()
    edit(data)
    return errors_of(data)


def one(errors: list[str], text: str) -> None:
    assert any(text in e for e in errors), errors


@pytest.mark.parametrize(
    "edit, where",
    [
        (lambda d: d.update(extra=1), "manifest: unknown keys ['extra']"),
        (lambda d: d["sources"]["demo"].update(url="x"), "unknown keys ['url']"),
        (lambda d: d["files"][0].update(size=1), "unknown keys ['size']"),
        (
            lambda d: d["sources"]["demo"]["license_files"][0].update(name="x"),
            "unknown keys ['name']",
        ),
        (lambda d: d.pop("files"), "missing keys ['files']"),
        (lambda d: d["files"][1].pop("smoke"), "missing keys ['smoke']"),
        (lambda d: d["sources"]["demo"].pop("copyright"), "missing keys"),
    ],
)
def test_unknown_or_missing_key_fails(edit, where):
    one(change(edit), where)


@pytest.mark.parametrize(
    "license", ["GPL-2.0-only", "LGPL-3.0", "TPC-EULA", "mit", "", None, ["MIT"]]
)
def test_license_not_in_allowlist_fails(license):
    errors = change(lambda d: d["sources"]["demo"].update(license=license))
    one(errors, "is not in the allowlist")


@pytest.mark.parametrize("license", sorted(m.LICENSES))
def test_each_allowlist_license_passes(license):
    assert change(lambda d: d["sources"]["demo"].update(license=license)) == []


def test_allowlist_is_that_of_the_design_record():
    assert m.LICENSES == {
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "PostgreSQL",
        "ISC",
        "CC0-1.0",
    }


@pytest.mark.parametrize("dialect", ["notadialect", "spark3", "Postgres", "", 1])
def test_dialect_not_pinned_fails(dialect):
    errors = change(lambda d: d["files"][0].update(dialect=dialect))
    assert any(".dialect" in e for e in errors), errors


@pytest.mark.parametrize("sha", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "", None, 12])
def test_bad_sha256_fails(sha):
    one(change(lambda d: d["files"][1].update(sha256=sha)), "not a sha256")
    one(
        change(lambda d: d["sources"]["demo"]["license_files"][0].update(sha256=sha)),
        "license_files[0].sha256: not a sha256",
    )


def test_duplicate_file_id_fails():
    def edit(d):
        d["files"].append(dict(d["files"][1], sha256="c" * 64))

    one(change(edit), "duplicate id")


def test_duplicate_source_id_fails():
    text = text_of(tiny()).replace(b'"sources": {', b'"sources": {"demo": {}, ', 1)
    with pytest.raises(m.ManifestError, match="duplicate key 'demo'"):
        m.parse(text)


def test_duplicate_sha256_fails():
    one(change(lambda d: d["files"][1].update(sha256=SHA_A)), "same sha256 as")


def test_files_not_sorted_fail():
    one(change(lambda d: d["files"].reverse()), "not sorted by source and path")


@pytest.mark.parametrize(
    "commit", [COMMIT[:7], COMMIT.upper(), "main", "REL_17_6", None]
)
def test_bad_commit_fails(commit):
    one(
        change(lambda d: d["sources"]["demo"].update(commit=commit)),
        "not a full commit sha",
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/example/demo-sql",
        "https://gitlab.com/example/demo-sql",
        "https://github.com/example",
        "https://github.com/example/demo-sql/",
        "https://github.com/example/demo-sql.git/x",
    ],
)
def test_bad_repository_fails(url):
    one(
        change(lambda d: d["sources"]["demo"].update(repository=url)),
        "not https://github.com",
    )


@pytest.mark.parametrize(
    "path",
    ["../sql/a.sql", "/sql/a.sql", "sql//a.sql", "sql/./a.sql", "sql\\a.sql", ""],
)
def test_bad_path_fails(path):
    def edit(d):
        d["files"][1].update(path=path, id=f"demo/{path}")

    assert any(".path" in e for e in change(edit))


def test_license_file_bad_path_fails():
    one(
        change(lambda d: d["sources"]["demo"]["license_files"][0].update(path="../L")),
        "license_files[0].path",
    )


def test_path_with_no_glob_fails():
    def edit(d):
        d["files"][1].update(path="docs/big.sql", id="demo/docs/big.sql")

    one(change(edit), "matches no glob of its source")


def test_glob_star_does_not_match_a_folder():
    def edit(d):
        d["files"][0].update(path="models/x/m.sql", id="demo/models/x/m.sql")

    one(change(edit), "matches no glob of its source")


def test_id_must_be_source_and_path():
    one(change(lambda d: d["files"][0].update(id="demo/m.sql")), "id is not")


def test_unknown_source_fails():
    one(change(lambda d: d["files"][0].update(source="other")), "unknown source")


@pytest.mark.parametrize("templater", ["dbt", "placeholder", "", None])
def test_bad_templater_fails(templater):
    one(change(lambda d: d["files"][0].update(templater=templater)), ".templater")


@pytest.mark.parametrize(
    "index, size, ok",
    [
        (0, 8 * 1024, True),
        (0, 8 * 1024 - 1, False),
        (1, 16 * 1024, True),
        (1, 16 * 1024 - 1, False),
        (1, 2 * 1024 * 1024, True),
        (1, 2 * 1024 * 1024 + 1, False),
    ],
)
def test_size_range(index, size, ok):
    def edit(d):
        d["files"][index].update(bytes=size, smoke=size <= 32 * 1024)

    errors = change(edit)
    assert (errors == []) == ok, errors


@pytest.mark.parametrize("index, smoke", [(0, False), (1, True)])
def test_smoke_flag_must_be_that_of_the_profile(index, smoke):
    one(change(lambda d: d["files"][index].update(smoke=smoke)), ".smoke")


@pytest.mark.parametrize(
    "key, value",
    [
        ("bytes", True),
        ("bytes", "40000"),
        ("bytes", 0),
        ("lines", -1),
        ("lines", 1.5),
        ("lines", 40001),
        ("smoke", 0),
        ("selection", ""),
        ("selection", None),
    ],
)
def test_bad_value_type_fails(key, value):
    assert change(lambda d: d["files"][1].update({key: value})) != []


@pytest.mark.parametrize(
    "key, value",
    [
        ("copyright", []),
        ("copyright", [""]),
        ("copyright", "Example Holder"),
        ("license_files", []),
        ("globs", []),
        ("note", ""),
    ],
)
def test_bad_source_value_fails(key, value):
    assert change(lambda d: d["sources"]["demo"].update({key: value})) != []


def test_duplicate_license_file_fails():
    def edit(d):
        files = d["sources"]["demo"]["license_files"]
        files.append(copy.deepcopy(files[0]))

    one(change(edit), "duplicate path")


@pytest.mark.parametrize("sid", ["Demo", "_demo", "-demo", "de mo", ""])
def test_bad_source_id_fails(sid):
    def edit(d):
        d["sources"][sid] = d["sources"].pop("demo")
        for f in d["files"]:
            f["source"] = sid
            f["id"] = f"{sid}/{f['path']}"

    one(change(edit), "bad source id")


@pytest.mark.parametrize("fmt", [2, True, "1", None])
def test_bad_format_fails(fmt):
    one(change(lambda d: d.update(format=fmt)), "format: not 1")


def test_not_json_fails():
    with pytest.raises(m.ManifestError, match="not a JSON file"):
        m.parse(b"{")
    with pytest.raises(m.ManifestError, match="not a JSON file"):
        m.parse(b"\xff")
    with pytest.raises(m.ManifestError, match="manifest: not an object"):
        m.parse(b"[]")


def test_each_error_is_reported():
    def edit(d):
        d["sources"]["demo"]["license"] = "GPL-2.0-only"
        d["files"][0]["dialect"] = "nope"
        d["files"][1]["sha256"] = "x"

    with pytest.raises(m.ManifestError) as info:
        m.parse(text_of(_edited(edit)))
    assert len(info.value.errors) == 3, info.value.errors


def test_missing_manifest_fails(tmp_path):
    with pytest.raises(m.ManifestError, match="cannot read"):
        m.load(tmp_path / "none.json")


def _edited(edit) -> dict:
    data = tiny()
    edit(data)
    return data
