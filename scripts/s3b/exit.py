"""S3b (Core: the shared syntax tree, source map, frozen interfaces, and the
sqll binary skeleton), task C17 (S3b exit: proof, exit record, and the
request for approval): the data of the S3b exit record
(docs/decisions/s3b-exit.md).

One command. Run it with the harness Python:

    uv run --frozen --project harness python scripts/s3b/exit.py [--check]

It reads only committed files (INPUTS): the S1 summary, the record of the
CI run on the exit head (results/S3b/exit-ci.json: the job results and the
log lines of the checks, copied from the GitHub job logs), the C17 speed
check (results/S3b/speed/C17.json), the interface index, and tracks.yml.
For the S1 summary, the interface index, and tracks.yml it reads byte
copies (FROZEN, results/S3b/exit-inputs/), because later stones change the
live files. Without --check, each copy must be equal to its live file.

It also runs the ownership probe: in a new git repository with the
tracks.yml of the copy, a pull request of each track other than core
(TRACKS) changes one Core path (an interface, a Cargo.toml, a build.rs, Cargo.lock), and
ci/ownership.py runs on the merge commit, without and with the label
"cross-track". A change of a status file of the track is the control.
--check runs the probe again on the copy and on the live tracks.yml: both
must give the recorded lines.

It writes OUT_FILE. With --check it writes nothing and fails if OUT_FILE is
not the new text. It runs no benchmark and no CI job.

Each value has an id, the value, and the text that the exit record shows.
A value is "copied" ("from" and "key" name the file and the key), "line"
(a line of a CI job log in the CI record), or "derived" (a "formula" over
other values). A key part in brackets selects one item of a list by its
fields: "jobs[name=build]".

It stops with exit code 1 (DataError) if a key is missing or if the inputs
do not agree (for example, another head in the CI record and the speed
check).
"""

import argparse
import copy
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_FILE = ROOT / "results" / "S3b" / "exit.json"
COMMAND = "uv run --frozen --project harness python scripts/s3b/exit.py"

INPUTS = {
    "s1": "results/s1/summary.json",
    "ci": "results/S3b/exit-ci.json",
    "speed": "results/S3b/speed/C17.json",
    "c9": "results/S3b/speed/C9.json",
    "c11": "results/S3b/speed/C11.json",
    "index": "docs/interfaces/README.md",
    "tracks": "tracks.yml",
}
FROZEN = {
    "s1": "results/S3b/exit-inputs/s1-summary.json",
    "index": "results/S3b/exit-inputs/interfaces-README.md",
    "tracks": "results/S3b/exit-inputs/tracks.yml",
}

# The S3 exit: main after the merge of the S3 exit record (T20, PR #56),
# the commit that the S3 approval records (docs/decisions/s3-exit.md,
# "Proof"). The sqll source of the C5 base (0c6b21a) is the same.
S3_EXIT = "319b7d66967a226e0dc4b5388303b56b96cefb58"
TOOL = "sqll"
# The state when each exit criterion is met. Before the approval (2026-11-11)
# it was "S3b awaiting approval"; status/S3b.md, "Approval", records the
# approval.
STATE = "S3b exit met"
OK_JOBS = ("success", "skipped")

# The log lines that the CI record must have, for each job (exit 1 and the
# oracle checks of S3b). Each is a full line of the job log.
CI_LINES = {
    "report": [
        "sqll rules: 2527 cases, 38 pass, 38 of them pass in the oracle",
        "sqll autofix: 61 cases, 0 pass, 0 of them pass in the oracle",
        "sqll templater: 43 cases, 0 pass, 0 of them pass in the oracle",
        "results/s1/summary.json is equal to the summary.",
    ],
    "dialect-oracle (sqlfluff)": [
        "sqll dialects: 2306 cases, 2306 pass, 2306 of them pass in the oracle",
    ],
    "build": [
        "tree guard: 84 of 84 inputs, 2 runs each: same output as the record",
    ],
    # The S2 benchmarks: the full profile of all tools (sqll with them),
    # checked against the S2 baseline (the push run has the full jobs).
    "bench-merge": [
        "out/bench.json: no schema error; complete for its scope.",
        "The stable data of 1120 results is that of the baseline "
        "results/s2/baseline.json.",
        "The report has the profile and each result of the baseline.",
    ],
}
# The prefixes of the other lines that the CI record must have (the line
# has counts that the record gives in full).
CI_PREFIXES = {
    "build": [
        "base native tests: PASS: 162 base tests pass in the base",
        "tree check: PASS: ",
        "source map check: PASS: ",
        "crawl check: PASS: ",
        "config check: PASS: ",
        "rules check: PASS: ",
        "cli check: PASS: ",
        "jinja as raw check: PASS: ",
        "schema check: PASS: ",
    ],
}

