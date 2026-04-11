-- Migration: Create user profiles/preferences and badge storage
-- This keeps auth identity in auth.users and app-level profile data in public schema.

CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Account and activity metadata
    account_tier TEXT NOT NULL DEFAULT 'free'
        CHECK (account_tier IN ('free', 'vip')),
    badge TEXT,
    last_action_at TIMESTAMPTZ,

    -- UI preferences
    language_code TEXT NOT NULL DEFAULT 'sk'
        CHECK (language_code IN ('sk', 'cs', 'en', 'de', 'pl', 'hu')),
    map_center_lat DOUBLE PRECISION NOT NULL DEFAULT 48.1486,
    map_center_lng DOUBLE PRECISION NOT NULL DEFAULT 17.1077,
    map_zoom NUMERIC(4,2) NOT NULL DEFAULT 11.00
        CHECK (map_zoom >= 1 AND map_zoom <= 22),
    default_category TEXT NOT NULL DEFAULT 'nature/forest',

    -- Display profile
    display_nickname TEXT NOT NULL,
    display_name TEXT,
    avatar_url TEXT,

    -- Audit timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Case-insensitive uniqueness for nickname
CREATE UNIQUE INDEX IF NOT EXISTS ux_profiles_display_nickname_lower
    ON profiles (LOWER(display_nickname));

CREATE TABLE IF NOT EXISTS user_badges (
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    badge_code TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    granted_by UUID,
    PRIMARY KEY (user_id, badge_code)
);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_profiles_updated_at ON profiles;
CREATE TRIGGER trg_profiles_updated_at
BEFORE UPDATE ON profiles
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION handle_new_auth_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    base_nick TEXT;
BEGIN
    base_nick := COALESCE(
        NULLIF(split_part(NEW.email, '@', 1), ''),
        'user_' || substr(replace(NEW.id::text, '-', ''), 1, 8)
    );

    INSERT INTO profiles (
        id,
        display_nickname,
        display_name,
        account_tier,
        language_code,
        map_center_lat,
        map_center_lng,
        map_zoom,
        default_category
    )
    VALUES (
        NEW.id,
        base_nick,
        COALESCE(NEW.raw_user_meta_data ->> 'full_name', base_nick),
        'free',
        'sk',
        48.1486,
        17.1077,
        11.00,
        'nature/forest'
    )
    ON CONFLICT (id) DO NOTHING;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
AFTER INSERT ON auth.users
FOR EACH ROW
EXECUTE FUNCTION handle_new_auth_user();

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_badges ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'profiles' AND policyname = 'profiles_select_own'
    ) THEN
        CREATE POLICY profiles_select_own
        ON profiles
        FOR SELECT
        TO authenticated
        USING (auth.uid() = id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'profiles' AND policyname = 'profiles_update_own'
    ) THEN
        CREATE POLICY profiles_update_own
        ON profiles
        FOR UPDATE
        TO authenticated
        USING (auth.uid() = id)
        WITH CHECK (auth.uid() = id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'profiles' AND policyname = 'profiles_insert_own'
    ) THEN
        CREATE POLICY profiles_insert_own
        ON profiles
        FOR INSERT
        TO authenticated
        WITH CHECK (auth.uid() = id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'user_badges' AND policyname = 'user_badges_select_own'
    ) THEN
        CREATE POLICY user_badges_select_own
        ON user_badges
        FOR SELECT
        TO authenticated
        USING (auth.uid() = user_id);
    END IF;
END $$;
