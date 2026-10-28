# S9 corpus

`sources.json` is the manifest of the S9 corpus: the source, commit,
license, and copyright holders of each file (G4.3). The repository has no
corpus SQL. The harness downloads each file at run time by its pinned
commit and checks its sha256. The rules: `docs/decisions/s9-corpus.md`.
The code: `harness/sqll_harness/corpus/`.

## Commands

```sh
cd harness
uv run python -m sqll_harness.corpus validate
uv run python -m sqll_harness.corpus fetch [--smoke] [--cache DIR]
```

Output: a JSON object. Exit code 2 if the manifest is not valid or the
fetch fails.

## Manifest format

```json
{
  "format": 1,
  "sources": {
    "<source id>": {
      "repository": "https://github.com/<owner>/<repo>",
      "commit": "<40 hex digits>",
      "license": "<SPDX id>",
      "copyright": ["<each copyright holder>"],
      "license_files": [{"path": "LICENSE", "bytes": 1071, "sha256": "<hex>"}],
      "globs": ["<glob of the selected paths>"],
      "note": "<optional>"
    }
  },
  "files": [
    {
      "id": "<source id>/<path>", "source": "<source id>", "path": "<path>",
      "dialect": "<sqlfluff dialect>", "templater": "raw",
      "bytes": 20000, "lines": 500, "sha256": "<hex>",
      "smoke": true, "selection": "<why the file is in>"
    }
  ]
}
```

The loader stops (fail closed) on:

- an unknown or missing key, a value of the wrong type, or a duplicate
  JSON key;
- a license that is not in the allowlist: MIT, Apache-2.0, BSD-2-Clause,
  BSD-3-Clause, PostgreSQL, ISC, CC0-1.0;
- a dialect that the pinned sqlfluff does not have;
- a repository that is not on GitHub, or a commit or sha256 that is not
  full lowercase hex;
- a path with an empty, `.`, or `..` part, or a path that matches no glob
  of its source (`*` does not match `/`, `**` matches folders);
- a duplicate id or sha256, or files that are not sorted by source and
  path;
- a size out of the range of the templater: `raw` 16 KiB to 2 MiB,
  `jinja` 8 KiB to 2 MiB;
- a `smoke` value that is not "bytes <= 32 KiB".

## Fetch

The fetch downloads each selected file, and each license and notice file
of its source, from
`https://raw.githubusercontent.com/<owner>/<repo>/<commit>/<path>`
(4 attempts, waits of 2, 4, and 8 s). It writes them to
`<cache>/<source id>/<commit>/<path>`, and a copy of the manifest to
`<cache>/_manifests/<manifest sha256>.json`. Thus the cache has the
license files and the manifest of each corpus file.

- Cache folder: `--cache`, else `$SQLL_CORPUS_CACHE`, else
  `out/corpus/cache`.
- A file goes to its cache path only if its size and sha256 are correct.
  A wrong size or sha256 stops the fetch. A corpus file must also be
  UTF-8, with the line count (`\n`) of the manifest.
- A cached file is used with no download only if its sha256 is correct.
  Else the fetch deletes it and downloads it again.
- The fetch refuses a cache folder if it, or a parent folder, has a
  sqlfluff or sqruff config file.
