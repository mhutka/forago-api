-- Users can create their own item even if another user used the same key.
DROP INDEX IF EXISTS ux_category_items_category_canonical_key;

CREATE UNIQUE INDEX IF NOT EXISTS ux_category_items_admin_canonical_key
    ON category_items(category_id, canonical_key)
    WHERE canonical_key IS NOT NULL AND owner_type = 'admin';

CREATE UNIQUE INDEX IF NOT EXISTS ux_category_items_user_canonical_key
    ON category_items(category_id, canonical_key, created_by_user_id)
    WHERE canonical_key IS NOT NULL AND owner_type = 'user';
