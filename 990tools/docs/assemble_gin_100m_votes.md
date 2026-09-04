# assemble_gin_100m_votes.py

**What:** Merge rule votes, AI shard votes, and parent overrides into `gin_phonebook_100m_votes.json`.

**Why:** The $100M ghost→EIN review is three layers (string equality, Grok thumbs, collision overrides). One assembler is the coverage check: every pair in `gin_phonebook_100m_pairs.tsv` must appear exactly once.

**How:** Reads `gin_phonebook_100m_review/auto_votes.json` and `shard_*_votes.json`, joins names from `pairs_enriched.json`, flips `gin_phonebook_100m_overrides.json`. Does not touch DuckDB.

```bash
python assemble_gin_100m_votes.py
```
