-- Keep the internal slug "herbs"; update the localized display labels.

WITH labels(variant_code, language_code, label) AS (
    VALUES
        ('forago-sk', 'sk', 'Rastliny'),
        ('forago-sk', 'cs', 'Rostliny'),
        ('forago-sk', 'en', 'Plants'),
        ('forago-cz', 'sk', 'Rastliny'),
        ('forago-cz', 'cs', 'Rostliny'),
        ('forago-cz', 'en', 'Plants')
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
WHERE c.slug = 'herbs'
  AND c.parent_category_id IS NULL
ON CONFLICT (category_id, language_code)
DO UPDATE SET
    label = EXCLUDED.label,
    description_text = EXCLUDED.description_text;
