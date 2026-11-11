"""S3b task C14: the proof that the Jinja templater of the pinned sqlfluff
gives the file of the raw templater for each input of the sqll adapter
(harness/sqll.md, "Adapter").

Run it with the harness Python from the repository root:

    uv run --frozen --project harness python scripts/s3b/jinja_raw_oracle.py record
    uv run --frozen --project harness python scripts/s3b/jinja_raw_oracle.py check

The inputs (harness Python): each SQL string of each rule case (pass_str,
fail_str, and fix_str, as the rules suite writes them) and the before.sql
of each autofix case (as the autofix suite writes it), for which the
templater is jinja (the sqlfluff default). The data (sqlfluff Python, the
"dump" command): for each input, with the config that sqlfluff uses for
it (the case config, the dialect, and for autofix the config files of the
case folder), the newlines of Linter.render_string, and then
process_with_variants of the Jinja templater and of the raw templater. The
input is "equal" if both give one variant, no error, and the same
templated text, sliced file, and raw slices.

RECORD_FILE has the sha256 of the UTF-8 bytes of each equal input. The
sqll adapter (harness/sqll_harness/adapters/sqll.py) runs sqll on a jinja
case only if the sha256 of each of its SQL files is in the record. A text
that is equal for one config and not equal for another is not in the
record.

record: write RECORD_FILE. check (CI job build): make the data again; it
must be the text of RECORD_FILE.

Exit code: 0 pass, 1 a failure.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQLFLUFF_ROOT = ROOT / "third_party" / "sqlfluff"
RECORD_FILE = ROOT / "results" / "S3b" / "C14-jinja-raw.json"
KIND = "sqll-s3b-c14-jinja-raw"
FORMAT = 1
COMMAND = "uv run --frozen --project harness python scripts/s3b/jinja_raw_oracle.py"
JINJA_DELIMITERS = ("{{", "{%", "{#")


class DataError(Exception):
    """A step failed, or the data do not agree."""


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


# The inputs, made with the harness Python.


def templater_of(configs) -> str:
    """The templater of a rule case config (default jinja, as sqlfluff)."""
    core = configs.get("core") if isinstance(configs, dict) else None
    value = core.get("templater", "jinja") if isinstance(core, dict) else "jinja"
    return str(value).strip()


def inputs() -> list[dict]:
    """Each input: {"suite", "id", "text", ...}. Rule inputs have
    "configs" and "dialect"; autofix inputs have "config_text" and
    "dialect"."""
    sys.path.insert(0, str(ROOT / "harness"))
    from sqll_harness.suites import autofix, rules

    out = []
    for case in rules.discover(SQLFLUFF_ROOT):
        if templater_of(case.configs) != "jinja":
            continue
        strings = {
            "pass": case.pass_str,
            "fail": case.fail_str,
            "fixed": case.fix_str if case.fail_str else None,
        }
        for name, text in strings.items():
            # As the suite: an empty string is no string.
            if not text:
                continue
            out.append(
                {
                    "suite": "rules",
                    "id": f"{case.id}/{name}",
                    "text": text,
                    "configs": case.configs,
                    "dialect": rules.default_dialect(case.configs),
                }
            )
    for case in autofix.discover(SQLFLUFF_ROOT):
        try:
            text = autofix.read_text(case.folder / "before.sql")
        except OSError:
            continue
        config_path = case.folder / autofix.CONFIG_NAME
        config_text = autofix.read_text(config_path) if config_path.exists() else ""
        out.append(
            {
                "suite": "autofix",
                "id": case.id,
                "text": text,
                "config_text": config_text,
                "dialect": case.dialect,
            }
        )
    return out


# The data, made with the sqlfluff Python (the "dump" command).


def variants(templater, text: str, fname: str, config) -> tuple[list, list]:
    from sqlfluff.core.errors import SQLTemplaterError

    files, errors = [], []
    try:
        for variant, errs in templater.process_with_variants(
            in_str=text, fname=fname, config=config
        ):
            if variant:
                files.append(variant)
            errors += errs
    except SQLTemplaterError as exc:
        errors.append(exc)
    return files, errors


def compare(text: str, fname: str, config) -> str | None:
    """None if the Jinja templater gives the file of the raw templater, else
    the reason."""
    from sqlfluff.core import Linter
    from sqlfluff.core.templaters import JinjaTemplater, RawTemplater

    text = Linter._normalise_newlines(text)
    jinja, jinja_errors = variants(JinjaTemplater(), text, fname, config)
    raw, raw_errors = variants(RawTemplater(), text, fname, config)
    if jinja_errors or raw_errors:
        return f"templater errors: {len(jinja_errors)} jinja, {len(raw_errors)} raw"
    if len(jinja) != 1 or len(raw) != 1:
        return f"variants: {len(jinja)} jinja, {len(raw)} raw"
    j, r = jinja[0], raw[0]
    if j.templated_str != r.templated_str:
        return "another templated text"
    if j.sliced_file != r.sliced_file:
        return "another sliced file"
    if j.raw_sliced != r.raw_sliced:
        return "another list of raw slices"
    return None


def rule_config(item: dict):
    from sqlfluff.core import FluffConfig

    overrides = {} if item["dialect"] is None else {"dialect": item["dialect"]}
    return FluffConfig(configs=item["configs"], overrides=overrides)


def autofix_config(item: dict, folder: Path):
    """The config of the file as "sqlfluff fix" makes it: the root config of
    the current folder (the sqlfluff root), then the files of the case
    folder."""
    from sqlfluff.core import FluffConfig

    (folder / ".sqlfluff").write_text(item["config_text"], encoding="utf8")
    root = FluffConfig.from_root(overrides={"dialect": item["dialect"]})
    return root.make_child_from_path(str(folder / "testing.sql"))


def dump(items: list[dict]) -> list[dict]:
    out = []
    here = os.getcwd()
    os.chdir(SQLFLUFF_ROOT)
    try:
        for item in items:
            with tempfile.TemporaryDirectory(prefix="sqll-c14-") as tmp:
                folder = Path(tmp)
                fname = str(folder / "testing.sql")
                try:
                    if item["suite"] == "rules":
                        config = rule_config(item)
                    else:
                        config = autofix_config(item, folder)
                    reason = compare(item["text"], fname, config)
                except Exception as exc:  # noqa: BLE001
                    reason = f"{type(exc).__name__}: {str(exc).splitlines()[0:1]}"
            out.append({"id": item["id"], "reason": reason})
    finally:
        os.chdir(here)
    return out


# The commands of the harness Python.


def tool_python() -> Path:
    sys.path.insert(0, str(ROOT / "harness"))
    from sqll_harness.paths import tools_dir

    return tools_dir() / "sqlfluff" / "bin" / "python"


def run_dump(items: list[dict]) -> list[dict]:
    python = tool_python()
    if not python.is_file():
        raise DataError(f"no sqlfluff Python at {python} (scripts/setup)")
    with tempfile.TemporaryDirectory(prefix="sqll-c14-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        data = Path(tmp) / "inputs.json"
        data.write_text(json.dumps(items), encoding="utf8")
        argv = [
            str(python),
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            "dump",
            str(data),
        ]
        print(f"jinja_raw_oracle: $ {' '.join(argv[:-1])} <inputs>", flush=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env.update(
            HOME=str(home), XDG_CONFIG_HOME=str(home), PYTHONDONTWRITEBYTECODE="1"
        )
        proc = subprocess.run(
            argv, cwd=ROOT, env=env, text=True, capture_output=True, check=False
        )
    if proc.returncode != 0:
        raise DataError(f"dump: exit code {proc.returncode}\n{proc.stderr[-4000:]}")
    results = json.loads(proc.stdout)
    if [r["id"] for r in results] != [i["id"] for i in items]:
        raise DataError("dump: the results are not those of the inputs")
    return results


def submodule_commit() -> str:
    out = subprocess.run(
        ["git", "-C", str(SQLFLUFF_ROOT), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    return out.stdout.strip()


def sqlfluff_version() -> str:
    proc = subprocess.run(
        [
            str(tool_python()),
            "-I",
            "-c",
            "import sqlfluff; print(sqlfluff.__version__)",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def summarize(items: list[dict], results: list[dict]) -> dict:
    """The equal texts (a text that is not equal for one input is not
    equal) and the counts."""
    equal: set[str] = set()
    not_equal: set[str] = set()
    with_delimiters = 0
    for item, result in zip(items, results, strict=True):
        h = sha256(item["text"])
        (not_equal if result["reason"] else equal).add(h)
        if any(d in item["text"] for d in JINJA_DELIMITERS):
            with_delimiters += 1
    equal -= not_equal
    counts = {
        "inputs": len(items),
        "rule_inputs": sum(i["suite"] == "rules" for i in items),
        "autofix_inputs": sum(i["suite"] == "autofix" for i in items),
        "inputs_with_delimiters": with_delimiters,
        "equal_inputs": sum(1 for i in items if sha256(i["text"]) in equal),
        "equal_texts": len(equal),
        "not_equal_texts": len(not_equal),
    }
    return {"counts": counts, "equal": sorted(equal)}


def problems_of(items: list[dict], results: list[dict]) -> list[str]:
    """An equal input with a Jinja delimiter, or a not equal input with no
    delimiter, is not what sqlfluff documents (the fast path of
    JinjaTemplater.process): the record must not hide it."""
    out = []
    for item, result in zip(items, results, strict=True):
        tags = any(d in item["text"] for d in JINJA_DELIMITERS)
        if result["reason"] is None and tags:
            out.append(f"{item['id']}: equal, but it has a Jinja delimiter")
        if result["reason"] is not None and not tags:
            out.append(f"{item['id']}: no Jinja delimiter, but {result['reason']}")
    return out


def record_data(summary: dict, problems: list[str]) -> dict:
    return {
        "kind": KIND,
        "format": FORMAT,
        "about": (
            "S3b C14: the sha256 of each SQL input of the rule and autofix "
            "suites whose Jinja templated file (sqlfluff process_with_variants, "
            "with the config of the input) is that of the raw templater: one "
            "variant, no error, the same text, sliced file, and raw slices "
            "(scripts/s3b/jinja_raw_oracle.py; harness/sqll.md). The sqll "
            "adapter runs sqll with the jinja templater only for these texts. "
            "notes: the inputs where the result and the Jinja delimiters do "
            "not agree."
        ),
        "command": f"{COMMAND} record",
        "sqlfluff": {"version": sqlfluff_version(), "commit": submodule_commit()},
        "counts": summary["counts"],
        "notes": problems,
        "equal": summary["equal"],
    }


def dumps(record: dict) -> str:
    """JSON with one line for each item of a list."""
    lines = ["{"]
    keys = list(record)
    for k, key in enumerate(keys):
        end = "," if k < len(keys) - 1 else ""
        value = record[key]
        if not isinstance(value, list) or not value:
            lines.append(
                f" {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}{end}"
            )
            continue
        lines.append(f" {json.dumps(key)}: [")
        for i, item in enumerate(value):
            sep = "," if i < len(value) - 1 else ""
            lines.append(f"  {json.dumps(item, ensure_ascii=False)}{sep}")
        lines.append(" ]" + end)
    lines.append("}")
    return "\n".join(lines) + "\n"


def make() -> dict:
    items = inputs()
    results = run_dump(items)
    return record_data(summarize(items, results), problems_of(items, results))


def record() -> int:
    data = make()
    RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECORD_FILE.write_text(dumps(data), encoding="utf8")
    print(f"jinja_raw_oracle: wrote {RECORD_FILE.relative_to(ROOT)}: {data['counts']}")
    return 0


def check() -> int:
    data = make()
    problems = []
    want = dumps(data)
    if not RECORD_FILE.is_file() or RECORD_FILE.read_text(encoding="utf8") != want:
        rel = RECORD_FILE.relative_to(ROOT)
        problems.append(f"{rel} is not the sqlfluff data ({COMMAND} record)")
    clean = subprocess.run(
        [str(ROOT / "scripts" / "check-submodule"), "after the jinja as raw data"],
        check=False,
    )
    if clean.returncode != 0:
        problems.append("the sqlfluff run changed the submodule")
    for p in problems:
        print(f"jinja as raw check: {p}")
    if problems:
        print(f"jinja as raw check: FAIL: {len(problems)} problems")
        return 1
    c = data["counts"]
    print(
        f"jinja as raw check: PASS: {c['inputs']} inputs ({c['rule_inputs']} rule, "
        f"{c['autofix_inputs']} autofix), {c['equal_inputs']} equal "
        f"({c['equal_texts']} texts), {c['inputs_with_delimiters']} with a Jinja "
        f"delimiter, {len(data['notes'])} notes"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("record", help="write the record file")
    sub.add_parser("check", help="make the data again and compare")
    d = sub.add_parser("dump", help="(sqlfluff Python) print the data as JSON")
    d.add_argument("inputs", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "dump":
            items = json.loads(args.inputs.read_text(encoding="utf8"))
            json.dump(dump(items), sys.stdout)
            return 0
        if args.command == "record":
            return record()
        return check()
    except DataError as e:
        print(f"jinja_raw_oracle: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
