"""The corpus parse run, the shard merge, and the completeness check
(docs/decisions/s9-corpus.md, "Parse check and report", "Profiles").

For each selected file of the manifest, each tool of the bench registry
parses the file through its S2 benchmark adapter (config, argv, env, and
tree reader), with the corpus settings. The S2 timer runs the tools in turn
(timer.run_in_turn): 1 warmup run, which is the check run, then the timed
runs of the profile. The check of the warmup run gives the status:

- ok: exit code 0, a tree, no unparsable segment, and the leaf text is the
  input (or, for a templated file, the render of the pinned sqlfluff).
- unparsable: as ok, but the tree has unparsable segments (exit code 0 or
  1). The result has their count and bytes.
- no_reference: a templated file with no sqlfluff render. The leaf text is
  not compared, so no tool gets ok on it.
- invalid: a crash, a panic, a timeout, no tree, a leaf text that is not
  the input, or another exit code.
- unsupported: the adapter refuses a setting (for example the dialect).
- error: the harness cannot run or check the tool.

A file of the manifest is in shard i % N + 1, where i is its index (from 0)
in the files of the profile. No code here knows a tool name, except the
corpus layer of a tool (TOOL_LAYERS). Thus a new tool needs only its bench
registry entry.
"""

import hashlib
import re
import shutil
import sys
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import paths
from ..adapters.base import Unsupported
from ..adapters.sqruff_config import nested_combine
from ..bench import report as bench_report
from ..bench import run as bench_run
from ..bench import timer
from ..bench.adapter import BenchAdapter, config_files_above, find_problem
from ..bench.adapter import settings as bench_settings
from ..bench.timer import Job, Measurement, Policy, Run, Series, overhead, run_in_turn
from . import report
from .manifest import JINJA, MIN_BYTES, CorpusFile, Manifest
from .reference import Render

# docs/decisions/s9-corpus.md, "Profiles".
PROFILES = {
    "smoke": Policy(min_runs=1, max_runs=1, budget_s=0.0, timeout_s=1200.0),
    "full": Policy(min_runs=1, max_runs=5, budget_s=10.0, timeout_s=1200.0),
}
SMOKE = "smoke"
PARSE = "parse"
INPUT_FILE = "input.sql"
CONFIG_DIR = "config"
RUNS_DIR = "runs"
REFERENCE_DIR = "_reference"
REASON_TEXT = 300
# docs/decisions/s9-corpus.md, "Settings": the corpus layer of a tool, on
# top of its S2 layer. Only the sqlfluff-rs layer has the Rust iteration
# limit.
RUST_ITERATIONS = 1_000_000_000_000
TOOL_LAYERS: dict[str, dict[str, Any]] = {
    "sqlfluff-rs": {"core": {"rust_parser_max_iterations": RUST_ITERATIONS}},
}
# docs/decisions/s9-corpus.md, "Templated files": the render settings. The
# dbt builtins, and no template variable, macro path, or library path: the
# selection takes only files that need nothing more (jinja_names.py).
JINJA_SETTINGS: dict[str, Any] = {"templater": {"jinja": {"apply_dbt_builtins": True}}}
_NEWLINES = re.compile(r"\r\n|\r")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
BOM = "\ufeff"


class RunError(Exception):
    """The run cannot start."""


class MergeError(Exception):
    """The reports cannot be merged into a correct report."""


# Settings.


def settings(templater: str) -> dict[str, Any]:
    """Return the corpus settings of all tools: the S2 settings, the
    templater of the file, and no parse node limit. A templated file also
    gets the render settings (JINJA_SETTINGS)."""
    s = bench_settings()
    s["core"]["templater"] = templater
    s["core"]["max_parse_nodes"] = 0
    if templater == JINJA:
        s = nested_combine(s, deepcopy(JINJA_SETTINGS))
    return s


