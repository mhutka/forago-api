-- Migration: Add item badge dictionary and item-badge assignments

CREATE TABLE IF NOT EXISTS item_badges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT NOT NULL UNIQUE,
    icon_key TEXT NOT NULL,
    color_token TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_item_badges_active_sort
    ON item_badges(is_active, sort_order);

CREATE TABLE IF NOT EXISTS item_badge_translations (
    badge_id UUID NOT NULL REFERENCES item_badges(id) ON DELETE CASCADE,
    language_code TEXT NOT NULL
        CHECK (language_code IN ('sk', 'cs', 'en', 'de', 'pl', 'hu')),
    label TEXT NOT NULL,
    description_text TEXT,
    PRIMARY KEY (badge_id, language_code)
);

CREATE TABLE IF NOT EXISTS category_item_badges (
    item_id UUID NOT NULL REFERENCES category_items(id) ON DELETE CASCADE,
    badge_id UUID NOT NULL REFERENCES item_badges(id) ON DELETE CASCADE,
    assigned_by_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (item_id, badge_id)
);

CREATE INDEX IF NOT EXISTS idx_category_item_badges_badge_item
    ON category_item_badges(badge_id, item_id);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_proc
        WHERE proname = 'set_updated_at'
          AND pg_function_is_visible(oid)
    ) THEN
        DROP TRIGGER IF EXISTS trg_item_badges_updated_at ON item_badges;
        CREATE TRIGGER trg_item_badges_updated_at
        BEFORE UPDATE ON item_badges
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
