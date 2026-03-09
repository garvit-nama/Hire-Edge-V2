#!/usr/bin/env python3
"""
HireEdge Production Backend
Stack: Flask + Gunicorn + LangChain + Groq API + pdfplumber

INSTALL:  pip install -r requirements.txt
SET KEY:  set GROQ_API_KEY=   (Windows CMD)
          export GROQ_API_KEY=gsk_xxxx (Mac/Linux)
DEV:      python app.py
PROD:     gunicorn -c gunicorn.conf.py app:app
"""

import os, re, time, json, uuid, threading
from pathlib import Path

from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import pdfplumber
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

# ════════════════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════════════════
app = Flask(__name__)
CORS(app, origins="*")

UPLOAD_FOLDER  = Path("uploads");  UPLOAD_FOLDER.mkdir(exist_ok=True)
REPORTS_FOLDER = Path("reports");  REPORTS_FOLDER.mkdir(exist_ok=True)

GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "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")
DEFAULT_MODEL  = "llama-3.3-70b-versatile"
RETRY_ATTEMPTS = 3
RETRY_DELAY    = 8

AVAILABLE_MODELS = [
    {"id": "llama-3.3-70b-versatile", "label": "LLaMA 3.3 70B",  "tag": "Best"},
    {"id": "llama-3.1-8b-instant",    "label": "LLaMA 3.1 8B",   "tag": "Fast"},
    {"id": "gemma2-9b-it",            "label": "Gemma 2 9B",      "tag": "Light"},
    {"id": "mixtral-8x7b-32768",      "label": "Mixtral 8x7B",    "tag": "Long ctx"},
    {"id": "llama3-70b-8192",         "label": "LLaMA 3 70B",     "tag": "Stable"},
]

jobs = {}

# ════════════════════════════════════════════════════════════════════════
#  PDF EXTRACTION
# ════════════════════════════════════════════════════════════════════════
def extract_pdf(path):
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    pages = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            t = page.extract_text()
            if t and t.strip():
                pages.append(f"--- Page {i+1} ---\n{t.strip()}")
    if not pages:
        raise ValueError("No readable text found. The PDF may be image-based/scanned.")
    return "\n\n".join(pages)

# ════════════════════════════════════════════════════════════════════════
#  MARKDOWN STRIPPER
# ════════════════════════════════════════════════════════════════════════
def clean_output(text):
    """Remove all markdown so output is clean plain text."""
    text = re.sub(r"```[\w]*\n?[\s\S]*?```", "", text)       # fenced code blocks
    text = re.sub(r"`[^`\n]+`", lambda m: m.group(0)[1:-1], text)  # inline code
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)             # bold
    text = re.sub(r"\*(.+?)\*",     r"\1", text)             # italic
    text = re.sub(r"__(.+?)__",     r"\1", text)             # bold alt
    text = re.sub(r"_(.+?)_",       r"\1", text)             # italic alt
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # headers
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)     # links
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)  # trailing spaces
    text = re.sub(r"\n{3,}", "\n\n", text)                    # excess newlines
    return text.strip()

# ════════════════════════════════════════════════════════════════════════
#  LANGCHAIN + GROQ RUNNER
# ════════════════════════════════════════════════════════════════════════
PLAIN_RULE = """CRITICAL FORMAT RULES — follow exactly:
- Output ONLY plain text. Zero markdown whatsoever.
- No asterisks (*), no bold (**), no headers (#), no backticks, no code blocks.
- UPPERCASE WORDS for section headers. Dashes (-) for bullets. Numbers (1. 2.) for lists.
- Start directly with content. No preamble or closing remarks."""

def run_agent(model_id, system, prompt, name):
    llm = ChatGroq(
        api_key=GROQ_API_KEY, model_name=model_id,
        temperature=0.6, max_tokens=4096
    )
    msgs = [
        SystemMessage(content=f"{system}\n\n{PLAIN_RULE}"),
        HumanMessage(content=prompt)
    ]
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return clean_output(llm.invoke(msgs).content)
        except Exception as e:
            err = str(e)
            if "rate_limit" in err.lower() or "429" in err:
                wait = RETRY_DELAY * attempt
                print(f"[{name}] rate limited — waiting {wait}s")
                time.sleep(wait)
            elif "401" in err or "invalid_api_key" in err.lower():
                raise RuntimeError("Invalid Groq API key. Set GROQ_API_KEY env variable.")
            else:
                print(f"[{name}] error: {err[:80]}, retry {attempt}")
                time.sleep(RETRY_DELAY)
    raise RuntimeError(f"{name} failed after {RETRY_ATTEMPTS} attempts.")

