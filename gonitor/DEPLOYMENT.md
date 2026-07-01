# Gonitor — Deployment Guide (Render + Vercel)

## Architecture

```
User Browser
     │
     ▼
  Vercel (CDN / Proxy)          ← your-app.vercel.app
     │  rewrites all requests
     ▼
  Render (FastAPI App)          ← gonitor-backend.onrender.com
     │  serves HTML, API, WebSocket
     ▼
  Render PostgreSQL DB          ← internal Render connection
```

> **Why Vercel + Render?**
> The "frontend" is Jinja2 templates rendered server-side by Python — Vercel cannot run them directly.
> Instead, Vercel acts as a CDN/proxy, forwarding all traffic to the Render backend.
> Users get a clean Vercel URL; Render handles all computation.

---

## Step 1 — Push to GitHub

From the `ServiceMonitor/` root:

```bash
git init
git add .
git commit -m "Add Render + Vercel deployment config"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

> ⚠️ `.gitignore` excludes `.env` files — your secrets stay local and out of git.

---

## Step 2 — Deploy Backend on Render

### 2a. Create a Render Account & New Blueprint

1. Go to [render.com](https://render.com) and log in (connect your GitHub).
2. Click **New** → **Blueprint**.
3. Select your GitHub repository.
4. Render will automatically detect `render.yaml` at the repo root.
5. It will create:
   - A **Web Service** (`gonitor-backend`) running the Docker container
   - A **PostgreSQL database** (`gonitor-db`) — `DATABASE_URL` is auto-injected

### 2b. Fill in Sensitive Environment Variables

After the blueprint is applied, go to your **Web Service** → **Environment** tab and fill in these values (they were left blank in `render.yaml` for security):

| Variable | Value |
|---|---|
| `SMTP_USER` | your Gmail address |
| `SMTP_PASSWORD` | Gmail **App Password** (not your login password) |
| `SMTP_FROM_EMAIL` | your Gmail address |
| `RECIPIENT_EMAIL` | where alert emails should go |
| `RECIPIENT_NAME` | your name |
| `GEMINI_API_KEY` | *(optional)* Google AI Studio key |
| `TWILIO_SID` | *(optional)* for SMS alerts |
| `TWILIO_AUTH_TOKEN` | *(optional)* |
| `TWILIO_FROM_PHONE` | *(optional)* |

> ✅ `DATABASE_URL` and `SECRET_KEY` are handled automatically — no action needed.

### 2c. Wait for First Deploy

Watch the **Logs** tab. A successful deploy shows:
```
DB tables ensured.
APScheduler started.
Uvicorn running on http://0.0.0.0:10000
```

> ℹ️ Render uses port `10000` internally (not 8000). Your `$PORT` env var is set automatically.

### 2d. Get Your Render URL

In Render → your web service → **Settings**, note your public URL:
```
https://gonitor-backend.onrender.com
```
(The actual name depends on your service name — check the Render dashboard.)

### 2e. Run Database Migrations

Render runs the app with `uvicorn` which already calls `Base.metadata.create_all` on startup.
Tables are created automatically on first boot.

If you ever need to run Alembic migrations manually, use the **Shell** tab in Render:
```bash
alembic upgrade head
```

---

## Step 3 — Update Vercel Config with Your Render URL

Edit `gonitor/frontend/vercel.json` and replace the URL with your actual Render service URL:

```json
{
  "rewrites": [
    {
      "source": "/(.*)",
      "destination": "https://YOUR-ACTUAL-SERVICE.onrender.com/$1"
    }
  ]
}
```

Commit and push:
```bash
git add gonitor/frontend/vercel.json
git commit -m "Set Render backend URL in vercel.json"
git push
```

---

## Step 4 — Deploy Frontend on Vercel

### 4a. Create a Vercel Project

1. Go to [vercel.com](https://vercel.com) and log in (connect your GitHub).
2. Click **Add New → Project** → import your repository.
3. In **Root Directory**, type: `gonitor/frontend`
4. **Framework Preset**: select **Other** (no build step needed).
5. Click **Deploy**.

### 4b. Get Your Vercel URL

Vercel will give you:
```
https://your-project.vercel.app
```

---

## Step 5 — Update SITE_URL in Render

Go to Render → your web service → **Environment** and update:

```
SITE_URL = https://your-project.vercel.app
```

This ensures login redirects, cookie paths, and alert email links use your Vercel URL.

Render will auto-redeploy after saving.

---

## Step 6 — Verify Everything Works

| Check | URL |
|---|---|
| Homepage / Login | `https://your-project.vercel.app/` |
| Dashboard | `https://your-project.vercel.app/dashboard` |
| Public Status Page | `https://your-project.vercel.app/status` |
| API Health Check | `https://your-project.vercel.app/api/monitoring/status` |
| WebSocket (real-time) | Auto-connects on dashboard load |

---

## WebSocket Notes

Vercel supports WebSocket proxying automatically — no special config needed for the `/ws` endpoint.

---

## Custom Domain (Optional)

1. In **Vercel** → your project → **Settings** → **Domains**: add your custom domain.
2. Update `SITE_URL` in Render to match your custom domain.

---

## Free Tier Limitations

| Platform | Limitation |
|---|---|
| Render Web Service (free) | Spins down after 15 min inactivity — first request is slow (~30s cold start). Upgrade to **Starter ($7/mo)** to keep it always-on. |
| Render PostgreSQL (free) | Expires after **90 days**. Upgrade to **Starter ($7/mo)** for persistent DB. |
| Vercel (free) | 100 GB bandwidth/mo — plenty for most use cases. |

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Render build fails | Check **Logs** — usually a missing env var or pip install error |
| `asyncpg` scheme error | Already handled in `config.py` — it auto-converts `postgresql://` → `postgresql+asyncpg://` |
| 502 on Vercel | Render service is cold-starting or crashed — check Render logs |
| Templates/static not found | Verify `/frontend` is in the Docker image (check Dockerfile) |
| WebSocket drops instantly | Normal on free tier cold start — re-open the page once Render warms up |
| DB connection refused | Render DB and web service must be in the **same region** |
