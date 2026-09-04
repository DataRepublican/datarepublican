#!/usr/bin/env python3
"""Rewrite by-state medicare provider links from ../providers/ to ../../../providers/.

National suite pages (suite/*.html) correctly use ../providers/ → reports/providers/.
State detail pages (suite/states/ST/*.html) need ../../../providers/ for the same
shared tree. Generation used the national-relative path by mistake.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Only the single-up form used by mistaken by-state generation.
# Do NOT use a bare replace of "../providers/" — that would corrupt
# already-correct "../../../providers/" (substring match).
_PATTERNS = (
    ('href="../providers/', 'href="../../../providers/'),
    ("href='../providers/", "href='../../../providers/"),
    ('\\"../providers/', '\\"../../../providers/'),
    ("'../providers/", "'../../../providers/"),
)


def fix_file(path: Path, *, dry_run: bool) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    if "../providers/" not in text:
        return 0
    new_text = text
    n = 0
    for old, new in _PATTERNS:
        c = new_text.count(old)
        if c:
            new_text = new_text.replace(old, new)
            n += c
    if new_text == text:
        return 0
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        type=Path,
        action="append",
        required=True,
        help="Report root(s), e.g. reports or fun/",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = 0
    replacements = 0
    for root in args.root:
        root = root.expanduser().resolve()
        # Only under */states/*/* (state detail / index pages)
        for path in root.rglob("states/*/*.html"):
            if not path.is_file():
                continue
            # skip if path has no provider refs
            n = fix_file(path, dry_run=args.dry_run)
            if n:
                files += 1
                replacements += n
    print(
        f"{'Would fix' if args.dry_run else 'Fixed'} {files} files "
        f"(~{replacements} path occurrences)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
