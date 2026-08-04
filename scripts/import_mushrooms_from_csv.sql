-- Import mushrooms category items from CSV (idempotent)
--
-- What this does:
-- 1) Loads raw CSV rows into a temp table.
-- 2) Cleans data: removes missing Slovak names and duplicates; Latin name is optional.
-- 2b) Adds first-word aliases from Slovak names (e.g. "Smrcok obycajny" -> "Smrcok").
-- 3) Upserts items into category_items for mushrooms in forago-sk + forago-cz variants.
-- 4) Upserts SK/CS translations.
-- 5) Assigns optional badges from Typ (edible/inedible/poisonous).
--
-- Usage (psql):
--   \set csv_path 'C:/Users/Pc/Desktop/FLUTTER/forago/forago/huby.csv'
--   \i c:/Users/Pc/Desktop/FLUTTER/forago_backend/scripts/import_mushrooms_from_csv.sql
--
-- Optional preview/export (psql) after load:
--   \copy (SELECT slovensky, latinsky, cesky, typ, canonical_key FROM tmp_huby_clean ORDER BY slovensky) \
--   TO 'C:/Users/Pc/Desktop/FLUTTER/forago/forago/huby.cleaned.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

BEGIN;

CREATE TEMP TABLE tmp_huby_raw (
    slovensky TEXT,
    latinsky TEXT,
    cesky TEXT,
    typ TEXT,
    mesiace TEXT
) ON COMMIT DROP;

-- psql meta-command (must be on a single line):
\copy tmp_huby_raw (slovensky, latinsky, cesky, typ, mesiace) FROM :csv_path WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
CREATE TEMP TABLE tmp_huby_clean AS
WITH normalized AS (
    SELECT
        NULLIF(BTRIM(slovensky), '') AS slovensky_raw,
        NULLIF(BTRIM(latinsky), '') AS latinsky_raw,
        NULLIF(BTRIM(cesky), '') AS cesky_raw,
        NULLIF(BTRIM(typ), '') AS typ_raw
    FROM tmp_huby_raw
), standardized AS (
    SELECT
        CASE WHEN slovensky_raw = '-' THEN NULL ELSE slovensky_raw END AS slovensky,
        CASE WHEN latinsky_raw = '-' THEN NULL ELSE latinsky_raw END AS latinsky,
        CASE WHEN cesky_raw = '-' THEN NULL ELSE cesky_raw END AS cesky,
        CASE WHEN typ_raw = '-' THEN NULL ELSE typ_raw END AS typ
    FROM normalized
), filtered AS (
    SELECT
        slovensky,
        latinsky,
        cesky,
        typ,
        LOWER(REGEXP_REPLACE(COALESCE(latinsky, slovensky), '\\s+', ' ', 'g')) AS dedupe_key,
        LOWER(REGEXP_REPLACE(COALESCE(latinsky, slovensky), '[^a-zA-Z0-9]+', '-', 'g')) AS canonical_key_raw,
        CASE
            WHEN typ ILIKE '%jedovat%' THEN 'poisonous'
            WHEN typ ILIKE '%nejedl%' THEN 'inedible'
            WHEN typ ILIKE '%vyborn%jedl%' THEN 'edible'
            WHEN typ ILIKE '%jedl%' THEN 'edible'
            ELSE NULL
        END AS badge_code
    FROM standardized
    WHERE slovensky IS NOT NULL
        -- Latin name can be missing; if present, keep only likely scientific names.
        AND (
            latinsky IS NULL
           OR latinsky ~ '^[A-Z][A-Za-z.-]+( [a-z][A-Za-z.-]+){0,3}$'
        )
), ranked AS (
    SELECT
        slovensky,
        latinsky,
        cesky,
        typ,
        NULLIF(REGEXP_REPLACE(canonical_key_raw, '-+', '-', 'g'), '') AS canonical_key,
        badge_code,
        ROW_NUMBER() OVER (
            PARTITION BY dedupe_key
            ORDER BY
                (cesky IS NOT NULL) DESC,
                (typ IS NOT NULL) DESC,
                LENGTH(slovensky) DESC,
                slovensky ASC
        ) AS rn
    FROM filtered
), base_clean AS (
    SELECT
        slovensky,
        latinsky,
        cesky,
        typ,
        canonical_key,
        badge_code
    FROM ranked
    WHERE rn = 1
      AND canonical_key IS NOT NULL
), with_aliases AS (
    -- Add short generic aliases from the first word of Slovak title.
    -- Badge is intentionally NULL for aliases to avoid ambiguous edible/poisonous labeling.
    SELECT
        bc.slovensky,
        bc.latinsky,
        bc.cesky,
        bc.typ,
        bc.canonical_key,
        bc.badge_code,
        FALSE AS is_alias
    FROM base_clean bc

    UNION ALL

    SELECT
        split_part(bc.slovensky, ' ', 1) AS slovensky,
        NULL::TEXT AS latinsky,
        NULL::TEXT AS cesky,
        NULL::TEXT AS typ,
        NULLIF(
            REGEXP_REPLACE(
                LOWER(REGEXP_REPLACE(split_part(bc.slovensky, ' ', 1), '\\s+', ' ', 'g')),
                '[^a-zA-Z0-9]+',
                '-',
                'g'
            ),
            ''
        ) AS canonical_key,
        NULL::TEXT AS badge_code,
        TRUE AS is_alias
    FROM base_clean bc
), alias_ranked AS (
    SELECT
        slovensky,
        latinsky,
        cesky,
        typ,
        canonical_key,
        badge_code,
        ROW_NUMBER() OVER (
            PARTITION BY canonical_key
            ORDER BY
                is_alias ASC,
                (latinsky IS NOT NULL) DESC,
                LENGTH(slovensky) DESC,
                slovensky ASC
        ) AS rn
    FROM with_aliases
    WHERE canonical_key IS NOT NULL
)
SELECT
    slovensky,
    latinsky,
    cesky,
    typ,
    canonical_key,
    badge_code
