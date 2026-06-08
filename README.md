# HireEdge — Interview Intelligence Platform

HireEdge is an AI-powered platform that helps job seekers land interviews by analyzing their resume alongside a hiring manager's LinkedIn profile. It runs them through **six sequential AI agents** to generate a complete campaign: candidate analysis, HR profiling, positioning strategy, outreach roadmap, message copywriting, and success scoring.

## Features

- **6-Agent AI Pipeline** powered by Groq (LLaMA 3.3 70B) via LangChain
- **PDF Resume & LinkedIn Profile** analysis
- **Personalized Outreach Campaign** — LinkedIn DMs, cold emails, referral requests, thank-you notes
- **Freemium Model** — 3 free analyses, then upgrade to premium
- **JWT Authentication** (24h expiry, bcrypt hashing)
- **Dashboard** with report history and downloadable reports

## Tech Stack

| Layer | Technology | Hosting |
|-------|-----------|---------|
| Backend | Python 3.11, Flask, Waitress | Render |
| Database | SQLite via SQLAlchemy | Render (ephemeral disk) |
| AI/LLM | Groq API, LangChain, `ChatGroq` | Groq Cloud |
| Frontend | Vanilla JS, HTML5, CSS3 (no build step) | Vercel |
| Auth | JWT (HS256), bcrypt | — |
| PDF | pypdf | — |

## Quick Start

### Prerequisites

- Python 3.11
- A [Groq API key](https://console.groq.com)

### Setup

```bash
# Clone the repo
git clone https://github.com/<your-username>/hireEdge.git
cd hireEdge

# Set up virtual environment
python -m venv venv
.\venv\Scripts\activate   # Windows
# source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r backend/requirements.txt

# Configure environment
cp backend/.env.example backend/.env
# Edit backend/.env and set your GROQ_API_KEY
```

### Run

```bash
python backend/app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

## Deployment

HireEdge uses a split deployment for faster UX:

- **Frontend** → [Vercel](https://vercel.com) (static hosting, instant cold start)
- **Backend** → [Render](https://render.com) (Flask web service)

### Backend — Render

1. Create a **Web Service** on Render from your repo.
2. Set:
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app.py`
3. Add environment variables:
   - `GROQ_API_KEY` — your Groq API key
   - `SECRET_KEY` — a strong random string
   - `PYTHON_VERSION` = `3.11.0`
4. Deploy. Note the URL (e.g. `https://hireedge-backend.onrender.com`).

### Frontend — Vercel

1. Import your repo on [Vercel](https://vercel.com/new).
2. The `vercel.json` at the repo root auto-configures the `frontend/` directory.
3. Set environment variable (optional):
   - `NEXT_PUBLIC_BACKEND_URL` — your Render backend URL
4. Deploy. Vercel serves the static files with instant cold start — users see the UI while the backend wakes up.

> **Note**: The backend URL is set in a hidden `<input id="backendUrl">` in each HTML page. Update it if your Render URL changes.

## Project Structure

```
hireEdge/
├── backend/
│   ├── app.py              # Flask server, API routes, agent pipeline
│   ├── models.py           # SQLAlchemy models (User, Job)
│   ├── requirements.txt
│   ├── .env.example
│   └── Procfile
├── frontend/
│   ├── index.html          # Main app with hero, upload form, results
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── js/
│   │   ├── api.js          # Fetch wrappers, auth headers
│   │   ├── state.js        # Global state + localStorage sync
│   │   ├── main.js         # UI handlers, form logic, polling
│   │   └── render.js       # Results tab rendering
│   └── css/
│       ├── reset.css
│       ├── layout.css
│       ├── components.css
│       ├── results.css
│       └── animations.css
├── AGENTS.md
├── CLAUDE.md
├── vercel.json             # Vercel config (frontend/ root)
└── README.md
```

## API Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| `POST /api/register` | No | Register new user |
| `POST /api/login` | No | Login, returns JWT |
| `GET /api/me` | Yes | Current user info |
| `GET /api/my-reports` | Yes | Report history |
| `POST /analyse` | Yes | Start analysis (2 PDFs) |
| `GET /status/<job_id>` | Yes | Poll pipeline progress |
| `GET /report/<job_id>` | Yes | Get full report |
| `GET /health` | No | Health check |

## AI Pipeline

The pipeline runs 6 agents sequentially, each feeding its output into the next:

1. **Candidate Analyser** — Strengths, gaps, resume score
2. **HR Profiler** — Hiring manager intelligence dossier
3. **Alignment Strategist** — Positioning strategy
4. **Outreach Architect** — Day 1 / Week 1 / Month 1 roadmap
5. **Message Copywriter** — 8-piece message suite
6. **Success Analyst** — Probability scoring + action plan
