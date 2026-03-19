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
from dotenv import load_dotenv
load_dotenv()

import os, re, time, json, uuid, threading
from pathlib import Path

# ── Flask ──────────────────────────────────────────────────────────────────────
from flask import Flask, request, jsonify, Response
from flask_cors import CORS

# ── LangChain 1.2.x compatible imports ────────────────────────────────────────
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.callbacks.base import BaseCallbackHandler

# ── PDF extraction ─────────────────────────────────────────────────────────────
from pypdf import PdfReader

# ── Waitress ───────────────────────────────────────────────────────────────────
from waitress import serve

# ════════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════════════════════════
app = Flask(__name__)
CORS(app, origins="*")

UPLOAD_FOLDER  = Path("uploads");  UPLOAD_FOLDER.mkdir(exist_ok=True)
REPORTS_FOLDER = Path("reports");  REPORTS_FOLDER.mkdir(exist_ok=True)

GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")

DEFAULT_MODEL  = "llama-3.3-70b-versatile"
RETRY_DELAY    = 8
RETRY_ATTEMPTS = 3

AVAILABLE_MODELS = [
    {"id": "llama-3.3-70b-versatile", "label": "LLaMA 3.3 70B",  "tag": "Best"},
    {"id": "llama-3.1-8b-instant",    "label": "LLaMA 3.1 8B",   "tag": "Fast"},
    {"id": "gemma2-9b-it",            "label": "Gemma 2 9B",      "tag": "Light"},
    {"id": "mixtral-8x7b-32768",      "label": "Mixtral 8x7B",    "tag": "Long ctx"},
    {"id": "llama3-70b-8192",         "label": "LLaMA 3 70B",     "tag": "Stable"},
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

class AgentProgressCallback(BaseCallbackHandler):
    def __init__(self, job_id: str, agent_index: int, agent_name: str):
        self.job_id      = job_id
        self.agent_index = agent_index
        self.agent_name  = agent_name

    def _job(self):
        return jobs.get(self.job_id)

    def on_llm_start(self, serialized, prompts, **kwargs):
        job = self._job()
        if job:
            job["agents"][self.agent_index]["status"] = "running"
            job["agents"][self.agent_index]["label"]  = f"{self.agent_name}: querying LLM..."
            job["message"] = f"Running {self.agent_name}..."

    def on_llm_end(self, response, **kwargs):
        job = self._job()
        if job:
            job["agents"][self.agent_index]["label"] = f"{self.agent_name}: processing output..."

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
            job["progress"] = sum(
                1 for a in job["agents"] if a["status"] == "done"
            )


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
                raise RuntimeError("Invalid Groq API key. Set GROQ_API_KEY env variable.")
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


# ════════════════════════════════════════════════════════════════════════════════
#  AGENT METADATA
# ════════════════════════════════════════════════════════════════════════════════

AGENT_META = [
    {"id": "a1", "name": "Candidate Analyser",   "label": "Parsing resume & extracting selling points"},
    {"id": "a2", "name": "HR Profiler",           "label": "Building hiring manager intelligence model"},
    {"id": "a3", "name": "Alignment Strategist",  "label": "Matching candidate strengths to HR priorities"},
    {"id": "a4", "name": "Outreach Architect",    "label": "Designing Day / Week / Month roadmap"},
    {"id": "a5", "name": "Message Copywriter",    "label": "Crafting personalized message suite"},
    {"id": "a6", "name": "Success Analyst",       "label": "Scoring campaign & building action plan"},
]


# ════════════════════════════════════════════════════════════════════════════════
#  BACKGROUND JOB RUNNER
# ════════════════════════════════════════════════════════════════════════════════

def run_job(job_id, c_pdf, h_pdf, role, model):
    job = jobs[job_id]
    try:
        job["status"]  = "extracting"
        job["message"] = "Extracting text from PDFs..."
        candidate_text = load_pdf(c_pdf)
        hr_text        = load_pdf(h_pdf)
        job["status"]  = "running"
        job["message"] = "Starting agentic pipeline..."

        r1 = agent1_candidate(model, job_id, candidate_text, role)
        r2 = agent2_hr(model, job_id, hr_text)
        r3 = agent3_alignment(model, job_id, r1, r2, role)
        r4 = agent4_roadmap(model, job_id, r1, r2, r3, role)
        r5 = agent5_messages(model, job_id, r1, r2, r3, role)
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
        job["results"] = {"a1":r1,"a2":r2,"a3":r3,"a4":r4,"a5":r5,"a6":r6}
        job["report"]  = report
        job["status"]  = "complete"
        job["message"] = "Analysis complete."

    except Exception as e:
        job["status"]  = "error"
        job["message"] = str(e)
        for ag in job["agents"]:
            if ag["status"] == "running":
                ag["status"] = "error"
                ag["error"]  = str(e)
    finally:
        try:
            c_pdf.unlink(missing_ok=True)
            h_pdf.unlink(missing_ok=True)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════════════════
#  API ROUTES
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/health")
def health():
    ok = GROQ_API_KEY not in ("", "YOUR_GROQ_API_KEY_HERE") and len(GROQ_API_KEY) > 20
    return jsonify({
        "status":   "ok",
        "groq":     ok,
        "version":  "3.0-waitress",
        "groq_msg": "Groq API key configured" if ok else "Set GROQ_API_KEY env variable",
    })

@app.route("/models")
def list_models():
    return jsonify({"models": AVAILABLE_MODELS})

@app.route("/analyse", methods=["POST"])
def analyse():
    if "candidate_pdf" not in request.files or "hr_pdf" not in request.files:
        return jsonify({"error": "Both candidate_pdf and hr_pdf required."}), 400
    role = request.form.get("job_role", "").strip()
    if not role:
        return jsonify({"error": "job_role required."}), 400
    model  = request.form.get("model", DEFAULT_MODEL).strip()
    jid    = str(uuid.uuid4())
    c_path = UPLOAD_FOLDER / f"{jid}_candidate.pdf"
    h_path = UPLOAD_FOLDER / f"{jid}_hr.pdf"
    request.files["candidate_pdf"].save(c_path)
    request.files["hr_pdf"].save(h_path)
    jobs[jid] = {
        "id": jid, "status": "queued", "message": "Queued.",
        "progress": 0, "job_role": role, "model": model,
        "agents": [{**m, "status":"queued","result":None,"error":None} for m in AGENT_META],
        "results": {}, "report": "",
    }
    threading.Thread(
        target=run_job, args=(jid, c_path, h_path, role, model), daemon=True
    ).start()
    return jsonify({"job_id": jid, "status": "queued"})

@app.route("/status/<jid>")
def job_status(jid):
    job = jobs.get(jid)
    if not job: return jsonify({"error": "Not found."}), 404
    resp = {k: job[k] for k in ("id","status","message","progress","job_role","model")}
    resp["agents"] = [
        {"id":a["id"],"name":a["name"],"label":a["label"],
         "status":a["status"],"error":a.get("error")}
        for a in job["agents"]
    ]
    if job["status"] == "complete":
        resp["results"] = job["results"]
    return jsonify(resp)

@app.route("/report/<jid>")
def download_report(jid):
    job = jobs.get(jid)
    if not job: return jsonify({"error": "Not found."}), 404
    if job["status"] != "complete": return jsonify({"error": "Not ready."}), 202
    return Response(job["report"], mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename=hireedge_{jid[:8]}.txt"})


# ════════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT  — Waitress (Windows-compatible, production-grade)
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 58)
    print("  HireEdge  —  http://localhost:5000")
    print("  Server  :  Waitress (Windows-compatible)")
    print("  Health  :  http://localhost:5000/health")
    print("=" * 58 + "\n")
    serve(app, host="0.0.0.0", port=5000, threads=4)
