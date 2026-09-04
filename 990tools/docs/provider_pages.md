# provider_pages.py

**What:** Static NPI dossiers under `dot_reporting/reports/providers/<npi>.html`.

**Why:** Medicare cluster tables link every entity. Only national top-N used to get a page, so by-state lists 404’d (~80k missing). Dead links on the public site are unprofessional.

**How:** Rollup + HCPCS + NPPES identity + addresses. Skip `medicare_provider_spending` (230M-row line grain) on bulk runs — that’s why a full backfill is overnight, not days.

```bash
# one NPI
python3 -u dot_reporting/provider_pages.py --npi 1770101545 --no-json --no-index

# every NPI linked from medicare HTML but missing a file
python3 -u dot_reporting/provider_pages.py --npis-file /tmp/missing_npis.txt --no-json --no-index
```

Copy into the site with `grumpytechbro.com/scripts/build_site.py`, then `./scripts/deploy.sh --with-fun`.
