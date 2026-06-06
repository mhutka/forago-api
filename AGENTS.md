# AGENTS.md

## Project Context (Always Assume)
- This product is full-stack, not backend-only.
- Backend in this workspace: `forago_backend` (FastAPI + PostgreSQL).
- Frontend exists in a separate Flutter workspace/repo (commonly sibling `forago`).
- Any backend API change can break Flutter app contracts.

## Non-Negotiable Working Rules
1. Always evaluate impact on both backend and frontend, even if task mentions only one side.
2. Do not change API response field names, types, or semantics without explicitly calling it out.
3. Preserve backward compatibility by default; if breaking change is required, document migration steps.
4. Keep changes minimal and scoped to the request. Avoid unrelated refactors.
5. Never commit secrets or environment credentials.

## Backend Standards (FastAPI + asyncpg)
- Use parameterized SQL only (`$1`, `$2`, ...). Never build SQL by string interpolation.
- Keep DB access in `queries.py` and connection lifecycle in `database.py`.
- Validate and serialize through Pydantic models used by route handlers.
- Return explicit HTTP errors (`HTTPException`) with correct status codes.
- Keep route handlers lean: validate input, call query layer, map output.

## Frontend-Awareness Rules
- For endpoint edits, verify:
  - URL path and method stability
  - query/body parameter compatibility
  - response JSON shape compatibility (camelCase fields used by app)
  - auth requirement changes (public vs private endpoints)
- If compatibility risk exists, include a short "Frontend impact" note in the final response.

## Testing and Validation Checklist
Before finishing any change:
1. Run or update relevant tests (`pytest` scope by changed feature).
2. If API contract changed, add/update at least one test covering the new contract.
3. Mention what was validated and what was not validated.
4. If frontend cannot be tested from this workspace, state that explicitly.

## Dependency Rules
- Keep pinned versions unless there is a proven compatibility/security reason to change.
- Before changing pinned versions in `requirements.txt`, validate availability and resolver compatibility with pip dry-run.

## Communication Rules
- In every implementation summary, include:
  - changed files
  - behavior change
  - compatibility risk (if any)
  - test status

## If Context Is Missing
- When a task likely affects Flutter behavior and frontend code is not available, ask for frontend repo path or confirm assumptions before making risky contract changes.