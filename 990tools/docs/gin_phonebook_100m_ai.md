# $100M ghost → phonebook EIN thumbs

**What:** 663 GIN (ghost name) → suggested 9-digit EIN pairs whose grants sum to ≥ $100M. After Charity-history GIN backfill (`charity_name_gin_backfill.py`).

**Why:** No backend votes. Thumbs-up/down “do these two orgs plausibly map?” on the expensive slice only. Approved → default-collapse in UI; rejected → stay a ghost. Does not replace the Trust-the-phone-book toggle for the long tail.

**Files:**

| Path | Role |
|---|---|
| `gin_phonebook_100m_pairs.tsv` | Input pairs (gitignored `*.tsv`) |
| `export_gin_100m_pairs.py` | Rebuilds the pair list from DuckDB |
| `assemble_gin_100m_votes.py` | Merges rule + AI shards + overrides |
| `gin_phonebook_100m_overrides.json` | Parent flips (name collisions / phantom EINs) |
| `gin_phonebook_100m_votes.json` | Final yes/no table |

**Prompt (one pair):** You are checking a 990-PF grantee string (ghost) against an IRS EIN the phone book suggested. Answer only `yes` or `no`: is it plausible that **ghost_name** is the same organization as **suggested_name** (EIN **suggested_ein**)? If the ghost is a generic/redacted/pass-through string, answer `no`.

**How this run was judged**

1. Fill empty Charity names from BMF.
2. **Rule yes** if names match ignoring case/punctuation.
3. **Rule no** if the ghost is generic (`See Attachment`, …) or the suggested EIN has no Charity and no BMF name (Harvard `421035800`, MIT `042103694`, UNICEF `911183380`, … — those phonebook EINs are not in IRS BMF).
4. AI on the remaining 263 (seven shards). No if DAF vs family foundation, university vs similarly named fund, WHO vs “World Organization”, etc.
5. Parent **override no** when the names match a tiny/duplicate BMF row and a famous same-name EIN exists (JHU, Fidelity Charitable, Robin Hood, PIH, MS GIFT, Princeton subordinate, Scholarship America, First Presbyterian, UC Santa Cruz-as-system).

**Result (2026-09-01):** 449 yes ($187B) / 214 no ($65B) of $252B in these pairs. Gates 2024 rename is **yes**. Votes are not written into DuckDB; export/UI will read the JSON.

```bash
cd 990tools
python export_gin_100m_pairs.py
python assemble_gin_100m_votes.py
```

---

## What this review says about the phonebook

These are the mechanical failures, not “AI is smarter than cream.”

**1. Never write an EIN that is not in BMF or Charity.** 83 of 663 suggested EINs are absent from BMF (~$28B). Examples: `998899999`, DAF dump `474744275`, Harvard `421035800`, MIT `042103694`. `resolve_donor_advised_fund_ein` currently *defaults* to `474744275`, which is not a BMF org.

**2. Single-digit / transposition repair, then name-check.** Several missing EINs are one edit from the real university:

| Ghost | Phonebook | Real BMF | Edit |
|---|---|---|---|
| MIT | 042103694 | 042103594 | one digit |
| USC | 911642394 | 951642394 | one digit |
| Caltech | 941643307 | 951643307 | one digit |
| NYU | 135562309 | 135562308 | one digit |
| Baylor College of Medicine | 741613278 | 741613878 | one digit |
| Sloan Kettering | 131624183 | 131624182 | one digit |
| NPT | 237285575 | 237825575 | transposition |
| Harvard (College) | 421035800 | 042103580 | lost leading zero + pad |

Require the repaired EIN’s BMF name to share tokens with the ghost. Do not take a hamming-1 hit on Knights of Columbus.

**3. Shared BMF names: skip or pick the giant, don’t take first row.** `build_exact_core_phonebook` is first-writer-wins by name. Hundreds of BMF rows are named `TRUSTEES OF PRINCETON UNIVERSITY` (subordinates, asset_cd=0). Same pattern: JHU `520591627` vs `520595110`, MS GIFT `320534221` ($132k) vs `527082731` ($9B), Fidelity `... INC` $1.2M vs `110303001` $86B. Charity-history GIN already skips collisions; cream does not.

**4. DAF sponsor allowlist, not keyword-in-BMF.** `resolve_donor_advised_fund_ein` returns the *first* BMF row whose name contains `SCHWAB`+`CHARITABLE` / `FIDELITY`+`CHARITABLE`. That is how we got Elmont-Schwabe, Anna C Macaskill Schwab, and Fidelity D&D. Hard-code the sponsor EINs (Fidelity `110303001`, Vanguard `232888152`, GS `311774905`, MS GIFT `527082731`, NPT `237825575`). Named account `CHABOT FAMILY DAF - VANGUARD` → sponsor is correct.

**5. FUND / FOUNDATION / UNIVERSITY / HOSPITAL are not junk tokens.** Cream treats a sig prefix/suffix as a 100% match. After stopword stripping, `UNIVERSITY OF PENNSYLVANIA` and `UNIVERSITY OF PENNSYLVANIA FUND` collide; so do Energy Foundation vs Association, EDF vs EDC, hospital vs parent system. Keep those legal-suffix distinctions in the key. Prefix remainder must look like `INC` / `ATTN` / DAF account, not `HEALTH` / `MEMORIAL` / `FUND`.

**6. Generic/redacted before any assignment.** `See Attachment`, `SCHEDULE ATTACHED`, `VARIOUS - SEE ATTACHED`, bare `See`, `DONOR ADVISED FUND`, `UNITED WAY`, `HABITAT FOR HUMANITY`, `FIRST PRESBYTERIAN CHURCH` (400+ BMF rows). Blocklist; leave GIN.

**7. Do not auto-merge university ↔ university foundation.** AI correctly rejected those as different legal entities. Phonebook should too. Collapse is a UI Trust-the-phone-book choice, not a backfill.

Charity-name GIN (Gates 2024) is the piece that already works. Next phonebook pass: validate EIN exists → collision/asset dominance → digit repair → DAF allowlist → keep legal suffixes.
