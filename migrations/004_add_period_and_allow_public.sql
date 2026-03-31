-- Migration: Add period (seasonal half-month window) and allow_public flag to finds

ALTER TABLE finds
    ADD COLUMN IF NOT EXISTS period VARCHAR(5)
        CHECK (period IN (
            'JAN_1','JAN_2','FEB_1','FEB_2','MAR_1','MAR_2',
            'APR_1','APR_2','MAY_1','MAY_2','JUN_1','JUN_2',
            'JUL_1','JUL_2','AUG_1','AUG_2','SEP_1','SEP_2',
            'OCT_1','OCT_2','NOV_1','NOV_2','DEC_1','DEC_2'
        ));

-- allow_public: controls whether this find contributes to public clusters
-- Default TRUE so existing records remain visible
ALTER TABLE finds
    ADD COLUMN IF NOT EXISTS allow_public BOOLEAN NOT NULL DEFAULT TRUE;

-- Indexes for filtered queries
CREATE INDEX IF NOT EXISTS idx_finds_period ON finds(period);
CREATE INDEX IF NOT EXISTS idx_finds_allow_public ON finds(allow_public);
