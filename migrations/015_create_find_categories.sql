-- Migration: real M:N find<->category join table, replacing the denormalized
-- finds.category_paths (JSONB) and finds.top_category_slug (text) fields.
-- A find can belong to multiple categories; subcategories are not used
-- (categories table only has top-level rows), so category_id here always
-- points at a top-level category row.

CREATE TABLE IF NOT EXISTS find_categories (
    find_id UUID NOT NULL REFERENCES finds(id) ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (find_id, category_id)
);

CREATE INDEX IF NOT EXISTS idx_find_categories_category_find
    ON find_categories(category_id, find_id);

CREATE INDEX IF NOT EXISTS idx_find_categories_find
    ON find_categories(find_id);

-- Backfill from the normalized tag relationship (each category_item already
-- belongs to exactly one category).
INSERT INTO find_categories (find_id, category_id)
SELECT DISTINCT fti.find_id, ci.category_id
FROM find_tag_items fti
JOIN category_items ci ON ci.id = fti.category_item_id
ON CONFLICT DO NOTHING;

-- Safety-net backfill from the legacy denormalized slug for any find whose
-- tags didn't already cover it.
INSERT INTO find_categories (find_id, category_id)
SELECT DISTINCT f.id, c.id
FROM finds f
JOIN categories c
  ON c.app_variant_id = f.app_variant_id
 AND c.slug = f.top_category_slug
 AND c.parent_category_id IS NULL
WHERE f.top_category_slug IS NOT NULL
ON CONFLICT DO NOTHING;

ALTER TABLE finds DROP COLUMN IF EXISTS category_paths;
ALTER TABLE finds DROP COLUMN IF EXISTS top_category_slug;
