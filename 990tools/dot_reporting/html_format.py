#!/usr/bin/env python3
"""Small HTML format helpers for report pages."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote_plus

# US ZIP or ZIP+4 — capture 5-digit core for search.
# Negative lookahead: do not treat house numbers as ZIPs
# ("32405 Diagonal Rd" — digits followed by a street word).
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b(?!\s*[A-Za-z])")


def esc(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def zip_search_url(zip5: str) -> str:
    """Google search for a ZIP (free, no API)."""
    return f"https://www.google.com/search?q={quote_plus(zip5 + ' zip code')}"


def zip_link_html(zip5: str, *, display: str | None = None) -> str:
    """Clickable ZIP with accessible label 'Search This Zip Code'."""
    z = (zip5 or "").strip()[:5]
    if len(z) != 5 or not z.isdigit():
        return esc(display or zip5)
    label = display if display is not None else z
    return (
        f'<a href="{esc(zip_search_url(z))}" target="_blank" rel="noopener" '
        f'title="Search This Zip Code" aria-label="Search This Zip Code">'
        f"{esc(label)}</a>"
    )


def linkify_zip_codes(text: Any) -> str:
    """Escape text, then wrap ZIP / ZIP+4 with search links.

    Full ZIP+4 is shown; search uses the 5-digit base.
    """
    if text is None:
        return ""
    s = str(text)
    if not s:
        return ""

    parts: list[str] = []
    last = 0
    for m in _ZIP_RE.finditer(s):
        parts.append(esc(s[last : m.start()]))
        full = m.group(0)
        z5 = m.group(1)
        parts.append(zip_link_html(z5, display=full))
        last = m.end()
    parts.append(esc(s[last:]))
    return "".join(parts)
