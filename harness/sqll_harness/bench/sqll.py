"""The benchmark adapter of sqll (S3 T13; harness/sqll.md, harness/bench.md).

sqll has only the parse command until S5. start and parse run "sqll parse
-f json --dialect D input.sql". lint and fix give "unsupported: lint" and
"unsupported: fix" with no run.

sqll reads no config file. Thus write_config writes the command-line
options of the settings to config/sqll-options.json, and argv reads them.
A setting that sqll cannot do gives "unsupported: setting <section>.<key>"
and no run, so a run never ignores a setting.
"""

import json
from pathlib import Path
from typing import Any

from ..adapters.base import EmptyHome, Unsupported, isolated_env
from ..adapters.sqll import SqllAdapter, parse_options
from .adapter import PARSE, BenchAdapter
from .inputs import START
from .tools import parse_record

OPTIONS_NAME = "sqll-options.json"
# The settings that sqll does with no option, and the only value of each:
# sqll has only the raw templater and no file size limit, and its parse runs
# no rule ("all" is the sqlfluff default).
FIXED: dict[tuple[str, str], Any] = {
    ("core", "templater"): "raw",
    ("core", "rules"): "all",
    ("core", "large_file_skip_byte_limit"): 0,
    ("core", "large_file_skip_char_limit"): 0,
}
_NO_VALUE = object()


def options(config: dict[str, Any]) -> list[str]:
    """Return the sqll parse options of config (sqlfluff config structure).

    core.dialect gives --dialect, core.max_parse_depth --max-parse-depth.
    A FIXED setting must have its value. Each other setting raises
    Unsupported.
    """
    args: list[str] = []
    extra: dict[str, dict[str, Any]] = {}
    for section, values in config.items():
        if not isinstance(values, dict):
            raise Unsupported(f"setting {section}")
        for key, value in values.items():
            if section == "core" and key == "dialect":
                if not isinstance(value, str) or not value:
                    raise Unsupported(f"setting core.dialect = {value!r}")
                args += ["--dialect", value]
                continue
            want = FIXED.get((section, key), _NO_VALUE)
            if want is _NO_VALUE:
                extra.setdefault(section, {})[key] = value
            elif type(value) is not type(want) or value != want:
                raise Unsupported(f"setting {section}.{key} = {value!r}")
    return args + parse_options(extra)


class SqllBench(BenchAdapter):
    name = "sqll"
    commands = {
        START: ["parse", "-f", "json"],
        PARSE: ["parse", "-f", "json"],
    }

    def __init__(self, binary: Path | None = None) -> None:
        super().__init__()
        self.s1 = SqllAdapter(binary)

    def version(self) -> str:
        return self.s1.version()

    def unsupported_command(self, command: str) -> str | None:
        return None if command in self.commands else command

    def unsupported(self, config: dict[str, Any]) -> str | None:
        try:
            options(config)
        except Unsupported as exc:
            return exc.item
        return None

    def write_config(self, config: dict[str, Any], folder: Path) -> Path:
        args = options(config)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / OPTIONS_NAME
        path.write_text(json.dumps(args), encoding="utf8")
        return path

    def argv(self, command: str, config_file: Path, sql: str) -> list[str]:
        if command not in self.commands:
            raise ValueError(f"sqll has no {command} command")
        args = json.loads(Path(config_file).read_text(encoding="utf8"))
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError(f"{config_file}: not a list of options")
        return [str(self.s1.binary), *self.commands[command], *args, sql]

    def env(self) -> dict[str, str]:
        return isolated_env(EmptyHome.path())

    def read_tree(self, stdout: bytes, sql: str) -> Any:
        # sqll prints the record of "sqlfluff parse -f json".
        return parse_record(stdout, sql)

    def read_violations(self, stdout: bytes, sql: str) -> list[dict] | None:
        raise ValueError("sqll has no lint output (unsupported: lint)")