# The 4 frozen interfaces of STONES.md, S3b, and the rows of the interface
# index (docs/interfaces/README.md) that make each.
STONES_INTERFACES = {
    "lexer to parser to tree": ["Segment kinds", "Syntax tree", "Parse", "Typed view"],
    "tree to rules to fixes": ["Config", "Rules and fixes"],
    "templater to source map": ["Source map"],
    "tree to schema for code generation": ["Tree to schema"],
}
WHY = {
    "Config": "a rule reads its settings from the config (the Rule trait has "
    "its config keys; docs/interfaces/rules.md)",
}

# Each bullet of STONES.md, S3b (the start of its text), with its tasks,
# documents, and tests. Each file must exist.
BULLETS = [
    {
        "bullet": "One lossless syntax tree",
        "tasks": ["C6", "C7", "C9", "C10"],
        "docs": [
            "docs/interfaces/segment-kinds.md",
            "docs/interfaces/tree.md",
            "docs/interfaces/parse.md",
            "docs/interfaces/typed-view.md",
        ],
        "tests": [
            "crates/sqll_interfaces/tests/segment_kinds.rs",
            "crates/sqll_interfaces/tests/tree.rs",
            "crates/sqll_interfaces/tests/parse.rs",
            "crates/sqll_interfaces/tests/typed_view.rs",
            "scripts/s3/tree_guard.py",
            "scripts/s3b/tree_check.py",
        ],
    },
    {
        "bullet": "The source map",
        "tasks": ["C8"],
        "docs": ["docs/interfaces/source-map.md"],
        "tests": [
            "crates/sqll_interfaces/tests/source_map.rs",
            "scripts/s3b/source_map_oracle.py",
        ],
    },
    {
        "bullet": "Frozen interfaces",
        "tasks": ["C6", "C7", "C8", "C9", "C10", "C11", "C12", "C15", "C16"],
        "docs": ["docs/interfaces/README.md", "docs/decisions/s3b-core.md"],
        "tests": [
            "harness/tests/test_s3b_interfaces.py",
            "crates/sqll_interfaces/tests/rules.rs",
            "crates/sqll_interfaces/tests/schema.rs",
        ],
    },
    {
        "bullet": "The sqll binary skeleton",
        "tasks": ["C11", "C13", "C14"],
        "docs": [
            "docs/interfaces/config.md",
            "harness/sqll.md",
        ],
        "tests": [
            "crates/sqll_interfaces/tests/config.rs",
            "crates/sqll/tests/cli.rs",
            "crates/sqll/tests/cli_config.rs",
            "scripts/s3b/cli_oracle.py",
            "harness/tests/test_sqll_tool.py",
            "harness/tests/test_sqll_bench.py",
        ],
    },
    {
        "bullet": "A code layout with one package for each part",
        "tasks": ["C4", "C16"],
        "docs": ["docs/decisions/s3b-core.md", "docs/interfaces/README.md"],
        "tests": [
            "harness/tests/test_s3b_core.py",
            "harness/tests/test_ownership.py",
        ],
    },
]

# The ownership probe: each track of tracks.yml other than core (each
# branch from tracks.yml) and the Core paths that each changes.
TRACKS = ["S3", "S7-tests", "S9", "S4", "S5", "S6", "S7-sqll", "S8", "S10", "S11"]
PROBE_PATHS = [
    "docs/interfaces/parse.md",
    "crates/sqll_interfaces/tests/parse.rs",
    "crates/sqll_syntax/src/lib.rs",
    "crates/sqll_parser/Cargo.toml",
    "crates/sqll_dialects/build.rs",
    "Cargo.lock",
]
LABEL = "cross-track"

