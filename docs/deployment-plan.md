# LinkSphere v2 Production Deployment Plan v3 (Single-Origin Architecture)

> **Important**: This document is an architectural and operational plan only. No deployment code or application changes have been committed. All costs, quotas, and limits listed below are marked with **(verify)** and must be verified against current vendor pricing.

---

## 0. Operator Decisions & Target Configuration

The following operational parameters govern this deployment plan:

* **Target Domain**: `<Operator to specify: owned domain name, or "will buy">` (e.g. `linksphere.io` or `app.example.com`)
* **Infrastructure Topology**: `<Operator to specify: Option A (PaaS + Managed Postgres) or Option B (Single VPS with Caddy)>`
* **Monthly Budget Ceiling**: `<Operator to specify: e.g. $15/month or $50/month (USD/EUR)>`
* **Application Rate Limiter**: **Hand-written in-process sliding window counter (Approved, zero external dependencies)**

---

## 1. Single-Origin Architecture & Route Topology

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
- **No CORS Preflights**: Because browser requests originate from `https://<your-domain>` and target `https://<your-domain>/api/*`, requests are same-origin. Preflight `OPTIONS` requests and cross-origin header checks are avoided. Session cookies (`SameSite=Lax`, `Secure`, `HttpOnly`) function reliably across all modern browsers.
- **No `VITE_API_URL`**: As verified in [`frontend/src/api.ts`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/frontend/src/api.ts), the frontend issues all API requests to relative paths (e.g. `fetch('/api/me')`). No build-time API domain injection is required.
- **Unified Short Link Domain**: `SHORT_LINK_BASE_URL` matches the apex/service origin: `https://<your-domain>`. Generated links take the form `https://<your-domain>/{short_code}`.

