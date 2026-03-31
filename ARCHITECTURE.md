# ForaGo Backend Architecture

## Overview
FastAPI + PostgreSQL backend for ForaGo bushcraft finding app. Dual-mode operation: mock (testing) or PostgreSQL (production).

## Technology Stack
- **Framework**: FastAPI 0.104.1
- **Server**: Uvicorn
- **Database**: PostgreSQL + asyncpg (async driver)
- **ORM**: Raw SQL via asyncpg (no ORM for query control)
- **Validation**: Pydantic v2
- **Auth**: JWT (planned, not yet wired)

## Project Structure

```
forago_backend/
├── main.py                    # FastAPI app + all HTTP endpoints
├── database.py                # Asyncpg pool + migrations runner
├── queries.py                 # Async query helpers for CRUD operations
├── requirements.txt           # Python dependencies
├── DB_SETUP.md                # Local PostgreSQL setup guide
├── .env.example               # Environment variables template
├── migrations/
│   ├── 001_create_finds.sql         # finds table schema
│   ├── 002_create_find_images.sql   # find_images table schema
│   └── 003_create_find_comments.sql # find_comments table schema
├── venv/                      # Python virtual environment
└── __pycache__/               # (ignored)
```

## Core Modules

### `main.py` — FastAPI Application
**Responsibilities:**
- App initialization + CORS middleware
- Pydantic request/response models
- HTTP route handlers
- Error handlers
- Startup/shutdown lifecycle

**Key Objects:**
```python
DATA_SOURCE_MODE = os.getenv("DATA_SOURCE_MODE", "mock")
# "mock" → use in-memory MOCK_FINDS dict
# "db"   → use PostgreSQL via asyncpg

MOCK_FINDS = {
    "rec_001": PrivateFindRecord(...),
    "rec_002": PublicFindRecord(...),
}
```

**Route Groups:**
1. **Health Check**
   - `GET /api/health` → `{"status": "ok", "dataSourceMode": ...}`

2. **Finds Endpoints** (main API)
   - `GET /api/finds/public` → List[PublicFindRecord]
   - `GET /api/finds/private?user_id=X` → List[PrivateFindRecord]
   - `GET /api/finds/nearby?cluster=X` → List[PublicFindRecord]
   - `POST /api/finds` → PrivateFindRecord (create)
   - `GET /api/finds/{id}` → PrivateFindRecord (get one)
   - `PUT /api/finds/{id}` → PrivateFindRecord (update, stub)
   - `DELETE /api/finds/{id}` → 204 No Content (delete, stub)

3. **Clusters Endpoints** (aggregated data)
   - `GET /api/clusters` → List[PublicClusterRecord]

### `database.py` — Connection & Migrations
**Responsibilities:**
- Manage asyncpg connection pool
- Load and run SQL migrations
- Provide durable database reference

**Key Functions:**
```python
async def init_db()
    # Create asyncpg.Pool with 5-20 connections
    # Called by app startup if DATA_SOURCE_MODE == "db"

async def close_db()
    # Close connection pool gracefully
    # Called by app shutdown

async def run_migrations()
    # Read all .sql files from migrations/ folder
    # Execute each in order (001, 002, 003...)
    # Runs on app startup after init_db()

def get_pool() -> asyncpg.Pool
    # Return global _pool reference
    # Used by queries.py

async def get_db_connection()
    # Acquire single connection from pool
    # Useful for transactions (not currently used)
```

**Environment Variables:**
```python
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "forago")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
```

### `queries.py` — Async Query Layer
**Responsibilities:**
- Encapsulate all database queries
- Handle parameter binding & filters
- Convert database rows → Python dicts → Pydantic models

**Key Functions:**

| Function | Input | Output | Used By |
|----------|-------|--------|---------|
| `query_public_finds()` | cluster, category, from_date, to_date | List[dict] | GET /api/finds/public |
| `query_private_finds()` | user_id, cluster, category, from_date, to_date | List[dict] | GET /api/finds/private |
| `query_finds_nearby()` | cluster, category, from_date, to_date | List[dict] | GET /api/finds/nearby |
| `insert_find()` | user_id, date, description, cluster_hash, lat, lng, category_paths | dict | POST /api/finds |

**Query Patterns:**

**Parameterized Query (prevents SQL injection):**
```python
query = "SELECT id, user_id FROM finds WHERE user_id = $1 AND cluster_hash = $2"
rows = await conn.fetch(query, user_id, cluster_hash)
```

**JSONB Containment (category filtering):**
```python
# Query: category_paths @> '["nature", "forest"]'::jsonb[]
# This checks if category_paths array contains ["nature", "forest"] as subarray
if category:
    segments = [seg for seg in category.split("/")]
    query += " AND category_paths @> $N::jsonb[]"
    params.append(json.dumps([segments]))
```

**Result Conversion:**
```python
results = []
for row in rows:
    results.append({
        "id": str(row["id"]),  # UUID → string
        "userId": str(row["user_id"]),
        "date": row["date"],  # TIMESTAMPTZ already datetime
        ...
    })
return [PublicFindRecord(**r) for r in results]  # Pydantic validation
```

### SQL Migrations
**Pattern:** `NNN_description.sql` (lexicographic ordering)

**001_create_finds.sql:**
- Main record table
- Columns: id (UUID), user_id, date, description, cluster_hash, latitude, longitude, category_paths (JSONB)
- Indexes for performance: user_id, cluster_hash, date, (user_id, cluster_hash)

