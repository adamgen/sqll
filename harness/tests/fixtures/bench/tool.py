"""A test double of a SQL tool, for the benchmark adapter tests.

Usage: tool.py COMMAND CONFIG FILE, where CONFIG is a JSON file in the
sqlfluff config structure. Exit code 2 if the config does not have the
benchmark settings (harness/bench.md, "Settings").

- parse: a JSON tree; its leaves are the lines of FILE.
- lint: {FILE: [{"code": C}, ...]} with the rule codes of the sqlfluff
  reference of FILE (found by sha256 in the definitions file named by
  SQLL_DOUBLE_DEFINITIONS). Exit code 1 if there is a code.
- fix: adds a line to FILE if the reference says that fix changes it. Exit
  code 3 if FILE already has that line: the run did not get a fresh copy.
"""

import hashlib
import json
import os
import sys

MARK = "-- fixed by the test double\n"
command, config_path, sql = sys.argv[1:]
with open(config_path, encoding="utf8") as f:
    core = json.load(f)["core"]
if not core.get("dialect") or (
    core.get("templater"),
    core.get("rules"),
    core.get("large_file_skip_byte_limit"),
) != ("raw", "all", 0):
    sys.exit(2)
with open(sql, "rb") as f:
    text = f.read().decode("utf8")
with open(os.environ["SQLL_DOUBLE_DEFINITIONS"], encoding="utf8") as f:
    definitions = json.load(f)
sha = hashlib.sha256(text.encode("utf8")).hexdigest()
reference = next(
    (r for r in definitions["reference"]["inputs"].values() if r["sha256"] == sha),
    {"lint_codes": [], "fix_changes": False},
)
if command == "parse":
    lines = text.splitlines(keepends=True)
    print(json.dumps({"file": [{"line": line} for line in lines]}))
elif command == "lint":
    codes = reference["lint_codes"]
    print(json.dumps({sql: [{"code": c} for c in codes]}))
    sys.exit(1 if codes else 0)
elif command == "fix":
    if text.endswith(MARK):
        print("the file is not a fresh copy", file=sys.stderr)
        sys.exit(3)
    if reference["fix_changes"]:
        with open(sql, "ab") as f:
            f.write(MARK.encode("utf8"))
else:
    sys.exit(f"unknown command {command}")
