-- Migration: Create find_images table (image references)

CREATE TABLE IF NOT EXISTS find_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    find_id UUID NOT NULL REFERENCES finds(id) ON DELETE CASCADE,
    thumbnail_url TEXT NOT NULL,
    full_url TEXT NOT NULL,
    storage_ref VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for find lookups
CREATE INDEX idx_find_images_find_id ON find_images(find_id);