**002_create_find_images.sql:**
- Store image metadata (thumbnails + full URLs)
- Foreign key to finds(id) with ON DELETE CASCADE
- Index on find_id for quick lookups

**003_create_find_comments.sql:**
- User comments on finds
- Foreign key to finds(id)
- Index on find_id + user_id for filtering

## Data Flow (DB Mode)

```
┌─────────────────────────────────────────────────────────────┐
│ Flutter App (lib/data/repositories/api_find_records_repo)   │
└─────────────────────────────────────────────────────────────┘
                          ↓
                   HTTP GET /api/finds/public
                   HTTP POST /api/finds
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ FastAPI Router (main.py route handler)                       │
│ - Parse query params (cluster, category, from_date, to_date) │
│ - Choose: if DATA_SOURCE_MODE == "db" → DB else → mock      │
└─────────────────────────────────────────────────────────────┘
                          ↓
               if DATA_SOURCE_MODE == "db":
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ queries.py (query_xxx functions)                             │
│ - Build parameterized SQL query                              │
│ - Apply filters (cluster, category, date range)              │
│ - Execute via conn.fetch() or conn.fetchrow()                │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ asyncpg.Pool (database.py)                                   │
│ - Get connection from pool (non-blocking)                    │
│ - Execute query against PostgreSQL                           │
│ - Return rows as asyncpg.Record objects                      │
└─────────────────────────────────────────────────────────────┘
                          ↓
              ┌───────────────────────┐
              │  PostgreSQL Database  │
              │  (finds, find_images, │
              │   find_comments)      │
              └───────────────────────┘
                          ↑
                   SQL Query + Params
```

## Dual-Mode Pattern

**All key endpoints follow this pattern:**

```python
@app.get("/api/finds/public", response_model=List[PublicFindRecord])
async def get_public_finds(cluster: Optional[str] = None, ...):
    try:
        if DATA_SOURCE_MODE == "db":
            # Database query
            results_data = await query_public_finds(cluster=cluster, ...)
            return [PublicFindRecord(**r) for r in results_data]
        else:
            # Mock mode (in-memory)
            results = _public_records_from_mock()
            if cluster:
                results = [f for f in results if f.clusterHash == cluster]
            return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")
```

**Benefits:**
- ✅ No code duplication (same logic flow both paths)
- ✅ Graceful degradation (if DB fails, operator can switch to mock)
- ✅ Easy testing (mock mode works without PostgreSQL)
- ✅ Zero Flutter-side changes needed (response shape identical)

## Error Handling Strategy

**HTTP Status Codes:**
- `200 OK` — Successful GET or PUT
- `201 Created` — Successful POST /api/finds
- `204 No Content` — Successful DELETE
- `400 Bad Request` — Client error (invalid params)
- `403 Forbidden` — User doesn't own record (future, with JWT)
- `404 Not Found` — Record doesn't exist
- `500 Internal Server Error` — DB query failed, unhandled exception
- `501 Not Implemented` — Feature not yet coded

**Response Format (errors):**
```python
{
    "error": "string details",
    "status": 500,
    "timestamp": "2026-03-25T10:00:00.000000"
}
```

## Authentication (Planned)

Currently: **no authentication** — `user_id` passed as query param by client.

**Future JWT flow:**
```python
from jose import jwt

# In route:
async def get_private_finds(
    cluster: Optional[str] = None,
    current_user: str = Depends(get_current_user)  # ← Validates JWT
):
    # Use current_user instead of ?user_id param
```

Where `get_current_user()` extracts + validates JWT token.

## Performance Considerations

1. **Connection Pooling**: asyncpg maintains min=5 idle connections, scales to max=20. Reuse > new connections.
2. **Indexes**: All filter columns (user_id, cluster_hash, date) indexed for O(log n) lookup.
3. **JSONB**: PostgreSQL JSONB is stored in binary format, efficiently indexed with GIN operators (`@>`).
4. **No N+1**: Images & comments not fetched yet (returns empty arrays). Future: use JOINs or batch queries.

## Running Tests

**Mock mode (no DB needed):**
```bash
python main.py
# Uses hardcoded MOCK_FINDS in memory
```

**Database mode:**
```bash
# .env: DATA_SOURCE_MODE=db
python main.py
# Initializes pool, runs migrations, connects to PostgreSQL
```

**Quick health check:**
```bash
curl http://localhost:8000/api/health
# {"status": "ok", "dataSourceMode": "db", ...}
```

## Deployment Checklist

- [ ] Set `DATA_SOURCE_MODE=db` in production `.env`
- [ ] Point `DB_HOST`, `DB_USER`, `DB_PASSWORD` to production PostgreSQL
- [ ] Ensure migrations run on startup
- [ ] Test all 4 endpoints after deploy
- [ ] Implement JWT authentication before public launch
- [ ] Monitor connection pool (`DB_PORT 5432` open, no firewall blocks)
- [ ] Set up automated backups for PostgreSQL

## References

- **asyncpg docs**: https://magicstack.github.io/asyncpg/current/
- **PostgreSQL JSONB**: https://www.postgresql.org/docs/current/datatype-json.html
- **FastAPI**: https://fastapi.tiangolo.com/
- **Pydantic**: https://docs.pydantic.dev/latest/
