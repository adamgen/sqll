"""S3 phase A, task T9: the data of the decision record (criterion C8 of
docs/decisions/s3-base.md).

One command. Run it with the harness Python:

    uv run --frozen --project harness python scripts/s3/decision_data.py [--check]

It reads only committed files: the S1 summary and the T2 to T8 outputs
(INPUTS). It writes OUT_FILE. With --check it writes nothing and fails if
OUT_FILE is not the new text. It runs no tool and no benchmark.

Each value of the output has an id, the value, and the text that the
decision record shows. A value is "copied" ("from" and "key" name the file
and the key), "derived" (a "formula" over copied values), or an "estimate"
(a "formula" and the reason). The tables of the decision record are made
from these values; the test harness/tests/test_s3_decision_data.py checks
that the record has each table row and only numbers of this file.

It stops with exit code 1 (DataError) if a key is missing or the inputs do
not agree (for example, the T5 native tree count and the S1 count).
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_a  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_FILE = ROOT / "results" / "s3" / "decision-data.json"
COMMAND = "uv run --frozen --project harness python scripts/s3/decision_data.py"

INPUTS = {
    "s1": "results/s1/summary.json",
    "t2": "results/s3/s1-by-base.json",
    "t3": "results/s3/sqruff-tree-diffs.json",
    "t4": "results/s3/sqruff-rule-diffs.json",
    "t5": "results/s3/sqlfluffrs-probe.json",
    "t6": "results/s3/speed-by-base.json",
    "t7": "results/s3/license-size.json",
    "t8": "results/s3/capabilities.json",
}

SUITES = ("dialects", "rules", "autofix", "templater")
COMMANDS = ("start", "parse", "lint", "fix", "all")
S6_TEMPLATERS = ("raw", "placeholder", "python", "jinja")
SPEED_BASES = {
    "sqruff": "1 sqruff",
    "sqlfluffrs": "2 sqlfluffrs",
    "new-parser-low": "3 low",
    "new-parser-high": "3 high",
}
SPEED_KIND = {
    "sqruff": "measured",
    "sqlfluffrs": "start, parse: measured; lint, fix, all: estimate",
    "new-parser-low": "estimate",
    "new-parser-high": "estimate",
}

RULES = [
    "copied: the value of the key in the file. derived: a formula over copied "
    "values. estimate: a formula and its reason; the record labels it.",
    "text: the form that docs/decisions/s3-base.md shows. A ratio has 3 "
    "digits, a share is a percent with 1 digit.",
    "Each number of the decision record outside code and links is the text of "
    "a value, or a version, or an id such as G3.5 or T5.",
]

ESTIMATE_LIMITS = [
    "The work estimates count items (cases, groups, rules, commands, lines); "
    "they give no time. One item can need much more work than another.",
    "A T3 group is a proxy for one grammar fix (T3 limit). A T4 changed tree "
    "is an upper bound of the rules that need a change.",
    "Option 3 has no implementation. Its engine size is that of the sqlfluffrs "
    "engine crates, and its rule size is that of the sqruff rules (T7).",
    "No base has native rules on sqlfluff trees. The rule work of options 2 "
    "and 3 is not measured; its size is that of the sqruff rule layer.",
]


class DataError(Exception):
    """A key is missing, or the inputs do not agree."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(paths: dict[str, Path] | None = None) -> dict[str, dict]:
    paths = paths or {k: phase_a.read_path(v) for k, v in INPUTS.items()}
    data = {}
    for name, path in paths.items():
        try:
            data[name] = json.loads(path.read_text("utf8"))
        except (OSError, ValueError) as exc:
            raise DataError(f"{INPUTS[name]}: {exc}") from None
    return data


def get(doc: dict, key: str):
    """Return the value of a dotted key. A part in brackets ("[x.y]") is one
    key that has dots."""
    value = doc
    for part in _parts(key):
        try:
            value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, ValueError, TypeError):
            raise DataError(f"no key {key!r}") from None
    return value


def _parts(key: str) -> list[str]:
    parts, word, depth = [], "", 0
    for ch in key:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "." and depth == 0:
            parts.append(word)
            word = ""
        else:
            word += ch
    return [*parts, word]


def fmt_ratio(x: float) -> str:
    return f"{x:.3f}"


def fmt_share(x: float) -> str:
    return f"{100 * x:.1f}%"


class Values:
    """The values of the decision record, each with its source."""

    def __init__(self, data: dict[str, dict]):
        self.data = data
        self.items: dict[str, dict] = {}

    def _add(self, vid: str, entry: dict) -> object:
        if vid in self.items:
            raise DataError(f"two values with the id {vid}")
        value = entry["value"]
        if "text" not in entry:
            entry["text"] = str(value)
        self.items[vid] = entry
        return value

    def copy(self, vid: str, src: str, key: str, text=None) -> object:
        value = get(self.data[src], key)
        entry = {"kind": "copied", "value": value, "from": INPUTS[src], "key": key}
        if text is not None:
            entry["text"] = text(value) if callable(text) else text
        return self._add(vid, entry)

    def derive(self, vid: str, value, formula: str, text=None) -> object:
        entry = {"kind": "derived", "value": value, "formula": formula}
        if text is not None:
            entry["text"] = text(value) if callable(text) else text
        return self._add(vid, entry)

    def estimate(self, vid: str, value, formula: str, reason: str) -> object:
        entry = {
            "kind": "estimate",
            "value": value,
            "formula": formula,
            "reason": reason,
        }
        return self._add(vid, entry)

    def t(self, vid: str) -> str:
        return self.items[vid]["text"]

    def v(self, vid: str):
        return self.items[vid]["value"]


