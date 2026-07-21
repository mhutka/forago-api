-- Migration: Seed initial top categories, unknown items, and badge dictionary

WITH variants AS (
    SELECT id, code, default_language_code
    FROM app_variants
    WHERE code IN ('forago-sk', 'forago-cz')
)
INSERT INTO categories (app_variant_id, parent_category_id, slug, icon_key, sort_order, is_active)
SELECT v.id, NULL, c.slug, c.icon_key, c.sort_order, TRUE
FROM variants v
CROSS JOIN (
    VALUES
        ('mushrooms', 'mushroom', 10),
        ('herbs', 'leaf', 20),
        ('birds', 'bird', 30),
        ('fish', 'fish', 40),
        ('butterflies', 'butterfly', 50),
        ('insects', 'insect', 60)
) AS c(slug, icon_key, sort_order)
ON CONFLICT (app_variant_id, slug) DO UPDATE
SET
    icon_key = EXCLUDED.icon_key,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    updated_at = NOW();

WITH labels AS (
    SELECT 'mushrooms'::text AS slug, 'sk'::text AS language_code, 'Huby'::text AS label UNION ALL
    SELECT 'herbs', 'sk', 'Bylinky' UNION ALL
    SELECT 'birds', 'sk', 'Vtaky' UNION ALL
    SELECT 'fish', 'sk', 'Ryby' UNION ALL
    SELECT 'butterflies', 'sk', 'Motyle' UNION ALL
    SELECT 'insects', 'sk', 'Hmyz' UNION ALL
    SELECT 'mushrooms', 'cs', 'Houby' UNION ALL
    SELECT 'herbs', 'cs', 'Bylinky' UNION ALL
    SELECT 'birds', 'cs', 'Ptaci' UNION ALL
    SELECT 'fish', 'cs', 'Ryby' UNION ALL
    SELECT 'butterflies', 'cs', 'Motyli' UNION ALL
    SELECT 'insects', 'cs', 'Hmyz'
)
INSERT INTO category_translations (category_id, language_code, label, description_text)
SELECT c.id, l.language_code, l.label, NULL
FROM categories c
JOIN app_variants v ON v.id = c.app_variant_id
JOIN labels l ON l.slug = c.slug AND l.language_code = v.default_language_code
ON CONFLICT (category_id, language_code) DO UPDATE
SET label = EXCLUDED.label;

-- Ensure each top category has an admin-owned fallback item: "unknown".
WITH unknown_creator AS (
    SELECT id AS user_id
    FROM profiles
    ORDER BY created_at ASC
    LIMIT 1
), target_categories AS (
    SELECT c.id AS category_id, c.app_variant_id
    FROM categories c
    WHERE c.parent_category_id IS NULL
), inserted_items AS (
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
        'unknown',
        uc.user_id,
        'admin',
        'visible',
        'approved',
        TRUE,
        NULL
    FROM target_categories tc
    CROSS JOIN unknown_creator uc
    WHERE uc.user_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1
                FROM category_items ci
                WHERE ci.category_id = tc.category_id
                    AND ci.canonical_key = 'unknown'
            )
    RETURNING id, app_variant_id
)
INSERT INTO category_item_translations (item_id, language_code, title, description_text)
SELECT ii.id, v.default_language_code, 'Neznamy', 'Fallback item for required add-record flow.'
FROM inserted_items ii
JOIN app_variants v ON v.id = ii.app_variant_id
ON CONFLICT (item_id, language_code) DO UPDATE
SET
    title = EXCLUDED.title,
    description_text = EXCLUDED.description_text;

INSERT INTO item_badges (code, icon_key, color_token, is_active, sort_order)
VALUES
    ('edible', 'badge_edible', '#2A9D8F', TRUE, 10),
    ('inedible', 'badge_inedible', '#6C757D', TRUE, 20),
    ('poisonous', 'badge_poisonous', '#C1121F', TRUE, 30)
ON CONFLICT (code) DO UPDATE
SET
    icon_key = EXCLUDED.icon_key,
    color_token = EXCLUDED.color_token,
    is_active = EXCLUDED.is_active,
    sort_order = EXCLUDED.sort_order,
    updated_at = NOW();

WITH badge_labels AS (
    SELECT 'edible'::text AS code, 'sk'::text AS language_code, 'Jedla'::text AS label, 'Bezpecna na konzumaciu.'::text AS description_text UNION ALL
    SELECT 'inedible', 'sk', 'Nejedla', 'Nevhodna na konzumaciu.' UNION ALL
    SELECT 'poisonous', 'sk', 'Jedovata', 'Rizikova alebo toxicka.' UNION ALL
    SELECT 'edible', 'cs', 'Jedla', 'Bezpecna pro konzumaci.' UNION ALL
    SELECT 'inedible', 'cs', 'Nejedla', 'Nevhodna pro konzumaci.' UNION ALL
    SELECT 'poisonous', 'cs', 'Jedovata', 'Rizikova nebo toxicka.' UNION ALL
    SELECT 'edible', 'en', 'Edible', 'Safe to consume.' UNION ALL
    SELECT 'inedible', 'en', 'Inedible', 'Not suitable for consumption.' UNION ALL
    SELECT 'poisonous', 'en', 'Poisonous', 'Toxic or potentially dangerous.'
)
INSERT INTO item_badge_translations (badge_id, language_code, label, description_text)
SELECT b.id, bl.language_code, bl.label, bl.description_text
FROM item_badges b
JOIN badge_labels bl ON bl.code = b.code
ON CONFLICT (badge_id, language_code) DO UPDATE
SET
    label = EXCLUDED.label,
    description_text = EXCLUDED.description_text;
