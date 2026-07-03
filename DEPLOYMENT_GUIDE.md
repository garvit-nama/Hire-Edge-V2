# Deployment Guide: HireEdge on Render + Supabase

This guide covers deploying HireEdge to production using Render (hosting) and Supabase (PostgreSQL database).

---

## Prerequisites

- Render account (render.com)
- Supabase account (supabase.com)
- GitHub repository with HireEdge code
- GROQ API key (gsk_...)

---

## Step 1: Set Up Supabase PostgreSQL

### 1.1 Create Supabase Project

1. Go to supabase.com and log in
2. Click "New Project"
3. Enter project name: `hireedge`
4. Set region (closest to your users)
5. Create strong database password
6. Wait for provisioning (~2 minutes)

### 1.2 Get Connection String

1. Go to "Settings" → "Database"
2. Copy "Connection string" (URI)
3. Format: `postgresql://postgres:PASSWORD@HOST:5432/postgres`

**Keep this secret!** Treat it like a password.

---

## Step 2: Deploy to Render

### 2.1 Connect GitHub Repository

1. Go to render.com
2. Click "New +" → "Web Service"
3. Select "Deploy an existing repository"
4. Connect your GitHub account
5. Select HireEdge repository
6. Click "Connect"

### 2.2 Configure Web Service

**Name:** `hireedge-backend`

**Environment:** Python 3

**Build Command:**
```bash
pip install -r backend/requirements.txt
```

**Start Command:**
```bash
python backend/app.py
```

Or (with gunicorn + eventlet for production WebSocket):
```bash
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:$PORT backend:app
```

**Note:** For now, use `python backend/app.py` (Flask dev server with SocketIO)

### 2.3 Add Environment Variables

Click "Advanced" → "Environment Variables" and add:

| Key | Value |
|-----|-------|
| `DATABASE_URL` | `postgresql://postgres:PASSWORD@HOST:5432/postgres` |
| `GROQ_API_KEY` | `gsk_...` (your Groq API key) |
| `SECRET_KEY` | Generate random: `openssl rand -hex 32` |
| `PYTHON_VERSION` | `3.11.0` |
| `FLASK_ENV` | `production` |

### 2.4 Deploy

1. Click "Create Web Service"
2. Render will auto-deploy from main branch
3. Wait for deployment (~5-10 minutes)
4. Once deployed, note the URL: `https://hireedge-backend.render.com`

### 2.5 Verify Deployment

Test your backend:

```bash
curl https://hireedge-backend.render.com/health
# Response: {"groq": true, "db": true}
```

---

## Step 3: Deploy Frontend

The frontend is served by the backend Flask server (no separate deployment needed).

### 3.1 Update Frontend Backend URL

Edit `frontend/js/api.js` or set via environment:

```javascript
function getBase() {
  // Production
  return 'https://hireedge-backend.render.com';
}
```

Or (if using hidden input):

```html
<!-- frontend/index.html -->
<input type="hidden" id="backendUrl" value="https://hireedge-backend.render.com" />
```

### 3.2 Commit & Push

```bash
git add .
git commit -m "Deploy: Update backend URL for production"
git push origin main
```

Render will auto-redeploy.

---

## Step 4: Database Migration

### 4.1 First Startup

On first startup, Flask-SQLAlchemy auto-creates tables:

```bash
# Happens automatically on first request to backend
curl https://hireedge-backend.render.com/health
# Tables created: user, job
```

### 4.2 Verify Tables

Check in Supabase dashboard:

1. Go to supabase.com → Project → SQL Editor
2. Run:
   ```sql
   \dt  -- List all tables
   ```
3. Should see: `public.user`, `public.job`, `public.alembic_version`

---

## Step 5: Test End-to-End

### 5.1 User Registration

```bash
curl -X POST https://hireedge-backend.render.com/api/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "testuser@example.com",
    "password": "securepass123"
  }'

# Response: {"user_id": "...", "message": "Registered successfully"}
```

### 5.2 User Login

```bash
curl -X POST https://hireedge-backend.render.com/api/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "testuser@example.com",
    "password": "securepass123"
  }'

# Response: {"token": "eyJhbGc...", "user": {...}}
```

### 5.3 Start Analysis

