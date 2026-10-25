-- Import category items for one top category from a CSV (idempotent)
--
-- CSV columns (header required): Slovensky, Latinsky, Cesky, Typ, Mesiace
-- Rows without a Latin name are skipped (the Latin name is the stable canonical key).
-- Items are created as admin-owned, visible and approved for forago-sk and forago-cz,
-- with SK/CS translations. Re-running updates existing items instead of duplicating them.
--
-- Usage (psql), one call per CSV:
--   \set category_slug 'birds'
--   \set csv_path 'C:/Users/Pc/Desktop/FLUTTER/forago/forago/vtaky.csv'
--   \i c:/Users/Pc/Desktop/FLUTTER/forago_backend/scripts/import_category_items_from_csv.sql
--
-- Mapping used for the current files:
--   herbs    <- rastliny.csv
--   birds    <- vtaky.csv
--   fish     <- ryby.csv
--   wildlife <- cicavce.csv, zver_plazy_obojzivelniky.csv
--   insects  <- hmyz.csv

\set ON_ERROR_STOP on

BEGIN;

CREATE TEMP TABLE tmp_items_raw (
    slovensky TEXT,
    latinsky TEXT,
    cesky TEXT,
    typ TEXT,
    mesiace TEXT
) ON COMMIT DROP;

-- \copy does not interpolate variables, so the command is built in a variable first.
\set copy_cmd '\\copy tmp_items_raw (slovensky, latinsky, cesky, typ, mesiace) FROM ' :'csv_path' ' WITH (FORMAT csv, HEADER true, ENCODING ''UTF8'')'
:copy_cmd

CREATE TEMP TABLE tmp_items_clean ON COMMIT DROP AS
WITH normalized AS (
    SELECT
        NULLIF(BTRIM(slovensky), '') AS slovensky,
        NULLIF(BTRIM(latinsky), '') AS latinsky,
        NULLIF(BTRIM(cesky), '') AS cesky
    FROM tmp_items_raw
), keyed AS (
    SELECT
        slovensky,
        latinsky,
        cesky,
        NULLIF(
            BTRIM(REGEXP_REPLACE(LOWER(latinsky), '[^a-z0-9]+', '-', 'g'), '-'),
            ''
        ) AS canonical_key
    FROM normalized
    WHERE slovensky IS NOT NULL
      AND latinsky IS NOT NULL
), ranked AS (
    SELECT
        slovensky,
        latinsky,
        cesky,
        canonical_key,
        ROW_NUMBER() OVER (
            PARTITION BY canonical_key
            ORDER BY (cesky IS NOT NULL) DESC, LENGTH(slovensky) DESC, slovensky ASC
        ) AS rn
    FROM keyed
    WHERE canonical_key IS NOT NULL
)
SELECT
    UPPER(LEFT(slovensky, 1)) || SUBSTR(slovensky, 2) AS slovensky,
    latinsky,
    UPPER(LEFT(COALESCE(cesky, slovensky), 1)) || SUBSTR(COALESCE(cesky, slovensky), 2) AS cesky,
    canonical_key
FROM ranked
WHERE rn = 1;

-- psql does not substitute variables inside $$ blocks, so pass the slug via a setting.
SELECT set_config('import.category_slug', :'category_slug', TRUE);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM tmp_items_clean) THEN
        RAISE EXCEPTION 'No valid rows after cleanup. Check CSV format/content.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM app_variants WHERE code IN ('forago-sk', 'forago-cz')) THEN
        RAISE EXCEPTION 'Required app variants forago-sk/forago-cz not found.';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM categories c
        JOIN app_variants v ON v.id = c.app_variant_id
        WHERE v.code IN ('forago-sk', 'forago-cz')
          AND c.slug = current_setting('import.category_slug')
          AND c.parent_category_id IS NULL
    ) THEN
        RAISE EXCEPTION 'Top category slug=% not found for forago-sk/forago-cz.', current_setting('import.category_slug');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM profiles) THEN
        RAISE EXCEPTION 'No profiles found. Cannot resolve created_by_user_id.';
    END IF;
END $$;

WITH target_categories AS (
    SELECT c.id AS category_id, c.app_variant_id
    FROM categories c
    JOIN app_variants v ON v.id = c.app_variant_id
    WHERE v.code IN ('forago-sk', 'forago-cz')
      AND c.slug = :'category_slug'
      AND c.parent_category_id IS NULL
), creator AS (
    SELECT id AS user_id
    FROM profiles
    ORDER BY created_at ASC
    LIMIT 1
)
INSERT INTO category_items (
    app_variant_id,
    category_id,
    canonical_key,
    created_by_user_id,
    owner_type,
    visibility_state,
    approval_state,
    promoted_to_admin,
    image_url
)
SELECT
    tc.app_variant_id,
    tc.category_id,
    ic.canonical_key,
    cr.user_id,
    'admin',
    'visible',
    'approved',
    TRUE,
    NULL
FROM target_categories tc
CROSS JOIN creator cr
CROSS JOIN tmp_items_clean ic
ON CONFLICT (category_id, canonical_key) WHERE canonical_key IS NOT NULL
DO UPDATE SET
    visibility_state = 'visible',
    approval_state = 'approved',
    promoted_to_admin = TRUE,
    updated_at = NOW();

WITH item_map AS (
    SELECT ci.id AS item_id, ic.slovensky, ic.cesky, ic.latinsky
    FROM category_items ci
    JOIN categories c ON c.id = ci.category_id
    JOIN app_variants v ON v.id = ci.app_variant_id
    JOIN tmp_items_clean ic ON ic.canonical_key = ci.canonical_key
    WHERE c.slug = :'category_slug'
      AND c.parent_category_id IS NULL
      AND v.code IN ('forago-sk', 'forago-cz')
)
INSERT INTO category_item_translations (item_id, language_code, title, description_text)
SELECT item_id, 'sk', slovensky, 'Latinsky: ' || latinsky FROM item_map
UNION ALL
SELECT item_id, 'cs', cesky, 'Latinsky: ' || latinsky FROM item_map
ON CONFLICT (item_id, language_code)
DO UPDATE SET
    title = EXCLUDED.title,
    description_text = EXCLUDED.description_text;

-- Summary: rows read, rows imported, items now present in the category per variant.
SELECT
    (SELECT COUNT(*) FROM tmp_items_raw) AS csv_rows,
    (SELECT COUNT(*) FROM tmp_items_clean) AS imported_unique_rows;

SELECT v.code AS variant, COUNT(*) AS items_in_category
FROM category_items ci
JOIN categories c ON c.id = ci.category_id
JOIN app_variants v ON v.id = ci.app_variant_id
WHERE c.slug = :'category_slug'
  AND c.parent_category_id IS NULL
  AND ci.visibility_state = 'visible'
GROUP BY v.code
ORDER BY v.code;

COMMIT;
