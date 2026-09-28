-- Replace Butterflies with Wildlife and reclassify existing finds as Insects.

INSERT INTO categories (
    app_variant_id,
    parent_category_id,
    slug,
    icon_key,
    sort_order,
    is_active
)
SELECT id, NULL, 'wildlife', 'wildlife', 50, TRUE
FROM app_variants
WHERE code IN ('forago-sk', 'forago-cz')
ON CONFLICT (app_variant_id, slug) DO UPDATE
SET
    icon_key = EXCLUDED.icon_key,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    updated_at = NOW();

WITH labels AS (
    SELECT 'forago-sk'::text AS variant_code, 'sk'::text AS language_code,
           'Zver'::text AS label
    UNION ALL
    SELECT 'forago-cz', 'cs', 'Zvířata'
)
INSERT INTO category_translations (
    category_id,
    language_code,
    label,
    description_text
)
SELECT c.id, labels.language_code, labels.label, NULL
FROM categories c
JOIN app_variants v ON v.id = c.app_variant_id
JOIN labels ON labels.variant_code = v.code
WHERE c.slug = 'wildlife'
ON CONFLICT (category_id, language_code) DO UPDATE
SET label = EXCLUDED.label;

-- Keep each find, changing only its top-level category membership.
INSERT INTO find_categories (find_id, category_id)
SELECT fc.find_id, insects.id
FROM find_categories fc
JOIN categories butterflies ON butterflies.id = fc.category_id
JOIN categories insects
  ON insects.app_variant_id = butterflies.app_variant_id
 AND insects.slug = 'insects'
WHERE butterflies.slug = 'butterflies'
ON CONFLICT (find_id, category_id) DO NOTHING;

DELETE FROM find_categories fc
USING categories butterflies
WHERE fc.category_id = butterflies.id
  AND butterflies.slug = 'butterflies';

-- Removing butterfly items also clears their tag links and nulls legacy item references.
DELETE FROM category_items items
USING categories butterflies
WHERE items.category_id = butterflies.id
  AND butterflies.slug = 'butterflies';

DELETE FROM categories
WHERE slug = 'butterflies';

UPDATE app_variants variant
SET topmenu_icon_set = jsonb_set(
    COALESCE(variant.topmenu_icon_set, '{}'::jsonb),
    '{topCategories}',
    (
        SELECT jsonb_agg(
            CASE
                WHEN entry.value->>'slug' = 'butterflies'
                    THEN jsonb_build_object('slug', 'wildlife', 'iconKey', 'wildlife')
                ELSE entry.value
            END
            ORDER BY entry.ordinality
        )
        FROM jsonb_array_elements(
            COALESCE(variant.topmenu_icon_set->'topCategories', '[]'::jsonb)
        ) WITH ORDINALITY AS entry(value, ordinality)
    ),
    TRUE
)
WHERE variant.code IN ('forago-sk', 'forago-cz')
  AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements(
          COALESCE(variant.topmenu_icon_set->'topCategories', '[]'::jsonb)
      ) AS category(value)
      WHERE category.value->>'slug' = 'butterflies'
  );