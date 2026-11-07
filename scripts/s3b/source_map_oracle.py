"""S3b task C8: the sqlfluff answers for the source map
(docs/interfaces/source-map.md).

Run it with the harness Python from the repository root:

    uv run --frozen --project harness python scripts/s3b/source_map_oracle.py record
    uv run --frozen --project harness python scripts/s3b/source_map_oracle.py check

Both run the pinned sqlfluff of the tool venv (tools/sqlfluff, pure Python)
on the templater fixtures of the pinned sqlfluff (all_fixtures: each SQL
file directly in a folder of test/fixtures/templater/, and each file of
the case table of test/core/templaters/jinja_test.py), with the config of
the fixture folder and the dialect ansi if the config has none. For each
fixture the data are: the slices and the templated text that the
templater gives; for each templated range (i, j), 0 <= i <= j <= the
templated length, the result of templated_slice_to_source_slice and
is_source_slice_literal (no result for a ValueError); the source line and
position of each source offset; and each segment of the parse tree, in
pre-order (type, templated slice, source slice, is_literal, source line
and position). The offsets are code points. The data have no text of the
source file: the tests read the file.

record: write RECORD_FILE for RECORD_FIXTURES (the hand-built example of
crates/sqll_interfaces/tests/source_map.rs, a loop example, and the empty
dialect fixture, for which the Jinja templater gives no slices).

check (CI job build, scripts/verify): make the data of RECORD_FIXTURES
again; it must be the text of RECORD_FILE. Then make the data of each
fixture of all_fixtures into WORK/all.json (the submodule must stay
clean: the sqlfluff Python runs with -B, so it writes no bytecode), and
the data of RANDOM_FILES invented files (random_file, seed RANDOM_SEED:
multi-byte characters, CR and LF, parts of raw slices, overlapping and
empty source slices) into WORK/random.json. Then run the ignored tests
TEST and RANDOM_TEST of crates/sqll_interfaces/tests/source_map.rs on
them (cargo test --locked). The check fails unless the record agrees,
cargo exits with 0, both tests pass, and the output has both pass lines.

Exit code: 0 pass, 1 a failure.
"""

import argparse
import json
import os
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQLFLUFF_ROOT = ROOT / "third_party" / "sqlfluff"
RECORD_FILE = ROOT / "results" / "S3b" / "C8-source-map.json"
WORK = ROOT / "out" / "s3b" / "c8"
KIND = "sqll-s3b-c8-source-map"
FORMAT = 1
COMMAND = "uv run --frozen --project harness python scripts/s3b/source_map_oracle.py"
FIXTURE_DIR = "test/fixtures/templater"
# The empty file: the Jinja templater gives no slices for it.
RECORD_FIXTURES = (
    "test/fixtures/templater/jinja_a/jinja.sql",
    "test/fixtures/templater/jinja_b/jinja.sql",
    "test/fixtures/dialects/ansi/empty_file.sql",
)
# The count of all_fixtures (docs/interfaces/source-map.md, "Proof").
FIXTURES = 54
DEFAULT_DIALECT = "ansi"
TEST = "each_templater_fixture_maps_as_sqlfluff"
ORACLE_ENV = "SQLL_SOURCE_MAP_ORACLE"
PASS_PREFIX = "source map: "
PASS_SUFFIX = " templater fixtures: as sqlfluff"
RANDOM_TEST = "random_files_map_as_sqlfluff"
RANDOM_ENV = "SQLL_SOURCE_MAP_RANDOM"
RANDOM_KIND = "sqll-s3b-c8-source-map-random"
RANDOM_SUFFIX = " random files: as sqlfluff"
RANDOM_SEED = 8
RANDOM_FILES = 20000
# Characters of 1, 2, 3, and 4 UTF-8 bytes, CR, and LF.
RANDOM_CHARS = "ab \u00e9\u20ac\U0001f600\r\n"
RAW_TYPES = ("literal", "templated", "comment", "block_start")


class DataError(Exception):
    """A step failed, or the data do not agree."""


# The data, made with the sqlfluff Python (the "dump" command).


