"""Offline checks of the committed corpus manifest (corpus/sources.json)
against its source list (corpus/select.json) and the rules of
docs/decisions/s9-corpus.md ("Licenses", "Selection", "Size", "Content").
No test uses the network.
"""

import json
import re
from collections import Counter

import pytest

from sqll_harness.corpus import jinja_names
from sqll_harness.corpus import manifest as m
from sqll_harness.corpus import select as s
from sqll_harness.paths import REPO_ROOT

# docs/decisions/s9-corpus.md, "Content": the limits of the smoke subset.
SMOKE_TOTAL_MAX_BYTES = 2 * 1024 * 1024
SMOKE_MAX_FILES = 100
# The dialects with a permissive source (T4 task scope).
DIALECTS = {"postgres", "mysql", "tsql", "oracle", "sqlite", "snowflake", "bigquery"}
# The dialects of the templated sources (T5).
TEMPLATED_DIALECTS = {"bigquery", "clickhouse"}
_NAMES = re.compile(r"; templater jinja: the Jinja code reads only \[([a-z_, ]*)\] ")


def _reads(selection: str) -> list[str]:
    """Return the names in the selection of a templated file ([] for "[]")."""
    names = _NAMES.search(selection)
    assert names, selection
    return names.group(1).split(", ") if names.group(1) else []


@pytest.fixture(scope="module")
def manifest() -> m.Manifest:
    return m.load()


@pytest.fixture(scope="module")
def specs() -> dict[str, s.SourceSpec]:
    return {spec.id: spec for spec in s.load_sources()}


def test_manifest_is_valid_and_not_empty(manifest):
    assert manifest.sources and manifest.files


def test_each_source_has_an_allowlist_license_with_a_text_check(manifest):
    for source in manifest.sources.values():
        assert source.license in m.LICENSES
        assert source.license in s.LICENSE_PHRASES
        assert source.copyright
        assert source.license_files
        for blob in source.license_files:
            assert len(blob.sha256) == 64 and blob.bytes > 0


def test_license_text_check_covers_the_allowlist():
    assert set(s.LICENSE_PHRASES) == set(m.LICENSES)


def test_manifest_sources_are_those_of_the_source_list(manifest, specs):
    assert sorted(manifest.sources) == sorted(specs)
    for sid, source in manifest.sources.items():
        spec = specs[sid]
        assert source.repository == spec.repository
        assert source.commit == spec.commit
        assert source.license == spec.license
        assert source.copyright == spec.copyright
        assert source.globs == tuple(spec.globs)
        assert source.note == (s.source_note(spec) or None)
        assert [b.path for b in source.license_files] == list(spec.license_files)


def test_each_file_has_the_dialect_templater_and_note_of_its_glob(manifest, specs):
    dialects = m.pinned_dialects()
    for f in manifest.files:
        spec = specs[f.source]
        hits = [i for i in spec.include if s.matches(f.path, i.glob)]
        assert len(hits) == 1, f.id
        include = hits[0]
        assert f.dialect == include.dialect and f.dialect in dialects
        assert f.templater == include.templater
        low = m.MIN_BYTES[f.templater]
        assert low <= f.bytes <= m.MAX_BYTES, f.id
        rule = (
            f"glob {include.glob} (dialect {include.dialect}); "
            f"{low} <= bytes <= {m.MAX_BYTES}; UTF-8; first file with its sha256"
        )
        if f.templater == m.RAW:
            assert f.selection == rule == s.selection(include)
            continue
        assert f.selection.startswith(rule + "; templater jinja: "), f.id
        reads = _reads(f.selection)
        assert reads == sorted(set(reads)) and set(reads) <= jinja_names.allowed()
        assert f.selection == s.selection(include, reads), f.id


def test_the_read_names_of_a_selection():
    include = s.Include("models/*.sql", "ansi", m.JINJA)
    assert _reads(s.selection(include, [])) == []
    assert _reads(s.selection(include, ["config", "ref"])) == ["config", "ref"]


def test_excluded_files_are_not_in_the_manifest(manifest, specs):
    ids = {f.id for f in manifest.files}
    excluded = [(spec, path) for spec in specs.values() for path, _ in spec.exclude]
    assert excluded
    for spec, path in excluded:
        assert f"{spec.id}/{path}" not in ids
        assert any(s.matches(path, glob) for glob in spec.globs)
        assert f"Excluded: {path}: " in manifest.sources[spec.id].note


def test_each_source_has_files(manifest):
    used = Counter(f.source for f in manifest.files)
    assert set(used) == set(manifest.sources)


def test_untemplated_files_cover_the_dialects_and_sizes(manifest):
    raw = [f for f in manifest.files if f.templater == m.RAW]
    assert DIALECTS <= {f.dialect for f in raw}
    assert sum(f.bytes > 100_000 for f in raw) >= 5
    assert sum(f.bytes > 1_000_000 for f in raw) >= 1


def test_templated_files_use_only_the_dbt_builtins(manifest, specs):
    jinja = [f for f in manifest.files if f.templater == m.JINJA]
    assert len(jinja) >= 10
    assert {f.dialect for f in jinja} == TEMPLATED_DIALECTS
    assert len({f.source for f in jinja}) >= 2
    used = set()
    for f in jinja:
        used |= set(_reads(f.selection))
    # The files use the main dbt builtins, and no name outside the rule.
    assert {"config", "ref", "source", "var", "is_incremental", "this"} <= used
    # A source of templated files has only templated globs.
    for sid in {f.source for f in jinja}:
        assert {i.templater for i in specs[sid].include} == {m.JINJA}


def test_smoke_subset_is_small(manifest):
    smoke = manifest.selected(smoke=True)
    assert smoke
    assert all(f.bytes <= m.SMOKE_MAX_BYTES for f in smoke)
    assert sum(f.bytes for f in smoke) <= SMOKE_TOTAL_MAX_BYTES
    assert len(smoke) <= SMOKE_MAX_FILES


def test_manifest_text_is_the_select_format(manifest):
    data = json.loads(manifest.text)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    assert manifest.text == text.encode("utf8")


def test_repository_has_no_corpus_sql():
    found = [
        p
        for p in (REPO_ROOT / "corpus").rglob("*")
        if p.is_file() and p.suffix.lower() == ".sql"
    ]
    assert found == []