def tool_config(adapter: BenchAdapter, templater: str, dialect: str | None) -> dict:
    """Return the settings that the tool gets for a file, in the sqlfluff
    config structure: the corpus settings, the S2 layer of the tool, and its
    corpus layer. With dialect None: the record for the report."""
    base = settings(templater)
    if dialect is not None:
        base["core"] = {"dialect": dialect, **base["core"]}
    return nested_combine(adapter.layer(base), deepcopy(TOOL_LAYERS.get(adapter.name)))


def tool_record(adapter: BenchAdapter) -> dict:
    return {
        "version": adapter.version(),
        "settings": {t: tool_config(adapter, t, None) for t in sorted(MIN_BYTES)},
    }


# The parse check.


def normalize(text: str) -> str:
    """Remove a first byte order mark and make each line end a \\n. The
    pinned sqlfluff does both before it lexes; sqlfluff[rs] and sqruff
    change the line ends too (measured)."""
    return _NEWLINES.sub("\n", text.removeprefix(BOM))


def tree_facts(record: Any) -> tuple[str, int, int]:
    """Return the leaf text of a tree record ({"file": ...}), the count of
    unparsable segments that are not in another unparsable segment, and the
    UTF-8 bytes of their text. ValueError if it is not a tree record. The
    walk is not recursive, so a deep tree cannot stop it."""
    parts: list[str] = []
    count = size = 0
    stack = [(k, v, False) for k, v in reversed(_items(record, "the tree"))]
    while stack:
        key, value, inside = stack.pop()
        if key == "unparsable" and not inside:
            count += 1
            inside = True
        if isinstance(value, str):
            parts.append(value)
            if inside:
                size += len(value.encode("utf8"))
        elif value is not None:
            stack.extend((k, v, inside) for k, v in reversed(_items(value, key)))
    return "".join(parts), count, size


def _items(value: Any, key: str) -> list[tuple[str, Any]]:
    """Return the (type, value) pairs of the children of a segment value: an
    object of segments, or a list of objects with one segment each."""
    if isinstance(value, dict):
        pairs = list(value.items())
    elif isinstance(value, list):
        pairs = []
        for item in value:
            if not isinstance(item, dict) or len(item) != 1:
                raise ValueError(f"segment {key!r}: a child is not one segment")
            pairs += item.items()
    else:
        raise ValueError(f"segment {key!r} has a {type(value).__name__}")
    for k, _ in pairs:
        if not isinstance(k, str):
            raise ValueError(f"segment type {k!r} is not a string")
    return pairs


@dataclass
class Found:
    """What the check of the warmup run found."""

    status: str | None = None
    unparsable: dict | None = None


def check_run(
    adapter: BenchAdapter, run: Run, expected: str | None, what: str
) -> tuple[str | None, Found | None]:
    """Return (reason, found) for the warmup run. reason is None if the run
    gives a complete tree: then found has the status ok or unparsable.
    expected: the leaf text that the tree must have (what names it), or None
    if there is no reference."""
    text = _ANSI.sub("", run.stderr.read_bytes().decode("utf8", errors="replace"))
    problem = find_problem(adapter, text)
    if problem:
        return problem, None
    code = run.sample.exit_code
    try:
        record = adapter.read_tree(run.stdout.read_bytes(), INPUT_FILE)
        if record is None:
            return f"no parse tree (exit code {code})", None
        leaf_text, count, size = tree_facts(record)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return f"no parse tree (exit code {code}): {exc!r}"[:REASON_TEXT], None
    if expected is not None:
        got, want = normalize(leaf_text), normalize(expected)
        if got != want:
            return (
                f"the tree text ({len(got)} characters) is not the {what} "
                f"({len(want)} characters)"
            ), None
    if count == 0 and code != 0:
        return f"exit code {code}, but the tree has no unparsable segment", None
    found = Found(
        report.OK if count == 0 else report.UNPARSABLE,
        {"count": count, "bytes": size},
    )
    return None, found


