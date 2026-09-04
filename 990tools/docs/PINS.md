# PINS — Browse export, Sankey, inferred grants

Pinned decisions for the DuckDB → `/browse` rebuild on `grokrefactor3`. Implementer starts at PR1. Do not treat GINs as IRS matches.

Live DB: `/Volumes/Data/final/irs990.duckdb` (via `990tools/irs990.duckdb`).

---

## Columns (do not confuse)

| Column | What it is |
|---|---|
| `Grants.recipient_ein` | Graph **key**. XML 9-digit if the 990 had one; else colocator-copied 9-digit; else **GIN** (`70` + hex SHA256 of cleaned grantee name, length 66 or 130). Match **does** write this (`grant_match_processor.py`). |
| `Grants.recipient_ein_backfilled` | IRS **guess**. Phonebook / BMF / einless. Never a GIN. |
| Draw / collapse | See **Node types** below. **Never present a GIN as an IRS EIN.** |

**GIN purpose:** For a 990-PF grant we know **name + address**, not an EIN. We cannot AI-match every pair. Hash the cleaned name so the same string is one **ghost node**. Phonebook may *suggest* an IRS EIN beside it; the user decides whether to trust that. GIN occupancy ≠ match rate.

**Hygiene:** empty XML EIN is recoverable without reingest: GIN / `8686` / non-9-digit in `recipient_ein` means the form did not give an EIN.

**Reported vs inferred (export flag):**

- **Reported:** filer is 990/990EZ **and** `recipient_ein` is `^[0-9]{9}$`.
- **Inferred:** 990-PF filer, **or** `recipient_ein` is a GIN, **or** XML empty and backfill is 9-digit.
- **Unmatched / ghost:** GIN (or empty) with no 9-digit backfill — still a node, not dropped.

Live snapshot (26.2M grants): ~40% have a 9-digit in `recipient_ein`; ~58% have a GIN there; ~96% have a 9-digit in *either* column (the extra is phonebook sitting next to the GIN). Quote **40%** as form-side; quote **96%** only as “we have a candidate EIN to draw.”

**Gates check:** Trust `911663695` → Foundation `562618866`. 2020–23 grantee `BILL & MELINDA GATES FOUNDATION`, GIN + backfill `562618866`. 2024 string `GATES FOUNDATION` (divorce rename), GIN only, backfill NULL. Duplicate grant rows exist (every amount twice) — separate hygiene.

---

## Node types (export + Sankey)

Three kinds of node. Ghosts are why GINs exist in the export.

| Type | Identity | We know | 990 card |
|---|---|---|---|
| **Charity** | 9-digit EIN, filed in our XML | Latest-year 990 metrics | Yes |
| **BMF-only** | 9-digit EIN, IRS BMF, never (or not yet) in our 990 set | Name, city/state from BMF (universities, churches, etc.) | No |
| **Ghost** | GIN (`70` + SHA256 of cleaned grantee name) | Name, maybe colocator. Same string → one ghost. | No |

Edges from a PF filer to a floater **land on the ghost**, not on a fake Charity. Phonebook is a **suggested link** ghost → Charity or BMF-only (`recipient_ein_backfilled`). Default graph: show ghosts (honest). Toggle **Trust the phone book** (plain language in the UI): collapse ghost into the suggested EIN when the link exists. Off: keep the ghost even if backfill is set. That is the 2020–23 Gates case: ghost “BILL & MELINDA GATES FOUNDATION” *suggested as* `562618866`; user chooses merge vs two nodes.

Browse `Charity` class is the 990 filer. Ghosts likely need a distinct model (or a `kind` on the node). Do not reuse GIN as `ein` on a Charity.

**Leftover stub** (see more) is separate: grants from an in-band org to counterparties **omitted by the dollar cut**, not “we don’t know who they are.”

---

## Who is in a dollar band

Org is in the **$T set** if **max across years** of any of (receipts, govt, contribs, assets, grants-to-others) **or a single grant** ≥ T.

Why max-across-years: catch a Biden-era $100M year even if the latest filing is quiet.

**Nodes in the TSV:** latest tax year only (name, assets, receipts, that 990).

**Edges:** all years between in-set orgs. A 2025 grant from A to B is allowed even if B’s card is 2024. Opening B’s 990 will not show that inflow. Accepted.

