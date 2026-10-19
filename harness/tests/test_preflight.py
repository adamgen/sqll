"""The preflight check finds sqlfluff config files above the repository."""

from pathlib import Path

import pytest

from sqll_harness import preflight


def _found(root: Path, top: Path) -> list[tuple[str, str]]:
    return [
        (str(path.relative_to(top)), reason)
        for path, reason in preflight.parent_configs(root)
        if path.is_relative_to(top)
    ]


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "a" / "b" / "repo"
    root.mkdir(parents=True)
    return tmp_path, root


@pytest.mark.parametrize(
    ("name", "text", "reason"),
    [
        (
            "pyproject.toml",
            "[tool.sqlfluff.core]\ndialect = 'ansi'\n",
            "a [tool.sqlfluff] table",
        ),
        ("pyproject.toml", "[tool.sqlfluff]\n", "a [tool.sqlfluff] table"),
        ("pyproject.toml", "[tool\n", "a pyproject.toml file that is not valid TOML"),
        (
            "setup.cfg",
            "[metadata]\nname = x\n[sqlfluff]\ndialect = ansi\n",
            "a [sqlfluff] section",
        ),
        ("tox.ini", "[sqlfluff:rules:LT01]\nx = 1\n", "a [sqlfluff] section"),
        ("pep8.ini", "  [sqlfluff]\n", "a [sqlfluff] section"),
        (".sqlfluff", "", "a .sqlfluff file"),
    ],
)
def test_finds_a_config_file(tree, name, text, reason):
    top, root = tree
    (top / "a" / name).write_text(text)
    assert _found(root, top) == [(f"a/{name}", reason)]
    assert preflight.check(root) == 2


@pytest.mark.parametrize(
    ("name", "text"),
    [
        (
            "pyproject.toml",
            "[tool.ruff]\nline-length = 88\n[project]\nname = 'sqlfluff'\n",
        ),
        ("setup.cfg", "[metadata]\nname = sqlfluff\n[sqlfluffx]\n"),
        ("tox.ini", "[testenv]\ncommands = sqlfluff lint\n"),
    ],
)
def test_ignores_a_file_without_sqlfluff_config(tree, name, text):
    top, root = tree
    (top / "a" / name).write_text(text)
    assert _found(root, top) == []


def test_ignores_config_in_the_repository(tree):
    top, root = tree
    (root / ".sqlfluff").write_text("[sqlfluff]\n")
    (root / "pyproject.toml").write_text("[tool.sqlfluff]\n")
    assert _found(root, top) == []


def test_finds_config_above_a_symlinked_root(tree):
    top, root = tree
    (top / "link").mkdir()
    (top / "link" / ".sqlfluff").write_text("")
    (top / "link" / "repo").symlink_to(root)
    assert _found(top / "link" / "repo", top) == [
        ("link/.sqlfluff", "a .sqlfluff file")
    ]


def test_message_names_each_file(tree, capsys):
    top, root = tree
    (top / "pyproject.toml").write_text("[tool.sqlfluff]\n")
    assert preflight.check(root) == 2
    err = capsys.readouterr().err
    assert f"{top / 'pyproject.toml'}: a [tool.sqlfluff] table" in err
    assert "parent folder of the repository" in err


def test_the_repository_has_no_config_file_above_it():
    # Fails in a checkout that gives other results than CI.
    assert preflight.parent_configs(preflight.REPO_ROOT) == []