RULES = [
    "copied: the value of the key in the file. line: a full line of a CI job "
    "log in the CI record. derived: a formula over other values. A key part "
    "in brackets selects one list item by its fields.",
    "text: the form that docs/decisions/s3b-exit.md shows. A ratio has 3 "
    "digits; a commit has 7 characters.",
]

# The reason (G3.6) of each benchmark of the speed check that is slower than
# the noise limit. The exit record gives it.
REASONS: dict[str, str] = {}


class DataError(Exception):
    """A key is missing, or the inputs do not agree."""


def read_path(name: str) -> Path:
    """The file to read for the input name: the frozen copy if it has one."""
    return ROOT / FROZEN.get(name, INPUTS[name])


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(paths: dict[str, Path]) -> dict:
    data = {}
    for name, path in paths.items():
        try:
            text = path.read_text("utf8")
            data[name] = json.loads(text) if path.suffix == ".json" else text
        except (OSError, ValueError) as exc:
            raise DataError(f"{INPUTS[name]}: {exc}") from None
    return data


def _parts(key: str) -> list[str]:
    return re.findall(r"\[[^\]]*\]|[^.\[\]]+", key)


def get(doc, key: str):
    """Return the value of a dotted key. "[a=x,b=y]" selects the one list
    item with these field values."""
    value = doc
    for part in _parts(key):
        try:
            if part.startswith("["):
                want = dict(f.split("=", 1) for f in part[1:-1].split(","))
                found = [
                    item
                    for item in value
                    if all(str(item.get(k)) == v for k, v in want.items())
                ]
                if len(found) != 1:
                    raise KeyError(part)
                value = found[0]
            else:
                value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, ValueError, TypeError, AttributeError):
            raise DataError(f"no key {key!r}") from None
    return value


def fmt_ratio(x: float) -> str:
    return f"{x:.3f}"


def fmt_commit(x: str) -> str:
    return x[:7]


class Values:
    """The values of the exit record, each with its source."""

    def __init__(self, data: dict):
        self.data = data
        self.items: dict[str, dict] = {}

    def _add(self, vid: str, entry: dict, text) -> object:
        if vid in self.items:
            raise DataError(f"two values with the id {vid}")
        value = entry["value"]
        entry["text"] = (
            str(value) if text is None else text(value) if callable(text) else text
        )
        self.items[vid] = entry
        return value

    def copy(self, vid: str, src: str, key: str, text=None) -> object:
        value = get(self.data[src], key)
        entry = {"kind": "copied", "value": value, "from": INPUTS[src], "key": key}
        return self._add(vid, entry, text)

    def line(self, vid: str, job: str, want: str, prefix: bool = False) -> str:
        lines = get(self.data["ci"], f"jobs[name={job}].lines")
        found = [x for x in lines if (x.startswith(want) if prefix else x == want)]
        if len(found) != 1:
            raise DataError(f"CI job {job}: {len(found)} lines {want!r}")
        entry = {"kind": "line", "value": found[0], "from": INPUTS["ci"], "job": job}
        return self._add(vid, entry, None)

    def derive(self, vid: str, value, formula: str, text=None) -> object:
        entry = {"kind": "derived", "value": value, "formula": formula}
        return self._add(vid, entry, text)

    def v(self, vid: str):
        return self.items[vid]["value"]


# Exit 1: the S1 harness and the S2 benchmarks run sqll through its adapters.


def ci_values(vs: Values) -> None:
    ci = vs.data["ci"]
    vs.copy("ci.run_id", "ci", "run_id")
    vs.copy("ci.event", "ci", "event")
    vs.copy("ci.head", "ci", "head_sha", text=fmt_commit)
    vs.copy("ci.conclusion", "ci", "conclusion")
    vs.copy("ci.jobs_total", "ci", "jobs_total")
    vs.derive(
        "ci.jobs_not_ok",
        sorted(j["name"] for j in ci["jobs"] if j["conclusion"] not in OK_JOBS),
        "the recorded jobs with a conclusion other than success or skipped",
        text=lambda v: str(len(v)),
    )
    for job, lines in CI_LINES.items():
        for i, want in enumerate(lines):
            vs.line(f"ci.line.{job}.{i}", job, want)
    for job, prefixes in CI_PREFIXES.items():
        for i, want in enumerate(prefixes):
            vs.line(f"ci.prefix.{job}.{i}", job, want, prefix=True)


