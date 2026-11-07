"""The benchmark adapter of sqll (S3 T13; harness/sqll.md, harness/bench.md).

sqll has only the parse command until S5. start and parse run "sqll parse
-f json --ignore-local-config --config <config> input.sql". lint and fix
give "unsupported: lint" and "unsupported: fix" with no run.

Since S3b C11 sqll reads the sqlfluff config. Thus write_config writes the
settings as the sqlfluff adapter does (config/pyproject.toml), and sqll
reads them as sqlfluff does. A setting that sqll cannot do stops the run
with exit code 2 ("unsupported: ..."), so a run never ignores a setting.

The base binary of a speed check (sqll-base) can be a build from before
C11, which reads no config file. For such a binary the adapter gives the
settings as options (legacy_options), as before C11.
"""

import json
import subprocess
from pathlib import Path
from typing import Any

from ..adapters.base import EmptyHome, Unsupported, isolated_env
from ..adapters.sqlfluff import CONFIG_NAME, sqlfluff_toml
from ..adapters.sqll import SqllAdapter, base_binary_path
from .adapter import PARSE, BenchAdapter
from .inputs import START
from .tools import parse_record

LEGACY_OPTIONS_NAME = "sqll-options.json"
# A binary from before C11: the settings that it does with no option, and
# the only value of each (raw templater, no file size limit, no rule).
LEGACY_FIXED: dict[tuple[str, str], Any] = {
    ("core", "templater"): "raw",
    ("core", "rules"): "all",
    ("core", "large_file_skip_byte_limit"): 0,
    ("core", "large_file_skip_char_limit"): 0,
}
_NO_VALUE = object()


def legacy_options(config: dict[str, Any]) -> list[str]:
    """The parse options of config for a sqll binary from before C11:
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


class SqllBench(BenchAdapter):
    name = "sqll"
    commands = {
        START: ["parse", "-f", "json"],
        PARSE: ["parse", "-f", "json"],
    }

    def __init__(self, binary: Path | None = None) -> None:
        super().__init__()
        self.s1 = SqllAdapter(binary)
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

    def version(self) -> str:
        return self.s1.version()

    def unsupported_command(self, command: str) -> str | None:
        return None if command in self.commands else command

    def unsupported(self, config: dict[str, Any]) -> str | None:
        try:
            if self.reads_config():
                sqlfluff_toml(config)
            else:
                legacy_options(config)
        except Unsupported as exc:
            return exc.item
        except ValueError as exc:
            return f"setting: {exc}"
        return None

    def write_config(self, config: dict[str, Any], folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        if self.reads_config():
            path = folder / CONFIG_NAME
            path.write_text(sqlfluff_toml(config), encoding="utf8")
        else:
            path = folder / LEGACY_OPTIONS_NAME
            path.write_text(json.dumps(legacy_options(config)), encoding="utf8")
        return path

    def argv(self, command: str, config_file: Path, sql: str) -> list[str]:
        if command not in self.commands:
            raise ValueError(f"sqll has no {command} command")
        head = [str(self.s1.binary), *self.commands[command]]
        if Path(config_file).name == LEGACY_OPTIONS_NAME:
            args = json.loads(Path(config_file).read_text(encoding="utf8"))
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                raise ValueError(f"{config_file}: not a list of options")
            return [*head, *args, sql]
        # As the sqlfluff adapter: only the --config file.
        return [*head, "--ignore-local-config", "--config", str(config_file), sql]

    def env(self) -> dict[str, str]:
        return isolated_env(EmptyHome.path())

    def read_tree(self, stdout: bytes, sql: str) -> Any:
        # sqll prints the record of "sqlfluff parse -f json".
        return parse_record(stdout, sql)

    def read_violations(self, stdout: bytes, sql: str) -> list[dict] | None:
        raise ValueError("sqll has no lint output (unsupported: lint)")


class SqllBaseBench(SqllBench):
    """The base binary of a speed check (scripts/speed-check;
    harness/bench.md, "Speed check of a change"): the adapter and settings
    of sqll, with the binary SQLL_BASE_BIN. Thus the base and the head of a
    change run in one report."""

    name = "sqll-base"

    def __init__(self, binary: Path | None = None) -> None:
        super().__init__(binary or base_binary_path())
