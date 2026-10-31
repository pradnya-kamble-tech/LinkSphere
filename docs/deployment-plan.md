# LinkSphere v2 Production Deployment Plan v2 (Single-Origin Architecture)

> **Important**: This document is an architectural and operational plan. No deployment code or application changes have been committed. All costs, quotas, and limits listed below are marked with **(verify)** and must be verified against current vendor pricing.

---

## 1. Single-Origin Architecture

LinkSphere v2 operates strictly on a **Single Origin** (`https://<your-domain>`). The backend ASGI service serves API routes, short-code redirects, and static frontend assets directly:

```
                                [ Client Browser ]
                                        │
                                        ▼ HTTPS (Port 443)
                        ┌───────────────────────────────┐
                        │   https://<your-domain>       │
                        │   (PaaS Ingress / Caddy Proxy)│
                        └───────────────┬───────────────┘
                                        │
                                        ▼ HTTP (Internal Port 8001)
                        ┌───────────────────────────────┐
                        │   FastAPI + Uvicorn Service   │
                        │                               │
                        │  ├─ /api/*        (JSON API)  │
                        │  ├─ /assets/*     (Static JS) │
                        │  ├─ /favicon.ico  (Static Root│
                        │  ├─ /{short_code} (302 Redir) │
                        │  └─ /login, etc.  (SPA HTML)  │
                        └───────────────┬───────────────┘
                                        │
                                        ▼ SQL (Port 5432 / 5434)
                        ┌───────────────────────────────┐
                        │        PostgreSQL 16          │
                        │ (Managed DB or Docker Engine) │
                        └───────────────────────────────┘
```

### Key Architectural Characteristics
- **No CORS**: Because browser requests originate from `https://<your-domain>` and target `https://<your-domain>/api/*`, requests are same-origin. Preflight `OPTIONS` requests and cross-origin header checks are avoided. Session cookies (`SameSite=Lax`, `Secure`, `HttpOnly`) function reliably across all modern browsers.
- **No `VITE_API_URL`**: As verified in [`frontend/src/api.ts`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/frontend/src/api.ts), the frontend issues all API requests to relative paths (e.g. `fetch('/api/me')`). No build-time API domain injection is required.
- **Unified Short Link Domain**: `SHORT_LINK_BASE_URL` matches the apex/service origin: `https://<your-domain>`. Generated links take the form `https://<your-domain>/{short_code}`.

### Required Code & Configuration Changes (Numbered List)
The following code adjustments are required to implement single-origin serving (listed for planning; no code has been modified):

1. **Multi-Stage Container Bundling**: Build the frontend (`npm run build` producing `frontend/dist`) during the Docker build process and copy `dist/` into `backend/static/`.
2. **Mount Hashed Assets Directory**: Mount `StaticFiles(directory="static/assets")` under `/assets` in [`backend/app/main.py`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/backend/app/main.py).
3. **Serve Root Static Files**: Add explicit endpoints or static mounts for `/favicon.ico`, `/robots.txt`, `/sitemap.xml`, and `/manifest.json` from `static/`.
4. **Explicit SPA Route Handling & Fallback Ordering**:
   - Order of route evaluation in FastAPI:
     1. `/api/*`: API routers (health, auth, users, links, analytics).
     2. `/assets/*`: Hashed JS and CSS assets.
     3. Known system/root static files (`/favicon.ico`, etc.).
     4. Known frontend client routes (`/`, `/login`, `/signup`, `/dashboard`, `/analytics`, `/settings`): Serve `static/index.html`.
     5. `/{short_code}`: Dynamic database redirect lookup. If found and active, return HTTP 302. If not found or soft-deleted, return the existing custom 404 HTML page.
5. **Caching Policy Middleware**:
   - `/assets/*`: `Cache-Control: public, max-age=31536000, immutable` (Vite creates content-hashed assets; can be cached permanently).
   - `/`, `/login`, `/dashboard`, etc. (`index.html`): `Cache-Control: no-cache, no-store, must-revalidate` (ensures users receive new frontend deployments immediately).
   - `/api/*`: `Cache-Control: no-store`.
   - `/{short_code}` (Redirect): `Cache-Control: private, max-age=0, no-cache` (forces every click to reach backend to record analytics).
