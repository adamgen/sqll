"""python -m sqll_harness.corpus COMMAND (corpus/README.md).

validate [--manifest FILE]: read and validate the manifest.
fetch [--smoke] [--manifest FILE] [--cache DIR]: download the files of the
manifest (only the smoke files with --smoke) into the cache folder and
check their sha256.

Output: a JSON object on stdout. Exit code 2 if the manifest is not valid
or the fetch fails (the reason is on stderr).
"""

import argparse
import json
import sys
from pathlib import Path

from . import fetch as fetch_module
from .manifest import MANIFEST, ManifestError, load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sqll_harness.corpus")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "fetch"):
        sub = commands.add_parser(name)
        sub.add_argument("--manifest", type=Path, default=MANIFEST)
    fetch_parser = commands.choices["fetch"]
    fetch_parser.add_argument(
        "--smoke", action="store_true", help="Fetch only the smoke files."
    )
    fetch_parser.add_argument(
        "--cache",
        help=f"Default: ${fetch_module.CACHE_ENV}, else out/corpus/cache.",
    )
    args = parser.parse_args(argv)
    try:
        manifest = load(args.manifest)
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
    except fetch_module.FetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
