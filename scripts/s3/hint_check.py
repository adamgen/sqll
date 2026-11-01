"""S3 T17: the check of the terminator hint exclusion.

greedy_match does not probe a terminator where its simple hint cannot match
(terminator_hint_excludes, match_algorithms.rs). This check builds sqll with
scripts/s3/hint-check.patch: the check build also runs each excluded probe,
counts it, and restores the parser limit state, so that its parse is that of
sqll. After the parse it writes one line to stderr:
"hint-check: exclusions=E probe_matches=M probe_limits=L".

The check runs the check build and the reference build (a fresh build of the
worktree, default out/sqll/bin/sqll) on the 2306 dialect fixtures and the 84
S2 parse inputs, with no option. It records the sums of E, M, and L, and
each run where the two builds give a different stdout, stderr (without the
hint-check line), or exit code. The exclusion is correct on the inputs if M
is 0 and no run differs. L counts the excluded probes that reach a parser
limit (depth, iterations, or nodes): on such an input the probe of the
source stops the parse, and sqll can give a tree (harness/sqll.md).

Command (from the repository root, about 10 minutes with 4 CPUs):

    uv run --frozen --project harness python scripts/s3/hint_check.py [--reference B]

It writes OUT_FILE. Exit code: 0 pass, 1 a probe match or a difference,
2 a usage or setup error.
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tree_guard  # noqa: E402
from sqll_harness import tools  # noqa: E402
from sqll_harness.adapters import sqll as sqll_adapter  # noqa: E402
from sqll_harness.paths import SQLFLUFF_ROOT  # noqa: E402

ROOT = tree_guard.ROOT
PATCH = ROOT / "scripts" / "s3" / "hint-check.patch"
OUT_FILE = ROOT / "results" / "s3" / "speed" / "T17-hint-check.json"
FIXTURES = SQLFLUFF_ROOT / "test" / "fixtures" / "dialects"
KIND = "sqll-s3-hint-check"
FIXTURE_COUNT = 2306
LINE = re.compile(
    r"^hint-check: exclusions=(\d+) probe_matches=(\d+) probe_limits=(\d+)$"
)


class CheckError(Exception):
    """The check cannot run: a setup or input error."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def build_check(scratch: Path) -> Path:
    """Build sqll from HEAD with the patch. Return the binary."""
    tree = scratch / "tree"
    git("worktree", "add", "--detach", "--force", str(tree), "HEAD")
    try:
        git("apply", str(PATCH), cwd=tree)
        env = dict(os.environ, CARGO_TARGET_DIR=str(scratch / "target"))
        env.setdefault("SQLL_TABLES_DIR", str(ROOT / "target" / "sqll-tables"))
        subprocess.run(
            ["cargo", "build", "--release", "--locked", "-p", "sqll"],
            cwd=tree,
            env=env,
            check=True,
        )
    finally:
        git("worktree", "remove", "--force", str(tree))
    return scratch / "target" / "release" / "sqll"


def cases(folder: Path) -> list[tuple[str, str, Path]]:
    """(name, dialect, file) of each fixture and S2 parse input."""
    out = [
        (f"fixture/{p.parent.name}/{p.stem}", p.parent.name, p)
        for p in sorted(FIXTURES.glob("*/*.sql"))
    ]
    if len(out) != FIXTURE_COUNT:
        raise CheckError(f"{len(out)} dialect fixtures, not {FIXTURE_COUNT}")
    for name in tree_guard.build_inputs(folder):
        out.append((f"input/{name}", name.split("/")[0], folder / f"{name}.sql"))
    return out


def run(binary: Path, dialect: str, sql: Path) -> subprocess.CompletedProcess:
    argv = tree_guard.sqll_argv(binary, dialect, str(sql), "default")
    return tree_guard.run_one(argv, sql.parent)


def check_one(check: Path, reference: Path, case: tuple[str, str, Path]) -> dict:
    name, dialect, sql = case
    got, want = run(check, dialect, sql), run(reference, dialect, sql)
    lines = got.stderr.decode("utf8", "replace").splitlines(keepends=True)
    counts = [LINE.match(line.rstrip("\n")) for line in lines]
    found = [m for m in counts if m]
    if len(found) != 1:
        raise CheckError(f"{name}: {len(found)} hint-check lines in stderr")
    stderr = "".join(line for line, m in zip(lines, counts) if not m)
    same = (
        got.stdout == want.stdout
        and stderr == want.stderr.decode("utf8", "replace")
        and got.returncode == want.returncode
    )
    e, m, limit = (int(g) for g in found[0].groups())
    return {"name": name, "exclusions": e, "matches": m, "limits": limit, "same": same}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hint_check.py")
    p.add_argument("--reference", type=Path, default=None)
    args = p.parse_args(argv)
    reference = (args.reference or sqll_adapter.binary_path()).resolve()
    try:
        info = tools.check_sqll(ROOT, ROOT, binary=reference)
        if info.errors:
            raise CheckError("; ".join(info.errors))
        with tempfile.TemporaryDirectory(prefix="sqll-hint-check-") as tmp:
            scratch = Path(tmp)
            check = build_check(scratch)
            jobs = cases(scratch / "inputs")
            with concurrent.futures.ThreadPoolExecutor(os.cpu_count() or 1) as ex:
                rows = list(ex.map(lambda c: check_one(check, reference, c), jobs))
    except (CheckError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    total = {k: sum(r[k] for r in rows) for k in ("exclusions", "matches", "limits")}
    record = {
        "kind": KIND,
        "commit": git("rev-parse", "HEAD").strip(),
        "patch_sha256": sha256(PATCH.read_bytes()),
        "reference_sha256": sha256(reference.read_bytes()),
        "options": [],
        "summary": {
            "inputs": len(rows),
            "fixtures": FIXTURE_COUNT,
            "parse_inputs": len(rows) - FIXTURE_COUNT,
            "exclusions": total["exclusions"],
            "probe_matches": total["matches"],
            "probe_limits": total["limits"],
            "different_runs": sum(not r["same"] for r in rows),
        },
        "matches": [r["name"] for r in rows if r["matches"]],
        "limits": [r["name"] for r in rows if r["limits"]],
        "different": [r["name"] for r in rows if not r["same"]],
    }
    OUT_FILE.write_text(json.dumps(record, indent=1) + "\n", encoding="utf8")
    s = record["summary"]
    print(
        f"hint check: {s['inputs']} inputs, {s['exclusions']} exclusions,"
        f" {s['probe_matches']} probe matches, {s['probe_limits']} probe limits,"
        f" {s['different_runs']} different runs"
    )
    return 1 if s["probe_matches"] or s["different_runs"] else 0


if __name__ == "__main__":
    sys.exit(main())