# ════════════════════════════════════════════════════════════════════════
#  6 AGENTS
# ════════════════════════════════════════════════════════════════════════

def a1_candidate(model, resume, role):
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
""", "Agent 1 Candidate")

def a2_hr(model, hr_text):
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
""", "Agent 2 HR")

def a3_alignment(model, a1, a2, role):
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
""", "Agent 3 Alignment")

def a4_roadmap(model, a1, a2, a3, role):
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
""", "Agent 4 Roadmap")

def a5_messages(model, a1, a2, a3, role):
    return run_agent(model,
        "You are an expert copywriter for job search outreach. Zero desperation. Confident and human.",
        f"""Write a complete outreach message suite for {role}, tailored to THIS HR person.

CANDIDATE:
{a1}

HR PROFILE:
{a2}

ALIGNMENT:
{a3}

Use this EXACT plain-text structure (absolutely no code blocks or pseudocode):

MESSAGE & EMAIL SUITE
======================

1. LINKEDIN CONNECTION REQUEST (max 300 characters)
----------------------------------------------------
[write message here — no placeholder text]


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
""", "Agent 5 Messages")

def a6_scorecard(model, a1, a2, a3, a4, role):
    return run_agent(model,
        "You are a data-driven career coach. Honest scores. Specific actions. No false hope. Never produce code or pseudocode.",
        f"""Score this job search campaign for {role} and give an action plan.

CANDIDATE:
{a1}

HR PROFILE:
{a2}

ALIGNMENT:
{a3}

ROADMAP:
{a4}

Use this EXACT plain-text structure (write plain English paragraphs — absolutely no code, no pseudocode, no programming syntax):

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
""", "Agent 6 Scorecard")

# ════════════════════════════════════════════════════════════════════════
#  AGENT METADATA
# ════════════════════════════════════════════════════════════════════════
AGENT_META = [
    {"id":"a1","name":"Candidate Analyser",  "label":"Parsing resume & extracting selling points"},
    {"id":"a2","name":"HR Profiler",         "label":"Building hiring manager intelligence model"},
    {"id":"a3","name":"Alignment Strategist","label":"Matching candidate strengths to HR priorities"},
    {"id":"a4","name":"Outreach Architect",  "label":"Designing Day / Week / Month roadmap"},
    {"id":"a5","name":"Message Copywriter",  "label":"Crafting personalized message suite"},
    {"id":"a6","name":"Success Analyst",     "label":"Scoring campaign & building action plan"},
]

# ════════════════════════════════════════════════════════════════════════
#  BACKGROUND JOB RUNNER
# ════════════════════════════════════════════════════════════════════════
def run_job(job_id, c_pdf, h_pdf, role, model):
    job = jobs[job_id]
    def ag(i, status, result=None, error=None):
        job["agents"][i]["status"] = status
        if result: job["agents"][i]["result"] = result
        if error:  job["agents"][i]["error"]  = error
        job["progress"] = sum(1 for a in job["agents"] if a["status"] == "done")
    try:
        job["status"]  = "extracting"
        job["message"] = "Extracting text from PDFs..."
        ct = extract_pdf(c_pdf)
        ht = extract_pdf(h_pdf)
        job["status"] = "running"
        ag(0,"running"); r1 = a1_candidate(model,ct,role); ag(0,"done",result=r1)
        ag(1,"running"); r2 = a2_hr(model,ht);            ag(1,"done",result=r2)
        ag(2,"running"); r3 = a3_alignment(model,r1,r2,role); ag(2,"done",result=r3)
        ag(3,"running"); r4 = a4_roadmap(model,r1,r2,r3,role); ag(3,"done",result=r4)
        ag(4,"running"); r5 = a5_messages(model,r1,r2,r3,role); ag(4,"done",result=r5)
        ag(5,"running"); r6 = a6_scorecard(model,r1,r2,r3,r4,role); ag(5,"done",result=r6)
        D = "="*70
        report = "\n".join([f"{D}","  HIREEDGE INTELLIGENCE REPORT",
            f"  Role: {role}  |  Model: {model}",f"{D}",
            f"\nSECTION 1 — CANDIDATE PROFILE\n{D}\n{r1}",
            f"\nSECTION 2 — HR PROFILE\n{D}\n{r2}",
            f"\nSECTION 3 — ALIGNMENT STRATEGY\n{D}\n{r3}",
            f"\nSECTION 4 — OUTREACH ROADMAP\n{D}\n{r4}",
            f"\nSECTION 5 — MESSAGE SUITE\n{D}\n{r5}",
            f"\nSECTION 6 — SUCCESS SCORECARD\n{D}\n{r6}",
            f"\n{D}\n  END OF REPORT\n{D}"])
        (REPORTS_FOLDER / f"{job_id}.txt").write_text(report, encoding="utf-8")
        job["results"] = {"a1":r1,"a2":r2,"a3":r3,"a4":r4,"a5":r5,"a6":r6}
        job["report"]  = report
        job["status"]  = "complete"
        job["message"] = "Analysis complete."
    except Exception as e:
        job["status"]  = "error"
        job["message"] = str(e)
        for a in job["agents"]:
            if a["status"] == "running":
                a["status"] = "error"; a["error"] = str(e)
    finally:
        try: c_pdf.unlink(missing_ok=True); h_pdf.unlink(missing_ok=True)
        except: pass

