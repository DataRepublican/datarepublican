# repair_phonebook_backfill.py

**What:** Re-resolve GIN-row `recipient_ein_backfilled` with the repaired cream/DAF phonebook. Never writes `recipient_ein`.

**Why:** Export would have drawn ghosts onto junk EINs (Harvard/MIT digit typos, Fidelity D&D, DAF dump `474744275`, JHU duplicate BMF row). Fail closed: ambiguous names stay ghosts.

**How:** DAF allowlist → exact-core cream (legal suffixes kept; namesake asset_cd dominance) → 1-edit EIN repair only if the current EIN is *not* in BMF → keep if the official name is still a core of the ghost (Gates rename) → else clear.

```bash
cd 990tools
python test_phonebook_guards.py
python repair_phonebook_backfill.py --db-path irs990.duckdb
python repair_phonebook_backfill.py --db-path irs990.duckdb --apply
```

See `docs/gin_phonebook_100m_ai.md` for the $100M failure modes this encodes.
