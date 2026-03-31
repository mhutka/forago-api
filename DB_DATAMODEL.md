# ForaGo DB Datamodel (Current State)

This document describes the current, implemented PostgreSQL datamodel based on migrations:
- 001_create_finds.sql
- 002_create_find_images.sql
- 003_create_find_comments.sql

## 1) Entity Relationship Overview

finds (1) ---- (N) find_images
finds (1) ---- (N) find_comments

Delete behavior:
- Deleting one row from finds cascades to find_images and find_comments.

## 2) Tables

### finds
Purpose:
- Main storage for find records used by public/private endpoints.

Columns:
- id: UUID, PRIMARY KEY, default gen_random_uuid()
- user_id: UUID, NOT NULL
- date: TIMESTAMPTZ, NOT NULL
- description: TEXT, nullable
- cluster_hash: VARCHAR(50), NOT NULL
- latitude: DOUBLE PRECISION, NOT NULL
- longitude: DOUBLE PRECISION, NOT NULL
- category_paths: JSONB, NOT NULL, default []
- period: VARCHAR(5), nullable, CHECK IN ('JAN_1','JAN_2','FEB_1','FEB_2','MAR_1','MAR_2','APR_1','APR_2','MAY_1','MAY_2','JUN_1','JUN_2','JUL_1','JUL_2','AUG_1','AUG_2','SEP_1','SEP_2','OCT_1','OCT_2','NOV_1','NOV_2','DEC_1','DEC_2')
- allow_public: BOOLEAN, NOT NULL, default TRUE
- created_at: TIMESTAMPTZ, NOT NULL, default now()
- updated_at: TIMESTAMPTZ, NOT NULL, default now()

Indexes:
- idx_finds_user_id on (user_id)
- idx_finds_cluster_hash on (cluster_hash)
- idx_finds_date on (date)
- idx_finds_user_id_cluster on (user_id, cluster_hash)
- idx_finds_period on (period)
- idx_finds_allow_public on (allow_public)

Period field notes:
- Represents which half-month a find was recorded in
- Format: 3-letter month code + underscore + half (1 = first half, 2 = second half)
- Examples: MAR_1 = first half of March (1st–15th), OCT_2 = second half of October (16th–31st)
- Used for seasonal search: "what can I find in mid-autumn?"
- Nullable: old records without period will not appear in period-filtered queries

Allow_public field notes:
- Controls whether the find contributes to public cluster views
- Default TRUE so records are public by default
- Setting to FALSE hides from GET /api/finds/public and /nearby but still visible in /private for the owner
- Intended for future UI: toggle per record by the user


### find_images
Purpose:
- Image references belonging to one find.

Columns:
- id: UUID, PRIMARY KEY, default gen_random_uuid()
- find_id: UUID, NOT NULL, FOREIGN KEY -> finds(id) ON DELETE CASCADE
- thumbnail_url: TEXT, NOT NULL
- full_url: TEXT, NOT NULL
- storage_ref: VARCHAR(255), nullable
- created_at: TIMESTAMPTZ, NOT NULL, default now()

Indexes:
- idx_find_images_find_id on (find_id)


### find_comments
Purpose:
- User comments for one find.

Columns:
- id: UUID, PRIMARY KEY, default gen_random_uuid()
- find_id: UUID, NOT NULL, FOREIGN KEY -> finds(id) ON DELETE CASCADE
- user_id: UUID, NOT NULL
- text: TEXT, NOT NULL
- created_at: TIMESTAMPTZ, NOT NULL, default now()
- updated_at: TIMESTAMPTZ, NOT NULL, default now()

Indexes:
- idx_find_comments_find_id on (find_id)
- idx_find_comments_user_id on (user_id)

## 3) Relationship Cardinality

- finds to find_images: one-to-many
- finds to find_comments: one-to-many

Meaning:
- One find can have zero or more images.
- One find can have zero or more comments.

## 4) Integrity Rules Already Enforced

- Primary keys on all three tables.
- Foreign keys with cascade delete from child tables to finds.
- NOT NULL on required fields for API contract consistency.
- Default timestamps on create.
- JSONB used for hierarchical category paths.

## 5) Query-Driven Model Notes

Current backend query layer uses these patterns:
- Filtering finds by cluster_hash, date range, and user_id.
- Category filtering via JSONB containment on category_paths.
- Nearby queries resolve via cluster_hash.

Current API response shape supports:
- finds as base records
- images and comments arrays (currently empty placeholders in query mapping; relation is ready in schema)

## 6) Gaps / Next Migration Candidates

Recommended next migration(s):
- Add trigger to auto-update updated_at on update for finds and find_comments.
- Add CHECK constraints for coordinate ranges:
  - latitude between -90 and 90
  - longitude between -180 and 180
- Add GIN index for category_paths JSONB if category filtering volume grows.
- Add users table FK when auth module is finalized (for user_id references).

## 7) Practical Mapping to App Model

- finds maps to:
  - PublicFindRecord (public mode, no exact location exposed in response logic)
  - PrivateFindRecord (private mode, location exposed)
- find_images maps to RecordImageRef list
- find_comments maps to RecordComment list
