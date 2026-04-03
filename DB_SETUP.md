# ForaGo Backend — DB Setup & Local Testing Guide

## Quick Start: Mock Mode (No DB needed)
```bash
cd forago_backend
python main.py
```
✓ Backend runs on `http://localhost:8000`
✓ Uses hardcoded `MOCK_FINDS` data
✓ Swagger docs: `http://localhost:8000/docs`

## Switch to Database Mode

### Step 1: Install PostgreSQL

**Windows:**
- Download from https://www.postgresql.org/download/windows/
- During install: set password for `postgres` user
- Ensure `psql` is in PATH

**Verify installation:**
```powershell
psql --version
# psql (PostgreSQL) 15.x
```

### Step 2: Create Database

```bash
psql -U postgres

# In psql prompt:
CREATE DATABASE forago;
CREATE USER forago_user WITH PASSWORD 'password123';
GRANT ALL PRIVILEGES ON DATABASE forago TO forago_user;
\q
```

Or quick one-liner:
```bash
psql -U postgres -c "CREATE DATABASE forago;" -c "CREATE USER forago_user WITH PASSWORD 'password123';" -c "GRANT ALL PRIVILEGES ON DATABASE forago TO forago_user;"
```

### Step 3: Configure Backend

Create `.env` file in `forago_backend/`:
```
DATA_SOURCE_MODE=db
DB_HOST=localhost
DB_PORT=5432
DB_NAME=forago
DB_USER=forago_user
DB_PASSWORD=password123
```

### Step 4: Run Backend

```bash
cd forago_backend
python main.py
```

**Expected output:**
```
🚀 ForaGo API started
📖 Docs: http://localhost:8000/docs
🔧 ReDoc: http://localhost:8000/redoc
🗂️ Data source mode: db
✓ DB pool initialized: forago_user@localhost:5432/forago
✓ 001_create_finds.sql executed
✓ 002_create_find_images.sql executed
✓ 003_create_find_comments.sql executed
```

### Step 5: Test Endpoints

**Create a find record (authenticated):**
```bash
export TOKEN="<jwt-with-sub-uuid>"

curl -X POST http://localhost:8000/api/finds \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "date": "2026-03-25T10:00:00Z",
    "categoryPaths": [["nature", "forest", "oak"]],
    "description": "Beautiful oak tree",
    "location": {"latitude": 48.14, "longitude": 17.11},
    "clusterHash": "48.14_17.11"
  }'
```

**List all public finds:**
```bash
curl http://localhost:8000/api/finds/public
```

**Filter by cluster:**
```bash
curl http://localhost:8000/api/finds/public?cluster=48.14_17.11
```

**Get private records for current user:**
```bash
curl http://localhost:8000/api/finds/private \
  -H "Authorization: Bearer $TOKEN"
```

## Troubleshooting

### PostgreSQL Connection Failed
```
psycopg2.OperationalError: could not connect to server
```
→ Check running: `pg_isrunning` or check Services (Windows)

### Migrations Not Running
```
✗ DB pool init failed: [error]
```
→ Check `.env` variables (DB_HOST, DB_NAME, DB_USER, DB_PASSWORD)
→ Verify database created: `psql -l`

### Fallback to Mock Mode
If DB is unavailable, set:
```
DATA_SOURCE_MODE=mock
```
Backend will skip DB init and use hardcoded data.

## Reset Database

If you need to start fresh:
```bash
psql -U postgres -c "DROP DATABASE forago;" -c "CREATE DATABASE forago;" -c "GRANT ALL PRIVILEGES ON DATABASE forago TO forago_user;"
```

Then restart backend — migrations will re-run automatically.

## Flutter Testing with DB

1. Start backend in DB mode (see above)
2. Update `lib/config/dependencies.dart` → `const String _apiBaseUrl = 'http://127.0.0.1:8000'`
3. Run Flutter:
   ```bash
   cd forago
   flutter run
   ```
4. App will fetch real data from PostgreSQL

## Supabase Alternative

If using Supabase instead of local PostgreSQL:

1. Create project at https://supabase.com
2. Go to **Settings → Database** → copy connection string
3. Update `.env`:
   ```
   DB_HOST=xyz.supabase.co
   DB_PORT=5432
   DB_NAME=postgres
   DB_USER=postgres
   DB_PASSWORD=[your-password]
   ```
4. Supabase will auto-run migrations (SQL executed as-is)

## Supabase Auth (JWT) Integration

Backend now validates Bearer JWT for private endpoints.

Recommended `.env` setup for Supabase Auth:
```
SUPABASE_URL=https://<project-ref>.supabase.co
JWT_ALGORITHMS=RS256
JWT_JWKS_URL=https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json
JWT_ISSUER=https://<project-ref>.supabase.co/auth/v1
SUPABASE_JWT_AUDIENCE=authenticated
```

If your Supabase project uses HS256 secret tokens, use:
```
JWT_ALGORITHMS=HS256
JWT_SECRET_KEY=<supabase-jwt-secret>
JWT_ISSUER=https://<project-ref>.supabase.co/auth/v1
SUPABASE_JWT_AUDIENCE=authenticated
```

Quick check with a real access token from Flutter/Supabase login:
```bash
curl http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer <access_token>"
```

Expected response:
```json
{
  "userId": "<supabase-user-uuid>",
  "issuer": "https://<project-ref>.supabase.co/auth/v1",
  "audience": "authenticated"
}
```

## Next Steps

- [ ] Add test data to `finds` table
- [ ] Implement DELETE/UPDATE endpoints (currently stub)
- [x] Add JWT authentication
- [ ] Fetch images and comments from related tables