# ════════════════════════════════════════════════════════════════════════
#  API ROUTES
# ════════════════════════════════════════════════════════════════════════
@app.route("/health")
def health():
    ok = GROQ_API_KEY not in ("","YOUR_GROQ_API_KEY_HERE") and len(GROQ_API_KEY) > 20
    return jsonify({"status":"ok","groq":ok,"version":"2.0",
        "groq_msg":"Groq API key configured" if ok else "Set GROQ_API_KEY env variable"})

@app.route("/models")
def list_models():
    return jsonify({"models": AVAILABLE_MODELS})

@app.route("/analyse", methods=["POST"])
def analyse():
    if "candidate_pdf" not in request.files or "hr_pdf" not in request.files:
        return jsonify({"error":"Both candidate_pdf and hr_pdf required."}), 400
    role = request.form.get("job_role","").strip()
    if not role: return jsonify({"error":"job_role required."}), 400
    model = request.form.get("model", DEFAULT_MODEL).strip()
    jid   = str(uuid.uuid4())
    cp = UPLOAD_FOLDER / f"{jid}_candidate.pdf"
    hp = UPLOAD_FOLDER / f"{jid}_hr.pdf"
    request.files["candidate_pdf"].save(cp)
    request.files["hr_pdf"].save(hp)
    jobs[jid] = {"id":jid,"status":"queued","message":"Queued.","progress":0,
        "job_role":role,"model":model,
        "agents":[{**m,"status":"queued","result":None,"error":None} for m in AGENT_META],
        "results":{},"report":""}
    threading.Thread(target=run_job,args=(jid,cp,hp,role,model),daemon=True).start()
    return jsonify({"job_id":jid,"status":"queued"})

@app.route("/status/<jid>")
def job_status(jid):
    job = jobs.get(jid)
    if not job: return jsonify({"error":"Not found."}), 404
    resp = {k:job[k] for k in ("id","status","message","progress","job_role","model")}
    resp["agents"] = [{"id":a["id"],"name":a["name"],"label":a["label"],
        "status":a["status"],"error":a.get("error")} for a in job["agents"]]
    if job["status"] == "complete": resp["results"] = job["results"]
    return jsonify(resp)

@app.route("/report/<jid>")
def download_report(jid):
    job = jobs.get(jid)
    if not job: return jsonify({"error":"Not found."}), 404
    if job["status"] != "complete": return jsonify({"error":"Not ready."}), 202
    return Response(job["report"], mimetype="text/plain",
        headers={"Content-Disposition":f"attachment; filename=hireedge_{jid[:8]}.txt"})

@app.route("/stream/<jid>")
def stream(jid):
    def gen():
        last = (-1,"")
        while True:
            job = jobs.get(jid)
            if not job:
                yield f"data: {json.dumps({'error':'not found'})}\n\n"; break
            cur = (job["progress"], job["status"])
            if cur != last:
                p = {"status":job["status"],"message":job["message"],"progress":job["progress"],
                    "agents":[{"id":a["id"],"name":a["name"],"label":a["label"],
                        "status":a["status"],"error":a.get("error")} for a in job["agents"]]}
                if job["status"] == "complete": p["results"] = job["results"]
                yield f"data: {json.dumps(p)}\n\n"
                last = cur
            if job["status"] in ("complete","error"): break
            time.sleep(0.8)
    return Response(stream_with_context(gen()), mimetype="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

# ════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\n" + "="*58)
    print("  HireEdge Backend  —  http://localhost:5000")
    print("  PRODUCTION: gunicorn -c gunicorn.conf.py app:app")
    print("="*58 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