```bash
TOKEN="eyJhbGc..."
curl -X POST https://hireedge-backend.render.com/analyse \
  -H "Authorization: Bearer $TOKEN" \
  -F "resume=@resume.pdf" \
  -F "job_role=Software Engineer"

# Response: {"job_id": "...", "status": "queued"}
```

### 5.4 Check Status (WebSocket)

Open browser console on frontend and watch for real-time updates:

```javascript
// Should see in console:
// ✅ WebSocket connected
// 📍 WebSocket job_status: {progress: 1, ...}
// 📍 WebSocket job_status: {progress: 2, ...}
// ... etc
```

---

## Troubleshooting

### "Module not found" errors

**Cause:** Missing dependencies

**Fix:**
```bash
# Ensure all requirements are in backend/requirements.txt
pip install -r backend/requirements.txt
# Commit & push; Render will redeploy
```

### WebSocket connection fails

**Cause:** SocketIO not responding

**Fix:**
1. Check Render logs: Dashboard → Web Service → Logs
2. Look for errors like `Error: no appropriate version of the found_precompiled_wheels`
3. Try gunicorn with eventlet:
   ```bash
   pip install gunicorn eventlet
   # Update Start Command in Render
   ```

### Database connection timeout

**Cause:** DATABASE_URL incorrect or network blocked

**Fix:**
1. Verify DATABASE_URL in Render environment variables
2. Check Supabase IP whitelist: Settings → Database → Connection Pooling
3. Add `0.0.0.0/0` to allow all IPs (for dev)

### Freemium truncation not working

**Cause:** Tier not set correctly

**Fix:**
1. Check user in Supabase: `SELECT email, subscription_tier FROM "user"`
2. Verify free user's analysis count: `SELECT COUNT(*) FROM job WHERE user_id = ?`
3. Ensure `is_truncated` is saved: `SELECT is_truncated FROM job WHERE id = ?`

### Real-time updates not appearing

**Cause:** WebSocket fallback to polling

**Fix:**
1. Check browser console for connection errors
2. Verify WebSocket URL matches backend
3. Check Render logs for SocketIO errors
4. Polling fallback will work but with 2s delay

---

## Production Checklist

- [x] Supabase PostgreSQL created and verified
- [x] Render web service configured with env vars
- [x] Backend auto-deploys on GitHub push
- [x] Database tables auto-created on first startup
- [x] Frontend served by Flask (no separate deploy)
- [x] Health endpoint responding: `/health`
- [x] Auth endpoints working: `/api/register`, `/api/login`
- [x] Analysis pipeline running: `/analyse`
- [x] WebSocket emitting real-time updates: `/status/<jid>`
- [x] Freemium truncation applied for 2nd+ free analyses
- [x] Reports persisted to database
- [x] Report download working: `/report/<jid>`

---

## Monitoring & Maintenance

### Daily Checks

```bash
# Health check
curl https://hireedge-backend.render.com/health

# Check for errors in Render logs
# Dashboard → Logs tab
```

### Weekly Tasks

1. Review Render metrics: Memory, CPU, requests
2. Check Supabase database size
3. Monitor Groq API usage

### Cost Optimization

- **Render Free Tier:** 750 free hours/month (stops after inactivity)
- **Supabase Free Tier:** 500 MB database, 2 GB bandwidth
- **Groq Free Tier:** Limited API calls

---

## Scaling to Production

### When to upgrade:

- **Render:** Scale up to Starter/Pro if CPU >80%
- **Supabase:** Upgrade to Pro for higher limits
- **WebSocket:** Use gunicorn + eventlet for multiple workers

### High-traffic setup:

```yaml
# Render (Production)
Environment: Python 3.11
Start Command: gunicorn --worker-class eventlet -w 4 --bind 0.0.0.0:$PORT backend:app
Memory: 1 GB
CPU: 2 cores

# Supabase
Plan: Pro ($25/month)
Max connections: 200
Database size: 8 GB
```

---

## Rollback

If deployment has issues:

1. Render dashboard → Web Service → "Deployment history"
2. Click previous deployment to rollback
3. Or revert GitHub commit and push:
   ```bash
   git revert HEAD
   git push origin main
   # Render will auto-redeploy with previous code
   ```

---

## Support

- Render docs: https://render.com/docs
- Supabase docs: https://supabase.com/docs
- HireEdge issues: Check GitHub Issues

---

**Next:** Set up monitoring, configure SSL (Render auto-handles), and enable backup retention in Supabase.
