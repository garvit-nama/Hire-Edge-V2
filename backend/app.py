#!/usr/bin/env python3
"""
HireEdge — Production Backend
===============================
Stack:
  - Flask + Waitress              (production WSGI — Windows compatible)
  - LangChain 1.2.x + ChatGroq    (LLM calls — no AgentExecutor needed)
  - LangChain Callbacks           (real-time progress tracking)
  - pypdf                         (PDF extraction)
  - Groq API                      (LLM provider)

INSTALL:
  pip install flask flask-cors langchain langchain-core langchain-groq groq pypdf waitress

SET KEY:
  Windows CMD:        set GROQ_API_KEY=gsk_xxxx
  Windows PowerShell: $env:GROQ_API_KEY="gsk_xxxx"

RUN:
  python app.py
"""
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

import os, re, time, json, uuid, threading, traceback, logging

# ── Flask ──────────────────────────────────────────────────────────────────────
from flask import Flask, request, jsonify, Response, g
from flask_cors import CORS

# ── WebSocket (Phase 5) ─────────────────────────────────────────────────────────
from flask_socketio import SocketIO, emit, join_room, leave_room

import bcrypt
import jwt
from functools import wraps
import datetime
from sqlalchemy.exc import OperationalError
from sqlalchemy import text as sa_text

# ── LangChain 1.2.x compatible imports ────────────────────────────────────────
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.callbacks.base import BaseCallbackHandler

# ── PDF extraction ─────────────────────────────────────────────────────────────
from pypdf import PdfReader

from flask import send_from_directory

# ── Models ─────────────────────────────────────────────────────────────────────
from models import db, User, Job

# ════════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════════════════════════
app = Flask(__name__, static_folder='../frontend', static_url_path='')

# ── CORS (Phase 2) ───────────────────────────────────────────────────────────
# Fully environment-configurable via ALLOWED_ORIGINS comma-separated list.
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if not ALLOWED_ORIGINS:
    raise RuntimeError(
        "ALLOWED_ORIGINS must be set in environment, e.g. "
        "'https://my-app.vercel.app,http://localhost:5000'"
    )
CORS(app, origins=ALLOWED_ORIGINS, supports_credentials=True)

# ── JWT Secret (Phase 1) ────────────────────────────────────────────────────
# No fallback — must be set explicitly in the environment.
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY must be set in environment and be >= 32 chars")
app.config['SECRET_KEY'] = SECRET_KEY

# ── Rate Limiting (Phase 3) ─────────────────────────────────────────────────
# In-memory only — no Redis. Limits reset on deploy/restart, acceptable for single-worker.
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
)

# ── WebSocket (Phase 5) ─────────────────────────────────────────────────────
# (eventlet monkey_patch was removed; waitress/threading is Windows-compatible)
socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS, async_mode='threading', logger=False, engineio_logger=False)

# ── Request ID Correlation (Phase 5) ────────────────────────────────────────
# Inject X-Request-ID into every response; read incoming if provided.
@app.before_request
def _inject_request_id():
    g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

@app.after_request
def _add_request_id_header(response):
    response.headers["X-Request-ID"] = g.request_id
    return response

# ── PDF Validation (Phase 4) ─────────────────────────────────────────────────
MAX_PDF_SIZE = 10 * 1024 * 1024  # 10 MB absolute limit
ALLOWED_MIME_TYPES = {"application/pdf"}
PDF_MAGIC_HEADER = b"%PDF-"


def _validate_pdf_file(file_storage, field_name: str):
    """Validate an uploaded PDF file.

    Checks:
    - File exists and has a filename
    - Non-zero size
    - Recognizable PDF magic header (%PDF-)
    - MIME type matches application/pdf
    - File size under MAX_PDF_SIZE (10 MB)
    - File extension .pdf

    Raises ValueError on any failure. Returns True on success.
    """
    if not file_storage:
        raise ValueError(f"{field_name} file is missing")
    if not file_storage.filename:
        raise ValueError(f"{field_name} has no filename")
    # Extension check
    if not file_storage.filename.lower().endswith(".pdf"):
        raise ValueError(f"{field_name} must have .pdf extension (got: {file_storage.filename})")
    # Size check — seek to end
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size == 0:
        raise ValueError(f"{field_name} is empty")
    if size > MAX_PDF_SIZE:
        raise ValueError(f"{field_name} exceeds {MAX_PDF_SIZE // 1024 // 1024}MB size limit (got {size // 1024 // 1024}MB)")
    # MIME type check (best-effort from browser)
    if file_storage.mimetype and file_storage.mimetype not in ALLOWED_MIME_TYPES:
        logging.warning(f"[PDF] {field_name} MIME mismatch: {file_storage.mimetype}, forcing extension check")
    # Magic header check — read first 5 bytes
    header = file_storage.stream.read(5)
    file_storage.stream.seek(0)
    if not header.startswith(PDF_MAGIC_HEADER):
        raise ValueError(f"{field_name} is not a valid PDF (missing '%PDF-' magic header)")
    return True
# Use absolute paths relative to backend/ so Procfile `python backend/app.py` vs `python app.py` both work
_BACKEND_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER  = _BACKEND_DIR / "uploads";  UPLOAD_FOLDER.mkdir(exist_ok=True)
REPORTS_FOLDER = _BACKEND_DIR / "reports"; REPORTS_FOLDER.mkdir(exist_ok=True)

# Database: respect DATABASE_URL env (Supabase Postgres on Render) else fallback to SQLite
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///hireedge.db")
# Normalize SQLite to absolute path to avoid cwd drift (python app.py vs python backend/app.py vs gunicorn)
if DATABASE_URL and DATABASE_URL.startswith("sqlite:///") and ":memory:" not in DATABASE_URL:
    # sqlite:////absolute vs sqlite:///relative
    if not DATABASE_URL.startswith("sqlite:////"):
        rel = DATABASE_URL[len("sqlite:///"):]
        # Only convert relative paths
        if rel and not Path(rel).is_absolute() and "://" not in rel:
            abs_path = (_BACKEND_DIR / rel).resolve()
            DATABASE_URL = f"sqlite:///{abs_path.as_posix()}"
# SQLAlchemy 2.x requires postgresql:// not postgres://
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Prevent pooled connections from going stale on Render/Supabase + timeouts
is_postgres = DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")
connect_args = {"connect_timeout": 5}
if is_postgres:
    # Supabase requires SSL; pooler on 6543 prefers sslmode=require
    connect_args["sslmode"] = "require"
    # TCP keepalives help on Render free tier
    connect_args["keepalives"] = 1
    connect_args["keepalives_idle"] = 30
    connect_args["keepalives_interval"] = 10
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True, "pool_recycle": 300, "connect_args": connect_args}

# Configure logging to stdout (Waitress/Flask capture stdout by default)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().handlers = []  # clear existing handlers from basicConfig
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)

# Phase 3: Initialize rate limiter (in-memory only, Redis postponed)
limiter.init_app(app)

# Helper: sanitized DB host for logs (hide password)
def _db_host_log(url: str) -> str:
    try:
        if "@" in url:
            return url.split("@")[-1]
        return url
    except Exception:
        return "unknown"

# Allow explicit SQLite fallback when Postgres is unreachable (useful for local dev if Supabase paused)
ALLOW_SQLITE_FALLBACK = os.environ.get("ALLOW_SQLITE_FALLBACK", "true").lower() in ("true", "1", "yes")

db.init_app(app)