# The jobs of one file.


@dataclass
class FileJob:
    """The parse of one file by one tool. If job is None, the tool does not
    run: status (unsupported or error) and reason say why."""

    tool: str
    folder: Path
    job: Job | None = None
    status: str | None = None
    reason: str | None = None
    found: Found | None = None


def file_job(
    adapter: BenchAdapter,
    entry: CorpusFile,
    data: bytes,
    expected: str | None,
    folder: Path,
) -> FileJob:
    fj = FileJob(adapter.name, folder)
    try:
        config = tool_config(adapter, entry.templater, entry.dialect)
        item = adapter.unsupported(config)
        if item is not None:
            fj.status, fj.reason = report.UNSUPPORTED, f"unsupported: {item}"
            return fj
        if folder.exists():
            shutil.rmtree(folder)
        config_file = adapter.write_config(config, folder / CONFIG_DIR)
        argv = adapter.argv(PARSE, config_file, INPUT_FILE)
        env = adapter.env()
    except Unsupported as exc:
        fj.status, fj.reason = report.UNSUPPORTED, f"unsupported: {exc.item}"
        return fj
    except Exception as exc:  # noqa: BLE001 - one tool must not stop the others.
        fj.status, fj.reason = report.ERROR, f"harness error: {exc!r}"
        return fj
    what = "input" if entry.templater != JINJA else "render of the pinned sqlfluff"

    def prepare(run_folder: Path) -> None:
        (run_folder / INPUT_FILE).write_bytes(data)

    def check(run: Run) -> str | None:
        reason, fj.found = check_run(adapter, run, expected, what)
        return reason

    fj.job = Job(
        argv=argv,
        expected_exits=frozenset(report.PARSE_EXITS),
        env=env,
        prepare=prepare,
        check=check,
    )
    return fj


def _status(
    adapter: BenchAdapter, fj: FileJob, m: Measurement, no_reference: str | None
) -> tuple[str, str | None]:
    """Return the report status and reason of a measured file job."""
    if m.status == timer.VALID:
        found = fj.found
        if no_reference is not None:
            return report.NO_REFERENCE, f"no reference: {no_reference}"
        if found.status == report.OK:
            return report.OK, None
        u = found.unparsable
        return report.UNPARSABLE, (
            f"{u['count']} unparsable segments ({u['bytes']} bytes)"
        )
    if m.status == timer.INVALID:
        reason = m.reason or "invalid"
        warmup = m.warmup
        if warmup is not None and warmup.sample.exit_code not in report.PARSE_EXITS:
            # The check did not run: give the crash or panic message.
            try:
                text = warmup.stderr.read_bytes().decode("utf8", errors="replace")
            except OSError:
                text = ""
            problem = find_problem(adapter, _ANSI.sub("", text))
            if problem:
                reason = f"{problem}; {reason}"
        return report.INVALID, reason[: 2 * REASON_TEXT]
    if m.status == timer.UNSUPPORTED:
        return report.UNSUPPORTED, m.reason
    assert m.status == timer.ERROR, m.status
    return report.ERROR, m.reason


def measure_file(
    entry: CorpusFile,
    data: bytes,
    adapters: list[BenchAdapter],
    policy: Policy,
    folder: Path,
    expected: str | None,
    no_reference: str | None,
) -> list[dict]:
    """Parse one file with each tool; the tools run in turn. Return one
    result entry for each tool."""
    jobs = [(a, file_job(a, entry, data, expected, folder / a.name)) for a in adapters]
    runnable = [(a, fj) for a, fj in jobs if fj.job is not None]
    measured = run_in_turn(
        [Series(fj.job, policy, fj.folder / RUNS_DIR) for _, fj in runnable]
    )
    by_tool = {fj.tool: m for (_, fj), m in zip(runnable, measured, strict=True)}
    out = []
    for adapter, fj in jobs:
        m = by_tool.get(fj.tool)
        if m is None:
            m = Measurement(fj.status, fj.reason, [], None)
            status, reason = fj.status, fj.reason
        else:
            status, reason = _status(adapter, fj, m, no_reference)
        unparsable = fj.found.unparsable if fj.found else None
        out.append(
            report.result_entry(
                entry.id, entry.bytes, fj.tool, status, reason, m, unparsable
            )
        )
    return out


