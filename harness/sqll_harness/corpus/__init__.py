"""The S9 external corpus (docs/decisions/s9-corpus.md, corpus/README.md).

manifest.py reads and validates corpus/sources.json. fetch.py downloads
each file of the manifest by its pinned commit into a cache folder and
checks its sha256. Run: python -m sqll_harness.corpus {validate,fetch}.
"""