FROM alias_ranked
WHERE rn = 1
  AND canonical_key IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM tmp_huby_clean) THEN
        RAISE EXCEPTION 'No valid mushroom rows after cleanup. Check CSV format/content.';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app_variants WHERE code IN ('forago-sk', 'forago-cz')) THEN
        RAISE EXCEPTION 'Required app variants forago-sk/forago-cz not found.';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM categories c
        JOIN app_variants v ON v.id = c.app_variant_id
        WHERE v.code IN ('forago-sk', 'forago-cz')
          AND c.slug = 'mushrooms'
    ) THEN
        RAISE EXCEPTION 'Category slug=mushrooms not found for one or both variants.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM profiles) THEN
        RAISE EXCEPTION 'No profiles found. Cannot resolve created_by_user_id.';
    END IF;
END $$;

WITH variants AS (
    SELECT id, code
    FROM app_variants
    WHERE code IN ('forago-sk', 'forago-cz')
), mushroom_categories AS (
    SELECT c.id AS category_id, c.app_variant_id
    FROM categories c
    JOIN variants v ON v.id = c.app_variant_id
    WHERE c.slug = 'mushrooms'
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
    mc.app_variant_id,
    mc.category_id,
    hc.canonical_key,
    cr.user_id,
    'admin',
    'visible',
    'approved',
    TRUE,
    NULL
FROM mushroom_categories mc
CROSS JOIN creator cr
CROSS JOIN tmp_huby_clean hc
ON CONFLICT (category_id, canonical_key) WHERE canonical_key IS NOT NULL
DO UPDATE SET
    visibility_state = 'visible',
    approval_state = 'approved',
    promoted_to_admin = TRUE,
    updated_at = NOW();

WITH item_map AS (
    SELECT
        ci.id AS item_id,
        hc.slovensky,
        hc.cesky,
        hc.latinsky,
        hc.typ,
        hc.badge_code
    FROM category_items ci
    JOIN categories c ON c.id = ci.category_id
    JOIN app_variants v ON v.id = ci.app_variant_id
    JOIN tmp_huby_clean hc ON hc.canonical_key = ci.canonical_key
    WHERE c.slug = 'mushrooms'
      AND v.code IN ('forago-sk', 'forago-cz')
)
INSERT INTO category_item_translations (
    item_id,
    language_code,
    title,
    description_text
)
SELECT
    item_id,
    language_code,
    title,
    description_text
FROM (
    SELECT
        im.item_id,
        'sk'::TEXT AS language_code,
        im.slovensky AS title,
        CONCAT(
            COALESCE('Latinsky: ' || im.latinsky, ''),
            CASE
                WHEN im.latinsky IS NOT NULL AND im.typ IS NOT NULL THEN ' | '
                ELSE ''
            END,
            COALESCE('Typ: ' || im.typ, '')
        ) AS description_text
    FROM item_map im

    UNION ALL

    SELECT
        im.item_id,
        'cs'::TEXT AS language_code,
        COALESCE(im.cesky, im.slovensky) AS title,
        CONCAT(
            COALESCE('Latinsky: ' || im.latinsky, ''),
            CASE
                WHEN im.latinsky IS NOT NULL AND im.typ IS NOT NULL THEN ' | '
                ELSE ''
            END,
            COALESCE('Typ: ' || im.typ, '')
        ) AS description_text
    FROM item_map im
) t
ON CONFLICT (item_id, language_code)
DO UPDATE SET
    title = EXCLUDED.title,
    description_text = EXCLUDED.description_text;

WITH item_map AS (
    SELECT
        ci.id AS item_id,
        hc.badge_code
    FROM category_items ci
    JOIN categories c ON c.id = ci.category_id
    JOIN app_variants v ON v.id = ci.app_variant_id
    JOIN tmp_huby_clean hc ON hc.canonical_key = ci.canonical_key
    WHERE c.slug = 'mushrooms'
      AND v.code IN ('forago-sk', 'forago-cz')
      AND hc.badge_code IS NOT NULL
), creator AS (
    SELECT id AS user_id
    FROM profiles
    ORDER BY created_at ASC
    LIMIT 1
)
INSERT INTO category_item_badges (
    item_id,
    badge_id,
    assigned_by_user_id
)
SELECT
    im.item_id,
    b.id AS badge_id,
    cr.user_id
FROM item_map im
JOIN item_badges b ON b.code = im.badge_code
CROSS JOIN creator cr
ON CONFLICT (item_id, badge_id) DO NOTHING;

-- Import summary
SELECT
    (SELECT COUNT(*) FROM tmp_huby_raw) AS raw_rows,
    (SELECT COUNT(*) FROM tmp_huby_clean) AS cleaned_rows,
    (
        SELECT COUNT(*)
        FROM category_items ci
        JOIN categories c ON c.id = ci.category_id
        JOIN app_variants v ON v.id = ci.app_variant_id
        WHERE c.slug = 'mushrooms'
          AND v.code IN ('forago-sk', 'forago-cz')
    ) AS mushrooms_items_total_variants;

COMMIT;