# C1: the S1 results of each base.


def s1_values(vs: Values) -> None:
    d = vs.data
    vs.derive("g3.limit", 1, "CONSTITUTION.md G3.4, G3.5: a ratio of the sums below 1")
    for suite in SUITES:
        vs.copy(
            f"s1.sqlfluff.{suite}.total", "s1", f"results.sqlfluff.suites.{suite}.total"
        )
        vs.copy(
            f"s1.sqlfluff.{suite}.pass", "s1", f"results.sqlfluff.suites.{suite}.passed"
        )
        for base in ("sqruff", "sqlfluffrs"):
            vs.copy(
                f"t2.{base}.{suite}.total", "t2", f"bases.{base}.suites.{suite}.total"
            )
            vs.copy(
                f"t2.{base}.{suite}.pass", "t2", f"bases.{base}.suites.{suite}.pass"
            )
            if vs.v(f"t2.{base}.{suite}.total") != vs.v(f"s1.sqlfluff.{suite}.total"):
                raise DataError(f"T2 {base} {suite}: another case count than S1")
    vs.copy(
        "s1.suites", "s1", "results.sqlfluff.parity.suites", text=lambda v: str(len(v))
    )
    vs.copy("s1.sqlfluff.exact", "s1", "results.sqlfluff.suites.dialects.checks.exact")
    vs.copy(
        "s1.sqlfluff.no_unparsable",
        "s1",
        "results.sqlfluff.suites.dialects.checks.no_unparsable",
    )
    for base in ("sqruff", "sqlfluffrs"):
        vs.copy(
            f"t2.{base}.exact", "t2", f"bases.{base}.suites.dialects.checks.exact.pass"
        )
        vs.copy(
            f"t2.{base}.no_unparsable",
            "t2",
            f"bases.{base}.suites.dialects.checks.no_unparsable.pass",
        )
    for base in ("sqruff", "sqlfluffrs", "new-parser"):
        vs.copy(f"option.{base}", "t2", f"bases.{base}.option")
    vs.copy("t5.native.exact", "t5", "fixtures.total.exact")
    vs.copy("t5.native.no_unparsable", "t5", "fixtures.total.no_unparsable")
    vs.copy("t5.native.cases", "t5", "fixtures.total.cases")
    vs.derive(
        "t5.cases_to_fix",
        vs.v("t5.native.cases") - vs.v("t5.native.exact"),
        "t5.native.cases - t5.native.exact",
    )
    if vs.v("t5.native.cases") != vs.v("s1.sqlfluff.dialects.total"):
        raise DataError("T5: another dialect case count than S1")

    dialects = get(d["t2"], "bases.sqruff.dialects")
    vs.derive("t2.dialects", len(dialects), "len(t2 bases.sqruff.dialects)")
    full = sorted(
        k for k, v in dialects.items() if v["checks"]["exact"]["pass"] == v["total"]
    )
    vs.derive(
        "t2.sqruff.dialects_all_exact",
        len(full),
        "count of t2 bases.sqruff.dialects with checks.exact.pass == total",
    )
    vs.derive(
        "t2.sqruff.dialects_all_exact_names",
        full,
        "the same dialects",
        text=", ".join(full),
    )
    worst = min(
        dialects,
        key=lambda k: (
            dialects[k]["checks"]["exact"]["pass"] / dialects[k]["total"],
            -dialects[k]["total"],
        ),
    )
    vs.copy(
        "t2.sqruff.worst.pass", "t2", f"bases.sqruff.dialects.{worst}.checks.exact.pass"
    )
    vs.copy("t2.sqruff.worst.total", "t2", f"bases.sqruff.dialects.{worst}.total")
    vs.derive(
        "t2.sqruff.worst.name",
        worst,
        "the t2 sqruff dialect with the lowest exact share (the largest on a tie)",
    )
    rs = get(d["t2"], "bases.sqlfluffrs.dialects")
    if sum(v["checks"]["exact"]["pass"] == v["total"] for v in rs.values()) != len(rs):
        raise DataError("T2: a sqlfluffrs dialect is not all exact")

    groups = get(d["t2"], "bases.sqruff.rules")
    codes = sorted({c for key in groups for c in key.split(",")})
    vs.derive("t2.rule_groups", len(groups), "len(t2 bases.sqruff.rules)")
    vs.derive(
        "t2.rule_codes",
        len(codes),
        "the rule codes in the keys of t2 bases.sqruff.rules",
    )
    vs.derive(
        "t2.sqruff.groups_all_pass",
        sum(g["fail"] + g["error"] == 0 for g in groups.values()),
        "count of t2 bases.sqruff.rules with fail + error == 0",
    )
    sq_codes = sorted(r["code"] for r in get(d["t4"], "coupling.rules"))
    missing = sorted(set(codes) - set(sq_codes))
    if set(sq_codes) - set(codes):
        raise DataError("T4: a sqruff rule code that is not in the S1 rule cases")
    vs.derive(
        "sqruff.rules_missing",
        len(missing),
        "the S1 rule codes that are not in t4 coupling.rules",
    )
    vs.derive(
        "sqruff.rules_missing_names", missing, "the same codes", text=", ".join(missing)
    )
    rs_rules = vs.copy(
        "t7.sqlfluffrs.rule_modules",
        "t7",
        "bases.sqlfluffrs.structure.values.rule_modules",
        text=lambda v: str(len(v)),
    )
    vs.derive(
        "sqlfluffrs.rule_names",
        sorted(m.removesuffix(".rs").upper() for m in rs_rules),
        "the t7 rule modules as codes",
        text=lambda v: ", ".join(v),
    )
    vs.derive(
        "sqlfluffrs.rules_in_python",
        len(codes) - len(rs_rules),
        "t2.rule_codes - len(t7.sqlfluffrs.rule_modules)",
    )
    vs.copy("t2.sqruff.rules.fail", "t2", "bases.sqruff.suites.rules.fail")
    vs.copy("t2.sqruff.rules.error", "t2", "bases.sqruff.suites.rules.error")


