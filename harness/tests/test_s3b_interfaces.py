"""S3b C16: the index of the frozen interfaces, docs/interfaces/README.md.

Each frozen interface has one row with its document (docs/interfaces/) and
its test (crates/sqll_interfaces/tests/). The files of each row exist, each
document names its test, and each interface document and test file is in
the index."""

import re
from pathlib import Path

import pytest
from conftest import ci_module

from sqll_harness.paths import REPO_ROOT

DOCS = REPO_ROOT / "docs" / "interfaces"
TESTS = REPO_ROOT / "crates" / "sqll_interfaces" / "tests"
INDEX = (DOCS / "README.md").read_text("utf8")
ROW = re.compile(
    r"^\| (?P<name>[^|]+?) \| (?P<task>C\d+) \| (?P<packages>[^|]+?) \|"
    r" \[(?P<doc>[\w.-]+)\]\((?P<link>[^)]+)\) \| `(?P<test>[^`]+)` \|$"
)
# The 8 frozen interfaces of S3b (STONES.md, S3b; docs/decisions/s3b-core.md).
INTERFACES = {
    "Segment kinds": ("segment-kinds.md", "segment_kinds.rs"),
    "Syntax tree": ("tree.md", "tree.rs"),
    "Source map": ("source-map.md", "source_map.rs"),
    "Parse": ("parse.md", "parse.rs"),
    "Typed view": ("typed-view.md", "typed_view.rs"),
    "Config": ("config.md", "config.rs"),
    "Rules and fixes": ("rules.md", "rules.rs"),
    "Tree to schema": ("schema.md", "schema.rs"),
}
# The task and the packages of each interface. A package of a later track
# names the track and its stone goal.
TASKS_AND_PACKAGES = {
    "Segment kinds": ("C6", "`sqll_tree`"),
    "Syntax tree": ("C7", "`sqll_tree`, `sqll_syntax`"),
    "Source map": ("C8", "`sqll_source`, `sqll_templater` (S6, templater parity)"),
    "Parse": ("C9", "`sqll_syntax`"),
    "Typed view": ("C10", "`sqll_tree`"),
    "Config": ("C11", "`sqll_config`"),
    "Rules and fixes": ("C12", "`sqll_lint`, `sqll_rules` (S5, rule parity)"),
    "Tree to schema": ("C15", "`sqll_schema`, `sqll_codegen` (S8, code generation)"),
}
PACKAGE = re.compile(r"`(?P<name>\w+)`(?: \((?P<track>[\w-]+), [^)]+\))?")


def rows(text: str) -> list[dict[str, str]]:
    """Return the rows of the interface table of an index text."""
    table = text.split("\n## ", 1)[0]
    lines = [line for line in table.splitlines() if line.startswith("| ")]
    found = []
    for line in lines[1:]:
        match = ROW.match(line)
        if match is None:
            raise ValueError(f"not an interface row: {line}")
        found.append(match.groupdict())
    return found


def problems(text: str, docs: Path = DOCS, tests: Path = TESTS) -> list[str]:
    """Return each difference between an index text and the files."""
    found = []
    entries = rows(text)
    names = [e["name"] for e in entries]
    if len(set(names)) != len(names):
        found.append("an interface has two rows")
    for entry in entries:
        doc, test = entry["doc"], entry["test"]
        if entry["link"] != doc:
            found.append(f"{entry['name']}: the link {entry['link']} is not {doc}")
        if not (docs / doc).is_file():
            found.append(f"{entry['name']}: no document {doc}")
            continue
        if Path(test).parent != Path("crates/sqll_interfaces/tests"):
            found.append(f"{entry['name']}: {test} is not an interface test")
        if not (tests / Path(test).name).is_file():
            found.append(f"{entry['name']}: no test {test}")
        head = " ".join((docs / doc).read_text("utf8").split("\n## ", 1)[0].split())
        if f"Interface test: `{test}`" not in head:
            found.append(f"{entry['name']}: {doc} does not name the test {test}")
    listed_docs = {e["doc"] for e in entries}
    for path in sorted(docs.glob("*.md")):
        if path.name != "README.md" and path.name not in listed_docs:
            found.append(f"the document {path.name} is not in the index")
    listed_tests = {Path(e["test"]).name for e in entries}
    for path in sorted(tests.glob("*.rs")):
        if path.name not in listed_tests:
            found.append(f"the test {path.name} is not in the index")
    return found


