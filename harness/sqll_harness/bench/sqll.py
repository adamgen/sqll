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

The base binary of a speed check (sqll-base) can be a build from before
S3b C11, which reads no config file: the speed check of the S3b exit (C17)
has the S3 exit as its base. For such a binary (its parse help has no
--config) the adapter gives the settings as options (legacy_options), as
the adapter did before C11. Only sqll-base does this.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from ..adapters.base import EmptyHome, Unsupported, isolated_env
from ..adapters.sqlfluff import CONFIG_NAME, sqlfluff_toml
from ..adapters.sqll import SqllAdapter, base_binary_path
from .adapter import FIX, LINT, PARSE, BenchAdapter
from .inputs import START
from .tools import SqlfluffBench, parse_record

LEGACY_OPTIONS_NAME = "sqll-options.json"
# A binary from before S3b C11: the settings that it does with no option,
# and the only value of each (raw templater, no file size limit, no rule).
LEGACY_FIXED: dict[tuple[str, str], Any] = {
    ("core", "templater"): "raw",
    ("core", "rules"): "all",
    ("core", "large_file_skip_byte_limit"): 0,
    ("core", "large_file_skip_char_limit"): 0,
}
_NO_VALUE = object()


def legacy_options(config: dict[str, Any]) -> list[str]:
    """The parse options of config for a sqll binary from before S3b C11:
    core.dialect gives --dialect, core.max_parse_depth --max-parse-depth,
    a LEGACY_FIXED setting must have its value, and each other setting
    raises Unsupported."""
    args: list[str] = []
    for section, values in config.items():
        if not isinstance(values, dict):
            raise Unsupported(f"setting {section}")
        for key, value in values.items():
            if section == "core" and key == "dialect":
                if not isinstance(value, str) or not value:
                    raise Unsupported(f"setting core.dialect = {value!r}")
                args += ["--dialect", value]
            elif section == "core" and key == "max_parse_depth" and type(value) is int:
                args += ["--max-parse-depth", str(value)]
            else:
                want = LEGACY_FIXED.get((section, key), _NO_VALUE)
                if want is _NO_VALUE:
                    raise Unsupported(f"setting {section}.{key}")
                if type(value) is not type(want) or value != want:
                    raise Unsupported(f"setting {section}.{key} = {value!r}")
    return args


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

    def unsupported_command(self, command: str, config: dict[str, Any]) -> str | None:
        if command not in self.commands:
            return command
        if command in (LINT, FIX):
            have, every = self.s1.rules()
            rules = selected_rules(config, every)
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
        self._reads_config: bool | None = None

    def reads_config(self) -> bool:
        """True if the binary reads the sqlfluff config (S3b C11): its parse
        help has --config."""
        if self._reads_config is None:
            try:
                out = subprocess.run(
                    [str(self.s1.binary), "parse", "--help"],
                    capture_output=True,
                    text=True,
                    env=self.env(),
                    timeout=60,
                    check=False,
                ).stdout
            except OSError:
                # No binary: the run fails later with its own reason.
                return True
            self._reads_config = "--config" in out
        return self._reads_config

    def unsupported(self, config: dict[str, Any]) -> str | None:
        if self.reads_config():
            return super().unsupported(config)
        try:
            legacy_options(config)
        except Unsupported as exc:
            return exc.item
        return None

    def write_config(self, config: dict[str, Any], folder: Path) -> Path:
        if self.reads_config():
            return super().write_config(config, folder)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / LEGACY_OPTIONS_NAME
        path.write_text(json.dumps(legacy_options(config)), encoding="utf8")
        return path

    def argv(self, command: str, config_file: Path, sql: str) -> list[str]:
        if Path(config_file).name != LEGACY_OPTIONS_NAME:
            return super().argv(command, config_file, sql)
        if command not in (START, PARSE):
            raise ValueError(f"a sqll binary from before C11 has no {command} command")
        args = json.loads(Path(config_file).read_text(encoding="utf8"))
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError(f"{config_file}: not a list of options")
        return [str(self.s1.binary), *self.commands[command], *args, sql]