def fixture_data(rel: str) -> dict:
    """The data of one fixture (code point offsets)."""
    from sqlfluff.core import FluffConfig, Linter

    path = SQLFLUFF_ROOT / rel
    folder = str(path.parent)
    config = FluffConfig.from_path(folder, require_dialect=False)
    if not config.get("dialect"):
        config = FluffConfig.from_path(folder, overrides={"dialect": DEFAULT_DIALECT})
    source = path.read_text(encoding="utf8")
    parsed = Linter(config=config).parse_string(source, fname=str(path))
    if not parsed.parsed_variants:
        raise DataError(f"{rel}: the templater gave no file")
    variant = parsed.parsed_variants[0]
    tf = variant.templated_file
    if tf.source_str != source:
        raise DataError(f"{rel}: the source text is not the file text")
    segments = None
    if variant.tree is not None:
        segments = []
        for seg in variant.tree.recursive_crawl_all():
            pm = seg.pos_marker
            line, pos = pm.source_position()
            t, s = pm.templated_slice, pm.source_slice
            literal = int(pm.is_literal())
            segments.append(
                [seg.get_type(), t.start, t.stop, s.start, s.stop, literal, line, pos]
            )
    data = map_data(tf)
    return {
        "path": rel,
        "templater": config.get("templater"),
        "dialect": config.get("dialect"),
        "source_chars": len(source),
        "templated_str": tf.templated_str,
        "sliced_file": data["sliced_file"],
        "raw_sliced": data["raw_sliced"],
        "violations": sorted(str(v.desc()) for v in parsed.violations),
        "source_points": data["source_points"],
        "ranges": data["ranges"],
        "segments": segments,
    }


def map_data(tf) -> dict:
    """The slices of a TemplatedFile and its answers for each templated
    range and each source offset."""
    n = len(tf.templated_str)
    ranges = []
    for i in range(n + 1):
        for j in range(i, n + 1):
            try:
                s = tf.templated_slice_to_source_slice(slice(i, j))
            except ValueError:
                ranges.append([i, j])
                continue
            literal = int(tf.is_source_slice_literal(s))
            ranges.append([i, j, s.start, s.stop, literal])
    return {
        "sliced_file": [
            [s.slice_type, s.source_slice.start, s.source_slice.stop]
            + [s.templated_slice.start, s.templated_slice.stop]
            for s in tf.sliced_file
        ],
        "raw_sliced": [
            [r.slice_type, r.source_idx, r.block_idx, r.tag] for r in tf.raw_sliced
        ],
        "source_points": [
            list(tf.get_line_pos_of_char_pos(i, source=True))
            for i in range(len(tf.source_str) + 1)
        ],
        "ranges": ranges,
    }


def random_file(rng: random.Random):
    """An invented TemplatedFile that the sqll SourceMap accepts (as the
    generator of the unit test in crates/sqll_source/src/map.rs): raw
    slices of 0 to 5 characters of random types; then 1 to 6 templated
    slices. A literal slice takes a random part of one raw slice (two
    slices can take the same or overlapping parts), with its text or with
    no templated text. A templated slice takes a random source range (it
    can be empty) and gives 0 to 3 random characters."""
    from sqlfluff.core.templaters.base import (
        RawFileSlice,
        TemplatedFile,
        TemplatedFileSlice,
    )

    def text(most: int) -> str:
        return "".join(rng.choice(RANDOM_CHARS) for _ in range(rng.randint(0, most)))

    def part(start: int, n: int) -> slice:
        a = rng.randint(0, n)
        return slice(start + a, start + rng.randint(a, n))

    source, raws = "", []
    for _ in range(rng.randint(1, 6)):
        raw = text(5)
        raws.append(RawFileSlice(raw, rng.choice(RAW_TYPES), len(source)))
        source += raw
    templated, slices = "", []
    for _ in range(rng.randint(1, 6)):
        start = len(templated)
        kind = rng.randrange(3)
        if kind < 2:
            r = rng.choice(raws)
            o = part(r.source_idx, len(r.raw))
            if kind == 0:
                templated += source[o]
            slices.append(
                TemplatedFileSlice("literal", o, slice(start, len(templated)))
            )
        else:
            o = part(0, len(source))
            templated += text(3)
            slices.append(
                TemplatedFileSlice("templated", o, slice(start, len(templated)))
            )
    return TemplatedFile(source, "random.sql", templated, slices, raws)


def dump_random(seed: int, count: int) -> dict:
    """The data of count random files (with their texts: they are not
    sqlfluff data)."""
    import sqlfluff

    rng = random.Random(seed)
    files = []
    for _ in range(count):
        tf = random_file(rng)
        files.append(
            {"source_str": tf.source_str, "templated_str": tf.templated_str}
            | map_data(tf)
        )
    return {
        "kind": RANDOM_KIND,
        "sqlfluff": {"version": sqlfluff.__version__},
        "seed": seed,
        "files": files,
    }


