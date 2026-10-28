"""The render of a templated corpus file by the pinned sqlfluff
(docs/decisions/s9-corpus.md, "Templated files").

The leaf text of a tree of a templated file is the render, not the input.
Thus the parse check compares it with the render of the pinned sqlfluff
(the reference). render() runs "sqlfluff render" once for a file through
the sqlfluff binary (G1.5), with the config file of the sqlfluff benchmark
adapter and the corpus settings. The parse tree is that of the first
render variant. The reference config also sets render_variant_limit = 1,
so that the output is only that variant, with no variant headers; the
first variant does not change. The command prints the render and a new
line. A templater error gives exit code 1 and no reference.
"""

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from ..adapters.sqruff_config import nested_combine
from ..bench.tools import SqlfluffBench
from .manifest import CorpusFile

INPUT_FILE = "input.sql"
REASON_TEXT = 300
# "sqlfluff render" prints this line before each variant if there are more.
VARIANTS_HEADER = b"SQLFluff rendered "
ONE_VARIANT = {"core": {"render_variant_limit": 1}}

# render(entry, data, config, folder) returns (render, None), or (None,
# reason) if there is no reference. config: the corpus settings of the
# reference tool for the file.
Render = Callable[[CorpusFile, bytes, dict, Path], tuple[str | None, str | None]]


def _tail(data: bytes) -> str:
    return data.decode("utf8", errors="replace").strip()[-REASON_TEXT:]


class SqlfluffRender:
    """The reference render of the pinned sqlfluff (the S2 reference tool)."""

    def __init__(self, adapter: SqlfluffBench | None = None, timeout_s=1200.0):
        self.adapter = adapter or SqlfluffBench()
        self.timeout_s = timeout_s

    def __call__(
        self, entry: CorpusFile, data: bytes, config: dict, folder: Path
    ) -> tuple[str | None, str | None]:
        if folder.exists():
            shutil.rmtree(folder)
        config = nested_combine(config, ONE_VARIANT)
        config_file = self.adapter.write_config(config, folder / "config")
        (folder / INPUT_FILE).write_bytes(data)
        argv = [
            str(self.adapter.s1.binary),
            "render",
            "--ignore-local-config",
            "--nocolor",
            "--config",
            str(config_file),
            INPUT_FILE,
        ]
        try:
            proc = subprocess.run(
                argv,
                cwd=folder,
                capture_output=True,
                env=self.adapter.env(),
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired:
            return None, f"the render did not stop in {self.timeout_s} s"
        finally:
            (folder / INPUT_FILE).unlink(missing_ok=True)
        out = proc.stdout
        if proc.returncode != 0:
            text = _tail(out + b"\n" + proc.stderr)
            return None, f"the render failed: exit code {proc.returncode}: {text}"
        if not out.endswith(b"\n") or out.startswith(VARIANTS_HEADER):
            return None, f"the render output is not one variant: {_tail(out)}"
        try:
            return out[:-1].decode("utf8"), None
        except UnicodeDecodeError as exc:
            return None, f"the render output is not UTF-8: {exc}"
