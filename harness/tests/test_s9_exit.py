"""The S9 exit record (status/S9.md, "S9 exit" and "Input for S3"): the
state text, a proof for each criterion, and the numbers of the record are
those of the manifest and of results/S9/baseline.json."""

import re
from collections import Counter

from sqll_harness.corpus import baseline, report
from sqll_harness.corpus.manifest import JINJA, RAW, load
from sqll_harness.paths import REPO_ROOT

MANIFEST = load()
BASE = report.load(baseline.BASELINE)
TOOLS = ["sqlfluff", "sqlfluff-rs", "sqruff"]
STATUS = (REPO_ROOT / "status" / "S9.md").read_text(encoding="utf8")
DECISION = (REPO_ROOT / "docs" / "decisions" / "s9-corpus.md").read_text(
    encoding="utf8"
)
STATE = (
    "- State: S9 (sqlfluff, sqlfluff[rs], sqruff) awaiting human approval; "
    "sqll results after S3b"
)
LARGE = 500_000
BY_KEY = {(r["file"], r["tool"]): r for r in BASE["results"]}


def _words(text: str) -> str:
    return " ".join(text.split())


def _section(title: str) -> str:
    start = STATUS.index(f"\n## {title}\n")
    end = STATUS.find("\n## ", start + 1)
    return _words(STATUS[start:end])


def _proofs() -> dict[str, str]:
    rows = {}
    for line in STATUS.splitlines():
        if line.startswith("| ") and not line.startswith("| Criterion"):
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip()[1:-1])]
            if len(cells) == 2:
                rows[cells[0]] = cells[1]
    return rows


def test_status_has_the_exact_state_text():
    assert STATUS.splitlines().count(STATE) == 1


def test_each_exit_criterion_has_a_proof():
    proofs = _proofs()
    criteria = [
        "STONES.md S9: collect large, complex SQL files from public sources",
        "STONES.md S9: record source and license; G4.3: source, version, "
        "and license of external test data",
        "G4.2: large, complex SQL files from public sources",
        "STONES.md S9 exit: the report shows parse success and speed for "
        "each file, for each tool",
        "The report runs in CI on main",
        "Local proof on the final commit",
    ]
    assert list(proofs) == criteria
    for name, proof in proofs.items():
        assert len(proof) > 40, name
        assert not re.search(
            r"\b(TODO|TBD|RUNID|MAINHEAD|JOBCOUNTS|VERIFYPROOF)\b", proof
        )
    ci = proofs["The report runs in CI on main"]
    assert re.search(r"CI run \[?\d{11}", ci)
    assert re.search(r"`[0-9a-f]{7,40}`", ci)
    assert "--baseline results/S9/baseline.json --full" in ci
    assert "scripts/verify --quick" in proofs["Local proof on the final commit"]
    assert "PR #PRNUM" not in STATUS


def test_the_corpus_proof_has_the_numbers_of_the_manifest():
    proof = _proofs()[
        "STONES.md S9: collect large, complex SQL files from public sources"
    ]
    sizes = [f.bytes for f in MANIFEST.files]
    kinds = Counter(f.templater for f in MANIFEST.files)
    dialects = {f.dialect for f in MANIFEST.files}
    assert (
        f"{len(sizes)} files ({kinds[RAW]} raw, {kinds[JINJA]} Jinja) of "
        f"{len(MANIFEST.sources)} public git sources"
    ) in proof
    assert f"{len(dialects)} dialects" in proof
    assert f"{min(sizes)} to {max(sizes)} bytes, {sum(sizes)} bytes in total" in proof
    large = _proofs()["G4.2: large, complex SQL files from public sources"]
    assert f"{sum(s >= LARGE for s in sizes)} files have 0.5 MB or more" in large


def test_the_license_proof_has_the_numbers_of_the_manifest():
    proof = _proofs()[
        "STONES.md S9: record source and license; G4.3: source, version, "
        "and license of external test data"
    ]
    blobs = {(s.id, b.path) for s in MANIFEST.sources.values() for b in s.license_files}
    n = len(MANIFEST.files)
    assert f"{len(MANIFEST.sources)} sources, {n} files" in proof
    assert f"{n + len(blobs)} files ({n} SQL and {len(blobs)} license files)" in proof
    for source in MANIFEST.sources.values():
        assert re.fullmatch(r"[0-9a-f]{40}", source.commit)
        assert source.license and source.copyright and source.license_files


def test_the_report_proof_has_the_numbers_of_the_baseline():
    proof = _proofs()[
        "STONES.md S9 exit: the report shows parse success and speed for "
        "each file, for each tool"
    ]
    results = BASE["results"]
    timed = [r for r in results if r["status"] in report.TIMED_STATUSES]
    other = [r for r in results if r["status"] not in report.TIMED_STATUSES]
    assert f"{len(results)} results = {len(BASE['inputs'])} files x 3 tools" in proof
    assert f"{len(timed)} results have a tree and the timing stats" in proof
    assert f"The other {len(other)} are `invalid`" in proof
    assert {r["status"] for r in other} == {report.INVALID}
    for r in timed:
        assert r["stats"]["wall_s"]["median"] > 0 and r["bytes_per_s"] > 0
    for r in other:
        assert r["samples"] and r["samples"][0]["wall_s"] > 0, r["file"]


