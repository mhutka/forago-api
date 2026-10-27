CREATE TABLE IF NOT EXISTS find_likes (
    find_id UUID NOT NULL REFERENCES finds(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (find_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_find_likes_user_id ON find_likes(user_id);

ALTER TABLE find_comments
    ADD COLUMN IF NOT EXISTS is_misidentification_report BOOLEAN NOT NULL DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS ux_find_comments_one_report_per_user
    ON find_comments(find_id, user_id)
    WHERE is_misidentification_report = TRUE;

CREATE INDEX IF NOT EXISTS idx_find_comments_reports
    ON find_comments(find_id)
    WHERE is_misidentification_report = TRUE;
