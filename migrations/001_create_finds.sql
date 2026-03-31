-- Migration: Create finds table (main record storage)

CREATE TABLE IF NOT EXISTS finds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    date TIMESTAMPTZ NOT NULL,
    description TEXT,
    cluster_hash VARCHAR(50) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    category_paths JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for common queries
CREATE INDEX idx_finds_user_id ON finds(user_id);
CREATE INDEX idx_finds_cluster_hash ON finds(cluster_hash);
CREATE INDEX idx_finds_date ON finds(date);
CREATE INDEX idx_finds_user_id_cluster ON finds(user_id, cluster_hash);