# C2 and C3: the sqruff failure classes, the systematic share, and the rule
# coupling.


def sqruff_values(vs: Values) -> None:
    vs.copy("t3.cases", "t3", "scope.cases")
    vs.copy("t3.dialect_cases", "t3", "scope.dialects")
    vs.copy("t3.templater_cases", "t3", "scope.templater")
    for name in (
        "extra_wrapper",
        "renamed",
        "missing_wrapper",
        "unparsable",
        "leaf_type",
        "unsupported_dialect",
    ):
        vs.copy(f"t3.class.{name}", "t3", f"classes.{name}.cases")
    vs.copy("t3.groups", "t3", "groups.groups")
    for n in ("10", "20", "50"):
        vs.derive(f"t3.top{n}.n", int(n), "a key of t3 groups.top")
        vs.copy(f"t3.top{n}.cases", "t3", f"groups.top.{n}.cases")
        vs.copy(f"t3.top{n}.share", "t3", f"groups.top.{n}.share", text=fmt_share)
    vs.copy("t3.groups_with_one_case", "t3", "groups.groups_with_one_case")
    vs.copy("t3.unique_fix", "t3", "groups.cases_with_a_unique_fix")
    vs.copy("t3.hand_check.agree", "t3", "hand_check.agree")
    vs.copy("t3.hand_check.size", "t3", "hand_check.size")
    for suite in ("rules", "autofix", "templater"):
        vs.copy(f"t4.failures.{suite}", "t4", f"scope.failures.{suite}")
    for cls in ("unsupported_item", "parse_cause", "rule_logic"):
        vs.copy(f"t4.total.{cls}", "t4", f"total.{cls}")
        vs.derive(
            f"t4.rules_autofix.{cls}",
            get(vs.data["t4"], f"counts.rules.{cls}")
            + get(vs.data["t4"], f"counts.autofix.{cls}"),
            f"t4 counts.rules.{cls} + counts.autofix.{cls}",
        )
    total = sum(vs.v(f"t4.failures.{s}") for s in ("rules", "autofix", "templater"))
    vs.derive("t4.failures", total, "t4 scope.failures: rules + autofix + templater")
    if total != sum(
        vs.v(f"t4.total.{c}") for c in ("unsupported_item", "parse_cause", "rule_logic")
    ):
        raise DataError("T4: the class totals do not add up")
    if vs.v("t4.failures.rules") != vs.v("t2.sqruff.rules.fail") + vs.v(
        "t2.sqruff.rules.error"
    ):
        raise DataError("T4: another rule failure count than T2")
    s = "coupling.summary"
    vs.copy("t4.rules", "t4", f"{s}.rules")
    vs.copy("t4.names", "t4", f"{s}.names")
    vs.copy("t4.names_renamed", "t4", f"{s}.names_renamed_in_t3")
    vs.copy(
        "t4.names_not_in_sqlfluff",
        "t4",
        f"{s}.names_not_in_sqlfluff",
        text=lambda v: str(len(v)),
    )
    vs.copy("t4.rules_differ", "t4", f"{s}.rules_with_a_name_that_differs")
    vs.copy("t4.rules_changed", "t4", f"{s}.rules_that_see_a_changed_tree")
    vs.copy(
        "t4.rules_not_changed",
        "t4",
        f"{s}.rules_that_see_no_changed_tree",
        text=lambda v: ", ".join(v),
    )


# C4: the sqlfluffrs probe and the generator.