# The plan.


def parse_shard(text: str | None) -> tuple[int, int] | None:
    return bench_run.parse_shard(text)


def select(
    manifest: Manifest, profile: str, shard: tuple[int, int] | None
) -> list[CorpusFile]:
    """Return the files of the profile in the shard, in manifest order."""
    files = manifest.selected(smoke=profile == SMOKE)
    if shard is None:
        return files
    k, n = shard
    return [f for i, f in enumerate(files) if i % n + 1 == k]


def scope(tools: list[str], shard: tuple[int, int] | None) -> dict:
    return {
        "tools": sorted(set(tools)),
        "shard": f"{shard[0]}/{shard[1]}" if shard else None,
    }


def reference_config(entry: CorpusFile) -> dict:
    """Return the settings of the reference render of a file."""
    config = settings(entry.templater)
    config["core"] = {"dialect": entry.dialect, **config["core"]}
    return config


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(
    *,
    manifest: Manifest,
    files: Mapping[str, Path],
    adapters: list[BenchAdapter],
    profile: str,
    shard: tuple[int, int] | None,
    work: Path,
    render: Render | None,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Parse the files of the profile and shard with each tool, and return
    the report. files: the local path of each file (from the fetch).
    render: the reference render of templated files (reference.py).
    RunError if a tool can read a config file above work, if a file is
    missing or not that of the manifest, or if a templated file has no
    render function."""
    work = Path(work).absolute()
    found = config_files_above(work)
    if found:
        raise RunError(
            f"a tool can read these config files above the work folder {work}: "
            + ", ".join(f"{p} ({why})" for p, why in found)
        )
    policy = PROFILES[profile]
    adapters = sorted(adapters, key=lambda a: a.name)
    selected = select(manifest, profile, shard)
    if render is None and any(f.templater == JINJA for f in selected):
        raise RunError("a templated file needs the reference render")
    timer_entry = overhead(work / "overhead")
    inputs: dict[str, dict] = {}
    results: list[dict] = []
    for i, entry in enumerate(selected):
        path = files.get(entry.id)
        if path is None:
            raise RunError(f"{entry.id}: not fetched")
        data = Path(path).read_bytes()
        if len(data) != entry.bytes or _sha256(data) != entry.sha256:
            raise RunError(f"{entry.id}: {path} is not the file of the manifest")
        folder = work / "files" / str(i)
        expected, no_reference, ref = data.decode("utf8"), None, None
        try:
            if entry.templater == JINJA:
                expected, no_reference = render(
                    entry, data, reference_config(entry), folder / REFERENCE_DIR
                )
                sha = None if expected is None else _sha256(expected.encode("utf8"))
                ref = report.reference_record(sha, no_reference)
            entries = measure_file(
                entry, data, adapters, policy, folder, expected, no_reference
            )
        except Exception as exc:  # noqa: BLE001 - one file must not stop the run.
            reason = f"harness error: {exc!r}"
            if entry.templater == JINJA and ref is None:
                ref = report.reference_record(None, reason)
            m = Measurement(timer.ERROR, reason, [], None)
            entries = [
                report.result_entry(
                    entry.id, entry.bytes, a.name, report.ERROR, reason, m, None
                )
                for a in adapters
            ]
        inputs[entry.id] = report.input_record(entry, ref)
        shutil.rmtree(folder, ignore_errors=True)
        results += entries
        if progress:
            progress(f"[{i + 1}/{len(selected)}] {entry.id}: " + _brief(entries))
    return report.build(
        sqlfluff_ref=paths.sqlfluff_ref(paths.SQLFLUFF_ROOT),
        profile=profile,
        policy=policy.as_dict(),
        machine=bench_report.machine(),
        harness=bench_report.harness(),
        timer=timer_entry,
        manifest_sha256=manifest.sha256,
        scope=scope([a.name for a in adapters], shard),
        tools={a.name: tool_record(a) for a in adapters},
        inputs=inputs,
        results=results,
    )


def _brief(entries: list[dict]) -> str:
    parts = []
    for r in entries:
        cell = f"{r['tool']} {r['status']}"
        if r["stats"] is not None:
            cell += f" {r['stats']['wall_s']['median']:.3f} s"
        parts.append(cell)
    return ", ".join(parts)


# Completeness.


def incomplete(rep: Mapping[str, Any], manifest: Manifest) -> list[str]:
    """Return each error of completeness: the report must be of this
    manifest, have the record of each file of its profile and shard (and no
    other), and one result for each of these files and each tool. Call it on
    a report with no schema error."""
    errors = []
    if rep["manifest_sha256"] != manifest.sha256:
        errors.append(
            f"manifest_sha256 {rep['manifest_sha256']} is not that of the "
            f"manifest ({manifest.sha256})"
        )
        return errors
    want = select(manifest, rep["profile"], parse_shard(rep["scope"]["shard"]))
    ids = [f.id for f in want]
    have = set(rep["inputs"])
    if have != set(ids):
        errors.append(
            f"inputs: missing {few(sorted(set(ids) - have))}, "
            f"extra {few(sorted(have - set(ids)))}"
        )
    for entry in want:
        record = rep["inputs"].get(entry.id)
        if record is None:
            continue
        mine = report.input_record(entry, record["reference"])
        if record != mine:
            errors.append(f"input {entry.id}: not the record of the manifest")
    for tool in rep["scope"]["tools"]:
        got = sorted(r["file"] for r in rep["results"] if r["tool"] == tool)
        if got != sorted(ids):
            missing = sorted(set(ids) - set(got))
            extra = sorted(set(got) - set(ids))
            errors.append(f"{tool}: no result for {few(missing)}; extra {few(extra)}")
    return errors


def few(items: list[str], n: int = 5) -> str:
    return bench_run.few(items, n) if items else "none"


# Merge.


def _without_shard(scope: Mapping[str, Any]) -> dict:
    return {**scope, "shard": None}


def expected_shards(path: Path) -> int:
    """Return the shard count of a file {"shards": N}."""
    return bench_run.expected_shards(path)


def merge(
    reports: list[tuple[str, dict]], manifest: Manifest, shards: int | None = None
) -> dict:
    """Merge (name, report) pairs of the shard runs of one run. MergeError if
    a report has a schema error or is not complete, if a shard is missing or
    repeated, if the shard count is not `shards` (if it is given), or if 2
    reports have another run record (sqlfluff ref, harness, profile,
    manifest, scope, or a tool)."""
    if not reports:
        raise MergeError("no reports to merge")
    for name, rep in reports:
        errors = report.check(rep)
        if errors:
            raise MergeError(f"{name}: schema error: {'; '.join(errors[:3])}")
        if rep["parts"] is not None:
            raise MergeError(f"{name}: a merged report cannot be merged again")
        errors = incomplete(rep, manifest)
        if errors:
            raise MergeError(f"{name}: not complete: {'; '.join(errors[:3])}")
    first_name, first = reports[0]
    for name, rep in reports[1:]:
        for key in ("sqlfluff_ref", "harness", "profile", "policy", "manifest_sha256"):
            if rep[key] != first[key]:
                raise MergeError(f"{name}: {key} differs from {first_name}")
        if _without_shard(rep["scope"]) != _without_shard(first["scope"]):
            raise MergeError(f"{name}: the scope differs from {first_name}")
        if rep["tools"] != first["tools"]:
            raise MergeError(f"{name}: the tool records differ from {first_name}")
    seen: dict[int, tuple[str, dict]] = {}
    counts = set()
    for name, rep in reports:
        k, n = parse_shard(rep["scope"]["shard"]) or (1, 1)
        counts.add(n)
        if k in seen:
            raise MergeError(f"shard {k}/{n} is in {seen[k][0]} and {name}")
        seen[k] = (name, rep)
    if len(counts) != 1:
        raise MergeError(f"the reports have different shard counts: {sorted(counts)}")
    n = counts.pop()
    if shards is not None and n != shards:
        raise MergeError(f"the reports have {n} shards, not the expected {shards}")
    missing = [f"{k}/{n}" for k in range(1, n + 1) if k not in seen]
    if missing:
        raise MergeError(f"no report for shard {', '.join(missing)}")
    inputs: dict[str, dict] = {}
    results: list[dict] = []
    parts = []
    for k in range(1, n + 1):
        name, rep = seen[k]
        inputs.update(rep["inputs"])
        results += rep["results"]
        parts.append(
            {"shard": f"{k}/{n}", "machine": rep["machine"], "timer": rep["timer"]}
        )
    merged = report.build(
        sqlfluff_ref=first["sqlfluff_ref"],
        profile=first["profile"],
        policy=first["policy"],
        machine=parts[0]["machine"],
        harness=first["harness"],
        timer=parts[0]["timer"],
        manifest_sha256=first["manifest_sha256"],
        scope=_without_shard(first["scope"]),
        tools=first["tools"],
        inputs=inputs,
        results=results,
        parts=parts,
    )
    errors = report.check(merged) or incomplete(merged, manifest)
    if errors:
        raise MergeError(f"the merged report is not correct: {'; '.join(errors[:3])}")
    return merged


# Text summary.


def summary_lines(rep: Mapping[str, Any]) -> list[str]:
    """Return a short text summary of a report."""
    tools = list(rep["tools"])
    shard = rep["scope"]["shard"]
    lines = [
        f"profile {rep['profile']}: {len(rep['inputs'])} files, {len(tools)} tools"
        + (f", shard {shard}" if shard else "")
        + (f", {len(rep['parts'])} parts" if rep["parts"] else "")
    ]
    width = max([len(t) for t in tools] + [4])
    lines.append(
        f"{'tool':<{width}}  {'version':<10}"
        + "".join(f"{s:>14}" for s in report.STATUSES)
    )
    for tool in tools:
        counts = rep["totals"][tool]
        lines.append(
            f"{tool:<{width}}  {rep['tools'][tool]['version']:<10}"
            + "".join(f"{counts[s]:>14}" for s in report.STATUSES)
        )
    c = rep["compared"]
    lines.append(
        f"compared: {c['files']} files where each tool is ok, {c['bytes']} bytes"
    )
    for tool, t in c["results"].items():
        rate = "-" if t["bytes_per_s"] is None else f"{t['bytes_per_s']:.0f} B/s"
        ratio = "-" if t["wall_ratio"] is None else f"{t['wall_ratio']:.3f}"
        lines.append(
            f"  {tool:<{width}} wall {t['wall_s']:.3f} s, cpu {t['cpu_s']:.3f} s, "
            f"{rate}, wall ratio to {report.RATIO_BASE} {ratio}"
        )
    bad = [r for r in rep["results"] if r["status"] != report.OK]
    if bad:
        lines.append(f"not ok: {len(bad)}")
        for r in bad:
            reason = (r["reason"] or "").replace("\n", " ")
            if len(reason) > 160:
                reason = reason[:157] + "..."
            lines.append(f"  {r['tool']} {r['file']}: {r['status']}: {reason}")
    return lines


def progress_to_stderr(line: str) -> None:
    print(line, file=sys.stderr, flush=True)
