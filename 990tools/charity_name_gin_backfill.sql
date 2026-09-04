-- Charity name-history GIN → Grants.recipient_ein_backfilled
-- Same hash as grant_match floaters: 70 || SHA256(stripped name)
-- DuckDB SHA256() returns 64-char hex VARCHAR; HEX() of that is 128 chars.
-- Stored GINs are either 66 (70+sha) or 130 (70+HEX(sha)). Join both.
-- Only fills empty backfill. Does not touch recipient_ein.
-- Ambiguous cores (2+ EINs) are excluded.

CREATE OR REPLACE TEMP TABLE charity_gin_map AS
WITH cleaned AS (
  SELECT
    ein,
    UPPER(TRIM(REGEXP_REPLACE(
      filer_name,
      '\s+(INC|CORP|LLC|FOUNDATION|MINISTRY|ASSOCIATION|CHURCH)$',
      '',
      'gi'
    ))) AS core
  FROM Charities
  WHERE filer_name IS NOT NULL AND TRIM(filer_name) != ''
),
cores AS (
  SELECT ein, core
  FROM cleaned
  WHERE core IS NOT NULL AND core != ''
),
unambiguous AS (
  SELECT core
  FROM cores
  GROUP BY core
  HAVING COUNT(DISTINCT ein) = 1
)
SELECT
  c.ein,
  c.core,
  '70' || SHA256(c.core) AS gin66,
  '70' || HEX(SHA256(c.core)) AS gin130
FROM cores c
JOIN unambiguous u ON u.core = c.core;

CREATE OR REPLACE TEMP TABLE gin_unique AS
SELECT gin66 AS gin, MIN(ein) AS ein
FROM charity_gin_map
GROUP BY gin66
HAVING COUNT(DISTINCT ein) = 1
UNION
SELECT gin130, MIN(ein)
FROM charity_gin_map
GROUP BY gin130
HAVING COUNT(DISTINCT ein) = 1;
