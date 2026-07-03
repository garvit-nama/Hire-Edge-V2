# HireEdge v2 Setup & Integration Guide

To attain the desired output (Authentication, Supabase Persistence, and Freemium Limits), follow these steps:

## 1. Environment Configuration
Navigate to `backend/.env` and ensure the following variables are set correctly:

- **`DATABASE_URL`**: Your Supabase PostgreSQL connection string. 
  - (Format: `postgresql://postgres:[password]@db.[project-id].supabase.co:5432/postgres`)
- **`SECRET_KEY`**: A random string used to sign security tokens.
- **`GROQ_API_KEY`**: Your existing model API key.

## 2. Install Backend Dependencies
Run this in your terminal to install the new libraries:
```bash
pip install flask-sqlalchemy psycopg2-binary bcrypt pyjwt
```

## 3. Code File Map (What Changed)

### Backend Logic
| File | Purpose |
| :--- | :--- |
| `backend/models.py` | Defines the **User** table (for auth) and **Job** table (for saved reports). |
| `backend/app.py` | Initialized SQLAlchemy and added `/api/register`, `/api/login`, and `/api/my-reports`. |
| `backend/app.py` | Modified `@app.route("/analyse")` to require a login token and check the 3-analysis free limit. |

### Frontend UI
| File | Purpose |
| :--- | :--- |
| `frontend/js/api.js` | Updated `fetch` calls to automatically include the `Authorization` header. |
| `frontend/js/state.js` | Now syncs with `localStorage` to keep you logged in across page refreshes. |
| `frontend/index.html` | Header updated to show "Login" or your Email address depending on status. |
| `frontend/login.html` | Created a new entry point for existing users. |
| `frontend/register.html` | Created a new entry point for new users. |
| `frontend/dashboard.html` | *(In Progress)* Will show your past reports fetched from Supabase. |

## 4. How the Freemium Model works
1. **User registers**: `subscription_tier` defaults to `free` and `free_analyses_used` is set to `0`.
2. **User runs analysis**: The backend checks if they have reached the limit of **3**.
3. **Limit reached**: The backend returns a `403 Forbidden` error, and the UI displays a paywall notification.
4. **Data Persistence**: Unlike the old version, every job is now saved to Supabase so you can view it later in the Dashboard.

## 5. Deployment Note (Supabase)
When you run the app for the first time, SQLAlchemy will automatically create the `user` and `job` tables in your Supabase project as soon as the server starts.
