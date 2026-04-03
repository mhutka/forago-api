-- Migration: Create find_comments table (user comments on records)

CREATE TABLE IF NOT EXISTS find_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    find_id UUID NOT NULL REFERENCES finds(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_find_comments_find_id ON find_comments(find_id);
CREATE INDEX IF NOT EXISTS idx_find_comments_user_id ON find_comments(user_id);
