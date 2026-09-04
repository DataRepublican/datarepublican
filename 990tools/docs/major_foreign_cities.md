# major_foreign_cities.json

## Why

Grok (and earlier stages) still leave **country/city-only** foreign tokens (`Moscow`, `Tehran`, `Nicaragua`) and offshore shells (`Trust Company Complex … Majuro`) as `grok:UNKN`. Paying Grok again is waste; bootstrap list makes free `FA:INTL` matches without hardcoding hundreds of names in Python.

## What

JSON lists:

- **cities** — exact name-only match (dual US place names intentionally omitted: Paris, London, San Jose, …)
- **countries** — same for country-as-street
- **shell_phrases** — substring match (Ajeltake / Majuro / trust company complex)

Loaded once by `GeocodingAPIProcessor._ensure_major_foreign_places`.

## How

Edit the JSON and re-run:

```bash
python3 preprocess_grok_pending.py --grok-failures
```

Valid US **state+ZIP** anchors still block foreign-name matching (e.g. Paris TX).