def probe_values(vs: Values) -> None:
    vs.copy(
        "t5.python_calls",
        "t5",
        "standalone.python_calls_during_cargo",
        text=lambda v: str(len(v)),
    )
    vs.copy("t5.libpython", "t5", "standalone.libpython_linked")
    vs.copy("t5.generation.files", "t5", "generation.files")
    vs.copy("t5.generation.lines", "t5", "generation.lines")
    vs.copy(
        "t5.generation.wall_s", "t5", "generation.wall_s", text=lambda v: f"{v:.0f}"
    )
    vs.copy("t5.table_builder_lines", "t5", "generator.table_builder_lines")
    vs.copy("t5.emitter_lines", "t5", "generator.rust_emitter_lines")
    vs.copy(
        "t5.private_attributes",
        "t5",
        "generator.private_attributes",
        text=lambda v: str(len(v)),
    )
    vs.copy(
        "t5.custom_match",
        "t5",
        "generator.dialect_files_with_custom_match",
        text=lambda v: str(len(v)),
    )
    vs.estimate(
        "t5.new_emitter_lines.a",
        0,
        "way (a) of t5 option3_reuse.conclusion: keep the sqlfluffrs_types table "
        "format, thus no new emitter lines",
        "A judgement of T5; way (b) needs a new emitter of the size of "
        "t5.emitter_lines.",
    )
    vs.copy(
        "t5.engine_lines",
        "t5",
        "build.lines.sqlfluffrs_parser.hand_written.lines",
    )


# C5: speed.


def speed_values(vs: Values) -> None:
    for base in SPEED_BASES:
        root = f"bases.{base}.summary"
        for c in COMMANDS:
            vs.copy(
                f"t6.{base}.{c}.total",
                "t6",
                f"{root}.{c}.g3_5_total.ratio",
                text=fmt_ratio,
            )
        a = f"{root}.all"
        vs.copy(f"t6.{base}.g3_4.met", "t6", f"{a}.g3_4.met")
        vs.copy(f"t6.{base}.g3_4.not_met", "t6", f"{a}.g3_4.not_met")
        vs.copy(f"t6.{base}.g3_4.unknown", "t6", f"{a}.g3_4.unknown")
        vs.copy(f"t6.{base}.g3_5.not_met", "t6", f"{a}.g3_5_each.not_met")
        vs.derive(
            f"t6.{base}.g3_5.pairs",
            get(vs.data["t6"], f"{a}.g3_5_each.met")
            + get(vs.data["t6"], f"{a}.g3_5_each.not_met"),
            f"t6 {a}.g3_5_each: met + not_met",
        )
        vs.copy(f"t6.{base}.benchmarks", "t6", f"{a}.benchmarks")
    for base in ("sqlfluffrs", "new-parser-low"):
        sp = f"bases.{base}.lex_parse_speedup.parse"
        vs.copy(f"t6.{base}.speedup.needed", "t6", f"{sp}.needed")
        vs.copy(
            f"t6.{base}.speedup.median",
            "t6",
            f"{sp}.median_factor",
            text=lambda v: f"{v:.2f}",
        )
        vs.copy(
            f"t6.{base}.speedup.max",
            "t6",
            f"{sp}.max_factor",
            text=lambda v: f"{v:.2f}",
        )
    for c in ("start", "parse", "lint", "fix"):
        vs.copy(
            f"t6.sqruff.{c}.over_sqlfluff",
            "t6",
            f"bases.sqruff.summary.{c}.g3_4.median_ratio",
            text=fmt_ratio,
        )
    for c in ("start", "parse"):
        vs.copy(
            f"t6.sqlfluffrs.{c}.over_sqlfluff",
            "t6",
            f"bases.sqlfluffrs.summary.{c}.g3_4.median_ratio",
            text=fmt_ratio,
        )
    vs.copy("t6.sqruff.not_valid", "t6", "bases.sqruff.not_valid.count")
    vs.copy(
        "t5.parse_large.median",
        "t5",
        "speed.summary.[parse/large].probe_over_sqruff.median_ratio",
        text=fmt_ratio,
    )
    vs.copy(
        "t5.parse_large.faster",
        "t5",
        "speed.summary.[parse/large].probe_over_sqruff.probe_faster",
    )
    vs.copy(
        "t5.parse_large.pairs",
        "t5",
        "speed.summary.[parse/large].probe_over_sqruff.pairs",
    )
    vs.copy(
        "t5.parse.share",
        "t5",
        "speed.summary.[parse/large].probe_phases.share.parse_s",
        text=lambda v: f"{v:.2f}",
    )
    vs.copy(
        "t8.setup_share",
        "t8",
        "G3_start.bases.sqlfluffrs.value.setup_share_of_probe_start",
        text=lambda v: f"{v:.2f}",
    )


# C6: license, size, and structure.