**Leftover:** one stub **per visible org** for grants to omitted counterparties (“see more”; display TBD). Not one global `.etc.` node.

Cutpoints (max-across-years, Charities only — grant-size union not folded in yet):

| T | Orgs |
|---|---:|
| $1M | 267k |
| **$10M (default load)** | **74k** |
| $100M | 14k |

Current full browse payload ~39MB zip / ~910k orgs; $10M should be ~10× fewer orgs.

---

## Browse behavior

1. **Default load = $10M band.** Fast path.
2. **Focus is the default interaction.** Plain click / cmd-click / Only This = `tunnelNode()` (this org + its up/down only). Preset **add** stays as a power switch so Uniparty can still seed several nodes. Dead code: `Charity.tunnelNode`, panel button `focusNode`.
3. **Jump to $1M** is user-initiated. Warn: you will wait. Then merge into the same IndexedDB so a return visit is already at that depth.
4. **Trust the phone book** toggle: collapse ghosts onto suggested EINs. Default **off** (ghosts stay visible; we are honest that PF is name+address). When on, inferred 9-digit edges use the backfill EIN. Copy in UI: this is a name/address phone book, not the 990.
5. Do not ship the full 910k set as default.

---

## PR order

0. **Charity name-history GIN phonebook** (`charity_name_gin_backfill.py`) — applied. **$100M AI thumbs** — `gin_phonebook_100m_votes.json`. **Cream/DAF repair** (`repair_phonebook_backfill.py`) — GIN backfill re-resolved; junk EINs cleared. Then export.
1. DuckDB → browse TSV at **$10M**: Charities, BMF-only endpoints, **ghosts (GIN + name)**, grants (from, to_key, inferred, suggested_ein), per-org leftover stub. Measure zip size / load time. GINs only as ghost ids.
2. Browse: load that band; **focus default**; keep add as a switch; render ghosts as a distinct node type.
3. “Load $1M” with explicit wait; IDB merge.
4. **Trust the phone book** toggle (collapse ghost → suggested EIN).
5. Org inspector: Google Maps from stored lat/lon; later **octopus** (Leaflet, same stack as OFAC/noblogs reports — tentacles = grants to geolocated NGOs).

Stretch stays stretch until PR1 works.

---

## Later: AI thumbs on expensive ghost→EIN pairs (not PR1)

No backend, so no user votes. Optional: Grok thumbs-up/down “does this ghost name plausibly map to this EIN?” **scoped by dollars**, not all 1.36M GIN→backfill pairs.

Live snapshot (GIN in `recipient_ein` + 9-digit backfill, summed `grant_amt`):

| Pair $ | Distinct GIN→EIN pairs | $ in those pairs |
|---|---:|---:|
| all | 1.36M | $662B |
| ≥ $1M | 63k | — |
| ≥ $10M | **8,791** | **$430B** |
| ≥ $100M | **663** (after Charity-GIN phonebook; was 642) | — |
| ≥ $1B | 23 | — |

Affordable slice is **$100M (663 after phonebook)** or **$10M (8.8k)**. **Done for $100M:** `gin_phonebook_100m_votes.json` — 449 yes / 214 no. UI can treat approved as default-collapse, rejected as ghost-only. Does not replace the Trust-the-phone-book toggle.

---

## Later: name-change phonebook (not PR1)

Orgs do rename (~11% of EINs have 2+ cleaned `filer_name`s across years; 98.5% of those cleaned strings map to exactly one EIN).

**Do later:** reuse the existing GIN function on **Charity name history** (`ein, cleaned_name, gin`). Join `Grants.recipient_ein` (GIN) → that table. Auto-backfill when GIN → 1 EIN; skip collisions (13k ambiguous names). Same `70||SHA256(...)` so current GIN rows join with no XML reingest. Would have caught 2024 `GATES FOUNDATION` because `562618866` already filed under that name.

Phonebook trust order when that ships: XML 9-digit → Charity-history GIN → BMF/cream phonebook → colocator → leave as GIN + leftover stub.

---

## Do not

- Reingest XML to recover “was this EIN on the form.” GINs/empties are the breadcrumb.
- Count GIN occupancy as a match rate.
- Replace the GIN in `recipient_ein` with the phonebook EIN in the database (keep both columns).
- Draw a ghost as if it were a Charity with a fake EIN.
- Drop an edge because the grantee’s latest year is older than the filer’s.
