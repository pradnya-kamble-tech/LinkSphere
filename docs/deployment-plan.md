# LinkSphere v2 Deployment Plan (Level 4.5 / Phase C1)

> **Important**: This document represents an architectural plan only. No deployment code has been written or deployed. All dollar figures and resource costs listed below are estimates that the user must verify themselves. Numbers marked with **(verify)** are subject to platform pricing tiers, egress quotas, and changes over time.

---

## 1. Target Architecture & Topology

LinkSphere v2 consists of three primary runtime components:
1. **Frontend**: Static React + Vite Single Page Application (SPA).
2. **Backend**: FastAPI (Python 3.11+) ASGI application running with Uvicorn.
3. **Database**: PostgreSQL 16 (with connection pooling and automated backups).

```
                      [ Client Browser ]
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
       [ Frontend (SPA) ]           [ Reverse Proxy / CDN ]
       (Vercel / Cloudflare)                 │ HTTPS
                                             ▼
                                     [ Backend API ]
                                     FastAPI + Uvicorn
                                     (Render / Railway)
                                             │
                                             ▼
                                     [ PostgreSQL 16 ]
                                     (Supabase / Neon / Render)
```

---

## 2. Infrastructure Options & Cost Estimates

### Option A: PaaS Stack (Recommended for Simplicity & Low Operational Burden)
* **Frontend**: Vercel (Hobby Tier) or Cloudflare Pages
  * Cost: **\$0/month** (Hobby / Free Tier) **(verify)**
  * Capabilities: Global CDN, automatic SSL/TLS, Git push deployments.
* **Backend API**: Render or Railway (Individual Web Service)
  * Render Starter Web Service (0.5 CPU, 512 MB RAM): **\$7/month (verify)**
  * Railway Hobby Tier: **\$5/month base + usage (verify)**
* **Managed Database**: Supabase or Neon (PostgreSQL 16)
  * Supabase Free Tier: **\$0/month** (500 MB DB storage, pause after inactivity) **(verify)**
  * Supabase Pro Tier: **\$25/month** (8 GB storage, daily backups, no pausing) **(verify)**
  * Neon Free Tier: **\$0/month** (0.5 GB storage, autoscaling) **(verify)**
* **Estimated Monthly Total (PaaS)**:
  * Minimal / Staging: **\$7/month (verify)**
  * Production-ready (unpaused DB): **\$32/month (verify)**

### Option B: Unified Single-Host VPS (Hetzner / DigitalOcean)
* **VPS Host**:
  * DigitalOcean Basic Droplet (1 vCPU, 2 GB RAM, 50 GB SSD): **\$12/month (verify)**
  * Hetzner Cloud CX22 (2 vCPU, 4 GB RAM, 40 GB NVMe): **€3.79/month (~$4.15/month) (verify)**
* **Architecture on Host**:
  * Caddy or Nginx reverse proxy with automated Let's Encrypt SSL/TLS.
  * Systemd service or Docker Compose running FastAPI backend (uvicorn workers).
  * Native or Dockerized PostgreSQL 16 with volume mount and cron pg_dump backups.
  * Static build files served directly by Caddy/Nginx.
* **Estimated Monthly Total (VPS)**:
  * Hetzner: **~\$4.20/month (verify)**
  * DigitalOcean: **~\$12/month (verify)**

---

## 3. Environment Variables & Secret Configuration

The production environment must configure the following variables securely via the hosting provider's dashboard (never committed to git):

| Variable | Description | Example / Format |
| :--- | :--- | :--- |
| `ENVIRONMENT` | Runtime mode | `production` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+psycopg://user:pass@host:5432/dbname?sslmode=require` |
| `FRONTEND_ORIGIN` | Allowed web origin for CORS & CSRF | `https://linksphere.yourdomain.com` |
| `SHORT_LINK_BASE_URL` | Domain prefix for generated short URLs | `https://linksphere.yourdomain.com` |
| `SESSION_SECRET` | 32-byte secret for session cookie signing | `openssl rand -hex 32` |
| `COOKIE_SECURE` | Enforce HTTPS-only cookie transmission | `true` |
| `GOOGLE_CLIENT_ID` | OAuth Client ID from Google Cloud Console | `*.apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | OAuth Client Secret from Google Cloud Console | `GOCSPX-*` |
| `GITHUB_CLIENT_ID` | OAuth App Client ID from GitHub Developer Settings | `Ov23*` |
| `GITHUB_CLIENT_SECRET` | OAuth App Secret from GitHub Developer Settings | `[40-hex-characters]` |

---

## 4. Rate-Limiting & Reverse Proxy Requirements (Level 4.5 Gateway)

To protect PostgreSQL connection pool and CPU resources, the reverse proxy or API gateway must enforce rate limits:
1. **Analytics Endpoints** (`/api/analytics/*`): **60 requests/minute per user**.
2. **Settings & Session Endpoints** (`/api/me/*`, `/api/auth/logout-all`): **30 requests/minute per user**.
3. **Redirect Endpoint** (`/{short_code}`): **120 requests/second per IP** (burst protection against link crawlers/scrapers).
4. **General Link Management** (`/api/links`): **60 requests/minute per user**.

---

## 5. Deployment Step-by-Step Procedure

1. **Step 1: Database Provisioning**:
   - Provision PostgreSQL 16 instance.
   - Run Alembic migrations: `alembic upgrade head`.
   - Verify connection pool connectivity (`pool_pre_ping=True`, `pool_size=10`, `max_overflow=20`).
2. **Step 2: Backend Service Deployment**:
   - Build container or virtualenv with dependencies pinned from `requirements.txt`.
   - Launch Uvicorn with appropriate worker count (on Linux host: `(2 * CPU cores) + 1` workers, e.g. 2–4 workers).
   - Verify health check: `GET /health` returns `{"status": "healthy"}`.
3. **Step 3: Frontend Deployment**:
   - Set build environment variable `VITE_API_URL` to the production backend API URL.
   - Run `npm run build` to generate `/dist`.
   - Configure SPA routing fallback: all non-asset paths rewrite to `/index.html`.
4. **Step 4: OAuth Provider Domain Configuration**:
   - In Google Cloud Console: Add authorized JavaScript origin (`https://linksphere.yourdomain.com`) and redirect URI (`https://api.yourdomain.com/api/auth/callback/google`).
   - In GitHub Developer Settings: Add authorization callback URL (`https://api.yourdomain.com/api/auth/callback/github`).
5. **Step 5: Post-Deployment Verification & Scaling Baseline**:
   - Execute benchmark scaling curve on the production deployment host at **1, 5, 20, and 50 concurrent users** across `GET /api/me`, `GET /{short_code}`, and `GET /api/analytics/summary` to establish true server saturation vs serialization points.
