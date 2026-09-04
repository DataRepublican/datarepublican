# backfill_contractor_owner_id

## What

One-shot (re-runnable) DuckDB writer that sets `Addresses.owner_id` for `address_type = 'contractor'` rows that were inserted with a null owner, and copies `colocator` onto `Contractors` when empty.

Runnable: `scripts/backfill_contractor_owner_id.py`

## Why

XML parse built contractor addresses **before** `contractor_id` was assigned, so production had **zero** joinable contractor address rows. Focus reports (`JOIN Contractors c ON c.contractor_id = a.owner_id`) showed 1816 “entities” with **no names** and **$0**. The pipeline fix (`models/contractor.py` → `owner_id=self.id`) only helps new inserts; this script repairs history.

## How

1. Pair by `upper(name) + colocator` when both sides have colocator (PO boxes).
2. Remaining: pair by `upper(name)` with `ROW_NUMBER()` among unmatched rows.
3. `UPDATE Addresses SET owner_id = …`; then fill empty `Contractors.colocator` from addresses.

```bash
python3 scripts/backfill_contractor_owner_id.py --dry-run
python3 scripts/backfill_contractor_owner_id.py --db /Volumes/Data/final/irs990.duckdb
```

Needs a write lock on the DB (no concurrent writers). Production run 2026-08-01: 984,680 pairs written, 0 null owners left.
