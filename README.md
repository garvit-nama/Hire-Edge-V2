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

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, Flask, Waitress |
| Database | SQLite via SQLAlchemy |
| AI/LLM | Groq API, LangChain, `ChatGroq` |
| Frontend | Vanilla JS, HTML5, CSS3 (no build step) |
| Auth | JWT (HS256), bcrypt |
| PDF | pypdf |

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

### Deploy (Heroku)

```bash
heroku create your-app-name
heroku config:set GROQ_API_KEY=your_key
heroku config:set SECRET_KEY=a-strong-secret
git push heroku main
```

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