def license_values(vs: Values) -> None:
    b = "bases"
    vs.copy("t7.sqruff.spdx", "t7", f"{b}.sqruff.license.spdx")
    vs.copy("t7.sqlfluffrs.spdx", "t7", f"{b}.sqlfluffrs.license.spdx")
    vs.copy("t7.new-parser.spdx", "t7", f"{b}.new-parser.license.spdx")
    vs.copy("t7.sqruff.hand", "t7", f"{b}.sqruff.size.totals.hand_written")
    vs.copy("t7.sqruff.generated", "t7", f"{b}.sqruff.size.totals.generated")
    vs.copy("t7.sqlfluffrs.hand", "t7", f"{b}.sqlfluffrs.size.totals.hand_written")
    vs.copy("t7.sqlfluffrs.generated", "t7", f"{b}.sqlfluffrs.size.totals.generated")
    vs.copy("t7.new-parser.engine", "t7", f"{b}.new-parser.size.hand_written_engine")
    vs.copy("t7.new-parser.rules", "t7", f"{b}.new-parser.size.hand_written_rules")
    vs.copy("t7.new-parser.generated", "t7", f"{b}.new-parser.size.generated")
    vs.copy("t7.sqruff.packages", "t7", f"{b}.sqruff.dependencies.installed.packages")
    vs.copy(
        "t7.sqlfluffrs.packages",
        "t7",
        f"{b}.sqlfluffrs.dependencies.standalone.packages",
    )
    for base, profile in (("sqruff", "installed"), ("sqlfluffrs", "standalone")):
        by = get(vs.data["t7"], f"{b}.{base}.dependencies.{profile}.by_class")
        if by["permissive"] != vs.v(f"t7.{base}.packages"):
            raise DataError(f"T7: a {base} dependency is not permissive")
    vs.copy(
        "t7.sqruff.port_lag",
        "t7",
        f"{b}.sqruff.sqlfluff_attribution.history_of_that_commit.commits_only_in_pin",
    )
    vs.copy(
        "t7.sqruff.fixture_copies",
        "t7",
        f"{b}.sqruff.sqlfluff_attribution.crate_data_files_equal_to_sqlfluff_fixtures",
        text=lambda v: str(sum(v.values())),
    )
    vs.copy(
        "t7.sqruff.node_matchers",
        "t7",
        f"{b}.sqruff.structure.values.node_matchers_in_dialect_modules",
    )
    vs.copy("t7.sqruff.rule_files", "t7", f"{b}.sqruff.structure.values.rule_files")
    vs.copy("t7.sqruff.rule_lines", "t7", f"{b}.sqruff.structure.values.rule_lines")
    lib = get(vs.data["t7"], f"{b}.sqruff.size.crates.sqruff-lib")
    vs.estimate(
        "sqruff.rule_layer_lines",
        lib["hand_written"]["lines"] - lib["hand_written_src_by_dir"]["src/templaters"],
        "t7 bases.sqruff.size.crates.sqruff-lib: hand_written.lines - "
        "hand_written_src_by_dir[src/templaters]",
        "The rule layer of sqruff (rules, reflow and fix utilities, linter core, "
        "config) is the crate sqruff-lib without its templaters. Options 2 and 3 "
        "need a rule layer of this kind.",
    )
    vs.copy(
        "t7.sqlfluff.rule_python_lines",
        "t7",
        f"{b}.new-parser.input_python_lines.rules.lines",
    )
    vs.copy("t7.open_questions", "t7", "open_questions", text=lambda v: str(len(v)))
    if vs.v("t7.sqruff.rule_files") != vs.v("t4.rules"):
        raise DataError("T7 and T4: another sqruff rule count")


# C7: capabilities.


def capability_values(vs: Values) -> None:
    d = vs.data["t8"]
    rows = {r["templater"]: r for r in get(d, "S6.templaters")}
    native = {
        base: [t for t in S6_TEMPLATERS if rows[t][base]["value"]["native"]]
        for base in ("sqruff", "sqlfluffrs", "new-parser")
    }
    vs.derive(
        "s6.templaters", len(S6_TEMPLATERS), "raw, placeholder, python, jinja (S6)"
    )
    for base, names in native.items():
        vs.derive(
            f"t8.{base}.native_templaters",
            len(names),
            f"t8 S6.templaters[raw, placeholder, python, jinja].{base}.value.native",
        )
        vs.derive(
            f"t8.{base}.templaters_to_write",
            len(S6_TEMPLATERS) - len(names),
            f"s6.templaters - t8.{base}.native_templaters",
        )
    vs.copy(
        "t8.templater.no_python_cases",
        "t8",
        "S6.templater_suite.sqruff.value.no_python_cases",
    )
    vs.copy(
        "t8.templater.no_python_pass",
        "t8",
        "S6.templater_suite.sqruff.value.no_python_pass",
    )
    styles = get(d, "S6.placeholder_styles.rows")
    vs.derive(
        "t8.placeholder.styles", len(styles), "len(t8 S6.placeholder_styles.rows)"
    )
    vs.derive(
        "t8.placeholder.sqruff",
        sum(
            r["sqruff"]["value"]["exists"] and r["sqruff"]["value"]["same_pattern"]
            for r in styles
        ),
        "t8 S6.placeholder_styles.rows with sqruff.value exists and same_pattern",
    )
    commands = get(d, "S7.commands")
    flu = [c["command"] for c in commands if c["sqlfluff"]["value"]]
    both = [
        c["command"]
        for c in commands
        if c["sqlfluff"]["value"] and c["sqruff"]["value"]
    ]
    vs.derive("t8.commands.sqlfluff", len(flu), "t8 S7.commands with sqlfluff.value")
    vs.derive(
        "t8.commands.sqruff",
        len(both),
        "t8 S7.commands with sqlfluff.value and sqruff.value",
    )
    vs.derive(
        "t8.commands.missing",
        len(flu) - len(both),
        "t8.commands.sqlfluff - t8.commands.sqruff",
    )
    opts = get(d, "S7.options")
    if sorted(opts) != sorted(both):
        raise DataError("T8: the option lists are not those of the shared commands")
    n_flu = sum(o["value"]["sqlfluff"] for o in opts.values())
    n_both = sum(len(o["value"]["both"]) for o in opts.values())
    vs.derive("t8.options.sqlfluff", n_flu, "sum of t8 S7.options.*.value.sqlfluff")
    vs.derive("t8.options.sqruff", n_both, "sum of len(t8 S7.options.*.value.both)")
    vs.derive(
        "t8.options.missing", n_flu - n_both, "t8.options.sqlfluff - t8.options.sqruff"
    )
    vs.copy("t8.keys.sqlfluff", "t8", "S7.config_keys.sqlfluff_defaults.value")
    vs.copy("t8.keys.sqruff", "t8", "S7.config_keys.in_both_defaults.value")
    vs.derive(
        "t8.keys.missing",
        vs.v("t8.keys.sqlfluff") - vs.v("t8.keys.sqruff"),
        "t8.keys.sqlfluff - t8.keys.sqruff",
    )
    vs.copy(
        "t8.unsupported_settings",
        "t8",
        "S7.config_keys.s1_unsupported_settings.value.cases",
    )
    flu_files = get(d, "S7.config.files_in_each_folder.sqlfluff.value")
    sq_files = get(d, "S7.config.files_in_each_folder.sqruff.value.read")
    vs.derive(
        "t8.config_files.sqlfluff",
        len(flu_files),
        "len(t8 S7.config.files_in_each_folder.sqlfluff.value)",
    )
    vs.derive(
        "t8.config_files.sqruff",
        len(set(flu_files) & set(sq_files)),
        "the sqlfluff config files that sqruff reads (t8 S7.config.files_in_each_folder)",
    )
    vs.copy("t8.placeholder.sqlfluffrs", "t8", "tables.S6.rows.6.4")
    vs.copy("t8.syntax_kinds", "t8", "G2_S8.typed_tree.sqruff.value.syntax_kinds")
    vs.copy("t8.parameter_styles.sqruff", "t8", "G2_S8.parameter_styles.sqruff.value")
    if vs.v("t8.syntax_kinds") != get(
        vs.data["t7"], "bases.sqruff.structure.values.syntax_kind_variants"
    ):
        raise DataError("T8 and T7: another SyntaxKind count")


