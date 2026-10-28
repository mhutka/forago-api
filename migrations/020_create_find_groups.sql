-- Migration: Find groups (several finds from one trip shown as a single find)

CREATE TABLE IF NOT EXISTS find_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_find_groups_user_id ON find_groups(user_id);

-- group_seq orders members inside a group; the lowest group_seq is the main find.
-- captured_at is the exact moment a single find was captured (date stays shared in a group).
ALTER TABLE finds
    ADD COLUMN IF NOT EXISTS group_id UUID REFERENCES find_groups(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS group_seq INTEGER,
    ADD COLUMN IF NOT EXISTS captured_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS ux_finds_group_seq
    ON finds(group_id, group_seq)
    WHERE group_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_finds_group_id
    ON finds(group_id)
    WHERE group_id IS NOT NULL;
