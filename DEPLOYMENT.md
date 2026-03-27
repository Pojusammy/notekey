# NoteKey — Deployment Guide

Production stack: **Vercel** (Next.js frontend) + **Oracle Cloud Always Free VM** (FastAPI backend) + **Supabase** (Postgres + Storage).

No Redis, no Celery, no Docker in production — background analysis runs via `asyncio.create_task` inside the FastAPI process.

---

## Architecture

```
┌────────────────────┐        HTTPS        ┌────────────────────────┐
│  Vercel             │ ──────────────────▶ │  Oracle Cloud VM       │
│  Next.js frontend   │    BACKEND_URL      │  Nginx → Gunicorn      │
│  (Preview + Prod)   │                     │  (FastAPI + Uvicorn)   │
└────────────────────┘                     └───────────┬────────────┘
                                                       │
                                       ┌───────────────┴──────────────┐
                                       ▼                              ▼
                               ┌──────────────┐              ┌──────────────┐
                               │   Supabase   │              │   Supabase   │
                               │   Postgres   │              │   Storage    │
                               └──────────────┘              └──────────────┘
```

**How the proxy works:** The Next.js API routes (`/api/upload`, `/api/analyze`, `/api/jobs/[id]`, `/api/results/[id]`, `/api/history`) proxy requests to the Python backend using the `BACKEND_URL` environment variable. If the backend is unreachable, they fall back to local JS-based analysis.

---

## 1. Supabase Setup

### Postgres

1. Create a project at [supabase.com](https://supabase.com)
2. Go to **Settings → Database** and copy the connection string
3. Format for the backend:
   ```
   postgresql+asyncpg://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
   ```

### Storage

1. Go to **Storage** → create a bucket called `uploads` (set to **private**)
2. Go to **Settings → API** and copy:
   - `Project URL` → `SUPABASE_URL`
   - `service_role` key → `SUPABASE_SERVICE_KEY` (NOT the `anon` key)

---

## 2. Oracle Cloud VM Setup

### Create the VM

1. Sign up for [Oracle Cloud Always Free](https://www.oracle.com/cloud/free/)
2. Create an **Ampere A1** instance (ARM, 4 OCPU / 24 GB RAM — Always Free eligible)
   - OS: Ubuntu 22.04 or 24.04
3. Open ports **80** and **443** in the VCN security list (ingress rules)
4. Point your domain's A record to the VM's public IP

### Automated Setup

SSH into the VM and run:

```bash
git clone https://github.com/Pojusammy/notekey.git /tmp/notekey-setup
sudo bash /tmp/notekey-setup/deploy/setup.sh \
    https://github.com/Pojusammy/notekey.git \
    api.your-domain.com
```

This installs all system dependencies, creates the Python venv, configures systemd + Nginx, and prepares the `.env` file.

### Configure Environment

```bash
sudo -u notekey nano /opt/notekey/backend/.env
```

Set these production values:

| Variable | Value | Notes |
|----------|-------|-------|
| `DEBUG` | `false` | |
| `DATABASE_URL` | `postgresql+asyncpg://...` | From Supabase |
| `STORAGE_BACKEND` | `supabase` | |
| `SUPABASE_URL` | `https://xxx.supabase.co` | From Supabase dashboard |
| `SUPABASE_SERVICE_KEY` | `eyJ...` | Service role key (NOT anon) |
| `SUPABASE_BUCKET` | `uploads` | |
| `CORS_ORIGINS` | `["https://notekey.vercel.app"]` | Your Vercel production domain |
| `CORS_ORIGIN_REGEX` | `https://.*\.vercel\.app` | Auto-allows all Vercel preview URLs |

### Start the API

```bash
sudo systemctl start notekey-api
sudo systemctl status notekey-api   # should show "active (running)"
curl http://localhost:8000/health    # {"status":"ok","service":"NoteKey API"}
```

### SSL (Let's Encrypt)

```bash
sudo certbot --nginx -d api.your-domain.com
```

Certbot auto-renews via systemd timer. After SSL:

```bash
curl https://api.your-domain.com/health
```

---

## 3. Vercel Setup (Frontend)

### Import the repo

1. Go to [vercel.com](https://vercel.com) → **Add New → Project**
2. Import the GitHub repo
3. Set **Root Directory** to `frontend`
4. Framework: Next.js (auto-detected)

### Environment Variables

Set `BACKEND_URL` in Vercel project settings → **Environment Variables**:

| Environment | Variable | Value |
|-------------|----------|-------|
| Production | `BACKEND_URL` | `https://api.your-domain.com` |
| Preview | `BACKEND_URL` | `https://api.your-domain.com` |
| Development | `BACKEND_URL` | `http://localhost:8000` |

Both Preview and Production point to the same Oracle VM backend. The backend's `CORS_ORIGIN_REGEX` (`https://.*\.vercel\.app`) automatically allows all Vercel preview URLs.

### Deploy

Push to `main` for production. Push to any other branch (or open a PR) for a preview deployment.

---

## 4. Verify End-to-End

```bash
# 1. Backend health
curl https://api.your-domain.com/health

# 2. Upload a file
curl -X POST https://api.your-domain.com/api/upload \
  -F "file=@test.wav"

# 3. Start analysis
curl -X POST https://api.your-domain.com/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"fileUrl":"<fileUrl from step 2>","selectedKey":"C"}'

# 4. Poll job status
curl https://api.your-domain.com/api/jobs/<jobId>

# 5. Get results
curl https://api.your-domain.com/api/results/<jobId>
```

---

## 5. Updating the Backend

```bash
ssh your-vm
cd /opt/notekey
sudo -u notekey git pull
sudo -u notekey /opt/notekey/venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart notekey-api
```

---

## Local Development

### With Docker (Postgres only, no Redis)

```bash
docker compose up --build
```

Starts Postgres + the API locally. No Supabase needed.

### Without Docker

```bash
# Terminal 1: Backend
cd backend
cp .env.example .env   # edit DATABASE_URL if needed
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Frontend
cd frontend
npm run dev   # reads BACKEND_URL from .env.local
```

---

## Cost Summary

| Service | Cost |
|---------|------|
| Oracle Cloud VM (A1 Ampere, 4 OCPU / 24 GB) | **Free** (Always Free tier) |
| Supabase (Postgres + Storage) | **Free** (500 MB DB, 1 GB storage) |
| Vercel (Next.js frontend) | **Free** (Hobby plan) |
| Domain + SSL | ~$10/year domain + Free (Let's Encrypt) |
| **Total** | **~$0–10/year** |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ResolutionImpossible` on pip install | Ensure Python 3.11 — TensorFlow/Basic Pitch needs it |
| Analysis hangs or times out | Check gunicorn `--timeout 300` and nginx `proxy_read_timeout` |
| Upload fails with 500 | Verify `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, bucket exists |
| CORS errors from Vercel preview | Check `CORS_ORIGIN_REGEX` is set to `https://.*\.vercel\.app` |
| FFmpeg not found | `sudo apt install ffmpeg` |
| VM not reachable on 80/443 | Check Oracle VCN security list AND `sudo iptables -L` |
| Service won't start | `journalctl -u notekey-api -f` for logs |
| ARM pip install fails | Some packages need build tools: `sudo apt install build-essential` |
