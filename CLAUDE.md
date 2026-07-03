# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HireEdge is an AI-powered interview intelligence platform that analyzes candidate resumes and HR profiles to generate personalized outreach strategies. Uses 6 sequential AI agents powered by Groq/LangChain.

## Architecture

**Stack:**
- **Backend:** Flask + Waitress (production WSGI), SQLite (SQLAlchemy ORM)
- **Frontend:** Vanilla JS + CSS (no framework), server-side rendered from Flask
- **AI:** LangChain 1.2.x + ChatGroq with callback-based progress tracking
- **Auth:** JWT tokens (bcrypt hashing), stored in localStorage

**Key Pattern:** The 6 agents run sequentially, each building on previous outputs:
1. Candidate Analyser → 2. HR Profiler → 3. Alignment Strategist → 4. Outreach Architect → 5. Message Copywriter → 6. Success Analyst

## Directory Structure

```
hireEdge/
├── backend/
│   ├── app.py          # Flask server, API routes, 6 agent definitions
│   ├── models.py       # SQLAlchemy: User, Job tables
│   └── requirements.txt
├── frontend/
│   ├── index.html      # Main app (hero + upload + results)
│   ├── login.html      # Auth page
│   ├── register.html   # Auth page
│   ├── dashboard.html  # Report history view
│   ├── js/
│   │   ├── state.js    # Global state (token, user, jobId, results)
│   │   ├── api.js      # Fetch wrappers for backend calls
│   │   ├── main.js     # UI handlers, agent board rendering
│   │   └── render.js   # Results tab rendering
│   └── css/            # Modular CSS (reset, layout, components, results, animations)
```

## Commands

**Setup:**
```bash
cd backend
pip install -r requirements.txt
```

**Run (development):**
```bash
cd backend
python app.py
# Server: http://localhost:5000
# Health: http://localhost:5000/health
```

**Environment (.env):**
```
GROQ_API_KEY=gsk_xxxx
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///hireedge.db
```

## API Routes

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/` | GET | - | Serve index.html |
| `/health` | GET | - | Groq API key status |
| `/models` | GET | - | List available AI models |
| `/api/register` | POST | - | Create user |
| `/api/login` | POST | - | JWT token |
| `/api/me` | GET | ✓ | Current user info |
| `/api/my-reports` | GET | ✓ | User's report history |
| `/analyse` | POST | ✓ | Start 6-agent pipeline (free tier: 3 max) |
| `/status/<jid>` | GET | ✓ | Poll job progress |
| `/report/<jid>` | GET | ✓ | Download report |

## Freemium Model

- Free tier: 3 analyses max (`free_analyses_used` counter)
- Premium tier: unlimited (set `subscription_tier='premium'`)
- Limit enforced in `/analyse` route (returns 403)

## Frontend Patterns

- **State:** Global `S` object in `state.js`, synced to localStorage for auth
- **API calls:** `getBase()` returns backend URL, `getHeaders()` adds JWT
- **Progress polling:** `pollJob()` interval until status = 'complete'/'error'
- **Step indicator:** `setStep(n)` updates progress bar (steps 1-4)

## Notes

- PDFs uploaded to `backend/uploads/`, deleted after processing
- Reports saved to `backend/reports/` + database
- Waitress WSGI server (Windows-compatible, production-ready)
- All markdown stripped from AI outputs via `clean_output()`
