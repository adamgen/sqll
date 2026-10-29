"""python -m sqll_harness.corpus COMMAND (corpus/README.md).

validate [--manifest FILE]: read and validate the manifest.
fetch [--smoke] [--manifest FILE] [--cache DIR]: download the files of the
manifest (only the smoke files with --smoke) into the cache folder and
check their sha256.
run --profile smoke|full [--shard K/N] [--tool T ...] [--cache DIR] [--out
FILE]: fetch the files of the profile and shard, parse each with each tool,
and write the report.
merge REPORT... [--expect FILE] [--out FILE]: merge the shard reports.
check REPORT [--baseline FILE [--full]]: check the schema and completeness
of a report, and its stable data against the baseline.
tables REPORT: print the Markdown tables of a report for status/S9.md.
select [--sources FILE] [--cache DIR] [--download] [--check]: make the
manifest from the source list and the cache (--download first fills the
cache with git), and write it to --manifest, or with --check compare it with
--manifest.

validate and fetch write a JSON object on stdout. Exit code 2 if the
manifest is not valid, or if a fetch, run, or merge cannot start or
complete; 1 if a report has an error.
"""

import argparse
import dataclasses
import json
import sys
import tempfile
from pathlib import Path

from ..bench import registry
from ..bench import run as bench_run
from ..bench.definitions import REFERENCE_TOOL
from . import baseline as corpus_baseline
from . import fetch as fetch_module
from . import report as corpus_report
from . import run as corpus_run
from . import select as corpus_select
from . import tables as corpus_tables
from .manifest import JINJA, MANIFEST, ManifestError, load
from .reference import SqlfluffRender

# The reference render of templated files. A test can change it.
make_render = SqlfluffRender


def _shard(text: str) -> tuple[int, int]:
    try:
        return corpus_run.parse_shard(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sqll_harness.corpus")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "fetch", "run", "merge", "check", "select"):
        sub = commands.add_parser(name)
        sub.add_argument("--manifest", type=Path, default=MANIFEST)
    commands.add_parser("tables").add_argument("report", type=Path)
    cache_help = f"Default: ${fetch_module.CACHE_ENV}, else out/corpus/cache."
    fetch_parser = commands.choices["fetch"]
    fetch_parser.add_argument(
        "--smoke", action="store_true", help="Fetch only the smoke files."
    )
    fetch_parser.add_argument("--cache", help=cache_help)
    run_parser = commands.choices["run"]
    run_parser.add_argument(
        "--profile", required=True, choices=sorted(corpus_run.PROFILES)
    )
    run_parser.add_argument("--shard", type=_shard, help="K/N: shard K of N.")
    run_parser.add_argument(
        "--tool",
        action="append",
        choices=registry.names(),
        help="A tool of the bench registry (repeat it). Default: all.",
    )
    run_parser.add_argument("--cache", help=cache_help)
    run_parser.add_argument("--out", type=Path, default=corpus_report.DEFAULT_REPORT)
    merge_parser = commands.choices["merge"]
    merge_parser.add_argument("reports", nargs="+", type=Path)
    merge_parser.add_argument(
        "--expect", type=Path, help='The shard count file ({"shards": N}).'
    )
    merge_parser.add_argument("--out", type=Path, default=corpus_report.DEFAULT_REPORT)
    check_parser = commands.choices["check"]
    check_parser.add_argument("report", type=Path)
    check_parser.add_argument("--baseline", type=Path)
    check_parser.add_argument(
        "--full",
        action="store_true",
        help="Also need the profile and each result of the baseline.",
    )
    select_parser = commands.choices["select"]
    select_parser.add_argument(
        "--sources", type=Path, default=corpus_select.SOURCES, help="The source list."
    )
    select_parser.add_argument("--cache", help=cache_help)
    select_parser.add_argument(
        "--download",
        action="store_true",
        help="First read each source with git into the cache.",
    )
    select_parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write the manifest. Exit code 1 if it is not the same.",
    )
    return parser


def _error(text: str) -> int:
    print(f"error: {text}", file=sys.stderr)
    return 2


def run_command(args: argparse.Namespace, manifest) -> int:
    names = sorted(set(args.tool or registry.names()))
    selected = corpus_run.select(manifest, args.profile, args.shard)
    templated = any(f.templater == JINJA for f in selected)
    checks = sorted(set(names) | ({REFERENCE_TOOL} if templated else set()))
    errors = bench_run.check_tools(checks)
    for line in errors:
        print(f"error: {line}", file=sys.stderr)
    if errors:
        return _error("the tool check failed. Run: scripts/setup")
    adapters = [registry.get(n) for n in names]
    cache = fetch_module.cache_dir(args.cache)
    # Fetch only the files of the shard. The cache gets the whole manifest.
    part = dataclasses.replace(manifest, files=tuple(selected))
    fetched = fetch_module.fetch(part, cache, smoke=args.profile == corpus_run.SMOKE)
    print(
        f"parsing {len(selected)} files with {len(names)} tools "
        f"({args.profile} profile)",
        file=sys.stderr,
    )
    with tempfile.TemporaryDirectory(prefix="sqll-corpus-") as tmp:
        rep = corpus_run.run(
            manifest=manifest,
            files=fetched.files,
            adapters=adapters,
            profile=args.profile,
            shard=args.shard,
            work=Path(tmp),
            render=make_render() if templated else None,
            progress=corpus_run.progress_to_stderr,
        )
    try:
        corpus_report.write(rep, args.out)
    except corpus_report.ReportError as exc:
        print(f"error: the report has a schema error: {exc}", file=sys.stderr)
        return 1
    errors = corpus_run.incomplete(rep, manifest)
    lines = [*corpus_run.summary_lines(rep), f"report: {args.out}", *errors]
    if errors:
        lines.append("FAIL: the report is not complete for the profile and shard.")
    print("\n".join(lines))
    return 1 if errors else 0


