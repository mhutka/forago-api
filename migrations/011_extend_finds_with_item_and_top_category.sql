-- Migration: Extend finds with item/category linkage for new top-menu filtering flow

ALTER TABLE finds
    ADD COLUMN IF NOT EXISTS top_category_slug TEXT,
    ADD COLUMN IF NOT EXISTS find_item_id UUID REFERENCES category_items(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_finds_variant_top_category_date
    ON finds(app_variant_id, top_category_slug, date DESC);

CREATE INDEX IF NOT EXISTS idx_finds_variant_item_date
    ON finds(app_variant_id, find_item_id, date DESC);

-- Best-effort backfill for existing records from legacy category_paths first segment.
UPDATE finds
SET top_category_slug = LOWER(NULLIF((category_paths #>> '{0,0}'), ''))
WHERE top_category_slug IS NULL
  AND jsonb_typeof(category_paths) = 'array'
  AND jsonb_array_length(category_paths) > 0
  AND jsonb_typeof(category_paths -> 0) = 'array'
  AND jsonb_array_length(category_paths -> 0) > 0;