def s1_values(vs: Values) -> None:
    vs.copy("s1.sqll.version", "s1", f"tools.{TOOL}.version")
    for suite in ("dialects", "rules", "autofix", "templater"):
        key = f"results.{TOOL}.suites.{suite}"
        vs.copy(f"s1.{suite}.total", "s1", f"{key}.total")
        vs.copy(f"s1.{suite}.passed", "s1", f"{key}.passed")
    key = f"results.{TOOL}.suites.dialects.checks"
    vs.copy("s1.dialects.exact", "s1", f"{key}.exact")
    vs.copy("s1.dialects.no_unparsable", "s1", f"{key}.no_unparsable")
    vs.copy("s1.parity.total", "s1", f"results.{TOOL}.parity.total")
    vs.copy("s1.parity.passed", "s1", f"results.{TOOL}.parity.passed")
    for key in ("new_failures", "unexpected_passes"):
        vs.copy(f"s1.{key}", "s1", f"results.{TOOL}.known_failures_check.{key}")


def exit_adapters(vs: Values) -> bool:
    want = {
        "dialects": (2306, 2306),
        "rules": (2527, 38),
        "autofix": (61, 0),
        "templater": (43, 0),
    }
    found = {s: (vs.v(f"s1.{s}.total"), vs.v(f"s1.{s}.passed")) for s in want}
    return vs.derive(
        "exit.adapters",
        vs.v("ci.conclusion") == "success"
        and not vs.v("ci.jobs_not_ok")
        and found == want
        and vs.v("s1.dialects.exact") == vs.v("s1.dialects.total")
        and vs.v("s1.new_failures") == 0
        and vs.v("s1.unexpected_passes") == 0,
        "the CI run on the exit head passed (each job success or skipped) with "
        "the ci.line and ci.prefix values; the S1 summary of sqll has dialects "
        "2306 of 2306 exact, rules 38 of 2527, autofix 0 of 61, templater 0 of "
        "43, 0 new failures, and 0 unexpected passes",
    )


# Exit 2: the interfaces are documented.

ROW = re.compile(
    r"^\| (?P<name>[^|]+?) \| (?P<task>C\d+) \| (?P<packages>[^|]+?) \|"
    r" \[(?P<doc>[\w.-]+)\]\([^)]+\) \| `(?P<test>[^`]+)` \|$"
)


def index_rows(text: str) -> list[dict]:
    table = text.split("\n## ", 1)[0]
    lines = [x for x in table.splitlines() if x.startswith("| ")][1:]
    rows = []
    for line in lines:
        match = ROW.match(line)
        if match is None:
            raise DataError(f"{INPUTS['index']}: not an interface row: {line}")
        rows.append(match.groupdict())
    return rows


def interface_values(vs: Values) -> list[dict]:
    rows = index_rows(vs.data["index"])
    by_name = {r["name"]: r for r in rows}
    mapped = [name for names in STONES_INTERFACES.values() for name in names]
    out = []
    for stone, names in STONES_INTERFACES.items():
        for name in names:
            if name not in by_name:
                raise DataError(f"{INPUTS['index']}: no row {name!r}")
            row = by_name[name]
            doc = f"docs/interfaces/{row['doc']}"
            out.append(
                {
                    "stones": stone,
                    "interface": name,
                    "task": row["task"],
                    "document": doc,
                    "test": row["test"],
                    "files_exist": (ROOT / doc).is_file()
                    and (ROOT / row["test"]).is_file(),
                    **({"why": WHY[name]} if name in WHY else {}),
                }
            )
    vs.derive("interfaces.rows", len(rows), "count of the rows of the index")
    vs.derive(
        "interfaces.stones", len(STONES_INTERFACES), "count of the STONES interfaces"
    )
    vs.derive(
        "interfaces.mapped",
        len(set(mapped)),
        "count of the rows that map to a STONES interface",
    )
    vs.derive(
        "exit.interfaces",
        sorted(mapped) == sorted(by_name)
        and len(mapped) == len(set(mapped))
        and all(r["files_exist"] for r in out),
        "each row of the index maps to one STONES interface, and the document "
        "and the test of each row exist",
    )
    return out


