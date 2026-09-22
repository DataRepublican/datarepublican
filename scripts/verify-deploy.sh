#!/usr/bin/env bash
# Verify a deploy by CONTENT, not status code.
#
# Three traps this exists to defeat, all of which make a broken deploy look fine
# and a fine deploy look broken:
#
#   1. `try_files $uri $uri/ /index.html` answers a MISSING asset with the home
#      page at 200. Status codes prove nothing; content-type does.
#   2. jekyll-seo-tag builds absolute URLs from `url:` in _config.yml, which is
#      always https://datarepublican.com. Following og:image/canonical off a
#      staging host measures production. Always request the host's own path.
#   3. The old /ea-explorer/*.html paths are jekyll-redirect-from stubs that
#      point at production from every environment. Excluded here on purpose.
#
# Usage: verify-deploy.sh <base-url> [git-ref]
set -uo pipefail
BASE="${1:?usage: verify-deploy.sh <base-url> [git-ref]}"
REF="${2:-HEAD}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
fail=0

echo "=== 1. routes (contract) ==="
while read -r r; do
  [ -z "$r" ] && continue
  case "$r" in *ea-explorer/network.html|*ea-explorer/words/opener.html) continue ;; esac
  # Retry once on a transport failure (000). A dropped connection mid-sweep is
  # not a missing route, and reporting it as one sends you hunting a ghost.
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$BASE$r")
  [ "$code" = "000" ] && code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 90 "$BASE$r")
  [ "$code" = "200" ] || { echo "  MISSING $code $r"; fail=$((fail+1)); }
done < "$REPO/tests/routes.txt"
echo "  done"

echo "=== 2. assets serve the right content-type (not the home page) ==="
# Asset list comes from the TARGET's own HTML, not a local _site that may be
# stale or built from a different ref. Fetch each route once and harvest.
: > /tmp/vd-assets.txt
while read -r r; do
  [ -z "$r" ] && continue
  case "$r" in *ea-explorer/network.html|*ea-explorer/words/opener.html) continue ;; esac
  curl -s --max-time 30 "$BASE$r" \
    | grep -o '/assets/[A-Za-z0-9_./-]*\.\(js\|css\|json\|png\|webp\|svg\|woff2\)' >> /tmp/vd-assets.txt
done < "$REPO/tests/routes.txt"
sort -u -o /tmp/vd-assets.txt /tmp/vd-assets.txt
while read -r a; do
  ct=$(curl -s -o /dev/null -w '%{content_type}' --max-time 30 "$BASE$a")
  case "$a:$ct" in
    *.js:*javascript*|*.css:*css*|*.json:*json*|*.png:*image*|*.webp:*image*|*.svg:*svg*|*.woff2:*font*) ;;
    *) echo "  WRONG TYPE $a -> $ct"; fail=$((fail+1)) ;;
  esac
done < /tmp/vd-assets.txt
echo "  checked $(wc -l < /tmp/vd-assets.txt) assets"

echo "=== 3. gzip is on (repo nginx.conf, not Coolify's config) ==="
for f in /noblogs/data.index.json /assets/css/styles.css; do
  enc=$(curl -s -o /dev/null -D - -H 'Accept-Encoding: gzip' --max-time 40 "$BASE$f" | grep -i '^content-encoding' | tr -d '\r' | awk '{print $2}')
  [ "$enc" = "gzip" ] || { echo "  NOT GZIPPED $f (enc=${enc:-none})"; fail=$((fail+1)); }
done
echo "  done"

echo "=== 4. binary assets match the ref, byte for byte ==="
for img in assets/images/og.png; do
  remote=$(curl -s --max-time 40 "$BASE/$img" | md5)
  local=$(git -C "$REPO" show "$REF:$img" 2>/dev/null | md5)
  [ "$remote" = "$local" ] || { echo "  MISMATCH /$img remote=$remote ref=$local"; fail=$((fail+1)); }
done
echo "  done"

echo "=== 5. it is the v2 chrome, not the old shell ==="
body=$(curl -s --max-time 40 "$BASE/")
echo "$body" | grep -q 'page-column' || { echo "  no .page-column — old chrome?"; fail=$((fail+1)); }
echo "$body" | grep -q 'site-header' && { echo "  found site-header — this is the OLD build"; fail=$((fail+1)); }
echo "  done"

echo
[ "$fail" -eq 0 ] && echo "PASS — $BASE" || echo "FAIL — $fail problem(s) at $BASE"
exit "$fail"
