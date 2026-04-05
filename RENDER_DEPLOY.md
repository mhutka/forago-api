# Render Deploy Guide (Backend)

## 1) Create Service
- In Render, choose New + Blueprint and point to this repository.
- Use `render.yaml` from backend root.
- Service name suggestion: `forago-backend-staging`.

## 2) Required Environment Variables
Set real values in Render dashboard:
- `DB_HOST`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `CORS_ORIGINS`
- `SUPABASE_URL`
- `JWT_ISSUER`
- `JWT_JWKS_URL`

Defaults already in blueprint:
- `ENVIRONMENT=production`
- `DATA_SOURCE_MODE=db`
- `DEBUG=false`
- `LOG_LEVEL=INFO`
- `DB_PORT=5432`
- `SUPABASE_JWT_AUDIENCE=authenticated`
- `JWT_ALGORITHMS=RS256`

## 3) CORS Example
For staging frontend:
- `CORS_ORIGINS=https://forago-staging.pages.dev`

For multiple origins, use comma-separated list:
- `CORS_ORIGINS=https://forago-staging.pages.dev,https://forago.app`

## 4) Smoke Checks After Deploy
- Health: `GET /api/health`
- Auth probe: `GET /api/auth/me` with valid Bearer token
- Private endpoint without token must return 401

## 5) Common Failures
- Startup fails with JWT config error:
  - check `JWT_ISSUER` and `JWT_JWKS_URL`
- DB connection failure:
  - verify DB host/user/password and networking
- Browser CORS errors:
  - verify `CORS_ORIGINS` matches exact frontend domain

## 6) Rollback
- In Render Deploys tab, redeploy last known good release.
- Keep `.env.staging.example` as the source of truth for required keys.