def bullet_values(vs: Values, stones: str) -> list[dict]:
    part = stones.split("\n## S3b.", 1)[1].split("\n## ", 1)[0]
    text = " ".join(part.split())
    out = []
    for b in BULLETS:
        files = [*b["docs"], *b["tests"]]
        out.append(
            {
                **b,
                "in_stones": f"- {b['bullet']}" in text,
                "files_exist": all((ROOT / f).is_file() for f in files),
            }
        )
    vs.derive(
        "bullets.ok",
        all(b["in_stones"] and b["files_exist"] for b in out),
        "each bullet is in STONES.md, S3b, and each of its documents and tests exists",
    )
    return out


# Exit 3: after S3b, each change to the core goes through the Core track.

GIT_ENV = {
    "GIT_AUTHOR_NAME": "probe",
    "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
    "GIT_AUTHOR_DATE": "2026-11-11T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-11-11T00:00:00+00:00",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.pop("GITHUB_STEP_SUMMARY", None)
    env["HOME"] = env.get("HOME", "/tmp")
    return {**env, **GIT_ENV}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        env=_env(),
        check=True,
        capture_output=True,
    )


def _pull_request(repo: Path, tracks_text: str, path: str) -> None:
    """A merge commit as GitHub makes it: the base has tracks.yml and the
    path; the pull request changes the path."""
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "tracks.yml").write_text(tracks_text, "utf8")
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text("base\n", "utf8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "pr")
    (repo / path).write_text("changed\n", "utf8")
    _git(repo, "commit", "-qam", "change")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "pr", "-m", "merge")