def dump(fixtures: list[str]) -> dict:
    import sqlfluff

    return {
        "sqlfluff": sqlfluff.__version__,
        "fixtures": [fixture_data(rel) for rel in fixtures],
    }


# The commands of the harness Python.


def sqlfluff_python() -> Path:
    sys.path.insert(0, str(ROOT / "harness"))
    from sqll_harness.paths import tools_dir

    python = tools_dir() / "sqlfluff" / "bin" / "python"
    if not python.is_file():
        raise DataError(f"no sqlfluff Python at {python} (scripts/setup)")
    return python


def run_sqlfluff(args: list[str]) -> dict:
    argv = [str(sqlfluff_python()), "-I", "-B", str(Path(__file__).resolve())]
    argv += args
    print(f"source_map_oracle: $ {' '.join(argv[:5])} ...", flush=True)
    out = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=False)
    if out.returncode != 0:
        raise DataError(f"{args[0]}: exit code {out.returncode}\n{out.stderr[-4000:]}")
    return json.loads(out.stdout)


def run_dump(fixtures: list[str]) -> dict:
    print(f"source_map_oracle: the data of {len(fixtures)} fixtures")
    return run_sqlfluff(["dump"] + fixtures)


def all_fixtures() -> list[str]:
    """Each SQL file directly in a fixture folder, and each SQL file of the
    case table of the sqlfluff Jinja test (it has fixtures in subfolders).
    A recursive search would also find the macro and loader files."""
    sys.path.insert(0, str(ROOT / "harness"))
    from sqll_harness.suites.templater import TEST_FILE, read_table

    folder = SQLFLUFF_ROOT / FIXTURE_DIR
    paths = set(folder.glob("*/*.sql"))
    for subpath, _, _ in read_table(SQLFLUFF_ROOT / TEST_FILE):
        path = folder / f"{subpath}.sql"
        if not path.is_file():
            raise DataError(f"no fixture file {path.relative_to(SQLFLUFF_ROOT)}")
        paths.add(path)
    return [p.relative_to(SQLFLUFF_ROOT).as_posix() for p in sorted(paths)]


