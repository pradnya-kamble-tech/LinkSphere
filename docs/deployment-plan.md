# LinkSphere v2 Production Deployment Plan v5 (Vercel + Serverless Architecture)

> **Important**: This document is an architectural and operational plan only. No deployment code or application changes have been committed. All external platform limits, prices, and features are marked with **(verify)** and cited against official vendor documentation.

---

## 0. Operator Decisions & Target Configuration

The following parameters are established for this deployment target:

* **Target Domain**: None (Custom domain deferred). Utilizing default platform production subdomain: `https://<project>.vercel.app`.
* **Hosting Topology**: **Option V: Vercel + Neon (Approved)**. Fallback: **Option V2 (Hybrid Vercel Frontend + Container API via Vercel Rewrites)**.
* **Monthly Budget Ceiling**: **Free tiers only** (Vercel Hobby + Neon Free Tier, $0/month).
* **Application Rate Limiter**: **Narrowed scope approved**: Database-backed fixed-window counters strictly for `POST /api/links` and OAuth login/callback routes; database-backed daily link cap (100 links/day); in-app rate limiting for analytics, settings, and redirects deferred as documented gaps.

---

## 1. Hosting Options (Single-Origin Serverless Topologies)

### Option V: Vercel Unified (Static Frontend + Python ASGI Serverless Function + Neon)
In Option V, the entire application is hosted on Vercel under a single origin (`https://<project>.vercel.app`), connecting to Neon Serverless Postgres via its built-in connection pooler:

```
                                    [ Client Browser ]
                                            │
                                            ▼ HTTPS
                            ┌───────────────────────────────┐
                            │    https://<project>.vercel.app│
                            └───────────────┬───────────────┘
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
         [ Vercel CDN / Static Edge ]             [ Vercel Serverless Function ]
         (Vite React SPA: /assets/*,               (Python 3.11+ ASGI: /api/*,
          /login, /dashboard, etc.)                 /{short_code} redirects)
                                                                   │
                                                                   ▼ SQL (Port 5432, Pooler)
                                                   ┌───────────────────────────────┐
                                                   │ Neon PostgreSQL 16 (Pooled)   │
                                                   │ Built-in PgBouncer (Tx Mode)  │
                                                   └───────────────────────────────┘
```

- **Pros**:
  - Zero infrastructure management, zero VM patching.
  - Generous free tiers on both Vercel and Neon ($0/month).
  - Automatic HTTPS, global CDN edge for static assets, and built-in Git deployment pipelines.
  - Single origin eliminates CORS preflight overhead and cross-origin cookie restrictions.
- **Cons**:
  - Python cold starts on initial invocations (800ms–2.5s) **(verify)**.
  - Neon compute autosuspends after 5 minutes of inactivity; waking it adds 500ms–2.5s to the first request **(verify)**.
  - 10-second maximum request execution timeout on Vercel Hobby tier **(verify)**.
  - Ephemeral function instances prevent in-memory state sharing (rate limiting requires database backing).
  - Post-response background work is unproven; default to synchronous insert before response.
- **Cost**: **$0/month** on Hobby/Free tiers **(verify)**.

---

### Fallback Option V2: Hybrid Single-Origin (Vercel Frontend + Container API via Rewrites)
If Vercel's Python serverless execution, cold starts, or background execution limits prove untenable during Spike 0, Option V2 retains a single origin by proxying API calls through Vercel's Edge network:

```
                                    [ Client Browser ]
                                            │
                                            ▼ HTTPS
                            ┌───────────────────────────────┐
                            │    https://<project>.vercel.app│
                            └───────────────┬───────────────┘
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
         [ Vercel CDN / Static Edge ]                   [ Vercel Edge Rewrites ]
         (Vite React SPA: /assets/*,                   /api/* and /{short_code}
          /login, /dashboard, etc.)                                │
                                                                   ▼ HTTPS
                                                       ┌───────────────────────────────┐
                                                       │ Standalone Container API      │
                                                       │ (Render / Railway / VPS)      │
                                                       └───────────────┬───────────────┘
                                                                       │
                                                                       ▼ SQL
                                                       ┌───────────────────────────────┐
                                                       │ Managed PostgreSQL 16         │
                                                       └───────────────────────────────┘
```