def _ownership(repo: Path, branch: str, labels: list[str]) -> tuple[int, list[str]]:
    env = {**_env(), "BRANCH": branch, "LABELS": json.dumps(labels)}
    for key in ("REPO", "HEAD_REPO"):
        env.pop(key, None)
    out = subprocess.run(
        [sys.executable, str(ROOT / "ci" / "ownership.py"), "pull_request"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    keep = [
        x
        for x in out.stdout.splitlines()
        if x.startswith(("Branch ", "- ", "Result: ", "error: "))
    ]
    return out.returncode, keep


def _branch(tracks: dict, track: str) -> str:
    plain = [b for b in tracks[track]["branches"] if "*" not in b]
    if not plain:
        raise DataError(f"tracks.yml: the track {track} has no plain branch")
    return plain[0]


def probe(tracks_text: str) -> list[dict]:
    """Run ci/ownership.py on a pull request of each track of TRACKS that
    changes one Core path, without and with the label; and on a change of
    the status file of the track (the control). The runs of one tracks.yml
    text are made one time in a process."""
    return copy.deepcopy(_probe(tracks_text))


@functools.cache
def _probe(tracks_text: str) -> list[dict]:
    try:
        import yaml
    except ImportError:
        raise DataError("PyYAML is not available") from None
    tracks = yaml.safe_load(tracks_text)["tracks"]
    runs = []
    with tempfile.TemporaryDirectory(prefix="s3b-probe-") as tmp:
        for path in [*PROBE_PATHS, *(f"status/{t}.md" for t in TRACKS)]:
            repo = Path(tmp) / f"r{len(list(Path(tmp).iterdir()))}"
            _pull_request(repo, tracks_text, path)
            control = path.startswith("status/")
            for track in TRACKS:
                if control and path != f"status/{track}.md":
                    continue
                branch = _branch(tracks, track)
                for labels in ([], [LABEL]):
                    if control and labels:
                        continue
                    code, lines = _ownership(repo, branch, labels)
                    runs.append(
                        {
                            "track": track,
                            "branch": branch,
                            "path": path,
                            "control": control,
                            "label": bool(labels),
                            "exit_code": code,
                            "lines": lines,
                        }
                    )
    return runs


def probe_values(vs: Values, runs: list[dict]) -> None:
    core = [r for r in runs if not r["control"]]
    fail = [
        r
        for r in core
        if not r["label"]
        and r["exit_code"] == 1
        and f"- {r['path']}: owned by core (another track)" in r["lines"]
        and r["lines"][-1] == "Result: fail."
    ]
    passed = [
        r
        for r in core
        if r["label"]
        and r["exit_code"] == 0
        and f"Result: pass with the label '{LABEL}'. These tracks must review the"
        " pull request: core."
        in r["lines"]
    ]
    control = [r for r in runs if r["control"] and r["exit_code"] == 0]
    vs.derive("probe.tracks", len(TRACKS), "count of the tracks other than core")
    vs.derive("probe.paths", len(PROBE_PATHS), "count of the Core paths")
    vs.derive("probe.core_runs", len(core) // 2, "probe.tracks * probe.paths")
    vs.derive(
        "probe.fail_without_label",
        len(fail),
        "count of the runs without the label that fail (exit code 1) and name "
        "the path as owned by core",
    )
    vs.derive(
        "probe.pass_with_label",
        len(passed),
        "count of the runs with the label that pass and ask for a core review",
    )
    vs.derive(
        "probe.control_pass",
        len(control),
        "count of the control runs (the status file of the track) that pass",
    )
    vs.derive(
        "exit.core_track",
        len(fail) == len(passed) == len(core) // 2 == len(TRACKS) * len(PROBE_PATHS)
        and len(control) == len(TRACKS),
        "probe.fail_without_label == probe.pass_with_label == probe.core_runs, "
        "and each control run passes",
    )


# G3: keep the S3 speed (the sum of the S3b changes).


def speed_values(vs: Values) -> None:
    sp = "speed"
    vs.copy("speed.base", sp, "base.commit", text=fmt_commit)
    vs.copy("speed.head", sp, "head.commit", text=fmt_commit)
    vs.copy("speed.head.version", sp, "head.version")
    vs.copy("speed.benchmarks", sp, "summary.slowdowns.benchmarks")
    for key in ("slower", "faster", "same", "failure"):
        vs.copy(f"speed.{key}", sp, f"summary.slowdowns.counts.{key}")
    vs.copy(
        "speed.slower_ids",
        sp,
        "summary.slowdowns.slower",
        text=lambda v: str(len(v)),
    )
    for group in ("start", "parse/small", "parse/medium", "parse/large", "total"):
        vs.copy(
            f"speed.ratio.{group}",
            sp,
            f"summary.slowdowns.groups[group={group}].ratio.total",
            text=fmt_ratio,
        )
    for other in ("sqruff", "sqlfluff"):
        g = f"summary.g3.{other}"
        vs.copy(f"speed.{other}.pairs", sp, f"{g}.pairs")
        vs.copy(f"speed.{other}.head_faster", sp, f"{g}.head_faster")
        vs.copy(
            f"speed.{other}.head_slower",
            sp,
            f"{g}.head_slower",
            text=lambda v: str(len(v)),
        )
        vs.copy(f"speed.{other}.ok", sp, f"{g}.ok")
        vs.copy(
            f"speed.{other}.ratio.total",
            sp,
            f"{g}.groups[group=total].ratio.total",
            text=fmt_ratio,
        )
    # The known S3b costs (the reason of each change): C9 (the parse
    # interface: the conversion to the SyntaxTree) and C11 (the config in
    # the start path).
    total = "summary.slowdowns.groups[group=total].ratio.total"
    vs.copy("c9.ratio.total", "c9", total, text=fmt_ratio)
    vs.copy(
        "c11.ratio.start",
        "c11",
        "summary.slowdowns.groups[group=start].ratio.total",
        text=fmt_ratio,
    )
    slower = list(vs.v("speed.slower_ids"))
    vs.derive(
        "speed.no_reason",
        sorted(s for s in slower if not REASONS.get(s)),
        "the slower benchmarks with no reason in REASONS",
        text=lambda v: str(len(v)),
    )
    vs.derive(
        "g3.met",
        vs.v("speed.failure") == 0
        and not vs.v("speed.no_reason")
        and vs.v("speed.sqlfluff.head_faster") == vs.v("speed.sqlfluff.pairs") == 112
        and vs.v("speed.sqruff.head_faster") == vs.v("speed.sqruff.pairs") == 108
        and not vs.v("speed.sqruff.head_slower")
        and vs.v("speed.sqruff.ok") is True
        and vs.v("speed.sqlfluff.ok") is True,
        "speed.failure == 0, each slower benchmark has a reason, HEAD is faster "
        "than sqlfluff on 112 of 112 and faster than sqruff on 108 of 108 pairs",
    )


def check_agreement(vs: Values) -> None:
    if not vs.v("speed.base").startswith(S3_EXIT):
        raise DataError(f"the speed check base is not the S3 exit {S3_EXIT}")
    # The guard of the sqll source: the speed check and the CI run have the
    # same head commit.
    if vs.v("speed.head") != vs.v("ci.head"):
        raise DataError("the speed check head is not the head of the CI run")
    # The version is the package version and the hash of the dialect tables.
    # It does not change with other sqll code, so it only shows that the
    # speed check and the S1 summary use the same dialect tables.
    if vs.v("speed.head.version") != vs.v("s1.sqll.version"):
        raise DataError(
            "the sqll version (with the hash of the dialect tables) of the speed "
            "check head is not that of the S1 summary"
        )


def criteria(vs: Values) -> list[dict]:
    return [
        {
            "id": "S3b.exit.adapters",
            "text": "STONES.md S3b exit: the S1 harness and the S2 benchmarks run "
            "sqll through its adapters.",
            "met": vs.v("exit.adapters"),
            "values": ["exit.adapters", "ci.run_id", "ci.head"],
        },
        {
            "id": "S3b.exit.interfaces",
            "text": "STONES.md S3b exit: the interfaces are documented.",
            "met": vs.v("exit.interfaces") and vs.v("bullets.ok"),
            "values": ["exit.interfaces", "interfaces.rows", "bullets.ok"],
        },
        {
            "id": "S3b.exit.core_track",
            "text": "STONES.md S3b exit: after S3b, each change to the core goes "
            "through the Core track.",
            "met": vs.v("exit.core_track"),
            "values": ["exit.core_track", "probe.core_runs"],
        },
        {
            "id": "G3.keep",
            "text": "CONSTITUTION.md G3 (keep the S3 speed): the S3b changes "
            "together, from the S3 exit to the S3b exit head.",
            "met": vs.v("g3.met"),
            "values": ["g3.met", "speed.base", "speed.head"],
        },
    ]


def make_report(paths: dict[str, Path] | None = None, live_probe: bool = False) -> dict:
    paths = paths or {k: read_path(k) for k in INPUTS}
    data = load(paths)
    vs = Values(data)
    ci_values(vs)
    s1_values(vs)
    exit_adapters(vs)
    interfaces = interface_values(vs)
    bullets = bullet_values(vs, (ROOT / "STONES.md").read_text("utf8"))
    runs = probe(data["tracks"])
    if live_probe and probe((ROOT / INPUTS["tracks"]).read_text("utf8")) != runs:
        raise DataError("the probe on the live tracks.yml gives other lines")
    probe_values(vs, runs)
    speed_values(vs)
    check_agreement(vs)
    crit = criteria(vs)
    met = all(c["met"] for c in crit)
    return {
        "kind": "sqll-s3b-exit",
        "task": "C17",
        "command": COMMAND,
        "inputs": {INPUTS[k]: sha256_file(p) for k, p in paths.items()},
        "rules": RULES,
        "criteria": crit,
        "result": {"met": met, "state": STATE if met else "S3b exit not met"},
        "interfaces": interfaces,
        "bullets": bullets,
        "reasons": REASONS,
        "probe": runs,
        "values": vs.items,
    }


def text(report: dict) -> str:
    return json.dumps(report, indent=1) + "\n"


def check_copies() -> None:
    """Each frozen copy is equal to its live file (only when it writes)."""
    for name, rel in FROZEN.items():
        if (ROOT / rel).read_bytes() != (ROOT / INPUTS[name]).read_bytes():
            raise DataError(f"{rel} is not equal to {INPUTS[name]}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="exit.py")
    p.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    try:
        if not args.check:
            check_copies()
        report = make_report(live_probe=args.check)
    except (DataError, subprocess.CalledProcessError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    new = text(report)
    rel = OUT_FILE.relative_to(ROOT) if OUT_FILE.is_relative_to(ROOT) else OUT_FILE
    if args.check:
        if not OUT_FILE.exists() or OUT_FILE.read_text("utf8") != new:
            print(f"error: {rel} is not the output of the inputs")
            return 1
        print(f"exit check: PASS: {rel}: no change; state: {report['result']['state']}")
        return 0
    OUT_FILE.write_text(new, "utf8")
    print(f"wrote {rel}; state: {report['result']['state']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