def test_the_index_has_the_8_interfaces():
    entries = rows(INDEX)
    assert len(entries) == 8
    got = {
        e["name"]: (e["doc"], e["test"].removeprefix("crates/sqll_interfaces/tests/"))
        for e in entries
    }
    assert got == INTERFACES


def test_the_task_and_the_packages_of_each_row_are_correct():
    got = {e["name"]: (e["task"], e["packages"]) for e in rows(INDEX)}
    assert got == TASKS_AND_PACKAGES


def test_the_track_of_each_package_of_the_index_is_its_owner_in_tracks_yml():
    ownership = ci_module("ownership")
    tracks = ownership.load()
    seen = 0
    for _, packages in TASKS_AND_PACKAGES.values():
        for match in PACKAGE.finditer(packages):
            track = match["track"] or "core"
            path = f"crates/{match['name']}/src/lib.rs"
            assert ownership.owner(path, tracks) == track, path
            seen += 1
    assert seen == 12


@pytest.mark.parametrize(
    "old, new",
    [
        ("| Config | C11 |", "| Config | C99 |"),
        ("`sqll_lint`, `sqll_rules` (S5, rule parity)", "`sqll_wrong`"),
        ("(S8, code generation)", "(S4, parser parity)"),
    ],
)
def test_a_changed_task_or_package_cell_fails(old, new):
    assert INDEX.count(old) == 1
    got = {e["name"]: (e["task"], e["packages"]) for e in rows(INDEX.replace(old, new))}
    assert got != TASKS_AND_PACKAGES


def test_each_document_and_test_of_the_index_exists():
    assert problems(INDEX) == []
    for doc, test in INTERFACES.values():
        assert (DOCS / doc).is_file(), doc
        assert (TESTS / test).is_file(), test


def test_each_interface_test_file_is_in_the_index():
    files = {p.name for p in TESTS.glob("*.rs")}
    assert files == {test for _, test in INTERFACES.values()}


def _without(name: str) -> str:
    lines = [line for line in INDEX.splitlines() if not line.startswith(f"| {name} |")]
    assert len(lines) == len(INDEX.splitlines()) - 1
    return "\n".join(lines)


def test_a_missing_row_fails():
    assert problems(_without("Config")) == [
        "the document config.md is not in the index",
        "the test config.rs is not in the index",
    ]


@pytest.mark.parametrize(
    "old, new, problem",
    [
        (
            "[parse.md](parse.md)",
            "[parse2.md](parse2.md)",
            "Parse: no document parse2.md",
        ),
        (
            "`crates/sqll_interfaces/tests/parse.rs`",
            "`crates/sqll_interfaces/tests/parse2.rs`",
            "Parse: no test crates/sqll_interfaces/tests/parse2.rs",
        ),
        (
            "`crates/sqll_interfaces/tests/parse.rs`",
            "`crates/sqll_syntax/tests/parse.rs`",
            "Parse: crates/sqll_syntax/tests/parse.rs is not an interface test",
        ),
        (
            "[parse.md](parse.md)",
            "[parse.md](tree.md)",
            "Parse: the link tree.md is not parse.md",
        ),
        (
            "| [tree.md](tree.md) | `crates/sqll_interfaces/tests/tree.rs` |",
            "| [tree.md](tree.md) | `crates/sqll_interfaces/tests/parse.rs` |",
            "Syntax tree: tree.md does not name the test"
            " crates/sqll_interfaces/tests/parse.rs",
        ),
    ],
)
def test_a_changed_row_fails(old, new, problem):
    assert INDEX.count(old) == 1
    assert problem in problems(INDEX.replace(old, new))


def test_a_new_document_or_test_that_is_not_in_the_index_fails(tmp_path):
    docs, tests = tmp_path / "docs", tmp_path / "tests"
    docs.mkdir()
    tests.mkdir()
    for path in DOCS.glob("*.md"):
        (docs / path.name).write_bytes(path.read_bytes())
    for path in TESTS.glob("*.rs"):
        (tests / path.name).write_bytes(path.read_bytes())
    assert problems(INDEX, docs, tests) == []
    (docs / "lexer.md").write_text("# Lexer\n")
    (tests / "lexer.rs").write_text("")
    assert problems(INDEX, docs, tests) == [
        "the document lexer.md is not in the index",
        "the test lexer.rs is not in the index",
    ]


def test_a_row_that_is_not_an_interface_row_fails():
    text = INDEX.replace("| Parse | C9 |", "| Parse | x |")
    with pytest.raises(ValueError, match="not an interface row"):
        rows(text)