def test_the_s3_input_has_the_numbers_of_the_baseline():
    text = _section("Input for S3")
    files = list(BASE["inputs"])

    def outcome(f, t):
        r = BY_KEY[(f, t)]
        return r["status"], r["unparsable"]

    assert all(outcome(f, "sqlfluff") == outcome(f, "sqlfluff-rs") for f in files)
    other_status = [
        f
        for f in files
        if BY_KEY[(f, "sqlfluff")]["status"] != BY_KEY[(f, "sqruff")]["status"]
    ]
    other_counts = [
        f
        for f in files
        if f not in other_status and outcome(f, "sqlfluff") != outcome(f, "sqruff")
    ]
    ok_unparsable = [
        f
        for f in files
        if BY_KEY[(f, "sqlfluff")]["status"] == report.OK
        and BY_KEY[(f, "sqruff")]["status"] == report.UNPARSABLE
    ]
    assert f"sqruff gives another status on {len(other_status)} files" in text
    assert f"On {len(other_counts)} other files, all 3 tools give unparsable" in text
    assert f"sqlfluff gives `ok` on {len(ok_unparsable)} files" in text
    groups = Counter()
    for f in ok_unparsable:
        name = f.rsplit("/", 1)[1]
        if f.startswith("sql-server-maintenance-solution/"):
            groups["maintenance"] += 1
        elif name.startswith("instnwnd"):
            groups["instnwnd"] += 1
        else:
            assert f"`{name}`" in text, name
    assert f"the {groups['instnwnd']} `instnwnd` files" in text
    assert f"{groups['maintenance']} `sql-server-maintenance-solution` files" in text
    compared = BASE["compared"]
    assert (
        f"{compared['files']} files where each tool is `ok` ({compared['bytes']} bytes)"
        in text
    )
    for tool in TOOLS[1:]:
        assert f"{compared['results'][tool]['wall_ratio']:.3f}" in text
    for tool in TOOLS:
        top = max(
            (r for r in BASE["results"] if r["tool"] == tool),
            key=lambda r: r["max_rss_kib"],
        )
        assert f"{top['max_rss_kib'] // 1024} MiB" in text
        assert top["file"].endswith("/Chinook_PostgreSql.sql")


def _ok_files() -> list[str]:
    return [
        f
        for f in BASE["inputs"]
        if all(BY_KEY[(f, t)]["status"] == report.OK for t in TOOLS)
    ]


def test_the_s3_input_has_the_details_of_the_baseline():
    text = _section("Input for S3")
    files = list(BASE["inputs"])
    ok_unparsable = [
        f
        for f in files
        if BY_KEY[(f, "sqlfluff")]["status"] == report.OK
        and BY_KEY[(f, "sqruff")]["status"] == report.UNPARSABLE
    ]
    dialects = Counter(BASE["inputs"][f]["dialect"] for f in ok_unparsable)
    assert f"{len(ok_unparsable)} files: {dialects['tsql']} tsql (" in text
    panics = [
        r["file"]
        for r in BASE["results"]
        if r["tool"] == "sqruff" and "panic" in (r["reason"] or "")
    ]
    assert len(panics) == 1
    assert f"sqruff panics on `{panics[0].rsplit('/', 1)[1]}`" in text

    ok = sorted(_ok_files(), key=lambda f: -BASE["inputs"][f]["bytes"])
    chinook = [f for f in ok if f.startswith("chinook-database/")]
    assert ok[: len(chinook)] == chinook
    sizes = [BASE["inputs"][f]["bytes"] / 1e6 for f in chinook]
    assert (
        f"Largest such files: {len(chinook)} Chinook files of "
        f"{min(sizes):.2f} to {max(sizes):.2f} MB" in text
    )
    pg = "chinook-database/ChinookDatabase/DataSources/Chinook_PostgreSql.sql"
    walls = [f"{BY_KEY[(pg, t)]['stats']['wall_s']['median']:.3f} s" for t in TOOLS]
    assert f"`Chinook_PostgreSql.sql`: {walls[0]}, {walls[1]}, and {walls[2]}" in text


def _no_tree() -> list[dict]:
    """The results that stop at max_parse_depth: the record gives the tool
    message of each ("S9 results")."""
    return [
        r
        for r in BASE["results"]
        if r["status"] == report.INVALID and "no parse tree" in (r["reason"] or "")
    ]


def test_the_max_parse_depth_results_are_those_of_the_baseline():
    no_tree = _no_tree()
    files = sorted({r["file"] for r in no_tree})
    decision = _words(DECISION)
    t8 = decision[decision.index("T8 decision:") :]
    t8 = t8[: t8.index("## ")]
    assert f"The {len(no_tree)} `invalid` results that stop at `max_parse_depth`" in t8
    text = _section("Input for S3")
    assert (
        f"`max_parse_depth` stops {len(no_tree)} results with no tree on "
        f"{len(files)} files" in text
    )
    for f in files:
        name = f.rsplit("/", 1)[1]
        assert f"`{name}`" in t8 and f"`{name}`" in text, name
        tools = {r["tool"] for r in no_tree if r["file"] == f}
        assert {"sqlfluff", "sqlfluff-rs"} <= tools, f
        if tools == set(TOOLS):
            assert f"No tool gives a tree on `{name}`" in text
            assert f"all 3 tools on `{name}`" in t8
        else:
            assert BY_KEY[(f, "sqruff")]["status"] in report.TIMED_STATUSES


def test_the_t8_decision_keeps_max_parse_depth():
    """No tool setting of the baseline changes max_parse_depth, so each tool
    uses the default (600) of the pinned sqlfluff, as the record says."""
    assert "T8 decision: S9 keeps `max_parse_depth = 600`" in _words(DECISION)
    assert "S9 keeps `max_parse_depth = 600`" in _words(STATUS)
    for tool in TOOLS:
        assert "max_parse_depth" not in repr(BASE["tools"][tool]["settings"])
