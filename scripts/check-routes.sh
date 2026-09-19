#!/usr/bin/env bash
#
# Assert that every route in tests/routes.txt still resolves 200 against a
# running site, and report any route the build publishes that the baseline
# does not know about.
#
# Usage:
#   scripts/check-routes.sh [base-url] [build-dir]
#
# Defaults: http://localhost:4000 and _site
#
# A missing route fails the run. A new route only warns — adding pages is
# normal; losing them silently is the failure this guards against. When a route
# is dropped on purpose, update tests/routes.txt in the same commit so the
# deletion is visible in review.

set -uo pipefail

cd "$(dirname "$0")/.."

BASE="${1:-http://localhost:4000}"
BUILD="${2:-_site}"
BASE="${BASE%/}"

# A server with SPA fallback turned on answers 200 for everything, which makes
# every assertion below pass while every route is really the home page. Prove
# the server 404s before trusting anything it says.
probe=$(curl -s -o /dev/null -w '%{http_code}' -L --max-time 30 "${BASE}/__route-check-probe-$$")
if [ "$probe" = "200" ]; then
  echo "FATAL: ${BASE} answers 200 for a path that does not exist."
  echo "The server has SPA/single-page fallback enabled, so this check cannot"
  echo "tell a live route from a missing one. Serve the build without it."
  exit 1
fi

missing=0
checked=0

while IFS= read -r route; do
  [ -z "$route" ] && continue
  status=$(curl -s -o /dev/null -w '%{http_code}' -L --max-time 30 "${BASE}${route}")
  checked=$((checked + 1))
  if [ "$status" != "200" ]; then
    echo "MISSING  $status  ${route}"
    missing=$((missing + 1))
  fi
done < tests/routes.txt

echo "checked ${checked} routes, ${missing} missing"

if [ -d "$BUILD" ]; then
  added=$(comm -13 tests/routes.txt <(./scripts/route-inventory.sh "$BUILD") || true)
  if [ -n "$added" ]; then
    echo
    echo "new routes not in tests/routes.txt (not a failure):"
    echo "$added" | sed 's/^/  + /'
  fi
fi

[ "$missing" -eq 0 ] || exit 1
