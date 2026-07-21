-- Migration: Create app variants and multi-variant user memberships

CREATE TABLE IF NOT EXISTS app_variants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    default_language_code TEXT NOT NULL
        CHECK (default_language_code IN ('sk', 'cs', 'en', 'de', 'pl', 'hu')),
    default_map_center_lat DOUBLE PRECISION NOT NULL,
    default_map_center_lng DOUBLE PRECISION NOT NULL,
    default_map_zoom NUMERIC(4,2) NOT NULL
        CHECK (default_map_zoom >= 1 AND default_map_zoom <= 22),
    topmenu_icon_set JSONB NOT NULL DEFAULT '{}'::jsonb,
    theme_tokens JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_app_variants_is_active
    ON app_variants(is_active);

CREATE TABLE IF NOT EXISTS user_variant_memberships (
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    app_variant_id UUID NOT NULL REFERENCES app_variants(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member'
        CHECK (role IN ('member', 'moderator', 'admin')),
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, app_variant_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_user_variant_memberships_default_per_user
    ON user_variant_memberships(user_id)
    WHERE is_default = TRUE;

CREATE INDEX IF NOT EXISTS idx_user_variant_memberships_variant
    ON user_variant_memberships(app_variant_id, is_active);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_proc
        WHERE proname = 'set_updated_at'
          AND pg_function_is_visible(oid)
    ) THEN
        DROP TRIGGER IF EXISTS trg_app_variants_updated_at ON app_variants;
        CREATE TRIGGER trg_app_variants_updated_at
        BEFORE UPDATE ON app_variants
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();

        DROP TRIGGER IF EXISTS trg_user_variant_memberships_updated_at ON user_variant_memberships;
        CREATE TRIGGER trg_user_variant_memberships_updated_at
        BEFORE UPDATE ON user_variant_memberships
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

-- Seed initial variants (SK/CZ)
INSERT INTO app_variants (
    code,
    display_name,
    default_language_code,
    default_map_center_lat,
    default_map_center_lng,
    default_map_zoom,
    topmenu_icon_set,
    theme_tokens,
    is_active
)
VALUES
(
    'forago-sk',
    'ForaGo SK',
    'sk',
    48.6690,
    19.6990,
    7.20,
    '{
      "topCategories": [
        {"slug": "mushrooms", "iconKey": "mushroom"},
        {"slug": "herbs", "iconKey": "leaf"},
        {"slug": "birds", "iconKey": "bird"},
        {"slug": "fish", "iconKey": "fish"},
        {"slug": "butterflies", "iconKey": "butterfly"},
        {"slug": "insects", "iconKey": "insect"}
      ]
    }'::jsonb,
    '{"primaryColor":"#2D6A4F","radiusScale":1.0}'::jsonb,
    TRUE
),
(
    'forago-cz',
    'ForaGo CZ',
    'cs',
    49.8175,
    15.4730,
    7.10,
    '{
      "topCategories": [
        {"slug": "mushrooms", "iconKey": "mushroom"},
        {"slug": "herbs", "iconKey": "leaf"},
        {"slug": "birds", "iconKey": "bird"},
        {"slug": "fish", "iconKey": "fish"},
        {"slug": "butterflies", "iconKey": "butterfly"},
        {"slug": "insects", "iconKey": "insect"}
      ]
    }'::jsonb,
    '{"primaryColor":"#386641","radiusScale":1.0}'::jsonb,
    TRUE
)
ON CONFLICT (code) DO UPDATE
SET
    display_name = EXCLUDED.display_name,
    default_language_code = EXCLUDED.default_language_code,
    default_map_center_lat = EXCLUDED.default_map_center_lat,
    default_map_center_lng = EXCLUDED.default_map_center_lng,
    default_map_zoom = EXCLUDED.default_map_zoom,
    topmenu_icon_set = EXCLUDED.topmenu_icon_set,
    theme_tokens = EXCLUDED.theme_tokens,
    is_active = EXCLUDED.is_active,
    updated_at = NOW();

-- Backfill only users without any membership yet.
INSERT INTO user_variant_memberships (user_id, app_variant_id, role, is_default, is_active)
SELECT p.id, v.id, 'member', TRUE, TRUE
FROM profiles p
JOIN app_variants v ON v.code = 'forago-sk'
LEFT JOIN user_variant_memberships m ON m.user_id = p.id
WHERE m.user_id IS NULL;
