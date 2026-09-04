# us_zip_lookup.py

## Why

ZIP→state disagreement (e.g. `Atlanta, NJ, 30339`) is a data-quality signal that should set a colocator **at Address ingest**, not only after expensive geocode stages. The same rule must also apply to residual `Geocoding` rows that never re-pass `Address.canonicalize`. One shared loader avoids two copies of `US_zips.txt.gz` logic drifting apart.

## What

Process-wide cache of `US_zips.txt.gz`:

| API | Role |
|-----|------|
| `is_valid_us_zip` | ZIP in file |
| `state_for_zip` | primary 2-letter state |
| `is_state_zip_mismatch` | declared state ≠ ZIP’s state (skips military/territories) |
| `ambig_colocator` | `AMBIG:{state}:{zip5}` |

## How / consumers

- **`models/address.py`** — after PO Box colocator, else if mismatch → set `AMBIG:…`
- **`geocoding_api_processor`** — residual preprocess shortcircuit for parked rows

Extend skip list in `_SKIP_STATE_MISMATCH` if more non-civilian codes appear.
