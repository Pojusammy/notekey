# NoteKey — Deployment Guide

Production stack: **Vercel** (frontend) + **Render** (backend + worker) + **Supabase** (Postgres + Storage) + **Render Redis** or **Upstash**.

---

## Architecture

```
┌─────────────┐     HTTPS      ┌─────────────────┐
│   Vercel     │ ──────────────▶│  Render: API     │
│  (Next.js)   │  BACKEND_URL   │  (FastAPI)       │
└─────────────┘                └────────┬────────┘
                                        │ Celery task
                                        ▼
                               ┌─────────────────┐
                               │  Render: Worker  │
                               │  (Celery)        │
                               └────────┬────────┘
                                        │
                        ┌───────────────┼───────────────┐
                        ▼               ▼               ▼
                ┌──────────┐   ┌──────────────┐  ┌──────────┐
                │ Supabase │   │   Supabase   │  │  Redis   │
                │ Postgres │   │   Storage    │  │ (Render) │
                └──────────┘   └──────────────┘  └──────────┘
```

---

## 1. Supabase Setup

### Database (Postgres)

1. Create a project at [supabase.com](https://supabase.com)
2. Go to **Settings → Database** and copy the connection string
3. Format for the backend:
   ```
   # Async (FastAPI)
   postgresql+asyncpg://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres

   # Sync (Celery) — the app auto-converts +asyncpg to +psycopg2
   ```

### Storage

1. Go to **Storage** in your Supabase dashboard
2. Create a new bucket called `uploads`
3. Set it to **private** (the backend uses the service role key)
4. Go to **Settings → API** and copy:
   - `Project URL` → `SUPABASE_URL`
   - `service_role` key → `SUPABASE_SERVICE_KEY` (NOT the `anon` key)

---

## 2. Redis Setup

### Option A: Render Redis

1. In your Render dashboard, add a **Redis** service
2. Copy the **Internal URL** for use by the API and worker
3. Use the same URL for both `REDIS_URL` and `CELERY_BROKER_URL`

### Option B: Upstash Redis

1. Create a database at [upstash.com](https://upstash.com)
2. Copy the `redis://...` connection string
3. Use for `REDIS_URL`, `CELERY_BROKER_URL`, and `CELERY_RESULT_BACKEND`

---

## 3. Render Setup (Backend + Worker)

### Option A: Deploy via render.yaml (recommended)

1. Push this repo to GitHub
2. In Render, click **New → Blueprint**
3. Connect the repo — Render reads `render.yaml` and creates all services
4. Fill in the env vars when prompted

### Option B: Manual setup

#### API Service

1. **New → Web Service** → connect your repo
2. Settings:
   - **Root Directory**: `backend`
   - **Runtime**: Python 3
   - **Build Command**: `./render-build.sh`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

#### Worker Service

1. **New → Background Worker** → connect your repo
2. Settings:
   - **Root Directory**: `backend`
   - **Runtime**: Python 3
   - **Build Command**: `./render-build.sh`
   - **Start Command**: `celery -A app.core.celery_app worker --loglevel=info --concurrency=2`

### Environment Variables (both services)

Set these on **both** the API and Worker services:

| Variable | Example | Notes |
|----------|---------|-------|
| `PYTHON_VERSION` | `3.11.9` | Must be 3.11.x (TensorFlow constraint) |
| `DATABASE_URL` | `postgresql+asyncpg://...` | From Supabase |
| `REDIS_URL` | `redis://...` | From Render Redis or Upstash |
| `CELERY_BROKER_URL` | `redis://...` | Same as REDIS_URL (or different DB number) |
| `CELERY_RESULT_BACKEND` | `redis://...` | Same as CELERY_BROKER_URL |
| `STORAGE_BACKEND` | `supabase` | Use `supabase` for production |
| `SUPABASE_URL` | `https://xxx.supabase.co` | From Supabase dashboard |
| `SUPABASE_SERVICE_KEY` | `eyJ...` | Service role key (NOT anon) |
| `SUPABASE_BUCKET` | `uploads` | Bucket name you created |
| `CORS_ORIGINS` | `["https://your-app.vercel.app"]` | Your Vercel domain |
| `DEBUG` | `false` | |

> Render provides `$PORT` automatically — do not set it manually.

### FFmpeg on Render

Render's Python runtime includes FFmpeg by default. No extra setup needed.

---

## 4. Vercel Setup (Frontend)

1. In Vercel, import the repo
2. Set **Root Directory** to `frontend`
3. Framework: Next.js (auto-detected)
4. Add environment variable:

| Variable | Value |
|----------|-------|
| `BACKEND_URL` | `https://notekey-api.onrender.com` (your Render API URL) |

5. Deploy

### How it works

The Next.js API routes (`/api/upload`, `/api/analyze`, `/api/jobs/[id]`, `/api/results/[id]`) proxy all requests to the Python backend using `BACKEND_URL`. If the backend is unreachable, they fall back to a local JS analysis (limited accuracy).

---

## 5. Verify Deployment

After all services are deployed:

```bash
# 1. Health check
curl https://notekey-api.onrender.com/health

# 2. Test upload
curl -X POST https://notekey-api.onrender.com/api/upload \
  -F "file=@test.wav"

# 3. Test analysis
curl -X POST https://notekey-api.onrender.com/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"fileUrl":"<fileUrl from step 2>","selectedKey":"C"}'

# 4. Check job status
curl https://notekey-api.onrender.com/api/jobs/<jobId>

# 5. Get results
curl https://notekey-api.onrender.com/api/results/<jobId>
```

---

## Local Development (with Docker)

Docker Compose is still available for local development:

```bash
docker compose up --build
```

This starts Postgres, Redis, the API, and the worker locally. No Supabase or Render needed.

To develop without Docker:

```bash
# Terminal 1: API
cd backend
cp .env.example .env  # edit with local Postgres/Redis URLs
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Worker
cd backend
celery -A app.core.celery_app worker --loglevel=info

# Terminal 3: Frontend
cd frontend
BACKEND_URL=http://localhost:8000 npm run dev
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ResolutionImpossible` on build | Ensure `PYTHON_VERSION=3.11.9` — TensorFlow needs Python 3.11 |
| Worker not processing tasks | Check Redis connectivity and that both services share the same `CELERY_BROKER_URL` |
| Upload fails with 500 | Verify `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and that the `uploads` bucket exists |
| CORS errors on frontend | Add your Vercel domain to `CORS_ORIGINS` on the API service |
| FFmpeg not found | Render includes it by default; if using a custom image, install `ffmpeg` |
| Cold start latency on Render | First request after idle may take 30-60s on the free/starter plan |
