-- Migration: Extend finds/comments with variant and share/comment metadata

ALTER TABLE finds
    ADD COLUMN IF NOT EXISTS app_variant_id UUID,
    ADD COLUMN IF NOT EXISTS share_token TEXT,
    ADD COLUMN IF NOT EXISTS share_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS share_expires_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS ux_finds_share_token
    ON finds(share_token)
    WHERE share_token IS NOT NULL;

ALTER TABLE find_comments
    ADD COLUMN IF NOT EXISTS parent_comment_id UUID REFERENCES find_comments(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS language_code TEXT
        CHECK (language_code IN ('sk', 'cs', 'en', 'de', 'pl', 'hu')),
    ADD COLUMN IF NOT EXISTS app_variant_id UUID;

CREATE INDEX IF NOT EXISTS idx_find_comments_parent_comment_id
    ON find_comments(parent_comment_id);

-- Backfill app_variant_id for finds via default membership of find owner.
WITH defaults AS (
    SELECT user_id, app_variant_id
    FROM user_variant_memberships
    WHERE is_default = TRUE
), candidate AS (
    SELECT f.id AS find_id, d.app_variant_id
    FROM finds f
    JOIN defaults d ON d.user_id = f.user_id
)
UPDATE finds f
SET app_variant_id = c.app_variant_id
FROM candidate c
WHERE f.id = c.find_id
  AND f.app_variant_id IS NULL;

-- Fallback for any remaining rows: assign SK variant.
UPDATE finds f
SET app_variant_id = v.id
FROM app_variants v
WHERE f.app_variant_id IS NULL
  AND v.code = 'forago-sk';

ALTER TABLE finds
    ALTER COLUMN app_variant_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_finds_app_variant'
          AND conrelid = 'finds'::regclass
    ) THEN
        ALTER TABLE finds
            ADD CONSTRAINT fk_finds_app_variant
            FOREIGN KEY (app_variant_id) REFERENCES app_variants(id) ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_finds_variant_public_date
    ON finds(app_variant_id, allow_public, date DESC);

CREATE INDEX IF NOT EXISTS idx_finds_variant_user_date
    ON finds(app_variant_id, user_id, date DESC);

CREATE INDEX IF NOT EXISTS idx_finds_variant_cluster_date
    ON finds(app_variant_id, cluster_hash, date DESC);

CREATE INDEX IF NOT EXISTS idx_finds_variant_period_date
    ON finds(app_variant_id, period, date DESC);

-- Backfill comment language and variant using related find.
UPDATE find_comments c
SET language_code = COALESCE(c.language_code, 'sk')
WHERE c.language_code IS NULL;

UPDATE find_comments c
SET app_variant_id = f.app_variant_id
FROM finds f
WHERE c.find_id = f.id
  AND c.app_variant_id IS NULL;

ALTER TABLE find_comments
    ALTER COLUMN language_code SET NOT NULL,
    ALTER COLUMN app_variant_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_find_comments_app_variant'
          AND conrelid = 'find_comments'::regclass
    ) THEN
        ALTER TABLE find_comments
            ADD CONSTRAINT fk_find_comments_app_variant
            FOREIGN KEY (app_variant_id) REFERENCES app_variants(id) ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_find_comments_variant_find_created
    ON find_comments(app_variant_id, find_id, created_at);