# Tables of the decision record.


def of(vs: Values, a: str, b: str) -> str:
    return f"{vs.t(a)} of {vs.t(b)}"


def tables(vs: Values) -> dict:
    t = {}
    flu = [
        "sqlfluff 4.4.0 (reference)",
        of(vs, "s1.sqlfluff.exact", "s1.sqlfluff.dialects.total"),
        of(vs, "s1.sqlfluff.no_unparsable", "s1.sqlfluff.dialects.total"),
        *[
            of(vs, f"s1.sqlfluff.{s}.pass", f"s1.sqlfluff.{s}.total")
            for s in SUITES[1:]
        ],
        "Python",
    ]
    sq = [
        f"{vs.t('option.sqruff')} sqruff",
        of(vs, "t2.sqruff.exact", "t2.sqruff.dialects.total"),
        of(vs, "t2.sqruff.no_unparsable", "t2.sqruff.dialects.total"),
        *[of(vs, f"t2.sqruff.{s}.pass", f"t2.sqruff.{s}.total") for s in SUITES[1:]],
        "native; Jinja in Python",
    ]
    rs = [
        f"{vs.t('option.sqlfluffrs')} sqlfluffrs in S1 (`sqlfluff-rs`)",
        of(vs, "t2.sqlfluffrs.exact", "t2.sqlfluffrs.dialects.total"),
        of(vs, "t2.sqlfluffrs.no_unparsable", "t2.sqlfluffrs.dialects.total"),
        *[
            of(vs, f"t2.sqlfluffrs.{s}.pass", f"t2.sqlfluffrs.{s}.total")
            for s in SUITES[1:]
        ],
        f"Python sqlfluff calls the Rust parser; {vs.t('sqlfluffrs.rules_in_python')} "
        f"of {vs.t('t2.rule_codes')} rules in Python",
    ]
    native = [
        f"{vs.t('option.sqlfluffrs')} sqlfluffrs native (T5 probe)",
        of(vs, "t5.native.exact", "t5.native.cases"),
        of(vs, "t5.native.no_unparsable", "t5.native.cases"),
        "no data",
        "no data",
        "no data",
        "native, no Python",
    ]
    new = [
        f"{vs.t('option.new-parser')} new parser",
        *["no data"] * 5,
        "no implementation",
    ]
    t["s1"] = {
        "columns": [
            "Base",
            "Dialects: exact tree",
            "Dialects: no unparsable",
            "Rule cases",
            "Autofix",
            "Templater",
            "How it runs",
        ],
        "rows": [flu, sq, rs, native, new],
    }
    t["failures"] = {
        "columns": ["sqruff failures", "Cases", "Classes (T3, T4)"],
        "rows": [
            [
                "Tree mismatches (dialects, templater)",
                vs.t("t3.cases"),
                ", ".join(
                    f"{n} {vs.t(f't3.class.{n}')}"
                    for n in (
                        "extra_wrapper",
                        "renamed",
                        "missing_wrapper",
                        "unparsable",
                        "leaf_type",
                    )
                )
                + " (a case can have more than one class)",
            ],
            [
                "Rule, autofix, and templater failures",
                vs.t("t4.failures"),
                ", ".join(
                    f"{n} {vs.t(f't4.total.{n}')}"
                    for n in ("unsupported_item", "parse_cause", "rule_logic")
                ),
            ],
        ],
    }
    t["speed"] = {
        "columns": [
            "Base",
            *[f"{c} / sqruff" for c in COMMANDS],
            "Faster than sqlfluff (G3.4)",
            "Slower than sqruff (G3.5, pairs)",
            "Kind",
        ],
        "rows": [
            [
                label,
                *[vs.t(f"t6.{b}.{c}.total") for c in COMMANDS],
                of(vs, f"t6.{b}.g3_4.met", f"t6.{b}.benchmarks"),
                of(vs, f"t6.{b}.g3_5.not_met", f"t6.{b}.g3_5.pairs"),
                SPEED_KIND[b],
            ]
            for b, label in SPEED_BASES.items()
        ],
    }
    t["license"] = {
        "columns": [
            "Base",
            "License",
            "Hand-written lines",
            "Generated lines",
            "Dependencies",
        ],
        "rows": [
            [
                f"{vs.t('option.sqruff')} sqruff",
                vs.t("t7.sqruff.spdx"),
                vs.t("t7.sqruff.hand"),
                vs.t("t7.sqruff.generated"),
                f"{vs.t('t7.sqruff.packages')} packages, all permissive",
            ],
            [
                f"{vs.t('option.sqlfluffrs')} sqlfluffrs",
                vs.t("t7.sqlfluffrs.spdx"),
                vs.t("t7.sqlfluffrs.hand"),
                vs.t("t7.sqlfluffrs.generated"),
                f"{vs.t('t7.sqlfluffrs.packages')} packages, all permissive",
            ],
            [
                f"{vs.t('option.new-parser')} new parser",
                f"{vs.t('t7.new-parser.spdx')} (the input)",
                f"{vs.t('t7.new-parser.engine')} engine and "
                f"{vs.t('t7.new-parser.rules')} rules (estimate)",
                f"{vs.t('t7.new-parser.generated')} (estimate)",
                "no implementation",
            ],
        ],
    }
    t["capabilities"] = {
        "columns": ["Item", "1 sqruff", "2 sqlfluffrs", "3 new parser"],
        "rows": [
            [
                "S6 native templaters (raw, placeholder, python, jinja)",
                f"{of(vs, 't8.sqruff.native_templaters', 's6.templaters')}: raw, placeholder",
                of(vs, "t8.sqlfluffrs.native_templaters", "s6.templaters"),
                of(vs, "t8.new-parser.native_templaters", "s6.templaters")
                + " (estimate)",
            ],
            [
                "S6, G2.3 placeholder styles of sqlfluff",
                of(vs, "t8.placeholder.sqruff", "t8.placeholder.styles"),
                of(vs, "t8.placeholder.sqlfluffrs", "t8.placeholder.styles"),
                of(vs, "t8.placeholder.sqlfluffrs", "t8.placeholder.styles")
                + " (estimate)",
            ],
            [
                "S7 sqlfluff commands",
                of(vs, "t8.commands.sqruff", "t8.commands.sqlfluff"),
                "no CLI",
                "no CLI",
            ],
            [
                "S7 option names of the shared commands",
                of(vs, "t8.options.sqruff", "t8.options.sqlfluff"),
                "no CLI",
                "no CLI",
            ],
            [
                "S7 sqlfluff config files, default keys",
                f"{of(vs, 't8.config_files.sqruff', 't8.config_files.sqlfluff')}; "
                f"{of(vs, 't8.keys.sqruff', 't8.keys.sqlfluff')}",
                "no config reader",
                "no config reader",
            ],
            [
                "G2 segment type",
                f"`SyntaxKind` enum ({vs.t('t8.syntax_kinds')} kinds)",
                "string",
                "enum from the generator (estimate)",
            ],
            ["G2.2 schema output", "no", "no", "no"],
        ],
    }
    t["work"] = {
        "columns": ["Goal or stone", "1 sqruff", "2 sqlfluffrs", "3 new parser"],
        "rows": [
            [
                "S4 trees",
                f"{vs.t('t3.dialect_cases')} dialect cases in {vs.t('t3.groups')} groups; "
                f"top {vs.t('t3.top50.n')} groups: {vs.t('t3.top50.share')} of "
                f"the cases; "
                f"{vs.t('t3.unique_fix')} cases need their own fix; by hand in "
                f"{vs.t('t7.sqruff.node_matchers')} node matchers",
                f"{vs.t('t5.cases_to_fix')} cases "
                f"({of(vs, 't5.native.exact', 't5.native.cases')} native)",
                f"an engine of about {vs.t('t7.new-parser.engine')} lines; "
                f"{vs.t('t5.native.cases')} cases to pass; generator reuse with "
                f"{vs.t('t5.new_emitter_lines.a')} or {vs.t('t5.emitter_lines')} new lines",
            ],
            [
                "S5 rules",
                f"{vs.t('t4.failures.rules')} rule and {vs.t('t4.failures.autofix')} "
                f"autofix failures; {vs.t('sqruff.rules_missing')} rules to add "
                f"({vs.t('sqruff.rules_missing_names')}); after S4, "
                f"{vs.t('t4.rules_changed')} of {vs.t('t4.rules')} rules see a "
                f"changed tree",
                f"{vs.t('sqlfluffrs.rules_in_python')} of {vs.t('t2.rule_codes')} "
                f"rules and the fixes; a rule layer of about "
                f"{vs.t('sqruff.rule_layer_lines')} lines",
                f"{vs.t('t2.rule_codes')} of {vs.t('t2.rule_codes')} rules and the "
                f"fixes; else as option 2",
            ],
            [
                "S6 templaters",
                f"{vs.t('t8.sqruff.templaters_to_write')} native templaters to "
                f"write (jinja, python)",
                f"{vs.t('t8.sqlfluffrs.templaters_to_write')} native templaters to "
                f"write; the source map exists",
                f"{vs.t('t8.new-parser.templaters_to_write')} native templaters to "
                f"write; the source map of option 2",
            ],
            [
                "S7 CLI and config",
                f"{vs.t('t8.commands.missing')} commands, "
                f"{vs.t('t8.options.missing')} option names, "
                f"{vs.t('t8.keys.missing')} default keys",
                f"{vs.t('t8.commands.sqlfluff')} commands, "
                f"{vs.t('t8.options.sqlfluff')} option names, "
                f"{vs.t('t8.keys.sqlfluff')} default keys",
                "as option 2",
            ],
            [
                "G2 code generation",
                "typed node view, schema output",
                "segment enum, typed node view, schema output",
                "typed node view, schema output",
            ],
            [
                "G3 speed",
                f"all / sqruff {vs.t('t6.sqruff.all.total')} must go below "
                f"{vs.t('g3.limit')}; "
                f"{vs.t('t6.sqruff.not_valid')} results not valid",
                f"lex and parse faster by a median {vs.t('t6.sqlfluffrs.speedup.median')} "
                f"(at most {vs.t('t6.sqlfluffrs.speedup.max')}) on "
                f"{vs.t('t6.sqlfluffrs.speedup.needed')} parse benchmarks",
                f"low bound: {vs.t('t6.new-parser-low.speedup.median')} "
                f"(at most {vs.t('t6.new-parser-low.speedup.max')}) on "
                f"{vs.t('t6.new-parser-low.speedup.needed')} parse benchmarks",
            ],
            [
                "G1.2, G4 new sqlfluff version",
                f"port the grammar by hand; the port is {vs.t('t7.sqruff.port_lag')} "
                f"commits before the pin",
                f"generate the tables again ({vs.t('t5.generation.files')} files in "
                f"{vs.t('t5.generation.wall_s')} s)",
                "as option 2",
            ],
        ],
    }
    return t


