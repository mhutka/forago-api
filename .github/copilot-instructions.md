# Copilot Instructions for forago_backend

Use `AGENTS.md` in repository root as the primary policy document.

## Required Context
- Treat ForaGo as a full-stack product: backend in this repo + Flutter frontend in a separate repo/workspace.
- Protect API contracts unless explicitly asked to change them.

## Required Practices
- Keep changes minimal and request-scoped.
- Use parameterized SQL and existing query layer boundaries.
- Flag frontend impact when endpoint behavior, payloads, or auth expectations change.
- Run relevant tests when possible and report what was/was not validated.