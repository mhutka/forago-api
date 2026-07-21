-- Migration: Create category tree and category item domain per app variant

CREATE TABLE IF NOT EXISTS categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_variant_id UUID NOT NULL REFERENCES app_variants(id) ON DELETE CASCADE,
    parent_category_id UUID NULL REFERENCES categories(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    icon_key TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (app_variant_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_categories_variant_parent_sort
    ON categories(app_variant_id, parent_category_id, sort_order);

CREATE TABLE IF NOT EXISTS category_translations (
    category_id UUID NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    language_code TEXT NOT NULL
        CHECK (language_code IN ('sk', 'cs', 'en', 'de', 'pl', 'hu')),
    label TEXT NOT NULL,
    description_text TEXT,
    PRIMARY KEY (category_id, language_code)
);

CREATE TABLE IF NOT EXISTS category_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_variant_id UUID NOT NULL REFERENCES app_variants(id) ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    canonical_key TEXT,
    created_by_user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    owner_type TEXT NOT NULL
        CHECK (owner_type IN ('admin', 'user')),
    visibility_state TEXT NOT NULL DEFAULT 'visible'
        CHECK (visibility_state IN ('visible', 'hidden')),
    approval_state TEXT NOT NULL DEFAULT 'none'
        CHECK (approval_state IN ('none', 'approved', 'rejected')),
    promoted_to_admin BOOLEAN NOT NULL DEFAULT FALSE,
    image_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_category_items_category_canonical_key
    ON category_items(category_id, canonical_key)
    WHERE canonical_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_category_items_variant_visibility_approval
    ON category_items(app_variant_id, visibility_state, approval_state);

CREATE INDEX IF NOT EXISTS idx_category_items_creator
    ON category_items(created_by_user_id, approval_state);

CREATE TABLE IF NOT EXISTS category_item_translations (
    item_id UUID NOT NULL REFERENCES category_items(id) ON DELETE CASCADE,
    language_code TEXT NOT NULL
        CHECK (language_code IN ('sk', 'cs', 'en', 'de', 'pl', 'hu')),
    title TEXT NOT NULL,
    description_text TEXT,
    search_tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', COALESCE(title, '') || ' ' || COALESCE(description_text, ''))
    ) STORED,
    PRIMARY KEY (item_id, language_code)
);

CREATE INDEX IF NOT EXISTS idx_category_item_translations_search
    ON category_item_translations USING GIN(search_tsv);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_proc
        WHERE proname = 'set_updated_at'
          AND pg_function_is_visible(oid)
    ) THEN
        DROP TRIGGER IF EXISTS trg_categories_updated_at ON categories;
        CREATE TRIGGER trg_categories_updated_at
        BEFORE UPDATE ON categories
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();

        DROP TRIGGER IF EXISTS trg_category_items_updated_at ON category_items;
        CREATE TRIGGER trg_category_items_updated_at
        BEFORE UPDATE ON category_items
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
