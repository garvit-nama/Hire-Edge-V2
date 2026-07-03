# AGENTS.md

Complements `CLAUDE.md`. Only what an agent would likely miss.

## Env gotchas

- `python-dotenv` loads `backend/.env` at startup — required but not mentioned in CLAUDE.md
- `app.py:60` hardcodes `sqlite:///hireedge.db`; the `DATABASE_URL` env var from `.env.example` (PostgreSQL) is **ignored**
- `SECRET_KEY` falls back to `'hireedge-super-secret-key'` if unset
- `GROQ_API_KEY` must be ≥20 chars; `/health` returns `groq: false` if missing
- Python 3.11 only (`runtime.txt`)

## Auth & limits

- JWT `Authorization: Bearer <token>` required for: `/analyse`, `/status/<jid>`, `/report/<jid>`, `/api/me`, `/api/my-reports`
- Tokens expire in 24h; upgrade is simulated client-side (writes `tier: premium` to localStorage)
- Free tier limit = 3 analyses → 403

## Frontend quirks

- Progress is polled (`setInterval` → `/status/<jid>`), not SSE/WebSocket
- `backendUrl` read from `<input id="backendUrl">` (hidden input for dev/prod switching)
- `downloadReport()` in `api.js:365` does **not** send auth headers
- No build step — Flask serves `../frontend/` directly

## Quality

- **No tests, no linter, no typechecker** — must be configured from scratch

## Pipeline details

- 6 agents run sequentially: a1→a2→a3→a4→a5→a6, each feeding the next
- Rate-limit retry: 8s × attempt, 3 max; invalid key errors immediately
- PDFs auto-deleted in `finally` block after processing
- DB tables auto-created via `db.create_all()` on first startup
- Reports saved to both `backend/reports/{jid}.txt` and SQLite `job` table
- All AI output cleaned by `clean_output()` (strips markdown)
