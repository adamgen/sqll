"""Tests of scripts/s3b/schema_check.py (S3b task C15): the jsonschema
package validates the committed JSON Schema output of the code generation
interface against the draft 2020-12 meta-schema, and the example values of
each case against its schema. The CI job build runs "check", which writes
the output again with cargo."""

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "s3b" / "schema_check.py"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def load():
    spec = importlib.util.spec_from_file_location("schema_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["schema_check"] = module
    spec.loader.exec_module(module)
    return module


sc = load()


@pytest.fixture
def record(tmp_path):
    """A copy of the committed record in tmp_path."""
    shutil.copy(sc.RECORD, tmp_path / sc.RECORD_NAME)
    shutil.copytree(sc.RECORD_DIR, tmp_path / sc.RECORD_DIR_NAME)
    return tmp_path


def change(folder: Path, case: str, edit) -> None:
    path = folder / sc.RECORD_DIR_NAME / f"{case}.json"
    schema = json.loads(path.read_text("utf8"))
    edit(schema)
    path.write_text(json.dumps(schema), "utf8")


def test_the_committed_record_is_valid():
    problems, counts = sc.validate(sc.FOLDER)
    assert problems == []
    assert counts == {"schemas": 4, "valid": 8, "invalid": 29}


def test_each_format_of_the_record_has_an_invalid_example_of_only_that_format():
    """For each format, an invalid example fails only by the format check:
    so the check of the format runs."""
    from jsonschema import Draft202012Validator

    record = json.loads(sc.RECORD.read_text("utf8"))
    used, refused = set(), set()
    for case in record["cases"]:
        schema = json.loads((sc.FOLDER / case["schema"]).read_text("utf8"))
        used |= sc.formats(schema)
        validator = Draft202012Validator(schema, format_checker=sc.FORMAT_CHECKER)
        for example in case["invalid"]:
            errors = list(validator.iter_errors(example))
            if errors and all(e.validator == "format" for e in errors):
                refused |= {e.validator_value for e in errors}
    assert used == {"date", "time", "date-time", "uuid"}
    assert refused == used


def test_the_time_formats_need_an_offset():
    """The RFC 3339 formats "time" and "date-time" need a time zone offset.
    Thus a time or a timestamp with no time zone has no format."""
    checker = sc.FORMAT_CHECKER
    assert checker.conforms("10:00:00+02:00", "time")
    assert not checker.conforms("10:00:00", "time")
    assert checker.conforms("2026-11-09T10:00:00Z", "date-time")
    assert not checker.conforms("2026-11-09T10:00:00", "date-time")
    named = json.loads((sc.RECORD_DIR / "named.json").read_text("utf8"))
    row = named["$defs"]["row"]["properties"]
    assert "format" not in row["at"] and row["at"]["x-sqll-type"] == "time"
    assert "format" not in row["local"]
    assert row["at_tz"]["format"] == "time"
    assert row["created"]["format"] == "date-time"


def test_a_format_with_no_checker_fails(record, monkeypatch):
    from jsonschema import FormatChecker

    monkeypatch.setattr(sc, "FORMAT_CHECKER", FormatChecker(formats=["date", "uuid"]))
    problems, _ = sc.validate(record)
    assert problems == [
        "named: the jsonschema package has no checker of the format 'date-time'",
        "named: the jsonschema package has no checker of the format 'time'",
    ]


def test_formats_finds_only_the_format_keywords():
    schema = {
        "properties": {"format": {"type": "string", "format": "uuid"}},
        "required": ["format"],
        "prefixItems": [{"format": "date"}],
        "x-sqll-name": "format",
    }
    assert sc.formats(schema) == {"uuid", "date"}


def test_the_record_has_the_cases_and_the_draft():
    record = json.loads(sc.RECORD.read_text("utf8"))
    assert record["kind"] == sc.KIND
    assert record["meta_schema"] == sc.DRAFT
    assert [c["name"] for c in record["cases"]] == list(sc.CASES)
    minimal = record["cases"][0]
    assert minimal["dialect"] == "ansi"
    assert minimal["origin"].startswith("sqll_codegen::LiteralSelect")
    assert (
        minimal["sql"] == "SELECT 1 AS id, 'x' AS \"Name\", TRUE AS ok, NULL AS note\n"
    )
    for case in record["cases"][1:]:
        assert case["sql"] is None
        assert case["origin"] == "hand-built description (writer test)"
    schemas = sorted(p.name for p in sc.RECORD_DIR.iterdir())
    assert schemas == sorted(f"{c}.json" for c in sc.CASES)


def test_the_validator_uses_the_draft_2020_12_meta_schema():
    from jsonschema import Draft202012Validator

    assert Draft202012Validator.META_SCHEMA["$id"] == sc.DRAFT
    # prefixItems is a keyword of draft 2020-12 only.
    assert (
        sc.schema_problems(
            {"$schema": sc.DRAFT, "title": "t", "prefixItems": [{"type": "integer"}]},
            "t",
        )
        == []
    )
    assert sc.schema_problems(
        {"$schema": sc.DRAFT, "title": "t", "prefixItems": {"type": "integer"}},
        "t",
    )


@pytest.mark.parametrize(
    "edit",
    [
        lambda s: s["$defs"]["row"]["properties"]["ID"].update(type="integr"),
        lambda s: s["$defs"]["row"].update(required="ID"),
        lambda s: s["$defs"]["row"].update(additionalProperties=1),
        lambda s: s["$defs"]["parameters"].update(properties=[]),
        lambda s: s.update(type=["object", "object"]),
    ],
)
def test_a_schema_that_the_meta_schema_refuses_fails(record, edit):
    change(record, "minimal", edit)
    problems, _ = sc.validate(record)
    assert any("not valid against the meta-schema" in p for p in problems), problems


def test_another_draft_or_title_fails(record):
    change(record, "named", lambda s: s.update({"$schema": "x", "title": "y"}))
    problems, _ = sc.validate(record)
    assert "named: $schema is not " + sc.DRAFT in problems
    assert "named: the title is not 'named'" in problems


def test_a_schema_that_is_too_wide_lets_an_invalid_example_pass(record):
    change(
        record,
        "minimal",
        lambda s: s["$defs"]["row"]["properties"]["ID"].update(
            type=["integer", "string"]
        ),
    )
    problems, _ = sc.validate(record)
    assert problems == ["minimal: invalid example 0 passes"]


def test_a_schema_that_is_too_narrow_fails_a_valid_example(record):
    change(
        record,
        "question_mark",
        lambda s: s["$defs"]["parameters"]["prefixItems"][1].update(type="string"),
    )
    problems, _ = sc.validate(record)
    assert len(problems) == 1
    assert problems[0].startswith("question_mark: valid example 1 fails")


def test_a_missing_schema_file_fails(record):
    (record / sc.RECORD_DIR_NAME / "numeric_dollar.json").unlink()
    problems, counts = sc.validate(record)
    assert counts["schemas"] == 3
    assert problems and problems[0].startswith("numeric_dollar: C15-schema/")


def test_compare_names_each_different_file(record, tmp_path):
    other = tmp_path / "other"
    shutil.copytree(record, other)
    assert sc.compare(other, record) == []
    change(other, "named", lambda s: s.update(title="named"))
    (other / sc.RECORD_DIR_NAME / "extra.json").write_text("{}", "utf8")
    assert sc.compare(other, record) == [
        "C15-schema/extra.json is not the committed record",
        "C15-schema/named.json is not the committed record",
    ]


def test_ci_runs_the_check_in_the_build_job():
    text = CI.read_text("utf8")
    build = text.split("\n  build:\n", 1)[1].split("\n  test:\n", 1)[0]
    command = "uv run --frozen --project harness python scripts/s3b/schema_check.py"
    assert f"run: {command} check" in build


def test_third_party_names_the_locked_versions_of_the_validator():
    import tomllib

    lock = tomllib.loads((REPO_ROOT / "harness" / "uv.lock").read_text("utf8"))
    versions = {p["name"]: p["version"] for p in lock["package"]}
    text = " ".join((REPO_ROOT / "THIRD_PARTY.md").read_text("utf8").split())
    for name in (
        "jsonschema",
        "jsonschema-specifications",
        "attrs",
        "referencing",
        "rpds-py",
        "rfc3339-validator",
        "six",
    ):
        assert f"`{name}` {versions[name]}" in text, name