### OAuth Redirect URI Behind Reverse Proxy (Code Audit)
- **Current Implementation**: An audit of [`backend/app/auth/router.py`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/backend/app/auth/router.py#L66) confirms that `redirect_uri` is constructed from configured base settings, **not** dynamically from `request.base_url`:
  ```python
  redirect_uri = f"{settings.FRONTEND_ORIGIN}/api/auth/callback/{provider}"
  ```
- **TLS-Termination Guarantee**: Because `redirect_uri` is derived from `settings.FRONTEND_ORIGIN` (`https://<your-domain>`), it remains strictly `https://` even when a reverse proxy (PaaS edge or Caddy) terminates TLS and forwards plain `http://localhost:8001` internally. This prevents OAuth protocol mismatch errors.
- **Required Verification Test in Plan**: Add a unit test in `backend/tests/test_auth.py` verifying that `/api/auth/{provider}/login` sets `redirect_uri` to `https://<configured-domain>/...` regardless of internal incoming `http://` scheme or internal proxy port headers.

### Required Code & Configuration Changes (Numbered List)
The following code adjustments are required to implement single-origin serving (listed for planning; no code has been modified):

1. **Multi-Stage Container Bundling**: Build the frontend (`npm run build` producing `frontend/dist`) during Docker build and copy `dist/` into `backend/static/`.
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
6. **Security Headers Middleware (Phased Rollout)**:
   - Detailed in Section 5 below.
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

### Corrected Removals & Health Path
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

## 4. Application-Level Rate Limiting & Daily Link Cap

### Design Specifications (Approved: Hand-Written, Zero New Dependencies)
The rate limiter is implemented directly in standard library Python (`time`, `collections.deque`, `threading.Lock`) within application middleware/dependencies:

1. **Thread-Safe State**: Protected by `threading.Lock()` to prevent race conditions during concurrent access across AnyIO worker threads.
2. **Monotonic Clock**: Uses `time.monotonic()` (never `time.time()`), rendering calculations immune to NTP wall-clock adjustments or leap seconds.
3. **Bounded Memory & Eviction**:
   - In-memory keys are tracked alongside an expiration timestamp.
   - A cleanup routine evicts keys that have been idle longer than the rate window (e.g. 5 minutes).
   - Maximum key threshold: If keys exceed 20,000 entries (e.g. under an IP-spoofing sweep), an LRU eviction purge drops the oldest inactive keys, ensuring memory usage cannot exceed ~10 MB per worker.
4. **429 Response & Headers**: Returns `HTTP 429 Too Many Requests` containing standard headers:
   - `Retry-After: <seconds_remaining>`
   - `Content-Type: application/json` with `{"detail": "Rate limit exceeded. Try again in X seconds."}`
5. **Multi-Worker Behavior Documented**:
   - In a multi-worker setup (e.g. 2–4 uvicorn workers per container) without Redis, each worker maintains its own isolated memory state.
   - Under round-robin load distribution across $N$ workers, the effective cluster rate limit is approximately $N \times \text{limit}$. This is documented and accepted as an appropriate trade-off to avoid Redis infrastructure costs and failure modes.

### Rate Limit Tiers

| Tier / Endpoint | Key / Identity | Rate Limit | Action on Exceeded |
| :--- | :--- | :--- | :--- |
| **Analytics Endpoints** (`/api/analytics/*`) | `user_id` (from session) | **60 req / min** | HTTP 429 Too Many Requests |
| **Settings & Session Endpoints** (`/api/me/*`, `/logout-all`) | `user_id` (from session) | **30 req / min** | HTTP 429 Too Many Requests |
| **General Link Endpoints** (`GET/PATCH/DELETE /api/links/*`) | `user_id` (from session) | **60 req / min** | HTTP 429 Too Many Requests |
| **Link Creation** (`POST /api/links`) | `user_id` (from session) | **20 req / min** | HTTP 429 Too Many Requests |
| **OAuth Initiation** (`GET /api/auth/{provider}/login`) | Client IP (trusted proxy) | **10 req / min** | HTTP 429 Too Many Requests |
| **OAuth Callback** (`GET /api/auth/callback/{provider}`) | Client IP (trusted proxy) | **10 req / min** | HTTP 429 Too Many Requests |
| **Short Link Redirect** (`/{short_code}`) | Client IP (trusted proxy) | **120 req / min** | HTTP 429 Custom HTML |

### Daily Link Creation Cap (Database-Backed)
In addition to the per-minute rate limiter, `POST /api/links` enforces a **100 links/day per user cap** queried directly from PostgreSQL:
```sql
SELECT count(*) FROM links 
WHERE user_id = :user_id 
  AND created_at >= (NOW() AT TIME ZONE 'UTC')::date;
```
- Computed using UTC calendar day boundaries from PostgreSQL `click_events`/`links` timestamp columns.
- Not stored in memory; survives process restarts and applies globally across all workers.
- Rejection Response: `HTTP 403 Forbidden` with `{"detail": "Daily link creation limit reached (100 links/day)."}`.

### Trusted Proxy Header & Client IP Verification
- **Threat**: Attackers sending forged `X-Forwarded-For: <fake-ip>` headers to evade IP rate limits or poison audit logs.
- **Strict Network Whitelist**:
  - `uvicorn --proxy-headers --forwarded-allow-ips="<TRUSTED_IPS>"`
  - **NEVER set `--forwarded-allow-ips` to `*`**.
  - For VPS (Option B): `--forwarded-allow-ips="127.0.0.1,::1"` (trusting only the local Caddy reverse proxy).
  - For PaaS (Option A): Set to the provider's documented private load-balancer CIDR.
- **Client IP Resolution Mechanism**:
  - Uvicorn parses `X-Forwarded-For` from right to left, stripping hops that match `--forwarded-allow-ips`.
  - The first un-trusted IP encountered is assigned to `request.client.host`.
  - If a direct connection arrives with a forged `X-Forwarded-For` from an untrusted source, Uvicorn ignores the header and uses the direct TCP socket address.

### Unit Tests Required for Rate Limiter
The test suite in `backend/tests/test_rate_limiter.py` must verify:
1. **Concurrency**: Multi-threaded hammer test verifying `threading.Lock` prevents counter race conditions.
2. **Eviction**: Verification that idle keys are pruned and memory remains strictly bounded under a flood of unique keys.
3. **Window Rollover**: Verification that requests rejected when the window fills are permitted immediately once the time window elapses.
4. **Retry-After Header**: Verification that HTTP 429 includes an accurate integer `Retry-After` header.

---

## 5. Security Headers & Phased Rollout Strategy

To prevent breaking client-side React rendering or locking domains out with bad HTTPS headers, security headers are introduced in phases:

### Phase 1: Content Security Policy (Report-Only Mode)
Initially deployed with header:
```http
Content-Security-Policy-Report-Only: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none';
```
- Does not block resources; logs violations to the browser developer console.
- **Manual Verification Checklist (All 5 Pages)**:
  1. [ ] Landing page (`/`) — verifies root HTML, fonts, and inline layout styles.
  2. [ ] Login page (`/login`) — verifies OAuth redirect buttons and icons.
  3. [ ] Dashboard (`/dashboard`) — verifies link creation forms, tables, and pagination.
  4. [ ] Analytics page (`/analytics`) — verifies dynamic SVG timeseries bar chart rendering and CSS transforms.
  5. [ ] Settings page (`/settings`) — verifies session tables and modal dialogs.
- Once all 5 pages confirm zero CSP violations in browser console, switch to enforcing `Content-Security-Policy`.

### Phase 2: Strict-Transport-Security (HSTS) with Safe Rollback
- **Initial Deployment**: Start with short duration, no subdomains, and no preload:
  ```http
  Strict-Transport-Security: max-age=300
  ```
  *(5 minutes; allows quick rollback if SSL certificate or DNS is misconfigured).*
- **Production Ramp-Up**: After 48 hours of clean operations, increase to 24 hours (`max-age=86400`), then 1 year (`max-age=31536000`).
- **Rollback Procedure**: If SSL issues arise, immediately set `max-age=0` in reverse proxy or middleware to instruct browsers to clear their cached HSTS requirements.

### Additional Standard Headers (Immediate Enforcement)
```http
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

---

## 6. Database Capacity, Sizing & Performance Hypotheses

### Connection Budget Arithmetic
$$\text{Total Connections} = N_{\text{instances}} \times N_{\text{workers}} \times (\text{DB\_POOL\_SIZE} + \text{DB\_MAX\_OVERFLOW}) + \text{Buffer}_{\text{admin}}$$

- **PaaS Stack (Option A)**:
  - 1 instance $\times$ 2 workers $\times$ (10 pool + 5 max_overflow) = **30 peak connections**.
  - Sits within entry-tier managed Postgres limits: **50 to 100 connections (verify)**.
  - Leaves 20–70 connections headroom for Alembic migrations, admin `psql`, and automated backup jobs.
- **VPS Stack (Option B)**:
  - 1 instance $\times$ 2 workers $\times$ (10 pool + 10 max_overflow) = **40 peak connections**.
  - Default PostgreSQL `max_connections` is **100 (verify)**; leaves 60 connections headroom.

### Threadpool Sizing vs Connection Pool (Hypothesis to Test)
- **Current Code Setting**: [`backend/app/main.py`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/backend/app/main.py#L28) configures `anyio.to_thread.current_default_thread_limiter().total_tokens = 200`.
- **Contrast**: The database pool allows 10–20 connections per worker.
- **Operational Hypothesis**:
  > *Hypothesis to test on deployment host*: When concurrency exceeds 20 requests per worker, worker threads quickly exhaust available database connections, causing incoming requests to queue in SQLAlchemy's connection checkout queue (`DB_POOL_TIMEOUT=30s`). This queueing delay is hypothesized to be the driver of the tail latencies (p95 > 1s) observed under 50-user load tests.
- **Empirical Validation Plan**: To be formally tested on the staging/production host by running a scaling curve at **1, 5, 20, and 50 concurrent users** to observe whether throughput saturates or serializes.

### Psycopg 3 Prepared Statements & Transaction Poolers
- **Risk**: Psycopg 3 caches server-side prepared statements by default. If a cloud PostgreSQL provider runs PgBouncer in **transaction pooling mode**, statements from the same client session execute on different PostgreSQL backend connections, triggering `SQLSTATE 26000: prepared statement does not exist`.
- **Configuration Fix**:
  - Set `prepare_threshold=None` in SQLAlchemy connect arguments:
    `create_engine(..., connect_args={"prepare_threshold": None})`.
  - Or connect via direct session port (port 5432) rather than transaction pooler port.

### Worker Count & Memory Sizing
- **Recommended Default**: **2 Uvicorn workers** on a 1 vCPU / 1–2 GB RAM host.
- **Memory Footprint Breakdown**:
  - Python runtime + FastAPI + dependencies: ~120 MB RSS per worker.
  - Memory under peak aggregation query load: ~180–220 MB RSS per worker.
  - 2 Workers Total: ~400–440 MB.
  - Host OS + Caddy reverse proxy: ~150–200 MB.
  - Total Memory Profile: ~650 MB. Fits safely within 1 GB or 2 GB RAM with zero OOM risk.

---

## 7. Operations, Resilience & Maintenance Policy

### GitHub Actions CI/CD Outline (`.github/workflows/ci.yml`)
- **Triggers**: `on: [push, pull_request]` against branch `main`.
- **Pipeline Structure**:
  1. `backend-test`:
     - Spawns service container `postgres:16` named `linksphere_test` (port 5432).
     - Installs `backend/requirements.txt`.
     - Executes `alembic upgrade head` on test database.
     - Runs `pytest -v` with dummy test secrets (`ENVIRONMENT=test`).
     - Must report 126+ passed, 0 failures.
  2. `frontend-build`:
     - Installs Node.js 20.
     - Runs `npm ci` and `npm run build` in `frontend/`.
  3. `deploy-gate`:
     - Evaluates results; deployment is completely blocked if either job fails.

### Multi-Stage Non-Root Dockerfile Outline
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
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/
COPY --from=frontend-builder /app/dist /app/static
RUN chown -R appuser:appgroup /app

USER appuser
EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8001/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2", "--proxy-headers"]
```

### Migrations as a Separate Release Step
- **Rule**: Never run `alembic upgrade head` in container boot scripts. Multiple container replicas booting concurrently cause DDL race conditions and database migration locks.
- **PaaS**: Run as dedicated Pre-Deploy / Release Phase command (e.g. Render `preDeployCommand: alembic upgrade head`).
- **VPS**: Execute `docker compose run --rm backend alembic upgrade head` prior to restarting services.

### Health & Readiness Checks
- Endpoint: `GET /api/health`
- Function: Executes `SELECT 1` through connection pool.
- Returns HTTP 200 `{"status": "ok", "database": "connected"}` when healthy.
- Returns HTTP 503 on database disconnect or pool checkout timeout.

### Rollback Strategy
1. **Application Code Rollback**: Re-deploy previous container image tag or commit SHA.
2. **Database Schema Rollback**:
   - Backward-compatible schema migrations (new columns nullable or defaulted).
   - Rollback command: `alembic downgrade <previous_revision>`.

### Backup Frequency & Quarterly Restore Drill
- **Backup Schedule**: Automated daily snapshot via `pg_dump -Fc` (compressed custom format) or managed cloud provider automated backups.
- **Retention**: 30 daily snapshots, 12 monthly snapshots.
- **Quarterly Disaster Recovery Drill**:
  1. Provision an isolated local or cloud PostgreSQL instance.
  2. Download the latest automated snapshot.
  3. Execute restore: `pg_restore -v -d test_restore_db snapshot.dump`.
  4. Run automated integrity check verifying count of `users`, `links`, and `click_events`.
  5. Validate RTO (Recovery Time Objective < 1 hour) and RPO (Recovery Point Objective < 24 hours).

### Cold-Start Behavior by Hosting Option
- **Option A (PaaS - Paid Tier)**: **0 seconds cold start**. Paid instances (e.g. Render Starter) run continuously 24/7 without sleep. (Note: Free PaaS tiers sleep after 15m inactivity and suffer 30–50s cold starts; rejected for production).
- **Option B (VPS)**: **0 seconds cold start**. VPS is continuously running.

### Dependency & Container Image Update Policy
- **Automated Security Scanning**:
  - Run `pip-audit` in CI or monthly automated workflow to scan Python dependencies for known CVEs.
  - Run `npm audit` for frontend dependencies.
- **Base Image Updates**:
  - Base image pinned to stable Debian release (`python:3.11-slim-bookworm`).
  - Container rebuilt monthly to pull latest OS-level security patches.

### Log Redaction & Privacy Policy
- **Never Log Cookies**: `session_token` must be redacted from all access logs.
- **Never Log Secrets**: `SESSION_SECRET`, `GOOGLE_CLIENT_SECRET`, and `GITHUB_CLIENT_SECRET` must never appear in logs.
- **Never Log OAuth Codes/Tokens**: `code`, `access_token`, and `refresh_token` parameters in query strings or payloads must be masked.
- **Never Log Full Destination URLs**: User destination URLs may contain authentication tokens or sensitive query params. Log only `link_id`, `short_code`, domain/hostname, and HTTP response status.

---

## 8. Two Deployment Options (Single-Origin Only)

### Option A: PaaS Stack (Container Web Service + Managed PostgreSQL)
- **Topology**:
  - Web: 1 Docker web service on Render, Railway, or Fly.io running the unified container.
  - Database: Managed PostgreSQL 16 (Render Managed Postgres, Supabase Pro, or Neon).
  - Storage & Backups: Managed automated daily backups.
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
  - **0 seconds cold start** on paid tiers.
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
  - **0 seconds cold start**.
- **Cost Estimates**:
  - Hetzner Cloud CX22 (2 vCPU, 4GB RAM, 40GB NVMe): **€3.79/month (~$4.15/month) (verify)**
  - DigitalOcean Droplet (1 vCPU, 2GB RAM, 50GB SSD): **\$12/month (verify)**
  - Offsite Backup Storage (Backblaze B2 / AWS S3, < 10GB): **<\$0.10/month (verify)**
  - **Estimated Total**: **~\$4.25 to \$12.10 / month (verify)**

---

## 9. Production OAuth Setup Guide

### Exact Production Redirect URIs
In both provider dashboards, configure the exact redirect URIs for your production domain:
- **Google OAuth**: `https://<your-domain>/api/auth/callback/google`
- **GitHub OAuth**: `https://<your-domain>/api/auth/callback/github`

### Separate Production GitHub OAuth App
- **Requirement**: A **separate, dedicated GitHub OAuth App** must be created for production.
- **Reason**: GitHub OAuth applications only support a single Authorization Callback URL. Local development uses `http://localhost:8001/api/auth/callback/github`. Development and production cannot share a client ID.
- **Configuration Steps**:
  1. In GitHub, navigate to **Settings** $\rightarrow$ **Developer settings** $\rightarrow$ **OAuth Apps** $\rightarrow$ **New OAuth App**.
  2. Application name: `LinkSphere Production`.
  3. Homepage URL: `https://<your-domain>`
  4. Authorization callback URL: `https://<your-domain>/api/auth/callback/github`
  5. Copy `Client ID` and generate a new `Client Secret`.

### Google Cloud Consent Screen Requirements & Publishing Status
1. **Pre-Publishing Verification Checklist (Verify)**:
   - Before Google Cloud allows transitioning an OAuth consent screen to **"In Production"**, verify the following required fields in Google Cloud Console:
     - [ ] **Application Homepage URL**: Must be a live URL (`https://<your-domain>`).
     - [ ] **Privacy Policy Link**: Must be a valid public URL (`https://<your-domain>/privacy` or external document) **(verify)**.
     - [ ] **Terms of Service Link**: Optional for basic scopes, but recommended **(verify)**.
     - [ ] **Authorized Domains**: Must list apex domain (`<your-domain>`).
2. **Publishing Status Requirement**:
   - While in **Testing** status: Only Google accounts explicitly added to the **Test users** list can authenticate. Any other user attempting login will receive an `access_denied (403)` error.
   - For public user access: Must click **"Publish App"** to transition to **In Production**.
   - *Verification Scope Note*: Because LinkSphere only requests standard identity scopes (`openid`, `email`, `profile`), Google Cloud does not require a paid security audit or application verification video.
3. **Web Credentials Setup**:
   - Authorized JavaScript origins: `https://<your-domain>`
   - Authorized redirect URIs: `https://<your-domain>/api/auth/callback/google`

### Operator Manual Tasks Checklist
1. Register/point domain DNS (A/CNAME records).
2. Configure Google Cloud OAuth consent screen (with homepage and privacy policy links), publish to production, and copy Client ID/Secret.
3. Create Production GitHub OAuth App and copy Client ID/Secret.
4. Generate 32-byte session secret: `openssl rand -hex 32`.
5. Enter all environment variables into the hosting dashboard.

---

## 10. Phased Implementation Sub-Levels (Level 4.5 Breakdown)

To ensure high quality and zero regressions, the implementation is decomposed into four discrete sub-levels:

### Level 4.5a: Single-Origin Serving, Reserved Routes & Security Headers
- **Deliverables**:
  1. Multi-stage Dockerfile setup for frontend asset building into `backend/static/`.
  2. Static file mounting under `/assets` and explicit root static endpoints.
  3. Route precedence ordering ensuring SPA client routes serve `index.html` and dynamic short codes evaluate last.
  4. Synchronize `RESERVED_CODES` in `app/links/schemas.py` to include `analytics` and `settings`.
  5. Security headers middleware (CSP Report-Only, short HSTS `max-age=300`, nosniff, DENY).
  6. Response caching headers (`immutable` for assets, `no-cache` for HTML/redirects).
- **Automated Tests**:
  - `test_reserved_codes_cover_all_frontend_routes`: Fails if `App.tsx` has routes not in `RESERVED_CODES`.
  - `test_single_origin_static_and_spa_routing`: Tests that `/login`, `/dashboard`, etc. return 200 with HTML, and `/assets/...` returns static assets.
  - `test_security_headers_present`: Verifies CSP-Report-Only, HSTS, and nosniff headers.
- **Acceptance Criteria**: All existing 126 tests pass + new routing tests pass; browser console on all 5 pages reports zero CSP errors.

### Level 4.5b: Application-Level Rate Limiting & Daily Link Cap
- **Deliverables**:
  1. Hand-written thread-safe sliding-window rate limiter with monotonic clock and memory-bounded eviction.
  2. Application middleware/dependencies applying rate limits across analytics (60/min), settings (30/min), links (20/min), auth (10/min), and redirect (120/min).
  3. Database-backed 100 links/day per user cap on `POST /api/links`.
  4. Trusted proxy configuration with strict `forwarded-allow-ips`.
- **Automated Tests**:
  - Unit tests for concurrency, eviction, window rollover, and `Retry-After` header.
  - Integration test for daily link cap exceeding 100 links returning HTTP 403.
  - Proxy header spoofing test asserting injected `X-Forwarded-For` from untrusted sources is ignored.
- **Acceptance Criteria**: Zero new external dependencies added; rate limits reject excess traffic cleanly with HTTP 429/403.

### Level 4.5c: Dockerfile & GitHub Actions CI Gate
- **Deliverables**:
  1. Production multi-stage Dockerfile running as non-root `appuser`.
  2. GitHub Actions CI pipeline `.github/workflows/ci.yml` running backend tests against PostgreSQL service container `linksphere_test` and building the frontend.
  3. Pre-deploy Alembic migration script.
- **Automated Tests**:
  - Successful local `docker build` and container health check verification.
  - Clean CI run on GitHub Actions with 100% test pass rate.
- **Acceptance Criteria**: Docker image contains zero secret credentials; CI blocks deployment on test or build failure.

### Level 4.5d: Staging Deployment, Scaling Curve & Production OAuth Validation
- **Deliverables**:
  1. Provision host environment according to chosen topology (PaaS or VPS).
  2. Execute Alembic migration on production database as a separate release phase step.
  3. Configure production Google and GitHub OAuth credentials and consent screen.
  4. Run scaling curve verification (1, 5, 20, 50 concurrent users) on deployment host to empirically test the threadpool vs pool sizing hypothesis.
- **Automated Tests**:
  - Live production `/api/health` returns HTTP 200 `{"status":"ok","database":"connected"}`.
  - Live walkthrough of Google and GitHub OAuth login, account linking, link creation, 5 redirects, and settings revocation.
  - Scaling curve benchmark report recorded.
- **Acceptance Criteria**: Zero deployment errors; production OAuth operational for arbitrary external accounts; scaling curve documented.
