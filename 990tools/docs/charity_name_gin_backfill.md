# charity_name_gin_backfill.py

**What:** Fill empty `Grants.recipient_ein_backfilled` by hashing Charity `filer_name` history with the same GIN as grant_match floaters, and joining onto GIN `recipient_ein`.

**Why:** 990-PF only has name+address. GINs group the name. Phonebook from BMF missed renames (Gates 2024: `GATES FOUNDATION` after Melinda dropped off). The Charity table already filed under the new name for EIN `562618866`.

**How:** Unambiguous cleaned names only (one EIN per core). Both 66-char (`70||SHA256`) and 130-char (`70||HEX(SHA256)`) GIN forms. Does not write `recipient_ein`. Ambiguous cores skipped.

```bash
cd 990tools
python charity_name_gin_backfill.py --db-path irs990.duckdb
python charity_name_gin_backfill.py --db-path irs990.duckdb --apply
```

See `docs/PINS.md` (name-change phonebook).