6. **Security Headers Middleware**: Enforce via FastAPI middleware or reverse proxy:
   - `Strict-Transport-Security`: `max-age=31536000; includeSubDomains; preload`
   - `Content-Security-Policy`: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none';`
   - `X-Content-Type-Options`: `nosniff`
   - `X-Frame-Options`: `DENY`
   - `Referrer-Policy`: `strict-origin-when-cross-origin`
   - `Permissions-Policy`: `camera=(), microphone=(), geolocation=()`
7. **CORS Middleware Removal / Restriction**: Remove or restrict `CORSMiddleware` in `app/main.py` since all traffic is same-origin.

---

## 2. Reserved Words & Frontend Route Synchronization

### Route Inventory
From [`frontend/src/App.tsx`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/frontend/src/App.tsx#L12-L21), the active client-side routes are:
- `/` (Home)
- `/login` (Login)
- `/signup` (Signup)
- `/dashboard` (Dashboard)
- `/analytics` (Analytics) — **Currently missing from `RESERVED_CODES`**
- `/settings` (Settings) — **Currently missing from `RESERVED_CODES`**

### Complete Target `RESERVED_CODES` Set
In [`backend/app/links/schemas.py`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/backend/app/links/schemas.py#L9-L24), `RESERVED_CODES` must include all frontend routes and system paths:
```python
RESERVED_CODES = {
    # System & API endpoints
    "api",
    "health",
    "docs",
    "redoc",
    "openapi.json",
    # Frontend SPA routes (derived from App.tsx)
    "login",
    "signup",
    "dashboard",
    "analytics",   # Newly added
    "settings",    # Newly added
    # Static assets and search engine roots
    "assets",
    "static",
    "favicon.ico",
    "robots.txt",
    "sitemap.xml",
    "admin",
}
```

### Proposed Automated Drift Prevention Test
To prevent regression when new frontend routes are added, add a test in `backend/tests/test_links.py`:
```python
def test_reserved_codes_cover_all_frontend_routes():
    """Ensure every route path registered in frontend/src/App.tsx is present in RESERVED_CODES."""
    import re
    from pathlib import Path
    from app.links.schemas import RESERVED_CODES

    app_tsx = Path("../frontend/src/App.tsx")
    if not app_tsx.exists():
        app_tsx = Path("frontend/src/App.tsx")
    
    content = app_tsx.read_text(encoding="utf-8")
    # Matches <Route path="/xyz" ...>
    routes = set(re.findall(r'<Route\s+path=["\']/([^"\'*]+)["\']', content))
    
    missing = routes - RESERVED_CODES
    assert not missing, f"Frontend routes missing from RESERVED_CODES: {missing}"
```

---

## 3. Code-vs-Plan Environment & Route Audit

### Environment Variable Comparison Table
Audit of every environment variable against [`backend/app/core/config.py`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/backend/app/core/config.py) and [`.env.example`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/.env.example):

| Variable Name | Status in Code | Production Value / Format | Default in Code | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `ENVIRONMENT` | Verified | `production` | `local` | Governs secure cookies, error output, and diagnostic routes |
| `DATABASE_URL` | Verified | `postgresql+psycopg://user:pass@host:5432/dbname?sslmode=require` | (Local dev URL) | Database connection string using Psycopg 3 |
| `FRONTEND_ORIGIN` | Verified | `https://<your-domain>` | `http://localhost:5173` | Allowed origin for CSRF checks on state-changing POST/DELETE |
| `SHORT_LINK_BASE_URL` | Verified | `https://<your-domain>` | `http://localhost:8001` | Canonical short URL prefix returned by link endpoints |
| `SESSION_SECRET` | Verified | `[64-character hex string]` | `""` (fails startup if empty) | Secret for session cookie verification |
| `GOOGLE_CLIENT_ID` | Verified | `*.apps.googleusercontent.com` | `""` (fails startup if empty) | Google OAuth 2.0 Web Client ID |
| `GOOGLE_CLIENT_SECRET` | Verified | `GOCSPX-*` | `""` (fails startup if empty) | Google OAuth 2.0 Web Client Secret |
| `GITHUB_CLIENT_ID` | Verified | `Ov23*` | `""` (fails startup if empty) | GitHub OAuth Application Client ID |
| `GITHUB_CLIENT_SECRET` | Verified | `[40-character hex string]` | `""` (fails startup if empty) | GitHub OAuth Application Client Secret |
| `SESSION_LIFETIME_DAYS` | Verified | `7` | `7` | Maximum absolute session lifetime |
| `SESSION_IDLE_TIMEOUT_HOURS`| Verified | `24` | `24` | Session idle timeout |
| `DB_POOL_SIZE` | Verified | `10` | `10` | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | Verified | `10` | `10` | Additional temporary connections under spike load |
| `DB_POOL_TIMEOUT` | Verified | `30` | `30` | Seconds to wait before raising connection checkout timeout |
| `DB_POOL_PRE_PING` | Verified | `True` | `True` | Tests connection liveness before checkout (`SELECT 1`) |

### Corrected Removals
- **Removed `COOKIE_SECURE`**: Does not exist as an environment variable. In `config.py`, `cookie_secure` is a computed property:
  ```python
  @property
  def cookie_secure(self) -> bool:
      return self.ENVIRONMENT.lower() == "production"
  ```
- **Removed `VITE_API_URL`**: Does not exist in frontend.
- **Corrected Health Path**: Path is `/api/health` (sync endpoint in `app/api/health.py`).
  - Healthy response: `HTTP 200 OK` with JSON `{"status": "ok", "database": "connected"}`.
  - Unhealthy response: `HTTP 503 Service Unavailable` with `{"detail": "Database connection failed: <error>"}`.

---

## 4. Application-Level Rate Limiting Design

### Architecture & Approach
To maintain documentation integrity and avoid adding unvetted third-party packages, we propose a **hand-written in-process sliding-window counter** implemented as FastAPI middleware/dependencies:
- **No Extra Dependencies**: Implemented in standard library Python (`time`, `collections.deque`, `threading.Lock`).
- **Alternative (Requires Operator Approval)**: `slowapi` (based on `limits`). *We ask for user approval before adding `slowapi` or Redis dependencies.*

### Multi-Worker Behavior (Without Shared Redis)
- In a multi-worker setup (e.g. 2–4 uvicorn workers per container), in-process memory is isolated to each worker process.
- Under round-robin load balancing, an in-memory limit of $N$ req/min results in an effective cluster capacity of up to $N \times W$ (where $W$ is worker count) if traffic distributes evenly.
- For a small-to-medium scale application, this provides reliable burst protection against single-worker saturation without the operational overhead, cost, and failure mode of an external Redis cluster.

### Rate Limit Tiers

| Tier / Endpoint | Key / Identity | Rate Limit | Action on Exceeded |
| :--- | :--- | :--- | :--- |
| **Analytics Endpoints** (`/api/analytics/*`) | `user_id` (from session) | **60 req / min** | HTTP 429 Too Many Requests |
| **Settings & Session Endpoints** (`/api/me/*`, `/logout-all`) | `user_id` (from session) | **30 req / min** | HTTP 429 Too Many Requests |
| **General Link Endpoints** (`GET/PATCH/DELETE /api/links/*`) | `user_id` (from session) | **60 req / min** | HTTP 429 Too Many Requests |
| **Link Creation** (`POST /api/links`) | `user_id` (from session) | **20 req / min** + **100 links / day** | HTTP 429 (rate) / HTTP 403 (daily quota) |
| **OAuth Initiation** (`GET /api/auth/{provider}/login`) | Client IP (trusted proxy) | **10 req / min** | HTTP 429 Too Many Requests |
| **OAuth Callback** (`GET /api/auth/callback/{provider}`) | Client IP (trusted proxy) | **10 req / min** | HTTP 429 Too Many Requests |
| **Short Link Redirect** (`/{short_code}`) | Client IP (trusted proxy) | **120 req / min** (burst: 30 / 10s) | HTTP 429 Custom HTML |

#### Daily Link Creation Cap Enforcement
In addition to the per-minute limit on `POST /api/links`, enforce a per-user daily cap of 100 links/day directly in PostgreSQL:
```sql
SELECT count(*) FROM links 
WHERE user_id = :user_id 
  AND created_at >= (NOW() AT TIME ZONE 'UTC')::date;
```
If count $\ge$ 100, reject with HTTP 403: `{"detail": "Daily link creation limit reached (100 links/day)."}`.

### Trusted Proxy Header & Client IP Verification
- **Threat**: Spoofing `X-Forwarded-For` by injecting fake headers in client requests.
- **Configuration**:
  - Run Uvicorn with `--proxy-headers` and `--forwarded-allow-ips`.
  - For VPS (Caddy on localhost): `--forwarded-allow-ips="127.0.0.1,::1"`.
  - For PaaS (Render / Railway): Set `--forwarded-allow-ips` to the private CIDR of the PaaS load balancer (or verify provider documentation).
- **IP Extraction Logic**: Inspect `request.client.host` after Uvicorn parses the proxy headers. Never read raw, untrusted `X-Forwarded-For` headers directly in application code.

---

## 5. Database Capacity, Connection Budget & Performance

### Connection Budget Arithmetic
Each FastAPI worker maintains an independent SQLAlchemy connection pool.

$$\text{Total Connections} = N_{\text{instances}} \times N_{\text{workers}} \times (\text{DB\_POOL\_SIZE} + \text{DB\_MAX\_OVERFLOW}) + \text{Buffer}_{\text{admin}}$$

- **PaaS Stack (Option A)**:
  - Web Instances: 1
  - Workers per Instance: 2
  - Pool Settings: `DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=5`
  - Calculation: $1 \times 2 \times (10 + 5) = 30\text{ connections peak}$.
  - Entry-tier managed Postgres limit: **50 to 100 connections (verify)**.
  - Leaves 20–70 connections available for Alembic migrations, administrative `psql`, and backup workers.
- **VPS Stack (Option B)**:
  - Web Instances: 1
  - Workers: 2
  - Pool Settings: `DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=10`
  - Calculation: $1 \times 2 \times (10 + 10) = 40\text{ connections peak}$.
  - PostgreSQL default `max_connections`: **100 connections (verify)**.
  - Leaves 60 connections headroom.

### Threadpool Sizing vs Connection Pool
- In [`backend/app/main.py`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/backend/app/main.py#L27-L29), the code sets:
  ```python
  anyio.to_thread.current_default_thread_limiter().total_tokens = 200
  ```
- Contrast: While the worker can execute up to 200 synchronous worker threads concurrently, the database connection pool only permits 10–20 active database checkouts.
- Consequence: Under heavy concurrent load (> 20 concurrent DB requests per worker), surplus requests queue up inside SQLAlchemy's pool checkout queue, waiting up to `DB_POOL_TIMEOUT=30` seconds before failing. This explains the tail latencies observed in earlier benchmarks.

### Psycopg 3 Prepared Statements vs Transaction Poolers (e.g. PgBouncer / Supabase)
- **Problem**: Psycopg 3 enables client-side prepared statement caching by default. If a managed PostgreSQL provider routes traffic through PgBouncer in **transaction pooling mode**, different statements within or between transactions are handled by different backend server connections. A prepared statement created on server connection A will trigger `Prepared statement does not exist (SQLSTATE 26000)` on server connection B.
- **Mitigation**:
  - In `DATABASE_URL` connect arguments, set `prepare_threshold=None` in SQLAlchemy's `connect_args={"prepare_threshold": None}`.
  - Alternatively, connect to the direct session port (typically port 5432) or use session pooling mode instead of transaction pooling mode.

### Default Worker Count & Memory Sizing
- **Recommended Worker Count**: **2 Uvicorn workers** on a 1 vCPU / 1–2 GB RAM instance.
- **Memory Footprint Breakdown**:
  - Base Python 3.11 + FastAPI + SQLAlchemy + Authlib: ~110–130 MB RSS per worker.
  - Memory under sustained query load: ~180–220 MB RSS per worker.
  - 2 Workers total: ~400–440 MB RAM.
  - Host OS + Caddy reverse proxy: ~150–200 MB RAM.
  - Total System RAM: ~650 MB. Fits safely within a 1 GB or 2 GB RAM profile with no OOM-killer risk.

---

## 6. Operational Architecture & Resilience

### GitHub Actions CI/CD Workflow Outline
Workflow file: `.github/workflows/ci.yml`
```yaml
name: CI / Test Gate

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  backend-test:
    runs-on: ubuntu-latest
    services:
      linksphere_test:
        image: postgres:16
        env:
          POSTGRES_DB: linksphere_test
          POSTGRES_USER: test_user
          POSTGRES_PASSWORD: test_password
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 5s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - name: Install dependencies
        run: pip install -r backend/requirements.txt
      - name: Run migrations
        env:
          DATABASE_URL: postgresql+psycopg://test_user:test_password@localhost:5432/linksphere_test
        run: |
          cd backend
          alembic upgrade head
      - name: Execute pytest
        env:
          ENVIRONMENT: test
          DATABASE_URL: postgresql+psycopg://test_user:test_password@localhost:5432/linksphere_test
          SESSION_SECRET: ci_test_dummy_session_secret_32_characters_minimum!
          GOOGLE_CLIENT_ID: dummy_google_client_id
          GOOGLE_CLIENT_SECRET: dummy_google_client_secret
          GITHUB_CLIENT_ID: dummy_github_client_id
          GITHUB_CLIENT_SECRET: dummy_github_client_secret
        run: |
          cd backend
          pytest -v

  frontend-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json
      - name: Install dependencies
        run: |
          cd frontend
          npm ci
      - name: Build frontend
        run: |
          cd frontend
          npm run build

  deploy-gate:
    needs: [backend-test, frontend-build]
    runs-on: ubuntu-latest
    steps:
      - name: Gate Check
        run: echo "All tests and builds passed. Ready for deployment."
```
*Rule*: Deployment is blocked unless both `backend-test` and `frontend-build` complete with zero errors.

### Backend Multi-Stage Dockerfile Outline
```dockerfile
# Stage 1: Build Frontend SPA
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Production Python Runtime
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Security: Create unprivileged application user
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

# Install system dependencies for build and health check
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ /app/

# Copy compiled frontend from Stage 1 into backend static directory
COPY --from=frontend-builder /app/dist /app/static

# Set permissions
RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8001/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2", "--proxy-headers"]
```
*Security Features*: Non-root user `appuser`, zero secret keys in image, multi-stage build discards Node/npm toolchain.

### Migrations as a Separate Release Step
- **Critical Rule**: Never execute `alembic upgrade head` inside container startup / entrypoint. When multiple workers or instances boot simultaneously, concurrent DDL causes table locks or schema deadlocks.
- **Execution Pattern**:
  - **PaaS (Option A)**: Configure as a dedicated Pre-Deploy / Release Command (e.g. Render `preDeployCommand: alembic upgrade head`). The release command runs in an isolated single-use container before traffic shifts to the new version.
  - **VPS (Option B)**: Execute migrations explicitly in the deployment script prior to restarting containers:
    ```bash
    docker compose run --rm backend alembic upgrade head
    docker compose up -d --no-deps backend
    ```

### Health & Readiness Checks
- Path: `GET /api/health`
- Function: Executes `SELECT 1` through the SQLAlchemy connection pool.
- Health evaluation:
  - If DB responds: returns HTTP 200 `{"status": "ok", "database": "connected"}`.
  - If DB connection fails or pool times out: returns HTTP 503 `{"detail": "Database connection failed: ..."}`.
  - Reverse proxy / container orchestrator removes unhealthy instances from routing immediately.

### Rollback Strategy
1. **Application Code Rollback**: Redeploy previous container tag or git commit SHA. Since the container contains both backend and frontend, UI and API roll back in sync.
2. **Database Schema Rollback**:
   - Backward-Compatible Migrations: All migrations must follow the expand-and-contract pattern (new columns nullable or default-valued; column drops deferred).
   - Rollback Command: `alembic downgrade <previous_revision>`.

### Backup Frequency & Restore Drill Procedure
- **Backup Schedule**: Automated daily snapshot via `pg_dump -Fc` (compressed custom format) or managed cloud provider automated backups.
- **Retention**: 30 daily snapshots, 12 monthly snapshots.
- **Quarterly Disaster Recovery Drill**:
  1. Provision an isolated local or cloud PostgreSQL instance.
  2. Download the latest automated snapshot.
  3. Execute restore: `pg_restore -v -d test_restore_db snapshot.dump`.
  4. Run automated integrity check verifying count of `users`, `links`, and `click_events`.
  5. Validate RTO (Recovery Time Objective < 1 hour) and RPO (Recovery Point Objective < 24 hours).

### Log Redaction & Privacy Policy
The logging configuration must guarantee zero sensitive data exposure:
- **Never Log Cookies**: `session_token` must be redacted from all access logs.
- **Never Log Secrets**: `SESSION_SECRET`, `GOOGLE_CLIENT_SECRET`, and `GITHUB_CLIENT_SECRET` must never appear in logs.
- **Never Log OAuth Codes/Tokens**: `code`, `access_token`, and `refresh_token` parameters in query strings or payloads must be masked.
- **Never Log Full Destination URLs**: User destination URLs may contain authentication tokens or sensitive query params. Log only `link_id`, `short_code`, domain/hostname, and HTTP response status.

---

## 7. Two Deployment Options (Single-Origin Only)

### Option A: PaaS Stack (Container Web Service + Managed PostgreSQL)
- **Topology**:
  - Web: 1 Docker web service on Render, Railway, or Fly.io running the unified container.
  - Database: Managed PostgreSQL 16 (Render Managed Postgres, Supabase Pro, or Neon).
  - Storage & Backups: Managed automated daily backups.

```
[ Client ] ──HTTPS──> [ PaaS Edge / Ingress ] ──HTTP──> [ Unified Container (FastAPI + SPA) ] ──SQL──> [ Managed Postgres 16 ]
```

- **Pros**:
  - Zero Linux server maintenance (no OS patching, no firewall management).
  - Automated SSL certificate management.
  - Native release commands for zero-downtime database migrations.
  - Automated point-in-time recovery and snapshot management.
- **Cons**:
  - Higher monthly cost for unpaused database instances.
  - Less control over PostgreSQL configuration and kernel parameters.
- **Ops Work Taken On**:
  - Setting environment variables in provider dashboard.
  - Configuring domain CNAME records.
  - Monitoring build logs and monthly usage invoices.
- **Cold-Start Behavior**:
  - **0 seconds cold start (zero downtime)** on standard paid tiers (e.g. Render Starter). Services run 24/7. (Free tiers sleep after 15 minutes of inactivity with 30–50s wake times; not recommended for production).
- **Cost Estimates**:
  - Web Service (0.5–1 CPU, 512MB–1GB RAM): **\$7 to \$15 / month (verify)**
  - Managed PostgreSQL 16 (Starter, automated backups): **\$7 to \$25 / month (verify)**
  - **Estimated Total**: **\$14 to \$40 / month (verify)**

---

### Option B: Unified Single-Host VPS (Caddy + Docker Compose)
- **Topology**:
  - Host: 1 Linux VPS (Hetzner Cloud CX22 or DigitalOcean Basic Droplet).
  - Reverse Proxy: Caddy installed natively or in Docker (handles Let's Encrypt TLS, serves static files, proxies `/api/*` and redirects to backend).
  - Containers: Docker Compose running FastAPI backend and PostgreSQL 16.
  - Backups: Nightly cron script running `pg_dump -Fc` with encrypted upload to Backblaze B2 / AWS S3.

```
[ Client ] ──HTTPS──> [ Caddy Reverse Proxy ]
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
          [ Static File Cache ]   [ Docker: Backend (Port 8001) ]
                                                │
                                                ▼
                                  [ Docker: Postgres 16 (Port 5432) ]
```

- **Pros**:
  - Extremely cost-effective for high CPU and RAM capacity.
  - Sub-millisecond database query transit latency (database on same local host).
  - Full control over PostgreSQL tuning, connection parameters, and extensions.
- **Cons**:
  - Full operational responsibility for host security, OS updates, firewall (`ufw`), and backup verification.
  - Host failure takes down both application and database until restored.
- **Ops Work Taken On**:
  - Linux server provisioning, SSH key management, fail2ban setup.
  - Configuring and maintaining `Caddyfile`.
  - Authoring and monitoring cron backup scripts and offsite S3 uploads.
  - Disk space monitoring and log rotation.
- **Cold-Start Behavior**:
  - **0 seconds cold start**. VPS is continuously running.
- **Cost Estimates**:
  - Hetzner Cloud CX22 (2 vCPU, 4GB RAM, 40GB NVMe): **€3.79/month (~$4.15/month) (verify)**
  - DigitalOcean Droplet (1 vCPU, 2GB RAM, 50GB SSD): **\$12/month (verify)**
  - Offsite Backup Storage (Backblaze B2 / AWS S3, < 10GB): **<\$0.10/month (verify)**
  - **Estimated Total**: **~\$4.25 to \$12.10 / month (verify)**

---

## 8. Production OAuth Setup Guide

### Exact Production Redirect URIs
In both provider dashboards, configure the exact redirect URIs for your production domain:
- **Google OAuth**: `https://<your-domain>/api/auth/callback/google`
- **GitHub OAuth**: `https://<your-domain>/api/auth/callback/github`

### Separate Production GitHub OAuth App
- **Requirement**: A **separate, dedicated GitHub OAuth App** must be created for production.
- **Reason**: GitHub OAuth applications only support a single Authorization Callback URL. Local development uses `http://localhost:8001/api/auth/callback/github`. Development and production cannot share a client ID.
- **Configuration Steps**:
  1. In GitHub, navigate to **Settings** $\rightarrow$ **Developer settings** $\rightarrow$ **OAuth Apps** $\rightarrow$ **New OAuth App**.
  2. Application name: `LinkSphere` (or `LinkSphere Production`).
  3. Homepage URL: `https://<your-domain>`
  4. Authorization callback URL: `https://<your-domain>/api/auth/callback/github`
  5. Copy `Client ID` and generate a new `Client Secret`.

### Google Cloud Console Consent Screen & Publishing Status
1. **OAuth Consent Screen Configuration**:
   - In Google Cloud Console, navigate to **APIs & Services** $\rightarrow$ **OAuth consent screen**.
   - User Type: **External**.
   - App name: `LinkSphere`.
   - User support email: Operator email.
   - Authorized domain: `<your-domain>`.
   - Scopes: `.../auth/userinfo.email`, `.../auth/userinfo.profile`, `openid`.
2. **Publishing Status Requirement**:
   - While in **Testing** status: Only Google accounts explicitly added to the **Test users** list can authenticate. Any other user attempting login will receive an `access_denied (403)` error.
   - For public user access: Click **"Publish App"** to transition to **In Production**.
   - *Verification Note*: Because LinkSphere only requests standard identity scopes (`openid`, `email`, `profile`), Google Cloud does not require a formal security audit or verification video.
3. **Web Credentials Setup**:
   - Navigate to **Credentials** $\rightarrow$ **Create Credentials** $\rightarrow$ **OAuth client ID**.
   - Application type: **Web application**.
   - Name: `LinkSphere Production Web Client`.
   - Authorized JavaScript origins: `https://<your-domain>`
   - Authorized redirect URIs: `https://<your-domain>/api/auth/callback/google`

### Manual Steps Required by Operator
The operator must execute the following actions by hand:
1. Purchase/configure domain name DNS (point A / CNAME records to server or PaaS edge).
2. Create Google Cloud Project, configure consent screen, set publishing status to "In Production", and generate OAuth Client ID & Secret.
3. Create Production GitHub OAuth App and generate Client ID & Secret.
4. Generate 32-byte session secret: `openssl rand -hex 32`.
5. Enter all environment variables securely into the production hosting dashboard.

---

## 9. Open Decisions for Operator

Before proceeding to any deployment code or scripts, please provide guidance on the following:

1. **Domain Name**: What is your production domain or subdomain (e.g. `linksphere.io` or `app.yourdomain.com`)?
2. **Hosting Topology**: Do you choose **Option A (PaaS + Managed Postgres)** for zero operational maintenance, or **Option B (Single VPS with Caddy)** for lowest cost and maximum control?
3. **Monthly Budget Ceiling**: What is your maximum preferred monthly infrastructure budget?
4. **Rate Limiting Implementation**: Do you approve implementing application-level rate limiting using a hand-written in-process sliding-window counter (zero external dependencies), or do you want to approve adding the `slowapi` library?
