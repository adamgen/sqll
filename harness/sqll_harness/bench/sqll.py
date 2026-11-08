"""The benchmark adapter of sqll (S3 T13; harness/sqll.md, harness/bench.md).

The commands are those of the sqlfluff adapter: start and parse run "sqll
parse -f json --ignore-local-config --config <config> input.sql", lint runs
"sqll lint -f json" and fix runs "sqll fix" with the same options.
write_config writes the settings as the sqlfluff adapter does
(config/pyproject.toml), and sqll reads them as sqlfluff does (S3b C11). A
setting that sqll cannot do stops the run with exit code 2 ("unsupported:
..."), so a run never ignores a setting.

lint and fix run only if sqll has each rule that the settings select (the
rules of "sqll rules", S3b C14). The S2 settings select all rules ("rules =
all"), and sqll does not have them all, so lint and fix are unsupported
with no run.
"""

import re
from pathlib import Path
from typing import Any

from ..adapters.base import EmptyHome, isolated_env
from ..adapters.sqlfluff import CONFIG_NAME, sqlfluff_toml
from ..adapters.sqll import SqllAdapter, base_binary_path
from .adapter import FIX, LINT, PARSE, BenchAdapter
from .inputs import START
from .tools import SqlfluffBench, parse_record


def selected_rules(config: dict[str, Any], every: frozenset[str]) -> list[str]:
    """The rules that the settings select: core.rules ("all", or references
    separated by ",") without core.exclude_rules. A reference that is not a
    code (a name, a group, or an alias) stays as it is, so it is never a
    rule that sqll has."""

    def refs(value: Any) -> list[str]:
        if isinstance(value, str):
            return [r.strip() for r in value.split(",") if r.strip()]
        if isinstance(value, list):
            return [str(r).strip() for r in value]
        return [str(value)]

    core = config.get("core", {})
    chosen = refs(core.get("rules", "all"))
    if "all" in chosen:
        chosen = sorted(every) + [r for r in chosen if r != "all"]
    excluded = set(refs(core["exclude_rules"])) if "exclude_rules" in core else set()
    return [r for r in chosen if r not in excluded]


class SqllBench(BenchAdapter):
    name = "sqll"
    problems = (
        # sqll fails closed on an item that it cannot do (exit code 2).
        (re.compile(r"^Error: unsupported: ", re.M), "sqll does not support an item"),
    )
    commands = {
        START: ["parse", "-f", "json"],
        PARSE: ["parse", "-f", "json"],
        LINT: ["lint", "-f", "json"],
        FIX: ["fix"],
    }

    def __init__(self, binary: Path | None = None) -> None:
        super().__init__()
        self.s1 = SqllAdapter(binary)

    def version(self) -> str:
        return self.s1.version()

    def unsupported_command(self, command: str) -> str | None:
        if command not in self.commands:
            return command
        if command in (LINT, FIX):
            have, every = self.s1.rules()
            rules = selected_rules(self.config(None), every)
            missing = [r for r in rules if r not in have]
            if missing:
                shown = ", ".join(missing[:3]) + (", ..." if len(missing) > 3 else "")
                return (
                    f"rule {shown} ({command}: sqll does not have {len(missing)} "
                    f"of the {len(rules)} rules of the settings)"
                )
        return None

    def unsupported(self, config: dict[str, Any]) -> str | None:
        try:
            sqlfluff_toml(config)
        except ValueError as exc:
            return f"setting: {exc}"
        return None

    def write_config(self, config: dict[str, Any], folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / CONFIG_NAME
        path.write_text(sqlfluff_toml(config), encoding="utf8")
        return path

    def argv(self, command: str, config_file: Path, sql: str) -> list[str]:
        if command not in self.commands:
            raise ValueError(f"sqll has no {command} command")
        # As the sqlfluff adapter: only the --config file.
        return [
            str(self.s1.binary),
            *self.commands[command],
            "--ignore-local-config",
            "--config",
            str(config_file),
            sql,
        ]

    def env(self) -> dict[str, str]:
        return isolated_env(EmptyHome.path())

    def read_tree(self, stdout: bytes, sql: str) -> Any:
        # sqll prints the record of "sqlfluff parse -f json".
        return parse_record(stdout, sql)

    def read_violations(self, stdout: bytes, sql: str) -> list[dict] | None:
        # sqll prints the records of "sqlfluff lint -f json".
        return SqlfluffBench.read_violations(self, stdout, sql)


class SqllBaseBench(SqllBench):
    """The base binary of a speed check (scripts/speed-check;
    harness/bench.md, "Speed check of a change"): the adapter and settings
    of sqll, with the binary SQLL_BASE_BIN. Thus the base and the head of a
    change run in one report."""

    name = "sqll-base"

    def __init__(self, binary: Path | None = None) -> None:
        super().__init__(binary or base_binary_path())
