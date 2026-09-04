#!/usr/bin/env python3
"""Merge rule + AI shard votes into gin_phonebook_100m_votes.json."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REVIEW = ROOT / "gin_phonebook_100m_review"
PAIRS = ROOT / "gin_phonebook_100m_pairs.tsv"
OUT_JSON = ROOT / "gin_phonebook_100m_votes.json"
OUT_TSV = ROOT / "gin_phonebook_100m_votes.tsv"


def main() -> None:
    pairs = list(csv.DictReader(PAIRS.open(), delimiter="\t"))
    by_key: dict[tuple[str, str], dict] = {}
    auto = json.loads((REVIEW / "auto_votes.json").read_text())
    for row in auto:
        key = (row["gin"], row["suggested_ein"])
        by_key[key] = {
            **row,
            "how": row.get("how") or "rule",
        }
    missing_shards = []
    for path in sorted(REVIEW.glob("shard_*_votes.json")):
        payload = json.loads(path.read_text())
        judgments = payload["judgments"] if isinstance(payload, dict) else payload
        for row in judgments:
            vote = (row.get("vote") or "").strip().lower()
            if vote not in {"yes", "no"}:
                raise SystemExit(f"bad vote in {path}: {row!r}")
            key = (row["gin"], row["suggested_ein"])
            by_key[key] = {
                "gin": row["gin"],
                "suggested_ein": row["suggested_ein"],
                "ghost_name": row.get("ghost_name"),
                "suggested_name": row.get("suggested_name"),
                "dollars": row.get("dollars"),
                "vote": vote,
                "reason": row.get("reason") or "",
                "how": "ai",
            }
    expected = {(r["gin"], r["suggested_ein"]) for r in pairs}
    got = set(by_key)
    missing = expected - got
    extra = got - expected
    if missing or extra:
        raise SystemExit(f"coverage fail missing={len(missing)} extra={len(extra)}")

    # Preserve dollars/grant_rows from the pair list; prefer filled names.
    enriched = json.loads((REVIEW / "pairs_enriched.json").read_text())
    names = {(r["gin"], r["suggested_ein"]): r for r in enriched}

    overrides = json.loads((ROOT / "gin_phonebook_100m_overrides.json").read_text())

    out = []
    for r in pairs:
        key = (r["gin"], r["suggested_ein"])
        v = by_key[key]
        meta = names[key]
        vote = v["vote"]
        how = v["how"]
        reason = v["reason"]
        if vote == "yes" and r["suggested_ein"] in overrides:
            vote = "no"
            how = "override"
            reason = "Parent override: " + overrides[r["suggested_ein"]]
        out.append(
            {
                "dollars": float(r["dollars"]),
                "grant_rows": int(r["grant_rows"]),
                "ghost_name": r["ghost_name"],
                "suggested_ein": r["suggested_ein"],
                "suggested_name": meta.get("suggested_name_filled") or r.get("suggested_name") or "",
                "name_source": meta.get("name_source"),
                "gin": r["gin"],
                "vote": vote,
                "reason": reason,
                "how": how,
            }
        )

    OUT_JSON.write_text(json.dumps(out, indent=2) + "\n")
    with OUT_TSV.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "dollars",
                "grant_rows",
                "ghost_name",
                "suggested_ein",
                "suggested_name",
                "vote",
                "how",
                "reason",
                "gin",
            ],
            delimiter="\t",
        )
        w.writeheader()
        for row in out:
            w.writerow({k: row[k] for k in w.fieldnames})

    c = Counter((r["vote"], r["how"]) for r in out)
    yes = sum(1 for r in out if r["vote"] == "yes")
    no = sum(1 for r in out if r["vote"] == "no")
    yes_d = sum(r["dollars"] for r in out if r["vote"] == "yes")
    no_d = sum(r["dollars"] for r in out if r["vote"] == "no")
    print(f"Wrote {OUT_JSON.name} and {OUT_TSV.name} n={len(out)}")
    print(f"yes={yes} (${yes_d:,.0f}) no={no} (${no_d:,.0f})")
    print("by vote,how:", dict(c))


if __name__ == "__main__":
    main()