def render(table: dict) -> list[str]:
    lines = ["| " + " | ".join(table["columns"]) + " |"]
    lines.append("|" + "---|" * len(table["columns"]))
    for row in table["rows"]:
        if len(row) != len(table["columns"]):
            raise DataError(f"a row with {len(row)} cells: {row[0]}")
        lines.append("| " + " | ".join(row) + " |")
    return lines


def make_report(paths: dict[str, Path] | None = None) -> dict:
    data = load(paths)
    vs = Values(data)
    s1_values(vs)
    sqruff_values(vs)
    probe_values(vs)
    speed_values(vs)
    license_values(vs)
    capability_values(vs)
    tabs = tables(vs)
    inputs = {
        rel: sha256_file((paths or {}).get(name, phase_a.read_path(rel)))
        for name, rel in INPUTS.items()
    }
    return {
        "kind": "sqll-s3-decision-data",
        "format": 1,
        "task": "T9",
        "criterion": "C8",
        "command": COMMAND,
        "inputs": inputs,
        "rules": RULES,
        "estimate_limits": ESTIMATE_LIMITS,
        "values": vs.items,
        "tables": {
            name: {**tab, "markdown": render(tab)} for name, tab in tabs.items()
        },
    }


# Output: one line for each object of scalars and each short value.