- **How it preserves Single Origin**: `vercel.json` rewrites `/api/:path*` and `/:short_code` to the backend container URL (`https://api-backend.onrender.com`). To the browser, all cookies and network requests remain bound strictly to `https://<project>.vercel.app`.
- **Pros**: Long-running workers, persistent threadpool, reliable background tasks, zero serverless cold starts.
- **Cons**: Requires managing a second hosting provider; potential double-hop network latency on API calls.

---

## 2. Serverless Feasibility Checklist (Official Documentation Audit)

Audit evaluated against official [Vercel Documentation](https://vercel.com/docs) and [Neon Documentation](https://neon.tech/docs):

| Feature / Requirement | Status | Official Limit / Specification | Source / Documentation Reference |
| :--- | :---: | :--- | :--- |
| **Python & FastAPI Support** | **OK** | Native support via `@vercel/python` builder or `/api/index.py` ASGI handler. Python 3.9–3.12 supported. | Vercel Docs: Serverless Functions (Python Runtime) |
| **Function Bundle Size** | **OK** | **50 MB** compressed, **250 MB** uncompressed. LinkSphere backend dependencies (FastAPI, SQLAlchemy, Authlib, Pydantic) consume ~45 MB uncompressed. | Vercel Docs: Serverless Functions Limitations **(verify)** |
| **Execution Duration Limit** | **OK (verify)**| **10 seconds** default & maximum on Hobby Free tier; up to 300s on Pro. Redirects and API endpoints execute in < 200 ms. | Vercel Docs: Functions Execution Limits **(verify)** |
| **Function Memory Limit** | **OK (verify)**| **1024 MB** default on Hobby tier. More than sufficient for LinkSphere's ~120 MB runtime RSS. | Vercel Docs: Functions Memory Limits **(verify)** |
| **Cold-Start Behavior** | **(verify)** | Python runtime initialization + importing SQLAlchemy/Pydantic models takes **800 ms to 2.5 s** on cold invocations. | Community benchmarks & Vercel Runtime metrics **(verify)** |
| **Neon Compute Autosuspend** | **(verify)** | On Neon Free tier, compute auto-suspends after 5 minutes of inactivity. First incoming request incurs **500 ms to 2.5 s** wake-up time. | Neon Docs: Free Tier & Autosuspend **(verify)** |
| **Post-Response Work (BackgroundTasks)**| **UNPROVEN** | Unproven on Vercel Python runtime; default to synchronous insert before response. Spike 0 directly measures a background-task variant. | AWS Lambda Execution Lifecycle / Vercel Functions Docs |
| **Psycopg3 Binary Wheels** | **OK** | `psycopg[binary]` provides pre-compiled `manylinux` x86_64 wheels that run on Vercel's Amazon Linux runtime without requiring native compilation or `libpq-dev`. | PyPI / Psycopg documentation |
| **Hobby Plan Terms** | **OK** | Free for personal, non-commercial applications. Commercial usage requires Pro. | Vercel Fair Use Policy / Terms of Service |
| **Deployment Protection (OAuth Impact)**| **(verify)**| Preview deployments enable "Vercel Authentication" by default, blocking incoming webhooks and OAuth callbacks. Production deployments (`<project>.vercel.app`) are public by default. | Vercel Docs: Deployment Protection **(verify)** |
| **Platform Rate Limiting** | **(verify)**| Custom WAF rate-limiting rules are restricted to Vercel Pro with Firewall add-on. Hobby tier includes only automated DDoS/Attack Challenge Mode. | Vercel Docs: Security & WAF Rules **(verify)** |
| **Neon Connection Pooler** | **OK** | Built-in PgBouncer in transaction mode accessible via connection string host with `-pooler` suffix on port `5432`. | Neon Docs: Connection Pooling |

---

## 3. Region Pairing (Latency Optimization)

### The Region Co-Location Mandate
Serverless function execution latency is heavily dominated by network transit time between the function compute instance and the database instance. If the function runs in Vercel `iad1` (US East) and the database is provisioned in Neon `eu-central-1` (Frankfurt), every database query adds **70–120 ms** of round-trip network latency. Across 2–3 database queries per request, response latency degrades by 200–350 ms.

**Rule**: Function compute and database must be provisioned in the **exact same cloud region**, closest to the target user audience.

### Platform Region Catalogs

#### Vercel Serverless Function Regions (AWS-Based) `(verify)`:
- `iad1`: Washington, D.C., USA (AWS us-east-1) — **Recommended Default**
- `cle1`: Cleveland, USA (AWS us-east-2)
- `sfo1`: San Francisco, USA (AWS us-west-1)
- `pdx1`: Portland, USA (AWS us-west-2)
- `fra1`: Frankfurt, Germany (AWS eu-central-1)
- `lhr1`: London, UK (AWS eu-west-2)
- `cdg1`: Paris, France (AWS eu-west-3)
- `arn1`: Stockholm, Sweden (AWS eu-north-1)
- `bom1`: Mumbai, India (AWS ap-south-1)
- `sin1`: Singapore (AWS ap-southeast-1)
- `syd1`: Sydney, Australia (AWS ap-southeast-2)
- `hnd1`: Tokyo, Japan (AWS ap-northeast-1)
- `icn1`: Seoul, South Korea (AWS ap-northeast-2)
- `gru1`: São Paulo, Brazil (AWS sa-east-1)

#### Neon Serverless Postgres Regions `(verify)`:
- AWS `us-east-1` (N. Virginia, USA) — **Recommended Default**
- AWS `us-east-2` (Ohio, USA)
- AWS `us-west-2` (Oregon, USA)
- AWS `eu-central-1` (Frankfurt, Germany)
- AWS `eu-west-1` (Ireland)
- AWS `eu-west-2` (London, UK)
- AWS `ap-south-1` (Mumbai, India)
- AWS `ap-southeast-1` (Singapore)
- AWS `ap-southeast-2` (Sydney, Australia)
- AWS `sa-east-1` (São Paulo, Brazil)
- Azure `eastus2` (Virginia, USA)

### Recommended Pairing Pairs:
- **US East (Default)**: Vercel `iad1` + Neon AWS `us-east-1` (N. Virginia). Sub-millisecond direct VPC transit latency.
- **India**: Vercel `bom1` + Neon AWS `ap-south-1` (Mumbai).
- **Europe**: Vercel `fra1` + Neon AWS `eu-central-1` (Frankfurt).

---

## 4. `vercel.json` Routing Design & Route Synchronization

### Route Precedence & Ordering
In Vercel, `routes` in `vercel.json` are evaluated sequentially. Static assets and SPA pages must match before the serverless function:

```json
{
  "version": 2,
  "builds": [
    {
      "src": "frontend/package.json",
      "use": "@vercel/static-build",
      "config": { "distDir": "dist" }
    },
    {
      "src": "backend/api/index.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/assets/(.*)",
      "headers": { "cache-control": "public, max-age=31536000, immutable" },
      "dest": "/assets/$1"
    },
    {
      "src": "/(favicon\\.ico|robots\\.txt|sitemap\\.xml)",
      "dest": "/$1"
    },
    {
      "src": "/api/(.*)",
      "dest": "backend/api/index.py"
    },
    {
      "src": "/(login|signup|dashboard|analytics|settings|)",
      "dest": "/index.html",
      "headers": { "cache-control": "no-cache, no-store, must-revalidate" }
    },
    {
      "src": "/([a-zA-Z0-9_-]{3,30})",
      "dest": "backend/api/index.py"
    },
    {
      "src": "/(.*)",
      "dest": "/index.html"
    }
  ]
}
```

### Route Drift Synchronization
1. **Frontend Inventory**: From [`frontend/src/App.tsx`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/frontend/src/App.tsx), all active routes (`/`, `/login`, `/signup`, `/dashboard`, `/analytics`, `/settings`) are routed directly to `/index.html` by Vercel edge routers.
2. **`RESERVED_CODES` Integrity**: Any path routed to `index.html` or static assets **must** be listed in `RESERVED_CODES` in [`backend/app/links/schemas.py`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/backend/app/links/schemas.py).
3. **Automated Drift Test**: CI pipeline executes `test_reserved_codes_cover_all_frontend_routes` ensuring any newly added route in `App.tsx` fails the build until registered in `RESERVED_CODES` and `vercel.json`.

### Vercel Production Branch & Requirements Detection
- **Production Branch**: Configured to `v2` in Vercel Project Settings $\rightarrow$ Git $\rightarrow$ Production Branch. (Commits to `v2` automatically trigger production deployments to `<project>.vercel.app`; other branches produce isolated preview deployments).
- **Python Dependencies Location**: According to official Vercel documentation, the `@vercel/python` builder looks for `requirements.txt` in the root of the project or in the directory of the entrypoint file `(verify)`. For LinkSphere, `requirements.txt` is maintained in `backend/requirements.txt` and symlinked or placed adjacent to the entrypoint.

### Preview vs Production URLs & OAuth Constraints
- **Vercel Preview URLs**: Every git branch or pull request generates preview URLs (e.g. `https://linksphere-git-feat-user.vercel.app`).
- **OAuth Mismatch**: Third-party OAuth providers (Google, GitHub) forbid wildcard callback URLs for security reasons. They require exact, literal redirect URIs.
- **Rule**: OAuth authentication is configured **strictly for the canonical production URL**:
  - `https://<project>.vercel.app/api/auth/callback/google`
  - `https://<project>.vercel.app/api/auth/callback/github`
- Preview branch testing must use mock auth or direct database-seeded sessions.

---

## 5. Environment Variables Separation & Startup Guard

### Environment Separation
In the Vercel Project Dashboard (Settings $\rightarrow$ Environment Variables), variables can be scoped to specific target environments:
- **Production**: Bound only to deployments on the production branch (`v2`).
- **Preview**: Bound to branch/pull request preview deployments.
- **Development**: Local CLI usage (`vercel dev`).

**Mandatory Security Rule**: Preview deployments must **NEVER** be granted access to the production database connection string. Preview environments must either use a separate Neon branch/database or mock services.

### Application Startup Guard Design
To eliminate the catastrophic risk of running automated test suites against a production database, a startup guard is implemented in [`backend/app/core/config.py`](file:///C:/Users/Shuddhodhan/LinkSphere_v2/backend/app/core/config.py):

```python
def validate_test_database_safety(self) -> None:
    """Refuse application startup if ENVIRONMENT=test is pointed at a non-test database."""
    if self.ENVIRONMENT.lower() == "test":
        url = self.DATABASE_URL.lower()
        # Parse database host and name
        parsed = urlparse(url)
        host = parsed.hostname or ""
        dbname = parsed.path.lstrip("/")
        
        is_local_host = host in ("localhost", "127.0.0.1", "::1", "linksphere-v2-db", "linksphere_test")
        is_test_dbname = dbname.endswith("_test") or dbname == "linksphere_test"
        
        if not (is_local_host or is_test_dbname):
            raise RuntimeError(
                f"FATAL: ENVIRONMENT=test is configured with unsafe database target '{host}/{dbname}'. "
                f"Automated tests may ONLY run against local test databases whose name ends with '_test'."
            )
```
If a test runner accidentally runs in production with `ENVIRONMENT=test`, the process terminates immediately with code 1 before executing any queries.

---

## 6. Serverless Database Architecture (Neon + Connection Pooling)

### Connection String Configuration
Neon provides two connection strings in its console:
1. **Pooled Connection String** (Used by FastAPI Serverless Function):
   ```
   postgresql+psycopg://user:password@ep-cold-name-pooler.region.aws.neon.tech/dbname?sslmode=require
   ```
2. **Direct Connection String** (Used for Alembic Migrations):
   ```
   postgresql+psycopg://user:password@ep-cold-name.region.aws.neon.tech/dbname?sslmode=require
   ```

### Serverless SQLAlchemy Pool Configuration
In serverless environments, each concurrent invocation or container replica runs an independent Python process. Standard connection pooling (`pool_size=10`) causes rapid connection multiplication under traffic spikes.
- **Recommended Strategy**: Use `NullPool` (or `pool_size=1, max_overflow=0`):
  ```python
  from sqlalchemy.pool import NullPool

  engine = create_engine(
      settings.DATABASE_URL,
      poolclass=NullPool,
      connect_args={"prepare_threshold": None},
  )
  ```
- **Why `prepare_threshold=None` is Mandatory**: Neon's connection pooler operates in **PgBouncer transaction mode**. Transaction pooling routes different queries within or across transactions to different PostgreSQL server connections. Psycopg 3's default prepared statement caching causes `SQLSTATE 26000: prepared statement does not exist` unless server-side statement preparation is disabled via `prepare_threshold=None`.

### Connection Budget Arithmetic
- Neon Free Tier PgBouncer limit: Supports **up to 10,000 pooled client connections** multiplexed onto a smaller backend connection pool **(verify)**.
- Direct connection limit: Capped at **100 concurrent connections** on Neon Free compute **(verify)**.
- With `NullPool` or `pool_size=1`, 50 concurrent Vercel function invocations open exactly 50 connections to Neon PgBouncer, easily within provider quotas.

### Database Migration Execution Strategy
- **Strict Rule**: Migrations (`alembic upgrade head`) must **NEVER** run inside the Vercel Serverless Function during startup. If multiple serverless instances cold-start concurrently, simultaneous DDL causes database migration deadlocks and function timeouts.
- **Execution Workflow**:
  1. Migrations are executed externally from a trusted local workstation or GitHub Actions CI step against Neon's **direct connection string**.
  2. The deployment pipeline requires operator confirmation before applying destructive schema changes.

---

## 7. Click Recording in Serverless (Durability vs Latency)

### Mechanism Evaluation
In serverless execution environments, code execution after sending the HTTP response is unproven on Vercel's Python runtime:
- **Default Strategy: Synchronous Insert Before Response**:
  - The redirect handler executes `INSERT INTO click_events` and increments `click_count` in PostgreSQL, commits the transaction, and then returns `RedirectResponse(302)`.
  - Durability: **100% guaranteed**. Zero dropped clicks.
  - Latency: Adds ~15–35 ms database round-trip to the redirect.
- **Post-Response Background Variant**:
  - Unproven on Vercel Python runtime. When an ASGI response finishes sending, AWS Lambda/Vercel typically freezes the CPU context immediately, causing queued `BackgroundTasks` to freeze mid-execution or drop entirely.
  - **Spike 0 Goal**: Spike 0 explicitly implements and benchmarks a background-task redirect endpoint (`GET /bg/{code}`) alongside the synchronous endpoint (`GET /{code}`) to empirically measure whether background tasks survive on Vercel.

### Staging Verification Test (Click Equality Gate)
Before approving production release, execute the click equality test:
- Automated test script issues $N = 100$ redirects (50 sequential, 50 concurrent) against `https://<project>.vercel.app/{short_code}`.
- Query database:
  ```sql
  SELECT count(*) FROM click_events WHERE link_id = :test_link_id;
  ```
- **Pass Criterion**: Exactly $N = 100$ rows recorded. If count $< 100$, the release is blocked.

---

## 8. Serverless Rate Limiting & Daily Link Cap

### Scope & Architectural Decisions
Because Vercel serverless function containers scale dynamically and do not share in-process memory, rate limiting is scoped strictly to high-risk abuse vectors using database backing:

1. **Scoped Database-Backed Rate Limiting**:
   - Implemented strictly for:
     - `POST /api/links` (Link creation spam)
     - `GET /api/auth/{provider}/login` (OAuth state generation spam)
     - `GET /api/auth/callback/{provider}` (Callback replay spam)
   - Backed by a lightweight PostgreSQL table `rate_limit_buckets (key TEXT PRIMARY KEY, window_start TIMESTAMPTZ, count INT)`.
   - Updated via atomic upsert:
     ```sql
     INSERT INTO rate_limit_buckets (key, window_start, count)
     VALUES (:key, :window_start, 1)
     ON CONFLICT (key) DO UPDATE
     SET count = CASE 
       WHEN rate_limit_buckets.window_start = EXCLUDED.window_start THEN rate_limit_buckets.count + 1
       ELSE 1
     END,
     window_start = EXCLUDED.window_start
     RETURNING count;
     ```
   - **Opportunistic Purge**: During rate-limit checks, counter rows older than 1 day are deleted opportunistically (`DELETE FROM rate_limit_buckets WHERE window_start < NOW() - INTERVAL '1 day'`) to prevent table growth.
2. **Known In-App Rate Limiting Gaps**:
   - `GET /api/analytics/*`: No in-app rate limiter.
   - `GET /api/me/*`, `DELETE /api/me/sessions/*`: No in-app rate limiter.
   - `GET /{short_code}` (Redirects): No in-app rate limiter.
   - *Platform Defense*: Protection against volumetric scraping on these endpoints relies on Vercel platform-level DDoS mitigation and Attack Challenge Mode. Custom per-path WAF rate limits require Vercel Pro with the Firewall add-on **(verify)**.

### Database-Backed Daily Link Cap (100 links/day)
- Enforced on `POST /api/links`.
- Daily link quota is calculated using UTC calendar midnight computed in Python:
  ```python
  from datetime import datetime, timezone

  now_utc = datetime.now(timezone.utc)
  today_midnight_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
  ```
- Enforced directly via SQL query including **soft-deleted links** to prevent quota evasion:
  ```sql
  SELECT count(*) FROM links 
  WHERE user_id = :user_id 
    AND created_at >= :today_midnight_utc;
  ```
  *(Note: Does NOT filter by `deleted_at IS NULL`; every link created today counts toward the 100 quota).*
- Rejection: Returns `HTTP 403 Forbidden` with `{"detail": "Daily link creation limit reached (100 links/day)."}`.

### Client IP Resolution on Vercel & Spoofing Analysis
- **Platform Header**: Vercel edge routers populate `x-forwarded-for` and `x-real-ip`.
- **Spoofing Vulnerability Analysis `(verify)`**:
  - When an incoming HTTP request hits Vercel's edge, Vercel appends the connecting client IP to `X-Forwarded-For`.
  - If application code naively takes the first IP in `X-Forwarded-For` without validating against proxy hops, a client can inject `X-Forwarded-For: 1.2.3.4` to spoof their IP address.
  - **Impact of Spoofing**: An attacker could spoof an arbitrary IP to bypass IP rate limits or consume the rate limit quota of innocent users (denial of service).
  - **Resolution**: Use `request.headers.get("x-real-ip")` or inspect the rightmost IP in `x-forwarded-for` provided by Vercel's edge.

---

## 9. Security Headers & Phased Rollout Strategy

### Phase 1: Content Security Policy (Report-Only)
```http
Content-Security-Policy-Report-Only: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none';
```
- **Manual Verification Checklist (5 Pages)**:
  1. [ ] Landing page (`/`) — verifies layout and styling.
  2. [ ] Login page (`/login`) — verifies OAuth action buttons.
  3. [ ] Dashboard (`/dashboard`) — verifies link creation and tables.
  4. [ ] Analytics page (`/analytics`) — verifies dynamic SVG timeseries chart rendering.
  5. [ ] Settings page (`/settings`) — verifies session tables and modals.

### Phase 2: Strict-Transport-Security (HSTS) with Rollback
- Initial setting: `Strict-Transport-Security: max-age=300` (5 minutes, no subdomains, no preload).
- Rollback procedure: If certificate issues occur, remove header or set `max-age=0`.

---

## 10. Production OAuth Setup Guide (`<project>.vercel.app`)

### Exact Callback URIs
- **Google OAuth**: `https://<project>.vercel.app/api/auth/callback/google`
- **GitHub OAuth**: `https://<project>.vercel.app/api/auth/callback/github`

### Dedicated GitHub OAuth App
- Create a dedicated GitHub OAuth app named `LinkSphere Vercel Production`.
- Homepage URL: `https://<project>.vercel.app`
- Authorization callback URL: `https://<project>.vercel.app/api/auth/callback/github`

### Google Cloud Console Consent Screen (Testing Status)
- Keep Google OAuth Consent Screen in **TESTING** status during initial rollout.
- Explicitly add the operator's Google email to the **Test users** list in Google Cloud Console.
- **Pre-Publishing Verification Checklist (Before Ever Publishing)**:
  - [ ] Live public application homepage (`https://<project>.vercel.app`) **(verify)**.
  - [ ] Live public Privacy Policy link (`https://<project>.vercel.app/privacy` or hosted document) **(verify)**.
  - [ ] Terms of Service link **(verify)**.
  - [ ] Domain ownership verified in Google Search Console if a custom apex domain is attached later.

---

## 11. Staged Rollout Sub-Levels (Spike 0 through Level 4.5d)

To de-risk the Vercel serverless platform constraints before writing full production code, work is structured into five progressive stages:

```
[ Spike 0: Feasibility Proof on spike/vercel ]
                     │
                     ▼
[ Level 4.5a: Single Origin & Headers on main ] ──> [ Level 4.5b: Scoped Rate Limiting ]
                                                                      │
                                                                      ▼
[ Level 4.5d: Staging Deploy & Scaling ] <────────── [ Level 4.5c: vercel.json & CI Gate ]
```

### Spike 0: Minimum Deployment Feasibility Spike (On `spike/vercel` branch)
A minimal self-contained application under `spike/` proving the three primary technical risks on Vercel + Neon:
1. **Risk 1 (Function & Pooler Connectivity)**: Verify Python serverless function boots on Vercel, executes queries through Neon PgBouncer transaction pooler with `prepare_threshold=None`, and returns `GET /api/spike/db` with timing and `VERCEL_REGION`.
2. **Risk 2 (Click Durability & Background Task Survivability)**: Compare synchronous insert (`GET /{code}`) vs `BackgroundTask` insert (`GET /bg/{code}`). Empirically determine whether background tasks survive on Vercel Python runtime.
3. **Risk 3 (Single-Origin Rewrites & Cookies)**: Verify that hitting `/login` sets and reads an `HttpOnly, Secure, SameSite=Lax` cookie across the single origin `https://<project>.vercel.app`.
- **Spike 0 Acceptance Criteria**:
  - `GET /api/spike/db` returns HTTP 200 with timing and region.
  - 100 sync redirects produce exactly 100 rows; background redirects measured after 10s wait.
  - Same-origin cookie read/write works without cross-origin blocking.

---

### Level 4.5a: Single-Origin Routing, Reserved Words & Security Headers (On `main`)
- **Deliverables**:
  1. Frontend build configuration emitting static assets to `dist/`.
  2. Synchronize `RESERVED_CODES` to include `analytics` and `settings`.
  3. Implement CSP-Report-Only middleware and initial short HSTS (`max-age=300`).
  4. Response caching headers (`immutable` for hashed assets, `no-cache` for HTML/redirects).
- **Tests & Acceptance**:
  - `test_reserved_codes_cover_all_frontend_routes` passes in CI.
  - Browser console on all 5 pages verifies zero CSP violation warnings.

---

### Level 4.5b: Serverless Rate Limiting & Daily Link Cap (On `main`)
- **Deliverables**:
  1. Database-backed atomic fixed-window rate limiter for `POST /api/links` and auth login/callback routes.
  2. Database-backed daily link cap (100 links/day per user computed using Python UTC midnight, counting soft-deleted links).
  3. Startup guard enforcing local test database when `ENVIRONMENT=test`.
- **Tests & Acceptance**:
  - Unit tests verifying concurrency, window expiration, and 429 Retry-After on scoped routes.
  - Integration test verifying 101st link created on the same UTC day returns HTTP 403.
  - Startup guard unit test verifying startup is aborted if `ENVIRONMENT=test` targets an unsafe database.

---

### Level 4.5c: `vercel.json` Configuration & GitHub Actions CI Gate (On `main`)
- **Deliverables**:
  1. Production `vercel.json` routing configuration mapping static assets, SPA routes, API functions, and short-code catch-all.
  2. GitHub Actions workflow (`.github/workflows/ci.yml`) running backend `pytest` against PostgreSQL service container `linksphere_test` and verifying `npm run build`.
- **Tests & Acceptance**:
  - CI pipeline passes with 126+ tests and zero build errors prior to any deployment trigger.

---

### Level 4.5d: Staging Deployment, Scaling Curve & Click Equality
- **Deliverables**:
  1. Deploy full application to Vercel production branch `v2` mapping to `https://<project>.vercel.app`.
  2. Run scaling curve verification (1, 5, 20, and 50 concurrent requests) to measure Vercel serverless cold/warm response latencies.
  3. Execute 100-request click equality validation test.
- **Tests & Acceptance**:
  - Click equality: 100 redirects produce exactly 100 rows in Neon `click_events`.
  - Full manual walkthrough: Login via Google/GitHub, create link, 5 redirects, view analytics, logout-all.

---

## 12. Open Questions for Operator

Before proceeding to deploy Spike 0, please confirm:

1. **Vercel Account Status**: Is your Vercel account created and connected to your GitHub account?
2. **Neon Account Status**: Is your Neon account created, and what AWS region did you select for the project (recommended: AWS `us-east-1` N. Virginia)?
