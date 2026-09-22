#!/usr/bin/env bash
#
# Emit the list of HTML routes a build publishes, one URL per line, sorted.
#
# This is the site's route contract. `tests/routes.txt` is a checked-in snapshot
# of it taken from the last commit of the old `docs/` build output, and CI
# asserts that a fresh build still serves every line. It is the file that stops
# a redesign PR from silently dropping a page.
#
# Usage:
#   scripts/route-inventory.sh                  # from committed docs/ (the baseline)
#   scripts/route-inventory.sh _site            # from a build directory
#
# With no argument it reads `git ls-files docs/` rather than the filesystem,
# because `.gitignore` excludes docs/charity, docs/pa and docs/990tools — those
# are built locally but never published, so the filesystem overstates what
# GitHub Pages actually serves.

set -euo pipefail

cd "$(dirname "$0")/.."

to_urls() {
  # docs/index.html      -> /
  # docs/foo/index.html  -> /foo/
  # docs/foo/bar.html    -> /foo/bar.html
  sed -E \
    -e "s|^${1}/|/|" \
    -e 's|/index\.html$|/|' \
    -e 's|^/index\.html$|/|' \
    -e 's|^$|/|'
}

if [ $# -eq 0 ]; then
  git ls-files 'docs/*.html' 'docs/**/*.html' | to_urls docs | LC_ALL=C sort -u
else
  root="${1%/}"
  [ -d "$root" ] || { echo "not a directory: $root" >&2; exit 1; }
  find "$root" -type f -name '*.html' | to_urls "$root" | LC_ALL=C sort -u
fi