def _flat(value: dict) -> bool:
    return not any(isinstance(v, dict | list) for v in value.values())


def dumps(value, indent: int = 0) -> str:
    pad = " " * (indent + 1)
    long = len(json.dumps(value)) > 100
    if isinstance(value, dict) and value and long and not _flat(value):
        items = [
            f"{pad}{json.dumps(k)}: {dumps(v, indent + 1)}" for k, v in value.items()
        ]
        return "{\n" + ",\n".join(items) + "\n" + " " * indent + "}"
    if isinstance(value, list) and value and long:
        items = [pad + dumps(v, indent + 1) for v in value]
        return "[\n" + ",\n".join(items) + "\n" + " " * indent + "]"
    return json.dumps(value, ensure_ascii=False)


def text(value: dict) -> str:
    return dumps(value) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="decision_data.py")
    p.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    try:
        new = text(make_report())
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        rel = OUT_FILE.resolve().relative_to(ROOT)
    except ValueError:
        rel = OUT_FILE
    if args.check:
        if not OUT_FILE.exists() or OUT_FILE.read_text("utf8") != new:
            print(f"error: {rel} is not the output of the inputs")
            return 1
        print(f"{rel}: no change")
        return 0
    OUT_FILE.write_text(new, "utf8")
    print(f"wrote {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