def merge_command(args: argparse.Namespace, manifest) -> int:
    try:
        shards = corpus_run.expected_shards(args.expect) if args.expect else None
        reports = [(str(p), corpus_report.load(p)) for p in args.reports]
        rep = corpus_run.merge(reports, manifest, shards)
    except (OSError, ValueError, corpus_run.MergeError) as exc:
        return _error(str(exc))
    corpus_report.write(rep, args.out)
    lines = [f"merged {len(reports)} reports", *corpus_run.summary_lines(rep)]
    print("\n".join([*lines, f"report: {args.out}"]))
    return 0


def check_command(args: argparse.Namespace, manifest) -> int:
    if args.full and args.baseline is None:
        return _error("--full needs --baseline")
    try:
        rep = corpus_report.load(args.report)
        base = corpus_report.load(args.baseline) if args.baseline else None
    except (OSError, ValueError) as exc:
        return _error(str(exc))
    errors = corpus_report.check(rep)
    if not errors:
        errors = corpus_run.incomplete(rep, manifest)
    if base is not None and not errors:
        errors = [f"baseline: {e}" for e in corpus_baseline.recorded(base, manifest)]
        if not errors:
            errors = corpus_baseline.drift(rep, base)
            if args.full:
                errors += corpus_baseline.missing(rep, base)
    for line in errors:
        print(line)
    if errors:
        print(f"FAIL: {args.report} has {len(errors)} errors.")
        return 1
    print(f"{args.report}: no schema error; complete for its profile and shard.")
    if base is not None:
        print(
            f"The stable data of {len(rep['results'])} results is that of the "
            f"baseline {args.baseline}."
        )
    if args.full:
        print("The report has the profile and each result of the baseline.")
    return 0


def tables_command(args: argparse.Namespace) -> int:
    try:
        rep = corpus_report.load(args.report)
    except (OSError, ValueError) as exc:
        return _error(str(exc))
    errors = corpus_report.check(rep)
    if errors:
        for line in errors:
            print(line)
        print(f"FAIL: {args.report} has {len(errors)} errors.")
        return 1
    print(corpus_tables.markdown(rep), end="")
    return 0


def select_command(args: argparse.Namespace) -> int:
    try:
        specs = corpus_select.load_sources(args.sources)
        cache = fetch_module.cache_dir(args.cache)
        if args.download:
            corpus_select.download_all(specs, cache)
        text, summary = corpus_select.build(specs, cache)
    except corpus_select.SelectError as e:
        print("error: the selection failed:", file=sys.stderr)
        for line in e.errors:
            print(f"  {line}", file=sys.stderr)
        return 2
    except (ManifestError, fetch_module.FetchError) as e:
        return _error(str(e))
    out = {"sources_file": str(args.sources), "manifest": str(args.manifest)}
    status = 0
    if args.check:
        try:
            same = Path(args.manifest).read_bytes() == text
        except OSError:
            same = False
        out["same_as_manifest"] = same
        status = 0 if same else 1
    else:
        Path(args.manifest).write_bytes(text)
    print(json.dumps({**out, **summary}, indent=2))
    return status


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "select":
        return select_command(args)
    if args.command == "tables":
        return tables_command(args)
    try:
        manifest = load(args.manifest)
        if args.command == "run":
            return run_command(args, manifest)
        if args.command == "merge":
            return merge_command(args, manifest)
        if args.command == "check":
            return check_command(args, manifest)
        if args.command == "validate":
            out = {
                "manifest": str(args.manifest),
                "manifest_sha256": manifest.sha256,
                "sources": len(manifest.sources),
                "files": len(manifest.files),
                "smoke_files": len(manifest.selected(smoke=True)),
            }
        else:
            cache = fetch_module.cache_dir(args.cache)
            result = fetch_module.fetch(manifest, cache, smoke=args.smoke)
            out = {
                "manifest": str(args.manifest),
                **result.summary(manifest, args.smoke),
            }
    except ManifestError as e:
        print(f"error: the manifest {args.manifest} is not valid:", file=sys.stderr)
        for line in e.errors:
            print(f"  {line}", file=sys.stderr)
        return 2
    except (fetch_module.FetchError, corpus_run.RunError) as e:
        return _error(str(e))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
