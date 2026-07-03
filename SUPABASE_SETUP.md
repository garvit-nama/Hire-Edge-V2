# Supabase Setup for HireEdge — Step-by-Step Guide

## 🚀 Quick Setup (5 minutes)

### Step 1: Create Supabase Account & Project

1. Go to **https://supabase.com**
2. Click **"Sign Up"** → Create account with email
3. Click **"New Project"** after verification
4. Fill in details:
   - **Project Name:** `hireedge` (or your choice)
   - **Database Password:** Create strong password (save it!)
   - **Region:** Choose closest to users (e.g., `us-east-1`)
5. Click **"Create new project"** and wait ~2 minutes

### Step 2: Get Database Connection String

1. Once project loads, click **Settings** (bottom left)
2. Click **Database** → **Connection String**
3. Select **Connection string** type (not pooling)
4. Copy the **full PostgreSQL URI** → looks like:
   ```
   postgresql://postgres:PASSWORD@aws-0-us-east-1.pooler.supabase.com:5432/postgres
   ```
5. **Replace `[YOUR-PASSWORD]` with your database password** (from Step 1)

### Step 3: Set Environment Variable Locally

Create `.env` file in project root:

```bash
# .env (local development - NOT committed to git)
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@aws-0-us-east-1.pooler.supabase.com:5432/postgres
GROQ_API_KEY=gsk_your_groq_key_here
SECRET_KEY=your_secret_key_here
```

### Step 4: Test Connection Locally

```bash
cd backend
pip install -r requirements.txt
python -c "from app import db; db.create_all(); print('✅ Connected to Supabase!')"
```

### Step 5: Deploy to Render (Production)

1. Go to **https://render.com**
2. Create Web Service (connect GitHub repo)
3. Add Environment Variables in Render:

| Key | Value |
|-----|-------|
| `DATABASE_URL` | Your Supabase connection string |
| `GROQ_API_KEY` | Your Groq API key |
| `SECRET_KEY` | Generate: `openssl rand -hex 32` |

4. Set Start Command: `python backend/app.py`
5. Deploy!

---

## 📊 Verify Supabase Connection

### Check Tables Were Created

Go to **Supabase Dashboard** → **SQL Editor** and run:

```sql
SELECT table_name FROM information_schema.tables 
WHERE table_schema='public';
```

Should see:
- `user`
- `job`
- `alembic_version`

### View Your Data

**Users table:**
```sql
SELECT id, email, subscription_tier, free_analyses_used FROM "user";
```

**Jobs table:**
```sql
SELECT id, user_id, job_role, status, is_truncated, analysis_number FROM job;
```

---

## 🔧 Troubleshooting

### Connection Refused
**Cause:** Wrong host or password  
**Fix:** Double-check DATABASE_URL in Supabase Dashboard → Settings → Database

### "too many connections"
**Cause:** Connection pool exhausted  
**Fix:** Add `?sslmode=require` to connection string

### Database not created
**Cause:** Tables don't exist yet  
**Fix:** Run backend once:
```bash
python backend/app.py
# First request creates tables automatically
```

### Can't connect from Render
**Cause:** IP whitelist issue  
**Fix:** In Supabase → Settings → Network → Allow connections from anywhere (`0.0.0.0/0`)

---

## 🔐 Security Best Practices

✅ **DO:**
- Store DATABASE_URL in `.env` (not committed)
- Use strong database passwords (20+ chars)
- Enable Supabase Row Level Security (RLS) for user data
- Rotate Groq API keys periodically

❌ **DON'T:**
- Commit `.env` file to git
- Share connection string publicly
- Use `postgres` user for apps (create separate user)
- Allow world-wide IP access in production

---

## 📈 Monitoring

### Check Database Usage

Supabase Dashboard → **Database** → Storage usage shown

### Monitor Connections

```sql
SELECT datname, usename, application_name, state 
FROM pg_stat_activity;
```

### View Query Performance

```sql
SELECT query, calls, mean_time 
FROM pg_stat_statements 
ORDER BY mean_time DESC LIMIT 10;
```

---

## 🚀 Production Deployment Checklist

- [x] Supabase project created
- [x] Connection string obtained
- [x] `.env` file configured locally
- [x] Tables created (verified in SQL Editor)
- [x] Render environment variables set
- [x] DATABASE_URL points to Supabase
- [x] Test connection successful
- [ ] Enable RLS on tables (optional but recommended)
- [ ] Set up Supabase backups (automatic)
- [ ] Monitor storage usage

---

## 📞 Support Links

- **Supabase Docs:** https://supabase.com/docs
- **PostgreSQL Docs:** https://www.postgresql.org/docs/
- **Connection Pooling:** https://supabase.com/docs/guides/database/connecting-to-postgres#connection-pooler
- **Row Level Security:** https://supabase.com/docs/guides/auth/row-level-security

---

## Quick Commands

```bash
# Test connection
psql postgresql://postgres:PASSWORD@host:5432/postgres

# Create backup
pg_dump postgresql://postgres:PASSWORD@host:5432/postgres > backup.sql

# Restore backup
psql postgresql://postgres:PASSWORD@host:5432/postgres < backup.sql

# Check connection status
pg_isready -h host -U postgres
```

---

**Next Step:** Follow DEPLOYMENT_GUIDE.md to deploy to Render!
