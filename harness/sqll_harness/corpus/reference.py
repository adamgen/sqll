"""The render of a templated corpus file by the pinned sqlfluff
(docs/decisions/s9-corpus.md, "Templated files").

The leaf text of a tree of a templated file is the render, not the input.
Thus the parse check compares it with the render of the pinned sqlfluff
(the reference). render() runs the Python of the sqlfluff tool venv once
for a file, with the config file of the sqlfluff benchmark adapter and the
corpus settings. It does the steps of "sqlfluff render" and "sqlfluff
parse" (load the file and its config, then render) and writes the render
of each variant as JSON, so no output format can change the text. The
parse tree is that of the first variant, so the reference is that variant.
If the render has a templater error or no variant, there is no reference.
"""

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from ..bench.tools import SqlfluffBench
from .manifest import CorpusFile

# argv: config file, SQL file. Output: {"variants": [...], "errors": [...]}.
RENDER_SCRIPT = """
import json, sys
from sqlfluff.core import FluffConfig, Linter
config = FluffConfig.from_root(extra_config_path=sys.argv[1], ignore_local_config=True)
linter = Linter(config=config)
raw, file_config, _ = linter.load_raw_file_and_config(sys.argv[2], linter.config)
file_config.process_raw_file_for_config(raw, sys.argv[2])
rendered = linter.render_string(raw, sys.argv[2], file_config, "utf8")
json.dump(
    {
        "variants": [v.templated_str for v in rendered.templated_variants],
        "errors": [str(e) for e in rendered.templater_violations],
    },
    sys.stdout,
)
"""
INPUT_FILE = "input.sql"
REASON_TEXT = 300

# render(entry, data, config, folder) returns (render, None), or (None,
# reason) if there is no reference. config: the corpus settings of the
# reference tool for the file.
Render = Callable[[CorpusFile, bytes, dict, Path], tuple[str | None, str | None]]


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
        config_file = self.adapter.write_config(config, folder / "config")
        (folder / INPUT_FILE).write_bytes(data)
        python = self.adapter.s1.venv / "bin" / "python"
        try:
            proc = subprocess.run(
                [str(python), "-I", "-c", RENDER_SCRIPT, str(config_file), INPUT_FILE],
                cwd=folder,
                capture_output=True,
                env=self.adapter.env(),
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired:
            return None, f"the render did not stop in {self.timeout_s} s"
        finally:
            (folder / INPUT_FILE).unlink(missing_ok=True)
        if proc.returncode != 0:
            tail = proc.stderr.decode("utf8", "replace").strip()[-REASON_TEXT:]
            return None, f"the render failed: exit code {proc.returncode}: {tail}"
        try:
            out = json.loads(proc.stdout)
            variants, errors = out["variants"], out["errors"]
        except (ValueError, KeyError, TypeError) as exc:
            return None, f"the render output cannot be read: {exc!r}"[:REASON_TEXT]
        if errors:
            text = "; ".join(str(e) for e in errors)
            return None, f"the render has a templater error: {text}"[:REASON_TEXT]
        if not variants or not isinstance(variants[0], str):
            return None, "the render has no variant"
        return variants[0], None
