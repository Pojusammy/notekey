# NoteKey — Deployment Guide

Production stack: **Vercel** (frontend) + **Oracle Cloud Always Free VM** (backend) + **Supabase** (Postgres + Storage).

No Redis, no Celery — background analysis jobs run via `asyncio.create_task` inside the FastAPI process.

---

## Architecture

```
┌─────────────┐     HTTPS      ┌──────────────────────┐
│   Vercel     │ ──────────────▶│  Oracle VM           │
│  (Next.js)   │  BACKEND_URL   │  Nginx → Gunicorn    │
└─────────────┘                │  (FastAPI + Uvicorn)  │
                               └──────────┬───────────┘
                                          │
                          ┌───────────────┴───────────────┐
                          ▼                               ▼
                  ┌──────────────┐               ┌──────────────┐
                  │   Supabase   │               │   Supabase   │
                  │   Postgres   │               │   Storage    │
                  └──────────────┘               └──────────────┘
```

---

## 1. Supabase Setup

### Database (Postgres)

1. Create a project at [supabase.com](https://supabase.com)
2. Go to **Settings → Database** and copy the connection string
3. Format for the backend:
   ```
   postgresql+asyncpg://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
   ```

### Storage

1. Go to **Storage** in your Supabase dashboard
2. Create a bucket called `uploads` (set to **private**)
3. Go to **Settings → API** and copy:
   - `Project URL` → `SUPABASE_URL`
   - `service_role` key → `SUPABASE_SERVICE_KEY` (NOT the `anon` key)

---

## 2. Oracle Cloud VM Setup

### Create the VM

1. Sign up for [Oracle Cloud Always Free](https://www.oracle.com/cloud/free/)
2. Create an **Ampere A1** instance (ARM, 4 OCPU / 24 GB RAM — Always Free eligible)
   - OS: Ubuntu 22.04 or 24.04
3. Open ports **80** and **443** in the VCN security list (ingress rules)

### Install System Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip \
    nginx certbot python3-certbot-nginx ffmpeg git
```

### Deploy the Backend

```bash
# Create service user
sudo useradd -r -s /bin/false notekey
sudo mkdir -p /opt/notekey
sudo chown notekey:notekey /opt/notekey

# Clone repo and set up venv
sudo -u notekey git clone https://github.com/YOUR_USER/note-keys.git /opt/notekey
cd /opt/notekey/backend
sudo -u notekey python3.11 -m venv /opt/notekey/venv
sudo -u notekey /opt/notekey/venv/bin/pip install --no-cache-dir -r requirements.txt
```

### Configure Environment

```bash
sudo -u notekey cp /opt/notekey/backend/.env.example /opt/notekey/backend/.env
sudo -u notekey nano /opt/notekey/backend/.env
```

Set these values in `.env`:

| Variable | Value | Notes |
|----------|-------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | From Supabase |
| `STORAGE_BACKEND` | `supabase` | Use `supabase` for production |
| `SUPABASE_URL` | `https://xxx.supabase.co` | From Supabase dashboard |
| `SUPABASE_SERVICE_KEY` | `eyJ...` | Service role key (NOT anon) |
| `SUPABASE_BUCKET` | `uploads` | Bucket name you created |
| `CORS_ORIGINS` | `["https://your-app.vercel.app"]` | Your Vercel domain |
| `DEBUG` | `false` | |

### Install systemd Service

```bash
sudo cp /opt/notekey/deploy/notekey-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now notekey-api
sudo systemctl status notekey-api
```

### Install Nginx Config

```bash
# Copy and edit the config (replace your-domain.com)
sudo cp /opt/notekey/deploy/notekey-nginx.conf /etc/nginx/sites-available/notekey
sudo ln -s /etc/nginx/sites-available/notekey /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default

# Test and reload
sudo nginx -t
sudo systemctl reload nginx
```

### Set Up SSL (Let's Encrypt)

```bash
sudo certbot --nginx -d your-domain.com
```

Certbot will auto-renew via systemd timer.

---

## 3. Vercel Setup (Frontend)

1. Import the repo in Vercel
2. Set **Root Directory** to `frontend`
3. Framework: Next.js (auto-detected)
4. Add environment variable:

| Variable | Value |
|----------|-------|
| `BACKEND_URL` | `https://your-domain.com` (your Oracle VM domain) |

5. Deploy

### How it works

The Next.js API routes (`/api/upload`, `/api/analyze`, `/api/jobs/[id]`, `/api/results/[id]`) proxy all requests to the Python backend using `BACKEND_URL`.

---

## 4. Verify Deployment

```bash
# 1. Health check
curl https://your-domain.com/health

# 2. Test upload
curl -X POST https://your-domain.com/api/upload \
  -F "file=@test.wav"

# 3. Test analysis
curl -X POST https://your-domain.com/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"fileUrl":"<fileUrl from step 2>","selectedKey":"C"}'

# 4. Check job status
curl https://your-domain.com/api/jobs/<jobId>

# 5. Get results
curl https://your-domain.com/api/results/<jobId>
```

---

## 5. Updating the Backend

```bash
cd /opt/notekey
sudo -u notekey git pull
sudo -u notekey /opt/notekey/venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart notekey-api
```

---

## Local Development (with Docker)

Docker Compose is still available for local development:

```bash
docker compose up --build
```

This starts Postgres and the API locally. No Supabase needed.

To develop without Docker:

```bash
# Terminal 1: API
cd backend
cp .env.example .env  # edit with local Postgres URL
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Frontend
cd frontend
BACKEND_URL=http://localhost:8000 npm run dev
```

---

## Cost Summary

| Service | Cost |
|---------|------|
| Oracle Cloud VM (A1 Ampere) | **Free** (Always Free tier) |
| Supabase (Postgres + Storage) | **Free** (Free tier: 500 MB DB, 1 GB storage) |
| Vercel (Frontend) | **Free** (Hobby plan) |
| Domain + SSL | ~$10/year (domain) + Free (Let's Encrypt) |
| **Total** | **~$0–10/year** |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ResolutionImpossible` on pip install | Ensure Python 3.11 — TensorFlow/Basic Pitch needs 3.11 |
| Analysis hangs or times out | Check gunicorn `--timeout 300` and nginx `proxy_read_timeout` |
| Upload fails with 500 | Verify `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, bucket exists |
| CORS errors on frontend | Add your Vercel domain to `CORS_ORIGINS` |
| FFmpeg not found | `sudo apt install ffmpeg` |
| VM not reachable on 80/443 | Check Oracle VCN security list AND `iptables` rules |
| Service won't start | `journalctl -u notekey-api -f` for logs |
