#!/bin/sh
# Build the pinned sqruff binary with cargo and install it as ROOT/bin/sqruff.
# Usage: tools/sqruff/install.sh ROOT
#        tools/sqruff/install.sh --print-version
#
# The version is the sqruff version in tools/sqruff/uv.lock. The "parser"
# feature adds the "parse" command. The "python" feature adds the jinja,
# python, dbt, and sqlmesh templaters. They use the sqruff Python package in
# ROOT/python (scripts/setup installs it from the same lock file).
#
# The python feature links to libpython. PYO3_PYTHON selects the Python 3.13
# to build against. Default: ROOT/python/bin/python3, else python3.13. That
# Python must have a shared libpython that the loader finds at run time.
set -eu

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
root=${1:?usage: install.sh ROOT}
features=parser,python
version=$(sed -n '/^name = "sqruff"$/{n;s/^version = "\(.*\)"$/\1/p;}' "$here/uv.lock")
if [ -z "$version" ]; then
    echo "error: no sqruff version in $here/uv.lock" >&2
    exit 2
fi
if [ "$root" = --print-version ]; then
    echo "$version"
    exit 0
fi

stamp="$root/sqll-install.txt"
want="sqruff $version features=$features"
installed() {
    [ -x "$root/bin/sqruff" ] &&
        [ "$(cat "$stamp" 2>/dev/null)" = "$want" ] &&
        [ "$("$root/bin/sqruff" --version 2>/dev/null)" = "sqruff $version" ]
}
if installed; then
    exit 0
fi

if [ -z "${PYO3_PYTHON:-}" ]; then
    if [ -x "$root/python/bin/python3" ]; then
        PYO3_PYTHON="$root/python/bin/python3"
    else
        PYO3_PYTHON=python3.13
    fi
fi
export PYO3_PYTHON

echo "building $want with $(cargo --version) and $("$PYO3_PYTHON" --version)" >&2
rm -f "$stamp"
cargo install sqruff --version "$version" --locked --force \
    --features "$features" --root "$root"

if ! out=$("$root/bin/sqruff" --version 2>&1) || [ "$out" != "sqruff $version" ]; then
    echo "error: $root/bin/sqruff --version gave: $out" >&2
    echo "Is the libpython of $PYO3_PYTHON in the library path?" >&2
    exit 1
fi
echo "$want" > "$stamp"