def submodule_commit() -> str:
    out = subprocess.run(
        ["git", "-C", str(SQLFLUFF_ROOT), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    return out.stdout.strip()


def record_data(data: dict) -> dict:
    return {
        "kind": KIND,
        "format": FORMAT,
        "about": (
            "S3b C8: the answers of the pinned sqlfluff TemplatedFile for the "
            "source map, for two templater fixtures and the empty dialect fixture "
            "(scripts/s3b/source_map_oracle.py; docs/interfaces/source-map.md). "
            "Offsets are code points. ranges: [i, j, source start, source stop, "
            "is_source_slice_literal] for the templated slice i..j, or [i, j] for "
            "a ValueError. segments: [type, templated start, templated stop, "
            "source start, source stop, is_literal, source line, source position] "
            "in pre-order."
        ),
        "command": f"{COMMAND} record",
        "sqlfluff": {"version": data["sqlfluff"], "commit": submodule_commit()},
        "fixtures": data["fixtures"],
    }


def dumps(record: dict) -> str:
    """JSON with one line for each list item of a fixture."""
    lines = ["{"]
    keys = list(record)
    for k, key in enumerate(keys):
        end = "," if k < len(keys) - 1 else ""
        if key != "fixtures":
            lines.append(f" {json.dumps(key)}: {json.dumps(record[key])}{end}")
            continue
        lines.append(' "fixtures": [')
        for f, fixture in enumerate(record["fixtures"]):
            lines.append("  {")
            fkeys = list(fixture)
            for i, fkey in enumerate(fkeys):
                fend = "," if i < len(fkeys) - 1 else ""
                value = fixture[fkey]
                if isinstance(value, list) and value and isinstance(value[0], list):
                    lines.append(f"   {json.dumps(fkey)}: [")
                    for v, item in enumerate(value):
                        vend = "," if v < len(value) - 1 else ""
                        lines.append(f"    {json.dumps(item)}{vend}")
                    lines.append(f"   ]{fend}")
                else:
                    lines.append(f"   {json.dumps(fkey)}: {json.dumps(value)}{fend}")
            lines.append("  }" + ("," if f < len(record["fixtures"]) - 1 else ""))
        lines.append(" ]" + end)
    lines.append("}")
    return "\n".join(lines) + "\n"


def record() -> int:
    data = run_dump(list(RECORD_FIXTURES))
    RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECORD_FILE.write_text(dumps(record_data(data)), encoding="utf8")
    print(f"source_map_oracle: wrote {RECORD_FILE.relative_to(ROOT)}")
    return 0


def pass_line(fixtures: int) -> str:
    return f"{PASS_PREFIX}{fixtures} of {fixtures}{PASS_SUFFIX}"


def random_pass_line(files: int) -> str:
    return f"{PASS_PREFIX}{files} of {files}{RANDOM_SUFFIX}"


def check_output(code: int, output: str, fixtures: int, files: int) -> list[str]:
    """Each problem of the cargo test run."""
    problems = []
    if code != 0:
        problems.append(f"cargo test: exit code {code}")
    for test in (TEST, RANDOM_TEST):
        if f"test {test} ... ok" not in output:
            problems.append(f"the test {test} did not pass")
    if "test result: ok. 2 passed;" not in output:
        problems.append("cargo did not run exactly 2 passing tests")
    for line in (pass_line(fixtures), random_pass_line(files)):
        if line not in output:
            problems.append(f"no line {line!r}")
    return problems


def check() -> int:
    problems = []
    want = dumps(record_data(run_dump(list(RECORD_FIXTURES))))
    if not RECORD_FILE.is_file() or RECORD_FILE.read_text(encoding="utf8") != want:
        problems.append(
            f"{RECORD_FILE.relative_to(ROOT)} is not the sqlfluff data ({COMMAND} record)"
        )
    fixtures = all_fixtures()
    if len(fixtures) != FIXTURES:
        problems.append(f"{len(fixtures)} templater fixtures, not {FIXTURES}")
    data = run_dump(fixtures)
    clean = subprocess.run(
        [str(ROOT / "scripts" / "check-submodule"), "after the sqlfluff data"],
        check=False,
    )
    if clean.returncode != 0:
        problems.append("the sqlfluff run changed the submodule")
    print(f"source_map_oracle: the data of {RANDOM_FILES} random files")
    random_data = run_sqlfluff(["random", str(RANDOM_SEED), str(RANDOM_FILES)])
    WORK.mkdir(parents=True, exist_ok=True)
    oracle = WORK / "all.json"
    oracle.write_text(json.dumps(record_data(data)), encoding="utf8")
    random_file_path = WORK / "random.json"
    random_file_path.write_text(json.dumps(random_data), encoding="utf8")
    env = {
        k: v for k, v in os.environ.items() if k not in ("RUST_LOG", "CARGO_TERM_COLOR")
    }
    env["CARGO_TERM_COLOR"] = "never"
    env[ORACLE_ENV] = str(oracle)
    env[RANDOM_ENV] = str(random_file_path)
    argv = ["cargo", "test", "--locked", "-p", "sqll_interfaces", "--test"]
    argv += ["source_map", "--", "--ignored", "--exact", TEST, RANDOM_TEST]
    argv += ["--nocapture"]
    print("source_map_oracle: $ " + " ".join(argv), flush=True)
    proc = subprocess.run(
        argv,
        cwd=ROOT,
        env=env,
        text=True,
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    sys.stdout.write(proc.stdout)
    problems += check_output(proc.returncode, proc.stdout, len(fixtures), RANDOM_FILES)
    for p in problems:
        print(f"source map check: {p}")
    if problems:
        print(f"source map check: FAIL: {len(problems)} problems")
        return 1
    print(
        f"source map check: PASS: {pass_line(len(fixtures))}; "
        f"{random_pass_line(RANDOM_FILES)}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("record", help="write the record file")
    sub.add_parser("check", help="check the record and each templater fixture")
    d = sub.add_parser("dump", help="(sqlfluff Python) print the data as JSON")
    d.add_argument("fixtures", nargs="+")
    r = sub.add_parser("random", help="(sqlfluff Python) the data of random files")
    r.add_argument("seed", type=int)
    r.add_argument("count", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "dump":
            json.dump(dump(args.fixtures), sys.stdout)
            return 0
        if args.command == "random":
            json.dump(dump_random(args.seed, args.count), sys.stdout)
            return 0
        if args.command == "record":
            return record()
        return check()
    except DataError as e:
        print(f"source_map_oracle: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
