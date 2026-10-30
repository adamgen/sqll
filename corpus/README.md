# S9 corpus

`sources.json` is the manifest of the S9 corpus: the source, commit,
license, and copyright holders of each file (G4.3). `select.json` is the
source list that `scripts/s9/select` makes it from. The repository has no
corpus SQL. The harness downloads each file at run time by its pinned
commit and checks its sha256. The rules: `docs/decisions/s9-corpus.md`.
The code: `harness/sqll_harness/corpus/`.

## Commands

```sh
cd harness
uv run python -m sqll_harness.corpus validate
uv run python -m sqll_harness.corpus fetch [--smoke] [--cache DIR]
uv run python -m sqll_harness.corpus notices [--cache DIR] [--out DIR]
uv run python -m sqll_harness.corpus run --profile smoke|full \
    [--shard K/N] [--tool T]... [--cache DIR] [--out FILE]
uv run python -m sqll_harness.corpus merge REPORT... [--expect FILE] [--out FILE]
uv run python -m sqll_harness.corpus check REPORT [--baseline FILE [--full]]
uv run python -m sqll_harness.corpus tables REPORT
uv run python -m sqll_harness.corpus select [--download] [--check] [--cache DIR]
```

`validate`, `fetch`, and `notices` write a JSON object. Exit code 2 if the manifest is
not valid, or if a fetch, run, or merge cannot start or complete.

`run` fetches the files of the profile (smoke: 32 KiB or less) and shard,
parses each file with each tool of the bench registry (default: all, except
sqll until its corpus results after S3b: `LATER` in
`harness/sqll_harness/corpus/run.py`), and
writes the report (default `out/corpus.json`). A templated file also gets
the render of the pinned sqlfluff. The jinja settings: `templater = jinja`
and `apply_dbt_builtins = True`, with no variable, macro, or library
path. `merge` joins the shard reports; `check` checks the schema and
completeness of a report, and its stable data against a baseline. Exit
code 1 if a report has an error. `tables` prints the Markdown tables of a
report for `status/S9.md`. The report schema and the statuses:
`docs/decisions/s9-corpus.md`, "Report". The recorded baseline:
`results/S9/baseline.json`.

`notices` writes the manifest (`_sources.json`) and each license and
notice file of each source (`<source id>/<path>`, from the cache, sha256
checked) to one folder (default `out/corpus-notices`). It replaces an old
folder only if that folder has `_sources.json`. Each CI artifact with a
corpus report also has this folder.

CI (`harness/README.md`, "Shards and CI"): the `corpus-smoke` job, and on
a push to main the `corpus-full` and `corpus-merge` jobs.
`ci-shards.json` (`{"shards": N}`) is the shard count of `corpus-full`.

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

## Selection

`select.json` gives each source with the keys of the manifest
(`repository`, `commit`, `license`, `copyright`, optional `note`), the
paths of its license and notice files (`license_files`, the license
first), and `include`: a list of `{"glob", "dialect"}` with an optional
`"templater"` (default `raw`). A path must match at most one glob. The
optional `exclude` gives files to leave out, as `{"<path>": "<reason>"}`;
each path must match a glob. The manifest note of the source gets
"Excluded: <path>: <reason>" for each.

```sh
scripts/s9/select --download   # read the sources with git, write sources.json
scripts/s9/select --check      # cache only: exit code 1 if sources.json differs
```

`--download` does a shallow, blobless git fetch of each commit, and writes
to the cache `_listings/<source>/<commit>.json` (the path, size, and git
blob id of each license file and each file that matches a glob) and the
bytes of the license files and of each file in the size range. Then, with
the cache only, the selection takes the files that match a glob, sorted by
source and path, and drops an excluded file, a file out of the size range
of its templater, a file that is not UTF-8, a templated file that the Jinja
rule refuses (`not_builtins_only`, with the reason), and a file with the
sha256 of an earlier file. The Jinja rule (`jinja_names.py`): the Jinja
code reads only dbt builtins of the pinned sqlfluff, Jinja globals, the
names that Jinja gives in a block, and names that the file sets; no
`import`, `include`, `extends`, `call`, `break`, or `continue`.
The `selection` of a templated file gives the names that it reads.
The output gives these counts for each source. The selection fails
(exit code 2) if:

- a cached file is not the git blob of the commit, or the listing is for
  other globs or another commit;
- the first license file does not have the phrases of its SPDX id
  (`LICENSE_PHRASES` in `harness/sqll_harness/corpus/select.py`);
- a copyright holder is in no license file and no selected file;
- a copyright notice in a selected file names no copyright holder of the
  source, or also names another holder. Notice forms (case is ignored):
  "Copyright" and then "(c)", "©", or a name, year, ":", or "by";
  "(c) 2021"; "©". A notice must be on one line;
- a selected file has the text, name, or SPDX id of another license (for
  example "GNU", "GPL", "Mozilla Public License"). Then give the file its
  own source with its terms, or exclude it or remove its glob, and give the
  reason in the note (`notice_errors` in `select.py`);
- a selected file has TPC material: "TPC-H", "TPC-DS", "tpch", "tpcds"
  (with "-", "_", " ", or nothing), or a TPC-H or TPC-DS table name such as
  `store_sales`, `date_dim`, or `lineitem` (`tpc_errors`). Exclude it;
- an excluded path matches no glob, a source has no selected file, or the
  manifest is not valid.
