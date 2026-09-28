-- Ensure Wildlife has a real fallback item with a database UUID.

WITH unknown_creator AS (
    SELECT id AS user_id
    FROM profiles
    ORDER BY created_at ASC
    LIMIT 1
), target_categories AS (
    SELECT c.id AS category_id, c.app_variant_id, v.default_language_code
    FROM categories c
    JOIN app_variants v ON v.id = c.app_variant_id
    WHERE c.slug = 'wildlife'
      AND c.parent_category_id IS NULL
      AND v.code IN ('forago-sk', 'forago-cz')
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
    WHERE NOT EXISTS (
        SELECT 1
        FROM category_items ci
        WHERE ci.category_id = tc.category_id
          AND ci.canonical_key = 'unknown'
    )
    RETURNING id, app_variant_id
)
INSERT INTO category_item_translations (
    item_id,
    language_code,
    title,
    description_text
)
SELECT
    ii.id,
    v.default_language_code,
    CASE v.default_language_code
        WHEN 'cs' THEN 'Neznámý'
        ELSE 'Neznámy'
    END,
    'Fallback item for required add-record flow.'
FROM inserted_items ii
JOIN app_variants v ON v.id = ii.app_variant_id
ON CONFLICT (item_id, language_code) DO UPDATE
SET
    title = EXCLUDED.title,
    description_text = EXCLUDED.description_text;