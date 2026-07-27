-- Migration: allow one find to reference multiple category items as searchable tags

CREATE TABLE IF NOT EXISTS find_tag_items (
    find_id UUID NOT NULL REFERENCES finds(id) ON DELETE CASCADE,
    category_item_id UUID NOT NULL REFERENCES category_items(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (find_id, category_item_id)
);

CREATE INDEX IF NOT EXISTS idx_find_tag_items_item_find
    ON find_tag_items(category_item_id, find_id);

CREATE INDEX IF NOT EXISTS idx_find_tag_items_find
    ON find_tag_items(find_id);

INSERT INTO find_tag_items (find_id, category_item_id)
SELECT id, find_item_id
FROM finds
WHERE find_item_id IS NOT NULL
ON CONFLICT (find_id, category_item_id) DO NOTHING;