# Ensure tables exist — log but don't crash on DB connection failure (shows as 500 otherwise)
# Try primary DB first, fallback to SQLite if enabled and OperationalError occurs
def _init_db_with_fallback():
    global DATABASE_URL
    try:
        with app.app_context():
            db.create_all()
            # Verify connectivity with a simple query
            db.session.execute(sa_text("SELECT 1"))
            db.session.commit()
            logging.info(f"[DB] connected: {_db_host_log(DATABASE_URL)}")
            return True
    except OperationalError as oe:
        logging.warning(f"[DB] OperationalError on create_all: {oe}; host={_db_host_log(DATABASE_URL)}")
        if ALLOW_SQLITE_FALLBACK and not DATABASE_URL.startswith("sqlite"):
            fallback_path = (_BACKEND_DIR / "hireedge.db").resolve()
            fallback_url = f"sqlite:///{fallback_path.as_posix()}"
            logging.warning(f"[DB] Falling back to SQLite: {fallback_url} (ALLOW_SQLITE_FALLBACK=true)")
            try:
                # Reconfigure engine to SQLite and retry
                app.config['SQLALCHEMY_DATABASE_URI'] = fallback_url
                # Need to recreate engine: dispose old, clear session
                try:
                    db.session.remove()
                    db.engine.dispose()
                except Exception:
                    pass
                # Update global for health reporting
                DATABASE_URL = fallback_url
                with app.app_context():
                    db.create_all()
                    db.session.execute(sa_text("SELECT 1"))
                    db.session.commit()
                    logging.info(f"[DB] fallback SQLite connected: {fallback_url}")
                    return True
            except Exception as fe:
                logging.error(f"[DB] fallback SQLite also failed: {fe}\n{traceback.format_exc()[-1200:]}")
        else:
            logging.warning(f"[DB] No fallback enabled. Set ALLOW_SQLITE_FALLBACK=true to use local SQLite when Supabase is unreachable. | trace: {traceback.format_exc()[-800:]}")
        return False
    except Exception as e:
        logging.warning(f"[DB] create_all failed ({e}); will retry on first request. DB URL: {_db_host_log(DATABASE_URL)} | trace: {traceback.format_exc()[-800:]}")
        return False

_init_db_with_fallback()

# ── Auth Middleware ────────────────────────────────────────────────────────────
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            parts = request.headers['Authorization'].split()
            if len(parts) == 2 and parts[0] == 'Bearer':
                token = parts[1]
        
        if not token:
            return jsonify({'error': 'Token is missing!'}), 401
            
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = User.query.filter_by(id=data['user_id']).first()
            if not current_user:
                return jsonify({'error': 'User not found. Please register again.'}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired. Please login again.'}), 401
        except jwt.InvalidTokenError as e:
            return jsonify({'error': f'Token is invalid: {str(e)}'}), 401
        except OperationalError as oe:
            logging.error(f"[auth] DB OperationalError: {oe}; host={_db_host_log(DATABASE_URL)}")
            try:
                db.session.rollback()
            except Exception:
                pass
            return jsonify({
                'error': 'Database unavailable',
                'detail': 'Could not reach database. Host may be wrong or Supabase paused. Check DATABASE_URL (use pooler host aws-0-...pooler.supabase.com:6543 with ?sslmode=require)',
                'hint': _db_host_log(DATABASE_URL)
            }), 503
        except Exception as e:
            logging.warning(f"[auth] token decode failed: {e}")
            return jsonify({'error': 'Token is invalid!'}), 401
            
        return f(current_user, *args, **kwargs)
    return decorated


# ════════════════════════════════════════════════════════════════════════════════
#  WEBSOCKET HANDLERS (Phase 5)
# ════════════════════════════════════════════════════════════════════════════════

@socketio.on('connect')
def handle_connect():
    print(f"[OK] WebSocket client connected: {request.sid}")
    emit('connected', {'data': 'Connected to HireEdge server'})

@socketio.on('join_job')
def on_join_job(data):
    """Client joins a job room to receive real-time status updates"""
    jid = data.get('job_id') if isinstance(data, dict) else str(data)
    join_room(jid)
    print(f"[ROOM] Client {request.sid} joined room: {jid}")
    emit('joined', {'job_id': jid})

@socketio.on('disconnect')
def handle_disconnect(*args):
    print(f"[DISCONNECT] WebSocket client disconnected: {request.sid}")


GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")

DEFAULT_MODEL  = "openai/gpt-oss-120b"
RETRY_DELAY    = 8
RETRY_ATTEMPTS = 3

AVAILABLE_MODELS = [
    {"id": "openai/gpt-oss-120b",   "label": "GPT-OSS 120B",     "tag": "Best"},
    {"id": "openai/gpt-oss-20b",    "label": "GPT-OSS 20B",      "tag": "Fast"},
    {"id": "qwen/qwen3.8-27b",      "label": "Qwen 3.8 27B",     "tag": "Balanced"},
    {"id": "allam-2-7b",            "label": "ALLaM 2 7B",       "tag": "Light"},
]

jobs: dict = {}


# ════════════════════════════════════════════════════════════════════════════════
#  PDF EXTRACTION  — pypdf (no langchain_community needed)
# ════════════════════════════════════════════════════════════════════════════════

def load_pdf(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    reader = PdfReader(str(path))
    if not reader.pages:
        raise ValueError("No pages found. PDF may be empty.")
    text_parts = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if text and text.strip():
            text_parts.append(f"--- Page {i+1} ---\n{text.strip()}")
    if not text_parts:
        raise ValueError("No readable text found. PDF may be scanned/image-based.")
    return "\n\n".join(text_parts)


# ════════════════════════════════════════════════════════════════════════════════
#  MARKDOWN STRIPPER
# ════════════════════════════════════════════════════════════════════════════════

def clean_output(text: str) -> str:
    text = re.sub(r"```[\w]*\n?[\s\S]*?```", "", text)
    text = re.sub(r"`[^`\n]+`", lambda m: m.group(0)[1:-1], text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = re.sub(r"__(.+?)__",     r"\1", text)
    text = re.sub(r"_(.+?)_",       r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ════════════════════════════════════════════════════════════════════════════════
#  CALLBACK HANDLER  — updates job state, frontend polls /status
# ════════════════════════════════════════════════════════════════════════════════

AGENT_META = [
    {"id": "a1", "name": "Candidate Analyser",   "label": "Parsing resume & extracting selling points"},
    {"id": "a2", "name": "HR Profiler",           "label": "Building hiring manager intelligence model"},
    {"id": "a3", "name": "Alignment Strategist",  "label": "Matching candidate strengths to HR priorities"},
    {"id": "a4", "name": "Outreach Architect",    "label": "Designing Day / Week / Month roadmap"},
    {"id": "a5", "name": "Message Copywriter",    "label": "Crafting personalized message suite"},
    {"id": "a6", "name": "Success Analyst",       "label": "Scoring campaign & building action plan"},
]

def get_agents_status(progress, status, current_message):
    agents = []
    for i, meta in enumerate(AGENT_META):
        agent_status = "queued"
        agent_label = meta["label"]
        if i < progress:
            agent_status = "done"
            agent_label = "Complete"
        elif i == progress:
            if status == "running":
                agent_status = "running"
                agent_label = current_message
            elif status == "error":
                agent_status = "error"
                agent_label = "Failed"
        agents.append({
            "id": meta["id"],
            "name": meta["name"],
            "label": agent_label,
            "status": agent_status,
            "error": None
        })
    return agents


class AgentProgressCallback(BaseCallbackHandler):
    def __init__(self, job_id: str, agent_index: int, agent_name: str):
        self.job_id      = job_id
        self.agent_index = agent_index
        self.agent_name  = agent_name

    def _job(self):
        return jobs.get(self.job_id)

    def on_llm_start(self, serialized, prompts, **kwargs):
        job = self._job()
        msg = f"Running {self.agent_name}..."
        if job:
            job["agents"][self.agent_index]["status"] = "running"
            job["agents"][self.agent_index]["label"]  = f"{self.agent_name}: querying LLM..."
            job["message"] = msg

        try:
            with app.app_context():
                job_db = Job.query.filter_by(id=self.job_id).first()
                if job_db:
                    job_db.current_message = msg
                    try:
                        db.session.commit()
                    except Exception as e:
                        logging.warning(f"[callback] on_llm_start commit failed: {e}")
                        db.session.rollback()
                    progress = job_db.progress
                else:
                    progress = 0
                agents_snapshot = job["agents"] if job else get_agents_status(progress, 'running', msg)
                try:
                    socketio.emit('job_status', {
                        'id': self.job_id,
                        'status': 'running',
                        'progress': progress,
                        'message': msg,
                        'agents': agents_snapshot
                    }, room=self.job_id)
                except Exception as e:
                    logging.warning(f"[socketio] on_llm_start emit failed: {e}")
        except Exception as e:
            logging.warning(f"[callback] on_llm_start failed: {e}")

    def on_llm_end(self, response, **kwargs):
        job = self._job()
        msg = f"{self.agent_name}: processing output..."
        if job:
            job["agents"][self.agent_index]["label"] = msg

        try:
            with app.app_context():
                job_db = Job.query.filter_by(id=self.job_id).first()
                if job_db:
                    job_db.current_message = msg
                    try:
                        db.session.commit()
                    except Exception as e:
                        logging.warning(f"[callback] on_llm_end commit failed: {e}")
                        db.session.rollback()
                    progress = job_db.progress
                else:
                    progress = 0
                agents_snapshot = job["agents"] if job else get_agents_status(progress, 'running', msg)
                try:
                    socketio.emit('job_status', {
                        'id': self.job_id,
                        'status': 'running',
                        'progress': progress,
                        'message': msg,
                        'agents': agents_snapshot
                    }, room=self.job_id)
                except Exception as e:
                    logging.warning(f"[socketio] on_llm_end emit failed: {e}")
        except Exception as e:
            logging.warning(f"[callback] on_llm_end failed: {e}")

    def on_llm_error(self, error, **kwargs):
        job = self._job()
        if job:
            job["agents"][self.agent_index]["status"] = "error"
            job["agents"][self.agent_index]["error"]  = str(error)

    def on_chain_end(self, outputs, **kwargs):
        job = self._job()
        if job:
            job["agents"][self.agent_index]["status"] = "done"
            job["agents"][self.agent_index]["label"]  = "Complete"


# ════════════════════════════════════════════════════════════════════════════════
#  SIMULATED MODE (MOCK)
# ════════════════════════════════════════════════════════════════════════════════

mock_entities = {}

def extract_entities(candidate_text, hr_text):
    # Candidate name
    candidate_name = "Alex Mercer"
    for line in candidate_text.split('\n'):
        l = line.strip()
        if l and 3 <= len(l) <= 40 and not any(x in l.lower() for x in ["@", "http", "resume", "cv", "phone", "email", "profile", "page"]):
            candidate_name = l
            break
            
    # Candidate skills
    known_skills = [
        "Python", "JavaScript", "React", "Node.js", "Java", "C++", "SQL", "PostgreSQL",
        "AWS", "Docker", "Kubernetes", "Git", "HTML", "CSS", "TypeScript", "Go", "Rust",
        "Machine Learning", "Data Analysis", "Project Management", "Agile", "Scrum"
    ]
    found_skills = []
    for skill in known_skills:
        if skill.lower() in candidate_text.lower():
            found_skills.append(skill)
    if not found_skills:
        found_skills = ["Software Engineering", "Problem Solving", "Systems Design"]
    candidate_skills = ", ".join(found_skills[:8])

    # Candidate Education
    education = "Bachelor of Science in Computer Science"
    for line in candidate_text.split('\n'):
        l = line.strip()
        if any(x in l.lower() for x in ["university", "college", "bachelor", "master", "degree", "b.s", "m.s"]):
            if len(l) < 100:
                education = l
                break

    # Candidate Experience
    experience = "5+ years of software development experience"
    for line in candidate_text.split('\n'):
        l = line.strip()
        if any(x in l.lower() for x in ["year", "experience", "lead", "senior", "developer", "engineer"]):
            if len(l) < 100 and any(char.isdigit() for char in l):
                experience = l
                break

    # HR Name & Company
    hr_name = "Sarah Jenkins"
    hr_company = "InnovateTech"
    hr_role = "Senior Talent Partner"
    
    # Try parsing HR text
    hr_lines = [l.strip() for l in hr_text.split('\n') if l.strip()]
    for i, line in enumerate(hr_lines):
        if "linkedin.com" in line.lower():
            continue
        if len(line) < 40 and not any(x in line.lower() for x in ["http", "profile", "contact", "about"]):
            hr_name = line
            # Check if next lines have company and role info
            for j in range(i+1, min(i+4, len(hr_lines))):
                next_line = hr_lines[j]
                if any(x in next_line.lower() for x in ["recruiter", "talent", "hr", "manager", "director", "acquisition"]):
                    hr_role = next_line
                if any(x in next_line.lower() for x in ["at ", "company", "inc", "co", "technologies"]):
                    hr_company = next_line.replace("at ", "").strip()
            break
            
    return {
        "candidate_name": candidate_name,
        "candidate_skills": candidate_skills,
        "candidate_education": education,
        "candidate_experience": experience,
        "hr_name": hr_name,
        "hr_company": hr_company,
        "hr_role": hr_role
    }

def generate_mock_a1(entities, role):
    return f"""CANDIDATE PROFILE
=================
Name: {entities['candidate_name']}
Current Role / Status: Software Engineer
Education: {entities['candidate_education']}
Total Experience: {entities['candidate_experience']}
Core Tech Stack / Skills: {entities['candidate_skills']}

STRONGEST SELLING POINTS FOR {role}
========================================
1. Solid foundational alignment with the core requirements of {role}.
2. Proven experience in key technologies: {entities['candidate_skills']}.
3. Strong academic background and credentials: {entities['candidate_education']}.
4. Demonstration of end-to-end ownership in past projects.
5. Excellent communication skills and collaborative professional approach.

GAPS / WEAKNESSES TO ADDRESS
==============================
1. Potential lack of direct experience with niche tools specific to {entities['hr_company']}.
2. Might need ramp-up on the internal infrastructure and deployment pipelines.
3. Resume does not explicitly detail high-scale system achievements.

HOW TO FRAME THIS CANDIDATE
=============================
Elevator pitch (3 sentences): {entities['candidate_name']} is an accomplished professional with a robust background in software engineering, specifically skilled in {entities['candidate_skills']}. They have a proven track record of delivering high-quality technical solutions and collaborating effectively across teams. Seeking to leverage their experience to drive impact in the {role} position.
Key narrative angle: A versatile and adaptable engineer who bridges technical skills with business value.
What makes them stand out: Quick learner with a solid foundation in {entities['candidate_skills']}.
What to downplay: Minimal exposure to proprietary systems or specific cloud platforms (if any).

RESUME SCORE FOR {role}: 8.5/10
Reasoning: Candidate has a very strong match for the primary skills and experience required for {role}, with minor gaps in specialized company tooling."""

def generate_mock_a2(entities):
    return f"""HR PROFILE INTELLIGENCE
========================
Name: {entities['hr_name']}
Current Role: {entities['hr_role']}
Company: {entities['hr_company']}
Industry: Technology / Staffing
Seniority: Mid-Senior Level
Location: Remote / Tech Hub

PROFESSIONAL PRIORITIES
========================
What they care about most: Hiring top talent efficiently and reducing time-to-hire.
Types of candidates they champion: Proactive, communicative, and technically sound candidates.
Topics they engage with: Employee engagement, diversity in tech, and hiring best practices.
Hiring philosophy (inferred): Values potential and soft skills as much as technical depth.

PERSONALITY & COMMUNICATION STYLE
===================================
Personality type (inferred): Warm, structured, and professional (ENFJ-like).
Preferred tone: Conversational yet respectful, brief, and direct.
Message length they prefer: Short (2-3 paragraphs max).
What gets a reply: Personalization, direct reference to active roles, clear value proposition.
What gets ignored: Generic copy-paste templates, overly aggressive follow-ups.

INFLUENCE LEVERS
=================
What impresses them: Candidates who have researched the company and mention specific challenges.
What signals a strong candidate: Clear resume layout, active GitHub/LinkedIn, concise messages.
Best conversation opener: Mentioning a recent company update or article they shared.
Topics that build rapport: Industry growth trends, candidate experience, remote work culture.

COMPANY CONTEXT
================
Company stage: Growing / Mid-size Tech
Likely hiring pain points: Sourcing qualified engineers who align with company values.
What the company values (inferred): Innovation, collaboration, and customer-first mindset."""

def generate_mock_a3(entities, role):
    return f"""POSITIONING STRATEGY
=====================
ALIGNMENT SCORE: 9.0/10
Why this candidate fits: High alignment on core tech stack ({entities['candidate_skills']}) and a proactive attitude that matches {entities['hr_name']}'s preferred candidate profile.

KEY ALIGNMENT POINTS (TOP 3)
==============================
1. Deep technical competency in {entities['candidate_skills']} directly applicable to the {role} role.
2. Experience working in collaborative environments, matching {entities['hr_company']}'s culture.
3. Strong communication skills that will resonate with a mid-senior recruiter like {entities['hr_name']}.

NARRATIVE ANGLE
================
Core story to tell: An engineer who loves solving complex problems and wants to contribute to {entities['hr_company']}'s growth.
How to connect background to HR priorities: Focus on reliability, clean code, and team collaboration.
The ONE thing this HR will remember: A candidate who took the time to personalize outreach and show genuine interest.

WHAT TO EMPHASIZE
==================
Skill 1 + why it matters to THIS HR: {entities['candidate_skills'].split(',')[0]} - directly matches their current job openings.
Skill 2 + why it matters to THIS HR: Collaboration - shows they are a team player and easy to onboard.
Achievement to highlight: Success in past projects with quantifiable impact.
Personal angle that creates connection: A shared interest in modern engineering practices.

WHAT TO AVOID
==============
Topics to skip: Lengthy explanations of unrelated past roles.
Framing that will backfire: Sounding like you are only interested in any job rather than THIS job.
Common mistakes to avoid: Copying boilerplate cover letters.

CONVERSATION HOOKS
===================
Opening hook (one sentence): I noticed your team at {entities['hr_company']} is expanding its {role} division and wanted to connect.
Question that flatters their expertise: What is the most critical quality you look for in engineers joining your team?
Shared interest / common ground: Passion for building user-centric software products."""

def generate_mock_a4(entities, role):
    return f"""OUTREACH ROADMAP FOR {role}
=================================

DAY 1 - MAKE FIRST CONTACT
----------------------------
LinkedIn connection request timing: Morning (9 AM - 10 AM local time).
What to do: Send a personalized connection request.
Note to include: Brief note referencing their work at {entities['hr_company']}.
Profile headline update: Optimize headline to match {role} keywords.
Keyword to add: {entities['candidate_skills'].split(',')[0]}.
Research move - what to find out: Look for recent articles or posts shared by {entities['hr_name']}.
Research move - how to use it: Reference their latest post in your next communication.

WEEK 1 - BUILD VISIBILITY
---------------------------
Day 2 - Action + Goal: Like or comment on a post shared by {entities['hr_name']} to build familiarity.
Day 3 - Action + Goal: Share an interesting article related to {role} on your own feed.
Day 4 - Action + Goal: Review the {role} job description at {entities['hr_company']} in detail.
Day 5 - Action + Goal: Draft your initial direct message (DM).
Day 7 - First DM message angle: Mention connection and ask a soft question about the hiring process.

WEEK 2 - ESTABLISH CREDIBILITY
--------------------------------
Move 1: Share a short post about a project you worked on using {entities['candidate_skills'].split(',')[0]}.
Move 2: Send a follow-up DM highlighting your direct match with the role requirements.
Move 3: Ask a mutual connection for an warm intro if possible.
Goal by end of week 2: Secure a short 15-minute phone screening.

MONTH 1 - CONVERT TO INTERVIEW
--------------------------------
Week 3 goal: Follow up via email with your resume and a brief portfolio link.
Week 4 goal: Schedule the technical interview stage.
Final push strategy: Offer to walk through a case study or past project.
Success milestone by Day 30: Completed first round of interviews.

FOLLOW-UP RULES
================
No reply after Day 1 connection: Wait 3 days before sending the first DM.
No reply after first DM: Wait 5 days before sending a gentle follow-up.
No reply after email: Wait 7 days before the final polite outreach.
Maximum follow-ups before moving on: 3 follow-up attempts.

PARALLEL STRATEGIES
====================
Other contacts at same company: Connect with engineering leads at {entities['hr_company']}.
Internal referral play: Reach out to alumni working at {entities['hr_company']}.
Mutual connection strategy: Ask common connections to endorse your skills on LinkedIn."""

def generate_mock_a5(entities, role):
    return f"""MESSAGE & EMAIL SUITE
======================

1. LINKEDIN CONNECTION REQUEST (max 300 characters)
----------------------------------------------------
Hi {entities['hr_name']}, I noticed you lead talent acquisition at {entities['hr_company']}. I'm a software engineer specializing in {entities['candidate_skills'].split(',')[0]} and saw your open {role} role. Would love to connect and keep in touch! Best, {entities['candidate_name']}.

2. LINKEDIN DM - AFTER CONNECTING (60-80 words)
------------------------------------------------
Hi {entities['hr_name']}, thanks for connecting! I've been following {entities['hr_company']}'s growth in the tech space and am really impressed by your culture. I recently applied for the {role} position. With my background in {entities['candidate_skills']}, I believe I could bring a lot of value to the team. Do you have 5 minutes this week for a brief chat about the role?

3. LINKEDIN DM - FOLLOW UP (40-50 words, no reply after 5 days)
---------------------------------------------------------------
Hi {entities['hr_name']}, hope you're having a great week! Just following up on my previous message regarding the {role} role. I'd love to share how my experience aligns with your team's current goals. Let me know if you have any availability. Thanks!

4. COLD EMAIL - FIRST OUTREACH
-------------------------------
Subject Line:
Software Engineer Application - {entities['candidate_name']} - {role}

Body (150-200 words):
Dear {entities['hr_name']},

I hope this email finds you well.

My name is {entities['candidate_name']}, and I am writing to express my strong interest in the {role} position at {entities['hr_company']}. Having worked as a Software Engineer with expertise in {entities['candidate_skills']}, I have successfully delivered high-performing features and collaborated with cross-functional teams to launch scalable products.

I have been following {entities['hr_company']} and admire your commitment to innovation. I believe my experience with {entities['candidate_skills'].split(',')[0]} matches what you are looking for in this role. I would appreciate the opportunity to discuss how my background can support your engineering team's current initiatives.

I have attached my resume for your review. Thank you for your time and consideration.

Sincerely,
{entities['candidate_name']}
{entities['candidate_education']}

5. FOLLOW-UP EMAIL (80-100 words, send 5 days after first email)
-----------------------------------------------------------------
Subject Line:
Follow-up: {role} Application - {entities['candidate_name']}

Body:
Hi {entities['hr_name']},

I hope you're having a productive week. I'm following up on my application for the {role} role.

I understand you're busy, but I wanted to reiterate my enthusiasm for the opportunity at {entities['hr_company']}. My technical foundation in {entities['candidate_skills']} makes me confident that I can hit the ground running.

Please let me know if there's any additional information I can provide. Looking forward to hearing from you.

Best regards,
{entities['candidate_name']}

6. FINAL EMAIL (50-70 words, Day 14, graceful last attempt)
------------------------------------------------------------
Subject Line:
Final follow-up: {role} Role - {entities['candidate_name']}

Body:
Hi {entities['hr_name']},

I'm reaching out one last time regarding the {role} opportunity. I assume the position may have been filled or your priorities have shifted, which I completely understand.

If things change, I would still love to connect in the future. I wish you and the team at {entities['hr_company']} all the best.

Best,
{entities['candidate_name']}

7. REFERRAL REQUEST (to a mutual connection, under 80 words)
-------------------------------------------------------------
Hi! Hope you're doing well. I saw you're connected to {entities['hr_name']} at {entities['hr_company']}. I'm applying for the {role} role there and think my profile is a great fit. Would you be open to introducing us? I'd really appreciate it!

8. THANK YOU MESSAGE (after reply or interview, 50-60 words)
-------------------------------------------------------------
Hi {entities['hr_name']}, thank you for taking the time to speak with me today about the {role} role. I really enjoyed learning more about {entities['hr_company']}'s goals. I'm excited about the possibility of joining the team and look forward to the next steps!

TONE GUIDE
==========
Voice to use: Professional, confident, respectful, and clear.
What makes these work for THIS HR: Directly addresses their priority of finding qualified candidates while respecting their time.
What was deliberately avoided: Overly pushy language or sounding desperate."""

def generate_mock_a6(entities, role):
    return f"""SUCCESS PROBABILITY SCORECARD
===============================
CONNECTION ACCEPTANCE RATE: 75%
  Why: The connection request is highly personalized and directly references their company, which dramatically increases acceptance rates among tech recruiters.

DM REPLY PROBABILITY: 60%
  Why: Recruiter {entities['hr_name']} values concise messages that state a clear value proposition. The drafted DM is structured perfectly.

EMAIL REPLY PROBABILITY: 55%
  Why: Clear subject line and direct link to the candidate's core skills ({entities['candidate_skills'].split(',')[0]}) matching the job description.

COLD CONVERSION TO INTERVIEW RATE: 40%
  Why: The multi-channel approach (LinkedIn + Email) and positioning strategy maximize the chances of securing a screening interview.

CRITICAL WEAKNESSES THAT COULD DERAIL THE PLAYBOOK (TOP 3)
============================================================
1. Over-relying on a single channel; must follow up on both LinkedIn and Email.
2. Failing to personalize the first email body with recent company achievements.
3. Lack of direct referral; warm intros always convert at higher rates.

TOP 3 RISKS THAT COULD DERAIL THIS
=====================================
1. The role gets filled internally before the outreach cycle completes.
2. Low responsiveness of the recruiter due to high volume of applicants.
3. Technical mismatches during the initial screening call if not prepared.

WHAT WOULD INCREASE SUCCESS BY 30%
=====================================
Action 1: Find a mutual connection working at {entities['hr_company']} and request a referral.
Action 2: Tailor your GitHub portfolio to highlight projects matching {entities['hr_company']}'s tech stack.
Action 3: Mention a specific feature or product of {entities['hr_company']} that you admire in your first message.

DAILY CHECKLIST FOR CANDIDATE
===============================
Every morning (5 mins): Check LinkedIn for connection approvals or replies.
Every evening (5 mins): Send follow-ups if the timeline dictates.
Weekly review: Assess status of all active conversations and adjust messaging.

FINAL ADVICE
=============
Single most important action: Stay consistent and follow the roadmap timeline.
Biggest mistake to avoid: Sending generic templates without customization.
Mindset note: Job hunting is a numbers and persistence game; keep your head high!"""

def run_simulated_agent(agent_name: str, callback: AgentProgressCallback) -> str:
    callback.on_llm_start(None, None)
    time.sleep(1.0)
    callback.on_llm_end(None)
    time.sleep(0.5)
    
    job_id = callback.job_id
    entities = mock_entities.get(job_id, {
        "candidate_name": "Alex Mercer",
        "candidate_skills": "Python, JavaScript, React, Node.js, SQL",
        "candidate_education": "Bachelor of Science in Computer Science",
        "candidate_experience": "5+ years of software development experience",
        "hr_name": "Sarah Jenkins",
        "hr_company": "InnovateTech",
        "hr_role": "Senior Talent Partner",
        "target_role": "Software Engineer"
    })
    role = entities.get("target_role", "Software Engineer")
    
    if agent_name == "Candidate Analyser":
        content = generate_mock_a1(entities, role)
    elif agent_name == "HR Profiler":
        content = generate_mock_a2(entities)
    elif agent_name == "Alignment Strategist":
        content = generate_mock_a3(entities, role)
    elif agent_name == "Outreach Architect":
        content = generate_mock_a4(entities, role)
    elif agent_name == "Message Copywriter":
        content = generate_mock_a5(entities, role)
    elif agent_name == "Success Analyst":
        content = generate_mock_a6(entities, role)
    else:
        content = f"Simulated response for {agent_name}."

    callback.on_chain_end(None)
    return clean_output(content)


# ════════════════════════════════════════════════════════════════════════════════
#  LLM RUNNER  — direct ChatGroq call, LangChain 1.2.x compatible
# ════════════════════════════════════════════════════════════════════════════════

PLAIN_RULE = """CRITICAL FORMAT RULES — follow exactly:
- Output ONLY plain text. Zero markdown whatsoever.
- No asterisks (*), no bold (**), no headers (#), no backticks, no code blocks.
- UPPERCASE WORDS for section headers. Dashes (-) for bullets. Numbers (1.) for lists.
- Start directly with the structured content. No preamble, no closing remarks."""


def run_agent(model_id: str, system: str, user_prompt: str,
              callback: AgentProgressCallback, agent_name: str) -> str:
    use_mock = os.environ.get("MOCK_LLM", "false").lower() in ("true", "1", "yes")
    if not GROQ_API_KEY or GROQ_API_KEY in ("YOUR_GROQ_API_KEY_HERE", "your_groq_api_key_here", "gsk_xxxx") or len(GROQ_API_KEY) < 20:
        use_mock = True

    if use_mock:
        print(f"[INFO] Running in Simulated Mode for {agent_name}...")
        return run_simulated_agent(agent_name, callback)

    llm = ChatGroq(
        api_key=GROQ_API_KEY,
        model=model_id,
        temperature=0.6,
        max_tokens=4096,
        callbacks=[callback],
    )
    messages = [
        SystemMessage(content=f"{system}\n\n{PLAIN_RULE}"),
        HumanMessage(content=user_prompt),
    ]
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            result = llm.invoke(messages)
            return clean_output(result.content)
        except Exception as e:
            err = str(e)
            if "rate_limit" in err.lower() or "429" in err:
                wait = RETRY_DELAY * attempt
                print(f"[{agent_name}] rate limited — waiting {wait}s (attempt {attempt})")
                time.sleep(wait)
            elif "401" in err or "invalid_api_key" in err.lower():
                print(f"[WARN] Groq API authentication failed. Falling back to Simulated Mode for {agent_name}...")
                os.environ["MOCK_LLM"] = "true"
                return run_simulated_agent(agent_name, callback)
            else:
                print(f"[{agent_name}] error: {err[:100]}, retry {attempt}/{RETRY_ATTEMPTS}")
                time.sleep(RETRY_DELAY)
    raise RuntimeError(f"{agent_name} failed after {RETRY_ATTEMPTS} attempts.")



# ════════════════════════════════════════════════════════════════════════════════
#  6 AGENTS
# ════════════════════════════════════════════════════════════════════════════════

def agent1_candidate(model, job_id, resume, role):
    cb = AgentProgressCallback(job_id, 0, "Candidate Analyser")
    return run_agent(model,
        "You are a senior career strategist and resume expert.",
        f"""Analyse this resume for the role: {role}

RESUME:
{resume}

Use this EXACT plain-text structure:

CANDIDATE PROFILE
=================
Name:
Current Role / Status:
Education:
Total Experience:
Core Tech Stack / Skills:

STRONGEST SELLING POINTS FOR {role}
========================================
1.
2.
3.
4.
5.

GAPS / WEAKNESSES TO ADDRESS
==============================
1.
2.
3.

HOW TO FRAME THIS CANDIDATE
=============================
Elevator pitch (3 sentences):
Key narrative angle:
What makes them stand out:
What to downplay:

RESUME SCORE FOR {role}: __/10
Reasoning:
""", cb, "Candidate Analyser")


def agent2_hr(model, job_id, hr_text):
    cb = AgentProgressCallback(job_id, 1, "HR Profiler")
    return run_agent(model,
        "You are a behavioral analyst specializing in HR professionals and hiring managers.",
        f"""Analyse this LinkedIn profile and build an intelligence dossier.

PROFILE TEXT:
{hr_text}

Use this EXACT plain-text structure:

HR PROFILE INTELLIGENCE
========================
Name:
Current Role:
Company:
Industry:
Seniority:
Location:

PROFESSIONAL PRIORITIES
========================
What they care about most:
Types of candidates they champion:
Topics they engage with:
Hiring philosophy (inferred):

PERSONALITY & COMMUNICATION STYLE
===================================
Personality type (inferred):
Preferred tone:
Message length they prefer:
What gets a reply:
What gets ignored:

INFLUENCE LEVERS
=================
What impresses them:
What signals a strong candidate:
Best conversation opener:
Topics that build rapport:

COMPANY CONTEXT
================
Company stage:
Likely hiring pain points:
What the company values (inferred):
""", cb, "HR Profiler")


def agent3_alignment(model, job_id, a1, a2, role):
    cb = AgentProgressCallback(job_id, 2, "Alignment Strategist")
    return run_agent(model,
        "You are a job search strategist connecting candidates with hiring managers.",
        f"""Build a positioning strategy to land a {role} interview.

CANDIDATE ANALYSIS:
{a1}

HR PROFILE:
{a2}

TARGET ROLE: {role}

Use this EXACT plain-text structure:

POSITIONING STRATEGY
=====================
ALIGNMENT SCORE: __/10
Why this candidate fits:

KEY ALIGNMENT POINTS (TOP 3)
==============================
1.
2.
3.

NARRATIVE ANGLE
================
Core story to tell:
How to connect background to HR priorities:
The ONE thing this HR will remember:

WHAT TO EMPHASIZE
==================
Skill 1 + why it matters to THIS HR:
Skill 2 + why it matters to THIS HR:
Achievement to highlight:
Personal angle that creates connection:

WHAT TO AVOID
==============
Topics to skip:
Framing that will backfire:
Common mistakes to avoid:

CONVERSATION HOOKS
===================
Opening hook (one sentence):
Question that flatters their expertise:
Shared interest / common ground:
""", cb, "Alignment Strategist")


def agent4_roadmap(model, job_id, a1, a2, a3, role):
    cb = AgentProgressCallback(job_id, 3, "Outreach Architect")
    return run_agent(model,
        "You are a relationship-building strategist designing job search outreach campaigns.",
        f"""Design a Day 1 / Week 1 / Month 1 roadmap to land a {role} interview.

CANDIDATE:
{a1}

HR PROFILE:
{a2}

ALIGNMENT:
{a3}

Use this EXACT plain-text structure:

OUTREACH ROADMAP FOR {role}
=================================

DAY 1 - MAKE FIRST CONTACT
----------------------------
LinkedIn connection request timing:
What to do:
Note to include:
Profile headline update:
Keyword to add:
Research move - what to find out:
Research move - how to use it:

WEEK 1 - BUILD VISIBILITY
---------------------------
Day 2 - Action + Goal:
Day 3 - Action + Goal:
Day 4 - Action + Goal:
Day 5 - Action + Goal:
Day 7 - First DM message angle:

WEEK 2 - ESTABLISH CREDIBILITY
--------------------------------
Move 1:
Move 2:
Move 3:
Goal by end of week 2:

MONTH 1 - CONVERT TO INTERVIEW
--------------------------------
Week 3 goal:
Week 4 goal:
Final push strategy:
Success milestone by Day 30:

FOLLOW-UP RULES
================
No reply after Day 1 connection:
No reply after first DM:
No reply after email:
Maximum follow-ups before moving on:

PARALLEL STRATEGIES
====================
Other contacts at same company:
Internal referral play:
Mutual connection strategy:
""", cb, "Outreach Architect")


def agent5_messages(model, job_id, a1, a2, a3, role):
    cb = AgentProgressCallback(job_id, 4, "Message Copywriter")
    return run_agent(model,
        "You are an expert copywriter for job search outreach. Zero desperation. Confident and human.",
        f"""Write a complete outreach message suite for {role}, tailored to THIS HR person.
No code blocks or pseudocode anywhere in your response.

CANDIDATE:
{a1}

HR PROFILE:
{a2}

ALIGNMENT:
{a3}

Use this EXACT plain-text structure:

MESSAGE & EMAIL SUITE
======================

1. LINKEDIN CONNECTION REQUEST (max 300 characters)
----------------------------------------------------
[write message here]


2. LINKEDIN DM - AFTER CONNECTING (60-80 words)
------------------------------------------------
[write message here]


3. LINKEDIN DM - FOLLOW UP (40-50 words, no reply after 5 days)
---------------------------------------------------------------
[write message here]


4. COLD EMAIL - FIRST OUTREACH
-------------------------------
Subject Line:
[write subject]

Body (150-200 words):
[write body]


5. FOLLOW-UP EMAIL (80-100 words, send 5 days after first email)
-----------------------------------------------------------------
Subject Line:
[write subject]

Body:
[write body]


6. FINAL EMAIL (50-70 words, Day 14, graceful last attempt)
------------------------------------------------------------
Subject Line:
[write subject]

Body:
[write body]


7. REFERRAL REQUEST (to a mutual connection, under 80 words)
-------------------------------------------------------------
[write message here]


8. THANK YOU MESSAGE (after reply or interview, 50-60 words)
-------------------------------------------------------------
[write message here]


TONE GUIDE
==========
Voice to use:
What makes these work for THIS HR:
What was deliberately avoided:
""", cb, "Message Copywriter")


def agent6_scorecard(model, job_id, a1, a2, a3, a4, role):
    cb = AgentProgressCallback(job_id, 5, "Success Analyst")
    return run_agent(model,
        "You are a data-driven career coach. Honest scores. Specific actions. No false hope. Never produce code or pseudocode.",
        f"""Score this job search campaign for {role} and give an action plan.
Plain English only. No code, no pseudocode, no programming syntax.

CANDIDATE:
{a1}

HR PROFILE:
{a2}

ALIGNMENT:
{a3}

ROADMAP:
{a4}

Use this EXACT plain-text structure:

SUCCESS PROBABILITY SCORECARD
===============================
CONNECTION ACCEPTANCE RATE: __%
  Why:

DM REPLY PROBABILITY: __%
  Why:

EMAIL REPLY PROBABILITY: __%
  Why:

INTERVIEW CONVERSION CHANCE: __%
  Why:

OVERALL CAMPAIGN STRENGTH: [Weak / Moderate / Strong / Elite]

TOP 3 THINGS WORKING IN CANDIDATE'S FAVOUR
============================================
1.
2.
3.

TOP 3 RISKS THAT COULD DERAIL THIS
=====================================
1.
2.
3.

WHAT WOULD INCREASE SUCCESS BY 30%
=====================================
Action 1:
Action 2:
Action 3:

DAILY CHECKLIST FOR CANDIDATE
===============================
Every morning (5 mins):
Every evening (5 mins):
Weekly review:

FINAL ADVICE
=============
Single most important action:
Biggest mistake to avoid:
Mindset note:
""", cb, "Success Analyst")





# ════════════════════════════════════════════════════════════════════════════
def run_job(job_id, user_id, c_pdf, h_pdf, role, model):
    if job_id not in jobs:
        jobs[job_id] = {
            "id": job_id, "status": "queued", "message": "Queued.",
            "progress": 0, "job_role": role, "model": model,
            "agents": get_agents_status(0, "queued", "Queued."),
            "results": {}, "report": "",
        }
    job = jobs[job_id]
    
    def update_status(status_str, progress_val, msg_str, results_dict=None, report_str=None):
        job["status"] = status_str
        job["progress"] = progress_val
        job["message"] = msg_str
        if results_dict is not None: job["results"] = results_dict
        if report_str is not None: job["report"] = report_str
        job["agents"] = get_agents_status(progress_val, status_str, msg_str)
        
        try:
            with app.app_context():
                job_db = Job.query.filter_by(id=job_id).first()
                if job_db:
                    job_db.status = status_str
                    job_db.progress = progress_val
                    job_db.current_message = msg_str
                    if results_dict is not None: job_db.results_json = json.dumps(results_dict)
                    if report_str is not None: job_db.report_content = report_str
                    
                    if status_str == 'complete':
                        job_db.analysis_number = Job.query.filter_by(user_id=user_id).count()
                    
                    db.session.commit()
        except Exception as e:
            logging.error(f"[update_status] DB commit failed for {job_id}: {e}\n{traceback.format_exc()}")
            try:
                with app.app_context():
                    db.session.rollback()
            except Exception:
                pass
            
        # Emit SocketIO update — never let emit crash the job (threading mode)
        try:
            socketio.emit('job_status', {
                'id': job_id,
                'status': status_str,
                'progress': progress_val,
                'message': msg_str,
                'agents': job["agents"],
                'results': results_dict
            }, room=job_id)
        except Exception as e:
            logging.warning(f"[socketio] emit failed for {job_id}: {e}")

    try:
        update_status("running", 0, "Extracting text from PDFs...")
        candidate_text = load_pdf(c_pdf)
        hr_text        = load_pdf(h_pdf)
        
        # Cache extracted entities for simulated/mock fallback if needed
        entities = extract_entities(candidate_text, hr_text)
        entities["target_role"] = role
        mock_entities[job_id] = entities
        
        update_status("running", 0, "Starting agentic pipeline...")

        r1 = agent1_candidate(model, job_id, candidate_text, role)
        update_status("running", 1, "Candidate analysis complete.")

        r2 = agent2_hr(model, job_id, hr_text)
        update_status("running", 2, "HR profile complete.")

        r3 = agent3_alignment(model, job_id, r1, r2, role)
        update_status("running", 3, "Alignment strategy complete.")

        r4 = agent4_roadmap(model, job_id, r1, r2, r3, role)
        update_status("running", 4, "Outreach roadmap complete.")

        r5 = agent5_messages(model, job_id, r1, r2, r3, role)
        update_status("running", 5, "Message suite complete.")

        r6 = agent6_scorecard(model, job_id, r1, r2, r3, r4, role)

        D = "=" * 70
        report = "\n".join([
            f"{D}", "  HIREEDGE INTELLIGENCE REPORT",
            f"  Role: {role}  |  Model: {model}", f"{D}",
            f"\nSECTION 1 - CANDIDATE PROFILE\n{D}\n{r1}",
            f"\nSECTION 2 - HR PROFILE\n{D}\n{r2}",
            f"\nSECTION 3 - ALIGNMENT STRATEGY\n{D}\n{r3}",
            f"\nSECTION 4 - OUTREACH ROADMAP\n{D}\n{r4}",
            f"\nSECTION 5 - MESSAGE SUITE\n{D}\n{r5}",
            f"\nSECTION 6 - SUCCESS SCORECARD\n{D}\n{r6}",
            f"\n{D}\n  END OF REPORT\n{D}",
        ])

        (REPORTS_FOLDER / f"{job_id}.txt").write_text(report, encoding="utf-8")
        job_results = {"a1":r1,"a2":r2,"a3":r3,"a4":r4,"a5":r5,"a6":r6}

        update_status("complete", 6, "Analysis complete.", results_dict=job_results, report_str=report)

    except Exception as e:
        tb = traceback.format_exc()
        logging.error(f"[run_job] {job_id} failed: {e}\n{tb}")
        job["status"] = "error"
        job["message"] = str(e)
        job["agents"] = get_agents_status(job["progress"], "error", str(e))
        
        try:
            with app.app_context():
                job_db = Job.query.filter_by(id=job_id).first()
                if job_db:
                    job_db.status = 'error'
                    job_db.current_message = str(e)[:250]
                    db.session.commit()
        except Exception as db_e:
            logging.error(f"[run_job] failed to persist error state: {db_e}")
            try:
                with app.app_context():
                    db.session.rollback()
            except Exception:
                pass
        
        # Emit error status via Socket.IO — don't crash if emit fails
        try:
            socketio.emit('job_status', {
                'id': job_id,
                'status': 'error',
                'progress': job["progress"],
                'message': str(e),
                'agents': job["agents"]
            }, room=job_id)
        except Exception as emit_e:
            logging.warning(f"[socketio] error emit failed: {emit_e}")
        
    finally:
        try:
            c_pdf.unlink(missing_ok=True)
            h_pdf.unlink(missing_ok=True)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════════════════
#  API ROUTES
# ════════════════════════════════════════════════════════════════════════════════
# ── Serve Frontend ─────────────────────────────────────────────────────────────

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

@app.route("/")
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.route("/health")
def health():
    is_mock = os.environ.get("MOCK_LLM", "false").lower() in ("true", "1", "yes")
    ok = (GROQ_API_KEY not in ("", "YOUR_GROQ_API_KEY_HERE") and len(GROQ_API_KEY) > 20) or is_mock
    # Test DB connectivity — do not leak password, just host + status
    db_ok = False
    db_error = None
    try:
        with app.app_context():
            db.session.execute(sa_text("SELECT 1"))
            db.session.commit()
            db_ok = True
    except OperationalError as oe:
        db_error = f"OperationalError: {str(oe)[:300]}"
        logging.warning(f"[health] DB OperationalError: {oe}; host={_db_host_log(DATABASE_URL)}")
        try:
            db.session.rollback()
        except Exception:
            pass
    except Exception as e:
        db_error = str(e)[:300]
        logging.warning(f"[health] DB error: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass

    payload = {
        "status":   "ok" if db_ok else "degraded",
        "groq":     ok,
        "is_mock":  is_mock,
        "version":  "3.0-waitress",
        "groq_msg": "Simulated Mode active" if is_mock else ("Groq API key configured" if ok else "Set GROQ_API_KEY env variable"),
        "db":       db_ok,
        "db_host":  _db_host_log(DATABASE_URL),
    }
    if db_error:
        payload["db_error"] = db_error
        payload["hint"] = "Check DATABASE_URL host (Supabase pooler uses aws-0-...pooler.supabase.com:6543 with sslmode=require) or set ALLOW_SQLITE_FALLBACK=true"
    # Return 503 if DB down so monitoring catches it, but still JSON for frontend parseJsonSafe
    status_code = 200 if db_ok else 503
    return jsonify(payload), status_code


@app.route("/models")
def list_models():
    return jsonify({"models": AVAILABLE_MODELS})

# ── Auth Routes ───────────────────────────────────────────────────────────────

@app.route("/api/register", methods=["POST"])
def register():
    try:
        data = request.get_json(silent=True)
        if not data or not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Email and password required'}), 400
        
        email = data['email'].strip().lower()
        password = data['password']
        
        # Validation
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return _error_response("VALIDATION_ERROR", "Invalid email format")
        if len(password) < 6:
            return _error_response("VALIDATION_ERROR", "Password must be at least 6 characters")
        if len(password.encode('utf-8')) > 72:
            return _error_response("VALIDATION_ERROR", "Password too long (max 72 bytes for bcrypt)")
        
        if User.query.filter_by(email=email).first():
            return _error_response("CONFLICT", "User already exists")
        
        try:
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        except Exception as e:
            logging.error(f"[register] bcrypt hash failed for {email}: {e}\n{traceback.format_exc()}")
            return _error_response("INTERNAL_ERROR", "Password hashing failed", detail=str(e))
        
        new_user = User(email=email, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        
        return jsonify({"message": "User created successfully!", "request_id": g.request_id}), 201
    except OperationalError as oe:
        tb = traceback.format_exc()
        logging.error(f"[register] OperationalError for {data.get('email') if 'data' in locals() and data else 'unknown'}: {oe}; host={_db_host_log(DATABASE_URL)}\n{tb[-1200:]}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return _error_response("DB_UNAVAILABLE", "Database unavailable",
                             detail=f"Could not reach database host {_db_host_log(DATABASE_URL)}. Check DATABASE_URL (use Supabase pooler host aws-0-...pooler.supabase.com:6543 with sslmode=require) or set ALLOW_SQLITE_FALLBACK=true for local dev.", status=503)
    except Exception as e:
        tb = traceback.format_exc()
        logging.error(f"[register] 500 for {data.get('email') if 'data' in locals() and data else 'unknown'}: {e}\n{tb}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return _error_response("INTERNAL_ERROR", "Registration failed", detail=str(e) if os.environ.get("FLASK_ENV") == "development" else "Registration failed"), 500

@app.route("/api/login", methods=["POST"])
def login():
    try:
        data = request.get_json(silent=True)
        if not data or not data.get('email') or not data.get('password'):
            return _error_response("VALIDATION_ERROR", "Email and password required")
        
        email = data['email'].strip().lower()
        password = data['password']
        
        user = User.query.filter_by(email=email).first()
        
        if not user:
            return _error_response("UNAUTHORIZED", "Invalid credentials")
        
        try:
            pw_ok = bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8'))
        except Exception as e:
            logging.error(f"[login] bcrypt check failed for {email}: {e}\n{traceback.format_exc()}")
            return _error_response("UNAUTHORIZED", "Invalid credentials")
        
        if not pw_ok:
            return _error_response("UNAUTHORIZED", "Invalid credentials")
            
        token = jwt.encode({
            'user_id': user.id,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }, app.config['SECRET_KEY'], algorithm="HS256")
        
        return jsonify({
            'token': token,
            'user': {'email': user.email, 'id': user.id},
            'request_id': g.request_id
        })
    except OperationalError as oe:
        tb = traceback.format_exc()
        logging.error(f"[login] OperationalError: {oe}; host={_db_host_log(DATABASE_URL)}\n{tb[-1200:]}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return _error_response("DB_UNAVAILABLE", "Database unavailable",
                             detail=f"Could not reach database host {_db_host_log(DATABASE_URL)}. Check DATABASE_URL (use Supabase pooler host aws-0-...pooler.supabase.com:6543 with sslmode=require) or set ALLOW_SQLITE_FALLBACK=true for local dev.", status=503)
    except Exception as e:
        tb = traceback.format_exc()
        logging.error(f"[login] 500: {e}\n{tb}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return _error_response("INTERNAL_ERROR", "Login failed", detail=str(e)), 500

@app.route("/api/me", methods=["GET"])
@token_required
def get_me(current_user):
    return jsonify({
        'email': current_user.email,
        'id': current_user.id
    })

@app.route("/api/my-reports", methods=["GET"])
@token_required
def get_my_reports(current_user):
    reports = Job.query.filter_by(user_id=current_user.id).all()
    return jsonify([{
        'id': r.id,
        'job_role': r.job_role,
        'status': r.status,
        'created_at': r.created_at.isoformat(),
        'request_id': g.request_id
    } for r in reports])

@app.route("/analyse", methods=["POST"])
@token_required
def analyse(current_user):
    if "candidate_pdf" not in request.files or "hr_pdf" not in request.files:
        return _error_response("VALIDATION_ERROR", "Both candidate_pdf and hr_pdf required.")

    # ── PDF Validation (Phase 4) ─────────────────────────────────────────────
    try:
        _validate_pdf_file(request.files["candidate_pdf"], "candidate_pdf")
        _validate_pdf_file(request.files["hr_pdf"], "hr_pdf")
    except ValueError as e:
        return _error_response("VALIDATION_ERROR", str(e))

    role = request.form.get("job_role", "").strip()
    if not role:
        return _error_response("VALIDATION_ERROR", "job_role required.")
    model  = request.form.get("model", DEFAULT_MODEL).strip()
    jid    = str(uuid.uuid4())
    c_path = UPLOAD_FOLDER / f"{jid}_candidate.pdf"
    h_path = UPLOAD_FOLDER / f"{jid}_hr.pdf"
    request.files["candidate_pdf"].save(c_path)
    request.files["hr_pdf"].save(h_path)
    
    # Save the job record immediately to the database (in queued state)
    try:
        new_job = Job(
            id=jid,
            user_id=current_user.id,
            job_role=role,
            model=model,
            status='queued',
            progress=0,
            current_message='Queued.'
        )
        db.session.add(new_job)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to initialize job in database: {str(e)}"}), 500

    # Populate in-memory dict for SocketIO room support
    jobs[jid] = {
        "id": jid, "status": "queued", "message": "Queued.",
        "progress": 0, "job_role": role, "model": model,
        "agents": get_agents_status(0, "queued", "Queued."),
        "results": {}, "report": "",
    }
    
    threading.Thread(
        target=run_job, args=(jid, current_user.id, c_path, h_path, role, model), daemon=True
    ).start()
    return jsonify({"job_id": jid, "status": "queued"})


@app.route("/status/<jid>")
@token_required
def job_status(current_user, jid):
    # Check if job belongs to user
    job_db = Job.query.filter_by(id=jid, user_id=current_user.id).first()
    
    if not job_db:
        return _error_response("NOT_FOUND", "Not found or access denied.", status=404)
        
    # Read status from database as source of truth
    resp = {
        "id": job_db.id,
        "status": job_db.status,
        "message": job_db.current_message,
        "progress": job_db.progress,
        "job_role": job_db.job_role,
        "model": job_db.model,
        "agents": get_agents_status(job_db.progress, job_db.status, job_db.current_message),
    }
    
    if job_db.status == 'complete' and job_db.results_json:
        resp["results"] = json.loads(job_db.results_json)
        
    return jsonify({**resp, "request_id": g.request_id})

@app.route("/report/<jid>")
@token_required
def download_report(current_user, jid):
    job_db = Job.query.filter_by(id=jid, user_id=current_user.id).first()
    if not job_db or job_db.status != "complete": 
        return _error_response("NOT_FOUND", "Not found or not ready.", status=404)
    
    return Response(job_db.report_content, mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename=hireedge_{jid[:8]}.txt",
                 "X-Request-ID": g.request_id})
# ── JSON error handlers (prevent <!doctype HTML on API 404/405/500) ─────────────
_API_PREFIXES = ("/api/", "/health", "/models", "/analyse", "/status/", "/report/")


def _is_api_path(path: str) -> bool:
    return path.startswith(_API_PREFIXES)


def _error_response(error_code: str, message: str, detail: str = None, status: int = None) -> tuple:
    """Standardized JSON error response including request_id.

    Schema (all API errors):
    {
        "error":    error_code,     e.g. "VALIDATION_ERROR", "UNAUTHORIZED"
        "message":  message,       e.g. "Email format invalid"
        "detail":   detail,        e.g. "regex mismatch at position 5"  (optional)
        "request_id": request_id   from flask.g
    }
    Status defaults to ERROR_MAP[error_code] if not provided.
    """
    rid = getattr(g, "request_id", None)
    payload = {"error": error_code, "message": message, "request_id": rid}
    if detail is not None:
        payload["detail"] = detail
    if status is None:
        # Default mapping
        defaults = {
            "VALIDATION_ERROR": 400,
            "UNAUTHORIZED": 401,
            "FORBIDDEN": 403,
            "NOT_FOUND": 404,
            "CONFLICT": 409,
            "RATE_LIMITED": 429,
            "DB_UNAVAILABLE": 503,
            "INTERNAL_ERROR": 500,
        }
        status = defaults.get(error_code, 500)
    payload["status"] = status
    return jsonify(payload), status


@app.errorhandler(404)
def handle_404(e):
    if _is_api_path(request.path):
        return _error_response("NOT_FOUND", "Not found", detail=request.path, status=404)
    accepts_html = "text/html" in (request.headers.get("Accept") or "")
    if accepts_html and not _is_api_path(request.path):
        try:
            return send_from_directory(FRONTEND_DIR, "index.html")
        except Exception:
            pass
    return _error_response("NOT_FOUND", "Not found", status=404)


@app.errorhandler(405)
def handle_405(e):
    if _is_api_path(request.path):
        return _error_response("CONFLICT", "Method not allowed", detail=request.path, status=405)
    return _error_response("CONFLICT", "Method not allowed", status=405)


@app.errorhandler(500)
def handle_500(e):
    tb = traceback.format_exc()
    logging.error(f"[500] {request.path}: {e}\n{tb}")
    is_debug = os.environ.get("FLASK_ENV") == "development" or os.environ.get("MOCK_LLM", "").lower() in ("true", "1")
    if is_debug or _is_api_path(request.path):
        detail = str(e) if str(e) and str(e) != "500 Internal Server Error" else (tb.splitlines()[-1] if tb else "Internal server error")
        return _error_response("INTERNAL_ERROR", "Internal server error", detail=detail, status=500)
    return _error_response("INTERNAL_ERROR", "Internal server error", status=500)


# ════════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT  — SocketIO (supports WebSocket + fallback polling)
# ════════════════════════════════════════════════════════════════════════════════
# For production (Render/Heroku), use: gunicorn --worker-class eventlet -w 1 app:app
# For local development, socketio.run() with Flask dev server

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("\n" + "=" * 58)
    print(f"  HireEdge  —  http://0.0.0.0:{port}")
    print("  Server  :  Flask-SocketIO (WebSocket + polling fallback)")
    print(f"  Health  :  http://0.0.0.0:{port}/health")
    print("=" * 58 + "\n")
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
